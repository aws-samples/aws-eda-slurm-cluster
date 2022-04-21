# ToDo List

List of tasks to be completed.

* Create a configuration to emulate an on-prem cluster
    * Use it to test burting from a static on-prem compute cluster to an AWS federation an multi-AZ/region.

* Configure always on instances for RIs or savings plans.

* Support multi-AZ/region for a single cluster.
    * Instead of federating clusters, add support for compute nodes in multiple availability zones and regions
    * Assumes that networking is configured between VPCs if multiple regions are used
    * Assumes that the storage architecture supports a consistent file system view for all compute nodes.
      This could be shared file systems that are mounted across the AZs and regions or AZ/region specific storage with some kind of data synchronization strategy.

* Support multiple clusters (federation)
    * Implementation is complete and is mostly working but has issues.
    * I see jobs running in other clusters when there are still resources in the primary cluster.
    * Job stuck in pending state with FedJobLock. Can't cancel or requeue, lower priority jobs stuck behind it in PENDING state. This completely hung cluster 1 and 3.

* Configure Preemption
    * https://slurm.schedmd.com/preempt.html
    * Configure preemption
    * Document how to use preemption
    * Example is interactive jobs should preempt regression jobs so that they can get a license and start running without waiting for a job to complte.
    * 1/21/22: It has been configured, but not tested

* Use EC2ImageBuilder to create AMIs

* Add a CustomResource to deconfigure the cluster when the stack is deleted
    * Run an SSM command on all instances in the VPC that runs the DeconfigureClusterCommand before the file systems
      are deleted.
    * I think that the ordering can be done by making the CustomResource dependent on the file systems.
    * This has been added but not tested.

* Put slurm logs on the file system so that they persist and can be accessed from other instances.

* Turn deletion_protection on for database. Have it turned off during testing to ease deletion of test stacks.

* Configure remote licenses that are stored on slurmdbd.
    * https://slurm.schedmd.com/licenses.html
    * Licenses can be configured with sacctmgr and assigned to clusters.

* Create separate script that saves EC2 instance info to a json file that is read by the Slurm plugin.
    * Currently this information is read from the EC2 API at every invocation. This would reduce the API calls and speed up the scripts.

* Create script to update license configuration based on actual available licenses on license server.
  * Use a customizable API for querying the license server and use the returned values to update the slurm license configuration.

* Document heterogeneous Job support usage
    * How is srun used
    * https://slurm.schedmd.com/heterogeneous_jobs.html

* Investigate removing memory as a consumable resource and allocate 1 job per node.
    * This is more scalable according to https://slurm.schedmd.com/big_sys.html because the scheduler doesn't have to keep track of the cores and memory on each node.

* Add support for nss_slurm plugin
    * https://slurm.schedmd.com/nss_slurm.html
    * Removes the need of the user_groups.json file and creating local users and groups.
    * 1/21/22: Implemented but when I remove the local user the username isn't found inside the job. The uid and gid exist, but without names. This results in "I have no name" in an interactive shell. May be acceptable to some, but stilling with the previous method of creating users and groups.
