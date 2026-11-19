"""Submit multiple JCL jobs concurrently, monitor, download spool, and generate reports."""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed


TERMINAL_STATUSES = {"OUTPUT", "COMPLETED"}
POLL_INTERVAL_SECONDS = 5


def run_zowe(args):
    """Run a Zowe CLI command and return its standard output."""
    command = ["zowe.cmd"] + args
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Could not find the Zowe CLI executable. Install it and ensure 'zowe' is on PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(
            f"Zowe command failed ({' '.join(command)}): {detail}"
        ) from exc
    return result.stdout.strip()


def parse_json(output):
    """Return parsed JSON, or None when the CLI returned plain text."""
    try:
        return json.loads(output)
    except (TypeError, ValueError):
        return None


def extract_field(output, field_name):
    """Extract a specific field (like jobid, status, or retcode) from Zowe JSON."""
    payload = parse_json(output)
    if payload is not None:
        pending = [payload]
        while pending:
            item = pending.pop()
            if isinstance(item, dict):
                for key, value in item.items():
                    if key.lower() == field_name.lower() and isinstance(value, str) and value:
                        return value.strip()
                    pending.append(value)
            elif isinstance(item, list):
                pending.extend(item)
    return None


def extract_job_id(output):
    job_id = extract_field(output, "jobid")
    if job_id:
        return job_id
    match = re.search(r"\bJOB[A-Z0-9]+\b", output, re.IGNORECASE)
    if match:
        return match.group(0)
    raise RuntimeError("Could not find a job ID in the submit response.")


def extract_status(output):
    status = extract_field(output, "status")
    if status:
        return status.upper()
    match = re.search(r"\bstatus\b\s*[:=]\s*([A-Z][A-Z0-9_-]*)", output, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    raise RuntimeError("Could not find a job status in the status response.")


def extract_retcode(output):
    """Extract the job completion code (e.g., CC 0000, ABEND)."""
    retcode = extract_field(output, "retcode")
    return retcode if retcode else "UNKNOWN"


def process_job(job_target):
    """Submit a single job, monitor it, extract the return code, and download the spool."""
    is_local_file = Path(job_target).is_file()
    
    if is_local_file:
        print(f"-> Submitting local file: {job_target}")
        submit_output = run_zowe(["jobs", "submit", "local-file", str(job_target), "--rfj"])
    else:
        print(f"-> Submitting mainframe dataset: {job_target}")
        submit_output = run_zowe(["jobs", "submit", "data-set", str(job_target), "--rfj"])
        
    job_id = extract_job_id(submit_output)
    print(f"[{job_id}] Submitted successfully.")

    # Poll for completion
    while True:
        status_output = run_zowe(["jobs", "view", "job-status-by-jobid", job_id, "--rfj"])
        status = extract_status(status_output)
        if status in TERMINAL_STATUSES:
            break
        time.sleep(POLL_INTERVAL_SECONDS)

    # Get final return code
    retcode = extract_retcode(status_output)
    print(f"[{job_id}] Status: {status} | Completion Code: {retcode} - Downloading spool...")

    # Download spool directly into the "output" directory
    run_zowe(["jobs", "download", "output", job_id, "-d", "output"])
    print(f"[{job_id}] Spool downloaded successfully into output/{job_id}")
    
    # Generate individual job status file inside the downloaded spool folder
    job_dir = Path("output") / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    status_file = job_dir / "completion_status.txt"
    
    success_flag = "SUCCESS" if retcode == "CC 0000" else "ATTENTION/FAILED"
    with open(status_file, "w") as f:
        f.write("========================================\n")
        f.write(f"JOB TARGET:  {job_target}\n")
        f.write(f"JOB ID:      {job_id}\n")
        f.write(f"STATUS:      {status}\n")
        f.write(f"RETURN CODE: {retcode} ({success_flag})\n")
        f.write("========================================\n")
    
    return {"job_target": str(job_target), "job_id": job_id, "status": status, "retcode": retcode}


def main():
    parser = argparse.ArgumentParser(description="Submit multiple JCL files or datasets concurrently.")
    parser.add_argument(
        "jobs",
        nargs="+",
        help="List of local JCL files (e.g. audit.jcl) or mainframe datasets (e.g. Z83220.JCL(MYJOB))"
    )
    args = parser.parse_args()

    print(f"Starting pipeline for {len(args.jobs)} job(s)...")

    # Ensure the output directory exists
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    results = []
    with ThreadPoolExecutor(max_workers=len(args.jobs)) as executor:
        futures = [executor.submit(process_job, job) for job in args.jobs]
        
        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
            except Exception as exc:
                print(f"Job failed: {exc}", file=sys.stderr)
                results.append({"job_target": "ERROR", "job_id": "N/A", "status": "FAILED", "retcode": str(exc)})

    # Generate the Master Pipeline Report inside the "output" directory
    report_file = output_dir / "pipeline_report.txt"
    with open(report_file, "w") as f:
        f.write("========================================\n")
        f.write("      CI/CD PIPELINE EXECUTION REPORT   \n")
        f.write("========================================\n\n")
        for res in results:
            success_flag = "SUCCESS" if res["retcode"] == "CC 0000" else "ATTENTION/FAILED"
            f.write(f"Target:      {res['job_target']}\n")
            f.write(f"Job ID:      {res['job_id']}\n")
            f.write(f"Status:      {res['status']}\n")
            f.write(f"Return Code: {res['retcode']} ({success_flag})\n")
            f.write("-" * 40 + "\n")
            
    print(f"\nPipeline complete. Execution summary saved to {report_file.resolve()}")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)