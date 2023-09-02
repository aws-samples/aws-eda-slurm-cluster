# Run Jobs

This page is to give some basic instructions on how to run and monitor jobs on Slurm.
Slurm provides excellent man pages for all of its commands, so if you have questions refer
to the man pages.

## Set Up

Load the environment module for Slurm to configure your PATH and Slurm related environment
variables.

```
module load {{ClusterName}}
```

The modulefile sets environment variables that control the defaults for Slurm commands.
These are documented in the man pages for each command.
If you don't like the defaults then you can set them in your environment (for example, your .bashrc) and
the modulefile won't change any variables that are already set.
The environment variables can always be overridden by the command line options.

For example, the SQUEUE_FORMAT2 and SQUEUE_SORT environment variables are set so that
the default output format is easier to read and contains useful information that isn't
in the default format.

## Key Slurm Commands

The key Slurm commands are

| Command | Description | Example
|---------|-------------|---------
| [salloc](https://slurm.schedmd.com/salloc.html)     | Create a compute allocation. | salloc -c 1 --mem 1G -C 'spot&GHz:3.1'
| [srun](https://slurm.schedmd.com/srun.html)         | Run a job within an allocation. | srun --pty bin/bash
| [sbatch](https://slurm.schedmd.com/sbatch.html)     | Submit a batch script | sbatch -c 1 --mem 1G -C 'spot&GHz:3.1' *script*
| [squeue](https://slurm.schedmd.com/squeue.html)     | Get job status |
| [scancel](https://slurm.schedmd.com/scancel.html)   | Cancel a job | scancel *jobid*
| [sinfo](https://slurm.schedmd.com/sinfo.html)       | Get info about Slurm node status | sinfo -p all
| [scontrol](https://slurm.schedmd.com/scontrol.html) | view or modify Slurm configuration and state | scontrol show node *nodename*
| [sstat](https://slurm.schedmd.com/sstat.html)       | Display various status information about a running job/step
| [sshare](https://slurm.schedmd.com/sshare.html)     | Tool for listing fair share information
| [sprio](https://slurm.schedmd.com/sprio.html)       | View the factors that comprise a job's scheduling priority
| [sacct](https://slurm.schedmd.com/sacct.html)       | Display accounting data for jobs
| [sreport](https://slurm.schedmd.com/sreport.html)   | Generate reports from the Slurm accounting data.
| [sview](https://slurm.schedmd.com/sview.html)       | Graphical tool for viewing cluster state

## sbatch

The most common options for sbatch are listed here.
For more details run `man sbatch`.

| Options | Description | Default
|---------|-------------|---------
| -p, --partition=*partition-names* | Select the partition/partitions to run job on. | Set by slurm.InstanceConfig.DefaultPartition in config file.
| -t, --time=*time* | Set a limit on total run time of the job. | SBATCH_TIMELIMIT="1:0:0" (1 hour)
| -c, --cpus-per-task=*ncpus* | Number of cores. | Default is 1.
| --mem=*size[units]*   | Amount of memory. Default unit is M. Valid units are \[K\|M\|G\|T\]. | SBATCH_MEM_PER_NODE=100M
| -L, --licenses=*license* | Licenses used by the job. |
| -a, --array=*indexes* | Submit job array |
| -C, --constraint=*list* | Features required by the job. Multiple constraints can be specified with AND(&) and OR(|). |
| -d, --dependency=*dependency-list* | Don't start the job until the dependencies have been completed. |
| -D, --chdir=*directory* | Set the working directory of the job |
| --wait | Do not exit until the job finishes, Exit code of sbatch will be the same as the exit code of the job. |
| --wrap | Wrap shell commands in a batch script. |

### Run a simulation build followed by a regression

```
build_jobid=$(sbatch -c 4 --mem 4G -L vcs_build -C 'GHz:4|GHz:4.5' -t 30:0 sim-build.sh)
if sbatch -d "afterok:$build_jobid" -c 1 --mem 100M --wait submit-regression.sh; then
    echo "Regression Passed"
else
    echo "Regression Failed"
fi
```

## srun

The srun is usually used to open a pseudo terminal on a compute node for you to run interactive jobs.
It accepts most of the same options as sbatch to request cpus, memory, and node features.

To open up a pseudo terminal in your shell on a compute node with 4 cores and 16G of memory, execute the following command.

```
srun -c 4 --mem 8G --pty /bin/bash
```

This will queue a job and when it is allocated to a node and the node runs, the job control will be returned to
your shell, but stdin and stdout will be on the compute node.
If you set your DISPLAY environment variable and allow external X11 connections you can use this to
run interactive GUI jobs on the compute node and have the windows on your instance.

```
xhost +
export DISPLAY=$(hostname):$(echo $DISPLAY | cut -d ':' -f 2)
srun -c 4 --mem 8G --pty /bin/bash
emacs . # Or whatever gui application you want to run. Should open a window.
```

Another way to run interactive GUI jobs is to use **srun**'s **--x11** flag to enable X11 forwarding.

```
srun -c 1 --mem 8G --pty --x11 emacs
```

## squeue

The squeue command shows the status of jobs.

The output format can be customized using the **--format** or **--Format** options and you can configure
the default output format using the corresponding **SQUEUE_FORMAT** or **SQUEUE_FORMAT2** environment variables.

```
squeue
```

## sprio

Use `sprio` to get information about a job's priority.
This can be useful to figure out why a job is scheduled before or after another job.

```
sprio -j10,11
```

## sacct

Display accounting information about jobs.
For example, it can be used to get the requested CPU and memory and see the CPU time and memory actually used.

```
sacct -o JobID,User,JobName,AllocCPUS,State,ExitCode,Elapsed,CPUTime,MaxRSS,MaxVMSize,ReqCPUS,ReqMem,SystemCPU,TotalCPU,UserCPU -j 44
```

This shows more details.

```
sacct --allclusters --allusers --federation --starttime 1970-01-01 --format 'Submit,Start,End,jobid%15,State%15,user,account,cluster%15,AllocCPUS,AllocNodes,ExitCode,ReqMem,MaxRSS,MaxVMSize,MaxPages,Elapsed,CPUTime,UserCPU,SystemCPU,TotalCPU' | less
```

For more information:

```
man sacct
```

## sreport

The `sreport` command can be used to generate report from the Slurm database.

## Other Slurm Commands

Use `man command` to get information about these less commonly used Slurm commands.

| Command     | Description
|-------------|-------------
| [sacctmgr](https://slurm.schedmd.com/sacctmgr.html)       | View/modify Slurm account information
| [sattach](https://slurm.schedmd.com/sattach.html)         | Attach to a job step
| [sbcast](https://slurm.schedmd.com/sbcast.html)           | Transmit a file to the nodes allocated to a Slurm job.
| [scrontab](https://slurm.schedmd.com/scrontab.html)       | Manage slurm crontab files
| [sdiag](https://slurm.schedmd.com/sdiag.html)             | Diagnostic tool for Slurm. Shows information related to slurmctld execution.
| seff                                                      |
| sgather                                                   | Transmit a file from the nodes allocated to a Slurm job.
| [sh5util](https://slurm.schedmd.com/sh5util.html)         | Tool for merging HDF5 files from the acct_gather_profile plugin that gathers detailed data for jobs.
| sjobexitmod                                               | Modify derived exit code of a job
| [strigger](https://slurm.schedmd.com/strigger.html)       | Set, get, or clear Slurm trigger information
