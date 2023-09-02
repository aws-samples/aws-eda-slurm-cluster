# Job Preemption

The cluster is set up with an interactive partition that has a higher priority than all other partitions.
All other partitions are configured to allow jobs to be preempted by the interactive queue.
When an interactive job is pending because of compute resources then it can preempt another job and use the resources.
The preempted job will be requeued so that it will rerun when resources become available.

Jobs should rarely pend because of lack of compute resources if you've defined enough compute nodes in your configuration.
The more likely reason for a job to pend is if it requires a license and all available licenses are already being used.
However, it appears that Slurm doesn't support preemption based on licenses availability so if the reason a job is pending is
because of licenses then it will not preempt jobs in a lower priority queue even if doing so would free up a license.

## Documentation

[https://slurm.schedmd.com/preempt.html](https://slurm.schedmd.com/preempt.html)
