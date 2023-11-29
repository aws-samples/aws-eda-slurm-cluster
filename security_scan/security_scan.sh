#!/bin/bash -ex
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

scriptdir=$(dirname $(readlink -f $0))

cd $scriptdir/..
./install.sh --config-file ~/slurm/res-eda/res-eda-pc-3-7-2-centos7-x86-config.yml --cdk-cmd synth

cfn_nag_scan --input-path $scriptdir/../source/cdk.out/res-eda-pc-3-7-2-centos7-x86-config.template.json --deny-list-path $scriptdir/cfn_nag-deny-list.yml --fail-on-warnings &> $scriptdir/cfn_nag.log

cd $scriptdir
if [ ! -e $scriptdir/bandit-env ]; then
    python3 -m venv bandit-env
    source bandit-env/bin/activate
    pip install bandit
    python3 -m pip install bandit
fi
source bandit-env/bin/activate

cd $scriptdir/..
bandit -r source/resources/playbooks/roles/SlurmCtl/files/opt/slurm/cluster/bin/SlurmPlugin.py &> $scriptdir/bandit.log

if [ ! -e $scriptdir/ScoutSuite ]; then
    cd $scriptdir
    git clone https://github.com/nccgroup/ScoutSuite
fi
if [ ! -e $scriptdir/ScoutSuite/scoutesuite-venv/bin/activate ]; then
    cd $scriptdir/ScoutSuite
    rm -f scoutesuite-venv
    python3 -m venv scoutesuite-venv
    source scoutesuite-venv/bin/activate
    python3 -m pip install -r requirements.txt
fi
cd $scriptdir/ScoutSuite
source scoutesuite-venv/bin/activate
python scout.py aws -r us-east-1
