#!/bin/bash -x

set -x

exec 1> >(logger -s -t on_compute_node_configured.sh) 2>&1

full_script=$(realpath $0)
script_dir=$(dirname $full_script)
base_script=$(basename $full_script)

date
echo "Started on_compute_node_configured.sh: $full_script"

config_dir=/opt/slurm/config
config_bin_dir=$config_dir/bin

assets_bucket={{assets_bucket}}
assets_base_key={{assets_base_key}}

dest_script="$config_bin_dir/on_compute_node_configured.sh"
if [ $full_script != $dest_script ]; then
    echo "cp $full_script $dest_script"
    cp $full_script $dest_script
    chmod 0700 $dest_script
fi

export PATH=/usr/sbin:$PATH

echo "Creating users and groups"
$config_bin_dir/create_users_groups.py -i $config_dir/users_groups.json

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

date
echo "Finished on_compute_node_configured.sh: $full_script"

exit 0
