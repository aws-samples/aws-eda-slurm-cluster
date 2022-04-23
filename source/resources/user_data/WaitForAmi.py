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

'''
Wait for AMI to be available and update SSM parameter
'''
import argparse
import boto3
import logging
from logging import handlers
from os import environ
from time import sleep

logger = logging.getLogger(__file__)
logger_formatter = logging.Formatter('%(levelname)s:%(asctime)s: %(message)s')
logger_rotatingFileHandler = logging.handlers.RotatingFileHandler(filename='/var/log/slurm/WaitForAmi.log', mode='a', maxBytes=1000000, backupCount=10)
logger_rotatingFileHandler.setFormatter(logger_formatter)
logger.addHandler(logger_rotatingFileHandler)
logger.setLevel(logging.INFO)
logger.propagate = False

def main():
    try:
        parser = argparse.ArgumentParser("Wait for AMI to be available.")
        parser.add_argument('--ami-id', required=True, help="AMI Id to wait for")
        parser.add_argument('--base-ssm-parameter', required=True, help="SSM Parameter to store the ami id in.")
        parser.add_argument('--instance-id', required=True, help="Instance ID that created the AMI.")
        parser.add_argument('--compute-regions', required=True, help="Comma separated list of compute regions")
        parser.add_argument('--debug', '-d', action='count', default=False, help="Enable debug messages")
        args = parser.parse_args()

        if args.debug:
            logger_streamHandler = logging.StreamHandler()
            logger_streamHandler.setFormatter(logger_formatter)
            logger.addHandler(logger_streamHandler)
            logger.setLevel(logging.DEBUG)
            logger.debug(f"Debugging level {args.debug}")

        logger.info(f"ami-id: {args.ami_id}")
        logger.info(f"base-ssm-parameter: {args.base_ssm_parameter}")
        logger.info(f"instance-id: {args.instance_id}")

        ec2_client = boto3.client('ec2')
        logger.info(f"Waiting for {args.ami_id} to be available.")
        while True:
            ami_info = ec2_client.describe_images(ImageIds=[args.ami_id])['Images'][0]
            state = ami_info['State']
            ami_name = ami_info['Name']
            logger.info(f"state={state}")
            if state == 'available':
                break
            sleep(60)
        ssm_parameter = f"{args.base_ssm_parameter}/{environ['AWS_DEFAULT_REGION']}"
        logger.info(f"Writing {args.ami_id} to {ssm_parameter}")
        ssm_client = boto3.client('ssm')
        ssm_client.put_parameter(Name=ssm_parameter, Type='String', Value=args.ami_id, Overwrite=True)

        # Copy AMI to remote regions
        main_region = environ['AWS_DEFAULT_REGION']
        compute_regions = args.compute_regions.split(',')
        remote_ami_ids = {}
        for region in compute_regions:
            if region == main_region:
                continue
            logger.info(f"Copying {args.ami_id} to {region}")
            ec2_client = boto3.client('ec2', region_name=region)
            remote_ami_ids[region] = ec2_client.copy_image(
                Name = f"{ami_name}",
                Encrypted = True,
                SourceImageId = args.ami_id,
                SourceRegion = main_region
            )['ImageId']
            logger.info(f"Created {remote_ami_ids[region]} in {region}")
        for region, remote_ami_id in remote_ami_ids.items():
            logger.info(f"Waiting for {remote_ami_id} to be available in {region}.")
            ec2_client = boto3.client('ec2', region_name=region)
            while True:
                state = ec2_client.describe_images(ImageIds=[remote_ami_id])['Images'][0]['State']
                logger.info(f"state={state}")
                if state == 'available':
                    break
                sleep(60)
            ssm_parameter = f"{args.base_ssm_parameter}/{region}"
            logger.info(f"Writing {remote_ami_id} to {ssm_parameter}")
            ssm_client.put_parameter(Name=ssm_parameter, Type='String', Value=remote_ami_id, Overwrite=True)

        logger.info(f"Stopping {args.instance_id}")

        ec2_client = boto3.client('ec2')
        ec2_client.stop_instances(InstanceIds=[args.instance_id])
    except Exception as e:
        logger.exception(str(e))
        exit(1)

if __name__ == '__main__':
    main()
