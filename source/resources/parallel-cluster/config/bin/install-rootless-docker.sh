#!/bin/bash -ex
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# This script calls an ansible playbook that installs rootless docker on a compute node.
# It has 2 different use cases:
#   * To build ParallelCluster AMIs
#   * To install docker on VDIs or other login nodes using a ParallellCluster.
# The location of the config directory is different for those 2 use cases.
# For an AMI build, the config directory and scripts will not exist and must be downloaded from S3.
# For a login node, the playbooks and scripts will already exist.

script=$0
script_name=$(basename $script)

# Jinja2 template variables
assets_bucket={{assets_bucket}}
assets_base_key={{assets_base_key}}
export AWS_DEFAULT_REGION={{Region}}
ClusterName={{ClusterName}}
ErrorSnsTopicArn={{ErrorSnsTopicArn}}
playbooks_s3_url={{playbooks_s3_url}}

# Notify user of errors
function on_exit {
    rc=$?
    set +e
    if [[ $rc -ne 0 ]] && [[ ":$ErrorSnsTopicArn" != ":" ]]; then
        tmpfile=$(mktemp)
        echo "See log files for more info:
    /var/lib/amazon/toe/TOE_*
    grep PCImageBuilderEDA /var/log/messages | less" > $tmpfile
        aws --region $AWS_DEFAULT_REGION sns publish --topic-arn $ErrorSnsTopicArn --subject "${ClusterName} install-rootless-docker.sh failed" --message file://$tmpfile
        rm $tmpfile
    fi
}
trap on_exit EXIT

# Redirect all IO to /var/log/messages and then echo to stderr
exec 1> >(logger -s -t install-rootless-docker) 2>&1

# Install ansible
if ! yum list installed ansible &> /dev/null; then
    yum install -y ansible || amazon-linux-extras install -y ansible2
fi

external_login_node_config_dir=/opt/slurm/${ClusterName}/config
if [ -e $external_login_node_config_dir ]; then
    config_dir=$external_login_node_config_dir
else
    config_dir=/opt/slurm/config
fi
config_bin_dir=$config_dir/bin
ANSIBLE_PATH=$config_dir/ansible
PLAYBOOKS_PATH=$ANSIBLE_PATH/playbooks
PLAYBOOKS_ZIP_PATH=$ANSIBLE_PATH/playbooks.zip

if ! [ -e $external_login_node_config_dir ]; then
    mkdir -p $config_bin_dir

    ansible_head_node_vars_yml_s3_url="s3://$assets_bucket/$assets_base_key/config/ansible/ansible_head_node_vars.yml"
    ansible_compute_node_vars_yml_s3_url="s3://$assets_bucket/$assets_base_key/config/ansible/ansible_compute_node_vars.yml"
    ansible_external_login_node_vars_yml_s3_url="s3://$assets_bucket/$assets_base_key/config/ansible/ansible_external_login_node_vars.yml"

    # Download ansible playbooks
    aws s3 cp $playbooks_s3_url ${PLAYBOOKS_ZIP_PATH}.new
    if ! [ -e $PLAYBOOKS_ZIP_PATH ] || ! diff -q $PLAYBOOKS_ZIP_PATH ${PLAYBOOKS_ZIP_PATH}.new; then
        mv $PLAYBOOKS_ZIP_PATH.new $PLAYBOOKS_ZIP_PATH
        rm -rf $PLAYBOOKS_PATH
        mkdir -p $PLAYBOOKS_PATH
        pushd $PLAYBOOKS_PATH
        yum -y install unzip
        unzip $PLAYBOOKS_ZIP_PATH
        chmod -R 0700 $ANSIBLE_PATH
        popd
    fi

    aws s3 cp $ansible_head_node_vars_yml_s3_url /opt/slurm/config/ansible/ansible_head_node_vars.yml

    aws s3 cp $ansible_compute_node_vars_yml_s3_url /opt/slurm/config/ansible/ansible_compute_node_vars.yml

    aws s3 cp $ansible_external_login_node_vars_yml_s3_url /opt/slurm/config/ansible/ansible_external_login_node_vars.yml
fi

pushd $PLAYBOOKS_PATH

ansible-playbook $PLAYBOOKS_PATH/install-rootless-docker.yml \
    -i inventories/local.yml \
    -e @$ANSIBLE_PATH/ansible_compute_node_vars.yml

popd
