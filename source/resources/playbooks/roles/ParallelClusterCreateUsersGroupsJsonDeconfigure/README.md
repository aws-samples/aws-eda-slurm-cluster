ParallelClusterCreateUsersGroupsJsonDeconfigure
=========

Deconfigure the server that is periodically updating the users_groups.json file.
Just removes the crontab entry on the server.

* Copies ansible playbooks to /tmp because the cluster's mount is removed by the playbook.
* Remove crontab that refreshes /opt/slurm/{{ClusterName}}/config/users_groups.json.
* Remove /opt/slurm/{{ClusterName}} from /etc/fstab and unmount it.

Requirements
------------

This is meant to be run on a server that is joined to your domain so that it
has access to info about all of the users and groups.
