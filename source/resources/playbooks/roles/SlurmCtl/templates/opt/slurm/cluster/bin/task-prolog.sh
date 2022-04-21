#!/bin/bash -ex
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# Script that runs as job's owner on job nodes before initiation of task.
# See https://slurm.schedmd.com/prolog_epilog.html
# Besides the normal environment variables, this has SLURM_TASK_PID available to
# identify the process ID of the task being started. Standard output from this
# program can be used to control the environment variables and output for the user program.
