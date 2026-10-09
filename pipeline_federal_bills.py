#!/usr/bin/env python3
"""Daily pipeline for the federal-bills-active dataset.

Flow:
1. Refresh the local bill cache with the most recent incremental bill activity.
2. Generate/update bill summaries for the highest-priority unsummarized bills.
3. Push the summarized dataset to Hugging Face.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

from lib.logging_utils import setup_logging

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_DIR = SCRIPT_DIR / "logs"
BUILD_SCRIPT = SCRIPT_DIR / "build_federal_bills.py"
SUMMARIZE_SCRIPT = SCRIPT_DIR / "summarize_federal_bills.py"


def run_step(log: logging.Logger, cmd: list[str], label: str) -> int:
    """Run a pipeline step and log the result."""
    log.info(f"[{label}] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=SCRIPT_DIR.parent)
    if result.returncode != 0:
        log.error(f"[{label}] Failed with exit code {result.returncode}")
    else:
        log.info(f"[{label}] Completed successfully")
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the daily federal bills pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Refresh cache and summaries without pushing to Hugging Face")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=300,
        help="Max bills to summarize per run (default: 300)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max bills to fetch during the incremental pull",
    )
    args = parser.parse_args()

    log = setup_logging(LOG_DIR, logger_name="federal_bills_pipeline")
    log.info("=" * 60)
    log.info("Federal bills daily pipeline starting")

    build_cmd = [sys.executable, str(BUILD_SCRIPT), "--incremental", "--dry-run"]
    if args.limit is not None:
        build_cmd.extend(["--limit", str(args.limit)])
    rc = run_step(log, build_cmd, "Pull")
    if rc != 0:
        return rc

    summarize_cmd = [sys.executable, str(SUMMARIZE_SCRIPT), "--batch-size", str(args.batch_size)]
    if args.dry_run:
        summarize_cmd.append("--dry-run")
    rc = run_step(log, summarize_cmd, "Summarize")
    if rc != 0:
        return rc

    log.info("Federal bills daily pipeline complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
