# Implementation Details

## Slurm Infrastructure

All hosts in the cluster must share a uniform user and group namespace.

The munged service must be running before starting any slurm daemons.

## Directory Structure

All of the configuration files, scripts, and logs can be found under the following directory.

```
/opt/slurm/{{ClusterName}}
```

## CloudWatch Metrics

CloudWatch metrics are published by the following sources, but the code is all in `SlurmPlugin.py`.

* Slurm power saving scripts
    * `/opt/slurm/{{ClusterName}}/bin/slurm_ec2_resume.py`
    * `/opt/slurm/{{ClusterName}}/bin/slurm_ec2_resume_fail.py`
    * `/opt/slurm/{{ClusterName}}/bin/slurm_ec2_stop.py`
    * `/opt/slurm/{{ClusterName}}/bin/slurm_ec2_terminate.py`
* Spot monitor running on compute nodes
    * `/opt/slurm/{{ClusterName}}/bin/spot_monitor.py`
* Cron jobs running on the Slurm controller
    * `/opt/slurm/{{ClusterName}}/bin/slurm_ec2_publish_cw.py`
    * `/opt/slurm/{{ClusterName}}/bin/terminate_old_instances.py`

## Down Node Handling

If a node has a problem running jobs then Slurm can mark it DOWN.
This includes if the resume script cannot start an instance for any reason include insufficient EC2 capacity.
This can create 2 issues. First, if the compute node is running then it is wasting EC2 costs.
Second, the node will be unavailable for scheduling which reduces the configured capacity of the cluster.

The cluster is configured to periodically check for DOWN nodes so that they aren't left running and wasting compute costs.
This is done by `/opt/slurm/{{ClusterName}}/bin/slurm_down_nodes_clean.sh`.

The script is called every day by a systemd service:

`/etc/systemd/system/slurm_down_nodes_clean.service`

This service is run at boot and once a day as defined in

`/etc/systemd/system/slurm_down_nodes_clean.timer`

## Insufficient Capacity Exception (ICE) Handling

When Slurm schedules a powered down node it calls the ResumeScript defined in `slurm.conf`.
This is in `/opt/slurm/{{ClusterName}}/bin/slurm_ec2_resume.py`.
The script will attempt to start an EC2 instance and if it receives and InsufficientCapacityException (ICE) then the node will be marked down and Slurm will requeue the job.
However, this is inadequate because if there are a large number of instances of that instance type configured then
Slurm will schedule them and try to start them with the same result.
Eventually all of the powered down nodes will be marked DOWN and depending on the job requirements the job will be allocated
to a node with a different instance type or it will fail.
This can take a substantial amount of time so `SlurmPlugin.py` does the following when it receives an ICE.

* Mark the node as DRAIN so no new jobs are scheduled on it.
* Find all other nodes of the same type and mark them DOWN so that they won't be scheduled after this node is marked DOWN. Nodes that are running will be left alone.
* Requeue jobs on the node that failed to resume because of ICE.
* Mark the node DOWN.
* Power down the node. This is so that Slurm knows that the node is powered down so that when it is marked IDLE it will be powered up when a job is scheduled on it.
* A cron job periodically finds all DOWN Slurm nodes, powers them down, and then marks them IDLE so that they can have jobs scheduled on them. This will allow Slurm to attempt to use more nodes of the instance type in the hopes that there is more capacity. If not, then the cycle repeats.
