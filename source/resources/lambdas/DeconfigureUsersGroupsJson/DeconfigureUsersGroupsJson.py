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
Deconfigure users and groups crontab using ssm run command.
'''
import boto3
import cfnresponse
import json
import logging
from os import environ as environ
from textwrap import dedent
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
        error_sns_topic_arn = environ['ErrorSnsTopicArn']
        cluster_region = environ['Region']
        domain_joined_instance_tags = json.loads(environ['DomainJoinedInstanceTagsJson'])

        logger.info(f"{requestType} request for {cluster_name} in {cluster_region}")

        if requestType != 'Delete':
            logger.info(f"Nothing to do for {requestType}")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=cluster_name)
            return

        tags_message = ''
        describe_instances_kwargs = {
            'Filters': [
                {'Name': 'instance-state-name', 'Values': ['running']}
            ]
        }
        for tag_dict in domain_joined_instance_tags:
            tag = tag_dict['Key']
            values = tag_dict['Values']
            tags_message += f"\n{tag}: {values}"
            describe_instances_kwargs['Filters'].append(
                {'Name': f"tag:{tag}", 'Values': values}
            )
        logger.info(f"Deconfigure update of /opt/slurm/{cluster_name}/config/users_groups.json from domain joined instance with following tags:{tags_message}")

        domain_joined_instance_id = None
        ec2_client = boto3.client('ec2', region_name=cluster_region)
        describe_instances_paginator = ec2_client.get_paginator('describe_instances')
        for describe_instances_response in describe_instances_paginator.paginate(**describe_instances_kwargs):
            for reservation_dict in describe_instances_response['Reservations']:
                domain_joined_instance_info = reservation_dict['Instances'][0]
                domain_joined_instance_id = domain_joined_instance_info['InstanceId']
                logger.info(f"Domain joined instance id: {domain_joined_instance_id}")
        if not domain_joined_instance_id:
            raise RuntimeError(f"No running instances found with tags:{tags_message}")

        ssm_client = boto3.client('ssm', region_name=cluster_region)
        commands = dedent(f"""set -ex

            script="/opt/aws-eda-slurm-cluster/{cluster_name}/bin/create_users_groups_json_deconfigure.sh"
            sudo $script
            """)
        logger.info(f"Submitting SSM command")
        send_command_response = ssm_client.send_command(
            DocumentName = 'AWS-RunShellScript',
            InstanceIds = [domain_joined_instance_id],
            Parameters = {'commands': [commands]},
            Comment = f"Deconfigure users and groups for {cluster_name}"
        )
        command_id = send_command_response['Command']['CommandId']
        logger.info(f"Sent SSM command {command_id}")

        # Wait for the command invocations to be made
        time.sleep(5)

        # Wait for the command to complete before returning so that the cluster resources aren't removed before the command completes.
        MAX_WAIT_TIME = 5 * 60
        DELAY = 10
        MAX_ATTEMPTS = int(MAX_WAIT_TIME / DELAY)
        logger.info(f"Waiting {MAX_WAIT_TIME} s for command {command_id} to complete.")
        waiter = ssm_client.get_waiter('command_executed')
        waiter.wait(
            CommandId=command_id,
            InstanceId=domain_joined_instance_id,
            WaiterConfig={
                'Delay': DELAY,
                'MaxAttempts': MAX_ATTEMPTS
            }
            )

        # Check the result of the command
        get_command_invocation_response = ssm_client.get_command_invocation(
            CommandId = command_id,
            InstanceId = domain_joined_instance_id
        )
        command_status = get_command_invocation_response['Status']
        if command_status in ['Success']:
            logger.info(f"Command passed on {domain_joined_instance_id}")
        else:
            logger.error(f"Command {command_status} on {domain_joined_instance_id}")
            cfnresponse.send(event, context, cfnresponse.FAILED, {'error': f"Deconfigure command failed."}, physicalResourceId=cluster_name)
            return

    except Exception as e:
        logger.exception(str(e))
        cfnresponse.send(event, context, cfnresponse.FAILED, {'error': str(e)}, physicalResourceId=cluster_name)
        sns_client = boto3.client('sns')
        sns_client.publish(
            TopicArn = error_sns_topic_arn,
            Subject = f"{cluster_name} DeconfigureRESUsersGroupsJson failed",
            Message = str(e)
        )
        logger.info(f"Published error to {environ['ErrorSnsTopicArn']}")
        raise

    cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=cluster_name)
