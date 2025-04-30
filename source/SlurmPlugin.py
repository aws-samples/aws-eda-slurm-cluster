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
import boto3
from botocore.exceptions import ClientError
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from EC2InstanceTypeInfoPkg.EC2InstanceTypeInfo import EC2InstanceTypeInfo
from functools import wraps
from isodate import parse_duration
from jinja2 import Template as Template
import json
import logging
from logging import error, info, warning
import os
from os import environ, path
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
from typing import List
import yaml

logger = logging.getLogger(__file__)
logger_formatter = logging.Formatter('%(levelname)s:%(asctime)s: %(message)s')
logger_streamHandler = logging.StreamHandler()
logger_streamHandler.setFormatter(logger_formatter)
logger.addHandler(logger_streamHandler)
logger.propagate = False
logger.setLevel(logging.INFO)

pp = pprint.PrettyPrinter(indent=4)

class SlurmPlugin:

    def __init__(self, slurm_config_file=f"/opt/slurm/config/slurm_config.json", region=None):
        if slurm_config_file:
            with open(slurm_config_file, 'r') as fh:
                self.config = json.load(fh)
            environ['AWS_DEFAULT_REGION'] = self.config['region']
        else:
            self.config = {}

        slurm_version_file = self.config.get('SlurmVersionFile', '')
        if slurm_version_file:
            with open(slurm_version_file, 'r') as fh:
                self.config.update(json.load(fh))

        az_info_file = self.config.get('AZInfoFile', '')
        if az_info_file and path.exists(az_info_file):
            with open(az_info_file, 'r') as fh:
                self.az_info = json.load(fh)
            logger.debug(f"self.az_info: {self.az_info}")
            self.az_ids = {}
            for az in self.az_info.keys():
                self.az_ids[self.az_info[az]['id']] = az
            logger.debug(f"self.az_ids: {self.az_ids}")
        else:
            self.az_info = {}
            self.az_ids = {}

        if region:
            self.config['region'] = region
            environ['AWS_DEFAULT_REGION'] = self.config['region']

        self.compute_regions = [self.config['region']]
        for az_dict in self.az_info.values():
            region = az_dict['region']
            if region not in self.compute_regions:
                self.compute_regions.append(region)
        self.compute_regions.sort()

        self.instance_types = None

        # Create all of the boto3 clients in one place so can make sure that all client api calls get throttling retries.
        # Create first so that can publish metrics for unhandled exceptions
        self.cw = boto3.client('cloudwatch')

        try:
            self.ssm_client = boto3.client('ssm')
            self.ec2 = {}
            self.ec2_describe_instances_paginator = {}
            self.sts_client = {}
            for region in self.compute_regions:
                self.ec2[region] = boto3.client('ec2', region_name=region)
                self.ec2_describe_instances_paginator[region] = self.ec2[region].get_paginator('describe_instances')
                self.sts_client[region] = boto3.client('sts', region_name=region)
        except:
            logger.exception('Unhandled exception in SlurmPlugin constructor')
            self.publish_cw_metrics(self.CW_UNHANDLED_PLUGIN_CONSTRUCTOR_EXCEPTION, 1, [])
            raise
        return

    def get_instance_type_and_family_info(self):
        logger.debug(f"get_instance_type_and_family_info()")
        eC2InstanceTypeInfo = EC2InstanceTypeInfo(self.compute_regions, get_savings_plans=False, json_filename=self.config['InstanceTypeInfoFile'])
        self.instance_type_and_family_info = eC2InstanceTypeInfo.instance_type_and_family_info

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

    def get_instance_families(self, region):
        return sorted(self.instance_type_and_family_info[region]['instance_families'].keys())

    def get_instance_families_info(self, region):
        return self.instance_type_and_family_info[region]['instance_families']

    def get_instance_family_info(self, region, instance_family):
        return self.instance_type_and_family_info[region]['instance_families'][instance_family]

    def get_instance_family_instance_types(self, region, instance_family):
        return self.get_instance_family_info(region, instance_family)['instance_types']

    def get_max_instance_type(self, region, instance_family):
        return self.instance_type_and_family_info[region]['instance_families'][instance_family]['MaxInstanceType']

    def get_instance_types(self, region):
        return sorted(self.instance_type_and_family_info[region]['instance_types'].keys())

    def get_instance_types_info(self, region):
        return self.instance_type_and_family_info[region]['instance_types']

    def get_instance_type_info(self, region, instance_type):
        return self.instance_type_and_family_info[region]['instance_types'][instance_type]

    def get_architecture(self, region, instance_type):
        return self.instance_type_and_family_info[region]['instance_types'][instance_type]['architecture']

    def get_physical_processor(self, region, instance_type):
        return self.instance_type_and_family_info[region]['instance_types'][instance_type]['physicalProcessor']

    def get_cpu_vendor(self, region, instance_type):
        physical_processor = self.get_physical_processor(region, instance_type)
        if 'AMD' in physical_processor:
            cpu_vendor = 'amd'
        elif 'Graviton' in physical_processor:
            cpu_vendor = 'aws'
        elif 'Intel' in physical_processor:
            cpu_vendor = 'intel'
        else:
            cpu_vendor = None
        return cpu_vendor

    def get_SustainedClockSpeedInGhz(self, region, instance_type):
        return self.instance_type_and_family_info[region]['instance_types'][instance_type]['SustainedClockSpeedInGhz']

    def get_CoreCount(self, region, instance_type):
        return self.instance_type_and_family_info[region]['instance_types'][instance_type]['DefaultCores']

    def get_DefaultThreadsPerCore(self, region, instance_type):
        return self.instance_type_and_family_info[region]['instance_types'][instance_type]['DefaultThreadsPerCore']

    def get_EfaSupported(self, region, instance_type):
        return self.instance_type_and_family_info[region]['instance_types'][instance_type]['EfaSupported']

    def get_MemoryInMiB(self, region, instance_type):
        return self.instance_type_and_family_info[region]['instance_types'][instance_type]['MemoryInMiB']

    def get_SSDCount(self, region, instance_type):
        return self.instance_type_and_family_info[region]['instance_types'][instance_type]['SSDCount']

    def get_SSDTotalSizeGB(self, region, instance_type):
        return self.instance_type_and_family_info[region]['instance_types'][instance_type]['SSDTotalSizeGB']

    def get_instance_types_from_instance_config(self, instance_config: dict, regions: List[str], instance_type_info: EC2InstanceTypeInfo) -> dict:
        '''
        Get instance types selected by the config file.

        Returns:
            dict: Dictionary of dictionary of instance types in each region. instance_types[region]{instance_types: {UseOnDemand: bool, UseSpot: bool, DisableSimultaneousMultithreading: bool}}
        '''
        instance_config = deepcopy(instance_config)

        default_instance_type_config = {
            'UseOnDemand': instance_config['UseOnDemand'],
            'UseSpot': instance_config['UseSpot'],
            'DisableSimultaneousMultithreading': instance_config['DisableSimultaneousMultithreading'],
            'EnableEfa': instance_config['EnableEfa'],
            'PlacementGroupName': instance_config.get('PlacementGroupName', None)
        }

        instance_types = {}
        for region in regions:
            # Compile strings into regular expressions
            instance_config_re = {}
            for include_exclude in ['Include', 'Exclude']:
                instance_config_re[include_exclude] = {}
                for filter_type in ['InstanceFamilies', 'InstanceTypes']:
                    if include_exclude == 'Include':
                        instance_config_re[include_exclude][filter_type] = {}
                    else:
                        instance_config_re[include_exclude][filter_type] = []
                    for index, re_item in enumerate(instance_config.get(include_exclude, {}).get(filter_type, {})):
                        if type(re_item) is str:
                            re_string = re_item
                            re_config = {}
                        else:
                            re_string = list(re_item.keys())[0]
                            re_config = re_item[re_string]
                        try:
                            compiled_re = re.compile(f"^{re_string}$")
                        except:
                            logger.exception(f"Invalid regular expression for instance_config['{include_exclude}']['{filter_type}'] {re_string}")
                            exit(1)
                        if include_exclude == 'Include':
                            instance_config_re[include_exclude][filter_type][re_string] = {
                                're': compiled_re,
                                'config': re_config
                            }
                        else:
                            instance_config_re[include_exclude][filter_type].append(compiled_re)

            region_instance_types = {}

            for instance_family in sorted(self.instance_type_and_family_info[region]['instance_families'].keys()):
                logger.debug(f"Considering {instance_family} family exclusions")
                exclude = False
                for instance_family_exclude_re in instance_config_re.get('Exclude', {}).get('InstanceFamilies', {}):
                    if instance_family_exclude_re.match(instance_family):
                        logger.debug(f"Excluding {instance_family} family")
                        exclude = True
                        break
                if exclude:
                    # Exclusions have precedence over inclusions so don't check instance type inclusions.
                    continue
                logger.debug(f"{instance_family} family not excluded")

                # Check to see if instance family is explicitly included
                include_instance_family = False
                if instance_config_re['Include']['InstanceFamilies']:
                    logger.debug(f"Considering {instance_family} family inclusions")
                    for instance_family_include_re_string in instance_config_re['Include']['InstanceFamilies']:
                        instance_family_include_re = instance_config_re['Include']['InstanceFamilies'][instance_family_include_re_string]['re']
                        if instance_family_include_re.match(instance_family):
                            logger.debug(f"Including {instance_family} family")
                            include_instance_family = True
                            instance_family_config = instance_config_re['Include']['InstanceFamilies'][instance_family_include_re_string]['config']
                            break
                if not include_instance_family:
                    logger.debug(f"{instance_family} family not included. Will check for instance type inclusions.")
                    instance_family_config = default_instance_type_config

                # Check the family's instance types for exclusion and inclusion. MaxSizeOnly is a type of exclusion.
                instance_family_info = self.instance_type_and_family_info[region]['instance_families'][instance_family]
                for instance_type in instance_family_info['instance_types']:
                    logger.debug(f"Checking {instance_type} for instance type exclusions")
                    if instance_config.get('Include', {}).get('MaxSizeOnly', False) and instance_type != instance_family_info['MaxInstanceType']:
                        logger.debug(f"Excluding {instance_type} because not MaxInstanceType.")
                        continue
                    exclude = False
                    for instance_type_exclude_re in instance_config_re['Exclude']['InstanceTypes']:
                        if instance_type_exclude_re.match(instance_type):
                            logger.debug(f"Excluding {instance_type} because instance type excluded")
                            exclude = True
                            break
                    if exclude:
                        continue
                    logger.debug(f"{instance_type} not excluded by instance type exclusions")

                    # The instance type isn't explicitly excluded so check if it is included

                    # Even if it is included because of the family, check for explicit instance type inclusion because the config may be different than for the family.
                    include_instance_type = False
                    instance_type_config = {}
                    #logger.info(f"instance_config_re:\n{json.dumps(instance_config_re, indent=4, default=lambda o: '<not serializable>')}")
                    for instance_type_re_string, instance_type_re_dict in instance_config_re['Include']['InstanceTypes'].items():
                        instance_type_re = instance_type_re_dict['re']
                        if instance_type_re.match(instance_type):
                            logger.debug(f"Including {instance_type} because explicitly included.")
                            include_instance_type = True
                            instance_type_config = instance_type_re_dict['config']
                            break

                    if include_instance_family:
                        logger.debug(f"Including {instance_type} because {instance_family} family is included.")

                    if not (include_instance_family or include_instance_type):
                        logger.debug(f"Excluding {instance_type} because not included")
                        continue

                    instance_type_config['UseOnDemand'] = instance_type_config.get('UseOnDemand', instance_family_config.get('UseOnDemand', default_instance_type_config['UseOnDemand']))
                    instance_type_config['UseSpot'] = instance_type_config.get('UseSpot', instance_family_config.get('UseSpot', default_instance_type_config['UseSpot']))
                    instance_type_config['DisableSimultaneousMultithreading'] = instance_type_config.get('DisableSimultaneousMultithreading', instance_family_config.get('DisableSimultaneousMultithreading', default_instance_type_config['DisableSimultaneousMultithreading']))
                    instance_type_config['EnableEfa'] = instance_type_config.get('EnableEfa', instance_family_config.get('EnableEfa', default_instance_type_config['EnableEfa']))
                    instance_type_config['PlacementGroupName'] = instance_type_config.get('PlacementGroupName', instance_family_config.get('PlacementGroupName', default_instance_type_config['PlacementGroupName']))

                    region_instance_types[instance_type] = instance_type_config

            instance_types[region] = region_instance_types
        return instance_types

    def get_region_name(self, region_code):
        '''
        Translate region code to region name
        '''
        endpoint_file = resource_filename('botocore', 'data/endpoints.json')
        try:
            with open(endpoint_file, 'r') as f:
                data = json.load(f)
            return data['partitions'][0]['regions'][region_code]['description']
        except Exception:
            logger.exception("Couldn't get region name for {}".format(region_code))
            raise
