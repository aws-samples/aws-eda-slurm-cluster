#!/bin/bash -x
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# This script gets called at the end of /opt/slurm/config/bin/on_compute_node_start.sh.
# The user can update this script so that they can do additional actions when the compute node is started.
# Be aware that /opt/slurm will not be mounted until after the compute node is started.

set -x
set -e

script_name=on_compute_node_start_custom_epilog.sh

exec 1> >(logger -s -t ${script_name}) 2>&1

echo "$(date): Started ${script_name}"

# Add your code after this line

echo "$(date): Finished ${script_name}"

exit 0
