#!/bin/bash -x
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

set -x
set -e

script_name=on_head_node_start.sh

exec 1> >(logger -s -t ${script_name}) 2>&1

echo "$(date): Started ${script_name}"

# Jinja2 template variables
assets_bucket={{assets_bucket}}
assets_base_key={{assets_base_key}}
export AWS_DEFAULT_REGION={{Region}}
ErrorSnsTopicArn={{ErrorSnsTopicArn}}
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

# Notify SNS topic that triggers creation of DNS A record for head node.
CreateHeadNodeARecordSnsTopicArnParameter={{CreateHeadNodeARecordSnsTopicArnParameter}}
CreateHeadNodeARecordSnsTopicArn=$(aws ssm get-parameter --name $CreateHeadNodeARecordSnsTopicArnParameter --query 'Parameter.Value' --output text)
aws sns publish --topic-arn $CreateHeadNodeARecordSnsTopicArn --message '{{ClusterName}} started'

ansible_head_node_vars_yml_s3_url="s3://$assets_bucket/$assets_base_key/config/ansible/ansible_head_node_vars.yml"
ansible_compute_node_vars_yml_s3_url="s3://$assets_bucket/$assets_base_key/config/ansible/ansible_compute_node_vars.yml"
ansible_external_login_node_vars_yml_s3_url="s3://$assets_bucket/$assets_base_key/config/ansible/ansible_external_login_node_vars.yml"

create_user_groups_json_py_s3_url="s3://$assets_bucket/$assets_base_key/config/bin/create_users_groups_json.py"
create_user_groups_py_s3_url="s3://$assets_bucket/$assets_base_key/config/bin/create_users_groups.py"
users_groups_json_s3_url="s3://$assets_bucket/$assets_base_key/config/users_groups.json"


# Download all of the config scripts
config_scripts=(\
    configure-eda.sh \
    configure-rootless-docker.sh \
    create_or_update_users_groups_json.sh \
    create_users_groups_json.py \
    create_users_groups_json_configure.sh \
    create_users_groups_json_deconfigure.sh \
    create_users_groups.py \
    install-rootless-docker.sh \
    on_head_node_start.sh \
    on_head_node_configured.sh \
    on_head_node_updated.sh \
    on_compute_node_start.sh \
    on_compute_node_configured.sh \
    external_login_node_configure.sh \
    external_login_node_deconfigure.sh \
    exostellar-compute-node-ami-configure.sh \
)
for config_script in ${config_scripts[*]}; do
    dest=$config_bin_dir/$config_script
    aws s3 cp s3://$assets_bucket/$assets_base_key/config/bin/$config_script $dest.new
    chmod 0700 $dest.new
    mv -f $dest.new $dest
done

mkdir -p $config_dir/build-files
aws s3 cp --recursive s3://$assets_bucket/$assets_base_key/config/build-files $config_dir/build-files

if ! [ -e $config_dir/users_groups.json ]; then
    aws s3 cp $users_groups_json_s3_url $config_dir/users_groups.json
    $config_bin_dir/create_users_groups.py -i $config_dir/users_groups.json
fi
chmod 0600 $config_dir/users_groups.json

export PATH=/usr/sbin:$PATH

$config_bin_dir/create_users_groups.py -i $config_dir/users_groups.json

# Install ansible
if ! yum list installed ansible &> /dev/null; then
    yum install -y ansible || amazon-linux-extras install -y ansible2
fi

# Download ansible playbooks

ANSIBLE_PATH=$config_dir/ansible
PLAYBOOKS_PATH=$ANSIBLE_PATH/playbooks
PLAYBOOKS_ZIP_PATH=$ANSIBLE_PATH/playbooks.zip
aws s3 cp $playbooks_s3_url ${PLAYBOOKS_ZIP_PATH}.new
if ! [ -e $PLAYBOOKS_ZIP_PATH ] || ! diff -q $PLAYBOOKS_ZIP_PATH ${PLAYBOOKS_ZIP_PATH}.new; then
    mv $PLAYBOOKS_ZIP_PATH.new $PLAYBOOKS_ZIP_PATH
    rm -rf $PLAYBOOKS_PATH
    mkdir -p $PLAYBOOKS_PATH
    pushd $PLAYBOOKS_PATH
    unzip $PLAYBOOKS_ZIP_PATH
    chmod -R 0700 $ANSIBLE_PATH
    popd
fi

aws s3 cp $ansible_head_node_vars_yml_s3_url /opt/slurm/config/ansible/ansible_head_node_vars.yml

aws s3 cp $ansible_compute_node_vars_yml_s3_url /opt/slurm/config/ansible/ansible_compute_node_vars.yml

aws s3 cp $ansible_external_login_node_vars_yml_s3_url /opt/slurm/config/ansible/ansible_external_login_node_vars.yml

# Don't run ansible until after slurmctld and slurmdbd are up and running successfully.

# Create jwt key for slurmrestd
# jwt key needs to be created before slurmctld can start because we configure the JWT key in extra slurm config settings
slurm_spool_dir=/opt/slurm/var/spool
jwt_key=$slurm_spool_dir/jwt_hs256.key
mkdir -p $slurm_spool_dir
chmod 0755 $slurm_spool_dir
if ! [ -e $jwt_key ]; then
    dd if=/dev/random of=$jwt_key bs=32 count=1
    chown slurm:slurm $jwt_key
    chmod 0600 $jwt_key
fi

echo "$(date): Finished ${script_name}"

exit 0
