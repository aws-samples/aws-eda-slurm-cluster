---
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
logs:
  logs_collected:
    files:
      collect_list:
      - file_path: /var/log/cfn-init.log
        log_group_name: cfn-init.log
        log_stream_name: "{instance_id}"
      - file_path: /opt/aws/amazon-cloudwatch-agent/logs/amazon-cloudwatch-agent.log
        log_group_name: amazon-cloudwatch-agent.log
        log_stream_name: "{instance_id}"
      - file_path: /var/log/messages
        log_group_name: messages
        log_stream_name: "{instance_id}"
      - file_path: /var/log/secure
        log_group_name: secure
        log_stream_name: "{instance_id}"
      - file_path: /var/log/slurm/slurmd.log
        log_group_name: slurmd.log
        log_stream_name: "{instance_id}"
metrics:
  append_dimensions:
    InstanceId: "${aws:InstanceId}"
  metrics_collected:
    collectd:
      metrics_aggregation_interval: 60
    cpu:
      measurement:
      - cpu_usage_idle
      - cpu_usage_iowait
      - cpu_usage_user
      - cpu_usage_system
      metrics_collection_interval: 60
      resources: ["*"]
      totalcpu: true
    disk:
      measurement:
      - used_percent
      - inodes_free
      metrics_collection_interval: 60
      resources: ["/"]
    diskio:
      measurement:
      - io_time
      - write_bytes
      - read_bytes
      - writes
      - reads
      metrics_collection_interval: 60
      resources: ["*"]
    netstat:
      measurement:
      - tcp_established
      - tcp_time_wait
      metrics_collection_interval: 60
    swap:
      measurement:
      - swap_used_percent
      metrics_collection_interval: 60
