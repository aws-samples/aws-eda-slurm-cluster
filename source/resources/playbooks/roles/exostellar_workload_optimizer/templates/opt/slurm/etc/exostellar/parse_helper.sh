#!/bin/bash
###############################################################################
##          Copyright (c) 2024 Exostellar Inc. All rights reserved.          ##
## Email:   support@exostellar.io                                            ##
###############################################################################

XCOMPUTE_HEAD_IP={{ xwo_mgt_ip }}

CERT_PATH=/etc/ssl/certs/

ami=""
image_name=""
s_file="script.sh"
pem=""
user_name=""
desc=""

while [ "$1" != "" ]; do
    case $1 in
        -a | --ami )
            shift
            ami="$1"
            ;;
        -d | --desc )
            shift
            desc="$1"
            ;;
        -i | --image_name )
            shift
            image_name="$1"
            ;;
        -p | --pem )
            shift
            pem="$1"
            ;;
        -s | --s_file )
            shift
            s_file="$1"
            ;;
        -u | --user )
            shift
            user_name="$1"
            ;;
        * ) echo "USAGE: parse_helper.sh -a <ami> -i <image name> -s <script file> -p <pem file> -u <user>"
            exit 1
            ;;
    esac
    shift
done

if [ -z "$ami" ] || [ -z "$image_name" ]; then
    echo "please provide -a <ami> -i <image name>"
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

if [ -f $s_file ]; then
    user_data=$(cat $s_file | base64 -w 0)
fi

if [ ! -z $pem ]; then
    user_pem=$(cat $pem | jq -Rsa . | sed -e 's/^"//' -e 's/"$//')
fi

TMP_FILE=$(mktemp).json
OUT_FILE=$(mktemp).json

cat << END > $TMP_FILE
{
    "Description": "$desc",
    "ImageId": "$ami",
    "ImageName": "$image_name",
    "UserData": "$user_data",
    "User": "$user_name",
    "UserKeyPem": "$user_pem"
}
END

echo "########## user_data ##########"
echo $user_data | base64 -d
echo
echo "##########   json    ##########"
cat $TMP_FILE
echo

echo "##########   parse   ##########"
http_code=$(curl -s -w "%{http_code}" -d "@$TMP_FILE" -H 'Content-Type: application/json' -X POST --cacert $CERT_PATH/ExostellarRootCA.crt --cert $CERT_PATH/ExostellarClient.pem https://ExostellarHeadNode/v1/xcompute/parse --resolve ExostellarHeadNode:443:$XCOMPUTE_HEAD_IP -o $OUT_FILE)
if [ $http_code  -ne 200 ]; then
    echo "parse FAILED; curl = $http_code"
    exit 3
fi
id=`jq -r '.JobId' $OUT_FILE`
echo -e "** OUT: JobId = $id\n"

for i in {0..59}; do
    echo -ne "Waiting for $image_name... $((i * 10))s\033[0K\r"
    http_code=$(curl -s -w "%{http_code}" -d "@$TMP_FILE" -H 'Content-Type: application/json' -X GET --cacert $CERT_PATH/ExostellarRootCA.crt --cert $CERT_PATH/ExostellarClient.pem https://ExostellarHeadNode/v1/xcompute/parse/$id --resolve ExostellarHeadNode:443:$XCOMPUTE_HEAD_IP -o $OUT_FILE)
    if [ $http_code -eq 200 ]; then
        echo -e "\n##########   done    ##########"
        curl -s -X GET --cacert $CERT_PATH/ExostellarRootCA.crt --cert $CERT_PATH/ExostellarClient.pem https://ExostellarHeadNode/v1/image/$image_name --resolve ExostellarHeadNode:443:$XCOMPUTE_HEAD_IP -o $OUT_FILE
        cat $OUT_FILE | jq -r 'to_entries|map("\(.key): \(.value|tostring)")|.[]'
        break
    fi
    if [ $http_code -eq 400 ]; then
        echo -e "\n##########   error   ##########"
        err=`jq -r '.Error' $OUT_FILE | cut -d"=" -f2`
        echo "err = $err"
        case $err in
            201)
                echo "image ${image_name} exists!"
                ;;
            202)
                echo "image ${image_name} not authorized!"
                ;;
            203)
                echo "image ${image_name} has ProductCodes!"
                ;;
            *)
                echo "check JobId = $id logs"
                ;;
        esac
        break
    fi
    sleep 10
done

rm -f $TMP_FILE $OUT_FILE
