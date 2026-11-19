# Mainframe JCL Job Runner

A Python tool that uses the Zowe CLI to submit local JCL files and mainframe
datasets, monitor jobs, download JES spool output, and create per-job and
pipeline completion reports.

Instead of manually submitting jobs one by one and looking up their JES spool,
the runner can monitor multiple jobs concurrently and collect their results on
your local machine.

## Features

- **Concurrent execution:** Uses Python's `ThreadPoolExecutor` to submit and
  monitor multiple jobs at once. Concurrency is capped at four jobs by default.
- **Target routing:** Existing local files are submitted as JCL. Other targets
  are submitted as mainframe datasets. Use `file:` or `dsn:` to explicitly
  select a target type when needed.
- **Automated spool retrieval:** Downloads each completed job's JES spool into
  `output/<JOBID>/`.
- **Status and return-code reporting:** Reads job status and return code from
  Zowe JSON responses, writes a completion status file for each job, and creates
  `output/pipeline_report.txt`.
- **Timeouts and failure signaling:** Each job has a one-hour completion timeout
  by default. The script exits with a nonzero code if any job fails or has a
  return code other than `CC 0000`.

## Requirements

- Python 3
- Zowe CLI installed and available as `zowe.cmd` on `PATH`
- An authorized Zowe CLI profile or login with access to the target z/OS system

## Test jobs

The sample JCL files are in [`test_jobs`](./test_jobs/):

- [`testjob.jcl`](./test_jobs/testjob.jcl) — a basic submission test using
  `IEFBR14`.
- [`audit_pipeline.jcl`](./test_jobs/audit_pipeline.jcl) — an inline COBOL
  compile, link, and run job using the `IGYWCLG` procedure. It includes sample
  log records and writes flagged records and a summary to the report output.
  Running it requires the appropriate COBOL compiler/procedure and site
  configuration.
- [`fail_job.jcl`](./test_jobs/fail_job.jcl) — intentionally requests the
  nonexistent program `ZOWEFAIL` to test failure reporting. A normal JES
  execution should produce a failed step/abend and a nonzero return code.

Job-card account and class values in the samples may need to be changed for
your site. Submit test jobs only to an environment where you are authorized to
run them.

## Usage

Run commands from the project root. For example, submit the basic local test:

```powershell
python .\automate_job.py .\test_jobs\testjob.jcl
```

Existing local files are detected automatically. A target that does not exist
locally is treated as a dataset by default; use the `file:` prefix if you want
a missing local path to be reported as an error instead.

Mainframe dataset names can be provided directly, without a prefix:

```powershell
python .\automate_job.py "USER.JCL(MYJOB)"
```

The `dsn:` prefix is optional, but can be used to explicitly select dataset
submission. Use `file:` to explicitly require local-file submission:

```powershell
python .\automate_job.py "dsn:USER.JCL(MYJOB)" "file:.\test_jobs\testjob.jcl"
```

You can mix local files and datasets in one run:

```powershell
python .\automate_job.py .\test_jobs\audit_pipeline.jcl "USER.JCL(MYJOB)"
```

Use `--max-workers` to set how many jobs may run at the same time (default: 4).
If you provide more jobs than this, the rest wait for a worker. Use `--timeout`
to set the maximum time in seconds to wait for each individual job to finish
(default: 3600 seconds, or one hour). This is a per-job limit, not a limit on
the total time for the whole batch of jobs.

```powershell
python .\automate_job.py --max-workers 2 --timeout 1800 .\test_jobs\testjob.jcl
```

In this example, no more than two jobs run concurrently, and each job may run
for up to 30 minutes. Change `2` and `1800` to the limits you need. Both values
must be positive numbers.

## Testing failure reporting

Run the intentionally failing job from the project root:

```powershell
python .\automate_job.py .\test_jobs\fail_job.jcl
```

The runner should download the spool, mark the job as failed in its status and
pipeline reports, and exit nonzero. Check the process result in PowerShell with:

```powershell
$LASTEXITCODE
```

## Output

- `output/<JOBID>/` — downloaded spool files and `completion_status.txt`
- `output/pipeline_report.txt` — summary of all requested jobs, in input order

## Tech stack

- Python 3
- Zowe CLI
- IBM z/OS and JES
