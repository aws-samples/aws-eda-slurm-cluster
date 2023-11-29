ParallelClusterCreateUsersGroupsJsonConfigure
=========

Configure the server that is periodically updating the users_groups.json file.
Creates the file and a cron job that refreshes it hourly.

* Mounts the cluster's /opt/slurm export at /opt/slurm/{{ClusterName}}
* Updates the /etc/fstab so that the mount works after a reboot.
* Creates a crontab to refresh /opt/slurm/{{ClusterName}}/config/users_groups.json is refreshed hourly.

Requirements
------------

This is meant to be run on a server that is joined to your domain so that it
has access to info about all of the users and groups.
For SOCA, this is the scheduler instance.
For RES, this is the {{EnvironmentName}}-cluster-manager instance.
