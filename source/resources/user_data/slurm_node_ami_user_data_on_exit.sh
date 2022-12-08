# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

    if [[ $exitCode -ne 0 ]] && [[ ":{{ERROR_SNS_TOPIC_ARN}}" != ":" ]]; then
        instance_id=$(curl --silent http://169.254.169.254/latest/meta-data/instance-id)
        msg_file=$(mktemp)
        echo -e "\nINSTANCE NAME: $INSTANCE_NAME" > $msg_file
        echo -e "\nINSTANCE ID:   $instance_id"   >> $msg_file
        echo -e "\ngrep cloud-init /var/log/messages | tail -n 200:\n\n" >> $msg_file
        grep cloud-init /var/log/messages |tail -n 200 >> $msg_file
        if [ -e /var/log/cloud-init.log ]; then
            echo -e "\n\n\ntail -n 200 /var/log/cloud-init.log:\n\n" >> $msg_file
            tail -n 200 /var/log/cloud-init.log >> $msg_file
        fi
        # --subject is limited to 100 characters
        aws sns publish --region {{AWS_DEFAULT_REGION}} --topic-arn {{ERROR_SNS_TOPIC_ARN}} --subject "$instance_id UserData failed" --message "file://$msg_file"
        rm $msg_file
    fi

    if ! needs-restarting -r; then
        reboot
    fi
