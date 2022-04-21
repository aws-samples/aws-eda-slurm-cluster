#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# Submit jobs as quickly as possible to see if we get connection issues

num_jobs=${1:-1024}

module purge
module load {{ClusterName}}

for i in {0..$num_jobs}; do
    echo "Submitting job $i"
    if ! sbatch -c 1 --mem 100 -C t3 sbatch_wrap.sh sleep 60; then
        echo "error: sbatch $i submission failed"
	    exit 1
    fi
done

echo "Passed"
