#!/bin/bash -x
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

echo $SLURM_ARRAY_TASK_ID

job_memory=$(squeue --job $SLURM_JOBID -o %m -h)
stress-ng -t 5m --times --perf --cpu $SLURM_JOB_CPUS_PER_NODE --vm 2 --vm-bytes 90%
