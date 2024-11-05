# Configuraton File Format

This project creates a ParallelCluster configuration file that is documented in the [ParallelCluster User Guide](https://docs.aws.amazon.com/parallelcluster/latest/ug/cluster-configuration-file-v3.html).

<pre>
<a href="#termination_protection">termination_protection</a>: bool
<a href="#stackname">StackName</a>: str
<a href="#region">Region</a>: str
<a href="#sshkeypair">SshKeyPair</a>: str
<a href="#vpcid">VpcId</a>: str
<a href="#cidr">CIDR</a>: str
<a href="#subnetid">SubnetId</a>: str
<a href="#errorsnstopicarn">ErrorSnsTopicArn</a>: str
<a href="#timezone">TimeZone</a>: str
<a href="#additionalsecuritygroupsstackname">AdditionalSecurityGroupsStackName</a>: str
<a href="#resstackname">RESStackName</a>: str
<a href="#externalloginnodes">ExternalLoginNodes</a>:
    - <a href="#tags">Tags</a>:
          - Key: str
            Values: [ str ]
      SecurityGroupId: str
<a href="#domainjoinedinstance">DomainJoinedInstance</a>:
    - <a href="#tags">Tags</a>:
          - Key: str
            Values: [ str ]
      SecurityGroupId: str
<a href="#slurm">slurm</a>:
    <a href="#parallelclusterconfig">ParallelClusterConfig</a>:
        <a href="#version">Version</a>: str
        <a href="#clusterconfig">ClusterConfig</a>: dict
        <a href="#image">Image</a>:
            <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/Image-v3.html#yaml-Image-Os">Os</a>: str
            <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/Image-v3.html#yaml-Image-CustomAmi">CustomAmi</a>: str
        <a href="#architecture">Architecture</a>: str
        <a href="#computenodeami">ComputeNodeAmi</a>: str
        <a href="#enableefa">EnableEfa</a>: bool
        <a href="#database">Database</a>:
            <a href="#databasestackname">DatabaseStackName</a>: str
            <a href="#fqdn">FQDN</a>: str
            <a href="#database-port">Port</a>: str
            <a href="#adminusername">AdminUserName</a>: str
            <a href="#adminpasswordsecretarn">AdminPasswordSecretArn</a>: str
            <a href="#database-clientsecuritygroup">ClientSecurityGroup</a>:
                SecurityGroupName: SecurityGroupId
        <a href="#slurmdbd">Slurmdbd</a>:
            <a href="#slurmdbdstackname">SlurmdbdStackName</a>: str
            <a href="#slurmdbd-host">Host</a>: str
            <a href="#slurmdbd-port">Port</a>: str
            <a href="#slurmdbd-clientsecuritygroup">ClientSecurityGroup</a>: str
        <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/HeadNode-v3.html#HeadNode-v3-Dcv">Dcv:</a>
            <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/HeadNode-v3.html#yaml-HeadNode-Dcv-Enabled">Enabled</a>: bool
            <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/HeadNode-v3.html#yaml-HeadNode-Dcv-Port">Port</a>: int
            <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/HeadNode-v3.html#yaml-HeadNode-Dcv-AllowedIps">AllowedIps</a>: str
        <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/LoginNodes-v3.html">LoginNodes</a>:
            <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/LoginNodes-v3.html#LoginNodes-v3-Pools">Pools</a>:
            - <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/LoginNodes-v3.html#yaml-LoginNodes-Pools-Name">Name</a>: str
                <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/LoginNodes-v3.html#yaml-LoginNodes-Pools-Count">Count</a>: int
                <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/LoginNodes-v3.html#yaml-LoginNodes-Pools-InstanceType">InstanceType</a>: str
                <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/LoginNodes-v3.html#yaml-LoginNodes-Pools-GracetimePeriod">GracetimePeriod</a>: int
                <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/LoginNodes-v3.html#yaml-LoginNodes-Pools-Image">Image</a>:
                    <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/LoginNodes-v3.html#yaml-LoginNodes-Pools-Image-CustomAmi">CustomAmi</a>: str
                <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/LoginNodes-v3.html#yaml-LoginNodes-Pools-Ssh">Ssh</a>:
                    <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/LoginNodes-v3.html#yaml-LoginNodes-Pools-Ssh-KeyName">KeyName</a>: str
                <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/LoginNodes-v3.html#yaml-LoginNodes-Pools-Networking">Networking</a>:
                    <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/LoginNodes-v3.html#yaml-LoginNodes-Pools-Networking-SubnetIds">SubnetIds</a>:
                        - str
                    <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/LoginNodes-v3.html#yaml-LoginNodes-Pools-Networking-SecurityGroups">SecurityGroups</a>:
                        - str
                    <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/LoginNodes-v3.html#yaml-LoginNodes-Pools-Networking-AdditionalSecurityGroups">AdditionalSecurityGroups</a>:
                        - str
                <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/LoginNodes-v3.html#yaml-LoginNodes-Pools-Iam">Iam</a>:
                    <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/LoginNodes-v3.html#yaml-LoginNodes-Pools-Iam-InstanceRole">InstanceRole</a>: str
                    <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/LoginNodes-v3.html#yaml-LoginNodes-Pools-Iam-InstanceProfile">InstanceProfile</a>: str
                    <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/LoginNodes-v3.html#yaml-LoginNodes-Pools-Iam-AdditionalIamPolicies">AdditionalIamPolicies</a>:
                    - <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/LoginNodes-v3.html#yaml-LoginNodes-Pools-Iam-AdditionalIamPolicies-Policy">Policy</a>: str
    <a href="#clustername">ClusterName</a>: str
    <a href="#mungekeysecret">MungeKeySecret</a>: str
    <a href="#slurmctl">SlurmCtl</a>:
        <a href="#slurmdport">SlurmdPort</a>: int
        <a href="#instance_type">instance_type</a>: str
        <a href="#volume_size">volume_size</a>: str
        <a href="#cloudwatchperiod">CloudWatchPeriod</a>: int
        <a href="#preemptmode">PreemptMode</a>: str
        <a href="#preempttype">PreemptType</a>: str
        <a href="#preemptexempttime">PreemptExemptTime</a>: str
        <a href="#slurmconfoverrides">SlurmConfOverrides</a>: str
        <a href="#slurmrestduid">SlurmrestdUid</a>: str
        <a href="#head-node-additionalsecuritygroups">AdditionalSecurityGroups</a>:
        - str
        <a href="#head-node-additionaliampolicies">AdditionalIamPolicies</a>:
        - str
        <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/HeadNode-v3.html#HeadNode-v3-Imds">Imds</a>:
            <a href="https://docs.aws.amazon.com/parallelcluster/latest/ug/HeadNode-v3.html#yaml-HeadNode-Imds-Secured">Secured</a>: bool
    <a href="#instanceconfig">InstanceConfig</a>:
        <a href="#useondemand">UseOnDemand</a>: str
        <a href="#usespot">UseSpot</a>: str
        <a href="#disablesimultaneousmultithreading">DisableSimultaneousMultithreading</a>: str
        <a href="#exclude">Exclude</a>:
            <a href="#exclude-instancefamilies">InstanceFamilies</a>:
            - str
            <a href="#exclude-instancetypes">InstanceTypes</a>:
            - str
        <a href="#include">Include</a>:
            <a href="#maxsizeonly">MaxSizeOnly</a>: bool
            <a href="#include-instancefamilies">InstanceFamilies</a>:
            - str
            - str:
                useOnDemand: bool
                UseSpot: bool
                DisableSimultaneousMultithreading: bool
            <a href="#include-instancetypes">InstanceTypes</a>:
            - str
            - str:
                UseOnDemand: bool
                UseSpot: bool
                DisableSimultaneousMultithreading: bool
        <a href="#nodecounts">NodeCounts</a>:
            <a href="#defaultmincount">DefaultMinCount</a>: str
            <a href="#defaultmaxcount">DefaultMaxCount</a>: str
            <a href="#computeresourcecounts">ComputeResourceCounts</a>:
                str: # <a href="#computeresourcename">ComputeResourceName</a>
                    <a href="#compute-resource-mincount">MinCount</a>: int
                    <a href="#compute-resource-maxcount">MaxCount</a>: int
        <a href="#compute-node-additionalsecuritygroups">AdditionalSecurityGroups</a>:
        - str
        <a href="#compute-node-additionaliampolicies">AdditionalIamPolicies</a>:
        - str
        <a href="#onpremcomputenodes">OnPremComputeNodes</a>:
            <a href="#configfile">ConfigFile</a>: str
            <a href="#on-premises-cidr">CIDR</a>: str
            <a href="#partition">Partition</a>: str
    <a href="#slurmuid">SlurmUid</a>: int
    <a href="#storage">storage</a>:
        <a href="#extramounts">ExtraMounts</a>:
        - <a href="#dest">dest</a>: str
          <a href="#src">src</a>: str
          <a href="#type">type</a>: str
          <a href="#options">options</a>: str
          <a href="#storagetype">StorageType</a>: str
          <a href="#filesystemid">FileSystemId</a>: str
          <a href="#volumeid">VolumeId</a>: str
    <a href="#licenses">Licenses</a>:
        <a href="#licensename">LicenseName</a>:
            <a href="#count">Count</a>: int
            <a href="#server">Server</a>: str
            <a href="#port">Port</a>: str
            <a href="#servertype">ServerType</a>:
            <a href="#statusscript">StatusScript</a>:
</pre>


## Top Level Config

### termination_protection

Enable Cloudformation Stack termination protection

default=True

### StackName

The name of the configuration stack that will configure ParallelCluster and deploy it.

If you do not specify the ClusterName then it will default to a value based on the StackName.
If StackName ends in `-config` then ClusterName will be the StackName with `-config` stripped off.
Otherwise it will be the StackName with `-cl` (for cluster) appended.

Optional so can be specified on the command-line

default='slurm-config'

### Region

AWS region where the cluster will be deployed.

Optional so can be specified on the command-line

### SshKeyPair

Default EC2 key pair that will be used for all cluster instances.

Optional so can be specified on the command-line

### VpcId

The ID of the VPC where the cluster will be deployed.

Optional so can be specified on the command-line

### CIDR

The CIDR of the VPC.
This is used in security group rules.

### SubnetId

The ID of the VPC subnet where the cluster will be deployed.

Optional. If not specified then the first private subnet is chosen.
If no private subnets exist, then the first isolated subnet is chosen.
If no isolated subnets exist, the the first public subnet is chosen.

We recommend using a private or isolated subnet.

### ErrorSnsTopicArn

The ARN of an existing SNS topic.
Errors will be published to the SNS topic.
You can subscribe to the topic so that you are notified for things like script or lambda errors.

Optional, but highly recommended

### TimeZone

The time zone to use for all EC2 instances in the cluster.

default='US/Central'

### AdditionalSecurityGroupsStackName

If you followed the [automated process to create security groups for external login nodes and file systems](deployment-prerequisites.md/#shared-security-groups-for-login-nodes-and-file-systems), then specify the stack name that you deployed and the additional security groups will be configured for the head and compute nodes.

### RESStackName

If you are deploying the cluster to use from Research and Engineering Studio (RES) virtual desktops, then you
can specify the stack name for the RES environment to automate the integration.
The virtual desktops automatically get configured to use the cluster.

This requires you to [configure security groups for external login nodes](deployment-prerequisites.md/#shared-security-groups-for-login-nodes-and-file-systems).

The Slurm binaries will be compiled for the OS of the desktops and and environment modulefile will be created
so that the users just need to load the cluster modulefile to use the cluster.

### ExternalLoginNodes

An array of specifications for instances that should automatically be configured as Slurm login nodes.
Each array element contains one or more tags that will be used to select login node instances.
It also includes the security group id that must be attached to the login node to give it access to the slurm cluster.
The tags for a group of instances is an array with the tag name and an array of values.

A lambda function processes each login node specification.
It uses the tags to select running instances.
If the instances do not have the security group attached, then it will attach the security group.
It will then run a script each instance to configure it as a login node for the slurm cluster.
To use the cluster, users simply load the environment modulefile that is created by the script.

For example, to configure RES virtual desktops as Slurm login nodes the following configuration is added.

```
---
ExternalLoginNodes:
- Tags:
  - Key: 'res:EnvironmentName'
    Values: [ 'res-eda' ]
  - Key: 'res:NodeType'
    Values: ['virtual-desktop-dcv-host']
  SecurityGroupId: <SlurmLoginNodeSGId>
```

### DomainJoinedInstance

A specifications for a domain joined instance that will be used to create and update users_groups.json.
It also includes the security group id that must be attached to the login node to give it access to the slurm head node so it can mount the slurm configuration file system.
The tags for the instance is an array with the tag name and an array of values.

A lambda function the specification.
It uses the tags to select a running instance.
If the instance does not have the security group attached, then it will attach the security group.
It will then run a script each instance to configure it to save all of the users and groups into a json file that
is used to create local users and groups on compute nodes when they boot.

For example, to configure the RES cluster manager, the following configuration is added.

```
---
DomainJoinedInstance:
- Tags:
  - Key: 'Name'
    Values: [ 'res-eda-cluster-manager' ]
  - Key: 'res:EnvironmentName'
    Values: [ 'res-eda' ]
  - Key: 'res:ModuleName'
    Values: [ 'cluster-manager' ]
  - Key: 'res:ModuleId'
    Values: [ 'cluster-manager' ]
  - Key: 'app'
    Values: ['virtual-desktop-dcv-host']
  SecurityGroupId: <SlurmLoginNodeSGId>
```

## slurm

Slurm configuration parameters.

### ParallelClusterConfig

ParallelCluster specific configuration parameters.

#### Version

The ParallelCluster version.

This is required and cannot be changed after the cluster is created.

Updating to a new version of ParallelCluster requires either deleting the current cluster or creating a new cluster.

#### ClusterConfig

type: dict

Additional ParallelCluster configuration settings that will be directly added
to the configuration without checking.

This will will be used to create the initial ParallelCluster configuration and other settings in this configuration file will override values in the dict.

This exists to enable further customization of ParallelCluster beyond what this configuration supports.

The [cluster configuration format](https://docs.aws.amazon.com/parallelcluster/latest/ug/cluster-configuration-file-v3.html) is documented in the ParallelCluster User Guide.

For example, if you want to change the [ScaledownIdletime](https://docs.aws.amazon.com/parallelcluster/latest/ug/Scheduling-v3.html#yaml-Scheduling-SlurmSettings-ScaledownIdletime), you would add the following to your config file.

```
slurm:
  ParallelClusterConfig:
    ClusterConfig:
      Scheduling:
        SlurmSettings:
          ScaledownIdletime: 20
```

#### Image

The OS and AMI to use for the head node and compute nodes.

##### OS

See the [ParallelCluster docs](https://docs.aws.amazon.com/parallelcluster/latest/ug/Image-v3.html#yaml-Image-Os) for the supported OS distributions and versions.

##### CustomAmi

See the [ParallelCluster docs](https://docs.aws.amazon.com/parallelcluster/latest/ug/Image-v3.html#yaml-Image-CustomAmi) for the custom AMI documentation.

**NOTE**: A CustomAmi must be provided for Rocky8 or Rocky9.
All other distributions have a default AMI that is provided by ParallelCluster.

#### Architecture

The CPU architecture to use for the cluster.

ParallelCluster doesn't support heterogeneous clusters.
All of the instances must have the same CPU architecture and the same OS.

The cluster, however, can be accessed from login nodes of any architecture and OS.

Valid Values:

* arm64
* x86_64

default: x86_64

#### ComputeNodeAmi

AMI to use for compute nodes.

All compute nodes will use the same AMI.

The default AMI is selected by the [Image](#image) parameters.

#### EnableEfa

type: bool

default: False

Recommend to not use EFA unless necessary to avoid insufficient capacity errors when starting new instances in group or when multiple instance types in the group.

See [https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/placement-groups.html#placement-groups-cluster](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/placement-groups.html#placement-groups-cluster)

#### Database

Optional

**Note**: Starting with ParallelCluster 3.10.0, you should use slurm/ParallelClusterConfig/[Slurmdbd](#slurmdbd) instead of slurm/ParallelClusterConfig/Database.
You cannot have both parameters.

Configure the Slurm database to use with the cluster.

This is created independently of the cluster so that the same database can be used with multiple clusters.

See [Create ParallelCluster Slurm Database](deployment-prerequisites.md/#create-parallelcluster-slurm-database) on the deployment prerequisites page.

If you used the [CloudFormation template provided by ParallelCluster](https://docs.aws.amazon.com/parallelcluster/latest/ug/tutorials_07_slurm-accounting-v3.html#slurm-accounting-db-stack-v3), then the easiest way to configure it is to pass
the name of the stack in slurm/ParallelClusterConfig/Database/[DatabaseStackName](#databasestackname).
All of the other parameters will be pulled from the outputs of the stack.

See the [ParallelCluster documentation](https://docs.aws.amazon.com/parallelcluster/latest/ug/Scheduling-v3.html#Scheduling-v3-SlurmSettings-Database).

##### DatabaseStackName

Name of the ParallelCluster CloudFormation stack that created the database.

The following parameters will be set using the outputs of the stack:

* FQDN
* Port
* AdminUserName
* AdminPasswordSecretArn
* ClientSecurityGroup

##### FQDN

Used with the Port to set the [Uri](https://docs.aws.amazon.com/parallelcluster/latest/ug/Scheduling-v3.html#yaml-Scheduling-SlurmSettings-Database-Uri) of the database.

##### Database: Port

type: int

Database's port.

##### AdminUserName

type: str

The identity that Slurm uses to connect to the database, write accounting logs, and perform queries. The user must have both read and write permissions on the database.

Sets the [UserName](https://docs.aws.amazon.com/parallelcluster/latest/ug/Scheduling-v3.html#yaml-Scheduling-SlurmSettings-Database-UserName) parameter in ParallelCluster.

##### AdminPasswordSecretArn

type: str

The Amazon Resource Name (ARN) of the AWS Secrets Manager secret that contains the AdminUserName plaintext password.
This password is used together with AdminUserName and Slurm accounting to authenticate on the database server.

Sets the [PasswordSecretArn](https://docs.aws.amazon.com/parallelcluster/latest/ug/Scheduling-v3.html#yaml-Scheduling-SlurmSettings-Database-PasswordSecretArn) parameter in ParallelCluster.

##### Database: ClientSecurityGroup

Security group that has permissions to connect to the database.

Required to be attached to the head node that is running slurmdbd so that the port connection to the database is allowed.

#### Slurmdbd

**Note**: This is not supported before ParallelCluster 3.10.0. If you specify this parameter then you cannot specify slurm/ParallelClusterConfig/[Database](#database).

Optional

Configure an external Slurmdbd instance to use with the cluster.
The Slurmdbd instance provides access to the shared Slurm database.
This is created independently of the cluster so that the same database can be used with multiple clusters.

This is created independently of the cluster so that the same slurmdbd instance can be used with multiple clusters.

See [Create Slurmdbd instance](deployment-prerequisites.md/#create-slurmdbd-instance) on the deployment prerequisites page.

If you used the [CloudFormation template provided by ParallelCluster](https://docs.aws.amazon.com/parallelcluster/latest/ug/external-slurmdb-accounting.html#external-slurmdb-accounting-step1), then the easiest way to configure it is to pass
the name of the stack in slurm/ParallelClusterConfig/Database/[SlurmdbdStackName](#slurmdbdstackname).
All of the other parameters will be pulled from the parameters and outputs of the stack.

See the [ParallelCluster documentation for ExternalSlurmdbd](https://docs.aws.amazon.com/parallelcluster/latest/ug/Scheduling-v3.html#Scheduling-v3-SlurmSettings-ExternalSlurmdbd).

##### SlurmdbdStackName

Name of the ParallelCluster CloudFormation stack that created the Slurmdbd instance.

The following parameters will be set using the outputs of the stack:

* Host
* Port
* ClientSecurityGroup

##### Slurmdbd: Host

IP address or DNS name of the Slurmdbd instance.

##### Slurmdbd: Port

Default: 6819

Port used by the slurmdbd daemon on the Slurmdbd instance.

##### Slurmdbd: ClientSecurityGroup

Security group that has access to use the Slurmdbd instance.
This will be added as an extra security group to the head node.

### ClusterName

Name of the ParallelCluster cluster.

Default: If StackName ends with "-config" then ClusterName is StackName with "-config" stripped off.
Otherwise add "-cl" to end of StackName.

### MungeKeySecret

AWS secret with a base64 encoded munge key to use for the cluster.
For an existing secret can be the secret name or the ARN.
If the secret doesn't exist one will be created, but won't be part of the cloudformation stack so that it won't be deleted when the stack is deleted.
Required if your login nodes need to use more than 1 cluster.

See [Create Munge Key](deployment-prerequisites.md/#create-munge-key) for more details.

### SlurmCtl

Configure the Slurm head node or controller.

Required, but can be an empty dict to accept all of the defaults.

#### SlurmdPort

Port used for the slurmd daemon on the compute nodes.

default=6818

type: int

#### instance_type

Instance type of the head node.

Must match the architecture of the cluster.

#### volume_size

The size of the EBS root volume on the head node in GB.

default=200

type: int

#### CloudWatchPeriod

The frequency of CloudWatch metrics in seconds.

default=5

type: int

#### PreemptMode

Set job preemption policy for the cluster.

Jobs can be set to be preemptible when they are submitted.
This allows higher priority jobs to preempt a running job when resources are constrained.
This policy sets what happens to the preempted jobs.

[Slurm documentation](https://slurm.schedmd.com/slurm.conf.html#OPT_PreemptMode)

Valid values:

* 'OFF'
* 'CANCEL'
* 'GANG'
* 'REQUEUE'
* 'SUSPEND'

default='REQUEUE'

#### PreemptType

[Slurm documentation](https://slurm.schedmd.com/slurm.conf.html#OPT_PreemptType)

Valid values:

* 'preempt/none'
* 'preempt/partition_prio'
* 'preempt/qos'

default='preempt/partition_prio'

#### PreemptExemptTime

[Slurm documentation](https://slurm.schedmd.com/slurm.conf.html#OPT_PreemptExemptTime)

Global option for minimum run time for all jobs before they can be considered for preemption.

A time of -1 disables the option, equivalent to 0. Acceptable time formats include "minutes", "minutes:seconds", "hours:minutes:seconds", "days-hours", "days-hours:minutes", and "days-hours:minutes:seconds".

default='0'

type: str

#### SlurmConfOverrides

File that will be included at end of slurm.conf to override configuration parameters.

This allows you to customize the slurm configuration arbitrarily.

This should be used with caution since it can result in errors that make the cluster non-functional.

type: str

#### SlurmrestdUid

User ID for the slurmrestd daemon.

type: int

default=901

#### SlurmRestApiVersion

The REST API version.

This is automatically set based on the Slurm version being used by the ParallelCluster version.

type: str

default: ''0.0.39'

#### Head Node AdditionalSecurityGroups

Additional security groups that will be added to the head node instance.

#### Head Node AdditionalIamPolicies

List of Amazon Resource Names (ARNs) of IAM policies for Amazon EC2 that will be added to the head node instance.

### InstanceConfig

Configure the instances used by the cluster for compute nodes.

ParallelCluster is limited to a total of 50 compute resources and
we only put 1 instance type in each compute resource.
This limits you to a total of 50 instance types per cluster.
If you need more instance types than that, then you will need to create multiple clusters.
If you configure both on-demand and spot for each instance type, then the limit is effectively 25 instance types because 2 compute resources will be created for each instance type.

If you configure more than 50 instance types then the installer will fail with an error.
You will then need to modify your configuration to either include fewer instance types or
exclude instance types from the configuration.

If no Include and Exclude parameters are specified then default EDA instance types
will be configured with both On-Demand and Spot Instances configured..
The defaults will include the latest generation instance families in the c, m, r, x, and u families.
Older instance families are excluded.
Metal instance types are also excluded.
Specific instance types are also excluded to keep the total number of instance types under 50.
If multiple instance types have the same amount of memory, then the instance types with the highest core counts are excluded.
This is because EDA workloads are typically memory limited, not core limited.

If any Include or Exclude parameters are specified, then minimal defaults will be used for the parameters that
aren't specified.
By default, all instance families are included and no specific instance types are included.
By default, all instance types with less than 4 GiB of memory are excluded because they don't have enough memory for a Slurm compute node.

If no includes or excludes are provided, the defaults are:

```
slurm:
  InstanceConfig:
    Exclude:
      InstanceFamilies:
      - 'a1'   # Graviton 1
      - 'c4'   # Replaced by c5
      - 'd2'   # SSD optimized
      - 'g3'   # Replaced by g4
      - 'g3s'  # Replaced by g4
      - 'h1'   # SSD optimized
      - 'i3'   # SSD optimized
      - 'i3en' # SSD optimized
      - 'm4'   # Replaced by m5
      - 'p2'   # Replaced by p3
      - 'p3'
      - 'p3dn'
      - 'r4'   # Replaced by r5
      - 't2'   # Replaced by t3
      - 'x1'
      - 'x1e'
      InstanceTypes:
      - '.*\.metal'
      # Reduce the number of selected instance types to 25.
      # Exclude larger core counts for each memory size
      # 2 GB:
      - 'c7a.medium'
      - 'c7g.medium'
      # 4 GB: m7a.medium, m7g.medium
      - 'c7a.large'
      - 'c7g.large'
      # 8 GB: r7a.medium, r7g.medium
      - 'm5zn.large'
      - 'm7a.large'
      - 'm7g.large'
      - 'c7a.xlarge'
      - 'c7g.xlarge'
      # 16 GB: r7a.large, x2gd.medium, r7g.large
      - 'r7iz.large'
      - 'm5zn.xlarge'
      - 'm7a.xlarge'
      - 'm7g.xlarge'
      - 'c7a.2xlarge'
      - 'c7g.2xlarge'
      # 32 GB: r7a.xlarge, x2gd.large, r7g.xlarge
      - 'r7iz.xlarge'
      - 'm5zn.2xlarge'
      - 'm7a.2xlarge'
      - 'm7g.2xlarge'
      - 'c7a.4xlarge'
      - 'c7g.4xlarge'
      # 64 GB: r7a.2xlarge, x2gd.xlarge, r7g.2xlarge
      - 'r7iz.2xlarge'
      - 'm7a.4xlarge'
      - 'm7g.4xlarge'
      - 'c7a.8xlarge'
      - 'c7g.8xlarge'
      # 96 GB:
      - 'm5zn.6xlarge'
      - 'c7a.12xlarge'
      - 'c7g.12xlarge'
      # 128 GB: x2iedn.xlarge, r7iz.4xlarge, x2gd.2xlarge, r7g.4xlarge
      - 'r7a.4xlarge'
      - 'm7a.8xlarge'
      - 'm7g.8xlarge'
      - 'c7a.16xlarge'
      - 'c7g.8xlarge'
      # 192 GB: m5zn.12xlarge, m7a.12xlarge, m7g.12xlarge
      - 'c7a.24xlarge'
      # 256 GB: x2iedn.2xlarge, x2iezn.2xlarge, x2gd.4xlarge, r7g.8xlarge
      - 'r7iz.8xlarge'
      - 'r7a.8xlarge'
      - 'm7a.16xlarge'
      - 'm7g.16xlarge'
      - 'c7a.32xlarge'
      # 384 GB: r7iz.12xlarge, r7g.12xlarge
      - 'r7a.12xlarge'
      - 'm7a.24xlarge'
      - 'c7a.48xlarge'
      # 512 GB: x2iedn.4xlarge, x2iezn.4xlarge, x2gd.8xlarge, r7g.16xlarge
      - 'r7iz.16xlarge'
      - 'r7a.16xlarge'
      - 'm7a.32xlarge'
      # 768 GB: r7a.24xlarge, x2gd.12xlarge
      - 'x2iezn.6xlarge'
      - 'm7a.48xlarge'
      # 1024 GB: x2iedn.8xlarge, x2iezn.8xlarge, x2gd.16xlarge
      - 'r7iz.32xlarge'
      - 'r7a.32xlarge'
      # 1536 GB: x2iezn.12xlarge, x2idn.24xlarge
      - 'r7a.48xlarge'
      # 2048 GB: x2iedn.16xlarge
      - 'x2idn.32xlarge'
      # 3072 GB: x2iedn.24xlarge
      # 4096 GB: x2iedn.32xlarge
    Include:
      InstanceFamilies:
      - 'c7a'               # AMD EPYC 9R14 Processor 3.7 GHz
      - 'c7g'               # AWS Graviton3 Processor 2.6 GHz
      - 'm5zn'              # Intel Xeon Platinum 8252 4.5 GHz
      - 'm7a'               # AMD EPYC 9R14 Processor 3.7 GHz
      - 'm7g'               # AWS Graviton3 Processor 2.6 GHz
      - 'r7a'               # AMD EPYC 9R14 Processor 3.7 GHz
      - 'r7g'               # AWS Graviton3 Processor 2.6 GHz
      - 'r7iz'              # Intel Xeon Scalable (Sapphire Rapids) 3.2 GHz
      - 'x2gd'              # AWS Graviton2 Processor 2.5 GHz 1TB
      - 'x2idn'             # Intel Xeon Scalable (Icelake) 3.5 GHz 2 TB
      - 'x2iedn'            # Intel Xeon Scalable (Icelake) 3.5 GHz 4 TB
      - 'x2iezn'            # Intel Xeon Platinum 8252 4.5 GHz 1.5 TB
      - 'u.*'
      InstanceTypes: []
```

#### UseOnDemand

Configure on-demand instances.
This sets the default for all included instance types.
It can be overridden for included instance families and by instance types.

type: bool

default: True

#### UseSpot

Configure spot instances.
This sets the default for all included instance types.
It can be overridden for included instance families and by instance types.

type: bool

default: True

#### DisableSimultaneousMultithreading

type: bool

default=True

Disable SMT on the compute nodes.
If true, multithreading on the compute nodes is disabled.
This sets the default for all included instance types.
It can be overridden for included instance families and by instance types.

Not all instance types can disable multithreading. For a list of instance types that support disabling multithreading, see CPU cores and threads for each CPU core per instance type in the Amazon EC2 User Guide for Linux Instances.

Update policy: The compute fleet must be stopped for this setting to be changed for an update.

[ParallelCluster documentation](https://docs.aws.amazon.com/parallelcluster/latest/ug/Scheduling-v3.html#yaml-Scheduling-SlurmQueues-ComputeResources-DisableSimultaneousMultithreading)

#### Exclude

Instance families and types to exclude.

Exclude patterns are processed first and take precedence over any includes.

Instance families and types are regular expressions with implicit '^' and '$' at the begining and end.

##### Exclude InstanceFamilies

Regular expressions with implicit '^' and '$' at the begining and end.

Default: []

##### Exclude InstanceTypes

Regular expressions with implicit '^' and '$' at the begining and end.

Default: []

#### Include

Instance families and types to include.

Exclude patterns are processed first and take precedence over any includes.

Instance families and types are regular expressions with implicit '^' and '$' at the begining and end.

Each element in the array can be either a regular expression string or a dictionary where the only key
is the regular expression string and that has overrides **UseOnDemand**, **UseSpot**, and **DisableSimultaneousMultithreading** for the matching instance families or instance types.

The settings for instance families overrides the defaults, and the settings for instance types override the others.

For example, the following configuration defaults to only On-Demand instances with SMT disabled.
It includes all of the r7a, r7i, and r7iz instance types.
The r7a instances will only have On-Demand instances.
The r7i and r7iz instance types will have spot instances except for the r7i.48xlarge which has spot disabled.

This allows you to control these attributes of the compute resources with whatever level of granularity that you need.

```
slurm:
  InstanceConfig:
    UseOnDemand: true
    UseSpot: false
    DisableSimultaneousMultithreading: true
    Exclude:
      InstanceTypes:
        - .*\.metal
    Include:
      InstanceFamilies:
        - r7a.*
        - r7i.*: {UseSpot: true}
      InstanceTypes:
        - r7i.48xlarge: {UseSpot: false}
```

##### MaxSizeOnly

type: bool

default: False

If MaxSizeOnly is True then only the largest instance type in a family will be included unless specific instance types are included.

##### Include InstanceFamilies

Regular expressions with implicit '^' and '$' at the begining and end.

Default: []

##### Include InstanceTypes

Regular expressions with implicit '^' and '$' at the begining and end.

Default: []

#### NodeCounts

Configure the number of compute nodes of each instance type.

##### DefaultMinCount

type: int

default: 0

Minimum number of compute nodes to keep running in a compute resource.
If the number is greater than zero then static nodes will be created.

##### DefaultMaxCount

type: int

The maximum number of compute nodes to create in a compute resource.

##### ComputeResourceCounts

Define compute node counts per compute resource.

These counts will override the defaults set by [DefaultMinCount](#defaultmincount) and [DefaultMaxCount](#defaultmaxcount).

###### ComputeResourceName

Name of the ParallelCluster compute resource. Can be found using `sinfo`.

####### Compute Resource MinCount

type: int

default: 0

####### Compute Resource MaxCount

type: int

#### Compute Node AdditionalSecurityGroups

Additional security groups that will be added to the compute node instances.

#### Compute Node AdditionalIamPolicies

List of Amazon Resource Names (ARNs) of IAM policies for Amazon EC2 that will be added to the compute node instances.

#### OnPremComputeNodes

Define on-premises compute nodes that will be managed by the ParallelCluster head node.

The compute nodes must be accessible from the head node over the network and any firewalls must allow all of the Slurm ports between the head node and compute nodes.

ParallelCluster will be configured to allow the neccessary network traffic and
the on-premises firewall can be configured to match the ParallelCluster seccurity groups.

##### ConfigFile

Configuration file with the on-premises compute nodes defined in Slurm NodeName format as described in the [Slurm slurm.conf documentation](https://slurm.schedmd.com/slurm.conf.html#OPT_NodeName).

The file will be included in the ParallelCluster slurm.conf so it can technically include any Slurm configuration updates including custom partition definitions.

**NOTE**: The syntax of the file isn't checked and syntax errors can result in the slurmctld daemon failing on the head node.

##### On-Premises CIDR

The CIDR that contains the on-premises compute nodes.

This is to allow egress from the head node to the on-premises nodes.

##### Partition

A partition that will contain all of the on-premises nodes.

### SlurmUid

type: int

default: 900

The user id of the slurm user.

### storage

#### ExtraMounts

Additional mounts for compute nodes.

This can be used so the compute nodes have the same file structure as the remote desktops.

This is used to configure [ParallelCluster SharedStorage](https://docs.aws.amazon.com/parallelcluster/latest/ug/SharedStorage-v3.html).

For example:

```
storage:
    ExtraMounts:
    - dest: "/tools"
      StorageType: FsxOpenZfs
      VolumeId: 'fsvol-abcd1234'
      src: 'fs-efgh5678.fsx.us-east-1.amazonaws.com:/fsx/'
      type: nfs4
      options: 'nfsvers=4.1'
```

##### dest

The directory where the file system will be mounted.

This sets the [MountDir](https://docs.aws.amazon.com/parallelcluster/latest/ug/SharedStorage-v3.html#yaml-SharedStorage-MountDir).

##### src

The source path on the file system export that will be mounted.

##### type

The type of mount. For example, nfs3.

##### options

Mount options.

##### StorageType

The type of file system to mount.

Valid values:

* Efs
* FsxLustre
* FsxOntap
* FsxOpenZfs

##### FileSystemId

Specifies the ID of an existing [FSx for Lustre](https://docs.aws.amazon.com/parallelcluster/latest/ug/SharedStorage-v3.html#yaml-SharedStorage-FsxLustreSettings-FileSystemId) or [EFS](https://docs.aws.amazon.com/parallelcluster/latest/ug/SharedStorage-v3.html#yaml-SharedStorage-EfsSettings-FileSystemId) file system.

##### VolumeId

Specifies the volume ID of an existing [FSx for ONTAP](https://docs.aws.amazon.com/parallelcluster/latest/ug/SharedStorage-v3.html#yaml-SharedStorage-FsxOntapSettings-VolumeId) or [FSx for OpenZFS](https://docs.aws.amazon.com/parallelcluster/latest/ug/SharedStorage-v3.html#yaml-SharedStorage-FsxOpenZfsSettings-VolumeId) file system.

### Licenses

Configure license counts for the scheduler.

If the Slurm database is configured then it will be updated with the license counts.
Otherwise, the license counts will be added to slurm.conf.

#### LicenseName

The name of the license, for example, `VCSCompiler_Net` or `VCSMXRunTime_Net`.
This is the license name that users specify when submitting a job.
It doesn't have to match the license name reported by the license server,
although that probably makes the most sense.

##### Count

The number of licenses available to Slurm to use to schedule jobs.
Once all of the license are used by running jobs, then any pending jobs will remain pending until a license becomes available.

##### Server

The license server hosting the licenses.

Not currently used.

##### Port

The port on the license server used to request licenses.

Not currently used.

##### ServerType

The type of license server, such as FlexLM.

Not currently used.

##### StatusScript

A script that queries the license server and dynamically updates the Slurm database with the actual total number of licenses and the number used.

Not currently implemented.

</pre>
