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

Some asset changes may cause a cluster update while others like a playbook will not.
First check to make sure that the cluster ins't already being updated.
If it is already being updated then don't need to do anything.
'''
import boto3
import cfnresponse
import json
import logging
from os import environ as environ
from textwrap import dedent

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
            'ParallelClusterConfigHash'
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
        logger.info(f"{requestType} request for {cluster_name} in {cluster_region}")
        logger.info(f"ParallelClusterConfigHash={properties['ParallelClusterConfigHash']}")

        if requestType == 'Delete':
            logger.info(f"Nothing to do for Delete")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=cluster_name)
            return
        if requestType == 'Create':
            logger.info(f"Nothing to do for Create")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=cluster_name)
            return

        # First check if the cluster is already being updated and return if it is.
        cfn_client = boto3.client("cloudformation", region_name=cluster_region)
        try:
            stack_info = cfn_client.describe_stacks(StackName=cluster_name)['Stacks'][0]
        except Exception as e:
            logger.info(f"ParallelCluster stack {cluster_name} doesn't exist.\n{e}")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=cluster_name)
            return
        stack_status = stack_info['StackStatus']
        logger.info(f"ParallelCluster stack {cluster_name} in {stack_status} state.")
        if stack_status in ['CREATE_IN_PROGRESS', 'UPDATE_IN_PROGRESS', 'UPDATE_COMPLETE_CLEANUP_IN_PROGRESS', 'UPDATE_ROLLBACK_IN_PROGRESS', 'UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS']:
            logger.warning(f"ParallelCluster stack {cluster_name} update already initiated.")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=cluster_name)
            return

        head_node_ip_address = None
        head_node_instance_id = None
        ec2_client = boto3.client('ec2', region_name=cluster_region)
        describe_instances_paginator = ec2_client.get_paginator('describe_instances')
        describe_instances_kwargs = {
            'Filters': [
                {'Name': 'tag:parallelcluster:cluster-name', 'Values': [cluster_name]},
                {'Name': 'tag:parallelcluster:node-type', 'Values': ['HeadNode']},
                {'Name': 'instance-state-name', 'Values': ['running']}
            ]
        }
        for describe_instances_response in describe_instances_paginator.paginate(**describe_instances_kwargs):
            for reservation_dict in describe_instances_response['Reservations']:
                if reservation_dict['Instances']:
                    head_node_info = reservation_dict['Instances'][0]
                    if 'PrivateIpAddress' in head_node_info:
                        head_node_ip_address = head_node_info['PrivateIpAddress']
                        head_node_instance_id = head_node_info['InstanceId']
                        break
        if not head_node_instance_id:
            # If the cluster hasn't deployed yet or didn't successfully deploy initially, then the head node might not exist.
            # This shouldn't cause the custom resource to fail.
            logger.info(f"No head node instance found.")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=cluster_name)
            return
        logger.info(f"head node instance id: {head_node_instance_id}")
        logger.info(f"head node ip address: {head_node_ip_address}")

        ssm_client = boto3.client('ssm', region_name=cluster_region)
        commands = f"""
set -ex

script="/opt/slurm/config/bin/on_head_node_updated.sh"
if ! [ -e $script ]; then
    echo "$script doesn't exist"
    exit 0
fi

sudo $script
        """
        send_command_response = ssm_client.send_command(
            DocumentName = 'AWS-RunShellScript',
            InstanceIds = [head_node_instance_id],
            Parameters = {'commands': [commands]},
            Comment = f"''Update head node of {cluster_name}({head_node_instance_id})"
        )
        command_id = send_command_response['Command']['CommandId']
        logger.info(f"Sent SSM command {command_id}")

        # If I wait then the stack creation or update won't finish until the command completes.
        # I like the idea that the stack waits for the update to complete.
        MAX_WAIT_TIME = 15 * 60
        DELAY = 5
        MAX_ATTEMPTS = int(MAX_WAIT_TIME / DELAY)
        waiter = ssm_client.get_waiter('command_executed')
        waiter.wait(
            CommandId=command_id,
            InstanceId=head_node_instance_id,
            WaiterConfig={
                'Delay': DELAY,
                'MaxAttempts': MAX_ATTEMPTS
            }
            )

        # I want the custom resource to be successful whether script passes or not so
        # don't need to check the return status.

    except Exception as e:
        logger.exception(str(e))
        cfnresponse.send(event, context, cfnresponse.FAILED, {'error': str(e)}, physicalResourceId=cluster_name)
        sns_client = boto3.client('sns')
        sns_client.publish(
            TopicArn = environ['ErrorSnsTopicArn'],
            Subject = f"{cluster_name} UpdateHeadNode failed",
            Message = str(e)
        )
        logger.info(f"Published error to {environ['ErrorSnsTopicArn']}")
        raise

    cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=cluster_name)
