#!/bin/bash -xe

full_script=$(realpath $0)
script_dir=$(dirname $full_script)
base_script=$(basename $full_script)

date
echo "Started submitter_deconfigure.sh: $full_script"

config_dir={{SubmitterSlurmConfigDir}}
config_bin_dir=$config_dir/bin

temp_config_dir=/tmp/{{ClusterName}}_config
rm -rf $temp_config_dir
cp -r $config_dir $temp_config_dir

# Configure using ansible
if ! yum list installed ansible &> /dev/null; then
    yum install -y ansible || amazon-linux-extras install -y ansible2
fi

ANSIBLE_PATH=$temp_config_dir/ansible
PLAYBOOKS_PATH=$ANSIBLE_PATH/playbooks

pushd $PLAYBOOKS_PATH
ansible-playbook $PLAYBOOKS_PATH/ParallelClusterSubmitterDeconfigure.yml \
    -i inventories/local.yml \
    -e @$ANSIBLE_PATH/ansible_head_node_vars.yml
popd

rm -rf $temp_config_dir

date
echo "Finished submitter_deconfigure.sh: $full_script"

exit 0
