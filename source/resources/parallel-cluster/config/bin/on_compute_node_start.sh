#!/bin/bash -x
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

set -x
set -e

script_name=on_compute_node_start.sh

exec 1> >(logger -s -t ${script_name}) 2>&1

echo "$(date): Started ${script_name}"

# Jinja2 template variables
ErrorSnsTopicArn={{ErrorSnsTopicArn}}

# Notify user of errors
function on_exit {
    rc=$?
    set +e
    if [[ $rc -ne 0 ]] && [[ ":$ErrorSnsTopicArn" != ":" ]]; then
        message_file=$(mktemp)
        echo "See log files for more info:
    grep ${script_name} /var/log/messages | less" > $message_file
        aws sns publish --topic-arn $ErrorSnsTopicArn --subject "${ClusterName} ${script_name} failed" --message file://$message_file
        rm $message_file
    fi
}
trap on_exit EXIT

# /opt/slurm isn't mounted yet.

# Configure pyxis and enroot

# Configure Enroot
ENROOT_PERSISTENT_DIR="/var/enroot"
ENROOT_VOLATILE_DIR="/run/enroot"

sudo mkdir -p $ENROOT_PERSISTENT_DIR
sudo chmod 1777 $ENROOT_PERSISTENT_DIR
sudo mkdir -p $ENROOT_VOLATILE_DIR
sudo chmod 1777 $ENROOT_VOLATILE_DIR
if [[ -e /opt/parallelcluster/examples/enroot/enroot.conf ]] && [[ -d /etc/enroot/ ]]; then
    sudo cp /opt/parallelcluster/examples/enroot/enroot.conf /etc/enroot/enroot.conf
    sudo chmod 0644 /etc/enroot/enroot.conf
fi

# Configure Pyxis
PYXIS_RUNTIME_DIR="/run/pyxis"

sudo mkdir -p $PYXIS_RUNTIME_DIR
sudo chmod 1777 $PYXIS_RUNTIME_DIR

echo "$(date): Finished ${script_name}"

exit 0
