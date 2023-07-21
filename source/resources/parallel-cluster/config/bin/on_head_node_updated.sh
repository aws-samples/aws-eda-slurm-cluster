#!/bin/bash -x

full_script=$(realpath $0)
script_dir=$(dirname $full_script)
base_script=$(basename $full_script)

date
echo "Started on_head_node_updated.sh: $full_script"

config_dir=/opt/slurm/config
config_bin_dir=$config_dir/bin

dest_script="$config_bin_dir/on_head_node_updated.sh"
if [ $full_script != $dest_script ]; then
    echo "cp $full_script $dest_script"
    cp $full_script $dest_script
    chmod 0700 $dest_script
fi

$config_bin_dir/on_head_node_configured.sh

date
echo "Finished on_head_node_updated.sh: $full_script"

exit 0
