#!/usr/bin/env python3

#import filecmp
from os import path, system
from os.path import abspath, dirname
import pytest
import subprocess
from subprocess import CalledProcessError, check_output


REPO_DIR = abspath(f"{dirname(__file__)}/..")

def test_slurm_minimal():
    try:
        output = check_output([f"{REPO_DIR}/install.sh", '--cdk-cmd', 'create', '--region', 'us-east-1'], stderr=subprocess.STDOUT, encoding='utf8')
    except CalledProcessError as e:
        print(f"returncode: {e.returncode}")
        print(f"output:\n{e.stdout}")
        raise
