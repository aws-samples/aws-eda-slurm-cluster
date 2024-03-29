# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# The environment variables are set before this part of the user_data runs.

script=$(readlink -f $0)
script_name=$(basename $script)

# Tag EBS disks manually
AWS_AVAIL_ZONE=$(curl -s http://169.254.169.254/latest/meta-data/placement/availability-zone)
AWS_INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)
EBS_IDS=$(aws ec2 describe-volumes --filters Name=attachment.instance-id,Values="$AWS_INSTANCE_ID" --region $AWS_DEFAULT_REGION --query "Volumes[*].[VolumeId]" --out text | tr "\n" " ")
aws ec2 create-tags --resources $EBS_IDS --region $AWS_DEFAULT_REGION --tags Key=Name,Value="${STACK_NAME} SlurmNodeAMI Root Disk"

# Tag Network Adapter
ENI_IDS=$(aws ec2 describe-network-interfaces --filters Name=attachment.instance-id,Values="$AWS_INSTANCE_ID" --region $AWS_DEFAULT_REGION --query "NetworkInterfaces[*].[NetworkInterfaceId]" --out text | tr "\n" " ")
aws ec2 create-tags --resources $ENI_IDS --region $AWS_DEFAULT_REGION --tags Key=Name,Value="${STACK_NAME} SlurmNodeAMI Network Adapter"

chmod +x $CONFIG_SCRIPT_PATH
$CONFIG_SCRIPT_PATH
