# Exostellar Workload Optimizer (XWO)

[Exostellar Workload Optimizer](https://exostellar.io/product/#workloadoptimizer) (XWO) runs applications in virtual machines (VMs) on EC2 instances and can dynamically migrate the VMs between instances based on actual memory utilization.
This can provide significant savings when users over-provision memory or provision memory
based on peak usage by running on instances with less memory when the extra memory isn't
required.
It also, optionally, provides the functionality of [Infrastructure Optimizer](https://exostellar.io/product/#infrastructureoptimizer) which migrates
VMs between Spot and On-Demnad instances based on availability and cost.

XWO runs on an Exostellar Management Server (EMS).
The EMS runs a web application and launches and manages the instances that run jobs.
In response to job requests it launches controller nodes that manage pools of worker nodes.
The controller launches workers and then starts one or more VMs on the workers.
The controller also determines when VMs need to be migrated, allocates new workers, and manages the VM migrations.

XWO Profiles configure XWO Controllers and XWO Workers.
The Workers run the XWO VMs.
The Controller manages the workers and the VMs that run on them.
The Worker configuration includes the instance types to use for
on-demand and spot instances.
It also includes the security groups and tags for the worker instances.

You create an XWO Application Environment for each Slurm cluster.
The Application Environment contains the URL for the Slurm head node,
configures pools of VMs,
and configures the path to the Slurm binaries and configuration.
The VM pools define the attributes of the instances including the number of CPUs, VM Image, min and max memory, and an associated XWO Profile.

You must also create XWO Images that are used to create the VMs.
The Images are created from AWS AMIs and are specified in the Pools.

**NOTE:** One current restriction of XWO VMs is that they cannot be created from ParallelCluster AMIs.
This is because the kernel modules that ParallelCluster installs aren't supported by the XWO hypervisor.

## XWO Configuration

This section will describe the process of configuring XWO to work with ParallelCluster.

Refer to [Exostellar's documentation](https://docs.exostellar.io/latest/Latest/HPC-User/getting-started-installation) to make sure you have the latest instructions.

### Deploy ParallelCluster without configuring XWO

First deploy your cluster without configuring XWO.
The cluster deploys ansible playbooks that will be used to create the XWO ParallelCluster AMI.

### Deploy the Exostellar Management Server (EMS)

The next step is to [install the Exostellar management server](https://docs.exostellar.io/latest/Latest/HPC-User/installing-management-server).
You must first subscribe to the three Exostellar Infrastructure AMIs in the AWS Marketplace.

* [Exostellar Management Server](https://aws.amazon.com/marketplace/server/procurement?productId=prod-crdnafbqnbnm2)
* [Exostellar Controller](https://aws.amazon.com/marketplace/server/procurement?productId=prod-d4lifqwlw4kja)
* [Exostellar Worker](https://aws.amazon.com/marketplace/server/procurement?productId=prod-2smeyk5fuxt7q)

Then follow the [directions to deploy the CloudFormation template](https://docs.exostellar.io/latest/Latest/HPC-User/installing-management-server#v2.4.0.0InstallingwithCloudFormationTemplate(AWS)-Step3:CreateaNewStack).

### Verify that the "az1" profile exists

In the EMS GUI go to Profiles and make sure that the "az1" profile exists.
I use that as a template to create your new profiles.

If it doesn't exist, there was a problem with the EMS deployment and you should contact Exostellar support.

### Create an XWO ParallelCluster AMI

Launch an instance using the base AMI for your OS.
For example, launch an instance with a base RHEL 8 or Rocky 8 AMI.

Mount the ParallelCluster NFS file system at /opt/slurm.

Run the ansible playbook to configure the instance for XWO.

```
/opt/slurm/config/bin/exostellar-compute-node-ami-configure.sh
```

Do any additional configuration that you require such as configuring file system mounts and installing
packages.

Create an AMI from the instance and wait for it to become available.

After the AMI has been successfully created you can either stop or terminate the instance to save costs.
If you may need to do additional customization, then stop it, otherwise terminate it.

Add the image id to your configuration as described below.

### Create XWO Configuration

The next step is to plan and configure your XWO deployment.
The key decisions that you must make are the instance types that you will use
and the AMI that you will use for the XWO VM Images.

XWO currently only supports x86_64 instance types and pools cannot mix AMD and Intel instance types.
The configuration has been simplified so that all you have to do is specify the instance types
and families that you want to use.
The instance types will be grouped by the number of cores and amount of memory to create
pools and Slurm partitions.
You can still create your own profiles and pools if the automatically generated ones do not
meet your needs.
The example only shows the simplified configuration.

**NOTE**: XWO currently doesn't support VMs larger than 1 TB.

Refer to [Best practices for Amazon EC2 Spot](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-best-practices.html) when planning your cluster deployment and creating your configuration.

It is highly recommended to use [EC2 Spot placement scores](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/work-with-spot-placement-score.html) when selecting the region and availability zone for your cluster.
This will give you an indication of the likelihood of getting desired spot capacity.

In the following example,
I've included instance families from the last 3 generations of instances to maximize the number of
available capacity pools and increase the likelihood of running on spot.

**Note**: The Intel instance families contain more configurations and higher memory instances. They also have high frequency instance types such as m5zn, r7iz, and z1d. They also tend to have more capacity. The AMD instance families include HPC instance types, however, they do not support spot pricing and can only be used for on-demand.

**Note**: This is only an example configuration. You should customize it for your requirements.

```
slurm:
  Xwo:
    ManagementServerStackName: exostellar-management-server
    PartitionName: xwo
    AvailabilityZone: us-east-1b

    Images:
      - ImageId: ami-xxxxxxxxxxxxxxxxx
        ImageName: <your-xio-vm-image-name>

    DefaultImageName: <your-xio-vm-image-name>

    InstanceTypes:
      - c5a:1
      - m5a:2
      - r5a:3
    SpotFleetTypes:
      - c5a:1
      - m5a:2
      - r5a:3

    PoolSize: 10
    EnableHyperthreading: false
    VmRootPasswordSecret: ExostellarVmRootPassword
```

### Update the cluster with the XWO configuration

Update the cluster with the XWO configuration.

This will update the profiles and environment on the EMS server and configure the cluster for XWO.
The only remaining step before you can submit jobs is to create the XWO VM image.

This is done before creating an image because the XWO scripts get deployed by this step.

### Create an XWO Image from the XWO ParallelCluster AMI

Connect to the head node and create the XWO Image from the AMI you created.
The IMAGE-NAME should be the same that you configured in the Pools.

```
/opt/slurm/etc/exostellar/parse_helper.sh -a <AMI-ID1> -i <IMAGE-NAME>
```

### Configure the Exostellar Certificates on the Head Node

The resume script needs an Exostellar certificate authority and client security certificate
to be able to call the REST API on the EMS.
Download the certificates and copy them to the head node.

* Open the EMS in a browser.
* Click on Settings
* Select the Certificates tab
* Click on **Generate Client Certificate**, name it **ExostellarClient.pem**, and save it in the Downloads folder.
* Click on **Download Exostellar CA**, name it **ExostellarRootCA.crt**, and save it in the Downloads folder.
* Copy the two certificates to /etc/ssl/certs/ on the head node.

### Test launching an XWO VM

Connect to the head node and test launching a VM.
The pool, profile, and image_name should be from your configuration.
The host name doesn't matter.

```
/opt/slurm/etc/exostellar/test_createVm.sh --pool <pool> --profile <profile> -i <image name> -h <host>
```

When this is done, the VM, worker, and controller should all terminate on their own.
If they do not, then connect to the EMS and cancel the job that started the controller.

Use `squeue` to list the controller jobs. Use `scancel` to terminate them.

### Run a test job using Slurm

```
srun --pty -p xwo-amd-64g-4c hostname
```

## Debug

### How to connect to EMS

Use ssh to connect to the EMS using your EC2 keypair.

* `ssh-add private-key.pem`
* `ssh -A rocky@${EMS_IP_ADDRESS}`

You can [install the aws-ssm-agent](https://docs.aws.amazon.com/systems-manager/latest/userguide/agent-install-rocky.html) so that you can connect from the EC2 console using SSM.

### How to connect to Controller

* First ssh to the EMS.
* Get the IP address of the controller from the EC2 console
* As root, ssh to the controller

### UpdateHeadNode resource failed

If the UpdateHeadNode resource fails then it is usually because a task in the ansible script failed.
Connect to the head node and look for errors in:

```/var/log/ansible.log```

Usually it will be a problem with the `/opt/slurm/etc/exostellar/configure_xio.py` script.

When this happens the CloudFormation stack will usually be in UPDATE_ROLLBACK_FAILED status.
Before you can update it again you will need to complete the rollback.
Go to Stack Actions, select `Continue update rollback`, expand `Advanced troubleshooting`, check the UpdateHeadNode resource, anc click `Continue update rollback`.

The problem is usually that there is an XWO controller running that is preventing updates to
the profile.
Cancel any XWO jobs and terminate any running workers and controllers and verify that all of the XWO profiles are idle.

### XWO Controller not starting

If a controller doesn't start, then the first thing to check is to make sure that the
`/opt/slurm/exostellar/resume_xspot.sh` script ran successfully on the head node.

`grep resume_xspot.sh /var/log/messages | less`

The script should get "http_code=200". If not, investigate the error.

If the resume script passed, then a controller should have started.

On EMS, check that a job is running to create the controller.

`squeue`

On EMS, check the autoscaling log to see if there are errors starting the instance.

`less /var/log/slurm/autoscaling.log`

EMS Slurm partitions are at:

`/xcompute/slurm/bin/partitions.json`

They are derived from the partition and pool names.

### Worker instance not starting

### VM not starting on worker

Connect to the controller instance and run the following command to get a list of worker instances and VMs.

```
xspot ps
```

Connect to the worker VM using the following command.

```
xspot console vm-abcd
```

This will show the console logs.
If you configured the root password then you can log in as root to do further debug.

### VM not starting Slurm job

Connect to the VM as above.

Check /var/log/slurmd.log for errors.
