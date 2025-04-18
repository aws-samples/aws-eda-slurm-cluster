#!/bin/bash
###############################################################################
##          Copyright (c) 2024 Exostellar Inc. All rights reserved.          ##
## Email:   support@exostellar.io                                            ##
###############################################################################

XCOMPUTE_HEAD_IP={{ xwo_mgt_ip }}

CERT_PATH=/etc/ssl/certs/

image_name=""
host=""
u_file="user_data.sh"
wo_enabled=false

while [ "$1" != "" ]; do
    case $1 in

        --pool )
            shift
            pool=$1
            ;;
        --profile )
            shift
            profile=$1
            ;;
        -i | --image_name )
            shift
            image_name="$1"
            ;;
        -h | --host )
            shift
            host="$1"
            ;;
        -u | --u_file )
            shift
            u_file="$1"
            ;;
        --cpus )
            shift
            cpus="$1"
            ;;
        --mem )
            shift
            mem="$1"
            ;;
        -w | --wo )
            shift
            wo_enabled=true
            ;;
        * ) echo "USAGE: test_createVm.sh --pool <pool> --profile <profile>  -i <image name> -h <host> -u <user data file> --cpus <int> --mem <mem-in-MB>"
            exit 1
            ;;
    esac
    shift
done

if [ -z "$pool" ] || [ -z "$profile" ] || [ -z "$image_name" ] || [ -z "$host" ] || [ -z "$cpus" ] || [ -z $mem ]; then
    echo "please provide --pool <pool> --profile <profile> -i <image name> -h <host> --cpus <int> --mem <mem-in-MB>"
    exit 2
fi

if [[ ! -f "$CERT_PATH/ExostellarRootCA.crt" || ! -f "$CERT_PATH/ExostellarClient.pem" ]]; then
    echo
    echo "please copy ExostellarRootCA.crt and ExostellarClient.pem to $CERT_PATH"
    echo
    echo "Example:"
    echo "scp -i <your_key.pem> rocky@<head_node_IP>:/etc/nginx/ssl/ExostellarRootCA.crt $CERT_PATH/ExostellarRootCA.crt"
    echo "scp -i <your_key.pem> rocky@<head_node_IP>:/etc/nginx/ssl/client.pem $CERT_PATH/ExostellarClient.pem"
    exit 2
fi

if [ -f $u_file ]; then
    user_data=$(cat $u_file | sed "s/XSPOT_NODENAME/$host/g" | base64 -w 0)
fi

TMP_FILE=$(mktemp).json
OUT_FILE=$(mktemp).json

cat << END > $TMP_FILE
{
    "NodeName": "$host",
    "PoolName": "$pool",
    "ProfileName": "$profile",
    "VM": {
        "CPUs": "$cpus",
        "ImageName": "$image_name",
        "MaxMemory": "$mem",
        "UserData": "$user_data",
        "EnableWO": $wo_enabled,
        "VolumeSize": 4
    }
}
END

echo "########## user_data ##########"
echo $user_data | base64 -d
echo
echo "##########   json    ##########"
cat $TMP_FILE
echo

echo "########## createVm  ##########"
http_code=$(curl -s -w "%{http_code}" -d "@$TMP_FILE" -H 'Content-Type: application/json' -X POST --cacert $CERT_PATH/ExostellarRootCA.crt --cert $CERT_PATH/ExostellarClient.pem https://ExostellarHeadNode/v1/xcompute/vm --resolve ExostellarHeadNode:443:$XCOMPUTE_HEAD_IP -o $OUT_FILE)
if [ $http_code  -ne 200 ]; then
    echo "create FAILED; curl = $http_code"
    exit 3
fi
id=`jq -r '.JobId' $OUT_FILE`
echo -e "** OUT: JobId = $id\n"

for i in {0..59}; do
    echo -ne "Waiting for $host... $((i * 10))s\033[0K\r"
    http_code=$(curl -s -w "%{http_code}" -d "@$TMP_FILE" -H 'Content-Type: application/json' -X GET --cacert $CERT_PATH/ExostellarRootCA.crt --cert $CERT_PATH/ExostellarClient.pem https://ExostellarHeadNode/v1/xcompute/vm/$host?detailedInfo=true --resolve ExostellarHeadNode:443:$XCOMPUTE_HEAD_IP -o $OUT_FILE)
    if [ $http_code -eq 200 ]; then
        if [ "$(jq '.Vm | has("PrivateIpAddress")' $OUT_FILE)" == "true" ]; then
            echo
            echo "##########   done    ##########"
            echo "NodeName: `jq -r '.NodeName' $OUT_FILE`"
            echo "Controller: `jq -r '.Controller.NodeName' $OUT_FILE`"
            echo "Controller IP: `jq -r '.Controller.PrivateIpAddress' $OUT_FILE`"
            echo "Vm IP: `jq -r '.Vm.PrivateIpAddress' $OUT_FILE`"
            break
        fi
    elif [ $http_code -ne 102 ]; then
        echo
        echo "Job FAILED; curl = $http_code"
        exit 4
    fi
    sleep 10
done

rm -f $TMP_FILE $OUT_FILE
