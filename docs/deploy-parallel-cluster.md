# Deploy AWS ParallelCluster

A ParallelCluster configuration will be generated and used to create a ParallelCluster slurm cluster.
The first supported ParallelCluster version is 3.6.0.
Version 3.7.0 is the recommended minimum version because it supports compute node weighting that is proportional to instance type
cost so that the least expensive instance types that meet job requirements are used.
The current latest version is 3.9.1.

## Prerequisites

See [Deployment Prerequisites](deployment-prerequisites.md) page.

## Create the Cluster

To install the cluster run the install script. You can override some parameters in the config file
with command line arguments, however it is better to specify all of the parameters in the config file.

```
./install.sh --config-file <config-file> --cdk-cmd create
```

This will create the ParallelCuster configuration file, store it in S3, and then use a lambda function to create the cluster.

If you look in CloudFormation you will see 2 new stacks when deployment is finished.
The first is the configuration stack and the second is the cluster.

## Create users_groups.json

**NOTE**: If you are using RES and specify RESEnvironmentName in your configuration, these steps will automatically be done for you.

Before you can use the cluster you must configure the Linux users and groups for the head and compute nodes.
One way to do that would be to join the cluster to your domain.
But joining each compute node to a domain effectively creates a distributed denial of service (DDOS) attack on the demain controller
when the cluster rapidly scales out or in and each node tries to join or leave the domain.
This can lead to domain controller timeouts and widespread havoc in your environment.

To solve this problem a script runs on a server that is joined to the domain which writes a JSON file with all
of the non-privileged users and groups and their respective uids and gids.
A script and cron job on the head and compute nodes reads this json file to create local users and groups that match the domain-joined servers.

Select the server that you want to use to create and update the JSON file.
The outputs of the configuration stack have the commands required.

| Config Stack Output                     | Description
|-----------------------------------------|------------------
| Command01_MountHeadNodeNfs              | Mounts the Slurm cluster's shared file system at /opt/slurm/{{ClusterName}}. This provides access to the configuration script used in the next step.
| Command02_CreateUsersGroupsJsonConfigure | Create /opt/slurm/{{ClusterName}}/config/users_groups.json and create a cron job to refresh it hourly. Update /etc/fstab with the mount in the previous step.

Before deleting the cluster you can undo the configuration by running the commands in the following outputs.

| Config Stack Output                       | Description
|-------------------------------------------|------------------
| command10_CreateUsersGroupsJsonDeconfigure | Removes the crontab that refreshes users_groups.json.

Now the cluster is ready to be used by sshing into the head node or a login node, if you configured one.

If you configured extra file systems for the cluster that contain the users' home directories, then they should be able to ssh
in with their own ssh keys.

## Configure submission hosts to use the cluster

**NOTE**: If you are using RES and specify RESEnvironmentName in your configuration, these steps will automatically be done for you on all running DCV desktops.

ParallelCluster was built assuming that users would ssh into the head node or login nodes to execute Slurm commands.
This can be undesirable for a number of reasons.
First, users shouldn't be given ssh access to a critical infrastructure like the cluster head node.
With ParallelCluster 3.7.0 you can configure login nodes, but if you have already provisioned desktop nodes then
it's wasteful to have to provision login nodes.
Second, it's just inconvenient to have to use ssh to access the cluster and use it.

Fortunately, you can configure any server as a submission host so that users can run slurm commands.
These commands must be run by an administrator that has root access to the submission host.
The commands could also be run to create a custom AMI for user desktops so that they can access the clusters.
The commands to configure submission hosts are in the outputs of the configuration CloudFormation stack.
Run them in the following order:

| Config Stack Output                     | Description
|-----------------------------------------|------------------
| Command01_MountHeadNodeNfs              | Mounts the Slurm cluster's shared file system at /opt/slurm/{{ClusterName}}. This provides access to the configuration script used in the next step.
| Command03_SubmitterConfigure            | Configure the submission host so it can directly access the Slurm cluster.  Update /etc/fstab with the mount in the previous step.

The first command simply mounts the head node's NFS file system so you have access to the Slurm commands and configuration.

The second command runs an ansible playbook that configures the submission host so that it can run the Slurm commands for the cluster.
It will also compile the Slurm binaries for the OS distribution and CPU architecture of your host.
It also configures the modulefile that sets up the environment to use the slurm cluster.

**NOTE**: When the new modulefile is created, you need to refresh your shell environment before the modulefile
can be used.
You can do this by opening a new shell or by sourcing your .profile: `source ~/.profile`.

The clusters have been configured so that a submission host can use more than one cluster by simply changing the modulefile that is loaded.

On the submission host just open a new shell and load the modulefile for your cluster and you can access Slurm.

## Customize the compute node AMI

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

## Run Your First Job

Run the following command in a shell to configure your environment to use your slurm cluster.

**NOTE**: When the new modulefile is created, you need to refresh your shell environment before the modulefile
can be used.
You can do this by opening a new shell or by sourcing your profile: `source ~/.bash_profile`.

```
module load {{ClusterName}}
```

If you want to get a list of all of the clusters that are available execute the following command.

```
module avail
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
