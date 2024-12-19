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
import requests
from time import sleep
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

        self.configure_vm_images()

        self.configure_profiles()

        self.configure_environment()

        if self.num_errors:
            logger.error(f"Failed with {self.num_errors} errors")
            exit(1)

    def configure_vm_images(self):
        for image_config in self.xio_config['Images']:
            image_name = image_config['ImageName']
            image_id = image_config['ImageId']
            response = requests.get(f"{self.ems_url}/v1/image/{image_name}", verify=False)
            if response.status_code == 200:
                image_info = json.loads(response.content.decode('utf8'))
                logger.info(f"Image {image_name} already exists:\n{json.dumps(image_info, indent=4)}")
                if image_info['ImageId'] == image_id:
                    continue
                logger.info(f"New ImageId ({image_id} for {image_name} so creating image with new AMI.)")
            else:
                logger.info(f"Image {image_name} doesn't exist so creating it.")

            image_json = {
                "Description": "",
                "ImageId": image_id,
                "ImageName": image_name,
                "UserData": "",
                "User": "",
                "UserKeyPem": ""
            }
            headers = {'Content-type': 'application/json'}
            response = requests.post(f"{self.ems_url}/v1/xcompute/parse", data=json.dumps(image_json), headers=headers)
            if response.status_code != 200:
                self.num_errors += 1
                logger.error(f"Error creating {image_name}. code={response.status_code} content:\n{response.content.decode('utf-i')}")
                continue
            job_id = json.loads(response.content.decode('utf-8'))['JobId']
            logger.info(f"Waiting for image {image_name}")
            while True:
                response = requests.get(f"{self.ems_url}/v1/image/{image_name}")
                if response.status_code == 200:
                    logger.info(f"Image {image_name} successfully created:\n{json.dumps(response.content.decode('utf-8'), indent=4)}")
                    break
                elif response.status_code == 400:
                    logger.error(f"Creation of image {image_name} failed:\n{json.dumps(response.content.decode('utf-8'))}")
                    break
                sleep(10)

    def configure_profiles(self):
        template_profile_config = self.get_template_profile_config()
        if not template_profile_config:
            self.num_errors += 1
            logger.error(f"Failed to get template profile.")
            exit(1)

        for profile_config in self.xio_config['Profiles']:
            self.configure_profile(profile_config, template_profile_config)

    def get_template_profile_config(self):
        profile_name = 'az1'
        logger.info(f"Checking if  profile {profile_name} exists.")
        response = requests.get(f"{self.ems_url}/v1/profile/{profile_name}", verify=False)
        if response.status_code != 200:
            if response.status_code == 404:
                logger.error(f"{profile_name} profile doesn't exist. code={response.status_code} content:\n{response.content.decode('utf8')}")
            else:
                self.num_errors += 1
                logger.error(f"Unknown error getting {profile_name} profile. code={response.status_code} content:\n{response.content.decode('utf8')}")
                return None
            self.num_errors += 1
            return None

        template_profile_config = None
        logger.info(f"Getting profile {profile_name} to use as a template for new profiles.")
        response = requests.get(f"{self.ems_url}/v1/profile/{profile_name}", verify=False)
        if response.status_code != 200:
            logger.error(f"Failed to get {profile_name} profile. code={response.status_code} content={response.content.decode('utf8')}")
            self.num_errors += 1
            return None

        template_profile_config = json.loads(response.content.decode('utf8'))
        logger.info(f"{profile_name} profile:\n{json.dumps(template_profile_config, indent=4)}")

        # Remove the Id which is unique to each
        template_profile_config.pop('Id', None)
        if 'InstanceType' in self.xio_config.get('Controllers', {}):
            if template_profile_config['Controller']['InstanceType'] != self.xio_config['Controllers']['InstanceType']:
                logger.info(f"Changing default Controller InstanceType from {template_profile_config['Controller']['InstanceType']} to {self.xio_config['Controllers']['InstanceType']}")
                template_profile_config['Controller']['InstanceType'] = self.xio_config['Controllers']['InstanceType']
        if 'ImageId' in self.xio_config.get('Controllers', {}):
            if template_profile_config['Controller']['ImageId'] != self.xio_config['Controllers']['ImageId']:
                logger.info(f"Changing default Controller ImageId from {template_profile_config['Controller']['ImageId']} to {self.xio_config['Controllers']['ImageId']}")
                template_profile_config['Controller']['ImageId'] = self.xio_config['Controllers']['ImageId']
        if 'ImageId' in self.xio_config.get('Workers', {}):
            if template_profile_config['Worker']['ImageId'] != self.xio_config['Workers']['ImageId']:
                logger.info(f"Changing default Worker ImageId from {template_profile_config['Worker']['ImageId']} to {self.xio_config['Workers']['ImageId']}")
                template_profile_config['Worker']['ImageId'] = self.xio_config['Workers']['ImageId']
        for security_group_id in self.xio_config.get('Controllers', {}).get('SecurityGroupIds', []):
            if security_group_id not in template_profile_config['Controller']['SecurityGroupIds']:
                logger.info(f"Adding {security_group_id} to default Controller SecurityGroupIds")
                template_profile_config['Controller']['SecurityGroupIds'].append(security_group_id)
        for security_group_id in self.xio_config.get('Workers', {}).get('SecurityGroupIds', []):
            if security_group_id not in template_profile_config['Worker']['SecurityGroupIds']:
                logger.info(f"Adding {security_group_id} to default Worker SecurityGroupIds")
                template_profile_config['Worker']['SecurityGroupIds'].append(security_group_id)
        logger.debug(f"Modified {profile_name} profile:\n{json.dumps(template_profile_config, indent=4)}")

        return template_profile_config

    def configure_profile(self, profile_config, template_profile_config):
        profile_name = profile_config['ProfileName']
        logger.info(f"Configuring {profile_name} profile")
        profile_exists = False
        response = requests.get(f"{self.ems_url}/v1/profile/{profile_name}", verify=False)
        logger.debug(f"response:\n{response}")
        if response.status_code == 404:
            logger.info(f"{profile_name} profile doesn't exist so creating it.")
            profile = deepcopy(template_profile_config)
        elif response.status_code != 200:
            self.num_errors += 1
            logger.error(f"Failed to get {profile_name} profile. code={response.status_code} content={response.content.decode('utf8')}")
        else:
            logger.info(f"{profile_name} profile exists so updating it.")
            profile_exists = True
            try:
                profile = json.loads(response.content.decode('utf8'))
            except Exception as e:
                logger.error(f"Invalid json config returned by server: {response.content.decode('utf8')}")
                self.num_errors += 1
                return
        profile.pop('Arbiter', None)
        profile.pop('MeteringList', None)
        profile.pop('Manufacturer', None)
        profile.pop('Status', None)

        if profile_exists:
            # Check fields against the template
            if profile['Controller'].get('ImageId', '') != template_profile_config['Controller']['ImageId']:
                logger.warning(f"    Changing Controller.Imageid from '{profile['Controller'].get('ImageId', '')} to {template_profile_config['Controller']['ImageId']}")
                profile['Controller']['ImageId'] = template_profile_config['Controller']['ImageId']
            if profile['Worker'].get('ImageId', '') != template_profile_config['Worker']['ImageId']:
                logger.warning(f"    Changing Worker.Imageid from '{profile['Worker'].get('ImageId', '')} to {template_profile_config['Worker']['ImageId']}")
                profile['Worker']['ImageId'] = template_profile_config['Worker']['ImageId']
            for security_group_id in template_profile_config['Controller']['SecurityGroupIds']:
                if security_group_id not in profile['Controller']['SecurityGroupIds']:
                    logger.info(f"    Adding {security_group_id} to Controller.SecurityGroupIds")
                    profile['Controller']['SecurityGroupIds'].append(security_group_id)
            for security_group_id in template_profile_config['Worker']['SecurityGroupIds']:
                if security_group_id not in profile['Worker']['SecurityGroupIds']:
                    logger.warning(f"    Adding {security_group_id} to Worker.SecurityGroupIds")
                    profile['Worker']['SecurityGroupIds'].append(security_group_id)

        # Set profile specific fields from the config
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
        profile['MaxControllers'] = profile_config['MaxControllers']
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
        profile['Xspot']['EnableHyperthreading'] = profile_config['EnableHyperthreading']
        logger.info(f"{profile_name} profile config:\n{json.dumps(profile, indent=4)}")

        headers = {'Content-type': 'application/json'}
        if profile_exists:
            logger.info(f"Updating profile {profile_name}")
            response = requests.put(f"{self.ems_url}/v1/profile", data=json.dumps(profile), headers=headers)
        else:
            logger.info(f"Creating profile {profile_name}")
            response = requests.post(f"{self.ems_url}/v1/profile", data=json.dumps(profile), headers=headers)
        if response.status_code == 200:
            logger.info(f"Succeeded: {response.content.decode('utf8')}")
        else:
            logger.error(f"{profile_name} update failed with code=={response.status_code}\n{response.content.decode('utf8')}")
            self.num_errors += 1

    def configure_environment(self):
        env_name = self.ansible_head_node_vars['cluster_name']
        logger.info(f"Getting {env_name} environment.")
        env_exists = False
        response = requests.get(f"{self.ems_url}/v1/env/{env_name}", verify=False)
        if response.status_code != 200:
            logger.info(f"{env_name} environment doesn't exist. code={response.status_code} content={response.content.decode('utf8')}")
            env = {}
        else:
            logger.info(f"{env_name} environment exists. code={response.status_code} content={response.content.decode('utf8')}")
            env_exists = True
            try:
                env = json.loads(response.content.decode('utf8'))
            except Exception as e:
                # Need the id from the existing environment or we can't update it so this is an error.
                self.num_errors += 1
                logger.error(f"Invalid environment configuration returned by server:\n{response.content.decode('utf8')}")
                return

        if not env:
            logger.info(f"Getting 'slurm' environment to use as a template for new environment.")
            response = requests.get(f"{self.ems_url}/v1/env/slurm", verify=False)
            if response.status_code != 200:
                self.num_errors += 1
                logger.error(f"Failed to get 'slurm' environment. code={response.status_code} content={response.content.decode('utf8')}")
                return
            else:
                logger.debug(f"response:\n{response}")
                logger.debug(f"response content:\n{response.content.decode('utf8')}")
                try:
                    template_env = json.loads(response.content.decode('utf8'))
                    logger.debug(f"template_env:\n{json.dumps(template_env, indent=4)}")
                except Exception as e:
                    self.num_errors += 1
                    logger.error(f"Invalid environment configuration returned by server:\n{response.content.decode('utf8')}")
                    return

        env['EnvName'] = env_name
        env['Type'] = 'slurm'
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

        headers = {'Content-type': 'application/json'}
        if env_exists:
            logger.info(f"Updating environment {env_name}")
            response = requests.put(f"{self.ems_url}/v1/env", data=json.dumps(env), headers=headers)
        else:
            logger.info(f"Creating environment {env_name}")
            response = requests.post(f"{self.ems_url}/v1/env", data=json.dumps(env), headers=headers)
        if response.status_code == 200:
            logger.info(f"Succeeded: {response.content.decode('utf8')}")
        else:
            self.num_errors += 1
            logger.error(f"{env_name} environment update failed with code=={response.status_code}\n{response.content.decode('utf8')}")

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

        app = ConfigureXio()
    except SystemExit as e:
        exit(e)
    except:
        logging.exception(f"Unhandled exception in {__file__}")
        raise
