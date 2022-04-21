#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# This script can be used to use sbatch to run a compiled program and pass it parameters.
# sbatch requires a script.
# It has a --wrap option that will create a script, but the --wrap option doesn't support
# passing arguments.
# So if you need to batch an executable and pass parameters then prefix the executable
# and args with this script.
#
# Example:
# sbatch -c 8 --mem 16G sbatch_wrap.sh <executable> [args]

# I'm not echoing the command so that the output will be the same as if you ran the command from a shell.
#echo "$@"

$@
