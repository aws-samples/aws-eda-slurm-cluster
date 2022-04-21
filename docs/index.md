# EDA SLURM Cluster

This project can be used to create a SLURM cluster running on AWS that is capable of running production EDA workloads.
Key features are:

* Automatic scaling of AWS EC2 instances based on demand
* Use any AWS EC2 instance type including Graviton2
* Use of spot instances
* Batch and interactive partitions (queues)
* License support
* User and group fair share scheduling
* SLURM accounting database
* CloudWatch dashboard
* Job preemption
* Multi-cluster federation

## Operating System and Processor Architecture Support

This SLURM cluster supports the following OSes:

- Alma Linux 8
* Amazon Linux 2
* CentOS 7
* RedHat 7 and 8
- Rocky Linux 8

This SLURM cluster supports both Intel/AMD (x86_64) based instances and ARM Graviton2 (arm64/aarch64) based instances.

Graviton 2 instances require Amazon Linux 2, CentOS 8, or RedHat 8 operating systems. CentOS/RedHat 7 do not support Graviton 2.

This provides the following different combinations of OS and processor architecture.

* Amazon Linux 2 and arm64
* Amazon Linux 2 and x86_64
* CentOS 7 and x86_64
* Alma Linux 8 and arm64
* Alma Linux 8 and x86_64
* RedHat 7 and x86_64
* RedHat 8 and arm64
* RedHat 8 and x86_64
* Rocky Linux 8 and arm64
* Rocky Linux 8 and x86_64
