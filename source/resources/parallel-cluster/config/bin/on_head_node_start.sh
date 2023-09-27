#!/bin/bash -x

set -x

exec 1> >(logger -s -t on_head_node_start.sh) 2>&1

full_script=$(realpath $0)
script_dir=$(dirname $full_script)
base_script=$(basename $full_script)

date
echo "Started on_head_node_start.sh: $full_script"

config_dir=/opt/slurm/config
config_bin_dir=$config_dir/bin

dest_script="$config_bin_dir/on_head_node_start.sh"
if [ $full_script != $dest_script ]; then
    echo "cp $full_script $dest_script"
    cp $full_script $dest_script
    chmod 0700 $dest_script
fi

assets_bucket={{assets_bucket}}
assets_base_key={{assets_base_key}}
playbooks_s3_url={{playbooks_s3_url}}

ansible_head_node_vars_yml_s3_url="s3://$assets_bucket/$assets_base_key/config/ansible/ansible_head_node_vars.yml"
ansible_compute_node_vars_yml_s3_url="s3://$assets_bucket/$assets_base_key/config/ansible/ansible_compute_node_vars.yml"
ansible_submitter_vars_yml_s3_url="s3://$assets_bucket/$assets_base_key/config/ansible/ansible_submitter_vars.yml"

create_user_groups_json_py_s3_url="s3://$assets_bucket/$assets_base_key/config/bin/create_users_groups_json.py"
create_user_groups_py_s3_url="s3://$assets_bucket/$assets_base_key/config/bin/create_users_groups.py"
users_groups_json_s3_url="s3://$assets_bucket/$assets_base_key/config/users_groups.json"

mkdir -p $config_bin_dir

# Download all of the config scripts
config_scripts=(\
    create_or_update_users_groups_json.sh \
    create_users_groups_json.py \
    create_users_groups_json_configure.sh \
    create_users_groups_json_deconfigure.sh \
    create_users_groups.py \
    on_head_node_start.sh \
    on_head_node_configured.sh \
    on_head_node_updated.sh \
    on_compute_node_start.sh \
    on_compute_node_configured.sh \
    submitter_configure.sh \
    submitter_deconfigure.sh \
)
for config_script in ${config_scripts[*]}; do
    dest=$config_bin_dir/$config_script
    aws s3 cp s3://$assets_bucket/$assets_base_key/config/bin/$config_script $dest.new
    chmod 0700 $dest.new
    mv -f $dest.new $dest
done

if ! [ -e $config_dir/users_groups.json ]; then
    aws s3 cp $users_groups_json_s3_url $config_dir/users_groups.json
    $config_bin_dir/create_users_groups.py -i $config_dir/users_groups.json
fi
chmod 0600 $config_dir/users_groups.json

export PATH=/usr/sbin:$PATH

$config_bin_dir/create_users_groups.py -i $config_dir/users_groups.json

# Configure using ansible
if ! yum list installed ansible &> /dev/null; then
    yum install -y ansible || amazon-linux-extras install -y ansible2
fi

# Download ansible playbooks

ANSIBLE_PATH=$config_dir/ansible
PLAYBOOKS_PATH=$ANSIBLE_PATH/playbooks
PLAYBOOKS_ZIP_PATH=$ANSIBLE_PATH/playbooks.zip
aws s3 cp $playbooks_s3_url ${PLAYBOOKS_ZIP_PATH}.new
if ! [ -e $PLAYBOOKS_ZIP_PATH ] || ! diff -q $PLAYBOOKS_ZIP_PATH ${PLAYBOOKS_ZIP_PATH}.new; then
    mv $PLAYBOOKS_ZIP_PATH.new $PLAYBOOKS_ZIP_PATH
    rm -rf $PLAYBOOKS_PATH
    mkdir -p $PLAYBOOKS_PATH
    pushd $PLAYBOOKS_PATH
    unzip $PLAYBOOKS_ZIP_PATH
    chmod -R 0700 $ANSIBLE_PATH
    popd
fi

aws s3 cp $ansible_head_node_vars_yml_s3_url /opt/slurm/config/ansible/ansible_head_node_vars.yml

aws s3 cp $ansible_compute_node_vars_yml_s3_url /opt/slurm/config/ansible/ansible_compute_node_vars.yml

aws s3 cp $ansible_submitter_vars_yml_s3_url /opt/slurm/config/ansible/ansible_submitter_vars.yml

# Don't run ansible until after slurmctld and slurmdbd are up and running successfully.

# Create jwt key for slurmrestd
# jwt key needs to be created before slurmctld can start because we configure the JWT key in extra slurm config settings
slurm_spool_dir=/opt/slurm/var/spool
jwt_key=$slurm_spool_dir/jwt_hs256.key
mkdir -p $slurm_spool_dir
chmod 0755 $slurm_spool_dir
if ! [ -e $jwt_key ]; then
    dd if=/dev/random of=$jwt_key bs=32 count=1
    chown slurm:slurm $jwt_key
    chmod 0600 $jwt_key
fi

/usr/bin/cp -f /etc/munge/munge.key $config_dir/munge.key

date
echo "Finished on_head_node_start.sh: $full_script"

exit 0
