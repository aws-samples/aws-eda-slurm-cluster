# Custom AMIs for ParallelCluster

ParallelCluster supports [building custom AMIs for the compute nodes](https://docs.aws.amazon.com/parallelcluster/latest/ug/building-custom-ami-v3.html).
The easiest way is to start an EC2 instance, update it with your changes, and create a new AMI from that instance.
You can then add the new AMI to your configuration file.

ParallelCluster can also automate this process for you using EC2 ImageBuilder.
When you build your cluster, example ParallelCluster build configuration files
will be created for you and stored on the head node at:

`/opt/slurm/`**ClusterName**`/config/build-files/parallelcluster-`**PCVersion**`-*.yml`

The build files with **eda** in the name build an image that installs the packages that are typically used by EDA tools.

The easiest way is to use the ParallelCluster UI to build the AMI using a build config file.

* Click on **Images** on the left
* Click on the **Custom** tab
* Click on **Build Image**
* Paste the contents of a config file into the window.
* Copy the image/name value into the **Image Id** field. It should begin with parallelcluster-
* Click **Build Image**

The UI will create a cloudformation template that uses EC2 ImageBuilder.
While it is being built it will show up as **Pending** in the UI.
When the build is complete the AMI will show up either as **Available** or **Failed**.
If it fails, the instance used to do the build will be left running.
You can connect to it using SSM and lookin in `/var/log/messages` for error messages.

When the build is successful, the stack will be deleted.
There is currently a bug where the stack deletion will fail.
This doesn't mean that the AMI build failed.
Simply select the stack and delete it manually and it should successfully delete.

## FPGA Developer AMI

The build file with **fpga** in the name is based on the FPGS Developer AMI.
The FPGA Developer AMI has the Xilinx Vivado tools that can be used free of additional
charges when run on AWS EC2 instances to develop FPGA images that can be run on AWS F1 instances.

First subscribe to the FPGA developer AMI in the [AWS Marketplace](https://us-east-1.console.aws.amazon.com/marketplace/home?region=us-east-1#/landing).
There are 2 versions, one for [CentOS 7](https://aws.amazon.com/marketplace/pp/prodview-gimv3gqbpe57k?ref=cns_1clkPro) and the other for [Amazon Linux 2](https://aws.amazon.com/marketplace/pp/prodview-iehshpgi7hcjg?ref=cns_1clkPro).

## Deploy or update the Cluster

After the AMI is built, add it to the config and create or update your cluster to use the AMI.
