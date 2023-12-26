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
Create/delete route53 zone in another region.
'''

import boto3
import cfnresponse
import logging

logging.getLogger().setLevel(logging.INFO)

def lambda_handler(event, context):
    try:
        logging.info(f"event:\n{json.dumps(event, indent=4)}")
        properties = event['ResourceProperties']
        required_properties = ['HostedZoneId', 'VpcId', 'VpcRegion']
        error_message = ""
        for property in required_properties:
            try:
                value = properties[property]
            except:
                error_message += "Missing {} property. ".format(property)
        if error_message:
            raise KeyError(error_message)

        requestType = event['RequestType']

        route53_client = boto3.client('route53')

        if requestType in ['Update', 'Delete']:
            try:
                route53_client.disassociate_vpc_from_hosted_zone(
                    HostedZoneId = properties['HostedZoneId'],
                    VPC = {
                        'VPCRegion': properties['VpcRegion'],
                        'VPCId': properties['VpcId'],
                    },
                    HostedZoneConfig = {'PrivateZone': True}
                )
            except:
                pass

        if requestType in ['Create', 'Update']:
            route53_client.associate_vpc_with_hosted_zone(
                HostedZoneId = properties['HostedZoneId'],
                VPC = {
                    'VPCRegion': properties['VpcRegion'],
                    'VPCId': properties['VpcId'],
                },
                HostedZoneConfig = {'PrivateZone': True}
            )

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

    cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, "")
