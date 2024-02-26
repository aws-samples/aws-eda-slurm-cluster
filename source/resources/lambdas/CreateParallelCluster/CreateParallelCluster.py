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
Create/update/delete ParallelCluster cluster and save config to S3 as json and yaml.
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

def get_clusters(cluster_region):
    clusters = []
    list_clusters_kwargs = {'region': cluster_region}
    while list_clusters_kwargs:
        clusters_dict = pc.list_clusters(**list_clusters_kwargs)
        if 'nextToken' in clusters_dict:
            list_clusters_kwargs['next_token'] = clusters_dict['nextToken']
        else:
            list_clusters_kwargs = None
        for cluster in clusters_dict['clusters']:
            clusters.append(cluster)
    return clusters

def get_cluster_status(cluster_name, cluster_region):
    logger.info("Listing clusters to get cluster status")
    cluster_status = None
    for cluster_dict in get_clusters(cluster_region):
        if cluster_dict['clusterName'] != cluster_name:
            continue
        logger.info(f"cluster_dict:\n{json.dumps(cluster_dict, indent=4)}")
        cluster_status = cluster_dict['clusterStatus']
        cluster_cloudformation_status = cluster_dict['cloudformationStackStatus']
        logger.info(f"{cluster_name} exists. Status={cluster_status} and cloudformation status={cluster_cloudformation_status}")
        break
    return cluster_status

def lambda_handler(event, context):
    try:
        logger.info(f"event:\n{json.dumps(event, indent=4)}")
        cluster_name = None
        requestType = event['RequestType']
        properties = event['ResourceProperties']
        required_properties = [
            'ParallelClusterConfigHash'
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

        cluster_name = environ['ClusterName']
        cluster_region = environ['Region']
        logger.info(f"{requestType} request for {cluster_name} in {cluster_region}")

        cluster_status = get_cluster_status(cluster_name, cluster_region)
        if cluster_status:
            valid_statuses = ['CREATE_COMPLETE', 'UPDATE_COMPLETE', 'UPDATE_ROLLBACK_COMPLETE']
            invalid_statuses = ['CREATE_IN_PROGRESS', 'UPDATE_IN_PROGRESS', 'DELETE_IN_PROGRESS']
            if cluster_status in invalid_statuses:
                logger.error(f"{cluster_name} has invalid status: {cluster_status}")
                cfnresponse.send(event, context, cfnresponse.FAILED, {'error': f"{cluster_name} in {cluster_status} state."}, physicalResourceId=cluster_name)
                return
            if requestType == 'Create':
                logger.info(f"{cluster_name} exists so changing request type from Create to Update.")
                requestType = 'Update'
        else:
            if requestType == 'Delete':
                logger.info(f"{cluster_name} doesn't exist so nothing to do.")
                cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=cluster_name)
                return
            elif requestType == 'Update':
                logger.info(f"{cluster_name} doesn't exist so changing request type from Update to Create.")
                requestType = 'Create'
            else:
                logger.info(f"{cluster_name} doesn't exist.")

        yaml_key = f"{environ['ParallelClusterConfigYamlS3Key']}"
        yaml_s3_url = f"s3://{environ['ParallelClusterConfigS3Bucket']}/{yaml_key}"

        logger.info(f"Getting Parallel Cluster yaml config from {yaml_s3_url}")
        s3_client = boto3.client('s3')
        parallel_cluster_config_yaml = s3_client.get_object(
            Bucket = environ['ParallelClusterConfigS3Bucket'],
            Key = yaml_key
        )['Body'].read().decode('utf-8')

        parallel_cluster_config = yaml.load(parallel_cluster_config_yaml, Loader=yaml.FullLoader)
        logger.info(f"HeadNode config:\n{json.dumps(parallel_cluster_config['HeadNode'], indent=4)}")

        if requestType == "Create":
            logger.info(f"Creating {cluster_name}")
            try:
                response = pc.create_cluster(
                    cluster_name = cluster_name,
                    cluster_configuration = parallel_cluster_config,
                    region = cluster_region,
                    rollback_on_failure = False,
                    # suppress_validators doesn't work
                    # suppress_validators = 'ALL'
                    # # suppress_validators = 'type:SharedStorageMountDirValidator'
                    # # suppress_validators = [
                    # #     # 'ALL',
                    # #     'type:SharedStorageMountDirValidator',
                    # #     'type:InstancesEFAValidator'
                    # # ]
                )
                logger.info("Create call succeeded.")
                logger.info(f"response={response}")
            except:
                logger.exception("ParallelCluster create failed. Ignoring exception")
        elif requestType == "Update":
            logger.info("Checking compute fleet status.")
            compute_fleet_status = pc.describe_compute_fleet(
                cluster_name = cluster_name,
                region = cluster_region)['status']
            logger.info(f"compute fleet status: {compute_fleet_status}")

            logger.info(f"Updating {cluster_name}")
            stop_and_retry = False
            try:
                response = pc.update_cluster(
                    cluster_name = cluster_name,
                    cluster_configuration = parallel_cluster_config,
                    region = cluster_region,
                    # suppress_validators doesn't work
                    # suppress_validators = 'ALL'
                    # # suppress_validators = 'type:SharedStorageMountDirValidator'
                    # # suppress_validators = [
                    # #     # 'ALL',
                    # #     'type:SharedStorageMountDirValidator',
                    # #     'type:InstancesEFAValidator'
                    # # ]
                )
                logger.info("Update call succeeded")
                logger.info(f"response={response}")
            except BadRequestException as e:
                message = e.content.message
                if 'No changes found in your cluster configuration' in message:
                    logger.info('No changes found in your cluster configuration.')
                else:
                    logger.error(message)

            except UpdateClusterBadRequestException as e:
                message = e.content.message
                logger.info(message)
                logger.info(f"{e.content.__dict__}")
                if 'All compute nodes must be stopped' in str(e.content.__dict__):
                    stop_and_retry = True
                else:
                    logger.error(f"{message}")

            if stop_and_retry:
                logger.info(f"Stopping the cluster and retrying the update.")
                try:
                    pc.update_compute_fleet(
                        cluster_name = cluster_name,
                        status = 'STOP_REQUESTED',
                        region = cluster_region
                    )
                except BadRequestException as e:
                    message = e.content.message
                    logger.error(e.content)
                    logger.error(e.content.message)
                    raise
                except Exception as e:
                    logger.exception("update_compute_fleet failed")
                    logger.error(f"{type(e)} {e.__dict__}")
                    raise
                logger.info(f"Stop requested. Waiting for cluster to be STOPPED.")
                while compute_fleet_status != 'STOPPED':
                    compute_fleet_status = pc.describe_compute_fleet(
                        cluster_name = cluster_name,
                        region = cluster_region)['status']
                    logger.info(f"compute fleet status: {compute_fleet_status}")
                    sleep(1)
                logger.info("Compute fleet is stopped. Retrying update.")
                try:
                    pc.update_cluster(
                        cluster_name = cluster_name,
                        cluster_configuration = parallel_cluster_config,
                        region = cluster_region,
                        # suppress_validators doesn't work
                        # suppress_validators = 'ALL'
                    )
                    logger.info("Update call succeeded")
                    logger.info(f"response={response}")
                except (BadRequestException, UpdateClusterBadRequestException) as e:
                    message = e.content.message
                    logger.error(message)
                    logger.error(f"{e.content.__dict__}")
                except Exception as e:
                    logger.exception("ParallelCluster Update failed.")

        elif requestType == 'Delete':
            logger.info(f"Deleting {cluster_name}")
            try:
                pc.delete_cluster(
                    cluster_name = cluster_name,
                    region = cluster_region
                )
                logger.info("Delete call succeeded")
            except:
                logger.exception("ParallelCluster Delete failed. Ignoring exception")
            # Wait for the delete to succeed or fail so that cluster resources can be deleted.
            # For example, cannot delete the head node security group until the head node has been deleted.
            while cluster_status:
                logger.info(f"Waiting for {cluster_name} to be deleted. Status={cluster_status}")
                sleep(60)
                cluster_status = get_cluster_status(cluster_name, cluster_region)
                if not cluster_status:
                    logger.info(f"{cluster_name} doesn't exist so delete complete.")
                    break
                if cluster_status == 'DELETE_FAILED':
                    logger.info(f"{cluster_name} delete failed")
                    cfnresponse.send(event, context, cfnresponse.FAILED, {'error': f"{cluster_name} in {cluster_status} state."}, physicalResourceId=cluster_name)
                    return
        else:
            raise ValueError(f"Unsupported requestType: {requestType}")

    except Exception as e:
        logger.exception(str(e))
        cfnresponse.send(event, context, cfnresponse.FAILED, {'error': str(e)}, physicalResourceId=cluster_name)
        sns_client = boto3.client('sns')
        sns_client.publish(
            TopicArn = environ['ErrorSnsTopicArn'],
            Subject = f"{cluster_name} CreateParallelCluster failed",
            Message = str(e)
        )
        logger.info(f"Published error to {environ['ErrorSnsTopicArn']}")
        raise

    cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=cluster_name)
