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
    hostname=$1

    echo "xspot suspending $hostname"
    curl -v -X DELETE  http://$XCOMPUTE_HEAD_IP:5000/v1/xcompute/vm/$hostname
}

echo "`date` Suspend invoked $0 $*" >> $SLURM_AWS_LOG

{% raw -%}
hostnames=$(${SLURM_BIN_PATH}/scontrol show hostnames $1)
xspot_hostnames=( )
pc_hostnames=( )
for hostname in $hostnames
do
    if [[ "$hostname" == "xspot-vm"* ]]; then
        xspot_hostnames+=( $hostname )
    else
        pc_hostnames+=( $hostname )
    fi
done

if [[ ${#pc_hostnames[@]} -gt 0 ]]; then
    pc_hostlist=$(${SLURM_BIN_PATH}/scontrol show hostlistsorted $(IFS=,; echo "${pc_hostnames[*]}"))
    echo "ParallelCluster suspending $pc_hostlist"
    /opt/parallelcluster/scripts/slurm/slurm_suspend $pc_hostlist
fi

if [[ ${#xspot_hostnames[@]} -gt 0 ]]; then
    for hostname in ${xspot_hostnames[@]}; do
        suspend_xspot $hostname
    done
fi
{% endraw %}
