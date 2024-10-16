exostellar_infrastructure_optimizer
=========

Configure Exostellar Infrastructure Optimizer (XIO).

This is run on the Slurm head node and uploads configuration files to the XIO managment server using curl commands.

Requirements
------------

Requires root permissions so that it can install the packages required by slurm.

Role Variables
--------------
cluster_name
xio_mgt_ip
