# AWS EDA Slurm Cluster

This repository contains an AWS Cloud Development Kit (CDK) application that creates a SLURM cluster that is suitable for running production EDA workloads on AWS.
Key features are:

* Automatic scaling of AWS EC2 instances based on demand
* Use any AWS EC2 instance type including Graviton2
* Use of spot instances
* Batch and interactive partitions (queues)
* Managed tool licenses as a consumable resource
* User and group fair share scheduling
* SLURM accounting database
* CloudWatch dashboard
* Manage on-premises compute nodes
* Configure partitions (queues) and nodes that are always on to support reserved instances RIs and savings plans.

## Operating System and Processor Architecture Support

This SLURM cluster supports the following OSes:

* Amazon Linux 2
* RedHat 7 and 8
* CentOS 7
* AlmaLinux 8
* RockyLinux 8

RedHat stopped supporting CentOS 8, so for a similar RedHat 8 binary compatible distribution we support Alma Linux and
Rocky Linux as replacements for CentOS.

This SLURM cluster supports both Intel/AMD (x86_64) based instances and ARM Graviton2 (arm64/aarch64) based instances.

[Graviton 2 instances require](https://github.com/aws/aws-graviton-getting-started/blob/main/os.md) Amazon Linux 2, RedHat 8, AlmaLinux 8, or RockyLinux 8 operating systems.
RedHat 7 and CentOS 7 do not support Graviton 2.

This provides the following different combinations of OS and processor architecture.

* Amazon Linux 2 and x86_64
* Amazon Linux 2 and arm64
* RedHat 7 and x86_64
* RedHat 8 and x86_64
* RedHat 8 and arm64
* CentOS 7 and x86_64
* AlmaLinux 8 and x86_64
* AlmaLinux 8 and arm64
* RockyLinux 8 and x86_64
* RockyLinux 8 and arm64

## Documentation

The docs are in the docs directory. You can view them in an editor or using the mkdocs tool.

I recommend installing mkdocs in a python virtual environment.

```
python3 -m venv ~/.mkdocs_venv
source ~/.mkdocs_venv/bin/activate
pip install mkdocs
```

To view the docs, clone the repository and run mkdocs:

```
source ~/.mkdocs_venv/bin/activate
mkdocs serve &
firefox http://127.0.0.1:8000/ &
```

Open a browser to: http://127.0.0.1:8000/

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.
