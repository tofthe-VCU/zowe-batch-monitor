# Mainframe JCL Job Runner

A Python tool that abstracts away the mainframe terminal, allowing you to concurrently submit JCL jobs (both local files and remote datasets) and automatically download their execution logs and completion statuses directly to your local machine.

Instead of manually submitting jobs one by one and hunting through the JES spool, this orchestrator handles multiple workloads simultaneously and generates a clean, readable summary report of your batch results.

## Features

* **Concurrent Execution:** Uses Python's ThreadPoolExecutor to submit and monitor multiple batch jobs at the same time without blocking your terminal.
* **Smart Target Routing:** Automatically detects whether an input is a local JCL file or a remote mainframe dataset and adjusts the Zowe CLI payload accordingly.
* **Automated Log Retrieval:** Downloads the complete JES spool output for each job into isolated local directories.
* **Status Extraction:** Parses mainframe JSON responses to extract exact job return codes (e.g., CC 0000 or ABEND) and builds a master execution report.

## Included Test Workload: The COBOL Audit Pipeline

This repository includes a file named `audit_pipeline.jcl`. While you can use this Python script to run any JCL job, this specific file is included as a complex test case to prove the engine's capabilities. 

Rather than testing with a simple dummy program, `audit_pipeline.jcl` is a full 3-step Compile, Link, and Go (IGYWCLG) procedure containing inline Enterprise COBOL source code and instream data. 

We include this heavy workload to demonstrate that the Python runner can successfully:
1. Manage long-running, multi-step batch executions.
2. Retrieve and organize complex spool results containing multiple dataset types (compiler diagnostics like `SYSPRINT`, runtime business logic like `RPTFILE`, and overarching system logs like `JESMSGLG`).
3. Accurately report the final return code of a complete software build cycle.

## Tech Stack
* Python 3
* Zowe CLI
* IBM z/OS (JES2)

## Usage

You can pass a mix of local JCL files and remote mainframe datasets to the script at the same time:

```bash
python automate_job.py .\audit_pipeline.jcl "Z83220.JCL(TESTJOB)" "ZXP.PUBLIC.JCL(IEFBR14)"