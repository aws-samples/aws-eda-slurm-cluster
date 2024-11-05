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

import boto3
from colored import fg, bg, attr
import ipaddress
import logging
import os
import pprint
import re
import sys

installer_path = "/".join(os.path.dirname(os.path.abspath(__file__)).split("/")[:-3])
sys.path.append(installer_path)

from prompt import get_input as get_input

logger = logging.getLogger(__file__)
logger_formatter = logging.Formatter('%(levelname)s: %(message)s')
logger_streamHandler = logging.StreamHandler()
logger_streamHandler.setFormatter(logger_formatter)
logger.addHandler(logger_streamHandler)
logger.propagate = False
logger.setLevel(logging.INFO)

pp = pprint.PrettyPrinter(indent=4)

class FindExistingResource:
    def __init__(self, region):
        self.region = region
        session = boto3.Session(region_name=self.region)
        self.ec2 = session.client("ec2")
        self.cloudformation = session.client("cloudformation")
        self.iam = session.client("iam")
        self.route53 = session.client("route53")
        self.install_parameters = {}
        self.sns = session.client("sns")

    def get_soca_stack_name(self, prompt, specified_value=''):
        try:
            stacks = {}
            for stack in self.cloudformation.list_stacks(
                    StackStatusFilter=[
                        'CREATE_COMPLETE',
                        'ROLLBACK_COMPLETE',
                        'UPDATE_COMPLETE',
                        'UPDATE_ROLLBACK_COMPLETE',
                        'IMPORT_COMPLETE',
                        'IMPORT_ROLLBACK_COMPLETE'
                    ]
                )["StackSummaries"]:
                stack_name = stack['StackName']
                if stack_name == specified_value:
                    return {'success': True, 'message': stack_name}
                if not re.match(r'^soca-[^-]+$', stack_name):
                    continue
                stack_id = stack['StackId']
                stack_status = stack['StackStatus']
                stacks[stack_name] = stack_status
            sorted_stacks = {}
            count = 1
            for stack_name in sorted(stacks):
                stack_status = stacks[stack_name]
                sorted_stacks[count] = [stack_name, stack_status]
                count += 1
            for index in sorted(sorted_stacks):
                stack_name = sorted_stacks[index][0]
                stack_status = sorted_stacks[index][1]
                print("    {:2} > {:20} {}".format(index, stack_name, stack_status))
            allowed_choices = list(sorted_stacks.keys())
            choice = get_input(prompt, None, allowed_choices, int)
            return {"success": True, "message": sorted_stacks[choice][0]}

        except Exception as err:
            return {"success": False, "message": str(err)}

    def check_keypair(self, specified_value=''):
        try:
            key_pairs = []
            for key_pair in self.ec2.describe_key_pairs()["KeyPairs"]:
                key_name = key_pair['KeyName']
                if key_name == specified_value:
                    return True
                key_pairs.append(key_name)
            print(f"Invalid keypair: {specified_value}\nValid values: {key_pairs}")
            return False
        except:
            return False

    def get_keypair(self, config_key, config_value, args_value, prompt):
        if args_value:
            if config_value:
                print(f"{config_key} overridden on command line from {config_value} to {args_value}")
            specified_value = args_value
        elif config_value:
            specified_value = config_value
        else:
            specified_value = ''
        key_pairs = []
        for key_pair in self.ec2.describe_key_pairs()["KeyPairs"]:
            key_name = key_pair['KeyName']
            if key_name == specified_value:
                return key_name
            key_pairs.append(key_name)
        if specified_value:
            msg = f"{fg('red')}Invalid keypair: {specified_value}\nValid values: {key_pairs}{attr('reset')}"
            if prompt:
                print(f'\n{msg}')
            else:
                raise ValueError(msg)
        options = {}
        count = 1
        for key_pair in sorted(key_pairs):
            options[count] = key_pair
            count += 1
        print(f"\nChoose the EC2 KeyPair")
        for option in sorted(options):
            print("    {:2} > {}".format(option, options[option]))
        allowed_choices = list(options.keys())
        choice = get_input(f"Select a KeyPair:", None, allowed_choices, int)
        return options[choice]

    def check_res_environment_name(self, config_key, res_environment_name, config) -> bool:
        try:
            res_stack_name = None
            stacks = {}
            for stack_dict in self.cloudformation.list_stacks(
                    StackStatusFilter=[
                        'CREATE_COMPLETE',
                        'ROLLBACK_COMPLETE',
                        'UPDATE_COMPLETE',
                        'UPDATE_ROLLBACK_COMPLETE',
                        'IMPORT_COMPLETE',
                        'IMPORT_ROLLBACK_COMPLETE'
                    ]
                )["StackSummaries"]:
                stack_name = stack_dict['StackName']
                if stack_name == res_environment_name:
                    res_stack_name = stack_dict['StackName']
                    # Don't break here so get all of the stack names
                stack_status = stack_dict['StackStatus']
                stacks[stack_name] = stack_status
            if not res_stack_name:
                message = f"CloudFormation RES stack named {res_environment_name} not found. Existing stacks:"
                for stack_name in sorted(stacks):
                    message += f"\n    {stack_name:32}: status={stacks[stack_name]}"
                raise ValueError(message)

            # Get VpcId, SubnetId from RES stack
            stack_parameters = self.cloudformation.describe_stacks(StackName=res_stack_name)['Stacks'][0]['Parameters']
            vpc_id = None
            subnet_ids = []
            for stack_parameter_dict in stack_parameters:
                stack_parameter_key = stack_parameter_dict['ParameterKey']
                if stack_parameter_key == 'VpcId':
                    vpc_id = stack_parameter_dict['ParameterValue']
                elif stack_parameter_key in ['PrivateSubnets', 'InfrastructureHostSubnets', 'VdiSubnets']:
                    subnet_ids += stack_parameter_dict['ParameterValue'].split(',')
            if not vpc_id:
                raise ValueError(f"VpcId parameter not found in {res_environment_name} RES stack.")
            if 'VpcId' in config and config['VpcId'] != vpc_id:
                raise ValueError(f"Config file VpcId={config['VpcId']} is not the same as RESEnvironmentName VpcId={vpc_id}.")
            logger.info(f"VpcId set to {vpc_id} by RESEnvironmentName.")
            config['VpcId'] = vpc_id
            if not subnet_ids:
                raise ValueError(f"PrivateSubnets, InfrastructureHostSubnets, or VdiSubnets parameters not found in {res_environment_name} RES stack.")
            if 'SubnetId' in config and config['SubnetId'] not in subnet_ids:
                raise ValueError(f"Config file SubnetId={config['SubnetId']} is not a RES private subnet. RES private subnets: {subnet_ids}.")
            if 'SubnetId' not in config:
                config['SubnetId'] = subnet_ids[0]
                logger.info(f"SubnetId set to {config['SubnetId']} by RESEnvironmentName.")

            return True
        except:
            raise
        return False

    def check_vpc_id(self, specified_vpc_id):
        try:
            vpcs = {}
            for page in self.ec2.get_paginator('describe_vpcs').paginate():
                for vpc in page['Vpcs']:
                    vpc_id = vpc['VpcId']
                    if specified_vpc_id == vpc_id:
                        return True
            return False
        except:
            return False

    def get_vpc_id(self, config_key, config_value, args_value, prompt):
        if args_value:
            if config_value:
                print(f"{config_key} overridden on command line from {config_value} to {args_value}")
            specified_value = args_value
        elif config_value:
            specified_value = config_value
        else:
            specified_value = ''
        try:
            vpcs = {}
            for page in self.ec2.get_paginator('describe_vpcs').paginate():
                for vpc in page['Vpcs']:
                    vpc_id = vpc['VpcId']
                    if specified_value == vpc_id:
                        return vpc_id
                    vpc_name = vpc_id
                    for tag in vpc.get('Tags', []):
                        key = tag['Key']
                        if key == 'Name':
                            vpc_name = tag['Value']
                    vpcs[vpc_name] = vpc_id
            if specified_value:
                msg = f"\n{fg('red')}Invalid {config_key}: {specified_value}\nValid values: {vpcs}{attr('reset')}"
                if prompt:
                    print(f'\n{msg}')
                else:
                    raise ValueError(msg)
            print(f"\nChoose a VPC")
            index = 1
            options = {}
            for vpc_name in sorted(vpcs.keys()):
                vpc_id = vpcs[vpc_name]
                print("    {:2} > {:18} {}".format(index, vpc_name, vpc_id))
                options[index] = vpc_id
                index += 1
            allowed_choices = sorted(options.keys())
            choice = get_input(f"Select the VPC:", None, allowed_choices, int)
            return options[choice]
        except Exception as err:
            raise

    def get_subnet_id(self, vpc_id, config_key, config_value, args_value, prompt):
        if args_value:
            if config_value:
                print(f"{config_key} overridden on command line from {config_value} to {args_value}")
            specified_value = args_value
        elif config_value:
            specified_value = config_value
        else:
            specified_value = ''
        try:
            subnets = {}
            for page in self.ec2.get_paginator('describe_subnets').paginate(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]):
                for subnet in page['Subnets']:
                    subnet_id = subnet['SubnetId']
                    if specified_value == subnet_id:
                        return subnet_id
                    subnet_name = subnet_id
                    for tag in subnet.get('Tags', []):
                        key = tag['Key']
                        if key == 'Name':
                            subnet_name = tag['Value']
                    subnets[subnet_name] = subnet_id
            if specified_value:
                msg = f"\n{fg('red')}Invalid {config_key}: {specified_value}\nValid values: {subnets}{attr('reset')}"
                if prompt:
                    print(f'\n{msg}')
                else:
                    raise ValueError(msg)
            print(f"\nChoose a Subnet (Optional):\nSelect 0 and the first private subnet in the VPC will be used:")
            index = 1
            options = {}
            for subnet_name in sorted(subnets.keys()):
                subnet_id = subnets[subnet_name]
                print("    {:2} > {:18} {}".format(index, subnet_name, subnet_id))
                options[index] = subnet_id
                index += 1
            print(f"    {0:2} > {'None':30} {''}")
            options[0] = None
            allowed_choices = sorted(options.keys()).append(0)
            choice = get_input(f"Select the Subnet:", None, allowed_choices, int)
            return options[choice]
        except Exception as err:
            raise

    def check_sns_topic_arn(self, specified_sns_topic_arn):
        try:
            for page in self.sns.get_paginator('list_topics').paginate():
                for topic_dict in page['Topics']:
                    sns_topic_arn = topic_dict['TopicArn']
                    if specified_sns_topic_arn == sns_topic_arn:
                        return True
            return False
        except:
            return False

    def get_sns_topic_arn(self, config_key, config_value, args_value, prompt):
        if args_value:
            if config_value:
                print(f"{config_key} overridden on command line from {config_value} to {args_value}")
            specified_value = args_value
            value_type = 'Command line'
        elif config_value:
            specified_value = config_value
            value_type = 'Config_file'
        else:
            specified_value = ''
        try:
            sns_topic_arns = {}
            for page in self.sns.get_paginator('list_topics').paginate():
                for topic_dict in page['Topics']:
                    sns_topic_arn = topic_dict['TopicArn']
                    if specified_value == sns_topic_arn:
                        return sns_topic_arn
                    sns_topic_name = sns_topic_arn.split(':')[-1]
                    sns_topic_arns[sns_topic_name] = sns_topic_arn
            if specified_value:
                # Value specified in config or on command line is invalid. Fail unless prompt is true
                msg_type = 'warning' if prompt else 'error'
                msg_color = 'yellow' if prompt else 'red'
                msg = f"{fg(msg_color)}{msg_type}: Invalid {value_type} value. {config_key}={specified_value}{attr('reset')}"
                if prompt:
                    print("\n{msg}")
                else:
                    raise ValueError(msg)
            if not sns_topic_arns:
                print("No SNS topics found. Create one if you would like to be notified of errors and rerun.")
                return ''
            index = 1
            options = {}
            print(f"\nChoose SNS Topic")
            for sns_topic_name in sorted(sns_topic_arns.keys()):
                sns_topic_arn = sns_topic_arns[sns_topic_name]
                print("    {:2} > {:30} {}".format(index, sns_topic_name, sns_topic_arn))
                options[index] = sns_topic_arn
                index += 1
            print(f"    {index:2} > {'None':30}")
            options[index] = ''
            index += 1
            allowed_choices = sorted(options.keys())
            choice = get_input(f"Choose the SNS Topic to use:", None, allowed_choices, int)
            return options[choice]
        except Exception as err:
            raise

    def get_external_login_node_security_groups(self, vpc_id, config_key, config_value, args_value, prompt):
        if args_value:
            if config_value:
                print(f"{config_key} overridden on command line from {config_value} to {args_value}")
            specified_value = args_value
        elif config_value:
            specified_value = config_value
        else:
            if not prompt:
                return None
            specified_value = {}
        try:
            security_group_ids = {} # sg-id: Name
            security_group_names = {} # Name: sg-id
            for page in self.ec2.get_paginator('describe_security_groups').paginate(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]):
                for security_group_dict in page['SecurityGroups']:
                    security_group_id = security_group_dict['GroupId']
                    security_group_name = security_group_dict['GroupName']
                    for tag in security_group_dict.get('Tags', []):
                        key = tag['Key']
                        if key == 'Name':
                            security_group_name = tag['Value']
                    security_group_ids[security_group_id] = security_group_name
                    # Make sure security group names are unique
                    index = 1
                    base_security_group_name = security_group_name
                    while security_group_name in security_group_names:
                        security_group_name = f"{base_security_group_name}{i}"
                    security_group_names[security_group_name] = security_group_id
            # Check specified values
            unchosen_security_group_names = security_group_names.copy()
            if specified_value:
                invalid_security_groups = {}
                num_errors = 0
                for security_group_name, security_group_id in specified_value.items():
                    if security_group_id in security_group_ids:
                        # Remove security groups that have already been selected
                        security_group_name = security_group_ids[security_group_id]
                        del unchosen_security_group_names[security_group_name]
                    else:
                        invalid_security_groups[security_group_name] = security_group_id
                if invalid_security_groups:
                    msg = f"{fg('red')}Invalid security groups specified in {config_key}:\n{pp.pformat(invalid_security_groups)}{attr('reset')}"
                    if prompt:
                        print(f'\n{msg}')
                    else:
                        raise ValueError(f"msg\nValid values:\n{pp.pformat(security_group_ids)}")
                    for security_group_name, security_group_id in invalid_security_groups.items():
                        del specified_value[security_group_name]
            if not prompt:
                return specified_value
            choice = 1
            while choice != 0:
                print(f"\nChoose External Login Node Security Groups")
                index = 0
                options = {}
                for security_group_name in sorted(unchosen_security_group_names.keys()):
                    index += 1
                    security_group_id = unchosen_security_group_names[security_group_name]
                    print(f"    {index:2} > {security_group_name:30} {security_group_id}")
                    options[index] = [security_group_name, security_group_id]
                clear_index = index + 1
                print(f"    {clear_index:2} > {'Clear':30} {''}")
                print(f"    {0:2} > {'Done':30} {''}")
                allowed_choices = sorted(options.keys()) + [clear_index, 0]
                if specified_value:
                    print(f"Selected security groups:")
                    for security_group_name in sorted(specified_value.keys()):
                        security_group_id = specified_value[security_group_name]
                        print(f"    {security_group_name:30}: {security_group_id}")
                else:
                    print("No security groups selected")
                choice = get_input(f"Choose Security Group or 0 when complete:", None, allowed_choices, int)
                if choice == 0: break
                if choice == clear_index:
                    specified_value = {}
                    unchosen_security_group_names = security_group_names.copy()
                else:
                    specified_value[options[choice][0]] = options[choice][1]
                    del unchosen_security_group_names[options[choice][0]]
            return specified_value
        except Exception as err:
            raise

    def get_public_subnets_info(self, stack_name):
        # AWS::EC2::Subnet
        try:
            public_subnets_info = []
            paginator = self.cloudformation.get_paginator('list_stack_resources')
            for page in paginator.paginate(StackName=stack_name):
                for resource in page['StackResourceSummaries']:
                    resource_type = resource['ResourceType']
                    if resource_type == 'AWS::EC2::Subnet':
                        logical_id = resource['LogicalResourceId']
                        if re.match(r'SOCAVpcPublic', logical_id):
                            subnet_id = resource['PhysicalResourceId']
                            subnet = self.ec2.describe_subnets(SubnetIds=[subnet_id])['Subnets'][0]
                            availability_zone = subnet['AvailabilityZone']
                            public_subnets_info.append({'id': subnet_id, 'az': availability_zone})
            if public_subnets_info:
                return {'success': True, 'message': public_subnets_info}
            else:
                return {"success": False, "message": f'Could not find any public subnets in {stack_name}'}
        except Exception as err:
            return {"success": False, "message": str(err)}

    def get_security_groups(self, prompt, vpc_id, security_group_names=[], prefix=''):
        try:
            security_groups = {}
            for security_group in self.ec2.describe_security_groups(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])['SecurityGroups']:
                resource_name = False
                if "Tags" in security_group.keys():
                    for tag in security_group["Tags"]:
                        if tag["Key"] == "Name":
                            resource_name = tag["Value"]
                if not resource_name:
                    continue
                if not re.match(f"^{prefix}", resource_name):
                    continue
                security_groups[resource_name] = security_group
            # Check supplied security group names
            invalid_security_group_names = []
            found_security_groups = {}
            if security_group_names:
                for security_group_name in sorted(security_group_names):
                    prefixed_security_group_name = prefix + security_group_name
                    if security_group_name in security_groups:
                        id = security_groups[security_group_name]['GroupId']
                        found_security_groups[security_group_name] = id
                        del security_groups[security_group_name]
                    elif prefixed_security_group_name in security_groups:
                        id = security_groups[prefixed_security_group_name]['GroupId']
                        found_security_groups[security_group_name] = id
                        del security_groups[prefixed_security_group_name]
                    else:
                        invalid_security_group_names.append(security_group_name)
                if not invalid_security_group_names:
                    return {'success': True, 'message': found_security_groups}
            options = {}
            count = 1
            for resource_name in sorted(security_groups):
                security_group = security_groups[resource_name]
                id = security_group['GroupId']
                security_group = security_groups[resource_name]
                options[count] = {
                    "id": id,
                    "name": resource_name,
                    "description": f"{resource_name} {id} {security_group['GroupName']}"
                }
                count += 1
            options[0] = {
                "id": f"",
                "name": "",
                "description": f"Select 0 when done"
            }
            choice = 1
            while choice != 0:
                allowed_choices = list(options.keys())
                [print("    {} > {}".format(key, value["description"])) for key, value in options.items()]
                choice = get_input(prompt, None, allowed_choices, int)
                if choice != 0:
                    found_security_groups[options[choice]['name']] = options[choice]['id']
                del options[choice]
            return {'success': True, 'message': found_security_groups}

        except Exception as err:
            print(str(err))
            return {'success': False, 'message': str(err)}

    def validate_sg_rules(self, cfn_params, check_fs=True):
        try:
            # Begin Verify Security Group Rules
            print(f"\n====== Please wait a little as we {fg('misty_rose_3')}validate your security group rules {attr('reset')} ======\n")
            sg_rules = self.get_rules_for_security_group([cfn_params["scheduler_sg"], cfn_params["compute_node_sg"]])
            if check_fs is True:
                fs_sg = self.get_fs_security_groups(cfn_params)

            if sg_rules["success"] is True:
                scheduler_sg_rules = sg_rules["message"][cfn_params["scheduler_sg"]]
                compute_node_sg_rules = sg_rules["message"][cfn_params["compute_node_sg"]]
            else:
                print(f"{fg('red')}Error: {sg_rules['message']} {attr('reset')}")
                sys.exit(1)

            errors = {}
            errors["SCHEDULER_SG_IN_COMPUTE"] = {
                    "status": False,
                    "error": f"Compute Node SG must allow all TCP traffic from Scheduler SG",
                    "resolution": f"Add new rule on {cfn_params['compute_node_sg']} that allow TCP ports '0-65535' for {cfn_params['scheduler_sg']}"}
            errors["COMPUTE_SG_IN_SCHEDULER"] = {
                    "status": False,
                    "error": f"Scheduler SG must allow all TCP traffic from Compute Node SG",
                    "resolution": f"Add a new rule on {cfn_params['scheduler_sg']} that allow TCP ports '0-65535' for {cfn_params['compute_node_sg']}"}
            errors["CLIENT_IP_HTTPS_IN_SCHEDULER"] = {
                    "status": False,
                    "error": f"Client IP must be allowed for port 443 (80 optional) on Scheduler SG",
                    "resolution": f"Add two rules on {cfn_params['scheduler_sg']} that allow TCP ports 80 and 443 for {self.client_ip}"}
            errors["CLIENT_IP_SSH_IN_SCHEDULER"] = {
                    "status": False,
                    "error": f"Client IP must be allowed for port 22 (SSH) on Scheduler SG",
                    "resolution": f"Add one rule on {cfn_params['scheduler_sg']} that allow TCP port 22 for {self.client_ip}"}
            errors["SCHEDULER_SG_EQUAL_COMPUTE"] = {
                    "status": False,
                    "error": "Scheduler SG and Compute SG must be different",
                    "resolution": "You must choose two different security groups"}
            errors["COMPUTE_SG_EGRESS_EFA"] = {
                    "status": False,
                    "error": "Compute SG must reference egress traffic to itself for EFA",
                    "resolution": f"Add a new (EGRESS) rule on {cfn_params['compute_node_sg']} that allow TCP ports '0-65535' for {cfn_params['compute_node_sg']}. Make sure you configure EGRESS rule and not INGRESS"}

            if check_fs is True:
                errors["FS_APP_SG"] = {
                    "status": False,
                    "error": f"SG assigned to EFS App {cfn_params['fs_apps']} must allow Scheduler SG and Compute SG",
                    "resolution": f"Add {cfn_params['scheduler_sg']} and {cfn_params['compute_node_sg']} on your EFS Apps {cfn_params['fs_apps']}"}

                errors["FS_DATA_SG"] = {
                    "status": False,
                    "error": f"SG assigned to EFS App {cfn_params['fs_data']} must allow Scheduler SG and Compute SG",
                    "resolution": f"Add {cfn_params['scheduler_sg']} and {cfn_params['compute_node_sg']} on your EFS Data {cfn_params['fs_data']}"}

            # Verify Scheduler Rules
            for rules in scheduler_sg_rules:
                if rules["from_port"] == 0 and rules["to_port"] == 65535:
                    for rule in rules["approved_ips"]:
                        if cfn_params['compute_node_sg'] in rule:
                            errors["COMPUTE_SG_IN_SCHEDULER"]["status"] = True

                if rules["from_port"] == 443 or rules["from_port"] == 22:
                    for rule in rules["approved_ips"]:
                        client_ip_netmask = 32
                        if client_ip_netmask == '32':
                            if ipaddress.IPv4Address(self.client_ip) in ipaddress.IPv4Network(rule):
                                if rules["from_port"] == 443:
                                    errors["CLIENT_IP_HTTPS_IN_SCHEDULER"]["status"] = True
                                if rules["from_port"] == 22:
                                    errors["CLIENT_IP_SSH_IN_SCHEDULER"]["status"] = True
                        else:
                            if self.client_ip in rule:
                                if rules["from_port"] == 443:
                                    errors["CLIENT_IP_HTTPS_IN_SCHEDULER"]["status"] = True
                                if rules["from_port"] == 22:
                                    errors["CLIENT_IP_SSH_IN_SCHEDULER"]["status"] = True
            # Verify Compute Node Rules
            for rules in compute_node_sg_rules:
                if rules["from_port"] == 0 and rules["to_port"] == 65535:
                    for rule in rules["approved_ips"]:
                        if cfn_params['scheduler_sg'] in rule:
                            errors["SCHEDULER_SG_IN_COMPUTE"]["status"] = True

                        if rules["type"] == "egress":
                            if cfn_params['compute_node_sg'] in rule:
                                errors["COMPUTE_SG_EGRESS_EFA"]["status"] = True

            if check_fs is True:
                if cfn_params['scheduler_sg'] in fs_sg["message"][cfn_params['fs_apps']] and cfn_params['compute_node_sg'] in fs_sg["message"][cfn_params['fs_apps']]:
                    errors["FS_APP_SG"]["status"] = True

                if cfn_params['scheduler_sg'] in fs_sg["message"][cfn_params['fs_data']] and cfn_params['compute_node_sg'] in fs_sg["message"][cfn_params['fs_data']]:
                    errors["FS_DATA_SG"]["status"] = True

            if cfn_params["scheduler_sg"] != cfn_params["compute_node_sg"]:
                errors["SCHEDULER_SG_EQUAL_COMPUTE"]["status"] = True

            sg_errors = {}

            confirm_sg_settings = False
            for error_id, error_info in errors.items():
                if error_info["status"] is False:
                    if check_fs is False and "EFS" in error_id:
                        pass
                    else:
                        print(f"{fg('yellow')}ATTENTION!! {error_info['error']} {attr('reset')}\nHow to solve: {error_info['resolution']}\n")
                        sg_errors[error_info["error"]] = error_info["resolution"]
                        confirm_sg_settings = True

            if confirm_sg_settings:
                choice = get_input("Your security groups may not be configured correctly. Verify them and determine if the warnings listed above are false-positive.\n Do you still want to continue with the installation?",
                                   None, ["yes", "no"], str)
                if choice.lower() == "no":
                    sys.exit(1)
            else:
                print(f"{fg('green')} Security Groups seems to be configured correctly{attr('reset')}")

            return {"success": True,
                    "message": ""}

        except Exception as e:

            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(f"{exc_type} {fname} {exc_tb.tb_lineno}")
            return {"success": False, "message": f"{exc_type} {fname} {exc_tb.tb_lineno}"}

    def get_role_arn(self, prompt, stack_name, logical_id_pattern):
        try:
            paginator = self.cloudformation.get_paginator('list_stack_resources')
            for page in paginator.paginate(StackName=stack_name):
                for resource in page['StackResourceSummaries']:
                    resource_type = resource['ResourceType']
                    if resource_type == 'AWS::IAM::Role':
                        logical_id = resource['LogicalResourceId']
                        if re.match(logical_id_pattern, logical_id):
                            role_name = resource['PhysicalResourceId']
                            role = self.iam.get_role(RoleName=role_name)
                            role_arn = role['Role']['Arn']
                            return {'success': True, 'message': role_arn}
            return {"success": False, "message": f'Could not find any role in {stack_name} that matches {logical_id_pattern}'}
        except Exception as err:
            return {"success": False, "message": str(err)}

    def get_hosted_zone_id(self, vpc_id):
        try:
            hosted_zone_ids = {}
            for hosted_zone_summary in self.route53.list_hosted_zones_by_vpc(VPCId= vpc_id, VPCRegion=self.region)['HostedZoneSummaries']:
                if hosted_zone_summary['Owner'].get('OwningService', None):
                    # Ignore because created by a service like a VPC endpoint
                    continue
                name = hosted_zone_summary['Name']
                hosted_zone_id = hosted_zone_summary['HostedZoneId']
                owning_account = hosted_zone_summary['Owner']['OwningAccount']
                hosted_zone_ids[name] = hosted_zone_id
            return {"success": True, "message": hosted_zone_ids}
        except Exception as err:
            return {"success": False, "message": str(err)}
