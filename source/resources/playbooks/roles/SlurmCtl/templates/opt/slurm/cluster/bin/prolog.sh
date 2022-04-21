#!/bin/bash -ex
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# Script that runs as root on job nodes before job starts
# See https://slurm.schedmd.com/prolog_epilog.html
# Prolog and Epilog scripts should be designed to be as short as possible
# and should not call Slurm commands (e.g. squeue, scontrol, sacctmgr, etc).
# If the Prolog fails (returns a non-zero exit code), this will result in the node
# being set to a DRAIN state and the job requeued in a held state (unless
# nohold_on_prolog_fail is configured in SchedulerParameters).
