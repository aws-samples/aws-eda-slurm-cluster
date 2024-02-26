# Delete Cluster

To delete the cluster all you need to do is delete the configuration CloudFormation stack.
This will delete the ParallelCluster cluster and all of the configuration resources.

If you specified RESEnvironmentName then it will also deconfigure the creation of `users_groups.json` and also deconfigure the VDI
instances so they are no longer using the cluster.

If you deployed the Slurm database stack then you can keep that and use it for other clusters.
If you don't need it anymore, then you can delete the stack.
You will also need to manually delete the RDS database.

If you deployed the ParallelCluster UI then you can keep it and use it with other clusters.
If you don't need it anymore then you can delete the stack.
