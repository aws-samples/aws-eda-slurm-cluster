#!/usr/bin/env python3
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
# Get RedHat AMIs
# See https://access.redhat.com/solutions/15356
'''
import argparse
import boto3
import logging
from pprint import PrettyPrinter

logger = logging.getLogger(__file__)

pp = PrettyPrinter()

distributions_dict = {
    'AlmaLinux': {
        # x86_64: https://aws.amazon.com/marketplace/pp/prodview-mku4y3g4sjrye
        # arm_64: https://aws.amazon.com/marketplace/pp/prodview-zgsymdwitnxmm
        'owner': '679593333241',
        'major_versions': ['8'],
        'name_filter': 'AlmaLinux OS {distribution_major_version}*',
    },
    'Amazon': {
        'owner': '137112412989',
        'major_versions': ['2'],
        'name_filter': 'amzn{distribution_major_version}-ami-hvm-2.*'
    },
    'CentOS': {
        'owner': '125523088429',
        'major_versions': ['7', '8'],
        'name_filter': 'CentOS {distribution_major_version}*'
    },
    'RedHat': {
        'owner': '309956199498',
        'major_versions': ['7', '8'],
        'name_filter': 'RHEL-{distribution_major_version}*'
    },
    'Rocky': {
        # x86_64: https://aws.amazon.com/marketplace/pp/prodview-2otariyxb3mqu
        # arm_64: https://aws.amazon.com/marketplace/pp/prodview-uzg6o44ep3ugw
        'owner': '679593333241',
        'major_versions': ['8'],
        'name_filter': 'Rocky Linux {distribution_major_version}*'
    },
}

def main(filename, region, distribution):
    ec2_client = boto3.client("ec2", region_name='us-east-1')

    # Get list of regions
    if region:
        regions = [region]
    else:
        regions = []
        for region_dict in ec2_client.describe_regions()['Regions']:
            region_name = region_dict['RegionName']
            regions.append(region_name)

    if distribution:
        distributions = [distribution]
    else:
        distributions = distributions_dict.keys()
    ami_map = {}
    for region in sorted(regions):
        logger.debug(f"region: {region}")
        ami_map[region] = {}
        ec2_client = boto3.client('ec2', region_name=region)

        for distribution in distributions:
            logger.debug(f"distribution: {distribution}")
            ami_map[region][distribution] = {}
            for distribution_major_version in distributions_dict[distribution]['major_versions']:
                logger.debug(f"distribution_major_version: {distribution_major_version}")
                ami_map[region][distribution][distribution_major_version] = {}
                name_filter = distributions_dict[distribution]['name_filter'].format(distribution_major_version=distribution_major_version)
                logger.debug(f"name_filter: {name_filter}")
                kwargs = {
                    'Owners': [distributions_dict[distribution]['owner']],
                    'Filters': [
                        {'Name': 'name', 'Values': [name_filter]},
                        {'Name': 'state', 'Values': ['available']}
                    ]
                }
                images = ec2_client.describe_images(**kwargs).get('Images', None)
                logger.debug(f"Found {len(images)} images")
                for image in images:
                    if 'BETA' in image['Name']:
                        continue
                    architecture = image['Architecture']
                    if architecture not in ami_map[region][distribution][distribution_major_version]:
                        ami_map[region][distribution][distribution_major_version][architecture] = image
                    else:
                        if image['Name'] > ami_map[region][distribution][distribution_major_version][architecture]['Name']:
                            ami_map[region][distribution][distribution_major_version][architecture] = image
                if architecture not in ami_map[region][distribution][distribution_major_version]:
                    del ami_map[region][distribution][distribution_major_version]
            if not ami_map[region][distribution]:
                del ami_map[region][distribution]
        if not ami_map[region]:
            del ami_map[region]

    logger.debug(pp.pformat(ami_map))

    fh = open(filename, 'w')
    print("AmiMap:", file=fh)
    for region in sorted(ami_map.keys()):
        print(f"  {region}:", file=fh)
        for distribution in sorted(ami_map[region].keys()):
            print(f"    {distribution}:", file=fh)
            for distribution_major_version in sorted(ami_map[region][distribution].keys()):
                print(f"      {distribution_major_version}:", file=fh)
                for architecture in sorted(ami_map[region][distribution][distribution_major_version].keys()):
                    image_id = ami_map[region][distribution][distribution_major_version][architecture]['ImageId']
                    name = ami_map[region][distribution][distribution_major_version][architecture]['Name']
                    root_device_name = ami_map[region][distribution][distribution_major_version][architecture]['RootDeviceName']
                    architecture_key = f"{architecture}:"
                    print(f"        {architecture}:", file=fh)
                    print(f"          ImageId: {image_id} # {name}", file=fh)
                    print(f"          RootDeviceName: {root_device_name}", file=fh)
    fh.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser("Create AMI map")
    parser.add_argument('-o', dest='filename', action='store', default='source/resources/config/ami_map.yml', help="output filename")
    parser.add_argument('--region', action='store', default='', help="Region. Use for debug. Default is all AWS regions.")
    parser.add_argument('--distribution', action='store', default='', help="Distribution. Use for debug.")
    parser.add_argument('--debug', '-d', action='count', default=False, help="Enable debug messages")
    args = parser.parse_args()

    logger_formatter = logging.Formatter('%(levelname)s:%(asctime)s: %(message)s')
    logger_streamHandler = logging.StreamHandler()
    logger_streamHandler.setFormatter(logger_formatter)
    logger.addHandler(logger_streamHandler)
    logger.setLevel(logging.INFO)
    if args.debug:
        logger.setLevel(logging.DEBUG)

    main(args.filename, args.region, args.distribution)
