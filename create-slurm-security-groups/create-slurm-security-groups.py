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
It's recommended to trigger this script via ../create-security-groups.sh as python's virtual env and all required
libraries/dependencies will be automatically installed.

If you run this script directly, make sure to have all the Python and CDK dependencies installed.
"""

import argparse
import boto3
from botocore.client import ClientError
from colored import fg, bg, attr
import logging
import os
import os.path
from os.path import dirname, realpath
import sys

script_path = os.path.dirname(os.path.abspath(__file__))
sys.path.append(script_path)

logger = logging.getLogger(__file__)
logger_formatter = logging.Formatter('%(levelname)s: %(message)s')
logger_streamHandler = logging.StreamHandler()
logger_streamHandler.setFormatter(logger_formatter)
logger.addHandler(logger_streamHandler)
logger.propagate = False
logger.setLevel(logging.INFO)

class CreateSlurmSecurityGroups():

    def __init__(self):
        self.stack_parameters = {}

    def main(self):
        parser = argparse.ArgumentParser(description="Create security groups for SLURM clusters.")
        parser.add_argument("--stack-name", type=str, required=True, help="CloudFormation stack name.")
        parser.add_argument("--region", "--Region", "-r", type=str, required=True, help="AWS region where you want to deploy your clusters.")
        parser.add_argument("--VpcId", type=str, required=True, help="Id of VPC to use")
        parser.add_argument("--slurmdbd-stack-name", type=str, help="Stack name that deployed external slurmdbd instance.")
        parser.add_argument("--slurmdbd-security-group-id", type=str, help="Id of security group attached to the slurmdbd instance.")
        parser.add_argument("--fsxl-security-group-id", type=str, help="Id of security group attached to FSx for Lustre file systems.")
        parser.add_argument("--fsxo-security-group-id", type=str, help="Id of security group attached to FSx for NetApp Ontap file systems.")
        parser.add_argument("--fsxz-security-group-id", type=str, help="Id of security group attached to FSx for OpenZfs file systems.")
        parser.add_argument("--cdk-cmd", type=str, choices=["deploy", "create", "update", "diff", "ls", "list", "synth", "synthesize", "destroy", "bootstrap"], default="create")
        parser.add_argument("--debug", action='store_const', const=True, default=False, help="Enable CDK debug mode")
        args = parser.parse_args()

        # Use script location as current working directory
        install_directory = os.path.dirname(os.path.realpath(f"{__file__}"))
        os.chdir(install_directory)
        logger.info(f"Working directory: {install_directory}")

        # Choose region
        # Must be passed to the stack.
        self.stack_parameters['region'] = args.region

        # Retrieve the AWS Account ID for CDK
        sts_client = boto3.client("sts", region_name=args.region)
        try:
            self.stack_parameters["account_id"] = sts_client.get_caller_identity()["Account"]
        except Exception as err:
            logger.error(f"{fg('red')}Unable to retrieve the Account ID due to {err}{attr('reset')}")
            sys.exit(1)

        self.stack_parameters['stack_name'] = args.stack_name

        self.stack_parameters['vpc_id'] = args.VpcId

        cfn_client = boto3.client("cloudformation", region_name=args.region)
        if args.slurmdbd_stack_name:
            slurmdbd_security_group_id = None
            try:
                stack_dict = cfn_client.describe_stacks(StackName=args.slurmdbd_stack_name)['Stacks'][0]
            except ClientError:
                logger.error(f"{args.slurmdbd_stack_name} stack not found.")
                exit(1)
            list_stack_resources_paginator = cfn_client.get_paginator('list_stack_resources')
            for stack_resource_summaries in list_stack_resources_paginator.paginate(StackName=args.slurmdbd_stack_name):
                for stack_resource_summary_dict in stack_resource_summaries['StackResourceSummaries']:
                    if stack_resource_summary_dict['LogicalResourceId'] == 'SlurmdbdServerSecurityGroup':
                        slurmdbd_security_group_id = stack_resource_summary_dict['PhysicalResourceId']
                        break
                if slurmdbd_security_group_id:
                    break
            if not slurmdbd_security_group_id:
                logger.error(f"SlurmdbdServerSecurityGroup resource not found in {args.slurmdbd_stack_name} stack.")
                exit(1)

        if args.slurmdbd_security_group_id:
            self.stack_parameters['slurmdbd_security_group_id'] = args.slurmdbd_security_group_id

        if args.fsxl_security_group_id:
            self.stack_parameters['fsxl_security_group_id'] = args.fsxl_security_group_id
        if args.fsxo_security_group_id:
            self.stack_parameters['fsxo_security_group_id'] = args.fsxo_security_group_id
        if args.fsxz_security_group_id:
            self.stack_parameters['fsxz_security_group_id'] = args.fsxz_security_group_id

        try:
            check_if_name_exist = cfn_client.describe_stacks(StackName=self.stack_parameters["stack_name"])
            if len(check_if_name_exist["Stacks"]) != 0:
                if args.cdk_cmd == 'create':
                    logger.error(f"{fg('red')}{self.stack_parameters['stack_name']} already exists in CloudFormation.{attr('reset')}")
                    sys.exit(1)
                elif args.cdk_cmd == 'deploy':
                    logger.error(f"{fg('red')}{self.stack_parameters['stack_name']} already exists in CloudFormation. Use --cdk-cmd update if you want to update it.{attr('reset')}")
                    sys.exit(1)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ValidationError":
                if args.cdk_cmd == 'update':
                    logger.error(f"{fg('red')}{self.stack_parameters['stack_name']} does not exist in CloudFormation so can't be updated. Use --cdk-cmd create if you want to create it.{attr('reset')}")
                    sys.exit(1)
                else:
                    # Stack does not exist so create it
                    pass
            else:
                logger.error(f"{fg('red')}Error checking if {self.stack_parameters['stack_name']} already exists in CloudFormation due to {e}.{attr('reset')}")
                sys.exit(1)

        # First, Bootstrap the environment. This will create a staging S3 bucket if needed
        bootstrap_cmd = f"cdk bootstrap 'aws://{self.stack_parameters['account_id']}/{args.region}' -c region={args.region} -c account_id={self.stack_parameters['account_id']}"
        logger.info("\n====== Running CDK Bootstrap ======\n")
        logger.info(f"cmd: {bootstrap_cmd}")
        bootstrap_rc = os.system(bootstrap_cmd) # nosec
        if int(bootstrap_rc) != 0:
            logger.error(f"{fg('red')}Unable to bootstrap environment. Please run {bootstrap_cmd} and fix any errors{attr('reset')}")
            logger.error(f"{fg('red')}{bootstrap_rc} {attr('reset')}")
            sys.exit(1)
        logger.info("Bootstrap succeeded")

        # Prepare CDK command
        if args.cdk_cmd in ['create', 'update']:
            cdk_cmd = 'deploy'
        else:
            cdk_cmd = args.cdk_cmd
        cmd = f"cdk {cdk_cmd}"
        cmd += f" --strict"
        cmd += f" -c {' -c '.join('{}={}'.format(key,val) for (key,val) in self.stack_parameters.items() if val is not None)} --require-approval never"

        if args.debug:
            cmd += " --debug -v -v -v"

        logger.info(f"\nExecuting {cmd}")
        os.system('pwd')

        # Then launch the actual CDK installer
        logger.info("\n====== Deploying Stack ======\n")
        launch_installer = os.system(cmd) # nosec
        if cdk_cmd == "deploy":
            if int(launch_installer) == 0:
                logger.info(f"{fg('green')}Stack was successfully deployed!{attr('reset')}")
        elif args.cdk_cmd == "destroy":
            # Destroy stack if known
            cmd_destroy = f"cdk destroy {self.stack_parameters['stack_name']} -c {' -c '.join('{}={}'.format(key, val) for (key, val) in self.stack_parameters.items() if val is not None)} --require-approval never"
            logger.info(f"Deleting stack, running {cmd_destroy}")
            delete_stack = os.system(cmd_destroy) # nosec
        else:
            # synth, ls etc ..
            pass

if __name__ == "__main__":
    app = CreateSlurmSecurityGroups()
    app.main()
