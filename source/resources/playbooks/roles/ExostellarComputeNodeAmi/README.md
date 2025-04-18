ExostellarComputeNodeAmi
=========

Configure an instance to create an AMI to be used by Exostellar Infrastructure Optimizer (XIO).
The instance should be launched from a base RHEL AMI, not a ParallelCluster AMI.

* Mount /opt/slurm in /etc/fstab
* Install required packages
* Configure munge
* Configure slurmd.

Requirements
------------
