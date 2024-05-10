# Deployment Prerequisites

This page shows common prerequisites that need to be done before deployment.

## Deployment Server/Instance Requirements

The deployment process was developed and tested using Amazon Linux 2.
It has also been tested on RHEL 8 and RHEL 9.
An easy way to create a deployment instance is to use an AWS Cloud 9 desktop.
This will give you a code editor IDE and shell environment that you can use to deploy the cluster.

If the required packages aren't installed then you will need sudo or root access on the instance.

## Configure AWS CLI Credentials

You will needs AWS credentials that provide admin access to deploy the cluster.

## Clone or Download the Repository

Clone or download the aws-eda-slurm-cluster repository to your system.

```
git clone git@github.com:aws-samples/aws-eda-slurm-cluster.git
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
$ yum -y install python3.11
$ python3.11 -m venv ~/.venv-python3.11
$ source ~/.venv-python3.11/bin/activate
$ python3 --version
Python 3.11.5
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

Note that CDK requires a pretty new version of nodejs which you may have to download from, for example, [https://nodejs.org/dist/v16.13.1/node-v16.13.1-linux-x64.tar.xz](https://nodejs.org/dist/v16.13.1/node-v16.13.1-linux-x64.tar.xz)

```
sudo yum -y install wget
wget https://nodejs.org/dist/v16.13.1/node-v16.13.1-linux-x64.tar.xz
tar -xf node-v16.13.1-linux-x64.tar.xz ~
```

Add the nodjs bin directory to your path.

[https://docs.aws.amazon.com/cdk/v2/guide/getting_started.html#getting_started_install](https://docs.aws.amazon.com/cdk/v2/guide/getting_started.html#getting_started_install)

Note that the version of aws-cdk changes frequently.
The version that has been tested is in the CDK_VERSION variable in the install script.

The install script will try to install the prerequisites if they aren't already installed.

## Security Groups for Login Nodes

If you want to allow instances like remote desktops to use the cluster directly, you must define
three security groups that allow connections between the instance, the Slurm head node, and the Slurm compute nodes.
We call the instance that is connecting to the Slurm cluster a login node or a submitter instance.

I'll call the three security groups the following names, but they can be whatever you want.

* SlurmSubmitterSG
* SlurmHeadNodeSG
* SlurmComputeNodeSG

### Slurm Submitter Security Group

The SlurmSubmitterSG will be attached to your login nodes, such as your virtual desktops.

It needs at least the following inbound rules:

| Type | Port range | Source | Description
|------|------------|--------|------------
| TCP  | 1024-65535 | SlurmHeadNodeSG    | SlurmHeadNode ephemeral
| TCP  | 1024-65535 | SlurmComputeNodeSG | SlurmComputeNode ephemeral
| TCP  | 6000-7024  | SlurmComputeNodeSG | SlurmComputeNode X11

It needs the following outbound rules.

| Type | Port range | Destination | Description
|------|------------|-------------|------------
| TCP  | 2049       | SlurmHeadNodeSG    | SlurmHeadNode NFS
| TCP  | 6818       | SlurmComputeNodeSG | SlurmComputeNode slurmd
| TCP  | 6819       | SlurmHeadNodeSG    | SlurmHeadNode slurmdbd
| TCP  | 6820-6829  | SlurmHeadNodeSG    | SlurmHeadNode slurmctld
| TCP  | 6830       | SlurmHeadNodeSG    | SlurmHeadNode slurmrestd

### Slurm Head Node Security Group

The SlurmHeadNodeSG will be specified in your configuration file for the slurm/SlurmCtl/AdditionalSecurityGroups parameter.

It needs at least the following inbound rules:

| Type | Port range | Source | Description
|------|------------|--------|------------
| TCP  | 2049       | SlurmSubmitterSG    | SlurmSubmitter NFS
| TCP  | 6819       | SlurmSubmitterSG    | SlurmSubmitter slurmdbd
| TCP  | 6820-6829  | SlurmSubmitterSG    | SlurmSubmitter slurmctld
| TCP  | 6830       | SlurmSubmitterSG    | SlurmSubmitter slurmrestd

It needs the following outbound rules.

| Type | Port range | Destination | Description
|------|------------|-------------|------------
| TCP  | 1024-65535 | SlurmSubmitterSG    | SlurmSubmitter ephemeral

### Slurm Compute Node Security Group

The SlurmComputeNodeSG will be specified in your configuration file for the slurm/InstanceConfig/AdditionalSecurityGroups parameter.

It needs at least the following inbound rules:

| Type | Port range | Source | Description
|------|------------|--------|------------
| TCP  | 6818       | SlurmSubmitterSG    | SlurmSubmitter slurmd

It needs the following outbound rules.

| Type | Port range | Destination | Description
|------|------------|-------------|------------
| TCP  | 1024-65535 | SlurmSubmitterSG    | SlurmSubmitter ephemeral
| TCP  | 6000-7024  | SlurmSubmitterSG    | SlurmSubmitter X11

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
| [StackName](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/cdk/config_schema.py#L366-L367) | The cloudformation stack that will deploy the cluster. |  | None
| [slurm/ClusterName](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/cdk/config_schema.py#L447-L452) | Name of the Slurm cluster | For ParallelCluster shouldn't be the same as StackName | | None
| [Region](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/cdk/config_schema.py#L368-L369) | Region where VPC is located | | `$AWS_DEFAULT_REGION`
| [VpcId](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/cdk/config_schema.py#L372-L373)  | The vpc where the cluster will be deployed. |  vpc-* | None
| [SshKeyPair](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/cdk/config_schema.py#L370-L371) | EC2 Keypair to use for instances | | None
| [ErrorSnsTopicArn](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/cdk/config_schema.py#L379-L380) | ARN of an SNS topic that will be notified of errors | `arn:aws:sns:{{region}}:{AccountId}:{TopicName}` | None
| [slurm/InstanceConfig](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/cdk/config_schema.py#L491-L543) | Configure instance types that the cluster can use and number of nodes. | | See [default_config.yml](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/resources/config/default_config.yml)

### Configure the Compute Instances

The [slurm/InstanceConfig](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/cdk/config_schema.py#L491-L543) configuration parameter configures the base operating systems, CPU architectures, instance families,
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

Licenses are configured using the [slurm/Licenses](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/cdk/config_schema.py#L569-L577) configuration variable.
If you are using the Slurm database then these will be configured in the database.
Otherwises they will be configured in **/opt/slurm/{{ClusterName}}/etc/slurm_licenses.conf**.

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
