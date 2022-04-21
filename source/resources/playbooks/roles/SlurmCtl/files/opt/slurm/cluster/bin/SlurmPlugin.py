#!/usr/bin/env python3
"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

Permission is hereby granted, free of charge, to any person obtaining a copy of this
software and associated documentation files (the "Software"), to deal in the Software
without restriction, including without limitation the rights to use, copy, modify,
merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

import argparse
import socket
import boto3
from botocore.exceptions import ClientError
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from functools import wraps
import hostlist
from isodate import parse_duration
from jinja2 import Template as Template
import json
import logging
from logging import error, info, warning, handlers
import os
from os.path import dirname, realpath
from pkg_resources import resource_filename
import pprint
import random
import re
# Subprocess not being used to execute user supplied data
import subprocess # nosec
from sys import exit
from tempfile import NamedTemporaryFile
from textwrap import dedent
import threading
import time
import traceback
import yaml

logger = logging.getLogger(__file__)
logger_formatter = logging.Formatter('%(levelname)s: %(message)s')
logger_streamHandler = logging.StreamHandler()
logger_streamHandler.setFormatter(logger_formatter)
logger.addHandler(logger_streamHandler)
logger.propagate = False
logger.setLevel(logging.INFO)

pp = pprint.PrettyPrinter(indent=4)

distribution_to_prefix_map = {
    'AlmaLinux': 'm',
    'Amazon': 'a',
    'CentOS': 'c',
    'RedHat': 'r',
    'Rocky': 'k'
}
prefix_to_distribution_map = {}
for distribution, prefix in distribution_to_prefix_map.items():
    prefix_to_distribution_map[prefix] = distribution

def retry_ec2_throttling(min_delay = 1, max_delay = 10 * 60, max_cumulative_delay = 12 * 3600, base = 1, logger = logger):
    """
    Retry calling the decorated function using a linear or exponential backoff.

    This is to handle EC2 API and resource throttling which uses a token bucket
    with a fixed refill rate. Once the bucket is emptied then throttling occurs
    until tokens are added. Tokens are added every second so the minimum retry
    interval is 1 second up to the specified maximum delay.

    I think I like this one better since it randomly spreads the backoff while
    still allowing some short backoffs.

    https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/

    http://www.saltycrane.com/blog/2009/11/trying-out-retry-decorator-python/
    original from: http://wiki.python.org/moin/PythonDecoratorLibrary#Retry

    Decorators described here:
    https://docs.python.org/2/whatsnew/2.4.html?highlight=decorator#pep-318-decorators-for-functions-and-methods

    :param min_delay: Minimum delay before retry
    :type min_delay: int

    :param max_delay: Maximum delay before retry
    :type max_delay: int

    :param max_cumulative_delay: Maximum total time to wait in seconds
    :type max_cumulative_delay: int

    :param base: Base for exponential backoff
    :type base: int

    :param logger: logger to use.
    :type logger: logging.Logger instance
    """
    def deco_retry(f):

        @wraps(f)
        def f_retry(*args, **kwargs):
            attempt = 0
            cumulative_delay = 0.0
            while (cumulative_delay < max_cumulative_delay):
                try:
                    attempt += 1
                    return f(*args, **kwargs)
                except ClientError as e:
                    if e.response['Error']['Code'] in ['RequestLimitExceeded', 'InternalError']:
                        pass
                    else:
                        logger.exception(f"Not retrying exception")
                        raise e
                    logger.debug("%s" % (traceback.format_exc()))
                    logger.debug("attempt=%d" % attempt)
                    current_max_delay = min(max_delay, base * 2 ** attempt)
                    logger.debug("delay_range=(%f %f)" % (min_delay, current_max_delay))
                    # This lousy random number is ok because only being used to sleep during exponential backoff.
                    # It's not used for any security reason.
                    delay = random.uniform(min_delay, current_max_delay) #nosec
                    logger.debug("cumulative delay=%f max=%d" % (cumulative_delay, max_cumulative_delay))
                    logger.debug("Retrying in %f seconds..." % (delay))
                    time.sleep(delay)
                    cumulative_delay += delay
            return f(*args, **kwargs)

        return f_retry  # true decorator

    return deco_retry

class LaunchInstanceThread(threading.Thread):
    '''
    Thread class for creating instances in parallel.
    This is required so that instances can be launched as quickly as possible so that slurm doesn't time out waiting
    for them to enter service.
    '''
    def __init__(self, plugin, kwargs):
        super(LaunchInstanceThread, self).__init__()
        self.plugin = plugin
        self.kwargs = kwargs
        self.result = None
        self.e = None

    def run(self):
        try:
            self.launch_instance()
        except ClientError as e:
            self.e = e
            self.traceback = traceback.format_exc()
            self.exception_reason = e.response['Error']['Code']
        except Exception as e:
            self.e = e
            self.traceback = traceback.format_exc()
            self.exception_reason = 'run_instances failure'
        return

    @retry_ec2_throttling()
    def launch_instance(self):
        self.result = self.plugin.ec2.run_instances(**self.kwargs)
        return

class SlurmPlugin:

    # CloudWatch Metric Names
    # Emitted by Resume
    CW_SLURM_RESUME = "Resume"
    CW_SLURM_TERMINATE_BEFORE_RESUME = "TerminateBeforeResume"
    CW_SLURM_TERMINATE_BEFORE_RESUME_ERROR = "TerminateBeforeResumeError"
    CW_SLURM_START = "Start"
    CW_SLURM_START_ERROR = "StartError"
    CW_SLURM_CREATE = "Create"
    CW_SLURM_CREATE_ERROR = "CreateError"
    CW_SLURM_INSUFFICIENT_CAPACITY = "InsufficientCapacity"
    CW_UNHANDLED_RESUME_EXCEPTION = 'UnhandledPluginResumeException'

    # Emitted by resume_fail
    CW_SLURM_RESUME_TIMEOUT = 'ResumeTimeout'
    CW_SLURM_RESUME_FAIL_TERMINATE = 'ResumeFailTerminate'
    CW_SLURM_RESUME_FAIL_TERMINATE_ERROR = 'ResumeFailTerminateError'
    CW_SLURM_RESUME_FAIL_STOP = 'ResumeFailStop'
    CW_SLURM_RESUME_FAIL_STOP_ERROR = 'ResumeFailStopError'
    CW_UNHANDLED_RESUME_FAIL_EXCEPTION = 'UnhandledPluginResumeFailException'

    # Emitted by stop
    CW_SLURM_STOP = 'Stop'
    CW_SLURM_STOP_TERMINATE = 'StopTerminate'
    CW_SLURM_STOP_TERMINATE_ERROR = 'StopTerminateError'
    CW_SLURM_STOP_STOP = 'StopStop'
    CW_SLURM_STOP_STOP_ERROR = 'StopStopError'
    CW_UNHANDLED_STOP_EXCEPTION = 'UnhandledPluginResumeStopException'

    # Emitted by terminate
    CW_SLURM_TERMINATE = 'Terminate'
    CW_SLURM_TERMINATE_ERROR = 'TerminateError'
    CW_UNHANDLED_TERMINATE_EXCEPTION = 'UnhandledPluginTerminateStopException'

    # Emitted by terminate_old_instances
    CW_SLURM_TERMINATE_OLD_AMI = 'TerminateOldAmi'
    CW_SLURM_TERMINATE_OLD_INSTANCE = 'TerminateOldInstance'
    CW_SLURM_TERMINATE_OLD_INSTANCES_FAILED = 'TerminateOldInstancesFailed'

    CW_SLURM_PUBLISH_CW_FAILED = 'PublishCwFailed'

    CW_SLURMCTLD_DOWN = "SlurmctldDown"

    CW_UNHANDLED_CREATE_NODE_CONF_EXCEPTION = 'UnhandledPluginCreateNodeConfException'
    CW_UNHANDLED_MARK_NODE_DOWN_EXCEPTION = 'UnhandledPluginMarkNodeDownException'
    CW_UNHANDLED_PLUGIN_CONSTRUCTOR_EXCEPTION = 'UnhandledPluginConstructorException'
    CW_UNHANDLED_PUBLISH_CW_METRICS_EXCEPTION = 'UnhandledPluginPublishCwMetricsException'
    CW_UNHANDLED_SUSPEND_RESUME_EXCEPTION = 'UnhandledPluginSuspendResumeException'
    CW_UNHANDLED_TERMINATE_OLD_INSTANCES_EXCEPTION = 'UnhandledPluginTerminateOldInstancesException'

    def __init__(self, slurm_config_file=f"/opt/slurm/config/slurm_config.json", slurm_version_file=f"/opt/slurm/config/SlurmVersion.json", region=None):
        if slurm_config_file:
            with open(slurm_config_file, 'r') as fh:
                self.config = json.load(fh)
            os.environ['AWS_DEFAULT_REGION'] = self.config['region']
        else:
            self.config = {}
        if slurm_version_file:
            with open(slurm_version_file, 'r') as fh:
                self.config.update(json.load(fh))
        if region:
            self.config['region'] = region
            os.environ['AWS_DEFAULT_REGION'] = self.config['region']

        # Create first so that can publish metrics for unhandled exceptions
        self.cw = boto3.client('cloudwatch')
        self.ssm = boto3.client('ssm')

        try:
            self.ec2 = boto3.client('ec2')
            self.ec2_describe_instances_paginator = self.ec2.get_paginator('describe_instances')
            self.describe_instance_status_paginator = self.ec2.get_paginator('describe_instance_status')
        except:
            logger.exception('Unhandled exception in SlurmPlugin constructor')
            self.publish_cw_metrics(self.CW_UNHANDLED_PLUGIN_CONSTRUCTOR_EXCEPTION, 1, [])
            raise
        return

    def suspend_resume_setup(self):
        # Parse args and setup for suspend/resume functions
        global logger

        try:
            logger_formatter = logging.Formatter('%(levelname)s:%(asctime)s: %(message)s')
            logger_rotatingFileHandler = logging.handlers.RotatingFileHandler(filename='/var/log/slurm/power_save.log', mode='a', maxBytes=1000000, backupCount=10)
            logger_rotatingFileHandler.setFormatter(logger_formatter)
            logger.addHandler(logger_rotatingFileHandler)
            logger.setLevel(logging.INFO)

            self.parser = argparse.ArgumentParser("SLURM suspend/resume plugin")
            self.parser.add_argument('hostname_list', help="hostname list")
            self.parser.add_argument('--debug', '-d', action='count', default=False, help="Enable debug messages")
            self.args = self.parser.parse_args()

            if self.args.debug:
                logger_streamHandler = logging.StreamHandler()
                logger_streamHandler.setFormatter(logger_formatter)
                logger.addHandler(logger_streamHandler)
                logger.setLevel(logging.DEBUG)

            self.hostlist = self.args.hostname_list
            self.hostnames = hostlist.expand_hostlist(self.args.hostname_list)
            logger.debug(f"hostnames: {self.hostnames}")

            self.get_instance_type_info()

            self.get_hostinfo(self.hostnames)
        except:
            logger.exception('Unhandled exception in suspend_resume_setup')
            self.publish_cw_metrics(self.CW_UNHANDLED_SUSPEND_RESUME_EXCEPTION, 1, [])
            raise

    def get_instance_type_info(self):
        logger.debug("get_instance_type_info")
        self.instance_type_info = {}
        self.instance_family_info = {}
        describe_instance_types_paginator = self.ec2.get_paginator('describe_instance_types')
        for result in self.paginate(describe_instance_types_paginator, {'Filters': [{'Name': 'current-generation', 'Values': ['true']}]}):
            for instance_type_info in result['InstanceTypes']:
                instanceType = instance_type_info['InstanceType']
                #logger.debug("Found instance info for {}".format(instanceType))
                self.instance_type_info[instanceType] = {}
                self.instance_type_info[instanceType]['full'] = instance_type_info
                architecture = instance_type_info['ProcessorInfo']['SupportedArchitectures'][0]
                self.instance_type_info[instanceType]['architecture'] = architecture
                self.instance_type_info[instanceType]['SustainedClockSpeedInGhz'] = instance_type_info['ProcessorInfo']['SustainedClockSpeedInGhz']
                if 'ValidThreadsPerCore' in instance_type_info['VCpuInfo']:
                    self.instance_type_info[instanceType]['ThreadsPerCore'] = max(instance_type_info['VCpuInfo']['ValidThreadsPerCore'])
                else:
                    if architecture == 'x86_64':
                        self.instance_type_info[instanceType]['ThreadsPerCore'] = 2
                    else:
                        self.instance_type_info[instanceType]['ThreadsPerCore'] = 1
                if 'ValidCores' in instance_type_info['VCpuInfo']:
                    self.instance_type_info[instanceType]['CoreCount'] = max(instance_type_info['VCpuInfo']['ValidCores'])
                else:
                    self.instance_type_info[instanceType]['CoreCount'] = int(instance_type_info['VCpuInfo']['DefaultVCpus']/self.instance_type_info[instanceType]['ThreadsPerCore'])
                self.instance_type_info[instanceType]['MemoryInMiB'] = instance_type_info['MemoryInfo']['SizeInMiB']
                self.instance_type_info[instanceType]['SSDCount'] = instance_type_info.get('InstanceStorageInfo', {'Disks': [{'Count': 0}]})['Disks'][0]['Count']
                self.instance_type_info[instanceType]['SSDTotalSizeGB'] = instance_type_info.get('InstanceStorageInfo', {'TotalSizeInGB': 0})['TotalSizeInGB']
                #logger.debug(pp.pformat(self.instance_type_info[instanceType]))

                (instance_family, instance_size) = instanceType.split(r'.')
                if instance_family not in self.instance_family_info:
                    self.instance_family_info[instance_family] = {}
                    self.instance_family_info[instance_family]['instance_types'] = [instanceType,]
                    self.instance_family_info[instance_family]['MaxInstanceType'] = instanceType
                    self.instance_family_info[instance_family]['MaxInstanceSize'] = instance_size
                    self.instance_family_info[instance_family]['MaxCoreCount'] = self.instance_type_info[instanceType]['CoreCount']
                    self.instance_family_info[instance_family]['architecture'] = architecture
                else:
                    self.instance_family_info[instance_family]['instance_types'].append(instanceType)
                    if self.instance_type_info[instanceType]['CoreCount'] > self.instance_family_info[instance_family]['MaxCoreCount']:
                        self.instance_family_info[instance_family]['MaxInstanceType'] = instanceType
                        self.instance_family_info[instance_family]['MaxInstanceSize'] = instance_size
                        self.instance_family_info[instance_family]['MaxCoreCount'] = self.instance_type_info[instanceType]['CoreCount']

    def get_instance_family(self, instanceType):
        instance_family = instanceType.split(r'.')[0]
        return instance_family

    def get_instance_size(self, instanceType):
        instance_size = instanceType.split(r'.')[1]
        return instance_size

    def get_short_instance_size(self, instanceType):
        instance_size = self.get_instance_size(instanceType)
        short_instance_size = instance_size.replace('large', 'l')
        short_instance_size = short_instance_size.replace('medium', 'm')
        short_instance_size = short_instance_size.replace('micro', 'u')
        short_instance_size = short_instance_size.replace('nano', 'n')
        short_instance_size = short_instance_size.replace('small', 's')
        return short_instance_size

    def decode_short_instance_size(self, short_instance_size):
        if short_instance_size[-1:] == 'l':
            instance_size = short_instance_size + 'arge'
        elif short_instance_size[-1:] == 'm':
            instance_size = 'medium'
        elif short_instance_size[-1:] == 'n':
            instance_size = 'nano'
        elif short_instance_size[-1:] == 's':
            instance_size = 'small'
        elif short_instance_size[-1:] == 'u':
            instance_size = 'micro'
        else:
            instance_size = short_instance_size
        return instance_size

    def get_instance_families(self):
        return sorted(self.instance_type_info.keys())

    def get_max_instance_type(self, instance_family):
        return self.instance_family_info[instance_family]['MaxInstanceType']

    def get_instance_types(self):
        return sorted(self.instance_type_info.keys())

    def get_architecture(self, instance_type):
        return self.instance_type_info[instance_type]['architecture']

    def get_SustainedClockSpeedInGhz(self, instance_type):
        return self.instance_type_info[instance_type]['SustainedClockSpeedInGhz']

    def get_CoreCount(self, instance_type):
        return self.instance_type_info[instance_type]['CoreCount']

    def get_ThreadsPerCore(self, instance_type):
        return self.instance_type_info[instance_type]['ThreadsPerCore']

    def get_MemoryInMiB(self, instance_type):
        return self.instance_type_info[instance_type]['MemoryInMiB']

    def get_SSDCount(self, instance_type):
        return self.instance_type_info[instance_type]['SSDCount']

    def get_SSDTotalSizeGB(self, instance_type):
        return self.instance_type_info[instance_type]['SSDTotalSizeGB']

    def get_full_info(self, instance_type):
        return self.instance_type_info[instance_type]['full']

    def get_hostinfo(self, hostnames):
        logger.debug(f"get_hostinfo({hostnames})")
        self.hostinfo = {}
        for hostname in hostnames:
            self.add_hostname_to_hostinfo(hostname)

        # Find existing unterminated instances
        # Collect the number of SlurmNodes in each state overall and by instance type
        slurmNodeStats = {}
        for result in self.paginate(self.ec2_describe_instances_paginator, {}):
            for reservation in result['Reservations']:
                for instance in reservation['Instances']:
                    # Ignore instances that aren't SlurmNodes
                    role = self.getTag('role', instance)
                    if not role or role != 'SlurmNode':
                        continue

                    # Ignore instances that aren't in this cluster
                    cluster = self.getTag('ClusterName', instance)
                    if not cluster or cluster != self.config['ClusterName']:
                        continue

                    # Ignore terminated or terminating instances
                    state = instance['State']['Name']
                    if state in ['shutting-down', 'terminated']:
                        continue

                    instanceType = instance['InstanceType']
                    if state not in slurmNodeStats:
                        slurmNodeStats[state] = {}
                        slurmNodeStats[state]['all'] = 0
                    if instanceType not in slurmNodeStats[state]:
                        slurmNodeStats[state][instanceType] = 0
                    slurmNodeStats[state][instanceType] += 1
                    slurmNodeStats[state]['all'] += 1

                    hostname = self.getTag('hostname', instance)
                    if not hostname:
                        continue
                    if hostname not in self.hostinfo:
                        self.add_hostname_to_hostinfo(hostname)

                    hostinfo = self.hostinfo[hostname]

                    # Check for duplicate instances with the same hostname
                    instanceId = instance['InstanceId']
                    if hostinfo['instanceId']:
                        reason = "Multiple instances of {}. Marking node as down. Instances: {} {}".format(hostname, hostinfo['instanceId'], instanceId)
                        logger.error(reason)
                        self.mark_node_down(hostname, reason)
                        continue

                    hostinfo['instanceId'] = instanceId
                    hostinfo['State'] = state
                    hostinfo['ImageId'] = instance['ImageId']
                    hostinfo['LaunchTime'] = instance.get('LaunchTime', None)
                    logger.debug("Found %s(%s) state=%s" % (hostname, instanceId, state))

        # Save SlurmNode counts to CloudWatch
        for state in slurmNodeStats.keys():
            for instanceType in slurmNodeStats[state]:
                count = slurmNodeStats[state][instanceType]
                self.publish_cw_metrics('NodeCount', count, [{'Name': 'State', 'Value': state}, {'Name': 'InstanceType', 'Value': instanceType}])

    def add_hostname_to_hostinfo(self, hostname):
        if hostname in self.hostinfo:
            return

        hostinfo = {}

        try:
            distribution, distribution_major_version, architecture, instance_family, instance_size, spot = self.parse_hostname(hostname)[0:6]
            bad_hostname = False
        except:
            logger.exception(f"Bad hostname: {hostname}")
            bad_hostname = True
        if bad_hostname:
            logger.error(f"Marking {hostname} as down.")
            self.mark_node_down(hostname, f'Invalid hostname={hostname}')
            return

        hostinfo['distribution'] = distribution
        hostinfo['distribution_major_version'] = distribution_major_version

        ssm_parameter_name = f"/{self.config['STACK_NAME']}/SlurmNodeAmis/{distribution}/{distribution_major_version}/{architecture}"
        try:
            hostinfo['ami'] = self.ssm.get_parameter(Name=ssm_parameter_name)["Parameter"]["Value"]
        except Exception as e:
            logging.exception(f"Error getting ami from SSM parameter {ssm_parameter_name}")
            # Don't have a way of handling this.
            raise e

        instance_type = instance_family + '.' + instance_size

        hostinfo['instance_family'] = instance_family
        hostinfo['instance_size'] = instance_size
        hostinfo['instance_type'] = instance_type

        hostinfo['spot'] = spot

        hostinfo['coreCount'] = self.instance_type_info[instance_type]['CoreCount']

        hostinfo['instanceId'] = None

        self.hostinfo[hostname] = hostinfo

    def update_hostinfo(self, instanceIds=[]):
        logger.debug("Updating hostinfo")
        for result in self.paginate(self.ec2_describe_instances_paginator, {'InstanceIds': instanceIds}):
            for reservation in result['Reservations']:
                for instance in reservation['Instances']:
                    # Ignore instances that aren't SlurmNodes
                    role = self.getTag('role', instance)
                    if not role or role != 'SlurmNode':
                        continue

                    # Ignore instances that aren't in this cluster
                    cluster = self.getTag('SlurmCluster', instance)
                    if not cluster or cluster != self.config['ClusterName']:
                        continue

                    # Ignore terminated or terminating instances
                    state = instance['State']['Name']
                    if state in ['shutting-down', 'terminated']:
                        continue

                    hostname = self.getTag('hostname', instance)
                    if not hostname:
                        continue
                    instanceId = instance['InstanceId']
                    logger.debug("Found %s(%s) state=%s" % (hostname, instanceId, state))

                    if hostname not in self.hostinfo:
                        self.add_hostname_to_hostinfo(hostname)
                    self.hostinfo[hostname]['instanceId'] = instanceId
                    self.hostinfo[hostname]['ImageId'] = instance['ImageId']
                    self.hostinfo[hostname]['State'] = state

    def getTag(self, key, instance):
        value = None
        for tag in instance.get('Tags', []):
            if tag['Key'] == key:
                value = tag['Value']
                break
        return value

    def resume(self):
        try:
            self.test_ice = False

            self.suspend_resume_setup()

            logger.info("Resuming {} hosts: {}".format(len(self.hostnames), self.hostlist))
            self.publish_cw_metrics(self.CW_SLURM_RESUME, len(self.hostnames), [])

            # Decide what to do for each hostname
            # Possible states:
            # * none     - create
            # * pending  - no action
            # * running  - no action
            # * stopping - Terminate if old ami and create, else wait for stopped then start
            # * stopped  - Terminate if old ami and create, else start
            # * shutting-down - ignored when collecting info
            # * terminated    - ignored when collecting info
            hostnames_to_create = []
            hostnames_to_terminate = []
            instanceIds_to_terminate = []
            stopping_hostnames = []
            stopping_instanceIds = []
            stopped_hostnames = []
            stopped_instanceIds = []
            for hostname in self.hostnames:
                hostinfo = self.hostinfo[hostname]

                # Create new instance if one doesn't exist
                instanceId =  hostinfo['instanceId']
                if not instanceId:
                    hostnames_to_create.append(hostname)
                    logger.debug("Creating new instance for %s" % hostname)
                    continue

                state = hostinfo['State']
                # Skip instances that are already pending or running
                if state in ['pending', 'running']:
                    logger.info("{}({}) already {}. Skipping.".format(hostname, hostinfo['instanceId'], state))
                    continue

                # Find stopping or stopped instances that need to be terminated because of old AMIs
                imageId = hostinfo['ImageId']
                ami = hostinfo['ami']
                if imageId != ami:
                    hostnames_to_terminate.append(hostname)
                    instanceIds_to_terminate.append(instanceId)
                    logger.info("Terminating {}({}) because current AMI({}) != {} then create new instance".format(hostname, instanceId, imageId, ami))
                    continue

                # Find hosts that are stopping or stopped that need to be started
                # Cannot start an instance that is in stopping state
                # Will wait for stopping instances below and then start them.
                if state == 'stopping':
                    stopping_hostnames.append(hostname)
                    stopping_instanceIds.append(instanceId)
                    logger.info("Waiting for {}({}) to stop".format(hostname, instanceId))
                    continue
                if state == 'stopped':
                    stopped_hostnames.append(hostname)
                    stopped_instanceIds.append(instanceId)
                    logger.info("Starting {}({})".format(hostname, instanceId))
                    hostinfo['State'] = 'running'
                    continue

            if instanceIds_to_terminate:
                terminated_hostnames = self.terminate_instanceIds(
                    hostnames_to_terminate, instanceIds_to_terminate,
                    'terminating instances before resume',
                    self.CW_SLURM_TERMINATE_BEFORE_RESUME,
                    self.CW_SLURM_TERMINATE_BEFORE_RESUME_ERROR)[0]
                for hostname in terminated_hostnames:
                    hostnames_to_create.append(hostname)

            if stopped_hostnames:
                self.publish_cw_metrics(self.CW_SLURM_START, len(stopped_hostnames), [])
                start_instances_exception = None
                start_instances_exception_reason = None
                try:
                    self.start_instances({'InstanceIds': stopped_instanceIds})
                except ClientError as e:
                    # botocore.exceptions.ClientError: An error occurred (ResourceCountExceeded) when calling the StartInstances operation:
                    # You have exceeded the number of resources allowed in a single call of this type
                    start_instances_exception = e
                    start_instances_exception_reason = e.response['Error']['Code']
                    logger.error("start_instances failed because {}".format(start_instances_exception_reason))
                except Exception as e:
                    start_instances_exception = e
                    start_instances_exception_reason = "Unknown"
                    logger.exception("start_instances failed with unknown exception")
                if start_instances_exception:
                    # If there is more than one instance then some may have started so need to iterate through each instance
                    # to see which ones started and which ones didn't so we can mark the failed
                    # instances as DOWN so that their jobs will be rescheduled immediately instead of waiting
                    # for the resume timeout.
                    self.update_hostinfo(stopped_instanceIds)
                    start_failures = 0
                    insufficientCapacity_failures = {}
                    for hostname in stopped_hostnames:
                        hostinfo = self.hostinfo[hostname]
                        state = hostinfo['State']
                        if state == 'stopped':
                            instanceId = hostinfo['instanceId']
                            logger.error("{}({}) failed to start because {}".format(hostname, instanceId, start_instances_exception_reason))
                            self.mark_node_down(hostname, start_instances_exception_reason)
                            if start_instances_exception_reason == 'InsufficientInstanceCapacity':
                                instanceType = hostinfo['instance_type']
                                insufficientCapacity_failures[instanceType] = insufficientCapacity_failures.get(instanceType, 0) + 1
                            else:
                                start_failures += 1
                    if start_instances_exception_reason == 'InsufficientInstanceCapacity':
                        for instance_type in insufficientCapacity_failures.keys():
                            self.publish_cw_metrics(self.CW_SLURM_INSUFFICIENT_CAPACITY, insufficientCapacity_failures[instance_type], [{'Name': 'InstanceType', 'Value': instance_type}])
                    else:
                        self.publish_cw_metrics(self.CW_SLURM_START_ERROR, max(start_failures, 1), [])
                        self.publish_cw_metrics(self.CW_SLURM_START_ERROR, max(start_failures, 1), [{'Name': 'Reason', 'Value': start_instances_exception_reason}])


            # Find hosts without instances that need to be launched
            # These each need to be run separately because they have different userdata and may have different instance types.
            # If they get run serially then later instances may time out if a bunch of instances are starting at
            # the same time.
            # So, create a thread for each instance to launch them as quickly as possible.
            #
            # When creating a new instance
            # Always use a new ip address because terminated instances should have deleted
            # their DNS entry. If an instance is still terminating then it might still be
            # using the IP address
            if hostnames_to_create:
                self.publish_cw_metrics(self.CW_SLURM_CREATE, len(hostnames_to_create), [])
            userDataFilename = os.path.join(dirname(realpath(__file__)), 'SlurmNodeUserData.sh')
            userDataTemplate = Template(open(userDataFilename, 'r').read())
            for hostname in hostnames_to_create:
                hostinfo = self.hostinfo[hostname]
                ami = hostinfo['ami']
                userData = userDataTemplate.render({
                        'DOMAIN': self.config['DOMAIN'],
                        'hostname': hostname,
                        'SlurmConfigDir': self.config['SlurmConfigDir'],
                        'SlurmLogsDir': self.config['SlurmLogsDir'],
                        'SlurmScriptsDir': self.config['SlurmScriptsDir'],
                    }
                )
                kwargs = {
                    'ImageId': ami,
                    'InstanceType': hostinfo['instance_type'],
                    'MaxCount': 1,
                    'MinCount': 1,
                    'KeyName': self.config['EC2_KEY_PAIR'],
                    'SecurityGroupIds': [self.config['SLURMNODE_SECURITY_GROUP']],
                    'SubnetId': self.config['SLURMNODE_SUBNET'],
                    'IamInstanceProfile': {'Arn': self.config['SLURMNODE_PROFILE_ARN']},
                    'UserData': userData,
                    'TagSpecifications': [
                        {
                            'ResourceType': 'instance',
                            'Tags': [
                                {'Key': 'Name', 'Value': f"{self.config['STACK_NAME']} {hostname}"},
                                {'Key': 'ClusterName', 'Value': self.config['ClusterName']},
                                {'Key': 'hostname', 'Value': hostname},
                                {'Key': 'role', 'Value': 'SlurmNode'},
                                {'Key': 'distribution', 'Value': hostinfo['distribution']},
                                {'Key': 'distribution_major_version', 'Value': hostinfo['distribution_major_version']},
                                {'Key': 'spot', 'Value': str(hostinfo['spot'])},
                            ]
                        }
                    ],
                    'BlockDeviceMappings': [],
                }
                if self.get_ThreadsPerCore(hostinfo['instance_type']) > 1:
                    kwargs['CpuOptions'] = {'CoreCount': hostinfo['coreCount'], 'ThreadsPerCore': 1}
                if hostinfo['spot']:
                    kwargs['InstanceMarketOptions'] = {
                        'MarketType': 'spot',
                        'SpotOptions': {
                            'SpotInstanceType': 'one-time',
                            'InstanceInterruptionBehavior': 'terminate'
                        }
                    }
                drive_letter = 'c'
                for ephemeral_index in range(0, self.instance_type_info[hostinfo['instance_type']]['SSDCount']):
                    kwargs['BlockDeviceMappings'].append({'DeviceName': '/dev/sd'+drive_letter, 'VirtualName': 'ephemeral'+str(ephemeral_index)})
                    drive_letter = chr(ord(drive_letter) + 1)
                logger.debug(f"run_instances kwargs:\n{pp.pformat(kwargs)}")
                hostinfo['launch_thread'] = LaunchInstanceThread(self, kwargs)
                hostinfo['launch_thread'].start()
            # Wait for instances to be launched
            launch_failures = 0
            insufficientCapacity_failures = {}
            for hostname in hostnames_to_create:
                hostinfo = self.hostinfo[hostname]
                launch_thread = hostinfo['launch_thread']
                launch_thread.join()
                if launch_thread.result:
                    instanceId = launch_thread.result['Instances'][0]['InstanceId']
                    hostinfo['instanceId'] = instanceId
                    hostinfo['ImageId'] = hostinfo['ami']
                    hostinfo['State'] = 'running'
                    logger.info("Created {}({})".format(hostname, instanceId))
                if self.test_ice:
                    launch_thread.exception_reason = 'InsufficientInstanceCapacity'
                    launch_thread.traceback = "Dummy traceback"
                if not launch_thread.result or self.test_ice:
                    logger.error(f"Failed to create {hostname}. Marking down with reason=\'{launch_thread.exception_reason}\'.\n{launch_thread.traceback}")
                    if launch_thread.exception_reason == 'InsufficientInstanceCapacity':
                        instanceType = hostinfo['instance_type']
                        insufficientCapacity_failures[instanceType] = insufficientCapacity_failures.get(instanceType, 0) + 1
                    else:
                        launch_failures += 1
                        self.publish_cw_metrics(self.CW_SLURM_CREATE_ERROR, 1, [{'Name': 'Reason', 'Value': launch_thread.exception_reason}])
                    self.mark_node_down(hostname, launch_thread.exception_reason)
            if launch_failures:
                self.publish_cw_metrics(self.CW_SLURM_CREATE_ERROR, launch_failures, [])
            for instance_type in insufficientCapacity_failures.keys():
                self.publish_cw_metrics(self.CW_SLURM_INSUFFICIENT_CAPACITY, insufficientCapacity_failures[instance_type], [{'Name': 'InstanceType', 'Value': instance_type}])

            # Wait for stopping instances to be stopped and then start them
            while stopping_hostnames:
                time.sleep(1)
                self.update_hostinfo(stopping_instanceIds)
                stopped_hostnames = []
                stopped_instanceIds = []
                for hostname in stopping_hostnames:
                    hostinfo = self.hostinfo[hostname]
                    state = hostinfo['State']
                    if state == 'stopped':
                        instanceId = hostinfo['instanceId']
                        stopped_hostnames.append(hostname)
                        stopped_instanceIds.append(instanceId)
                        logger.info("Starting {}({}) after it finished stopping".format(hostname, instanceId))
                if stopped_instanceIds:
                    self.publish_cw_metrics(self.CW_SLURM_START, len(stopped_instanceIds), [])
                    start_instances_exception = None
                    start_instances_exception_reason = None
                    try:
                        self.start_instances({'InstanceIds': stopped_instanceIds})
                    except ClientError as e:
                        start_instances_exception = e
                        start_instances_exception_reason = e.response['Error']['Code']
                        logger.exception("start_instances failed because {}".format(start_instances_exception_reason))
                    except Exception as e:
                        start_instances_exception = e
                        start_instances_exception_reason = "Unknown"
                        logger.exception("start_instances failed with unknown exception")
                    if start_instances_exception:
                        # If there is more than one instance then some may have started so need to iterate through each instance
                        # to see which ones started and which ones didn't so we can mark the failed
                        # instances as DOWN so that their jobs will be rescheduled immediately instead of waiting
                        # for the resume timeout.
                        self.update_hostinfo(stopped_instanceIds)
                        start_failures = 0
                        insufficientCapacity_failures = {}
                        for hostname in stopped_hostnames:
                            hostinfo = self.hostinfo[hostname]
                            state = hostinfo['State']
                            if state == 'stopped':
                                start_failures += 1
                                instanceId = hostinfo['instanceId']
                                logger.error("{}({}) failed to start because {}".format(hostname, instanceId, start_instances_exception_reason))
                                self.mark_node_down(hostname, start_instances_exception_reason)
                                if start_instances_exception_reason == 'InsufficientInstanceCapacity':
                                    instanceType = hostinfo['instance_type']
                                    insufficientCapacity_failures[instanceType] = insufficientCapacity_failures.get(instanceType, 0) + 1
                                else:
                                    start_failures += 1
                        if start_instances_exception_reason == 'InsufficientInstanceCapacity':
                            for instance_type in insufficientCapacity_failures.keys():
                                self.publish_cw_metrics(self.CW_SLURM_INSUFFICIENT_CAPACITY, insufficientCapacity_failures[instance_type], [{'Name': 'InstanceType', 'Value': instance_type}])
                        else:
                            self.publish_cw_metrics(self.CW_SLURM_START_ERROR, max(start_failures, 1), [])
                            self.publish_cw_metrics(self.CW_SLURM_START_ERROR, max(start_failures, 1), [{'Name': 'Reason', 'Value': start_instances_exception_reason}])

                    for hostname in stopped_hostnames:
                        instanceId = self.hostinfo[hostname]['instanceId']
                        stopping_hostnames.remove(hostname)
                        stopping_instanceIds.remove(instanceId)

            self.update_hostinfo()
            self.terminate_old_instances()
        except:
            logger.exception('Unhandled exception in SlurmPlugin.resume')
            self.publish_cw_metrics(self.CW_UNHANDLED_RESUME_EXCEPTION, 1, [])
            raise

    def resume_fail(self):
        try:
            self.suspend_resume_setup()

            logger.error("Resume failed on {} hosts: {}".format(len(self.hostnames), self.hostlist))
            # They will already have been marked down my slurmctld
            # Just log it to CloudWatch
            self.publish_cw_metrics(self.CW_SLURM_RESUME_TIMEOUT, len(self.hostnames), [])

            # Now stop them so that they stop consuming resources until they can be debugged.
            hostnames_to_terminate = []
            instanceIds_to_terminate = []
            hostnames_to_stop = []
            instanceIds_to_stop = []
            for hostname in self.hostnames:
                hostinfo = self.hostinfo[hostname]
                instanceId = hostinfo['instanceId']
                if not instanceId:
                    logger.info("Not stopping {}({}) because no instance found".format(hostname, instanceId))
                    continue
                state = hostinfo['State']
                if state in ['stopping', 'stopped']:
                    logger.info("Not stopping {}({}) because state={}".format(hostname, instanceId, state))
                elif state == 'pending':
                    logger.info("Terminating {}({}) during resume_fail because state={}".format(hostname, instanceId, state))
                    hostnames_to_terminate.append(hostname)
                    instanceIds_to_terminate.append(instanceId)
                elif hostinfo['spot']:
                    logger.info(f"Terminating {hostname}({instanceId}) during resume_fail because spot instances can't be stopped")
                    hostnames_to_terminate.append(hostname)
                    instanceIds_to_terminate.append(instanceId)
                else:
                    logger.info("Stopping {}({}) because resume failed".format(hostname, instanceId))
                    hostnames_to_stop.append(hostname)
                    instanceIds_to_stop.append(instanceId)

            if instanceIds_to_terminate:
                self.terminate_instanceIds(
                    hostnames_to_terminate, instanceIds_to_terminate,
                    'terminating instances during resume_fail',
                    self.CW_SLURM_RESUME_FAIL_TERMINATE, self.CW_SLURM_RESUME_FAIL_TERMINATE_ERROR)

            if instanceIds_to_stop:
                self.stop_instanceIds(
                    hostnames_to_stop, instanceIds_to_stop,
                    'stopping instances during resume_fail',
                    self.CW_SLURM_RESUME_FAIL_STOP, self.CW_SLURM_RESUME_FAIL_STOP_ERROR)

        except:
            logger.exception('Unhandled exception in SlurmPlugin.resume_fail')
            self.publish_cw_metrics(self.CW_UNHANDLED_RESUME_FAIL_EXCEPTION, 1, [])
            raise

    def stop(self):
        try:
            self.suspend_resume_setup()

            logger.info("Stopping  {} hosts: {}".format(len(self.hostnames), self.hostlist))
            self.publish_cw_metrics(self.CW_SLURM_STOP, len(self.hostnames), [])

            # Decide what to do for each hostname
            # Possible states:
            # * none     - no action
            # * pending  - no action. Will update slurm when starts running
            # * running  - if old ami terminate, else stop
            # * stopping - if old ami terminate, else no action
            # * stopped  - if old ami terminate, else no action
            # * shutting-down - ignored when collecting info
            # * terminated    - ignored when collecting info
            hostnames_to_terminate = []
            instanceIds_to_terminate = []
            hostnames_to_stop = []
            instanceIds_to_stop = []
            for hostname in self.hostnames:
                hostinfo = self.hostinfo[hostname]
                instanceId = hostinfo['instanceId']
                if not instanceId:
                    logger.info("Not stopping {}({}) because no instance found".format(hostname, instanceId))
                    continue

                state = hostinfo['State']
                if state == 'pending':
                    # Skip because when it starts running it will contact slurmctld and state will update to POWER_UP,IDLE
                    logger.info('Cannot stop {}({}) because state=={}. Skipping because state will be updated when enters service.'.format(hostname, instanceId, state))
                    continue

                # Spot instances can't be stopped so terminate them
                if hostinfo['spot']:
                    hostnames_to_terminate.append(hostname)
                    instanceIds_to_terminate.append(instanceId)
                    logger.info(f"Terminating {hostname}({instanceId}) because spot instances can't be stopped.")
                    continue

                # Find instances that need to be terminated because of old AMIs
                ami = hostinfo['ami']
                imageId = hostinfo['ImageId']
                if imageId != ami:
                    hostnames_to_terminate.append(hostname)
                    instanceIds_to_terminate.append(instanceId)
                    logger.info("Terminating {}({}) because current AMI({}) != {}".format(hostname, instanceId, imageId, ami))
                    continue

                if state in ['stopping', 'stopped']:
                    logger.info("Not stopping {}({}) because state={}".format(hostname, instanceId, state))
                    continue

                if state not in ['running']:
                    # Shouldn't ever get here
                    logger.error('Cannot stop {}({}) because not running. State={}'.format(hostname, instanceId, state))
                    continue

                hostnames_to_stop.append(hostname)
                instanceIds_to_stop.append(instanceId)

            if instanceIds_to_terminate:
                self.terminate_instanceIds(
                    hostnames_to_terminate, instanceIds_to_terminate,
                    'terminating instance during stop',
                    self.CW_SLURM_STOP_TERMINATE,
                    self.CW_SLURM_STOP_TERMINATE_ERROR
                )

            if instanceIds_to_stop:
                self.stop_instanceIds(hostnames_to_stop, instanceIds_to_stop, 'stopping instance during stop', self.CW_SLURM_STOP_STOP, self.CW_SLURM_STOP_STOP_ERROR)

            self.update_hostinfo()
            self.terminate_old_instances()
        except:
            logger.exception('Unhandled exception in SlurmPlugin.stop')
            self.publish_cw_metrics(self.CW_UNHANDLED_STOP_EXCEPTION, 1, [])
            raise

    def terminate(self):
        try:
            self.suspend_resume_setup()

            logger.info("Terminating {} hosts: {}".format(len(self.hostnames), self.hostlist))
            self.publish_cw_metrics(self.CW_SLURM_TERMINATE, len(self.hostnames), [])

            # Find instances that need to be terminated
            # Decide what to do for each hostname
            # Possible states:
            # * none     - no action
            # * pending  - terminate
            # * running  - terminate
            # * stopping - terminate
            # * stopped  - terminate
            # * shutting-down - ignored when collecting info
            # * terminated    - ignored when collecting info
            hostnames_to_terminate = []
            instanceIds_to_terminate = []
            for hostname in self.hostnames:
                hostinfo = self.hostinfo[hostname]
                instanceId = hostinfo['instanceId']
                if not instanceId:
                    continue

                hostnames_to_terminate.append(hostname)
                instanceIds_to_terminate.append(instanceId)
                logger.info("Terminating {}({})".format(hostname, instanceId))
            if instanceIds_to_terminate:
                self.terminate_instanceIds(
                    hostnames_to_terminate, instanceIds_to_terminate,
                    'terminating instances',
                    self.CW_SLURM_TERMINATE,
                    self.CW_SLURM_TERMINATE_ERROR
                )

            self.update_hostinfo()
            self.terminate_old_instances()
        except:
            logger.exception('Unhandled exception in SlurmPlugin.terminate')
            self.publish_cw_metrics(self.CW_UNHANDLED_TERMINATE_EXCEPTION, 1, [])
            raise

    def terminate_old_instances_main(self):
        global logger
        try:
            logger_formatter = logging.Formatter('%(levelname)s:%(asctime)s: %(message)s')
            logger_rotatingFileHandler = logging.handlers.RotatingFileHandler(filename='/var/log/slurm/terminate_old_instances.log', mode='a', maxBytes=1000000, backupCount=10)
            logger_rotatingFileHandler.setFormatter(logger_formatter)
            logger.addHandler(logger_rotatingFileHandler)
            logger.setLevel(logging.INFO)
            logger.propagate = False

            self.parser = argparse.ArgumentParser("Create SLURM node config from EC2 instance metadata")
            self.parser.add_argument('--debug', '-d', action='count', default=False, help="Enable debug messages")
            self.args = self.parser.parse_args()

            if self.args.debug:
                logger_streamHandler = logging.StreamHandler()
                logger_streamHandler.setFormatter(logger_formatter)
                logger.addHandler(logger_streamHandler)
                logger.setLevel(logging.DEBUG)
                logger.debug(f"Debugging level {self.args.debug}")

            logger.debug("terminate_old_instances_main()")

            if not self.check_slurmctld():
                logger.error("check_slurmctld failed")
                self.publish_cw_metrics(self.CW_SLURM_TERMINATE_OLD_INSTANCES_FAILED, 1, [])
                return 1

            self.get_instance_type_info()
            self.get_hostinfo([])
            self.terminate_old_instances()
        except:
            logger.exception("Unhandled exception in SlurmPlugin.terminate_old_instances_main")
            self.publish_cw_metrics(self.CW_UNHANDLED_TERMINATE_OLD_INSTANCES_EXCEPTION, 1, [])
            raise
        return 0

    def check_slurmctld(self):
        '''
        Check to make sure that the slurmctld service is up.
        '''
        try:
            # Not executing untrusted input.
            subprocess.check_output(["/usr/bin/systemctl", 'status', 'slurmctld'], stderr=subprocess.STDOUT, encoding='UTF-8') # nosec
            return True
        except subprocess.CalledProcessError as e:
            logger.exception(f"slurmctld service not running\ncommand: {e.cmd}\noutput:\n{e.output}")
            self.publish_cw_metrics(self.CW_SLURMCTLD_DOWN, 1, [])
        return False

    def terminate_old_instances(self):
        # Find stopped instances that have an old AMI
        logger.debug("Checking for stopped instances with old AMIs to terminate")
        hostnames_to_terminate = []
        instanceIds_to_terminate = []
        for hostname in sorted(self.hostinfo.keys()):
            hostinfo = self.hostinfo[hostname]
            instanceId = hostinfo['instanceId']
            if not instanceId:
                continue

            state = hostinfo['State']
            if state not in ['stopping', 'stopped']:
                continue

            ami = hostinfo['ami']
            imageId = hostinfo['ImageId']
            if ami != imageId:
                hostnames_to_terminate.append(hostname)
                instanceIds_to_terminate.append(instanceId)
                logger.info("Terminating {}({}) because current AMI({}) != {}".format(hostname, instanceId, imageId, ami))
                continue

        if instanceIds_to_terminate:
            self.terminate_instanceIds(
                hostnames_to_terminate, instanceIds_to_terminate,
                'terminating because of old ami',
                self.CW_SLURM_TERMINATE_OLD_AMI,
                self.CW_SLURM_TERMINATE_ERROR
            )

        # Find old stopped instances
        deadline = datetime.now(tz=timezone.utc) - parse_duration(self.config['MaxStoppedDuration'])
        logger.debug(f"Checking for stopped instances that are older than {deadline} to terminate")
        hostnames_to_terminate = []
        instanceIds_to_terminate = []
        for hostname in sorted(self.hostinfo.keys()):
            hostinfo = self.hostinfo[hostname]
            instanceId = hostinfo['instanceId']
            if not instanceId:
                continue

            state = hostinfo['State']
            if state not in ['stopping', 'stopped']:
                continue

            launchTime = hostinfo.get('LaunchTime', None)
            if launchTime and launchTime <= deadline:
                hostnames_to_terminate.append(hostname)
                instanceIds_to_terminate.append(instanceId)
                logger.info(f"Terminating {hostname}({instanceId}) because it is stopped and older than {deadline}.")
                continue

        if instanceIds_to_terminate:
            self.terminate_instanceIds(
                hostnames_to_terminate, instanceIds_to_terminate,
                'terminating because older than {deadline}',
                self.CW_SLURM_TERMINATE_OLD_AMI,
                self.CW_SLURM_TERMINATE_ERROR
            )

    def stop_instanceIds(self, hostnames_to_stop, instanceIds_to_stop,
        action, metric, error_metric):
        if not instanceIds_to_stop:
            return
        self.publish_cw_metrics(self.CW_SLURM_STOP_STOP, len(instanceIds_to_stop), [])
        retry = False
        try:
            self.stop_instances({'InstanceIds': instanceIds_to_stop})
        except ClientError as e:
            retry = True
            if e.response['Error']['Code'] == 'ResourceCountExceeded':
                logger.info("Caught {} while stopping {} instances".format(e.response['Error']['Code'], len(instanceIds_to_stop)))
            else:
                logger.exception("Error {}".format(action))
                self.publish_cw_metrics(error_metric, 1, [])
        except:
            retry = True
            logger.exception("Error while stopping instances")
            self.publish_cw_metrics(self.CW_SLURM_STOP_STOP_ERROR, 1, [])
            # This will create a ticket, but instances may still be running
            # that should be stopped.
            # So try again doing them one at a time
        if retry:
            for hostname in hostnames_to_stop:
                hostinfo = self.hostinfo[hostname]
                instanceId = hostinfo['instanceId']
                try:
                    self.stop_instances({'InstanceIds': [instanceId]})
                except:
                    logger.exception("Error while stopping {}({})".format(hostname, instanceId))
                    self.publish_cw_metrics(self.CW_SLURM_STOP_STOP_ERROR, 1)

    def terminate_instanceIds(self, hostnames_to_terminate, instanceIds_to_terminate,
        action, metric, error_metric):
        if not instanceIds_to_terminate:
            return
        self.publish_cw_metrics(metric, len(instanceIds_to_terminate), [])
        retry = False
        try:
            self.terminate_instances({'InstanceIds': instanceIds_to_terminate})
            terminated_hostnames = hostnames_to_terminate
            terminated_instanceIds = instanceIds_to_terminate
            for hostname in hostnames_to_terminate:
                self.hostinfo[hostname]['instanceId'] = None
        except ClientError as e:
            retry = True
            if e.response['Error']['Code'] == 'ResourceCountExceeded':
                logger.info("Caught {} while terminating {} instances".format(e.response['Error']['Code'], len(instanceIds_to_terminate)))
            else:
                logger.exception("Error {}".format(action))
                self.publish_cw_metrics(error_metric, 1, [])
        except:
            retry = True
            logger.exception("Error {}".format(action))
            self.publish_cw_metrics(error_metric, 1, [])
            # This will create a ticket, but instances may still be running
            # that should be terminated.
            # So try again doing them one at a time
        if retry:
            terminated_hostnames = []
            terminated_instanceIds = []
            for hostname in hostnames_to_terminate:
                instanceId = self.hostinfo[hostname]['instanceId']
                try:
                    self.terminate_instances({'InstanceIds': [instanceId]})
                    terminated_hostnames.append(hostname)
                    terminated_instanceIds.append(instanceId)
                except:
                    logger.exception("Error {} {}({})".format(action, hostname, instanceId))
                    self.publish_cw_metrics(error_metric, 1, [])
        return (terminated_hostnames, terminated_instanceIds)

    def publish_cw_metrics(self, metric_name, value, dimensions):
        # All metrics need to include the ClusterName as a dimension.
        dimensions.append({'Name': 'Cluster', 'Value': self.config['ClusterName']})
        msg = "CW publish SLURM:{}".format(metric_name)
        for dimension in dimensions:
            msg += ":{}={}".format(dimension['Name'], dimension['Value'])
        msg += ":{}".format(value)
        logger.debug(msg)
        try:
            self.cw.put_metric_data(
                Namespace='SLURM',
                MetricData=[
                    {'MetricName': metric_name,
                    'Dimensions': dimensions, 'Value': value, 'Unit': 'Count'}
                ]
            )
        except:
            logger.exception("PutMetricData failed")
        return

    def parse_hostname(self, hostname):
        logger.debug(f"hostname={hostname}")
        fields = hostname.split('-')
        logger.debug(f"fields: {fields}")
        if len(fields) < 5:
            raise ValueError(f"{hostname} has less than 5 fields: {fields}")
        elif len(fields) > 6:
            raise ValueError(f"{hostname} has more than 6 fields: {fields}")
        (os, short_architecture, instance_family, short_instance_size) = fields[0:4]
        spot = fields[4] == 'sp'
        index = fields[-1]
        if len(os) != 2:
            raise ValueError(f"{hostname} has invalid os: {os}. Must be 2 characters.")
        distribution_prefix = os[0]
        try:
            distribution = prefix_to_distribution_map[distribution_prefix]
        except KeyError as e:
            raise ValueError("{hostname} has invalid distribution: {distribution_prefix}. Must be in {prefix_to_distribution_map.keys()}")
        distribution_version = os[1]
        logger.debug(f"distribution={distribution}")
        logger.debug(f"distribution_version={distribution_version}")
        if short_architecture == 'x86':
            architecture = 'x86_64'
        elif short_architecture == 'arm':
            architecture = 'arm64'
        else:
            raise ValueError(f"{hostname} architecture='{short_architecture}' not in ['x86', 'arm64'].")
        logger.debug(f"architecture={architecture}")
        instance_size = self.decode_short_instance_size(short_instance_size)
        logger.debug(f"instance_family={instance_family}")
        logger.debug(f"instance_size={instance_size}")
        logger.debug(f"spot={spot}")
        logger.debug(f"index={index}")
        return (distribution, distribution_version, architecture, instance_family, instance_size, spot, index)

    def drain(self, hostname, reason):
        logger.info(f"Setting {hostname} to drain so new jobs do not run on it.")
        try:
            # Not executing untrusted input.
            subprocess.run([f"{self.config['SLURM_ROOT']}/bin/scontrol", 'update', f"nodename={hostname}", 'state=DRAIN', f"reason='{reason}'"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='UTF-8') # nosec
        except subprocess.CalledProcessError as e:
            logger.exception(f"Could not drain {hostname}\ncommand: {e.cmd}\noutput:\n{e.output}")
            raise
        logger.info(f"{hostname} draining")

    def requeue_jobs(self, hostname, reason):
        logger.info(f"Requeuing jobs on {hostname} because {reason}")
        try:
            # Not executing untrusted input.
            lines = subprocess.check_output([f"{self.config['SLURM_ROOT']}/bin/squeue", '--noheader', '--format=%A', f"--nodelist={hostname}"], stderr=subprocess.STDOUT, encoding='UTF-8') # nosec
        except subprocess.CalledProcessError as e:
            logger.exception(f"Could not get list of jobs\ncommand: {e.cmd}\noutput:\n{e.output}")
            raise
        logger.info(f"Jobs running on {hostname}:\n{lines}")
        jobs = lines.split('\n')
        if jobs[-1] == '': jobs = jobs[0:-1]
        logger.info(f"{len(jobs)} jobs")
        if len(jobs):
            joblist = ','.join(jobs)
            logger.info(f"Requeueing {joblist}")
            try:
                # Not executing untrusted input.
                subprocess.run([f"{self.config['SLURM_ROOT']}/bin/scontrol", 'requeue', f"{joblist}", f"reason='{reason}'"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='UTF-8') # nosec
            except subprocess.CalledProcessError as e:
                logger.exception(f"Could not requeue jobs\ncommand: {e.cmd}\noutput:\n{e.output}")
                raise

    def power_down_node(self, hostname, reason):
        logger.info(f"Powering down {hostname}")
        try:
            # Not executing untrusted input.
            subprocess.run([f"{self.config['SLURM_ROOT']}/bin/scontrol", 'update', f"nodename={hostname}", 'state=POWER_DOWN', f"reason='{reason}'"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='UTF-8') # nosec
        except subprocess.CalledProcessError as e:
            logger.exception(f"Could not power down {hostname}\ncommand: {e.cmd}\noutput:\n{e.output}")
            raise
        logger.info(f"Powered down {hostname}")

    def mark_node_down(self, hostname, reason):
        try:
            # Mark the node as draining so new or requeued jobs don't land on it.
            self.drain(hostname, reason)

            # If ICE then mark all powered down nodes of the same instance type as down so that jobs don't get scheduled on them.
            if reason == 'InsufficientInstanceCapacity':
                self.mark_ice_nodes_down(hostname, reason)

            # Requeue jobs on the node before marking it down so the jobs don't fail
            self.requeue_jobs(hostname, reason)

            # Mark the node down
            try:
                # Not executing untrusted input.
                lines = subprocess.check_output([f"{self.config['SLURM_ROOT']}/bin/scontrol", 'update', f'nodename={hostname}', 'state=DOWN', f"reason='{reason}'"], stderr=subprocess.STDOUT, encoding='UTF-8') # nosec
            except subprocess.CalledProcessError as e:
                logger.exception(f"scontrol failed:\ncommand: {e.cmd}\noutput:\n{e.output}")
                raise

            # Power down the node
            self.power_down_node(hostname, reason)
        except Exception:
            # This error isn't fatal so publish the error to CloudWatch and continue.
            logger.exception("Unhandled exception while marking {} down with reason={}".format(hostname, reason))
            self.publish_cw_metrics(self.CW_UNHANDLED_MARK_NODE_DOWN_EXCEPTION, 1, [])

    def mark_ice_nodes_down(self, hostname, reason):
        instance_type_hostlist = '-'.join(hostname.split('-')[0:-1]) + '-[0-9999]'
        logger.info(f"Finding POWERED_DOWN nodes in {instance_type_hostlist}")
        powered_down_nodes = self.get_powered_down_nodes(instance_type_hostlist)

        if not powered_down_nodes:
            logger.info(f"None of {instance_type_hostlist} are powered down")
        else:
            try:
                powered_down_nodes.remove(hostname)
            except:
                logger.exception("Failed to remove {hostname} from powered_down_nodes")
            if powered_down_nodes:
                powered_down_hostlist = hostlist.collect_hostlist(powered_down_nodes)
                logger.info(f"Marking {powered_down_hostlist} DOWN because of {reason}")
                try:
                    # Not executing untrusted input.
                    lines = subprocess.check_output([f"{self.config['SLURM_ROOT']}/bin/scontrol", 'update', f'nodename={powered_down_hostlist}', 'state=DOWN', f"reason='{reason}'"], stderr=subprocess.STDOUT, encoding='UTF-8') # nosec
                except subprocess.CalledProcessError as e:
                    logger.exception(f"scontrol failed:\ncommand: {e.cmd}\noutput:\n{e.output}")
                    raise

    def get_powered_down_nodes(self, nodelist):
        try:
            # Not executing untrusted input.
            lines = subprocess.check_output([f"{self.config['SLURM_ROOT']}/bin/sinfo", '-p', 'all', '--noheader', '-t', 'power_down,powering_down,powered_down', '-o', "%N %T", '-n', f"{nodelist}"], stderr=subprocess.STDOUT, encoding='UTF-8') # nosec
        except subprocess.CalledProcessError as e:
            logger.exception(f"sinfo failed:\ncommand: {e.cmd}\noutput:\n{e.output}")
            raise
        nodes = []
        for line in lines.split('\n'):
            if not line: continue
            nodelist, state = line.split()
            nodes += hostlist.expand_hostlist(nodelist)
        return sorted(nodes)

    def create_node_conf(self):
        try:
            global logger
            logger_formatter = logging.Formatter('%(levelname)s:%(asctime)s: %(message)s')
            logger_streamHandler = logging.StreamHandler()
            logger_streamHandler.setFormatter(logger_formatter)
            logger.addHandler(logger_streamHandler)
            logger.setLevel(logging.INFO)

            self.parser = argparse.ArgumentParser("Create SLURM node config from EC2 instance metadata")
            self.parser.add_argument('--config-file', default=False, help="YAML file with instance families and types to include/exclude")
            self.parser.add_argument('--output-file', '-o', required=True, help="Output file")
            self.parser.add_argument('--debug', '-d', action='count', default=False, help="Enable debug messages")
            self.args = self.parser.parse_args()

            if self.args.debug:
                logger.setLevel(logging.DEBUG)
                logger.debug(f"Debugging level {self.args.debug}")

            if self.args.config_file:
                instance_config = yaml.load(open(self.args.config_file, 'r').read(), Loader=yaml.SafeLoader)
            else:
                instance_config = {
                    'UseSpot': True,
                    'DefaultPartition': 'CentOS_7_x86_64',
                    'NodesPerInstanceType': 10,
                    'BaseOsArchitecture': {
                        'AlmaLinux': {8: ['x86_64', 'arm64']},
                        'CentOS': {
                            '7': ['x86_64'],
                            '8': ['x86_64', 'arm64']
                            },
                        'Amazon': {'2': ['x86_64', 'arm64']},
                        'RedHat': {
                            '7': ['x86_64'],
                            '8': ['x86_64', 'arm64']
                            },
                        'Rocky': {8: ['x86_64', 'arm64']},
                    },
                    'Include': {
                        'MaxSizeOnly': False,
                        'InstanceFamilies': [
                            't3',
                            't3a',
                            't4g',
                        ],
                        'InstanceTypes': []
                    },
                    'Exclude': {
                        'InstanceFamilies': [
                            'a1',   # Graviton 1
                            'c4',   # Replaced by c5
                            'd2',   # SSD optimized
                            'g3',   # Replaced by g4
                            'g3s',  # Replaced by g4
                            'h1',   # SSD optimized
                            'i3',   # SSD optimized
                            'i3en', # SSD optimized
                            'm4',   # Replaced by m5
                            'p2',   # Replaced by p3
                            'p3',
                            'p3dn',
                            'r4',   # Replaced by r5
                            't2',   # Replaced by t3
                            'u',
                            'x1',
                            'x1e'
                        ],
                        'InstanceTypes': []
                    },
                    'AlwaysOnNodes': [],
                    'AlwaysOnPartitions': []
                }

            # Check for required fields
            if 'DefaultPartition' not in instance_config:
                raise ValueError(f"InstanceConfig missing DefaultPartition")
            if 'BaseOsArchitecture' not in instance_config:
                raise ValueError(f"InstanceConfig missing BaseOsArchitecture")

            # Set defaults for missing fields
            if 'UseSpot' not in instance_config:
                instance_config['UseSpot'] = True
            if 'NodesPerInstanceType' not in instance_config:
                instance_config['NodesPerInstanceType'] = 10
            if 'Include' not in instance_config:
                instance_config['Include'] = {}
            if 'MaxSizeOnly' not in instance_config['Include']:
                instance_config['Include']['MaxSizeOnly'] = 10

            instance_types = self.get_instance_types_from_instance_config(instance_config)
            logger.debug(f"instance_types:\n{pp.pformat(instance_types)}")

            region_name = self.get_region_name(self.config['region'])

            self.pricing_client = boto3.client('pricing')
            for instanceType in sorted(instance_types):
                logger.debug("instanceType: {}".format(instanceType))
                os = 'Linux'
                pricing_filter = [
                    {'Field': 'ServiceCode', 'Value': 'AmazonEC2', 'Type': 'TERM_MATCH'},
                    {'Field': 'instanceType', 'Value': instanceType, 'Type': 'TERM_MATCH'},
                    {'Field': 'tenancy', 'Value': 'shared', 'Type': 'TERM_MATCH'},
                    {'Field': 'preInstalledSw', 'Value': 'NA', 'Type': 'TERM_MATCH'},
                    {'Field': 'location', 'Value': region_name, 'Type': 'TERM_MATCH'},
                    {'Field': 'operatingSystem', 'Value': os, 'Type': 'TERM_MATCH'},
                    {'Field': 'capacitystatus', 'Value': 'Used', 'Type': 'TERM_MATCH'},
                ]
                kwargs = {
                    'ServiceCode': 'AmazonEC2',
                    'Filters': pricing_filter
                }
                priceLists = self.pricing_get_products(ServiceCode='AmazonEC2', Filters=pricing_filter)['PriceList']
                if self.args.debug > 2:
                    logger.debug("{} priceLists".format(len(priceLists)))
                if len(priceLists) != 1:
                    raise RuntimeError("Number of PriceLists != 1 for {}".format(instanceType))
                priceList = json.loads(priceLists[0])
                if self.args.debug > 2:
                    logger.debug("pricelist:\n{}".format(pp.pformat(priceList)))
                onDemandTerms = priceList['terms']['OnDemand']
                if self.args.debug > 2:
                    logger.debug("onDemandTerms:\n{}".format(pp.pformat(onDemandTerms)))
                id1 = list(onDemandTerms)[0]
                if self.args.debug > 2:
                    logger.debug("id1:{}".format(pp.pformat(id1)))
                id2 = list(onDemandTerms[id1]['priceDimensions'])[0]
                if self.args.debug > 2:
                    logger.debug("id2:{}".format(pp.pformat(id2)))
                unit = onDemandTerms[id1]['priceDimensions'][id2]['unit']
                if unit != 'Hrs':
                    raise RuntimeError("Unknown pricing unit: {}".format(unit))
                if self.args.debug > 2:
                    logger.debug("unit: {}".format(unit))
                currency = list(onDemandTerms[id1]['priceDimensions'][id2]['pricePerUnit'])[0]
                if currency != 'USD':
                    raise RuntimeError("Unknown currency: {}".format(currency))
                price = onDemandTerms[id1]['priceDimensions'][id2]['pricePerUnit']['USD']
                if self.args.debug > 2:
                    logger.debug("price: {}".format(price))

                self.instance_type_info[instanceType]['price'] = price
                if self.args.debug > 2:
                    logger.debug(f"{instanceType} info:\n{pp.pformat(self.instance_type_info[instanceType])}")

            architecture_prefix_map = {
                'x86_64': 'x86',
                'arm64':  'arm',
            }
            node_sets = {}
            for distribution, distribution_dict in instance_config['BaseOsArchitecture'].items():
                logger.debug(distribution)
                logger.debug(f"distribution_dict:\n{pp.pformat(distribution_dict)}")
                os_prefix = distribution_to_prefix_map[distribution]
                for distribution_major_version, architectures in distribution_dict.items():
                    for architecture in architectures:
                        node_set = f"{distribution}_{distribution_major_version}_{architecture}"
                        node_sets[node_set] = {'nodes': [], 'node_names': []}
                        if instance_config['UseSpot']:
                            spot_node_set = f"{node_set}_spot"
                            node_sets[spot_node_set] = {'nodes': [], 'node_names': []}
                        architecture_prefix = architecture_prefix_map[architecture]
                        partitionName = f"{distribution}_{distribution_major_version}_{architecture}"
                        for instanceType in sorted(instance_types):
                            if self.instance_type_info[instanceType]['architecture'] != architecture:
                                continue
                            logger.debug(f"{pp.pformat(self.instance_type_info[instanceType])}")
                            instance_family = self.get_instance_family(instanceType)
                            short_instance_size = self.get_short_instance_size(instanceType)
                            max_node_index = instance_config['NodesPerInstanceType'] - 1

                            node = f"{os_prefix}{distribution_major_version}-{architecture_prefix}-{instance_family}-{short_instance_size}-[0-{max_node_index}]"
                            node_sets[node_set]['nodes'].append(node)
                            if instance_config['UseSpot']:
                                spot_node = f"{os_prefix}{distribution_major_version}-{architecture_prefix}-{instance_family}-{short_instance_size}-sp-[0-{max_node_index}]"
                                node_sets[spot_node_set]['nodes'].append(spot_node)

                            coreCount = self.instance_type_info[instanceType]['CoreCount']
                            realMemory = self.instance_type_info[instanceType]['MemoryInMiB']
                            if realMemory > 650:
                                realMemory -= 650
                            realMemory = int(realMemory * 0.95)
                            clockSpeedInGHz = self.instance_type_info[instanceType]['SustainedClockSpeedInGhz']
                            featureList = f"{os_prefix}{distribution_major_version},{partitionName},{instance_family},{instanceType},{architecture},GHz:{clockSpeedInGHz}"
                            if self.instance_type_info[instanceType]['SSDCount']:
                                featureList += ",ssd"
                            price = self.instance_type_info[instanceType]['price']
                            weight = int(float(price) * 10000)
                            node_name = "NodeName={:30s} CPUs={:2s} RealMemory={:7s} Feature={:65s} Weight={}".format(
                                node, str(coreCount), str(realMemory), featureList, weight)
                            node_sets[node_set]['node_names'].append(node_name)

                            if instance_config['UseSpot']:
                                spot_feature_list = f"{featureList},spot"
                                weight = int(weight / 10)
                                spot_node_name = "NodeName={:30s} CPUs={:2s} RealMemory={:7s} Feature={:65s} Weight={}".format(
                                    spot_node, str(coreCount), str(realMemory), spot_feature_list, weight)
                                node_sets[spot_node_set]['node_names'].append(spot_node_name)

            fh = open(self.args.output_file, 'w')
            print(dedent('''\
                #
                # COMPUTE NODES
                #
                # Create a NodeName for each os and instance type.
                # The NodeNames can then be added to partitions.
                #
                # Weight is $/hour * 10,000
                #
                # OS is chosen by partition, not weight
                #
                # Cloud nodes that get powered up and down
                # Scripts assume the following NodeName pattern: os-instancetype-index
                #   os: al2 | centos7 | rhel7
                #   instancetype: '.' replaced with '_'
                # Gres: Generic resources
                # Jobs will be scheduled on the node with the lowest weight that meets the requirements.
                #   * Lower weight == higher priority
                #   * Give more expensive instances higher weights.
                #   * RHEL7 instances are billed per hour so they should have the highest weight.
                NodeName=Default State=CLOUD'''), file=fh)

            for node_set in node_sets:
                print(f"\n# {node_set}", file=fh)
                for node_name in node_sets[node_set]['node_names']:
                    print(node_name, file=fh)

            print(dedent('''\
                #
                # NodeSets:
                # Used to group nodes to simplify partition definition.
                #
                '''), file=fh)
            for node_set in node_sets:
                print(dedent(f"""\
                    #
                    # {node_set} NodeSet
                    #
                    NodeSet={node_set}_nodes Nodes=\\"""), file=fh)
                print(',\\\n'.join(node_sets[node_set]['nodes']), file=fh)

            print(dedent('''\
                #
                # Partitions: Slurm's version of queues
                # Selected by -p option
                #
                # Set defaults for partitions
                #
                PartitionName=Default MaxTime=INFINITE State=UP Default=NO PriorityTier=1
                '''), file=fh)

            node_set_name = f"{instance_config['DefaultPartition']}_nodes"
            print(dedent(f"""\
                #
                # Batch Partition
                #
                # The is the default partition and includes all nodes from the 1st OS.
                #
                PartitionName=batch Default=YES Nodes=\\"""), file=fh)
            print(f"{node_set_name}", file=fh)

            print(dedent(f"""\
                #
                # Interactive Partition
                #
                # The interative partition has a high weight so that jobs in its queue will
                # have the highest scheduling priority so that they should start before
                # jobs in lower priority partitions.
                #
                # This is to allow interactive users to run small numbers of jobs that
                # require immediate results.
                #
                PartitionName=interactive Default=NO PriorityTier=10000 Nodes=\\"""), file=fh)
            print(f"{node_set_name}", file=fh)

            for node_set in node_sets:
                node_set_name = f"{node_set}_nodes"
                partitionName = node_set
                print(dedent(f"""\
                    #
                    # {partitionName} Partition
                    #
                    PartitionName={partitionName} Default=NO Nodes={node_set_name}"""), file=fh)

            print(dedent(f"""\
                #
                # All Partition
                #
                # Partition that includes all nodes.
                #
                # Note: This includes a heterogenous mix of nodes with different OSes and
                # architectures
                #
                PartitionName=all Default=NO PriorityTier=10000 Nodes=ALL"""), file=fh)

            if instance_config['AlwaysOnNodes']:
                print(dedent(f"""\
                    #
                    # Always on compute nodes
                    #
                    SuspendExcNodes=\\"""), file=fh)
                print(',\\\n'.join(instance_config['AlwaysOnNodes']), file=fh)

            if instance_config['AlwaysOnPartitions']:
                print(dedent(f"""\
                    #
                    # Always on partitions
                    #
                    SuspendExcParts=\\"""), file=fh)
                print(',\\\n'.join(instance_config['AlwaysOnPartitions']), file=fh)

            fh.close()
        except:
            logger.exception('Unhandled exception in SlurmPlugin.create_node_conf')
            self.publish_cw_metrics(self.CW_UNHANDLED_CREATE_NODE_CONF_EXCEPTION, 1, [])
            raise

    def get_instance_types_from_instance_config(self, instance_config):
        # Compile strings into regular expressions
        instance_config_re = {}
        for include_exclude in ['Include', 'Exclude']:
            instance_config_re[include_exclude] = {}
            for filter_type in ['InstanceFamilies', 'InstanceTypes']:
                instance_config_re[include_exclude][filter_type] = []
                for index, re_string in enumerate(instance_config.get(include_exclude, {}).get(filter_type, {})):
                    try:
                        instance_config_re[include_exclude][filter_type].append(re.compile(f"^{re_string}$"))
                    except:
                        logging.exception(f"Invalid regular expression for instance_config['{include_exclude}']['{filter_type}'] {re_string}")
                        exit(1)

        self.get_instance_type_info()

        instance_types = []

        for instance_family in sorted(self.instance_family_info.keys()):
            logger.debug(f"Considering {instance_family} family exclusions")
            exclude = False
            for instance_family_re in instance_config_re.get('Exclude', {}).get('InstanceFamilies', {}):
                if instance_family_re.match(instance_family):
                    logger.debug(f"Excluding {instance_family} family")
                    exclude = True
                    break
            if exclude:
                # Exclusions have precedence over inclusions so don't check instance type inclusions.
                continue
            logger.debug(f"{instance_family} family not excluded")

            # Check to see if instance family is explicitly included
            include_family = False
            if instance_config_re['Include']['InstanceFamilies']:
                logger.debug(f"Considering {instance_family} family inclusions")
                for instance_family_re in instance_config_re['Include']['InstanceFamilies']:
                    if instance_family_re.match(instance_family):
                        logger.debug(f"Including {instance_family} family")
                        include_family = True
                        break
                if not include_family:
                    logger.debug(f"{instance_family} family not included. Will check for instance type inclusions.")

            # Check the family's instance types for exclusion and inclusion. MaxSizeOnly is a type of exclusion.
            instance_family_info = self.instance_family_info[instance_family]
            for instance_type in instance_family_info['instance_types']:
                logger.debug(f"Checking {instance_type} for instance type exclusions")
                if instance_config.get('Include', {}).get('MaxSizeOnly', False) and instance_type != instance_family_info['MaxInstanceType']:
                    logger.debug(f"Excluding {instance_type} because not MaxInstanceType.")
                    continue
                exclude = False
                for instance_type_re in instance_config_re['Exclude']['InstanceTypes']:
                    if instance_type_re.match(instance_type):
                        logger.debug(f"Excluding {instance_type} because excluded")
                        exclude = True
                        break
                if exclude:
                    continue
                logger.debug(f"{instance_type} not excluded by instance type exclusions")

                # The instance type isn't explicitly excluded so check if it is included
                if include_family:
                    logger.debug(f"Including {instance_type} because {instance_family} family is included.")
                    instance_types.append(instance_type)
                    continue
                include = False
                for instance_type_re in instance_config_re['Include']['InstanceTypes']:
                    if instance_type_re.match(instance_type):
                        logger.debug(f"Including {instance_type}")
                        include = True
                        instance_types.append(instance_type)
                        break
                if not include:
                    logger.debug(f"Excluding {instance_type} because not included")
                    continue
        return sorted(instance_types)

    # Translate region code to region name
    def get_region_name(self, region_code):
        endpoint_file = resource_filename('botocore', 'data/endpoints.json')
        try:
            with open(endpoint_file, 'r') as f:
                data = json.load(f)
            return data['partitions'][0]['regions'][region_code]['description']
        except Exception:
            logger.exception("Couldn't get region name for {}".format(region_code))
            raise

    def publish_cw(self):
        global logger
        try:
            logger_formatter = logging.Formatter('%(levelname)s:%(asctime)s: %(message)s')
            logger_rotatingFileHandler = logging.handlers.RotatingFileHandler(filename='/var/log/slurm/cloudwatch.log', mode='a', maxBytes=1000000, backupCount=10)
            logger_rotatingFileHandler.setFormatter(logger_formatter)
            logger.addHandler(logger_rotatingFileHandler)
            logger.setLevel(logging.INFO)

            self.parser = argparse.ArgumentParser("SLURM suspend/resume plugin")
            self.parser.add_argument('--debug', '-d', action='count', default=False, help="Enable debug messages")
            self.args = self.parser.parse_args()

            if self.args.debug:
                logger_streamHandler = logging.StreamHandler()
                logger_streamHandler.setFormatter(logger_formatter)
                logger.addHandler(logger_streamHandler)
                logger.setLevel(logging.DEBUG)

            if not self.check_slurmctld():
                logger.error("check_slurmctld failed")
                self.publish_cw_metrics(self.CW_SLURM_PUBLISH_CW_FAILED, 1, [])
                return 1

            self.get_instance_type_info()
            self.get_hostinfo([])

            try:
                # Not executing untrusted input.
                lines = subprocess.check_output([f"{self.config['SLURM_ROOT']}/bin/squeue", '-o', '%T %y', '--noheader'], stderr=subprocess.STDOUT, encoding='UTF-8') # nosec
            except subprocess.CalledProcessError as e:
                logger.exception(f"squeue failed:\ncommand: {e.cmd}\noutput:\n{e.output}")
                raise
            # Lines are: "State Nice"
            # with a newline at the end
            jobs = [_.split() for _ in lines.split('\n') if _]
            # Gives us a list of lists [[state, nice]]
            jobs = [{'state': state, 'nice': nice} for state, nice in jobs]
            # Gives us a list of dicts [{state, nice}]
            num_jobs = len(jobs)
            logger.debug("Found {} jobs".format(num_jobs))
            counts = defaultdict()
            for job in jobs:
                for key, value in job.items():
                    count = counts.get(key)
                    if count:
                        counts[key] += Counter([value])
                    else:
                        counts[key] = Counter([value])
            self.publish_cw_metrics('JobCount', num_jobs, [{'Name': 'State', 'Value': 'all'}])
            for count in counts.keys():
                logger.debug("    {}: {}".format(count, counts[count]))
                for key, value in counts[count].items():
                    self.publish_cw_metrics('JobCount', value, [{'Name': count.capitalize(), 'Value': key}])

            try:
                # Not executing untrusted input.
                lines = subprocess.check_output([f"{self.config['SLURM_ROOT']}/bin/sinfo", '-o', '%T,%D', '--noheader'], stderr=subprocess.STDOUT, encoding='UTF-8') # nosec
            except subprocess.CalledProcessError as e:
                logger.exception(f"sinfo failed:\ncommand: {e.cmd}\noutput:\n{e.output}")
                raise
            node_states = lines.split()
            logger.debug(node_states)
            for node_state in node_states:
                (state, count) = node_state.split(',')
                logger.debug("Nodes in {:10s} state: {}".format(state, count))
                self.publish_cw_metrics('NodeState', int(count), [{'Name': 'State', 'Value': state}])

            # License usage
            try:
                # Not executing untrusted input.
                lines = subprocess.check_output([f"{self.config['SLURM_ROOT']}/bin/scontrol", '--oneline', 'show', 'lic'], stderr=subprocess.STDOUT, encoding='UTF-8') # nosec
            except subprocess.CalledProcessError as e:
                logger.exception(f"scontrol failed:\ncommand: {e.cmd}\noutput:\n{e.output}")
                raise
            logger.debug(pp.pformat(lines))
            license_lines = lines.split('\n')
            logger.debug(node_states)
            for license_line in license_lines:
                # LicenseName=VCSAMSCompiler_Net Total=610 Used=0 Free=610 Remote=no
                if not license_line: continue
                logger.debug(license_line)
                fields = license_line.split(' ')
                logger.debug(pp.pformat(fields))
                licenseName = fields[0].split('=')[1]
                total = fields[1].split('=')[1]
                used = fields[2].split('=')[1]
                logger.debug("Used {} of {}".format(used, licenseName))
                self.publish_cw_metrics('LicensesUsed', int(used), [{'Name': 'LicenseName', 'Value': licenseName}])
                self.publish_cw_metrics('LicensesTotal', int(total), [{'Name': 'LicenseName', 'Value': licenseName}])

        except:
            logger.exception('Unhandled exception in SlurmPlugin.publish_cw')
            self.publish_cw_metrics(self.CW_UNHANDLED_PUBLISH_CW_METRICS_EXCEPTION, 1, [])
            raise
        return 0

    @retry_ec2_throttling()
    def paginate(self, paginator, kwargs):
        result = paginator.paginate(**kwargs)
        return result

    @retry_ec2_throttling()
    def start_instances(self, kwargs):
        result = self.ec2.start_instances(**kwargs)
        return result

    @retry_ec2_throttling()
    def stop_instances(self, kwargs):
        result = self.ec2.stop_instances(**kwargs)
        return result

    @retry_ec2_throttling()
    def terminate_instances(self, kwargs):
        result = self.ec2.terminate_instances(**kwargs)
        return result

    @retry_ec2_throttling()
    def pricing_get_products(self, ServiceCode, Filters):
        result = self.pricing_client.get_products(ServiceCode=ServiceCode, Filters=Filters)
        return result
