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
Wait for AMI to be available and update SSM parameter
'''
import boto3
import json
import logging
from time import sleep

logging.getLogger().setLevel(logging.INFO)

def lambda_handler(event, context):
    try:
        logging.info(f"event: {event}")
        properties = event
        required_properties = ['ami-id', 'ssm-parameter', 'instance-id']
        error_message = ""
        for property in required_properties:
            try:
                value = properties[property]
            except:
                error_message += f"Missing {property} property. "
        if error_message:
            raise KeyError(error_message)
        ec2_client = boto3.client('ec2')
        ami_id = properties['ami-id']
        ssm_parameter_name = properties['ssm-parameter']
        logging.info(f"Waiting for {ami_id} to be available.")
        while True:
            state = ec2_client.describe_images(ImageIds=[ami_id])['Images'][0]['State']
            logging.info(f"state={state}")
            if state == 'available':
                break
            sleep(60)
        logging.info(f"Writing {ami_id} to {ssm_parameter_name}")
        ssm_client = boto3.client('ssm')
        ssm_client.put_parameter(Name=ssm_parameter_name, Type='String', Value=ami_id, Overwrite=True)
        logging.info(f"Stopping {properties['instance-id']}")
        ec2_client.stop_instances(InstanceIds=[properties['instance-id']])
    except Exception as e:
        logging.exception(str(e))
        return {
            'statusCode': 300,
            'body': json.dumps(f"error: {e}")
        }

    return {
        'statusCode': 200,
        'body': json.dumps(f"success")
    }
