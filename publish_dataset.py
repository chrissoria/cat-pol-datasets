#!/usr/bin/env python3
"""Validate and publish a parquet dataset to Hugging Face."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from lib.hf_utils import push_hf_dataset
from lib.logging_utils import setup_logging
from lib.validation import (
    validate_required_columns,
    validate_row_count_change,
    validate_unique_key,
)

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_DIR = SCRIPT_DIR / "logs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and publish a parquet dataset")
    parser.add_argument("--input-parquet", type=Path, required=True, help="Dataset parquet to publish")
    parser.add_argument("--repo", required=True, help="Hugging Face dataset repo id")
    parser.add_argument("--cache-path", type=Path, required=True, help="Local cache parquet to update after publish")
    parser.add_argument(
        "--key-column",
        dest="key_columns",
        action="append",
        default=[],
        help="Column that must be unique. Repeat for composite keys.",
    )
    parser.add_argument(
        "--required-column",
        dest="required_columns",
        action="append",
        default=[],
        help="Column that must exist. Repeat as needed.",
    )
    parser.add_argument(
        "--previous-parquet",
        type=Path,
        help="Optional previous dataset parquet for row-count regression validation",
    )
    parser.add_argument(
        "--min-row-ratio",
        type=float,
        default=0.5,
        help="Minimum allowed current/previous row ratio when --previous-parquet is provided",
    )
    parser.add_argument("--dry-run", action="store_true", help="Run validation only, skip publish")
    return parser.parse_args()


def validate_and_publish_dataset(
    df: pd.DataFrame,
    repo: str,
    cache_path: Path,
    log,
    key_columns: list[str] | None = None,
    required_columns: list[str] | None = None,
    previous_df: pd.DataFrame | None = None,
    min_row_ratio: float = 0.5,
    dry_run: bool = False,
) -> int:
    """Validate an in-memory dataset and publish it if checks pass."""
    key_columns = key_columns or []
    required_columns = required_columns or []

    missing_columns = validate_required_columns(df, required_columns)
    if missing_columns:
        log.error(f"Missing required columns: {', '.join(missing_columns)}")
        return 1

    if key_columns:
        duplicate_count = validate_unique_key(df, key_columns)
        if duplicate_count:
            log.error(
                f"Duplicate rows found for key columns {key_columns}: {duplicate_count}"
            )
            return 1

    if previous_df is not None:
        if not validate_row_count_change(previous_df, df, min_ratio=min_row_ratio):
            log.error(
                f"Row-count validation failed: current={len(df)} previous={len(previous_df)} "
                f"min_ratio={min_row_ratio}"
            )
            return 1

    if dry_run:
        log.info("Dry run: validation passed, skipping publish")
        return 0

    push_hf_dataset(df, repo, cache_path, log)
    return 0


def main() -> int:
    args = parse_args()
    log = setup_logging(LOG_DIR, logger_name="dataset_publish")

    if not args.input_parquet.exists():
        log.error(f"Input parquet not found: {args.input_parquet}")
        return 1

    df = pd.read_parquet(args.input_parquet)
    log.info(f"Loaded {len(df)} rows from {args.input_parquet}")

    previous_df = None
    if args.previous_parquet:
        if not args.previous_parquet.exists():
            log.error(f"Previous parquet not found: {args.previous_parquet}")
            return 1
        previous_df = pd.read_parquet(args.previous_parquet)

    return validate_and_publish_dataset(
        df=df,
        repo=args.repo,
        cache_path=args.cache_path,
        log=log,
        key_columns=args.key_columns,
        required_columns=args.required_columns,
        previous_df=previous_df,
        min_row_ratio=args.min_row_ratio,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
