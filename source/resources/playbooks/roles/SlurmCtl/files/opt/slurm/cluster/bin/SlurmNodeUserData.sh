#!/bin/bash -xe
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

function error_exit {
    rc=$?
    if [[ $rc != 0 ]]; then
        $SLURM_ROOT/bin/scontrol update nodename={{hostname}} state=DOWN reason="UserData failed"
        {{SlurmScriptsDir}}/requeue_node_jobs.py
    fi
    exit $rc
}
trap error_exit EXIT

source /etc/profile.d/instance_vars.sh

# Update to latest ssm agent
if [[ $ARCHITECTURE == 'x86_64' ]]; then
    amazon_ssm_agent_url=https://s3.$AWS_DEFAULT_REGION.amazonaws.com/amazon-ssm-$AWS_DEFAULT_REGION/latest/linux_amd64/amazon-ssm-agent.rpm
elif [[ $ARCHITECTURE == 'arm64' ]]; then
    amazon_ssm_agent_url=https://s3.$AWS_DEFAULT_REGION.amazonaws.com/amazon-ssm-$AWS_DEFAULT_REGION/latest/linux_arm64/amazon-ssm-agent.rpm
fi
if yum install -y $amazon_ssm_agent_url; then
    systemctl restart amazon-ssm-agent
else
    if ! yum list installed amazon-ssm-agent &> /dev/null; then
        echo "error: Could not install amazon-ssm-agent"
        exit 1
    fi
fi
systemctl enable amazon-ssm-agent || true

# Make sure awscli is installed. Requires epel-release
if ! yum list installed epel-release &> /dev/null; then
    if [[ $Distribution == 'Amazon' ]]; then
        amazon-linux-extras install -y epel
    else
        if [[ $DistributionVersion == '7' ]]; then
            yum -y install epel-release || yum -y install https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm
        elif [[ $DistributionVersion == '8' ]]; then
            yum -y install epel-release || yum -y install https://dl.fedoraproject.org/pub/epel/epel-release-latest-8.noarch.rpm
        fi
    fi
fi
if ! yum list installed ansible &> /dev/null; then
    if [[ $Distribution == 'Amazon' ]]; then
        amazon-linux-extras install -y epel
    else
        yum -y install ansible
    fi
fi
if ! yum list installed unzip &> /dev/null; then
    yum -y install unzip
fi
export PATH=/usr/local/bin:$PATH
if ! aws --version &> /dev/null; then
    pushd /tmp
    rm -f awscliv2.zip
    rm -rf aws
    if [[ $ARCHITECTURE == 'x86_64' ]]; then
        awscli_url=https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip
    elif [[ $ARCHITECTURE == 'arm64' ]]; then
        awscli_url=https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip
    fi
    curl "$awscli_url" -o "awscliv2.zip"
    unzip awscliv2.zip
    ./aws/install --update
    rm -f awscliv2.zip
    rm -rf aws
    popd
fi

ipaddress=$(hostname -I)
# munge needs to be running before calling scontrol
cp {{SlurmConfigDir}}/munge.key /etc/munge/munge.key
systemctl enable munged
systemctl start munged

$SLURM_ROOT/bin/scontrol update nodename={{hostname}} nodeaddr=$ipaddress

# Set hostname
hostname={{hostname}}
hostname_fqdn={{hostname}}.{{DOMAIN}}
if [ $(hostname) != $hostname_fqdn ]; then
    hostnamectl --static set-hostname $hostname_fqdn
    hostnamectl --pretty set-hostname $hostname
fi

if [ -e {{SlurmConfigDir}}/users_groups.json ] && [ -e {{SlurmScriptsDir}}/create_users_groups.py ]; then
    {{SlurmScriptsDir}}/create_users_groups.py -i {{SlurmConfigDir}}/users_groups.json
fi

# Create directory for slurmd.log
logs_dir={{SlurmLogsDir}}/nodes/{{hostname}}
if [[ ! -d $logs_dir ]]; then
    mkdir -p $logs_dir
fi
if [[ -e /var/log/slurm ]]; then
    rm -rf /var/log/slurm
fi
ln -s $logs_dir /var/log/slurm

systemctl enable slurmd
systemctl start slurmd
# Restart so that log file goes to file system
systemctl restart spot_monitor
