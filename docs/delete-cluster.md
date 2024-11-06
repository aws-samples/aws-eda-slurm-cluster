# Delete Cluster

Before deleting the cluster, you should stop the cluster and make sure that no instances are
connected to the clusters head node.

For example, you should deconfigure external login nodes and instances that are creating and updating the users_groups.json file.

If you specified RESEnvironmentName then it will also deconfigure the creation of `users_groups.json` and also deconfigure the VDI
instances so they are no longer using the cluster.

If you configured [DomanJoinedInstance](config.md/#domainjoinedinstance) then the creation of `users_groups.json` will be automatically deconfigured.

If you configured [ExternalLoginNodes](config.md/#externalloginnodes) then they will automatically deconfigured.

If you manually did this configuration, then you should manually deconfigure them also before deleting the cluster.
Otherwise, the NFS mounts of the head node will hang and file system related commands on the instance may hang.
The commands to manually deconfigure can be found in the outputs of the configuration stack.

| Output | Description
|--------|-------------
| command10CreateUsersGroupsJsonDeconfigure | Deconfigure the creation of users_groups.json
| command11ExternalLoginNodeDeconfigure     | Deconfigure external login node

To delete the cluster all you need to do is delete the configuration CloudFormation stack.
This will delete the ParallelCluster cluster stack and all of the configuration resources.
You should not manually delete the ParallelCluster stack.
If you do, the deconfiguration of login nodes and such may fail.

If you deployed the Slurm database stack then you can keep that and use it for other clusters.
If you don't need it anymore, then you can delete the stack.
You will also need to manually delete the RDS database.

If you deployed the ParallelCluster UI then you can keep it and use it with other clusters.
If you don't need it anymore then you can delete the stack.
