# AWS EDA Slurm Cluster

This repository contains an AWS Cloud Development Kit (CDK) application that creates a Slurm cluster that is suitable for running production EDA workloads on AWS.
Key features are:

* Automatic scaling of AWS EC2 instances based on demand
* Use any AWS EC2 instance type including Graviton2
* Use of spot instances
* Batch and interactive partitions (queues)
* Managed tool licenses as a consumable resource
* User and group fair share scheduling
* Slurm accounting database
* CloudWatch dashboard
* Job preemption
* Multi-cluster federation
* Manage on-premises compute nodes
* Configure partitions (queues) and nodes that are always on to support reserved instances RIs and savings plans.
* AWS Fault Injection Simulator (FIS) templates to test spot terminations

## Operating System and Processor Architecture Support

This Slurm cluster supports the following OSes:

* Alma Linux 8
* Amazon Linux 2
* CentOS 7
* RedHat 7 and 8
* Rocky Linux 8

RedHat stopped supporting CentOS 8, so for a similar RedHat 8 binary compatible distribution we support Alma Linux and
Rocky Linux as replacements for CentOS.

This Slurm cluster supports both Intel/AMD (x86_64) based instances and ARM Graviton2 (arm64/aarch64) based instances.

[Graviton 2 instances require](https://github.com/aws/aws-graviton-getting-started/blob/main/os.md) Amazon Linux 2, RedHat 8, AlmaLinux 8, or RockyLinux 8 operating systems.
RedHat 7 and CentOS 7 do not support Graviton 2.

This provides the following different combinations of OS and processor architecture.

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

## Documentation

[View on GitHub Pages](https://aws-samples.github.io/aws-eda-slurm-cluster/)

To view the docs locally, clone the repository and run mkdocs:

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
