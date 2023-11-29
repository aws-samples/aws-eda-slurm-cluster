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

from aws_cdk import (
    Aws,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cloudwatch_actions,
    aws_ec2 as ec2,
    aws_efs as efs,
    aws_fis as fis,
    aws_fsx as fsx,
    aws_iam as iam,
    aws_kms as kms,
    aws_lambda as aws_lambda,
    aws_logs as logs,
    aws_opensearchservice as opensearch,
    aws_rds as rds,
    aws_route53 as route53,
    aws_s3 as s3,
    aws_s3_assets as s3_assets,
    aws_secretsmanager as secretsmanager,
    aws_sns as sns,
    aws_sns_subscriptions as subs,
    aws_sqs as sqs,
    aws_ssm as ssm,
    CfnOutput,
    CfnResource,
    CustomResource,
    Duration,
    RemovalPolicy,
    Size,
    Stack,
    SymlinkFollowMode,
    Tags,
    )
import base64
import boto3
from botocore.exceptions import ClientError
from config_schema import get_PARALLEL_CLUSTER_MUNGE_VERSION, get_PARALLEL_CLUSTER_PYTHON_VERSION, get_SLURM_VERSION
from constructs import Construct
from copy import copy, deepcopy
from jinja2 import Template as Template
import json
import logging
from os import makedirs, path
from os.path import dirname, realpath
from packaging.version import parse as parse_version
from pprint import PrettyPrinter
import re
import subprocess
from subprocess import check_output
import sys
from sys import exit
from tempfile import NamedTemporaryFile
from textwrap import dedent
from types import SimpleNamespace
import yaml
from yaml.scanner import ScannerError

sys.path.append(f"{dirname(__file__)}/../resources/playbooks/roles/SlurmCtl/files/opt/slurm/cluster/bin")
from EC2InstanceTypeInfoPkg.EC2InstanceTypeInfo import EC2InstanceTypeInfo
from SlurmPlugin import SlurmPlugin

pp = PrettyPrinter()

logger = logging.getLogger(__file__)
logger_formatter = logging.Formatter('%(levelname)s: %(message)s')
logger_streamHandler = logging.StreamHandler()
logger_streamHandler.setFormatter(logger_formatter)
logger.addHandler(logger_streamHandler)
logger.propagate = False
logger.setLevel(logging.INFO)

class CdkSlurmStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.onprem_cidr = None

        self.principals_suffix = {
            "backup": f"backup.{Aws.URL_SUFFIX}",
            "cloudwatch": f"cloudwatch.{Aws.URL_SUFFIX}",
            "ec2": f"ec2.{Aws.URL_SUFFIX}",
            "fis": f"fis.{Aws.URL_SUFFIX}",
            "lambda": f"lambda.{Aws.URL_SUFFIX}",
            "sns": f"sns.{Aws.URL_SUFFIX}",
            "spotfleet": f"spotfleet.{Aws.URL_SUFFIX}",
            "ssm": f"ssm.{Aws.URL_SUFFIX}"
        }

        self.ec2_client = boto3.client('ec2', region_name=self.region)

        # Read the config file and then any overrides from the context variables.
        self.config = self.get_config('config_file', 'default_config.yml')

        # Get context variables to override the config
        self.override_config_with_context()

        self.check_config()

        self.cluster_region = self.config['Region']

        self.ec2_client = boto3.client('ec2', region_name=self.cluster_region)

        self.create_vpc()

        self.check_regions_config()

        self.create_security_groups()

        self.create_parallel_cluster_lambdas()

        self.create_parallel_cluster_assets()

        self.create_parallel_cluster_config()

        self.create_fault_injection_templates()

    def get_config(self, context_var, default_path):
        default_config_file_path = realpath(f"{dirname(realpath(__file__))}/../resources/config/")
        config_file_path = self.node.try_get_context(context_var)
        if not config_file_path:
            config_file_path = f"{default_config_file_path}/{default_path}"
        if path.isabs(config_file_path):
            if not path.exists(config_file_path):
                logger.error(f"{config_file_path} does not exist")
                exit(1)
        else:
            # Not an absolute path so check to see if it exists as a relative path
            if path.exists(config_file_path):
                config_file_path = realpath(config_file_path)
            elif path.exists(f"{default_config_file_path}/{config_file_path}"):
                # Check to see if in default config file path
                config_file_path = realpath(f"{default_config_file_path}/{config_file_path}")
            else:
                logger.error(f"Could not find {config_file_path}")
                exit(1)
        logger.info(f"Using config: {config_file_path}")

        try:
            config_parameters = yaml.load(open(config_file_path, 'r'), Loader=yaml.FullLoader) # nosec
        except ScannerError as err:
            logger.error(f"{config_file_path} is not a valid YAML file. Verify syntax, {err}")
            exit(1)
        except FileNotFoundError:
            logger.error(f"{config_file_path} not found")
            exit(1)

        if context_var == 'config_file':
            # Validate config against schema
            from config_schema import check_schema
            from schema import SchemaError
            region = self.node.try_get_context('region')
            try:
                config_parameters = check_schema(config_parameters)
            except SchemaError:
                logger.exception(f"Invalid config file: {config_file_path}")
                exit(1)

        if config_parameters:
            return config_parameters
        else:
            exit("No parameters were specified.")

    def override_config_with_context(self):
        '''
        Override the config using context variables
        '''
        region = self.node.try_get_context('region')
        config_key = 'Region'
        if region:
            if config_key not in self.config:
                logger.info(f"{config_key:20} set from command line: {region}")
            elif region != self.config[config_key]:
                logger.info(f"{config_key:20} in config file overridden on command line from {self.config[config_key]} to {region}")
            self.config[config_key] = region
        if config_key not in self.config:
            logger.error(f"Must set --region from the command line or {config_key} in the config files")
            exit(1)

        config_key = 'SshKeyPair'
        ssh_keypair = self.node.try_get_context(config_key)
        if ssh_keypair:
            if config_key not in self.config:
                logger.info(f"{config_key:20} set from command line: {ssh_keypair}")
            elif ssh_keypair != self.config[config_key]:
                logger.info(f"{config_key:20} in config file overridden on command line from {self.config[config_key]} to {ssh_keypair}")
            self.config[config_key] = ssh_keypair
        if config_key not in self.config:
            logger.error("You must provide --ssh-keypair on the command line or {config_key} in the config file.")
            exit(1)

        config_key = 'VpcId'
        vpc_id = self.node.try_get_context(config_key)
        if vpc_id:
            if config_key not in self.config:
                logger.info(f"{config_key:20} set from command line: {vpc_id}")
            elif vpc_id != self.config[config_key]:
                logger.info(f"{config_key:20} in config file overridden on command line from {self.config[config_key]} to {vpc_id}")
            self.config[config_key] = vpc_id
        if config_key not in self.config:
            logger.error("You must provide --vpc-id on the command line or {config_key} in the config file.")
            exit(1)

        config_key = 'CIDR'
        cidr = self.node.try_get_context(config_key)
        if cidr:
            if config_key not in self.config:
                logger.info(f"{config_key:20} set from command line: {cidr}")
            elif cidr != self.config[config_key]:
                logger.info(f"{config_key:20} in config file overridden on command line from {self.config[config_key]} to {cidr}")
            self.config[config_key] = cidr
        if config_key not in self.config:
            logger.error("You must provide --cidr on the command line or {config_key} in the config file.")
            exit(1)

        config_key = 'SubnetId'
        subnet_id = self.node.try_get_context(config_key)
        if subnet_id:
            if config_key not in self.config:
                logger.info(f"{config_key:20} set from command line: {subnet_id}")
            elif subnet_id != self.config[config_key]:
                logger.info(f"{config_key:20} in config file overridden on command line from {self.config[config_key]} to {subnet_id}")
            self.config[config_key] = subnet_id

        config_key = 'ErrorSnsTopicArn'
        errorSnsTopicArn = self.node.try_get_context(config_key)
        if subnet_id:
            if config_key not in self.config:
                logger.info(f"{config_key:20} set from command line: {errorSnsTopicArn}")
            elif errorSnsTopicArn != self.config[config_key]:
                logger.info(f"{config_key:20} in config file overridden on command line from {self.config[config_key]} to {errorSnsTopicArn}")
            self.config[config_key] = errorSnsTopicArn

        config_key = 'SubmitterSecurityGroupIds'
        submitterSecurityGroupIds_b64_string = self.node.try_get_context(config_key)
        if submitterSecurityGroupIds_b64_string:
            submitterSecurityGroupIds = json.loads(base64.b64decode(submitterSecurityGroupIds_b64_string).decode('utf-8'))
            if config_key not in self.config['slurm']:
                logger.info(f"slurm/{config_key:20} set from command line: {submitterSecurityGroupIds}")
            else:
                logger.info(f"slurm/{config_key:20} in config file overridden on command line from {self.config['slurm'][config_key]} to {submitterSecurityGroupIds}")
            self.config['slurm'][config_key] = submitterSecurityGroupIds

    def check_config(self):
        '''
        Check config, set defaults, and sanity check the configuration
        '''
        config_errors = 0

        if self.stack_name:
            if 'StackName' not in self.config:
                logger.info(f"config/StackName set from command line: {self.stack_name}")
            elif self.stack_name != self.config['StackName']:
                logger.info(f"config/StackName in config file overridden on command line from {self.config['StackName']} to {self.stack_name}")
            self.config['StackName'] = self.stack_name
        if 'StackName' not in self.config:
            logger.error(f"You must provide --stack-name on the command line or StackName in the config file.")
            config_errors += 1

        error_sns_topic_arn = self.node.try_get_context('ErrorSnsTopicArn')
        if error_sns_topic_arn:
            self.config['ErrorSnsTopicArn'] = error_sns_topic_arn
        else:
            if 'ErrorSnsTopicArn' not in self.config:
                logger.warning(f"ErrorSnsTopicArn not set. Provide error-sns-topic-arn on the command line or ErrorSnsTopicArn in the config file to get error notifications.")
                self.config['ErrorSnsTopicArn'] = ''

        if 'ClusterName' not in self.config['slurm']:
            self.config['slurm']['ClusterName'] = f"{self.stack_name}-cl"
            logger.info(f"slurm/ClusterName defaulted to {self.config['StackName']}")

        self.PARALLEL_CLUSTER_VERSION = parse_version(self.config['slurm']['ParallelClusterConfig']['Version'])

        if self.PARALLEL_CLUSTER_VERSION < parse_version('3.7.0'):
            if 'LoginNodes' in self.config['slurm']['ParallelClusterConfig']:
                logger.error(f"slurm/ParallelClusterConfig/LoginNodes not supported before version 3.7.0")
                config_errors += 1

        if 'Database' in self.config['slurm']['ParallelClusterConfig']:
            if 'DatabaseStackName' in self.config['slurm']['ParallelClusterConfig']['Database'] and 'EdaSlurmClusterStackName' in self.config['slurm']['ParallelClusterConfig']['Database']:
                logger.error(f"Cannot specify both slurm/ParallelClusterConfig/Database/DatabaseStackName and slurm/ParallelClusterConfig/Database/EdaSlurmClusterStackName")
                config_errors += 1

            required_keys = ['ClientSecurityGroup', 'FQDN', 'Port', 'AdminUserName', 'AdminPasswordSecretArn']
            if 'DatabaseStackName' in self.config['slurm']['ParallelClusterConfig']['Database'] or 'EdaSlurmClusterStackName' in self.config['slurm']['ParallelClusterConfig']['Database']:
                invalid_keys = []
                for database_key in self.config['slurm']['ParallelClusterConfig']['Database']:
                    if database_key in ['DatabaseStackName', 'EdaSlurmClusterStackName']:
                        continue
                    if database_key in required_keys:
                        logger.error(f"Cannot specify slurm/ParallelClusterConfig/Database/{database_key} and slurm/ParallelClusterConfig/Database/[Database,EdaSlurmCluster]StackName")
                        invalid_keys.append(database_key)
                        config_errors += 1
                for database_key in invalid_keys:
                    del self.config['slurm']['ParallelClusterConfig']['Database'][database_key]

            if 'DatabaseStackName' in self.config['slurm']['ParallelClusterConfig']['Database']:
                cfn_client = boto3.client('cloudformation', region_name=self.config['Region'])
                # Check to make sure that the database is in the same VPC.
                parameter_dicts = cfn_client.describe_stacks(StackName=self.config['slurm']['ParallelClusterConfig']['Database']['DatabaseStackName'])['Stacks'][0]['Parameters']
                vpc_checked = False
                for parameter_dict in parameter_dicts:
                    if parameter_dict['ParameterKey'] == 'Vpc':
                        database_vpc_id = parameter_dict['ParameterValue']
                        if database_vpc_id != self.config['VpcId']:
                            logger.error(f"Config slurm/ParallelClusterConfig/Database/DatabaseStackName({self.config['slurm']['ParallelClusterConfig']['Database']['DatabaseStackName']}) is deployed in {database_vpc_id} but needs to be in {self.config['VpcId']}")
                            config_errors += 1
                        vpc_checked = True
                        break
                assert vpc_checked, f"Didn't find vpc for database in\n{json.dumps(parameter_dicts, indent=4)}"

                stack_outputs = cfn_client.describe_stacks(StackName=self.config['slurm']['ParallelClusterConfig']['Database']['DatabaseStackName'])['Stacks'][0]['Outputs']
                output_to_key_map = {
                    'DatabaseHost': 'FQDN',
                    'DatabasePort': 'Port',
                    'DatabaseAdminUser': 'AdminUserName',
                    'DatabaseSecretArn': 'AdminPasswordSecretArn',
                    'DatabaseClientSecurityGroup': 'ClientSecurityGroup'
                }
                for output in stack_outputs:
                    if output['OutputKey'] in output_to_key_map:
                        database_key = output_to_key_map[output['OutputKey']]
                        if database_key == 'Port':
                            value = int(output['OutputValue'])
                        else:
                            value = output['OutputValue']
                        if database_key == 'ClientSecurityGroup':
                            self.config['slurm']['ParallelClusterConfig']['Database'][database_key] = {f"{self.config['slurm']['ParallelClusterConfig']['Database']['DatabaseStackName']}-DatabaseClientSG": value}
                        else:
                            self.config['slurm']['ParallelClusterConfig']['Database'][database_key] = value
                for output, database_key in output_to_key_map.items():
                    if database_key not in self.config['slurm']['ParallelClusterConfig']['Database']:
                        logger.error(f"{output} output not found in self.config['slurm']['ParallelClusterConfig']['Database']['DatabaseStackName'] stack to set slurm/ParallelClusterConfig/Database/{database_key}")

            elif 'EdaSlurmClusterStackName' in self.config['slurm']['ParallelClusterConfig']['Database']:
                cfn_client = boto3.client('cloudformation', region_name=self.config['region'])
                stack_outputs = cfn_client.describe_stacks(StackName=self.config['slurm']['ParallelClusterConfig']['Database']['EdaSlurmClusterStackName'])['Stacks'][0]['Outputs']
                output_to_key_map = {
                    'DatabaseHost': 'FQDN',
                    'DatabasePort': 'Port',
                    'DatabaseAdminUser': 'AdminUserName',
                    'DatabaseAdminPasswordSecretArn': 'AdminPasswordSecretArn',
                    'SlurmDbdSecurityGroup': 'ClientSecurityGroup'
                }
                for output in stack_outputs:
                    if output['OutputKey'] in output_to_key_map:
                        database_key = output_to_key_map[output['OutputKey']]
                        if database_key == 'Port':
                            value = int(output['OutputValue'])
                        else:
                            value = output['OutputValue']
                        if database_key == 'ClientSecurityGroup':
                            self.config['slurm']['ParallelClusterConfig']['Database'][database_key] = {f"{self.config['slurm']['ParallelClusterConfig']['Database']['EdaSlurmClusterStackName']}-SlurmDbdSG": value}
                        else:
                            self.config['slurm']['ParallelClusterConfig']['Database'][database_key] = value
                for output, database_key in output_to_key_map.items():
                    if database_key not in self.config['slurm']['ParallelClusterConfig']['Database']:
                        logger.error(f"{output} output not found in self.config['slurm']['ParallelClusterConfig']['Database']['EdaSlurmClusterStackName'] stack to set slurm/ParallelClusterConfig/Database/{database_key}")

            else:
                for database_key in required_keys:
                    if database_key not in self.config['slurm']['ParallelClusterConfig']['Database']:
                        logger.error(f"Must specify slurm/ParallelClusterConfig/Database/{database_key} when slurm/ParallelClusterConfig/Database/[Database,EdaSlurmCluster]StackName not set")
                        config_errors += 1

            if self.config['slurm']['ParallelClusterConfig']['Image']['Os'] == 'centos7' and self.config['slurm']['ParallelClusterConfig']['Architecture'] != 'x86_64':
                logger.error(f'centos7 only supports x86_64 architecture. Update slurm/ParallelClusterConfig/Architecture.')
                config_errors += 1

            for extra_mount_dict in self.config['slurm'].get('storage', {}).get('ExtraMounts', {}):
                mount_dir = extra_mount_dict['dest']
                if 'StorageType' not in extra_mount_dict:
                    logger.error(f"ParallelCluster requires StorageType for {mount_dir} in slurm/storage/ExtraMounts")
                    config_errors += 1
                    continue
                storage_type = extra_mount_dict['StorageType']
                if storage_type == 'Efs':
                    if 'FileSystemId' not in extra_mount_dict:
                        logger.error(f"ParallelCluster requires FileSystemId for {mount_dir} in slurm/storage/ExtraMounts")
                        config_errors += 1
                elif storage_type == 'FsxLustre':
                    if 'FileSystemId' not in extra_mount_dict:
                        logger.error(f"ParallelCluster requires FileSystemId for {mount_dir} in slurm/storage/ExtraMounts")
                        config_errors += 1
                elif storage_type == 'FsxOntap':
                    if 'VolumeId' not in extra_mount_dict:
                        logger.error(f"ParallelCluster requires VolumeId for {mount_dir} in slurm/storage/ExtraMounts")
                        config_errors += 1
                elif storage_type == 'FsxOpenZfs':
                    if 'VolumeId' not in extra_mount_dict:
                        logger.error(f"ParallelCluster requires VolumeId for {mount_dir} in slurm/storage/ExtraMounts")
                        config_errors += 1

        if config_errors:
            exit(1)

        # Validate updated config against schema
        from config_schema import check_schema
        from schema import SchemaError
        try:
            validated_config = check_schema(self.config)
        except SchemaError:
            logger.exception(f"Invalid config")
            exit(1)
        self.config = validated_config

    def create_parallel_cluster_assets(self):
        self.parallel_cluster_asset_read_policy = iam.ManagedPolicy(
            self, "ParallelClusterAssetReadPolicy",
            path = '/parallelcluster/',
            managed_policy_name = f"{self.stack_name}-ParallelClusterAssetReadPolicy",
        )

        self.parallel_cluster_jwt_write_policy = iam.ManagedPolicy(
            self, "ParallelClusterJwtWritePolicy",
            managed_policy_name = f"{self.stack_name}-ParallelClusterJwtWritePolicy",
        )
        self.jwt_token_for_root_ssm_parameter.grant_write(self.parallel_cluster_jwt_write_policy)
        self.jwt_token_for_slurmrestd_ssm_parameter.grant_write(self.parallel_cluster_jwt_write_policy)

        self.playbooks_asset = s3_assets.Asset(self, 'Playbooks',
            path = 'resources/playbooks',
            follow_symlinks = SymlinkFollowMode.ALWAYS
        )
        self.playbooks_asset.grant_read(self.parallel_cluster_asset_read_policy)
        self.playbooks_s3_url = self.playbooks_asset.s3_object_url

        self.assets_bucket = self.playbooks_asset.s3_bucket_name
        self.assets_base_key = self.config['slurm']['ClusterName']

        self.parallel_cluster_munge_key_write_policy = iam.ManagedPolicy(
            self, "ParallelClusterMungeKeyWritePolicy",
            managed_policy_name = f"{self.stack_name}-ParallelClusterMungeKeyWritePolicy",
            statements = [
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        's3:PutObject',
                    ],
                    resources=[f"arn:aws:s3:::{self.assets_bucket}/{self.config['slurm']['ClusterName']}/config/munge.key"]
                )
            ]
        )

        s3_client = boto3.client('s3', region_name=self.cluster_region)

        template_vars = {
            'assets_bucket': self.assets_bucket,
            'assets_base_key': self.assets_base_key,
            'ClusterName': self.config['slurm']['ClusterName'],
            'ErrorSnsTopicArn': self.config.get('ErrorSnsTopicArn', ''),
            'playbooks_s3_url': self.playbooks_s3_url,
            'Region': self.cluster_region,
            'SubnetId': self.config['SubnetId'],
            'SubmitterSlurmConfigDir': f"/opt/slurm/{self.config['slurm']['ClusterName']}/config"
        }
        # Additions or deletions to the list should be reflected in config_scripts in on_head_node_start.sh.
        files_to_upload = [
            'config/bin/configure-eda.sh',
            'config/bin/create_or_update_users_groups_json.sh',
            'config/bin/create_users_groups_json.py',
            'config/bin/create_users_groups_json_configure.sh',
            'config/bin/create_users_groups_json_deconfigure.sh',
            'config/bin/create_users_groups.py',
            'config/bin/on_head_node_start.sh',
            'config/bin/on_head_node_configured.sh',
            'config/bin/on_head_node_updated.sh',
            'config/bin/on_compute_node_start.sh',
            'config/bin/on_compute_node_configured.sh',
            'config/bin/submitter_configure.sh',
            'config/bin/submitter_deconfigure.sh',
            'config/users_groups.json',
        ]
        self.custom_action_s3_urls = {}
        for file_to_upload in files_to_upload:
            local_template_file = f"resources/parallel-cluster/{file_to_upload}"
            s3_key = f"{self.assets_base_key}/{file_to_upload}"
            self.custom_action_s3_urls[file_to_upload] = f"s3://{self.assets_bucket}/{s3_key}"
            local_template = Template(open(local_template_file, 'r').read())
            local_file_content = local_template.render(**template_vars)
            s3_client.put_object(
                Bucket = self.assets_bucket,
                Key    = s3_key,
                Body   = local_file_content
            )

        ami_builds = {
            'amzn': {
                '2': {
                    'arm64': {},
                    'x86_64': {}
                }
            },
            'centos': {
                '7': {
                    'x86_64': {}
                }
            },
            'rhel': {
                '8': {
                    'arm64': {},
                    'x86_64': {}
                },
            }
        }
        template_vars['ComponentS3Url'] = self.custom_action_s3_urls['config/bin/configure-eda.sh']
        cfn_client = boto3.client('cloudformation', region_name=self.config['Region'])
        cfn_list_resources_paginator = cfn_client.get_paginator('list_stack_resources')
        try:
            response_iterator = cfn_list_resources_paginator.paginate(
                StackName = self.stack_name
            )
            imagebuilder_sg_id = None
            asset_read_policy_arn = None
            for response in response_iterator:
                for stack_resource_summary in response['StackResourceSummaries']:
                    if stack_resource_summary['LogicalResourceId'].startswith('ImageBuilderSG'):
                        imagebuilder_sg_id = stack_resource_summary['PhysicalResourceId']
                    if stack_resource_summary['LogicalResourceId'].startswith('ParallelClusterAssetReadPolicy'):
                        asset_read_policy_arn = stack_resource_summary['PhysicalResourceId']
                    if imagebuilder_sg_id and asset_read_policy_arn:
                        break
                if imagebuilder_sg_id and asset_read_policy_arn:
                    break
            template_vars['ImageBuilderSecurityGroupId'] = imagebuilder_sg_id
            template_vars['AssetReadPolicy'] = asset_read_policy_arn
        except:
            template_vars['ImageBuilderSecurityGroupId'] = self.imagebuilder_sg.security_group_id
            template_vars['AssetReadPolicy'] = self.parallel_cluster_asset_read_policy.managed_policy_arn
        parallelcluster_version = self.config['slurm']['ParallelClusterConfig']['Version']
        parallelcluster_version_name = parallelcluster_version.replace('.', '-')
        build_file_path = f"resources/parallel-cluster/config/build-files"
        build_file_template_path = f"{build_file_path}/build-file.yml"
        build_files_path = f"{build_file_path}/{parallelcluster_version}/{self.config['slurm']['ClusterName']}"
        makedirs(build_files_path, exist_ok=True)
        for distribution in ami_builds:
            for version in ami_builds[distribution]:
                for architecture in ami_builds[distribution][version]:
                    template_vars['ImageName'] = f"parallelcluster-{parallelcluster_version_name}-eda-{distribution}-{version}-{architecture}".replace('_', '-')
                    if architecture == 'arm64':
                        template_vars['InstanceType'] = 'c6g.2xlarge'
                    else:
                        template_vars['InstanceType'] = 'c6i.2xlarge'
                    template_vars['ParentImage'] = self.get_image_builder_parent_image(distribution, version, architecture)
                    template_vars['RootVolumeSize'] = int(self.get_ami_root_volume_size(template_vars['ParentImage'])) + 10
                    logger.info(f"{distribution}-{version}-{architecture} image id: {template_vars['ParentImage']} root volume size={template_vars['RootVolumeSize']}")
                    build_file_template = Template(open(build_file_template_path, 'r').read())
                    build_file_content = build_file_template.render(**template_vars)
                    s3_client.put_object(
                        Bucket = self.assets_bucket,
                        Key    = f"{self.assets_base_key}/config/build-files/{template_vars['ImageName']}.yml",
                        Body   = build_file_content
                    )
                    fh = open(f"{build_files_path}/{template_vars['ImageName']}.yml", 'w')
                    fh.write(build_file_content)

                    template_vars['ParentImage'] = self.get_fpga_developer_image(distribution, version, architecture)
                    if not template_vars['ParentImage']:
                        logger.debug(f"No FPGA Developer AMI found for {distribution}{version} {architecture}")
                        continue
                    template_vars['ImageName'] = f"parallelcluster-{parallelcluster_version_name}-fpga-{distribution}-{version}-{architecture}".replace('_', '-')
                    template_vars['RootVolumeSize'] = int(self.get_ami_root_volume_size(template_vars['ParentImage'])) + 10
                    logger.info(f"{distribution}-{version}-{architecture} fpga developer image id: {template_vars['ParentImage']} root volume size={template_vars['RootVolumeSize']}")
                    build_file_content = build_file_template.render(**template_vars)
                    s3_client.put_object(
                        Bucket = self.assets_bucket,
                        Key    = f"{self.assets_base_key}/config/build-files/{template_vars['ImageName']}.yml",
                        Body   = build_file_content
                    )
                    fh = open(f"{build_files_path}/{template_vars['ImageName']}.yml", 'w')
                    fh.write(build_file_content)

        ansible_head_node_template_vars = self.get_instance_template_vars('ParallelClusterHeadNode')
        fh = NamedTemporaryFile('w', delete=False)
        fh.write('---\n')
        for name, value in sorted(ansible_head_node_template_vars.items()):
            fh.write(f"{name:35}: {value}\n")
        fh.close()
        local_file = fh.name
        s3_key = f"{self.assets_base_key}/config/ansible/ansible_head_node_vars.yml"
        s3_client.upload_file(
            local_file,
            self.assets_bucket,
            s3_key)

        ansible_compute_node_template_vars = self.get_instance_template_vars('ParallelClusterComputeNode')
        fh = NamedTemporaryFile('w', delete=False)
        fh.write('---\n')
        for name, value in sorted(ansible_compute_node_template_vars.items()):
            fh.write(f"{name:20}: {value}\n")
        fh.close()
        local_file = fh.name
        s3_key = f"{self.assets_base_key}/config/ansible/ansible_compute_node_vars.yml"
        s3_client.upload_file(
            local_file,
            self.assets_bucket,
            s3_key)

        ansible_submitter_template_vars = self.get_instance_template_vars('ParallelClusterSubmitter')
        fh = NamedTemporaryFile('w', delete=False)
        fh.write('---\n')
        for name, value in sorted(ansible_submitter_template_vars.items()):
            fh.write(f"{name:28}: {value}\n")
        fh.close()
        local_file = fh.name
        s3_key = f"{self.assets_base_key}/config/ansible/ansible_submitter_vars.yml"
        s3_client.upload_file(
            local_file,
            self.assets_bucket,
            s3_key)

        self.create_munge_ssm_parameter()

    def get_image_builder_parent_image(self, distribution, version, architecture):
        filters = [
            {'Name': 'architecture', 'Values': [architecture]},
            {'Name': 'is-public', 'Values': ['true']},
            {'Name': 'state', 'Values': ['available']},
        ]
        if distribution == 'Rocky':
            filters.extend(
                [
                    {'Name': 'owner-alias', 'Values': ['aws-marketplace']},
                    {'Name': 'name', 'Values': [f"Rocky-{version}-EC2-Base-{version}.*"]},
                ],
            )
        else:
            parallelcluster_version = self.config['slurm']['ParallelClusterConfig']['Version']
            filters.extend(
                [
                    {'Name': 'owner-alias', 'Values': ['amazon']},
                    {'Name': 'name', 'Values': [f"aws-parallelcluster-{parallelcluster_version}-{distribution}{version}*"]},
                ],
            )
        response = self.ec2_client.describe_images(
            Filters = filters
        )
        logger.debug(f"Images:\n{json.dumps(response['Images'], indent=4)}")
        images = sorted(response['Images'], key=lambda image: image['CreationDate'], reverse=True)
        image_id = images[0]['ImageId']
        return image_id

    def get_fpga_developer_image(self, distribution, version, architecture):
        valid_distributions = {
            'amzn': ['2'],
            'centos': ['7']
        }
        valid_architectures = ['x86_64']
        if distribution not in valid_distributions:
            return None
        if version not in valid_distributions[distribution]:
            return None
        if architecture not in valid_architectures:
            return None
        filters = [
            {'Name': 'architecture', 'Values': [architecture]},
            {'Name': 'is-public', 'Values': ['true']},
            {'Name': 'state', 'Values': ['available']},
        ]
        if distribution == 'amzn':
            name_filter = "FPGA Developer AMI(AL2) - *"
        elif distribution == 'centos':
            name_filter = "FPGA Developer AMI - *"
        filters.extend(
            [
                {'Name': 'owner-alias', 'Values': ['aws-marketplace']},
                {'Name': 'name', 'Values': [name_filter]},
            ],
        )
        response = self.ec2_client.describe_images(
            Filters = filters
        )
        logger.debug(f"Images:\n{json.dumps(response['Images'], indent=4)}")
        images = sorted(response['Images'], key=lambda image: image['CreationDate'], reverse=True)
        if not images:
            return None
        image_id = images[0]['ImageId']
        return image_id

    def get_ami_root_volume_size(self, image_id: str):
        response = self.ec2_client.describe_images(
            ImageIds = [image_id]
        )
        logger.debug(f"{json.dumps(response, indent=4)}")
        root_volume_size = response['Images'][0]['BlockDeviceMappings'][0]['Ebs']['VolumeSize']
        return root_volume_size

    def create_vpc(self):
        logger.info(f"VpcId: {self.config['VpcId']}")
        self.vpc = ec2.Vpc.from_lookup(self, "Vpc", vpc_id = self.config['VpcId'])
        self.private_and_isolated_subnets = self.vpc.private_subnets + self.vpc.isolated_subnets
        self.private_and_isolated_subnet_ids_map = {}
        for subnet in self.private_and_isolated_subnets:
            self.private_and_isolated_subnet_ids_map[subnet.subnet_id] = subnet
        if len(self.private_and_isolated_subnets) == 0:
            logger.error(f"{self.config['VpcId']} must have at least one private or isolated subnet.")
            logger.info(f"    {len(self.vpc.public_subnets)} public subnets")
            for subnet in self.vpc.public_subnets:
                logger.info(f"        {subnet.subnet_id}")
            logger.info(f"    {len(self.vpc.private_subnets)} private subnets")
            for subnet in self.vpc.private_subnets:
                logger.info(f"        {subnet.subnet_id}")
            logger.info(f"    {len(self.vpc.isolated_subnets)} isolated subnets")
            for subnet in self.vpc.isolated_subnets:
                logger.info(f"        {subnet.subnet_id}")
            exit(1)

        valid_subnet_ids = []
        if 'SubnetId' in self.config:
            self.subnet = None
            logger.info(f"Checking for {self.config['SubnetId']} in {len(self.private_and_isolated_subnets)} private and isolated subnets")
            for subnet in self.private_and_isolated_subnets:
                logger.info(f"    {subnet.subnet_id}")
                valid_subnet_ids.append(subnet.subnet_id)
                # If this is a new VPC then the cdk.context.json will not have the VPC and will be refreshed after the bootstrap phase. Until then the subnet ids will be placeholders so just pick the first subnet. After the bootstrap finishes the vpc lookup will be done and then the info will be correct.
                if subnet.subnet_id in ['p-12345', 'p-67890']:
                    logger.warning(f"VPC {self.config['VpcId']} not in cdk.context.json and will be refreshed before synth.")
                    self.subnet = subnet
                    break
                if subnet.subnet_id == self.config['SubnetId']:
                    self.subnet = subnet
                    break
            if not self.subnet:
                logger.error(f"SubnetId {self.config['SubnetId']} not found in VPC {self.config['VpcId']}\nValid subnet ids:\n{pp.pformat(valid_subnet_ids)}")
                exit(1)
        else:
            # Subnet not specified so pick the first private or isolated subnet
            self.subnet = self.private_and_isolated_subnets[0]
            self.config['SubnetId'] = self.subnet.subnet_id
        logger.info(f"Subnet set to {self.config['SubnetId']}")
        logger.info(f"availability zone: {self.subnet.availability_zone}")

    def check_regions_config(self):
        '''
        Do this after the VPC object has been created so that we can choose a default SubnetId.
        '''
        if 'Regions' not in self.config['slurm']['InstanceConfig']:
            self.config['slurm']['InstanceConfig']['Regions'] = {}
            self.config['slurm']['InstanceConfig']['Regions'][self.cluster_region] = {
                'VpcId': self.config['VpcId'],
                'CIDR': self.config['CIDR'],
                'SshKeyPair': self.config['SshKeyPair'],
                'AZs': [
                    {
                        'Priority': 1,
                        'Subnet': self.config['SubnetId']
                    }
                ]
            }
            logger.info(f"Added {self.cluster_region} to InstanceConfig:\n{json.dumps(self.config['slurm']['InstanceConfig'], indent=4)}")

        if len(self.config['slurm']['InstanceConfig']['Regions'].keys()) > 1:
            logger.error(f"Can only specify 1 region in slurm/InstanceConfig/Regions and it must be {self.cluster_region}")
            sys.exit(1)

        self.compute_regions = []
        self.remote_compute_regions = {}
        self.compute_region_cidrs_dict = {}
        for compute_region, region_dict in self.config['slurm']['InstanceConfig']['Regions'].items():
            if  compute_region != self.cluster_region:
                logger.error(f"Can only specify 1 region in slurm/InstanceConfig/Regions and it must be {self.cluster_region}")
                sys.exit(1)
            compute_region_cidr = region_dict['CIDR']
            if compute_region not in self.compute_regions:
                self.compute_regions.append(compute_region)
                if compute_region != self.cluster_region:
                    self.remote_compute_regions[compute_region] = compute_region_cidr
            if compute_region_cidr not in self.compute_region_cidrs_dict:
                self.compute_region_cidrs_dict[compute_region] = compute_region_cidr
        logger.info(f"{len(self.compute_regions)} regions configured: {sorted(self.compute_regions)}")

        self.eC2InstanceTypeInfo = EC2InstanceTypeInfo(self.compute_regions, get_savings_plans=False, json_filename='/tmp/instance_type_info.json', debug=False)

        self.plugin = SlurmPlugin(slurm_config_file=None, region=self.cluster_region)
        self.plugin.instance_type_and_family_info = self.eC2InstanceTypeInfo.instance_type_and_family_info
        self.az_info = self.plugin.get_az_info_from_instance_config(self.config['slurm']['InstanceConfig'])
        logger.info(f"{len(self.az_info.keys())} AZs configured: {sorted(self.az_info.keys())}")

        az_partitions = []
        for az, az_info in self.az_info.items():
            az_partitions.append(f"{az}_all")
        self.default_partition = ','.join(az_partitions)

        self.region_instance_types = self.plugin.get_instance_types_from_instance_config(self.config['slurm']['InstanceConfig'], self.compute_regions, self.eC2InstanceTypeInfo)
        self.instance_types = []
        for compute_region in self.compute_regions:
            region_instance_types = self.region_instance_types[compute_region]
            if len(region_instance_types) == 0:
                logger.error(f"No instance types found in region {compute_region}. Update slurm/InstanceConfig. Current value:\n{pp.pformat(self.config['slurm']['InstanceConfig'])}\n{region_instance_types}")
                sys.exit(1)
            logger.info(f"{len(region_instance_types)} instance types configured in {compute_region}:\n{pp.pformat(region_instance_types)}")
            for instance_type in region_instance_types:
                self.instance_types.append(instance_type)
        self.instance_types = sorted(self.instance_types)

        # Filter the instance types by architecture due to PC limitation to 1 architecture
        cluster_architecture = self.config['slurm']['ParallelClusterConfig']['Architecture']
        logger.info(f"ParallelCluster Architecture: {cluster_architecture}")
        filtered_instance_types = []
        for instance_type in self.instance_types:
            instance_architecture = self.plugin.get_architecture(self.cluster_region, instance_type)
            if instance_architecture != cluster_architecture:
                logger.warning(f"Excluding {instance_type} because architecture ({instance_architecture}) != {cluster_architecture}")
                continue
            filtered_instance_types.append(instance_type)
        self.instance_types = filtered_instance_types
        logger.info(f"ParallelCluster configured to use {len(self.instance_types)} instance types :\n{pp.pformat(self.instance_types)}")
        if len(self.instance_types) == 0:
            logger.error(f"No instance type configured. Update slurm/InstanceConfig with {cluster_architecture} instance types.")
            sys.exit(1)

        # Validate updated config against schema
        from config_schema import check_schema
        from schema import SchemaError
        try:
            validated_config = check_schema(self.config)
        except SchemaError:
            logger.exception(f"Invalid config")
            exit(1)
        self.config = validated_config

    def create_parallel_cluster_lambdas(self):
        self.create_callSlurmRestApiLambda()

        self.parallel_cluster_lambda_layer = aws_lambda.LayerVersion(self, "ParallelClusterLambdaLayer",
            description = 'ParallelCluster Layer',
            code = aws_lambda.Code.from_bucket(
                s3.Bucket.from_bucket_name(self, 'ParallelClusterBucket', f"{self.cluster_region}-aws-parallelcluster"),
                f"parallelcluster/{self.config['slurm']['ParallelClusterConfig']['Version']}/layers/aws-parallelcluster/lambda-layer.zip"
            ),
            compatible_architectures = [
                aws_lambda.Architecture.ARM_64,
                aws_lambda.Architecture.X86_64,
            ],
            compatible_runtimes = [
                aws_lambda.Runtime.PYTHON_3_9,
                aws_lambda.Runtime.PYTHON_3_10,
                # aws_lambda.Runtime.PYTHON_3_11, # Doesn't work: No module named 'rpds.rpds'
            ],
        )

        createParallelClusterLambdaAsset = s3_assets.Asset(self, "CreateParallelClusterAsset", path="resources/lambdas/CreateParallelCluster")
        self.create_parallel_cluster_lambda = aws_lambda.Function(
            self, "CreateParallelClusterLambda",
            function_name=f"{self.stack_name}-CreateParallelCluster",
            description="Create ParallelCluster from json string",
            memory_size=2048,
            runtime=aws_lambda.Runtime.PYTHON_3_9,
            architecture=aws_lambda.Architecture.X86_64,
            timeout=Duration.minutes(15),
            log_retention=logs.RetentionDays.INFINITE,
            handler="CreateParallelCluster.lambda_handler",
            code=aws_lambda.Code.from_bucket(createParallelClusterLambdaAsset.bucket, createParallelClusterLambdaAsset.s3_object_key),
            layers=[self.parallel_cluster_lambda_layer],
            vpc = self.vpc,
            allow_all_outbound = True
        )
        self.create_parallel_cluster_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    's3:*',
                ],
                resources=['*']
                )
            )
        self.create_parallel_cluster_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    '*',
                ],
                resources=['*']
                )
            )

    def create_callSlurmRestApiLambda(self):
        callSlurmRestApiLambdaAsset = s3_assets.Asset(self, "CallSlurmRestApiLambdaAsset", path="resources/lambdas/CallSlurmRestApi")
        self.call_slurm_rest_api_lambda = aws_lambda.Function(
            self, "CallSlurmRestApiLambda",
            function_name=f"{self.stack_name}-CallSlurmRestApiLambda",
            description="Example showing how to call Slurm REST API",
            memory_size=128,
            runtime=aws_lambda.Runtime.PYTHON_3_8,
            architecture=aws_lambda.Architecture.ARM_64,
            timeout=Duration.minutes(1),
            log_retention=logs.RetentionDays.INFINITE,
            handler="CallSlurmRestApi.lambda_handler",
            code=aws_lambda.Code.from_bucket(callSlurmRestApiLambdaAsset.bucket, callSlurmRestApiLambdaAsset.s3_object_key),
            vpc=self.vpc,
            vpc_subnets = ec2.SubnetSelection(subnets=[self.subnet]),
            security_groups = [self.slurm_rest_api_lambda_sg],
            environment = {
                'CLUSTER_NAME': f"{self.config['slurm']['ClusterName']}",
                'SLURM_REST_API_VERSION': self.config['slurm']['SlurmCtl']['SlurmRestApiVersion'],
                'SLURMRESTD_URL': f"http://slurmctl1.{self.config['slurm']['ClusterName']}.pcluster:{self.slurmrestd_port}"
                }
        )

        # Create an SSM parameter to store the JWT tokens for root and slurmrestd
        self.jwt_token_for_root_ssm_parameter_name = f"/{self.config['slurm']['ClusterName']}/slurmrestd/jwt/root"
        self.jwt_token_for_root_ssm_parameter = ssm.StringParameter(
            self, f"JwtTokenForRootParameter",
            parameter_name = self.jwt_token_for_root_ssm_parameter_name,
            string_value = 'None'
        )
        self.jwt_token_for_root_ssm_parameter.grant_read(self.call_slurm_rest_api_lambda)

        self.jwt_token_for_slurmrestd_ssm_parameter_name = f"/{self.config['slurm']['ClusterName']}/slurmrestd/jwt/slurmrestd"
        self.jwt_token_for_slurmrestd_ssm_parameter = ssm.StringParameter(
            self, f"JwtTokenForSlurmrestdParameter",
            parameter_name = self.jwt_token_for_slurmrestd_ssm_parameter_name,
            string_value = 'None'
        )
        self.jwt_token_for_slurmrestd_ssm_parameter.grant_read(self.call_slurm_rest_api_lambda)

    def create_security_groups(self):
        self.slurmctld_port_min = 6820
        self.slurmctld_port_max = 6829
        self.slurmctld_port = '6820-6829'
        self.slurmd_port = 6818
        self.slurmdbd_port = 6819
        self.slurmrestd_port = 6830

        self.imagebuilder_sg = ec2.SecurityGroup(self, "ImageBuilderSG", vpc=self.vpc, allow_all_outbound=True, description="ImageBuilder Security Group")
        Tags.of(self.imagebuilder_sg).add("Name", f"{self.stack_name}-ImageBuilderSG")

        self.nfs_sg = ec2.SecurityGroup(self, "NfsSG", vpc=self.vpc, allow_all_outbound=False, description="Nfs Security Group")
        Tags.of(self.nfs_sg).add("Name", f"{self.stack_name}-NfsSG")
        self.suppress_cfn_nag(self.nfs_sg, 'W29', 'Egress port range used to block all egress')

        # FSxZ requires all output access
        self.zfs_sg = ec2.SecurityGroup(self, "ZfsSG", vpc=self.vpc, allow_all_outbound=True, description="Zfs Security Group")
        Tags.of(self.zfs_sg).add("Name", f"{self.stack_name}-ZfsSG")
        self.suppress_cfn_nag(self.zfs_sg, 'W29', 'Egress port range used to block all egress')

        # Compute nodes may use lustre file systems so create a security group with the required ports.
        self.lustre_sg = ec2.SecurityGroup(self, "LustreSG", vpc=self.vpc, allow_all_outbound=False, description="Lustre Security Group")
        Tags.of(self.lustre_sg).add("Name", f"{self.stack_name}-LustreSG")
        self.suppress_cfn_nag(self.lustre_sg, 'W29', 'Egress port range used to block all egress')

        # These are the security groups that have client access to mount the extra file systems
        self.extra_mount_security_groups = {}
        for fs_type in self.config['slurm'].get('storage', {}).get('ExtraMountSecurityGroups', {}).keys():
            self.extra_mount_security_groups[fs_type] = {}
            for extra_mount_sg_name, extra_mount_sg_id in self.config['slurm']['storage']['ExtraMountSecurityGroups'][fs_type].items():
                (allow_all_outbound, allow_all_ipv6_outbound) = self.allow_all_outbound(extra_mount_sg_id)
                self.extra_mount_security_groups[fs_type][extra_mount_sg_name] = ec2.SecurityGroup.from_security_group_id(
                    self, f"{extra_mount_sg_name}{fs_type}",
                    security_group_id = extra_mount_sg_id,
                    allow_all_outbound = allow_all_outbound,
                    allow_all_ipv6_outbound = allow_all_ipv6_outbound
                )

        self.slurmctl_sg = ec2.SecurityGroup(self, "SlurmCtlSG", vpc=self.vpc, allow_all_outbound=False, description="SlurmCtl Security Group")
        self.slurmctl_sg_name = f"{self.stack_name}-SlurmCtlSG"
        Tags.of(self.slurmctl_sg).add("Name", self.slurmctl_sg_name)
        self.suppress_cfn_nag(self.slurmctl_sg, 'W29', 'Egress port range used to block all egress')

        if 'ExistingSlurmDbd' in self.config['slurm']:
            for slurmdbd_sg_name, slurmdbd_sg_id in self.config['slurm']['ExistingSlurmDbd']['SecurityGroup'].items():
                (allow_all_outbound, allow_all_ipv6_outbound) = self.allow_all_outbound(slurmdbd_sg_id)
                self.slurmdbd_sg = ec2.SecurityGroup.from_security_group_id(
                    self, f"{slurmdbd_sg_name}",
                    security_group_id = slurmdbd_sg_id,
                    allow_all_outbound = allow_all_outbound,
                    allow_all_ipv6_outbound = allow_all_ipv6_outbound
                )
                self.slurmdbd_sg_name = slurmdbd_sg_name
        elif 'SlurmDbd' in self.config['slurm']:
            self.slurmdbd_sg = ec2.SecurityGroup(self, "SlurmDbdSG", vpc=self.vpc, allow_all_outbound=False, description="SlurmDbd Security Group")
            self.slurmdbd_sg_name = f"{self.stack_name}-SlurmDbdSG"
            Tags.of(self.slurmdbd_sg).add("Name", self.slurmdbd_sg_name)
        else:
            self.slurmdbd_sg = None
        if self.slurmdbd_sg:
            self.suppress_cfn_nag(self.slurmdbd_sg, 'W29', 'Egress port range used to block all egress')

        self.slurmnode_sg = ec2.SecurityGroup(self, "SlurmNodeSG", vpc=self.vpc, allow_all_outbound=False, description="SlurmNode Security Group")
        self.slurmnode_sg_name = f"{self.stack_name}-SlurmNodeSG"
        Tags.of(self.slurmnode_sg).add("Name", self.slurmnode_sg_name)
        self.suppress_cfn_nag(self.slurmnode_sg, 'W29', 'Egress port range used to block all egress')

        self.federated_slurmctl_sgs = {}
        if 'Federation' in self.config['slurm']:
            for federated_slurmctl_sg_name, federated_slurmctl_sg_id in self.config['slurm']['Federation']['SlurmCtlSecurityGroups'].items():
                (allow_all_outbound, allow_all_ipv6_outbound) = self.allow_all_outbound(federated_slurmctl_sg_id)
                federated_slurmctl_sg = ec2.SecurityGroup.from_security_group_id(
                    self, f"{federated_slurmctl_sg_name}",
                    security_group_id = federated_slurmctl_sg_id,
                    allow_all_outbound = allow_all_outbound,
                    allow_all_ipv6_outbound = allow_all_ipv6_outbound
                )
                self.federated_slurmctl_sgs[federated_slurmctl_sg_name] = federated_slurmctl_sg
                federated_slurmctl_sg.connections.allow_to(self.slurmnode_sg, ec2.Port.tcp(self.slurmd_port), f"{federated_slurmctl_sg_name} to {self.slurmnode_sg_name}")
                if self.onprem_cidr:
                    federated_slurmctl_sg.connections.allow_to(self.onprem_cidr, ec2.Port.tcp(self.slurmd_port), f"{federated_slurmctl_sg_name} to OnPremNodes")

        self.federated_slurmnode_sgs = {}
        if 'Federation' in self.config['slurm']:
            for federated_slurmnode_sg_name, federated_slurmnode_sg_id in self.config['slurm']['Federation']['SlurmNodeSecurityGroups'].items():
                (allow_all_outbound, allow_all_ipv6_outbound) = self.allow_all_outbound(federated_slurmnode_sg_id)
                federated_slurmnode_sg = ec2.SecurityGroup.from_security_group_id(
                    self, f"{federated_slurmnode_sg_name}",
                    security_group_id = federated_slurmnode_sg_id,
                    allow_all_outbound = allow_all_outbound,
                    allow_all_ipv6_outbound = allow_all_ipv6_outbound
                )
                self.federated_slurmnode_sgs[federated_slurmnode_sg_name] = federated_slurmnode_sg

        self.submitter_security_groups = {}
        self.slurm_submitter_sg = ec2.SecurityGroup(self, "SlurmSubmitterSG", vpc=self.vpc, allow_all_outbound=False, description="SlurmSubmitter Security Group")
        self.slurm_submitter_sg_name = f"{self.stack_name}-SlurmSubmitterSG"
        Tags.of(self.slurm_submitter_sg).add("Name", self.slurm_submitter_sg_name)
        self.suppress_cfn_nag(self.slurm_submitter_sg, 'W29', 'Egress port range used to block all egress')
        self.submitter_security_groups[self.slurm_submitter_sg_name] = self.slurm_submitter_sg
        for slurm_submitter_sg_name, slurm_submitter_sg_id in self.config['slurm']['SubmitterSecurityGroupIds'].items():
            (allow_all_outbound, allow_all_ipv6_outbound) = self.allow_all_outbound(slurm_submitter_sg_id)
            self.submitter_security_groups[slurm_submitter_sg_name] = ec2.SecurityGroup.from_security_group_id(
                self, f"{slurm_submitter_sg_name}",
                security_group_id = slurm_submitter_sg_id,
                allow_all_outbound = allow_all_outbound,
                allow_all_ipv6_outbound = allow_all_ipv6_outbound
            )

        self.slurm_rest_api_lambda_sg = ec2.SecurityGroup(self, "SlurmRestLambdaSG", vpc=self.vpc, allow_all_outbound=False, description="SlurmRestApiLambda to SlurmCtl Security Group")
        self.slurm_rest_api_lambda_sg_name = f"{self.stack_name}-SlurmRestApiLambdaSG"
        Tags.of(self.slurm_rest_api_lambda_sg).add("Name", self.slurm_rest_api_lambda_sg_name)
        self.slurm_rest_api_lambda_sg.add_egress_rule(ec2.Peer.ipv4("0.0.0.0/0"), ec2.Port.tcp(443), description=f"{self.slurm_rest_api_lambda_sg_name} to {self.slurmctl_sg_name} - TLS")

        # Security Group Rules

        # NFS Connections
        fs_client_sgs = {
            "SlurmCtl": self.slurmctl_sg,
            "SlurmNode": self.slurmnode_sg,
            **self.submitter_security_groups
        }
        if self.slurmdbd_sg and 'ExistingSlurmDbd' not in self.config['slurm']:
            fs_client_sgs['SlurmDbd'] = self.slurmdbd_sg
        for fs_client_sg_name, fs_client_sg in fs_client_sgs.items():
            fs_client_sg.connections.allow_to(self.nfs_sg, ec2.Port.tcp(2049), f"{fs_client_sg_name} to Nfs")
        if self.onprem_cidr:
            self.nfs_sg.connections.allow_from(self.onprem_cidr, ec2.Port.tcp(2049), 'OnPremNodes to Nfs')
        # Allow compute nodes in remote regions access to NFS
        for compute_region, compute_region_cidr in self.remote_compute_regions.items():
            self.nfs_sg.connections.allow_from(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.tcp(2049), f"{compute_region} to Nfs")

        # ZFS Connections
        # https://docs.aws.amazon.com/fsx/latest/OpenZFSGuide/limit-access-security-groups.html
        for fs_client_sg_name, fs_client_sg in fs_client_sgs.items():
            fs_client_sg.connections.allow_to(self.zfs_sg, ec2.Port.tcp(111), f"{fs_client_sg_name} to Zfs")
            fs_client_sg.connections.allow_to(self.zfs_sg, ec2.Port.udp(111), f"{fs_client_sg_name} to Zfs")
            fs_client_sg.connections.allow_to(self.zfs_sg, ec2.Port.tcp(2049), f"{fs_client_sg_name} to Zfs")
            fs_client_sg.connections.allow_to(self.zfs_sg, ec2.Port.udp(2049), f"{fs_client_sg_name} to Zfs")
            fs_client_sg.connections.allow_to(self.zfs_sg, ec2.Port.tcp_range(20001, 20003), f"{fs_client_sg_name} to Zfs")
            fs_client_sg.connections.allow_to(self.zfs_sg, ec2.Port.udp_range(20001, 20003), f"{fs_client_sg_name} to Zfs")
            self.suppress_cfn_nag(fs_client_sg, 'W27', 'Correct, restricted range for zfs: 20001-20003')
            self.suppress_cfn_nag(fs_client_sg, 'W29', 'Correct, restricted range for zfs: 20001-20003')
        self.suppress_cfn_nag(self.zfs_sg, 'W27', 'Correct, restricted range for zfs: 20001-20003')
        if self.onprem_cidr:
            self.zfs_sg.connections.allow_from(self.onprem_cidr, ec2.Port.tcp(111), 'OnPremNodes to Zfs')
            self.zfs_sg.connections.allow_from(self.onprem_cidr, ec2.Port.udp(111), 'OnPremNodes to Zfs')
            self.zfs_sg.connections.allow_from(self.onprem_cidr, ec2.Port.tcp(2049), 'OnPremNodes to Zfs')
            self.zfs_sg.connections.allow_from(self.onprem_cidr, ec2.Port.udp(2049), 'OnPremNodes to Zfs')
            self.zfs_sg.connections.allow_from(self.onprem_cidr, ec2.Port.tcp_range(20001, 20003), 'OnPremNodes to Zfs')
            self.zfs_sg.connections.allow_from(self.onprem_cidr, ec2.Port.udp_range(20001, 20003), 'OnPremNodes to Zfs')
            self.suppress_cfn_nag(self.zfs_sg, 'W27', 'Correct, restricted range for zfs: 20001-20003')
            self.suppress_cfn_nag(self.zfs_sg, 'W29', 'Correct, restricted range for zfs: 20001-20003')
        # Allow compute nodes in remote regions access to ZFS
        for compute_region, compute_region_cidr in self.remote_compute_regions.items():
            self.zfs_sg.connections.allow_from(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.tcp(111), f"{compute_region} to Zfs")
            self.zfs_sg.connections.allow_from(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.udp(111), f"{compute_region} to Zfs")
            self.zfs_sg.connections.allow_from(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.tcp(2049), f"{compute_region} to Zfs")
            self.zfs_sg.connections.allow_from(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.udp(2049), f"{compute_region} to Zfs")
            self.zfs_sg.connections.allow_from(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.tcp_range(20001, 20003), f"{compute_region} to Zfs")
            self.zfs_sg.connections.allow_from(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.udp_range(20001, 20003), f"{compute_region} to Zfs")

        # Lustre Connections
        lustre_fs_client_sgs = copy(fs_client_sgs)
        lustre_fs_client_sgs['Lustre'] = self.lustre_sg
        for fs_client_sg_name, fs_client_sg in lustre_fs_client_sgs.items():
            fs_client_sg.connections.allow_to(self.lustre_sg, ec2.Port.tcp(988), f"{fs_client_sg_name} to Lustre")
            fs_client_sg.connections.allow_to(self.lustre_sg, ec2.Port.tcp_range(1021, 1023), f"{fs_client_sg_name} to Lustre")
            self.lustre_sg.connections.allow_to(fs_client_sg, ec2.Port.tcp(988), f"Lustre to {fs_client_sg_name}")
            self.lustre_sg.connections.allow_to(fs_client_sg, ec2.Port.tcp_range(1021, 1023), f"Lustre to {fs_client_sg_name}")
            self.suppress_cfn_nag(fs_client_sg, 'W27', 'Correct, restricted range for lustre: 1021-1023')
            self.suppress_cfn_nag(fs_client_sg, 'W29', 'Correct, restricted range for lustre: 1021-1023')
        self.lustre_sg.connections.allow_from(self.lustre_sg, ec2.Port.tcp(988), f"Lustre to Lustre")
        self.lustre_sg.connections.allow_from(self.lustre_sg, ec2.Port.tcp_range(1021, 1023), f"Lustre to Lustre")
        self.suppress_cfn_nag(self.lustre_sg, 'W27', 'Correct, restricted range for lustre: 1021-1023')
        if self.onprem_cidr:
            self.lustre_sg.connections.allow_from(self.onprem_cidr, ec2.Port.tcp(988), 'OnPremNodes to Lustre')
            self.lustre_sg.connections.allow_from(self.onprem_cidr, ec2.Port.tcp_range(1021, 1023), 'OnPremNodes to Lustre')
            self.lustre_sg.connections.allow_to(self.onprem_cidr, ec2.Port.tcp(988), f"Lustre to OnPremNodes")
            self.lustre_sg.connections.allow_to(self.onprem_cidr, ec2.Port.tcp_range(1021, 1023), f"Lustre to OnPremNodes")
        # Allow compute nodes in remote regions access to Lustre
        for compute_region, compute_region_cidr in self.remote_compute_regions.items():
            self.lustre_sg.connections.allow_from(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.tcp(988), f"{compute_region} to Lustre")
            self.lustre_sg.connections.allow_from(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.tcp_range(1021, 1023), f"{compute_region} to Lustre")
            self.lustre_sg.connections.allow_to(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.tcp(988), f"Lustre to {compute_region}")
            self.lustre_sg.connections.allow_to(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.tcp_range(1021, 1023), f"Lustre to {compute_region}")

        for fs_type in self.extra_mount_security_groups.keys():
            for extra_mount_sg_name, extra_mount_sg in self.extra_mount_security_groups[fs_type].items():
                if fs_type in ['nfs', 'zfs']:
                    self.slurmnode_sg.connections.allow_to(extra_mount_sg, ec2.Port.tcp(2049), f"SlurmNode to {extra_mount_sg_name} - Nfs")
                    if fs_type == 'zfs':
                        self.slurmnode_sg.connections.allow_to(extra_mount_sg, ec2.Port.tcp(111), f"SlurmNode to {extra_mount_sg_name} - Zfs")
                        self.slurmnode_sg.connections.allow_to(extra_mount_sg, ec2.Port.udp(111), f"SlurmNode to {extra_mount_sg_name} - Zfs")
                        self.slurmnode_sg.connections.allow_to(extra_mount_sg, ec2.Port.udp(2049), f"SlurmNode to {extra_mount_sg_name} - Zfs")
                        self.slurmnode_sg.connections.allow_to(extra_mount_sg, ec2.Port.tcp_range(20001, 20003), f"SlurmNode to {extra_mount_sg_name} - Zfs")
                        self.slurmnode_sg.connections.allow_to(extra_mount_sg, ec2.Port.udp_range(20001, 20003), f"SlurmNode to {extra_mount_sg_name} - Zfs")
                        self.suppress_cfn_nag(self.slurmnode_sg, 'W27', 'Correct, restricted range for zfs: 20001-20003')
                        self.suppress_cfn_nag(self.slurmnode_sg, 'W29', 'Correct, restricted range for zfs: 20001-20003')
                elif fs_type == 'lustre':
                    self.slurmnode_sg.connections.allow_to(self.lustre_sg, ec2.Port.tcp(988), f"SlurmNode to {extra_mount_sg_name} - Lustre")
                    self.slurmnode_sg.connections.allow_to(self.lustre_sg, ec2.Port.tcp_range(1021, 1023), f"SlurmNode to {extra_mount_sg_name} - Lustre")
                    self.lustre_sg.connections.allow_to(self.slurmnode_sg, ec2.Port.tcp(988), f"{extra_mount_sg_name} to SlurmNode")
                    self.lustre_sg.connections.allow_to(fs_client_sg, ec2.Port.tcp_range(1021, 1023), f"{extra_mount_sg_name} to SlurmNode")
                    self.suppress_cfn_nag(self.slurmnode_sg, 'W27', 'Correct, restricted range for lustre: 1021-1023')
                    self.suppress_cfn_nag(self.slurmnode_sg, 'W29', 'Correct, restricted range for lustre: 1021-1023')

        # slurmctl connections
        # egress
        self.slurmctl_sg.connections.allow_from(self.slurmctl_sg, ec2.Port.tcp_range(self.slurmctld_port_min, self.slurmctld_port_max), f"{self.slurmctl_sg_name} to {self.slurmctl_sg_name}")
        self.slurmctl_sg.connections.allow_to(self.slurmctl_sg, ec2.Port.tcp_range(self.slurmctld_port_min, self.slurmctld_port_max), f"{self.slurmctl_sg_name} to {self.slurmctl_sg_name}")
        self.slurmctl_sg.connections.allow_to(self.slurmnode_sg, ec2.Port.tcp(self.slurmd_port), f"{self.slurmctl_sg_name} to {self.slurmnode_sg_name}")
        if self.slurmdbd_sg:
            self.slurmctl_sg.connections.allow_to(self.slurmdbd_sg, ec2.Port.tcp(self.slurmdbd_port), f"{self.slurmctl_sg_name} to {self.slurmdbd_sg_name} - Write job information")
        if 'ExistingSlurmDbd' in self.config['slurm']:
            self.slurmdbd_sg.connections.allow_from(self.slurmctl_sg, ec2.Port.tcp(self.slurmdbd_port), f"{self.slurmctl_sg_name} to {self.slurmdbd_sg_name} - Write job information")
        for slurm_submitter_sg_name, slurm_submitter_sg in self.submitter_security_groups.items():
            self.slurmctl_sg.connections.allow_to(slurm_submitter_sg, ec2.Port.tcp_range(1024, 65535), f"{self.slurmctl_sg_name} to {slurm_submitter_sg_name} - srun")
            self.suppress_cfn_nag(slurm_submitter_sg, 'W27', 'Port range ok. slurmctl requires requires ephemeral ports to submitter for srun: 1024-65535')
        self.suppress_cfn_nag(self.slurmctl_sg, 'W27', 'Port range ok. slurmctl requires requires ephemeral ports to submitter for srun: 1024-65535')
        self.slurmctl_sg.add_egress_rule(ec2.Peer.ipv4("0.0.0.0/0"), ec2.Port.tcp(80), description="Internet")
        self.slurmctl_sg.add_egress_rule(ec2.Peer.ipv4("0.0.0.0/0"), ec2.Port.tcp(443), description="Internet")
        self.suppress_cfn_nag(self.slurmctl_sg, 'W5', 'Egress to internet required to install packages and slurm software')
        for federated_slurmctl_sg_name, federated_slurmctl_sg in self.federated_slurmctl_sgs.items():
            self.slurmctl_sg.connections.allow_from(federated_slurmctl_sg, ec2.Port.tcp_range(self.slurmctld_port_min, self.slurmctld_port_max), f"{federated_slurmctl_sg_name} to {self.slurmctl_sg_name}")
            self.slurmctl_sg.connections.allow_to(federated_slurmctl_sg, ec2.Port.tcp_range(self.slurmctld_port_min, self.slurmctld_port_max), f"{self.slurmctl_sg_name} to {federated_slurmctl_sg_name}")
        for federated_slurmnode_sg_name, federated_slurmnode_sg in self.federated_slurmnode_sgs.items():
            self.slurmctl_sg.connections.allow_to(federated_slurmnode_sg, ec2.Port.tcp(self.slurmd_port), f"{self.slurmctl_sg_name} to {federated_slurmnode_sg_name}")
        if self.onprem_cidr:
            self.slurmctl_sg.connections.allow_to(self.onprem_cidr, ec2.Port.tcp(self.slurmd_port), f'{self.slurmctl_sg_name} to OnPremNodes')
            self.slurmctl_sg.connections.allow_from(self.onprem_cidr, ec2.Port.tcp_range(self.slurmctld_port_min, self.slurmctld_port_max), f'OnPremNodes to {self.slurmctl_sg_name}')
        for compute_region, compute_region_cidr in self.remote_compute_regions.items():
            self.slurmctl_sg.connections.allow_to(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.tcp(self.slurmd_port), f"{self.slurmctl_sg_name} to {compute_region}")
        self.slurmctl_sg.connections.allow_from(self.slurm_rest_api_lambda_sg, ec2.Port.tcp(self.slurmrestd_port), f"{self.slurm_rest_api_lambda_sg_name} to {self.slurmctl_sg_name} - slurmrestd")
        # slurmdbd connections
        # egress
        if self.slurmdbd_sg:
            self.slurmdbd_sg.connections.allow_to(self.slurmctl_sg, ec2.Port.tcp_range(self.slurmctld_port_min, self.slurmctld_port_max), f"{self.slurmdbd_sg_name} to {self.slurmctl_sg_name}")
            # @todo Does slurmdbd really need ephemeral access to slurmctl?
            # self.slurmdbd_sg.connections.allow_to(self.slurmctl_sg, ec2.Port.tcp_range(1024, 65535), f"{self.slurmdbd_sg_name} to {self.slurmctl_sg_name} - Ephemeral")
            if 'ExistingSlurmDbd' not in self.config['slurm']:
                self.slurmdbd_sg.add_egress_rule(ec2.Peer.ipv4("0.0.0.0/0"), ec2.Port.tcp(80), description="Internet")
                self.slurmdbd_sg.add_egress_rule(ec2.Peer.ipv4("0.0.0.0/0"), ec2.Port.tcp(443), description="Internet")
                self.suppress_cfn_nag(self.slurmdbd_sg, 'W5', 'Egress to internet required to install packages and slurm software')

        # slurmnode connections
        # egress
        self.slurmnode_sg.connections.allow_to(self.slurmctl_sg, ec2.Port.tcp_range(self.slurmctld_port_min, self.slurmctld_port_max), f"{self.slurmnode_sg_name} to {self.slurmctl_sg_name}")
        self.slurmnode_sg.connections.allow_to(self.slurmnode_sg, ec2.Port.tcp(self.slurmd_port), f"{self.slurmnode_sg_name} to {self.slurmnode_sg_name}")
        self.slurmnode_sg.connections.allow_to(self.slurmctl_sg, ec2.Port.tcp(self.slurmrestd_port), f"{self.slurmnode_sg_name} to {self.slurmctl_sg_name} - slurmrestd")
        self.slurmnode_sg.connections.allow_to(self.slurmnode_sg, ec2.Port.tcp_range(1024, 65535), f"{self.slurmnode_sg_name} to {self.slurmnode_sg_name} - ephemeral")
        self.suppress_cfn_nag(self.slurmnode_sg, 'W27', 'Port range ok. slurmnode requires requires ephemeral ports to other slurmnodes: 1024-65535')
        for slurm_submitter_sg_name, slurm_submitter_sg in self.submitter_security_groups.items():
            self.slurmnode_sg.connections.allow_to(slurm_submitter_sg, ec2.Port.tcp_range(6000, 7024), f"{self.slurmnode_sg_name} to {slurm_submitter_sg_name} - x11")
            # @todo Not sure if this is really initiated from the slurm node
            self.slurmnode_sg.connections.allow_to(slurm_submitter_sg, ec2.Port.tcp_range(1024, 65535), f"{self.slurmnode_sg_name} to {slurm_submitter_sg_name} - ephemeral")
            self.suppress_cfn_nag(slurm_submitter_sg, 'W27', 'Port range ok. slurmnode requires requires ephemeral ports to slurm submitters: 1024-65535')
            if self.onprem_cidr:
                slurm_submitter_sg.connections.allow_from(self.onprem_cidr, ec2.Port.tcp_range(6000, 7024), f"OnPremNodes to {slurm_submitter_sg_name} - x11")
                # @todo Not sure if this is really initiated from the slurm node
                self.slurmnode_sg.connections.allow_from(self.onprem_cidr, ec2.Port.tcp_range(1024, 65535), f"OnPremNodes to {slurm_submitter_sg_name} - ephemeral")
            for compute_region, compute_region_cidr in self.remote_compute_regions.items():
                slurm_submitter_sg.connections.allow_from(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.tcp_range(6000, 7024), f"{compute_region} to {slurm_submitter_sg_name} - x11")
                # @todo Not sure if this is really initiated from the slurm node
                slurm_submitter_sg.connections.allow_from(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.tcp_range(1024, 65535), f"{compute_region} to {slurm_submitter_sg_name} - ephemeral")
        self.suppress_cfn_nag(self.slurmnode_sg, 'W27', 'Port range ok. slurmnode requires requires ephemeral ports to slurm submitters: 1024-65535')
        self.slurmnode_sg.add_egress_rule(ec2.Peer.ipv4("0.0.0.0/0"), ec2.Port.tcp(80), description="Internet")
        self.slurmnode_sg.add_egress_rule(ec2.Peer.ipv4("0.0.0.0/0"), ec2.Port.tcp(443), description="Internet")
        self.suppress_cfn_nag(self.slurmnode_sg, 'W5', 'Egress to internet required to install packages and slurm software')
        for federated_slurmnode_sg_name, federated_slurmnode_sg in self.federated_slurmnode_sgs.items():
            federated_slurmnode_sg.connections.allow_to(self.slurmctl_sg, ec2.Port.tcp_range(self.slurmctld_port_min, self.slurmctld_port_max), f"{federated_slurmnode_sg_name} to {self.slurmctl_sg_name}")
            self.slurmnode_sg.connections.allow_to(federated_slurmnode_sg, ec2.Port.tcp(self.slurmd_port), f"{self.slurmnode_sg_name} to {federated_slurmnode_sg_name}")
            self.slurmnode_sg.connections.allow_to(federated_slurmnode_sg, ec2.Port.tcp_range(1024, 65535), f"{self.slurmnode_sg_name} to {federated_slurmnode_sg_name} - ephemeral")
            if self.onprem_cidr:
                federated_slurmnode_sg.connections.allow_from(self.onprem_cidr, ec2.Port.tcp(self.slurmd_port), f"OnPremNodes to {federated_slurmnode_sg_name}")
                self.federated_slurmnode_sg.connections.allow_to(self.onprem_cidr, ec2.Port.tcp_range(1024, 65535), f"OnPremNodes to {federated_slurmnode_sg_name} - ephemeral")
        if self.onprem_cidr:
            self.slurmnode_sg.connections.allow_from(self.onprem_cidr, ec2.Port.tcp(self.slurmd_port), f"OnPremNodes to {self.slurmnode_sg_name}")
            self.slurmnode_sg.connections.allow_from(self.onprem_cidr, ec2.Port.tcp_range(1024, 65535), f"OnPremNodes to {self.slurmnode_sg_name}")
        for compute_region, compute_region_cidr in self.remote_compute_regions.items():
            self.slurmctl_sg.connections.allow_from(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.tcp_range(self.slurmctld_port_min, self.slurmctld_port_max), f"{compute_region} to {self.slurmctl_sg_name}")
            self.slurmnode_sg.connections.allow_from(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.tcp(self.slurmd_port), f"{compute_region} to {self.slurmnode_sg_name}")
            self.slurmnode_sg.connections.allow_to(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.tcp(self.slurmd_port), f"{self.slurmnode_sg_name} to {compute_region}")
            self.slurmnode_sg.connections.allow_from(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.tcp_range(1024, 65535), f"{compute_region} to {self.slurmnode_sg_name}")
            self.slurmnode_sg.connections.allow_to(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.tcp_range(1024, 65535), f"{self.slurmnode_sg_name} to {compute_region}")

        # slurm submitter connections
        # egress
        for slurm_submitter_sg_name, slurm_submitter_sg in self.submitter_security_groups.items():
            slurm_submitter_sg.connections.allow_to(self.slurmctl_sg, ec2.Port.tcp_range(self.slurmctld_port_min, self.slurmctld_port_max), f"{slurm_submitter_sg_name} to {self.slurmctl_sg_name}")
            slurm_submitter_sg.connections.allow_to(self.slurmnode_sg, ec2.Port.tcp(self.slurmd_port), f"{slurm_submitter_sg_name} to {self.slurmnode_sg_name} - srun")
            if self.slurmdbd_sg:
                slurm_submitter_sg.connections.allow_to(self.slurmdbd_sg, ec2.Port.tcp(self.slurmdbd_port), f"{slurm_submitter_sg_name} to {self.slurmdbd_sg_name} - sacct")
            slurm_submitter_sg.connections.allow_to(self.slurmctl_sg, ec2.Port.tcp(self.slurmrestd_port), f"{slurm_submitter_sg_name} to {self.slurmctl_sg_name} - slurmrestd")
            if self.onprem_cidr:
                slurm_submitter_sg.connections.allow_to(self.onprem_cidr, ec2.Port.tcp(self.slurmd_port), f"{slurm_submitter_sg_name} to OnPremNodes - srun")
            for compute_region, compute_region_cidr in self.remote_compute_regions.items():
                slurm_submitter_sg.connections.allow_to(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.tcp(self.slurmd_port), f"{slurm_submitter_sg_name} to {compute_region} - srun")

        # Try to suppress cfn_nag warnings on ingress/egress rules
        for slurm_submitter_sg_name, slurm_submitter_sg in self.submitter_security_groups.items():
            self.suppress_cfn_nag(self.slurmnode_sg, 'W27', 'Port range ok. slurmsubmitter requires ephemeral ports for several reasons: 1024-65535')

    def allow_all_outbound(self, security_group_id: str):
        allow_all_outbound = False
        allow_all_ipv6_outbound = False
        egress_rules = self.ec2_client.describe_security_groups(GroupIds=[security_group_id])['SecurityGroups'][0]['IpPermissionsEgress']
        for egress_rule in egress_rules:
            if 'FromPort' not in egress_rule and 'ToPort' not in egress_rule and egress_rule['IpProtocol'] == '-1' and egress_rule.get('IpRanges', []) and egress_rule['IpRanges'][0].get('CidrIp', '') == '0.0.0.0/0':
                allow_all_outbound = True
            if 'FromPort' not in egress_rule and 'ToPort' not in egress_rule and egress_rule['IpProtocol'] == '-1' and egress_rule.get('Ipv6Ranges', []) and egress_rule['Ipv6Ranges'][0]['CidrIpv6'] == '::/0':
                allow_all_ipv6_outbound = True
        return (allow_all_outbound, allow_all_ipv6_outbound)

    def get_instance_template_vars(self, instance_role):

        # instance_template_vars is used to create environment variables,
        # extra ansible variables, and to use jinja2 to template user data scripts.
        # The keys are the environment and ansible variable names.
        cluster_name = self.config['slurm']['ClusterName']
        if instance_role.startswith('ParallelCluster'):
            instance_template_vars = {
                "AWS_DEFAULT_REGION": self.cluster_region,
                "ClusterName": cluster_name,
                "Region": self.cluster_region,
                "TimeZone": self.config['TimeZone'],
            }
            instance_template_vars['DefaultPartition'] = 'batch'
            instance_template_vars['FileSystemMountPath'] = '/opt/slurm'
            instance_template_vars['ParallelClusterVersion'] = self.config['slurm']['ParallelClusterConfig']['Version']
            instance_template_vars['SlurmBaseDir'] = '/opt/slurm'
            instance_template_vars['SlurmOSDir'] = '/opt/slurm'
            instance_template_vars['SlurmVersion'] =  get_SLURM_VERSION(self.config)

        if instance_role == 'ParallelClusterHeadNode':
            if 'Database' in self.config['slurm']['ParallelClusterConfig']:
                instance_template_vars['AccountingStorageHost'] = 'pcvluster-head-node'
            else:
                instance_template_vars['AccountingStorageHost'] = ''
            instance_template_vars['Licenses'] = self.config['Licenses']
            instance_template_vars['ParallelClusterMungeVersion'] = get_PARALLEL_CLUSTER_MUNGE_VERSION(self.config)
            instance_template_vars['ParallelClusterPythonVersion'] = get_PARALLEL_CLUSTER_PYTHON_VERSION(self.config)
            instance_template_vars['PrimaryController'] = True
            instance_template_vars['SlurmctldPort'] = self.slurmctld_port
            instance_template_vars['SlurmctldPortMin'] = self.slurmctld_port_min
            instance_template_vars['SlurmctldPortMax'] = self.slurmctld_port_max
            instance_template_vars['SlurmrestdJwtForRootParameter'] = self.jwt_token_for_root_ssm_parameter_name
            instance_template_vars['SlurmrestdJwtForSlurmrestdParameter'] = self.jwt_token_for_slurmrestd_ssm_parameter_name
            instance_template_vars['SlurmrestdPort'] = self.slurmrestd_port
            instance_template_vars['SlurmrestdSocketDir'] = '/opt/slurm/com'
            instance_template_vars['SlurmrestdSocket'] = f"{instance_template_vars['SlurmrestdSocketDir']}/slurmrestd.socket"
            instance_template_vars['SlurmrestdUid'] = self.config['slurm']['SlurmCtl']['SlurmrestdUid']
        elif instance_role == 'ParallelClusterSubmitter':
            instance_template_vars['FileSystemMountPath'] = f'/opt/slurm/{cluster_name}'
            instance_template_vars['ParallelClusterMungeVersion'] = get_PARALLEL_CLUSTER_MUNGE_VERSION(self.config)
            instance_template_vars['SlurmBaseDir'] = f'/opt/slurm/{cluster_name}'
            instance_template_vars['SlurmOSDir'] = f'/opt/slurm/{cluster_name}'

        elif instance_role == 'ParallelClusterComputeNode':
            pass
        else:
            raise ValueError(f"Invalid instance role {instance_role}")

        return instance_template_vars

    def create_munge_ssm_parameter(self):
        ssm_client = boto3.client('ssm', region_name=self.cluster_region)
        response = ssm_client.describe_parameters(
            ParameterFilters = [
                {
                    'Key': 'Name',
                    'Option': 'Equals',
                    'Values': [self.config['slurm']['MungeKeySsmParameter']]
                }
            ]
        )['Parameters']
        if response:
            logger.info(f"{self.config['slurm']['MungeKeySsmParameter']} SSM parameter exists and will be used.")
            self.munge_key_ssm_parameter = ssm.StringParameter.from_string_parameter_name(
                self, f"MungeKeySsmParamter",
                string_parameter_name  = f"{self.config['slurm']['MungeKeySsmParameter']}"
            )
        else:
            logger.info(f"{self.config['slurm']['MungeKeySsmParameter']} SSM parameter doesn't exist. Creating it so can give IAM permissions to it.")
            output = check_output(['dd if=/dev/random bs=1 count=1024 | base64 -w 0'], shell=True, stderr=subprocess.DEVNULL, encoding='utf8', errors='ignore')
            munge_key = output.split('\n')[0]
            self.munge_key_ssm_parameter = ssm.StringParameter(
                self, f"MungeKeySsmParamter",
                parameter_name  = f"{self.config['slurm']['MungeKeySsmParameter']}",
                string_value = f"{munge_key}"
            )

    def create_fault_injection_templates(self):
        self.fis_spot_termination_role = iam.Role(
            self, "FISSpotTerminationRole",
            assumed_by=iam.CompositePrincipal(
                iam.ServicePrincipal(self.principals_suffix["ec2"]),
                iam.ServicePrincipal(self.principals_suffix["fis"])
            ),
            inline_policies = {
                'spot_termination': iam.PolicyDocument(
                    statements = [
                        iam.PolicyStatement(
                            effect = iam.Effect.ALLOW,
                            actions = [
                                'ec2:DescribeInstances'
                            ],
                            # Does not support resource-level permissions and require you to choose All resources
                            resources = ["*"]
                        ),
                        iam.PolicyStatement(
                            effect = iam.Effect.ALLOW,
                            actions = [
                                'ec2:RebootInstances',
                                'ec2:SendSpotInstanceInterruptions',
                                'ec2:StartInstances',
                                'ec2:StopInstances',
                                'ec2:TerminateInstances'
                            ],
                            resources = [f"arn:{Aws.PARTITION}:ec2:*:{Aws.ACCOUNT_ID}:instance/*"]
                        )
                    ]
                )
            }
        )
        self.suppress_cfn_nag(self.fis_spot_termination_role, "W11", "ec2:DescribeInstances does not support resource-level permissions")

        fis_log_group = logs.LogGroup(
            self,
            "FISLogGroup",
            retention = logs.RetentionDays.TEN_YEARS
            )
        fis_log_group.grant_write(self.fis_spot_termination_role)
        fis_log_configuration = fis.CfnExperimentTemplate.ExperimentTemplateLogConfigurationProperty(
            log_schema_version = 1,
            cloud_watch_logs_configuration = {'LogGroupArn': fis_log_group.log_group_arn}
            )

        resource_tags = {
            'spot': 'True',
            'ClusterName': self.config['slurm']['ClusterName']
            }
        resource_type = 'aws:ec2:spot-instance'
        filters = [
            fis.CfnExperimentTemplate.ExperimentTemplateTargetFilterProperty(
                path = 'State.Name',
                values = [
                    'starting',
                    'running',
                    'stopping'
                    ]
                )
            ]
        actions = {
                'spot_termination': fis.CfnExperimentTemplate.ExperimentTemplateActionProperty(
                    action_id = 'aws:ec2:send-spot-instance-interruptions',
                    parameters = {'durationBeforeInterruption': 'PT5M'}, # Time between rebalance recommendation and spot termination notification
                    targets = {'SpotInstances': 'spot_instances'}
                )
            }
        stop_conditions = [
            fis.CfnExperimentTemplate.ExperimentTemplateStopConditionProperty(
                source = 'none', # ['none', 'aws:cloudwatch:alarm']
                #value = ''
                )
            ]

        fis.CfnExperimentTemplate(
            self, 'SpotTerminationFISTemplate1Instance',
            description = f"Inject spot termination notification to 1 instance in {self.config['slurm']['ClusterName']} slurm cluster",
            tags = {'Name': f"{self.stack_name} SpotTermination 1 instance"},
            targets = {
                'spot_instances': fis.CfnExperimentTemplate.ExperimentTemplateTargetProperty(
                    selection_mode = 'COUNT(1)', # [ALL, COUNT(n), PERCENT(n)]
                    resource_tags = resource_tags,
                    resource_type = resource_type,
                    filters = filters
                    )
                },
            actions = actions,
            log_configuration = fis_log_configuration,
            role_arn = self.fis_spot_termination_role.role_arn,
            stop_conditions = stop_conditions
        )

        for spot_instance_percent in [1, 25, 50, 100]:
            fis.CfnExperimentTemplate(
                self, f'SpotTerminationFISTemplate{spot_instance_percent}Percent',
                description = f'Inject spot termination notification to {spot_instance_percent} percent of spot instances',
                tags = {'Name': f"{self.stack_name} SpotTermination {spot_instance_percent} Percent"},
                targets = {
                    'spot_instances': fis.CfnExperimentTemplate.ExperimentTemplateTargetProperty(
                        selection_mode = f'PERCENT({spot_instance_percent})', # [ALL, COUNT(n), PERCENT(n)]
                        resource_tags = resource_tags,
                        resource_type = resource_type,
                        filters = filters
                        )
                    },
                actions = actions,
                log_configuration = fis_log_configuration,
                role_arn = self.fis_spot_termination_role.role_arn,
                stop_conditions = stop_conditions
            )

    def suppress_cfn_nag(self, resource, msg_id, reason):
        # Warnings suppressed:
        # WARN W12: IAM policy should not allow * resource
        # WARN W27: Security Groups found ingress with port range instead of just a single port
        # WARN W29: Security Groups found egress with port range instead of just a single port

        # print(f"suppress_cfn_nag {resource.node.path}")
        # print(f"    {len(resource.node.children)} children")
        # print(f"    resource: {resource}")

        if isinstance(resource, CfnResource):
            # print(f"    is cfn resource")
            metadata = resource.cfn_options.metadata
            metadata['cfn_nag'] = metadata.get('cfn_nag', {})
            metadata['cfn_nag']['rules_to_suppress'] = metadata['cfn_nag'].get('rules_to_suppress', [])
            metadata['cfn_nag']['rules_to_suppress'].append(
                {
                    'id': msg_id,
                    'reason': reason
                }
            )
            # print(f"    metadata={pp.pformat(metadata)}")
            # print(f"    metadata={pp.pformat(resource.cfn_options.metadata)}")
            resource.cfn_options.metadata = metadata
            # print(f"    metadata={pp.pformat(resource.cfn_options.metadata)}")

        # Apply this to all children to make sure to get separate ingress and egress rules
        for child in resource.node.children:
            self.suppress_cfn_nag(child, msg_id, reason)

    def create_parallel_cluster_config(self):
        MAX_NUMBER_OF_QUEUES = 50
        MAX_NUMBER_OF_COMPUTE_RESOURCES = 50
        if self.PARALLEL_CLUSTER_VERSION < parse_version('3.7.0'):
            # ParallelCluster has a restriction where a queue can have only 1 instance type with memory based scheduling
            # So, for now creating a queue for each instance type and purchase option
            PARALLEL_CLUSTER_SUPPORTS_MULTIPLE_COMPUTE_RESOURCES_PER_QUEUE = False
            PARALLEL_CLUSTER_SUPPORTS_MULTIPLE_INSTANCE_TYPES_PER_COMPUTE_RESOURCE = False
        else:
            PARALLEL_CLUSTER_SUPPORTS_MULTIPLE_COMPUTE_RESOURCES_PER_QUEUE = True
            PARALLEL_CLUSTER_SUPPORTS_MULTIPLE_INSTANCE_TYPES_PER_COMPUTE_RESOURCE = True

        # Check the architecture of the ComputeNodeAmi
        if 'ComputeNodeAmi' in self.config['slurm']['ParallelClusterConfig']:
            compute_node_ami = self.config['slurm']['ParallelClusterConfig']['ComputeNodeAmi']
            ami_info = self.ec2_client.describe_images(ImageIds=[compute_node_ami])['Images'][0]
            ami_architecture = ami_info['Architecture']
            cluster_architecture = self.config['slurm']['ParallelClusterConfig']['Architecture']
            if ami_architecture != cluster_architecture:
                logger.error(f"Config slurm/ParallelClusterConfig/ComputeNodeAmi({compute_node_ami}) architecture=={ami_architecture}. Must be the same as slurm/ParallelClusterConfig/Architecture({cluster_architecture})")
                exit(1)

        self.parallel_cluster_config = {
            'HeadNode': {
                'Dcv': {
                    'Enabled': self.config['slurm']['ParallelClusterConfig']['Dcv']['Enable'],
                    'Port': self.config['slurm']['ParallelClusterConfig']['Dcv']['Port']
                },
                'Iam': {
                    'AdditionalIamPolicies': [
                        {'Policy': 'arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore'},
                        {'Policy': self.parallel_cluster_asset_read_policy.managed_policy_arn},
                        {'Policy': self.parallel_cluster_jwt_write_policy.managed_policy_arn},
                        {'Policy': self.parallel_cluster_munge_key_write_policy.managed_policy_arn},
                    ],
                },
                'Imds': {
                    'Secured': True
                },
                'InstanceType': self.config['slurm']['SlurmCtl']['instance_type'],
                'Ssh': {
                    'KeyName':self.config['SshKeyPair']
                },
                'Networking': {
                    'SubnetId': self.config['SubnetId'],
                    'AdditionalSecurityGroups': [
                        self.slurmctl_sg.security_group_id
                    ]
                },
                'CustomActions': {
                    'OnNodeStart': {
                        'Sequence': [
                            {
                                'Script': self.custom_action_s3_urls['config/bin/on_head_node_start.sh'],
                                'Args': []
                            }
                        ]
                    },
                    'OnNodeConfigured': {
                        'Sequence': [
                            {
                                'Script': self.custom_action_s3_urls['config/bin/on_head_node_configured.sh'],
                                'Args': []
                            }
                        ]
                    },
                    'OnNodeUpdated': {
                        'Sequence': [
                            {
                                'Script': self.custom_action_s3_urls['config/bin/on_head_node_updated.sh'],
                                'Args': []
                            }
                        ]
                    }
                },
            },
            'Image': {
                'Os': self.config['slurm']['ParallelClusterConfig']['Image']['Os']
            },
            'Imds': {
                'ImdsSupport': 'v2.0'
            },
            'Region': self.cluster_region,
            'Scheduling': {
                'Scheduler': 'slurm',
                'SlurmQueues': [],
                'SlurmSettings': {
                    'EnableMemoryBasedScheduling': True,
                    'CustomSlurmSettings': [
                        {'AuthAltTypes': 'auth/jwt'},
                        {'AuthAltParameters': 'jwt_key=/opt/slurm/var/spool/jwt_hs256.key'},
                        {'FederationParameters': 'fed_display'},
                        # JobRequeue must be set to 1 to enable preemption to requeue jobs.
                        {'JobRequeue': 1},
                        # {'LaunchParameters': 'enable_nss_slurm'},
                        {'PreemptExemptTime': self.config['slurm']['SlurmCtl']['PreemptExemptTime']},
                        {'PreemptMode': self.config['slurm']['SlurmCtl']['PreemptMode']},
                        {'PreemptParameters': ','.join([
                            'reclaim_licenses',
                            'send_user_signal',
                            'strict_order',
                            'youngest_first',
                        ])},
                        {'PreemptType': self.config['slurm']['SlurmCtl']['PreemptType']},
                        {'PrologFlags': 'X11'},
                        {'SchedulerParameters': ','.join([
                            'batch_sched_delay=10',
                            'bf_continue',
                            'bf_interval=30',
                            'bf_licenses',
                            'bf_max_job_test=500',
                            'bf_max_job_user=0',
                            'bf_yield_interval=1000000',
                            'default_queue_depth=10000',
                            'max_rpc_cnt=100',
                            'nohold_on_prolog_fail',
                            'sched_min_internal=2000000',
                        ])},
                        {'ScronParameters': 'enable'},
                        {'PluginDir': '/opt/slurm/lib/slurm'},
                    ],
                },
            },
            'Tags': [
                {
                    'Key': 'parallelcluster-ui',
                    'Value': 'true'
                }
            ]
        }

        if 'AllowedIps' in self.config['slurm']['ParallelClusterConfig']['Dcv']:
            self.parallel_cluster_config['HeadNode']['Dcv']['AllowedIps'] = self.config['slurm']['ParallelClusterConfig']['AllowedIps']

        if 'CustomAmi' in self.config['slurm']['ParallelClusterConfig']['Image']:
            self.parallel_cluster_config['Image']['CustomAmi'] = self.config['slurm']['ParallelClusterConfig']['Image']['CustomAmi']

        if 'volume_size' in self.config['slurm']['SlurmCtl']:
            self.parallel_cluster_config['HeadNode']['LocalStorage'] = {
                'RootVolume': {
                    'Size': self.config['slurm']['SlurmCtl']['volume_size']
                }
            }

        if 'Database' in self.config['slurm']['ParallelClusterConfig']:
            for security_group_name, security_group_id in self.config['slurm']['ParallelClusterConfig']['Database']['ClientSecurityGroup'].items():
                self.parallel_cluster_config['HeadNode']['Networking']['AdditionalSecurityGroups'].append(security_group_id)

        if 'LoginNodes' in self.config['slurm']['ParallelClusterConfig']:
            self.parallel_cluster_config['LoginNodes'] = self.config['slurm']['ParallelClusterConfig']['LoginNodes']
            for login_node_pool in self.parallel_cluster_config['LoginNodes']['Pools']:
                if 'Networking' not in login_node_pool:
                    login_node_pool['Networking'] = {'SubnetIds': [self.config['SubnetId']]}

        # Give the head node access to extra mounts
        for fs_type in self.extra_mount_security_groups.keys():
            for extra_mount_sg_name, extra_mount_sg in self.extra_mount_security_groups[fs_type].items():
                self.parallel_cluster_config['HeadNode']['Networking']['AdditionalSecurityGroups'].append(
                    extra_mount_sg.security_group_id
                )

        # Create list of instance types by number of cores and amount of memory
        instance_types_by_core_memory = {}
        # Create list of instance types by amount of memory and number of cores
        instance_types_by_memory_core = {}
        logger.info(f"Bucketing {len(self.instance_types)} instance types based on core and memory")
        for instance_type in self.instance_types:
            cores = self.plugin.get_CoreCount(self.cluster_region, instance_type)
            mem_gb = int(self.plugin.get_MemoryInMiB(self.cluster_region, instance_type) / 1024)
            if cores not in instance_types_by_core_memory:
                instance_types_by_core_memory[cores] = {}
            if mem_gb not in instance_types_by_core_memory[cores]:
                instance_types_by_core_memory[cores][mem_gb] = []
            instance_types_by_core_memory[cores][mem_gb].append(instance_type)

            if mem_gb not in instance_types_by_memory_core:
                instance_types_by_memory_core[mem_gb] = {}
            if cores not in instance_types_by_memory_core[mem_gb]:
                instance_types_by_memory_core[mem_gb][cores] = []
            instance_types_by_memory_core[mem_gb][cores].append(instance_type)
        logger.info("Instance type by core and memory:")
        logger.info(f"    {len(instance_types_by_core_memory)} unique core counts:")
        for cores in sorted(instance_types_by_core_memory):
            logger.info(f"        {cores} core(s)")
            for mem_gb in instance_types_by_core_memory[cores]:
                logger.info(f"            {len(instance_types_by_core_memory[cores][mem_gb])} instance type with {mem_gb} GB")
        logger.info("Instance type by memory and core:")
        logger.info(f"    {len(instance_types_by_memory_core)} unique memory size:")
        for mem_gb in sorted(instance_types_by_memory_core):
            logger.info(f"        {mem_gb} GB")
            for cores in sorted(instance_types_by_memory_core[mem_gb]):
                logger.info(f"            {len(instance_types_by_memory_core[mem_gb][cores])} instance type with {cores} core(s)")

        purchase_options = ['ONDEMAND']
        if self.config['slurm']['InstanceConfig']['UseSpot']:
            purchase_options.append('SPOT')

        nodesets = {}
        number_of_queues = 0
        number_of_compute_resources = 0
        if PARALLEL_CLUSTER_SUPPORTS_MULTIPLE_COMPUTE_RESOURCES_PER_QUEUE and PARALLEL_CLUSTER_SUPPORTS_MULTIPLE_INSTANCE_TYPES_PER_COMPUTE_RESOURCE:
            # Creating a queue for each memory size
            # In each queue, create a CR for each permutation of memmory and core count
            for purchase_option in purchase_options:
                nodesets[purchase_option] = []
                for mem_gb in sorted(instance_types_by_memory_core.keys()):
                    if purchase_option == 'ONDEMAND':
                        queue_name_prefix = "od"
                        allocation_strategy = 'lowest-price'
                    else:
                        queue_name_prefix = "sp"
                        allocation_strategy = 'capacity-optimized'
                    queue_name = f"{queue_name_prefix}-{mem_gb}-gb"
                    if number_of_queues >= MAX_NUMBER_OF_QUEUES:
                        logger.warning(f"Skipping {queue_name} queue because MAX_NUMBER_OF_QUEUES=={MAX_NUMBER_OF_QUEUES}")
                        continue
                    if number_of_compute_resources >= MAX_NUMBER_OF_COMPUTE_RESOURCES:
                        logger.warning(f"Skipping {queue_name} queue because MAX_NUMBER_OF_COMPUTE_RESOURCES=={MAX_NUMBER_OF_COMPUTE_RESOURCES}")
                        continue
                    nodeset = f"{queue_name}_nodes"
                    nodesets[purchase_option].append(nodeset)
                    parallel_cluster_queue = {
                        'Name': queue_name,
                        'AllocationStrategy': allocation_strategy,
                        'CapacityType': purchase_option,
                        'ComputeResources': [],
                        'ComputeSettings': {
                            'LocalStorage': {
                                'RootVolume': {
                                    'VolumeType': 'gp3'
                                }
                            }
                        },
                        'CustomActions': {
                            'OnNodeStart': {
                                'Sequence': [
                                    {
                                        'Script': self.custom_action_s3_urls['config/bin/on_compute_node_start.sh'],
                                        'Args': []
                                    }
                                ]
                            },
                            'OnNodeConfigured': {
                                'Sequence': [
                                    {
                                        'Script': self.custom_action_s3_urls['config/bin/on_compute_node_configured.sh'],
                                        'Args': []
                                    }
                                ]
                            },
                        },
                        'Iam': {
                            'AdditionalIamPolicies': [
                                {'Policy': 'arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore'},
                                {'Policy': self.parallel_cluster_asset_read_policy.managed_policy_arn},
                            ]
                        },
                        'Networking': {
                            'SubnetIds': [self.config['SubnetId']],
                            'AdditionalSecurityGroups': [self.slurmnode_sg.security_group_id],
                            'PlacementGroup': {}
                        },
                    }
                    if 'ComputeNodeAmi' in self.config['slurm']['ParallelClusterConfig']:
                        parallel_cluster_queue['Image'] = {
                            'CustomAmi': self.config['slurm']['ParallelClusterConfig']['ComputeNodeAmi']
                        }
                    number_of_queues += 1

                    # Give the compute node access to extra mounts
                    for fs_type in self.extra_mount_security_groups.keys():
                        for extra_mount_sg_name, extra_mount_sg in self.extra_mount_security_groups[fs_type].items():
                            parallel_cluster_queue['Networking']['AdditionalSecurityGroups'].append(extra_mount_sg.security_group_id)

                    for num_cores in sorted(instance_types_by_memory_core[mem_gb].keys()):
                        compute_resource_name = f"{queue_name_prefix}-{mem_gb}gb-{num_cores}-cores"
                        if len(parallel_cluster_queue['ComputeResources']):
                            logger.warning(f"Skipping {compute_resource_name} compute resource to reduce the number of compute resources to 1 per queue")
                            continue
                        if number_of_compute_resources >= MAX_NUMBER_OF_COMPUTE_RESOURCES:
                            logger.warning(f"Skipping {compute_resource_name} compute resource because MAX_NUMBER_OF_COMPUTE_RESOURCES=={MAX_NUMBER_OF_COMPUTE_RESOURCES}")
                            continue
                        instance_types = sorted(instance_types_by_memory_core[mem_gb][num_cores])
                        if compute_resource_name in self.config['slurm']['InstanceConfig']['NodeCounts']['ComputeResourceCounts']:
                            min_count = self.config['slurm']['InstanceConfig']['NodeCounts']['ComputeResourceCounts'][compute_resource_name]['MinCount']
                            max_count = self.config['slurm']['InstanceConfig']['NodeCounts']['ComputeResourceCounts'][compute_resource_name]['MaxCount']
                        else:
                            min_count = self.config['slurm']['InstanceConfig']['NodeCounts']['DefaultMinCount']
                            max_count = self.config['slurm']['InstanceConfig']['NodeCounts']['DefaultMaxCount']
                        compute_resource = {
                            'Name': compute_resource_name,
                            'MinCount': min_count,
                            'MaxCount': max_count,
                            'DisableSimultaneousMultithreading': self.config['slurm']['ParallelClusterConfig']['DisableSimultaneousMultithreading'],
                            'Instances': [],
                            'Efa': {'Enabled': False},
                        }
                        efa_supported = self.config['slurm']['ParallelClusterConfig']['EnableEfa']
                        min_price = sys.maxsize
                        max_price = 0
                        total_price = 0
                        for instance_type in sorted(instance_types):
                            efa_supported = efa_supported and self.plugin.get_EfaSupported(self.cluster_region, instance_type)
                            if purchase_option == 'ONDEMAND':
                                price = self.plugin.instance_type_and_family_info[self.cluster_region]['instance_types'][instance_type]['pricing']['OnDemand']
                            else:
                                price = self.plugin.instance_type_and_family_info[self.cluster_region]['instance_types'][instance_type]['pricing']['spot']['max']
                            min_price = min(min_price, price)
                            max_price = max(max_price, price)
                            total_price += price
                            compute_resource['Instances'].append(
                                {
                                    'InstanceType': instance_type
                                }
                            )
                        average_price = total_price / len(instance_types)
                        compute_resource['Efa']['Enabled'] = efa_supported
                        if self.PARALLEL_CLUSTER_VERSION >= parse_version('3.7.0'):
                            compute_resource['StaticNodePriority'] = int(average_price *  1000)
                            compute_resource['DynamicNodePriority'] = int(average_price * 10000)
                        compute_resource['Networking'] = {
                            'PlacementGroup': {
                                'Enabled': efa_supported
                            }
                        }
                        parallel_cluster_queue['ComputeResources'].append(compute_resource)
                        number_of_compute_resources += 1
                    self.parallel_cluster_config['Scheduling']['SlurmQueues'].append(parallel_cluster_queue)
        else:
            for purchase_option in purchase_options:
                nodesets[purchase_option] = []
                for instance_type in self.instance_types:
                    efa_supported = self.plugin.get_EfaSupported(self.cluster_region, instance_type) and self.config['slurm']['ParallelClusterConfig']['EnableEfa']
                    if purchase_option == 'ONDEMAND':
                        queue_name_prefix = "od"
                        allocation_strategy = 'lowest-price'
                        price = self.plugin.instance_type_and_family_info[self.cluster_region]['instance_types'][instance_type]['pricing']['OnDemand']
                    else:
                        queue_name_prefix = "sp"
                        allocation_strategy = 'capacity-optimized'
                        price = self.plugin.instance_type_and_family_info[self.cluster_region]['instance_types'][instance_type]['pricing']['spot']['max']
                    queue_name = f"{queue_name_prefix}-{instance_type}"
                    queue_name = queue_name.replace('.', '-')
                    nodeset = f"{queue_name}_nodes"
                    nodesets[purchase_option].append(nodeset)
                    parallel_cluster_queue = {
                        'Name': queue_name,
                        'AllocationStrategy': allocation_strategy,
                        'CapacityType': purchase_option,
                        'ComputeResources': [],
                        'ComputeSettings': {
                            'LocalStorage': {
                                'RootVolume': {
                                    'VolumeType': 'gp3'
                                }
                            }
                        },
                        'CustomActions': {
                            'OnNodeStart': {
                                'Sequence': [
                                    {
                                        'Script': self.custom_action_s3_urls['config/bin/on_compute_node_start.sh'],
                                        'Args': []
                                    }
                                ]
                            },
                            'OnNodeConfigured': {
                                'Sequence': [
                                    {
                                        'Script': self.custom_action_s3_urls['config/bin/on_compute_node_configured.sh'],
                                        'Args': []
                                    }
                                ]
                            },
                        },
                        'Iam': {
                            'AdditionalIamPolicies': [
                                {'Policy': 'arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore'},
                                {'Policy': self.parallel_cluster_asset_read_policy.managed_policy_arn},
                            ]
                        },
                        'Networking': {
                            'SubnetIds': [self.config['SubnetId']],
                            'AdditionalSecurityGroups': [self.slurmnode_sg.security_group_id],
                        },
                    }
                    if 'ComputeNodeAmi' in self.config['slurm']['ParallelClusterConfig']:
                        parallel_cluster_queue['Image'] = {
                            'CustomAmi': self.config['slurm']['ParallelClusterConfig']['ComputeNodeAmi']
                        }

                    # Give the compute node access to extra mounts
                    for fs_type in self.extra_mount_security_groups.keys():
                        for extra_mount_sg_name, extra_mount_sg in self.extra_mount_security_groups[fs_type].items():
                            parallel_cluster_queue['Networking']['AdditionalSecurityGroups'].append(extra_mount_sg.security_group_id)

                    compute_resource_name = f"{queue_name_prefix}-{instance_type}-cr1".replace('.', '-')
                    if compute_resource_name in self.config['slurm']['InstanceConfig']['NodeCounts']['ComputeResourceCounts']:
                        min_count = self.config['slurm']['InstanceConfig']['NodeCounts']['ComputeResourceCounts'][compute_resource_name]['MinCount']
                        max_count = self.config['slurm']['InstanceConfig']['NodeCounts']['ComputeResourceCounts'][compute_resource_name]['MaxCount']
                    else:
                        min_count = self.config['slurm']['InstanceConfig']['NodeCounts']['DefaultMinCount']
                        max_count = self.config['slurm']['InstanceConfig']['NodeCounts']['DefaultMaxCount']
                    compute_resource = {
                        'Name': compute_resource_name,
                        'MinCount': min_count,
                        'MaxCount': max_count,
                        'DisableSimultaneousMultithreading': self.config['slurm']['ParallelClusterConfig']['DisableSimultaneousMultithreading'],
                        'Instances': [],
                        'Efa': {'Enabled': efa_supported},
                        'Networking': {
                            'PlacementGroup': {
                                'Enabled': efa_supported
                            }
                        }
                    }
                    compute_resource['Instances'].append(
                        {
                            'InstanceType': instance_type
                        }
                    )
                    if self.PARALLEL_CLUSTER_VERSION >= parse_version('3.7.0'):
                        compute_resource['StaticNodePriority'] = int(price *  1000)
                        compute_resource['DynamicNodePriority'] = int(price * 10000)
                    parallel_cluster_queue['ComputeResources'].append(compute_resource)
                    self.parallel_cluster_config['Scheduling']['SlurmQueues'].append(parallel_cluster_queue)

        logger.info(f"Created {number_of_queues} queues with {number_of_compute_resources} compute resources")

        if 'OnPremComputeNodes' in self.config['slurm']['InstanceConfig']:
            if not path.exists(self.config['slurm']['InstanceConfig']['OnPremComputeNodes']['ConfigFile']):
                logger.error(f"slurm/InstanceConfig/OnPremComputeNodes/ConfigFile: On-premises compute nodes config file not found: {self.config['slurm']['InstanceConfig']['OnPremComputeNodes']['ConfigFile']}")
                exit(1)
            fh = open(self.config['slurm']['InstanceConfig']['OnPremComputeNodes']['ConfigFile'], 'r')
            for line in fh.readline():
                line = line.strip()
                if not line: continue
                if re.match(r'\s*#', line): continue
                key_value_pairs = line.split(' ')
                if not key_value_pairs: continue
                slurm_settings_dict = {}
                for key_value_pair in key_value_pairs:
                    (key, value) = key_value_pair.split('=', 1)
                    slurm_settings_dict[key] = value
                self.parallel_cluster_config['Scheduling']['SlurmSettings']['CustomSlurmSettings'].append(slurm_settings_dict)

        # Create custom partitions based on those created by ParallelCluster
        if 'ONDEMAND' in nodesets:
            self.parallel_cluster_config['Scheduling']['SlurmSettings']['CustomSlurmSettings'].extend(
                [
                    {
                        'PartitionName': 'on-demand',
                        'Default': 'NO',
                        'PriorityTier': '1',
                        'Nodes': ','.join(nodesets['ONDEMAND']),
                    }
                ]
            )
        if 'SPOT' in nodesets:
            self.parallel_cluster_config['Scheduling']['SlurmSettings']['CustomSlurmSettings'].extend(
                [
                    {
                        'PartitionName': 'spot',
                        'Default': 'NO',
                        'PriorityTier': '10',
                        'Nodes': ','.join(nodesets['SPOT']),
                    }
                ]
            )
        self.parallel_cluster_config['Scheduling']['SlurmSettings']['CustomSlurmSettings'].extend(
            [
                {
                    'PartitionName': 'all',
                    'Default': 'NO',
                    'PriorityTier': '10',
                    'Nodes': 'ALL',
                },
                {
                    'PartitionName': 'interactive',
                    'Default': 'NO',
                    'PriorityTier': '10000',
                    'Nodes': 'ALL'
                },
                {
                    'PartitionName': 'batch',
                    'Default': 'YES',
                    'PriorityTier': '10',
                    'Nodes': 'ALL'
                },
            ]
        )

        if 'Database' in self.config['slurm']['ParallelClusterConfig']:
            self.parallel_cluster_config['Scheduling']['SlurmSettings']['Database'] = {
                'Uri': f"{self.config['slurm']['ParallelClusterConfig']['Database']['FQDN']}:{self.config['slurm']['ParallelClusterConfig']['Database']['Port']}",
                'UserName': self.config['slurm']['ParallelClusterConfig']['Database']['AdminUserName'],
                'PasswordSecretArn': self.config['slurm']['ParallelClusterConfig']['Database']['AdminPasswordSecretArn'],
            }
            self.parallel_cluster_config['Scheduling']['SlurmSettings']['CustomSlurmSettings'].extend(
                [
                    {'AccountingStoreFlags': 'job_comment'},
                    {'PriorityType': 'priority/multifactor'},
                    {'PriorityWeightPartition': '100000'},
                    {'PriorityWeightFairshare': '10000'},
                    {'PriorityWeightQOS': '10000'},
                    {'PriorityWeightAge': '1000'},
                    {'PriorityWeightAssoc': '0'},
                    {'PriorityWeightJobSize': '0'},
                ]
            )
        else:
            # Remote licenses configured using sacctmgr
            license_strings = []
            for license_name in self.config['Licenses']:
                full_license_name = license_name
                if 'Server' in self.config['Licenses'][license_name]:
                    full_license_name += f"@{self.config['Licenses'][license_name]['Server']}"
                    if 'Port' in self.config['Licenses'][license_name]:
                        # Using '@' for the port separator instead of ':' because sbatch doesn't work if ':' is in the server name.
                        full_license_name += f"@{self.config['Licenses'][license_name]['Port']}"
                license_strings.append(f"{full_license_name}:{self.config['Licenses'][license_name]['Count']}")
            self.parallel_cluster_config['Scheduling']['SlurmSettings']['CustomSlurmSettings'].append({'Licenses': ','.join(license_strings)})

        if 'SlurmConfOverrides' in self.config['slurm']['SlurmCtl']:
            if not path.exists(self.config['slurm']['SlurmCtl']['SlurmConfOverrides']['ConfigFile']):
                logger.error(f"slurm/SlurmCtl/SlurmConfOverrides/ConfigFile: On-premises compute nodes config file not found: {self.config['slurm']['SlurmCtl']['SlurmConfOverrides']['ConfigFile']}")
                exit(1)
            fh = open(self.config['slurm']['SlurmCtl']['SlurmConfOverrides']['ConfigFile'], 'r')
            for line in fh.readline():
                line = line.strip()
                if not line: continue
                if re.match(r'\s*#', line): continue
                key_value_pairs = line.split(' ')
                if not key_value_pairs: continue
                slurm_settings_dict = {}
                for key_value_pair in key_value_pairs:
                    (key, value) = key_value_pair.split('=', 1)
                    slurm_settings_dict[key] = value
                self.parallel_cluster_config['Scheduling']['SlurmSettings']['CustomSlurmSettings'].append(slurm_settings_dict)

        self.parallel_cluster_config['SharedStorage'] = []
        for extra_mount_dict in self.config['slurm'].get('storage', {}).get('ExtraMounts', {}):
            mount_dir = extra_mount_dict['dest']
            storage_type = extra_mount_dict['StorageType']
            if storage_type == 'Efs':
                parallel_cluster_storage_dict = {
                    'Name': mount_dir,
                    'StorageType': storage_type,
                    'MountDir': mount_dir,
                    'EfsSettings': {'FileSystemId': extra_mount_dict['FileSystemId']},
                }
            elif storage_type == 'FsxLustre':
                parallel_cluster_storage_dict = {
                    'Name': mount_dir,
                    'StorageType': storage_type,
                    'MountDir': mount_dir,
                    'FsxLustreSettings': {'FileSystemId': extra_mount_dict['FileSystemId']},
                }
            elif storage_type == 'FsxOntap':
                parallel_cluster_storage_dict = {
                    'Name': mount_dir,
                    'StorageType': storage_type,
                    'MountDir': mount_dir,
                    'FsxOntapSettings': {'VolumeId': extra_mount_dict['VolumeId']},
                }
            elif storage_type == 'FsxOpenZfs':
                parallel_cluster_storage_dict = {
                    'Name': mount_dir,
                    'StorageType': storage_type,
                    'MountDir': mount_dir,
                    'FsxOpenZfsSettings': {'VolumeId': extra_mount_dict['VolumeId']},
                }
            self.parallel_cluster_config['SharedStorage'].append(parallel_cluster_storage_dict)

        self.parallel_cluster_config_json_s3_key = f"{self.assets_base_key}/ParallelClusterConfig.json"
        self.parallel_cluster_config_yaml_s3_key = f"{self.assets_base_key}/ParallelClusterConfig.yml"

        self.parallel_cluster = CustomResource(
            self, "ParallelCluster",
            service_token = self.create_parallel_cluster_lambda.function_arn,
            properties = {
                'ParallelClusterConfigJson': json.dumps(self.parallel_cluster_config, sort_keys=False),
                'ParallelClusterConfigS3Bucket': self.assets_bucket,
                'ParallelClusterConfigJsonS3Key': self.parallel_cluster_config_json_s3_key,
                'ParallelClusterConfigYamlS3Key': self.parallel_cluster_config_yaml_s3_key,
                'Region': self.config['Region'],
                'ClusterName': self.config['slurm']['ClusterName'],
            }
        )
        self.parallel_cluster_config_json_s3_url = self.parallel_cluster.get_att_string('ConfigJsonS3Url')
        self.parallel_cluster_config_yaml_s3_url = self.parallel_cluster.get_att_string('ConfigYamlS3Url')

        CfnOutput(self, "ParallelClusterConfigJsonS3Url",
            value = self.parallel_cluster_config_json_s3_url
        )
        CfnOutput(self, "ParallelClusterConfigYamlS3Url",
            value = self.parallel_cluster_config_yaml_s3_url
        )
        CfnOutput(self, "MungeParameterName",
            value = self.munge_key_ssm_parameter.parameter_name
        )
        CfnOutput(self, "MungeParameterArn",
            value = self.munge_key_ssm_parameter.parameter_arn
        )
        CfnOutput(self, "PlaybookS3Url",
            value = self.playbooks_asset.s3_object_url
        )
        region = self.cluster_region
        cluster_name = self.config['slurm']['ClusterName']
        CfnOutput(self, "Command01_SubmitterMountHeadNode",
            value = f"head_ip=$(aws ec2 describe-instances --region {region} --filters 'Name=tag:parallelcluster:cluster-name,Values={cluster_name}' 'Name=tag:parallelcluster:node-type,Values=HeadNode' --query 'Reservations[0].Instances[0].PrivateIpAddress' --output text) && sudo mkdir -p /opt/slurm/{cluster_name} && sudo mount $head_ip:/opt/slurm /opt/slurm/{cluster_name}"
        )
        CfnOutput(self, "Command02_CreateUsersGroupsJsonConfigure",
            value = f"sudo /opt/slurm/{cluster_name}/config/bin/create_users_groups_json_configure.sh"
        )
        CfnOutput(self, "Command03_SubmitterConfigure",
            value = f"sudo /opt/slurm/{cluster_name}/config/bin/submitter_configure.sh"
        )
        CfnOutput(self, "command10_CreateUsersGroupsJsonDeconfigure",
            value = f"sudo /opt/slurm/{cluster_name}/config/bin/create_users_groups_json_deconfigure.sh"
        )
        CfnOutput(self, "command11_SubmitterDeconfigure",
            value = f"sudo /opt/slurm/{cluster_name}/config/bin/submitter_deconfigure.sh && sudo umount /opt/slurm/{cluster_name}"
        )
