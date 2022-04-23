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
Create/delete DNS entry
'''
import cfnresponse
import boto3
import logging
logging.getLogger().setLevel(logging.INFO)

def lambda_handler(event, context):
    try:
        logging.info("event: {}".format(event))
        properties = event['ResourceProperties']
        required_properties = ['Hostname', 'Domain', 'HostedZoneId', 'Type', 'Value']
        error_message = ""
        for property in required_properties:
            try:
                value = properties[property]
            except:
                error_message += "Missing {} property. ".format(property)
        if error_message:
            raise KeyError(error_message)
        route53_client = boto3.client('route53')
        requestType = event['RequestType']
        if requestType in ['Create', 'Update']:
            action = 'UPSERT'
        elif requestType == 'Delete':
            action = 'DELETE'
        else:
            raise ValueError('Invalid RequestType: {}'.format(event['RequestType']))
        hostname = properties['Hostname']
        domain = properties['Domain']
        type = properties['Type']
        value = properties['Value']
        logging.info("{} {}.{} {} record, value=".format(action, hostname, type, value))
        route53_client.change_resource_record_sets(
            HostedZoneId=properties['HostedZoneId'],
            ChangeBatch={
                'Comment': '{} {} DNS record'.format(action, hostname),
                'Changes': [
                    {
                        'Action': action,
                        'ResourceRecordSet': {
                            'Name': "{}.{}".format(hostname, domain),
                            'Type': type,
                            'TTL': 60,
                            'ResourceRecords': [{'Value': value}]
                        }
                    }
                ]
            }
        )
    except Exception as e:
        logging.exception(str(e))
        cfnresponse.send(event, context, cfnresponse.FAILED, {'error': str(e)}, str(e))
        raise

    cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, "{} {}.{} {}".format(properties['Type'], properties['Hostname'], properties['Domain'], properties['Value']))
