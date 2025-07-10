#!/bin/bash -xe
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Download the original templates from s3
# This is so that they can be used to create modified versions
#
# https://s3.amazonaws.com/aws-hpc-recipes/main/recipes/res/res_demo_env/assets/bi.yaml

script_dir=$(dirname $(realpath $0))
cd $script_dir
aws s3 cp s3://aws-hpc-recipes/main/recipes/res/res_demo_env/assets/bi.yaml               res-demo-original/.
aws s3 cp s3://aws-hpc-recipes/main/recipes/res/res_demo_env/assets/keycloak.yaml         res-demo-original/.
aws s3 cp s3://aws-hpc-recipes/main/recipes/res/res_demo_env/assets/res-demo-stack.yaml   res-demo-original/.
aws s3 cp s3://aws-hpc-recipes/main/recipes/res/res_demo_env/assets/res-sso-keycloak.yaml res-demo-original/.
aws s3 cp s3://aws-hpc-recipes/main/recipes/net/hpc_large_scale/assets/main.yaml          res-demo-original/networking.yaml

aws s3 cp s3://aws-hpc-recipes/main/recipes/res/res_demo_env/assets/res.ldif res-demo-original/.
