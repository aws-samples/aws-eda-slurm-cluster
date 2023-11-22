# SOCA Integration

[Scale Out Computing on AWS (SOCA)](https://aws.amazon.com/solutions/implementations/scale-out-computing-on-aws/) is an AWS solution that
was the basis for the [Research and Engineering Studion (RES)](https://docs.aws.amazon.com/res/latest/ug/overview.html) service.
Unless you are already a SOCA user, it is highly recommended that you use RES, which is a fully supported AWS service.

Integration with SOCA is straightforward.

Set the following parameters in your config file.

| Parameter | Description | Value
|-----------|-------------|------
| VpcId | VPC id for the SOCA cluster | vpc-xxxxxx
| SubmitterSecurityGroupIds | The ComputeNode security group name and id | *cluster-id*-*ComputeNodeSG*: sg-xxxxxxxx
| ExtraMounts | Add the mount parameters for the /apps and /data directories. This is required for access to the home directory. |

Deploy your slurm cluster.

Connect to the SOCA Scheduler instance and follow the instructions to [Create users_groups.json](deploy-parallel-cluster.md#create-users_groupsjson).

Connect to a remote desktop instance and follow the instructions in [Configure submission hosts to use the cluster](deploy-parallel-cluster.md#configure-submission-hosts-to-use-the-cluster).
If all users need to use the cluster then it is probably best to create a custom AMI that is configured with the configuration
commands.

You are now ready to run jobs from your SOCA desktop.
