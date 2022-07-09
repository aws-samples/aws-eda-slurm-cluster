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
Create/delete compute node security group in another region.
'''
import cfnresponse
import boto3
import json
import logging
logging.getLogger().setLevel(logging.INFO)

def get_security_group_id(ec2_client, security_group_name: str) -> str:
    security_group_id = ec2_client.describe_security_groups(
        Filters = [
            {
                'Name': 'group-name',
                'Values': [security_group_name]
            }
        ]
    )['SecurityGroups'][0]['GroupId']
    return security_group_id

def lambda_handler(event, context):
    try:
        logging.info(f"event:\n{json.dumps(event, indent=4)}")
        properties = event['ResourceProperties']
        required_properties = [
            'Region',
            'VpcId',
            'SecurityGroupName',
            'Description',
            'ControllerCIDR',
            'CIDRs',
            'StackName'
            ]
        error_message = ""
        for property in required_properties:
            try:
                value = properties[property]
            except:
                error_message += f"Missing {property} property. "
        if error_message:
            raise KeyError(error_message)

        ec2_client = boto3.client('ec2', region_name=properties['Region'])
        requestType = event['RequestType']

        cidrs = properties['CIDRs']

        if requestType in ['Update', 'Delete']:
            security_group_id = get_security_group_id(ec2_client, properties['SecurityGroupName'])

        if requestType == 'Update':
            logging.info(f"Updating {security_group_id}")
            # Delete existing rules and recreate them
            logging.info(f"Deleting rules")
            security_group_rules = ec2_client.describe_security_group_rules(
                Filters = [{'Name': 'group-id', 'Values': [security_group_id]}]
            )['SecurityGroupRules']
            logging.info(f"{len(security_group_rules)} security_group_rules:\n{json.dumps(security_group_rules, indent=4)}")
            ingress_rule_ids = []
            egress_rule_ids = []
            for security_group_rule in security_group_rules:
                security_group_rule_id = security_group_rule['SecurityGroupRuleId']
                if security_group_rule['IsEgress']:
                    logging.info(f"Deleting ingress rule: {security_group_rule_id}")
                    egress_rule_ids.append(security_group_rule_id)
                else:
                    logging.info(f"Deleting egress rule: {security_group_rule_id}")
                    ingress_rule_ids.append(security_group_rule_id)
            if ingress_rule_ids:
                ec2_client.revoke_security_group_ingress(
                    GroupId = security_group_id,
                    SecurityGroupRuleIds=ingress_rule_ids
                )
            if egress_rule_ids:
                ec2_client.revoke_security_group_egress(
                    GroupId = security_group_id,
                    SecurityGroupRuleIds=egress_rule_ids
                )

        if requestType == 'Create':
            security_group_id = ec2_client.create_security_group(
                GroupName = properties['SecurityGroupName'],
                Description = properties['Description'],
                VpcId = properties['VpcId'],
                TagSpecifications = [
                    {
                        'ResourceType': 'security-group',
                        'Tags': [
                            {'Key': 'Name', 'Value': f"{properties['SecurityGroupName']}"},
                            {'Key': 'cloudformation:stack-name', 'Value': f"{properties['StackName']}"}
                            ]
                    }
                ]
            )['GroupId']
            logging.info(f"Created {security_group_id}")

        if requestType in ['Create', 'Update']:
            logging.info(f"Adding security group rules")
            ec2_client.authorize_security_group_ingress(
                GroupId = security_group_id,
                IpPermissions = [
                    {
                        'IpProtocol': 'tcp',
                        'FromPort': 6818,
                        'ToPort': 6818,
                        'IpRanges': [{'CidrIp': properties['ControllerCIDR'], 'Description': f"{properties['StackName']}-SlurmCtl to {properties['Region']}-SlurmNode"}]
                    },
                ]
            )
            ec2_client.authorize_security_group_egress(
                GroupId = security_group_id,
                IpPermissions = [
                    {
                        'IpProtocol': 'tcp',
                        'FromPort': 80,
                        'ToPort': 80,
                        'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': f"{properties['Region']}-SlurmNode to Internet"}]
                    },
                    {
                        'IpProtocol': 'tcp',
                        'FromPort': 111,
                        'ToPort': 111,
                        'IpRanges': [{'CidrIp': properties['ControllerCIDR'], 'Description': f"{properties['Region']}-SlurmNode to {properties['StackName']}-ZFS"}]
                    },
                    {
                        'IpProtocol': 'udp',
                        'FromPort': 111,
                        'ToPort': 111,
                        'IpRanges': [{'CidrIp': properties['ControllerCIDR'], 'Description': f"{properties['Region']}-SlurmNode to {properties['StackName']}-ZFS"}]
                    },
                    {
                        'IpProtocol': 'tcp',
                        'FromPort': 443,
                        'ToPort': 443,
                        'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': f"{properties['Region']}-SlurmNode to Internet"}]
                    },
                    {
                        'IpProtocol': 'tcp',
                        'FromPort': 2049,
                        'ToPort': 2049,
                        'IpRanges': [{'CidrIp': properties['ControllerCIDR'], 'Description': f"{properties['Region']}-SlurmNode to {properties['StackName']}-ZFS"}]
                    },
                    {
                        'IpProtocol': 'udp',
                        'FromPort': 2049,
                        'ToPort': 2049,
                        'IpRanges': [{'CidrIp': properties['ControllerCIDR'], 'Description': f"{properties['Region']}-SlurmNode to {properties['StackName']}-ZFS"}]
                    },
                    {
                        'IpProtocol': 'tcp',
                        'FromPort': 6817,
                        'ToPort': 6817,
                        'IpRanges': [{'CidrIp': properties['ControllerCIDR'], 'Description': f"{properties['Region']}-SlurmNode to {properties['StackName']}-SlurmCtl"}]
                    },
                    {
                        'IpProtocol': 'tcp',
                        'FromPort': 20001,
                        'ToPort': 20003,
                        'IpRanges': [{'CidrIp': properties['ControllerCIDR'], 'Description': f"{properties['Region']}-SlurmNode to {properties['StackName']}-ZFS"}]
                    },
                    {
                        'IpProtocol': 'udp',
                        'FromPort': 20001,
                        'ToPort': 20003,
                        'IpRanges': [{'CidrIp': properties['ControllerCIDR'], 'Description': f"{properties['Region']}-SlurmNode to {properties['StackName']}-ZFS"}]
                    },
                ]
            )
            for compute_region, cidr in cidrs.items():
                if compute_region == properties['Region']:
                    ec2_client.authorize_security_group_ingress(
                        GroupId = security_group_id,
                        IpPermissions = [
                            {
                                'IpProtocol': 'tcp',
                                'FromPort': 1024,
                                'ToPort': 65535,
                                'UserIdGroupPairs': [{'GroupId': security_group_id, 'Description': f"{compute_region}-SlurmNode to {compute_region}-SlurmNode"}]
                            },
                        ]
                    )
                    ec2_client.authorize_security_group_egress(
                        GroupId = security_group_id,
                        IpPermissions = [
                            {
                                'IpProtocol': 'tcp',
                                'FromPort': 1024,
                                'ToPort': 65535,
                                'UserIdGroupPairs': [{'GroupId': security_group_id, 'Description': f"{properties['Region']}-SlurmNode to {compute_region}-SlurmNode"}]
                            },
                            {
                                'IpProtocol': 'tcp',
                                'FromPort': 6818,
                                'ToPort': 6818,
                                'UserIdGroupPairs': [{'GroupId': security_group_id, 'Description': f"{properties['Region']}-SlurmNode to {compute_region}-SlurmNode"}]
                            },
                        ]
                    )
                else:
                    ec2_client.authorize_security_group_ingress(
                        GroupId = security_group_id,
                        IpPermissions = [
                            {
                                'IpProtocol': 'tcp',
                                'FromPort': 1024,
                                'ToPort': 65535,
                                'IpRanges': [{'CidrIp': cidr, 'Description': f"{compute_region}-SlurmNode to {properties['Region']}-SlurmNode"}]
                            },
                        ]
                    )
                    ec2_client.authorize_security_group_egress(
                        GroupId = security_group_id,
                        IpPermissions = [
                            {
                                'IpProtocol': 'tcp',
                                'FromPort': 1024,
                                'ToPort': 65535,
                                'IpRanges': [{'CidrIp': cidr, 'Description': f"{properties['Region']}-SlurmNode to {compute_region}-SlurmNode"}]
                            },
                            {
                                'IpProtocol': 'tcp',
                                'FromPort': 6818,
                                'ToPort': 6818,
                                'IpRanges': [{'CidrIp': cidr, 'Description': f"{properties['Region']}-SlurmNode to {compute_region}-SlurmNode"}]
                            },
                        ]
                    )

        if requestType == 'Delete':
            logging.info(f"Deleting {security_group_id}")
            ec2_client.delete_security_group(
                GroupId = security_group_id
            )

    except Exception as e:
        logging.exception(str(e))
        cfnresponse.send(event, context, cfnresponse.FAILED, {'error': str(e)}, str(e))
        raise

    cfnresponse.send(event, context, cfnresponse.SUCCESS, {'GroupId': security_group_id}, f"{security_group_id}")
