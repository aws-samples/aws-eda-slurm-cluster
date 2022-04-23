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

'''
Deconfigure the slurm cluster
Remove user/group cron jobs
Unmount the slurm file system.
'''
import cfnresponse
import boto3
import logging
from textwrap import dedent

logging.getLogger().setLevel(logging.INFO)

def lambda_handler(event, context):
    try:
        logging.info("event: {}".format(event))
        requestType = event['RequestType']
        if requestType != 'Delete':
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, "")
            return

        properties = event['ResourceProperties']
        required_properties = ['ClusterName', 'MountPath', 'SubmitterInstanceTags']
        error_message = ""
        for property in required_properties:
            try:
                value = properties[property]
            except:
                error_message += "Missing {} property. ".format(property)
        if error_message:
            raise KeyError(error_message)

        ssm_client = boto3.client('ssm')
        cluster_name = properties['ClusterName']
        mount_path = properties['MountPath']
        submitter_instance_tags = properties['SubmitterInstanceTags']

        cmd = f"mkdir -p /tmp/{cluster_name} && cd /tmp/{cluster_name} && sudo rsync -av {mount_path}/ansible . && cd ansible/playbooks && sudo ansible-playbook -i inventories/local.yml -e @../ansible_extra_vars.yml SlurmSubmitterDeconfigure.yml && cd /tmp && rm -rf {cluster_name}"
        logging.info(f'cmd: {cmd}')

        targets = []
        for tag, values in submitter_instance_tags.items():
            targets.append({'Key': f'tag:{tag}', 'Values': values})
        response = ssm_client.send_command(
            Targets = targets,
            DocumentName = 'AWS-RunShellScript',
            DocumentVersion = '1',
            Parameters = {
                'workingDirectory': ['/tmp'],
                'executionTimeout': ['3600'],
                'commands' : [
                    dedent(f'''set -ex
                        if ! [ -e {mount_path}/ansible ]; then
                            exit 0
                        fi
                        sudo mkdir -p /tmp/{cluster_name}
                        cd /tmp/{cluster_name}
                        sudo rsync -av {mount_path}/ansible .
                        cd ansible/playbooks
                        sudo ansible-playbook -i inventories/local.yml -e @../ansible_extra_vars.yml SlurmSubmitterDeconfigure.yml && cd /tmp && rm -rf {cluster_name}
                        ''')
                ]
            },
            TimeoutSeconds = 600,
        )

        logging.info('Success')

    except Exception as e:
        logging.exception(str(e))
        cfnresponse.send(event, context, cfnresponse.FAILED, {'error': str(e)}, str(e))
        raise

    cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, "")
