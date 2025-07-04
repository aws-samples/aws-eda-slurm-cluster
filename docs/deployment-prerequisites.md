# Deployment Prerequisites

This page shows common prerequisites that need to be done before deployment.

## Deployment Server/Instance Requirements

The deployment process was developed and tested using Mac OS and RHEL 8.
Amazon Linux 2 doesn't support the current version of node.js so it cannot be used.
It has also been tested on RHEL 9 and should work on Rocky Linux 8 and 9.

If the required packages aren't installed then you will need sudo or root access on the instance.

## Configure AWS CLI Credentials

You will needs AWS credentials that provide admin access to deploy the cluster.

## Clone or Download the Repository

Clone or download the aws-eda-slurm-cluster repository to your system.

```
git clone https://github.com/aws-samples/aws-eda-slurm-cluster.git
```

## Create SNS Topic for Error Notifications (Optional but recommended)

The Slurm cluster allows you to specify an SNS notification that will be notified when an error is detected.
You can provide the ARN for the topic in the config file or on the command line.

You can use the SNS notification in various ways.
The simplest is to subscribe your email address to the topic so that you get an email when there is an error.
You could also use it to trigger a CloudWatch alarm that could be used to trigger a lambda to do automatic
remediation or create a support ticket.

## Make sure using at least python version 3.7

This application requires at least python version 3.7.

Many distributions use older versions of python by default such as python 3.6.8 in RHEL 8 and Rocky Linux 8.
Newer versions are available, but can't be made the system default without breaking OS tools such as yum.
The easiest way to get around this is to create a python virtual environment using a newer version of python.
Simply install the newer version and then use it to create and activate a virtual environment.

```
$ python3 --version
Python 3.6.8
$ yum -y install python3.12
$ python3.12 -m venv ~/.venv-python3.12
$ source ~/.venv-python3.12/bin/activate
$ python3 --version
Python 3.12.8
```

## Make sure required packages are installed

```
cd aws-eda-slurm-cluster
source setup.sh
```

The setup script assumes that you have sudo access so that you can install or update packages.
If you do not, then contact an administrator to help you do the updates.
If necessary modify the setup script for your environment.

### Install Cloud Development Kit (CDK) (Optional)

The setup script will attempt to install all of the prerequisites for you.
If the install script fails on your system then you can refer to this section for instructions
on how to install or update CDK.

This cluster uses Cloud Development Kit (CDK) and Python 3 to deploy the cluster.

Install the packages used by the installer.

```
sudo yum -y install curl gcc-c++ make nfs-utils python3 tcl unzip wget
```

The following link documents how to setup for CDK.
Follow the instructions for Python.

[https://docs.aws.amazon.com/cdk/v2/guide/getting_started.html#getting_started_prerequisites](https://docs.aws.amazon.com/cdk/v2/guide/getting_started.html#getting_started_prerequisites)

Note that CDK requires a pretty new version of nodejs which you may have to download from, for example, [https://nodejs.org/dist/v20.19.0/node-v20.19.0-linux-x64.tar.xz](https://nodejs.org/dist/v20.19.0/node-v20.19.0-linux-x64.tar.xz)

```
sudo yum -y install wget
wget https://nodejs.org/dist/v20.19.0/node-v20.19.0-linux-x64.tar.xz
tar -xf node-v20.19.0-linux-x64.tar.xz ~
```

Add the nodjs bin directory to your path.

[https://docs.aws.amazon.com/cdk/v2/guide/getting_started.html#getting_started_install](https://docs.aws.amazon.com/cdk/v2/guide/getting_started.html#getting_started_install)

Note that the version of aws-cdk changes frequently.
The version that has been tested is in the CDK_VERSION variable in the install script.

The install script will try to install the prerequisites if they aren't already installed.

## Create ParallelCluster UI (optional but recommended)

It is highly recommended to create a ParallelCluster UI to manage your ParallelCluster clusters.
A different UI is required for each version of ParallelCluster that you are using.
The versions are list in the [ParallelCluster Release Notes](https://docs.aws.amazon.com/parallelcluster/latest/ug/document_history.html).
The minimum required version is 3.6.0 which adds support for RHEL 8 and increases the number of allows queues and compute resources.
The suggested version is at least 3.7.0 because it adds configurable compute node weights which we use to prioritize the selection of
compute nodes by their cost.

The instructions are in the [ParallelCluster User Guide](https://docs.aws.amazon.com/parallelcluster/latest/ug/install-pcui-v3.html).

## Create Munge Key

Munge is a package that Slurm uses to secure communication between servers.
The munge service uses a preshared key that must be the same on all of the servers in the Slurm cluster.
If you want to be able to use multiple clusters from your submission hosts, such as virtual desktops, then all of the clusters must be using the same munge key.
This is done by creating a munge key and storing it in secrets manager.
The secret is then passed as a parameter to ParallelCluster so that it can use it when configuring munge on all of the cluster instances.

To create the munge key and store it in AWS Secrets Manager, run the following commands.

```
aws secretsmanager create-secret --name SlurmMungeKey --secret-string "$(dd if=/dev/random bs=1024 count=1 | base64 -w 0)"
```

Save the ARN of the secret for when you create the Slurmdbd instance and for when you create the configuration file.

See the [Slurm documentation for authentication](https://slurm.schedmd.com/authentication.html) for more information.

See the [ParallelCluster documentation for MungeKeySecretArn](https://docs.aws.amazon.com/parallelcluster/latest/ug/Scheduling-v3.html#yaml-Scheduling-SlurmSettings-MungeKeySecretArn).

See the [MungeKeySecret configuration parameter](config.md/#mungekeysecret).

## Create ParallelCluster Slurm Database

The Slurm Database is required for configuring Slurm accounts, users, groups, and fair share scheduling.
It you need these and other features then you will need to create a ParallelCluster Slurm Database.
You do not need to create a new database for each cluster; multiple clusters can share the same database.
Follow the directions in this [ParallelCluster tutorial to configure slurm accounting](https://docs.aws.amazon.com/parallelcluster/latest/ug/tutorials_07_slurm-accounting-v3.html#slurm-accounting-db-stack-v3).

## Create Slurmdbd Instance

**Note**: Before ParallelCluster 3.10.0, the slurmdbd daemon that connects to the data was created on each cluster's head node.
The recommended Slurm architecture is to have a shared slurmdbd daemon that is used by all of the clusters.
Starting in version 3.10.0, ParallelCluster supports specifying an external slurmdbd instance when you create a cluster and provide a cloud formation template to create it.

**Note**: The Slurm version used by slurmdbd must be greater than or equal to the version of your clusters.
If you have already deployed a slurmdbd instance then you will need to create a new slurmdbd
instance with the latest version of ParallelCluster.
Also note that Slurm only maintains backwards compatibility for the 2 previous major releases so
at some point you will need upgrade your clusters to newer versions before you can use the latest version
of ParallelCluster.

Follow the directions in this [ParallelCluster tutorial to configure slurmdbd](https://docs.aws.amazon.com/parallelcluster/latest/ug/external-slurmdb-accounting.html#external-slurmdb-accounting-step1).
This requires that you have already created the slurm database.

Here are some notes on the required parameters and how to fill them out.

| Parameter    | Description
|--------------|------------
| AmiId        | You can get this using the ParallelCluster UI. Click on Images and sort on Operating system. Confirm that the version is at least 3.10.0. Select the AMI for alinux2023 and the arm64 architecture.
| CustomCookbookUrl | Leave blank
| DBMSClientSG | Get this from the DatabaseClientSecurityGroup output of the database stack.
| DBMSDatabaseName | This is an arbitrary name. It must be alphanumeric. I use **slurmaccounting**
| DBMSPasswordSecretArn | Get this from the DatabaseSecretArn output of the database stack
| DBMSUri               | Get this from the DatabaseHost output of the database stack. Note that if you copy and paste the link you should delete the https:// prefix and the trailing '/'.
| DBMSUsername          | Get this from the DatabaseAdminUser output of the database stack.
| EnableSlurmdbdSystemService | Set to true. Note the warning. If the database already exists and was created with an older version of slurm then the database will be upgraded. This may break clusters using an older slurm version that are still using the cluster. Set to false if you don't want this to happen.
| InstanceType          | Choose an instance type that is compatible with the AMI. For example, m7g.large.
| KeyName               | Use an existing EC2 key pair.
| MungeKeySecretArn     | ARN of an existing munge key secret. See [Create Munge Key](#create-munge-key).
| PrivateIp             | Choose an available IP in the subnet.
| PrivatePrefix         | CIDR of the instance's subnet.
| SlurmdbdPort          | 6819
| SubnetId              | Preferably the same subnet where the clusters will be deployed.
| VPCId                 | The VPC of the subnet.

The stack name will be used in two places.
It will be used by the script that creates security groups for you in the following section.
It will also be used in the slurm/ParallelClusterConfig/[SlurmdbdStackName](config.md/#slurmdbdstackname) configuration parameter when you create your cluster.

The stack will only take about 3 minutes to deploy.

## Shared Security Groups for login nodes and file systems

Instances like remote desktops that access the cluster directly are called login nodes.
If you want to use your own login nodes to access the cluster, then you must define
several security groups that allow connections between the login nodes, the Slurm head node, and the Slurm compute nodes.
If you are using shared file servers like FSx file systems, then you also need to configure security
groups for the file systems that allows the login and slurm nodes to access the file systems.

The [details](security-groups.md) are straightforward, but time consuming, so the process has been automated for you.
Simply run the following script which will deploy a CloudFormation stack that creates the required
security groups.

```
cd aws-eda-slurm-cluster
./create-slurm-security-groups.sh --region <REGION> --stack-name <STACK_NAME> --VpcId <VPC_ID>
```

Additional script options can be specified if you created an external SlurmDbd instance or have existing security groups for your FSx file systems.

| Script Option                    | Description
|----------------------------------|-----
| **--slurmdbd-stack-name**        | Stack name that deployed external slurmdbd instance.
| **--slurmdbd-security-group-id** | Id of security group attached to the slurmdbd instance.
| **--fsxl-security-group-id**     | Id of security group attached to FSx for Lustre file systems
| **--fsxo-security-group-id**     | Id of security group attached to FSx for NetApp Ontap file systems
| **--fsxz-security-group-id**     | Id of security group attached to FSx for OpenZfs file systems

The stack outputs will have the security group ids.

| Output Name          | Use
|----------------------|------
| SlurmHeadNodeSGId    | Additional security group for Slurm head node
| SlurmComputeNodeSGId | Additional security group for Slurm compute nodes
| SlurmSubmitterSGId   | Additional security group for Slurm login nodes
| SlurmLustreSGId      | Security group for FSx for Lustre file systems
| SlurmOntapSGId       | Security group for FSx for NetApp Ontap file systems
| SlurmZfsSGId         | Security group for FSx for OpenZfs file systems

You can pass the name of the stack to the [AdditionalSecurityGroupsStackName](config.md/#additionalsecuritygroupsstackname) configuration parameter when you create your cluster
and it will get the security groups ids for you and configure the cluster to use them.

## Create File Systems

Most EDA workloads require a high performance shared file system.
AWS provides managed file systems that meet the needs of EDA workloads.
FSx for NetApp ONTAP, FSx for OpenZfs, and FSx for Lustre are managed file systems
that meet the needs of EDA workloads.

Create the file systems that you require and use the appropriate security group from the previous section
when you create the file system.

If the file system already exists, then attach the appropriate security group to the network interfaces of
the file systems.

## Create Exostellar Management Server

If you're going to use Exostellar Infrastructure Optimizer (XIO) then you will need to deploy the Exostellar management server.
See the [XIO page](exostellar-infrastructure-optimizer.md) for details.

## Create Configuration File

Before you deploy a cluster you need to create a configuration file.
A default configuration file is found in [source/resources/config/default_config.yml](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/resources/config/default_config.yml).
You should create a new config file and update the parameters for your cluster.
Ideally you should version control this file so you can keep track of changes.

The schema for the config file along with its default values can be found in [source/cdk/config_schema.py](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/cdk/config_schema.py#L230-L445).
The schema is defined in python, but the actual config file should be in yaml format.
See [Configuration File Format](config.md) for documentation on all of the parameters.

The following are key parameters that you will need to update.
If you do not have the required parameters in your config file then the installer script will fail unless you specify the `--prompt` option.
You should save your selections in the config file.

| Parameter                          | Description | Valid Values | Default
|------------------------------------|-------------|--------------|--------
| [StackName](config.md/#stackname) | The cloudformation stack that will deploy the cluster. I prefer to end the name with "-config" .|  | None
| [slurm/ClusterName](config.md/#clustername) | Name of the Slurm cluster | Can't be the same as StackName. | If StackName ends in "-config" then StackName with "-config" stripped off. Otherwise, StackName with "-cl" appended.
| [Region](config.md/#region) | Region where VPC is located | | `$AWS_DEFAULT_REGION`
| [VpcId](config.md/#vpcid)  | The vpc where the cluster will be deployed. |  vpc-* | None
| [SshKeyPair](config.md/#sshkeypair) | EC2 Keypair to use for instances | | None
| [ErrorSnsTopicArn](config.md/#errorsnstopicarn) | ARN of an SNS topic that will be notified of errors | `arn:aws:sns:{{region}}:{AccountId}:{TopicName}` | None
| [slurm/InstanceConfig](config.md/#instanceconfig) | Configure instance types that the cluster can use and number of nodes. | | See [default_config.yml](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/resources/config/default_config.yml)
| [AdditionalSecurityGroupsStackName](config.md/#additionalsecuritygroupsstackname) | Name of stack that created security groups for external login nodes and file systems. | |
| [RESStackName](config.md/##resstackname) | Name of RES environment | |
| [slurm/storage/ExtraMounts](config.md/#extramounts) | Extra mount points | | None

### Configure Slurm Accounting database (slurmdbd)

If you [created a ParallelCluster Slurm Database](#create-parallelcluster-slurm-database) and a [Slurmdbd Instance](#create-slurmdbd-instance) then add the following configuration parameters.

```
slurm:
  ParallelClusterConfig:
    Slurmdbd:
      SlurmdbdStackName: <Slurmdbd-Stack-Name>
```

### Configure Linux Users and Groups

The cluster defines a script that can capture the users and groups from your identity provider (IDP) into a json file.
When a new compute node starts, another script creates local Linux users and groups from the json file.

The first script gets installed at:

`/opt/slurm/{{ cluster_name }}/config/bin/create_users_and_groups_json.py`

This script should be run on an instance that is joined to your IDP.
It first tries to use `wbinfo -u` and if that fails it uses `getent passwd` to get the list of users and their userids.
It uses `id` to get the uid and gids for the users.
The json file gets stored at

`/opt/slurm/{{ cluster_name }}/config/users_groups.json`

The compute node calls:

`/opt/slurm/{{ cluster_name }}/config/bin/create_users_groups.py -i /opt/slurm/{{ cluster_name }}/config/users_groups.json`

The script calls useradd and groupadd to create local users and groups.

To enable this mechanism you must configure the EC2 tags of the domain joined instance that will be used to create the json file.
A Lambda function will create the json file and create a lambda that will refresh it hourly.
You will also need to provide the security group id of the SlurmExternalLoginNodeSG which will be added to the instance so that it can mount the head node's NFS file system.

```
DomainJoinedInstance:
  Tags:
    - Key: Name
      Value: ClusterManager
  SecurityGroupId: sg-xxxxxxxx
```

You can provide 1 or more keys and the set will be done on the first instance that matches.

**Note:** You do not have to use this mechanism.
ParallelCluster supports using Microsoft Active Directory and you can configure that using the `slurm/ParallelClusterConfig/ClusterConfig/DirectoryService` [parameter](https://docs.aws.amazon.com/parallelcluster/latest/ug/DirectoryService-v3.html).
You can also use custom action scripts that run on your compute nodes that configure domains or users and groups to meet your needs.

**Note:** This is automatically configured for you if you specify the [RESStackName](config.md/#resstackname) parameter.

### Configure the Compute Instances

The [slurm/InstanceConfig](config.md/#instanceconfig) configuration parameter configures the base operating systems, CPU architectures, instance families,
and instance types that the Slurm cluster should support.
ParallelCluster currently doesn't support heterogeneous clusters;
all nodes must have the same architecture and Base OS.

| Base OS        | CPU Architectures
|----------------|------------------
| Amazon Linux 2 | x86_64, arm64
| CentOS 7       | x86_64
| RedHat 7       | x86_64
| RedHat 8       | x86_64, arm64
| RedHat 9       | x86_64, arm64
| Rocky 8        | x86_64, arm64
| Rocky 9        | x86_64, arm64

You can exclude instances types by family or specific instance type.
By default the InstanceConfig excludes older generation instance families.

You can include instances by family or specific instance type.
If no includes are specified then all non-excluded instance types will be used.
You can also choose to only include the largest instance size within a family.
The advantage of using the max instance size is that jobs running on the instance
have the highest network bandwidth for that family and fewer instances are required
to run the same number of jobs.
This may help jobs run faster and allow jobs to wait less time for a new instance to start.
The disadvantage is higher cost if the instance is lightly loaded.

The default InstanceConfig includes all supported base OSes and architectures and burstable and general purpose
instance types.

* [default instance families](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/cdk/config_schema.py#L230-L271)
* [default instance types](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/cdk/config_schema.py#L314-L319)
* [default excluded instance families](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/cdk/config_schema.py#L321-L338)
* [default excluded instance types](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/cdk/config_schema.py#L340-L343)

Note that instance types and families are python regular expressions.

```
slurm:
  InstanceConfig:
    Include:
      InstanceFamilies:
        - t3.*
        - m6a.*
      InstanceTypes:
        - r6a.large
```

The following InstanceConfig configures instance types recommended for EDA workloads running on CentOS.

```
slurm:
  InstanceConfig:
    Include:
      InstanceFamilies:
        - c5.*
        - c6g.*
        - f1
        - m5.*
        - m6g.*
        - r5.*
        - r6g.*
        - x2gd
        - z1d
```

If you have reserved instances (RIs) or savings plans then you can configure instances so that they are always on since you are paying for them whether they are running or not.
To do this add a MinCount greater than 0 for the compute resources that contain the instance types.

```
slurm:
  InstanceConfig:
    NodeCounts:
      DefaultMinCount: 1
```

### Configure Fair Share Scheduling (Optional)

Slurm supports [fair share scheduling](https://slurm.schedmd.com/fair_tree.html), but it requires the fair share policy to be configured.
By default, all users will be put into a default group that has a low fair share.
The configuration file is at [source/resources/playbooks/roles/ParallelClusterHeadNode/files/opt/slurm/config/accounts.yml.example](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/resources/playbooks/roles/ParallelClusterHeadNode/files/opt/slurm/config/accounts.yml.example)
in the repository and is deployed to **/opt/slurm/{{ClusterName}}/conf/accounts.yml**.

The file is a simple yaml file that allows you to configure groups, the users that belong to the group, and a fair share weight for the group.
Refer to the Slurm documentation for details on how the fair share weight is calculated.
The scheduler can be configured so that users who aren't getting their fair share of resources get
higher priority.
The following shows 3 top level groups.
Note that the fairshare weights aren't a percentage. They are just a relative weight.
In this example, the projects have 9 times higher weight than the jenkins group.

```
jenkins:
  fairshare: 10
  users:
  - jenkins

project1:
  fairshare: 90

project2:
  fairshare: 90
```

The allocation of top level groups can be further subdivided to control the
relative priority of jobs within that group.
For example, a project may have design verification (dv), rtl design (rtl), physical design (dv),
and formal verification (fv) teams.
The following example shows how the project's allocation can be prioritized for the different teams.
If a group is using more than it's fair share then its jobs will have lower priority than
jobs whose users aren't getting their fair share.

```
project1-dv:
  parent: project1
  fairshare: 80
  users:
  - dvuser1
project1-pd:
  parent: project1
  fairshare: 10
  users:
  - pduser1
project1-rtl:
  parent: project1
  fairshare: 10
  users:
  - rtluser1
project1-fv:
  parent: project1
  fairshare: 10
  users:
  - fvuser1
```

The scheduler uses the **priority/multifactor** plugin to calculate job priorities.
Fair share is just one of the factors.
Read the [Multifactor Priority Plugin](https://slurm.schedmd.com/priority_multifactor.html) documentation
for the details.

This is the default configuration in slurm.conf.
The partition weight is set the highest so that jobs in the interactive partition always have the highest priority.
Fairshare and QOS are the next highest weighted factors.
The next factor is the job age, which means all else being equal the jobs run in FIFO order with the jobs that have been waiting
the longest getting higher priority.

```
PriorityType=priority/multifactor
PriorityWeightPartition=100000
PriorityWeightFairshare=10000
PriorityWeightQOS=10000
PriorityWeightAge=1000
PriorityWeightAssoc=0
PriorityWeightJobSize=0
```

These weights can be adjusted based on your needs to control job priorities.

### Configure Licenses

Slurm supports [configuring licenses as a consumable resource](https://slurm.schedmd.com/licenses.html).
It will keep track of how many running jobs are using a license and when no more licenses are available
then jobs will stay pending in the queue until a job completes and frees up a license.
Combined with the fairshare algorithm, this can prevent users from monopolizing licenses and preventing others from
being able to run their jobs.

Licenses are configured using the [slurm/Licenses](config.md/#licenses) configuration variable.
If you are using the Slurm database then these will be configured in the database.
Otherwise they will be configured in **/opt/slurm/{{ClusterName}}/etc/pcluster/custom_slurm_settings_include_file_slurm.conf**.

The example configuration shows how the number of licenses can be configured.
In this example, the cluster will manage 800 vcs licenses and 1 ansys license.
Users must request a license using the **-L** or **--licenses** options.

```
slurm:
  Licenses:
    vcs:
      Count: 800
    ansys:
      Count: 1
```

### Configure File Systems

The Storage/ExtraMounts parameter allows you to configure additional file systems to mount on compute nodes.
Note that the security groups for the file systems must allow connections from the compute nodes.

#### Lustre

The following example shows how to add an FSx for Lustre file system.
The mount information can be found from the FSx console.

```
  storage:
    ExtraMounts
      - dest: /lustre
        src: <FileSystemId>.fsx.<Region>.amazonaws.com@tcp:/<MountName>
        StorageType: FsxLustre
        FileSystemId: <FileSystemId>
        type: lustre
        options: relatime,flock
```

#### ONTAP

The following example shows how to add an FSx for NetApp ONTAP file system.
The mount information can be found from the FSx console.

```
  storage:
    ExtraMounts
      - dest: /ontap
        src: <SvmId>.<FileSystemId>.fsx.<Region>.amazonaws.com:/vol1
        StorageType: FsxOntap
        FileSystemId: <FileSystemId>
        VolumeId: <VolumeId>
        type: nfs
        options: default
```

#### ZFS

The following example shows how to add an FSx for OpenZFS file system.
The mount information can be found from the FSx console.

```
  storage:
    ExtraMounts
      - dest: /zfs
        src: <FileSystemId>.fsx.<Region>.amazonaws.com:/fsx
        StorageType: FsxOpenZfs
        FileSystemId: <FileSystemId>
        VolumeId: <VolumeId>
        type: nfs
        options: noatime,nfsvers=3,sync,nconnect=16,rsize=1048576,wsize=1048576
```

### Configure Custom Partitions (Optional)

Partitions are automatically created based on spot/on-demand, instance types, and memory and core configuration.
In addition a partition called batch is created that contains all compute nodes.
Another partition called interactive is created that contains all compute nodes that has a higher priority so that its jobs are scheduled before the jobs in the batch queue.

You can create your own custom partitions and specify which compute nodes it uses and what its priority is relative to other partitions.
You do this by using ParallelCluster's [CustomSlurmSettings](https://docs.aws.amazon.com/parallelcluster/latest/ug/Scheduling-v3.html#yaml-Scheduling-SlurmSettings-CustomSlurmSettings).

```
slurm:
  ParallelClusterConfig:
    ClusterConfig:
      Scheduling:
        SlurmSettings:
          CustomSlurmSettings:
            - PartitionName: sim-16-gb
              Default: 'NO'
              PriorityTier: 1
              Nodes: sp-r7i-l-dy-sp-16-gb-1-cores-[1-100],sp-r7a-l-dy-sp-16-gb-2-cores-[1-20]
```

### Configure Custom Head/Compute Node Scripts

ParallelCluster support custom scripts for the head and compute nodes.

#### Head Node Scripts

Custom scripts for the head node are defined in the [CustomActions](https://docs.aws.amazon.com/parallelcluster/latest/ug/HeadNode-v3.html#HeadNode-v3-CustomActions) section of the ParallelCluster configuration.

**NOTE:** The CustomActions cannot be updated once the cluster is created.

```
slurm:
  ParallelClusterConfig:
    ClusterConfig:
      HeadNode:
        CustomActions:
          OnNodeStart:
            Sequence:
              - Script: string
                Args:
                  - string
          OnNodeConfigured:
            Sequence:
              - Script: string
                Args:
                  - string
          OnNodeUpdated:
            Sequence:
              - Script: string
                Args:
                  - string
```

When the cluster is created, the following two scripts are created that you can locally modify on the head node to customize the actions that are taken when the head node is updated.

* /opt/slurm/config/bin/on_head_node_updated_prolog.sh
* /opt/slurm/config/bin/on_head_node_updated_epilog.sh

These scripts are called at the beginning and end of the `on_head_node_updated.sh` script.

#### Compute Node Scripts

If the following scripts exist they will be executed at the beginning and end of the `on_compute_node_configured.sh` script:

* /opt/slurm/config/bin/on_compute_node_configured_custom_prolog.sh
* /opt/slurm/config/bin/on_compute_node_configured_custom_epilog.sh

You can also add additional scripts to all of the ParallelCluster compute nodes that will be prepended to the [CustomActions](https://docs.aws.amazon.com/parallelcluster/latest/ug/Scheduling-v3.html#Scheduling-v3-SlurmQueues-CustomActions) arrays in the ParallelCluster queues.

**NOTE:** Updating these configuration parameters either requires the cluster to be stopped or the QueueUpdateStrategy to be set.

The custom scripts are declared using the following configuration parameters.

```
slurm:
  ParallelClusterConfig:
    ComputeNodeCustomActions:
      OnNodeStart:
        Sequence:
          - Script: string
            Args:
              - string
      OnNodeConfigured:
        Sequence:
          - Script: string
            Args:
              - string
```
