# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import pytest

from aws_cdk import core
from cdk.cdk_slurm_stack import CdkSlurmStack


def get_template():
    app = core.App()
    CdkSlurmStack(app, "cdk")
    return json.dumps(app.synth().get_stack("cdk").template)


def test_sqs_queue_created():
    assert("AWS::SQS::Queue" in get_template())


def test_sns_topic_created():
    assert("AWS::SNS::Topic" in get_template())
