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

import boto3
from botocore.exceptions import ClientError
import csv
from datetime import datetime
import json
import logging
from logging import error, info, warning, handlers
import os
from os import environ, path
from pkg_resources import resource_filename
import pprint
from EC2InstanceTypeInfoPkg.retry_boto3_throttling import retry_boto3_throttling
import sys

logger = logging.getLogger(__file__)
logger_formatter = logging.Formatter('%(levelname)s:%(asctime)s: %(message)s')
logger_streamHandler = logging.StreamHandler()
logger_streamHandler.setFormatter(logger_formatter)
logger.addHandler(logger_streamHandler)
logger.setLevel(logging.INFO)
logger.propagate = False

pp = pprint.PrettyPrinter(indent=4)

class EC2InstanceTypeInfo:

    def __init__(self, regions, json_filename=None, debug=False):
        if debug:
            logger.setLevel(logging.DEBUG)

        if not regions:
            # Get a list of all AWS regions
            ec2_client = boto3.client('ec2')
            try:
                regions = sorted([region["RegionName"] for region in ec2_client.describe_regions()["Regions"]])
            except ClientError as err:
                logger.error(f"Unable to list all AWS regions. Make sure you have set your IAM credentials. {err}")
                sys.exit(1)
        self.regions = regions

        logger.info(f"Getting EC2 pricing info for following regions:\n{pp.pformat(self.regions)}")

        if json_filename:
            if path.exists(json_filename):
                logger.info(f"Reading cached info from {json_filename}")
                self.instance_type_info = json.loads(open(json_filename, 'r').read())
            else:
                logger.info(f"{json_filename} doesn't exist so cannot be read")
        if not json_filename or not path.exists(json_filename):
            self.instance_type_info = {}

        # Endpoints only supported in 2 regions: https://docs.aws.amazon.com/cli/latest/reference/pricing/index.html
        self.pricing_client = boto3.client('pricing', region_name='us-east-1')

        for region in self.regions:
            if region in self.instance_type_info and json_filename:
                logger.info(f'Using EC2 instance info from {json_filename} for {region}')
                continue
            region_name = self.get_region_name(region)
            logger.info(f'Getting EC2 instance info for {region} ({region_name})')
            self.ec2 = boto3.client('ec2', region_name=region)
            self.get_instance_type_info(region)

            # Save json after each successful region to speed up reruns
            if json_filename:
                logger.info(f"Saving instance type info for {region} in {json_filename}")
                fh = open(json_filename, 'w')
                print(json.dumps(self.instance_type_info, indent=4, sort_keys=True), file=fh)
                fh.close()

        return

    def get_instance_type_info(self, region):
        region_name = self.get_region_name(region)
        logger.debug(f"region_name={region_name}")
        instance_type_info = {}
        self.instance_type_info[region] = instance_type_info
        describe_instance_types_paginator = self.ec2.get_paginator('describe_instance_types')
        for result in describe_instance_types_paginator.paginate(**{'Filters': [{'Name': 'current-generation', 'Values': ['true']}]}):
            for instanceTypeDict in result['InstanceTypes']:
                #logger.debug(pp.pformat("instanceTypeDict:\n%s" % (pp.pformat(instanceTypeDict))))
                instanceType = instanceTypeDict['InstanceType']
                logger.debug(pp.pformat("instanceType: %s" % (instanceType)))
                instance_type_info[instanceType] = {}
                #instance_type_info[instanceType]['full'] = instanceTypeDict
                architecture = instanceTypeDict['ProcessorInfo']['SupportedArchitectures'][0]
                instance_type_info[instanceType]['architecture'] = architecture
                instance_type_info[instanceType]['SustainedClockSpeedInGhz'] = instanceTypeDict['ProcessorInfo']['SustainedClockSpeedInGhz']
                if 'ValidThreadsPerCore' in instanceTypeDict['VCpuInfo']:
                    instance_type_info[instanceType]['ThreadsPerCore'] = max(instanceTypeDict['VCpuInfo']['ValidThreadsPerCore'])
                else:
                    if architecture == 'x86_64':
                        instance_type_info[instanceType]['ThreadsPerCore'] = 2
                    else:
                        instance_type_info[instanceType]['ThreadsPerCore'] = 1
                if 'ValidCores' in instanceTypeDict['VCpuInfo']:
                    instance_type_info[instanceType]['CoreCount'] = int(max(instanceTypeDict['VCpuInfo']['ValidCores']))
                else:
                    instance_type_info[instanceType]['CoreCount'] = int(instanceTypeDict['VCpuInfo']['DefaultVCpus']/instance_type_info[instanceType]['ThreadsPerCore'])
                instance_type_info[instanceType]['MemoryInMiB'] = instanceTypeDict['MemoryInfo']['SizeInMiB']
                instance_type_info[instanceType]['SSDCount'] = instanceTypeDict.get('InstanceStorageInfo', {'Disks': [{'Count': 0}]})['Disks'][0]['Count']
                instance_type_info[instanceType]['SSDTotalSizeGB'] = instanceTypeDict.get('InstanceStorageInfo', {'TotalSizeInGB': 0})['TotalSizeInGB']
                instance_type_info[instanceType]['Hypervisor'] = instanceTypeDict.get('Hypervisor', '')
                instance_type_info[instanceType]['NetworkPerformance'] = instanceTypeDict['NetworkInfo']['NetworkPerformance']
                if 'GpuInfo' in instanceTypeDict and 'Gpus' in instanceTypeDict['GpuInfo']:
                    instance_type_info[instanceType]['GpuCount'] = int(instanceTypeDict['GpuInfo']['Gpus'][0].get('Count', 0))
                    instance_type_info[instanceType]['GpuManufacturer'] = instanceTypeDict['GpuInfo']['Gpus'][0].get('Manufacturer', "")
                    instance_type_info[instanceType]['GpuName'] = instanceTypeDict['GpuInfo']['Gpus'][0].get('Name', "")
                    instance_type_info[instanceType]['GpuMemoryMiB'] = instanceTypeDict['GpuInfo']['Gpus'][0].get('MemoryInfo', {}).get('SizeInMiB', 0)
                    instance_type_info[instanceType]['GpuTotalMemoryMiB'] = instanceTypeDict['GpuInfo'].get('TotalGpuMemoryInMiB', 0)

                # (instance_family, instance_size) = instanceType.split('.')
                # if instance_family not in instance_family_info:
                #     instance_family_info[instance_family] = {}
                #     instance_family_info[instance_family]['instance_types'] = [instanceType,]
                #     instance_family_info[instance_family]['MaxInstanceType'] = instanceType
                #     instance_family_info[instance_family]['MaxInstanceSize'] = instance_size
                #     instance_family_info[instance_family]['MaxCoreCount'] = instance_type_info[instanceType]['CoreCount']
                # else:
                #     instance_family_info[instance_family]['instance_types'].append(instanceType)
                #     if instance_type_info[instanceType]['CoreCount'] > instance_family_info[instance_family]['MaxCoreCount']:
                #         instance_family_info[instance_family]['MaxInstanceType'] = instanceType
                #         instance_family_info[instance_family]['MaxInstanceSize'] = instance_size
                #         instance_family_info[instance_family]['MaxCoreCount'] = instance_type_info[instanceType]['CoreCount']

        logger.debug("Getting pricing info for instances")
        instance_types = instance_type_info.keys()
        logger.debug("{} instance types in {}".format(len(instance_types), region))

        for instanceType in sorted(instance_types):
            logger.debug("instanceType: {}".format(instanceType))
            os = 'Linux'
            pricing_filter = [
                {'Field': 'ServiceCode', 'Value': 'AmazonEC2', 'Type': 'TERM_MATCH'},
                {'Field': 'instanceType', 'Value': instanceType, 'Type': 'TERM_MATCH'},
                {'Field': 'tenancy', 'Value': 'shared', 'Type': 'TERM_MATCH'},
                {'Field': 'preInstalledSw', 'Value': 'NA', 'Type': 'TERM_MATCH'},
                {'Field': 'location', 'Value': region_name, 'Type': 'TERM_MATCH'},
                {'Field': 'operatingSystem', 'Value': os, 'Type': 'TERM_MATCH'},
                {'Field': 'capacitystatus', 'Value': 'Used', 'Type': 'TERM_MATCH'},
            ]
            priceLists = self.get_products(pricing_filter)
            if len(priceLists) == 0:
                logger.warning(f"No pricelist for {instanceType} {region} ({region_name}). Instance type may not be available in this region.")
                continue
            if len(priceLists) > 1:
                raise RuntimeError("Number of PriceLists > 1 for {}".format(instanceType))

            instance_type_info[instanceType]['pricing'] = {}
            instance_type_info[instanceType]['pricing']['Reserved'] = {}
            instance_type_info[instanceType]['pricing']['spot'] = {}
            on_demand_price = 0
            ri_min_price = 0
            ri_min_price_terms = ''
            ri_max_price = 0
            ri_max_price_terms = ''

            # instance_type_info[instanceType]['priceLists'] = []
            for priceListJson in priceLists:
                priceList = json.loads(priceListJson)
                logger.debug("pricelist:\n{}".format(pp.pformat(priceList)))
                #instance_type_info[instanceType]['priceLists'].append(priceList)
                if 'physicalProcessor' in priceList['product']['attributes']:
                    physicalProcessor = priceList['product']['attributes']['physicalProcessor']
                for term, termInfo in priceList['terms'].items():
                    if term == 'OnDemand':
                        for rateCodeKey, rateCode in termInfo.items():
                            for dimensionKey, priceDimension in rateCode['priceDimensions'].items():
                                unit = priceDimension['unit']
                                if unit != 'Hrs':
                                    raise RuntimeError("Unknown pricing unit: {}".format(unit))
                                currency = list(priceDimension['pricePerUnit'])[0]
                                if currency != 'USD':
                                    raise RuntimeError("Unknown currency: {}".format(currency))
                                on_demand_price = float(priceDimension['pricePerUnit']['USD'])
                    elif term == 'Reserved':
                        for ri_info_key, ri_info in termInfo.items():
                            attributes = ri_info['termAttributes']
                            ri_length = attributes['LeaseContractLength']
                            ri_class = attributes['OfferingClass']
                            ri_PurchaseOption = attributes['PurchaseOption']
                            ri_terms = "{} {} {}".format(ri_length, ri_class, ri_PurchaseOption)
                            ri_length_hours = float(ri_length.split('yr')[0]) * 365 * 24
                            ri_price = float(0)
                            for priceDimensionKey, priceDimension in ri_info['priceDimensions'].items():
                                unit = priceDimension['unit']
                                pricePerUnit = float(priceDimension['pricePerUnit']['USD'])
                                if unit == 'Quantity':
                                    ri_price += pricePerUnit / ri_length_hours
                                elif unit == 'Hrs':
                                    ri_price += pricePerUnit
                                else:
                                    raise RuntimeError("Invalid reserved instance unit {}".format(unit))
                            instance_type_info[instanceType]['pricing']['Reserved'][ri_terms] = ri_price
                            if ri_price > ri_max_price:
                                ri_max_price = max(ri_max_price, ri_price)
                                ri_max_price_terms = ri_terms
                            if ri_min_price == 0 or ri_price < ri_min_price:
                                ri_min_price = ri_price
                                ri_min_price_terms = ri_terms
                    else:
                        raise RuntimeError("Invalid term {}".format(term))
            instance_type_info[instanceType]['ri_min_price'] = ri_min_price
            instance_type_info[instanceType]['ri_min_price_terms'] = ri_min_price_terms
            instance_type_info[instanceType]['ri_max_price'] = ri_max_price
            instance_type_info[instanceType]['ri_max_price_terms'] = ri_max_price_terms
            instance_type_info[instanceType]['pricing']['OnDemand'] = on_demand_price
            instance_type_info[instanceType]['physicalProcessor'] = physicalProcessor

            # Get spot price for each AZ
            result = self.ec2.describe_spot_price_history(
                InstanceTypes = [instanceType],
                Filters = [
                    {'Name': 'product-description', 'Values': ['Linux/UNIX']}
                ],
                StartTime = datetime.now()
            )
            for spotPriceHistory in result['SpotPriceHistory']:
                az = spotPriceHistory['AvailabilityZone']
                spot_price = float(spotPriceHistory['SpotPrice'])
                instance_type_info[instanceType]['pricing']['spot'][az] = spot_price
                instance_type_info[instanceType]['pricing']['spot']['min'] = min(spot_price, instance_type_info[instanceType]['pricing']['spot'].get('min', 999999999))
                instance_type_info[instanceType]['pricing']['spot']['max'] = max(spot_price, instance_type_info[instanceType]['pricing']['spot'].get('max', 0))


    def print_csv(self, filename=""):
        if filename:
            fh = open(filename, 'w')
        else:
            fh = sys.stdout
        csv_writer = csv.writer(fh, dialect='excel')

        # Get all ri_terms
        ri_terms_dict = {}
        for region, instance_type_info in self.instance_type_info.items():
            for instanceType in instance_type_info.keys():
                if 'pricing' in instance_type_info[instanceType]:
                    for ri_term in instance_type_info[instanceType]['pricing']['Reserved'].keys():
                        ri_terms_dict[ri_term] = 1
        ri_terms = sorted(ri_terms_dict.keys())

        column_names = ["Region", "InstanceType", "Architecture", "CoreCount", "RealMemory(MiB)", "ClockSpeed(GHz)", "NetworkPerformance", "SSDCount", "SSDTotalSizeGB", "physicalProcessor", "GPU Count", "GPU", "GPU Memory (MiB)", "ODPrice", "MinSpotPrice", "MaxSpotDiscount", "MaxSpotPrice", "MinSpotDiscount"]
        for ri_term in ri_terms:
            column_names.append(ri_term)
            column_names.append(f"{ri_term} Discount")
        csv_writer.writerow(column_names)
        for region, instance_type_info in self.instance_type_info.items():
            instance_types = sorted(instance_type_info.keys())
            for instanceType in instance_types:
                if 'pricing' not in instance_type_info[instanceType]:
                    continue
                architecture = instance_type_info[instanceType]['architecture']
                coreCount = instance_type_info[instanceType]['CoreCount']
                realMemory = int(int(instance_type_info[instanceType]['MemoryInMiB']))
                clockSpeedInGHz = instance_type_info[instanceType]['SustainedClockSpeedInGhz']
                networkPerformance = instance_type_info[instanceType]['NetworkPerformance']
                ssdCount = instance_type_info[instanceType]['SSDCount']
                SSDTotalSizeGB = instance_type_info[instanceType]['SSDTotalSizeGB']
                gpuCount =        instance_type_info[instanceType].get('GpuCount', 0)
                gpuManufacturer = instance_type_info[instanceType].get('GpuManufacturer', '')
                gpuName =         instance_type_info[instanceType].get('GpuName', '')
                gpu = gpuManufacturer + " " + gpuName
                #gpuMemoryMiB =       instance_type_info[instanceType].get('GpuMemoryMiB', 0)
                gpuTotalMemoryMiB =  instance_type_info[instanceType].get('GpuTotalMemoryMiB', 0)
                physicalProcessor = instance_type_info[instanceType].get('physicalProcessor', 'UNKNOWN')
                on_demand_price = instance_type_info[instanceType]['pricing']['OnDemand']
                if 'min' in instance_type_info[instanceType]['pricing']['spot']:
                    min_spot_price = instance_type_info[instanceType]['pricing']['spot']['min']
                    max_spot_discount = (on_demand_price - min_spot_price) / on_demand_price
                    max_spot_price = instance_type_info[instanceType]['pricing']['spot']['max']
                    min_spot_discount = (on_demand_price - max_spot_price) / on_demand_price
                else:
                    logger.debug(f"{instanceType} doesn't have spot discounts")
                    min_spot_price = max_spot_discount = max_spot_price = min_spot_discount = ''

                columns = [region, instanceType, architecture, str(coreCount), str(realMemory), str(clockSpeedInGHz), networkPerformance, str(ssdCount), str(SSDTotalSizeGB), physicalProcessor, str(gpuCount), gpu, str(gpuTotalMemoryMiB), str(on_demand_price), str(min_spot_price), str(max_spot_discount), str(max_spot_price), str(min_spot_discount)]

                for ri_term in ri_terms:
                    if ri_term in instance_type_info[instanceType]['pricing']['Reserved']:
                        ri_price = instance_type_info[instanceType]['pricing']['Reserved'][ri_term]
                        columns.append(str(ri_price))
                        ri_discount = (on_demand_price - ri_price) / on_demand_price
                        columns.append(ri_discount)
                    else:
                        logger.debug(f"{instanceType} doesn't have {ri_term} RIs")
                        columns.append('')
                        columns.append('')

                csv_writer.writerow(columns)

    @staticmethod
    def get_instance_family(instanceType):
        instance_family = instanceType.split('.')[0]
        return instance_family

    @staticmethod
    def get_instance_size(instanceType):
        instance_size = instanceType.split('.')[1]
        return instance_size

    # Translate region code to region name
    def get_region_name(self, region_code):
        missing_regions = {
            'ap-northeast-3': 'Asia Pacific (Osaka)'
        }
        endpoint_file = resource_filename('botocore', 'data/endpoints.json')
        with open(endpoint_file, 'r') as f:
            data = json.load(f)
        try:
            region_name = data['partitions'][0]['regions'][region_code]['description']
        except KeyError:
            if region_code in missing_regions:
                return missing_regions[region_code]
            logger.exception(f"Couldn't get region name for {region_code}\nendpoint_file: {endpoint_file}\ndata:\n{pp.pformat(data['partitions'][0]['regions'])}")
            raise
        region_name = region_name.replace('Europe', 'EU')
        return region_name

    @retry_boto3_throttling()
    def get_products(self, pricing_filter):
        priceLists = self.pricing_client.get_products(
            ServiceCode='AmazonEC2', Filters=pricing_filter
        )['PriceList']
        return priceLists
