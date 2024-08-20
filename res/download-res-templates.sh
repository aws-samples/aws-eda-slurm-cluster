#!/bin/bash -xe

script_dir=$(dirname $(realpath $0))
cd $script_dir
aws s3 cp s3://aws-hpc-recipes/main/recipes/res/res_demo_env/assets/res-demo-stack.yaml res-demo/.
aws s3 cp s3://aws-hpc-recipes/main/recipes/res/res_demo_env/assets/bi.yaml res-demo/.
aws s3 cp s3://aws-hpc-recipes/main/recipes/net/hpc_large_scale/assets/main.yaml res-demo/networking.yaml

aws s3 cp s3://aws-hpc-recipes/main/recipes/res/res_demo_env/assets/res.ldif res-demo/.
