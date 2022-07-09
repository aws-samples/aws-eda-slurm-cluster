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
Do DNS lookup and return the IP address.
'''
import cfnresponse
import json
import logging
from socket import getaddrinfo, SOCK_STREAM

logging.getLogger().setLevel(logging.INFO)

def lambda_handler(event, context):
    try:
        logging.info(f"event:\n{json.dumps(event, indent=4)}")
        properties = event['ResourceProperties']
        required_properties = ['FQDN']
        error_message = ""
        for property in required_properties:
            try:
                value = properties[property]
            except:
                error_message += f"Missing {property} property. "
        if error_message:
            raise KeyError(error_message)

        requestType = event['RequestType']
        if requestType == 'Delete':
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, "")
            return

        fqdn = properties['FQDN']
        ip_address_tuples = getaddrinfo(host=fqdn, port=None, type=SOCK_STREAM)
        logging.info(f"Found {len(ip_address_tuples)} ip addresses")
        for ip_address_tuple in ip_address_tuples:
            logging.info(f"ip_address_tuple: {ip_address_tuple}")
        ip_address = ip_address_tuples[0][4][0]
        logging.info(f"ip_address: {ip_address}")

    except Exception as e:
        logging.exception(str(e))
        cfnresponse.send(event, context, cfnresponse.FAILED, {'error': str(e)}, str(e))
        raise

    cfnresponse.send(event, context, cfnresponse.SUCCESS, {'IpAddress': ip_address}, f"{ip_address}")
