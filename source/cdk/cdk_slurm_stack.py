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
    aws_lambda_event_sources as lambda_event_sources,
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
import config_schema
from config_schema import get_PARALLEL_CLUSTER_MUNGE_VERSION, get_PARALLEL_CLUSTER_PYTHON_VERSION, get_PC_SLURM_VERSION, get_SLURM_VERSION
from constructs import Construct
from copy import copy, deepcopy
from hashlib import sha512
from jinja2 import Template as Template
import json
import logging
import os
from os import makedirs, path
from os.path import dirname, realpath
from packaging.version import parse as parse_version
from pprint import PrettyPrinter
import re
from shutil import make_archive
import subprocess
from subprocess import check_output
import sys
from sys import exit
from tempfile import NamedTemporaryFile
from textwrap import dedent
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

        # Assets needs ARNs of topics used to trigger Lambdas so must be declared as part of assets
        self.create_parallel_cluster_assets()

        # Lambdas need ARNs from assets in IAM permissions
        self.create_parallel_cluster_lambdas()

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

        if not config_schema.PARALLEL_CLUSTER_SUPPORTS_LOGIN_NODES(self.PARALLEL_CLUSTER_VERSION):
            if 'LoginNodes' in self.config['slurm']['ParallelClusterConfig']:
                logger.error(f"slurm/ParallelClusterConfig/LoginNodes not supported before version {config_schema.PARALLEL_CLUSTER_SUPPORTS_LOGIN_NODES_VERSION}")
                config_errors += 1

        self.mount_home = False
        if not config_schema.PARALLEL_CLUSTER_SUPPORTS_HOME_MOUNT(self.PARALLEL_CLUSTER_VERSION):
            if 'storage' in self.config['slurm']:
                for mount_dict in self.config['slurm']['storage']['ExtraMounts']:
                    logger.info(f"mount_dict={mount_dict}")
                    if mount_dict['dest'] == '/home':
                        self.mount_home = True
                        self.mount_home_src = mount_dict['src']
                        logger.info(f"Mounting /home from {self.mount_home_src} on compute nodes")

        if self.config['slurm']['ParallelClusterConfig']['Image']['Os'] == 'rocky8':
            if not config_schema.PARALLEL_CLUSTER_SUPPORTS_CUSTOM_ROCKY_8(self.PARALLEL_CLUSTER_VERSION):
                logger.error(f"rocky8 is not supported in ParallelCluster version {self.PARALLEL_CLUSTER_VERSION}. Support added in {PARALLEL_CLUSTER_SUPPORTS_CUSTOM_ROCKY_8_VERSION}.")
                config_errors += 1
            if 'CustomAmi' not in self.config['slurm']['ParallelClusterConfig']['Image']:
                logger.error(f"Must specify config slurm/ParallelClusterConfig/Image/Os/CustomAmi with rocky8.")
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
        # Create a secure hash of all of the assets so that changes can be easily detected to trigger cluster updates.
        self.assets_hash = sha512()

        self.parallel_cluster_asset_read_policy = iam.ManagedPolicy(
            self, "ParallelClusterAssetReadPolicy",
            path = '/parallelcluster/',
            #managed_policy_name = f"{self.stack_name}-ParallelClusterAssetReadPolicy",
        )
        # If use managed_policy_name, then get the following cfn_nag warning.
        # W28: Resource found with an explicit name, this disallows updates that require replacement of this resource

        self.create_munge_key_secret()

        self.playbooks_asset = s3_assets.Asset(self, 'Playbooks',
            path = 'resources/playbooks',
            follow_symlinks = SymlinkFollowMode.ALWAYS
        )
        self.playbooks_asset.grant_read(self.parallel_cluster_asset_read_policy)
        self.playbooks_asset_bucket = self.playbooks_asset.s3_bucket_name
        self.playbooks_asset_key    = self.playbooks_asset.s3_object_key

        self.assets_bucket = self.playbooks_asset.s3_bucket_name
        self.assets_base_key = self.config['slurm']['ClusterName']

        self.parallel_cluster_config_json_s3_key = f"{self.assets_base_key}/ParallelClusterConfig.json"
        self.parallel_cluster_config_yaml_s3_key = f"{self.assets_base_key}/ParallelClusterConfig.yml"

        self.parallel_cluster_munge_key_write_policy = iam.ManagedPolicy(
            self, "ParallelClusterMungeKeyWritePolicy",
            #managed_policy_name = f"{self.stack_name}-ParallelClusterMungeKeyWritePolicy",
            statements = [
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        's3:PutObject',
                    ],
                    resources=[f"arn:{Aws.PARTITION}:s3:::{self.assets_bucket}/{self.config['slurm']['ClusterName']}/config/munge.key"]
                )
            ]
        )
        # If use managed_policy_name, then get the following cfn_nag warning.
        # W28: Resource found with an explicit name, this disallows updates that require replacement of this resource

        self.parallel_cluster_sns_publish_policy = iam.ManagedPolicy(
            self, "ParallelClusterSnsPublishPolicy",
            path = '/parallelcluster/',
            #managed_policy_name = f"{self.stack_name}-ParallelClusterSnspublishPolicy",
        )

        if 'ErrorSnsTopicArn' in self.config:
            self.error_sns_topic = sns.Topic.from_topic_arn(
                self, 'ErrorSnsTopic',
                topic_arn = self.config['ErrorSnsTopicArn']
            )
            self.error_sns_topic.grant_publish(self.parallel_cluster_sns_publish_policy)

        # SNS topic that gets notified when cluster is created and triggers a lambda to create the head nodes's A record
        self.create_head_node_a_record_sns_topic = sns.Topic(
            self, "CreateHeadNodeARecordSnsTopic",
            topic_name = f"{self.config['slurm']['ClusterName']}CreateHeadNodeARecord"
            )
        # W47:SNS Topic should specify KmsMasterKeyId property
        self.suppress_cfn_nag(self.create_head_node_a_record_sns_topic, 'W47', 'Use default KMS key.')
        if 'RESEnvironmentName' in self.config:
            # SNS topic that gets notified when cluster is created and triggers a lambda to configure the cluster manager
            self.configure_cluster_manager_sns_topic = sns.Topic(
                self, "ConfigureClusterManagerSnsTopic",
                topic_name = f"{self.config['slurm']['ClusterName']}ConfigureClusterManager"
                )
            # W47:SNS Topic should specify KmsMasterKeyId property
            self.suppress_cfn_nag(self.configure_cluster_manager_sns_topic, 'W47', 'Use default KMS key.')
            # SNS topic that gets notified when cluster is created and triggers a lambda to configure the cluster manager
            self.configure_submitters_sns_topic = sns.Topic(
                self, "ConfigureSubmittersSnsTopic",
                topic_name = f"{self.config['slurm']['ClusterName']}ConfigureSubmitters"
                )
            # W47:SNS Topic should specify KmsMasterKeyId property
            self.suppress_cfn_nag(self.configure_submitters_sns_topic, 'W47', 'Use default KMS key.')

        # Create an SSM parameter to store the JWT tokens for root and slurmrestd
        self.jwt_token_for_root_ssm_parameter_name = f"/{self.config['slurm']['ClusterName']}/slurmrestd/jwt/root"
        self.jwt_token_for_root_ssm_parameter = ssm.StringParameter(
            self, f"JwtTokenForRootParameter",
            parameter_name = self.jwt_token_for_root_ssm_parameter_name,
            string_value = 'None'
        )
        self.jwt_token_for_slurmrestd_ssm_parameter_name = f"/{self.config['slurm']['ClusterName']}/slurmrestd/jwt/slurmrestd"
        self.jwt_token_for_slurmrestd_ssm_parameter = ssm.StringParameter(
            self, f"JwtTokenForSlurmrestdParameter",
            parameter_name = self.jwt_token_for_slurmrestd_ssm_parameter_name,
            string_value = 'None'
        )

        self.s3_client = boto3.client('s3', region_name=self.cluster_region)

        # The asset isn't uploaded right away so create our own zipfile and upload it
        playbooks_zipfile_base_filename = f"/tmp/{self.config['slurm']['ClusterName']}_playbooks"
        playbooks_zipfile_filename = playbooks_zipfile_base_filename + '.zip'
        make_archive(playbooks_zipfile_base_filename, 'zip', 'resources/playbooks')
        self.playbooks_bucket = self.playbooks_asset_bucket
        self.playbooks_key = f"{self.assets_base_key}/playbooks.zip"
        self.playbooks_s3_url = f"s3://{self.playbooks_bucket}/{self.playbooks_key}"
        with open(playbooks_zipfile_filename, 'rb') as playbooks_zipfile_fh:
            self.assets_hash.update(playbooks_zipfile_fh.read())
        with open(playbooks_zipfile_filename, 'rb') as playbooks_zipfile_fh:
            self.s3_client.put_object(
                Bucket = self.assets_bucket,
                Key    = self.playbooks_key,
                Body   = playbooks_zipfile_fh
            )
        os.remove(playbooks_zipfile_filename)

        self.configure_cluster_manager_sns_topic_arn_parameter_name = f"/{self.config['slurm']['ClusterName']}/ConfigureClusterManagerSnsTopicArn"
        self.configure_cluster_manager_sns_topic_arn_parameter = ssm.StringParameter(
            self, f"ConfigureClusterManagerSnsTopicArnParameter",
            parameter_name = self.configure_cluster_manager_sns_topic_arn_parameter_name,
            string_value = self.configure_cluster_manager_sns_topic.topic_arn
        )
        self.configure_cluster_manager_sns_topic_arn_parameter.grant_read(self.parallel_cluster_asset_read_policy)

        self.configure_submitters_sns_topic_arn_parameter_name = f"/{self.config['slurm']['ClusterName']}/ConfigureSubmittersSnsTopicArn"
        self.configure_submitters_sns_topic_arn_parameter = ssm.StringParameter(
            self, f"ConfigureSubmittersSnsTopicArnParameter",
            parameter_name = self.configure_submitters_sns_topic_arn_parameter_name,
            string_value = self.configure_submitters_sns_topic.topic_arn
        )
        self.configure_submitters_sns_topic_arn_parameter.grant_read(self.parallel_cluster_asset_read_policy)

        self.create_head_node_a_record_sns_topic_arn_parameter_name = f"/{self.config['slurm']['ClusterName']}/CreateHeadNodeARecordSnsTopicArn"
        self.create_head_node_a_record_sns_topic_arn_parameter = ssm.StringParameter(
            self, f"CreateHeadNodeARecordSnsTopicArnParameter",
            parameter_name = self.create_head_node_a_record_sns_topic_arn_parameter_name,
            string_value = self.create_head_node_a_record_sns_topic.topic_arn
        )
        self.create_head_node_a_record_sns_topic_arn_parameter.grant_read(self.parallel_cluster_asset_read_policy)

        template_vars = {
            'assets_bucket': self.assets_bucket,
            'assets_base_key': self.assets_base_key,
            'ClusterName': self.config['slurm']['ClusterName'],
            'ConfigureClusterManagerSnsTopicArnParameter': self.configure_cluster_manager_sns_topic_arn_parameter_name,
            'ConfigureSubmittersSnsTopicArnParameter': self.configure_submitters_sns_topic_arn_parameter_name,
            'CreateHeadNodeARecordSnsTopicArnParameter': self.create_head_node_a_record_sns_topic_arn_parameter_name,
            'ErrorSnsTopicArn': self.config.get('ErrorSnsTopicArn', ''),
            'playbooks_s3_url': self.playbooks_s3_url,
            'Region': self.cluster_region,
            'SubnetId': self.config['SubnetId'],
            'SubmitterSlurmConfigDir': f"/opt/slurm/{self.config['slurm']['ClusterName']}/config"
        }
        if config_schema.PARALLEL_CLUSTER_SUPPORTS_CUSTOM_MUNGE_KEY(self.PARALLEL_CLUSTER_VERSION):
            template_vars['MungeKeySecretId'] = ''
        else:
            template_vars['MungeKeySecretId'] = self.config['slurm'].get('MungeKeySecret', '')
        if self.mount_home and not config_schema.PARALLEL_CLUSTER_SUPPORTS_HOME_MOUNT(self.PARALLEL_CLUSTER_VERSION):
            template_vars['HomeMountSrc'] = self.mount_home_src
        else:
            template_vars['HomeMountSrc'] = ''

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
            self.s3_client.put_object(
                Bucket = self.assets_bucket,
                Key    = s3_key,
                Body   = local_file_content
            )
            self.assets_hash.update(bytes(local_file_content, 'utf-8'))

        self.ami_builds = {
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
        if config_schema.PARALLEL_CLUSTER_SUPPORTS_CUSTOM_ROCKY_8(self.PARALLEL_CLUSTER_VERSION):
            self.ami_builds['Rocky'] = {
                '8': {
                    'arm64': {},
                    'x86_64': {}
                }
            }
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
            template_vars['AssetReadPolicyArn'] = asset_read_policy_arn
        except:
            template_vars['ImageBuilderSecurityGroupId'] = self.imagebuilder_sg.security_group_id
            template_vars['AssetReadPolicyArn'] = self.parallel_cluster_asset_read_policy.managed_policy_arn
        parallelcluster_version = self.config['slurm']['ParallelClusterConfig']['Version']
        parallelcluster_version_name = parallelcluster_version.replace('.', '-')
        self.build_files_path = f"resources/parallel-cluster/config/build-files"
        self.build_file_template_path = f"{self.build_files_path}/build-file-template.yml"
        build_file_template_content = open(self.build_file_template_path, 'r').read()
        self.s3_client.put_object(
            Bucket = self.assets_bucket,
            Key    = f"{self.assets_base_key}/config/build-files/build-file-template.yml",
            Body   = build_file_template_content
        )
        build_file_template = Template(build_file_template_content)
        cluster_build_files_path = f"{self.build_files_path}/{parallelcluster_version}/{self.config['slurm']['ClusterName']}"
        makedirs(cluster_build_files_path, exist_ok=True)
        for distribution in self.ami_builds:
            for version in self.ami_builds[distribution]:
                for architecture in self.ami_builds[distribution][version]:
                    if architecture == 'arm64':
                        template_vars['InstanceType'] = 'c6g.2xlarge'
                    else:
                        template_vars['InstanceType'] = 'c6i.2xlarge'
                    template_vars['ParentImage'] = self.get_image_builder_parent_image(distribution, version, architecture)
                    template_vars['RootVolumeSize'] = int(self.get_ami_root_volume_size(template_vars['ParentImage'])) + 10
                    logger.info(f"{distribution}-{version}-{architecture} image id: {template_vars['ParentImage']} root volume size={template_vars['RootVolumeSize']}")

                    # Base image without EDA packages
                    template_vars['ImageName'] = f"parallelcluster-{parallelcluster_version_name}-{distribution}-{version}-{architecture}".replace('_', '-')
                    template_vars['ComponentS3Url'] = None
                    build_file_content = build_file_template.render(**template_vars)
                    self.assets_hash.update(bytes(build_file_content, 'utf-8'))
                    fh = open(f"{cluster_build_files_path}/{template_vars['ImageName']}.yml", 'w')
                    fh.write(build_file_content)

                    template_vars['ImageName'] = f"parallelcluster-{parallelcluster_version_name}-eda-{distribution}-{version}-{architecture}".replace('_', '-')
                    template_vars['ComponentS3Url'] = self.custom_action_s3_urls['config/bin/configure-eda.sh']
                    build_file_content = build_file_template.render(**template_vars)
                    self.assets_hash.update(bytes(build_file_content, 'utf-8'))
                    fh = open(f"{cluster_build_files_path}/{template_vars['ImageName']}.yml", 'w')
                    fh.write(build_file_content)

                    template_vars['ParentImage'] = self.get_fpga_developer_image(distribution, version, architecture)
                    if not template_vars['ParentImage']:
                        logger.debug(f"No FPGA Developer AMI found for {distribution}{version} {architecture}")
                        continue
                    template_vars['ImageName'] = f"parallelcluster-{parallelcluster_version_name}-fpga-{distribution}-{version}-{architecture}".replace('_', '-')
                    template_vars['RootVolumeSize'] = int(self.get_ami_root_volume_size(template_vars['ParentImage'])) + 10
                    logger.info(f"{distribution}-{version}-{architecture} fpga developer image id: {template_vars['ParentImage']} root volume size={template_vars['RootVolumeSize']}")
                    build_file_content = build_file_template.render(**template_vars)
                    self.assets_hash.update(bytes(build_file_content, 'utf-8'))
                    fh = open(f"{cluster_build_files_path}/{template_vars['ImageName']}.yml", 'w')
                    fh.write(build_file_content)

        ansible_head_node_template_vars = self.get_instance_template_vars('ParallelClusterHeadNode')
        fh = NamedTemporaryFile('w', delete=False)
        fh.write('---\n')
        for name, value in sorted(ansible_head_node_template_vars.items()):
            fh.write(f"{name:35}: {value}\n")
        fh.close()
        local_file = fh.name
        s3_key = f"{self.assets_base_key}/config/ansible/ansible_head_node_vars.yml"
        self.s3_client.upload_file(
            local_file,
            self.assets_bucket,
            s3_key)
        with open(local_file, 'rb') as fh:
            self.assets_hash.update(fh.read())

        ansible_compute_node_template_vars = self.get_instance_template_vars('ParallelClusterComputeNode')
        fh = NamedTemporaryFile('w', delete=False)
        fh.write('---\n')
        for name, value in sorted(ansible_compute_node_template_vars.items()):
            fh.write(f"{name:20}: {value}\n")
        fh.close()
        local_file = fh.name
        s3_key = f"{self.assets_base_key}/config/ansible/ansible_compute_node_vars.yml"
        self.s3_client.upload_file(
            local_file,
            self.assets_bucket,
            s3_key)
        with open(local_file, 'rb') as fh:
            self.assets_hash.update(fh.read())

        ansible_submitter_template_vars = self.get_instance_template_vars('ParallelClusterSubmitter')
        fh = NamedTemporaryFile('w', delete=False)
        fh.write('---\n')
        for name, value in sorted(ansible_submitter_template_vars.items()):
            fh.write(f"{name:28}: {value}\n")
        fh.close()
        local_file = fh.name
        s3_key = f"{self.assets_base_key}/config/ansible/ansible_submitter_vars.yml"
        self.s3_client.upload_file(
            local_file,
            self.assets_bucket,
            s3_key)
        with open(local_file, 'rb') as fh:
            self.assets_hash.update(fh.read())

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
                    {'Name': 'name', 'Values': [f"Rocky-{version}-EC2-Base-{version}.8*"]},
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
        if not images:
            logger.error(f"No AMI found for {distribution} {version} {architecture}")
            exit(1)
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

        createBuildFilesLambdaAsset = s3_assets.Asset(self, "CreateBuildFilesAsset", path="resources/lambdas/CreateBuildFiles")
        self.create_build_files_lambda = aws_lambda.Function(
            self, "CreateBuildFilesLambda",
            function_name=f"{self.stack_name}-CreateBuildFiles",
            description="Create ParallelCluster build configuration files",
            memory_size=2048,
            runtime=aws_lambda.Runtime.PYTHON_3_9,
            architecture=aws_lambda.Architecture.X86_64,
            timeout=Duration.minutes(2),
            log_retention=logs.RetentionDays.INFINITE,
            handler="CreateBuildFiles.lambda_handler",
            code=aws_lambda.Code.from_bucket(createBuildFilesLambdaAsset.bucket, createBuildFilesLambdaAsset.s3_object_key),
            layers=[self.parallel_cluster_lambda_layer],
            environment = {
                'AmiBuildsJson': json.dumps(self.ami_builds),
                'AssetReadPolicyArn': self.parallel_cluster_asset_read_policy.managed_policy_arn,
                'AssetsBaseKey': self.assets_base_key,
                'AssetsBucket': self.assets_bucket,
                'ClusterName': self.config['slurm']['ClusterName'],
                'ConfigureEdaScriptS3Url': self.custom_action_s3_urls['config/bin/configure-eda.sh'],
                'ErrorSnsTopicArn': self.config['ErrorSnsTopicArn'],
                'ImageBuilderSecurityGroupId': self.imagebuilder_sg.security_group_id,
                'ParallelClusterVersion': self.config['slurm']['ParallelClusterConfig']['Version'],
                'Region': self.cluster_region,
                'SubnetId': self.config['SubnetId'],
            }
        )
        self.create_build_files_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    's3:DeleteObject',
                    's3:GetObject',
                    's3:PutObject'
                ],
                resources=[
                    f"arn:{Aws.PARTITION}:s3:::{self.assets_bucket}/{self.config['slurm']['ClusterName']}/*"
                    ]
                )
            )
        self.create_build_files_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    'ec2:DescribeImages'
                ],
                resources=[
                    f"*"
                    ]
                )
            )
        self.create_build_files_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    'sns:Publish'
                ],
                resources=[self.config['ErrorSnsTopicArn']]
                )
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
            environment = {
                'ErrorSnsTopicArn': self.config['ErrorSnsTopicArn']
            }
        )
        self.create_parallel_cluster_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    's3:DeleteObject',
                    's3:GetObject',
                    's3:PutObject'
                ],
                resources=[
                    f"arn:{Aws.PARTITION}:s3:::{self.assets_bucket}/{self.config['slurm']['ClusterName']}/*",
                    f"arn:{Aws.PARTITION}:s3:::{self.assets_bucket}/{self.config['slurm']['ClusterName']}/{self.parallel_cluster_config_json_s3_key}"
                    ]
                )
            )
        self.create_parallel_cluster_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    'sns:Publish'
                ],
                resources=[self.config['ErrorSnsTopicArn']]
                )
            )
        # From https://docs.aws.amazon.com/parallelcluster/latest/ug/iam-roles-in-parallelcluster-v3.html#iam-roles-in-parallelcluster-v3-base-user-policy
        self.create_parallel_cluster_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "cloudformation:*",
                    "cloudwatch:DeleteAlarms",
                    "cloudwatch:DeleteDashboards",
                    "cloudwatch:DescribeAlarms",
                    "cloudwatch:GetDashboard",
                    "cloudwatch:ListDashboards",
                    "cloudwatch:PutDashboard",
                    "cloudwatch:PutCompositeAlarm",
                    "cloudwatch:PutMetricAlarm",
                    'ec2:AllocateAddress',
                    'ec2:AssociateAddress',
                    'ec2:AttachNetworkInterface',
                    'ec2:AuthorizeSecurityGroupEgress',
                    'ec2:AuthorizeSecurityGroupIngress',
                    'ec2:CreateFleet',
                    'ec2:CreateLaunchTemplate',
                    'ec2:CreateLaunchTemplateVersion',
                    'ec2:CreateNetworkInterface',
                    'ec2:CreatePlacementGroup',
                    'ec2:CreateSecurityGroup',
                    'ec2:CreateSnapshot',
                    'ec2:CreateTags',
                    'ec2:CreateVolume',
                    'ec2:DeleteLaunchTemplate',
                    'ec2:DeleteNetworkInterface',
                    'ec2:DeletePlacementGroup',
                    'ec2:DeleteSecurityGroup',
                    'ec2:DeleteVolume',
                    'ec2:Describe*',
                    'ec2:DisassociateAddress',
                    'ec2:ModifyLaunchTemplate',
                    'ec2:ModifyNetworkInterfaceAttribute',
                    'ec2:ModifyVolume',
                    'ec2:ModifyVolumeAttribute',
                    'ec2:ReleaseAddress',
                    'ec2:RevokeSecurityGroupEgress',
                    'ec2:RevokeSecurityGroupIngress',
                    'ec2:RunInstances',
                    'ec2:TerminateInstances',
                    "fsx:DescribeFileCaches",
                    "logs:DeleteLogGroup",
                    "logs:PutRetentionPolicy",
                    "logs:DescribeLogGroups",
                    "logs:CreateLogGroup",
                    "logs:TagResource",
                    "logs:UntagResource",
                    "logs:FilterLogEvents",
                    "logs:GetLogEvents",
                    "logs:CreateExportTask",
                    "logs:DescribeLogStreams",
                    "logs:DescribeExportTasks",
                    "logs:DescribeMetricFilters",
                    "logs:PutMetricFilter",
                    "logs:DeleteMetricFilter",
                    "resource-groups:ListGroupResources",
                    "route53:ChangeResourceRecordSets",
                    "route53:ChangeTagsForResource",
                    "route53:CreateHostedZone",
                    "route53:DeleteHostedZone",
                    "route53:GetChange",
                    "route53:GetHostedZone",
                    "route53:ListResourceRecordSets",
                    "route53:ListQueryLoggingConfigs",
                ],
                resources=['*']
                )
            )
        self.create_parallel_cluster_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    'dynamodb:DescribeTable',
                    'dynamodb:ListTagsOfResource',
                    'dynamodb:CreateTable',
                    'dynamodb:DeleteTable',
                    'dynamodb:GetItem',
                    'dynamodb:PutItem',
                    'dynamodb:UpdateItem',
                    'dynamodb:Query',
                    'dynamodb:TagResource'
                ],
                resources=[f"arn:{Aws.PARTITION}:dynamodb:*:{Aws.ACCOUNT_ID}:table/parallelcluster-*"]
                )
            )
        self.create_parallel_cluster_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "iam:GetRole",
                    "iam:GetRolePolicy",
                    "iam:GetPolicy",
                    "iam:SimulatePrincipalPolicy",
                    "iam:GetInstanceProfile"
                ],
                resources=[
                    f"arn:{Aws.PARTITION}:iam::{Aws.ACCOUNT_ID}:role/*",
                    f"arn:{Aws.PARTITION}:iam::{Aws.ACCOUNT_ID}:policy/*",
                    f"arn:{Aws.PARTITION}:iam::aws:policy/*",
                    f"arn:{Aws.PARTITION}:iam::{Aws.ACCOUNT_ID}:instance-profile/*"
                    ]
                )
            )
        self.create_parallel_cluster_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "iam:CreateInstanceProfile",
                    "iam:DeleteInstanceProfile",
                    "iam:AddRoleToInstanceProfile",
                    "iam:RemoveRoleFromInstanceProfile"
                ],
                resources=[f"arn:{Aws.PARTITION}:iam::{Aws.ACCOUNT_ID}:instance-profile/parallelcluster/*"]
                )
            )
        self.create_parallel_cluster_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "iam:PassRole"
                ],
                resources=[
                    f"arn:{Aws.PARTITION}:iam::{Aws.ACCOUNT_ID}:role/parallelcluster/*"
                    ]
                )
                # "Condition": {
                #     "StringEqualsIfExists": {
                #         "iam:PassedToService": [
                #             "lambda.amazonaws.com",
                #             "ec2.amazonaws.com",
                #             "spotfleet.amazonaws.com"
                #         ]
                #     }
                #  },
            )
        self.create_parallel_cluster_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "lambda:CreateFunction",
                    "lambda:DeleteFunction",
                    "lambda:GetFunctionConfiguration",
                    "lambda:GetFunction",
                    "lambda:InvokeFunction",
                    "lambda:AddPermission",
                    "lambda:RemovePermission",
                    "lambda:UpdateFunctionConfiguration",
                    "lambda:TagResource",
                    "lambda:ListTags",
                    "lambda:UntagResource"
                ],
                resources=[
                    f"arn:{Aws.PARTITION}:lambda:*:{Aws.ACCOUNT_ID}:function:parallelcluster-*",
                    f"arn:{Aws.PARTITION}:lambda:*:{Aws.ACCOUNT_ID}:function:pcluster-*"
                    ]
                )
            )
        self.create_parallel_cluster_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:*"
                ],
                resources=[
                    f"arn:{Aws.PARTITION}:s3:::parallelcluster-*",
                    f"arn:{Aws.PARTITION}:s3:::aws-parallelcluster-*"
                    ]
                )
            )
        self.create_parallel_cluster_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:Get*",
                    "s3:List*"
                ],
                resources=[f"arn:{Aws.PARTITION}:s3:::*-aws-parallelcluster*"]
                )
            )
        self.create_parallel_cluster_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "elasticfilesystem:*"
                ],
                resources=[
                    f"arn:{Aws.PARTITION}:elasticfilesystem:*:{Aws.ACCOUNT_ID}:*"
                    ]
                )
            )
        self.create_parallel_cluster_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "secretsmanager:DescribeSecret"
                ],
                resources=[f"arn:{Aws.PARTITION}:secretsmanager:{self.config['Region']}:{Aws.ACCOUNT_ID}:secret:*"]
                )
            )
        # https://docs.aws.amazon.com/parallelcluster/latest/ug/iam-roles-in-parallelcluster-v3.html#iam-roles-in-parallelcluster-v3-user-policy-manage-iam
        # From Privileged IAM access mode
        self.create_parallel_cluster_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "iam:AttachRolePolicy",
                    "iam:CreateRole",
                    "iam:CreateServiceLinkedRole",
                    "iam:DeleteRole",
                    "iam:DeleteRolePolicy",
                    "iam:DetachRolePolicy",
                    "iam:PutRolePolicy",
                    "iam:TagRole",
                ],
                resources=[
                    f"arn:{Aws.PARTITION}:iam::{Aws.ACCOUNT_ID}:role/parallelcluster/*"
                    ]
                )
            )
        if self.munge_key_secret_arn:
            self.create_parallel_cluster_lambda.add_to_role_policy(
                statement=iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        "secretsmanager:GetSecretValue"
                    ],
                    resources=[self.munge_key_secret_arn]
                    )
                )

        createHeadNodeARecordAsset = s3_assets.Asset(self, "CreateHeadNodeARecordAsset", path="resources/lambdas/CreateHeadNodeARecord")
        self.create_head_node_a_record_lambda = aws_lambda.Function(
            self, "CreateHeadNodeARecordLambda",
            function_name=f"{self.stack_name}-CreateHeadNodeARecord",
            description="Create head node A record",
            memory_size=2048,
            runtime=aws_lambda.Runtime.PYTHON_3_9,
            architecture=aws_lambda.Architecture.X86_64,
            timeout=Duration.minutes(15),
            log_retention=logs.RetentionDays.INFINITE,
            handler="CreateHeadNodeARecord.lambda_handler",
            code=aws_lambda.Code.from_bucket(createHeadNodeARecordAsset.bucket, createHeadNodeARecordAsset.s3_object_key),
            environment = {
                'ClusterName': self.config['slurm']['ClusterName'],
                'ErrorSnsTopicArn': self.config['ErrorSnsTopicArn'],
                'Region': self.cluster_region,
            }
        )
        self.create_head_node_a_record_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    'ec2:DescribeInstances',
                    'route53:ChangeResourceRecordSets',
                    'route53:ListHostedZones',
                    'route53:ListResourceRecordSets',
                ],
                resources=['*']
                )
            )
        self.create_head_node_a_record_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    'sns:Publish'
                ],
                resources=[self.config['ErrorSnsTopicArn']]
                )
            )
        self.create_head_node_a_record_lambda.add_event_source(
            lambda_event_sources.SnsEventSource(self.create_head_node_a_record_sns_topic)
        )
        self.create_head_node_a_record_sns_topic.grant_publish(self.parallel_cluster_sns_publish_policy)

        updateHeadNodeLambdaAsset = s3_assets.Asset(self, "UpdateHeadNodeAsset", path="resources/lambdas/UpdateHeadNode")
        self.update_head_node_lambda = aws_lambda.Function(
            self, "UpdateHeadNodeLambda",
            function_name=f"{self.stack_name}-UpdateHeadNode",
            description="Update head node",
            memory_size=2048,
            runtime=aws_lambda.Runtime.PYTHON_3_9,
            architecture=aws_lambda.Architecture.X86_64,
            timeout=Duration.minutes(15),
            log_retention=logs.RetentionDays.INFINITE,
            handler="UpdateHeadNode.lambda_handler",
            code=aws_lambda.Code.from_bucket(updateHeadNodeLambdaAsset.bucket, updateHeadNodeLambdaAsset.s3_object_key),
            environment = {
                'ClusterName': self.config['slurm']['ClusterName'],
                'ErrorSnsTopicArn': self.config['ErrorSnsTopicArn'],
                'Region': self.cluster_region
            }
        )
        self.update_head_node_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    'ec2:DescribeInstances',
                    'ssm:GetCommandInvocation',
                    'ssm:SendCommand',
                ],
                resources=['*']
                )
            )
        self.update_head_node_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    'sns:Publish'
                ],
                resources=[self.config['ErrorSnsTopicArn']]
                )
            )

        if 'RESEnvironmentName' in self.config:
            configureClusterManagerLambdaAsset = s3_assets.Asset(self, "ConfigureClusterManagerAsset", path="resources/lambdas/ConfigureClusterManager")
            self.configure_cluster_manager_lambda = aws_lambda.Function(
                self, "ConfigureClusterManagerLambda",
                function_name=f"{self.stack_name}-ConfigureClusterManager",
                description="Configure RES cluster manager",
                memory_size=2048,
                runtime=aws_lambda.Runtime.PYTHON_3_9,
                architecture=aws_lambda.Architecture.X86_64,
                timeout=Duration.minutes(15),
                log_retention=logs.RetentionDays.INFINITE,
                handler="ConfigureClusterManager.lambda_handler",
                code=aws_lambda.Code.from_bucket(configureClusterManagerLambdaAsset.bucket, configureClusterManagerLambdaAsset.s3_object_key),
                environment = {
                    'ClusterName': self.config['slurm']['ClusterName'],
                'ErrorSnsTopicArn': self.config['ErrorSnsTopicArn'],
                    'Region': self.cluster_region,
                    'RESEnvironmentName': self.config['RESEnvironmentName']
                }
            )
            self.configure_cluster_manager_lambda.add_to_role_policy(
                statement=iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        'ec2:DescribeInstances',
                        'ssm:GetCommandInvocation',
                        'ssm:SendCommand',
                    ],
                    resources=['*']
                    )
                )
            self.configure_cluster_manager_lambda.add_to_role_policy(
                statement=iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        'sns:Publish'
                    ],
                    resources=[self.config['ErrorSnsTopicArn']]
                    )
                )
            self.configure_cluster_manager_lambda.add_event_source(
                lambda_event_sources.SnsEventSource(self.configure_cluster_manager_sns_topic)
            )
            self.configure_cluster_manager_sns_topic.grant_publish(self.parallel_cluster_sns_publish_policy)

            configureSubmittersLambdaAsset = s3_assets.Asset(self, "ConfigureSubmittersAsset", path="resources/lambdas/ConfigureSubmitters")
            self.configure_submitters_lambda = aws_lambda.Function(
                self, "ConfigureSubmittersLambda",
                function_name=f"{self.stack_name}-ConfigureSubmitters",
                description="Configure submitters",
                memory_size=2048,
                runtime=aws_lambda.Runtime.PYTHON_3_9,
                architecture=aws_lambda.Architecture.X86_64,
                timeout=Duration.minutes(15),
                log_retention=logs.RetentionDays.INFINITE,
                handler="ConfigureSubmitters.lambda_handler",
                code=aws_lambda.Code.from_bucket(configureSubmittersLambdaAsset.bucket, configureSubmittersLambdaAsset.s3_object_key),
                environment = {
                    'Region': self.cluster_region,
                    'ClusterName': self.config['slurm']['ClusterName'],
                    'ErrorSnsTopicArn': self.config['ErrorSnsTopicArn'],
                    'RESEnvironmentName': self.config['RESEnvironmentName']
                }
            )
            self.configure_submitters_lambda.add_to_role_policy(
                statement=iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        'ec2:DescribeInstances',
                        'ssm:GetCommandInvocation',
                        'ssm:SendCommand',
                    ],
                    resources=['*']
                    )
                )
            self.configure_submitters_lambda.add_to_role_policy(
                statement=iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        'sns:Publish'
                    ],
                    resources=[self.config['ErrorSnsTopicArn']]
                    )
                )
            self.configure_submitters_lambda.add_event_source(
                lambda_event_sources.SnsEventSource(self.configure_submitters_sns_topic)
            )
            self.configure_submitters_sns_topic.grant_publish(self.parallel_cluster_sns_publish_policy)

            self.deconfigureClusterManagerLambdaAsset = s3_assets.Asset(self, "DeconfigureClusterManagerAsset", path="resources/lambdas/DeconfigureClusterManager")
            self.deconfigure_cluster_manager_lambda = aws_lambda.Function(
                self, "DeconfigureClusterManagerLambda",
                function_name=f"{self.stack_name}-DeconfigureClusterManager",
                description="Deconfigure RES cluster manager",
                memory_size=2048,
                runtime=aws_lambda.Runtime.PYTHON_3_9,
                architecture=aws_lambda.Architecture.X86_64,
                timeout=Duration.minutes(15),
                log_retention=logs.RetentionDays.INFINITE,
                handler="DeconfigureClusterManager.lambda_handler",
                code=aws_lambda.Code.from_bucket(self.deconfigureClusterManagerLambdaAsset.bucket, self.deconfigureClusterManagerLambdaAsset.s3_object_key),
                environment = {
                    'ClusterName': self.config['slurm']['ClusterName'],
                    'ErrorSnsTopicArn': self.config['ErrorSnsTopicArn'],
                    'Region': self.cluster_region,
                    'RESEnvironmentName': self.config['RESEnvironmentName']
                }
            )
            self.deconfigure_cluster_manager_lambda.add_to_role_policy(
                statement=iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        'ec2:DescribeInstances',
                        'ssm:GetCommandInvocation',
                        'ssm:SendCommand',
                    ],
                    resources=['*']
                    )
                )
            self.deconfigure_cluster_manager_lambda.add_to_role_policy(
                statement=iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        'sns:Publish'
                    ],
                    resources=[self.config['ErrorSnsTopicArn']]
                    )
                )

            deconfigureSubmittersLambdaAsset = s3_assets.Asset(self, "DeconfigureSubmittersAsset", path="resources/lambdas/DeconfigureSubmitters")
            self.deconfigure_submitters_lambda = aws_lambda.Function(
                self, "DeconfigureSubmittersLambda",
                function_name=f"{self.stack_name}-DeconfigureSubmitters",
                description="Deconfigure submitters",
                memory_size=2048,
                runtime=aws_lambda.Runtime.PYTHON_3_9,
                architecture=aws_lambda.Architecture.X86_64,
                timeout=Duration.minutes(15),
                log_retention=logs.RetentionDays.INFINITE,
                handler="DeconfigureSubmitters.lambda_handler",
                code=aws_lambda.Code.from_bucket(deconfigureSubmittersLambdaAsset.bucket, deconfigureSubmittersLambdaAsset.s3_object_key),
                environment = {
                    'ClusterName': self.config['slurm']['ClusterName'],
                    'ErrorSnsTopicArn': self.config['ErrorSnsTopicArn'],
                    'Region': self.cluster_region,
                    'RESEnvironmentName': self.config['RESEnvironmentName']
                }
            )
            self.deconfigure_submitters_lambda.add_to_role_policy(
                statement=iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        'ec2:DescribeInstances',
                        'ssm:GetCommandInvocation',
                        'ssm:SendCommand',
                    ],
                    resources=['*']
                    )
                )
            self.deconfigure_submitters_lambda.add_to_role_policy(
                statement=iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        'sns:Publish'
                    ],
                    resources=[self.config['ErrorSnsTopicArn']]
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
                'ErrorSnsTopicArn': self.config['ErrorSnsTopicArn'],
                'SLURM_REST_API_VERSION': self.config['slurm']['SlurmCtl']['SlurmRestApiVersion'],
                'SLURMRESTD_URL': f"http://slurmctl1.{self.config['slurm']['ClusterName']}.pcluster:{self.slurmrestd_port}"
                }
        )
        self.call_slurm_rest_api_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    'sns:Publish'
                ],
                resources=[self.config['ErrorSnsTopicArn']]
                )
            )

        self.jwt_token_for_root_ssm_parameter.grant_read(self.call_slurm_rest_api_lambda)

        self.jwt_token_for_slurmrestd_ssm_parameter.grant_read(self.call_slurm_rest_api_lambda)

        self.parallel_cluster_jwt_write_policy = iam.ManagedPolicy(
            self, "ParallelClusterJwtWritePolicy",
            #managed_policy_name = f"{self.stack_name}-ParallelClusterJwtWritePolicy",
        )
        self.jwt_token_for_root_ssm_parameter.grant_write(self.parallel_cluster_jwt_write_policy)
        self.jwt_token_for_slurmrestd_ssm_parameter.grant_write(self.parallel_cluster_jwt_write_policy)

    def create_security_groups(self):
        self.NFS_PORT = 2049
        self.slurmctld_port_min = 6820
        self.slurmctld_port_max = 6829
        self.slurmctld_port = '6820-6829'
        self.slurmd_port = 6818
        self.slurmdbd_port = 6819
        self.slurmrestd_port = 6830

        self.imagebuilder_sg = ec2.SecurityGroup(self, "ImageBuilderSG", vpc=self.vpc, allow_all_outbound=True, description="ImageBuilder Security Group")
        Tags.of(self.imagebuilder_sg).add("Name", f"{self.stack_name}-ImageBuilderSG")
        # W5:Security Groups found with cidr open to world on egress
        self.suppress_cfn_nag(self.imagebuilder_sg, 'W5', 'All outbound allowed.')
        # W40:Security Groups egress with an IpProtocol of -1 found
        self.suppress_cfn_nag(self.imagebuilder_sg, 'W40', 'All outbound allowed.')

        self.nfs_sg = ec2.SecurityGroup(self, "NfsSG", vpc=self.vpc, allow_all_outbound=False, description="Nfs Security Group")
        Tags.of(self.nfs_sg).add("Name", f"{self.stack_name}-NfsSG")
        self.suppress_cfn_nag(self.nfs_sg, 'W29', 'Egress port range used to block all egress')

        # FSxZ requires all output access
        self.zfs_sg = ec2.SecurityGroup(self, "ZfsSG", vpc=self.vpc, allow_all_outbound=True, description="Zfs Security Group")
        Tags.of(self.zfs_sg).add("Name", f"{self.stack_name}-ZfsSG")
        # W5:Security Groups found with cidr open to world on egress
        self.suppress_cfn_nag(self.zfs_sg, 'W5', 'FSxZ requires all egress access.')
        # W40:Security Groups egress with an IpProtocol of -1 found
        self.suppress_cfn_nag(self.zfs_sg, 'W40', 'FSxZ requires all egress access.')
        #self.suppress_cfn_nag(self.zfs_sg, 'W29', 'Egress port range used to block all egress')

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
            fs_client_sg.connections.allow_to(self.nfs_sg, ec2.Port.tcp(self.NFS_PORT), f"{fs_client_sg_name} to Nfs")
        if self.onprem_cidr:
            self.nfs_sg.connections.allow_from(self.onprem_cidr, ec2.Port.tcp(self.NFS_PORT), 'OnPremNodes to Nfs')
        # Allow compute nodes in remote regions access to NFS
        for compute_region, compute_region_cidr in self.remote_compute_regions.items():
            self.nfs_sg.connections.allow_from(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.tcp(self.NFS_PORT), f"{compute_region} to Nfs")

        # ZFS Connections
        # https://docs.aws.amazon.com/fsx/latest/OpenZFSGuide/limit-access-security-groups.html
        for fs_client_sg_name, fs_client_sg in fs_client_sgs.items():
            fs_client_sg.connections.allow_to(self.zfs_sg, ec2.Port.tcp(111), f"{fs_client_sg_name} to Zfs")
            fs_client_sg.connections.allow_to(self.zfs_sg, ec2.Port.udp(111), f"{fs_client_sg_name} to Zfs")
            fs_client_sg.connections.allow_to(self.zfs_sg, ec2.Port.tcp(self.NFS_PORT), f"{fs_client_sg_name} to Zfs")
            fs_client_sg.connections.allow_to(self.zfs_sg, ec2.Port.udp(self.NFS_PORT), f"{fs_client_sg_name} to Zfs")
            fs_client_sg.connections.allow_to(self.zfs_sg, ec2.Port.tcp_range(20001, 20003), f"{fs_client_sg_name} to Zfs")
            fs_client_sg.connections.allow_to(self.zfs_sg, ec2.Port.udp_range(20001, 20003), f"{fs_client_sg_name} to Zfs")
            self.suppress_cfn_nag(fs_client_sg, 'W27', 'Correct, restricted range for zfs: 20001-20003')
            self.suppress_cfn_nag(fs_client_sg, 'W29', 'Correct, restricted range for zfs: 20001-20003')
        self.suppress_cfn_nag(self.zfs_sg, 'W27', 'Correct, restricted range for zfs: 20001-20003')
        if self.onprem_cidr:
            self.zfs_sg.connections.allow_from(self.onprem_cidr, ec2.Port.tcp(111), 'OnPremNodes to Zfs')
            self.zfs_sg.connections.allow_from(self.onprem_cidr, ec2.Port.udp(111), 'OnPremNodes to Zfs')
            self.zfs_sg.connections.allow_from(self.onprem_cidr, ec2.Port.tcp(self.NFS_PORT), 'OnPremNodes to Zfs')
            self.zfs_sg.connections.allow_from(self.onprem_cidr, ec2.Port.udp(self.NFS_PORT), 'OnPremNodes to Zfs')
            self.zfs_sg.connections.allow_from(self.onprem_cidr, ec2.Port.tcp_range(20001, 20003), 'OnPremNodes to Zfs')
            self.zfs_sg.connections.allow_from(self.onprem_cidr, ec2.Port.udp_range(20001, 20003), 'OnPremNodes to Zfs')
            self.suppress_cfn_nag(self.zfs_sg, 'W27', 'Correct, restricted range for zfs: 20001-20003')
            self.suppress_cfn_nag(self.zfs_sg, 'W29', 'Correct, restricted range for zfs: 20001-20003')
        # Allow compute nodes in remote regions access to ZFS
        for compute_region, compute_region_cidr in self.remote_compute_regions.items():
            self.zfs_sg.connections.allow_from(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.tcp(111), f"{compute_region} to Zfs")
            self.zfs_sg.connections.allow_from(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.udp(111), f"{compute_region} to Zfs")
            self.zfs_sg.connections.allow_from(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.tcp(self.NFS_PORT), f"{compute_region} to Zfs")
            self.zfs_sg.connections.allow_from(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.udp(self.NFS_PORT), f"{compute_region} to Zfs")
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
                    self.slurmnode_sg.connections.allow_to(extra_mount_sg, ec2.Port.tcp(self.NFS_PORT), f"SlurmNode to {extra_mount_sg_name} - Nfs")
                    if fs_type == 'zfs':
                        self.slurmnode_sg.connections.allow_to(extra_mount_sg, ec2.Port.tcp(111), f"SlurmNode to {extra_mount_sg_name} - Zfs")
                        self.slurmnode_sg.connections.allow_to(extra_mount_sg, ec2.Port.udp(111), f"SlurmNode to {extra_mount_sg_name} - Zfs")
                        self.slurmnode_sg.connections.allow_to(extra_mount_sg, ec2.Port.udp(self.NFS_PORT), f"SlurmNode to {extra_mount_sg_name} - Zfs")
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
            slurm_submitter_sg.connections.allow_to(self.slurmctl_sg, ec2.Port.tcp(self.NFS_PORT), f"{slurm_submitter_sg_name} to {self.slurmctl_sg_name} - NFS")
            slurm_submitter_sg.connections.allow_to(self.slurmctl_sg, ec2.Port.tcp_range(self.slurmctld_port_min, self.slurmctld_port_max), f"{slurm_submitter_sg_name} to {self.slurmctl_sg_name}")
            slurm_submitter_sg.connections.allow_to(self.slurmnode_sg, ec2.Port.tcp(self.slurmd_port), f"{slurm_submitter_sg_name} to {self.slurmnode_sg_name} - srun")
            if self.slurmdbd_sg:
                slurm_submitter_sg.connections.allow_to(self.slurmdbd_sg, ec2.Port.tcp(self.slurmdbd_port), f"{slurm_submitter_sg_name} to {self.slurmdbd_sg_name} - sacct")
            slurm_submitter_sg.connections.allow_to(self.slurmctl_sg, ec2.Port.tcp(self.slurmrestd_port), f"{slurm_submitter_sg_name} to {self.slurmctl_sg_name} - slurmrestd")
            if self.onprem_cidr:
                slurm_submitter_sg.connections.allow_to(self.onprem_cidr, ec2.Port.tcp(self.slurmd_port), f"{slurm_submitter_sg_name} to OnPremNodes - srun")
            for compute_region, compute_region_cidr in self.remote_compute_regions.items():
                slurm_submitter_sg.connections.allow_to(ec2.Peer.ipv4(compute_region_cidr), ec2.Port.tcp(self.slurmd_port), f"{slurm_submitter_sg_name} to {compute_region} - srun")
            # W29:Security Groups found egress with port range instead of just a single port
            self.suppress_cfn_nag(self.slurmnode_sg, 'W29', 'Port range ok. Submitter to SlurmCtl requires range for slurmctld ports')

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

        if instance_role == 'ParallelClusterHeadNode':
            instance_template_vars['PCSlurmVersion'] =  get_PC_SLURM_VERSION(self.config)
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
            instance_template_vars['SlurmVersion']                = get_SLURM_VERSION(self.config)
            instance_template_vars['ParallelClusterMungeVersion'] = get_PARALLEL_CLUSTER_MUNGE_VERSION(self.config)
            instance_template_vars['SlurmrestdPort']        = self.slurmrestd_port
            instance_template_vars['FileSystemMountPath']   = f'/opt/slurm/{cluster_name}'
            instance_template_vars['SlurmBaseDir']          = f'/opt/slurm/{cluster_name}'
            instance_template_vars['SubmitterSlurmBaseDir'] = f'/opt/slurm/{cluster_name}'
            instance_template_vars['SlurmConfigDir']        = f'/opt/slurm/{cluster_name}/config'
            instance_template_vars['SlurmSrcDir']           = f'/opt/slurm/{cluster_name}/config/src'
            instance_template_vars['SlurmEtcDir']           = f'/opt/slurm/{cluster_name}/etc'
            instance_template_vars['ModulefilesBaseDir']    = f'/opt/slurm/{cluster_name}/config/modules/modulefiles'

        elif instance_role == 'ParallelClusterComputeNode':
            pass
        else:
            raise ValueError(f"Invalid instance role {instance_role}")

        return instance_template_vars

    def create_munge_key_secret(self):
        self.munge_key_secret_arn = None
        if 'MungeKeySecret' not in self.config['slurm']:
            return

        # Check to see if secret exists
        # Use it if it exists, otherwise create a new secret
        secretsmanager_client = boto3.client('secretsmanager', region_name=self.cluster_region)
        try:
            response = secretsmanager_client.get_secret_value(
                SecretId = self.config['slurm']['MungeKeySecret']
            )
            self.munge_key_secret_arn = response['ARN']
            secret_string = response['SecretString']
            logger.info(f"Munge key secret exists and will be used: {secret_string} length={len(secret_string)}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                logger.info(f"MungeKeySecret {self.config['slurm']['MungeKeySecret']} doesn't exist so creating for you.")
            else:
                logger.exception("Error getting MungeKeySecret {self.config['slurm']['MungeKeySecret']}")

        if not self.munge_key_secret_arn:
            logger.info(f"{self.config['slurm']['MungeKeySecret']} doesn't exist so creating it. This isn't a stack resource and will not be deleted with the stack.")
            output = check_output(['dd if=/dev/random bs=1 count=1024 | base64 -w 0'], shell=True, stderr=subprocess.DEVNULL, encoding='utf8', errors='ignore')
            munge_key = output.split('\n')[0]
            secretsmanager_client.create_secret(
                Name = self.config['slurm']['MungeKeySecret'],
                SecretString = munge_key
            )
            self.munge_key_secret_arn = secretsmanager_client.get_secret_value(
                SecretId = self.config['slurm']['MungeKeySecret']
            )['ARN']

        if self.munge_key_secret_arn:
            self.munge_key_secret = secretsmanager.Secret.from_secret_complete_arn(
                self, 'MungeKeySecret',
                secret_complete_arn = self.munge_key_secret_arn
            )
            self.munge_key_secret.grant_read(self.parallel_cluster_asset_read_policy)
            logger.info(f"Munge key secret arn: {self.munge_key_secret_arn}")

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
        # W84: CloudWatchLogs LogGroup should specify a KMS Key Id to encrypt the log data
        self.suppress_cfn_nag(fis_log_group, 'W84', 'Use default KMS key.')
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

    def ami_supports_instance_type(self, image_id, instance_type):
        # Check to see if the instance type is supported by the AMI
        supports = False
        error_message = None
        try:
            self.ec2_client.run_instances(
                ImageId = image_id,
                InstanceType = instance_type,
                SubnetId = self.config['SubnetId'],
                MinCount = 1,
                MaxCount = 1,
                DryRun = True
            )
            assert False # Should always throw at least a DryRunOperation exception
        except ClientError as e:
            if e.response['Error']['Code'] == 'DryRunOperation':
                supports = True
            else:
                supports = False
                error_message = f"{e.response['Error']['Code']}: {e.response['Error']['Message']}"
        return supports, error_message

    def create_parallel_cluster_config(self):
        MAX_NUMBER_OF_QUEUES = 50
        MAX_NUMBER_OF_COMPUTE_RESOURCES = 50

        # Check the architecture of the ComputeNodeAmi
        if 'ComputeNodeAmi' in self.config['slurm']['ParallelClusterConfig']:
            compute_node_ami = self.config['slurm']['ParallelClusterConfig']['ComputeNodeAmi']
            images_info = self.ec2_client.describe_images(ImageIds=[compute_node_ami])['Images']
            if not images_info:
                logger.error(f"ComputeNodeAmi({compute_node_ami}) doesn't exist.")
                exit(1)
            ami_info = images_info[0]
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
                        {'Policy': self.parallel_cluster_sns_publish_policy.managed_policy_arn},
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

        if self.munge_key_secret_arn:
                self.parallel_cluster_config['Scheduling']['SlurmSettings']['MungeKeySecretArn'] = self.munge_key_secret_arn

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

        if 'CustomAmi' in self.config['slurm']['ParallelClusterConfig']['Image']:
            # Check that the AMI support the head node instance type
            head_node_ami = self.config['slurm']['ParallelClusterConfig']['Image']['CustomAmi']
            instance_type = self.config['slurm']['SlurmCtl']['instance_type']
            supports, error_message = self.ami_supports_instance_type(head_node_ami, instance_type)
            if not supports:
                logger.error(f"Head node instance type of {instance_type} not supported for {head_node_ami}. {error_message}")
                exit(1)
        else:
            head_node_ami = None

        if 'ComputeNodeAmi' in self.config['slurm']['ParallelClusterConfig']:
            compute_node_ami = self.config['slurm']['ParallelClusterConfig']['ComputeNodeAmi']
        elif 'CustomAmi' in self.config['slurm']['ParallelClusterConfig']['Image']:
            compute_node_ami = self.config['slurm']['ParallelClusterConfig']['Image']['CustomAmi']
        else:
            compute_node_ami = None

        # Create list of instance types by number of cores and amount of memory
        instance_types_by_core_memory = {}
        # Create list of instance types by amount of memory and number of cores
        instance_types_by_memory_core = {}
        logger.info(f"Bucketing {len(self.instance_types)} instance types based on core and memory")
        for instance_type in self.instance_types:
            if compute_node_ami:
                supports, error_message = self.ami_supports_instance_type(compute_node_ami, instance_type)
                if not supports:
                    logger.warning(f"{instance_type:12s} not supported for {compute_node_ami}. {error_message}")
                    continue

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
                logger.info(f"            {len(instance_types_by_core_memory[cores][mem_gb])} instance type with {mem_gb:4} GB: {instance_types_by_core_memory[cores][mem_gb]}")
        logger.info("Instance type by memory and core:")
        logger.info(f"    {len(instance_types_by_memory_core)} unique memory size:")
        for mem_gb in sorted(instance_types_by_memory_core):
            logger.info(f"        {mem_gb} GB")
            for cores in sorted(instance_types_by_memory_core[mem_gb]):
                logger.info(f"            {len(instance_types_by_memory_core[mem_gb][cores])} instance type with {cores:3} core(s): {instance_types_by_memory_core[mem_gb][cores]}")

        purchase_options = ['ONDEMAND']
        if self.config['slurm']['InstanceConfig']['UseSpot']:
            purchase_options.append('SPOT')

        nodesets = {}
        number_of_queues = 0
        number_of_compute_resources = 0
        for purchase_option in purchase_options:
            nodesets[purchase_option] = []
        if config_schema.PARALLEL_CLUSTER_SUPPORTS_MULTIPLE_COMPUTE_RESOURCES_PER_QUEUE(self.PARALLEL_CLUSTER_VERSION) and config_schema.PARALLEL_CLUSTER_SUPPORTS_MULTIPLE_COMPUTE_RESOURCES_PER_QUEUE(self.PARALLEL_CLUSTER_VERSION):
            # Creating a queue for each memory size
            # In each queue, create a CR for each permutation of memory and core count
            for mem_gb in sorted(instance_types_by_memory_core.keys()):
                for purchase_option in purchase_options:
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
                    logger.info(f"Configuring {queue_name} queue:")
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
                                {'Policy': self.parallel_cluster_sns_publish_policy.managed_policy_arn}
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
                        instance_types = sorted(instance_types_by_memory_core[mem_gb][num_cores])
                        # If we do multiple CRs per queue then we hit the CR limit without being able to create queues for all memory sizes.
                        # Select the instance types with the lowest core count for higher memory/core ratio and lower cost.
                        if len(parallel_cluster_queue['ComputeResources']):
                            logger.info(f"    Skipping {compute_resource_name:18} compute resource: {instance_types} to reduce number of CRs.")
                            continue
                        if number_of_compute_resources >= MAX_NUMBER_OF_COMPUTE_RESOURCES:
                            logger.warning(f" Skipping {compute_resource_name:18} compute resource: {instance_types} because MAX_NUMBER_OF_COMPUTE_RESOURCES=={MAX_NUMBER_OF_COMPUTE_RESOURCES}")
                            continue
                        logger.info(f"    Adding   {compute_resource_name:18} compute resource: {instance_types}")
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
            # ParallelCluster has a restriction where a queue can have only 1 instance type with memory based scheduling
            # So, for now creating a queue for each instance type and purchase option
            for purchase_option in purchase_options:
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
                                {'Policy': self.parallel_cluster_sns_publish_policy.managed_policy_arn}
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
            if mount_dir == '/home' and not config_schema.PARALLEL_CLUSTER_SUPPORTS_HOME_MOUNT(self.PARALLEL_CLUSTER_VERSION):
                continue
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

        self.build_config_files = CustomResource(
            self, "BuildConfigFiles",
            service_token = self.create_build_files_lambda.function_arn
        )

        self.parallel_cluster = CustomResource(
            self, "ParallelCluster",
            service_token = self.create_parallel_cluster_lambda.function_arn,
            properties = {
                'ParallelClusterConfigHash': self.assets_hash.hexdigest(),
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
        # The lambda to create an A record for the head node must be built before the parallel cluster.
        self.parallel_cluster.node.add_dependency(self.create_head_node_a_record_lambda)
        self.parallel_cluster.node.add_dependency(self.update_head_node_lambda)
        # The lambdas to configure instances must exist befor the cluster so they can be called.
        self.parallel_cluster.node.add_dependency(self.configure_cluster_manager_lambda)
        self.parallel_cluster.node.add_dependency(self.configure_submitters_lambda)
        # Build config files need to be created before cluster so that they can be downloaded as part of on_head_node_configures
        self.parallel_cluster.node.add_dependency(self.build_config_files)

        self.call_slurm_rest_api_lambda.node.add_dependency(self.parallel_cluster)

        # Custom resource to update the head node anytime the assets_hash changes
        self.update_head_node = CustomResource(
            self, "UpdateHeadNode",
            service_token = self.update_head_node_lambda.function_arn,
            properties = {
                'ParallelClusterConfigHash': self.assets_hash.hexdigest(),
            }
        )
        self.update_head_node.node.add_dependency(self.parallel_cluster)

        if 'RESEnvironmentName' in self.config:
            # Custom resource to deconfigure cluster manager before deleting cluster
            self.deconfigure_cluster_manager = CustomResource(
                self, "DeconfigureClusterManager",
                service_token = self.deconfigure_cluster_manager_lambda.function_arn,
                properties = {
                }
            )
            self.deconfigure_cluster_manager.node.add_dependency(self.parallel_cluster)

            # Custom resource to deconfigure submitters before deleting cluster
            self.deconfigure_submitters = CustomResource(
                self, "DeconfigureSubmitters",
                service_token = self.deconfigure_submitters_lambda.function_arn,
                properties = {
                }
            )
            self.deconfigure_submitters.node.add_dependency(self.parallel_cluster)

        CfnOutput(self, "ParallelClusterConfigJsonS3Url",
            value = self.parallel_cluster_config_json_s3_url
        )
        CfnOutput(self, "ParallelClusterConfigYamlS3Url",
            value = self.parallel_cluster_config_yaml_s3_url
        )
        CfnOutput(self, "PlaybookS3Url",
            value = self.playbooks_asset.s3_object_url
        )
        region = self.cluster_region
        cluster_name = self.config['slurm']['ClusterName']
        CfnOutput(self, "Command01_SubmitterMountHeadNode",
            value = f"head_ip=head_node.{self.config['slurm']['ClusterName']}.pcluster && sudo mkdir -p /opt/slurm/{cluster_name} && sudo mount $head_ip:/opt/slurm /opt/slurm/{cluster_name}"
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
