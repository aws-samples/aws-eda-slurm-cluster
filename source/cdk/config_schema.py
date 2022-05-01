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

from email.policy import default
import re
from schema import Schema, And, Use, Optional, Regex, SchemaError

config = {}
valid_regions = []

filesystem_lifecycle_policies = [
    'None',
    'AFTER_14_DAYS',
    'AFTER_30_DAYS',
    'AFTER_60_DAYS',
    'AFTER_7_DAYS',
    'AFTER_90_DAYS'
    ]

default_storage = {
    'provider': 'efs',
    'removal_policy': 'RETAIN',
    'efs': {
        'enable_automatic_backups': False,
        'lifecycle_policy': 'AFTER_30_DAYS',
        'use_efs_helper': False,
        'throughput_mode': 'BURSTING',
        'performance_mode': 'GENERAL_PURPOSE',
        'encrypted': True
    },
}

config_schema = Schema(
    {
        Optional('termination_protection', default=True): bool,
        Optional('StackName'): str,
        Optional('Region'): And(str, lambda s: s in valid_regions),
        Optional('SshKeyPair'): str,
        Optional('VpcId'): And(str, lambda s: re.match('vpc-', s)),
        Optional('SubnetId'): And(str, lambda s: re.match('subnet-', s)),
        Optional('ErrorSnsTopicArn'): str,
        Optional('Domain'): str,
        Optional('HostedZoneId'): str,
        Optional('TimeZone', default='US/Central'): str,
        'slurm': {
            Optional('SlurmVersion', default='21.08.7'): str,
            Optional('ClusterName'): str,
            Optional('MungeKeySsmParameter', default='/slurm/munge_key'): str,
            'SlurmCtl': {
                Optional('NumberOfControllers', default=1): And(Use(int), lambda n: 1 <= n <= 3),
                Optional('BaseHostname', default='slurmctl'): str,
                Optional('architecture', default='arm64'): str,
                Optional('instance_type', default='c6g.large'): str,
                Optional('volume_size', default=200): int,
                Optional('SuspendAction', default='stop'): str,
                Optional('MaxStoppedDuration', default='P0Y0M0DT1H0M0S'): str,
                Optional('CloudWatchPeriod', default=5): int,
                Optional('PreemptMode', default='REQUEUE'): And(str, lambda s: s in ['OFF', 'CANCEL', 'GANG', 'REQUEUE', 'SUSPEND']),
                Optional('PreemptType', default='preempt/partition_prio'): And(str, lambda s: s in ['preempt/none', 'preempt/partition_prio', 'preempt/qos']),
                Optional('PreemptExemptTime', default='0'): str,
            },
            Optional('ExistingSlurmDbd'): {
                Optional('UseSlurmDbd', default=True): bool,
                Optional('StackName'): str,
                Optional('SecurityGroup'): {str: And(str, lambda s: re.match('sg-', s))},
                Optional('HostnameFQDN'): str,
            },
            Optional('SlurmDbd'): {
                Optional('UseSlurmDbd', default=True): bool,
                Optional('Hostname', default='slurmdbd'): str,
                Optional('architecture', default='arm64'): str,
                Optional('instance_type', default='m6g.large'): str,
                Optional('volume_size', default=200): int,
                Optional('database', default={'port': 3306}): {
                    'port': int,
                }
            },
            Optional('Federation'): {
                'Name': str,
                Optional('FederatedClusterStackNames'): [str],
                Optional('SlurmCtlSecurityGroups', default={}): {
                    Optional(str): And(str, lambda s: re.match('sg-', s))
                },
                Optional('SlurmNodeSecurityGroups', default={}): {
                    Optional(str): And(str, lambda s: re.match('sg-', s))
                },
            },
            Optional('SlurmNodeAmis', default={'instance_type': {'x86_64': 'm5.large', 'arm64': 'm6g.large'}}): {
                Optional('instance_type', default={'x86_64': 'm5.large', 'arm64': 'm6g.large'}): {
                    'x86_64': str,
                    'arm64': str,
                },
                Optional('BaseAmis'): {
                    str: { # region
                        str: { # distribution
                            int: { # distribution_major_version
                                str: { # architecture
                                    'ImageId': And(str, lambda s: re.match('ami-', s)),
                                    Optional('RootDeviceSize'): str,
                                }
                            }
                        }
                    }
                },
            },
            Optional('SubmitterSecurityGroupIds'): {str: str},
            Optional('SubmitterInstanceTags'): {str: [str]},
            'InstanceConfig': {
                Optional('UseSpot', default=True): bool,
                'DefaultPartition': str,
                'NodesPerInstanceType': int,
                'BaseOsArchitecture': {
                    str: { # distribution
                        int: [ # distribution_major_version
                            str # architecture
                        ]
                    }
                },
                'Include': {
                    Optional('MaxSizeOnly', default=False): bool,
                    'InstanceFamilies': [str],
                    'InstanceTypes': [str]
                },
                Optional('Exclude', default={'InstanceFamilies': [], 'InstanceTypes': []}): {
                    'InstanceFamilies': [str],
                    'InstanceTypes': [str]
                },
                Optional('AlwaysOnNodes', default=[]): [
                    str # Nodelist
                ],
                Optional('AlwaysOnPartitions', default=[]): [
                    str # Partitionlist
                ],
                Optional('OnPremComputeNodes', default={}): {
                    'ConfigFile': str,
                    'CIDR': str,
                    Optional('Partition', default='onprem'): str,
                }
            },
            Optional('ElasticSearch'): {
                Optional('ebs_volume_size', default=20): int,
                Optional('ebs_volume_type', default='GP2'): str,
                Optional('enable_version_upgrade', default=False): bool,
                Optional('number_of_azs', default=2): int,
                Optional('master_nodes', default=2): int,
                Optional('master_node_instance_type', default='m5.large.search'): str,
                Optional('data_nodes', default=1): int,
                Optional('data_node_instance_type', default='m5.large.search'): str,
                Optional('warm_nodes', default=0): int,
                Optional('warm_instance_type', default='ultrawarm.medium.search'): str,
            },
            Optional('JobCompType', default='jobcomp/filetxt'): And(str, lambda s: s in ('jobcomp/none', 'jobcomp/elasticsearch', 'jobcomp/filetxt')),
            Optional('JobCompLoc'): str,
            Optional('SlurmUid', default=900): int,
            'storage': {
                Optional('mount_path'): str,
                Optional('provider', default='efs'): And(str, lambda s: s in ('efs', 'lustre', 'ontap')),
                Optional('removal_policy', default='RETAIN'): And(str, lambda s: s in ('DESTROY', 'RETAIN', 'SNAPSHOT')),
                Optional('kms_key_arn'): str,
                Optional('efs'): {
                    Optional('enable_automatic_backups', default=False): bool,
                    Optional('lifecycle_policy', default='AFTER_30_DAYS'): And(str, lambda s: s in filesystem_lifecycle_policies),
                    Optional('use_efs_helper', default=False): bool,
                    Optional('throughput_mode', default='BURSTING'): And(str, lambda s: s in ('BURSTING', 'PROVISIONED')),
                    Optional('provisioned_throughput_per_second'): int,
                    Optional('performance_mode', default='GENERAL_PURPOSE'): And(str, lambda s: s in ('GENERAL_PURPOSE', 'MAX_IO')),
                    Optional('encrypted', default=True): bool,
                },
                Optional('lustre'): {
                    Optional('deployment_type', default='SCRATCH_2'): And(str, lambda s: s in ('PERSISTENT_1', 'SCRATCH_1', 'SCRATCH_2')),
                    Optional('drive_cache_type', default='NONE'): And(str, lambda s: s in ('NONE', 'READ')),
                    Optional('per_unit_storage_throughput', default=50): int,
                    Optional('storage_capacity', default=1200): int,
                    Optional('storage_type'): And(str, lambda s: s in ('HDD', 'SSD')),
                },
                Optional('ontap'): {
                    Optional('deployment_type', default='SINGLE_AZ_1'): And(str, lambda s: s in ('SINGLE_AZ_1', 'MULTI_AZ_1')),
                    Optional('storage_capacity', default=1024): And(int, lambda s: s >= 1024 and s <= 196608), # 1024 GiB up to 196,608 GiB (192 TiB)
                    Optional('iops'): int,
                    Optional('throughput_capacity', default=128): And(int, lambda s: s in [128, 256, 512, 1024, 2048]),
                    Optional('tiering_policy', default='AUTO'): And(str, lambda s: s in ('ALL', 'AUTO', 'NONE', 'SNAPSHOT_ONLY')),
                    Optional('cooling_period', default=31): And(int, lambda s: (s >= 2 and s <= 183)),
                },
                Optional('ExtraMounts', default=[]): [
                    {
                        'dest': str,
                        'src': str,
                        'type': str,
                        'options': str
                    }
                ]
            },
        },
        Optional('AmiMap', default={}): {
            str: { # Region
                str: { # Distribution
                    int: { # distribution_major_version
                        And(str, lambda s: s in ['x86_64', 'arm64']): {
                            'ImageId': str,
                            'RootDeviceName': str
                        }
                    }
                }
            }
        }
    }
)

def check_schema(config_in, regions):
    # Validate config against schema
    global config
    global valid_regions
    config = config_in
    valid_regions = regions
    validated_config = config_schema.validate(config)
    return validated_config
