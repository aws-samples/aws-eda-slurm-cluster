#!/bin/bash -x

full_script=$(realpath $0)
script_dir=$(dirname $full_script)
base_script=$(basename $full_script)

date
echo "Started on_compute_node_start.sh: $full_script"

config_dir=/opt/slurm/config
config_bin_dir=$config_dir/bin

assets_bucket={{assets_bucket}}
assets_base_key={{assets_base_key}}

dest_script="$config_bin_dir/on_compute_node_start.sh"
if [ $full_script != $dest_script ]; then
    echo "cp $full_script $dest_script"
    cp $full_script $dest_script
    chmod 0700 $dest_script
fi

$config_bin_dir/create_users_groups.py -i $config_dir/users_groups.json

date
echo "Finished on_compute_node_start.sh: $full_script"

exit 0
