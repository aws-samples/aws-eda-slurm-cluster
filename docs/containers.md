# Containers

Slurm supports [running jobs in unprivileged OCI containers](https://slurm.schedmd.com/containers.html).
OCI is the [Open Container Initiative](https://opencontainers.org/), an open governance structure with the purpose of creating open industry standards around container formats and runtimes.

I'm going to document how to add OCI support to your EDA Slurm cluster.
Note that most EDA tools are not containerized and that some won't run in containers and that some may run in a container, but not correctly.
I recommend following the guidance of your EDA vendor and consult with them.

I've seen a couple of main motivations for using containers for EDA tools.
The first is because orchestration tools like Kubernetes and AWS Batch require jobs to run in containers.
The other is to have more flexibility managing the run time environment of the tools.
Since the EDA tools themselves aren't containerized, the container is usually used to manage file system mounts and packages that are used by the tools.
If new packages are required by a new tool, then it is easy to update and distribute a new version of the container.

## Compute node configuration

The compute node must be configured to use an unprivileged container runtime.
We'll show how to install and configure rootless Docker.

The following directions have been automated in the [creation of a custom EDA compute node AMI](custom-amis.md).

First, [install the latest Docker from the Docker yum repo](https://docs.docker.com/engine/install/rhel/).

Next, [configure Docker to run rootless](https://docs.docker.com/engine/security/rootless/).

Configure subuid and subgid.

Each user that will run Docker must have an entry in `/etc/subuid` and `/etc/subgid`.

## Per user configuration

You must configure docker to use a non-NFS storage location for storing images.

`~/.config/docker/daemon.json`:

```
{
    "data-root": "/var/tmp/${USER}/containers/storage"
}
```

## Create OCI Bundle

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
runc run containerid
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

## Test the bundle locally

```
export OCI_BUNDLES_DIR=~/oci-bundles
export BUNDLE_NAME=rockylinux8
cd $OCI_BUNDLES_DIR/$BUNDLE_NAME
runc spec --rootless
runc run containerid2
```

## Run a bundle on Slurm

```
export OCI_BUNDLES_DIR=~/oci-bundles
export BUNDLE_NAME=rockylinux8

srun -p interactive --container $OCI_BUNDLES_DIR/$BUNDLE_NAME --pty hostname

srun -p interactive --container $OCI_BUNDLES_DIR/$BUNDLE_NAME --pty bash

sbatch -p interactive --container $OCI_BUNDLES_DIR/$BUNDLE_NAME --wrap hostname
```
