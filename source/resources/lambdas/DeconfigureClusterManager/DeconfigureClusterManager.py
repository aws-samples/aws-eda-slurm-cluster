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

mount_dest=/opt/slurm/{cluster_name}

# Make sure that the cluster is still mounted and mount is accessible.
# If the cluster has already been deleted then the mount will be hung and we have to do manual cleanup.
if mount | grep " $mount_dest "; then
    echo "$mount_dest is mounted."
    if ! timeout 1s ls $mount_dest; then
        echo "Mount point ($mount_dest) is hung. Source may have already been deleted."
        timeout 5s sudo umount -lf $mount_dest
        timeout 1s rm -rf $mount_dest
    fi
fi

script="$mount_dest/config/bin/create_users_groups_json_deconfigure.sh"
if ! timeout 1s ls $script; then
    echo "$script doesn't exist or isn't accessible."
else
    sudo $script
fi

# Do manual cleanup just in case something above failed.

sudo grep -v " $mount_dest " /etc/fstab > /etc/fstab.new
if diff -q /etc/fstab /etc/fstab.new; then
    sudo rm -f /etc/fstab.new
else
    sudo cp /etc/fstab /etc/fstab.$(date '+%Y-%m-%d@%H:%M:%S~')
    sudo mv -f /etc/fstab.new /etc/fstab
fi

if timeout 1s mountpoint $mount_dest; then
    echo "$mount_dest is a mountpoint"
    sudo umount -lf $mount_dest
fi

if timeout 1s ls $mount_dest; then
    sudo rmdir $mount_dest
fi
        """
        logger.info(f"Submitting SSM command")
        response = ssm_client.send_command(
            DocumentName = 'AWS-RunShellScript',
            InstanceIds = [cluster_manager_instance_id],
            Parameters = {'commands': [commands]},
            Comment = f"Deconfigure {environment_name} cluster manager for {cluster_name}"
        )
        command_id = response['Command']['CommandId']
        logger.info(f"Sent SSM command {command_id}")

        # Wait for the command invocations to be made
        time.sleep(5)
        # Wait for the command to complete before returning so that the cluster resources aren't removed before the command completes.
        num_errors = 0
        MAX_WAIT_TIME = 13 * 60
        wait_time = 0
        instance_id = cluster_manager_instance_id
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
            if wait_time >= MAX_WAIT_TIME:
                logger.error(f"Timed out waiting for command completion.")
                num_errors += 1
                break
            time.sleep(10)
            wait_time += 10
        if num_errors:
            cfnresponse.send(event, context, cfnresponse.FAILED, {'error': f"Denconfigure command failed."}, physicalResourceId=cluster_name)
            return

    except Exception as e:
        logger.exception(str(e))
        cfnresponse.send(event, context, cfnresponse.FAILED, {'error': str(e)}, physicalResourceId=cluster_name)
        raise

    cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=cluster_name)
