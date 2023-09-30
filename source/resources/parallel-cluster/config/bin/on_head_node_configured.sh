#!/bin/bash -x

set -x

exec 1> >(logger -s -t on_head_node_configured.sh) 2>&1

full_script=$(realpath $0)
script_dir=$(dirname $full_script)
base_script=$(basename $full_script)

date
echo "Started on_head_node_configured.sh: $full_script"

config_dir=/opt/slurm/config
config_bin_dir=$config_dir/bin
ANSIBLE_PATH=$config_dir/ansible
PLAYBOOKS_PATH=$ANSIBLE_PATH/playbooks

dest_script="$config_bin_dir/on_head_node_configured.sh"
if [ $full_script != $dest_script ]; then
    echo "cp $full_script $dest_script"
    cp $full_script $dest_script
    chmod 0700 $dest_script
fi

export PATH=/usr/sbin:$PATH

$config_bin_dir/on_head_node_start.sh

pushd $PLAYBOOKS_PATH
ansible-playbook $PLAYBOOKS_PATH/ParallelClusterHeadNode.yml \
    -i inventories/local.yml \
    -e @$ANSIBLE_PATH/ansible_head_node_vars.yml
popd

date
echo "Finished on_head_node_configured.sh: $full_script"

exit 0
