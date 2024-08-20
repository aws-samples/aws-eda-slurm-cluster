#!/bin/bash -xe

script_dir=$(dirname $(realpath $0))
cd $script_dir

python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
./upload-res-templates.py "$@"
