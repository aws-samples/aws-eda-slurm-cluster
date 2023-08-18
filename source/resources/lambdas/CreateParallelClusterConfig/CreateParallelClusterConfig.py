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

def lambda_handler(event, context):
    try:
        logging.info(f"event:\n{json.dumps(event, indent=4)}")
        physical_resource_id = None
        requestType = event['RequestType']
        properties = event['ResourceProperties']
        required_properties = [
            'ParallelClusterConfigYaml',
            'S3Bucket',
            'S3Key',
            'S3ObjectUrl'
            ]
        error_message = ""
        for property in required_properties:
            try:
                value = properties[property]
            except:
                error_message += f"Missing {property} property. "
        if error_message:
            logging.info(error_message)
            if requestType == 'Delete':
                cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=physical_resource_id)
                return
            else:
                raise KeyError(error_message)

        physical_resource_id = properties['S3ObjectUrl']
        s3_resource = boto3.resource('s3')
        config_object = s3_resource.Object(
            bucket_name = properties['S3Bucket'],
            key = properties['S3Key']
        )
        if requestType == 'Delete':
            # Don't delete because if the custom resource is replaced and the new and old resoure point to the same object then it would be deleted.
            pass
            # logging.info(f"Deleting Parallel Cluster config in {properties['S3ObjectUrl']}")

            # config_object.delete(Body=properties['ParallelClusterConfigYaml'])
        else:
            logging.info(f"Saving Parallel Cluster config in {properties['S3ObjectUrl']}")

            config_object.put(Body=properties['ParallelClusterConfigYaml'])

    except Exception as e:
        logging.exception(str(e))
        if requestType != 'Delete':
            cfnresponse.send(event, context, cfnresponse.FAILED, {'error': str(e)}, physicalResourceId=physical_resource_id)
            raise

    cfnresponse.send(event, context, cfnresponse.SUCCESS, {'S3ObjectUrl': physical_resource_id}, physicalResourceId=physical_resource_id)
