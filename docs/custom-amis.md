# Custom AMIs for ParallelCluster

ParallelCluster supports [building custom ParallelCluster AMIs for the head and compute nodes](https://docs.aws.amazon.com/parallelcluster/latest/ug/building-custom-ami-v3.html). You can specify a custom AMI for the entire cluster (head and compute nodes) and you can also specify a custom AMI for just the compute nodes.
By default, ParallelCluster will use pre-built AMIs for the OS that you select.
The exception is Rocky 8 and 9, for which ParallelCluster does not provide pre-built AMIs.
To use Rocky Linux, you must first build a custom AMI and specify it in your config file at **slurm/ParallelClusterConfig/Os/CustomAmi**.

The easiest way is to start an EC2 instance with an existing ParallelCluster AMI, update it with your changes, and create a new AMI from that instance.
You can find the official ParallelCluster AMIs using the ParallelCluster UI.
Click on **Images** and the list of **Official Images** will be listed.
After you create the a new AMI, you can then add it to your configuration file.

ParallelCluster can also automate this process for you using EC2 ImageBuilder.
When you build your cluster, example ParallelCluster build configuration files
will be created for you and stored on the head node at:

`/opt/slurm/`**ClusterName**`/config/build-files/parallelcluster-`**PCVersion**`-*.yml`

The build files with **eda** in the name build an image that installs the packages that are typically used by EDA tools.

The build files can be modified for your needs.
The build file format is docummented in the [ParallelCluster User Guide](https://docs.aws.amazon.com/parallelcluster/latest/ug/image-builder-configuration-file-v3.html).
For example, you can add your own scripts to run during the AMI
build process.

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

**Note**: The FPGA Developer AMI hasn't been ported to the latest OS versions, so it will not show up in the build file templates.

## Deploy or update the Cluster

After the AMI is built, add it to the config and create or update your cluster to use the AMI.
You can set the AMI for the compute and head nodes using **slurm/ParallelClusterConfig/Os/CustomAmi** and for the compute nodes only using **slurm/ParallelClusterConfig/ComputeNodeAmi**.

**Note**: You cannot update the OS of the cluster or the AMI of the head node. If they need to change then you will need to create a new cluster.

The config file will look something like the following:

```
slurm:
  ParallelClusterConfig:
    Image:
      Os: rocky8
      CustomAmi: ami-abc123 # Rocky linux
    ComputeNodeAmi: ami-def456 # Rocky linux + EDA packages and EDA file systems
```
