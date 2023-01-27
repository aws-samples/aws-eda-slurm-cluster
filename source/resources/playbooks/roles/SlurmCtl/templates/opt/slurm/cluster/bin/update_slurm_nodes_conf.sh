#!/bin/bash -ex
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# Update slurm_nodes.conf

cd {{SlurmScriptsDir}}
rm -f {{SlurmConfigDir}}/instance-type-info.new.json
rm -f {{SlurmEtcDir}}/slurm_nodes.conf.new
if ! ./slurm_ec2_create_node_conf.py --config-file {{INSTANCE_CONFIG_LOCAL_PATH}} --az-info-file {{SlurmConfigDir}}/AZInfo.json -o {{SlurmEtcDir}}/slurm_nodes.conf.new --instance-types-json {{SlurmConfigDir}}/InstanceTypes.json --instance-type-info-json {{SlurmConfigDir}}/instance-type-info.new.json; then
    rm -f {{SlurmConfigDir}}/instance-type-info.new.json
    rm -f {{SlurmEtcDir}}/slurm_nodes.conf.new
    exit 1
fi
if ! diff -q {{SlurmConfigDir}}/instance-type-info.json {{SlurmConfigDir}}/instance-type-info.new.json; then
    cp {{SlurmConfigDir}}/instance-type-info.json {{SlurmConfigDir}}/instance-type-info.json.$(date '+%Y-%m-%d@%H:%M:%S')
    mv {{SlurmConfigDir}}/instance-type-info.new.json {{SlurmConfigDir}}/instance-type-info.json
fi
if ! diff -q {{SlurmEtcDir}}/slurm_nodes.conf {{SlurmEtcDir}}/slurm_nodes.conf.new; then
    cp {{SlurmEtcDir}}/slurm_nodes.conf {{SlurmEtcDir}}/slurm_nodes.conf.$(date '+%Y-%m-%d@%H:%M:%S')
    mv {{SlurmEtcDir}}/slurm_nodes.conf.new {{SlurmEtcDir}}/slurm_nodes.conf
    systemctl restart slurmctld
    systemctl status slurmctld
fi
