#!/bin/bash -x

set -x

exec 1> >(logger -s -t on_compute_node_start.sh) 2>&1

full_script=$(realpath $0)
script_dir=$(dirname $full_script)
base_script=$(basename $full_script)

date
echo "Started on_compute_node_start.sh: $full_script"

# /opt/slurm isn't mounted yet.

export PATH=/usr/sbin:$PATH

date
echo "Finished on_compute_node_start.sh: $full_script"

exit 0
