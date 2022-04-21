#!/bin/bash -ex

if ! yum list installed nvme-cli; then
    yum -y install nvme-cli
fi

ssds=( $(nvme list | grep 'Amazon EC2 NVMe Instance Storage' | awk '{print $1}') )
if [ -z "$ssds" ]; then
    echo "No nvme SSDs found"
    # Search for ssd block devices
    ssds=()
    ephemerals=( ephemeral0 ephemeral1 ephemeral2 ephemeral3 )
    for ephemeral in ${ephemerals[@]}; do
        device=$(cat /run/cloud-init/instance-data.json | jq -r ".ds.\"meta-data\".\"block-device-mapping\".\"$ephemeral\"")
        if [ ":$device" = ":" ] || [ ":$device" = ":null" ]; then
            continue
        fi
        if [ -e /dev/$device ]; then
            ssds+=(/dev/${device/sd/xvd})
            continue
        fi
        device=${device/sd/xvd}
        if [ -e /dev/$device ]; then
            ssds+=(/dev/$device)
        fi
    done
fi
{% raw %}
if [[ ${#ssds} == 0 ]]; then
{% endraw %}
    echo "No SSDs found"
    exit 0
fi
{% raw %}
echo "Found ${#ssds[@]} SSDs: ${ssds[@]}"
{% endraw %}
if ! yum list installed lvm2; then
    yum -y install lvm2
fi
for ssd in ${ssds[@]}; do
    if pvs $ssd; then
        echo "Physical volumes already exist: pv$ssd"
    else
         pvcreate $ssd
    fi
done
if vgs vgssd; then
    echo "vgssd volume group already exists"
else
    vgcreate vgssd ${ssds[@]}
fi
if lvs vgssd/tmp; then
    echo "vgssd/tmp logical volume exists"
else
    lvcreate -n tmp -l 100%VG vgssd
    mkfs.ext4 /dev/vgssd/tmp
fi
if [ ! -d /ssd ]; then
    mkdir /ssd
else
    echo "/ssd already exists"
fi
if [ ! -d /mnt/ssd/tmp ]; then
    mkdir -p /mnt/ssd/tmp
else
    echo "/mnt/ssd/tmp already exists"
fi
if ! findmnt --source /dev/vgssd/tmp --target /mnt/ssd/tmp; then
    mount /dev/vgssd/tmp /mnt/ssd/tmp
    chmod a+rwx /mnt/ssd/tmp
fi
if ! findmnt --source /dev/vgssd/tmp --target /ssd; then
    mount /dev/vgssd/tmp /ssd
    chmod a+rwx /ssd
fi
if ! findmnt --source /dev/vgssd/tmp --target /tmp; then
    mount /dev/vgssd/tmp /tmp
    chmod a+rwx /tmp
fi

ssd_size=$(lvs -o lv_size --units b --noheadings --nosuffix vgssd/tmp)


if [ ! -e /tmp/swapfile ]; then
    swap_size=$( expr $ssd_size / 2 )
    fallocate -l $swap_size /tmp/swapfile
    chmod 0600 /tmp/swapfile
    mkswap /tmp/swapfile
    swapon /tmp/swapfile
    free
fi
