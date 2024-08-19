# Security Groups

This page documents the configuration of security groups that will be used by your clusters.

**Note**: This process has been automated and is described on the [deployment prerequisites page](../deployment-prerequisites#shared-security-groups-for-clusters-and-file-systems).
You can refer to this page to understand the security groups that are created or if you choose to manually create the security groups yourself.

## Security Groups for Login Nodes

We call instances that can connect to the Slurm cluster a login node.
Login nodes can be used to submit and manage jobs.
ParallelCluster can be configured to create login nodes that you must SSH into to use the cluster.
If you want to allow instances like remote desktops to use the cluster directly, you must configure them as login nodes
and give them network permissions to connect to the cluster instances.
You must create three security groups that allow connections between the login node, the Slurm head node, and the Slurm compute nodes.
You will also need to know the security group id for your external Slurmdbd instance, if you have one.

| Security Group Name | Description
|---------------------|-------------
| SlurmLoginNodeSG    | Security group that must be attached to login nodes
| SlurmHeadNodeSG     | Additional security group for head node
| SlurmComputeNodeSG  | Additional security group for compute nodes
| SlurmdbdSG          | (Optional) Existing Slurmdbd security group

First create these security groups without any security group rules.
The reason for this is that the security group rules reference the other security groups so the groups must all exist before any of the rules can be created.
After you have created the security groups then create the rules as described below.

### Slurm Login Node Security Group

The LoginNodeSG will be attached to your login nodes, such as your virtual desktops.

**NOTE**: To make this available to Research and Engineering Studio (RES) so that it can be automatically assigned to virtual desktops, you need to add a tag named **res:Resource** with a value of **vdi-security-group**.
When you create a project, you can select this security group to be added to virtual desktops that use the project.

It needs at least the following inbound rules:

| Type | Port range | Source             | Description | Details
|------|------------|--------------------|------------ |--------
| TCP  | 1024-65535 | SlurmHeadNodeSG    | SlurmHeadNode ephemeral    | Head node can use ephemeral ports to connect to the login node
| TCP  | 1024-65535 | SlurmComputeNodeSG | SlurmComputeNode ephemeral | Compute node will connect to login node using ephemeral ports to manage interactive shells
| TCP  | 6000-7024  | SlurmComputeNodeSG | SlurmComputeNode X11       | Compute node can send X11 traffic to login node for GUI applications

It needs the following outbound rules.

| Type | Port range | Destination        | Description | Details
|------|------------|--------------------|-------------|--------
| TCP  | 2049       | SlurmHeadNodeSG    | SlurmHeadNode NFS       | Mount the slurm NFS file system with binaries and config
| TCP  | 6818       | SlurmComputeNodeSG | SlurmComputeNode slurmd | Connect to compute node for interactive jobs
| TCP  | 6819       | SlurmHeadNodeSG    | SlurmHeadNode slurmdbd  | Connect to slurmdbd (accounting database) daemon on head node for versions before 3.10.0.
| TCP  | 6819       | SlurmdbdSG         | Slurmdbd                | Connect to external Slurmdbd instance. For versions starting in 3.10.0.
| TCP  | 6820-6829  | SlurmHeadNodeSG    | SlurmHeadNode slurmctld
| TCP  | 6830       | SlurmHeadNodeSG    | SlurmHeadNode slurmrestd

### Slurm Head Node Security Group

The SlurmHeadNodeSG will be specified in your configuration file for the slurm/SlurmCtl/AdditionalSecurityGroups parameter.

It needs at least the following inbound rules:

| Type | Port range | Source | Description
|------|------------|--------|------------
| TCP  | 2049       | SlurmLoginNodeSG    | SlurmLoginNode NFS
| TCP  | 6819       | SlurmLoginNodeSG    | SlurmLoginNode slurmdbd. If not using external Slurmdbd.
| TCP  | 6820-6829  | SlurmLoginNodeSG    | SlurmLoginNode slurmctld
| TCP  | 6830       | SlurmLoginNodeSG    | SlurmLoginNode slurmrestd

It needs the following outbound rules.

| Type | Port range | Destination | Description
|------|------------|-------------|------------
| TCP  | 1024-65535 | SlurmLoginNodeSG    | SlurmLoginNode ephemeral

### Slurm Compute Node Security Group

The SlurmComputeNodeSG will be specified in your configuration file for the slurm/InstanceConfig/AdditionalSecurityGroups parameter.

It needs at least the following inbound rules:

| Type | Port range | Source | Description
|------|------------|--------|------------
| TCP  | 6818       | SlurmLoginNodeSG    | SlurmLoginNode slurmd

It needs the following outbound rules.

| Type | Port range | Destination         | Description
|------|------------|---------------------|------------
| TCP  | 2049       | SlurmHeadNodeSG     | SlurmHeadNode NFS       | Mount the slurm NFS file system with binaries and config
| TCP  | 1024-65535 | SlurmLoginNodeSG    | SlurmLoginNode ephemeral
| TCP  | 6000-7024  | SlurmLoginNodeSG    | SlurmLoginNode X11

### External Slurmdbd Security Group

**Note**: ParallelCluster 3.10.0 added support for an external Slurmdbd instance.

The login node must be able to directly access the Slurmdbd instance on port 6819 when running commands like `sacctmgr`.
You must edit the inbound rules of the Slurmdbd instance's security group to allow the access.
Add the following inbound rule.

| Type | Port range | Source | Description
|------|------------|--------|------------
| TCP  | 6819       | SlurmLoginNodeSG | SlurmLoginNode slurmdbd

## Security Groups for File Systems

You will usually have externally created file systems that should be mounted on the compute nodes and login nodes.
You will need to define security groups for the file system network interfaces and modify the Slurm security groups to give them access to the file systems.

### FSx for Lustre Security Group

We'll refer to this group as FSxLustreSG, but you can name it whatever you want.
This security group can either be provided when the file system is created, or can be attached to the network interfaces of the file system after it is created.

The [required security group rules are documented in the FSx documentation](https://docs.aws.amazon.com/fsx/latest/LustreGuide/limit-access-security-groups.html#lustre-client-inbound-outbound-rules).

It needs the following inbound rules.

| Type | Port range | Source             | Description | Details
|------|------------|--------------------|------------ |--------
| TCP  |  988       | FSxLustreSG, SlurmHeadNodeSG, SlurmComputeNodeSG, SlurmLoginNodeSG | Allows Lustre traffic between FSx for Lustre file servers and Lustre clients |
| TCP  | 1018-1023  | FSxLustreSG, SlurmHeadNodeSG, SlurmComputeNodeSG, SlurmLoginNodeSG | Allows Lustre traffic between FSx for Lustre file servers and Lustre clients |

It needs the following outbound rules.

| Type | Port range | Destination        | Description | Details
|------|------------|--------------------|-------------|--------
| TCP  |  988       | FSxLustreSG, SlurmHeadNodeSG, SlurmComputeNodeSG, SlurmLoginNodeSG | Allow Lustre traffic between FSx for Lustre file servers and Lustre clients |
| TCP  | 1018-1023  | FSxLustreSG, SlurmHeadNodeSG, SlurmComputeNodeSG, SlurmLoginNodeSG | Allow Lustre traffic between FSx for Lustre file servers and Lustre clients |

The same inbound and outbound rules need to be added to all 3 of the Slurm security groups too.

## FSx for NetApp Ontap Security Group

We'll refer to this group as FSxOntapSG, but you can name it whatever you want.
This security group can either be provided when the file system is created, or can be attached to the network interfaces of the file system after it is created.

All the [security group rule are documented in the FSx documentation](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/limit-access-security-groups.html#fsx-vpc-security-groups).

The minimum set required for mounting the file system are documented below.

It needs the following inbound rules.

| Type     | Port range  | Source             | Description | Details
|----------|-------------|--------------------|------------ |--------
| TCP, UDP |  111        | SlurmHeadNodeSG, SlurmComputeNodeSG, SlurmLoginNodeSG | | Remote procedure call for NFS
| TCP, UDP |  635        | SlurmHeadNodeSG, SlurmComputeNodeSG, SlurmLoginNodeSG | | NFS mount
| TCP, UDP | 2049        | SlurmHeadNodeSG, SlurmComputeNodeSG, SlurmLoginNodeSG | | NFS server daemon
| TCP, UDP | 4045        | SlurmHeadNodeSG, SlurmComputeNodeSG, SlurmLoginNodeSG | | NFS lock daemon
| TCP, UDP  | 4046        | SlurmHeadNodeSG, SlurmComputeNodeSG, SlurmLoginNodeSG | | Network status monitor for NFS

It needs the following outbound rules.

| Type | Port range | Destination        | Description | Details
|------|------------|--------------------|-------------|--------
| All  |  All       | | |

The Slurm security groups need to add the following outbound rule to allow mounting using NFS.

| Type     | Port range  | Destination        | Description | Details
|----------|-------------|--------------------|-------------|--------
| TCP, UDP |  111        | FSxOntap           |             | Remote procedure call for NFS
| TCP, UDP |  635        | FSxOntap           |             | NFS mount
| TCP, UDP | 2049        | FSxOntap           |             | NFS server daemon
| TCP,UDP | 4045        | FSxOntap           |             | NFS lock daemon
| TCP, UDP | 4046        | FSxOntap           |             | Network status monitor for NFS

## FSx for OpenZFS Security Group

We'll refer to this group as FSxZfsSG, but you can name it whatever you want.
This security group can either be provided when the file system is created, or can be attached to the network interfaces of the file system after it is created.

The [required security group rule are documented in the FSx documentation](https://docs.aws.amazon.com/fsx/latest/OpenZFSGuide/limit-access-security-groups.html).

It needs the following inbound rules.

| Type | Port range | Source             | Description | Details
|------|------------|--------------------|------------ |--------
| TCP, UDP |  111        | SlurmHeadNodeSG, SlurmComputeNodeSG, SlurmLoginNodeSG | | Remote procedure call for NFS
| TCP, UDP | 2049        | SlurmHeadNodeSG, SlurmComputeNodeSG, SlurmLoginNodeSG | | NFS server daemon
| TCP, UDP | 20001-20003 | SlurmHeadNodeSG, SlurmComputeNodeSG, SlurmLoginNodeSG | | NFS mount, status monitor, and lock daemon

Remove all outbound rules.

The Slurm security groups need to add the following outbound rule to allow mounting using NFS.

| Type     | Port range  | Destination        | Description | Details
|----------|-------------|--------------------|-------------|--------
| TCP, UDP |  111        | FSxZfs             |             | Remote procedure call for NFS
| TCP, UDP | 2049        | FSxZfs             |             | NFS server daemon
| TCP, UDP | 20001-20003 | FSxZfs             |             | NFS mount, status monitor, and lock daemon
