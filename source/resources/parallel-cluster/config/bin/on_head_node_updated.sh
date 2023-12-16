#!/bin/bash -x
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

set -x
set -e

script_name=on_head_node_updated.sh

exec 1> >(logger -s -t ${script_name}) 2>&1

echo "$(date): Started ${script_name}"

# Jinja2 template variables
assets_bucket={{assets_bucket}}
assets_base_key={{assets_base_key}}
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

config_dir=/opt/slurm/config
config_bin_dir=$config_dir/bin

# Make sure we're running the latest version
dest_script="$config_bin_dir/${script_name}"
mkdir -p $config_bin_dir
aws s3 cp s3://$assets_bucket/$assets_base_key/config/bin/${script_name} $dest_script.new
chmod 0700 $dest_script.new
if ! [ -e $dest_script ] || ! diff -q $dest_script $dest_script.new; then
    mv -f $dest_script.new $dest_script
    exec $dest_script
else
    rm $dest_script.new
fi

export PATH=/usr/sbin:$PATH

$config_bin_dir/on_head_node_configured.sh

echo "$(date): Finished ${script_name}"

exit 0
