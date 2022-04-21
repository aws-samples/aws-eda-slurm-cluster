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

class EC2InstanceTypeInfo:

    def __init__(self):
        self.ec2 = boto3.client('ec2')
        self.get_instance_type_info()
        return

    def get_instance_type_info(self):
        self.instance_type_info = {}
        self.instance_family_info = {}
        describe_instance_types_paginator = self.ec2.get_paginator('describe_instance_types')
        for result in describe_instance_types_paginator.paginate(**{'Filters': [{'Name': 'current-generation', 'Values': ['true']}]}):
            for instance_type_info in result['InstanceTypes']:
                instanceType = instance_type_info['InstanceType']
                self.instance_type_info[instanceType] = {}
                self.instance_type_info[instanceType]['full'] = instance_type_info
                architecture = instance_type_info['ProcessorInfo']['SupportedArchitectures'][0]
                self.instance_type_info[instanceType]['architecture'] = architecture
                self.instance_type_info[instanceType]['SustainedClockSpeedInGhz'] = instance_type_info['ProcessorInfo']['SustainedClockSpeedInGhz']
                if 'ValidThreadsPerCore' in instance_type_info['VCpuInfo']:
                    self.instance_type_info[instanceType]['ThreadsPerCore'] = max(instance_type_info['VCpuInfo']['ValidThreadsPerCore'])
                else:
                    if architecture == 'x86_64':
                        self.instance_type_info[instanceType]['ThreadsPerCore'] = 2
                    else:
                        self.instance_type_info[instanceType]['ThreadsPerCore'] = 1
                if 'ValidCores' in instance_type_info['VCpuInfo']:
                    self.instance_type_info[instanceType]['CoreCount'] = max(instance_type_info['VCpuInfo']['ValidCores'])
                else:
                    self.instance_type_info[instanceType]['CoreCount'] = instance_type_info['VCpuInfo']['DefaultVCpus']/self.instance_type_info[instanceType]['ThreadsPerCore']
                self.instance_type_info[instanceType]['MemoryInMiB'] = instance_type_info['MemoryInfo']['SizeInMiB']
                self.instance_type_info[instanceType]['SSDCount'] = instance_type_info.get('InstanceStorageInfo', {'Disks': [{'Count': 0}]})['Disks'][0]['Count']
                self.instance_type_info[instanceType]['SSDTotalSizeGB'] = instance_type_info.get('InstanceStorageInfo', {'TotalSizeInGB': 0})['TotalSizeInGB']

                (instance_family, instance_size) = instanceType.split(r'\.')
                if instance_family not in self.instance_family_info:
                    self.instance_family_info[instance_family] = {}
                    self.instance_family_info[instance_family]['instance_types'] = [instanceType,]
                    self.instance_family_info[instance_family]['MaxInstanceType'] = instanceType
                    self.instance_family_info[instance_family]['MaxInstanceSize'] = instance_size
                    self.instance_family_info[instance_family]['MaxCoreCount'] = self.instance_type_info[instanceType]['CoreCount']
                else:
                    self.instance_family_info[instance_family]['instance_types'].append(instanceType)
                    if self.instance_type_info[instanceType]['CoreCount'] > self.instance_family_info[instance_family]['MaxCoreCount']:
                        self.instance_family_info[instance_family]['MaxInstanceType'] = instanceType
                        self.instance_family_info[instance_family]['MaxInstanceSize'] = instance_size
                        self.instance_family_info[instance_family]['MaxCoreCount'] = self.instance_type_info[instanceType]['CoreCount']

    def get_instance_family(self, instanceType):
        instance_family = instanceType.split(r'\.')[0]
        return instance_family

    def get_instance_size(self, instanceType):
        instance_size = instanceType.split(r'\.')[1]
        return instance_size

    def get_instance_families(self):
        return sorted(self.instance_type_info.keys())

    def get_max_instance_type(self, instance_family):
        return self.instance_family_info[instance_family]['MaxInstanceType']

    def get_instance_types(self):
        return sorted(self.instance_type_info.keys())

    def get_architecture(self, instance_type):
        return self.instance_type_info[instance_type]['architecture']

    def get_SustainedClockSpeedInGhz(self, instance_type):
        return self.instance_type_info[instance_type]['SustainedClockSpeedInGhz']

    def get_CoreCount(self, instance_type):
        return self.instance_type_info[instance_type]['CoreCount']

    def get_ThreadsPerCore(self, instance_type):
        return self.instance_type_info[instance_type]['ThreadsPerCore']

    def get_MemoryInMiB(self, instance_type):
        return self.instance_type_info[instance_type]['MemoryInMiB']

    def get_SSDCount(self, instance_type):
        return self.instance_type_info[instance_type]['SSDCount']

    def get_SSDTotalSizeGB(self, instance_type):
        return self.instance_type_info[instance_type]['SSDTotalSizeGB']

    def get_full_info(self, instance_type):
        return self.instance_type_info[instance_type]['full']
