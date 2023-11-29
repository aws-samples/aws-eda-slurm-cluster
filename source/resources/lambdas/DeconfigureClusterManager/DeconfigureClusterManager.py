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

        ec2_client = boto3.client('ec2', region_name=cluster_region)
        cluster_manager_info = ec2_client.describe_instances(
            Filters = [
                {'Name': 'tag:res:EnvironmentName', 'Values': [environment_name]},
                {'Name': 'tag:res:ModuleId', 'Values': ['cluster-manager']}
            ]
        )['Reservations'][0]['Instances'][0]
        cluster_manager_instance_id = cluster_manager_info['InstanceId']
        logger.info(f"cluster manager instance id: {cluster_manager_instance_id}")

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

script="/opt/slurm/{cluster_name}/config/bin/create_users_groups_json_deconfigure.sh"
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
        logger.info(f"Submitting SSM command")
        response = ssm_client.send_command(
            DocumentName = 'AWS-RunShellScript',
            InstanceIds = [cluster_manager_instance_id],
            Parameters = {'commands': [commands]},
            Comment = f"Deconfigure {environment_name} cluster manager for {cluster_name}"
        )
        logger.info(f"Sent SSM command {response['Command']['CommandId']}")

    except Exception as e:
        logger.exception(str(e))
        cfnresponse.send(event, context, cfnresponse.FAILED, {'error': str(e)}, physicalResourceId=cluster_name)
        raise

    cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=cluster_name)
