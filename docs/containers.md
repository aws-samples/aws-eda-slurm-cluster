# Containers

Slurm supports running jobs in unprivileged containers a couple of different ways.
It natively supports running jobs in unprivileged [Open Container Initiative (OCI) containers](https://slurm.schedmd.com/containers.html).
Starting with ParallelCluster 3.11.1, it also supports running docker containers using the [Pyxis SPANK plugin](https://github.com/NVIDIA/pyxis) which uses [enroot](https://github.com/NVIDIA/enroot) to run unprivileged containers.
I will describe using Pyxis first because it is easier than using OCI containers.

**Note**: Most EDA tools are not containerized.
Some won't run in containers and some may run in a container, but not correctly.
I recommend following the guidance of your EDA vendor and consult with them.

I've seen a couple of main motivations for using containers for EDA tools.
The first is because orchestration tools like Kubernetes and AWS Batch require jobs to run in containers.
The other is to have more flexibility managing the run time environment of the tools.
Since the EDA tools themselves aren't containerized, the container is usually used to manage file system mounts and packages that are used by the tools.
If new packages are required by a new tool, then it is easy to update and distribute a new version of the container.
Another reason is to use legacy OS distributions on an instance running a newer distribution.

## Using Pyxis

The enroot and Pyxis packages were developed by NVIDIA to make it easier to run containers on Slurm compute nodes.
ParallelCluster started installing enroot and Pyxis in version 3.11.1 so that you can [run containerized jobs with Pyxis](https://docs.aws.amazon.com/en_us/parallelcluster/latest/ug/tutorials_11_running-containerized-jobs-with-pyxis.html).

To configure Slurm to use the Pyxis plugin, set the **slurm/ParallelClusterConfig/EnablePyxis** parameter to **true** and create or update your cluster.
This will configure the head node to use the Pyxis plugin.
It will also configure your external login nodes to install, configure, and use enroot and the Pyxis plugin.

### Running a containerized job using Pyxis

With Pyxis configured in your cluster, you have new options in srun and sbatch to specify a container image.

```
# Submitting an interactive job
srun -N 2 --container-image docker://rockylinux:8 hostname

# Submitting a batch job
sbatch -N 2 --wrap='srun --container-image docker://rockylinux:8 hostname'
```

## Using OCI containers

Slurm supports [running jobs in unprivileged OCI containers](https://slurm.schedmd.com/containers.html).
OCI is the [Open Container Initiative](https://opencontainers.org/), an open governance structure with the purpose of creating open industry standards around container formats and runtimes.

I'm going to document how to add OCI support to your EDA Slurm cluster.

**NOTE**: Rootless docker requires user-specific setup for each user that will run the containers.
For this reason, it is much easier to use Pyxis.

### Configure rootless docker on login and compute nodes

The login and compute nodes must be configured to use an unprivileged container runtime.

Run the following script as root to install rootless Docker.

```
/opt/slurm/${ClusterName}/config/bin/install-rootless-docker.sh
```

The script [installs the latest Docker from the Docker yum repo](https://docs.docker.com/engine/install/rhel/).

The creation of a compute node AMI with rootless docker installed has been automated in the [creation of a custom compute node AMI](custom-amis.md).
Use one of the build config files with **docker** in the name to create a custom AMI and configure your cluster to use it.

### Per user configuration

Next, [configure Docker to run rootless](https://docs.docker.com/engine/security/rootless/) by running the following script as the user that will be running Docker.

```
dockerd-rootless-setuptool.sh
```

Each user that will run Docker must have an entry in `/etc/subuid` and `/etc/subgid`.
The creates_users_groups_json.py script will create `/opt/slurm/config/subuid` and `/opt/slurm/config/subgid` and the compute nodes will copy them to `/etc/subuid` and `/etc/subgid`.

You must configure docker to use a non-NFS storage location for storing images.

`~/.config/docker/daemon.json`:

```
{
    "data-root": "/var/tmp/${USER}/containers/storage"
}
```

### Create OCI Bundle

Each container requires an [OCI bundle](https://slurm.schedmd.com/containers.html#bundle).

The bundle directories can be stored on NFS and shared between users.
For example, you could create an oci-bundles directory on your shared file system.

This shows how to create an ubuntu bundle.
You can do this as root with the docker service running, but it would be better to run
it using rootless Docker.

```
export OCI_BUNDLES_DIR=~/oci-bundles
export IMAGE_NAME=ubuntu
export BUNDLE_NAME=ubuntu
mkdir -p $OCI_BUNDLES_DIR
cd $OCI_BUNDLES_DIR
mkdir -p $BUNDLE_NAME
cd $BUNDLE_NAME
docker pull $IMAGE_NAME
docker export $(docker create $IMAGE_NAME) > $BUNDLE_NAME.tar
mkdir rootfs
tar -C rootfs -xf $IMAGE_NAME.tar
runc spec --rootless
runc run containerid1
```

The same process works for Rocky Linux 8.

```
export OCI_BUNDLES_DIR=~/oci-bundles
export IMAGE_NAME=rockylinux:8
export BUNDLE_NAME=rockylinux8
mkdir -p $OCI_BUNDLES_DIR
cd $OCI_BUNDLES_DIR
mkdir -p $BUNDLE_NAME
cd $BUNDLE_NAME
docker pull $IMAGE_NAME
docker export $(docker create $IMAGE_NAME) > $BUNDLE_NAME.tar
mkdir rootfs
tar -C rootfs -xf $BUNDLE_NAME.tar
runc spec --rootless
runc run containerid2
```

### Run a bundle on Slurm using OCI container

```
export OCI_BUNDLES_DIR=~/oci-bundles
export BUNDLE_NAME=rockylinux8

srun -p interactive --container $OCI_BUNDLES_DIR/$BUNDLE_NAME --pty hostname

srun -p interactive --container $OCI_BUNDLES_DIR/$BUNDLE_NAME --pty bash

sbatch -p interactive --container $OCI_BUNDLES_DIR/$BUNDLE_NAME --wrap hostname
```
