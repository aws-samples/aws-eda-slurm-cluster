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
from botocore.client import ClientError
import json
import logging
from os import environ
from packaging.version import parse as parse_version
import re
from schema import And, Schema, Optional, Or, Regex, Use, SchemaError
from sys import exit

logger = logging.getLogger(__file__)
logger_formatter = logging.Formatter('%(levelname)s: %(message)s')
logger_streamHandler = logging.StreamHandler()
logger_streamHandler.setFormatter(logger_formatter)
logger.addHandler(logger_streamHandler)
logger.propagate = False
logger.setLevel(logging.INFO)

# MIN_PARALLEL_CLUSTER_VERSION
# 3.3.0:
#     * Add support for multiple instance types in a compute resource
# 3.4.0:
#     * Add support for launching nodes across multiple availability zones to increase capacity availability
#     * Add support for specifying multiple subnets for each queue to increase capacity availability
#     * Add possibility to specify a custom script to be executed in the head node during the update of the cluster. The script can be specified with OnNodeUpdated parameter when using Slurm as scheduler.
# 3.5.0:
#     * Add logging of compute node console output to CloudWatch on compute node bootstrap failure.
# 3.6.0:
#     * Add support for RHEL8.7.
#     * Add support for customizing the cluster Slurm configuration via the ParallelCluster configuration YAML file.
#     * Increase the limit on the maximum number of queues per cluster from 10 to 50. Compute resources can be distributed
#       flexibly across the various queues as long as the cluster contains a maximum of 50 compute resources.
#     * Allow to specify a sequence of multiple custom actions scripts per event for OnNodeStart, OnNodeConfigured and OnNodeUpdated parameters.
#     * Upgrade Slurm to version 23.02.2.
# 3.7.0b1:
#     * Login Nodes
#     * Add support for configurable node weights within queue
MIN_PARALLEL_CLUSTER_VERSION = parse_version('3.6.0')
DEFAULT_PARALLEL_CLUSTER_VERSION = parse_version('3.6.1')
DEFAULT_PARALLEL_CLUSTER_MUNGE_VERSION = '0.5.15'
DEFAULT_PARALLEL_CLUSTER_MUNGE_VERSIONS = {
    '3.6.0':   '0.5.15',
    '3.6.1':   '0.5.15',
}
DEFAULT_PARALLEL_CLUSTER_PYTHON_VERSION = '3.9.16'
DEFAULT_PARALLEL_CLUSTER_PYTHON_VERSIONS = {
    '3.6.0':   '3.9.16',
    '3.6.1':   '3.9.16',
    '3.7.0b1': '3.9.16',
}
DEFAULT_PARALLEL_CLUSTER_SLURM_VERSION = '23-02-3-1'
DEFAULT_PARALLEL_CLUSTER_SLURM_VERSIONS = {
    '3.7.0b1': DEFAULT_PARALLEL_CLUSTER_SLURM_VERSION,
}

def get_DEFAULT_PARALLEL_CLUSTER_MUNGE_VERSION(config):
    parallel_cluster_version = config.get('slurm', {}).get('ParallelClusterConfig', {}).get('Version', DEFAULT_PARALLEL_CLUSTER_VERSION)
    munge_version = DEFAULT_PARALLEL_CLUSTER_MUNGE_VERSIONS.get(parallel_cluster_version, str(DEFAULT_PARALLEL_CLUSTER_MUNGE_VERSION))
    return munge_version

def get_DEFAULT_PARALLEL_CLUSTER_PYTHON_VERSION(config):
    parallel_cluster_version = config.get('slurm', {}).get('ParallelClusterConfig', {}).get('Version', DEFAULT_PARALLEL_CLUSTER_VERSION)
    python_version = DEFAULT_PARALLEL_CLUSTER_PYTHON_VERSIONS.get(parallel_cluster_version, str(DEFAULT_PARALLEL_CLUSTER_PYTHON_VERSION))
    return python_version

PARALLEL_CLUSTER_ALLOWED_OSES = ['alinux2', 'centos7', 'rhel8', 'ubuntu2004', 'ubuntu2204']

DEFAULT_SLURM_VERSION = '23.02.1'
def get_DEFAULT_SLURM_VERSION(config):
    if config.get('slurm', {}).get('ParallelClusterConfig', {}).get('Enable', False):
        parallel_cluster_version = config.get('slurm', {}).get('ParallelClusterConfig', {}).get('Version', DEFAULT_PARALLEL_CLUSTER_VERSION)
        slurm_version = DEFAULT_PARALLEL_CLUSTER_SLURM_VERSIONS.get(parallel_cluster_version, DEFAULT_PARALLEL_CLUSTER_SLURM_VERSION)
    else:
        slurm_version = DEFAULT_SLURM_VERSION
    return slurm_version

DEFAULT_SLURM_REST_API_VERSION = '0.0.39'
DEFAULT_SLURM_REST_API_VERSIONs = {
    '23.02.1': '0.0.39',
    '23-02-3-1': '0.0.39',
}
def get_default_slurm_rest_api_version(config):
    slurm_version = config.get('slurm', {}).get('SlurmVersion', get_DEFAULT_SLURM_VERSION(config))
    default_slurm_rest_api_version = DEFAULT_SLURM_REST_API_VERSIONs.get(slurm_version, DEFAULT_SLURM_REST_API_VERSION)
    return default_slurm_rest_api_version

# Determine all AWS regions available on the account.
default_region = environ.get("AWS_DEFAULT_REGION", "us-east-1")
ec2_client = boto3.client("ec2", region_name=default_region)
try:
    # describe_regions only describes the regions that are enabled for your account unless AllRegions is set.
    valid_regions = [region["RegionName"] for region in ec2_client.describe_regions(AllRegions=True)["Regions"]]
except ClientError as err:
    logger.error(f"{fg('red')}Unable to list all AWS regions. Make sure you have set your IAM credentials. {err} {attr('reset')}")
    exit(1)

filesystem_lifecycle_policies = [
    'None',
    'AFTER_14_DAYS',
    'AFTER_30_DAYS',
    'AFTER_60_DAYS',
    'AFTER_7_DAYS',
    'AFTER_90_DAYS'
    ]

default_eda_instance_families = [
    #'c5',                # Mixed depending on size
    #'c5a',               # AMD EPYC 7R32 3.3 GHz
    #'c5ad',              # AMD EPYC 7R32 3.3 GHz
    'c6a',
    'c6ad',
    'c6i',               # Intel Xeon 8375C (Ice Lake) 3.5 GHz
    'c6id',
    'c6g',               # AWS Graviton2 Processor 2.5 GHz
    #'c6gd',              # AWS Graviton2 Processor 2.5 GHz
    #'f1',                # Intel Xeon E5-2686 v4 (Broadwell) 2.3 GHz
    #'m5',                # Intel Xeon Platinum 8175 (Skylake) 3.1 GHz
    #'m5d',               # Intel Xeon Platinum 8175 (Skylake) 3.1 GHz
    #'m5a',               # AMD EPYC 7571 2.5 GHz
    #'m5ad',              # AMD EPYC 7571 2.5 GHz
    'm5zn',              # Intel Xeon Platinum 8252 4.5 GHz
    'm6a',               # AMD EPYC 7R13 Processor 3.6 GHz
    'm6ad',
    'm6i',               # Intel Xeon 8375C (Ice Lake) 3.5 GHz
    'm6id',
    'm6g',               # AWS Graviton2 Processor 2.5 GHz
    #'m6gd',              # AWS Graviton2 Processor 2.5 GHz
    'r5',                # Intel Xeon Platinum 8175 (Skylake) 3.1 GHz
    'r5d',               # Intel Xeon Platinum 8175 (Skylake) 3.1 GHz
    #'r5b',               # Intel Xeon Platinum 8259 (Cascade Lake) 3.1 GHz
    'r5a',               # AMD EPYC 7571 2.5 GHz
    'r5ad',              # AMD EPYC 7571 2.5 GHz
    'r6a',
    'r6i',               # Intel Xeon 8375C (Ice Lake) 3.5 GHz 1TB
    'r6id',
    'r6g',               # AWS Graviton2 Processor 2.5 GHz
    #'r6gd',              # AWS Graviton2 Processor 2.5 GHz
    #'x1',                # High Frequency Intel Xeon E7-8880 v3 (Haswell) 2.3 GHz 2TB
    #'x1e',               # High Frequency Intel Xeon E7-8880 v3 (Haswell) 2.3 GHz 4TB
    'x2gd',              # AWS Graviton2 Processor 2.5 GHz 1TB
    'x2idn',             # Intel Xeon Scalable (Icelake) 3.5 GHz 2 TB
    'x2iedn',            # Intel Xeon Scalable (Icelake) 3.5 GHz 4 TB
    'x2iezn',            # Intel Xeon Platinum 8252 4.5 GHz 1.5 TB
    'z1d',               # Intel Xeon Platinum 8151 4.0 GHz
    #'u-6tb1',            # Intel Xeon Scalable (Skylake) 6 TB
    #'u-9tb1',            # Intel Xeon Scalable (Skylake) 9 TB
    #'u-12tb1',           # Intel Xeon Scalable (Skylake) 12 TB
]

default_eda_instance_types = [
    #'c5\.(l|x|2|4|9|18).*',  # Intel Xeon Platinum 8124M 3.4 GHz
    #'c5\.(12|24).*',         # Intel Xeon Platinum 8275L 3.6 GHz
    #'c5d\.(l|x|2|4|9|18).*', # Intel Xeon Platinum 8124M 3.4 GHz
    #'c5d\.(12|24).*',        # Intel Xeon Platinum 8275L 3.6 GHz
]

default_excluded_instance_families = [
    'a1',   # Graviton 1
    'c4',   # Replaced by c5
    'd2',   # SSD optimized
    'g3',   # Replaced by g4
    'g3s',  # Replaced by g4
    'h1',   # SSD optimized
    'i3',   # SSD optimized
    'i3en', # SSD optimized
    'm4',   # Replaced by m5
    'p2',   # Replaced by p3
    'p3',
    'p3dn',
    'r4',   # Replaced by r5
    't2',   # Replaced by t3
    'x1',
    'x1e',
]

default_excluded_instance_types = [
    '.+\.(micro|nano)', # Not enough memory
    '.*\.metal'
]

architectures = [
    'arm64',
    'x86_64'
]

os_distributions = [
    'AlmaLinux',
    'Amazon',
    'CentOS',
    'RedHat',
    'Rocky'
]

# The config file is used in the installer and the CDK app.
# Some configuration values are required in the CDK app but are optional so that they can be set by the installer.
def get_config_schema(config):
    return Schema(
    {
        # termination_protection:
        #     Enable Cloudformation Stack termination protection
        Optional('termination_protection', default=True): bool,
        # Optional so can be specified on the command-line
        Optional('StackName', default='slurm'): str,
        # Optional so can be specified on the command-line
        Optional('Region'): And(str, lambda s: s in valid_regions),
        # Optional so can be specified on the command-line
        Optional('SshKeyPair'): str,
        # Optional so can be specified on the command-line
        Optional('VpcId'): And(str, lambda s: re.match('vpc-', s)),
        Optional('CIDR'): And(str, lambda s: re.match(r'\d+\.\d+\.\d+\.\d+/\d+', s)),
        #
        # SubnetId
        # Optional. If not specified then the first private subnet is chosen.
        Optional('SubnetId'): And(str, lambda s: re.match('subnet-', s)),
        # Optional, but highly recommended
        Optional('ErrorSnsTopicArn'): str,
        #
        # Domain:
        #     Domain name for the Route 53 private hosted zone that will be used
        #     by the slurm cluster for DNS.
        #     Alternately, provide HostedZoneId of an existing Route53 hosted zone to use and
        #     the zone name of the HostedZoneId.
        #     By default will be {StackName}.local
        Optional('Domain'): str,
        #
        # HostedZoneId:
        #     ID of an existing hosted zone that will be used by the slurm cluster for DNS.
        #     You must provide the Domain name of the HostedZone if it is different than the default.
        Optional('HostedZoneId'): str,
        Optional('TimeZone', default='US/Central'): str,
        'slurm': {
            Optional('ParallelClusterConfig'): {
                'Enable': bool,
                Optional('Version', default=str(DEFAULT_PARALLEL_CLUSTER_VERSION)): And(str, lambda s: parse_version(s) >= MIN_PARALLEL_CLUSTER_VERSION),
                Optional('MungeVersion', default=get_DEFAULT_PARALLEL_CLUSTER_MUNGE_VERSION(config)): str,
                Optional('PythonVersion', default=get_DEFAULT_PARALLEL_CLUSTER_PYTHON_VERSION(config)): str,
                Optional('Image', default={'Os': 'centos7'}): {
                    Optional('Os', default='centos7'): And(str, lambda s: s in PARALLEL_CLUSTER_ALLOWED_OSES)
                },
                Optional('Architecture', default='arm64'): And(str, lambda s: s in ['arm64', 'x86_64']),
                Optional('ComputeNodeAmi'): And(str, lambda s: s.startswith('ami-')),
                Optional('DisableSimultaneousMultithreading', default=True): bool,
                # Recommend to not use EFA unless necessary to avoid insufficient capacity errors when starting new instances in group or when multiple instance types in the group
                # See https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/placement-groups.html#placement-groups-cluster
                Optional('EnableEfa', default=False): bool,
                Optional('Database'): {
                    Optional('DatabaseStackName'): str,
                    Optional('EdaSlurmClusterStackName'): str,
                    Optional('FQDN'): str,
                    Optional('Port'): int,
                    Optional('AdminUserName'): str,
                    Optional('AdminPasswordSecretArn'): And(str, lambda s: s.startswith('arn:')),
                    Optional('ClientSecurityGroup'): {str: And(str, lambda s: re.match('sg-', s))},
                },
                Optional('Dcv', default={}): {
                    Optional('Enable', default=False): bool,
                    Optional('Port', default=8443): int,
                    Optional('AllowedIps', default='10.0.0.0/32'): str
                },
                Optional('LoginNodes'): {
                    'Pools': [
                        {
                            'Name': str,
                            Optional('Image'): {
                                'CustomAmi': And(str, lambda s: s.startswith('ami-'))
                            },
                            'Count': int,
                            'InstanceType': str,
                            Optional('Networking'): {
                                Optional('SubnetIds'): [ # Only 1 subnet supported for the MVP. Default to slurm subnet
                                    And(str, lambda s: s.startswith('subnet-'))
                                ],
                                Optional('SecurityGroups'): [
                                    And(str, lambda s: s.startswith('sg-'))
                                ],
                                Optional('AdditionalSecurityGroups'): [
                                    And(str, lambda s: s.startswith('sg-'))
                                ],
                            },
                            Optional('Ssh'): {
                                'KeyName': str # default value: same ssh key used for the Head Node
                            },
                            Optional('Iam'): {
                                'InstanceRole': str,
                                'InstanceProfile': str,
                                'AdditionalIamPolicies': [
                                    {'Policy': str}
                                ]
                            },
                            Optional('GracetimePeriod'): And(int, lambda s: s > 0 and s <= 120) # optional, default value: 60 mins (max 120 mins)
                        }
                    ]
                }
            },
            # SlurmVersion:
            #     Latest tested version
            #     Critical security fix released in 21.08.8. Must be later than that.
            Optional('SlurmVersion', default=get_DEFAULT_SLURM_VERSION(config)): str,
            #
            # ClusterName:
            #     Default to the StackName
            Optional('ClusterName'): str,
            #
            # MungeKeySsmParameter:
            #     SSM String Parameter with a base64 encoded munge key to use for the cluster.
            #     Required if your submitters need to use more than 1 cluster.
            #     Will be created if it doesn't exist to save the value in Parameter Store.
            Optional('MungeKeySsmParameter', default='/slurm/munge_key'): str,
            #
            # SlurmCtl:
            #     Required, but can be an empty dict to accept all of the defaults
            'SlurmCtl': {
                # NumberOfControllers
                #     For high availability configure multiple controllers
                Optional('SlurmctldPort', default='6817'): str, # Needs to be a string because it can be a range of ports.
                Optional('SlurmctldPortMin', default=6817): int,
                Optional('SlurmctldPortMax', default=6817): int,
                Optional('SlurmdPort', default=6818): int,
                Optional('NumberOfControllers', default=1): And(Use(int), lambda n: 1 <= n <= 3),
                Optional('SubnetIds'): [
                    And(str, lambda subnetid: re.match('subnet-', subnetid))
                ],
                Optional('BaseHostname', default='slurmctl'): str,
                Optional('architecture', default='arm64'): And(str, lambda s: s in architectures),
                Optional('instance_type', default='c6g.large'): str,
                Optional('volume_size', default=200): int,
                #
                # SuspendAction:
                #     Set to stop or terminate.
                #     Stopped nodes will restart quicker, but you will continue to be charged for the EBS volumes
                #     attached to the instance.
                Optional('SuspendAction', default='stop'): And(str, lambda s: s in ['stop', 'terminate']),
                #
                # MaxStoppedDuration:
                #     In ISO 8601 duration format: https://en.wikipedia.org/wiki/ISO_8601#Durations
                #     Default: 1 hour = P0Y0M0DT1H0M0S
                #     Evaluated at least hourly by cron job.
                Optional('MaxStoppedDuration', default='P0Y0M0DT1H0M0S'): str,
                Optional('CloudWatchPeriod', default=5): int,
                Optional('PreemptMode', default='REQUEUE'): And(str, lambda s: s in ['OFF', 'CANCEL', 'GANG', 'REQUEUE', 'SUSPEND']),
                Optional('PreemptType', default='preempt/partition_prio'): And(str, lambda s: s in ['preempt/none', 'preempt/partition_prio', 'preempt/qos']),
                Optional('PreemptExemptTime', default='0'): str,
                #
                # SlurmConfOverrides:
                #     File that will be included at end of slurm.conf to override configuration parameters.
                Optional('SlurmConfOverrides'): str,
                Optional('SlurmrestdUid', default=901): int,
                Optional('SlurmrestdPort', default=6820): int,
                Optional('SlurmRestApiVersion', default=get_default_slurm_rest_api_version(config)): str,
            },
            #
            # The accounting database is required to enable fairshare scheduling
            # It is managed by the Slurm Database Daemon (slurmdbd) instance
            # The instance can be created as part of the cluster or can use an existing instance in a federation of clusters.
            #
            # SlurmDbd:
            #     It is recommended to get the basic cluster configured and working before enabling the accounting database
            Optional('SlurmdbdPort', default=6819): int,
            Optional('SlurmDbd'): {
                Optional('UseSlurmDbd', default=True): bool,
                Optional('Hostname', default='slurmdbd'): str,
                Optional('architecture', default='arm64'): And(str, lambda s: s in architectures),
                Optional('instance_type', default='m6g.large'): str,
                Optional('volume_size', default=200): int,
                Optional('database', default={'port': 3306}): {
                    'port': int,
                },
                Optional('subnets', default=[]): [
                    And(str, lambda s: re.match('subnet-', s))
                ]
            },
            #
            # ExistingSlurmDbd:
            #     Used for federated clusters that must share a common slurmdbd instance.
            Optional('ExistingSlurmDbd'): {
                Optional('UseSlurmDbd', default=True): bool,
                Optional('StackName'): str,
                Optional('SecurityGroup'): {str: And(str, lambda s: re.match('sg-', s))},
                Optional('HostnameFQDN'): str,
                Optional('Port', default=3306): int,
                Optional('UserName'): str,
                Optional('PasswordSecretArn'): And(str, lambda s: s.startswith('arn:')),
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
                    'arm64': str,
                    'x86_64': str,
                },
                #
                # BaseAmis:
                #     Customized AMIs with file system mounts, packages, etc. configured.
                #     If these aren't defined then the generic base AMIs are used.
                Optional('BaseAmis'): {
                    And(str, lambda s: s in valid_regions): { # region
                        And(str, lambda s: s in os_distributions): { # Distribution
                            And(int, lambda n: n in [2, 7, 8]): { # distribution_major_version
                                str: { # architecture
                                    'ImageId': And(str, lambda s: re.match('ami-', s)),
                                    Optional('RootDeviceSize'): str,
                                }
                            }
                        }
                    }
                },
            },
            #
            # SubmitterSecurityGroupIds:
            #     External security groups that should be able to use the cluster
            Optional('SubmitterSecurityGroupIds', default={}): {
                Optional(str): And(str, lambda s: re.match(r'sg-', s))
            },
            # SubmitterInstanceTags:
            #    Tags of instances configure to submit to the cluster. When the cluster is deleted the tag is used unmount the slurm filesystem from the instannces using SSM.
            Optional('SubmitterInstanceTags'): {str: [str]},
            #
            # InstanceConfig:
            #     Configure the instances used by the cluster
            #     A partition will be created for each combination of Base OS, Architecture, and Spot
            'InstanceConfig': {
                # UseSpot:
                #     Configure spot instances
                Optional('UseSpot', default=True): bool,
                'BaseOsArchitecture': {
                    And(str, lambda s: s in os_distributions): { # Distribution
                        And(int, lambda n: n in [2, 7, 8]): [ # distribution_major_version
                            And(str, lambda s: s in architectures) # architecture
                        ]
                    }
                },
                # Include*/Exclude*:
                #     Instance families and types are regular expressions with implicit '^' and '$' at the begining and end.
                #     Exclude patterns are processed first and take precesdence over any includes.
                #     An empty list is the same as '.*'.
                Optional('Exclude', default={'InstanceFamilies': default_excluded_instance_families, 'InstanceTypes': default_excluded_instance_types}): {
                    Optional('InstanceFamilies', default=default_excluded_instance_families): [str],
                    Optional('InstanceTypes', default=default_excluded_instance_types): [str]
                },
                Optional('Include', default={'MaxSizeOnly': False, 'InstanceFamilies': default_eda_instance_families, 'InstanceTypes': default_eda_instance_types}): {
                    # MaxSizeOnly:
                    #     If MaxSizeOnly is True then only the largest instance type in
                    #     a family will be included unless specific instance types are included.
                    #     Default: false
                    Optional('MaxSizeOnly', default=False): bool,
                    Optional('InstanceFamilies', default=default_eda_instance_families): [str],
                    Optional('InstanceTypes', default=default_eda_instance_types): [str]
                },
                'NodeCounts': {
                    Optional('DefaultMinCount', default=0): And(int, lambda s: s >= 0),
                    'DefaultMaxCount': And(int, lambda s: s >= 0),
                    Optional('ComputeResourceCounts', default={}): {
                        Optional(str): {
                            Optional('MinCount', default=0): And(int, lambda s: s >= 0),
                            'MaxCount': And(int, lambda s: s >= 0)
                        }
                    }
                },
                Optional('Regions'): {
                    str: {
                        'VpcId': And(str, lambda s: re.match('vpc-', s)),
                        'CIDR': str,
                        'SshKeyPair': str,
                        'AZs': [
                            {
                                'Priority': int,
                                'Subnet': And(str, lambda s: re.match('subnet-', s))
                            }
                        ],
                    }
                },
                Optional('AlwaysOnNodes', default=[]): [
                    str # Nodelist
                ],
                Optional('AlwaysOnPartitions', default=[]): [
                    str # Partitionlist
                ],
                Optional('OnPremComputeNodes'): {
                    'ConfigFile': str,
                    'CIDR': str,
                    Optional('Partition', default='onprem'): str,
                }
            },
            #
            # ElasticSearch:
            # Configure the ElasticSearch/OpenSearch domain used by the slurm cluster
            # If not specified then won't be created or used by the cluster.
            Optional('ElasticSearch'): {
                Optional('ebs_volume_size', default=20): int,
                Optional('ebs_volume_type', default='GP2'): str,
                Optional('enable_version_upgrade', default=False): bool,
                Optional('number_of_azs', default=2): int,
                Optional('master_nodes', default=2): int,
                Optional('master_node_instance_type', default='m5.large.search'): str,
                #
                # data_nodes:
                #     Must be a multiple of number_of_azs
                Optional('data_nodes', default=1): int,
                Optional('data_node_instance_type', default='m5.large.search'): str,
                Optional('warm_nodes', default=0): int,
                Optional('warm_instance_type', default='ultrawarm.medium.search'): str,
                Optional('subnets', default=[]): [
                    And(str, lambda s: re.match('subnet-', s))
                ]
            },
            #
            # JobCompType:
            #     Job completion database type.
            #     This is independent and separate from the slurmdbd results database and has less information.
            Optional('JobCompType', default='jobcomp/filetxt'): And(str, lambda s: s in ('jobcomp/none', 'jobcomp/elasticsearch', 'jobcomp/filetxt')),
            #
            # JobCompLoc:
            #     Used with jobcomp/elasticsearch
            #     A complete URL endpoint with format <host>:<port>/<target>/_doc
            #     http://{{EsDomain}}.{{Region}}.es.amazonaws.com/slurm/_doc
            Optional('JobCompLoc'): str,
            Optional('SlurmUid', default=900): int,
            Optional('storage'): {
                #
                # mount_path:
                # Default is /opt/slurm/{{cluster_name}}
                Optional('mount_path'): str,
                Optional('provider'): And(str, lambda s: s in ('efs', 'ontap', 'zfs')),
                #
                # removal_policy:
                # RETAIN will preserve the EFS even if you delete the stack.
                # Any other value will delete EFS if you delete the CFN stack
                Optional('removal_policy'): And(str, lambda s: s in ('DESTROY', 'RETAIN', 'SNAPSHOT')),
                Optional('kms_key_arn'): str,
                Optional('efs'): {
                    Optional('enable_automatic_backups', default=False): bool,
                    #
                    # lifecycle_policy
                    # https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-efs-filesystem-lifecyclepolicy.html
                    Optional('lifecycle_policy', default='AFTER_30_DAYS'): And(str, lambda s: s in filesystem_lifecycle_policies),
                    Optional('use_efs_helper', default=False): bool,
                    Optional('throughput_mode', default='BURSTING'): And(str, lambda s: s in ('BURSTING', 'PROVISIONED')),
                    #
                    # provisioned_throughput_per_second:
                    #     In MiB/s. Minimum value of 1
                    Optional('provisioned_throughput_per_second'): int,
                    Optional('performance_mode', default='GENERAL_PURPOSE'): And(str, lambda s: s in ('GENERAL_PURPOSE', 'MAX_IO')),
                    #
                    # encrypted
                    # https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-efs-filesystem.html#cfn-efs-filesystem-encrypted
                    Optional('encrypted', default=True): bool,
                    Optional('subnets', default=[]): [
                        And(str, lambda s: re.match('subnet-', s))
                    ]
                },
                Optional('ontap'): {
                    Optional('deployment_type', default='SINGLE_AZ_1'): And(str, lambda s: s in ('SINGLE_AZ_1', 'MULTI_AZ_1')),
                    Optional('storage_capacity', default=1024): And(int, lambda s: s >= 1024 and s <= 196608), # 1024 GiB up to 196,608 GiB (192 TiB)
                    Optional('iops'): int,
                    Optional('throughput_capacity', default=128): And(int, lambda s: s in [128, 256, 512, 1024, 2048]),
                    Optional('tiering_policy', default='AUTO'): And(str, lambda s: s in ('ALL', 'AUTO', 'NONE', 'SNAPSHOT_ONLY')),
                    Optional('cooling_period', default=31): And(int, lambda s: (s >= 2 and s <= 183)),
                    Optional('extra_subnet'): And(str, lambda s: re.match('subnet-', s)),
                },
                Optional('zfs'): {
                    Optional('storage_capacity', default=64): And(int, lambda s: s >= 64 and s <= 524288),
                    Optional('iops'): int,
                    Optional('throughput_capacity', default=64): And(int, lambda s: s in [64, 128, 256, 512, 1024, 2048, 3072, 4096]),
                    Optional('data_compression_type', default='ZSTD'): And(str, lambda s: s in ('NONE', 'ZSTD', 'LZ4')),
                },
                #
                # ExtraMounts
                # Additional mounts for compute nodes.
                # This can be used so the compute nodes have the same file structure as the remote desktops.
                Optional('ExtraMounts', default=[]): [
                    {
                        'dest': str,
                        'src': str,
                        'type': str,
                        'options': str,
                        Optional('StorageType'): And(str, lambda s: s in ('Efs', 'FsxLustre', 'FsxOntap', 'FsxOpenZfs')),
                        Optional('FileSystemId'): And(str, lambda s: s.startswith('fs-')),
                        Optional('VolumeId'): And(str, lambda s: s.startswith('fsvol-')),
                    }
                ],
                # ExtraMountSecurityGroups
                Optional('ExtraMountSecurityGroups', default={}): {
                    Optional(Or('nfs', 'zfs', 'lustre')): {
                        str: And(str, lambda s: re.match(r'sg-', s))
                    }
                },
                # ExtraMountCidrs
                Optional('ExtraMountCidrs', default={}): {
                    Optional(Or('nfs', 'zfs', 'lustre')): {
                        str: And(str, lambda s: re.match(r'\d+\.\d+\.\d+\.\d+/\d+', s))
                    }
                }
            },
        },
        Optional('Licenses', default={}): {
            Optional(str): { # License name: for example VCSCompiler_Net, VCSMXRunTime_Net
                'Count': int,
                Optional('Server'): str,
                Optional('Port'): str,
                Optional('ServerType'): str,
                Optional('StatusScript'): str,
            }
        },
        Optional('AmiMap', default={}): {
            #str: { # Region
            And(str, lambda s: s in valid_regions, error=f"Invalid region. valid_regions={valid_regions}"): { # Region
                And(str, lambda s: s in os_distributions): { # Distribution
                    And(int, lambda n: n in [2, 7, 8]): { # distribution_major_version
                        And(str, lambda s: s in architectures): {
                            'ImageId': str,
                            'RootDeviceName': str
                        }
                    }
                }
            }
        }
    }
)

def check_schema(config_in):
    # Validate config against schema
    config_schema = get_config_schema(config_in)
    validated_config = config_schema.validate(config_in)
    return validated_config
