# This file should be sourced, not executed, to set up the environment.
#
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

set -e
set -x

# Function to display error messages
function error() {
    echo -e "\033[31mERROR: $1\033[0m" >&2
    exit 1
}

# Function to display info messages
function info() {
    echo -e "\033[32mINFO: $1\033[0m"
}

scriptdir=$(dirname $(readlink -f ${BASH_SOURCE[0]}))
repodir=$scriptdir

pushd $repodir

# Detect operating system
OS="$(uname -s)"
info "Detected operating system: $OS"

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


case "$OS" in
    Linux)
        # Check if script is run as non-root user
        if [ "$EUID" -eq 0 ]; then
            error "This script must be run as a non-root user for rootless Docker installation on Linux"
        fi

        # Install dependencies for Linux
        info "Installing Linux dependencies..."

        # Install packages based on package manager
        if command -v yum &>/dev/null; then
            sudo yum -y install curl iptables fuse-overlayfs slirp4netns || error "Failed to install dependencies"
        elif command -v apt-get &>/dev/null; then
            sudo apt-get -y install curl iptables fuse-overlayfs slirp4netns || error "Failed to install dependencies"
        else
            error "Unsupported Linux distribution. Please install Docker manually."
        fi

        # Install rootless Docker on Linux
        info "Installing rootless Docker for Linux..."

        # Check if running on Amazon Linux 2
        if grep -q "Amazon Linux 2" /etc/os-release; then
            sudo yum install -y amazon-linux-extras \
                shadow-utils \
                util-linux \
                curl \
                tar \
                gcc \
                make \
                shadow-utils \
                containerd \
                iproute \
                fuse-overlayfs \
                iptables \
                git || error "Failed to install dependencies"

            # # Setup user namespaces
            # info "Setting up user namespaces..."
            # sudo sh -c 'echo "user.max_user_namespaces=28633" > /etc/sysctl.d/99-userns.conf'
            # sudo sysctl --system || error "Failed to apply sysctl settings"

            # Install slirp4netns for rootless networking
            if ! command -v slirp4netns &>/dev/null; then
                info "Installing slirp4netns..."
                cd /tmp
                SLIRP4NETNS_VERSION="1.2.0"
                curl -LO "https://github.com/rootless-containers/slirp4netns/releases/download/v${SLIRP4NETNS_VERSION}/slirp4netns-$(uname -m)"
                chmod +x slirp4netns-$(uname -m)
                sudo mv slirp4netns-$(uname -m) /usr/local/bin/slirp4netns
                cd -
            fi
            cat <<EOF | sudo sh -x
curl -o /etc/yum.repos.d/vbatts-shadow-utils-newxidmap-epel-7.repo https://copr.fedorainfracloud.org/coprs/vbatts/shadow-utils-newxidmap/repo/epel-7/vbatts-shadow-utils-newxidmap-epel-7.repo
yum -y install shadow-utils46-newxidmap
EOF
        fi

        # Check if Docker is already installed
        if command -v docker &> /dev/null; then
            info "Docker is already installed. Checking if it's rootless..."
            if [ -f "$HOME/.config/systemd/user/docker.service" ]; then
                info "Rootless Docker is already installed"
            else
                info "Installing rootless Docker mode..."
                export FORCE_ROOTLESS_INSTALL=1
                export SKIP_IPTABLES=1
                curl -fsSL https://get.docker.com/rootless | sh || error "Failed to install rootless Docker"
            fi
        else
            info "Installing Docker rootless..."
            curl -fsSL https://get.docker.com/rootless | sh || error "Failed to install rootless Docker"
        fi

        # Add Docker to PATH if not already there
        if ! grep -q "PATH=.*docker" "$HOME/.bashrc" 2>/dev/null; then
            echo 'export PATH=/usr/bin:$PATH:$HOME/bin:$HOME/.local/bin' >> "$HOME/.bashrc"
            echo 'export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock' >> "$HOME/.bashrc"
        fi

        # Source the updated PATH
        export PATH=/usr/bin:$PATH:$HOME/bin:$HOME/.local/bin
        export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock

        # Start the Docker service for Linux
        systemctl --user start docker 2>/dev/null || true
        systemctl --user enable docker 2>/dev/null || true
        ;;

    Darwin)
        # macOS Docker installation
        info "Installing Docker for macOS..."

        # Check if Homebrew is installed
        if ! command -v brew &>/dev/null; then
            info "Installing Homebrew..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || error "Failed to install Homebrew"
        fi

        # Check if Docker is already installed via Homebrew
        if ! command -v docker &>/dev/null; then
            info "Installing Docker via Homebrew..."
            brew install --cask docker || error "Failed to install Docker"

            info "Starting Docker for Mac..."
            open /Applications/Docker.app
            info "Please complete the Docker setup if prompted."
            info "Waiting for Docker to start... (this may take a minute)"
        else
            info "Docker is already installed, ensuring it's running..."
            if ! docker ps &>/dev/null; then
                open -a Docker 2>/dev/null || true
                info "Starting Docker... Please wait"
            fi
        fi
        ;;

    *)
        error "Unsupported operating system: $OS"
        ;;
esac

# Wait for Docker to be ready
info "Waiting for Docker daemon to be ready..."
timeout=60  # Increased timeout for macOS which may take longer to start Docker
while ! docker info &>/dev/null && [ $timeout -gt 0 ]; do
    sleep 2
    timeout=$((timeout-2))
    echo -n "."
done
echo ""

if ! docker info &>/dev/null; then
    error "Docker daemon did not become ready in time"
fi

info "Docker installation and setup complete!"

# Create a Dockerfile for Rocky Linux 9 with Python 3.12, Node.js 20.19.0, and CDK 2.179
info "Creating Dockerfile for Rocky Linux 9 container..."
cat > Dockerfile << 'EOL'
FROM rockylinux:9

# Install development tools and necessary dependencies
RUN dnf -y update && \
    dnf -y install epel-release && \
    dnf -y install gcc gcc-c++ make wget openssl-devel bzip2-devel libffi-devel zlib-devel \
                   readline-devel sqlite-devel tar xz sudo git which

# Install Python 3.12
RUN cd /tmp && \
    wget https://www.python.org/ftp/python/3.12.1/Python-3.12.1.tgz && \
    tar xzf Python-3.12.1.tgz && \
    cd Python-3.12.1 && \
    ./configure --enable-optimizations && \
    make altinstall && \
    ln -sf /usr/local/bin/python3.12 /usr/bin/python3 && \
    ln -sf /usr/local/bin/python3.12 /usr/bin/python && \
    ln -sf /usr/local/bin/pip3.12 /usr/bin/pip3 && \
    ln -sf /usr/local/bin/pip3.12 /usr/bin/pip && \
    cd /tmp && rm -rf Python-3.12.1*

# Install Node.js 20.19.0
RUN cd /tmp && \
    wget https://nodejs.org/dist/v20.19.0/node-v20.19.0-linux-x64.tar.xz && \
    tar -xf node-v20.19.0-linux-x64.tar.xz && \
    mv node-v20.19.0-linux-x64 /usr/local/node-v20.19.0 && \
    ln -sf /usr/local/node-v20.19.0/bin/node /usr/bin/node && \
    ln -sf /usr/local/node-v20.19.0/bin/npm /usr/bin/npm && \
    ln -sf /usr/local/node-v20.19.0/bin/npx /usr/bin/npx && \
    cd /tmp && rm -rf node-v20.19.0-linux-x64*

# Install AWS CDK 2.179.0
RUN npm install -g aws-cdk@2.179.0

# Create a working directory
WORKDIR /app

# Create a mount point for repo so can run install script
RUN mkdir -p /app/aws-eda-slurm-cluster

# Add a script that can receive command line arguments
COPY run_script.sh /app/
RUN chmod +x /app/run_script.sh

ENTRYPOINT ["/app/run_script.sh"]
EOL

# Create a sample script to run in the container that can receive arguments
info "Creating a sample script to run in the container..."
cat > run_script.sh << 'EOL'
#!/bin/bash

echo "Running inside Rocky Linux 9 container"
echo "Python version: $(python3 --version)"
echo "Node.js version: $(node --version)"
echo "CDK version: $(cdk --version)"
echo ""
echo "Command line arguments received:"

# Print all received arguments
for arg in "$@"; do
    echo "- $arg"
done

# Demonstrate access to shared data
echo ""
echo "Contents of shared directory:"
ls -la /app/shared_data/

# Write to shared directory
echo "This file was created inside the container - $(date)" > /app/shared_data/container_file.txt
echo "Created a file in the shared directory: /app/shared_data/container_file.txt"

# You can add your specific script logic here
# For example, you might want to run a CDK command with the provided arguments:
# if [ "$1" == "deploy" ]; then
#     cdk deploy "$2"
# fi
EOL

chmod +x run_script.sh

# Build the Docker image
info "Building Docker image..."
docker build -t rocky-cdk-image . || error "Failed to build Docker image"

# Run the container with command line arguments and mounted directory
info "Running container with sample arguments and mounted directory..."
docker run --rm -v "$SHARED_DIR:/app/shared_data" rocky-cdk-image "arg1" "arg2" "example argument 3"

info "Checking shared directory after container execution:"
ls -la "$SHARED_DIR"

info "Script execution completed successfully!"
info "You can now run your container with your own arguments using:"
info "docker run --rm -v \"$SHARED_DIR:/app/shared_data\" rocky-cdk-image [your arguments]"
info ""
info "The shared directory at $SHARED_DIR is available inside the container at /app/shared_data"
info "Any files you place in this directory will be accessible from the container, and"
info "any files the container writes to /app/shared_data will appear in $SHARED_DIR"

return 0


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
