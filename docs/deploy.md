# Deploy the Cluster

The original (legacy) version used a custom Slurm plugin for orchestrating the EC2 compute nodes.
The latest version uses ParallelCluster to provision the core Slurm infrastructure.
When using ParallelCluster, a ParallelCluster configuration will be generated and use to create a ParallelCluster slurm cluster.
The first supported ParallelCluster version is 3.6.0.

## Prerequisites

### Configure AWS CLI Credentials

You will needs AWS credentials that provide admin access to deploy the cluster.

### Clone or Download the Repository

Clone or download the aws-eda-slurm-cluster repository to your system.

### Make sure required packages are installed

```
cd aws-eda-slurm-cluster
source setup.sh
```

The setup script assumes that you have sudo access so that you can install or update packages.
If you do not, then contact an administrator to help you do the updates.
If necessary modify the setup script for your environment.

### Create SNS Topic for Error Notifications (Optional but recommended)

The Slurm cluster allows you to specify an SNS notification that will be notified when an error is detected.
You can provide the ARN for the topic in the config file or on the command line.

You can use the SNS notification in various ways.
The simplest is to subscribe your email address to the topic so that you get an email when there is an error.
You could also use it to trigger a CloudWatch alarm that could be used to trigger a lambda to do automatic
remediation or create a support ticket.

## Deploy Using ParallelCluster

### Create ParallelCluster UI

It is highly recommended to create a ParallelCluster UI to manage your ParallelCluster clusters.
A different UI is required for each version of ParallelCluster that you are using.
The versions are list in the [ParallelCluster Release Notes](https://docs.aws.amazon.com/parallelcluster/latest/ug/document_history.html).
The minimum required version is 3.6.0 which adds support for RHEL 8 and increases the number of allows queues and compute resources.
The suggested version is at least 3.7.0 because it adds configurate compute node weights which we use to prioritize the selection of
compute nodes by their cost.

The instructions are in the [ParallelCluster User Guide](https://docs.aws.amazon.com/parallelcluster/latest/ug/install-pcui-v3.html).

### Create ParallelCluster Slurm Database

The Slurm Database is required for configuring Slurm accounts, users, groups, and fair share scheduling.
It you need these and other features then you will need to create ParallelCluster Slurm Database.
Follow the directions in this [ParallelCluster tutorial to configure slurm accounting](https://docs.aws.amazon.com/parallelcluster/latest/ug/tutorials_07_slurm-accounting-v3.html#slurm-accounting-db-stack-v3).

### Configuration File

The first step in deploying your cluster is to create a configuration file.
A default configuration file is found in [source/resources/config/default_config.yml](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/resources/config/default_config.yml).
You should create a new config file and update the parameters for your cluster.

The schema for the config file along with its default values can be found in [source/cdk/config_schema.py](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/cdk/config_schema.py).
The schema is defined in python, but the actual config file should be in yaml format.

The following are key parameters that you will need to update.
If you do not have the required parameters in your config file then the installer script will fail unless you specify the `--prompt` option.
You should save your selections in the config file.

| Parameter                       | Description | Valid Values | Default
|---------------------------------|-------------|--------------|--------
| StackName                       | The cloudformation stack that will deploy the cluster. | | None
| ClusterName                     | Shouldn't be the same as StackName | | None
| Region                          | Region where VPC is located | | `$AWS_DEFAULT_REGION`
| VpcId                           | The vpc where the cluster will be deployed. |  vpc-* | None
| SshKeyPair                      | EC2 Keypair to use for instances | | None
| slurm/SubmitterSecurityGroupIds | Existing security groups that can submit to the cluster. For SOCA this is the ComputeNodeSG* resource. | sg-* | None
| ErrorSnsTopicArn                | ARN of an SNS topic that will be notified of errors | `arn:aws:sns:{{region}}:{AccountId}:{TopicName}` | None

The defaults for the following parameters are generally acceptable, but may be modified based on your requirements.

| Parameter | Description | Valid Values | Default
|-----------|-------------|--------------|--------
| InstanceConfig | Configures the instance families and types that the cluster can use. | | See default_config.yml

### Configure the Compute Instances

The InstanceConfig configuration parameter configures the base operating systems, CPU architectures, instance families,
and instance types that the Slurm cluster should support.
ParallelCluster currently doesn't support heterogeneous cluster;
all nodes must have the same architecture and Base OS.

The supported OSes and CPU architectures are:

| Base OS        | CPU Architectures
|----------------|------------------
| Amazon Linux 2 | x86_64, arm64
| CentOS 7       | x86_64
| RedHat 7       | x86_64
| RedHat 8       | x86_64, arm64

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
Note that instance types and families are python regular expressions.

```
slurm:
  InstanceConfig:
    BaseOsArchitecture:
      CentOS:
        7: [x86_64]
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
    BaseOsArchitecture:
      CentOS:
          7: [x86_64]
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

## Create the Cluster

To install the cluster run the install script. You can override some parameters in the config file
with command line arguments, however it is better to specify all of the parameters in the config file.

```
./install.sh --config-file <config-file> --cdk-cmd create
```

This will create the ParallelCuster configuration file, store it in S3, and use it to create a cluster.


### Customize the compute node AMI

The easiest way to create a custom AMI is to find the default ParallelCluster AMI in the UI.
Create an instance using the AMI and make whatever customizations you require such as installing packages and
configuring users and groups.

Custom file system mounts can be configured in the aws-eda-slurm-cluster config file which will add it to the
ParallelCluster config file so that ParallelCluster can manage them for you.

When you are done create a new AMI and wait for the AMI to become available.
After it is available you can add the custom ami to the aws-eda-slurm-cluster config file.

```
slurm:
  ParallelClusterConfig:
    ComputeNodeAmi: ami-0fdb972bda05d2932
```

Then update your aws-eda-slurm-cluster stack by running the install script again.

## Deploy using legacy cluster

## Subscribe to AWS MarketPlace AMIs (Legacy)

This is only required for the Legacy scheduler. It is not required for ParallelCluster which uses it's own public AMIs.

Subscribe to the MarketPlace AMIs you will use in your cluster.
Examples are:

* [Alma Linux 8 - arm64](https://aws.amazon.com/marketplace/pp/prodview-zgsymdwitnxmm?sr=0-2&ref_=beagle&applicationId=AWS-Marketplace-Console)
* [Alma Linux 8 - x86_64](https://aws.amazon.com/marketplace/pp/prodview-mku4y3g4sjrye?sr=0-1&ref_=beagle&applicationId=AWS-Marketplace-Console)
* [AWS FPGA Developer AMI - CentOS 7 -x86_64](https://aws.amazon.com/marketplace/pp/prodview-gimv3gqbpe57k?sr=0-1&ref_=beagle&applicationId=AWS-Marketplace-Console)
* [AWS FPGA Developer AMI - Amazon Linux 2 - x86_64](https://aws.amazon.com/marketplace/pp/prodview-iehshpgi7hcjg?sr=0-2&ref_=beagle&applicationId=AWS-Marketplace-Console)
* [CentOS 7 - x86_64](https://aws.amazon.com/marketplace/pp/prodview-qkzypm3vjr45g?sr=0-1&ref_=beagle&applicationId=AWS-Marketplace-Console)
* [Rocky Linux 8 - arm64](https://aws.amazon.com/marketplace/pp/prodview-uzg6o44ep3ugw?sr=0-3&ref_=beagle&applicationId=AWS-Marketplace-Console)
* [Rocky Linux 8 - x86_64](https://aws.amazon.com/marketplace/pp/prodview-2otariyxb3mqu?sr=0-1&ref_=beagle&applicationId=AWS-Marketplace-Console)

## Quick Minimal Deployment

The install script can create a minimal Slurm cluster using the default configuration file in the repository and
it will prompt you for the required parameters. You will first need to configure your AWS credentials.
The installer now defaults to using the ParallelCluster version.

```
cd edaslurmcluster
./install.sh --prompt --cdk-cmd create
```

## Install Cloud Development Kit (CDK) (Optional)

The install script will attempt to install all of the prerequisites for you.
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

## Configuration File

The first step in deploying your cluster is to create a configuration file.
A default configuration file is found in [source/resources/config/default_config.yml](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/resources/config/default_config.yml).
You should create a new config file and update the parameters for your cluster.

The schema for the config file along with its default values can be found in [source/cdk/config_schema.py](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/cdk/config_schema.py).
The schema is defined in python, but the actual config file should be in yaml format.

The following are key parameters that you will need to update.
If you do not have the required parameters in your config file then the installer script will fail unless you specify the `--prompt` option.
You should save your selections in the config file.

| Parameter                       | Description | Valid Values | Default
|---------------------------------|-------------|--------------|--------
| StackName                       | The cloudformation stack that will deploy the cluster. | | None
| VpcId                           | The vpc where the cluster will be deployed. |  vpc-* | None
| Region                          | Region where VPC is located | | `$AWS_DEFAULT_REGION`
| SshKeyPair                      | EC2 Keypair to use for instances | | None
| slurm/SubmitterSecurityGroupIds | Existing security groups that can submit to the cluster. For SOCA this is the ComputeNodeSG* resource. | sg-* | None
| ErrorSnsTopicArn                | ARN of an SNS topic that will be notified of errors | `arn:aws:sns:{{region}}:{AccountId}:{TopicName}` | None

The defaults for the following parameters are generally acceptable, but may be modified based on your requirements.

| Parameter | Description | Valid Values | Default
|-----------|-------------|--------------|--------
| slurm/SlurmDbd | Create a slurmdbd instance connected to an RDS Serverless database. | | No database.
| InstanceConfig | Configures the instance families and types that the cluster can use. | | See default_config.yml
| NumberOfControllers | For high availability you can have 2 or 3 controllers. | 1-3 | 1
| SuspendAction | What to do to an idle instance. Stopped instances will restart faster, but still incur EBS charges while stopped. | stop or terminate | stop
| MaxStoppedDuration | You can configure how long instances can be stopped before they are automatically terminated. The default is set to 1 hour. This is checked at least hourly. The format uses the ISO 8601 duration format. | PnYnMnDTnHnMnS | P0Y0M0DT1H0M0S
| CloudWatchPeriod | Default: 5. Set to 1 for finer metric resolution.

## Configure the Compute Instances

The InstanceConfig configuration parameter configures the base operating systems, CPU architectures, instance families,
and instance types that the Slurm cluster should support.
The supported OSes and CPU architectures are:

### ParallelCluster

| Base OS        | CPU Architectures
|----------------|------------------
| Amazon Linux 2 | x86_64, arm64
| CentOS 7       | x86_64
| RedHat 7       | x86_64
| RedHat 8       | x86_64, arm64

### Legacy

| Base OS        | CPU Architectures
|----------------|------------------
| Alma Linux 8   | x86_64, arm64
| Amazon Linux 2 | x86_64, arm64
| CentOS 7       | x86_64
| RedHat 7       | x86_64
| RedHat 8       | x86_64, arm64
| Rocky Linux 8  | x86_64, arm64

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
Note that instance types and families are python regular expressions.

```
slurm:
  InstanceConfig:
    DefaultPartition: CentOS_7_x86_64
    BaseOsArchitecture:
      AlmaLinux:
        8: [x86_64, arm64]
      CentOS:
        7: [x86_64]
      Amazon: {2: [x86_64, arm64]}
      RedHat:
        7: [x86_64]
        8: [x86_64, arm64]
    Include:
      MaxSizeOnly: false
      InstanceFamilies:
        - t3.*
        - t4g
        - m5.*
      InstanceTypes: []
    Exclude:
      InstanceTypes:
        - '.+\.(micro|nano)'    # Not enough memory
        - '.*\.metal'
```

The following InstanceConfig configures instance types recommended for EDA workloads running on CentOS.

```
slurm:
  InstanceConfig:
    DefaultPartition: CentOS_7_x86_64
    BaseOsArchitecture:
      AlmaLinux: {8: [x86_64, arm64]}
      CentOS:
          7: [x86_64]
    Include:
      MaxSizeOnly: false
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
      InstanceTypes: []
    Exclude:
      InstanceTypes:
        - '.*\.metal'
```

If you have reserved instances (RIs) or savings plans then you can configure instances so that they are always on since you are paying for them whether they are running or not.

```
slurm:
  InstanceConfig:
    AlwaysOnNodes:
      - nodename-[0-4]
```

## Update to Latest Base Operating System AMIs (Optional)

The default configuration includes the latest AMIs that have been tested.
If you want to use the latest base OS AMIs, then configure your AWS cli credentials and run the following script.

**Note**: Updating the AMIs to a newer version may break deployment if repositories and package versions have changed from
the tested version.

```
./source/create-ami-map.py > source/resources/config/ami_map.yml
```

## Use Your Own AMIs (Optional)

You may already have base AMIs that are configured for your environment.
To use them update the SlurmNodeAmis configuration parameter.
The parameter is a map with the keys being the region, base OS, and CPU architecture as the keys.
So, for example, to use a custom CentOS 7 AMI in the us-east-1 region you would have:

```
slurm:
  SlurmNodeAmis:
    us-east-1:
      CentOS:
        7:
          x86_64: ami-xxxxxxxxxxxxxxxxx
```

Another example is to use the AWS FPGA Developer AMI as the base AMI for your compute nodes so that you
can use the Xilinx Vivado tools for FPGA development for AWS F1 instances.
By default the EBS volumes are created with the same sizes as in the AMI.
You can increase the size of the root EBS volume as shown in this example.
This is useful if the root volume needs additional space to install additional packages or tools.

```
  SlurmNodeAmis:
    # Customized AMIs with file system mounts, packages, etc. configured.
    BaseAmis:
      us-east-1:
        Amazon: {2: {x86_64: {ImageId: ami-0efdec76678df9a64, RootDeviceSize: '+5'}}}
        CentOS: {7: {x86_64: {ImageId: ami-02155c6289e76719a, RootDeviceSize: '+5'}}}
```

## Configure Fair Share Scheduling (Optional)

Slurm supports [fair share scheduling](https://slurm.schedmd.com/fair_tree.html), but it requires the fair share policy to be configured.
By default, all users will be put into a default group that has a low fair share.
The configuration file is at [source/resources/playbooks/roles/SlurmCtl/templates/opt/slurm/cluster/etc/accounts.yml.example](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/resources/playbooks/roles/SlurmCtl/templates/opt/slurm/cluster/etc/accounts.yml.example)
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

## Configure Licenses

Slurm supports [configuring licenses as a consumable resource](https://slurm.schedmd.com/licenses.html).
It will keep track of how many running jobs are using a license and when no more licenses are available
then jobs will stay pending in the queue until a job completes and frees up a license.
Combined with the fairshare algorithm, this can prevent users from monopolizing licenses and preventing others from
being able to run their jobs.

The configuration file is at [source/resources/playbooks/roles/SlurmCtl/templates/tools/slurm/etc/slurm_licenses.conf.example](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/resources/playbooks/roles/SlurmCtl/templates/opt/slurm/cluster/etc/slurm_licenses.conf.example)
in the repository and is deployed to **/opt/slurm/{{ClusterName}}/conf/accounts.yml**.

The example configuration shows how the number of licenses can be configured as just a comma separated list.
In this example, the cluster will manage 800 vcs licenses and 1 ansys license.
Users must request a license using the **-L** or **--licenses** options.

```
Licenses=vcs:800,ansys:1
```

## Create the Cluster

To install the cluster run the install script. You can override some parameters in the config file
with command line arguments, however it is better to specify all of the parameters in the config file.

```
./install.sh --config-file <config-file> --stack-name <stack-name> --cdk-cmd create
```

## Create Custom ParallelCluster AMI

The ParallelCluster User Guide has [instructions for customizing the AMI](https://docs.aws.amazon.com/parallelcluster/latest/ug/custom-ami-v3.html) used by compute nodes.

## Use the Cluster

Configuring your environment for users requires root privileges.
The configuration commands are found in the outputs of the Slurm cloudformation stack.

### Configure Slurm Users and Groups

The Slurm cluster needs to configure the users and groups of your environment.
For efficiency, it does this by capturing the users and groups from your environment
and saves them in a json file.
When the compute nodes start they create local unix users and groups using this json file.

Choose a single instance in your VPC that will always be running and that is joined to a domain
so that it can list all users and groups.
For SOCA this would be the Scheduler instance.
Connect to that instance and run the commands in the **MountCommand** and **ConfigureSyncSlurmUsersGroups** outputs
of the Slurm stack.
These commands will mount the Slurm file system at **/opt/slurm/{{ClusterName}}** and then create
a cron job that runs every 5 minutes and updates **/opt/slurm/{{ClusterName}}/config/users_groups.json**.

### Configure Slurm Submitter Instances

Instances that need to submit to Slurm need to have their security group IDs in the **SubmitterSecurityGroupIds** configuration parameter
so that the security groups allow communication between the submitter instances and the Slurm cluster.
They also need to be configured by mounting the file system with the Slurm tools and
configuring their environment.
Connect to the submitter instance and run the commands in the **MountCommand** and **ConfigureSubmitterCommand** outputs
of the Slurm stack.
If all users need to use the cluster then it is probably best to create a custom AMI that is configured with the configuration
commands.

### Run Your First Job

Run the following command in a shell to configure your environment to use your slurm cluster.

```
module load {{ClusterName}}
```

To submit a job run the following command.

```
sbatch /opt/slurm/$SLURM_CLUSTER_NAME/test/job_simple_array.sh
```

To check the status run the following command.

```
squeue
```

To open an interactive shell on a slurm node.

```
srun --pty /bin/bash
```

## Slurm Documentation

[https://slurm.schedmd.com](https://slurm.schedmd.com)
