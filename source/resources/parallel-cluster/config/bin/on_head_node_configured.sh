#!/bin/bash -x
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

set -x
set -e

script_name=on_head_node_configured.sh

exec 1> >(logger -s -t ${script_name}) 2>&1

echo "$(date): Started ${script_name}"

# Jinja2 template variables
assets_bucket={{assets_bucket}}
assets_base_key={{assets_base_key}}
export AWS_DEFAULT_REGION={{Region}}
MungeKeySecretId={{MungeKeySecretId}}
playbooks_s3_url={{playbooks_s3_url}}

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

config_dir=/opt/slurm/config
config_bin_dir=$config_dir/bin
ANSIBLE_PATH=$config_dir/ansible
PLAYBOOKS_PATH=$ANSIBLE_PATH/playbooks

# Make sure we're running the latest version
dest_script="$config_bin_dir/${script_name}"
mkdir -p $config_bin_dir
aws s3 cp s3://$assets_bucket/$assets_base_key/config/bin/${script_name} $dest_script.new
chmod 0700 $dest_script.new
if ! [ -e $dest_script ] || ! diff -q $dest_script $dest_script.new; then
    mv -f $dest_script.new $dest_script
    exec $dest_script
else
    rm $dest_script.new
fi

export PATH=/usr/sbin:$PATH

# Rerun on_head_node_start.sh to download latest versions of all config files and scripts
$config_bin_dir/on_head_node_start.sh

if ! [ -z $MungeKeySecretId ]; then
    echo "Download munge key from $MungeKeySecretId"
    munge_key_b64=$(aws secretsmanager get-secret-value --secret-id $MungeKeySecretId --query 'SecretString' --output text)
    echo "$munge_key_b64" | base64 -d -w 0 > /etc/munge/munge.key.new
    echo "" >> /etc/munge/munge.key.new
    chown munge /etc/munge/munge.key.new
    chmod 0600 /etc/munge/munge.key.new
    if diff -q /etc/munge/munge.key /etc/munge/munge.key.new; then
        echo "Munge key is correct"
        rm -f /etc/munge/munge.key.new
    else
        echo "Update munge key from $MungeKeySecretId"
        cp /etc/munge/munge.key /etc/munge/munge.key.back$(date '+%Y-%m-%dT%H:%M:%S')
        mv -f /etc/munge/munge.key.new /etc/munge/munge.key
        echo "Restart services"
        systemctl restart munge
        systemctl restart slurmdbd
        systemctl restart slurmctld
    fi
fi
/usr/bin/cp -f /etc/munge/munge.key $config_dir/munge.key

pushd $PLAYBOOKS_PATH
ansible-playbook $PLAYBOOKS_PATH/ParallelClusterHeadNode.yml \
    -i inventories/local.yml \
    -e @$ANSIBLE_PATH/ansible_head_node_vars.yml
popd

# Notify SNS topic that trigger configuration of cluster manager and submitters
ConfigureClusterManagerSnsTopicArnParameter={{ConfigureClusterManagerSnsTopicArnParameter}}
ConfigureClusterManagerSnsTopicArn=$(aws ssm get-parameter --name $ConfigureClusterManagerSnsTopicArnParameter --query 'Parameter.Value' --output text)
aws sns publish --topic-arn $ConfigureClusterManagerSnsTopicArn --message '{{ClusterName}} configured'

ConfigureSubmittersSnsTopicArnParameter={{ConfigureSubmittersSnsTopicArnParameter}}
ConfigureSubmittersSnsTopicArn=$(aws ssm get-parameter --name $ConfigureSubmittersSnsTopicArnParameter --query 'Parameter.Value' --output text)
aws sns publish --topic-arn $ConfigureSubmittersSnsTopicArn --message '{{ClusterName}} configured'

echo "$(date): Finished ${script_name}"

exit 0
