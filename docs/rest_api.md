# Slurm REST API

The [Slurm REST API](https://slurm.schedmd.com/rest_api.html) give a programmatic way to access the features of Slurm.
The REST API can be used, for example, to use a Lambda function to submit jobs to the Slurm cluster.

## How to use the REST API

The following shows how to run a simple REST call.

```
source /opt/slurm/{{ClusterName}}/config/slurm_config.sh
unset SLURM_JWT
. <(scontrol token)
wget --header "X-SLURM-USER-TOKEN: $SLURM_JWT" --header "X-SLURM-USER-NAME: $USER" -q $SLURMRESTD_URL/slurm/v0.0.38/diag/ -O -
```

The REST API is documented at [https://slurm.schedmd.com/rest_api.html](https://slurm.schedmd.com/rest_api.html).

The token returned by `scontrol token` has a default lifetime of 3600 seconds (1 hour).
For automation, a cron job on the Slurm controller creates a new token for the `root` and `slurmrestd` users every 30 minutes and stores them in SSM Parameter Store at `/{{ClusterName}}/slurmrestd/jwt/{{user_name}}`.
These tokens can be used by automations such as a Lambda function to access the REST API.
An example Lambda function called `{{ClusterName}}-CallSlurmRestApiLambda` shows how to call various API functions.
You can use this as a template to write functions that use your Slurm cluster for automations.
