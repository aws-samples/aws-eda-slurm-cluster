#!/bin/bash -xe
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# This script configures an instance as an external login node for a ParallelCluster cluster.
#
# The script and ansible playbooks needed to undo this will be installed at:
#
# /opt/aws-eda-slurm-cluster/{{ cluster_name }}
#
# To deconfigure the instance as a login node run the following script:
#
# /opt/aws-eda-slurm-cluster/{{ cluster_name }}/external_login_node_deconfigure.sh

full_script=$(realpath $0)
script_dir=$(dirname $full_script)
script_name=$(basename $full_script)

echo "$(date): Started ${script_name}"

# Jinja2 template variables
assets_bucket={{ assets_bucket }}
assets_base_key={{ assets_base_key }}
export AWS_DEFAULT_REGION={{ Region }}
ClusterName={{ ClusterName }}
config_dir={{ ExternalLoginNodeSlurmConfigDir }}
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

config_bin_dir=$config_dir/bin

# Configure using ansible
if ! yum list installed ansible &> /dev/null; then
    yum install -y ansible || amazon-linux-extras install -y ansible2
fi

ANSIBLE_PATH=$config_dir/ansible
PLAYBOOKS_PATH=$ANSIBLE_PATH/playbooks

pushd $PLAYBOOKS_PATH
ansible-playbook $PLAYBOOKS_PATH/ParallelClusterExternalLoginNodeConfigure.yml \
    -i inventories/local.yml \
    -e @$ANSIBLE_PATH/ansible_external_login_node_vars.yml
popd

modulefile_profile=/etc/profile.d/slurm_${ClusterName}_modulefiles.sh
if ! [ -e $modulefile_profile ]; then
    echo "error: $modulefile_profile doesn't exist"
    exit 1
fi
modulefile=$(cat $modulefile_profile | grep 'module use' | cut -d ' ' -f 3)
if [ -z $modulefile ]; then
    echo "error: Couldn't get modulefile path from $modulefile_profile:"
    cat $modulefile_profile
    cat $modulefile_profile | grep 'module use'
    exit1
fi

pushd $PLAYBOOKS_PATH
ansible-playbook $PLAYBOOKS_PATH/ParallelClusterExternalLoginNodeInstallSlurm.yml \
    -i inventories/local.yml \
    -e @$ANSIBLE_PATH/ansible_external_login_node_vars.yml
popd

echo "$(date): Finished ${script_name}"

exit 0
