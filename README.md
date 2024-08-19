# AWS EDA Slurm Cluster

This repository contains an AWS Cloud Development Kit (CDK) application that creates a Slurm cluster that is suitable for running production EDA workloads on AWS.

The original (legacy) version of this repo that used a custom Python plugin to integrate Slurm with AWS has been deprecated and is no longer supported.
It can be found on the v1 branch.
The latest version of the repo uses AWS ParallelCluster for the core Slurm infrastructure and AWS integration.
The big advantage of moving to AWS ParallelCluster is that it is a supported AWS service.
Currently, some of the features of the legacy version are not supported in the ParallelCluster version, but
work continues to add features to ParallelCluster so that those features may be supported in the future.

Key features are:

* Automatic scaling of AWS EC2 instances based on demand
* Use any AWS EC2 instance type including Graviton2
* Use of spot instances
* Memory-aware scheduling
* License-aware scheduling (Manages tool licenses as a consumable resource)
* User and group fair share scheduling
* Handling of spot terminations
* Handling of insufficient capacity exceptions
* Batch and interactive partitions (queues)
* Slurm accounting database
* CloudWatch dashboard
* Job preemption
* Manage on-premises compute nodes
* Configure partitions (queues) and nodes that are always on to support reserved instances (RIs) and savings plans (SPs).
* Integration with [Research and Engineering Studio on AWS (RES)](https://aws.amazon.com/hpc/res/)

Features in the legacy version and not in the ParallelCluster version:

* Heterogenous clusters with mixed OSes and CPU architectures on compute nodes.
* Multi-AZ support. Supported by ParallelCluster, but not currently implemented.
* Multi-region support
* AWS Fault Injection Simulator (FIS) templates to test spot terminations
* Multi-cluster federation

ParallelCluster Limitations

* Number of "Compute Resources" (CRs) is limited to 50 which limits the number of instance types allowed in a cluster.
  ParallelCluster can have multiple instance types in a compute resource (CR), but with memory based scheduling enabled, they must all have the same number of cores and amount of memory.
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
* RedHat 7, 8 and 9
* Rocky Linux 8 and 9

This Slurm cluster supports both Intel/AMD (x86_64) based instances and Graviton (arm64/aarch64) based instances.

[Graviton instances require](https://github.com/aws/aws-graviton-getting-started/blob/main/os.md) Amazon Linux 2 or RedHat/Rocky >=8 operating systems.
RedHat 7 and CentOS 7 do not support Graviton 2.

This provides the following different combinations of OS and processor architecture.

ParallelCluster:

* Amazon Linux 2 and arm64
* Amazon Linux 2 and x86_64
* CentOS 7 and x86_64
* RedHat 7 and x86_64
* RedHat 8/9 and arm64
* RedHat 8/9 and x86_64
* Rocky 8/9 and arm64
* Rocky 8/9 and x86_64

Note that in ParallelCluster, all compute nodes must have the same OS and architecture.
However, you can create as many clusters as you require.

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
