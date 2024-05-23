# RES Integration

Integration with [Research and Engineering Studion (RES)](https://docs.aws.amazon.com/res/latest/ug/overview.html) is straightforward.
You simply specify the **--RESEnvironmentName** option for the `install.sh` script or add the **RESEnvironmentName** configuration parameter
to your configuration file.
The install script will set the following configuration parameters based on your RES environment or check them if you have them set to make sure they are consistent
with your RES environment.
The intention is to completely automate the deployment of ParallelCluster and set up the RES environment so that it can easily be used.

| Parameter | Description | Value
|-----------|-------------|------
| VpcId     | VPC id for the RES cluster | vpc-xxxxxx
| SubnetId  | Subnet in the RES VPC. | subnet-xxxxx
| SubmitterInstanceTags | The tag of VDI instances. | 'res:EnvironmentName': *EnvironmentName*'
| ExtraMounts | The mount parameters for the /home directory. This is required for access to the home directory. |
| ExtraMountSecurityGroups | Security groups that give access to the ExtraMounts. These will be added to compute nodes so they can access the file systems.

You must also create security groups as described in [Security Groups for Login Nodes](deployment-prerequisites.md#security-groups-for-login-nodes) and specify the SlurmHeadNodeSG in the `slurm/SlurmCtl/AdditionalSecurityGroups` parameter and the SlurmComputeNodeSG in the `slurm/InstanceConfig/AdditionalSecurityGroups` parameter.

When you specify **RESEnvironmentName**, a lambda function will run SSM commands to create a cron job on a RES domain joined instance to update the users_groups.json file every hour. Another lambda function will also automatically configure all running VDI hosts to use the cluster.

The following example shows the configuration parameters for a RES with the EnvironmentName=res-eda.

```
---
#====================================================================
# EDA Slurm cluster for RES using ParallelCluster
#
# Defaults and valid configuration options are in source/config_schema.py.
# Command line values override values in the config file.
#====================================================================

StackName: res-eda-pc-3-9-1-rhel8-x86-config

Region: <region>
SshKeyPair: <key-name>

RESEnvironmentName: res-eda

ErrorSnsTopicArn: <topic-arn>

TimeZone: 'US/Central'

slurm:
  ClusterName: res-eda-pc-3-9-1-rhel8-x86

  ParallelClusterConfig:
    Version: '3.9.1'
    Image:
      Os: 'rhel8'
    Architecture: 'x86_64'
    Database:
      DatabaseStackName: pcluster-slurm-db-res

  SlurmCtl:
    AdditionalSecurityGroups:
    - sg-12345678 # SlurmHeadNodeSG

  # Configure typical EDA instance types
  # A partition will be created for each combination of Base OS, Architecture, and Spot
  InstanceConfig:
    AdditionalSecurityGroups:
    - sg-23456789 # SlurmComputeNodeSG
    UseSpot: true
    NodeCounts:
      DefaultMaxCount: 10
```

When the cluster deployment finishes you are ready to run jobs from your RES DCV desktop.
