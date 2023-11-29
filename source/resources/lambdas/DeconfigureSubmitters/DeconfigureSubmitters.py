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
Update the head node when the config assets hash changes.
'''
import boto3
import cfnresponse
import json
import logging
from os import environ as environ
import time

logger=logging.getLogger(__file__)
logger_formatter = logging.Formatter('%(levelname)s: %(message)s')
logger_streamHandler = logging.StreamHandler()
logger_streamHandler.setFormatter(logger_formatter)
logger.addHandler(logger_streamHandler)
logger.setLevel(logging.INFO)
logger.propagate = False

def lambda_handler(event, context):
    try:
        logger.info(f"event:\n{json.dumps(event, indent=4)}")
        cluster_name = None
        requestType = event['RequestType']
        properties = event['ResourceProperties']
        required_properties = [
            ]
        error_message = ""
        for property in required_properties:
            try:
                value = properties[property]
            except:
                error_message += f"Missing {property} property. "
        if error_message:
            logger.info(error_message)
            if requestType == 'Delete':
                cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=cluster_name)
                return
            else:
                raise KeyError(error_message)

        cluster_name = environ['ClusterName']
        cluster_region = environ['Region']
        environment_name = environ['RESEnvironmentName']
        logger.info(f"{requestType} request for {cluster_name} in {cluster_region}")

        if requestType != 'Delete':
            logger.info(f"Nothing to do for {requestType}")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=cluster_name)
            return

        logger.info(f"Deconfigure RES({environment_name}) submitters for {cluster_name} in {cluster_region}")

        ec2_client = boto3.client('ec2', region_name=cluster_region)
        describe_instances_paginator = ec2_client.get_paginator('describe_instances')
        describe_instances_iterator = describe_instances_paginator.paginate(
            Filters = [
                {'Name': 'tag:res:EnvironmentName', 'Values': [environment_name]},
                {'Name': 'tag:res:NodeType', 'Values': ['virtual-desktop-dcv-host']}
            ]
        )
        submitter_instance_ids = []
        reservation_index = 0
        for response in describe_instances_iterator:
            for reservation_info in response['Reservations']:
                logger.info(f"reservation[{reservation_index}]:")
                reservation_index += 1
                instance_index = 0
                for instance_info in reservation_info['Instances']:
                    logger.info(f"    instance[{instance_index}]:")
                    instance_index += 1
                    logger.info(f"        instance_id: {instance_info['InstanceId']}")
                    if instance_info['State']['Name'] != 'running':
                        logger.info(f"            Skipping because state = {instance_info['State']['Name']}")
                        continue
                    for tags in instance_info['Tags']:
                        logger.info(f"            {tags}")
                    submitter_instance_ids.append(instance_info['InstanceId'])
        logger.info(f"submitter_instance_ids: {submitter_instance_ids}")
        if not submitter_instance_ids:
            logger.info("No running submitters.")
            return

        ssm_client = boto3.client('ssm', region_name=cluster_region)
        commands = f"""
set -ex

if ! [ -e /opt/slurm/{cluster_name} ]; then
    echo "/opt/slurm/{cluster_name} doesn't exist"
fi
if ! mountpoint /opt/slurm/{cluster_name}; then
    echo "/opt/slurm/{cluster_name} is not a mountpoint"
    if [ -e /opt/slurm/{cluster_name} ]; then
        rmdir /opt/slurm/{cluster_name}
    fi
    exit 0
fi
echo "/opt/slurm/{cluster_name} is a mountpoint"

script="/opt/slurm/{cluster_name}/config/bin/submitter_deconfigure.sh"
if ! [ -e $script ]; then
    echo "$script doesn't exist"
    exit 1
fi

sudo $script

if mountpoint /opt/slurm/{cluster_name}; then
    sudo umount /opt/slurm/{cluster_name}
fi
if [ -e /opt/slurm/{cluster_name} ]; then
    rmdir /opt/slurm/{cluster_name}
fi
        """
        response = ssm_client.send_command(
            DocumentName = 'AWS-RunShellScript',
            InstanceIds = submitter_instance_ids,
            Parameters = {'commands': [commands]},
            Comment = f"Deconfigure {environment_name} submitters for {cluster_name}"
        )
        command_id = response['Command']['CommandId']
        logger.info(f"Sent SSM command {command_id}")

        # Wait for the command invocations to be made
        time.sleep(5)
        # Wait for the command to complete before returning so that the cluster resources aren't removed before the command completes.
        num_errors = 0
        for instance_id in submitter_instance_ids:
            command_complete = False
            while not command_complete:
                response = ssm_client.get_command_invocation(
                    CommandId = command_id,
                    InstanceId = instance_id
                )
                command_status = response['Status']
                if command_status in ['Success']:
                    logger.info(f"Command passed on {instance_id}")
                    break
                elif command_status in ['Cancelled', 'TimedOut', 'Failed', 'Cancelling']:
                    logger.error(f"Command {command_status} on {instance_id}")
                    num_errors += 1
                    break
                else:
                    logger.info(f"Command still running on {instance_id}")
                time.sleep(10)
        if num_errors:
            cfnresponse.send(event, context, cfnresponse.FAILED, {'error': f"Denconfigure command failed."}, physicalResourceId=cluster_name)
            return

    except Exception as e:
        logger.exception(str(e))
        cfnresponse.send(event, context, cfnresponse.FAILED, {'error': str(e)}, physicalResourceId=cluster_name)
        raise

    cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=cluster_name)
