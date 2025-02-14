#!/bin/bash -xe
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# This script creates the json file with user and group information.

full_script=$(realpath $0)
script_dir=$(dirname $full_script)
base_script=$(basename $full_script)

date
echo "Started create_or_update_users_groups_json.sh: $full_script"

config_dir={{ ExternalLoginNodeSlurmConfigDir }}
config_bin_dir=$config_dir/bin

$config_bin_dir/create_users_groups_json.py -o $config_dir/users_groups.json.new --subuid_filename $config_dir/subuid.new --subgid_filename $config_dir/subgid.new
if ! diff $config_dir/users_groups.json.new $config_dir/users_groups.json; then
    mv $config_dir/users_groups.json.new $config_dir/users_groups.json
    mv $config_dir/subuid.new $config_dir/subuid
    mv $config_dir/subgid.new $config_dir/subgid
fi

date
echo "Finished create_or_update_users_groups_json.sh: $full_script"

exit 0
