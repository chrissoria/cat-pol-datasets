#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-present Christopher Soria <chrissoria@berkeley.edu>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Diagnose the most recent one-off federal bill bullets backfill batch.

This reconstructs the likely targeted batch as the first N rows in the current
missing-`summary_bullets` backlog ordered by `date_updated` descending. It then
writes a CSV so we can inspect which rows are still missing and likely failed
inside the summarization step.

Usage:
    python diagnose_federal_bills_bullets_batch.py
    python diagnose_federal_bills_bullets_batch.py --batch-size 300
    python diagnose_federal_bills_bullets_batch.py --output checkpoints/federal_bills/bullets_batch_diagnostic.csv
"""

import argparse
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_FILE = SCRIPT_DIR / ".federal_bills_cache.parquet"
DEFAULT_OUTPUT = SCRIPT_DIR / "checkpoints" / "federal_bills" / "bullets_batch_diagnostic.csv"


def main():
    parser = argparse.ArgumentParser(description="Diagnose the likely targeted bullets backfill batch")
    parser.add_argument("--batch-size", type=int, default=300, help="Size of the suspected targeted batch")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="CSV path to write")
    args = parser.parse_args()

    df = pd.read_parquet(CACHE_FILE)
    if "summary_threads" in df.columns and "short_summary" not in df.columns:
        df = df.rename(columns={"summary_threads": "short_summary"})

    needs = df[df["summary_bullets"].isna() & (df["text"].fillna("").str.len() > 50)].copy()
    needs = needs.sort_values("date_updated", ascending=False).reset_index(drop=True)
    target = needs.head(args.batch_size).copy()

    target["target_rank"] = target.index + 1
    target["still_missing_summary_bullets"] = target["summary_bullets"].isna()
    target["text_len"] = target["text"].fillna("").str.len()
    target["likely_failure_mode"] = target["still_missing_summary_bullets"].map(
        lambda missing: "likely_cat_pol_failure_or_non_success_status" if missing else "filled"
    )

    cols = [
        "target_rank",
        "bill_type",
        "bill_number",
        "date_updated",
        "date_last_action",
        "title",
        "status",
        "text_len",
        "still_missing_summary_bullets",
        "likely_failure_mode",
        "summary_bullets",
        "short_summary",
        "url",
    ]
    output_df = target[[c for c in cols if c in target.columns]].copy()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output_df.to_csv(args.output, index=False)

    total = len(output_df)
    missing = int(output_df["still_missing_summary_bullets"].sum())
    filled = total - missing

    print(f"wrote {args.output}")
    print(f"target_rows {total}")
    print(f"filled_rows {filled}")
    print(f"still_missing_rows {missing}")


if __name__ == "__main__":
    main()
