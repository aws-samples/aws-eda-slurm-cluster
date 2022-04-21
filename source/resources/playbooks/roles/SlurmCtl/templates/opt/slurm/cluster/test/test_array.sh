#!/bin/bash -ex
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

num_jobs=${1:-10}

scriptdir=$(dirname $(readlink -f $0))

module purge
module load {{ClusterName}}

jobid=$(sbatch -c 1 --mem 1 --parsable --wait -a 1-${num_jobs} $scriptdir/job_simple_array.sh)
if [[ $? -ne 0 ]]; then
    echo "error: sbatch failed"
    exit 1
fi

echo "Array job $jobid finished"

for i in $(seq 1 $num_jobs); do
    task_id=$(cat slurm-${jobid}_$i.out)
    if [ $task_id != $i ]; then
	    echo "error: array task id miscompare: exp=$i act=$task_id"
    fi
done

echo "Passed"
