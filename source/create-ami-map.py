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
import csv
import json
import logging
from os import system
from pprint import PrettyPrinter

logger = logging.getLogger(__file__)

pp = PrettyPrinter()

distributions_dict = {
    'AlmaLinux': {
        'major_versions': ['8'],
        # https://wiki.almalinux.org/cloud/AWS.html#aws-marketplace
        'csv': 'https://wiki.almalinux.org/ci-data/aws_amis.csv'
        # 'owner': '764336703387',
        # 'name_filter': 'AlmaLinux OS {distribution_major_version}.*',
        # 'product_codes': [
        #     'be714bpjscoj5uvqz0of5mscl', # x86_64: https://aws.amazon.com/marketplace/pp/prodview-mku4y3g4sjrye
        #     '6vto7uou7jjh4um1mwoy8ov0s', # arm_64: https://aws.amazon.com/marketplace/pp/prodview-zgsymdwitnxmm
        # ]
    },
    'Amazon': {
        'owner': '137112412989',
        'major_versions': ['2'],
        #'name_filter': 'amzn{distribution_major_version}-ami-hvm-2*'
        #'name_filter': 'amzn{distribution_major_version}-ami-kernel-5.10-hvm-*'
        'ssm-parameters': {
            '2': {
                'arm64':  ['/aws/service/ami-amazon-linux-latest/amzn2-ami-hvm-arm64-gp2'],
                'x86_64': ['/aws/service/ami-amazon-linux-latest/amzn2-ami-hvm-x86_64-gp2']
            }
        }
    },
    'CentOS': {
        # https://wiki.centos.org/Cloud/AWS
        'owner': '125523088429',
        'major_versions': ['7'],
        'name_filter': 'CentOS Linux {distribution_major_version} *',
    },
    'RedHat': {
        'owner': '309956199498',
        'major_versions': ['7', '8'],
        'name_filter': 'RHEL-{distribution_major_version}*'
    },
    'Rocky': {
        'owner': '679593333241',
        'major_versions': ['8'],
        'product_codes': [
            'cotnnspjrsi38lfn8qo4ibnnm', # x86_64: https://aws.amazon.com/marketplace/pp/prodview-2otariyxb3mqu
            '7tvwi95pv43herd5jg0bs6cu5', # arm_64: https://aws.amazon.com/marketplace/pp/prodview-uzg6o44ep3ugw
        ]
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
    for distribution in distributions:
        if 'csv' not in distributions_dict[distribution]:
            continue
        csv_filename = f"/tmp/{distribution}-aws-amis.csv"
        system(f"rm -f {csv_filename}")
        rc = system(f"wget {distributions_dict[distribution]['csv']} -o /dev/null -O {csv_filename}")
        assert rc == 0
        csv_reader_fh = open(csv_filename, 'r')
        csv_reader = csv.reader(csv_reader_fh, dialect='excel')
        while True:
            try:
                (os, version, region, ami_id, architecture) = next(csv_reader)
                distribution_major_version = version.split(r'.')[0]
                if distribution_major_version not in distributions_dict[distribution]['major_versions']:
                    continue
                name = f"{os} {version} {architecture}"
                # Make sure that AMI exists
                ec2_client = boto3.client('ec2', region_name=region)
                try:
                    image_dict = ec2_client.describe_images(ImageIds=[ami_id]).get('Images', None)[0]
                except:
                    logger.warning(f"{ami_id} ({name}) not found in {region}")
                    continue
                if region not in ami_map:
                    ami_map[region] = {}
                if distribution not in ami_map[region]:
                    ami_map[region][distribution] = {}
                if distribution_major_version not in ami_map[region][distribution]:
                    ami_map[region][distribution][distribution_major_version] = {}
                if architecture == 'aarch64':
                    architecture = 'arm64'
                ami_map[region][distribution][distribution_major_version][architecture] = {
                    'ImageId': ami_id,
                    'Name': image_dict['Name'],
                    'RootDeviceName': image_dict['RootDeviceName']
                }
            except StopIteration:
                break
    for region in sorted(regions):
        logger.debug(f"region: {region}")
        if region not in ami_map:
            ami_map[region] = {}
        ec2_client = boto3.client('ec2', region_name=region)

        for distribution in distributions:
            if 'csv' in distributions_dict[distribution]:
                continue
            logger.debug(f"distribution: {distribution}")
            ami_map[region][distribution] = {}
            for distribution_major_version in distributions_dict[distribution]['major_versions']:
                logger.debug(f"distribution_major_version: {distribution_major_version}")
                if 'ssm-parameters' in distributions_dict[distribution]:
                    ssm_client = boto3.client('ssm', region_name=region)
                    image_id = None
                    for architecture in distributions_dict[distribution]['ssm-parameters'][distribution_major_version]:
                        for ssm_parameter in distributions_dict[distribution]['ssm-parameters'][distribution_major_version][architecture]:
                            image_id = ssm_client.get_parameter(Name=ssm_parameter)['Parameter']['Value']
                            try:
                                image_dict = ec2_client.describe_images(ImageIds=[image_id]).get('Images', None)[0]
                            except:
                                logger.warning(f"{image_id} ({ssm_parameter}) not found in {region}")
                                continue
                            if distribution not in ami_map[region]:
                                ami_map[region][distribution] = {}
                            if distribution_major_version not in ami_map[region][distribution]:
                                ami_map[region][distribution][distribution_major_version] = {}
                            ami_map[region][distribution][distribution_major_version][architecture] = {
                                'ImageId': image_id,
                                'Name': image_dict['Name'],
                                'RootDeviceName': image_dict['RootDeviceName']
                            }
                    continue
                kwargs = {
                    'Owners': [distributions_dict[distribution]['owner']],
                    'Filters': [
                        {'Name': 'state', 'Values': ['available']}
                    ]
                }
                if 'name_filter' in distributions_dict[distribution]:
                    name_filter = distributions_dict[distribution]['name_filter'].format(distribution_major_version=distribution_major_version)
                    logger.debug(f"name_filter: {name_filter}")
                    filter = {
                        'Name': 'name',
                        'Values': [name_filter]
                    }
                    kwargs['Filters'].append(filter)
                if 'product_codes' in distributions_dict[distribution]:
                    product_codes = distributions_dict[distribution]['product_codes']
                    logger.debug(f'product_codes: {product_codes}')
                    filter = {
                        'Name': 'product-code',
                        'Values': product_codes
                    }
                    kwargs['Filters'].append(filter)
                images = ec2_client.describe_images(**kwargs).get('Images', None)
                if not images:
                    logger.warning(f"No images found in {region} for {distribution} {distribution_major_version}")
                    continue
                logger.debug(f"Found {len(images)} images:\n{json.dumps(images, indent=4)}")
                ami_map[region][distribution][distribution_major_version] = {}
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

    logger.debug(f"ami_map:\n{json.dumps(ami_map, indent=4)}")

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
