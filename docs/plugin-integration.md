# Plugin Integration Into Existing Slurm Cluster (legacy)

If you have an existing Slurm cluster and want to enable it to scale into AWS then you can integrate
the `SlurmPlugin.py` into your existing cluster.
The plugin implements the Slurm power saving API scripts so the integration is as simple
as copying the plugin and it's scripts into your file system and then modifying your slurm configuration to use them.

## Network Requirements

The instructions for integrating the AWS cluster with on-premises compute nodes contains the [network requirements](/onprem/#network-requirements).

The VPC's DNS must be configured so that it can resolve the on-prem hostnames such as the slurm controller and file systems.

## File System Requirements

The compute nodes in the AWS VPC will need access to the same file systems paths as your existing compute nodes.
This can easily be accomplished by mounting your on-prem file systems across the VPN of Direct Connect connection, but
that will likely have significant latency and performance impacts.
If your on-prem file systems are NetApp Ontap then you can create [Amazon FSx for NetApp Ontap](https://aws.amazon.com/fsx/netapp-ontap/)
file systems configured with FlexCache volumes to provide low latency, high performance caches of your on-prem file systems on AWS.
If you do not use NetApp then you can use [Amazon File Cache](https://aws.amazon.com/filecache/) to create high performance
file caches of your on-prem file systems.

## Create AWS Slurm Cluster

The plugin requires a number of configuration files as well as AWS resources for the compute nodes such as Amazon Machine Images (AMIs),
IAM instance roles, and security groups.
The easiest way to create all of the required resources is to follow the [instructions to deploy a cluster with on-premises compute nodes](/onprem)
into your AWS VPC and then use those resources to configure your existing cluster.
Note that `slurm_nodes_on_prem.conf` can be empty and doesn't have to include any on-prem compute nodes.
The configuration file should include the file systems that should be mounted on the AWS compute nodes.


After you've deployed the AWS cluster,
Mount the slurm file system on your slurm controller at

<pre>/opt/slurm/<b><i>cluster-name</i></b></pre>

## AWS Credentials

The power saving scripts run as the `slurm` user on your slurm controller and require AWS IAM permissions
to orchestrate AWS instances for your Slurm cluster.
Specifically, the slurm controller needs access to the AMIs and permission to start, stop, and terminate EC2 instances.
The permissions are defined in the SlurmCtlPolicy resource of the cluster's Cloudformation stack.
You can create a `slurm` IAM user and attach the SlurmCtlPolicy.
Then you can create IAM credentials for the `slurm` user and save them on the slurm controller using `aws config`.

## Amazon Machine Images for Compute Nodes

You can modify the AMIs created by the AWS slurm cluster for use by your on-prem cluster.

## SSM Parameter Store Variables

The plugin reads serveral SSM parameters to get information that it needs to orchestrate instances.

| SSM Parameter | Description
|---------------|-------------
| <pre>/<b><i>cluster-name</i></b>/SlurmNodeAmi/<b><i>os-distribution</i></b>/<b><i>os-major-version</i></b>/<b><i>architecture</i></b>/<b><i>region</i></b></pre> | AMIs for AWS EC2 compute nodes
| <pre>/<b><i>cluster-name</i></b>/SlurmNodeEc2KeyPairs/<b><i>region</i></b></pre> | EC2 Keypairs for each region
| <pre>/<b><i>cluster-name</i></b>/SlurmNodeSecurityGroups/<b><i>region</i></b></pre> | Security groups for AWS EC2 compute nodes

| Field | Valid Values
|-------|-------------
| os-distribution | AlmaLinux \| Amazon \| CentOS \| RedHat \| Rocky
| architecture | arm64 \| x86_64


## Slurm Configuration

The existing slurm cluster's configuration file will need to be updated to to configure the AWS compute nodes
and to use the `SlurmPlugin.py`.

Update your `slurm.conf` based on `/opt/slurm/slurmaws/etc/slurm.conf`.
At a minimum you will need to add the following lines.

```
# CommunicationParameters:
# NoAddrCache: Do not assume that nodes will retain their IP addresses. Do not cache node->ip mapping
CommunicationParameters = NoAddrCache

# ReturnToService
# 0: Make node available if it registers with a valid configuration regardless of why it is down.
# 1: Only return to service if DOWN due to being non-responsive.
# 2: A DOWN node will become available for use upon registration with a valid configuration.
ReturnToService=2

# TreeWidth is set to the maximum for cloud clusters so messages go directly between controller and nodes.
# https://slurm.schedmd.com/elastic_computing.html
TreeWidth = 65533

#
# SlurmctldParameters
# cloud_dns: Do not set cloud_dns unless joining the domain and adding nodes to DNS
#     Joining the domain overloads the DCs when lots of nodes are started so
#     not joining the domain or using cloud_dns.
# idle_on_node_suspend: Mark nodes as idle, regardless of current state, when suspending
#     nodes with SuspendProgram so that nodes will be eligible to be resumed at a later time.
# node_reg_mem_percent: Percentage of memory a node is allowed to register with without being marked as invalid with low memory.
#     Use this so can configure nodes with 100% of their memory.
#     Without this option the node will fail because the system uses some of the memory.
SlurmctldParameters=\
idle_on_node_suspend,\
,node_reg_mem_percent=90
#
# Allow users to see state of nodes that are powered down
PrivateData = cloud

#
# POWER SAVE SUPPORT FOR IDLE NODES
#
SuspendProgram = /opt/slurm/slurmaws/bin/slurm_ec2_stop.py
ResumeProgram = /opt/slurm/slurmaws/bin/slurm_ec2_resume.py
ResumeFailProgram = /opt/slurm/slurmaws/bin/slurm_ec2_resume_fail.py
# Maximum time between when a node is suspended and when suspend is complete.
# At that time it should be ready to be resumed.
SuspendTimeout = 60
ResumeTimeout = 600
# Number of nodes per minute that can be resumed or suspended
ResumeRate = 300
SuspendRate = 60
# Time that a node has to be idle or down before being suspended
# Should be >= (SuspendTimeout + ResumeTimeout)
SuspendTime = 660

include /opt/slurm/slurmaws/etc/slurm_nodes.conf
```
