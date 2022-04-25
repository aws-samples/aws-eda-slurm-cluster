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
import json
import logging
from logging import error, info, warning, handlers
import os
import requests
from socket import gethostname
# Subprocess not being used to execute user supplied data
import subprocess # nosec
from subprocess import CalledProcessError # nosec
import sys
from time import sleep

logger = logging.getLogger(__file__)
logger_formatter = logging.Formatter('%(levelname)s:%(asctime)s: %(message)s')
logger_rotatingFileHandler = logging.handlers.RotatingFileHandler(filename='/var/log/slurm/spot_monitor.log', mode='a', maxBytes=1000000, backupCount=10)
logger_rotatingFileHandler.setFormatter(logger_formatter)
logger.addHandler(logger_rotatingFileHandler)
logger.setLevel(logging.INFO)

SLURM_ROOT = os.environ['SLURM_ROOT']
SCANCEL = f"{SLURM_ROOT}/bin/scancel"
SCONTROL = f"{SLURM_ROOT}/bin/scontrol"
SQUEUE = f"{SLURM_ROOT}/bin/squeue"
METADATA_URL = 'http://169.254.169.254/latest/meta-data/'
INSTANCE_LIFE_CYCLE_URL = 'http://169.254.169.254/latest/meta-data/instance-life-cycle'
SPOT_INSTANCE_ACTION_URL = 'http://169.254.169.254/latest/meta-data/spot/instance-action'
REBALANCE_RECOMMENDATION_URL = 'http://169.254.169.254/latest/meta-data/events/recommendations/rebalance'

cloudwatch_client = boto3.client("cloudwatch")

def main():
    global logger
    global logger_formatter

    # Put inside an infinite loop so will continue to run if there's an unhandled exception.
    while True:
        try:
            logger.info("Spot monitor started")

            parser = argparse.ArgumentParser("SLURM spot monitor")
            parser.add_argument('--debug', '-d', action='count', default=False, help="Enable debug messages")
            args = parser.parse_args()

            if args.debug:
                logger_streamHandler = logging.StreamHandler()
                logger_streamHandler.setFormatter(logger_formatter)
                logger.addHandler(logger_streamHandler)
                logger.setLevel(logging.DEBUG)

            hostname_fqdn = gethostname()
            hostname = hostname_fqdn.split('.')[0]
            logger.info(f"hostname: {hostname}")
            # Check to see if this is a spot instance
            r = requests.get(INSTANCE_LIFE_CYCLE_URL)
            if r.status_code == 200 and r.text != 'spot':
                logger.info(f"Not a spot instance. Going to sleep")
                while True:
                    sleep(1000000000)
            logger.info(f"{hostname} is a spot instance. Monitoring for spot termination.")

            rebalance_received = False
            while True:
                if not rebalance_received:
                    rebalance_request = requests.get(REBALANCE_RECOMMENDATION_URL)
                    logger.debug(f"rebalance_request rc={rebalance_request.status_code} message={rebalance_request.text}")
                    if rebalance_request.status_code == 200:
                        rebalance_received = True
                        logger.info(f"Spot rebalance recommendation received: {rebalance_request.text}")
                        message = json.loads(rebalance_request.text)
                        logger.info(str(message))
                        write_cw_metric(hostname, 'SpotRebalanceRecommendation')
                        logger.info(f"Draining {hostname}")
                        drain(hostname, 'SpotRebalanceRecommendation')
                spot_termination_notification_request = requests.get(SPOT_INSTANCE_ACTION_URL)
                logger.debug(f"spot_termination_notification_request rc={spot_termination_notification_request.status_code} message={spot_termination_notification_request.text}")
                if spot_termination_notification_request.status_code == 200:
                    logger.info(f"Spot termination notification received: {spot_termination_notification_request.text}")
                    message = json.loads(spot_termination_notification_request.text)
                    logger.info(str(message))
                    logger.info(f"Draining {hostname}")
                    drain(hostname, 'SpotTermination')
                    logger.info(f"Requeueing jobs on {hostname}")
                    requeue_jobs(hostname)
                    write_cw_metric(hostname, 'SpotTermination')
                    logger.info(f"Powering down {hostname}")
                    power_down(hostname, 'SpotTermination')
                    sys.exit(0)

                sleep(5)
        except SystemExit:
            pass
        except:
            logger.exception(f"Unhandled exception in spot_monitor. Restarting after 5 seconds.")
            sleep(5)

def write_cw_metric(hostname, event_name):
    logger.info(f"Writing {event_name} cloudwatch metric")
    try:
        cloudwatch_client.put_metric_data(
            Namespace='SLURM',
            MetricData=[
                {'MetricName': event_name, 'Value': 1, 'Unit': 'Count'}
            ]
        )
    except:
        logger.exception("Cloudwatch metric publish failed")

def drain(hostname, event_name):
    logger.info(f"Setting {hostname} to drain so new jobs do not run on it.")
    try:
        subprocess.check_output([SCONTROL, 'update', f"nodename={hostname}", 'state=DRAIN', f"reason='{event_name}'"], stderr=subprocess.STDOUT, encoding='UTF-8') # nosec
    except CalledProcessError as e:
        logger.exception(f"Could not drain {hostname}\ncommand: {e.cmd}\noutput:\n{e.output}")
    logger.info(f"{hostname} draining")

def requeue_jobs(hostname):
    logger.info(f"Requeuing jobs on {hostname}")
    try:
        lines = subprocess.check_output([SQUEUE, '--noheader', '--format=%A', f"--nodelist={hostname}"], stderr=subprocess.STDOUT, encoding='UTF-8') # nosec
    except CalledProcessError as e:
        logger.exception(f"Could not get list of jobs\ncommand: {e.cmd}\noutput:\n{e.output}")
    jobs = lines.split('\n')
    if jobs[-1] == '':
        jobs = jobs[0:-1]
    lines = '\n'.join(jobs)
    logger.info(f"{len(jobs)} jobs running on {hostname}:\n{lines}")
    for job in jobs:
        logger.info(f"Requeueing {job}")
        try:
            subprocess.check_output([SCONTROL, 'requeue', f"{job}"], stderr=subprocess.STDOUT, encoding='UTF-8') # nosec
        except CalledProcessError as e:
            logger.warning(f"Could not requeue {job}\ncommand: {e.cmd}\noutput:\n{e.output}")
            try:
                subprocess.check_output([SCANCEL, f"{job}"], stderr=subprocess.STDOUT, encoding='UTF-8') # nosec
            except CalledProcessError as e:
                logger.exception(f"Could not cancel {job}\ncommand: {e.cmd}\noutput:\n{e.output}")

def power_down(hostname, event_name):
    logger.info(f"Powering down {hostname}")
    try:
        subprocess.check_output([SCONTROL, 'update', f"nodename={hostname}", 'state=POWER_DOWN', "reason='spot termination'"], stderr=subprocess.STDOUT, encoding='UTF-8') # nosec
    except CalledProcessError as e:
        logger.exception(f"Could not power down {hostname}\ncommand: {e.cmd}\noutput:\n{e.output}")
    logger.info(f"Powered down {hostname}")

if __name__ == '__main__':
    main()
