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
    aws_s3_assets as s3_assets,
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
from constructs import Construct
from copy import copy, deepcopy
from jinja2 import Template as Template
import json
import logging
import os.path
from os.path import dirname, realpath
from pprint import PrettyPrinter
import sys
from tempfile import NamedTemporaryFile
from textwrap import dedent
from types import SimpleNamespace
import yaml
from yaml.scanner import ScannerError

sys.path.append(f"{dirname(__file__)}/../resources/playbooks/roles/SlurmCtl/files/opt/slurm/cluster/bin")
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

        # Read the config file and then any overrides from the context variables.
        self.config = self.get_config('config_file', 'default_config.yml')

        self.ami_map = self.get_config('ami_map', 'ami_map.yml')
        self.config.update(self.ami_map)

        # Get context variables to override the config
        self.get_context()

        self.check_config()

        plugin = SlurmPlugin(slurm_config_file=None, slurm_version_file=None, region=self.config['Region'])
        self.config['slurm']['InstanceTypes'] = plugin.get_instance_types_from_instance_config(self.config['slurm']['InstanceConfig'])
        if len(self.config['slurm']['InstanceTypes']) == 0:
            logger.error(f"No instance types found. Update slurm/InstanceConfig. Current value:\n{pp.pformat(self.config['slurm']['InstanceConfig'])}\n{self.config['slurm']['InstanceTypes']}")
            sys.exit(1)
        logger.info(f"{len(self.config['slurm']['InstanceTypes'])} instance types configured:\n{pp.pformat(self.config['slurm']['InstanceTypes'])}")

        # Assets must be created before setting instance_template_vars so the playbooks URL exists
        self.create_assets()

        self.create_lambdas()
        self.create_vpc()
        self.create_security_groups()
        if 'ElasticSearch' not in self.config['slurm']:
            self.create_elasticsearch()
        self.create_file_system()
        if 'SlurmDbd' in self.config['slurm']:
            self.create_db()
        self.create_cw()
        self.create_slurm_nodes()
        self.create_slurmctl()
        if 'SlurmDbd' in self.config['slurm']:
            self.create_slurmdbd()
        self.create_slurm_node_ami()
        self.create_fault_injection_templates()

    def get_config(self, context_var, default_path):
        default_config_file_path = realpath(f"{dirname(realpath(__file__))}/../resources/config/")
        config_file_path = self.node.try_get_context(context_var)
        if not config_file_path:
            config_file_path = f"{default_config_file_path}/{default_path}"
        if os.path.isabs(config_file_path):
            if not os.path.exists(config_file_path):
                logger.error(f"{config_file_path} does not exist")
                sys.exit(1)
        else:
            # Not an absolute path so check to see if it exists as a relative path
            if os.path.exists(config_file_path):
                config_file_path = realpath(config_file_path)
            elif os.path.exists(f"{default_config_file_path}/{config_file_path}"):
                # Check to see if in default config file path
                config_file_path = realpath(f"{default_config_file_path}/{config_file_path}")
            else:
                logger.error(f"Could not find {config_file_path}")
                sys.exit(1)
        logger.info(f"Using config: {config_file_path}")

        try:
            config_parameters = yaml.load(open(config_file_path, 'r'), Loader=yaml.FullLoader) # nosec
        except ScannerError as err:
            logger.error(f"{config_file_path} is not a valid YAML file. Verify syntax, {err}")
            sys.exit(1)
        except FileNotFoundError:
            logger.error(f"{config_file_path} not found")
            sys.exit(1)

        if context_var == 'config_file':
            # Validate config against schema
            from config_schema import check_schema
            from schema import SchemaError
            region = self.node.try_get_context('region')
            try:
                config_parameters = check_schema(config_parameters, [region])
            except SchemaError:
                logger.exception(f"Invalid config file: {config_file_path}")
                sys.exit(1)

        if config_parameters:
            return config_parameters
        else:
            sys.exit("No parameters were specified.")

    def get_context(self):
        # Get context variables to override the config

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
            sys.exit(1)

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
            sys.exit(1)

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
            sys.exit(1)

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
        # Check config, set defaults, and sanity check the configuration

        if self.stack_name:
            if 'StackName' not in self.config:
                logger.info(f"config/StackName set from command line: {self.stack_name}")
            elif self.stack_name != self.config['StackName']:
                logger.info(f"config/StackName in config file overridden on command line from {self.config['StackName']} to {self.stack_name}")
            self.config['StackName'] = self.stack_name
        if 'StackName' not in self.config:
            logger.error(f"You must provide --stack-name on the command line or StackName in the config file.")
            sys.exit(1)

        error_sns_topic_arn = self.node.try_get_context('ErrorSnsTopicArn')
        if error_sns_topic_arn:
            self.config['ErrorSnsTopicArn'] = error_sns_topic_arn
        else:
            if 'ErrorSnsTopicArn' not in self.config:
                logger.warning(f"ErrorSnsTopicArn not set. Provide error-sns-topic-arn on the command line or ErrorSnsTopicArn in the config file to get error notifications.")
                self.config['ErrorSnsTopicArn'] = ''

        if 'Domain' not in self.config and 'HostedZoneId' not in self.config:
            self.config['Domain'] = f"{self.stack_name}.local"
        if 'Domain' in self.config and 'HostedZoneId' in self.config:
            logger.error(f"Cannot specify both Domain({self.config['Domain']}) and HostedZoneId{self.config['HostedZoneId']}")
            sys.exist(1)

        if 'ClusterName' not in self.config['slurm']:
            self.config['slurm']['ClusterName'] = self.stack_name
            logger.info(f"slurm/ClusterName defaulted to {self.config['StackName']}")

        if 'mount_path' not in self.config['slurm']['storage']:
            self.config['slurm']['storage']['mount_path'] = f"/opt/slurm/{self.config['slurm']['ClusterName']}"

        if 'SlurmDbd' in self.config['slurm'] and 'ExistingSlurmDbd' in self.config['slurm']:
            logger.error(f"Cannot specify both slurm/SlurmDbd and slurm/ExistingSlurmDbd")
            sys.exit(1)

        self.useSlurmDbd = False
        self.slurmDbdFQDN = ''
        if 'SlurmDbd' in self.config['slurm']:
            self.useSlurmDbd = self.config['slurm']['SlurmDbd']['UseSlurmDbd']
            self.slurmDbdFQDN = f"{self.config['slurm']['SlurmDbd']['Hostname']}.{self.config['Domain']}"
        if 'ExistingSlurmDbd' in self.config['slurm']:
            self.useSlurmDbd = self.config['slurm']['ExistingSlurmDbd']['UseSlurmDbd']
            if 'StackName' in self.config['slurm']['ExistingSlurmDbd']:
                if 'SecurityGroup' in self.config['slurm']['ExistingSlurmDbd']:
                    logger.error("Cannot specify slurm/ExistingSlurmDbd/SecurityGroup if slurm/ExistingSlurmDbd/StackName set")
                    sys.exit(1)
                if 'HostnameFQDN' in self.config['slurm']['ExistingSlurmDbd']:
                    logger.error("Cannot specify slurm/ExistingSlurmDbd/HostnameFQDN if slurm/ExistingSlurmDbd/StackName set")
                    sys.exit(1)
                slurmdbd_stack_name = self.config['slurm']['ExistingSlurmDbd']['StackName']
                slurmDbdSG = None
                cfn_client = boto3.client('cloudformation', region_name=self.config['Region'])
                for page in cfn_client.get_paginator('list_stack_resources').paginate(StackName=slurmdbd_stack_name):
                    for resource in page['StackResourceSummaries']:
                        if resource['ResourceType'] == 'AWS::EC2::SecurityGroup':
                            logical_resource_id = resource['LogicalResourceId']
                            if logical_resource_id.startswith('SlurmDbdSG'):
                                slurmDbdSG = resource['PhysicalResourceId']
                if not slurmDbdSG:
                    logger.error(f"SlurmDbdSG resource not found in {slurmdbd_stack_name} stack")
                    sys.exit(1)
                self.config['slurm']['ExistingSlurmDbd']['SecurityGroup'] = {f"{slurmdbd_stack_name}-SlurmDbdSG": slurmDbdSG}
                # Find FQDN output
                stack_outputs = cfn_client.describe_stacks(StackName=slurmdbd_stack_name)['Stacks'][0]['Outputs']
                for output in stack_outputs:
                    if output['OutputKey'] == 'SlurmDbdFQDN':
                        self.slurmDbdFQDN = output['OutputValue']
                        break
                if not self.slurmDbdFQDN:
                    logger.error(f"SlurmDbdFQDN output not found in {slurmdbd_stack_name} stack")
                    sys.exit(1)
            else:
                if 'SecurityGroup' not in self.config['slurm']['ExistingSlurmDbd']:
                    logger.error("Must specify slurm/ExistingSlurmDbd/SecurityGroup if slurm/ExistingSlurmDbd/StackName is not set.")
                    sys.exit(1)
                if len(self.config['slurm']['SlurmDbd']['ExistingSlurmDbd']['SecurityGroup']) != 1:
                    logger.error(f"slurm/ExistingSlurmDbd/SecurityGroup dictionary must have only 1 entry")
                    sys.exit(1)
                if 'HostnameFQDN' not in self.config['slurm']['ExistingSlurmDbd']:
                    logger.error("Must specify slurm/ExistingSlurmDbd/HostnameFQDN if slurm/ExistingSlurmDbd/StackName is not set.")
                    sys.exit(1)
                self.slurmDbdFQDN = self.config['slurm']['ExistingSlurmDbd']['HostnameFQDN']

        if 'Federation' in self.config['slurm']:
            if 'FederatedClusterStackNames' in self.config['slurm']['Federation']:
                if 'SlurmCtlSecurityGroups' not in self.config['slurm']['Federation']:
                    self.config['slurm']['Federation']['SlurmCtlSecurityGroups'] = {}
                if 'SlurmNodeSecurityGroups' not in self.config['slurm']['Federation']:
                    self.config['slurm']['Federation']['SlurmNodeSecurityGroups'] = {}
                for federated_stack_name in self.config['slurm']['Federation']['FederatedClusterStackNames']:
                    cfn_client = boto3.client('cloudformation', region_name=self.config['Region'])
                    stacks = cfn_client.describe_stacks(StackName=federated_stack_name)['Stacks']
                    if len(stacks) != 1:
                        logger.error(f"Federated cluseter {federated_stack_name} does not exist.")
                        sys.exit(1)
                    slurmCtlSG = None
                    slurmNodeSG = None
                    for page in cfn_client.get_paginator('list_stack_resources').paginate(StackName=federated_stack_name):
                        for resource in page['StackResourceSummaries']:
                            resource_type = resource['ResourceType']
                            if resource_type == 'AWS::EC2::SecurityGroup':
                                logical_resource_id = resource['LogicalResourceId']
                                if logical_resource_id.startswith('SlurmCtlSG'):
                                    slurmCtlSG = resource['PhysicalResourceId']
                                if logical_resource_id.startswith('SlurmNodeSG'):
                                    slurmNodeSG = resource['PhysicalResourceId']
                    if not slurmCtlSG:
                        logger.error(f"SlurmCtlSG not found in {federated_stack_name} stack")
                        sys.exit(1)
                    if not slurmNodeSG:
                        logger.error(f"SlurmNodeSG not found in {federated_stack_name} stack")
                        sys.exit(1)
                    self.config['slurm']['Federation']['SlurmCtlSecurityGroups'][f"{federated_stack_name}-SlurmCtlSG"] = slurmCtlSG
                    self.config['slurm']['Federation']['SlurmNodeSecurityGroups'][f"{federated_stack_name}-SlurmNodeSG"] = slurmNodeSG

        if 'JobCompLoc' in self.config['slurm']:
            if self.config['slurm']['JobCompType'] == 'jobcomp/filetxt':
                logger.error("Can't specify slurm/JobCompType==jobcomp/filetxt and slurm/JobCompLoc.")
                sys.exit(1)
        else:
            self.config['slurm']['JobCompLoc'] = ''
            if self.config['slurm']['JobCompType'] == 'jobcomp/elasticsearch':
                if not self.config['slurm']['ElasticSearch']:
                    logger.error(f"Must specify existing ElasticSearch domain in slurm/JobCompLoc when slurm/JobCompType == jobcomp/elasticsearch and slurm/ElasticSearch is not set.")
                    sys.exit(1)

        # Validate updated config against schema
        from config_schema import check_schema
        from schema import SchemaError
        try:
            validated_config = check_schema(self.config, [self.config['Region']])
        except SchemaError:
            logger.exception(f"Invalid config")
            sys.exit(1)

    def create_assets(self):
        self.slurmctl_user_data_asset = s3_assets.Asset(self, "SlurmCtlUserData", path="resources/user_data/slurmctl_user_data.sh")
        self.slurmctl_config_asset = s3_assets.Asset(self, "SlurmCtlConfigScript", path="resources/user_data/slurmctl_config.sh")

        self.slurmdbd_user_data_asset = s3_assets.Asset(self, "SlurmDbdUserData", path="resources/user_data/slurmdbd_user_data.sh")
        self.slurmdbd_config_asset = s3_assets.Asset(self, "SlurmDbdConfigScript", path="resources/user_data/slurmdbd_config.sh")

        self.slurm_node_ami_user_data_asset = s3_assets.Asset(self, "SlurmNodeAmiUserData", path="resources/user_data/slurm_node_ami_user_data.sh")
        self.slurm_node_ami_config_asset = s3_assets.Asset(self, "SlurmNodeAmiConfigScript", path="resources/user_data/slurm_node_ami_config.sh")
        self.slurm_node_ami_wait_for_ami_asset = s3_assets.Asset(self, "SlurmNodeAmiWaitForAmiScript", path="resources/user_data/WaitForAmi.py")

        self.playbooks_asset = s3_assets.Asset(self, 'Playbooks',
            path = 'resources/playbooks',
            follow_symlinks = SymlinkFollowMode.ALWAYS
        )

        fh = NamedTemporaryFile()
        yaml.dump(self.config['slurm']['InstanceConfig'], fh, encoding='utf-8')
        self.instance_config_asset = s3_assets.Asset(self, "InstanceConfigAsset", path=fh.name)

    def create_lambdas(self):
        updateDnsLambdaAsset = s3_assets.Asset(self, "UpdateDnsLambdaAsset", path="resources/lambdas/UpdateDns")
        self.update_dns_lambda = aws_lambda.Function(
            self, "UpdateDnsLambda",
            function_name=f"{self.stack_name}-UpdateDns",
            description="Update DNS record",
            memory_size=128,
            runtime=aws_lambda.Runtime.PYTHON_3_7,
            timeout=Duration.minutes(3),
            log_retention=logs.RetentionDays.INFINITE,
            handler="UpdateDns.lambda_handler",
            code=aws_lambda.Code.from_bucket(updateDnsLambdaAsset.bucket, updateDnsLambdaAsset.s3_object_key)
        )

        getOntapSvmDNSNameLambdaAsset = s3_assets.Asset(self, "GetOntapSvmDNSNameLambdaAsset", path="resources/lambdas/GetOntapSvmDNSName")
        self.get_ontap_svm_dnsname_lambda = aws_lambda.Function(
            self, "GetOntapSvmDNSNameLambda",
            function_name=f"{self.stack_name}-GetOntapSvmDNSNameLambda",
            description="Get the DNSName attribute of an Ontap SVM",
            memory_size=128,
            runtime=aws_lambda.Runtime.PYTHON_3_8,
            timeout=Duration.minutes(15),
            log_retention=logs.RetentionDays.INFINITE,
            handler="GetOntapSvmDNSName.lambda_handler",
            code=aws_lambda.Code.from_bucket(getOntapSvmDNSNameLambdaAsset.bucket, getOntapSvmDNSNameLambdaAsset.s3_object_key)
        )

        self.get_ontap_svm_dnsname_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "fsx:DescribeStorageVirtualMachines",
                    ],
                resources=['*']
                )
            )

        deconfigureClusterLambdaAsset = s3_assets.Asset(self, "DeconfigureClusterLambdaAsset", path="resources/lambdas/DeconfigureCluster")
        self.deconfigure_cluster_lambda = aws_lambda.Function(
            self, "DeconfigureClusterLambda",
            function_name=f"{self.stack_name}-DeconfigureCluster",
            description="Unmount file system and remove user/group cron job",
            memory_size=128,
            runtime=aws_lambda.Runtime.PYTHON_3_8,
            timeout=Duration.minutes(15),
            log_retention=logs.RetentionDays.INFINITE,
            handler="DeconfigureCluster.lambda_handler",
            code=aws_lambda.Code.from_bucket(deconfigureClusterLambdaAsset.bucket, deconfigureClusterLambdaAsset.s3_object_key)
        )

        self.deconfigure_cluster_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "ssm:SendCommand",
                ],
                resources=[f'arn:{Aws.PARTITION}:ssm:{Aws.REGION}::document/AWS-RunShellScript']
                )
            )

    def create_vpc(self):
        self.vpc = ec2.Vpc.from_lookup(self, "Vpc", vpc_id = self.config['VpcId'])

        self.subnets = self.vpc.private_subnets
        valid_subnet_ids = []
        if 'SubnetId' in self.config:
            self.subnet = None
            for subnet in self.subnets:
                valid_subnet_ids.append(subnet.subnet_id)
                if subnet.subnet_id == self.config['SubnetId']:
                    self.subnet = subnet
                    break
            if not self.subnet:
                # If this is a new VPC then the cdk.context.json will not have the VPC and will be refreshed after the bootstrap phase. Until then the subnet ids will be placeholders so just pick the first subnet. After the bootstrap finishes the vpc lookup will be done and then the info will be correct.
                if valid_subnet_ids[0] == 'p-12345':
                    logger.warning(f"VPC {self.config['VpcId']} not in cdk.context.json and will be refresshed before synth.")
                    self.subnet = self.vpc.private_subnets[0]
                else:
                    logger.error(f"SubnetId {self.config['SubnetId']} not found in VPC {self.config['VpcId']}\nValid subnet ids:\n{pp.pformat(valid_subnet_ids)}")
                    sys.exit(1)
        else:
            self.subnet = self.vpc.private_subnets[0]
            self.config['SubnetId'] = self.subnet.subnet_id
        logger.info(f"Subnet set to {self.config['SubnetId']}")
        logger.info(f"availability zone: {self.subnet.availability_zone}")

        # Can't create query logging for private hosted zone.
        if 'HostedZoneId' in self.config:
            self.hosted_zone = route53.HostedZone.from_hosted_zone_id(self, "PrivateDns", hosted_zone_id=self.config['HostedZoneId'])
            self.config['Domain'] = self.hosted_zone.zone_name
        else:
            self.hosted_zone = route53.HostedZone(self, "PrivateDns",
                vpcs = [self.vpc],
                zone_name = self.config['Domain']
            )

        self.update_dns_lambda.add_to_role_policy(
            statement=iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "route53:ChangeResourceRecordSets"
                ],
                resources=[self.hosted_zone.hosted_zone_arn]
                )
            )

    def create_security_groups(self):
        self.nfs_sg = ec2.SecurityGroup(self, "NfsSG", vpc=self.vpc, allow_all_outbound=False, description="Nfs Security Group")
        Tags.of(self.nfs_sg).add("Name", f"{self.stack_name}-NfsSG")
        self.suppress_cfn_nag(self.nfs_sg, 'W29', 'Egress port range used to block all egress')

        self.zfs_sg = ec2.SecurityGroup(self, "ZfsSG", vpc=self.vpc, allow_all_outbound=False, description="Zfs Security Group")
        Tags.of(self.zfs_sg).add("Name", f"{self.stack_name}-ZfsSG")
        self.suppress_cfn_nag(self.zfs_sg, 'W29', 'Egress port range used to block all egress')

        self.lustre_sg = ec2.SecurityGroup(self, "LustreSG", vpc=self.vpc, allow_all_outbound=False, description="Lustre Security Group")
        Tags.of(self.lustre_sg).add("Name", f"{self.stack_name}-LustreSG")
        self.suppress_cfn_nag(self.lustre_sg, 'W29', 'Egress port range used to block all egress')

        self.database_sg = ec2.SecurityGroup(self, "DatabaseSG", vpc=self.vpc, allow_all_outbound=False, description="Database Security Group")
        Tags.of(self.database_sg).add("Name", f"{self.stack_name}-DatabaseSG")
        self.suppress_cfn_nag(self.database_sg, 'W29', 'Egress port range used to block all egress')

        self.slurmctl_sg = ec2.SecurityGroup(self, "SlurmCtlSG", vpc=self.vpc, allow_all_outbound=False, description="SlurmCtl Security Group")
        self.slurmctl_sg_name = f"{self.stack_name}-SlurmCtlSG"
        Tags.of(self.slurmctl_sg).add("Name", self.slurmctl_sg_name)
        self.suppress_cfn_nag(self.slurmctl_sg, 'W29', 'Egress port range used to block all egress')

        if 'ExistingSlurmDbd' in self.config['slurm']:
            for slurmdbd_sg_name, slurmdbd_sg_id in self.config['slurm']['ExistingSlurmDbd']['SecurityGroup'].items():
                self.slurmdbd_sg = ec2.SecurityGroup.from_security_group_id(
                    self, f"{slurmdbd_sg_name}",
                    security_group_id = slurmdbd_sg_id,
                    allow_all_outbound = False,
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
                federated_slurmctl_sg = ec2.SecurityGroup.from_security_group_id(
                    self, f"{federated_slurmctl_sg_name}",
                    security_group_id = federated_slurmctl_sg_id,
                    allow_all_outbound = False,
                )
                self.federated_slurmctl_sgs[federated_slurmctl_sg_name] = federated_slurmctl_sg
                federated_slurmctl_sg.connections.allow_to(self.slurmnode_sg, ec2.Port.tcp(6818), f"{federated_slurmctl_sg_name} to {self.slurmnode_sg_name}")

        self.federated_slurmnode_sgs = {}
        if 'Federation' in self.config['slurm']:
            for federated_slurmnode_sg_name, federated_slurmnode_sg_id in self.config['slurm']['Federation']['SlurmNodeSecurityGroups'].items():
                federated_slurmnode_sg = ec2.SecurityGroup.from_security_group_id(
                    self, f"{federated_slurmnode_sg_name}",
                    security_group_id = federated_slurmnode_sg_id,
                    allow_all_outbound = False,
                )
                self.federated_slurmnode_sgs[federated_slurmnode_sg_name] = federated_slurmnode_sg

        self.submitter_security_groups = {}
        self.slurm_submitter_sg = ec2.SecurityGroup(self, "SlurmSubmitterSG", vpc=self.vpc, allow_all_outbound=False, description="SlurmSubmitter Security Group")
        self.slurm_submitter_sg_name = f"{self.stack_name}-SlurmSubmitterSG"
        Tags.of(self.slurm_submitter_sg).add("Name", self.slurm_submitter_sg_name)
        self.suppress_cfn_nag(self.slurm_submitter_sg, 'W29', 'Egress port range used to block all egress')
        self.submitter_security_groups[self.slurm_submitter_sg_name] = self.slurm_submitter_sg
        if 'SubmitterSecurityGroupIds' in self.config['slurm']:
            for slurm_submitter_sg_name, slurm_submitter_sg_id in self.config['slurm']['SubmitterSecurityGroupIds'].items():
                self.submitter_security_groups[slurm_submitter_sg_name] = ec2.SecurityGroup.from_security_group_id(
                    self, f"{slurm_submitter_sg_name}",
                    security_group_id = slurm_submitter_sg_id,
                    allow_all_outbound = False,
                )

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

        # ZFS Connections
        for fs_client_sg_name, fs_client_sg in fs_client_sgs.items():
            fs_client_sg.connections.allow_to(self.zfs_sg, ec2.Port.tcp(2049), f"{fs_client_sg_name} to Zfs")
            fs_client_sg.connections.allow_to(self.zfs_sg, ec2.Port.tcp_range(32765, 32769), f"{fs_client_sg_name} to Zfs")
            self.suppress_cfn_nag(fs_client_sg, 'W27', 'Correct, restricted range for zfs: 32765-3276')
            self.suppress_cfn_nag(fs_client_sg, 'W29', 'Correct, restricted range for zfs: 32765-3276')
        self.suppress_cfn_nag(self.zfs_sg, 'W27', 'Correct, restricted range for zfs: 32765-3276')

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

        # slurmctl connections
        # egress
        self.slurmctl_sg.connections.allow_from(self.slurmctl_sg, ec2.Port.tcp(6817), f"{self.slurmctl_sg_name} to {self.slurmctl_sg_name}")
        self.slurmctl_sg.connections.allow_to(self.slurmctl_sg, ec2.Port.tcp(6817), f"{self.slurmctl_sg_name} to {self.slurmctl_sg_name}")
        self.slurmctl_sg.connections.allow_to(self.slurmnode_sg, ec2.Port.tcp(6818), f"{self.slurmctl_sg_name} to {self.slurmnode_sg_name}")
        if self.slurmdbd_sg:
            self.slurmctl_sg.connections.allow_to(self.slurmdbd_sg, ec2.Port.tcp(6819), f"{self.slurmctl_sg_name} to {self.slurmdbd_sg_name} - Write job information")
        if 'ExistingSlurmDbd' in self.config['slurm']:
            self.slurmdbd_sg.connections.allow_from(self.slurmctl_sg, ec2.Port.tcp(6819), f"{self.slurmctl_sg_name} to {self.slurmdbd_sg_name} - Write job information")
        for slurm_submitter_sg_name, slurm_submitter_sg in self.submitter_security_groups.items():
            self.slurmctl_sg.connections.allow_to(slurm_submitter_sg, ec2.Port.tcp_range(1024, 65535), f"{self.slurmctl_sg_name} to {slurm_submitter_sg_name} - srun")
            self.suppress_cfn_nag(slurm_submitter_sg, 'W27', 'Port range ok. slurmctl requires requires ephemeral ports to submitter for srun: 1024-65535')
        self.suppress_cfn_nag(self.slurmctl_sg, 'W27', 'Port range ok. slurmctl requires requires ephemeral ports to submitter for srun: 1024-65535')
        self.slurmctl_sg.add_egress_rule(ec2.Peer.ipv4("0.0.0.0/0"), ec2.Port.tcp(80), description="Internet")
        self.slurmctl_sg.add_egress_rule(ec2.Peer.ipv4("0.0.0.0/0"), ec2.Port.tcp(443), description="Internet")
        self.suppress_cfn_nag(self.slurmctl_sg, 'W5', 'Egress to internet required to install packages and slurm software')
        for federated_slurmctl_sg_name, federated_slurmctl_sg in self.federated_slurmctl_sgs.items():
            self.slurmctl_sg.connections.allow_from(federated_slurmctl_sg, ec2.Port.tcp(6817), f"{federated_slurmctl_sg_name} to {self.slurmctl_sg_name}")
            self.slurmctl_sg.connections.allow_to(federated_slurmctl_sg, ec2.Port.tcp(6817), f"{self.slurmctl_sg_name} to {federated_slurmctl_sg_name}")
        for federated_slurmnode_sg_name, federated_slurmnode_sg in self.federated_slurmnode_sgs.items():
            self.slurmctl_sg.connections.allow_to(federated_slurmnode_sg, ec2.Port.tcp(6818), f"{self.slurmctl_sg_name} to {federated_slurmnode_sg_name}")

        # slurmdbd connections
        # egress
        if self.slurmdbd_sg:
            self.slurmdbd_sg.connections.allow_to(self.slurmctl_sg, ec2.Port.tcp(6817), f"{self.slurmdbd_sg_name} to {self.slurmctl_sg_name}")
            # @todo Does slurmdbd really need ephemeral access to slurmctl?
            # self.slurmdbd_sg.connections.allow_to(self.slurmctl_sg, ec2.Port.tcp_range(1024, 65535), f"{self.slurmdbd_sg_name} to {self.slurmctl_sg_name} - Ephemeral")
            if 'ExistingSlurmDbd' not in self.config['slurm']:
                self.slurmdbd_sg.add_egress_rule(ec2.Peer.ipv4("0.0.0.0/0"), ec2.Port.tcp(80), description="Internet")
                self.slurmdbd_sg.add_egress_rule(ec2.Peer.ipv4("0.0.0.0/0"), ec2.Port.tcp(443), description="Internet")
                self.suppress_cfn_nag(self.slurmdbd_sg, 'W5', 'Egress to internet required to install packages and slurm software')

        # slurmnode connections
        # egress
        self.slurmnode_sg.connections.allow_to(self.slurmctl_sg, ec2.Port.tcp(6817), f"{self.slurmnode_sg_name} to {self.slurmctl_sg_name}")
        self.slurmnode_sg.connections.allow_to(self.slurmnode_sg, ec2.Port.tcp(6818), f"{self.slurmnode_sg_name} to {self.slurmnode_sg_name}")
        self.slurmnode_sg.connections.allow_to(self.slurmnode_sg, ec2.Port.tcp_range(1024, 65535), f"{self.slurmnode_sg_name} to {self.slurmnode_sg_name} - ephemeral")
        self.suppress_cfn_nag(self.slurmnode_sg, 'W27', 'Port range ok. slurmnode requires requires ephemeral ports to other slurmnodes: 1024-65535')
        for slurm_submitter_sg_name, slurm_submitter_sg in self.submitter_security_groups.items():
            self.slurmnode_sg.connections.allow_to(slurm_submitter_sg, ec2.Port.tcp_range(6000, 7024), f"{self.slurmnode_sg_name} to {slurm_submitter_sg_name} - x11")
            # @todo Not sure if this is really initiated from the slurm node
            self.slurmnode_sg.connections.allow_to(slurm_submitter_sg, ec2.Port.tcp_range(1024, 65535), f"{self.slurmnode_sg_name} to {slurm_submitter_sg_name} - ephemeral")
            self.suppress_cfn_nag(slurm_submitter_sg, 'W27', 'Port range ok. slurmnode requires requires ephemeral ports to slurm submitters: 1024-65535')
        self.suppress_cfn_nag(self.slurmnode_sg, 'W27', 'Port range ok. slurmnode requires requires ephemeral ports to slurm submitters: 1024-65535')
        self.slurmnode_sg.add_egress_rule(ec2.Peer.ipv4("0.0.0.0/0"), ec2.Port.tcp(80), description="Internet")
        self.slurmnode_sg.add_egress_rule(ec2.Peer.ipv4("0.0.0.0/0"), ec2.Port.tcp(443), description="Internet")
        self.suppress_cfn_nag(self.slurmnode_sg, 'W5', 'Egress to internet required to install packages and slurm software')
        for federated_slurmnode_sg_name, federated_slurmnode_sg in self.federated_slurmnode_sgs.items():
            federated_slurmnode_sg.connections.allow_to(self.slurmctl_sg, ec2.Port.tcp(6817), f"{federated_slurmnode_sg_name} to {self.slurmctl_sg_name}")
            self.slurmnode_sg.connections.allow_to(federated_slurmnode_sg, ec2.Port.tcp(6818), f"{self.slurmnode_sg_name} to {federated_slurmnode_sg_name}")
            self.slurmnode_sg.connections.allow_to(federated_slurmnode_sg, ec2.Port.tcp_range(1024, 65535), f"{self.slurmnode_sg_name} to {federated_slurmnode_sg_name} - ephemeral")

        # slurm submitter connections
        # egress
        for slurm_submitter_sg_name, slurm_submitter_sg in self.submitter_security_groups.items():
            slurm_submitter_sg.connections.allow_to(self.slurmctl_sg, ec2.Port.tcp(6817), f"{slurm_submitter_sg_name} to {self.slurmctl_sg_name}")
            slurm_submitter_sg.connections.allow_to(self.slurmnode_sg, ec2.Port.tcp(6818), f"{slurm_submitter_sg_name} to {self.slurmnode_sg_name} - srun")
            if self.slurmdbd_sg:
                slurm_submitter_sg.connections.allow_to(self.slurmdbd_sg, ec2.Port.tcp(6819), f"{slurm_submitter_sg_name} to {self.slurmdbd_sg_name} - sacct")

        # Try to suppress cfn_nag warnings on ingress/egress rules
        for slurm_submitter_sg_name, slurm_submitter_sg in self.submitter_security_groups.items():
            self.suppress_cfn_nag(self.slurmnode_sg, 'W27', 'Port range ok. slurmsubmitter requires ephemeral ports for several reasons: 1024-65535')

    def create_elasticsearch(self):
        if 'ElasticSearch' not in self.config['slurm']:
            return

        self.elasticsearch_sg = ec2.SecurityGroup(self, "ElasticSearchSG", vpc=self.vpc, allow_all_outbound=False, description="ElasticSearch Security Group")
        Tags.of(self.elasticsearch_sg).add("Name", f"{self.stack_name}-ElasticSearchSG")

        for sg in [[self.slurmdbd_sg, 'SlurmDbdSG'], [self.slurmctl_sg, 'SlurmCtlSG']]:
            self.elasticsearch_sg.connections.allow_from(sg[0], ec2.Port.tcp(80), f'{sg[1]} to ElasticSearchSG')
            self.elasticsearch_sg.connections.allow_from(sg[0], ec2.Port.tcp(443), f'{sg[1]} to ElasticSearchSG')

        es_subnets = []
        for subnet_index in range(self.config['slurm']['ElasticSearch']['number_of_azs']):
            es_subnets.append(ec2.SubnetSelection(subnets=[self.subnets[subnet_index]]))

        if self.config['slurm']['ElasticSearch']['number_of_azs'] > 1:
            zone_awareness = opensearch.ZoneAwarenessConfig(
                enabled = True,
                availability_zone_count = self.config['slurm']['ElasticSearch']['number_of_azs']
            )
        else:
            zone_awareness = None

        domain_name = f'{self.stack_name}'
        self.elasticsearch = opensearch.Domain(
            self, "ElasticSearchDomain",
            domain_name = domain_name,
            version = opensearch.EngineVersion.ELASTICSEARCH_7_10,
            advanced_options={"rest.action.multi.allow_explicit_index": "true"},
            automated_snapshot_start_hour=0,
            capacity = opensearch.CapacityConfig(
                master_nodes = self.config['slurm']['ElasticSearch']['master_nodes'],
                master_node_instance_type = self.config['slurm']['ElasticSearch']['master_node_instance_type'],
                data_nodes = self.config['slurm']['ElasticSearch']['data_nodes'],
                data_node_instance_type = self.config['slurm']['ElasticSearch']['data_node_instance_type'],
                warm_nodes = self.config['slurm']['ElasticSearch']['warm_nodes'],
                warm_instance_type = self.config['slurm']['ElasticSearch']['warm_instance_type'],
                ),
            ebs = opensearch.EbsOptions(
                volume_size = self.config['slurm']['ElasticSearch']['ebs_volume_size'],
                volume_type = ec2.EbsDeviceVolumeType(self.config['slurm']['ElasticSearch']['ebs_volume_type'])
                ),
            enable_version_upgrade = self.config['slurm']['ElasticSearch']['enable_version_upgrade'],
            encryption_at_rest = opensearch.EncryptionAtRestOptions(enabled = True),
            enforce_https = False,
            # fine_grained_access_control = opensearch.AdvancedSecurityOptions(),
            logging = opensearch.LoggingOptions(
                app_log_enabled = True,
                # audit_log_enabled = True, # Requires fine_grained_access_control
                slow_index_log_enabled = True,
                slow_search_log_enabled = True,
            ),
            node_to_node_encryption = False,
            removal_policy = RemovalPolicy.RETAIN, # RemovalPolicy.DESTROY
            security_groups = [self.elasticsearch_sg],
            vpc = self.vpc,
            vpc_subnets = es_subnets,
            zone_awareness = zone_awareness,
            access_policies = [
                iam.PolicyStatement(
                    principals = [iam.AnyPrincipal()],
                    actions = [
                        "es:ESHttp*",
                        'es:*'
                        ],
                    resources=[
                        f"arn:{Aws.PARTITION}:es:{Aws.REGION}:{Aws.ACCOUNT_ID}:domain/{domain_name}/*"
                    ]
                )
            ],
        )


        domain_endpoint = self.elasticsearch.domain_endpoint
        self.config['slurm']['JobCompLoc'] = f"http://{domain_endpoint}/slurm/_doc"

    def create_file_system(self):
        if 'kms_key_arn' in self.config['slurm']['storage']:
            kms_key = kms.Key.from_key_arn(self.config['slurm']['storage']['kms_key_arn'])
        else:
            kms_key = None

        removal_policies = {
            'DESTROY': RemovalPolicy.DESTROY,
            'RETAIN': RemovalPolicy.RETAIN,
            'SNAPSHOT': RemovalPolicy.SNAPSHOT,
            }

        if self.config['slurm']['storage']['provider'] == "efs":
            lifecycle_policies = {
                'None': None,
                'AFTER_14_DAYS': efs.LifecyclePolicy.AFTER_14_DAYS,
                'AFTER_30_DAYS': efs.LifecyclePolicy.AFTER_30_DAYS,
                'AFTER_60_DAYS': efs.LifecyclePolicy.AFTER_60_DAYS,
                'AFTER_7_DAYS':  efs.LifecyclePolicy.AFTER_7_DAYS,
                'AFTER_90_DAYS': efs.LifecyclePolicy.AFTER_90_DAYS,
                }
            performance_modes = {
                'GENERAL_PURPOSE': efs.PerformanceMode.GENERAL_PURPOSE,
                'MAX_IO': efs.PerformanceMode.MAX_IO
                }
            throughput_modes = {
                'BURSTING': efs.ThroughputMode.BURSTING,
                'PROVISIONED': efs.ThroughputMode.PROVISIONED,
                }
            throughput_mode = throughput_modes[self.config['slurm']['storage']['efs']['throughput_mode']]
            if throughput_mode == efs.ThroughputMode.PROVISIONED:
                if 'provisioned_throughput_per_second' not in self.config['slurm']['storage']['efs']:
                    logger.error(f"Must configure slurm/storage/efs/provisioned_throughput_per_second if slurm/storage/efs/throughput_mode == PROVISIONED")
                    sys.exit(1)
                provisioned_throughput_per_second = Size.mebibytes(self.config['slurm']['storage']['efs']['provisioned_throughput_per_second'])
            else:
                provisioned_throughput_per_second = None

            self.file_system = efs.FileSystem(self, "EFS",
                vpc = self.vpc,
                encrypted = self.config['slurm']['storage']['efs']['encrypted'],
                kms_key = kms_key,
                performance_mode = performance_modes[self.config['slurm']['storage']['efs']['performance_mode']],
                throughput_mode = throughput_mode,
                provisioned_throughput_per_second = provisioned_throughput_per_second,
                lifecycle_policy = lifecycle_policies[self.config['slurm']['storage']['efs']['lifecycle_policy']],
                # @BUG Cloudformation fails with: Resource handler returned message: "One or more LifecyclePolicy objects specified are malformed
                #out_of_infrequent_access_policy = efs.OutOfInfrequentAccessPolicy.AFTER_1_ACCESS,
                removal_policy = removal_policies[self.config['slurm']['storage']['removal_policy']],
                vpc_subnets  = ec2.SubnetSelection(subnets=self.subnets),
                security_group  = self.nfs_sg
                )

            self.file_system_dependency = self.file_system

            self.file_system_dns = f"{self.file_system.file_system_id}.efs.{self.region}.amazonaws.com"
            self.file_system_dns = self.file_system_dns

            self.file_system_port = 2049

            self.file_system_mount_name = ""

            self.file_system_mount_src = f"{self.file_system_dns}:/"
            self.file_system_mount_source = self.file_system_mount_src

            if self.config['slurm']['storage']['efs']['use_efs_helper']:
                self.file_system_type = 'efs'
                self.file_system_options = 'tls'
            else:
                self.file_system_type = 'nfs4'
                self.file_system_options = 'nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2,noresvport'

            self.file_system_mount_command = f"sudo mkdir -p {self.config['slurm']['storage']['mount_path']} && sudo yum -y install nfs-utils && sudo mount -t {self.file_system_type} -o {self.file_system_options} {self.file_system_mount_src} {self.config['slurm']['storage']['mount_path']}"

        elif self.config['slurm']['storage']['provider'] == "lustre":
            deployment_types = {
                'PERSISTENT_1': fsx.LustreDeploymentType.PERSISTENT_1,
                'SCRATCH_1': fsx.LustreDeploymentType.SCRATCH_1,
                'SCRATCH_2': fsx.LustreDeploymentType.SCRATCH_2,
            }
            deployment_type = deployment_types[self.config['slurm']['storage']['lustre']['deployment_type']]

            if deployment_type == fsx.LustreDeploymentType.PERSISTENT_1:
                per_unit_storage_throughput = self.config['slurm']['storage']['lustre']['per_unit_storage_throughput']
                if per_unit_storage_throughput not in [50, 100, 200]:
                    raise ValueError(f"Invalid per_unit_storage_throughput: {per_unit_storage_throughput}")
            else:
                per_unit_storage_throughput = None

            lustre_configuration = fsx.LustreConfiguration(
                deployment_type = deployment_type,
                per_unit_storage_throughput = per_unit_storage_throughput,
                )

            self.file_system = fsx.LustreFileSystem(
                self, "FSxLustre",
                lustre_configuration = lustre_configuration,
                vpc = self.vpc,
                vpc_subnet = self.vpc.select_subnets(subnet_type=ec2.SubnetType.PRIVATE).subnets[0],
                kms_key = kms_key,
                removal_policy = removal_policies[self.config['slurm']['storage']['removal_policy']],
                security_group = self.lustre_sg,
                storage_capacity_gib = self.config['slurm']['storage']['lustre']['storage_capacity'],
                )

            self.file_system_dependency = self.file_system

            self.file_system_port = 988

            self.file_system_type = 'lustre'
            self.file_system_dns = self.file_system.dns_name
            self.file_system_mount_name = self.file_system.mount_name

            self.file_system_mount_source = f"{self.file_system_dns}@tcp:/{self.file_system_mount_name}"

            self.file_system_options = 'noatime,flock'

            self.file_system_mount_command = f"sudo mkdir -p {self.config['slurm']['storage']['mount_path']} && sudo mount -t lustre -o {self.file_system_options} {self.file_system_mount_source} {self.config['slurm']['storage']['mount_path']}"

        elif self.config['slurm']['storage']['provider'] == "ontap":
            if 'iops' in self.config['slurm']['storage']['ontap']:
                disk_iops_configuration = fsx.CfnFileSystem.DiskIopsConfigurationProperty(
                    iops = self.config['slurm']['storage']['ontap']['iops'],
                    mode = 'USER_PROVISIONED'
                )
            else:
                disk_iops_configuration = fsx.CfnFileSystem.DiskIopsConfigurationProperty(
                    mode = 'AUTOMATIC'
                )

            ontap_configuration_kwargs = {
                'deployment_type': self.config['slurm']['storage']['ontap']['deployment_type'],
                'preferred_subnet_id': self.subnet.subnet_id,
                'throughput_capacity': self.config['slurm']['storage']['ontap']['throughput_capacity']
            }
            ontap_configuration = fsx.CfnFileSystem.OntapConfigurationProperty(**ontap_configuration_kwargs)

            subnet_ids = [self.subnet.subnet_id]
            if self.config['slurm']['storage']['ontap']['deployment_type'] == 'MULTI_AZ_1':
                for subnet in self.vpc.private_subnets:
                    if subnet.subnet_id != self.subnet.subnet_id:
                        subnet_ids.append(subnet.subnet_id)
                        break

            self.file_system = fsx.CfnFileSystem(
                self, "Ontap",
                file_system_type = 'ONTAP',
                subnet_ids = subnet_ids,
                ontap_configuration = ontap_configuration,
                security_group_ids = [self.nfs_sg.security_group_id],
                storage_capacity = self.config['slurm']['storage']['ontap']['storage_capacity'],
                )

            self.svm = fsx.CfnStorageVirtualMachine(
                self, "OntapSVM",
                file_system_id = self.file_system.ref,
                name = 'slurm',
                root_volume_security_style = 'UNIX'
            )

            svm_id = self.svm.ref

            # Get DNSName of SVM
            self.file_system_dns = CustomResource(
                self, f"OntapSvmDNSName",
                service_token = self.get_ontap_svm_dnsname_lambda.function_arn,
                properties={
                    "SvmId": svm_id
                }
            ).get_att_string('DNSName')

            # Add a volume
            self.volume = fsx.CfnVolume(
                self, 'OntapVolume',
                name = 'slurm',
                ontap_configuration = fsx.CfnVolume.OntapConfigurationProperty(
                    junction_path = '/slurm',
                    size_in_megabytes = str(self.config['slurm']['storage']['ontap']['storage_capacity'] * 1024),
                    storage_efficiency_enabled = 'true',
                    storage_virtual_machine_id = svm_id,
                    security_style = 'UNIX',
                    tiering_policy = fsx.CfnVolume.TieringPolicyProperty(
                        cooling_period = self.config['slurm']['storage']['ontap']['cooling_period'],
                        name = self.config['slurm']['storage']['ontap']['tiering_policy']
                    )
                ),
                volume_type = 'ONTAP'
            )

            self.file_system_dependency = self.volume

            self.file_system_port = 2049

            self.file_system_type = 'nfs'

            self.file_system_mount_name = ""

            self.file_system_mount_source = f"{self.file_system_dns}:/slurm"

            self.file_system_options = 'nfsvers=4.1'

            self.file_system_mount_command = f"sudo mkdir -p {self.config['slurm']['storage']['mount_path']} && sudo mount -t nfs -o {self.file_system_options} {self.file_system_mount_source} {self.config['slurm']['storage']['mount_path']}"

        else:
            raise ValueError(f"Invalid value of slurm.storage.provider: {self.config['slurm']['storage']['provider']}")

        Tags.of(self.file_system).add("Name", f"{self.stack_name}-Slurm")

        CfnOutput(self, "FileSystemProvider",
            value = self.config['slurm']['storage']['provider']
        )
        CfnOutput(self, "FileSystemType",
            value = self.file_system_type
        )
        CfnOutput(self, "FileSystemMountName",
            value = self.file_system_mount_name
        )
        CfnOutput(self, "FileSystemDnsName",
            value = self.file_system_dns
        )
        CfnOutput(self, "MountCommand",
            value = self.file_system_mount_command
        )

        CfnOutput(self, "ConfigureSubmitterCommand",
            value = f"sudo yum -y install epel-release && sudo yum -y install ansible && pushd {self.config['slurm']['storage']['mount_path']}/ansible/playbooks && ansible-playbook -i inventories/local.yml -e @../ansible_extra_vars.yml SlurmSubmitter.yml && popd"
        )

        CfnOutput(self, "ConfigureSyncSlurmUsersGroups",
            value = f"sudo yum -y install epel-release && sudo yum -y install ansible && pushd {self.config['slurm']['storage']['mount_path']}/ansible/playbooks && ansible-playbook -i inventories/local.yml -e @../ansible_extra_vars.yml create_users_groups_json.yml && popd"
        )

        CfnOutput(self, "DeconfigureClusterCommand",
            value = f"sudo mkdir -p /tmp/{self.config['slurm']['ClusterName']} && pushd /tmp/{self.config['slurm']['ClusterName']} && sudo rsync -av {self.config['slurm']['storage']['mount_path']}/ansible . && cd ansible/playbooks && sudo ansible-playbook -i inventories/local.yml -e @../ansible_extra_vars.yml SlurmSubmitterDeconfigure.yml && cd /tmp && rm -rf {self.config['slurm']['ClusterName']} && popd"
        )

        if 'SubmitterInstanceTags' in self.config['slurm']:
            # Create a custom resource to unmount the file system before deleting the cluster
            self.deconfigure_cluster_resource = CustomResource(
                self, "DeconfigureCluster",
                service_token = self.deconfigure_cluster_lambda.function_arn,
                properties={
                    "ClusterName": self.config['slurm']['ClusterName'],
                    "MountPath": self.config['slurm']['storage']['mount_path'],
                    "SubmitterInstanceTags": self.config['slurm']['SubmitterInstanceTags'],
                }
            )

            self.deconfigure_cluster_resource.node.add_dependency(self.file_system)

    def create_db(self):
        if 'SlurmDbd' not in self.config['slurm']:
            return

        # See https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless.how-it-works.html#aurora-serverless.architecture
        self.db_cluster = rds.ServerlessCluster(
            self, "SlurmDBCluster",
            engine = rds.DatabaseClusterEngine.AURORA_MYSQL,
            vpc = self.vpc,
            backup_retention = Duration.days(35),
            credentials = rds.Credentials.from_generated_secret(username="slurm"),
            default_database_name = "slurm_acct_db",
            deletion_protection = False,
            scaling = rds.ServerlessScalingOptions(auto_pause=Duration.days(1)),
            security_groups = [self.database_sg],
            parameter_group = rds.ParameterGroup(
                self, "SlurmDBClusterParameterGroup",
                engine = rds.DatabaseClusterEngine.AURORA_MYSQL,
                parameters = {'time_zone': self.config['TimeZone']}
                )
            )

        self.database_sg.connections.allow_from(self.slurmdbd_sg, ec2.Port.tcp(self.config['slurm']['SlurmDbd']['database']['port']), description=f"{{self.slurmdbd_sg_name}} - Database")

        self.database_read_endpoint = self.db_cluster.cluster_read_endpoint.hostname

        self.database_secret = self.db_cluster.secret

    def create_cw(self):
        if self.config['ErrorSnsTopicArn']:
            self.error_sns_topic = sns.Topic.from_topic_arn(self, 'ErrorSnsTopic', self.config['ErrorSnsTopicArn'])
        else:
            self.error_sns_topic = None

        self.slurm_namespace = 'SLURM'
        # The ClusterName will be added as a dimension of all alarms
        self.slurm_alarms = {
            'InsufficientCapacity': {'description': 'Slurm failed to start node because there was insufficient capacity.'},
            'TerminateBeforeResumeError': {'description': 'Slurm plugin had an error when terminating a node before creating a new one'},
            'StartError': {'description': 'Slurm plugin had an error when starting an existing node'},
            'CreateError': {'description': 'Slurm plugin had an error when creating a new instance'},
            'PublishCwFailed': {'description': 'slurm_ec2_publish_cw.py failed. Could be publish_cw or terminate_old_instances cron jobs.'},
            'ResumeTimeout': {'description': 'Slurm timed out waiting for a node to resume'},
            'SlurmctldDown': {'description': 'The slurmctld service is down.'},
            'SpotRebalanceRecommendation': {'description': 'Spot rebalance recommendation received by instance.'},
            'SpotTermination': {'description': 'Spot termination received by instance.'},
            'StopTerminateError': {'description': 'Slurm plugin had an error when terminating an instance while stopping a node'},
            'StopStopError': {'description': 'Slurm plugin had an error when stopping an instance while stopping a node'},
            'TerminateError': {'description': 'Slurm plugin had an error when stopping an instance while stopping a node'},
            'TerminateOldInstancesFailed': {'description': 'terminate_old_instances.py failed'},
            'UnhandledPluginCreateNodeConfException': {'description': 'Slurm plugin had an unhandled exception in create_node_conf'},
            'UnhandledPluginMarkNodeDownException': {'description': 'Slurm plugin had an unhandled exception in mark_node_down'},
            'UnhandledPluginConstructorException': {'description': 'Slurm plugin had an unhandled exception in constructor'},
            'UnhandledPluginPublishCwMetricsException': {'description': 'Slurm plugin had an unhandled exception in publish_cw'},
            'UnhandledPluginResumeException': {'description': 'Slurm plugin had an unhandled exception in the resume constructor'},
            'UnhandledPluginResumeFailException': {'description': 'Slurm plugin had an unhandled exception in the resume_fail constructor'},
            'UnhandledPluginStopException': {'description': 'Slurm plugin had an unhandled exception in the stop constructor'},
            'UnhandledPluginSuspendResumeException': {'description': 'Slurm plugin had an unhandled exception in suspend_resume_setup'},
            'UnhandledPluginTerminateException': {'description': 'Slurm plugin had an unhandled exception in the terminate constructor'},
            'UnhandledPluginTerminateOldInstancesException': {'description': 'Slurm plugin had an unhandled exception in terminate_old_instances_main constructor'},
            'DownNodes': {
                'metric_name': 'NodeState',
                'description': 'Slurm nodes in down state',
                'dimensions_map': {'State': 'down~'},
                'threshold': 200
                },
            'MaxJobCount': {
                'metric_name': 'JobCount',
                'description': 'Alarm when over 100000 jobs in Slurm, across all partitions',
                'dimensions_map': {'State': 'all'},
                'statistic': 'Maximum',
                'threshold': 100000
                },
        }
        for slurm_alarm_name, slurm_alarm_details in self.slurm_alarms.items():
            dimensions_map = slurm_alarm_details.get('dimensions_map', {})
            dimensions_map['Cluster'] = self.config['slurm']['ClusterName']
            slurm_alarm_details['metric'] = cloudwatch.Metric(
                namespace = self.slurm_namespace,
                metric_name = slurm_alarm_details.get('metric_name', slurm_alarm_name),
                dimensions_map = dimensions_map,
                label = slurm_alarm_name,
                period = Duration.minutes(self.config['slurm']['SlurmCtl']['CloudWatchPeriod']),
                statistic = slurm_alarm_details.get('statistic', 'Sum'),
                unit = slurm_alarm_details.get('unit', cloudwatch.Unit.COUNT)
            )
            alarm = slurm_alarm_details['metric'].create_alarm(
                self, f"Slurm{slurm_alarm_name}Alarm",
                alarm_description = slurm_alarm_details['description'],
                threshold = slurm_alarm_details.get('threshold', 0),
                comparison_operator = slurm_alarm_details.get('comparison_operator', cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD),
                treat_missing_data = cloudwatch.TreatMissingData.NOT_BREACHING,
                evaluation_periods = 1
            )
            if self.error_sns_topic:
                alarm.add_alarm_action(cloudwatch_actions.SnsAction(self.error_sns_topic))

        # Dashboard Widgets
        self.job_count_widget = cloudwatch.GraphWidget(
            title = "Job Count",
            period = Duration.minutes(self.config['slurm']['SlurmCtl']['CloudWatchPeriod']),
            stacked = True,
            statistic = 'Maximum',
            )
        for job_state in ['CONFIGURING', 'PENDING', 'SUSPENDED', 'RUNNING']:
            self.job_count_widget.add_left_metric(
                cloudwatch.Metric(
                    namespace = self.slurm_namespace,
                    metric_name = 'JobCount',
                    dimensions_map = {'State': job_state},
                    label = job_state,
                ),
            )

        self.vcs_licenses_widget = cloudwatch.GraphWidget(
            title = "VCS Licenses",
            period = Duration.minutes(self.config['slurm']['SlurmCtl']['CloudWatchPeriod']),
            stacked = False,
            statistic = 'Maximum',
        )
        for metric_name in ['LicensesTotal', 'LicensesUsed']:
            for license_name in ['VCSCompiler_Net', 'VCSMXRunTime_Net']:
                self.vcs_licenses_widget.add_left_metric(
                    cloudwatch.Metric(
                        namespace = self.slurm_namespace,
                        metric_name = metric_name,
                        dimensions_map = {'LicenseName': license_name},
                        label = license_name,
                    ),
                )

        self.running_instances_widget = cloudwatch.GraphWidget(
            title = "Running Instances",
            period = Duration.minutes(self.config['slurm']['SlurmCtl']['CloudWatchPeriod']),
            stacked = False,
            statistic = 'Maximum',
            )
        self.running_instances_widget.add_left_metric(
            cloudwatch.Metric(
                namespace = self.slurm_namespace,
                metric_name = 'NodeCount',
                dimensions_map = {
                    'State': 'running',
                    'InstanceType': 'all'
                    },
                label = 'NodeCount',
            ),
            )

        self.active_nodes_widget = cloudwatch.GraphWidget(
            title = "Active Nodes",
            period = Duration.minutes(self.config['slurm']['SlurmCtl']['CloudWatchPeriod']),
            stacked = False,
            statistic = 'Maximum',
            )
        for node_state in ['allocated', 'allocated#', 'completing', 'completing*', 'mixed', 'mixed#']:
            self.active_nodes_widget.add_left_metric(
                cloudwatch.Metric(
                    namespace = self.slurm_namespace,
                    metric_name = 'NodeState',
                    dimensions_map = {'State': node_state},
                    label = node_state,
                    ),
                )

        self.idle_nodes_widget = cloudwatch.GraphWidget(
            title = "Idle Nodes",
            period = Duration.minutes(self.config['slurm']['SlurmCtl']['CloudWatchPeriod']),
            stacked = True,
            statistic = 'Maximum',
            )
        for node_state in ['idle', 'idle#', 'idle%']:
            self.idle_nodes_widget.add_left_metric(
                cloudwatch.Metric(
                    namespace = self.slurm_namespace,
                    metric_name = 'NodeState',
                    dimensions_map = {'State': node_state},
                    label = node_state,
                    ),
                )

        self.stopped_nodes_widget = cloudwatch.GraphWidget(
            title = "Stopped Nodes",
            period = Duration.minutes(self.config['slurm']['SlurmCtl']['CloudWatchPeriod']),
            stacked = True,
            statistic = 'Maximum',
            )
        for node_state in ['stopped']:
            self.stopped_nodes_widget.add_left_metric(
                cloudwatch.Metric(
                    namespace = self.slurm_namespace,
                    metric_name = 'NodeCount',
                    dimensions_map = {
                        'State': node_state,
                        'InstanceType': 'all'},
                    label = node_state,
                ),
            )

        self.down_nodes_widget = cloudwatch.GraphWidget(
            title = "Down/Drained Nodes",
            period = Duration.minutes(self.config['slurm']['SlurmCtl']['CloudWatchPeriod']),
            stacked = True,
            statistic = 'Maximum',
            )
        for node_state in ['down', 'down~', 'drained', 'drained~']:
            self.down_nodes_widget.add_left_metric(
                cloudwatch.Metric(
                    namespace = self.slurm_namespace,
                    metric_name = 'NodeState',
                    dimensions_map = {'State': node_state},
                    label = node_state,
                    ),
                )

        self.insufficient_capacity_exceptions_widget = cloudwatch.GraphWidget(
            title = "Insufficient Capacity Exceptions",
            period = Duration.minutes(self.config['slurm']['SlurmCtl']['CloudWatchPeriod']),
            stacked = True,
            statistic = 'Sum',
            )
        for metric_name in ['CreateError', 'StartError']:
            self.insufficient_capacity_exceptions_widget.add_left_metric(
                cloudwatch.Metric(
                    namespace = self.slurm_namespace,
                    metric_name = 'metric_name',
                    dimensions_map = {'Reason': 'InsufficientInstanceCapacity'},
                ),
            )
        for instance_type in self.config['slurm']['InstanceTypes']:
            self.insufficient_capacity_exceptions_widget.add_left_metric(
                cloudwatch.Metric(
                    namespace = self.slurm_namespace,
                    metric_name = 'InsufficientCapacity',
                    dimensions_map = {'InstanceType': instance_type},
                    label = instance_type,
                ),
            )

        self.running_instances_by_type_stacked_widget = cloudwatch.GraphWidget(
            title = "Running Instances by Type",
            period = Duration.minutes(self.config['slurm']['SlurmCtl']['CloudWatchPeriod']),
            stacked = True,
            statistic = 'Maximum',
        )
        for instance_type in self.config['slurm']['InstanceTypes']:
            self.running_instances_by_type_stacked_widget.add_left_metric(
                cloudwatch.Metric(
                    namespace = self.slurm_namespace,
                    metric_name = 'NodeCount',
                    dimensions_map = {
                        'State': 'running',
                        'InstanceType': instance_type},
                    label = instance_type,
                ),
            )

        self.running_instances_by_type_unstacked_widget = cloudwatch.GraphWidget(
            title = "Running Instances by Type",
            period = Duration.minutes(self.config['slurm']['SlurmCtl']['CloudWatchPeriod']),
            stacked = False,
            statistic = 'Maximum',
        )
        for instance_type in self.config['slurm']['InstanceTypes']:
            self.running_instances_by_type_unstacked_widget.add_left_metric(
                cloudwatch.Metric(
                    namespace = self.slurm_namespace,
                    metric_name = 'NodeCount',
                    dimensions_map = {
                        'State': 'running',
                        'InstanceType': instance_type},
                    label = instance_type,
                ),
            )

        self.job_count_by_instance_type_widget = cloudwatch.GraphWidget(
            title = "JobCount by InstanceType",
            period = Duration.minutes(self.config['slurm']['SlurmCtl']['CloudWatchPeriod']),
            stacked = False,
            statistic = 'Maximum',
        )
        for instance_type in self.config['slurm']['InstanceTypes']:
            self.job_count_by_instance_type_widget.add_left_metric(
                cloudwatch.Metric(
                    namespace = self.slurm_namespace,
                    metric_name = 'JobCount',
                    dimensions_map = {'InstanceType': instance_type},
                    label = instance_type,
                ),
            )

        self.running_jobs_by_instance_type_widget = cloudwatch.GraphWidget(
            title = "Running Jobs by Instance Type",
            period = Duration.minutes(self.config['slurm']['SlurmCtl']['CloudWatchPeriod']),
            stacked = False,
            statistic = 'Maximum',
        )
        for instance_type in self.config['slurm']['InstanceTypes']:
            self.running_jobs_by_instance_type_widget.add_left_metric(
                cloudwatch.Metric(
                    namespace = self.slurm_namespace,
                    metric_name = 'RunningJobs',
                    dimensions_map = {'InstanceType': instance_type},
                    label = instance_type,
                ),
            )

        self.static_node_count_by_instance_type_widget = cloudwatch.GraphWidget(
            title = "Static Node Count By Instance Type",
            period = Duration.minutes(self.config['slurm']['SlurmCtl']['CloudWatchPeriod']),
            stacked = False,
            statistic = 'Maximum',
        )
        for instance_type in self.config['slurm']['InstanceTypes']:
            self.static_node_count_by_instance_type_widget.add_left_metric(
                cloudwatch.Metric(
                    namespace = self.slurm_namespace,
                    metric_name = 'StaticNodeCount',
                    dimensions_map = {'InstanceType': instance_type},
                    label = instance_type,
                ),
            )

        self.memory_used_percent_by_instance_type_widget = cloudwatch.GraphWidget(
            title = "Memory Utilization by Instance Type",
            period = Duration.minutes(self.config['slurm']['SlurmCtl']['CloudWatchPeriod']),
            stacked = False,
            statistic = 'Average',
        )
        for instance_type in self.config['slurm']['InstanceTypes']:
            self.memory_used_percent_by_instance_type_widget.add_left_metric(
                cloudwatch.Metric(
                    namespace = self.slurm_namespace,
                    metric_name = 'MemoryUsedPercent',
                    dimensions_map = {'InstanceType': instance_type},
                ),
            )

        self.memory_stats_by_instance_type_widget = cloudwatch.GraphWidget(
            title = "Memory Stats by Instance Type",
            period = Duration.minutes(self.config['slurm']['SlurmCtl']['CloudWatchPeriod']),
            stacked = False,
            statistic = 'Average',
        )
        for instance_type in self.config['slurm']['InstanceTypes']:
            self.memory_stats_by_instance_type_widget.add_left_metric(
                cloudwatch.Metric(
                    namespace = self.slurm_namespace,
                    metric_name = 'MemoryRequested',
                    dimensions_map = {'InstanceType': instance_type},
                ),
            )
        for instance_type in self.config['slurm']['InstanceTypes']:
            self.memory_stats_by_instance_type_widget.add_right_metric(
                cloudwatch.Metric(
                    namespace = self.slurm_namespace,
                    metric_name = 'MemoryUsed',
                    dimensions_map = {'InstanceType': instance_type},
                ),
            )

        # self.down_percent_by_node_type = cloudwatch.GraphWidget(
        #     title = "DownPercent by NodeType",
        #     period = Duration.minutes(self.config['slurm']['SlurmCtl']['CloudWatchPeriod']),
        #     stacked = False,
        #     statistic = 'Average',
        # )
        # self.down_percent_by_node_type.add_left_metric(
        #     cloudwatch.MathExpression(
        #         expression = "SEARCH(' {SLURM,NodeType,Partition} Partition=\"all\" MetricName=\"DownPercent\" ', 'Average', 300)",
        #         using_metrics = cloudwatch.Metric(
        #             namespace = self.slurm_namespace,
        #             metric_name = 'DownPercent',
        #             dimensions_map = {'Partition': 'all'},
        #             ),
        #         label = 'DownPercent'
        #     )
        # )

        self.slurm_dashboard = cloudwatch.Dashboard(
            self, 'SlurmDashboard',
            dashboard_name = f"{self.stack_name}-{self.config['slurm']['ClusterName']}",
            widgets = [
                [
                    self.job_count_widget,
                    self.vcs_licenses_widget,
                    self.running_instances_widget,
                    self.active_nodes_widget
                ],
                [
                    self.idle_nodes_widget,
                    self.stopped_nodes_widget,
                    self.down_nodes_widget,
                    self.insufficient_capacity_exceptions_widget,
                ],
                [
                    self.running_instances_by_type_stacked_widget,
                    self.running_instances_by_type_unstacked_widget,
                    self.job_count_by_instance_type_widget,
                    self.running_jobs_by_instance_type_widget,
                ],
                [
                    self.static_node_count_by_instance_type_widget,
                    self.memory_used_percent_by_instance_type_widget,
                    self.memory_stats_by_instance_type_widget,
                    # self.down_percent_by_node_type
                ]
            ]
        )

    def get_instance_template_vars(self, instance_role):

        # instance_template_vars is used to create create environment variables,
        # extra ansible variables, and to use jinja2 to template user data scripts.
        # The keys are the environment and ansible variable names.
        instance_template_vars = {
            "AWS_ACCOUNT_ID": Aws.ACCOUNT_ID,
            "AWS_PARTITION": Aws.PARTITION,
            "AWS_DEFAULT_REGION": Aws.REGION,
            "ClusterName": self.config['slurm']['ClusterName'],
            "Domain": self.config['Domain'],
            "EC2_KEYPAIR": self.config['SshKeyPair'],
            "ERROR_SNS_TOPIC_ARN": self.config['ErrorSnsTopicArn'],
            "ExtraMounts": self.config['slurm']['storage']['ExtraMounts'],
            "FileSystemDns": self.file_system_dns,
            "FileSystemMountPath": self.config['slurm']['storage']['mount_path'],
            "FileSystemMountSrc": self.file_system_mount_source,
            "FileSystemOptions": self.file_system_options,
            "FileSystemPort": self.file_system_port,
            "FileSystemType": self.file_system_type,
            "MountCommand": self.file_system_mount_command,
            "PLAYBOOKS_S3_URL": self.playbooks_asset.s3_object_url,
            "Region": Aws.REGION,
            "SlurmUid": self.config['slurm']['SlurmUid'],
            "SlurmVersion": self.config['slurm']['SlurmVersion'],
            "STACK_NAME": self.stack_name,
            "TimeZone": self.config['TimeZone'],
            "VPC_ID": self.config['VpcId'],
        }
        if instance_role == 'SlurmDbd':
            instance_template_vars['SlurmDBWriteEndpoint'] = self.db_cluster.cluster_endpoint.hostname
            instance_template_vars['SlurmDBSecretName'] = self.database_secret.secret_name
        elif instance_role == 'SlurmCtl':
            if self.useSlurmDbd:
                instance_template_vars["AccountingStorageHost"] = self.slurmDbdFQDN
            else:
                instance_template_vars["AccountingStorageHost"] = ''
            instance_template_vars["CloudWatchPeriod"] = self.config['slurm']['SlurmCtl']['CloudWatchPeriod']
            if 'Federation' in self.config['slurm']:
                instance_template_vars["Federation"] = self.config['slurm']['Federation']['Name']
            instance_template_vars["GridSubnet1"] = self.subnet.subnet_id
            instance_template_vars["JobCompLoc"] = self.config['slurm']['JobCompLoc']
            instance_template_vars["JobCompType"] = self.config['slurm']['JobCompType']
            instance_template_vars["MaxStoppedDuration"] = self.config['slurm']['SlurmCtl']['MaxStoppedDuration']
            instance_template_vars['MungeKeySsmParameter'] = self.config['slurm']['MungeKeySsmParameter']
            instance_template_vars["NumberOfControllers"] = self.config['slurm']['SlurmCtl']['NumberOfControllers']
            instance_template_vars["PreemptExemptTime"] = self.config['slurm']['SlurmCtl']['PreemptExemptTime']
            instance_template_vars["PreemptMode"] = self.config['slurm']['SlurmCtl']['PreemptMode']
            instance_template_vars["PreemptType"] = self.config['slurm']['SlurmCtl']['PreemptType']
            instance_template_vars["SlurmCtlBaseHostname"] = self.config['slurm']['SlurmCtl']['BaseHostname']
            instance_template_vars['SlurmNodeProfileArn'] = self.slurm_node_instance_profile.attr_arn
            instance_template_vars['SlurmNodeRoleName'] = self.slurm_node_role.role_name
            instance_template_vars["SlurmNodeSecurityGroup"] = self.slurmnode_sg.security_group_id
            instance_template_vars["SuspendAction"] = self.config['slurm']['SlurmCtl']['SuspendAction']
            instance_template_vars["UseAccountingDatabase"] = self.useSlurmDbd
        elif 'SlurmNodeAmi':
            pass
            # instance_template_vars['SlurmNodeRoleArn'] = self.slurm_node_role.role_arn
        else:
            raise ValueError(f"Invalid instance role {instance_role}")

        return instance_template_vars

    def create_slurmctl(self):
        if self.config['slurm']['MungeKeySsmParameter']:
            self.munge_key_ssm_parameter = ssm.StringParameter.from_string_parameter_name(
                self, f"MungeKeySsmParamter",
                string_parameter_name  = f"{self.config['slurm']['MungeKeySsmParameter']}"
            )
        else:
            self.munge_key_ssm_parameter = None

        self.slurmctl_role = iam.Role(self, "SlurmCtlRole",
            assumed_by=iam.CompositePrincipal(
                iam.ServicePrincipal(self.principals_suffix["ssm"]),
                iam.ServicePrincipal(self.principals_suffix["ec2"])
            )
        )

        self.slurmctl_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCOre"))
        self.slurmctl_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchAgentServerPolicy"))

        self.slurmctl_policy = iam.Policy(self, "SlurmCtlPolicy",
            policy_name = "SlurmCtl",
            roles = [self.slurmctl_role],
            statements = [
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        'ec2:CreateTags',
                    ],
                    resources = [
                        f"arn:{Aws.PARTITION}:ec2:*:{Aws.ACCOUNT_ID}:volume/*",
                        f"arn:{Aws.PARTITION}:ec2:*:{Aws.ACCOUNT_ID}:network-interface/*",
                    ]
                ),
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        'ec2:DescribeVolumes',
                    ],
                    # Does not support resource-level permissions and require you to choose All resources
                    resources = ["*"]
                ),
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        'ec2:DescribeNetworkInterfaces',
                    ],
                    # Does not support resource-level permissions and require you to choose All resources
                    resources = ["*"]
                ),
                # Permissions required to run instances
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        'ec2:RunInstances'
                    ],
                    resources = [
                        f"arn:{Aws.PARTITION}:ec2:{Aws.REGION}:{Aws.ACCOUNT_ID}:instance/*",
                        f"arn:{Aws.PARTITION}:ec2:{Aws.REGION}:{Aws.ACCOUNT_ID}:key-pair/{self.config['SshKeyPair']}",
                        f"arn:{Aws.PARTITION}:ec2:{Aws.REGION}:{Aws.ACCOUNT_ID}:network-interface/*",
                        f"arn:{Aws.PARTITION}:ec2:{Aws.REGION}:{Aws.ACCOUNT_ID}:security-group/{self.slurmnode_sg.security_group_id}",
                        f"arn:{Aws.PARTITION}:ec2:{Aws.REGION}:{Aws.ACCOUNT_ID}:subnet/{self.subnet.subnet_id}",
                        f"arn:{Aws.PARTITION}:ec2:{Aws.REGION}:{Aws.ACCOUNT_ID}:volume/*",
                        f"arn:{Aws.PARTITION}:ec2:{Aws.REGION}:{Aws.ACCOUNT_ID}:image/*",
                        f"arn:{Aws.PARTITION}:ec2:{Aws.REGION}::image/*",
                    ]
                ),
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        'iam:PassRole'
                    ],
                    resources = [
                        self.slurm_node_role.role_arn,
                        self.slurm_node_instance_profile.attr_arn
                    ]
                ),
                # Permissions to describe instances
                # Permissions to start instances
                # Permissions to stop instances
                # Permissions to terminate instances
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        'ec2:CreateTags',
                        'ec2:StartInstances',
                        'ec2:StopInstances',
                        'ec2:TerminateInstances'
                    ],
                    resources = [f"arn:{Aws.PARTITION}:ec2:{Aws.REGION}:{Aws.ACCOUNT_ID}:instance/*"]
                ),
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        'ec2:DescribeInstances',
                        'ec2:DescribeInstanceTypes',
                    ],
                    # Does not support resource-level permissions and require you to choose All resources
                    resources = ["*"]
                ),
                # Decode error messages
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        'sts:DecodeAuthorizationMessage'
                    ],
                    # Does not support resource-level permissions and require you to choose All resources
                    resources = ["*"]
                ),
                # Allow Slurm Master to get Ec2 Pricing Data
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        "pricing:GetProducts",
                    ],
                    # Does not support resource-level permissions and require you to choose All resources
                    resources = ["*"]
                ),
            ]
            )
        if self.config['ErrorSnsTopicArn']:
            self.slurmctl_policy.add_statements(
                # Allow SlurmMaster instances to publish to SNS when cfn-init fails
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        "sns:Publish*",
                        ],
                    resources = [self.config['ErrorSnsTopicArn']]
                    )
                )

        # Create the SlurmCtl Instance(s)
        distribution = 'Amazon'
        distribution_major_version = 2
        architecture = self.config['slurm']['SlurmCtl']['architecture']
        ami_id = self.config['AmiMap'][self.region][distribution][distribution_major_version][architecture]['ImageId']
        root_device_name = self.config['AmiMap'][self.region][distribution][distribution_major_version][architecture]['RootDeviceName']
        self.slurmctl_instances = []
        for instance_index in range(1, self.config['slurm']['SlurmCtl']['NumberOfControllers'] + 1):
            hostname = f"{self.config['slurm']['SlurmCtl']['BaseHostname']}{instance_index}"
            slurmctl_instance = ec2.Instance(self, f"SlurmCtlInstance{instance_index}",
                machine_image=ec2.MachineImage.generic_linux({self.region: ami_id}),
                instance_type=ec2.InstanceType(self.config['slurm']['SlurmCtl']['instance_type']),
                key_name=self.config['SshKeyPair'],
                vpc=self.vpc,
                vpc_subnets = ec2.SubnetSelection(subnets=[self.subnet]),
                block_devices=[
                    ec2.BlockDevice(
                        device_name = root_device_name,
                        volume=ec2.BlockDeviceVolume.ebs(
                            volume_size=int(self.config['slurm']['SlurmCtl']['volume_size']),
                            volume_type=ec2.EbsDeviceVolumeType.GP3,
                            delete_on_termination = True,
                            encrypted = True
                        )
                    )
                ],
                role=self.slurmctl_role,
                security_group=self.slurmctl_sg,
                user_data=ec2.UserData.for_linux(shebang='#!/bin/bash -ex')
            )
            self.slurmctl_instances.append(slurmctl_instance)

            name = f"{self.stack_name}-SlurmSlurmCtl{instance_index}"
            Tags.of(slurmctl_instance).add("Name", name)
            Tags.of(slurmctl_instance).add("hostname", hostname)
            Tags.of(slurmctl_instance).add("NodeType", "slurm_slurmctl")

            slurmctl_instance.node.add_dependency(self.file_system_dependency)

            instance_template_vars = self.get_instance_template_vars('SlurmCtl')
            instance_template_vars['PrimaryController'] = instance_index == 1
            instance_template_vars['CONFIG_SCRIPT_PATH'] = '/root/slurmctl_config.sh'
            instance_template_vars['INSTANCE_CONFIG_LOCAL_PATH'] = f"/root/InstanceConfig.yml"
            instance_template_vars['INSTANCE_CONFIG_PATH'] = f"/opt/slurm/{self.config['slurm']['ClusterName']}/config/InstanceConfig.yml"
            instance_template_vars['PLAYBOOKS_ZIP_PATH'] = '/root/playbooks.zip'

            if self.munge_key_ssm_parameter:
                self.munge_key_ssm_parameter.grant_read(slurmctl_instance)
                self.munge_key_ssm_parameter.grant_write(slurmctl_instance)

            # Configure user_data
            instance_template_vars['SlurmCtlHostname'] = hostname

            # Add on_exit commands at top of user_data
            slurmctl_instance.user_data.add_signal_on_exit_command(slurmctl_instance)
            on_exit_commands_template = Template(open("resources/user_data/slurmctl_user_data_on_exit.sh", 'r').read())
            on_exit_commands = on_exit_commands_template.render(**instance_template_vars)
            slurmctl_instance.user_data.add_on_exit_commands(on_exit_commands)

            # Set the environment.
            self.add_environment_user_data(slurmctl_instance, name, architecture, distribution, distribution_major_version, instance_template_vars)

            # Download playbook
            self.playbooks_asset.grant_read(slurmctl_instance.role)
            slurmctl_instance.user_data.add_s3_download_command(
                bucket = self.playbooks_asset.bucket,
                bucket_key = self.playbooks_asset.s3_object_key,
                local_file = instance_template_vars['PLAYBOOKS_ZIP_PATH']
            )

            # Download config script
            self.slurmctl_config_asset.grant_read(slurmctl_instance.role)
            slurmctl_instance.user_data.add_s3_download_command(
                bucket = self.slurmctl_config_asset.bucket,
                bucket_key = self.slurmctl_config_asset.s3_object_key,
                local_file = instance_template_vars['CONFIG_SCRIPT_PATH']
            )

            # Download InstanceConfig
            self.instance_config_asset.grant_read(slurmctl_instance.role)
            slurmctl_instance.user_data.add_s3_download_command(
                bucket = self.instance_config_asset.bucket,
                bucket_key = self.instance_config_asset.s3_object_key,
                local_file = instance_template_vars['INSTANCE_CONFIG_LOCAL_PATH']
            )

            user_data_template = Template(open("resources/user_data/slurmctl_user_data.sh", 'r').read())
            user_data = user_data_template.render(**instance_template_vars)
            slurmctl_instance.user_data.add_commands(user_data)

            # Create DNS entry
            self.slurmctl_dns_record = CustomResource(
                self, f"SlurmCtl{instance_index}DnsRecord",
                service_token = self.update_dns_lambda.function_arn,
                properties={
                    "Hostname": hostname,
                    "Domain": self.config['Domain'],
                    "HostedZoneId": self.hosted_zone.hosted_zone_id,
                    "Type": 'A',
                    "Value": slurmctl_instance.instance_private_ip
                }
            ).get_att_string('CIDR')

    def create_slurmdbd(self):
        if 'SlurmDbd' not in self.config['slurm']:
            return

        self.slurmdbd_role = iam.Role(self, "SlurmDbdRole",
            assumed_by=iam.CompositePrincipal(
                iam.ServicePrincipal(self.principals_suffix["ssm"]),
                iam.ServicePrincipal(self.principals_suffix["ec2"])
            )
        )

        self.slurmdbd_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCOre"))
        self.slurmdbd_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchAgentServerPolicy"))

        self.slurmdbd_policy = iam.Policy(self, "SlurmDbdPolicy",
            policy_name = "SlurmDbd",
            roles = [self.slurmdbd_role],
            statements = [
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        'ec2:CreateTags',
                    ],
                    resources = [
                        f"arn:{Aws.PARTITION}:ec2:*:{Aws.ACCOUNT_ID}:volume/*",
                        f"arn:{Aws.PARTITION}:ec2:*:{Aws.ACCOUNT_ID}:network-interface/*",
                    ]
                ),
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        'ec2:DescribeNetworkInterfaces',
                    ],
                    # Does not support resource-level permissions and require you to choose All resources
                    resources = ["*"]
                ),
                # Allow instances to get ssm CW agent configuration parameters, AMI parameters
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        "ssm:GetParameter"
                    ],
                    resources = [
                        f"arn:{Aws.PARTITION}:ssm:{Aws.REGION}:{Aws.ACCOUNT_ID}:parameter/AmazonCloudWatch*"
                        f"arn:{Aws.PARTITION}:ssm:{Aws.REGION}:{Aws.ACCOUNT_ID}:parameter/CloudWatchAgentConfig*"
                    ]
                ),
            ]
        )
        if self.config['ErrorSnsTopicArn']:
            self.slurmdbd_policy.add_statements(
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        "sns:Publish"
                        ],
                    resources = [self.config['ErrorSnsTopicArn']]
                    )
                )

        # Create the SlurmDbd Instance
        distribution = 'Amazon'
        distribution_major_version = 2
        architecture = self.config['slurm']['SlurmDbd']['architecture']
        ami_id = self.config['AmiMap'][self.region][distribution][distribution_major_version][architecture]['ImageId']
        root_device_name = self.config['AmiMap'][self.region][distribution][distribution_major_version][architecture]['RootDeviceName']
        hostname = self.config['slurm']['SlurmDbd']['Hostname']
        self.slurmdbd_instance = ec2.Instance(self, "SlurmDbdInstance",
            machine_image=ec2.MachineImage.generic_linux({self.region: ami_id}),
            instance_type=ec2.InstanceType(self.config['slurm']['SlurmDbd']['instance_type']),
            key_name=self.config['SshKeyPair'],
            vpc=self.vpc,
            vpc_subnets = ec2.SubnetSelection(subnets=[self.subnet]),
            block_devices=[
                ec2.BlockDevice(
                    device_name = root_device_name,
                    volume=ec2.BlockDeviceVolume.ebs(
                        volume_size=int(self.config['slurm']['SlurmDbd']['volume_size']),
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                        delete_on_termination = True,
                        encrypted = True
                    )
                )
            ],
            role=self.slurmdbd_role,
            security_group=self.slurmdbd_sg,
            user_data=ec2.UserData.for_linux(shebang='#!/bin/bash -ex')
        )
        name = f"{self.stack_name}-SlurmSlurmDbd"
        Tags.of(self.slurmdbd_instance).add("Name", name)
        Tags.of(self.slurmdbd_instance).add("hostname", hostname)
        Tags.of(self.slurmdbd_instance).add("NodeType", "slurm_slurmdbd")

        self.slurmdbd_instance.node.add_dependency(self.file_system_dependency)
        self.slurmdbd_instance.node.add_dependency(self.db_cluster)

        self.database_secret.grant_read(self.slurmdbd_instance)

        # Configure user_data
        instance_template_vars = self.get_instance_template_vars('SlurmDbd')
        instance_template_vars['SlurmDbdHostname'] = hostname
        instance_template_vars['CONFIG_SCRIPT_PATH'] = '/root/slurmdbd_config.sh'
        instance_template_vars['PLAYBOOKS_ZIP_PATH'] = '/root/playbooks.zip'

        # Add on_exit commands at top of user_data
        self.slurmdbd_instance.user_data.add_signal_on_exit_command(self.slurmdbd_instance)
        on_exit_commands_template = Template(open("resources/user_data/slurmdbd_user_data_on_exit.sh", 'r').read())
        on_exit_commands = on_exit_commands_template.render(**instance_template_vars)
        self.slurmdbd_instance.user_data.add_on_exit_commands(on_exit_commands)

        # Set the environment.
        self.add_environment_user_data(self.slurmdbd_instance, name, architecture, distribution, distribution_major_version, instance_template_vars)

        # Download playbook
        self.playbooks_asset.grant_read(self.slurmdbd_instance.role)
        self.slurmdbd_instance.user_data.add_s3_download_command(
            bucket = self.playbooks_asset.bucket,
            bucket_key = self.playbooks_asset.s3_object_key,
            local_file = instance_template_vars['PLAYBOOKS_ZIP_PATH']
        )

        # Download config script
        self.slurmdbd_config_asset.grant_read(self.slurmdbd_instance.role)
        self.slurmdbd_instance.user_data.add_s3_download_command(
            bucket = self.slurmdbd_config_asset.bucket,
            bucket_key = self.slurmdbd_config_asset.s3_object_key,
            local_file = instance_template_vars['CONFIG_SCRIPT_PATH']
        )

        user_data_template = Template(open("resources/user_data/slurmdbd_user_data.sh", 'r').read())
        user_data = user_data_template.render(**instance_template_vars)
        self.slurmdbd_instance.user_data.add_commands(user_data)

        # Create DNS entry
        self.slurmdbd_dns_record = CustomResource(
            self, "SlurmDbdDnsRecord",
            service_token = self.update_dns_lambda.function_arn,
            properties={
                "Hostname": self.config['slurm']['SlurmDbd']['Hostname'],
                "Domain": self.config['Domain'],
                "HostedZoneId": self.hosted_zone.hosted_zone_id,
                "Type": 'A',
                "Value": self.slurmdbd_instance.instance_private_ip
                }
            ).get_att_string('CIDR')

        if self.slurmDbdFQDN:
            CfnOutput(self, "SlurmDbdFQDN",
                value = self.slurmDbdFQDN
                )

    def create_slurm_nodes(self):
        self.slurm_node_role = iam.Role(
            self, "SlurmNodeRole",
            assumed_by=iam.CompositePrincipal(
                iam.ServicePrincipal(self.principals_suffix["ssm"]),
                iam.ServicePrincipal(self.principals_suffix["ec2"])
            )
        )

        self.slurm_node_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCOre"))
        self.slurm_node_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchAgentServerPolicy"))

        policy_statements = [
            iam.PolicyStatement(
                effect = iam.Effect.ALLOW,
                actions = [
                    "cloudwatch:PutMetricData",
                    ],
                resources = [
                    f'arn:{Aws.PARTITION}:cloudwatch:{Aws.REGION}:{Aws.ACCOUNT_ID}:*'
                    ]
                ),
            ]
        if self.config['ErrorSnsTopicArn']:
            policy_statements.append(
                # Publish errors to SNS
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        "sns:Publish*",
                        ],
                    resources = [self.config['ErrorSnsTopicArn']]
                    ),
            )
        self.slurm_node_policy = iam.Policy(self, "SlurmNodePolicy",
            policy_name = "SlurmNodeAmi",
            roles = [self.slurm_node_role],
            statements = policy_statements
        )

        self.slurm_node_instance_profile = iam.CfnInstanceProfile(
            self, "SlurmNodeInstanceProfile",
            roles = [self.slurm_node_role.role_name]
        )

    def create_slurm_node_ami(self):
        self.slurm_node_ami_role = iam.Role(self, "SlurmNodeAmiRole",
            assumed_by=iam.CompositePrincipal(
                iam.ServicePrincipal(self.principals_suffix["ssm"]),
                iam.ServicePrincipal(self.principals_suffix["ec2"])
            )
        )

        self.slurm_node_ami_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCOre"))
        self.slurm_node_ami_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchAgentServerPolicy"))

        self.slurm_node_ami_policy = iam.Policy(self, "SlurmNodeAmiPolicy",
            policy_name = "SlurmNodeAmi",
            roles = [self.slurm_node_ami_role],
            statements = [
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        'ec2:CreateTags',
                    ],
                    resources = [
                        f"arn:{Aws.PARTITION}:ec2:{Aws.REGION}::image/*",
                        f"arn:{Aws.PARTITION}:ec2:{Aws.REGION}:{Aws.ACCOUNT_ID}:network-interface/*",
                        f"arn:{Aws.PARTITION}:ec2:{Aws.REGION}:{Aws.ACCOUNT_ID}:volume/*",
                    ]
                ),
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        'ec2:DescribeVolumes',
                        'ec2:DescribeImages'
                    ],
                    # Does not support resource-level permissions and require you to choose All resources
                    resources = ["*"]
                ),
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        'ec2:DescribeNetworkInterfaces',
                    ],
                    # Does not support resource-level permissions and require you to choose All resources
                    resources = ["*"]
                ),
                # Permissions to stop instances
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        'ec2:StopInstances'
                    ],
                    resources = [
                        f"arn:{Aws.PARTITION}:ec2:{Aws.REGION}:{Aws.ACCOUNT_ID}:instance/*",
                    ]
                ),
                # Permissions to create and tag AMI
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        'ec2:CreateTags',
                    ],
                    resources=[f'arn:{Aws.PARTITION}:ec2:{Aws.REGION}:{Aws.ACCOUNT_ID}:image/*']
                ),
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        'ec2:CreateImage',
                    ],
                    resources=[
                        f'arn:{Aws.PARTITION}:ec2:{Aws.REGION}::image/*',
                        f'arn:{Aws.PARTITION}:ec2:{Aws.REGION}:{Aws.ACCOUNT_ID}:instance/*',
                        f'arn:{Aws.PARTITION}:ec2:{Aws.REGION}::snapshot/*'
                        ]
                ),
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        'ec2:DescribeImages'
                    ],
                    # Does not support resource-level permissions and require you to choose All resources
                    resources = ["*"]
                ),
                # Decode error messages
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        'sts:DecodeAuthorizationMessage'
                    ],
                    # Does not support resource-level permissions and require you to choose All resources
                    resources = ["*"]
                ),
            ]
        )
        if self.config['ErrorSnsTopicArn']:
            self.slurm_node_ami_policy.add_statements(
                # Publish errors to SNS
                iam.PolicyStatement(
                    effect = iam.Effect.ALLOW,
                    actions = [
                        "sns:Publish*",
                        ],
                    resources = [self.config['ErrorSnsTopicArn']]
                    )
                )

        # Create the SlurmNodeAmi Instances
        # At a minimum need Amazon Linux 2 for the CPU architectures used by the slurmctl and slurmdbd instances.
        # Add to that the distributions and architectures in the InstanceConfig
        self.slurm_node_ami_instances = {}
        self.ami_ssm_parameters = {}
        distributions = {
            'Amazon': {2: [self.config['slurm']['SlurmCtl']['architecture']]}
        }
        if 'SlurmDbd' in self.config['slurm']:
            if self.config['slurm']['SlurmDbd']['architecture'] != self.config['slurm']['SlurmCtl']['architecture']:
                distributions['Amazon'][2].append(self.config['slurm']['SlurmDbd']['architecture'])
        if 'BaseAmis' in self.config['slurm']['SlurmNodeAmis']:
            for distribution, distribution_dict in self.config['slurm']['SlurmNodeAmis']['BaseAmis'][self.region].items():
                if distribution not in distributions:
                    distributions[distribution] = {}
                for distribution_major_version, version_dict in distribution_dict.items():
                    if distribution_major_version not in distributions[distribution]:
                        distributions[distribution][distribution_major_version] = []
                    for architecture in version_dict:
                        if architecture not in distributions[distribution][distribution_major_version]:
                            distributions[distribution][distribution_major_version].append(architecture)
        for distribution, distribution_dict in self.config['slurm']['InstanceConfig']['BaseOsArchitecture'].items():
            if distribution not in distributions:
                distributions[distribution] = {}
            for distribution_major_version, version_dict in distribution_dict.items():
                if distribution_major_version not in distributions[distribution]:
                    distributions[distribution][distribution_major_version] = []
                for architecture in version_dict:
                    if architecture not in distributions[distribution][distribution_major_version]:
                        distributions[distribution][distribution_major_version].append(architecture)
        ec2_client = boto3.client('ec2', region_name=self.region)
        for distribution, distribution_dict in distributions.items():
            self.slurm_node_ami_instances[distribution] = {}
            self.ami_ssm_parameters[distribution] = {}
            for distribution_major_version, version_dict in distribution_dict.items():
                self.slurm_node_ami_instances[distribution][distribution_major_version] = {}
                self.ami_ssm_parameters[distribution][distribution_major_version] = {}
                for architecture in version_dict:
                    os_tag = f"{distribution}-{distribution_major_version}-{architecture}"
                    try:
                        ami_id = self.config['slurm']['SlurmNodeAmis']['BaseAmis'][self.region][distribution][distribution_major_version][architecture]['ImageId']
                    except KeyError:
                        try:
                            ami_id = self.config['AmiMap'][self.region][distribution][distribution_major_version][architecture]['ImageId']
                        except KeyError:
                            logger.error(f"AmiMap doesn't have ImageId for {self.region}/{distribution}/{distribution_major_version}/{architecture}")
                            sys.exit(1)
                    ami_info = ec2_client.describe_images(ImageIds=[ami_id])['Images'][0]
                    block_devices = []
                    root_device = True
                    for block_device_info in ami_info['BlockDeviceMappings']:
                        ami_volume_size = int(block_device_info['Ebs']['VolumeSize'])
                        if root_device:
                            try:
                                volume_size = str(self.config['slurm']['SlurmNodeAmis']['BaseAmis'][self.region][distribution][distribution_major_version][architecture]['RootDeviceSize'])
                                if volume_size[0] == '+':
                                    volume_size = int(ami_volume_size) + int(volume_size[1:])
                                else:
                                    volume_size = int(volume_size)
                                    if volume_size < ami_volume_size:
                                        logger.error(f"slurm/SlurmNodeAmis/BaseAmis/{self.region}/{distribution}/{distribution_major_version}/{architecture}/RootDeviceSize must be >= {ami_volume_size}")
                                        sys.exit(1)
                            except KeyError:
                                volume_size = ami_volume_size
                            root_device = False
                        else:
                            volume_size = block_device_info['Ebs']['VolumeSize']
                        block_devices.append(
                            ec2.BlockDevice(
                                device_name = block_device_info['DeviceName'],
                                volume=ec2.BlockDeviceVolume.ebs(
                                    volume_size = volume_size,
                                    volume_type=ec2.EbsDeviceVolumeType.GP3,
                                    delete_on_termination = True,
                                    encrypted = True
                                )
                            )
                        )
                    self.slurm_node_ami_instance = ec2.Instance(
                        self, f"SlurmNodeAmisInstance{distribution}{distribution_major_version}{architecture}",
                        machine_image=ec2.MachineImage.generic_linux({self.region: ami_id}),
                        instance_type=ec2.InstanceType(self.config['slurm']['SlurmNodeAmis']['instance_type'][architecture]),
                        key_name=self.config['SshKeyPair'],
                        vpc=self.vpc,
                        vpc_subnets = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
                        block_devices = block_devices,
                        role=self.slurm_node_ami_role,
                        security_group=self.slurmnode_sg,
                        user_data=ec2.UserData.for_linux(shebang='#!/bin/bash -ex')
                    )
                    self.slurm_node_ami_instances[distribution][distribution_major_version][architecture] = self.slurm_node_ami_instance
                    name = f"{self.stack_name}-SlurmSlurmNodeAmi-{os_tag}"
                    Tags.of(self.slurm_node_ami_instance).add("Name", name)
                    Tags.of(self.slurm_node_ami_instance).add("NodeType", "slurm_node_ami")

                    self.slurm_node_ami_instance.node.add_dependency(self.file_system_dependency)

                    self.ami_ssm_parameters[distribution][distribution_major_version][architecture] = ssm.StringParameter(
                        self, f"SlurmNodeAmiSsmParameter{distribution}{distribution_major_version}{architecture}",
                        parameter_name = f"/{self.stack_name}/SlurmNodeAmis/{distribution}/{distribution_major_version}/{architecture}",
                        string_value = "UNDEFINED",
                    )
                    self.ami_ssm_parameters[distribution][distribution_major_version][architecture].grant_write(self.slurm_node_ami_instance)
                    ami_ssm_parameter = self.ami_ssm_parameters[distribution][distribution_major_version][architecture]

                    instance_template_vars = self.get_instance_template_vars('SlurmNodeAmi')
                    instance_template_vars['CONFIG_SCRIPT_PATH'] = '/root/slurm_node_ami_config.sh'
                    instance_template_vars['WAIT_FOR_AMI_SCRIPT_PATH'] = '/root/WaitForAmi.py'
                    instance_template_vars['PLAYBOOKS_ZIP_PATH'] = '/root/playbooks.zip'
                    instance_template_vars['SlurmNodeAmiSsmParameter'] = ami_ssm_parameter.parameter_name
                    instance_template_vars['SLURM_ROOT'] = f"{instance_template_vars['FileSystemMountPath']}/slurm-{self.config['slurm']['SlurmVersion']}/{distribution}/{distribution_major_version}/{architecture}"

                    # Add on_exit commands at top of user_data
                    self.slurm_node_ami_instance.user_data.add_signal_on_exit_command(self.slurm_node_ami_instance)
                    on_exit_commands_template = Template(open("resources/user_data/slurm_node_ami_user_data_on_exit.sh", 'r').read())
                    on_exit_commands = on_exit_commands_template.render(**instance_template_vars)
                    self.slurm_node_ami_instance.user_data.add_on_exit_commands(on_exit_commands)

                    # Set the environment.
                    self.add_environment_user_data(self.slurm_node_ami_instance, name, architecture, distribution, distribution_major_version, instance_template_vars)

                    # Download playbook
                    self.playbooks_asset.grant_read(self.slurm_node_ami_instance.role)
                    self.slurm_node_ami_instance.user_data.add_s3_download_command(
                        bucket = self.playbooks_asset.bucket,
                        bucket_key = self.playbooks_asset.s3_object_key,
                        local_file = instance_template_vars['PLAYBOOKS_ZIP_PATH']
                    )

                    # Download config script
                    self.slurm_node_ami_config_asset.grant_read(self.slurm_node_ami_instance.role)
                    self.slurm_node_ami_instance.user_data.add_s3_download_command(
                        bucket = self.slurm_node_ami_config_asset.bucket,
                        bucket_key = self.slurm_node_ami_config_asset.s3_object_key,
                        local_file = instance_template_vars['CONFIG_SCRIPT_PATH']
                    )

                    # Download WaitForAmi.py script
                    self.slurm_node_ami_wait_for_ami_asset.grant_read(self.slurm_node_ami_instance.role)
                    self.slurm_node_ami_instance.user_data.add_s3_download_command(
                        bucket = self.slurm_node_ami_wait_for_ami_asset.bucket,
                        bucket_key = self.slurm_node_ami_wait_for_ami_asset.s3_object_key,
                        local_file = instance_template_vars['WAIT_FOR_AMI_SCRIPT_PATH']
                    )

                    user_data_template = Template(open("resources/user_data/slurm_node_ami_user_data.sh", 'r').read())
                    user_data = user_data_template.render(**instance_template_vars)
                    self.slurm_node_ami_instance.user_data.add_commands(user_data)

    def add_environment_user_data(self, instance, name, architecture, distribution, distribution_major_version, vars):
        instance.user_data.add_commands(dedent(f"""
            # Set variables used by user_data_bootstrap.sh
            AWS_DEFAULT_REGION={self.region}
            ARCHITECTURE={architecture}
            DISTRIBUTION={distribution}
            DISTRIBUTION_MAJOR_VERSION={distribution_major_version}
            INSTANCE_NAME={name}
            """))

        # Install ssm agent, ansible, awscli
        # The awscli must be install before can download asses from s3.
        instance.user_data.add_commands(open('resources/user_data/user_data_bootstrap.sh').read())

        # Set environment variables
        # This needs to be in the UserData section of the script so that tokens get correctly substituted by CloudFormation
        user_data = ""
        user_data += "{\n"
        user_data += '    echo "export ARCHITECTURE=\\"$ARCHITECTURE\\""\n'
        user_data += '    echo "export DISTRIBUTION=\\"$DISTRIBUTION\\""\n'
        user_data += '    echo "export DISTRIBUTION_MAJOR_VERSION=\\"$DISTRIBUTION_MAJOR_VERSION\\""\n'
        user_data += '    echo "export INSTANCE_NAME=\\"$INSTANCE_NAME\\""\n'
        user_data += '    echo "export PATH=/usr/local/bin:$PATH"\n'
        for name, value in sorted(vars.items()):
            user_data += f'    echo "export {name}=\\"{value}\\""\n'
        user_data += "} > /etc/profile.d/instance_vars.sh\n"
        user_data += "source /etc/profile.d/instance_vars.sh\n"
        instance.user_data.add_commands(user_data)

        fh = NamedTemporaryFile('w', delete=False)
        fh.write("\n{")
        fh.write('    echo "setenv ARCHITECTURE \\"$ARCHITECTURE\\""\n')
        fh.write('    echo "setenv DISTRIBUTION \\"$DISTRIBUTION\\""\n')
        fh.write('    echo "setenv DISTRIBUTION_MAJOR_VERSION \\"$DISTRIBUTION_MAJOR_VERSION\\""\n')
        fh.write('    echo "setenv INSTANCE_NAME \\"$INSTANCE_NAME\\""\n')
        fh.write('    echo "setenv PATH /usr/local/bin:$PATH"\n')
        for name, value in sorted(vars.items()):
            fh.write(f'    echo "setenv {name} \\"${name}\\""\n')
        fh.write("} > /etc/profile.d/instance_vars.csh\n")
        instance_vars_csh_asset = s3_assets.Asset(self, fh.name, path=fh.name)
        instance_vars_csh_asset.grant_read(instance.role)
        instance.user_data.add_s3_download_command(
            bucket = instance_vars_csh_asset.bucket,
            bucket_key = instance_vars_csh_asset.s3_object_key,
            local_file = '/tmp/create-instance_vars_csh.sh'
        )
        instance.user_data.add_commands('chmod +x /tmp/create-instance_vars_csh.sh')
        instance.user_data.add_commands('/tmp/create-instance_vars_csh.sh\n')

        fh = NamedTemporaryFile('w', delete=False)
        fh.write("\n{\n")
        for name, value in sorted(vars.items()):
            fh.write(f'    echo {name}: "${name}"\n')
        fh.write("} > /root/ansible_extra_vars.yml\n")
        fh.close()
        ansible_extra_vars_yml_asset = s3_assets.Asset(self, fh.name, path=fh.name)
        ansible_extra_vars_yml_asset.grant_read(instance.role)
        instance.user_data.add_s3_download_command(
            bucket = ansible_extra_vars_yml_asset.bucket,
            bucket_key = ansible_extra_vars_yml_asset.s3_object_key,
            local_file = '/tmp/create-ansible_extra_vars_yml.sh'
        )
        instance.user_data.add_commands('chmod +x /tmp/create-ansible_extra_vars_yml.sh')
        instance.user_data.add_commands('/tmp/create-ansible_extra_vars_yml.sh\n')

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
                            resources = [f"arn:{Aws.PARTITION}:ec2:{Aws.REGION}:{Aws.ACCOUNT_ID}:instance/*"]
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
