# Slurm REST API

The Slurm REST API give a programmatic way to access the features of Slurm.
The REST API can be used, for example, to use a Lambda function to submit jobs to the Slurm cluster.

## Host to use the REST API

The following shows how to run a simple REST call.

```
source /opt/slurm/{{ClusterName}}/config/slurm_config.sh
unset SLURM_JWT
. <(scontrol token)
wget --header "X-SLURM-USER-TOKEN: $SLURM_JWT" --header "X-SLURM-USER-NAME: $USER" -q $SLURMRESTD_URL/slurm/v0.0.38/diag/ -O -
```

The REST API is documented at [https://slurm.schedmd.com/rest_api.html](https://slurm.schedmd.com/rest_api.html).
