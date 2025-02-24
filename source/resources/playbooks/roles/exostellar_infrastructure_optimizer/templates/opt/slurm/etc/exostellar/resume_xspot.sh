#!/bin/bash
###############################################################################
##          Copyright (c) 2024 Exostellar Inc. All rights reserved.          ##
## Email:   support@exostellar.io                                            ##
###############################################################################

SLURM_AWS_LOG=/var/log/slurm/power_save.log

exec 1> >(logger -s -t resume_xspot.sh) 2>&1

set -x
set -e

SLURM_BIN_PATH="/opt/slurm/{{ cluster_name }}/bin"
SLURM_CONF_PATH="/opt/slurm/{{ cluster_name }}/etc"

XCOMPUTE_HEAD_IP={{ xio_mgt_ip }}

function join_by_char()
{
    local IFS=$1
    shift
    echo "$*"
}

function resume_xspot()
{
    host=$1

    echo "xspot resuming $host"

    host_fields=($(echo $host | tr '-' ' '))
{% raw %}
    pool_name_fields=("${host_fields[@]:2:${#host_fields[@]}-3}")
{% endraw %}
    pool_name=$(join_by_char '-' "${pool_name_fields[@]}")
    echo "PoolName=$pool_name"
    profile_name=''
    image_name=''
    cpus=''
    mem=''
    vol_size=''
{% for pool_config in xio_config.Pools %}
    if [[ $pool_name == '{{ pool_config.PoolName }}' ]]; then
        profile_name='{{ pool_config.ProfileName }}'
        image_name='{{ pool_config.ImageName }}'
        cpus={{ pool_config.CPUs }}
        mem={{ pool_config.MaxMemory }}
        vol_size={{ pool_config.VolumeSize }}
    fi
{% endfor %}
    if [[ -z $profile_name ]]; then
        echo "error: No profile_name for $host"
        return 1
    fi
    if [[ -z $image_name ]]; then
        echo "error: No image_name for $host"
        return 1
    fi
    if [[ -z $cpus ]]; then
        echo "error: No cpus for $host"
        return 1
    fi
    if [[ -z $mem ]]; then
        echo "error: No mem for $host"
        return 1
    fi
    if [[ -z $vol_size ]]; then
        echo "error: No vol_size for $host"
        return 1
    fi
    echo "ProfileName=$profile_name"
    echo "ImageName=$image_name"
    echo "CPUs=$cpus"
    echo "MaxMemory=$mem"
    echo "VolumeSize=$vol_size"

    TMP_USER_DATA_FILE=$(mktemp).sh
    cp ${SLURM_CONF_PATH}/exostellar/xspot-vm_user_data.sh $TMP_USER_DATA_FILE
    sed -i "s/XSPOT_NODENAME/$host/g" $TMP_USER_DATA_FILE
    cat $TMP_USER_DATA_FILE
    user_data=$(cat $TMP_USER_DATA_FILE | base64 -w 0)

    TMP_FILE=$(mktemp).json
    cat << END > $TMP_FILE
{
    "NodeName": "$host",
    "PoolName": "$pool_name",
    "ProfileName": "$profile_name",
    "VM": {
        "CPUs": $cpus,
        "ImageName": "$image_name",
        "MaxMemory": $mem,
        "UserData": "$user_data",
        "VolumeSize": $vol_size
    }
}
END
    cat $TMP_FILE
    mapfile -t curl_out < <(curl -s -w '\n%{http_code}' -d "@$TMP_FILE" -H 'Content-Type: application/json' -X POST http://$XCOMPUTE_HEAD_IP:5000/v1/xcompute/vm)
    echo "${curl_out[@]}"
    http_code=${curl_out[-1]}
    echo "http_code=$http_code"
    if [ $http_code -ne 200 ]; then
        echo "`date` error: Resume FAILED with status = $http_code: ${curl_out[@]}" >> $SLURM_AWS_LOG
    fi
    rm -f $TMP_USER_DATA_FILE
    rm -f $TMP_FILE
}

echo "`date` Resume invoked $0 $*" >> $SLURM_AWS_LOG
echo "SLURM_RESUME_FILE=${SLURM_RESUME_FILE}"

{% raw %}
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
    echo "ParallelCluster resuming $pc_hostlist"
    /opt/parallelcluster/scripts/slurm/slurm_resume $pc_hostlist
fi

if [[ ${#xspot_hostnames[@]} -gt 0 ]]; then
    for hostname in ${xspot_hostnames[@]}; do
        resume_xspot $hostname
    done
fi
{% endraw %}
