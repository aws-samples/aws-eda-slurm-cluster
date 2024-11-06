#!/bin/bash -xe
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# This script creates the json file with user and group information.
# It also creates a crontab entry to update the json file every hour.

full_script=$(realpath $0)
script_dir=$(dirname $full_script)
base_script=$(basename $full_script)

date
echo "Started create_users_groups_json_configure.sh: $full_script"

config_dir={{ ExternalLoginNodeSlurmConfigDir }}
config_bin_dir=$config_dir/bin

# Configure using ansible
if ! yum list installed ansible &> /dev/null; then
    yum install -y ansible || amazon-linux-extras install -y ansible2
fi

ANSIBLE_PATH=$config_dir/ansible
PLAYBOOKS_PATH=$ANSIBLE_PATH/playbooks

pushd $PLAYBOOKS_PATH
ansible-playbook $PLAYBOOKS_PATH/ParallelClusterCreateUsersGroupsJsonConfigure.yml \
    -i inventories/local.yml \
    -e @$ANSIBLE_PATH/ansible_external_login_node_vars.yml
popd

date
echo "Finished create_users_groups_json_configure.sh: $full_script"

exit 0
