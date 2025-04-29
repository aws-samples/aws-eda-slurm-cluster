# This file should be sourced, not executed, to set up the environment.
#
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

scriptdir=$(dirname $(readlink -f ${BASH_SOURCE[0]}))
repodir=$scriptdir

pushd $repodir

arch=$(uname -m)
if [[ $arch == 'x86_64' ]]; then
    shortarch='x86'
else
    shortarch=$arch
fi
if [[ $(uname -s) == 'Linux' ]]; then
    os=linux
    installer='sudo yum -y'
    shellrc='.bashrc'
elif [[ $(uname -s) == 'Darwin' ]]; then
    os=macos
    installer='brew'
    shellrc='.zshrc'
else
    echo "error: Unsupported OS $(uname -s)"
    return 1
fi

if ! make --version &> /dev/null; then
    echo -e "\nInstalling make"
    if ! $installer install make; then
        echo -e "\nwarning: Couldn't install make"
    fi
fi

if ! wget --version &> /dev/null; then
    echo -e "\nInstalling wget"
    if ! $installer install wget; then
        echo -e "\nwarning: Couldn't install wget"
    fi
fi

if ! python3 --version &> /dev/null; then
    echo -e "\nInstalling python3"
    if ! $installer install python3; then
        echo -e "\nerror: Couldn't find python3 in the path or install it. This is required."
        return 1
    fi
fi

# Check python version
python_version=$(python3 --version 2>&1 | awk '{print $2}')
python_major_version=$(echo $python_version | cut -d '.' -f 1)
python_minor_version=$(echo $python_version | cut -d '.' -f 2)
if [[ $python_minor_version -lt 7 ]]; then
    echo "error: CDK requires python 3.7 or later. You have $python_version. Update your python3 version."
    return 1
fi
echo "Using python $python_version"

# Check nodejs version
# https://nodejs.org/en/about/previous-releases
if [[ $os == 'macos' ]]; then
    required_nodejs_version=20.19.0
else
    # linux
    required_nodejs_version=16.20.2
fi
# required_nodejs_version=18.20.2
# On Amazon Linux 2 and nodejs 18.20.2 I get the following errors:
#     node: /lib64/libm.so.6: version `GLIBC_2.27' not found (required by node)
#     node: /lib64/libc.so.6: version `GLIBC_2.28' not found (required by node)
# required_nodejs_version=20.13.1
# On Amazon Linux 2 and nodejs 20.13.1 I get the following errors:
#     node: /lib64/libm.so.6: version `GLIBC_2.27' not found (required by node)
#     node: /lib64/libc.so.6: version `GLIBC_2.28' not found (required by node)
export JSII_SILENCE_WARNING_DEPRECATED_NODE_VERSION=1
if ! which node &> /dev/null; then
    echo -e "\nnode not found in your path."
    echo "Installing nodejs in your home dir."
    nodejs_version=None
else
    nodejs_version=$(node -v 2>&1 | awk '{print $1}')
    nodejs_version=${nodejs_version:1}
    node_major_version=$(echo $nodejs_version | cut -d '.' -f 1)
    node_minor_version=$(echo $nodejs_version | cut -d '.' -f 2)
    if [[ $node_major_version -lt 14 ]]; then
        echo "error: CDK requires node 14.15.0 or later. You have $nodejs_version. Update your node version."
        return 1
    fi
    if [[ $node_major_version -eq 14 ]] && [[ $node_minor_version -lt 6 ]]; then
        echo "error: CDK requires node 14.15.0 or later. You have $nodejs_version. Update your node version."
        return 1
    fi
    if [[ $nodejs_version != $required_nodejs_version ]]; then
        echo "Updating nodejs version from $nodejs_version to $required_nodejs_version"
    fi
fi

if [[ $nodejs_version != $required_nodejs_version ]]; then
    echo "Installing nodejs ${required_nodejs_version} in your home dir. Hit ctrl-c to abort"
    pushd $HOME
    if [[ $os == 'linux' ]]; then
        nodedir=node-v${required_nodejs_version}-linux-${shortarch}
    elif [[ $os == 'macos' ]]; then
        nodedir=node-v${required_nodejs_version}-darwin-${shortarch}
    fi
    tarball=${nodedir}.tar.xz
    wget https://nodejs.org/dist/v${required_nodejs_version}/$tarball
    tar -xf $tarball
    rm $tarball
    cat >> ~/$shellrc << EOF

# Nodejs
export PATH=$HOME/$nodedir/bin:\$PATH
EOF
    source ~/$shellrc
    popd
fi

echo "Using nodejs version $nodejs_version"

# Create a local installation of cdk
CDK_VERSION=2.179.0 # When you change the CDK version here, make sure to also change it in source/requirements.txt
if ! cdk --version &> /dev/null; then
    echo "CDK not installed. Installing global version of cdk@$CDK_VERSION."
    if ! npm install -g aws-cdk@$CDK_VERSION; then
        sudo npm install -g aws-cdk@$CDK_VERSION
    fi
fi
cdk_version=$(cdk --version | awk '{print $1}')
if [[ $cdk_version != $CDK_VERSION ]]; then
    echo "Updating the global version of aws-cdk from version $cdk_version to $CDK_VERSION"
    echo "Uninstalling old version: npm uninstall -g aws-cdk"
    npm uninstall -g aws-cdk
    echo "npm install -g aws-cdk@$CDK_VERSION"
    if ! npm install -g --force aws-cdk@$CDK_VERSION; then
        sudo npm install -g --force aws-cdk@$CDK_VERSION
    fi
fi
echo "Using CDK $cdk_version"

# Create python virtual environment
cd $repodir/source
if [ ! -e $repodir/source/.venv/bin/activate ]; then
    rm -f .requirements_installed
    python3 -m pip install --upgrade virtualenv
    python3 -m venv .venv
fi
source .venv/bin/activate
make .requirements_installed

popd
