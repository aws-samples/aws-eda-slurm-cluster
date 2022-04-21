#!/bin/bash -x
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

scriptdir=$(dirname $(readlink -f $0))

module purge
module load {{ClusterName}}

sbatch -p all -c 1 --mem 1 -C 'a2&x86_64' $scriptdir/job_simple_array.sh
sbatch -p all -c 1 --mem 1 -C 'c7&x86_64' $scriptdir/job_simple_array.sh
sbatch -p all -c 1 --mem 1 -C 'c8&x86_64' $scriptdir/job_simple_array.sh
sbatch -p all -c 1 --mem 1 -C 'r7&x86_64' $scriptdir/job_simple_array.sh

sbatch -p all -c 1 --mem 1 -C 'a2&arm64' $scriptdir/job_simple_array.sh
sbatch -p all -c 1 --mem 1 -C 'c8&arm64' $scriptdir/job_simple_array.sh
sbatch -p all -c 1 --mem 1 -C 'r8&arm64' $scriptdir/job_simple_array.sh
