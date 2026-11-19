"""Submit multiple JCL jobs concurrently, monitor, download spool, and generate reports."""

import argparse
import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed


TERMINAL_STATUSES = {"OUTPUT", "COMPLETED"}
POLL_INTERVAL_SECONDS = 5
ZOWE_COMMAND_TIMEOUT_SECONDS = 120
DEFAULT_JOB_TIMEOUT_SECONDS = 3600
DEFAULT_MAX_WORKERS = 4
DEFAULT_LOCAL_JCL_DIRS = (Path("test_jobs"),)

# Matches standard z/OS sequential datasets (HLQ.QUAL2.QUAL3) and PDS members (HLQ.PDS(MEMBER))
ZOS_DATASET_PATTERN = re.compile(
    r"^[A-Z@#$][A-Z0-9@#$]{0,7}(\.[A-Z@#$][A-Z0-9@#$]{0,7})*(\([A-Z@#$][A-Z0-9@#$]{0,7}\))?$",
    re.IGNORECASE,
)


def positive_int(value):
    """Parse a positive integer for CLI options."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def positive_float(value):
    """Parse a positive number of seconds for CLI options."""
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive number")
    return parsed


def is_valid_zos_dataset(name):
    """Validate z/OS dataset naming rules (max 44 chars before member, 1-8 char qualifiers)."""
    base_name = name.split("(", 1)[0]
    if not base_name or len(base_name) > 44:
        return False
    return bool(ZOS_DATASET_PATTERN.match(name))


def resolve_job_target(job_target):
    """Resolve whether a target is a local JCL file or a valid z/OS dataset."""
    raw = job_target.strip()
    if not raw:
        raise ValueError("Job target cannot be empty.")

    if raw.startswith("dsn:"):
        dataset = raw[4:].strip()
        if not is_valid_zos_dataset(dataset):
            raise ValueError(f"Invalid z/OS dataset name: '{dataset}'")
        return "dataset", dataset

    if raw.startswith("file:"):
        file_str = raw[5:].strip()
        target_path = Path(file_str).expanduser()
        if not target_path.is_file():
            raise FileNotFoundError(f"Local JCL file not found: {target_path}")
        return "file", target_path

    # Unprefixed target: check exact local path first
    target_path = Path(raw).expanduser()
    if target_path.is_file():
        return "file", target_path
    if target_path.exists():
        raise FileNotFoundError(f"Local JCL target is not a file: {target_path}")

    # Fallback: if a bare filename (e.g., 'audit_pipeline.jcl' or '.\audit_pipeline.jcl')
    # was passed, check default local JCL directories like ./test_jobs/
    if target_path.parent in (Path("."), Path("")):
        for fallback_dir in DEFAULT_LOCAL_JCL_DIRS:
            candidate = fallback_dir / target_path.name
            if candidate.is_file():
                return "file", candidate

    # Reject obvious local paths or .jcl filenames instead of mistaking them for datasets
    looks_like_local_path = (
        "\\" in raw
        or "/" in raw
        or raw.startswith(".")
        or raw.lower().endswith(".jcl")
    )
    if looks_like_local_path:
        searched = ", ".join(str(d) for d in (Path("."), *DEFAULT_LOCAL_JCL_DIRS))
        raise FileNotFoundError(
            f"Local JCL file not found: '{raw}' (searched in: {searched}). "
            "Use 'dsn:<DATASET>' if you intended a mainframe dataset."
        )

    if is_valid_zos_dataset(raw):
        return "dataset", raw

    raise ValueError(
        f"Target '{raw}' was not found as a local file and is not a valid z/OS dataset name."
    )


def run_zowe(args, timeout=ZOWE_COMMAND_TIMEOUT_SECONDS):
    """Run a Zowe CLI command and return its standard output."""
    command = ["zowe.cmd"] + args
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
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
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Zowe command timed out after {timeout:g} seconds: {' '.join(command)}"
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


def process_job(job_target, job_timeout_seconds):
    """Submit a single job, monitor it, extract the return code, and download the spool."""
    target_type, resolved_target = resolve_job_target(job_target)

    if target_type == "dataset":
        print(f"-> Submitting mainframe dataset: {resolved_target}")
        submit_output = run_zowe(
            ["jobs", "submit", "data-set", resolved_target, "--rfj"]
        )
    else:
        print(f"-> Submitting local file: {resolved_target}")
        submit_output = run_zowe(
            ["jobs", "submit", "local-file", str(resolved_target), "--rfj"]
        )

    job_id = extract_job_id(submit_output)
    print(f"[{job_id}] Submitted successfully.")

    deadline = time.monotonic() + job_timeout_seconds
    status = "UNKNOWN"
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"Job {job_id} for {job_target} did not complete within "
                f"{job_timeout_seconds:g} seconds (last status: {status})."
            )
        status_output = run_zowe(
            ["jobs", "view", "job-status-by-jobid", job_id, "--rfj"],
            timeout=min(ZOWE_COMMAND_TIMEOUT_SECONDS, remaining),
        )
        status = extract_status(status_output)
        if status in TERMINAL_STATUSES:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"Job {job_id} for {job_target} did not complete within "
                f"{job_timeout_seconds:g} seconds (last status: {status})."
            )
        time.sleep(min(POLL_INTERVAL_SECONDS, remaining))

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

    success_flag = (
        "SUCCESS"
        if status in TERMINAL_STATUSES and retcode == "CC 0000"
        else "ATTENTION/FAILED"
    )
    with open(status_file, "w") as f:
        f.write("========================================\n")
        f.write(f"JOB TARGET:  {resolved_target}\n")
        f.write(f"JOB ID:      {job_id}\n")
        f.write(f"STATUS:      {status}\n")
        f.write(f"RETURN CODE: {retcode} ({success_flag})\n")
        f.write("========================================\n")

    return {
        "job_target": str(resolved_target),
        "job_id": job_id,
        "status": status,
        "retcode": retcode,
    }


def main():
    parser = argparse.ArgumentParser(description="Submit multiple JCL files or datasets concurrently.")
    parser.add_argument(
        "jobs",
        nargs="+",
        help=(
            "Local JCL files (checked in current dir and ./test_jobs) or mainframe "
            "datasets. Use 'file:' or 'dsn:' to force a target type."
        ),
    )
    parser.add_argument(
        "--max-workers",
        type=positive_int,
        default=DEFAULT_MAX_WORKERS,
        help=f"Maximum jobs to run concurrently (default: {DEFAULT_MAX_WORKERS})",
    )
    parser.add_argument(
        "--timeout",
        type=positive_float,
        default=DEFAULT_JOB_TIMEOUT_SECONDS,
        help=(
            "Maximum seconds to wait for each submitted job to finish "
            f"(default: {DEFAULT_JOB_TIMEOUT_SECONDS})"
        ),
    )
    args = parser.parse_args()

    print(f"Starting pipeline for {len(args.jobs)} job(s)...")

    # Ensure the output directory exists
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    results = [None] * len(args.jobs)
    with ThreadPoolExecutor(max_workers=min(args.max_workers, len(args.jobs))) as executor:
        futures = {
            executor.submit(process_job, job, args.timeout): (index, job)
            for index, job in enumerate(args.jobs)
        }

        for future in as_completed(futures):
            index, job_target = futures[future]
            try:
                results[index] = future.result()
            except Exception as exc:
                print(f"Job {job_target} failed: {exc}", file=sys.stderr)
                results[index] = {
                    "job_target": str(job_target),
                    "job_id": "N/A",
                    "status": "FAILED",
                    "retcode": str(exc),
                }

    # Generate the Master Pipeline Report inside the "output" directory
    report_file = output_dir / "pipeline_report.txt"
    with open(report_file, "w") as f:
        f.write("========================================\n")
        f.write("      CI/CD PIPELINE EXECUTION REPORT   \n")
        f.write("========================================\n\n")
        for res in results:
            success_flag = (
                "SUCCESS"
                if res["status"] in TERMINAL_STATUSES and res["retcode"] == "CC 0000"
                else "ATTENTION/FAILED"
            )
            f.write(f"Target:      {res['job_target']}\n")
            f.write(f"Job ID:      {res['job_id']}\n")
            f.write(f"Status:      {res['status']}\n")
            f.write(f"Return Code: {res['retcode']} ({success_flag})\n")
            f.write("-" * 40 + "\n")

    print(f"\nPipeline complete. Execution summary saved to {report_file.resolve()}")
    return int(
        any(
            res["status"] not in TERMINAL_STATUSES or res["retcode"] != "CC 0000"
            for res in results
        )
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)