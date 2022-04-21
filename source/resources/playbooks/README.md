Ansible Playbooks For VPCs
=================
This playbook updates all instances in the VPC with required configuration and packages.

## TOC

* Quick Start
* Roles
  * common
  * domain_joined
  * nfs_client
  * slurm_submitter
  * workspace

## Quick Start

Paste temporary Admin credentials into your shell from Isengard.

Generate the inventory files.

```
make inventory
```

Do a dryrun:

```
make deploy-check
```

Do a run on your workspace or other instance before deploying to everyting.

```
make deploy limit=hostname
```

Deploy:

```
make deploy
```

## Roles

### [common](roles/common/README.md)

Installs all of the packages neede by EDA tools.

### [domain_joined](roles/domain_joined/README.md)

Configures instance with scripts required to join the domain
and dynamically update DNS records.

### [nfs_client](roles/nfs_client/README.md)

Configure instance as an NFS client using autofs.

### [slurm_submitter](roles/slurm_submitter/README.md)

Configure instance so it can submit jobs to the Slurm cluster.

### [workspace](roles/workspace/README.md)

Configure AWS Workspaces instances for the VPC.

