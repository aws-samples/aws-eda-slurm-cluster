#!/bin/bash -xe

full_script=$(realpath $0)
script_dir=$(dirname $full_script)
base_script=$(basename $full_script)

date
echo "Started submitter_configure.sh: $full_script"

config_dir={{SubmitterSlurmConfigDir}}
config_bin_dir=$config_dir/bin

assets_bucket={{assets_bucket}}
assets_base_key={{assets_base_key}}

# Configure using ansible
if ! yum list installed ansible &> /dev/null; then
    yum install -y ansible || amazon-linux-extras install -y ansible2
fi

ANSIBLE_PATH=$config_dir/ansible
PLAYBOOKS_PATH=$ANSIBLE_PATH/playbooks

pushd $PLAYBOOKS_PATH
ansible-playbook $PLAYBOOKS_PATH/ParallelClusterSubmitterConfigure.yml \
    -i inventories/local.yml \
    -e @$ANSIBLE_PATH/ansible_submitter_vars.yml
popd

date
echo "Finished submitter_configure.sh: $full_script"

exit 0
