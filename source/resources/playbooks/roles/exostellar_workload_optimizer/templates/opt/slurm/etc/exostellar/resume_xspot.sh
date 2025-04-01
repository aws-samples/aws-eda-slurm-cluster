#!/bin/bash
###############################################################################
##          Copyright (c) 2024 Exostellar Inc. All rights reserved.          ##
## Email:   support@exostellar.io                                            ##
###############################################################################

SLURM_AWS_LOG=/var/log/slurm/power_save.log

exec 1> >(logger -s -t resume_xspot.sh) 2>&1

set -x
set -e

# NOTE: ExostellarRootCA.crt and ExostellarClient.pem are now required.
CERT_PATH=/etc/ssl/certs/

SLURM_BIN_PATH="/opt/slurm/{{ cluster_name }}/bin"
SLURM_CONF_PATH="/opt/slurm/{{ cluster_name }}/etc"

XCOMPUTE_HEAD_IP={{ xwo_mgt_ip }}

export AWS_DEFAULT_REGION={{ region }}

function join_by_char()
{
    local IFS=$1
    shift
    echo "$*"
}

# Function to check if secret exists and get its value
get_secret() {
    local secret_name="{{ exostellar_vm_root_password_secret }}"

    # Try to get the secret value
    if secret_value=$(sudo aws secretsmanager get-secret-value --region $AWS_DEFAULT_REGION --secret-id "$secret_name" --query 'SecretString' --output text 2>/dev/null); then
        echo "$secret_value"
        return 0
    else
        echo "Secret $secret_name not found or access denied" >&2
        return 1
    fi
}

function resume_xspot()
{
    host=$1

    echo "xspot resuming $host"

    host_fields=($(echo $host | tr '-' ' '))
{% raw %}
    host_prefix=${host_fields[0]}
    if [[ $host_prefix == 'xio' ]] || [[ $host_prefix == 'xwo' ]]; then
        pool_name_fields=("${host_fields[@]:1:${#host_fields[@]}-2}")
    elif [[ $host_prefix == 'xspot' ]] && [[ ${host_fields[1]} == 'vm' ]]; then
        pool_name_fields=("${host_fields[@]:2:${#host_fields[@]}-3}")
    else
        echo "error: Invalid hostname for xspot"
        return
    fi
    pool_name=$(join_by_char '-' "${pool_name_fields[@]}")
    echo "PoolName=$pool_name"
{% endraw %}

    profile_name=''
    image_name=''
    cpus=''
    mem=''
    vol_size=''
{% for pool_name, pool_config in xwo_config.Pools.items() %}
    if [[ $pool_name == '{{ pool_name }}' ]]; then
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
    if ! [[ -z $secret_value ]]; then
        # Replace just the first occurrence
        sed -i "0,/EXOSTELLAR_VM_ROOT_PASSWORD/{s/EXOSTELLAR_VM_ROOT_PASSWORD/$secret_value/}" $TMP_USER_DATA_FILE
    fi
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
        "EnableWO": true,
        "ImageName": "$image_name",
        "MaxMemory": $mem,
        "UserData": "$user_data",
        "VolumeSize": $vol_size
    }
}
END
    cat $TMP_FILE

    # mapfile: read lines from stdin into an array. -t strips trailing newline
    mapfile -t curl_out < <(curl -s -w '\n%{http_code}' -d "@$TMP_FILE" -H 'Content-Type: application/json' -X POST --cacert $CERT_PATH/ExostellarRootCA.crt --cert $CERT_PATH/ExostellarClient.pem https://ExostellarHeadNode/v1/xcompute/vm --resolve ExostellarHeadNode:443:$XCOMPUTE_HEAD_IP -o /dev/null)
    http_code=${curl_out[-1]}
    echo "http_code=$http_code"
    if [ $http_code -ne 200 ]; then
        echo "`date` Resume $host FAILED with status = $http_code" >> $SLURM_AWS_LOG
    fi
    rm -f $TMP_USER_DATA_FILE
    rm -f $TMP_FILE
}

echo "`date` Resume invoked $0 $*" >> $SLURM_AWS_LOG
echo "SLURM_RESUME_FILE=${SLURM_RESUME_FILE}"

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

# Put all ParallelCluster hostname back into hostlist format and send to ParallelCluster
if [[ ${#pc_hostnames[@]} -gt 0 ]]; then
    pc_hostlist=$(${SLURM_BIN_PATH}/scontrol show hostlistsorted $(IFS=,; echo "${pc_hostnames[*]}"))
    echo "ParallelCluster resuming $pc_hostlist"
    /opt/parallelcluster/scripts/slurm/slurm_resume $pc_hostlist
fi

if [[ ${#xspot_hostnames[@]} -gt 0 ]]; then
    # Get the secret value
    # Ignore errors from get_secret
    set +e
    # Don't print the secret to the logfile
    set +x
    secret_value=$(get_secret)
    set -x
    set -e

    # Check if secret retrieval was successful
    if [ $? -eq 0 ]; then
        echo "Retrieved VM root password from SecretsManager"
    else
        echo "Failed to retrieve VM root password from SecretsManager"
        unset secret_value
    fi

    for hostname in ${xspot_hostnames[@]}; do
        resume_xspot $hostname
    done
fi
{% endraw %}
