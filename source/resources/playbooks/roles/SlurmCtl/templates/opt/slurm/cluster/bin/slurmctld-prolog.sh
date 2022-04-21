#!/bin/bash -ex
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# Script that runs as root on slurm controller before job starts
# See https://slurm.schedmd.com/prolog_epilog.html
# If the PrologSlurmctld fails (returns a non-zero exit code), this will cause
# the job to be requeued. Only batch jobs can be requeued. Interactive jobs
# (salloc and srun) will be cancelled if the PrologSlurmctld fails.
