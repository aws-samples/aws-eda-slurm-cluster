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
Create/update/delete ParallelCluster cluster config file and save to S3 as json and yaml.
'''
import boto3
import cfnresponse
from hashlib import sha512
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

def lambda_handler(event, context):
    try:
        logger.info(f"event:\n{json.dumps(event, indent=4)}")
        cluster_name = environ.get('ClusterName', None)
        requestType = event['RequestType']
        properties = event['ResourceProperties']
        required_properties = [
            'ParallelClusterConfigTemplateYamlHash'
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

        s3_client = boto3.client('s3')

        yaml_template_key = environ['ParallelClusterConfigYamlTemplateS3Key']
        yaml_template_s3_url = f"s3://{environ['ParallelClusterConfigS3Bucket']}/{yaml_template_key}"

        yaml_key = f"{environ['ParallelClusterConfigYamlS3Key']}"
        yaml_s3_url = f"s3://{environ['ParallelClusterConfigS3Bucket']}/{yaml_key}"

        parallel_cluster_config_hash = sha512()

        if requestType == 'Delete':
            logger.info(f"Deleting Parallel Cluster yaml config template in {yaml_template_s3_url}")
            try:
                s3_client.delete_object(
                    Bucket = environ['ParallelClusterConfigS3Bucket'],
                    Key = yaml_template_key
                )
            except:
                pass

            logger.info(f"Deleting Parallel Cluster yaml config in {yaml_s3_url}")
            try:
                s3_client.delete_object(
                    Bucket = environ['ParallelClusterConfigS3Bucket'],
                    Key = yaml_key
                )
            except:
                pass
        else: # Create or Update
            logger.info(f"Deleting Parallel Cluster yaml config template from {yaml_template_s3_url}")
            parallel_cluster_config_yaml_template = Template(
                s3_client.get_object(
                    Bucket = environ['ParallelClusterConfigS3Bucket'],
                    Key = yaml_template_key
                )['Body'].read().decode('utf-8'))

            template_vars = {}
            for template_var in environ:
                template_vars[template_var] = environ[template_var]
            logger.info(f"template_vars:\n{json.dumps(template_vars, indent=4, sort_keys=True)}")
            parallel_cluster_config_yaml = parallel_cluster_config_yaml_template.render(**template_vars)

            parallel_cluster_config_hash.update(bytes(parallel_cluster_config_yaml, 'utf-8'))
            logger.info(f"Config hash: {parallel_cluster_config_hash.hexdigest()}")

            parallel_cluster_config = yaml.load(parallel_cluster_config_yaml, Loader=yaml.FullLoader)
            logger.info(f"HeadNode config:\n{json.dumps(parallel_cluster_config['HeadNode'], indent=4)}")

            logger.info(f"Saving Parallel Cluster yaml config in {yaml_s3_url}")
            s3_client.put_object(
                Bucket = environ['ParallelClusterConfigS3Bucket'],
                Key = yaml_key,
                Body = parallel_cluster_config_yaml
            )

    except Exception as e:
        logger.exception(str(e))
        cfnresponse.send(event, context, cfnresponse.FAILED, {'error': str(e)}, physicalResourceId=yaml_s3_url)
        sns_client = boto3.client('sns')
        sns_client.publish(
            TopicArn = environ['ErrorSnsTopicArn'],
            Subject = f"{cluster_name} CreateParallelClusterConfig failed",
            Message = str(e)
        )
        logger.info(f"Published error to {environ['ErrorSnsTopicArn']}")
        raise

    cfnresponse.send(event, context, cfnresponse.SUCCESS, {'ConfigTemplateYamlS3Url': yaml_template_s3_url, 'ConfigYamlS3Url': yaml_s3_url, 'ConfigYamlHash': parallel_cluster_config_hash.hexdigest()}, physicalResourceId=yaml_s3_url)
