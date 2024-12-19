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
Exostellar Infrastructure Optimizer has a bug where it is using IMDS v1.
In accounts where IMDS v2 is required XIO doesn't work because it can't fetch
instance metadata.

This lambda gets triggered by EC2 instance launches and sets IMDSV2 as optional
instead of required. This will allow XIO to query instance metadata.

It seems like there is a race condition in the instance userdata so I also had to modify the
following file on the EMS server:

/xcompute/slurm/bin/configure-xcompute-controller-node.sh

Added these lines at the top.

while ! curl http://169.254.169.254/ &> /dev/null; do
    echo "Waiting 1s for IMDS v1 to work"
    sleep 1
done
echo "IMDS v1 working"
'''
import boto3
import cfnresponse
import json
import logging
from os import environ as environ
from textwrap import dedent
from time import sleep

logger=logging.getLogger(__file__)
logger_formatter = logging.Formatter('%(levelname)s: %(message)s')
logger_streamHandler = logging.StreamHandler()
logger_streamHandler.setFormatter(logger_formatter)
logger.addHandler(logger_streamHandler)
logger.setLevel(logging.INFO)
logger.propagate = False

def lambda_handler(event, context):
    try:
        logger.info(f"event:\n{json.dumps(event)}")
        # logger.info(f"event:\n{json.dumps(event, indent=4)}")

        if event['detail'].get('errorCode', None) == 'Client.DryRunOperation':
            logger.info(f"DryRun")
            return

        if not event['detail'].get('responseElements', None):
            logger.info("No ResponseElements")
            return

        clusterName = environ['ClusterName']
        errorSnsTopicArn = environ['ErrorSnsTopicArn']
        vpcId = environ['VpcId']
        xio_controller_tags = json.loads(environ['XioControllerTags'])
        xio_worker_tags = json.loads(environ['XioWorkerTags'])

        ec2_client = boto3.client('ec2')

        for instanceSet in event['detail']['responseElements']['instancesSet']['items']:
            instance_vpc_id = instanceSet['vpcId']
            if instance_vpc_id != vpcId:
                continue
            instance_id = instanceSet['instanceId']
            kwargs = {
                'Filters': [
                    {
                        'Name': 'resource-id',
                        'Values': [instance_id]
                    }
                ]
            }
            tags = {}
            for response in ec2_client.get_paginator('describe_tags').paginate(**kwargs):
                for tag in response['Tags']:
                    tags[tag['Key']] = tag['Value']
            xio_controller = True
            xio_worker = True
            for xio_tag in xio_controller_tags:
                if xio_tag not in tags:
                    xio_controller = False
                    break
                if xio_controller_tags[xio_tag] != tags[xio_tag]:
                    xio_controller = False
                    break
            for xio_tag in xio_worker_tags:
                if xio_tag not in tags:
                    xio_controller = False
                    break
                if xio_worker_tags[xio_tag] != tags[xio_tag]:
                    xio_controller = False
                    break
            if not(xio_controller or xio_worker):
                continue
            logger.info(f"{instance_id} is an XIO instance")

            # Instance must be running or stopped to modify IMDSv2 option.
            instance_state = instanceSet['instanceState']['name']
            while instance_state in ['pending'] and instance_state != 'running':
                logger.info(f"{instance_id} is in pending state. Wait for it to get to running.")
                sleep(1)
                response = ec2_client.describe_instance_status(
                    InstanceIds = [instance_id],
                    IncludeAllInstances = True # By default only returns running instances
                )
                logger.info(f"response: {response}")
                instance_state = response['InstanceStatuses'][0]['InstanceState']['Name']
            if instance_state != 'running':
                continue

            logger.info(f"Setting IMDS HttpTokens to optional: {instance_id}")
            ec2_client.modify_instance_metadata_options(
                InstanceId = instance_id,
                HttpTokens = 'optional'
            )

        return

    except Exception as e:
        logger.exception(str(e))
        sns_client = boto3.client('sns')
        sns_client.publish(
            TopicArn = errorSnsTopicArn,
            Subject = f"{clusterName} XioDisableImdsv2 failed",
            Message = str(e)
        )
        logger.info(f"Published error to {errorSnsTopicArn}")
        raise
