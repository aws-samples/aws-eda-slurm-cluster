#!/bin/bash -xe
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

source /etc/profile.d/instance_vars.sh

function on_exit {
    rc=$?
    set +e

    if [[ $rc -ne 0 ]] && [[ ":$ERROR_SNS_TOPIC_ARN" != ":" ]]; then
        aws sns publish --region $AWS_DEFAULT_REGION --topic-arn $ERROR_SNS_TOPIC_ARN --subject "$INSTANCE_NAME slurmctl_config.sh failed" --message "See /var/log/cloud-init.log or grep cloud-init /var/log/messages | less for more info."
    fi

    # Make sure that security patches that require a reboot are applied
    if ! needs-restarting -r; then
        reboot
    fi
}
trap on_exit EXIT

# Install security updates first.
# Since this is Amazon Linux 2 don't need to configure proxy because yum repos are in S3.
# Disable epel because it isn't in S3 and requires configuration.
yum -y update --security --bugfix

# Update to latest ssm agent
if yum install -y https://s3.$AWS_DEFAULT_REGION.amazonaws.com/amazon-ssm-$AWS_DEFAULT_REGION/latest/linux_amd64/amazon-ssm-agent.rpm; then
    systemctl restart amazon-ssm-agent
fi

# Configure using ansible
if ! yum list installed ansible &> /dev/null; then
    amazon-linux-extras install -y ansible2
fi

hostnamectl set-hostname --static $SlurmCtlHostname.$Domain

PLAYBOOKS_PATH=/root/playbooks
if [ -e $PLAYBOOKS_ZIP_PATH ]; then
    rm -rf $PLAYBOOKS_PATH
    mkdir -p $PLAYBOOKS_PATH
    pushd $PLAYBOOKS_PATH
    unzip -q $PLAYBOOKS_ZIP_PATH
    rm $PLAYBOOKS_ZIP_PATH
    popd
fi

pushd $PLAYBOOKS_PATH
ansible-playbook $PLAYBOOKS_PATH/SlurmCtl.yml \
    -i inventories/local.yml \
    -e @/root/ansible_extra_vars.yml
popd

# Disable automatic motd update
/usr/sbin/update-motd --disable
rm -f /etc/cron.d/update-motd
rm -f /etc/update-motd.d/*

# Set up motd
if ! yum list installed figlet &> /dev/null; then
    yum install -y figlet
fi
figlet -f slant "SlurmCtl" > /etc/motd
echo -e "Stack Name: ${STACK_NAME}
" >> /etc/motd
