# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

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

# Install epel-release. Contains ansible
if ! yum list installed epel-release &> /dev/null; then
    if [[ $DISTRIBUTION == 'Amazon' ]]; then
        amazon-linux-extras install -y epel
    else
        if [[ $DISTRIBUTION_MAJOR_VERSION == '7' ]]; then
            yum -y install epel-release || yum -y install https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm
        elif [[ $DISTRIBUTION_MAJOR_VERSION == '8' ]]; then
            yum -y install epel-release || yum -y install https://dl.fedoraproject.org/pub/epel/epel-release-latest-8.noarch.rpm
        fi
    fi
fi

# Install ansible
if [ $DISTRIBUTION == 'AlmaLinux' ] || ([ $DISTRIBUTION == 'RedHat' ] && [ $DISTRIBUTION_MAJOR_VERSION == '8' ]); then
    if ! yum list installed ansible-core &> /dev/null; then
        yum -y install ansible-core ansible-collection-ansible-posix ansible-collection-community-general
    fi
elif [ $DISTRIBUTION == 'Amazon' ]; then
    if ! yum list installed ansible &> /dev/null; then
        amazon-linux-extras install -y ansible2
    fi
else
    if ! yum list installed ansible &> /dev/null; then
        yum -y install ansible
    fi
fi

# Install unzip. Used to install awscli
if ! yum list installed unzip &> /dev/null; then
    yum -y install unzip
fi

# Add path to aws cli
export PATH=/usr/local/bin:$PATH

# Install/update awscli to make sure running version 2
if ! aws --version | grep aws-cli/2; then
    pushd /tmp
    if yum list installed awscli &> /dev/null; then
        yum -y remove awscli
    fi
    rm -rf /usr/local/aws-cli
    rm -f awscliv2.zip
    rm -rf aws
    if [[ $ARCHITECTURE == 'x86_64' ]]; then
        awscli_url=https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip
    elif [[ $ARCHITECTURE == 'arm64' ]]; then
        awscli_url=https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip
    else
        echo "error: Unsupported $ARCHITECTURE architecture"
        exit 1
    fi
    curl "$awscli_url" -o "awscliv2.zip"
    unzip -q awscliv2.zip
    ./aws/install
    rm -f awscliv2.zip
    rm -rf aws
    popd
    if ! aws --version | grep aws-cli/2; then
        echo "error: Could not update awscli to v2"
        exit 1
    fi
fi
