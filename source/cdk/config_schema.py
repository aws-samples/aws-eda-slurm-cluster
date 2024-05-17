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
# Releases: https://github.com/aws/aws-parallelcluster/releases
# 3.2.0:
#     * Add support for memory-based job scheduling in Slurm
# 3.3.0:
#     * Add support for multiple instance types in a compute resource
#     * Add new configuration section Scheduling/SlurmSettings/Database to enable accounting functionality in Slurm.
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
# 3.7.0:
#     * Login Nodes
#     * Add support for configurable node weights within queue
#     * Allow memory-based scheduling when multiple instance types are specified for a Slurm Compute Resource.
# 3.7.1:
#     * Fix pmix CVE
#     * Use Slurm 23.02.5
# 3.8.0:
#     * Add support for Rocky Linux 8
#     * Add support for user-provided /home directory for the cluster
#     * Add support for MungeKeySecretArn to permit user-provided Munge key.
#     * Add head node alarms
#     * Add support for il-central-1 region
#     * Upgrade Slurm from 23.02.6 to 23.02.7
# 3.9.0:
#     * Add support for RHEL9
#     * Add support for Rocky9
#     * Upgrade Slurm from 23.02.7 to 23.11.4
#     * Upgrade Pmix from 4.2.6 to 4.2.9.
# 3.9.1:
#     * Bug fixes
MIN_PARALLEL_CLUSTER_VERSION = parse_version('3.6.0')
# Update source/resources/default_config.yml with latest version when this is updated.
PARALLEL_CLUSTER_VERSIONS = [
    '3.6.0',
    '3.6.1',
    '3.7.0',
    '3.7.1',
    '3.7.2',
    '3.8.0',
    '3.9.0',
    '3.9.1',
]
PARALLEL_CLUSTER_MUNGE_VERSIONS = {
    # This can be found on the head node at /opt/parallelcluster/sources
    # This can be found on the head node at /etc/chef/local-mode-cache/cache/
    '3.6.0':   '0.5.15', # confirmed
    '3.6.1':   '0.5.15', # confirmed
    '3.7.0':   '0.5.15', # confirmed
    '3.7.1':   '0.5.15', # confirmed
    '3.7.2':   '0.5.15', # confirmed
    '3.8.0':   '0.5.15', # confirmed
    '3.9.0':   '0.5.15', # confirmed
    '3.9.1':   '0.5.15', # confirmed
}
PARALLEL_CLUSTER_PYTHON_VERSIONS = {
    # This can be found on the head node at /opt/parallelcluster/pyenv/versions
    '3.6.0':   '3.9.16', # confirmed
    '3.6.1':   '3.9.16', # confirmed
    '3.7.0':   '3.9.16', # confirmed
    '3.7.1':   '3.9.16', # confirmed
    '3.7.2':   '3.9.16', # confirmed
    '3.8.0':   '3.9.17', # confirmed
    '3.9.0':   '3.9.17', # confirmed
    '3.9.1':   '3.9.17', # confirmed
}
PARALLEL_CLUSTER_SLURM_VERSIONS = {
    # This can be found on the head node at /etc/chef/local-mode-cache/cache/
    '3.6.0':   '23.02.2', # confirmed
    '3.6.1':   '23.02.2', # confirmed
    '3.7.0':   '23.02.4', # confirmed
    '3.7.1':   '23.02.5', # confirmed
    '3.7.2':   '23.02.6', # confirmed
    '3.8.0':   '23.02.7', # confirmed
    '3.9.0':   '23.11.4', # confirmed
    '3.9.1':   '23.11.4', # confirmed
}
PARALLEL_CLUSTER_PC_SLURM_VERSIONS = {
    # This can be found on the head node at /etc/chef/local-mode-cache/cache/
    '3.6.0':   '23-02-2-1', # confirmed
    '3.6.1':   '23-02-2-1', # confirmed
    '3.7.0':   '23-02-4-1', # confirmed
    '3.7.1':   '23-02-5-1', # confirmed
    '3.7.2':   '23-02-6-1', # confirmed
    '3.8.0':   '23-02-6-1', # confirmed
    '3.9.0':   '23-11-4-1', # confirmed
    '3.9.1':   '23-11-4-1', # confirmed
}
SLURM_REST_API_VERSIONS = {
    '23-02-2-1': '0.0.39',
    '23-02-3-1': '0.0.39',
    '23-02-4-1': '0.0.39',
    '23-02-5-1': '0.0.39',
    '23-02-6-1': '0.0.39',
    '23-02-7-1': '0.0.39',
    '23-11-4-1': '0.0.39',
}
PARALLEL_CLUSTER_ALLOWED_OSES = [
    'alinux2',
    'centos7',
    'rhel8',
    'rhel9',
    'rocky8',
    'rocky9',
    'ubuntu2004',
    'ubuntu2204'
    ]

def get_parallel_cluster_version(config):
    parallel_cluster_version = config['slurm']['ParallelClusterConfig']['Version']
    if parallel_cluster_version not in PARALLEL_CLUSTER_VERSIONS:
        logger.error(f"Unsupported ParallelCluster version: {parallel_cluster_version}\nSupported versions are:\n{json.dumps(PARALLEL_CLUSTER_VERSIONS, indent=4)}")
        raise KeyError(parallel_cluster_version)
    return parallel_cluster_version

def get_PARALLEL_CLUSTER_MUNGE_VERSION(config):
    parallel_cluster_version = get_parallel_cluster_version(config)
    return PARALLEL_CLUSTER_MUNGE_VERSIONS[parallel_cluster_version]

def get_PARALLEL_CLUSTER_PYTHON_VERSION(config):
    parallel_cluster_version = get_parallel_cluster_version(config)
    return PARALLEL_CLUSTER_PYTHON_VERSIONS[parallel_cluster_version]

def get_SLURM_VERSION(config):
    parallel_cluster_version = get_parallel_cluster_version(config)
    return PARALLEL_CLUSTER_SLURM_VERSIONS[parallel_cluster_version]

def get_PC_SLURM_VERSION(config):
    parallel_cluster_version = get_parallel_cluster_version(config)
    return PARALLEL_CLUSTER_PC_SLURM_VERSIONS[parallel_cluster_version]

def get_slurm_rest_api_version(config):
    slurm_version = get_PC_SLURM_VERSION(config)
    return SLURM_REST_API_VERSIONS.get(slurm_version, )

# Feature support

def MAX_NUMBER_OF_QUEUES(parallel_cluster_version):
    return 50

def MAX_NUMBER_OF_COMPUTE_RESOURCES(parallel_cluster_version):
    return 50

def MAX_NUMBER_OF_COMPUTE_RESOURCES_PER_QUEUE(parallel_cluster_version):
    return 50

# Version 3.7.0:
PARALLEL_CLUSTER_SUPPORTS_LOGIN_NODES_VERSION = parse_version('3.7.0')
def PARALLEL_CLUSTER_SUPPORTS_LOGIN_NODES(parallel_cluster_version):
    return parallel_cluster_version >= PARALLEL_CLUSTER_SUPPORTS_LOGIN_NODES_VERSION

PARALLEL_CLUSTER_SUPPORTS_MULTIPLE_COMPUTE_RESOURCES_PER_QUEUE_VERSION = parse_version('3.7.0')
def PARALLEL_CLUSTER_SUPPORTS_MULTIPLE_COMPUTE_RESOURCES_PER_QUEUE(parallel_cluster_version):
    return parallel_cluster_version >= PARALLEL_CLUSTER_SUPPORTS_MULTIPLE_COMPUTE_RESOURCES_PER_QUEUE_VERSION

PARALLEL_CLUSTER_SUPPORTS_MULTIPLE_INSTANCE_TYPES_PER_COMPUTE_RESOURCE_VERSION = parse_version('3.7.0')
def PARALLEL_CLUSTER_SUPPORTS_MULTIPLE_INSTANCE_TYPES_PER_COMPUTE_RESOURCE(parallel_cluster_version):
    return parallel_cluster_version >= PARALLEL_CLUSTER_SUPPORTS_MULTIPLE_INSTANCE_TYPES_PER_COMPUTE_RESOURCE_VERSION

PARALLEL_CLUSTER_SUPPORTS_NODE_WEIGHTS_VERSION = parse_version('3.7.0')
def PARALLEL_CLUSTER_SUPPORTS_NODE_WEIGHTS(parallel_cluster_version):
    return parallel_cluster_version >= PARALLEL_CLUSTER_SUPPORTS_NODE_WEIGHTS_VERSION

# Version 3.8.0

PARALLEL_CLUSTER_SUPPORTS_CUSTOM_ROCKY_8_VERSION = parse_version('3.8.0')
def PARALLEL_CLUSTER_SUPPORTS_CUSTOM_ROCKY_8(parallel_cluster_version):
    return parallel_cluster_version >= PARALLEL_CLUSTER_SUPPORTS_CUSTOM_ROCKY_8_VERSION

PARALLEL_CLUSTER_SUPPORTS_CUSTOM_MUNGE_KEY_VERSION = parse_version('3.8.0')
def PARALLEL_CLUSTER_SUPPORTS_CUSTOM_MUNGE_KEY(parallel_cluster_version):
    return parallel_cluster_version >= PARALLEL_CLUSTER_SUPPORTS_CUSTOM_MUNGE_KEY_VERSION

PARALLEL_CLUSTER_SUPPORTS_HOME_MOUNT_VERSION = parse_version('3.8.0')
def PARALLEL_CLUSTER_SUPPORTS_HOME_MOUNT(parallel_cluster_version):
    return parallel_cluster_version >= PARALLEL_CLUSTER_SUPPORTS_HOME_MOUNT_VERSION

# Determine all AWS regions available on the account.
default_region = environ.get("AWS_DEFAULT_REGION", "us-east-1")
ec2_client = boto3.client("ec2", region_name=default_region)
try:
    # describe_regions only describes the regions that are enabled for your account unless AllRegions is set.
    valid_regions = [region["RegionName"] for region in ec2_client.describe_regions(AllRegions=True)["Regions"]]
except ClientError as err:
    logger.error(f"{fg('red')}Unable to list all AWS regions. Make sure you have set your IAM credentials. {err} {attr('reset')}")
    exit(1)

VALID_ARCHITECTURES = ['arm64', 'x86_64']

DEFAULT_ARCHITECTURE = 'x86_64'

# Controller needs at least 4 GB  or will hit OOM

DEFAULT_ARM_CONTROLLER_INSTANCE_TYPE = 'c6g.large'

DEFAULT_X86_CONTROLLER_INSTANCE_TYPE = 'c6a.large'

def default_controller_instance_type(config):
    architecture = config['slurm']['ParallelClusterConfig'].get('Architecture', DEFAULT_ARCHITECTURE)
    if architecture == 'x86_64':
        return DEFAULT_X86_CONTROLLER_INSTANCE_TYPE
    elif architecture == 'arm64':
        return DEFAULT_ARM_CONTROLLER_INSTANCE_TYPE
    else:
        raise ValueError(f"Invalid architecture: {architecture}")

DEFAULT_ARM_OS = 'rhel8'

DEFAULT_X86_OS = 'rhel8'

def DEFAULT_OS(config):
    architecture = config['slurm']['ParallelClusterConfig'].get('Architecture', DEFAULT_ARCHITECTURE)
    if architecture == 'x86_64':
        return DEFAULT_X86_OS
    elif architecture == 'arm64':
        return DEFAULT_ARM_OS
    else:
        raise ValueError(f"Invalid architecture: {architecture}")

filesystem_lifecycle_policies = [
    'None',
    'AFTER_14_DAYS',
    'AFTER_30_DAYS',
    'AFTER_60_DAYS',
    'AFTER_7_DAYS',
    'AFTER_90_DAYS'
    ]

# By default I've chosen to exclude *7i instance types because they have 50% of the cores as *7z instances with the same memory.
default_eda_instance_families = [
    'c7a',               # AMD EPYC 9R14 Processor 3.7 GHz

    'c7g',               # AWS Graviton3 Processor 2.6 GHz
    # 'c7gd',              # AWS Graviton3 Processor 2.6 GHz
    # 'c7gn',              # AWS Graviton3 Processor 2.6 GHz

    # 'c7i',               # Intel Xeon Scalable (Sapphire Rapids) 3.2 GHz

    #'f1',                # Intel Xeon E5-2686 v4 (Broadwell) 2.3 GHz

    'm5zn',              # Intel Xeon Platinum 8252 4.5 GHz

    'm7a',               # AMD EPYC 9R14 Processor 3.7 GHz

    # 'm7i',               # Intel Xeon Scalable (Sapphire Rapids) 3.2 GHz

    'm7g',               # AWS Graviton3 Processor 2.6 GHz
    # 'm7gd',               # AWS Graviton3 Processor 2.6 GHz

    'r7a',               # AMD EPYC 9R14 Processor 3.7 GHz

    'r7g',               # AWS Graviton3 Processor 2.6 GHz
    # 'r7gd',               # AWS Graviton3 Processor 2.6 GHz

    # 'r7i',               # Intel Xeon Scalable (Sapphire Rapids) 3.2 GHz

    'r7iz',              # Intel Xeon Scalable (Sapphire Rapids) 3.2 GHz

    'x2gd',              # AWS Graviton2 Processor 2.5 GHz 1TB

    'x2idn',             # Intel Xeon Scalable (Icelake) 3.5 GHz 2 TB

    'x2iedn',            # Intel Xeon Scalable (Icelake) 3.5 GHz 4 TB

    'x2iezn',            # Intel Xeon Platinum 8252 4.5 GHz 1.5 TB

    'u',
    #'u-6tb1',            # Intel Xeon Scalable (Skylake) 6 TB
    #'u-9tb1',            # Intel Xeon Scalable (Skylake) 9 TB
    #'u-12tb1',           # Intel Xeon Scalable (Skylake) 12 TB
]

old_eda_instance_families = [
    'c5',                # Mixed depending on size
    'c5a',               # AMD EPYC 7R32 3.3 GHz
    'c5ad',              # AMD EPYC 7R32 3.3 GHz
    'c6a',
    'c6ad',
    'c6i',               # Intel Xeon 8375C (Ice Lake) 3.5 GHz
    'c6id',
    'c6g',               # AWS Graviton2 Processor 2.5 GHz
    'c6gd',              # AWS Graviton2 Processor 2.5 GHz
    'f1',                # Intel Xeon E5-2686 v4 (Broadwell) 2.3 GHz
    'm5',                # Intel Xeon Platinum 8175 (Skylake) 3.1 GHz
    'm5d',               # Intel Xeon Platinum 8175 (Skylake) 3.1 GHz
    'm5a',               # AMD EPYC 7571 2.5 GHz
    'm5ad',              # AMD EPYC 7571 2.5 GHz
    'm5zn',              # Intel Xeon Platinum 8252 4.5 GHz
    'm6a',               # AMD EPYC 7R13 Processor 3.6 GHz
    'm6ad',
    'm6i',               # Intel Xeon 8375C (Ice Lake) 3.5 GHz
    'm6id',
    'm6g',               # AWS Graviton2 Processor 2.5 GHz
    'm6gd',              # AWS Graviton2 Processor 2.5 GHz
    'r5',                # Intel Xeon Platinum 8175 (Skylake) 3.1 GHz
    'r5d',               # Intel Xeon Platinum 8175 (Skylake) 3.1 GHz
    'r5b',               # Intel Xeon Platinum 8259 (Cascade Lake) 3.1 GHz
    'r5a',               # AMD EPYC 7571 2.5 GHz
    'r5ad',              # AMD EPYC 7571 2.5 GHz
    'r6a',
    'r6i',               # Intel Xeon 8375C (Ice Lake) 3.5 GHz 1TB
    'r6id',
    'r6g',               # AWS Graviton2 Processor 2.5 GHz
    'r6gd',              # AWS Graviton2 Processor 2.5 GHz
    'x1',                # High Frequency Intel Xeon E7-8880 v3 (Haswell) 2.3 GHz 2TB
    'x1e',               # High Frequency Intel Xeon E7-8880 v3 (Haswell) 2.3 GHz 4TB
    'x2gd',              # AWS Graviton2 Processor 2.5 GHz 1TB
    'x2idn',             # Intel Xeon Scalable (Icelake) 3.5 GHz 2 TB
    'x2iedn',            # Intel Xeon Scalable (Icelake) 3.5 GHz 4 TB
    'x2iezn',            # Intel Xeon Platinum 8252 4.5 GHz 1.5 TB
    'z1d',               # Intel Xeon Platinum 8151 4.0 GHz
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
    '.*\.metal.*',

    # Reduce the number of selected instance types to 25.
    # Exclude larger core counts for each memory size
    # 2 GB:
    'c7a.medium',
    'c7g.medium',
    # 4 GB: m7a.medium, m7g.medium
    'c7a.large',
    'c7g.large',
    # 8 GB: r7a.medium, r7g.medium
    'm5zn.large',
    'm7a.large',
    'm7g.large',
    'c7a.xlarge',
    'c7g.xlarge',
    # 16 GB: r7a.large, x2gd.medium, r7g.large
    'r7iz.large',
    'm5zn.xlarge',
    'm7a.xlarge',
    'm7g.xlarge',
    'c7a.2xlarge',
    'c7g.2xlarge',
    # 32 GB: r7a.xlarge, x2gd.large, r7g.xlarge
    'r7iz.xlarge',
    'm5zn.2xlarge',
    'm7a.2xlarge',
    'm7g.2xlarge',
    'c7a.4xlarge',
    'c7g.4xlarge',
    # 64 GB: r7a.2xlarge, x2gd.xlarge, r7g.2xlarge
    'r7iz.2xlarge',
    'm7a.4xlarge',
    'm7g.4xlarge',
    'c7a.8xlarge',
    'c7g.8xlarge',
    # 96 GB:
    'm5zn.6xlarge',
    'c7a.12xlarge',
    'c7g.12xlarge',
    # 128 GB: x2iedn.xlarge, r7iz.4xlarge, x2gd.2xlarge, r7g.4xlarge
    'r7a.4xlarge',
    'm7a.8xlarge',
    'm7g.8xlarge',
    'c7a.16xlarge',
    'c7g.8xlarge',
    # 192 GB: m5zn.12xlarge, m7a.12xlarge, m7g.12xlarge
    'c7a.24xlarge',
    # 256 GB: x2iedn.2xlarge, x2iezn.2xlarge, x2gd.4xlarge, r7g.8xlarge
    'r7iz.8xlarge',
    'r7a.8xlarge',
    'm7a.16xlarge',
    'm7g.16xlarge',
    'c7a.32xlarge',
    # 384 GB: 'r7iz.12xlarge', r7g.12xlarge
    'r7a.12xlarge',
    'm7a.24xlarge',
    'c7a.48xlarge',
    # 512 GB: x2iedn.4xlarge, x2iezn.4xlarge, x2gd.8xlarge, r7g.16xlarge
    'r7iz.16xlarge',
    'r7a.16xlarge',
    'm7a.32xlarge',
    # 768 GB: r7a.24xlarge, x2gd.12xlarge
    'x2iezn.6xlarge',
    'm7a.48xlarge',
    # 1024 GB: x2iedn.8xlarge, x2iezn.8xlarge, x2gd.16xlarge
    'r7iz.32xlarge',
    'r7a.32xlarge',
    # 1536 GB: x2iezn.12xlarge, x2idn.24xlarge
    'r7a.48xlarge',
    # 2048 GB: x2iedn.16xlarge
    'x2idn.32xlarge',
    # 3072 GB: 'x2iedn.24xlarge',
    # 4096 GB: x2iedn.32xlarge
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
        Optional('StackName', default='slurm-config'): str,
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
        Optional('TimeZone', default='US/Central'): str,
        Optional('RESEnvironmentName'): str,
        'slurm': {
            Optional('ParallelClusterConfig'): {
                Optional('Enable', default=True): And(bool, lambda s: s == True),
                'Version': And(str, lambda version: version in PARALLEL_CLUSTER_VERSIONS, lambda version: parse_version(version) >= MIN_PARALLEL_CLUSTER_VERSION),
                Optional('ClusterConfig'): lambda s: True,
                Optional('Image', default={'Os': DEFAULT_OS(config)}): {
                    'Os': And(str, lambda s: s in PARALLEL_CLUSTER_ALLOWED_OSES),
                    # CustomAmi: AMI to use for head and compute nodes instead of the pre-built AMIs.
                    Optional('CustomAmi'): And(str, lambda s: s.startswith('ami-')),
                },
                Optional('Architecture', default=DEFAULT_ARCHITECTURE): And(str, lambda s: s in VALID_ARCHITECTURES),
                Optional('ComputeNodeAmi'): And(str, lambda s: s.startswith('ami-')),
                Optional('DisableSimultaneousMultithreading', default=True): bool,
                # Recommend to not use EFA unless necessary to avoid insufficient capacity errors when starting new instances in group or when multiple instance types in the group
                # See https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/placement-groups.html#placement-groups-cluster
                Optional('EnableEfa', default=False): bool,
                Optional('Database'): {
                    Optional('DatabaseStackName'): str,
                    Optional('FQDN'): str,
                    Optional('Port'): int,
                    Optional('AdminUserName'): str,
                    Optional('AdminPasswordSecretArn'): And(str, lambda s: s.startswith('arn:')),
                    Optional('ClientSecurityGroup'): {str: And(str, lambda s: re.match('sg-', s))},
                },
                Optional('Dcv', default={}): {
                    Optional('Enabled', default=False): bool,
                    Optional('Port', default=8443): int,
                    Optional('AllowedIps'): str # Can't set a default without knowing the VPC's CIDR range.
                },
                Optional('LoginNodes'): {
                    'Pools': [
                        {
                            'Name': str,
                            'Count': int,
                            'InstanceType': str,
                            Optional('GracetimePeriod'): And(int, lambda s: s > 0 and s <= 120), # optional, default value: 60 mins (max 120 mins)
                            Optional('Image'): {
                                'CustomAmi': And(str, lambda s: s.startswith('ami-'))
                            },
                            Optional('Ssh'): {
                                'KeyName': str # default value: same ssh key used for the Head Node
                            },
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
                            Optional('Iam'): {
                                'InstanceRole': str,
                                'InstanceProfile': str,
                                'AdditionalIamPolicies': [
                                    {'Policy': str}
                                ]
                            },
                        }
                    ]
                }
            },
            #
            # ClusterName:
            #     Name of the ParallelCluster cluster.
            #     Default:
            #         If StackName ends with "-config" then ClusterName is StackName with "-config" stripped off.
            #         Otherwise add "-cl" to end of StackName.
            Optional('ClusterName'): And(str, lambda s: s != config['StackName']),
            #
            # MungeKeySecret:
            #     AWS secret with a base64 encoded munge key to use for the cluster.
            #     For an existing secret can be the secret name or the ARN.
            #     If the secret doesn't exist one will be created, but won't be part of the cloudformation stack
            #     so that it won't be deleted when the stack is deleted.
            #     Required if your submitters need to use more than 1 cluster.
            Optional('MungeKeySecret', default='/slurm/munge_key'): str,
            #
            # SlurmCtl:
            #     Required, but can be an empty dict to accept all of the defaults
            'SlurmCtl': {
                Optional('SlurmdPort', default=6818): int,
                Optional('instance_type', default=default_controller_instance_type(config)): str,
                Optional('volume_size', default=200): int,
                Optional('CloudWatchPeriod', default=5): int,
                Optional('PreemptMode', default='REQUEUE'): And(str, lambda s: s in ['OFF', 'CANCEL', 'GANG', 'REQUEUE', 'SUSPEND']),
                Optional('PreemptType', default='preempt/partition_prio'): And(str, lambda s: s in ['preempt/none', 'preempt/partition_prio', 'preempt/qos']),
                Optional('PreemptExemptTime', default='0'): str,
                #
                # SlurmConfOverrides:
                #     File that will be included at end of slurm.conf to override configuration parameters.
                Optional('SlurmConfOverrides'): str,
                Optional('SlurmrestdUid', default=901): int,
                Optional('SlurmRestApiVersion', default=get_slurm_rest_api_version(config)): str,
                Optional('AdditionalSecurityGroups'): [
                    And(str, lambda s: s.startswith('sg-'))
                ],
                Optional('AdditionalIamPolicies'): [
                    str
                ],
                Optional('Imds', default={'Secured': True}): {
                    Optional('Secured', default=True): bool
                }
            },
            # SubmitterInstanceTags:
            #    Tags of instances that can be configured to submit to the cluster.
            #    When the cluster is deleted, the tag is used to unmount the slurm filesystem from the instances using SSM.
            Optional('SubmitterInstanceTags'): {str: [str]},
            #
            # InstanceConfig:
            #     Configure the instances used by the cluster
            #     A partition will be created for each combination of Base OS, Architecture, and Spot
            'InstanceConfig': {
                # UseSpot:
                #     Configure spot instances
                Optional('UseSpot', default=True): bool,
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
                Optional('AdditionalSecurityGroups'): [
                    And(str, lambda s: s.startswith('sg-'))
                ],
                Optional('AdditionalIamPolicies'): [
                    str
                ],
                Optional('OnPremComputeNodes'): {
                    'ConfigFile': str,
                    'CIDR': str,
                    Optional('Partition', default='onprem'): str,
                }
            },
            Optional('SlurmUid', default=900): int,
            Optional('storage'): {
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
        }
    }
)

def check_schema(config_in):
    # Validate config against schema
    config_schema = get_config_schema(config_in)
    validated_config = config_schema.validate(config_in)
    return validated_config
