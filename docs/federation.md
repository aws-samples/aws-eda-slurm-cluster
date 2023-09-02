# Federation (legacy)

To maximize performance, EDA workloads should run in a single AZ.
If you need to run jobs in more than one AZ then you can use the [federation feature of Slurm](https://slurm.schedmd.com/federation.html) so that you can run jobs on multiple clusters.

The config directory has example configuration files that demonstrate how deploy federated cluster into 3 AZs.

* [source/config/slurm_eda_az1.yml](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/config/slurm_eda_az1.yml)
* [source/config/slurm_eda_az2.yml](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/config/slurm_eda_az2.yml)
* [source/config/slurm_eda_az3.yml](https://github.com/aws-samples/aws-eda-slurm-cluster/blob/main/source/config/slurm_eda_az3.yml)

These clusters should be deployed sequentially.
The first cluster creates a cluster and a slurmdbd instance.
The other 2 clusters are deployed into their own AZ by configuring the SubnetId of the cluster.
They reuse the same slurmdbd instance so that they can reuse a common pool of licenses that
is managed by the slurmdbd instance.

The config files for the 2nd and 3rd clusters provide the stack names from the others
so that the security groups can be updated to allow the required network traffic between the
clusters.

The following shows an example of the configuration.

slurm_eda_az1:
```
  Federation:
    Name: slurmeda
    FederatedClusterStackNames: []
```

slurm_eda_az2:
```
  Federation:
    Name: slurmeda
    FederatedClusterStackNames:
      - slurmedaaz1
```

slurm_eda_az3:
```
  Federation:
    Name: slurmeda
    FederatedClusterStackNames:
      - slurmedaaz1
      - slurmedaaz2
```
