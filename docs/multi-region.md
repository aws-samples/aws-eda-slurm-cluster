# Multi-AZ and Multi-Region Support (legacy)

By default, the EDA Slurm Cluster deploys all resources in a single availability zone (AZ).
This is done for performance and cost reasons to minimize network latency and network cross AZ charges.
Very large clusters may hit capacity constraints in a single AZ and can benefit from being able to launch compute nodes in multiple AZs and even multiple
regions to get the required capacity.
For this reason, the cluster can support compute nodes in multiple AZ and regions.

All compute nodes are managed by one Slurm controller and the compute nodes encode the region and AZ in their node names.
When a job gets scheduled on a compute node, the Slurm plugin runs an instance in the region and AZ encoded in the node name.
Compute nodes in each AZ are grouped in partitions that can be given priorities.
This allows a job submission to specify multiple partitions and the scheduler will choose available compute nodes from the highest priority partition.

**NOTE**: This is an advanced topic with significant configuration complexity so it is recommended that you get guidance
from and AWS specialist to help you set up your configuration.
This page documents a simple setup which is unlikely to meet your file system performance goals without modification.

## Requirements

There are three primary requirements for multi-AZ/region support: 1) networking, 2) file systems and 3) DNS.

### Networking

The main networking requirement is that each region must have a VPC with a subnet in each AZ.
The CIDR ranges of the VPC must be non-overlapping.
The VPCs must connected using VPC Peering Connections or Transit Gateways and the routes and ACLs must be configured to allow communication between all of the VPCs.
The compute nodes use all the ephemeral ports so those ports must be routed between the VPCs.

### File Systems

The compute nodes must have the same logical view of the file systems.
All paths used by the compute nodes must be available in each AZ and region.
One way to accomplish this is to simply mount the exact same file systems on all compute nodes.
This has the advantage of simplicity, however, it will incur performance penalties because of increased network latency and network charges
because of cross-AZ and cross-Region network charges.

The slurm file system is not performance critical and can be cross mounted.

Performance critical file systems can be replicated across AZs and regions and and automatically synchronized using FSx for NetApp Ontap (FSxN) and FlexCache or SnapMirror.
FlexCache is particularly efficient because it is a sparse cache that only synchronizes data when it it accessed.
This means that not all of the data has to be replicated anywhere.
If you replicate file systems then it means that your machine images will need to be configured to mount the closest file system.
This could be done at boot time by using SSM parameters or by using location specific automount maps.
Currently Route53 doesn't support a policy that allows you to choose an AZ dependent domain resolution.
This is an advanced topic and we recommend that you consult with an AWS storage specialist to help you architect a storage solution
that will meet your performance needs.

### DNS

The cluster creates a Route53 private hosted zone or can use an existing one to get the IP addresses for the Slurm controllers and slurmdbd instances.
It uses the AWS provided DNS in the VPC to get the IP addresses of AWS managed file systems.
All of the VPCs need access to all of the DNS entries used by the Slurm instances.

## Configuration

This example is going to demonstrate how to configure a cluster that spans 3 AZs in 3 regions for a total of 9 AZs.
It is going to use a very simple file system topology with all of the file systems located in the primary AZ.

### Create VPCs

In this example I deployed 3 Scale Out Computing on AWS (SOCA) clusters in eu-west-1, us-east-1, and us-west-2 with non-overlapping CIDRs.
This created 3 VPCs each with 3 private subnets.

| Region    | SOCA Cluster | CIDR |
|-----------|--------------|------|
| eu-west-1 | oktank-dub   | 10.1.0.0/16 |
| us-east-1 | oktank-iad   | 10.2.0.0/16 |
| us-west-2 | oktank-pdx   | 10.3.0.0/16 |

I am going to create a multi-region Slurm cluster in eu-west-1 that can run compute nodes in all 3 regions with the priority of the regions being

1. eu-west-1 (dub)
1. us-east-1 (iad)
1. us-west-2 (pdx)

If you have a globally distributed team you could modify the instructions to use regions close to your global team and deploy a cluster in the
local region of each team that they can use that can run jobs in all of the regions.

### Connect the VPCs using VPC Peering Connections

1. Go to the VPC console in eu-west-1 and select **Peering connections** on the left.
1. Click on **Create peering connection** on the upper right
1. Name the connection dub-to-iad
1. For the local VPC select the SOCA VPC
1. For the other VPC's region select **Another Region**
1. Select us-east-1
1. Open the us-east-1 VPC console in another tab and copy the SOCA vpc id
1. Go back to the eu-west-1 VPC console and paste the vpc id into the **VPC ID (Accepter) field
1. Click **Create peering connection** to create the connection.
1. Go back to the us-east-1 console and select **Peering connections** on the left.
1. Select the connection you just created. It should be in **Pending acceptance** state.
1. Select **Actions** and **Accept request**

Repeat the same steps to create VPC peering connections between eu-west-1 (dub) and us-west-2 (pdx) and between
us-east-1 (iad) and us-west-2 (pdx).
When you are complete all of the VPCs will have a connection to the others.

The next step is to set up routing table entries to route the traffic between the VPCs over the peering connections.
Do the following steps in each region.

1. Open the VPC console
1. Select **Route tables** on the left
1. Select the route table for each of the 3 private subnets
1. Click **Edit routes**
1. Click **Add route**
1. Enter the CIDR range for another VPC in the destination and the peering connection to that VPC (start typing pcx- and then select from the list)
1. Click **Save changes**

When this is done packets from each VPC to any other will be routed across the appropriate VPC peering connection.

## DNS: Route53 Private Hosted Zone

The oktank-dub SOCA cluster has two EFS file systems mounted at /apps and /data that contain the home and tools directories for the user's desktops.
We are enabling the SOCA users to submit jobs to Slurm so those volumes will need to be available on all compute nodes.
However, the EFS DNS name will only able to be resolved by the AWS provided DNS server in the oktank-dub VPC.
We could just use the IP address, but it is more maintainable to create a Route53 private hosted zone that is shared
by all of the clusters so that we can refer the the EFS file systems with a friendly DNS name.

**Note** that Route53 is a global, not regional, service.

1. Open the Route53 console
1. Select Hosted zones on the left
1. Click **Create hosted zone** in the upper right
1. Enter a domain name like slurmdub.local
1. For Type select **Private hosted zone**
1. Associate the oktank-dub VPC with the hosted zone.
   1. For Region select eu-west-1
   1. Click the VPC ID and select the SOCA VPC
1. Associate the oktank-iad VPC with the hosted zone.
   1. Click **Add VPC**
   1. For Region select eu-west-1
   1. Click the VPC ID and select the SOCA VPC
1. Associate the oktank-pdx VPC with the hosted zone.
   1. Click **Add VPC**
   1. For Region select eu-west-1
   1. Click the VPC ID and select the SOCA VPC
1. Click **Create hosted zone**
1. Expand **Hosted zone details** and save the **Hosted zone ID** which will be used in the config file.

Create DNS entries for the SOCA EFS file systems.

1. Open the EFS console in eu-west-1
1. Select the Apps file system
1. Select the Network tab and note the IP addresses for all 3 availability zones.
1. Repeat to get the IP addresses for the Data file system.
1. Open the Route53 console and select the slurmdub.local hosted zone.
1. Click **Create record**
1. Name it fs-apps
1. For record type select **A**
1. For **Value** put the 3 IP addresses for the EFS file system on separate lines
1. For **Routing policy** select **latency**
1. For **Region** select eu-west-1
1. For **Record ID** enter **fs-apps-dub**
1. Create idential A records for fs-apps in the us-east-1 and us-west-2 regions with **Record ID** of fs-apps-iad and fs-apps-pdx.
1. Repeat for the Data file system and create fs-data A records in all 3 regions.

## File System Access

Make sure that file system security groups allow access from all slurm VPCs.

You may need to allow inbound access from 10.2.0.0/16 and 10.3.0.0/16.

## Slurm Configuration

The following configuration file configures all three regions.
Note that there are values for key pairs, VPC IDs, subnet IDs, etc. that you will have to update with the information from
your SOCA clusters.

Regional resources that must be provided:
* VPC IDs
* VPC CIDRs
* Subnet IDs
* EC2 Keypairs
* Security Group IDs

Regional resources that will be created for you:
* ComputeNodeSecurityGroup

Global resources that will be created for you:
* IAM instance roles

slurm_dub.yml:

```
---
# Multi-region Slurm cluster with Netapp Ontap
#
# Origin of the cluster is in eu-west-1 and extends into us-east-1 and us-west-2

StackName: slurmdub

Region: eu-west-1

SshKeyPair: admin-eu-west-1 # Or whatever Key Pair you've created

VpcId: vpc-xxxxxxxxxxxxxxxxx # oktank-dub

SubnetId: subnet-xxxxxxxxxxxxxxxxx # oktank-dub, PrivateSubnet1

HostedZoneId: XXXXXXXXXXXXXXXXXXX # The hosted zone ID for the hosted zone you created above.

ErrorSnsTopicArn: arn:aws:sns:eu-west-1:${AccountId}:SlurmError # ARN of your SNS topic.

TimeZone: 'US/Central' # Or whatever you prefer

slurm:
  MungeKeySsmParameter: "/slurm/munge_key"

  SlurmCtl:
    NumberOfControllers: 2

  SlurmDbd: {}

  # External security groups that should be able to use the cluster
  SubmitterSecurityGroupIds:
    soca-oktank-dub-ComputeNodeSG: sg-xxxxxxxxxxxxxxxxx

  SubmitterInstanceTags:
    'soca:ClusterId': ['soca-oktank-dub']

  # InstanceConfig:
  # Configure the instances used by the cluster
  # A partition will be created for each combination of Base OS, Architecture, and Spot
  InstanceConfig:
    UseSpot: true
    NodesPerInstanceType: 10
    BaseOsArchitecture:
      AlmaLinux: {8: [x86_64, arm64]}
      CentOS:
        7: [x86_64]
    Include:
      MaxSizeOnly: false
      InstanceFamilies:
        - t3
        - t4g
      InstanceTypes: []
    Exclude:
      InstanceFamilies: []
      InstanceTypes:
        - '.+\.(micro|nano)'   # Not enough memory
        - '.*\.metal'
    Regions:
      eu-west-1:
        VpcId: vpc-xxxxxxxxxxxxxxxxx # oktank-dub
        CIDR: 10.1.0.0/16
        SshKeyPair: admin-eu-west-1
        AZs:
          - Priority: 10
            Subnet: subnet-xxxxxxxxxxxxxxxxx # oktank-dub - PrivateSubnet1
          - Priority: 9
            Subnet: subnet-xxxxxxxxxxxxxxxxx # oktank-dub - PrivateSubnet2
          - Priority: 8
            Subnet: subnet-xxxxxxxxxxxxxxxxx # oktank-dub - PrivateSubnet3
      us-east-1:
        VpcId: vpc-xxxxxxxxxxxxxxxxx
        CIDR: 10.2.0.0/16
        SshKeyPair: admin-us-east-1
        AZs:
          - Priority: 7
            Subnet: subnet-xxxxxxxxxxxxxxxxx # oktank-iad - PrivateSubnet1
          - Priority: 6
            Subnet: subnet-xxxxxxxxxxxxxxxxx # oktank-iad - PrivateSubnet2
          - Priority: 5
            Subnet: subnet-xxxxxxxxxxxxxxxxx # oktank-iad - PrivateSubnet3
      us-west-2:
        VpcId: vpc-xxxxxxxxxxxxxxxxx
        CIDR: 10.3.0.0/16
        SshKeyPair: admin-us-west-2
        AZs:
          - Priority: 4
            Subnet: subnet-xxxxxxxxxxxxxxxxx # oktank-pdx - PrivateSubnet1
          - Priority: 3
            Subnet: subnet-xxxxxxxxxxxxxxxxx # oktank-pdx - PrivateSubnet2
          - Priority: 2
            Subnet: subnet-xxxxxxxxxxxxxxxxx # oktank-pdx - PrivateSubnet3

  storage:
    provider: ontap
    removal_policy: DESTROY
    ontap: {}

    ExtraMounts:
      - dest: /apps
        src: fs-apps.slurmdub.local:/
        type: nfs4
        options: nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2,noresvport
      - dest: /data
        src: fs-data.slurmdub.local:/
        type: nfs4
        options: nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2,noresvport
```

## Deployment

After the configuration is complete then deployment is the same as document on the [Deploy the Legacy Cluster](deploy-legacy-cluster.md) page.
