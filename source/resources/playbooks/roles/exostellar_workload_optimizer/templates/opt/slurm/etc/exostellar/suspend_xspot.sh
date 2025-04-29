#!/bin/bash
###############################################################################
##          Copyright (c) 2024 Exostellar Inc. All rights reserved.          ##
## Email:   support@exostellar.io                                            ##
###############################################################################

SLURM_AWS_LOG=/var/log/slurm/power_save.log

exec 1> >(logger -s -t suspend_xspot.sh) 2>&1

set -x
set -e

# NOTE: ExostellarRootCA.crt and ExostellarClient.pem are now required.
CERT_PATH=/etc/ssl/certs/

SLURM_BIN_PATH="/opt/slurm/{{ cluster_name }}/bin"
SLURM_CONF_PATH="/opt/slurm/{{ cluster_name }}/etc"

XCOMPUTE_HEAD_IP={{ xwo_mgt_ip }}

function suspend_xspot()
{
    hostname=$1

    echo "xspot suspending $hostname"

    mapfile -t curl_out < <(curl -s -w "%{http_code}" -H 'Content-Type: application/json' -X DELETE --cacert $CERT_PATH/ExostellarRootCA.crt --cert $CERT_PATH/ExostellarClient.pem https://ExostellarHeadNode/v1/xcompute/vm/$hostname --resolve ExostellarHeadNode:443:$XCOMPUTE_HEAD_IP -o /dev/null)
    echo "$curl_out"
    http_code=${curl_out[-1]}
    echo "http_code=$http_code"
    if [ $http_code -ne 200 ]; then
        echo "`date` Suspend $hostname FAILED; curl = $http_code" >> $SLURM_AWS_LOG
    fi
}

echo "`date` Suspend invoked $0 $*" >> $SLURM_AWS_LOG

{% raw -%}
hostnames=$(${SLURM_BIN_PATH}/scontrol show hostnames $1)
xspot_hostnames=( )
pc_hostnames=( )
for hostname in $hostnames
do
    if [[ "$hostname" == "xspot-vm"* ]] || [[ "$hostname" == "xio"* ]] || [[ "$hostname" == "xwo"* ]]; then
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
