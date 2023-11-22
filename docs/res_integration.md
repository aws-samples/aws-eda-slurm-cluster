# RES Integration

Integration with [Research and Engineering Studion (RES)](https://docs.aws.amazon.com/res/latest/ug/overview.html) is straightforward.

Set the following parameters in your config file.

| Parameter | Description | Value
|-----------|-------------|------
| VpcId     | VPC id for the RES cluster | vpc-xxxxxx
| SubnetId  | Private subnet in the RES VPC. | subnet-xxxxx
| SubmitterSecurityGroupIds | The security group name and id used by RES VDIs. The name will be something like *EnvironmentName*-vdc-dcv-host-security-group | *EnvironmentName*-*VDISG*: sg-xxxxxxxx
| SubmitterInstanceTags | The tag of VDI instances. | 'res:EnvironmentName': *EnvironmentName*'
| ExtraMounts | Add the mount parameters for the /home directory. This is required for access to the home directory. |
| ExtraMountSecurityGroups | Security groups that give access to the ExtraMounts. These will be added to compute nodes so they can access the file systems.

The following example shows the configuration parameters for a RES with the EnvironmentName=res-eda.

```
---
#====================================================================
# EDA Slurm cluster for RES using ParallelCluster
#
# Defaults and valid configuration options are in source/config_schema.py.
# Command line values override values in the config file.
#====================================================================

StackName: res-eda-pc-3-7-2-r8-x86-config

Region: <region>
SshKeyPair: <key-name>

VpcId: vpc-xxxxxxxxxxxxxxxxx # res-bi

SubnetId: subnet-xxxxxxxxxxxxxxxxx # res-bi, res-bi-Networking-xxxxxxxxxxxxx:PrivateSubnetA-<region>

ErrorSnsTopicArn: <topic-arn>

TimeZone: 'US/Central'

slurm:
  ClusterName: res-eda-pc-3-7-2-r8-x86

  ParallelClusterConfig:
    Version: '3.7.2'
    Image:
      Os: 'rhel8'
    Architecture: 'x86_64'
    Database:
      DatabaseStackName: pcluster-slurm-db-res

  # External security groups that should be able to use the cluster
  SubmitterSecurityGroupIds:
    res-eda-DCV-SG: sg-xxxxxxxxxxxxxxxxx # res-eda-vdc-dcv-host-security-group

  SubmitterInstanceTags:
    'res:EnvironmentName': ['res-eda']

  SlurmCtl: {}

  # Configure typical EDA instance types
  # A partition will be created for each combination of Base OS, Architecture, and Spot
  InstanceConfig:
    UseSpot: true
    NodeCounts:
      DefaultMaxCount: 10

  storage:
    ExtraMounts:
      - dest: /home
        StorageType: Efs
        FileSystemId: 'fs-06613eabfa09fe039'
        FileSystemId: 'fs-xxxxxxxxxxxxxxxxx'
        src: fs-xxxxxxxxxxxxxxxxx.efs.<region>.amazonaws.com:/
        type: nfs4
        options: nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2,noresvport
    ExtraMountSecurityGroups:
      nfs:
        res-eda-DCV-SG: sg-xxxxxxxxxxxxxxxxx # res-eda-vdc-dcv-host-security-group

Licenses:
  vcs:
    Count: 10
    Server: synopsys_licenses
    Port: '24680'
    ServerType: flexlm
  ansys:
    Count: 1
    Server: ansys_licenses
    Port: '2200'
```
Deploy your cluster.

Connect to the RES cluster manager instance and follow the instructions to [Create users_groups.json](deploy-parallel-cluster.md#create-users_groupsjson).

Connect to a remote desktop instance and follow the instructions in [Configure submission hosts to use the cluster](deploy-parallel-cluster.md#configure-submission-hosts-to-use-the-cluster).
If all users need to use the cluster then it is probably best to create a custom AMI that is configured with the configuration
commands.

You are now ready to run jobs from your RES DCV desktop.
