#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# Submit 2048 jobs as quickly as possible to see if we get connection issues

num_jobs=${1:-10}

module purge
module load {{ClusterName}}

for i in {0..$num_jobs}; do
    echo "Submitting job $i"
    sbatch -c 1 --mem 100 -C t3 sbatch_wrap.sh sleep 60 &
done

wait

echo "Passed"
