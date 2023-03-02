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
Example showing how to call Slurm REST API from a Lambda function.
'''

import boto3
import json
import logging
from os import environ
from urllib.parse import urlencode
import urllib3

logging.getLogger().setLevel(logging.INFO)

class SlurmRestApi:
    def __init__(self, cluster_name:str, slurm_rest_api_version:str, slurmrestd_url:str, user_name:str) -> None:
        self.cluster_name = cluster_name
        self.slurm_rest_api_version = slurm_rest_api_version
        self.slurmrestd_url = slurmrestd_url
        self.user_name = user_name

        ssm_client = boto3.client('ssm')
        parameter_name = f"/{cluster_name}/slurmrestd/jwt/{user_name}"
        logging.debug(f"Getting jwt token from {parameter_name}")
        self.jwt_token = ssm_client.get_parameter(Name=parameter_name)['Parameter']['Value']
        logging.debug(f"jwt token: {self.jwt_token}")

        self.http = urllib3.PoolManager()

    VALID_REQUEST_TYPES = [
        'DELETE',
        'GET',
        'POST',
    ]

    def _request(self, request_type:str, api_path:str, fields={}):
        assert request_type in self.VALID_REQUEST_TYPES
        url = f"{self.slurmrestd_url}/{api_path}"
        headers = {
            'X-SLURM-USER-TOKEN': self.jwt_token,
            'X-SLURM-USER-NAME': self.user_name,
            }
        if request_type == 'POST':
            headers['Content-Type'] = 'application/json'
            body = json.dumps(fields).encode('utf-8')
        else:
            body = None
        response = self.http.request(
            request_type,
            url,
            headers={
                'X-SLURM-USER-TOKEN': self.jwt_token,
                'X-SLURM-USER-NAME': self.user_name,
                'Content-Type': 'application/json'
            },
            body = body
            )
        logging.debug(f"status: {response.status}")
        logging.debug(f"response: {response}")
        logging.debug(f"response: {response.data}")
        logging.debug(f"response: {response.data.decode('utf-8')}")
        if response.status == 200:
            json_response = json.loads(response.data.decode('utf-8'))
            return json_response
        try:
            json_response = json.loads(response.data.decode('utf-8'))
            logging.error(f"response:\n{json.dumps(json_response, indent=4)}")
        except:
            logging.error(f"response: {json.dumps(response.data.decode('utf-8'), indent=4)}")
        raise RuntimeError(f"{request_type} {url} failed with status={response.status}")

    def delete_node(self, node_name:str):
        return self._request('DELETE', f"slurm/v{self.slurm_rest_api_version}/node/{node_name}")

    def diag(self):
        return self._request('GET', f"slurm/v{self.slurm_rest_api_version}/diag")

    def scancel(self, job_id):
        return self._request('DELETE', f"slurm/v{self.slurm_rest_api_version}/job/{job_id}")

    def get_job_info(self, job_id:str):
        return self._request('GET', f"slurm/v{self.slurm_rest_api_version}/job/{job_id}")

    def get_all_job_info(self):
        return self._request('GET', f"slurm/v{self.slurm_rest_api_version}/jobs")

    def get_licenses(self):
        return self._request('GET', f"slurm/v{self.slurm_rest_api_version}/licenses")

    def get_node_info(self, node_name:str):
        return self._request('GET', f"slurm/v{self.slurm_rest_api_version}/node/{node_name}")

    def get_all_node_info(self):
        return self._request('GET', f"slurm/v{self.slurm_rest_api_version}/nodes")

    def get_partition_info(self, partition_name:str):
        return self._request('GET', f"slurm/v{self.slurm_rest_api_version}/partition/{partition_name}")

    def get_all_partition_info(self):
        return self._request('GET', f"slurm/v{self.slurm_rest_api_version}/partitions")

    def ping(self):
        return self._request('GET', f"slurm/v{self.slurm_rest_api_version}/ping")

    def submit(self, name:str, ntasks:int, nodes: int, script:str, constraints:str):
        fields = {
            "job": {
                "name": name,
                "ntasks": ntasks,
                "nodes": nodes,
                "constraints": constraints,
                "current_working_directory": f"/data/home/{self.user_name}",
                "standard_input": "/dev/null",
                "standard_output": f"/data/home/{self.user_name}/stdio.txt",
                "standard_error": f"/data/home/{self.user_name}/stderr.txt",
                "environment": {
                    "PATH": "/bin:/usr/bin/:/usr/local/bin/",
                    "LD_LIBRARY_PATH": "/lib/:/lib64/:/usr/local/lib"
                    }
                },
            "script": script
            }
        url = f"slurm/v{self.slurm_rest_api_version}/job/submit"
        return self._request('POST', url, fields)

def lambda_handler(event, context):
    try:
        logging.debug(f"event:\n{json.dumps(event, indent=4)}")

        s3_bucket = event['Records'][0]['s3']['bucket']['name']
        s3_key    = event['Records'][0]['s3']['object']['key']

        logging.info(f"Triggered by s3 put to s3://{s3_bucket}/{s3_key}")

        cluster_name = environ['CLUSTER_NAME']
        slurm_rest_api_version = environ['SLURM_REST_API_VERSION']
        slurmrestd_url = environ['SLURMRESTD_URL']
        user_name = 'root'
        logging.info(f"CLUSTER_NAME: {cluster_name}")
        logging.info(f"SLURM_REST_API_VERSION: {slurm_rest_api_version}")
        logging.info(f"SLURMRESTD_URL: {slurmrestd_url}")
        logging.info(f"user name: {user_name}")

        slurm_rest_api = SlurmRestApi(cluster_name, slurm_rest_api_version, slurmrestd_url, user_name)

        json_response = slurm_rest_api.diag()
        logging.info(f"diag:\n{json.dumps(json_response, indent=4)}")

        json_response = slurm_rest_api.ping()
        logging.info(f"ping response:\n{json.dumps(json_response, indent=4)}")

        # Get list of nodes
        json_response = slurm_rest_api.get_all_node_info()
        logging.info(f"{len(json_response['nodes'])} nodes")
        node_state_dict = {}
        for node_dict in json_response['nodes']:
            node_state_dict[node_dict['state']] = node_state_dict.get(node_dict['state'], 0) + 1
        for node_state in sorted(node_state_dict.keys()):
            logging.info(f"    {node_state}: {node_state_dict[node_state]}")
        # logging.info(f"all node info:\n{json.dumps(json_response, indent=4)}")

        # Get list of partitions
        json_response = slurm_rest_api.get_all_partition_info()
        #logging.info(f"all partition info: {json_response}")
        logging.info(f"{len(json_response['partitions'])} partitions:")
        for partition_dict in sorted(json_response['partitions'], key=lambda p: p['name']):
            logging.info(f"    {partition_dict['name']}")

        # Get list of licenses
        json_response = slurm_rest_api.get_licenses()
        logging.info(f"{len(json_response['licenses'])} licenses:")
        for license_dict in sorted(json_response['licenses'], key=lambda l: l['LicenseName']):
            logging.info(f"    license_dict['LicenseName']: total={license_dict['Total']:5} used={license_dict['Used']:5} free={license_dict['Free']:5}")

        json_response = slurm_rest_api.get_all_job_info()
        logging.info(f"{len(json_response['jobs'])} jobs:")
        for job_dict in sorted(json_response['jobs'], key=lambda j: j['job_id']):
            logging.info(f"    job_dict['job_id']: user_name={job_dict['user_name']} partition={job_dict['partition']} job_state={job_dict['job_state']}")

        # Test submitting a job
        json_response = slurm_rest_api.submit(name='rest-test', ntasks=1, nodes=1, constraints='c7&c6i.large&spot', script=f"#!/bin/bash\necho 'I am from the REST API'")
        logging.info(f"Submitted {json_response['job_id']}")
        json_response = slurm_rest_api.get_job_info(json_response['job_id'])

    except Exception as e:
        logging.exception(str(e))
        raise
