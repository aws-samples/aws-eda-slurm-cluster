# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# Configuration variables used by slurm plugin
export AWS_DEFAULT_REGION={{Region}}
export DOMAIN={{Domain}}
export SLURM_POWER_LOG=/var/log/slurm/power_save.log
export SLURMNODE_PROFILE_ARN="{{SlurmNodeProfileArn}}"
export SLURMNODE_ROLE_NAME={{SlurmNodeRoleName}}
export SLURMRESTD_PORT="{{SlurmrestdPort}}"
export SLURMRESTD_URL="http://slurmctl1.{{Domain}}:{{SlurmrestdPort}}"
export STACK_NAME={{STACK_NAME}}
