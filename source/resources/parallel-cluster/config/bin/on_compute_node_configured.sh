#!/bin/bash -x
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

set -x

script_name=on_compute_node_configured.sh

exec 1> >(logger -s -t ${script_name}) 2>&1

echo "$(date): Started ${script_name}"

# Jinja2 template variables
assets_bucket={{assets_bucket}}
assets_base_key={{assets_base_key}}
export AWS_DEFAULT_REGION={{Region}}
ErrorSnsTopicArn={{ErrorSnsTopicArn}}
HomeMountSrc={{HomeMountSrc}}
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

if ! [ -z $HomeMountSrc ]; then
    umount /home
    mount $HomeMountSrc /home
fi

if ! diff -q $config_dir/munge.key /etc/munge/munge.key; then
    echo "Updating /etc/munge/munge.key"
    /usr/bin/cp /etc/munge/munge.key /etc/munge/munge.key.back$(date '+%Y-%m-%dT%H:%M:%S')
    /usr/bin/cp $config_dir/munge.key /etc/munge/munge.key
    systemctl restart munge
    systemctl restart slurmd
fi

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

echo "Creating users and groups"
if [[ -e $config_dir/users_groups.json ]]; then
    $config_bin_dir/create_users_groups.py -i $config_dir/users_groups.json
fi

# ansible_compute_node_vars_yml_s3_url="s3://$assets_bucket/$assets_base_key/config/ansible/ansible_compute_node_vars.yml"

# # Configure using ansible
# if ! yum list installed ansible &> /dev/null; then
#     yum install -y ansible || amazon-linux-extras install -y ansible2
# fi

# ANSIBLE_PATH=$config_dir/ansible
# PLAYBOOKS_PATH=$ANSIBLE_PATH/playbooks
# pushd $PLAYBOOKS_PATH
# ansible-playbook $PLAYBOOKS_PATH/ParallelClusterComputeNode.yml \
#     -i inventories/local.yml \
#     -e @$ANSIBLE_PATH/ansible_compute_node_vars.yml &
# popd

echo "$(date): Finished ${script_name}"

exit 0
