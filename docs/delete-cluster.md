# Delete Cluster

Most of the resources can be deleted by simply deleting the cluster's CloudFormation stack.
However, there a couple of resources that must be manually deleted:

* The Slurm RDS database
* The Slurm file system

The deletion of the CloudFormation stack will fail because of these 2 resources and some resources that are used
by them will also fail to delete.
Manually delete the resources and then retry deleting the CloudFormation stack.

## Manually Delete RDS Database

If the database contains production data then it is highly recommended that you back up the data.
You could also keep the database and use it for creating new clusters.


Even after deleting the database CloudFormation may say that it failed to delete.
Confirm in the RDS console that it deleted and then ignore the resource when retrying the stack deletion.

* Go the the RDS console
* Select Databases on the left
* Remove deletion protection
    * Select the cluster's database
    * Click `Modify`
    * Expand `Additional scaling configuration`
    * Uncheck `Scale the capacity to 0 ACIs when cluster is idle`
    * Uncheck `Enable deletion protection`
    * Click `Continue`
    * Select `Apply immediately`
    * Click `Modify cluster`
* Delete the database
    * Select the cluster's database
    * Click `Actions` -> `Delete`
    * Click `Delete DB cluster`

## Manually delete the Slurm file system

### FSx for OpenZfs

* Go to the FSx console
* Select the cluster's file system
* Click `Actions` -> `Delete file system`
* Click `Delete file system`
