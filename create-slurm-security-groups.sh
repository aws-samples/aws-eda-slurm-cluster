#!/bin/bash -xe

cd create-slurm-security-groups

python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
pwd
./create-slurm-security-groups.py "$@"
