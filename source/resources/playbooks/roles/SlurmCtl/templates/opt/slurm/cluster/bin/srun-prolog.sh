#!/bin/bash -ex
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# Script that runs as user on job nodes before job starts
# See https://slurm.schedmd.com/prolog_epilog.html
# The command line arguments for the executable will be the command and arguments
# of the job step. This configuration parameter may be overridden by srun's
# --epilog parameter. Note that while the other "Epilog" executables (e.g., TaskEpilog)
# are run by slurmd on the compute nodes where the tasks are executed, the
#SrunEpilog runs on the node where the "srun" is executing.
