FROM arm64v8/rockylinux:9

# Install development tools and necessary dependencies
RUN dnf -y update &&     dnf -y install epel-release &&     dnf -y install gcc gcc-c++ make wget openssl-devel bzip2-devel libffi-devel zlib-devel                    readline-devel sqlite-devel tar xz sudo git which

# Install Python 3.12
RUN cd /tmp &&     wget https://www.python.org/ftp/python/3.12.1/Python-3.12.1.tgz &&     tar xzf Python-3.12.1.tgz &&     cd Python-3.12.1 &&     ./configure --enable-optimizations &&     make altinstall &&     ln -sf /usr/local/bin/python3.12 /usr/bin/python3 &&     ln -sf /usr/local/bin/python3.12 /usr/bin/python &&     ln -sf /usr/local/bin/pip3.12 /usr/bin/pip3 &&     ln -sf /usr/local/bin/pip3.12 /usr/bin/pip &&     cd /tmp && rm -rf Python-3.12.1*

# Install Node.js 20.19.0
RUN cd /tmp &&     wget https://nodejs.org/dist/v20.19.0/node-v20.19.0-darwin-arm64.tar.xz &&     tar -xf node-v20.19.0-darwin-arm64.tar.xz &&     mv node-v20.19.0-darwin-arm64 /usr/local/node-v20.19.0 &&     ln -sf /usr/local/node-v20.19.0/bin/node /usr/bin/node &&     ln -sf /usr/local/node-v20.19.0/bin/npm /usr/bin/npm &&     ln -sf /usr/local/node-v20.19.0/bin/npx /usr/bin/npx &&     cd /tmp && rm -rf node-v20.19.0-linux-x64*

RUN node --version

# Install AWS CDK 2.179.0
RUN /usr/bin/npm install -g aws-cdk@2.179.0

# Create a working directory
WORKDIR /app

# Create a mount point for repo so can run install script
RUN mkdir -p /app/aws-eda-slurm-cluster

# Add a script that can receive command line arguments
COPY run_script.sh /app/
RUN chmod +x /app/run_script.sh

ENTRYPOINT ["/app/run_script.sh"]
