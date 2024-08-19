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
Call /opt/slurm/{{ClusterName}}/config/bin/create_users_groups_json_configure.sh using ssm run command.
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
        res_environment_name = environ['RESEnvironmentName']
        res_domain_joined_instance_name        = environ['RESDomainJoinedInstanceName']
        res_domain_joined_instance_module_name = environ['RESDomainJoinedInstanceModuleName']
        res_domain_joined_instance_module_id   = environ['RESDomainJoinedInstanceModuleId']
        res_domain_joined_instance_node_type   = environ['RESDomainJoinedInstanceNodeType']
        slurm_login_node_sg_id = environ['SlurmLoginNodeSGId']
        logger.info(f"Configure update of /opt/slurm/{cluster_name}/config/users_groups.json from RES {res_environment_name} domain joined instance with following tags:\nName={res_domain_joined_instance_name}\nres:ModuleName={res_domain_joined_instance_module_name}\nres:ModuleId={res_domain_joined_instance_module_name}\nres:NodeType={res_domain_joined_instance_node_type}\nstate=running")

        domain_joined_instance_id = None
        domain_joined_instance_security_group_ids = []
        ec2_client = boto3.client('ec2', region_name=cluster_region)
        describe_instances_paginator = ec2_client.get_paginator('describe_instances')
        describe_instances_kwargs = {
            'Filters': [
                {'Name': 'tag:res:EnvironmentName', 'Values': [res_environment_name]},
                {'Name': 'tag:Name',           'Values': [res_domain_joined_instance_name]},
                {'Name': 'tag:res:ModuleName', 'Values': [res_domain_joined_instance_module_name]},
                {'Name': 'tag:res:ModuleId',   'Values': [res_domain_joined_instance_module_id]},
                {'Name': 'tag:res:NodeType',   'Values': [res_domain_joined_instance_node_type]},
                {'Name': 'instance-state-name', 'Values': ['running']}
            ]
        }
        for describe_instances_response in describe_instances_paginator.paginate(**describe_instances_kwargs):
            for reservation_dict in describe_instances_response['Reservations']:
                domain_joined_instance_info = reservation_dict['Instances'][0]
                domain_joined_instance_id = domain_joined_instance_info['InstanceId']
                logger.info(f"Domain joined instance id: {domain_joined_instance_id}")
                for security_group_dict in domain_joined_instance_info['SecurityGroups']:
                    domain_joined_instance_security_group_ids.append(security_group_dict['GroupId'])
        if not domain_joined_instance_id:
            raise RuntimeError(f"No running instances found with tags res:EnvironmentName={res_environment_name}, Name={res_domain_joined_instance_name}, res:ModuleName={res_domain_joined_instance_module_name}, res:ModuleId={res_domain_joined_instance_module_id}, res:NodeType={res_domain_joined_instance_node_type}")

        # Make sure that the RES login nodes have the required security group attached.
        if slurm_login_node_sg_id not in domain_joined_instance_security_group_ids:
            # Attach the security group
            logger.info(f"Attaching {slurm_login_node_sg_id} to {domain_joined_instance_id}.")
            domain_joined_instance_security_group_ids.append(slurm_login_node_sg_id)
            ec2_client.modify_instance_attribute(InstanceId=domain_joined_instance_id, Groups=domain_joined_instance_security_group_ids)
        else:
            logger.info(f"{slurm_login_node_sg_id} already attached to {domain_joined_instance_id}")

        ssm_client = boto3.client('ssm', region_name=cluster_region)
        commands = f"""
set -ex

if ! [ -e /opt/slurm/{cluster_name} ]; then
    sudo mkdir -p /opt/slurm/{cluster_name}
fi
if ! mountpoint /opt/slurm/{cluster_name} ; then
    timeout 5s sudo mount head_node.{cluster_name}.pcluster:/opt/slurm /opt/slurm/{cluster_name} || true
fi

script="/opt/slurm/{cluster_name}/config/bin/create_users_groups_json_configure.sh"
if ! [ -e $script ]; then
    echo "$script doesn't exist"
    exit 1
fi

sudo $script
        """
        send_command_response = ssm_client.send_command(
            DocumentName = 'AWS-RunShellScript',
            InstanceIds = [domain_joined_instance_id],
            Parameters = {'commands': [commands]},
            Comment = f"Configure {res_environment_name} users and groups for {cluster_name}",
            TimeoutSeconds = 5 * 60 # 5 minutes
        )
        command_id = send_command_response['Command']['CommandId']
        logger.info(f"Sent SSM command {command_id}")

        # Wait for SSM command to complete
        MAX_WAIT_TIME = 15 * 60
        DELAY = 10
        MAX_ATTEMPTS = int(MAX_WAIT_TIME / DELAY)
        waiter = ssm_client.get_waiter('command_executed')
        waiter.wait(
            CommandId=send_command_response['Command']['CommandId'],
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
            cfnresponse.send(event, context, cfnresponse.FAILED, {'error': f"Configure command failed."}, physicalResourceId=cluster_name)
            return

    except Exception as e:
        logger.exception(str(e))
        sns_client = boto3.client('sns')
        sns_client.publish(
            TopicArn = environ['ErrorSnsTopicArn'],
            Subject = f"{cluster_name} ConfigureRESUsersGroupsJson failed",
            Message = str(e)
        )
        logger.info(f"Published error to {environ['ErrorSnsTopicArn']}")
        raise
