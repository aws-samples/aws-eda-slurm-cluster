# Custom AMIs for ParallelCluster

ParallelCluster supports [building custom AMIs for the compute nodes](https://docs.aws.amazon.com/parallelcluster/latest/ug/building-custom-ami-v3.html).
The easiest way is to start an EC2 instances, update it with your changes, and create a new AMI from that instance.
You can then add the new AMI to your configuration file.

ParallelCluster can also automate this process for you and when you build your cluster, example ParallelCluster build configuration files
will be created for you in `source/resources/parallel-cluster/config/build-files/parallelcluster-eda-*.yml`.

The easiest way is to use the ParallelCluster UI to build the AMI using a build config file.

* Click on **Images** on the left
* Click on the **Custom** tab
* Click on **Build Image**
* Paste the contents of a config file into the window.
* Copy the image/name value into the **Image Id** field. It should begin with parallelcluster-
* Click **Build Image**

## FPGA Developer AMI

This tutorial shows how to create an AMI based on the AWS FPGA Developer AMI.
The FPGA Developer AMI has the Xilinx Vivado tools that can be used free of additional
charges when run on AWS EC2 instances to develop FPGA images that can be run on AWS F1 instances.

### Subscribe To the AMI

First subscribe to the FPGA developer AMI in the [AWS Marketplace](https://us-east-1.console.aws.amazon.com/marketplace/home?region=us-east-1#/landing).
There are 2 versions, one for [CentOS 7](https://aws.amazon.com/marketplace/pp/prodview-gimv3gqbpe57k?ref=cns_1clkPro) and the other for [Amazon Linux 2](https://aws.amazon.com/marketplace/pp/prodview-iehshpgi7hcjg?ref=cns_1clkPro).

## Deploy the Cluster

With the config updated, the AMIs for the compute nodes will be built using the specified base AMIs.
