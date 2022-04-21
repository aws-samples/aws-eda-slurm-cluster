# SOCA Integration

Integration with SOCA is straightforward.

Set the following parameters in your config file.

| Parameter | Description | Value
|-----------|-------------|------
| VpcId | VPC id for the SOCA cluster | vpc-xxxxxx
| SubmitterSecurityGroupIds | The ComputeNode security group name and id | *cluster-id*-*ComputeNodeSG*: sg-xxxxxxxx
| ExtraMounts | Add the mount parameters for the /apps and /data directories. This is required for access to the home directory. |

Deploy your slurm cluster.

Connect to the SOCA Scheduler instance and run the commands in the **MountCommand** and **ConfigureSyncSlurmUsersGroups** outputs
of the SLURM stack as root.
These commands will mount the SLURM file system at **/opt/slurm/{{ClusterName}}** and then create
a cron job that runs every 5 minutes and updates **/opt/slurm/{{ClusterName}}/config/users_groups.json**.

Connect to a remote desktop instance and run the commands in the **MountCommand** and **ConfigureSubmitterCommand** outputs
of the SLURM stack.
If all users need to use the cluster then it is probably best to create a custom AMI that is configured with the configuration
commands.

You are now ready to run jobs.
