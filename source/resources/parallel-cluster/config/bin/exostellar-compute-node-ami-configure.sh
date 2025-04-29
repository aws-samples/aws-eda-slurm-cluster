#!/bin/bash -ex
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# This script configures an instance so that it can be used to create an AMI to be used by
# Exostellar Infrastructure Optimizer or Workload Optimizer.
# The instance should be launched using a plain RHEL AMI.

script=$0
script_name=$(basename $script)

# Jinja2 template variables
assets_bucket={{assets_bucket}}
assets_base_key={{assets_base_key}}
export AWS_DEFAULT_REGION={{Region}}
ClusterName={{ClusterName}}
ErrorSnsTopicArn={{ErrorSnsTopicArn}}
playbooks_s3_url={{playbooks_s3_url}}

# Redirect all IO to /var/log/messages and then echo to stderr
exec 1> >(logger -s -t exostellar-compute-node-ami-configure.sh) 2>&1

# Install ansible
if ! yum list installed ansible &> /dev/null; then
    yum install -y ansible || amazon-linux-extras install -y ansible2
fi
ansible-galaxy collection install ansible.posix

config_dir=/opt/slurm/config
config_bin_dir=$config_dir/bin
ANSIBLE_PATH=$config_dir/ansible
PLAYBOOKS_PATH=$ANSIBLE_PATH/playbooks
PLAYBOOKS_ZIP_PATH=$ANSIBLE_PATH/playbooks.zip

pushd $PLAYBOOKS_PATH

ansible-playbook $PLAYBOOKS_PATH/ExostellarComputeNodeAmi.yml \
    -i inventories/local.yml \
    -e @$ANSIBLE_PATH/ansible_head_node_vars.yml

popd
