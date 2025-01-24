# Exostellar Infrastructure Optimizer (XIO)

[Exostellar Infrastructure Optimizer](https://exostellar.io/infrastructureoptimizer-technical-information/) (XIO) runs applications in virtual machines (VMs) on EC2 instances and can dynamically migrate the VMs between instances based on availability and cost.
Long-running, stateful jobs are not normally run on spot instances because of the risk of lost work after a spot termination.
XIO reduces this risk by predicting spot terminations and migrating the VM to another instance with higher availability.
This could be a different spot instance type or an on-demand instance.
When spot capacity becomes available again, the VM can be migrated back to a spot instance.
This allows you to save up to 90% over on-demand pricing by running on spot when capacity is available.
You increase the potential for savings by configuring as many spot capacity pools as possible.
This doesn't completely eliminate the risk of the job failing.
The job will still fail and need to be restarted from the beginning if a spot termination isn't predicted far enough in advance for the job to be migrated or if a new instance cannot be launched to migrate the job to.

**Note**: Job reliability will be increased by following EC2 Spot best practices such as configuring as many capacity pools and instance types as possible.

XIO runs on an Exostellar Management Server (EMS).
The EMS runs a web application and launches and manages the instances that run jobs.
In response to job requests it launches controller nodes that manage pools of worker nodes.
The controller launches workers and then starts one or more VMs on the workers.
The controller also determines when VMs need to be migrated, allocates new workers, and manages the VM migrations.

You create an XIO Application Environment for each Slurm cluster.
The Application Environment contains the URL for the Slurm head node,
configures pools of VMs,
and configures the path to the Slurm binaries and configuration.
The VM pools define the attributes of the instances including the number of CPUs, VM Image, min and max memory, and an associated XIO Profile.

You must also create the XIO Profiles that are used by the VM Pools.
Each profile configures XIO Controllers and XIO Workers.
The Workers run the XIO VMs.
The Controller manages the workers and the VMs that run on them.
The Worker configuration includes the instance types to use for
on-demand and spot instances.
It also includes the security groups and tags for the worker instances.

You must also create XIO Images that are used to create the VMs.
The Images are created from AWS AMIs and are specified in the VM Pools.

**NOTE:** One current restriction of XIO VMs is that they cannot be created from ParallelCluster AMIs.
This is because the kernel modules that ParallelCluster installs aren't supported by the XIO hypervisor.

## XIO Configuration

This section will describe the process of configuring XIO to work with ParallelCluster.

Refer to [Exostellar's documentation](https://docs.exostellar.io/latest/Latest/HPC-User/getting-started-installation) to make sure you have the latest instructions.

### Deploy ParallelCluster without configuring XIO

First deploy your cluster without configuring XIO.
The cluster deploys ansible playbooks that will be used to create the XIO ParallelCluster AMI.

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

### Create an XIO ParallelCluster AMI

Launch an instance using the base AMI for your OS.
For example, launch an instance with a base RHEL 8 or Rocky 8 AMI.

Mount the ParallelCluster NFS file system at /opt/slurm.

Run the ansible playbook to configure the instance for XIO.

```
/opt/slurm/config/bin/xio-compute-node-ami-configure.sh
```

Do any additional configuration that you require such as configuring file system mounts and installing
packages.

Create an AMI from the instance and wait for it to become available.

After the AMI has been successfully created you can either stop or terminate the instance to save costs.
If you may need to do additional customization, then stop it, otherwise terminate it.

Add the image id to your configuration as described below.

### Create XIO Configuration

The next step is to plan and configure your XIO deployment.
The key decisions that you must make are the instance types that you will use
and the AMI that you will use for the XIO VM Images.

XIO currently only supports x86_64 instance types and pools cannot mix AMD and Intel instance types.
The following XIO configuration for aws-eda-slurm-cluster shows 2 pools that contain Intel and AMD instances.
Note that we first define the XIO Profiles with instance types with the same manufacturer, number of cores, and amount of memory.
Then we configure pools for the Application Environment that use the profiles.
The numbers after the instance type are a priority to bias XIO to use higher priority instance types if they are available.
We've chosen to prioritize the latest generation instance types so our jobs run faster and configure
older generation instance types at a lower priority to increase the number of capacity pools so that
we have a better chance of running on spot and having instances to run our jobs.
Refer to [Best practices for Amazon EC2 Spot](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-best-practices.html) when planning your cluster deployment and creating your configuration.

**NOTE**: XIO currently doesn't support VMs larger than 1 TB.

It is highly recommended to use [EC2 Spot placement scores](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/work-with-spot-placement-score.html) when selecting the region and availability zone for your cluster.
This will give you an indication of the likelihood of getting desired spot capacity.

In the following example I've configured a profile for AMD and Intel instance families.
I've included instance families from the last 3 generations of instances to maximize the number of
available capacity pools and increase the likelihood of running on spot.

**Note**: The Intel instance families contain more configurations and higher memory instances. They also have high frequency instance types such as m5zn, r7iz, and z1d. They also tend to have more capacity. The AMD instance families include HPC instance types, however, they do not support spot pricing and can only be used for on-demand.

**Note**: This is only an example configuration. You should customize it for your requirements.

```
slurm:
  Xio:
    ManagementServerStackName: exostellar-management-server
    PartitionName: xio
    AvailabilityZone: us-east-2b

    Images:
      - ImageId: ami-xxxxxxxxxxxxxxxxx
        ImageName: <your-xio-vm-image-name>

    DefaultImageName: <your-xio-vm-image-name>
    Profiles:
      - ProfileName: amd
        NodeGroupName: amd
        MaxControllers: 10
        InstanceTypes:
          - c5a:1
          - c5ad:1
          - c6a:4
          - c7a:7

          - m5a:1
          - m5ad:1
          - m6a:4
          - m7a:7

          - r5a:1
          - r5ad:1
          - r6a:4
          - r7a:7
        SpotFleetTypes:
          - c5a:1
          - c5ad:1
          - c6a:4
          - c7a:7

          - m5a:1
          - m5ad:1
          - m6a:4
          - m7a:7

          - r5a:1
          - r5ad:1
          - r6a:4
          - r7a:7
        EnableHyperthreading: false

      - ProfileName: intel
        NodeGroupName: intel
        MaxControllers: 10
        InstanceTypes:
          - c5n:1
          - c5d:1
          - c5:1
          - c6in:4
          - c6id:4
          - c6i:4
          - c7i:7

          - m5:1
          - m5d:1
          - m5dn:1
          - m5n:1
          - m5zn:1
          - m6i:4
          - m6id:4
          - m6idn:4
          - m6in:4
          - m7i:7

          - r5:1
          - r5b:1
          - r5d:1
          - r5dn:1
          - r5n:1
          - r6i:4
          - r6id:4
          - r6idn:4
          - r6in:4
          - r7i:7
          - r7iz:7

          # - x2idn:1
          # - x2iedn:1

          - z1d:1
        SpotFleetTypes:
          - c5n:1
          - c5d:1
          - c5:1
          - c6in:4
          - c6id:4
          - c6i:4
          - c7i:7

          - m5:1
          - m5d:1
          - m5dn:1
          - m5n:1
          - m5zn:1
          - m6i:4
          - m6id:4
          - m6idn:4
          - m6in:4
          - m7i:7

          - r5:1
          - r5b:1
          - r5d:1
          - r5dn:1
          - r5n:1
          - r6i:4
          - r6id:4
          - r6idn:4
          - r6in:4
          - r7i:7
          - r7iz:7

          # - x2idn:1
          # - x2iedn:1

          - z1d:1
        EnableHyperthreading: false
    Pools:
      - PoolName: amd-8g-2c
        ProfileName: amd
        PoolSize: 10
        CPUs: 2
        InstanceMemory: 8192
      - PoolName: amd-8g-4c
        ProfileName: amd
        PoolSize: 10
        CPUs: 4
        InstanceMemory: 8192
      - PoolName: amd-16g-1c
        ProfileName: amd
        PoolSize: 10
        CPUs: 1
        InstanceMemory: 16384
      - PoolName: amd-16g-2c
        ProfileName: amd
        PoolSize: 10
        CPUs: 2
        InstanceMemory: 16384
      - PoolName: amd-16g-4c
        ProfileName: amd
        PoolSize: 10
        CPUs: 4
        InstanceMemory: 16384
      - PoolName: amd-16g-8c
        ProfileName: amd
        PoolSize: 10
        CPUs: 8
        InstanceMemory: 16384
      - PoolName: amd-32g-2c
        ProfileName: amd
        PoolSize: 10
        CPUs: 2
        InstanceMemory: 32768
      - PoolName: amd-32g-4c
        ProfileName: amd
        PoolSize: 10
        CPUs: 4
        InstanceMemory: 32768
      - PoolName: amd-32g-8c
        ProfileName: amd
        PoolSize: 10
        CPUs: 8
        InstanceMemory: 32768
      - PoolName: amd-64g-4c
        ProfileName: amd
        PoolSize: 10
        CPUs: 4
        InstanceMemory: 65536
      - PoolName: amd-64g-8c
        ProfileName: amd
        PoolSize: 10
        CPUs: 8
        InstanceMemory: 65536
      - PoolName: amd-64g-16c
        ProfileName: amd
        PoolSize: 10
        CPUs: 16
        InstanceMemory: 65536
      - PoolName: amd-64g-32c
        ProfileName: amd
        PoolSize: 10
        CPUs: 32
        InstanceMemory: 65536
      - PoolName: amd-128g-8c
        ProfileName: amd
        PoolSize: 10
        CPUs: 8
        InstanceMemory: 131072
      - PoolName: amd-128g-16c
        ProfileName: amd
        PoolSize: 10
        CPUs: 16
        InstanceMemory: 131072
      - PoolName: amd-128g-32c
        ProfileName: amd
        PoolSize: 10
        CPUs: 32
        InstanceMemory: 131072
      - PoolName: amd-128g-64c
        ProfileName: amd
        PoolSize: 10
        CPUs: 64
        InstanceMemory: 131072
      - PoolName: amd-192g-24c
        ProfileName: amd
        PoolSize: 10
        CPUs: 24
        InstanceMemory: 196608
      - PoolName: amd-192g-48c
        ProfileName: amd
        PoolSize: 10
        CPUs: 48
        InstanceMemory: 196608
      - PoolName: amd-256g-16c
        ProfileName: amd
        PoolSize: 10
        CPUs: 16
        InstanceMemory: 262144
      - PoolName: amd-256g-32c
        ProfileName: amd
        PoolSize: 10
        CPUs: 32
        InstanceMemory: 262144
      - PoolName: amd-256g-64c
        ProfileName: amd
        PoolSize: 10
        CPUs: 64
        InstanceMemory: 262144
      - PoolName: amd-256g-128c
        ProfileName: amd
        PoolSize: 10
        CPUs: 128
        InstanceMemory: 262144
      - PoolName: amd-384g-24c
        ProfileName: amd
        PoolSize: 10
        CPUs: 24
        InstanceMemory: 393216
      - PoolName: amd-384g-48c
        ProfileName: amd
        PoolSize: 10
        CPUs: 48
        InstanceMemory: 393216
      - PoolName: amd-384g-96c
        ProfileName: amd
        PoolSize: 10
        CPUs: 96
        InstanceMemory: 393216
      - PoolName: amd-384g-192c
        ProfileName: amd
        PoolSize: 10
        CPUs: 192
        InstanceMemory: 393216
      - PoolName: amd-512g-32c
        ProfileName: amd
        PoolSize: 10
        CPUs: 32
        InstanceMemory: 524288
      - PoolName: amd-512g-64c
        ProfileName: amd
        PoolSize: 10
        CPUs: 64
        InstanceMemory: 524288
      - PoolName: amd-512g-128c
        ProfileName: amd
        PoolSize: 10
        CPUs: 128
        InstanceMemory: 524288
      - PoolName: amd-768g-48c
        ProfileName: amd
        PoolSize: 10
        CPUs: 48
        InstanceMemory: 786432
      - PoolName: amd-768g-96c
        ProfileName: amd
        PoolSize: 10
        CPUs: 96
        InstanceMemory: 786432
      - PoolName: amd-768g-192c
        ProfileName: amd
        PoolSize: 10
        CPUs: 192
        InstanceMemory: 786432
      - PoolName: amd-1024g-64c
        ProfileName: amd
        PoolSize: 10
        CPUs: 64
        InstanceMemory: 1048576
      - PoolName: amd-1536g-96c
        ProfileName: amd
        PoolSize: 10
        CPUs: 96
        InstanceMemory: 1572864
      - PoolName: amd-1536g-192c
        ProfileName: amd
        PoolSize: 10
        CPUs: 192
        InstanceMemory: 1572864

      - PoolName: intel-8g-1c
        ProfileName: intel
        PoolSize: 10
        CPUs: 1
        InstanceMemory: 8192
      - PoolName: intel-8g-2c
        ProfileName: intel
        PoolSize: 10
        CPUs: 2
        InstanceMemory: 8192
      - PoolName: intel-16g-1c
        ProfileName: intel
        PoolSize: 10
        CPUs: 1
        InstanceMemory: 16384
      - PoolName: intel-16g-2c
        ProfileName: intel
        PoolSize: 10
        CPUs: 2
        InstanceMemory: 16384
      - PoolName: intel-16g-4c
        ProfileName: intel
        PoolSize: 10
        CPUs: 4
        InstanceMemory: 16384
      - PoolName: intel-32g-2c
        ProfileName: intel
        PoolSize: 10
        CPUs: 2
        InstanceMemory: 32768
      - PoolName: intel-32g-4c
        ProfileName: intel
        PoolSize: 10
        CPUs: 4
        InstanceMemory: 32768
      - PoolName: intel-32g-8c
        ProfileName: intel
        PoolSize: 10
        CPUs: 8
        InstanceMemory: 32768
      - PoolName: intel-48g-6c
        ProfileName: intel
        PoolSize: 10
        CPUs: 6
        InstanceMemory: 49152
      - PoolName: intel-64g-4c
        ProfileName: intel
        PoolSize: 10
        CPUs: 4
        InstanceMemory: 65536
      - PoolName: intel-64g-8c
        ProfileName: intel
        PoolSize: 10
        CPUs: 8
        InstanceMemory: 65536
      - PoolName: intel-64g-16c
        ProfileName: intel
        PoolSize: 10
        CPUs: 16
        InstanceMemory: 65536
      - PoolName: intel-72g-18c
        ProfileName: intel
        PoolSize: 10
        CPUs: 18
        InstanceMemory: 73728
      - PoolName: intel-96g-6c
        ProfileName: intel
        PoolSize: 10
        CPUs: 6
        InstanceMemory: 98304
      - PoolName: intel-96g-12c
        ProfileName: intel
        PoolSize: 10
        CPUs: 12
        InstanceMemory: 98304
      - PoolName: intel-96g-24c
        ProfileName: intel
        PoolSize: 10
        CPUs: 12
        InstanceMemory: 98304
      # - PoolName: intel-128g-2c # x2iedn.xlarge
      #   ProfileName: intel
      #   PoolSize: 10
      #   CPUs: 2
      #   InstanceMemory: 131072
      - PoolName: intel-128g-8c
        ProfileName: intel
        PoolSize: 10
        CPUs: 8
        InstanceMemory: 131072
      - PoolName: intel-128g-16c
        ProfileName: intel
        PoolSize: 10
        CPUs: 16
        InstanceMemory: 131072
      - PoolName: intel-128g-32c
        ProfileName: intel
        PoolSize: 10
        CPUs: 32
        InstanceMemory: 131072
      - PoolName: intel-144g-36c # c5[d].18xlarge
        ProfileName: intel
        PoolSize: 10
        CPUs: 36
        InstanceMemory: 147456
      - PoolName: intel-192g-12c
        ProfileName: intel
        PoolSize: 10
        CPUs: 12
        InstanceMemory: 196608
      - PoolName: intel-192g-24c
        ProfileName: intel
        PoolSize: 10
        CPUs: 24
        InstanceMemory: 196608
      - PoolName: intel-192g-48c
        ProfileName: intel
        PoolSize: 10
        CPUs: 48
        InstanceMemory: 196608
      # - PoolName: intel-256g-4c # x2iedn.2xlarge
      #   ProfileName: intel
      #   PoolSize: 10
      #   CPUs: 4
      #   InstanceMemory: 262144
      - PoolName: intel-256g-16c
        ProfileName: intel
        PoolSize: 10
        CPUs: 16
        InstanceMemory: 262144
      - PoolName: intel-256g-32c
        ProfileName: intel
        PoolSize: 10
        CPUs: 32
        InstanceMemory: 262144
      - PoolName: intel-256g-64c
        ProfileName: intel
        PoolSize: 10
        CPUs: 64
        InstanceMemory: 262144
      - PoolName: intel-384g-24c
        ProfileName: intel
        PoolSize: 10
        CPUs: 24
        InstanceMemory: 393216
      - PoolName: intel-384g-48c
        ProfileName: intel
        PoolSize: 10
        CPUs: 48
        InstanceMemory: 393216
      - PoolName: intel-384g-96c
        ProfileName: intel
        PoolSize: 10
        CPUs: 96
        InstanceMemory: 393216
      # - PoolName: intel-512g-8c # x2iedn.4xlarge
      #   ProfileName: intel
      #   PoolSize: 10
      #   CPUs: 8
      #   InstanceMemory: 524288
      - PoolName: intel-512g-32c
        ProfileName: intel
        PoolSize: 10
        CPUs: 32
        InstanceMemory: 524288
      - PoolName: intel-512g-64c
        ProfileName: intel
        PoolSize: 10
        CPUs: 64
        InstanceMemory: 524288
      - PoolName: intel-768g-48c
        ProfileName: intel
        PoolSize: 10
        CPUs: 48
        InstanceMemory: 786432
      - PoolName: intel-768g-96c
        ProfileName: intel
        PoolSize: 10
        CPUs: 96
        InstanceMemory: 786432
      # - PoolName: intel-1024g-16c # x2iedn.8xlarge
      #   ProfileName: intel
      #   PoolSize: 10
      #   CPUs: 16
      #   InstanceMemory: 1048576
      # - PoolName: intel-1024g-32c # x2idn.16xlarge
      #   ProfileName: intel
      #   PoolSize: 10
      #   CPUs: 32
      #   InstanceMemory: 1048576
      - PoolName: intel-1024g-64c
        ProfileName: intel
        PoolSize: 10
        CPUs: 64
        InstanceMemory: 1048576
```

### Update the cluster with the XIO configuration

Update the cluster with the XIO configuration.

This will update the profiles and environment on the EMS server and configure the cluster for XIO.
The only remaining step before you can submit jobs is to create the XIO VM image.

This is done before creating an image because the XIO scripts get deployed by this step.

### Create an XIO Image from the XIO ParallelCluster AMI

Connect to the head node and create the XIO Image from the AMI you created.
The IMAGE-NAME should be the same that you configured in the Pools.

```
/opt/slurm/etc/exostellar/parse_helper.sh -a <AMI-ID1> -i <IMAGE-NAME>
```

### Test launching an XIO VM

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
srun --pty -p xio-
```

## Debug

### UpdateHeadNode resource failed

If the UpdateHeadNode resource fails then it is usually because as task in the ansible script failed.
Connect to the head node and look for errors in:

```/var/log/ansible.log```

Usually it will be a problem with the `/opt/slurm/etc/exostellar/configure_xio.py` script.

When this happens the CloudFormation stack will usually be in UPDATE_ROLLBACK_FAILED status.
Before you can update it again you will need to complete the rollback.
Go to Stack Actions, select `Continue update rollback`, expand `Advanced troubleshooting`, check the UpdateHeadNode resource, anc click `Continue update rollback`.

### XIO Controller not starting

On EMA, check that a job is running to create the controller.

`squeue`

On EMS, check the autoscaling log to see if there are errors starting the instance.

`less /var/log/slurm/autoscaling.log``

EMS Slurm partions are at:

`/xcompute/slurm/bin/partitions.json`

They are derived from the partition and pool names.

### Worker instance not starting

### VM not starting on worker

### VM not starting Slurm job
