#!/bin/bash -x
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

SLURM_BIN={{SlurmBinDir}}

# First make sure that all down nodes are powered down
DOWN_NODES=$($SLURM_BIN/sinfo --noheader -t down -o '%N|%E|%H')
for DOWN_NODE in ${DOWN_NODES[@]}; do
    node_list=$(echo $DOWN_NODE | cut -f1 -d\|)
    reason=$(echo $DOWN_NODE | cut -f2 -d\|)
    timestamp=$(echo $DOWN_NODE | cut -f3 -d\|)
    echo "Powering down $node_list which was down because $reason"
    $SLURM_BIN/scontrol update state=POWER_DOWN nodename="$node_list"
done

# Mark down nodes as idle
# If they are down because of Insufficient Capacity Exception (ICE) then wait before making them available again
HOUR_SECS=$((60 * 60))
CHECK_EPOCH=$(( $(date +%s) - $HOUR_SECS ))
for DOWN_NODE in ${DOWN_NODES[@]}; do
    node_list=$(echo $DOWN_NODE | cut -f1 -d\|)
    reason=$(echo $DOWN_NODE | cut -f2 -d\|)
    timestamp=$(echo $DOWN_NODE | cut -f3 -d\|)
    if echo $reason | grep InsufficientInstanceCapacity; then
        ICE_EPOCH=`date -d $timestamp +%s`
        if [ "$ICE_EPOCH" -lt "$CHECK_EPOCH" ]; then
            $SLURM_BIN/scontrol update state=IDLE nodename=$node_list
        fi
    else
        $SLURM_BIN/scontrol update state=IDLE nodename=$node_list
    fi
done
