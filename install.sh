#!/bin/bash -e
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

scriptdir=$(dirname $(readlink -f $0))
repodir=$scriptdir

cd $repodir

# Deactivate any active virtual envs
deactivate &> /dev/null || true

if ! yum list installed make &> /dev/null; then
    echo -e "\nInstalling make"
    if ! sudo yum -y install make; then
        echo -e "\nwarning: Couldn't install make"
    fi
fi

if ! yum list installed wget &> /dev/null; then
    echo -e "\nInstalling wget"
    if ! sudo yum -y install wget; then
        echo -e "\nwarning: Couldn't install wget"
    fi
fi

if ! python3 --version &> /dev/null; then
    echo -e "\nInstalling python3"
    if ! sudo yum -y install python3; then
        echo -e "\nerror: Couldn't find python3 in the path or install it. This is required."
        exit 1
    fi
fi

# Check python version
python_version=$(python3 --version 2>&1 | awk '{print $2}')
python_major_version=$(echo $python_version | cut -d '.' -f 1)
python_minor_version=$(echo $python_version | cut -d '.' -f 2)
if [[ $python_minor_version -lt 7 ]]; then
    echo "error: CDK requires python 3.7 or later. You have $python_version. Update your python3 version."
    exit 1
fi

# Check nodejs version
required_nodejs_version=16.15.0
if ! node -v &> /dev/null; then
    echo -e "\nnode not found in your path."
    echo "Installing nodejs in your home dir. Hit ctrl-c to abort"
    pushd $HOME
    wget https://nodejs.org/dist/v${required_nodejs_version}/node-v${required_nodejs_version}-linux-x64.tar.xz
    tar -xf node-v${required_nodejs_version}-linux-x64.tar.xz
    rm node-v${required_nodejs_version}-linux-x64.tar.xz
    cat >> ~/.bashrc << EOF

# Nodejs
export PATH=$HOME/node-v${required_nodejs_version}-linux-x64/bin:\$PATH
EOF
    source ~/.bashrc
    popd
fi

nodejs_version=$(node -v 2>&1 | awk '{print $1}')
nodejs_version=${nodejs_version:1}
node_major_version=$(echo $nodejs_version | cut -d '.' -f 1)
node_minor_version=$(echo $nodejs_version | cut -d '.' -f 2)
if [[ $node_major_version -lt 14 ]]; then
    echo "error: CDK requires node 14.15.0 or later. You have $nodejs_version. Update your node version."
    exit 1
fi
if [[ $node_major_version -eq 14 ]] && [[ $node_minor_version -lt 6 ]]; then
    echo "error: CDK requires node 14.15.0 or later. You have $nodejs_version. Update your node version."
    exit 1
fi

# Create a local installation of cdk
CDK_VERSION=2.42.1 # If you change the CDK version here, make sure to also change it in source/requirements.txt
if ! cdk --version &> /dev/null; then
    echo "CDK not installed. Installing global version of cdk@$CDK_VERSION."
    if ! npm install -g aws-cdk@$CDK_VERSION; then
        sudo npm install -g aws-cdk@$CDK_VERSION
    fi
fi
version=$(cdk --version | awk '{print $1}')
if [[ $version != $CDK_VERSION ]]; then
    echo "Updating the global version of aws-cdk from version $version to $CDK_VERSION"
    echo "Uninstalling old version: npm uninstall -g aws-cdk"
    npm uninstall -g aws-cdk
    echo "npm install -g aws-cdk@$CDK_VERSION"
    if ! npm install -g aws-cdk@$CDK_VERSION; then
        sudo npm install -g aws-cdk@$CDK_VERSION
    fi
fi

# Create python virtual environment
cd $repodir/source
if [ ! -e $repodir/source/.venv/bin/activate ]; then
    rm -f .requirements_installed
    python3 -m pip install --upgrade virtualenv
    python3 -m venv .venv
fi
source .venv/bin/activate
make .requirements_installed

./installer.py "$@"
