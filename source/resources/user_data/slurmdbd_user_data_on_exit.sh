# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

    if [[ $exitCode -ne 0 ]] && [[ ":{{ERROR_SNS_TOPIC_ARN}}" != ":" ]]; then
        aws sns publish --region {{AWS_DEFAULT_REGION}} --topic-arn {{ERROR_SNS_TOPIC_ARN}} --subject "$INSTANCE_NAME UserData failed" --message "See /var/log/cloud-init.log or grep cloud-init /var/log/messages | less for more info."
    fi

    if ! needs-restarting -r; then
        reboot
    fi
