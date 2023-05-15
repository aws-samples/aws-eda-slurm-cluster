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
from EC2InstanceTypeInfoPkg.get_savings_plans import SavingsPlanInfo
from EC2InstanceTypeInfoPkg.retry_boto3_throttling import retry_boto3_throttling
import json
import logging
from logging import error, info, warning, handlers
import os
from os import environ, path
from pkg_resources import resource_filename
import pprint
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

    def __init__(self, regions, get_savings_plans=True, json_filename=None, debug=False):
        if debug:
            logger.setLevel(logging.DEBUG)

        if not regions:
            # Get a list of all AWS regions
            self.ec2_client = boto3.client('ec2', region_name='us-east-1')
            try:
                regions = sorted([region["RegionName"] for region in self.describe_regions()["Regions"]])
            except ClientError as err:
                logger.error(f"Unable to list all AWS regions. Make sure you have set your IAM credentials. {err}")
                sys.exit(1)
        self.regions = regions

        self.get_savings_plans = get_savings_plans

        logger.info(f"Getting EC2 pricing info for following regions:\n{pp.pformat(self.regions)}")

        if json_filename:
            if path.exists(json_filename):
                logger.info(f"Reading cached info from {json_filename}")
                try:
                    self.instance_type_and_family_info = json.loads(open(json_filename, 'r').read())
                except:
                    logger.exception(f"Error reading {json_filename}. Creating new version with latest format and data.")
                    os.rename(json_filename, json_filename + '.back')
                try:
                    self.check_instance_type_and_family_info()
                except:
                    logger.exception(f"Incorrect data in {json_filename}. Creating new version with latest format and data.")
                    os.rename(json_filename, json_filename + '.back')
            else:
                logger.info(f"{json_filename} doesn't exist so cannot be read and will be created.")
        if not json_filename or not path.exists(json_filename):
            self.instance_type_and_family_info = {}

        # Endpoints only supported in 2 regions: https://docs.aws.amazon.com/cli/latest/reference/pricing/index.html
        self.pricing_client = boto3.client('pricing', region_name='us-east-1')

        for region in self.regions:
            if region in self.instance_type_and_family_info and json_filename:
                logger.info(f'Using EC2 instance info from {json_filename} for {region}')
                continue
            region_name = self.get_region_name(region)
            logger.info(f'Getting EC2 instance info for {region} ({region_name})')
            self.ec2_client = boto3.client('ec2', region_name=region)
            self.get_instance_type_and_family_info(region)

            # Save json after each successful region to speed up reruns
            if json_filename:
                logger.info(f"Saving instance type info for {region} in {json_filename}")
                fh = open(json_filename, 'w')
                print(json.dumps(self.instance_type_and_family_info, indent=4, sort_keys=True), file=fh)
                fh.close()

        return

    def get_instance_type_and_family_info(self, region):
        region_name = self.get_region_name(region)
        logger.debug(f"region_name={region_name}")
        azs = []
        for az_info in self.describe_availability_zones(region)['AvailabilityZones']:
            if az_info['ZoneType'] != 'availability-zone':
                continue
            azs.append(az_info['ZoneName'])
        azs = sorted(azs)
        instance_type_info = {}
        instance_family_info = {}
        self.instance_type_and_family_info[region] = {
            'instance_types': instance_type_info,
            'instance_families': instance_family_info
        }
        describe_instance_types_paginator = self.get_paginator('describe_instance_types')
        for result in self.paginate(describe_instance_types_paginator, {'Filters': [{'Name': 'current-generation', 'Values': ['true']}]}):
            for instanceTypeDict in result['InstanceTypes']:
                #logger.debug(pp.pformat("instanceTypeDict:\n%s" % (pp.pformat(instanceTypeDict))))
                instanceType = instanceTypeDict['InstanceType']
                logger.debug(pp.pformat("instanceType: %s" % (instanceType)))
                instance_type_info[instanceType] = {}
                #instance_type_info[instanceType]['full'] = instanceTypeDict
                architecture = instanceTypeDict['ProcessorInfo']['SupportedArchitectures'][0]
                instance_type_info[instanceType]['architecture'] = architecture
                instance_type_info[instanceType]['SustainedClockSpeedInGhz'] = instanceTypeDict['ProcessorInfo']['SustainedClockSpeedInGhz']
                instance_type_info[instanceType]['DefaultVCpus'] = instanceTypeDict['VCpuInfo']['DefaultVCpus']
                instance_type_info[instanceType]['DefaultCores'] = instanceTypeDict['VCpuInfo']['DefaultCores']
                instance_type_info[instanceType]['DefaultThreadsPerCore'] = instanceTypeDict['VCpuInfo']['DefaultThreadsPerCore']
                instance_type_info[instanceType]['ValidThreadsPerCore'] = instanceTypeDict['VCpuInfo'].get('ValidThreadsPerCore', [instance_type_info[instanceType]['DefaultThreadsPerCore']])
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

                (instance_family, instance_size) = instanceType.split('.')
                if instance_family not in instance_family_info:
                    instance_family_info[instance_family] = {}
                    instance_family_info[instance_family]['instance_types'] = [instanceType,]
                    instance_family_info[instance_family]['architecture'] = instance_type_info[instanceType]['architecture']
                else:
                    instance_family_info[instance_family]['instance_types'].append(instanceType)
                if instance_size != 'metal':
                    if instance_type_info[instanceType]['DefaultCores'] > instance_family_info[instance_family].get('MaxCoreCount', 0):
                        instance_family_info[instance_family]['MaxInstanceType'] = instanceType
                        instance_family_info[instance_family]['MaxInstanceSize'] = instance_size
                        instance_family_info[instance_family]['MaxCoreCount'] = instance_type_info[instanceType]['DefaultCores']

        for instance_family in instance_family_info:
            instance_family_info[instance_family]['instance_types'].sort()
            if len(instance_family_info[instance_family]['instance_types']) == 1 and 'MaxCoreCount' not in instance_family_info[instance_family]:
                instanceType = instance_family_info[instance_family]['instance_types'][0]
                (instance_family, instance_size) = instanceType.split('.')
                instance_family_info[instance_family]['MaxInstanceType'] = instanceType
                instance_family_info[instance_family]['MaxInstanceSize'] = instance_size
                instance_family_info[instance_family]['MaxCoreCount'] = instance_type_info[instanceType]['DefaultCores']

        instance_types = sorted(instance_type_info.keys())

        logger.debug(f"Getting pricing info for {len(instance_types)} instance types:\n{json.dumps(instance_types, indent=4, sort_keys=True)}")
        logger.debug("{} instance types in {}".format(len(instance_types), region))

        if self.get_savings_plans:
            savingsPlanInfo = SavingsPlanInfo(region)

        count = 1
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
            instance_type_info[instanceType]['pricing']['EC2SavingsPlan'] = {}
            instance_type_info[instanceType]['pricing']['ComputeSavingsPlan'] = {}

            on_demand_price = 0
            ri_min_price = 0
            ri_min_price_terms = ''
            ri_max_price = 0
            ri_max_price_terms = ''

            # instance_type_info[instanceType]['priceLists'] = []
            for priceListJson in priceLists:
                priceList = json.loads(priceListJson)
                #logger.debug("pricelist:\n{}".format(pp.pformat(priceList)))
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
                            ri_terms = "RI {} {} {}".format(ri_length, ri_class, ri_PurchaseOption)
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
            instance_type_info[instanceType]['pricing']['Reserved_min'] = ri_min_price
            instance_type_info[instanceType]['pricing']['Reserved_min_terms'] = ri_min_price_terms
            instance_type_info[instanceType]['pricing']['Reserved_max'] = ri_max_price
            instance_type_info[instanceType]['pricing']['Reserved_max_terms'] = ri_max_price_terms
            instance_type_info[instanceType]['pricing']['OnDemand'] = on_demand_price
            instance_type_info[instanceType]['physicalProcessor'] = physicalProcessor

            # Get spot price for each AZ
            for az in azs:
                result = self.describe_spot_price_history(az, instanceType)
                if not result['SpotPriceHistory']:
                    continue
                spotPriceHistory = result['SpotPriceHistory'][0]
                spot_price = float(spotPriceHistory['SpotPrice'])
                instance_type_info[instanceType]['pricing']['spot'][az] = spot_price
                instance_type_info[instanceType]['pricing']['spot']['min'] = min(spot_price, instance_type_info[instanceType]['pricing']['spot'].get('min', 999999999))
                instance_type_info[instanceType]['pricing']['spot']['max'] = max(spot_price, instance_type_info[instanceType]['pricing']['spot'].get('max', 0))

            if self.get_savings_plans:
                min_ec2_sp_discount = 1.0
                max_ec2_sp_discount = 0.0
                min_compute_sp_discount = 1.0
                max_compute_sp_discount = 0.0
                for duration_years in SavingsPlanInfo.VALID_DURATIONS:
                    for payment_option in SavingsPlanInfo.VALID_PAYMENT_OPTIONS:
                        term = f"EC2 SP {duration_years}yr {payment_option}"
                        ec2_savings_plan_rate = savingsPlanInfo.get_ec2_savings_plan_rate(instanceType, duration_years, payment_option)
                        if ec2_savings_plan_rate:
                            logger.debug(f"    EC2     savings plan {term}     for {instanceType}: {ec2_savings_plan_rate}")
                            instance_type_info[instanceType]['pricing']['EC2SavingsPlan'][term] = ec2_savings_plan_rate
                            discount = (on_demand_price - ec2_savings_plan_rate)/on_demand_price
                            min_ec2_sp_discount = min(min_ec2_sp_discount, discount)
                            max_ec2_sp_discount = max(max_ec2_sp_discount, discount)
                        else:
                            logger.debug(f"    No EC2 savings plan {term} for {instanceType}")

                        term = f"Compute SP {duration_years}yr {payment_option}"
                        compute_savings_plan_rate = savingsPlanInfo.get_compute_savings_plan_rate(instanceType, duration_years, payment_option)
                        if compute_savings_plan_rate:
                            logger.debug(f"    Compute savings plan {term} for {instanceType}: {compute_savings_plan_rate}")
                            instance_type_info[instanceType]['pricing']['ComputeSavingsPlan'][term] = compute_savings_plan_rate
                            discount = (on_demand_price - compute_savings_plan_rate)/compute_savings_plan_rate
                            min_compute_sp_discount = min(min_compute_sp_discount, discount)
                            max_compute_sp_discount = max(max_compute_sp_discount, discount)
                        else:
                            logger.debug(f"    No Compute savings plan {term} for {instanceType}")
                instance_type_info[instanceType]['pricing']['EC2SavingsPlan_min_discount'] = min_ec2_sp_discount
                instance_type_info[instanceType]['pricing']['EC2SavingsPlan_max_discount'] = max_ec2_sp_discount
                instance_type_info[instanceType]['pricing']['ComputeSavingsPlan_min_discount'] = min_compute_sp_discount
                instance_type_info[instanceType]['pricing']['ComputeSavingsPlan_max_discount'] = max_compute_sp_discount
            logger.debug(f"    instance_type_info:\n{json.dumps(instance_type_info[instanceType], indent=4, sort_keys=True)}")

    def check_instance_type_and_family_info(self):
        '''
        Raises KeyError
        '''
        for region, region_dict in self.instance_type_and_family_info.items():
                for instance_type, instance_type_dict in region_dict['instance_types'].items():
                    try:
                        assert 'architecture' in instance_type_dict
                        assert 'SustainedClockSpeedInGhz' in instance_type_dict
                        assert 'SustainedClockSpeedInGhz' in instance_type_dict
                        assert 'DefaultVCpus' in instance_type_dict
                        assert 'DefaultCores' in instance_type_dict
                        assert 'DefaultThreadsPerCore' in instance_type_dict
                        assert 'ValidThreadsPerCore' in instance_type_dict
                        assert 'DefaultThreadsPerCore' in instance_type_dict
                        assert 'MemoryInMiB' in instance_type_dict
                        assert 'SSDCount' in instance_type_dict
                        assert 'SSDTotalSizeGB' in instance_type_dict
                        assert 'Hypervisor' in instance_type_dict
                        assert 'NetworkPerformance' in instance_type_dict
                        if 'pricing' in instance_type_dict:
                            assert 'ComputeSavingsPlan' in instance_type_dict['pricing']
                    except:
                        logger.error(f"{instance_type} instance type missing data:\n{json.dumps(instance_type_dict, indent=4)}")
                        raise
                for instance_family, instance_family_dict in region_dict['instance_families'].items():
                    try:
                        assert 'instance_types' in instance_family_dict
                        assert 'architecture' in instance_family_dict
                        assert 'MaxCoreCount' in instance_family_dict
                        assert 'MaxInstanceType' in instance_family_dict
                        assert 'MaxInstanceSize' in instance_family_dict
                    except:
                        logger.error(f"{instance_family} family missing data:\n{json.dumps(instance_family_dict, indent=4)}")
                        raise

    def print_csv(self, filename=""):
        if filename:
            fh = open(filename, 'w')
        else:
            fh = sys.stdout
        csv_writer = csv.writer(fh, dialect='excel')

        # Get all ri_terms
        ri_terms_dict = {}
        for region, instance_type_and_family_info in self.instance_type_and_family_info.items():
            instance_type_info = instance_type_and_family_info['instance_types']
            for instanceType in instance_type_info.keys():
                if 'pricing' in instance_type_info[instanceType]:
                    for ri_term in instance_type_info[instanceType]['pricing']['Reserved'].keys():
                        ri_terms_dict[ri_term] = 1
        ri_terms = sorted(ri_terms_dict.keys())
        logger.debug(f"ri_terms: \n{json.dumps(ri_terms, indent=4)}")

        # Get all Savings Plans terms
        ec2_sp_terms_dict = {}
        for region, instance_type_and_family_info in self.instance_type_and_family_info.items():
            instance_type_info = instance_type_and_family_info['instance_types']
            for instanceType in instance_type_info.keys():
                if 'pricing' in instance_type_info[instanceType]:
                    for sp_term in instance_type_info[instanceType]['pricing']['EC2SavingsPlan'].keys():
                        ec2_sp_terms_dict[sp_term] = 1
        ec2_sp_terms = sorted(ec2_sp_terms_dict.keys())
        logger.debug(f"ec2_sp_terms: \n{json.dumps(ec2_sp_terms, indent=4)}")

        compute_sp_terms_dict = {}
        for region, instance_type_and_family_info in self.instance_type_and_family_info.items():
            instance_type_info = instance_type_and_family_info['instance_types']
            for instanceType in instance_type_info.keys():
                if 'pricing' in instance_type_info[instanceType]:
                    for sp_term in instance_type_info[instanceType]['pricing']['ComputeSavingsPlan'].keys():
                        compute_sp_terms_dict[sp_term] = 1
        compute_sp_terms = sorted(compute_sp_terms_dict.keys())
        logger.debug(f"compute_sp_terms: \n{json.dumps(compute_sp_terms, indent=4)}")

        column_names = ["Region", "InstanceType", "Architecture", "CoreCount", "RealMemory(MiB)", "ClockSpeed(GHz)", "NetworkPerformance", "SSDCount", "SSDTotalSizeGB", "physicalProcessor", "GPU Count", "GPU", "GPU Memory (MiB)", "ODPrice", "MinSpotPrice", "MaxSpotDiscount", "MaxSpotPrice", "MinSpotDiscount"]
        for ri_term in ri_terms:
            column_names.append(ri_term)
            column_names.append(f"{ri_term} Discount")
        for ec2_sp_term in ec2_sp_terms:
            column_names.append(ec2_sp_term)
            column_names.append(f"{ec2_sp_term} Discount")
        for compute_sp_term in compute_sp_terms:
            column_names.append(compute_sp_term)
            column_names.append(f"{compute_sp_term} Discount")
        csv_writer.writerow(column_names)
        for region, instance_type_and_family_info in self.instance_type_and_family_info.items():
            instance_type_info = instance_type_and_family_info['instance_types']
            instance_types = sorted(instance_type_info.keys())
            for instanceType in instance_types:
                if 'pricing' not in instance_type_info[instanceType]:
                    logger.debug(f"Skipping {instanceType} because no pricing info.")
                    continue
                architecture = instance_type_info[instanceType]['architecture']
                coreCount = instance_type_info[instanceType]['DefaultCores']
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
                    ri_price = instance_type_info[instanceType]['pricing']['Reserved'].get(ri_term, None)
                    if ri_price:
                        columns.append(str(ri_price))
                        ri_discount = (on_demand_price - ri_price) / on_demand_price
                        columns.append(ri_discount)
                    else:
                        logger.debug(f"{region} {instanceType} doesn't have {ri_term} RIs")
                        columns.append('')
                        columns.append('')
                for ec2_sp_term in ec2_sp_terms:
                    esp_price = instance_type_info[instanceType]['pricing']['EC2SavingsPlan'].get(ec2_sp_term, None)
                    if esp_price:
                        columns.append(str(esp_price))
                        esp_discount = (on_demand_price - esp_price) / on_demand_price
                        columns.append(esp_discount)
                    else:
                        logger.debug(f"{region} {instanceType} doesn't have {ec2_sp_term} ESPs")
                        columns.append('')
                        columns.append('')
                for compute_sp_term in compute_sp_terms:
                    csp_price = instance_type_info[instanceType]['pricing']['ComputeSavingsPlan'].get(compute_sp_term, None)
                    if csp_price:
                        columns.append(str(csp_price))
                        csp_discount = (on_demand_price - csp_price) / on_demand_price
                        columns.append(csp_discount)
                    else:
                        logger.debug(f"{region} {instanceType} doesn't have {compute_sp_term} CSPs")
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
    def describe_regions(self):
        response = self.ec2_client.describe_regions()
        return response

    @retry_boto3_throttling()
    def describe_availability_zones(self, region):
        response = self.ec2_client.describe_availability_zones(Filters=[{'Name': 'region-name', 'Values': [region]}], AllAvailabilityZones=False)
        return response

    @retry_boto3_throttling()
    def get_paginator(self, command):
        paginator = self.ec2_client.get_paginator(command)
        return paginator

    @retry_boto3_throttling()
    def paginate(self, paginator, kwargs):
        response = paginator.paginate(**kwargs)
        return response

    @retry_boto3_throttling()
    def describe_spot_price_history(self, az, instanceType):
        response = self.ec2_client.describe_spot_price_history(
            AvailabilityZone = az,
            InstanceTypes = [instanceType],
            Filters = [
                {'Name': 'product-description', 'Values': ['Linux/UNIX']}
            ],
            StartTime = datetime.now()
        )
        return response

    @retry_boto3_throttling()
    def get_products(self, pricing_filter):
        priceLists = self.pricing_client.get_products(
            ServiceCode='AmazonEC2', Filters=pricing_filter
        )['PriceList']
        return priceLists
