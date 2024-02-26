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
Create an A record for the ParallelCluster head node.

This should be called by on_head_node_started.sh.
'''
import boto3
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

        cluster_name = environ['ClusterName']
        cluster_region = environ['Region']

        logger.info(f"Create head node A record for {cluster_name} in {cluster_region}")

        route53_client = boto3.client('route53', region_name=cluster_region)

        # Get the ParallelCluster hosted zone
        hosted_zone_name = f"{cluster_name}.pcluster."
        hosted_zone_id = None
        list_hosted_zones_paginator = route53_client.get_paginator('list_hosted_zones')
        for response in list_hosted_zones_paginator.paginate():
            for hosted_zone_info in response['HostedZones']:
                if hosted_zone_info['Name'] == hosted_zone_name:
                    hosted_zone_id = hosted_zone_info['Id']
                    logger.info(f"{hosted_zone_name} hosted zone id: {hosted_zone_id}")
                    break
            if hosted_zone_id:
                break
        if not hosted_zone_id:
            raise ValueError(f"No private hosted zone named {hosted_zone_name} found.")

        # Check to see if the A record already exists
        list_resource_record_sets_paginator = route53_client.get_paginator('list_resource_record_sets')
        list_resource_record_sets_iterator = list_resource_record_sets_paginator.paginate(HostedZoneId=hosted_zone_id)
        head_node_a_record_name = f"head_node.{hosted_zone_name}"
        for response in list_resource_record_sets_iterator:
            for resource_record_set_info in response['ResourceRecordSets']:
                if resource_record_set_info['Type'] != 'A':
                    continue
                if resource_record_set_info['Name'] == head_node_a_record_name:
                    logger.info(f"{head_node_a_record_name} A record already exists")
                    return

        logger.info(f"Creating {head_node_a_record_name} A record.")

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
                for instance_dict in reservation_dict['Instances']:
                    head_node_ip_address = instance_dict.get('PrivateIpAddress', None)
                    if head_node_ip_address:
                        head_node_instance_id = instance_dict['InstanceId']
        if not head_node_ip_address:
            raise ValueError(f"No head node private IP address found for {cluster_name}")
        logger.info(f"head node instance id: {head_node_instance_id}")
        logger.info(f"head node ip address: {head_node_ip_address}")

        route53_client.change_resource_record_sets(
            HostedZoneId = hosted_zone_id,
            ChangeBatch = {
                'Changes': [
                    {
                        'Action': 'CREATE',
                        'ResourceRecordSet': {
                            'Name': head_node_a_record_name,
                            'Type': 'A',
                            'ResourceRecords': [
                                {'Value': str(head_node_ip_address)}
                            ],
                            'TTL': 300,
                        }
                    }
                ]
            }
        )
        logger.info(f"Successfully created {head_node_a_record_name} A record")

    except Exception as e:
        logger.exception(str(e))
        sns_client = boto3.client('sns')
        sns_client.publish(
            TopicArn = environ['ErrorSnsTopicArn'],
            Subject = f"{cluster_name} CreateHeadNodeARecord failed",
            Message = str(e)
        )
        logger.info(f"Published error to {environ['ErrorSnsTopicArn']}")
        raise
