# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# Rerun after reboot
script=$(readlink -f $0)
script_name=$(basename $script)
rerun_script=/var/lib/cloud/scripts/per-boot/10_$script_name
ln -sf $script $rerun_script

# Tag EBS disks manually as CFN ASG does not support it
AWS_AVAIL_ZONE=$(curl http://169.254.169.254/latest/meta-data/placement/availability-zone)
AWS_REGION="`echo \"$AWS_AVAIL_ZONE\" | sed "s/[a-z]$//"`"
AWS_INSTANCE_ID=$(curl http://169.254.169.254/latest/meta-data/instance-id)
EBS_IDS=$(aws ec2 describe-volumes --filters Name=attachment.instance-id,Values="$AWS_INSTANCE_ID" --region $AWS_DEFAULT_REGION --query "Volumes[*].[VolumeId]" --out text | tr "\n" " ")
aws ec2 create-tags --resources $EBS_IDS --region $AWS_DEFAULT_REGION --tags Key=Name,Value="${STACK_NAME} SLURM DB Root Disk"

# Tag Network Adapter for the Proxy
ENI_IDS=$(aws ec2 describe-network-interfaces --filters Name=attachment.instance-id,Values="$AWS_INSTANCE_ID" --region $AWS_DEFAULT_REGION --query "NetworkInterfaces[*].[NetworkInterfaceId]" --out text | tr "\n" " ")
aws ec2 create-tags --resources $ENI_IDS --region $AWS_DEFAULT_REGION --tags Key=Name,Value="${STACK_NAME} SLURM DB Network Adapter"

chmod +x $CONFIG_SCRIPT_PATH
$CONFIG_SCRIPT_PATH
