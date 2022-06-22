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
if [[ $python_minor_version -lt 6 ]]; then
    echo "error: CDK requires python 3.6 or later. You have $python_version. Update your python3 version."
    exit 1
fi

if ! node -v &> /dev/null; then
    echo -e "\nnode not found in your path."
    echo "Installing nodejs in your home dir. Hit ctrl-c to abort"
    pushd $HOME
    wget https://nodejs.org/dist/v16.13.1/node-v16.13.1-linux-x64.tar.xz
    tar -xf node-v16.13.1-linux-x64.tar.xz
    rm node-v16.13.1-linux-x64.tar.xz
    cat >> ~/.bashrc << EOF

# Nodejs
export PATH=$HOME/node-v16.13.1-linux-x64/bin:\$PATH
EOF
    source ~/.bashrc
    popd
fi
# Check node version
node_version=$(node -v 2>&1 | awk '{print $1}')
node_version=${node_version:1}
node_major_version=$(echo $node_version | cut -d '.' -f 1)
node_minor_version=$(echo $node_version | cut -d '.' -f 2)
if [[ $node_major_version -lt 14 ]]; then
    echo "error: CDK requires node 14.15.0 or later. You have $node_version. Update your node version."
    exit 1
fi
if [[ $node_major_version -eq 14 ]] && [[ $node_minor_version -lt 6 ]]; then
    echo "error: CDK requires node 14.15.0 or later. You have $node_version. Update your node version."
    exit 1
fi

# Create a local installation of cdk
CDK_VERSION=2.21.1 # If you change the CDK version here, make sure to also change it in source/requirements.txt
if ! cdk --version &> /dev/null; then
    echo "CDK not installed. Installing global version of cdk@$CDK_VERSION."
    sudo npm install -g aws-cdk@$CDK_VERSION
fi
version=$(cdk --version | awk '{print $1}')
if [[ $version != $CDK_VERSION ]]; then
    echo "Updating the global version of aws-cdk from version $version to $CDK_VERSION"
    sudo npm install -g aws-cdk@$CDK_VERSION
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
