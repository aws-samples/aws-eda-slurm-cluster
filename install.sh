#!/bin/bash -e
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

scriptdir=$(dirname $(readlink -f $0))
repodir=$scriptdir

cd $repodir

source setup.sh

source/installer.py "$@"
