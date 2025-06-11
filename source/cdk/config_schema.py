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

from aws_cdk import (
    aws_lambda as aws_lambda
)
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
# 3.9.2:
#     * Upgrade Slurm to 23.11.7 (from 23.11.4).
# 3.9.3:
#     * Add support for FSx Lustre as a shared storage type in us-iso-east-1.
#     * Bug fixes
# 3.10.0:
#     * Add new configuration section Scheduling/SlurmSettings/ExternalSlurmdbd to connect the cluster to an external Slurmdbd
#     * CentOS 7 is no longer supported.
#     * Upgrade munge to version 0.5.16 (from 0.5.15).
#     * Upgrade Python to 3.9.19 (from 3.9.17).
# 3.10.1:
#     * Build fix for China regions
# 3.11.0:
#     * Add support for ap-southeast-3
#     * login node enhancements
# 3.11.1:
#     * Disable Pyxis Spack plugin by default
#     * Upgrade Python runtime to 3.12
#     * Upgrade libjwt to version 1.17.0.
# 3.12.0:
#     * OpenZFS security group requirements fixed.
# 3.13.0:
#     * Upgrade Slurm to 24.05.07
#     * Upgrade to Python 3.12.8
# 3.13.1:
#     * Upgrade Slurm to 24.05.08
#     * EFS utils to fix Rocky builds
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
    '3.9.2',
    '3.9.3',
    '3.10.0',
    '3.10.1',
    '3.11.0',
    '3.11.1',
    '3.12.0',
    '3.13.0',
    '3.13.1',
]
PARALLEL_CLUSTER_ENROOT_VERSIONS = {
    # This can be found on the head node by running 'yum info enroot'
    '3.11.0':  '3.4.1', # confirmed
    '3.11.1':  '3.4.1', # confirmed
    '3.12.0':  '3.4.1', # confirmed
    '3.13.0':  '3.4.1', # confirmed
    '3.13.1':  '3.4.1', # confirmed
}
PARALLEL_CLUSTER_PYXIS_VERSIONS = {
    # This can be found on the head node at /opt/parallelcluster/sources
    '3.11.0':  '0.20.0', # confirmed
    '3.11.1':  '0.20.0', # confirmed
    '3.12.0':  '0.20.0', # confirmed
    '3.13.0':  '0.20.0', # confirmed
    '3.13.1':  '0.20.0', # confirmed
}
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
    '3.9.2':   '0.5.15', # confirmed
    '3.9.3':   '0.5.15', # confirmed
    '3.10.0':  '0.5.16', # confirmed
    '3.10.1':  '0.5.16', # confirmed
    '3.11.0':  '0.5.16', # confirmed
    '3.11.1':  '0.5.16', # confirmed
    '3.12.0':  '0.5.16', # confirmed
    '3.13.0':  '0.5.16', # confirmed
    '3.13.1':  '0.5.16', # confirmed
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
    '3.9.2':   '3.9.17', # confirmed
    '3.9.3':   '3.9.17', # confirmed
    '3.10.0':  '3.9.19', # confirmed
    '3.10.1':  '3.9.19', # confirmed
    '3.11.0':  '3.9.20', # confirmed
    '3.11.1':  '3.9.20', # confirmed
    '3.12.0':  '3.9.20', # confirmed
    '3.13.0':  '3.12.0', # confirmed
    '3.13.1':  '3.12.8', # confirmed
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
    '3.9.2':   '23.11.7', # confirmed
    '3.9.3':   '23.11.7', # confirmed
    '3.10.0':  '23.11.7', # confirmed
    '3.10.1':  '23.11.7', # confirmed
    '3.11.0':  '23.11.10', # confirmed
    '3.11.1':  '23.11.10', # confirmed
    '3.12.0':  '23.11.10', # confirmed
    '3.13.0':  '24.05.7',  # confirmed
    '3.13.1':  '24.05.8',  # confirmed
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
    '3.9.2':   '23-11-7-1', # confirmed
    '3.9.3':   '23-11-7-1', # confirmed
    '3.10.0':  '23-11-7-1', # confirmed
    '3.10.1':  '23-11-7-1', # confirmed
    '3.11.0':  '23-11-10-1', # confirmed
    '3.11.1':  '23-11-10-1', # confirmed
    '3.12.0':  '23-11-10-1', # confirmed
    '3.13.0':  '24-05-7-1',  # confirmed
    '3.13.1':  '24-05-8-1',  # confirmed
}
SLURM_REST_API_VERSIONS = {
    '23-02-2-1': '0.0.39',
    '23-02-3-1': '0.0.39',
    '23-02-4-1': '0.0.39',
    '23-02-5-1': '0.0.39',
    '23-02-6-1': '0.0.39',
    '23-02-7-1': '0.0.39',
    '23-11-4-1': '0.0.39',
    '23-11-7-1': '0.0.39',
    '23-11-10-1': '0.0.39',
    '24-05-7-1': '0.0.39',
    '24-05-8-1': '0.0.39',
}

def get_parallel_cluster_version(config):
    parallel_cluster_version = config['slurm']['ParallelClusterConfig']['Version']
    if parallel_cluster_version not in PARALLEL_CLUSTER_VERSIONS:
        logger.error(f"Unsupported ParallelCluster version: {parallel_cluster_version}\nSupported versions are:\n{json.dumps(PARALLEL_CLUSTER_VERSIONS, indent=4)}")
        raise KeyError(parallel_cluster_version)
    return parallel_cluster_version

PARALLEL_CLUSTER_SUPPORTS_CENTOS_7_MIN_VERSION = MIN_PARALLEL_CLUSTER_VERSION
PARALLEL_CLUSTER_SUPPORTS_CENTOS_7_DEPRECATED_VERSION = parse_version('3.10.0')
def PARALLEL_CLUSTER_SUPPORTS_CENTOS_7(parallel_cluster_version):
    return parallel_cluster_version >= PARALLEL_CLUSTER_SUPPORTS_CENTOS_7_MIN_VERSION and parallel_cluster_version < PARALLEL_CLUSTER_SUPPORTS_CENTOS_7_DEPRECATED_VERSION

PARALLEL_CLUSTER_SUPPORTS_RHEL_8_MIN_VERSION = parse_version('3.6.0')
def PARALLEL_CLUSTER_SUPPORTS_RHEL_8(parallel_cluster_version):
    return parallel_cluster_version >= PARALLEL_CLUSTER_SUPPORTS_RHEL_8_MIN_VERSION

PARALLEL_CLUSTER_SUPPORTS_ROCKY_8_MIN_VERSION = parse_version('3.8.0')
def PARALLEL_CLUSTER_SUPPORTS_ROCKY_8(parallel_cluster_version):
    return parallel_cluster_version >= PARALLEL_CLUSTER_SUPPORTS_ROCKY_8_MIN_VERSION

PARALLEL_CLUSTER_SUPPORTS_RHEL_9_MIN_VERSION = parse_version('3.9.0')
def PARALLEL_CLUSTER_SUPPORTS_RHEL_9(parallel_cluster_version):
    return parallel_cluster_version >= PARALLEL_CLUSTER_SUPPORTS_RHEL_9_MIN_VERSION

PARALLEL_CLUSTER_SUPPORTS_ROCKY_9_MIN_VERSION = parse_version('3.9.0')
def PARALLEL_CLUSTER_SUPPORTS_ROCKY_9(parallel_cluster_version):
    return parallel_cluster_version >= PARALLEL_CLUSTER_SUPPORTS_ROCKY_9_MIN_VERSION

PARALLEL_CLUSTER_SUPPORTS_AMAZON_LINUX_2023_MIN_VERSION = parse_version('3.10.0')
def PARALLEL_CLUSTER_SUPPORTS_AMAZON_LINUX_2023(parallel_cluster_version):
    return parallel_cluster_version >= PARALLEL_CLUSTER_SUPPORTS_AMAZON_LINUX_2023_MIN_VERSION

def get_PARALLEL_CLUSTER_ALLOWED_OSES(config):
    allowed_oses = [
    'alinux2',
    'ubuntu2004',
    'ubuntu2204'
    ]
    parallel_cluster_version = parse_version(get_parallel_cluster_version(config))
    if PARALLEL_CLUSTER_SUPPORTS_AMAZON_LINUX_2023(parallel_cluster_version):
        allowed_oses.append('alinux2023')
    if PARALLEL_CLUSTER_SUPPORTS_CENTOS_7(parallel_cluster_version):
        allowed_oses.append('centos7')
    if PARALLEL_CLUSTER_SUPPORTS_RHEL_8(parallel_cluster_version):
        allowed_oses.append('rhel8')
    if PARALLEL_CLUSTER_SUPPORTS_RHEL_9(parallel_cluster_version):
        allowed_oses.append('rhel9')
    if PARALLEL_CLUSTER_SUPPORTS_ROCKY_8(parallel_cluster_version):
        allowed_oses.append('rocky8')
    if PARALLEL_CLUSTER_SUPPORTS_ROCKY_9(parallel_cluster_version):
        allowed_oses.append('rocky9')
    return sorted(allowed_oses)

def get_PARALLEL_CLUSTER_MUNGE_VERSION(config):
    parallel_cluster_version = get_parallel_cluster_version(config)
    return PARALLEL_CLUSTER_MUNGE_VERSIONS[parallel_cluster_version]

def get_PARALLEL_CLUSTER_ENROOT_VERSION(config):
    parallel_cluster_version = get_parallel_cluster_version(config)
    return PARALLEL_CLUSTER_ENROOT_VERSIONS[parallel_cluster_version]

def get_PARALLEL_CLUSTER_PYXIS_VERSION(config):
    parallel_cluster_version = get_parallel_cluster_version(config)
    return PARALLEL_CLUSTER_PYXIS_VERSIONS[parallel_cluster_version]

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

# Version 3.11.0

def get_PARALLEL_CLUSTER_LAMBDA_RUNTIME(parallel_cluster_version):
    if parallel_cluster_version < parse_version('3.11.1'):
        return aws_lambda.Runtime.PYTHON_3_9
    else:
        return aws_lambda.Runtime.PYTHON_3_12

# Version 3.11.1

PARALLEL_CLUSTER_SUPPORTS_PYXIS_VERSION = parse_version('3.11.1')
def PARALLEL_CLUSTER_SUPPORTS_PYXIS(parallel_cluster_version):
    return parallel_cluster_version >= PARALLEL_CLUSTER_SUPPORTS_PYXIS_VERSION

# Version 3.12.0

def PARALLEL_CLUSTER_REQUIRES_FSXZ_OUTBOUND_SG_RULES(parallel_cluster_version):
    if parallel_cluster_version < parse_version('3.12.0'):
        return True
    else:
        return False

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

# Head node needs at least 13.8 GB
DEFAULT_ARM_CONTROLLER_INSTANCE_TYPE = 'm6g.xlarge'

# Head node needs at least 13.8 GB
DEFAULT_X86_CONTROLLER_INSTANCE_TYPE = 'm6a.xlarge'

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

default_included_instance_families = []

default_included_instance_types = []

default_excluded_instance_families = []

default_excluded_instance_types = []

old_eda_instance_families = [
    'c7g',               # AWS Graviton3 Processor 2.6 GHz
    'c7gd',              # AWS Graviton3 Processor 2.6 GHz
    'c7gn',              # AWS Graviton3 Processor 2.6 GHz

    'm5zn',              # Intel Xeon Platinum 8252 4.5 GHz

    'm7g',               # AWS Graviton3 Processor 2.6 GHz
    'm7gd',              # AWS Graviton3 Processor 2.6 GHz

    'r7g',               # AWS Graviton3 Processor 2.6 GHz
    'r7gd',              # AWS Graviton3 Processor 2.6 GHz

    'x2gd',              # AWS Graviton2 Processor 2.5 GHz 1TB
]

default_included_eda_instance_families = [
    # Some of these will be excluded to reduce the number of instance types
    # arm64: 72 instance types
    # x86_64:

    'c7a',               # AMD EPYC 9R14 Processor 3.7 GHz

    'c8g',               # AWS Graviton4 Processor 2.8 GHz

    'c7i',               # Intel Xeon Scalable (Sapphire Rapids) 3.2 GHz

    # Don't make F1 a default because based on older instance type and is a specialty instance.
    # 'f1',                # Intel Xeon E5-2686 v4 (Broadwell) 2.3 GHz

    'm7a',               # AMD EPYC 9R14 Processor 3.7 GHz

    'm7i',               # Intel Xeon Scalable (Sapphire Rapids) 3.2 GHz

    'm8g',               # AWS Graviton4 Processor 2.8 GHz

    'r7a',               # AMD EPYC 9R14 Processor 3.7 GHz

    'r8g',               # AWS Graviton4 Processor 2.8 GHz

    'r7i',               # Intel Xeon Scalable (Sapphire Rapids) 3.2 GHz

    'r7iz',              # Intel Xeon Scalable (Sapphire Rapids) 3.2 GHz

    'x8g',               # AWS Graviton4 Processor 2.8 GHz

    'x2idn',             # Intel Xeon Scalable (Icelake) 3.5 GHz 2 TB

    'x2iedn',            # Intel Xeon Scalable (Icelake) 3.5 GHz 4 TB

    'x2iezn',            # Intel Xeon Platinum 8252 4.5 GHz 1.5 TB

    # Don't include u instances by default because older CPU family
    # If someone really needs this amount of memory they will manually include it in their config.
    #'u.*',
    #'u-6tb1',            # Intel Xeon Scalable (Skylake) 6 TB
    #'u-9tb1',            # Intel Xeon Scalable (Skylake) 9 TB
    #'u-12tb1',           # Intel Xeon Scalable (Skylake) 12 TB
]

default_included_eda_instance_types = {
    'on_demand_and_spot': [],
    'on_demand_or_spot': []
}

old_instance_families = [
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

default_excluded_eda_instance_families = {
    'on_demand_and_spot': old_instance_families + [],
    'on_demand_or_spot': old_instance_families + []
}

default_excluded_eda_instance_types = {
    'on_demand_and_spot': [
        r'.*\.metal.*',

        # Reduce the number of selected instance types to 25.
        # Exclude larger core counts for each memory size
        # 2 GB:

        # 4 GB:
        #     1 core
        'm7a.medium',
        #     2 cores
        'c7a.large',
        'c8g.large',

        # 8 GB:
        #     1 core
        'r7a.medium',

        #     2 cores
        'c7i.xlarge',
        'm7a.large',
        'm8g.large',
        #     4 cores
        'c7a.xlarge',
        'c8g.xlarge',

        # 16 GB:
        #     1 core
        'r7iz.large',
        #     2 cores
        'm7i.xlarge',
        'r7a.large',
        'r8g.large',
        #     4 cores
        'c7i.2xlarge',
        'm7a.xlarge',
        'm8g.xlarge',
        #     8 cores
        'c7a.2xlarge',
        'c8g.2xlarge',

        # 32 GB:
        #     2 cores
        'r7iz.xlarge',
        'r8g.xlarge',
        #     4 core(s):
        'm7i.2xlarge',
        'r7a.xlarge',
        #     8 core(s): ['m8g.2xlarge']
        'c7i.4xlarge',
        'm7a.2xlarge',
        'm8g.2xlarge',
        #     16 core(s): ['c8g.4xlarge']
        'c7a.4xlarge',
        'c8g.4xlarge',

        # 64 GB: r7a.2xlarge, x2gd.xlarge
        #     4 core(s):
        'r7iz.2xlarge',
        #     8 core(s):
        'm7i.4xlarge',
        'r7a.2xlarge',
        'r8g.2xlarge',
        #     16 core(s): ['m8g.4xlarge']
        'c7i.8xlarge',
        'm7a.4xlarge',
        'm8g.4xlarge',
        #     32 core(s): ['c8g.8xlarge']
        'c7a.8xlarge',
        'c8g.8xlarge',

        # 96 GB:
        'm5zn.6xlarge',
        'c7a.12xlarge',

        # 128 GB:
        #     2 cores
        'x2iedn.xlarge',
        #     16 cores
        'm7i.8xlarge',
        'r7a.4xlarge',
        'r8g.4xlarge',
        #     32 cores
        'c7i.16xlarge',
        'm7a.8xlarge',
        'm8g.8xlarge',
        #     64 cores
        'c7a.16xlarge',
        'c8g.16xlarge',

        # 192 GB:
        #     48 cores
        'c7i.24xlarge',
        'm7a.12xlarge',
        #     96 cores
        'c7a.24xlarge',
        'c8g.24xlarge',

        # 256 GB:
        #     4 cores
        'x2iedn.2xlarge', # Have newer r7iz
        'x2iezn.2xlarge', # Have newer r7iz
        #     32 cores
        'm7i.16xlarge',
        'r7a.8xlarge',
        'r8g.8xlarge',
        #     64 cores
        'm7a.16xlarge',
        'm8g.16xlarge',
        #     128 cores
        'c7a.32xlarge',

        # 384 GB:
        #     48 cores
        'm7i.24xlarge',
        'r7a.12xlarge',
        #     96 cores
        'c7i.48xlarge',
        'm7a.24xlarge',
        'm8g.24xlarge',
        #     192 cores
        'c7a.48xlarge',
        'c8g.48xlarge',

        # 512 GB:
        #     8 cores
        'x2iedn.4xlarge', # Have newer r7iz
        'x2iezn.4xlarge', # Have newer r7iz
        #     64 cores
        'r7a.16xlarge',
        'r8g.16xlarge',
        #     128 cores
        'm7a.32xlarge',

        # 768 GB:
        #     96 cores
        'm7i.48xlarge',
        'r7a.24xlarge',
        'r8g.24xlarge',
        #     192 cores
        'm7a.48xlarge',
        'm8g.48xlarge',

        # 1024 GB:
        #     16 cores
        'x2iedn.8xlarge',
        #     32 cores
        'x2idn.16xlarge',
        #     128 cores
        'r7a.32xlarge',

        # 1536 GB:
        #     48 cores
        'x2idn.24xlarge',
        #     192 cores
        'r7a.48xlarge',

        # 2048 GB: x2iedn.16xlarge
        'x2idn.32xlarge',
        # 3072 GB: 'x2iedn.24xlarge',
        # 4096 GB: x2iedn.32xlarge
    ],
    'on_demand_or_spot': [
        r'.*\.metal.*',

        # Reduce the number of selected instance types to 50.
        # Exclude larger core counts for each memory size
        # 2 GB:
        #     3 instance type with   1 core(s): ['c8g.medium']
        # 4 GB:
        #     1 core(s): ['m8g.medium']
        #     2 core(s): ['c8g.large']
        'c7a.large',
        'c8g.large',
        # 8 GB:
        #     1 core(s): ['r8g.medium']
        #     2 core(s):
        'c7i.xlarge',
        'm7a.large',
        'm8g.large',
        #     4 core(s):
        'c7a.xlarge',
        'c8g.xlarge',

        # 16 GB:
        #     2 core(s):
        #     4 core(s): ['m8g.xlarge']
        'm8g.xlarge',
        #     8 core(s): ['c8g.2xlarge']
        'c8g.2xlarge',

        # 32 GB:
        #     4 core(s): ['r8g.xlarge']
        'm7i.2xlarge',
        #     8 core(s): ['m8g.2xlarge']
        'c7i.4xlarge',
        'm7a.2xlarge',
        'm8g.2xlarge',
        #     16 core(s): ['c8g.4xlarge']
        'c7a.4xlarge',
        'c8g.4xlarge',

        # 64 GB
        #     8 core(s):
        'm7i.4xlarge',
        #     16 core(s): ['m8g.4xlarge']
        'c7i.8xlarge',
        'm7a.4xlarge',
        'm8g.4xlarge',
        #     32 core(s): ['c8g.8xlarge']
        'c7a.8xlarge',
        'c8g.8xlarge',

        # 128 GB
        #     2 cores
        'x2iedn.xlarge',
        #     16 cores
        'm7i.8xlarge',
        #     32 cores
        'c7i.16xlarge',
        'm7a.8xlarge',
        #     64 cores
        'c7a.16xlarge',
        # 192 GB
        #     48 cores
        'c7i.24xlarge',
        #     96 cores
        'm7a.24xlarge',
        # 256 GB
        #     4 cores
        'x2iedn.2xlarge',
        #     32 cores
        'm7i.16xlarge',
        #     64 cores
        'm7a.16xlarge',
        #     128 cores
        'c7a.32xlarge',
        # 384 GB
        #     48 cores
        'm7i.24xlarge',
        #     96 cores
        'c7i.48xlarge',
        'm7a.24xlarge',
        #     192 cores
        'c7a.48xlarge',
        # 512 GB
        #     8 cores
        'x2iedn.4xlarge',
        #     128 cores
        'm7a.32xlarge',
        # 768 GB
        #     96 cores
        'm7i.48xlarge',
        #     192 cores
        'm7a.48xlarge',
        # 1024 GB
        #     16 cores
        'x2iedn.8xlarge',
        #     32 cores
        'x2idn.16xlarge',
        # 1536 GB
        #     48 cores
        'x2idn.24xlarge',
        # 2048 GB
        #     64 cores
        'x2idn.32xlarge',
    ]
}

architectures = [
    'arm64',
    'x86_64'
]

cpu_vendors = [
    'amd',
    'aws',
    'intel'
]

os_distributions = [
    'AlmaLinux',
    'Amazon',
    'CentOS',
    'RedHat',
    'Rocky'
]

exostellar_cpu_vendors = [
    'amd',
    'intel'
]

default_xio_profiles= [
    {
        'ProfileName': 'amd',
        'CpuVendor': 'amd',
        'NodeGroupName': 'amd',
        'MaxControllers': 10,
        'InstanceTypes': [
            'c5a',
            'c5ad',
            'c6a',
            'c7a',
            'm5a',
            'm5ad',
            'm6a',
            'm7a',
            'r5a',
            'r5ad',
            'r6a',
            'r7a',
            'hpc6a',
            'hpc7a',
        ],
        'SpotFleetTypes': [
            'c5a',
            'c5ad',
            'c6a',
            'c7a',
            'm5a',
            'm5ad',
            'm6a',
            'm7a',
            'r5a',
            'r5ad',
            'r6a',
            'r7a',
        ],
        'EnableHyperthreading': False,
    },
    {
        'ProfileName': 'intel',
        'CpuVendor': 'intel',
        'NodeGroupName': 'intel',
        'MaxControllers': 10,
        'InstanceTypes': [
            'c5n:1',
            'c5d:1',
            'c5:1',
            'c6i:2',
            'c6id:2',
            'c6in:2',
            'c7i:3',

            'm5:1',
            'm5d:1',
            'm5dn:1',
            'm5n:1',
            'm5zn:1',
            'm6i:2',
            'm6id:2',
            'm6idn:2',
            'm6in:2',
            'm7i:3',

            'r5:1',
            'r5b:1',
            'r5d:1',
            'r5dn:1',
            'r5n:1',
            'r6i:2',
            'r6id:2',
            'r6idn:2',
            'r6in:2',
            'r7i:3',
            'r7iz:3',

            'x2idn:1',
            'x2iedn:1',
            'z1d:1',
        ],
        'SpotFleetTypes': [
            'c5n:1',
            'c5d:1',
            'c5:1',
            'c6i:2',
            'c6id:2',
            'c6in:2',
            'c7i:3',
            'm5:1',
            'm5d:1',
            'm5dn:1',
            'm5n:1',
            'm5zn:1',
            'm6i:2',
            'm6id:2',
            'm6idn:2',
            'm6in:2',
            'm7i:3',
            'r5:1',
            'r5b:1',
            'r5d:1',
            'r5dn:1',
            'r5n:1',
            'r6i:2',
            'r6id:2',
            'r6idn:2',
            'r6in:2',
            'r7i:3',
            'r7iz:3',
            'x2idn:1',
            'x2iedn:1',
            'z1d:1',
        ],
        'EnableHyperthreading': False
    }
]

default_xio_pools = [
    {
        'PoolName': 'amd-8-gb-2-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 2,
        'InstanceMemory': 8192,
    },
    {
        'PoolName': 'amd-8-gb-4-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 4,
        'InstanceMemory': 8291,
    },
    {
        'PoolName': 'amd-16-gb-1-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 1,
        'InstanceMemory': 16384,
    },
    {
        'PoolName': 'amd-16-gb-2-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 2,
        'InstanceMemory': 16384,
    },
    {
        'PoolName': 'amd-16-gb-4-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 4,
        'InstanceMemory': 16384,
    },
    {
        'PoolName': 'amd-16-gb-8-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 8,
        'InstanceMemory': 16384,
    },
    {
        'PoolName': 'amd-32-gb-2-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 2,
        'InstanceMemory': 32768,
    },
    {
        'PoolName': 'amd-32-gb-4-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 4,
        'InstanceMemory': 32768,
    },
    {
        'PoolName': 'amd-32-gb-8-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 8,
        'InstanceMemory': 32768,
    },
    {
        'PoolName': 'amd-64-gb-4-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 4,
        'InstanceMemory': 65536,
    },
    {
        'PoolName': 'amd-64-gb-8-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 8,
        'InstanceMemory': 65536,
    },
    {
        'PoolName': 'amd-64-gb-16-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 16,
        'InstanceMemory': 65536,
    },
    {
        'PoolName': 'amd-64-gb-32-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 32,
        'InstanceMemory': 65536,
    },
    {
        'PoolName': 'amd-128-gb-8-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 8,
        'InstanceMemory': 131972,
    },
    {
        'PoolName': 'amd-128-gb-16-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 16,
        'InstanceMemory': 131972,
    },
    {
        'PoolName': 'amd-128-gb-32-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 32,
        'InstanceMemory': 131972,
    },
    {
        'PoolName': 'amd-128-gb-64-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 64,
        'InstanceMemory': 131972,
    },
    {
        'PoolName': 'amd-192-gb-24-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 24,
        'InstanceMemory': 196608,
    },
    {
        'PoolName': 'amd-192-gb-48-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 48,
        'InstanceMemory': 196608,
    },
    {
        'PoolName': 'amd-256-gb-16-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 16,
        'InstanceMemory': 262144,
    },
    {
        'PoolName': 'amd-256-gb-32-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 32,
        'InstanceMemory': 262144,
    },
    {
        'PoolName': 'amd-256-gb-64-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 64,
        'InstanceMemory': 262144,
    },
    {
        'PoolName': 'amd-256-gb-128-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 128,
        'InstanceMemory': 262144,
    },
    {
        'PoolName': 'amd-384-gb-24-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 24,
        'InstanceMemory': 393216,
    },
    {
        'PoolName': 'amd-384-gb-48-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 48,
        'InstanceMemory': 393216,
    },
    {
        'PoolName': 'amd-384-gb-96-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 96,
        'InstanceMemory': 393216,
    },
    {
        'PoolName': 'amd-384-gb-192-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 192,
        'InstanceMemory': 393216,
    },
    {
        'PoolName': 'amd-512-gb-32-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 32,
        'InstanceMemory': 524288,
    },
    {
        'PoolName': 'amd-512-gb-64-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 64,
        'InstanceMemory': 524288,
    },
    {
        'PoolName': 'amd-512-gb-128-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 128,
        'InstanceMemory': 524288,
    },
    {
        'PoolName': 'amd-768-gb-48-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 48,
        'InstanceMemory': 786432,
    },
    {
        'PoolName': 'amd-768-gb-96-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 96,
        'InstanceMemory': 786432,
    },
    {
        'PoolName': 'amd-768-gb-192-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 192,
        'InstanceMemory': 786432,
    },
    {
        'PoolName': 'amd-1024-gb-64-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 64,
        'InstanceMemory': 1048576,
    },
    {
        'PoolName': 'amd-1024-gb-128-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 128,
        'InstanceMemory': 1048576,
    },
    {
        'PoolName': 'amd-1536-gb-96-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 96,
        'InstanceMemory': 1572864,
    },
    {
        'PoolName': 'amd-1536-gb-192-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 192,
        'InstanceMemory': 1572864,
    },

    {
        'PoolName': 'intel-8g-1c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 1,
        'InstanceMemory': 8192,
    },
    {
        'PoolName': 'intel-8g-2c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 2,
        'InstanceMemory': 8192,
    },
    {
        'PoolName': 'intel-16g-1c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 1,
        'InstanceMemory': 16384,
    },
    {
        'PoolName': 'intel-16g-2c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 2,
        'InstanceMemory': 16384,
    },
    {
        'PoolName': 'intel-16g-4c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 4,
        'InstanceMemory': 16384,
    },
    {
        'PoolName': 'intel-32g-2c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 2,
        'InstanceMemory': 32768,
    },
    {
        'PoolName': 'intel-32g-4c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 4,
        'InstanceMemory': 32768,
    },
    {
        'PoolName': 'intel-32g-8c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 8,
        'InstanceMemory': 32768,
    },
    {
        'PoolName': 'intel-48g-6c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 6,
        'InstanceMemory': 49152,
    },
    {
        'PoolName': 'intel-64g-4c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 4,
        'InstanceMemory': 65536,
    },
    {
        'PoolName': 'intel-64g-8c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 8,
        'InstanceMemory': 65536,
    },
    {
        'PoolName': 'intel-64g-16c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 16,
        'InstanceMemory': 65536,
    },
    {
        'PoolName': 'intel-72g-18c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 18,
        'InstanceMemory': 73728,
    },
    {
        'PoolName': 'intel-96g-6c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 6,
        'InstanceMemory': 98304,
    },
    {
        'PoolName': 'intel-96g-12c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 12,
        'InstanceMemory': 98304,
    },
    {
        'PoolName': 'intel-96g-24c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 24,
        'InstanceMemory': 98304,
    },
    # {   # x2iedn.xlarge
    #     'PoolName': 'intel-128g-2c',
    #     'ProfileName': 'intel',
    #     'PoolSize': 10,
    #     'CPUs': 2,
    #     'InstanceMemory': 131072,
    # },
    {
        'PoolName': 'intel-128g-8c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 8,
        'InstanceMemory': 131072,
    },
    {
        'PoolName': 'intel-128g-16c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 16,
        'InstanceMemory': 131072,
    },
    {
        'PoolName': 'intel-128g-32c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 32,
        'InstanceMemory': 131072,
    },
    {   # c5[d].18xlarge
        'PoolName': 'intel-144g-36c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 36,
        'InstanceMemory': 147456,
    },
    {
        'PoolName': 'intel-192gb-12c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 12,
        'InstanceMemory': 196608,
    },
    {
        'PoolName': 'intel-192gb-24c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 24,
        'InstanceMemory': 196608,
    },
    {
        'PoolName': 'intel-192g-48c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 48,
        'InstanceMemory': 196608,
    },
    # {   # x2iedn.2xlarge
    #     'PoolName': 'intel-256g-4c',
    #     'ProfileName': 'intel',
    #     'PoolSize': 10,
    #     'CPUs': 4,
    #     'InstanceMemory': 262144,
    # },
    {
        'PoolName': 'intel-256g-16c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 16,
        'InstanceMemory': 262144,
    },
    {
        'PoolName': 'intel-256g-32c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 32,
        'InstanceMemory': 262144,
    },
    {
        'PoolName': 'intel-256g-64c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 64,
        'InstanceMemory': 262144,
    },
    {
        'PoolName': 'intel-384g-24c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 24,
        'InstanceMemory': 393216,
    },
    {
        'PoolName': 'intel-384g-48c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 48,
        'InstanceMemory': 393216,
    },
    {
        'PoolName': 'intel-384g-96c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 96,
        'InstanceMemory': 393216,
    },
    # {   # x2iedn.4xlarge
    #     'PoolName': 'intel-512g-8c',
    #     'ProfileName': 'intel',
    #     'PoolSize': 10,
    #     'CPUs': 8,
    #     'InstanceMemory': 524288,
    # },
    {
        'PoolName': 'intel-512g-32c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 32,
        'InstanceMemory': 524288,
    },
    {
        'PoolName': 'intel-512g-64c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 64,
        'InstanceMemory': 524288,
    },
    {
        'PoolName': 'intel-768g-48c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 48,
        'InstanceMemory': 786432,
    },
    {
        'PoolName': 'intel-768g-96c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 96,
        'InstanceMemory': 786432,
    },
    # {   # x2iedn.8xlarge
    #     'PoolName': 'intel-1024g-16c',
    #     'ProfileName': 'intel',
    #     'PoolSize': 10,
    #     'CPUs': 16,
    #     'InstanceMemory': 1048576,
    # },
    # {   # x2idn.16xlarge
    #     'PoolName': 'intel-1024g-32c',
    #     'ProfileName': 'intel',
    #     'PoolSize': 10,
    #     'CPUs': 32,
    #     'InstanceMemory': 1048576,
    # },
    {
        'PoolName': 'intel-1024g-64c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 64,
        'InstanceMemory': 1048576,
    },
    # {   # x2idn.24xlarge
    #     'PoolName': 'intel-1536-gb-48-cores',
    #     'ProfileName': 'intel',
    #     'PoolSize': 10,
    #     'CPUs': 48,
    #     'InstanceMemory': 1572864,
    # },
    # {
    #     'PoolName': 'intel-1536g-96c',
    #     'ProfileName': 'intel',
    #     'PoolSize': 10,
    #     'CPUs': 96,
    #     'InstanceMemory': 1572864,
    # },
    # {   # x2iedn.16xlarge
    #     'PoolName': 'intel-2048g-32c',
    #     'ProfileName': 'intel',
    #     'PoolSize': 10,
    #     'CPUs': 32,
    #     'InstanceMemory': 2097152,
    # },
    # {   # x2idn.32xlarge
    #     'PoolName': 'intel-2048g-64c',
    #     'ProfileName': 'intel',
    #     'PoolSize': 10,
    #     'CPUs': 64,
    #     'InstanceMemory': 2097152,
    # },
    # {   # x2iedn.24xlarge
    #     'PoolName': 'intel-3072g-48c',
    #     'ProfileName': 'intel',
    #     'PoolSize': 10,
    #     'CPUs': 48,
    #     'InstanceMemory': 3145728,
    # },
    # {   # x2iedn.32xlarge
    #     'PoolName': 'intel-4096g-64c',
    #     'ProfileName': 'intel',
    #     'PoolSize': 10,
    #     'CPUs': 64,
    #     'InstanceMemory': 4194304,
    # },
]

default_xwo_profiles= [
    {
        'ProfileName': 'amd',
        'CpuVendor': 'amd',
        'NodeGroupName': 'amd',
        'MaxControllers': 10,
        'InstanceTypes': [
            'c5a',
            'c5ad',
            'c6a',
            'c7a',
            'm5a',
            'm5ad',
            'm6a',
            'm7a',
            'r5a',
            'r5ad',
            'r6a',
            'r7a',
            'hpc6a',
            'hpc7a',
        ],
        'SpotFleetTypes': [
            'c5a',
            'c5ad',
            'c6a',
            'c7a',
            'm5a',
            'm5ad',
            'm6a',
            'm7a',
            'r5a',
            'r5ad',
            'r6a',
            'r7a',
        ],
        'EnableHyperthreading': False,
    },
    {
        'ProfileName': 'intel',
        'CpuVendor': 'intel',
        'NodeGroupName': 'intel',
        'MaxControllers': 10,
        'InstanceTypes': [
            'c5n:1',
            'c5d:1',
            'c5:1',
            'c6i:2',
            'c6id:2',
            'c6in:2',
            'c7i:3',

            'm5:1',
            'm5d:1',
            'm5dn:1',
            'm5n:1',
            'm5zn:1',
            'm6i:2',
            'm6id:2',
            'm6idn:2',
            'm6in:2',
            'm7i:3',

            'r5:1',
            'r5b:1',
            'r5d:1',
            'r5dn:1',
            'r5n:1',
            'r6i:2',
            'r6id:2',
            'r6idn:2',
            'r6in:2',
            'r7i:3',
            'r7iz:3',

            'x2idn:1',
            'x2iedn:1',
            'z1d:1',
        ],
        'SpotFleetTypes': [
            'c5n:1',
            'c5d:1',
            'c5:1',
            'c6i:2',
            'c6id:2',
            'c6in:2',
            'c7i:3',
            'm5:1',
            'm5d:1',
            'm5dn:1',
            'm5n:1',
            'm5zn:1',
            'm6i:2',
            'm6id:2',
            'm6idn:2',
            'm6in:2',
            'm7i:3',
            'r5:1',
            'r5b:1',
            'r5d:1',
            'r5dn:1',
            'r5n:1',
            'r6i:2',
            'r6id:2',
            'r6idn:2',
            'r6in:2',
            'r7i:3',
            'r7iz:3',
            'x2idn:1',
            'x2iedn:1',
            'z1d:1',
        ],
        'EnableHyperthreading': False
    }
]

default_xwo_pools = [
    {
        'PoolName': 'amd-8-gb-2-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 2,
        'InstanceMemory': 8192,
    },
    {
        'PoolName': 'amd-8-gb-4-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 4,
        'InstanceMemory': 8291,
    },
    {
        'PoolName': 'amd-16-gb-1-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 1,
        'InstanceMemory': 16384,
    },
    {
        'PoolName': 'amd-16-gb-2-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 2,
        'InstanceMemory': 16384,
    },
    {
        'PoolName': 'amd-16-gb-4-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 4,
        'InstanceMemory': 16384,
    },
    {
        'PoolName': 'amd-16-gb-8-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 8,
        'InstanceMemory': 16384,
    },
    {
        'PoolName': 'amd-32-gb-2-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 2,
        'InstanceMemory': 32768,
    },
    {
        'PoolName': 'amd-32-gb-4-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 4,
        'InstanceMemory': 32768,
    },
    {
        'PoolName': 'amd-32-gb-8-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 8,
        'InstanceMemory': 32768,
    },
    {
        'PoolName': 'amd-64-gb-4-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 4,
        'InstanceMemory': 65536,
    },
    {
        'PoolName': 'amd-64-gb-8-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 8,
        'InstanceMemory': 65536,
    },
    {
        'PoolName': 'amd-64-gb-16-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 16,
        'InstanceMemory': 65536,
    },
    {
        'PoolName': 'amd-64-gb-32-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 32,
        'InstanceMemory': 65536,
    },
    {
        'PoolName': 'amd-128-gb-8-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 8,
        'InstanceMemory': 131972,
    },
    {
        'PoolName': 'amd-128-gb-16-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 16,
        'InstanceMemory': 131972,
    },
    {
        'PoolName': 'amd-128-gb-32-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 32,
        'InstanceMemory': 131972,
    },
    {
        'PoolName': 'amd-128-gb-64-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 64,
        'InstanceMemory': 131972,
    },
    {
        'PoolName': 'amd-192-gb-24-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 24,
        'InstanceMemory': 196608,
    },
    {
        'PoolName': 'amd-192-gb-48-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 48,
        'InstanceMemory': 196608,
    },
    {
        'PoolName': 'amd-256-gb-16-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 16,
        'InstanceMemory': 262144,
    },
    {
        'PoolName': 'amd-256-gb-32-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 32,
        'InstanceMemory': 262144,
    },
    {
        'PoolName': 'amd-256-gb-64-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 64,
        'InstanceMemory': 262144,
    },
    {
        'PoolName': 'amd-256-gb-128-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 128,
        'InstanceMemory': 262144,
    },
    {
        'PoolName': 'amd-384-gb-24-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 24,
        'InstanceMemory': 393216,
    },
    {
        'PoolName': 'amd-384-gb-48-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 48,
        'InstanceMemory': 393216,
    },
    {
        'PoolName': 'amd-384-gb-96-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 96,
        'InstanceMemory': 393216,
    },
    {
        'PoolName': 'amd-384-gb-192-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 192,
        'InstanceMemory': 393216,
    },
    {
        'PoolName': 'amd-512-gb-32-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 32,
        'InstanceMemory': 524288,
    },
    {
        'PoolName': 'amd-512-gb-64-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 64,
        'InstanceMemory': 524288,
    },
    {
        'PoolName': 'amd-512-gb-128-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 128,
        'InstanceMemory': 524288,
    },
    {
        'PoolName': 'amd-768-gb-48-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 48,
        'InstanceMemory': 786432,
    },
    {
        'PoolName': 'amd-768-gb-96-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 96,
        'InstanceMemory': 786432,
    },
    {
        'PoolName': 'amd-768-gb-192-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 192,
        'InstanceMemory': 786432,
    },
    {
        'PoolName': 'amd-1024-gb-64-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 64,
        'InstanceMemory': 1048576,
    },
    {
        'PoolName': 'amd-1024-gb-128-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 128,
        'InstanceMemory': 1048576,
    },
    {
        'PoolName': 'amd-1536-gb-96-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 96,
        'InstanceMemory': 1572864,
    },
    {
        'PoolName': 'amd-1536-gb-192-cores',
        'ProfileName': 'amd',
        'PoolSize': 10,
        'CPUs': 192,
        'InstanceMemory': 1572864,
    },

    {
        'PoolName': 'intel-8g-1c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 1,
        'InstanceMemory': 8192,
    },
    {
        'PoolName': 'intel-8g-2c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 2,
        'InstanceMemory': 8192,
    },
    {
        'PoolName': 'intel-16g-1c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 1,
        'InstanceMemory': 16384,
    },
    {
        'PoolName': 'intel-16g-2c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 2,
        'InstanceMemory': 16384,
    },
    {
        'PoolName': 'intel-16g-4c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 4,
        'InstanceMemory': 16384,
    },
    {
        'PoolName': 'intel-32g-2c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 2,
        'InstanceMemory': 32768,
    },
    {
        'PoolName': 'intel-32g-4c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 4,
        'InstanceMemory': 32768,
    },
    {
        'PoolName': 'intel-32g-8c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 8,
        'InstanceMemory': 32768,
    },
    {
        'PoolName': 'intel-48g-6c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 6,
        'InstanceMemory': 49152,
    },
    {
        'PoolName': 'intel-64g-4c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 4,
        'InstanceMemory': 65536,
    },
    {
        'PoolName': 'intel-64g-8c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 8,
        'InstanceMemory': 65536,
    },
    {
        'PoolName': 'intel-64g-16c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 16,
        'InstanceMemory': 65536,
    },
    {
        'PoolName': 'intel-72g-18c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 18,
        'InstanceMemory': 73728,
    },
    {
        'PoolName': 'intel-96g-6c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 6,
        'InstanceMemory': 98304,
    },
    {
        'PoolName': 'intel-96g-12c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 12,
        'InstanceMemory': 98304,
    },
    {
        'PoolName': 'intel-96g-24c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 24,
        'InstanceMemory': 98304,
    },
    # {   # x2iedn.xlarge
    #     'PoolName': 'intel-128g-2c',
    #     'ProfileName': 'intel',
    #     'PoolSize': 10,
    #     'CPUs': 2,
    #     'InstanceMemory': 131072,
    # },
    {
        'PoolName': 'intel-128g-8c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 8,
        'InstanceMemory': 131072,
    },
    {
        'PoolName': 'intel-128g-16c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 16,
        'InstanceMemory': 131072,
    },
    {
        'PoolName': 'intel-128g-32c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 32,
        'InstanceMemory': 131072,
    },
    {   # c5[d].18xlarge
        'PoolName': 'intel-144g-36c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 36,
        'InstanceMemory': 147456,
    },
    {
        'PoolName': 'intel-192gb-12c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 12,
        'InstanceMemory': 196608,
    },
    {
        'PoolName': 'intel-192gb-24c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 24,
        'InstanceMemory': 196608,
    },
    {
        'PoolName': 'intel-192g-48c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 48,
        'InstanceMemory': 196608,
    },
    # {   # x2iedn.2xlarge
    #     'PoolName': 'intel-256g-4c',
    #     'ProfileName': 'intel',
    #     'PoolSize': 10,
    #     'CPUs': 4,
    #     'InstanceMemory': 262144,
    # },
    {
        'PoolName': 'intel-256g-16c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 16,
        'InstanceMemory': 262144,
    },
    {
        'PoolName': 'intel-256g-32c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 32,
        'InstanceMemory': 262144,
    },
    {
        'PoolName': 'intel-256g-64c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 64,
        'InstanceMemory': 262144,
    },
    {
        'PoolName': 'intel-384g-24c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 24,
        'InstanceMemory': 393216,
    },
    {
        'PoolName': 'intel-384g-48c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 48,
        'InstanceMemory': 393216,
    },
    {
        'PoolName': 'intel-384g-96c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 96,
        'InstanceMemory': 393216,
    },
    # {   # x2iedn.4xlarge
    #     'PoolName': 'intel-512g-8c',
    #     'ProfileName': 'intel',
    #     'PoolSize': 10,
    #     'CPUs': 8,
    #     'InstanceMemory': 524288,
    # },
    {
        'PoolName': 'intel-512g-32c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 32,
        'InstanceMemory': 524288,
    },
    {
        'PoolName': 'intel-512g-64c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 64,
        'InstanceMemory': 524288,
    },
    {
        'PoolName': 'intel-768g-48c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 48,
        'InstanceMemory': 786432,
    },
    {
        'PoolName': 'intel-768g-96c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 96,
        'InstanceMemory': 786432,
    },
    # {   # x2iedn.8xlarge
    #     'PoolName': 'intel-1024g-16c',
    #     'ProfileName': 'intel',
    #     'PoolSize': 10,
    #     'CPUs': 16,
    #     'InstanceMemory': 1048576,
    # },
    # {   # x2idn.16xlarge
    #     'PoolName': 'intel-1024g-32c',
    #     'ProfileName': 'intel',
    #     'PoolSize': 10,
    #     'CPUs': 32,
    #     'InstanceMemory': 1048576,
    # },
    {
        'PoolName': 'intel-1024g-64c',
        'ProfileName': 'intel',
        'PoolSize': 10,
        'CPUs': 64,
        'InstanceMemory': 1048576,
    },
    # {   # x2idn.24xlarge
    #     'PoolName': 'intel-1536-gb-48-cores',
    #     'ProfileName': 'intel',
    #     'PoolSize': 10,
    #     'CPUs': 48,
    #     'InstanceMemory': 1572864,
    # },
    # {
    #     'PoolName': 'intel-1536g-96c',
    #     'ProfileName': 'intel',
    #     'PoolSize': 10,
    #     'CPUs': 96,
    #     'InstanceMemory': 1572864,
    # },
    # {   # x2iedn.16xlarge
    #     'PoolName': 'intel-2048g-32c',
    #     'ProfileName': 'intel',
    #     'PoolSize': 10,
    #     'CPUs': 32,
    #     'InstanceMemory': 2097152,
    # },
    # {   # x2idn.32xlarge
    #     'PoolName': 'intel-2048g-64c',
    #     'ProfileName': 'intel',
    #     'PoolSize': 10,
    #     'CPUs': 64,
    #     'InstanceMemory': 2097152,
    # },
    # {   # x2iedn.24xlarge
    #     'PoolName': 'intel-3072g-48c',
    #     'ProfileName': 'intel',
    #     'PoolSize': 10,
    #     'CPUs': 48,
    #     'InstanceMemory': 3145728,
    # },
    # {   # x2iedn.32xlarge
    #     'PoolName': 'intel-4096g-64c',
    #     'ProfileName': 'intel',
    #     'PoolSize': 10,
    #     'CPUs': 64,
    #     'InstanceMemory': 4194304,
    # },
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
        Optional('AdditionalSecurityGroupsStackName'): str,
        Optional('RESStackName'): str,
        # ExternalLoginNodes:
        #     Configure external login nodes
        #    Tags of instances that can be configured to submit to the cluster.
        #    When the cluster is deleted, the tag is used to unmount the slurm filesystem from the instances using SSM.
        Optional('ExternalLoginNodes'): [
            {
                'Tags': [
                    {
                        'Key': str,
                        'Values': [str]
                    }
                ],
                Optional('SecurityGroupId'): str
            }
        ],
        Optional('DomainJoinedInstance'): {
            'Tags': [
                {
                    'Key': str,
                    'Values': [str]
                }
            ],
            Optional('SecurityGroupId'): str
        },
        'slurm': {
            Optional('ParallelClusterConfig'): {
                Optional('Enable', default=True): And(bool, lambda s: s == True),
                'Version': And(str, lambda version: version in PARALLEL_CLUSTER_VERSIONS, lambda version: parse_version(version) >= MIN_PARALLEL_CLUSTER_VERSION),
                Optional('ClusterConfig'): lambda s: True,
                Optional('Image', default={'Os': DEFAULT_OS(config)}): {
                    'Os': And(str, lambda s: s in get_PARALLEL_CLUSTER_ALLOWED_OSES(config)),
                    # CustomAmi: AMI to use for head and compute nodes instead of the pre-built AMIs.
                    Optional('CustomAmi'): And(str, lambda s: s.startswith('ami-')),
                },
                Optional('Architecture', default=DEFAULT_ARCHITECTURE): And(str, lambda s: s in VALID_ARCHITECTURES),
                Optional('ComputeNodeAmi'): And(str, lambda s: s.startswith('ami-')),
                # Recommend to not use EFA unless necessary to avoid insufficient capacity errors when starting new instances in group or when multiple instance types in the group
                # See https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/placement-groups.html#placement-groups-cluster
                Optional('EnableEfa', default=False): bool,
                Optional('EnablePyxis', default=False): bool,
                Optional('Database'): {
                    Optional('DatabaseStackName'): str,
                    Optional('FQDN'): str,
                    Optional('Port'): int,
                    Optional('AdminUserName'): str,
                    Optional('AdminPasswordSecretArn'): And(str, lambda s: s.startswith('arn:')),
                    Optional('ClientSecurityGroup'): {str: And(str, lambda s: re.match('sg-', s))},
                },
                Optional('Slurmdbd'): {
                    Optional('SlurmdbdStackName'): str,
                    Optional('Host'): str,
                    Optional('Port'): int,
                    Optional('ClientSecurityGroup'): And(str, lambda s: re.match('sg-', s))
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
            #     Required if your external login nodes need to use more than 1 cluster.
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
            #
            # InstanceConfig:
            #     Configure the instances used by the cluster
            #     A partition will be created for each combination of Base OS, Architecture, and Spot
            'InstanceConfig': {
                # UseOnDemand:
                #     Configure on-demand instances
                Optional('UseOnDemand', default=True): bool,
                # UseSpot:
                #     Configure spot instances
                Optional('UseSpot', default=True): bool,
                Optional('DisableSimultaneousMultithreading', default=True): bool,
                # This is a global setting that can be overridden for instance types in InstanceConfig.
                # Recommend to not use EFA unless necessary to avoid insufficient capacity errors when starting new instances in group or when multiple instance types in the group
                # See https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/placement-groups.html#placement-groups-cluster
                Optional('EnableEfa', default=False): bool,
                Optional('PlacementGroupName'): str,
                Optional('CpuVendor', default=cpu_vendors): [
                    And(str, lambda s: s in cpu_vendors)
                ],
                # Include*/Exclude*:
                #     Instance families and types are regular expressions with implicit '^' and '$' at the begining and end.
                #     Exclude patterns are processed first and take precedence over any includes.
                Optional('Exclude', default={}): {
                    Optional('InstanceFamilies'): [str],
                    Optional('InstanceTypes'): [str]
                },
                Optional('Include', default={'MaxSizeOnly': False}): {
                    # MaxSizeOnly:
                    #     If MaxSizeOnly is True then only the largest instance type in
                    #     a family will be included unless specific instance types are included.
                    #     Default: false
                    Optional('MaxSizeOnly', default=False): bool,
                    Optional('InstanceFamilies'): [
                        Or(
                            str,
                            And(
                                {
                                    str: {
                                        Optional('UseOnDemand'): bool,
                                        Optional('UseSpot'): bool,
                                        Optional('DisableSimultaneousMultithreading'): bool,
                                        Optional('EnableEfa'): bool,
                                        Optional('PlacementGroupName'): str
                                    }
                                },
                                lambda d: len(d) == 1
                            )
                        ),
                    ],
                    Optional('InstanceTypes'): [
                        Or(
                            str,
                            And(
                                {
                                    str: {
                                        Optional('UseOnDemand'): bool,
                                        Optional('UseSpot'): bool,
                                        Optional('DisableSimultaneousMultithreading'): bool,
                                        Optional('EnableEfa'): bool,
                                        Optional('PlacementGroupName'): str
                                    }
                                },
                                lambda d: len(d) == 1
                            )
                        ),
                    ]
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
            Optional('Xio'): {
                Optional('ManagementServerStackName'): str,
                Optional('ManagementServerIp'): str,
                'PartitionName': str,
                Optional('Images'): [
                    {
                        'ImageName': str,
                        'ImageId': str,
                        Optional('VolumeSize'): int
                    }
                ],
                Optional('InstanceTypes'): [ str ],
                Optional('SpotFleetTypes'): [ str],
                Optional('MaxControllers', default=10): int,
                Optional('PoolSize', default=10): int,
                Optional('EnableHyperthreading', default=False): bool,
                Optional('DefaultImageName'): str,
                Optional('DefaultVolumeSize', default=10): int,
                Optional('Profiles', default={}): {
                    str: {
                        'CpuVendor': And(str, lambda s: s in ['amd', 'intel']),
                        'NodeGroupName': str,
                        'MaxControllers': int,
                        'InstanceTypes': [
                            str
                        ],
                        'SpotFleetTypes': [
                            str
                        ],
                        'EnableHyperthreading': bool
                    }
                },
                Optional('Pools', default={}): {
                    str: {
                        'ProfileName': str,
                        'PoolSize': int,
                        'CPUs': int,
                        Optional('ImageName'): str,
                        Optional('InstanceMemory'): int,
                        Optional('MaxMemory'): int,
                        Optional('VolumeSize'): int,
                        Optional('Weight'): int
                    }
                },
                Optional('AvailabilityZone'): str,
                Optional('Controllers'): {
                    Optional('ImageId'): str,
                    Optional('SecurityGroupIds'): [str],
                    Optional('IdentityRole'): str,
                    Optional('InstanceType'): str
                },
                Optional('Workers'): {
                    Optional('ImageId'): str,
                    Optional('SecurityGroupIds'): [ str ],
                    Optional('IdentityRole'): str
                },
                Optional('VmRootPasswordSecret'): str
            },
            Optional('Xwo'): { # Exostellar Workload Optimizer
                Optional('ManagementServerStackName'): str,
                Optional('ManagementServerIp'): str,
                'PartitionName': str,
                Optional('Images'): [
                    {
                        'ImageName': str,
                        'ImageId': str,
                        Optional('VolumeSize'): int
                    }
                ],
                Optional('InstanceTypes'): [ str ],
                Optional('SpotFleetTypes'): [ str],
                Optional('MaxControllers', default=10): int,
                Optional('PoolSize', default=10): int,
                Optional('EnableHyperthreading', default=False): bool,
                Optional('DefaultImageName'): str,
                Optional('DefaultVolumeSize', default=10): int,
                Optional('Profiles', default={}): {
                    Optional(str): {
                            'CpuVendor': And(str, lambda s: s in ['amd', 'intel']),
                            'NodeGroupName': str,
                            'MaxControllers': int,
                            'InstanceTypes': [
                                str
                            ],
                            'SpotFleetTypes': [
                                str
                            ],
                            'EnableHyperthreading': bool
                        }
                },
                Optional('Pools', default={}): {
                    Optional(str): {
                            'ProfileName': str,
                            'PoolSize': int,
                            'CPUs': int,
                            Optional('ImageName'): str,
                            Optional('InstanceMemory'): int,
                            Optional('MaxMemory'): int,
                            Optional('VolumeSize'): int,
                            Optional('Weight'): int
                        }
                },
                Optional('AvailabilityZone'): str,
                Optional('Controllers'): {
                    Optional('ImageId'): str,
                    Optional('SecurityGroupIds'): [str],
                    Optional('IdentityRole'): str,
                    Optional('InstanceType'): str
                },
                Optional('Workers'): {
                    Optional('ImageId'): str,
                    Optional('SecurityGroupIds'): [ str ],
                    Optional('IdentityRole'): str
                },
                Optional('VmRootPasswordSecret'): str
            },
            Optional('SlurmUid', default=401): int,
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
                ]
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
