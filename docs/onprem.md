# On-Premises Integration

The slurm cluster can also be configured to manage on-premises compute nodes.
The user must configure the on-premises compute nodes and then give the configuration information.

## On-Premises Network and Compute Nodes

The on-prem network must have a CIDR range that doesn't overlap the Slurm cluster's VPC and the two networks
need to be connected using VPN or AWS Direct Connect.
The on-prem firewall must allow ingress and egress from the VPC.
The ports are used to connect to the file systems, slurm controllers, and allow traffic between virtual desktops and compute nodes.

Local network DNS must have an entry for the slurm controller or have a forwarding rule to the AWS provided DNS in the Slurm VPC.

All of the compute nodes in the cluster, including the on-prem nodes, must have file system mounts that replicate the same directory structure.
This can involve mounting filesystems across VPN or Direct Connect or synchronizing file systems using tools like rsync or NetApp FlexCache or SnapMirror.
Performance will dictate the architecture of the file system.

## Slurm Configuration of On-Premises Compute Nodes

The slurm cluster's configuration file allows the configuration of on-premises compute nodes.
The Slurm cluster will not provision any of the on-prem nodes, network, or firewall, but it will configure
the cluster's resources to be used by the on-prem nodes.
All that needs to be configured are the configuration file for the on-prem nodes and the CIDR block.

```
  InstanceConfig:
    UseSpot: true
    DefaultPartition: CentOS_7_x86_64_spot
    NodesPerInstanceType: 10
    BaseOsArchitecture:
      CentOS: {7: [x86_64]}
    Include:
      MaxSizeOnly: false
      InstanceFamilies:
        - t3
      InstanceTypes: []
    Exclude:
      InstanceFamilies: []
      InstanceTypes:
        - '.+\.(micro|nano)'   # Not enough memory
        - '.*\.metal'
    OnPremComputeNodes:
      ConfigFile: 'slurm_nodes_on_prem.conf'
      CIDR: '10.1.0.0/16'
```

`slurm_nodes_on_prem.conf`

```
#
# ON PREMISES COMPUTE NODES
#
# Config file with list of statically provisioned on-premises compute nodes that
# are managed by this cluster.
#
# These nodes must be addressable on the network and firewalls must allow access on all ports
# required by slurm.
#
# The compute nodes must have mounts that mirror the compute cluster including mounting the slurm file system
# or a mirror of it.
NodeName=Default State=DOWN

NodeName=onprem-c7-x86-t3-2xl-0 NodeAddr=onprem-c7-x86-t3-2xl-0.onprem.com  CPUs=4  RealMemory=30512   Feature=c7,CentOS_7_x86_64,x86_64,GHz:2.5 Weight=1
NodeName=onprem-c7-x86-t3-2xl-1 NodeAddr=onprem-c7-x86-t3-2xl-1.onprem.com  CPUs=4  RealMemory=30512   Feature=c7,CentOS_7_x86_64,x86_64,GHz:2.5 Weight=1
NodeName=onprem-c7-x86-t3-2xl-2 NodeAddr=onprem-c7-x86-t3-2xl-2.onprem.com  CPUs=4  RealMemory=30512   Feature=c7,CentOS_7_x86_64,x86_64,GHz:2.5 Weight=1
NodeName=onprem-c7-x86-t3-2xl-3 NodeAddr=onprem-c7-x86-t3-2xl-3.onprem.com  CPUs=4  RealMemory=30512   Feature=c7,CentOS_7_x86_64,x86_64,GHz:2.5 Weight=1
NodeName=onprem-c7-x86-t3-2xl-4 NodeAddr=onprem-c7-x86-t3-2xl-4.onprem.com  CPUs=4  RealMemory=30512   Feature=c7,CentOS_7_x86_64,x86_64,GHz:2.5 Weight=1
NodeName=onprem-c7-x86-t3-2xl-5 NodeAddr=onprem-c7-x86-t3-2xl-5.onprem.com  CPUs=4  RealMemory=30512   Feature=c7,CentOS_7_x86_64,x86_64,GHz:2.5 Weight=1
NodeName=onprem-c7-x86-t3-2xl-6 NodeAddr=onprem-c7-x86-t3-2xl-6.onprem.com  CPUs=4  RealMemory=30512   Feature=c7,CentOS_7_x86_64,x86_64,GHz:2.5 Weight=1
NodeName=onprem-c7-x86-t3-2xl-7 NodeAddr=onprem-c7-x86-t3-2xl-7.onprem.com  CPUs=4  RealMemory=30512   Feature=c7,CentOS_7_x86_64,x86_64,GHz:2.5 Weight=1
NodeName=onprem-c7-x86-t3-2xl-8 NodeAddr=onprem-c7-x86-t3-2xl-8.onprem.com  CPUs=4  RealMemory=30512   Feature=c7,CentOS_7_x86_64,x86_64,GHz:2.5 Weight=1
NodeName=onprem-c7-x86-t3-2xl-9 NodeAddr=onprem-c7-x86-t3-2xl-9.onprem.com  CPUs=4  RealMemory=30512   Feature=c7,CentOS_7_x86_64,x86_64,GHz:2.5 Weight=1

#
#
# OnPrem Partition
#
# The is the default partition and includes all nodes from the 1st OS.
#
PartitionName=onprem Default=YES PriorityTier=20000 Nodes=\
onprem-c7-x86-t3-2xl-[0-9]

#
# Always on partitions
#
SuspendExcParts=onprem

```

## Simulating an On-Premises Network Using AWS

Create a new VPC with public and private subnets and NAT gateways.
To simulate the latency between an AWS region and on-prem you can create the VPC in a different region in your account.
The CIDR must not overlap with the Slurm VPC.

Create a VPC peering connection to your Slurm VPC and accept the connection in the Slurm VPC.
Create routes in the private subnets for the CIDR of the peered VPC and route it to the vpc peering connection.

Add the on-prem VPC to the Slurm VPC's Route53 private local zone.

Create a Route53 private hosted zone for the on-prem compute nodes and add it to the onprem VPC and the slurm VPC so that onprem compute nodes
can be resolved.

Copy the Slurm AMIs to the region of the on-prem VPC.
Create an instance using the copied AMI.
Connect to the instance and confirm that the mount points mounted correctly.
You will probably have to change the DNS names for the file systems to IP addresses.
I created A records in the Route53 zone for the file systems so that if the IP addresses ever change in the future I can easily update them in one place without having to create a new AMI or updated any instances.
Create a new AMI from the instance.

Create compute node instances from the new AMI and run the following commands on them get the slurmd daemon running so
they can join the slurm cluster.

```
# Instance specific variables
hostname=onprem-c7-x86-t3-2xl-0

# Domain specific variables
onprem_domain=onprem.com

source /etc/profile.d/instance_vars.sh

# munge needs to be running before calling scontrol
/usr/bin/cp /opt/slurm/$ClusterName/config/munge.key /etc/munge/munge.key
systemctl enable munged
systemctl start munged

ipaddress=$(hostname -I)
$SLURM_ROOT/bin/scontrol update nodename=${hostname} nodeaddr=$ipaddress

# Set hostname
hostname_fqdn=${hostname}.${onprem_domain}
if [ $(hostname) != $hostname_fqdn ]; then
    hostnamectl --static set-hostname $hostname_fqdn
    hostnamectl --pretty set-hostname $hostname
fi

if [ -e /opt/slurm/${ClusterName}/config/users_groups.json ] && [ -e /opt/slurm/${ClusterName}/bin/create_users_groups.py ]; then
    /opt/slurm/${ClusterName}/bin/create_users_groups.py -i /opt/slurm/${ClusterName}/config/users_groups.json
fi

# Create directory for slurmd.log
logs_dir=/opt/slurm/${ClusterName}/logs/nodes/${hostname}
if [[ ! -d $logs_dir ]]; then
    mkdir -p $logs_dir
fi
if [[ -e /var/log/slurm ]]; then
    rm -rf /var/log/slurm
fi
ln -s $logs_dir /var/log/slurm

systemctl enable slurmd
systemctl start slurmd
# Restart so that log file goes to file system
systemctl restart spot_monitor
```
