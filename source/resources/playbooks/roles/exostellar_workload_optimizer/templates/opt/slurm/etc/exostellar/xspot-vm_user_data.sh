#!/bin/bash -ex
###############################################################################
##          Copyright (c) 2024 Exostellar Inc. All rights reserved.          ##
## Email:   support@exostellar.io                                            ##
###############################################################################

# Do not edit this file
# If you need to customize the VM image add your customizations to xspot-vm_custom_user_data.sh.

secret_value='EXOSTELLAR_VM_ROOT_PASSWORD'
if [[ $secret_value != 'EXOSTELLAR_VM_ROOT_PASSWORD' ]]; then
    echo "$secret_value" | passwd --stdin root
fi

# Patch eth0 configuration to remove workers IP address
if ip addr show dev eth0 | grep -q 'global secondary noprefixroute eth0'; then
    worker_ip_address=$(ip addr show dev eth0 | grep 'global noprefixroute eth0' | awk '{print $2}')
    vm_ip_address=$(ip addr show dev eth0 | grep 'global secondary noprefixroute eth0' | awk '{print $2}')
    echo "Found 2 ip addresses for eth0"
    ip addr show dev eth0
    echo "Worker ip address: $worker_ip_address"
    echo "VM     ip address: $vm_ip_address"
    echo "Deleting worker IP address from etho0 configuration"
    ip addr del $worker_ip_address dev eth0
else
    echo "No secondary IP address found"
fi

systemctl stop amazon-ssm-agent || true
systemctl disable amazon-ssm-agent || true

if ! [[ -d /opt/slurm ]]; then
    mkdir /opt/slurm
fi
if ! mountpoint /opt/slurm; then
    mount -t nfs -o defaults head_node.{{ cluster_name }}.pcluster:/opt/slurm /opt/slurm
fi

if ! [[ -d /opt/parallelcluster/shared ]]; then
    mkdir -p /opt/parallelcluster/shared
fi
if ! mountpoint /opt/parallelcluster/shared; then
    mount -t nfs -o defaults head_node.{{ cluster_name }}.pcluster:/opt/parallelcluster/shared /opt/parallelcluster/shared
fi

if ! [[ -d /opt/intel ]]; then
    mkdir -p /opt/intel
fi
if ! mountpoint /opt/intel; then
    mount -t nfs -o defaults head_node.{{ cluster_name }}.pcluster:/opt/intel /opt/intel
fi

{% for mount_config in xwo_config.ExtraMounts %}
if ! [[ -d "{{ mount_config.dest }}" ]]; then
    mkdir -p "{{ mount_config.dest }}"
fi
mount -t "{{ mount_config.type }}" -o "{{ mount_config.options }}" "{{ mount_config.src }}" "{{ mount_config.dest }}"

{% endfor %}
if [[ -e /opt/slurm/config/users_groups.json ]]; then
    /opt/slurm/config/bin/create_users_groups.py -i /opt/slurm/config/users_groups.json
fi

if ! [[ -e /var/log/parallelcluster ]]; then
    mkdir -p /var/log/parallelcluster
    chmod 0777 /var/log/parallelcluster
fi

if [[ -e /opt/slurm/etc/exostellar/custom_xwo_user_data.sh ]]; then
    /opt/slurm/etc/exostellar/custom_xwo_user_data.sh
fi

if ! [[ -e /etc/profile.d/slurm.sh ]]; then
    cat <<EOF > /etc/profile.d/slurm.sh
PATH=$PATH:/opt/slurm/bin
MANPATH=$MANPATH:/opt/slurm/share/man

export PATH MANPATH
EOF
fi
source /etc/profile.d/slurm.sh

if ! [[ -e /etc/profile.d/slurm.csh ]]; then
    cat <<EOF > /etc/profile.d/slurm.csh
set path = ($path /opt/slurm/bin)
if ( ${?MANPATH} ) then
  setenv MANPATH ${MANPATH}:/opt/slurm/share/man
else
  setenv MANPATH :/opt/slurm/share/man
endif
EOF
fi

cat <<EOF > /etc/sysconfig/slurmd
SLURMD_OPTIONS='-N XSPOT_NODENAME'
EOF

hostnamectl set-hostname XSPOT_NODENAME

echo XSPOT_NODENAME > /var/run/nodename

scontrol update nodename=XSPOT_NODENAME nodeaddr=$(hostname -I)

systemctl start slurmd
