#!/usr/bin/env python3.11
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

import argparse
from copy import deepcopy
from io import BytesIO
import json
import logging
import logging.handlers
import os
import pycurl
import requests
import yaml

logger = logging.getLogger(__file__)

class ConfigureXio:

    def __init__(self):
        logger.info("Configuring Exostellar Infrastructure Optimizer")

        with open('/opt/slurm/config/ansible/ansible_head_node_vars.yml', 'r') as fh:
            self.ansible_head_node_vars = yaml.safe_load(fh)

        self.xio_config = self.ansible_head_node_vars['xio_config']

        logger.info(f"Xio config:\n{json.dumps(self.xio_config, indent=4)}")

        self.ems_url = f"http://{self.xio_config['ManagementServerIp']}:5000"

        self.num_errors = 0

        self.configure_profiles()

        self.configure_environment()

    def configure_profiles(self):
        logger.info(f"Getting profile az1 to use as a template for new profiles.")
        response = requests.get(f"{self.ems_url}/v1/profile/az1", verify=False)
        if response.status_code != 200:
            self.num_errors += 1
            logger.error(f"Failed to get az1 profile. code={response.status_code} content={response.content.decode('utf8')}")
            az1_profile = None
        else:
            # logger.info(f"response content:\n{response.content.decode('utf8')}")
            az1_profile = json.loads(response.content.decode('utf8'))
            # logger.info(f"az1 profile:\n{json.dumps(az1_profile, indent=4)}")

        for profile_config in self.xio_config['Profiles']:
            self.configure_profile(profile_config)

    def configure_profile(self, profile_config):
            profile_name = profile_config['ProfileName']
            response = requests.get(f"{self.ems_url}/v1/profile/{profile_name}", verify=False)
            profile = json.loads(response.content.decode('utf8'))
            profile.pop('Arbiter', None)
            profile['ProfileName'] = profile_name
            profile['NodeGroupName'] = profile_name
            name_tag = f"xspot-controller-{profile_name}"
            name_tag_found = False
            for tag_dict in profile['Controller']['InstanceTags']:
                if tag_dict['Key'] == 'Name':
                    name_tag_found = True
                    tag_dict['Value'] = name_tag
            if not name_tag_found:
                profile['Controller']['InstanceTags'].append({
                    'Key': 'Name',
                    'Value': name_tag
                })
            if not profile['Controller']['ImageId']:
                profile['Controller']['ImageId'] = self.xio_config['ControllerImageId']
            profile['MaxControllers'] = profile_config['MaxControllers']
            profile['Controller']['SecurityGroupIds'] = []
            for security_group_id in self.xio_config['ControllerSecurityGroupIds']:
                profile['Controller']['SecurityGroupIds'].append(security_group_id)
            profile['Worker']['InstanceTypes'] = []
            for instance_type in profile_config['InstanceTypes']:
                profile['Worker']['InstanceTypes'].append(instance_type)
            profile['Worker']['SpotFleetTypes'] = []
            for spot_fleet_type in profile_config['SpotFleetTypes']:
                profile['Worker']['SpotFleetTypes'].append(spot_fleet_type)
            name_tag_found = False
            name_tag = f"xspot-worker-{profile_name}"
            for tag_dict in profile['Worker']['InstanceTags']:
                if tag_dict['Key'] == 'Name':
                    name_tag_found = True
                    tag_dict['Value'] = name_tag
            if not name_tag_found:
                profile['Worker']['InstanceTags'].append({
                    'Key': 'Name',
                    'Value': name_tag
                })
            profile['Worker']['SecurityGroupIds'] = []
            for security_group_id in self.xio_config['WorkerSecurityGroupIds']:
                profile['Worker']['SecurityGroupIds'].append(security_group_id)
            profile['Xspot']['EnableHyperthreading'] = profile_config['EnableHyperthreading']
            logger.info(f"{profile_name}:\n{json.dumps(profile, indent=4)}")

            logger.info(f"Updating profile {profile_name}")
            headers = {'Content-type': 'application/json'}
            response = requests.put(f"{self.ems_url}/v1/profile", data=json.dumps(profile), headers=headers)
            if response.status_code == 200:
                logger.info(f"Succeeded: {response.content.decode('utf8')}")
            else:
                logger.error(f"{profile_name} update failed with code=={response.status_code}\n{response.content.decode('utf8')}")

    def configure_environment(self):
        logger.info(f"Getting slurm environment to use as a template for new environments.")
        response = requests.get(f"{self.ems_url}/v1/env/slurm", verify=False)
        if response.status_code != 200:
            self.num_errors += 1
            logger.error(f"Failed to get slurm environment. code={response.status_code} content={response.content.decode('utf8')}")
            slurm_env = None
        else:
            # logger.info(f"response:\n{response}")
            # logger.info(f"response content:\n{response.content.decode('utf8')}")
            slurm_env = json.loads(response.content.decode('utf8'))
            # logger.info(f"slurm env:\n{json.dumps(slurm_env, indent=4)}")

        env_name = self.ansible_head_node_vars['cluster_name']
        logger.info(f"Getting {env_name} environment.")
        response = requests.get(f"{self.ems_url}/v1/env/{env_name}", verify=False)
        if response.status_code != 200:
            self.num_errors += 1
            logger.error(f"Failed to get {env_name} environment. code={response.status_code} content={response.content.decode('utf8')}")
            env = None
        else:
            env = json.loads(response.content.decode('utf8'))
            env['HeadAddress'] = f"head_node.{env_name}.pcluster"
            env['Pools'] = []
            for pool_config in self.xio_config['Pools']:
                env['Pools'].append({
                    'PoolName': pool_config['PoolName'],
                    'PoolSize': pool_config['PoolSize'],
                    'ProfileName': pool_config['ProfileName'],
                    'VM': {
                        'CPUs': pool_config['CPUs'],
                        'ImageName': pool_config.get('ImageName', self.xio_config['DefaultImageName']),
                        'MinMemory': pool_config['MinMemory'],
                        'MaxMemory': pool_config['MaxMemory'],
                        'VolumeSize': pool_config['VolumeSize'],
                        'PrefixCount': 0,
                        'UserData': ''
                    }
                })
            env['Slurm'] = {
                'BinPath': f"/opt/slurm/bin",
                'ConfPath': f"/opt/slurm/etc",
                'PartitionName': self.xio_config['PartitionName']
            }
            logger.info(f"{env_name} application environment:\n{json.dumps(env, indent=4)}")

            logger.info(f"Updating environment {env_name}")
            headers = {'Content-type': 'application/json'}
            response = requests.put(f"{self.ems_url}/v1/env", data=json.dumps(env), headers=headers)
            if response.status_code == 200:
                logger.info(f"Succeeded: {response.content.decode('utf8')}")
            else:
                logger.error(f"{env} environment update failed with code=={response.status_code}\n{response.content.decode('utf8')}")

        return

if __name__ == '__main__':
    logger_formatter = logging.Formatter('%(levelname)s: %(message)s')
    logger_streamHandler = logging.StreamHandler()
    logger_streamHandler.setFormatter(logger_formatter)
    logger.addHandler(logger_streamHandler)
    logger.propagate = False
    logger.setLevel(logging.INFO)


    try:
        parser = argparse.ArgumentParser("Configure Exostellar Infrastructure Optimizer")
        parser.add_argument('--debug', '-d', action='count', default=False, help="Enable debug messages")
        args = parser.parse_args()

        if args.debug:
            logger.setLevel(logging.DEBUG)
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(logger_formatter)
            logger.addHandler(stream_handler)

        app = ConfigureXio()
    except:
        logging.exception(f"Unhandled exception in {__file__}")
        raise
