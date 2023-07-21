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
Create/update/delete ParallelCluster cluster.
'''
import cfnresponse
import json
import logging
from os import environ as environ
import pcluster.lib as pc

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
        cluster_name = None
        requestType = event['RequestType']
        properties = event['ResourceProperties']
        required_properties = [
            'Region',
            'ClusterName',
            'ParallelClusterConfigJson',
            'ParallelClusterConfigS3Url'
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

        cluster_name = properties['ClusterName']
        cluster_region = properties['Region']
        logger.info(f"{requestType} request for {cluster_name} in {cluster_region}")

        logger.info("Listing clusters to get cluster status")
        clusters_dict = pc.list_clusters(region=cluster_region)
        logger.info(f"clusters_dict:\n{json.dumps(clusters_dict, indent=4)}")
        cluster_status = None
        for cluster_dict in clusters_dict['clusters']:
            if cluster_dict['clusterName'] != cluster_name:
                continue
            cluster_status = cluster_dict['clusterStatus']
            cluster_cloudformation_status = cluster_dict['cloudformationStackStatus']
            break
        if cluster_status:
            logger.info(f"{cluster_name} exists. Status={cluster_status} and cloudformation status={cluster_cloudformation_status}")
            valid_statuses = ['CREATE_COMPLETE', 'UPDATE_COMPLETE', 'UPDATE_ROLLBACK_COMPLETE']
            invalid_statuses = ['UPDATE_IN_PROGRESS', 'DELETE_IN_PROGRESS']
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

        if requestType == "Create":
            logger.info(f"Creating {properties['ClusterName']}")
            try:
                pc.create_cluster(
                    cluster_name = properties['ClusterName'],
                    cluster_configuration = properties['ParallelClusterConfigJson'],
                    region = properties['Region'],
                    rollback_on_failure = False,
                )
                logger.info("Create call succeeded.")
            except:
                logger.exception("ParallelCluster create failed. Ignoring exception")
        elif requestType == "Update":
            logger.info(f"Updating {properties['ClusterName']}")
            try:
                pc.update_cluster(
                    cluster_name = properties['ClusterName'],
                    cluster_configuration = properties['ParallelClusterConfigJson'],
                    region = properties['Region']
                )
                logger.info("Update call succeeded")
            except:
                logger.exception("ParallelCluster Update failed. Ignoring exception.")
        elif requestType == 'Delete':
            logger.info(f"Deleting {properties['ClusterName']}")
            try:
                pc.delete_cluster(
                    cluster_name = properties['ClusterName'],
                    region = properties['Region']
                )
                logger.info("Delete call succeeded")
            except:
                logger.exception("ParallelCluster Delete failed. Ignoring exception")
        else:
            raise ValueError(f"Unsupported requestType: {requestType}")

    except Exception as e:
        logger.exception(str(e))
        cfnresponse.send(event, context, cfnresponse.FAILED, {'error': str(e)}, physicalResourceId=cluster_name)
        raise

    cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=cluster_name)
