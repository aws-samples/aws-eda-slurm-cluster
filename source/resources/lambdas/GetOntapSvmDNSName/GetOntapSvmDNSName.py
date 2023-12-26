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
Configure the Ontap file system
'''
import cfnresponse
import boto3
import logging
from time import sleep

logging.getLogger().setLevel(logging.INFO)

def lambda_handler(event, context):
    try:
        logging.info("event: {}".format(event))
        requestType = event['RequestType']
        if requestType == 'Delete':
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, "")
            return

        properties = event['ResourceProperties']
        required_properties = ['SvmId']
        error_message = ""
        for property in required_properties:
            try:
                value = properties[property]
            except:
                error_message += "Missing {} property. ".format(property)
        if error_message:
            raise KeyError(error_message)

        fsx_client = boto3.client('fsx')
        response = fsx_client.describe_storage_virtual_machines(StorageVirtualMachineIds=[properties['SvmId']])['StorageVirtualMachines'][0]
        dns_name = response['Endpoints']['Nfs']['DNSName']
        logging.info(f"DNSName={dns_name}")

        logging.info('Success')

    except Exception as e:
        logging.exception(str(e))
        cfnresponse.send(event, context, cfnresponse.FAILED, {'error': str(e)}, str(e))
        sns_client = boto3.client('sns')
        sns_client.publish(
            TopicArn = environ['ErrorSnsTopicArn'],
            Subject = f"{cluster_name} CreateHeadNodeARecord failed",
            Message = str(e)
        )
        logger.info(f"Published error to {environ['ErrorSnsTopicArn']}")
        raise

    cfnresponse.send(event, context, cfnresponse.SUCCESS, {'DNSName': dns_name}, f"{dns_name}")
