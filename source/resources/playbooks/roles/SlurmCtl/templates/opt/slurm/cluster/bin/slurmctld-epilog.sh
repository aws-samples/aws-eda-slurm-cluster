#!/bin/bash -ex
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# Script that slurmctld runs as slurm upon terminatino of a job allocation.
# Can drain nodes and requeue the job if a failure occurs.
# Information about the job being initiated, its allocated nodes, etc. are
# passed to the program using environment variables.
# See Prolog and Epilog Scripts for more information.
# https://slurm.schedmd.com/prolog_epilog.html
# If the EpilogSlurmctld fails (returns a non-zero exit code), this will only be logged.
