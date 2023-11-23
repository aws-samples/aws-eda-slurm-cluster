#!/bin/bash -x

script=$0

AWS_DEFAULT_REGION={{Region}}
ClusterName={{ClusterName}}
ErrorSnsTopicArn={{ErrorSnsTopicArn}}

# Notify user of errors
function on_exit {
    rc=$?
    set +e
    if [[ $rc -ne 0 ]] && [[ ":$ErrorSnsTopicArn" != ":" ]]; then
        tmpfile=$(mktemp)
        echo "See log files for more info:
    /var/lib/amazon/toe/TOE_*
    grep PCImageBuilderEDA /var/log/messages | less" > $tmpfile
        aws --region $AWS_DEFAULT_REGION sns publish --topic-arn $ErrorSnsTopicArn --subject "${ClusterName} EDAComponent failed" --message file://$tmpfile
        rm $tmpfile
    fi
}
trap on_exit EXIT

# Redirect all IO to /var/log/messages and then echo to stderr
exec 1> >(logger -s -t PCImageBuilderEDA) 2>&1

assets_bucket={{assets_bucket}}
assets_base_key={{assets_base_key}}
playbooks_s3_url={{playbooks_s3_url}}

ansible_head_node_vars_yml_s3_url="s3://$assets_bucket/$assets_base_key/config/ansible/ansible_head_node_vars.yml"
ansible_compute_node_vars_yml_s3_url="s3://$assets_bucket/$assets_base_key/config/ansible/ansible_compute_node_vars.yml"
ansible_submitter_vars_yml_s3_url="s3://$assets_bucket/$assets_base_key/config/ansible/ansible_submitter_vars.yml"

config_dir=/opt/slurm/config
config_bin_dir=$config_dir/bin

mkdir -p $config_bin_dir

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

aws s3 cp $ansible_submitter_vars_yml_s3_url /opt/slurm/config/ansible/ansible_submitter_vars.yml

pushd $PLAYBOOKS_PATH

ansible-playbook $PLAYBOOKS_PATH/eda_tools.yml \
    -i inventories/local.yml \
    -e @$ANSIBLE_PATH/ansible_head_node_vars.yml

popd
