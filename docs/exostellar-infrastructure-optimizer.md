# Exostellar Infrastructure Optimizer

[Exostellar Infrastructure Optimizer](https://exostellar.io/infrastructureoptimizer-technical-information/) (XIO) runs applications in virtual machines (VMs) on EC2 instances and dynamically relocates the VMs between instances based on availability and cost.
Long-running, stateful jobs cannot normally be run on spot instances because they can't be restarted after a spot termination.
XIO reduces this risk by predicting spot terminations and dynamically relocating the VM to an on-demand instance.
When spot capacity becomes available again, the VM can be migrated back to a spot instance.
This allows you to save up to 90% over on-demand pricing by running on spot when capacity is available.

## XIO Configuration

Refer to [Exostellar's documentation](https://docs.exostellar.io/latest/Latest/HPC-User/getting-started-installation) to make sure you have the latest instructions.

### Create IAM permissions stack

[Create the EC2 instances profiles](https://docs.exostellar.io/latest/Latest/HPC-User/getting-ready-prerequisites#GettingReady:Prerequisites-EC2InstanceProfiles).

* Download the CloudFormation template
* Create a stack using the template

### Install the Management Server

[Install the management server](https://docs.exostellar.io/latest/Latest/HPC-User/installing-management-server)

For the shared security group id use the SlurmLoginNodeSGId so that it has access to the Slurm head node.

### Configure Slurm

```
export MGMT_SERVER=10.4.130.5
export SLURM_CONF_DIR=/opt/slurm/res-eda-pc-3-10-1-rhel8-x86/etc

"I2Nsb3VkLWNvbmZpZwpydW5jbWQ6CiAgLSBbc2gsIC1jLCAibWtkaXIgLXAgL3hjb21wdXRlIl0KICAtIFtzaCwgLWMsICJtb3VudCAxNzIuMzEuMjQuNToveGNvbXB1dGUgL3hjb21wdXRlIl0KICAtIFtzaCwgLWMsICJta2RpciAtcCAvaG9tZS9zbHVybSJdCiAgLSBbc2gsIC1jLCAibW91bnQgMTcyLjMxLjI0LjU6L2hvbWUvc2x1cm0gL2hvbWUvc2x1cm0iXQogIC0gW3NoLCAtYywgInJtIC1yZiAvZXRjL3NsdXJtIl0KICAtIFtzaCwgLWMsICJsbiAtcyAveGNvbXB1dGUvc2x1cm0vIC9ldGMvc2x1cm0iXQogIC0gW3NoLCAtYywgImNwIC94Y29tcHV0ZS9zbHVybS9tdW5nZS5rZXkgL2V0Yy9tdW5nZS9tdW5nZS5rZXkiXQogIC0gW3NoLCAtYywgInN5c3RlbWN0bCByZXN0YXJ0IG11bmdlIl0KICAjIEFMV0FZUyBMQVNUIQogIC0gWwogICAgICBzaCwKICAgICAgLWMsCiAgICAgICJlY2hvIFhTUE9UX05PREVOQU1FID4gL3Zhci9ydW4vbm9kZW5hbWU7IHNjb250cm9sIHVwZGF0ZSBub2RlbmFtZT1YU1BPVF9OT0RFTkFNRSBub2RlYWRkcj1gaG9zdG5hbWUgLUlgIiwKICAgIF0KCg=="
```
