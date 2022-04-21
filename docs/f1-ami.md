# SLURM AMI Based On FPGA Developer AMI

This tutorial shows how to create an AMI based on the AWS FPGA Developer AMI.
The FPGA Developer AMI has the Xilinx Vivado tools that can be used free of additional
charges when run on AWS EC2 instances to develop FPGA images that can be run on AWS F1 instances.

## Subscribe To the AMI

First subscribe to the FPGA developer AMI in the AWS Marketplace.
There are 2 versions, one for [CentOS 7](https://aws.amazon.com/marketplace/pp/prodview-gimv3gqbpe57k?ref=cns_1clkPro) and the other for [Amazon Linux 2](https://aws.amazon.com/marketplace/pp/prodview-iehshpgi7hcjg?ref=cns_1clkPro).

## Add the AMI to Your Config File

```
slurm:
  SlurmNodeAmis:
    # Customized AMIs with file system mounts, packages, etc. configured.
    # If these aren't defined then the generic base AMIs are used.
    # Example in the comment below is the AWS FPGA Developer AMI
    BaseAmis:
      us-east-1:
        Amazon: {2: {x86_64: {ImageId: ami-0efdec76678df9a64, RootDeviceSize: '+5'}}}
        CentOS: {7: {x86_64: {ImageId: ami-02155c6289e76719a, RootDeviceSize: '+5'}}}
```

## Deploy the Cluster

With the config updated the AMIs for the compute nodes will be built using the specified base AMIs.
