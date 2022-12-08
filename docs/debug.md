# Debug

## Log Files

Most of the key log files are stored on the Slurm file system so that they can be accessed from any instance with the file system mounted.

| Logfile | Description
|---------|------------
| `/opt/slurm/{{ClusterName}}/logs/nodes/{{node-name}}/slurmd.log` | Slurm daemon (slurmd) logfile
| `/opt/slurm/{{ClusterName}}/logs/nodes/{{node-name}}/spot_monitor.log` | Spot monitor logfile
| `/opt/slurm/{{ClusterName}}/logs/nodes/slurmctl[1-2]/cloudwatch.log` | Cloudwatch cron (slurm_ec2_publish_cw.py) logfile
| `/opt/slurm/{{ClusterName}}/logs/nodes/slurmctl[1-2]/power_save.log` | Power saving API logfile
| `/opt/slurm/{{ClusterName}}/logs/nodes/slurmctl[1-2]/slurmctld.log` | Slurm controller daemon (slurmctld) logfile
| `/opt/slurm/{{ClusterName}}/logs/nodes/slurmctl[1-2]/terminate_old_instances.log` | Terminate old instances cron (terminate_old_instances.py) logfile
| `/opt/slurm/{{ClusterName}}/logs/nodes/slurmdbd/slurmdbd.log` | Slurm database daemon (slurmdbd) logfile

## Slurm Controller

If slurm commands hang, then it's likely a problem with the Slurm controller.

The first thing to check is the controller's logfile which is stored on the Slurm file system.

`/opt/slurm/{{ClusterName}}/logs/nodes/slurmctl[1-2]/slurmctld.log`

If the logfile doesn't exist or is empty then you will need to connect to the slurmctl instance using SSM Manager or ssh and switch to the root user.

`sudo su`

The first thing to do is to ensure that the Slurm controller daemon is running:

`systemctl status slurmctld`

If it isn't then first check for errors in the user data script. The following command will show the output:

`grep cloud-init /var/log/messages | less`

The most common problem is that the ansible playbook failed.
Check the ansible log file to see what failed.

`less /var/log/ansible.log`

The following command will rerun the user data.
It will download the playbooks from the S3 deployment bucket and then run it to configure the instance.

`/var/lib/cloud/instance/scripts/part-001`

If the problem is with the ansible playbook, then you can edit it in /root/playbooks and then run
your modified playbook by running the following command.

`/root/slurmctl_config.sh`

The daemon may also be failing because of some other error.
Check the `slurmctld.log` for errors.

Another way to debug the `slurmctld` daemon is to launch it interactively with debug set high.
The first thing to do is get the path to the slurmctld binary.

```
slurmctld=$(cat /etc/systemd/system/slurmctld.service | awk -F '=' '/ExecStart/ {print $2}')
```

Then you can run slurmctld:

```
$slurmctld -D -vvvvv
```

### Slurm Controller Log Files

| Logfile | Description
|---------|------------
| `/var/log/ansible.log` | Ansible logfile
| `/var/log/slurm/cloudwatch.log` | Logfile for the script that uploads CloudWatch events.
| `/var/log/slurm/slurmctld.log` | slurmctld logfile
| `/var/log/slurm/power_save.log` | Slurm plugin logfile with power saving scripts that start, stop, and terminated instances.
| `/var/log/slurm/terminate_old_instances.log` | Logfile for the script that terminates stopped instances.

## Slurm Accounting Database (slurmdbd)

If you are having problems with the slurm accounting database connect to the slurmdbd instance using SSM Manager.

Check for cloud-init and ansible errors the same way as for the slurmctl instance.

Also check the `slurmdbd.log` for errors.

### Log Files

| Logfile | Description
|---------|------------
| `/var/log/ansible.log` | Ansible logfile
| `/var/log/slurm/slurmdbd.log` | slurmctld logfile

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
| `/var/log/slurm/slurmd.log` | slurmctld logfile

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
