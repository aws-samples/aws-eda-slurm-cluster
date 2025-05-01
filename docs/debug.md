# Debug

For ParallelCluster and Slurm issues, refer to the official [AWS ParallelCluster Troubleshooting documentation](https://docs.aws.amazon.com/parallelcluster/latest/ug/troubleshooting-v3.html).

## Config stack deploys, but ParallelCluster stack doesn't

This happens when the lambda function that create the cluster encounters an error.
This is usually some kind of configuration error that is detected by ParallelCluster.

* Open the CloudWatch console and go the log groups
* Find the log group named /aws/lambda/*-CreateParallelCluster
* Look for the error

## ParallelCluster stack creation fails

### HeadNodeWaitCondition failed to create

If the stack fails with an error like:

```The following resoure(s) failed to create
[HeadNodeWaitCondition2025050101134602]```

Connect to the head node and look in `/var/log/ansible.log` for errors.

If it shows that it failed waiting for slurmctld to accept requests then check `/var/log/slurmctld.log` for errors.

## Slurm Head Node

If slurm commands hang, then it's likely a problem with the Slurm controller.

Connect to the head node from the EC2 console using SSM Manager or ssh and switch to the root user.

`sudo su`

The first thing to do is to ensure that the Slurm controller daemon is running:

`systemctl status slurmctld`

If it isn't then first check for errors in the user data script. The following command will show the output:

`grep cloud-init /var/log/messages | less`

Then check the controller's logfile.

`/var/log/slurmctld.log`

The following command will rerun the user data.

`/var/lib/cloud/instance/scripts/part-001`

Another way to debug the `slurmctld` daemon is to launch it interactively with debug set high.
The first thing to do is get the path to the slurmctld binary.

```
slurmctld=$(cat /etc/systemd/system/slurmctld.service | awk -F '=' '/ExecStart/ {print $2}')
```

Then you can run slurmctld:

```
$slurmctld -D -vvvvv
```

## Compute Nodes

If there are problems with the compute nodes, connect to them using SSM Manager.

Check for cloud-init errors the same way as for the slurmctl instance.
The compute nodes do not run ansible; their AMIs are configured using ansible.

Also check the `slurmd.log`.

Check that the slurm daemon is running.

`systemctl status slurmd`

### Log Files

| Logfile | Description
|---------|------------
| `/var/log/slurmd.log` | slurmctld logfile

## Job Stuck in Pending State

You can use scontrol to get detailed information about a job.

```
scontrol show job *jobid*
```

## Job Stuck in Completing State

When a node starts it reports it's number of cores and free memory to the controller.
If the memory is less than in slurm_node.conf then the controller will mark the node
as invalid.
You can confirm this by searching for the node in /var/log/slurm/slurmctld.log on the controller.
If this happens, fix the memory in slurm_nodes.conf and restart slurmctld.

```
systemctl restart slurmctld
```

Then reboot the node.

Another cause of this is a hung process on the compute node.
To clear this out, connect to the slurm controller and mark the node down, resume, and then idle.

```
scontrol update node NODENAME state=DOWN reason=hung
scontrol update node NODENAME state=RESUME
scontrol update node NODENAME state=IDLE
```
