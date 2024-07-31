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
Create/update/delete ParallelCluster AMI build configuration files and store them in S3.

Don't fail if can't create build-files so that cluster can successfully deploy.
'''
import boto3
import cfnresponse
from jinja2 import Template as Template
import json
import logging
from os import environ as environ
import pcluster.lib as pc
from pcluster.api.errors import BadRequestException, UpdateClusterBadRequestException
from time import sleep
import yaml

logger=logging.getLogger(__file__)
logger_formatter = logging.Formatter('%(levelname)s: %(message)s')
logger_streamHandler = logging.StreamHandler()
logger_streamHandler.setFormatter(logger_formatter)
logger.addHandler(logger_streamHandler)
logger.setLevel(logging.INFO)
logger.propagate = False

ec2_client = boto3.client('ec2')

def get_image_builder_parent_image(distribution, version, architecture, parallelcluster_version):
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
        filters.extend(
            [
                {'Name': 'owner-alias', 'Values': ['amazon']},
                {'Name': 'name', 'Values': [f"aws-parallelcluster-{parallelcluster_version}-{distribution}{version}*"]},
            ],
        )
    response = ec2_client.describe_images(
        Filters = filters
    )
    logger.debug(f"Images:\n{json.dumps(response['Images'], indent=4)}")
    images = sorted(response['Images'], key=lambda image: image['CreationDate'], reverse=True)
    if not images:
        return None
    image_id = images[0]['ImageId']
    return image_id

def get_fpga_developer_image(distribution, version, architecture):
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
    response = ec2_client.describe_images(
        Filters = filters
    )
    logger.debug(f"Images:\n{json.dumps(response['Images'], indent=4)}")
    images = sorted(response['Images'], key=lambda image: image['CreationDate'], reverse=True)
    if not images:
        return None
    image_id = images[0]['ImageId']
    return image_id

def get_ami_root_volume_size(image_id: str):
    response = ec2_client.describe_images(
        ImageIds = [image_id]
    )
    logger.debug(f"{json.dumps(response, indent=4)}")
    root_volume_size = response['Images'][0]['BlockDeviceMappings'][0]['Ebs']['VolumeSize']
    return root_volume_size

def lambda_handler(event, context):
    try:
        logger.info(f"event:\n{json.dumps(event, indent=4)}")
        cluster_name = None
        requestType = event['RequestType']
        properties = event['ResourceProperties']
        required_properties = [
            ]
        error_message = ""
        for property in required_properties:
            try:
                value = properties[property]
            except:
                error_message += f"Missing {property} property. "
        if error_message:
            logger.info(error_message)
            if requestType == 'Delete':
                cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=cluster_name)
                return
            else:
                raise KeyError(error_message)

        ami_builds = json.loads(environ['AmiBuildsJson'])
        assets_bucket = environ['AssetsBucket']
        assets_base_key = environ['AssetsBaseKey']
        cluster_name = environ['ClusterName']
        cluster_region = environ['Region']
        parallelcluster_version = environ['ParallelClusterVersion']

        parallelcluster_version_name = parallelcluster_version.replace('.', '-')

        template_vars = {
            'AssetReadPolicyArn': environ['AssetReadPolicyArn'],
            'ComponentS3Url': None,
            'ImageBuilderSecurityGroupId': environ['ImageBuilderSecurityGroupId'],
            'ImageName': None,
            'InstanceType': None,
            'ParentImage': None,
            'RootVolumeSize': None,
            'SubnetId': environ['SubnetId'],
        }

        s3_client = boto3.client('s3', region_name=cluster_region)

        build_file_template_s3_key = f"{assets_base_key}/config/build-files/build-file-template.yml"
        if requestType == 'Delete':
            response = s3_client.delete_object(
                Bucket = assets_bucket,
                Key    = build_file_template_s3_key
            )
        else:
            # Get build file template from S3
            response = s3_client.get_object(
                Bucket = assets_bucket,
                Key    = build_file_template_s3_key
            )
            build_file_template_content = response['Body'].read().decode('utf-8')
            build_file_template = Template(build_file_template_content)

        error_count = 0
        error_messages = []
        for distribution in ami_builds:
            for version in ami_builds[distribution]:
                for architecture in ami_builds[distribution][version]:
                    if architecture == 'arm64':
                        template_vars['InstanceType'] = 'c6g.2xlarge'
                    else:
                        template_vars['InstanceType'] = 'c6i.2xlarge'
                    template_vars['ParentImage'] = get_image_builder_parent_image(distribution, version, architecture, parallelcluster_version)
                    if not template_vars['ParentImage']:
                        error_count += 1
                        error_message = f"No parent AMI found for {distribution} {version} {architecture}"
                        logger.error(error_message)
                        error_messages.append(error_message)
                        continue
                    template_vars['RootVolumeSize'] = int(get_ami_root_volume_size(template_vars['ParentImage'])) + 10
                    logger.info(f"{distribution}-{version}-{architecture} image id: {template_vars['ParentImage']} root volume size={template_vars['RootVolumeSize']}")

                    # Base image without EDA packages
                    template_vars['ImageName'] = f"parallelcluster-{parallelcluster_version_name}-{distribution}-{version}-{architecture}".replace('_', '-')
                    logger.info(f"Creating build config file for {template_vars['ImageName']}")
                    template_vars['ComponentS3Url'] = None
                    build_file_s3_key = f"{assets_base_key}/config/build-files/{template_vars['ImageName']}.yml"
                    if requestType == 'Delete':
                        response = s3_client.delete_object(
                            Bucket = assets_bucket,
                            Key    = build_file_s3_key
                        )
                    else:
                        build_file_content = build_file_template.render(**template_vars)
                        s3_client.put_object(
                            Bucket = assets_bucket,
                            Key    = build_file_s3_key,
                            Body   = build_file_content
                        )

                    # Image with EDA packages
                    template_vars['ImageName'] = f"parallelcluster-{parallelcluster_version_name}-eda-{distribution}-{version}-{architecture}".replace('_', '-')
                    template_vars['ComponentS3Url'] = environ['ConfigureEdaScriptS3Url']
                    build_file_s3_key = f"{assets_base_key}/config/build-files/{template_vars['ImageName']}.yml"
                    if requestType == 'Delete':
                        response = s3_client.delete_object(
                            Bucket = assets_bucket,
                            Key    = build_file_s3_key
                        )
                    else:
                        build_file_content = build_file_template.render(**template_vars)
                        s3_client.put_object(
                            Bucket = assets_bucket,
                            Key    = build_file_s3_key,
                            Body   = build_file_content
                        )

                    template_vars['ParentImage'] = get_fpga_developer_image(distribution, version, architecture)
                    if not template_vars['ParentImage']:
                        logger.info(f"No FPGA Developer AMI found for {distribution}{version} {architecture}")
                        continue
                    template_vars['ImageName'] = f"parallelcluster-{parallelcluster_version_name}-fpga-{distribution}-{version}-{architecture}".replace('_', '-')
                    template_vars['RootVolumeSize'] = int(get_ami_root_volume_size(template_vars['ParentImage'])) + 10
                    logger.info(f"{distribution}-{version}-{architecture} fpga developer image id: {template_vars['ParentImage']} root volume size={template_vars['RootVolumeSize']}")
                    build_file_s3_key = f"{assets_base_key}/config/build-files/{template_vars['ImageName']}.yml"
                    if requestType == 'Delete':
                        response = s3_client.delete_object(
                            Bucket = assets_bucket,
                            Key    = build_file_s3_key
                        )
                    else:
                        build_file_content = build_file_template.render(**template_vars)
                        s3_client.put_object(
                            Bucket = assets_bucket,
                            Key    = build_file_s3_key,
                            Body   = build_file_content
                        )

        if error_count:
            message = f"Errors occurred when creating build config files."
            for error_message in error_messages:
                message += f"\n{error_message}"
            raise RuntimeError(message)

    except Exception as e:
        logger.exception(str(e))
        cfnresponse.send(event, context, cfnresponse.SUCCESS, {'error': str(e)}, physicalResourceId=cluster_name)
        sns_client = boto3.client('sns')
        sns_client.publish(
            TopicArn = environ['ErrorSnsTopicArn'],
            Subject = f"{cluster_name} CreateBuildFiles failed",
            Message = str(e)
        )
        logger.info(f"Published error to {environ['ErrorSnsTopicArn']}")
        return

    cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=cluster_name)
