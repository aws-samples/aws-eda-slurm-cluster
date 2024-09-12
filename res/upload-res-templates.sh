#!/bin/bash -xe
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Create a virtual environment and call upload-res-templates.py.

script_dir=$(dirname $(realpath $0))
cd $script_dir

python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
./upload-res-templates.py "$@"
