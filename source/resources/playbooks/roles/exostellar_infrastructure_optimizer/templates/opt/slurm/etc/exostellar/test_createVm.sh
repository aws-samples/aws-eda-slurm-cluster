#!/bin/bash
###############################################################################
##          Copyright (c) 2024 Exostellar Inc. All rights reserved.          ##
## Email:   support@exostellar.io                                            ##
###############################################################################

XCOMPUTE_HEAD_IP={{ xio_mgt_ip }}

pool=""
profile=""
image_name=""
host=""
u_file="user_data.sh"

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
        * ) echo "USAGE: test_createVm.sh --pool <pool> --profile <profile>  -i <image name> -h <host> -u <user data file>"
            exit 1
            ;;
    esac
    shift
done

if [ -z "$pool" ] || [ -z "$profile" ] || [ -z "$image_name" ] || [ -z "$host" ]; then
    echo "please provide --pool <pool> --profile <profile> -i <image name> -h <host>"
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
        "CPUs": 2,
        "ImageName": "$image_name",
        "MaxMemory": 1990,
        "UserData": "$user_data",
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
http_code=$(curl -s -w "%{http_code}" -d "@$TMP_FILE" -H 'Content-Type: application/json' -X POST http://$XCOMPUTE_HEAD_IP:5000/v1/xcompute/vm -o $OUT_FILE)
if [ $http_code  -ne 200 ]; then
    echo "parse FAILED; curl = $http_code"
fi
id=`jq -r '.JobId' $OUT_FILE`
echo -e "** OUT: JobId = $id\n"

for i in {0..59}; do
    echo -ne "Waiting for $host... $((i * 10))s\033[0K\r"
    http_code=$(curl -s -w "%{http_code}" -X GET http://$XCOMPUTE_HEAD_IP:5000/v1/xcompute/vm/$host?detailedInfo=true -o $OUT_FILE)
    echo
    jq -r '' $OUT_FILE
    if [ $http_code -eq 200 ]; then
        echo "NodeName: `jq -r '.NodeName' $OUT_FILE`"
        echo "Controller: `jq -r '.Controller.NodeName' $OUT_FILE`"
        echo "Controller IP: `jq -r '.Controller.PrivateIpAddress' $OUT_FILE`"
        echo "Vm IP: `jq -r '.Vm.PrivateIpAddress' $OUT_FILE`"
        if [ "$(jq '.Vm | has("PrivateIpAddress")' $OUT_FILE)" == "true" ]; then
            echo "##########   done    ##########"
            break
        fi
        echo
    fi
    sleep 10
done

rm -f $TMP_FILE $OUT_FILE
