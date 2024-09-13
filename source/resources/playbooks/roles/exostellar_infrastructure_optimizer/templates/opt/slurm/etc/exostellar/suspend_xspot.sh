#!/bin/bash
###############################################################################
##          Copyright (c) 2024 Exostellar Inc. All rights reserved.          ##
## Email:   support@exostellar.io                                            ##
###############################################################################

SLURM_AWS_LOG=/var/log/slurm/power_save.log

exec 1> >(logger -s -t suspend_xspot.sh) 2>&1

set -x
set -e

SLURM_BIN_PATH="/opt/slurm/{{ cluster_name }}/bin"
SLURM_CONF_PATH="/opt/slurm/{{ cluster_name }}/etc"

XCOMPUTE_HEAD_IP={{ xio_mgt_ip }}

function suspend_xspot()
{
    host=$1

    if [[ "$host" == "xspot-vm"* ]]; then
        echo "xspot suspending $host"
        curl -v -X DELETE  http://$XCOMPUTE_HEAD_IP:5000/v1/xcompute/vm/$host
    else
        echo "ParallelCluster suspending $host"
        /opt/parallelcluster/scripts/slurm/slurm_suspend $host
    fi
}

echo "`date` Suspend invoked $0 $*" >> $SLURM_AWS_LOG

hosts=$(${SLURM_BIN_PATH}/scontrol show hostnames $1)
for host in $hosts
do
    suspend_xspot $host
done
