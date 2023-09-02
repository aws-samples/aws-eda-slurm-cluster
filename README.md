# AWS EDA Slurm Cluster

This repository contains an AWS Cloud Development Kit (CDK) application that creates a Slurm cluster that is suitable for running production EDA workloads on AWS.

The original (legacy) version of this repo used a custom Python plugin to integrate Slurm with AWS.
The latest version of the repo uses AWS ParallelCluster for the core Slurm infrastructure and AWS integration.
The big advantage of moving to AWS ParallelCluster is that it is a supported AWS service.
Currently, some of the features of the legacy version are not supported in the ParallelCluster version, but
work continues to add features to ParallelCluster so that those features can be supported in the future.

Key features are supported by both versions are:

* Automatic scaling of AWS EC2 instances based on demand
* Use any AWS EC2 instance type including Graviton2
* Use of spot instances
* Handling of spot terminations
* Handling of insufficient capacity exceptions
* Batch and interactive partitions (queues)
* Manages tool licenses as a consumable resource
* User and group fair share scheduling
* Slurm accounting database
* CloudWatch dashboard
* Job preemption
* Manage on-premises compute nodes
* Configure partitions (queues) and nodes that are always on to support reserved instances (RIs) and savings plans (SPs).

Features in the legacy version and not in the ParallelCluster version:

* Heterogenous clusters with mixed OSes and CPU architectures on compute nodes.
* Multi-AZ support. Supported by ParallelCluster, but not currently implemented.
* Multi-region support
* AWS Fault Injection Simulator (FIS) templates to test spot terminations
* Support for MungeKeySsmParameter
* Multi-cluster federation

ParallelCluster Limitations

* Number of "Compute Resources" (CRs) is limited to 50 which limits the number of instance types allowed in a cluster.
  ParallelCluster can have multiple instance types in a CR, but with memory based scheduling enabled, they must all have the same number of cores and amount of memory.
* All Slurm instances must have the same OS and CPU architecture.
* Stand-alone Slurm database daemon instance. Prevents federation.
* Multi-region support. This is unlikely to change because multi-region services run against our archiectural philosophy.
  Federation may be an option but its current implementation limits scheduler performance and doesn't allow cluster prioritization so jobs land on
  random clusters.

Slurm Limitations

* Job preemption based on licenses
* Federation doesn't support prioritizing federated clusters for job scheduling. Result is jobs scattered across the federated clusters.

## Operating System and Processor Architecture Support

This Slurm cluster supports the following OSes:

ParallelCluster:

* Amazon Linux 2
* CentOS 7
* RedHat 7 and 8

Legacy:

* Alma Linux 8
* Amazon Linux 2
* CentOS 7
* RedHat 7 and 8
* Rocky Linux 8

RedHat stopped supporting CentOS 8, so for a similar RedHat 8 binary compatible distribution we support Alma Linux and
Rocky Linux as replacements for CentOS.
These RHEL 8 downstreams are not currently supported by ParallelCluster.

This Slurm cluster supports both Intel/AMD (x86_64) based instances and ARM Graviton2 (arm64/aarch64) based instances.

[Graviton instances require](https://github.com/aws/aws-graviton-getting-started/blob/main/os.md) Amazon Linux 2, RedHat 8, AlmaLinux 8, or RockyLinux 8 operating systems.
RedHat 7 and CentOS 7 do not support Graviton 2.

This provides the following different combinations of OS and processor architecture.

ParallelCluster:

* Amazon Linux 2 and arm64
* Amazon Linux 2 and x86_64
* CentOS 7 and x86_64
* RedHat 7 and x86_64
* RedHat 8 and arm64
* RedHat 8 and x86_64

Legacy:

* Alma Linux 8 and arm64
* Alma Linux 8 and x86_64
* Amazon Linux 2 and arm64
* Amazon Linux 2 and x86_64
* CentOS 7 and x86_64
* RedHat 7 and x86_64
* RedHat 8 and arm64
* RedHat 8 and x86_64
* Rocky Linux 8 and arm64
* Rocky Linux 8 and x86_64

Note that in the ParallelCluster version, all compute nodes must have the same OS and architecture.

## Documentation

[View on GitHub Pages](https://aws-samples.github.io/aws-eda-slurm-cluster/)

You can also view the docs locally,
The docs are in the docs directory. You can view them in an editor or using the mkdocs tool.

I recommend installing mkdocs in a python virtual environment.

```
python3 -m venv ~/.mkdocs_venv
source ~/.mkdocs_venv/bin/activate
pip install mkdocs
```

Then run mkdocs.

```
source ~/.mkdocs_venv/bin/activate
mkdocs serve &
firefox http://127.0.0.1:8000/ &
```

Open a browser to: http://127.0.0.1:8000/

Or you can simply let make do this for you.

```
make local-docs
```

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the [LICENSE](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/LICENSE) file.
