#!/usr/bin/env python3

import aws_cdk as cdk
from aws_cdk import App, Environment
from create_slurm_security_groups.create_slurm_security_groups_stack import CreateSlurmSecurityGroupsStack

app = cdk.App()

cdk_env = Environment(
    account = app.node.try_get_context('account_id'),
    region = app.node.try_get_context('region')
)
stack_name = app.node.try_get_context('stack_name')

CreateSlurmSecurityGroupsStack(app, stack_name, env=cdk_env, termination_protection = True,)

app.synth()
