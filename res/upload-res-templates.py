#!/usr/bin/env python3
"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

Permission is hereby granted, free of charge, to any person obtaining a copy of this
software and associated documentation files (the "Software"), to deal in the Software
without restriction, including without limitation the rights to use, copy, modify,
merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

"""
It's recommended to trigger this script via deploy-res.sh as python's virtual env and all required
libraries/dependencies will be automatically installed.

If you run this script directly, make sure to have all the Python and CDK dependencies installed.
"""

import argparse
import boto3
from jinja2 import Template as JinjaTemplate
import logging
import os
import os.path
from os.path import dirname, realpath
from shutil import copy
import sys

script_path = os.path.dirname(os.path.abspath(__file__))
sys.path.append(script_path)

logger = logging.getLogger(__file__)
logger_formatter = logging.Formatter('%(levelname)s: %(message)s')
logger_streamHandler = logging.StreamHandler()
logger_streamHandler.setFormatter(logger_formatter)
logger.addHandler(logger_streamHandler)
logger.propagate = False
logger.setLevel(logging.INFO)

class UploadRESTemplates():

    def __init__(self):
        self.stack_parameters = {}

    def main(self):
        parser = argparse.ArgumentParser(description="Configure and upload RES templates to S3 so they can be deployed.")
        parser.add_argument("--s3-bucket",   type=str, required=True, help="S3 bucket for templates.")
        parser.add_argument("--s3-base-key", type=str, required=True, help="Base S3 bucket key for templates.")
        parser.add_argument("--region", '-r', type=str, default='us-east-1', help="AWS region to use for s3 commands.")
        parser.add_argument("--debug", action='store_const', const=True, default=False, help="Enable debug messages.")
        args = parser.parse_args()

        if args.debug:
            logger.setLevel(logging.DEBUG)

        # Use script location as current working directory
        script_directory = os.path.dirname(os.path.realpath(f"{__file__}"))
        os.chdir(script_directory)
        logger.info(f"Working directory: {script_directory}")

        template_vars = {
            'LDIFS3Path': f"{args.s3_bucket}/{args.s3_base_key}/res.ldif",
            'TemplateBucket': args.s3_bucket,
            'TemplateBaseKey': args.s3_base_key
        }
        src_dir = 'res-demo-with-cidr'
        dst_dir = 'rendered_templates'
        template_files = [
            'res-demo-stack.yaml',
            'bi.yaml'
            ]
        os.makedirs(dst_dir, exist_ok=True)
        for template_file in template_files:
            jinja_template = JinjaTemplate(open(f"{src_dir}/{template_file}", 'r').read())
            fh = open(f"rendered_templates/{template_file}", 'w')
            fh.write(jinja_template.render(**template_vars))
            fh.close()
        copy(f"{src_dir}/res.ldif", dst_dir)

        s3_client = boto3.client('s3', region_name=args.region)
        for root, dirs, files in os.walk(dst_dir):
            for filename in files:
                s3_client.put_object(
                    Bucket = args.s3_bucket,
                    Key = os.path.join(args.s3_base_key, filename),
                    Body = open(os.path.join(root, filename), 'r').read()
                )
                os.path.join(root, filename)

        logger.info("Use the following link to deploy RES using CloudFormation.")
        logger.info(f"https://console.aws.amazon.com/cloudformation/home?region={args.region}#/stacks/quickcreate?templateURL=https://{args.s3_bucket}.s3.amazonaws.com/{args.s3_base_key}/res-demo-stack.yaml")

if __name__ == "__main__":
    app = UploadRESTemplates()
    app.main()
