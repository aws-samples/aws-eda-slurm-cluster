#!/bin/bash -x
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# This script gets called at the beginning of /opt/slurm/config/bin/on_head_node_updated.sh.
# The user can update this script so that they can do additional actions when the head node is updated.

set -x
set -e

script_name=on_head_node_updated_custom_prolog.sh

exec 1> >(logger -s -t ${script_name}) 2>&1

echo "$(date): Started ${script_name}"

# Add your code after this line

echo "$(date): Finished ${script_name}"

exit 0
