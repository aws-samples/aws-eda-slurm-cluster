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
Call /opt/slurm/{{ClusterName}}/config/bin/on_head_node_updated.sh using ssm run command.
'''
import boto3
from textwrap import dedent
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
        external_login_nodes_config = json.loads(environ['ExternalLoginNodesConfigJson'])

        logger.info(f"Configure external login nodes for {cluster_name} in {cluster_region}")

        ec2_client = boto3.client('ec2', region_name=cluster_region)

        login_node_instance_ids = []
        for external_login_node_config in external_login_nodes_config:
            slurm_login_node_sg_id = external_login_node_config.get('SecurityGroupId', None)

            tags_message = ''
            describe_instances_kwargs = {
                'Filters': [
                    {'Name': 'instance-state-name', 'Values': ['running']}
                ]
            }
            for tag_dict in external_login_node_config['Tags']:
                tag = tag_dict['Key']
                values = tag_dict['Values']
                tags_message += f"\n{tag}: {values}"
                describe_instances_kwargs['Filters'].append(
                    {'Name': f"tag:{tag}", 'Values': values}
                )
            logger.info(f"Configure instances with the following tags as login nodes:{tags_message}")

            describe_instances_paginator = ec2_client.get_paginator('describe_instances')
            describe_instances_iterator = describe_instances_paginator.paginate(**describe_instances_kwargs)
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
                        instance_id = instance_info['InstanceId']
                        login_node_instance_ids.append(instance_id)
                        security_group_ids = []
                        for security_group_dict in instance_info['SecurityGroups']:
                            security_group_ids.append(security_group_dict['GroupId'])
                        if slurm_login_node_sg_id:
                            if slurm_login_node_sg_id not in security_group_ids:
                                # Attach the security group
                                logger.info(f"Attaching {slurm_login_node_sg_id} to {instance_id}.")
                                security_group_ids.append(slurm_login_node_sg_id)
                                ec2_client.modify_instance_attribute(InstanceId=instance_id, Groups=security_group_ids)
                            else:
                                logger.info(f"{slurm_login_node_sg_id} already attached to {instance_id}")

        if login_node_instance_ids:
            logger.info(f"Found {len(login_node_instance_ids)} login nodes. instance_ids:" + "\n".join(login_node_instance_ids))
        else:
            logger.info("No running login nodes.")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=cluster_name)
            return

        ssm_client = boto3.client('ssm', region_name=cluster_region)

        ssm_script = dedent(f"""
            set -ex

            if ! [ -e /opt/slurm/{cluster_name} ]; then
                sudo mkdir -p /opt/slurm/{cluster_name}
            fi
            if ! mountpoint /opt/slurm/{cluster_name} ; then
                sudo mount head_node.{cluster_name}.pcluster:/opt/slurm /opt/slurm/{cluster_name} || true
            fi

            script="/opt/slurm/{cluster_name}/config/bin/submitter_configure.sh"
            if ! [ -e $script ]; then
                echo "$script doesn't exist"
                exit 1
            fi

            sudo $script
            """)

        TIMEOUT_MINUTES = 90
        TIMEOUT_SECONDS = TIMEOUT_MINUTES * 60
        send_command_response = ssm_client.send_command(
            DocumentName = 'AWS-RunShellScript',
            InstanceIds = login_node_instance_ids,
            Parameters = {'commands': [ssm_script]},
            Comment = f"Configure external login nodes for {cluster_name}",
            TimeoutSeconds = TIMEOUT_SECONDS
        )
        logger.info(f"Sent SSM command {send_command_response['Command']['CommandId']}")

    except Exception as e:
        logger.exception(str(e))
        sns_client = boto3.client('sns')
        sns_client.publish(
            TopicArn = environ['ErrorSnsTopicArn'],
            Subject = f"{cluster_name} ConfigureRESSubmitters failed",
            Message = str(e)
        )
        logger.info(f"Published error to {environ['ErrorSnsTopicArn']}")
        raise
