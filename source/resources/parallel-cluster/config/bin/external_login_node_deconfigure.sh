#!/bin/bash -xe
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

full_script=$(realpath $0)
script_dir=$(dirname $full_script)
base_script=$(basename $full_script)

date
echo "Started external_login_node_deconfigure.sh: $full_script"

ErrorSnsTopicArn={{ ErrorSnsTopicArn }}

config_dir={{ ExternalLoginNodeSlurmConfigDir }}
config_bin_dir=$config_dir/bin

temp_config_dir=/tmp/{{ClusterName}}_config
temp_config_bin_dir=$temp_config_dir/bin
if [[ $script_dir != $temp_config_bin_dir ]]; then
    rm -rf $temp_config_dir
    cp -r $config_dir $temp_config_dir
    exec $temp_config_dir/bin/$base_script
fi

# Install ansible
if ! yum list installed ansible &> /dev/null; then
    yum install -y ansible || amazon-linux-extras install -y ansible2
fi

ANSIBLE_PATH=$temp_config_dir/ansible
PLAYBOOKS_PATH=$ANSIBLE_PATH/playbooks

pushd $PLAYBOOKS_PATH
ansible-playbook $PLAYBOOKS_PATH/ParallelClusterExternalLoginNodeDeconfigure.yml \
    -i inventories/local.yml \
    -e @$ANSIBLE_PATH/ansible_external_login_node_vars.yml
popd

rm -rf $temp_config_dir

date
echo "Finished external_login_node_deconfigure.sh: $full_script"

exit 0
