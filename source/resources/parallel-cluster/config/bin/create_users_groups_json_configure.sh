#!/bin/bash -xe
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# This script creates the json file with user and group information.
# It also creates a crontab entry to update the json file every hour.
#
# The script and ansible playbooks needed to undo this will be installed at:
#
# /opt/aws-eda-slurm-cluster/{{ cluster_name }}
#
# To deconfigure the instance, run the following script:
#
# /opt/aws-eda-slurm-cluster/{{ cluster_name }}/create_users_groups_json_deconfigure.sh

full_script=$(realpath $0)
script_dir=$(dirname $full_script)
base_script=$(basename $full_script)

echo "$(date): Started create_users_groups_json_configure.sh: $full_script"

config_dir={{ ExternalLoginNodeSlurmConfigDir }}
config_bin_dir=$config_dir/bin

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

echo "$(date): Finished create_users_groups_json_configure.sh: $full_script"

exit 0
