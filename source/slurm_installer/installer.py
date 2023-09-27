#!/usr/bin/env python3
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

"""
It's recommended to trigger this script via ../installer.sh as python's virtual env and all required
libraries/dependencies will be automatically installed.

If you trigger ./installer.py directly, make sure to have all the Python and CDK dependencies installed
"""

import argparse
import base64
import boto3
from botocore.client import ClientError
from botocore.exceptions import ProfileNotFound, ValidationError
from botocore import config
from colored import fg, bg, attr
import datetime
import json
import logging
import os
import os.path
from os.path import dirname, realpath
from requests import get
from requests.exceptions import RequestException, Timeout
import shutil
from shutil import make_archive, copytree
import sys
import urllib3
import yaml
from yaml.scanner import ScannerError

installer_path = os.path.dirname(os.path.abspath(__file__))
sys.path.append(installer_path)
source_path = os.path.dirname(installer_path)
sys.path.append(source_path)

from find_existing_resources import FindExistingResource
from prompt import get_input as get_input

logger = logging.getLogger(__file__)
logger_formatter = logging.Formatter('%(levelname)s: %(message)s')
logger_streamHandler = logging.StreamHandler()
logger_streamHandler.setFormatter(logger_formatter)
logger.addHandler(logger_streamHandler)
logger.propagate = False
logger.setLevel(logging.INFO)

urllib3.disable_warnings()

class SlurmInstaller():

    def __init__(self):
        self.install_parameters = {}

    def main(self):
        parser = argparse.ArgumentParser(description="Create a high throughput SLURM cluster.")
        parser.add_argument("--config-file", type=str, help="Configuration file. Can be absolute or relative path or filename in the config directory.")
        parser.add_argument("--prompt", action='store_true', help="Prompt for configuration values if not in config file or if invalid.")
        parser.add_argument("--stack-name", type=str, help="CloudFormation stack name.")
        parser.add_argument("--profile", "-p", type=str, help="AWS CLI profile to use.")
        parser.add_argument("--region", "-r", type=str, help="AWS region where you want to deploy your SOCA environment.")
        parser.add_argument("--SshKeyPair", "-ssh", type=str, help="SSH key to use")
        parser.add_argument("--VpcId", type=str, help="Id of VPC to use")
        parser.add_argument("--SubnetId", type=str, help="SubnetId to use")
        parser.add_argument("--ErrorSnsTopicArn", type=str, default='', help="SNS topic for error notifications.")
        parser.add_argument("--SubmitterSecurityGroupIds", type=str, default=None, help="External security groups that should be able to use the cluster.")
        parser.add_argument("--debug", action='store_const', const=True, default=False, help="Enable CDK debug mode")
        parser.add_argument("--cdk-cmd", type=str, choices=["deploy", "create", "update", "diff", "ls", "list", "synth", "synthesize", "destroy", "bootstrap"], default="synth")
        args = parser.parse_args()

        # Use script location as current working directory
        install_directory = os.path.dirname(os.path.realpath(f"{__file__}/.."))
        os.chdir(install_directory)
        logger.info(f"\nWorking directory: {install_directory}")

        logger.info("\n====== Validating AWS environment ======\n")

        # Load AWS custom profile if specified
        if args.profile:
            try:
                session = boto3.session.Session(profile_name=args.profile)
            except ProfileNotFound:
                logger.error(f"{fg('red')}Profile {args.profile} not found. Check ~/.aws/credentials file{attr('reset')}")
                sys.exit(1)
        else:
            session = boto3.session.Session()

        # Determine all AWS regions available on the account. We do not display opt-out region
        default_region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        ec2 = session.client("ec2", region_name=default_region)
        try:
            self.accepted_regions = [region["RegionName"] for region in ec2.describe_regions()["Regions"]]
        except ClientError as err:
            logger.error(f"{fg('red')}Unable to list all AWS regions. Make sure you have set your IAM credentials. {err} {attr('reset')}")
            sys.exit(1)

        self.config = self.get_config(args.config_file)

        # Apply command line arguments to the config

        # Save prompted responses
        cmdline_args = sys.argv[1:]
        prompt_args = []

        # Choose region where SOCA is installed
        # Must be passed to the stack.
        if 'Region' not in self.config and not args.region:
            if not args.prompt:
                logger.error(f"{fg('red')}Must specify --prompt or --region on the command line or Region in the config file.{attr('reset')}")
                sys.exit(1)
            self.config['Region'] = get_input("Which AWS region will the SLURM cluster be installed in?", '', self.accepted_regions, str)
            prompt_args += ['--region', self.config['Region']]
        else:
            if args.region:
                if 'Region' in self.config:
                    logger.info(f"Region overridden on command line from {self.config['Region']} to {args.region}")
                self.config['Region'] = args.region
            # Check value
            get_input("Which AWS region will the SLURM cluster be installed in?", self.config['Region'], self.accepted_regions, str)
        self.install_parameters['region'] = self.config['Region']
        region = self.install_parameters['region']
        logger.info(f"region: {self.install_parameters['region']}")

        # Initiate boto3 client now the region is known
        ec2 = session.client("ec2", region_name=region)
        sts = session.client("sts", region_name=region)
        s3 = session.resource("s3", region_name=region)
        cloudformation = session.client("cloudformation", region_name=region)
        iam = session.client("iam", region_name=region)

        # Retrieve the AWS Account ID for CDK
        try:
            self.install_parameters["account_id"] = sts.get_caller_identity()["Account"]
        except Exception as err:
            logger.error(f"{fg('red')}Unable to retrieve the Account ID due to {err}{attr('reset')}")
            sys.exit(1)

        # User Specified Variables
        logger.info("\n====== Validating SLURM parameters ======\n")

        if 'StackName' not in self.config and not args.stack_name:
            if not args.prompt:
                logger.error(f"Must specify --stack-name on the command line or StackName in the config file.")
                sys.exit(1)
            self.config["StackName"] = get_input(f"Enter SLURM CloudFormation stack name", '', None, str)
            prompt_args += ['--stack-name', self.config['StackName']]
        elif args.stack_name:
            if 'StackName' in self.config:
                logger.info(f"StackName overridden on command line from {self.config['StackName']} to {args.stack_name}")
            self.config["StackName"] = args.stack_name
        self.install_parameters['stack_name'] = self.config["StackName"]
        logger.info("{:30} {}".format("stack_name:", self.install_parameters['stack_name']))

        resource_finder = FindExistingResource(region)

        config_key = 'SshKeyPair'
        if config_key not in self.config and not args.SshKeyPair and not args.prompt:
            logger.error(f"{fg('red')}Must specify --prompt or --{config_key} on the command line or {config_key} in the config file.{attr('reset')}")
            sys.exit(1)
        try:
            # Check provided values and if not provided, prompt for a value if --prompt specified
            checked_value = resource_finder.get_keypair(config_key, self.config.get(config_key, ''), args.SshKeyPair, args.prompt)
        except ValueError as e:
            logger.error(e)
            sys.exit(1)
        if args.prompt:
            if args.SshKeyPair:
                if args.SshKeyPair != checked_value:
                    for arg_index, arg_name in enumerate(cmdline_args):
                        if arg_name == f'--{config_key}':
                            cmdline_args[arg_index + 1] = checked_value
            else:
                prompt_args += [f'--{config_key}', checked_value]
        self.config[config_key] = checked_value
        self.install_parameters[config_key] = self.config[config_key]
        logger.info(f"{config_key:30}: {self.install_parameters[config_key]}")

        config_key = 'VpcId'
        if config_key not in self.config and not args.VpcId:
            if not args.prompt:
                logger.error(f"{fg('red')}Must specify --prompt or --{config_key} on the command line or {config_key}  in the config file.{attr('reset')}")
                sys.exit(1)
        try:
            checked_value = resource_finder.get_vpc_id(config_key, self.config.get(config_key, ''), args.VpcId, args.prompt)
        except ValueError as e:
            logger.error(e)
            sys.exit(1)
        if args.prompt:
            if args.VpcId:
                if args.VpcId != checked_value:
                    for arg_index, arg_name in enumerate(cmdline_args):
                        if arg_name == f'--{config_key}':
                            cmdline_args[arg_index + 1] = checked_value
            else:
                prompt_args += [f'--{config_key}', checked_value]
        self.config[config_key] = checked_value
        self.install_parameters[config_key] = self.config[config_key]
        logger.info(f"{config_key:30}: {self.install_parameters[config_key]}")

        # Get the CIDR block for the VPC. Used in multi-region deployments
        config_key = 'CIDR'
        if config_key not in self.config:
            cidr = ec2.describe_vpcs(VpcIds=[self.config['VpcId']])['Vpcs'][0]['CidrBlock']
            self.config[config_key] = cidr
        self.install_parameters[config_key] = cidr
        logger.info(f"{config_key:30}: {self.install_parameters[config_key]}")

        # Optional
        config_key = 'SubnetId'
        if config_key in self.config or args.SubnetId or args.prompt:
            try:
                checked_value = resource_finder.get_subnet_id(self.config['VpcId'], config_key, self.config.get(config_key, ''), args.SubnetId, args.prompt)
            except ValueError as e:
                logger.error(e)
                sys.exit(1)
            if checked_value:
                if args.prompt:
                    if args.SubnetId:
                        if args.SubnetId != checked_value:
                            for arg_index, arg_name in enumerate(cmdline_args):
                                if arg_name == f'--{config_key}':
                                    cmdline_args[arg_index + 1] = checked_value
                    else:
                        prompt_args += [f'--{config_key}', checked_value]
                self.config[config_key] = checked_value
                self.install_parameters[config_key] = self.config[config_key]
                logger.info(f"{config_key:30}: {self.install_parameters[config_key]}")
            elif args.SubnetId:
                while f'--{config_key}' in cmdline_args:
                    arg_index = cmdline_args.index(f'--{config_key}')
                    del cmdline_args[arg_index]
                    del cmdline_args[arg_index]

        # Optional
        config_key = 'ErrorSnsTopicArn'
        if config_key not in self.config and not args.ErrorSnsTopicArn and not args.prompt:
            logger.warning(f"{fg('yellow')}Recommend specifying --prompt or --{config_key} on the command line or {config_key} in the config file.{attr('reset')}")
        else:
            try:
                checked_value = resource_finder.get_sns_topic_arn(config_key, self.config.get(config_key, ''), args.ErrorSnsTopicArn, args.prompt)
            except ValueError as e:
                logger.error(e)
                sys.exit(1)
            if checked_value:
                if args.prompt:
                    if args.ErrorSnsTopicArn:
                        if args.ErrorSnsTopicArn != checked_value:
                            for arg_index, arg_name in enumerate(cmdline_args):
                                if arg_name == f'--{config_key}':
                                    cmdline_args[arg_index + 1] = checked_value
                    else:
                        prompt_args += [f'--{config_key}', checked_value]
                self.config[config_key] = checked_value
                self.install_parameters[config_key] = self.config[config_key]
                logger.info(f"{config_key:30}: {self.install_parameters[config_key]}")
            else:
                if args.ErrorSnsTopicArn:
                    while f'--{config_key}' in cmdline_args:
                        arg_index = cmdline_args.index(f'--{config_key}')
                        del cmdline_args[arg_index]
                        del cmdline_args[arg_index]

        # Optional
        config_key = 'SubmitterSecurityGroupIds'
        if config_key not in self.config and not args.SubmitterSecurityGroupIds and not args.prompt:
            pass
        else:
            if args.SubmitterSecurityGroupIds:
                arg_json_value = args.SubmitterSecurityGroupIds
                arg_SubmitterSecurityGroupIds = json.loads(args.SubmitterSecurityGroupIds)
            else:
                arg_json_value = ''
                arg_SubmitterSecurityGroupIds = None
            try:
                checked_value = resource_finder.get_submitter_security_groups(self.config['VpcId'], config_key, self.config.get(config_key, None), arg_SubmitterSecurityGroupIds, args.prompt)
            except ValueError as e:
                logger.error(e)
                sys.exit(1)
            if checked_value:
                checked_value_json = json.dumps(checked_value)
                if args.prompt:
                    if args.SubmitterSecurityGroupIds:
                        if arg_json_value != checked_value_json:
                            for arg_index, arg_name in enumerate(cmdline_args):
                                if arg_name == f'--{config_key}':
                                    cmdline_args[arg_index + 1] = f"'{checked_value_json}'"
                    else:
                        prompt_args += [f'--{config_key}', f"'{checked_value_json}'"]
                self.config[config_key] = checked_value
                self.install_parameters[config_key] = base64.b64encode(checked_value_json.encode('utf-8')).decode('utf-8')
                logger.info(f"{config_key:30}: {self.config[config_key]}")
            else:
                while f'--{config_key}' in cmdline_args:
                    arg_index = cmdline_args.index(f'--{config_key}')
                    del cmdline_args[arg_index]
                    del cmdline_args[arg_index]

        self.install_parameters['config_file'] = args.config_file

        try:
            check_if_name_exist = cloudformation.describe_stacks(StackName=self.install_parameters["stack_name"])
            if len(check_if_name_exist["Stacks"]) != 0:
                if args.cdk_cmd == 'create':
                    logger.error(f"{fg('red')}{self.install_parameters['stack_name']} already exists in CloudFormation.{attr('reset')}")
                    sys.exit(1)
                elif args.cdk_cmd == 'deploy':
                    logger.error(f"{fg('red')}{self.install_parameters['stack_name']} already exists in CloudFormation. Use --cdk-cmd update if you want to update it.{attr('reset')}")
                    sys.exit(1)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ValidationError":
                if args.cdk_cmd == 'update':
                    logger.error(f"{fg('red')}{self.install_parameters['stack_name']} does not exist in CloudFormation so can't be updated. Use --cdk-cmd create if you want to create it.{attr('reset')}")
                    sys.exit(1)
                else:
                    # Stack does not exist so create it
                    pass
            else:
                logger.error(f"{fg('red')}Error checking if {self.install_parameters['stack_name']} already exists in CloudFormation due to {e}.{attr('reset')}")
                sys.exit(1)

        # Prepare CDK commands
        if args.cdk_cmd in ['create', 'update']:
            cdk_cmd = 'deploy'
        else:
            cdk_cmd = args.cdk_cmd
        cmd = f"cdk {cdk_cmd}"
        cmd += f" --strict"
        #cmd += f" --debug"
        cmd += f" -c {' -c '.join('{}={}'.format(key,val) for (key,val) in self.install_parameters.items() if val is not None)} --require-approval never"
        cmd_bootstrap = f"cdk bootstrap aws://{self.install_parameters['account_id']}/{region} -c {' -c '.join('{}={}'.format(key,val) for (key,val) in self.install_parameters.items() if val is not None)}"

        if args.debug:
            cmd += " --debug -v -v -v"

        if args.profile:
            cmd += f" --profile {args.profile}"
            cmd_bootstrap += f" --profile {args.profile}"

        logger.info(f"\nExecuting {cmd}")

        # Log command in history book
        with open("installer_history.txt", "a+") as f:
            f.write(f"\n[{datetime.datetime.utcnow()}] {cmd}")

        # First, Bootstrap the environment. This will create a staging S3 bucket if needed
        logger.info("\n====== Running CDK Bootstrap ======\n")

        bootstrap_environment = os.system(cmd_bootstrap) # nosec
        if int(bootstrap_environment) != 0:
            logger.error(f"{fg('red')}Unable to bootstrap environment. Please run {cmd_bootstrap} and fix any errors{attr('reset')}")
            logger.error(f"{fg('red')}{bootstrap_environment} {attr('reset')}")
            sys.exit(1)

        # Upload required assets to customer S3 account
        # if cdk_cmd == "deploy":
        #     upload_objects(install_directory, self.install_parameters['bucket'], self.install_parameters['stack_name'])

        # Then launch the actual SOCA installer
        logger.info("\n====== Deploying SLURM ======\n")
        launch_installer = os.system(cmd) # nosec
        if cdk_cmd == "deploy":
            if int(launch_installer) == 0:
                logger.info(f"{fg('green')}SLURM was successfully deployed!{attr('reset')}")
        elif args.cdk_cmd == "destroy":
            # Destroy stack if known
            cmd_destroy = f"cdk destroy {self.install_parameters['stack_name']} -c {' -c '.join('{}={}'.format(key, val) for (key, val) in self.install_parameters.items() if val is not None)} --require-approval never"
            logger.info(f"Deleting stack, running {cmd_destroy}")
            delete_stack = os.system(cmd_destroy) # nosec
        else:
            # synth, ls etc ..
            pass

        # Print out the command if --prompt was specified so they don't have to keep going through the prompts.
        if args.prompt:
            quoted_args = []
            for arg in sys.argv[1:]:
                if ' ' in arg:
                    quoted_args.append(f"'{arg}'")
                else:
                    quoted_args.append(arg)
            print(f"Original command:\n./install.sh {' '.join(quoted_args)}")
            # Delete --prompt arg
            while '--prompt' in cmdline_args:
                arg_index = cmdline_args.index('--prompt')
                del cmdline_args[arg_index]
            quoted_args = []
            for arg in cmdline_args + prompt_args:
                if ' ' in arg:
                    quoted_args.append(f"'{arg}'")
                else:
                    quoted_args.append(arg)
            if '--cdk-cmd' not in quoted_args:
                quoted_args.extend(['--cdk-cmd', 'synth'])
            new_cmd = f"./install.sh {' '.join(quoted_args)}"
            print(f"\nCommand line to update the stack without prompts:\n{new_cmd}")

    def get_config(self, config_file):
        default_config_file_path = realpath(f"{dirname(realpath(__file__))}/../resources/config/")
        config_file_path = config_file
        if config_file_path:
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
        else:
            config_file_path = f"{default_config_file_path}/default_config.yml"
            logger.info(f"Using default config: {config_file_path}")
        try:
            config_parameters = yaml.load(open(config_file_path, 'r'), Loader=yaml.FullLoader) # nosec
        except ScannerError as err:
            logger.error(f"{config_file_path} is not a valid YAML file. Verify syntax, {err}")
            sys.exit(1)
        except FileNotFoundError:
            logger.error(f"{config_file_path} not found")
            sys.exit(1)

        if not config_parameters:
            logger.error("No parameters were specified.")
            sys.exit(1)

        # Validate config against schema
        from config_schema import check_schema
        from schema import SchemaError
        try:
            validated_config = check_schema(config_parameters)
        except SchemaError as e:
            logger.error(f"Invalid config file: {config_file_path}\n{e}\nSee: {dirname(dirname(__file__))}/cdk/config_schema.py")
            sys.exit(1)

        return validated_config

def upload_objects(install_directory, bucket, stack_name):
    # Upload required assets to customer S3 bucket
    logger.info(f"\n====== Uploading install files to {bucket}/{stack_name} ======\n")
    dist_directory = f"{install_directory}/../../dist/{stack_name}/"
    if os.path.isdir(dist_directory):
        logger.info(f"{dist_directory} already exist. Creating a new one for your build")
        shutil.rmtree(dist_directory)
    os.makedirs(dist_directory)

    try:
        install_bucket = s3.Bucket(bucket)
        for path, subdirs, files in os.walk(f"{dist_directory}"):
            path = path.replace("\\", "/")
            directory = path.split("/")[-1]
            for file in files:
                if directory:
                    upload_location = f"{stack_name}/{directory}/{file}"
                else:
                    upload_location = f"{stack_name}/{file}"
                logger.info(f"{fg('green')}[+] Uploading {os.path.join(path, file)} to s3://{bucket}/{upload_location} {attr('reset')}")
                install_bucket.upload_file(os.path.join(path, file), upload_location)

    except Exception as upload_error:
        logger.info(f"{fg('red')} Error during upload {upload_error}{attr('reset')}")


if __name__ == "__main__":
    app = SlurmInstaller()
    app.main()
