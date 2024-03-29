#!/bin/bash -xe
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

source /etc/profile.d/instance_vars.sh

function on_exit {
    rc=$?
    set +e

    if [[ $rc -ne 0 ]] && [[ ":$ERROR_SNS_TOPIC_ARN" != ":" ]]; then
        msg_file=$(mktemp)
        echo -e "\nINSTANCE NAME: $INSTANCE_NAME" > $msg_file
        echo -e "\nINSTANCE ID:   $instance_id"   >> $msg_file
        echo -e "\ngrep cloud-init /var/log/messages | tail -n 200:\n\n" >> $msg_file
        grep cloud-init /var/log/messages |tail -n 200 >> $msg_file
        if [ -e /var/log/cloud-init.log ]; then
            echo -e "\n\n\ntail -n 200 /var/log/cloud-init.log:\n\n" >> $msg_file
            tail -n 200 /var/log/cloud-init.log >> $msg_file
        fi

        # --subject is limited to 100 characters
        aws sns publish --region $AWS_DEFAULT_REGION --topic-arn $ERROR_SNS_TOPIC_ARN --subject "$instance_id $0 Failed" --message "file://$msg_file"
        rm $msg_file
    fi

    # Make sure that security patches that require a reboot are applied
    if ! needs-restarting -r; then
        reboot
    fi
}
trap on_exit EXIT

instance_id=$(curl --silent http://169.254.169.254/latest/meta-data/instance-id)

# Don't do anything after the reboot caused by AMI creation.
# Wait for the AMI to be available and then stop the instance.
if [ -e /var/lib/cloud/instance/sem/ami.txt ]; then
    ami=$(cat /var/lib/cloud/instance/sem/ami.txt)
    echo "First reboot after ami ($ami) created."
    chmod +x /root/WaitForAmi.py
    if ! /root/WaitForAmi.py --ami-id $ami --base-ssm-parameter $SlurmNodeAmiSsmParameterBaseName --instance-id $instance_id --compute-regions $ComputeRegions; then
        echo "Could not wait for AMI. Do not try to create a new one because it may be a problem with the WaitForAmi.py script."
        exit 1
    else
        # Delete the semaphore so that if the instance reboots because of template changes then a new AMI will be created
        mv /var/lib/cloud/instance/sem/ami.txt /var/lib/cloud/instance/sem/$ami.txt
        exit 0
    fi
fi

# Install security updates first.
# Since this is Amazon Linux 2 don't need to configure proxy because yum repos are in S3.
# Disable epel because it isn't in S3 and requires configuration.
if [ $DISTRIBUTION == 'AlmaLinux' ]; then
    yum -y update --security --bugfix --skip-broken --nobest
else
    yum -y update --security --bugfix --skip-broken
fi

export PATH=/usr/local/bin:$PATH

# Configure using ansible
if ! yum list installed epel-release &> /dev/null; then
    amazon-linux-extras install -y epel || yum -y install epel-release || yum -y install https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm
fi
if ! yum list installed ansible &> /dev/null; then
    amazon-linux-extras install -y ansible2 || yum -y install ansible
fi
if ! aws --version &> /dev/null; then
    export PATH=/usr/local/bin:$PATH
fi
if ! yum list installed unzip &> /dev/null; then
    yum -y install unzip
fi

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
ansible-playbook $PLAYBOOKS_PATH/SlurmNodeAmi.yml \
    -i inventories/local.yml \
    -e @/root/ansible_extra_vars.yml
popd

# Save logs for debugging problems, delete the rest
mkdir -p /root/logs
mv /var/log/ansible.log /root/logs || true
mv /var/log/messages /root/logs || true
rm -f /var/log/* || true
rm -f /var/log/amazon/* || true
rm -f /var/log/chrony/* || true
rm -f /var/log/slurm/* || true
rm -f /var/log/tuned/* || true

ami_id=$(aws ec2 create-image --instance-id $instance_id --name ${STACK_NAME}-SlurmNode-$DISTRIBUTION-$DISTRIBUTION_MAJOR_VERSION-$ARCHITECTURE-$(date '+%Y-%m-%d-%H-%M-%S') --output text)
aws ec2 create-tags --resources $ami_id --tags Key=Name,Value="${STACK_NAME}-SlurmNodeAMI-$DISTRIBUTION-$DISTRIBUTION_MAJOR_VERSION-$ARCHITECTURE"
aws ec2 create-tags --resources $ami_id --tags Key=Stack,Value="${STACK_NAME}"
aws ec2 create-tags --resources $ami_id --tags Key=ClusterName,Value="${ClusterName}"
echo $ami_id > /var/lib/cloud/instance/sem/ami.txt
