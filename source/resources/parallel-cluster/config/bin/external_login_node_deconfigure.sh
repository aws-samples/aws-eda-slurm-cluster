#!/bin/bash -xe
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# This script deconfigures an instance that has been configured as a ParallelCluster Slurm login node.
#
# This script and it's ansible playbook are copied to /opt/aws-eda-slurm-cluster/{{ cluster_name }} so
# that they can be executed whether the cluster still exists or not.

full_script=$(realpath $0)
script_dir=$(dirname $full_script)
base_script=$(basename $full_script)
ANSIBLE_PATH=$(dirname $script_dir)/ansible
PLAYBOOKS_PATH=$ANSIBLE_PATH/playbooks

echo "$(date): Started $base_script: $full_script"

ErrorSnsTopicArn={{ ErrorSnsTopicArn }}

# Notify user of errors
function on_exit {
    rc=$?
    set +e
    if [[ $rc -ne 0 ]] && [[ ":$ErrorSnsTopicArn" != ":" ]]; then
        message_file=$(mktemp)
        echo "See log files for more info:
    grep ${script_name} /var/log/messages | less" > $message_file
        aws sns publish --topic-arn $ErrorSnsTopicArn --subject "${ClusterName} ${script_name} failed" --message file://$message_file
        rm $message_file
    fi
}
trap on_exit EXIT

# Install ansible
if ! yum list installed ansible &> /dev/null; then
    yum install -y ansible || amazon-linux-extras install -y ansible2
fi

pushd $PLAYBOOKS_PATH
ansible-playbook $PLAYBOOKS_PATH/ParallelClusterExternalLoginNodeDeconfigure.yml \
    -i inventories/local.yml \
    -e @$ANSIBLE_PATH/ansible_external_login_node_vars.yml
popd

rm -rf $(dirname $script_dir)

echo "$(date): Finished $base_script: $full_script"

exit 0
