# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# This is the first thing to run in the user_data

script=$(readlink -f $0)
script_name=$(basename $script)

# Rerun after reboot
# We want the user_data to be run every time the instance boots so that all of the latest S3 assets and other configuration is downloaded.
# But this is only for the AMI instances.
# Check the "role" tag and delete the rerun script if not "slurm_node_ami"
old_rerun_script=/var/lib/cloud/scripts/per-boot/10_user_data
rm -f $old_rerun_script
rerun_script=/var/lib/cloud/scripts/per-boot/10_slurm_node_ami_user_data
AWS_INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)
node_type=$(aws ec2 describe-tags --filters '[{"Name":"resource-id","Values":["'$AWS_INSTANCE_ID'"]},{"Name":"tag:NodeType","Values":["*"]}]' --query 'Tags[0].Value' --output text)
if [[ $node_type == 'slurm_node_ami' ]]; then
    ln -sf $script $rerun_script
else
    trap - EXIT
    rm -f $rerun_script
    exit 0
fi
