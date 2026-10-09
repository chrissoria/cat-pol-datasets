#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-present Christopher Soria <chrissoria@berkeley.edu>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Generate and backfill LLM summaries for the federal-bills-active dataset.

THIS SCRIPT ONLY HANDLES SUMMARIZATION — NOT BILL FETCHING.
For fetching new/updated bills, run build_federal_bills.py --incremental separately.

Each run summarizes up to BATCH_SIZE bills that are missing summaries, prioritizing
the most recently updated bills first. With ~13,500 bills in the backlog and a batch
size of 300, each run takes ~45 minutes and makes steady progress.

Usage:
    python summarize_federal_bills.py              # Summarize next batch, push to HF
    python summarize_federal_bills.py --dry-run    # Summarize next batch, skip HF push
    python summarize_federal_bills.py --batch-size 500  # Override batch size

HuggingFace repo: chrissoria/federal-bills-active
"""

import argparse
import logging
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
load_dotenv(PROJECT_ROOT / ".env", override=True)
CACHE_FILE = SCRIPT_DIR / ".federal_bills_cache.parquet"
LOG_DIR = SCRIPT_DIR / "logs"
HF_REPO = "chrissoria/federal-bills-active"
BATCH_SIZE = 300  # Bills to summarize per run — increase for faster backlog recovery
HF_TOKEN = os.getenv("CATLLM_HUGGINGFACE_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_APIKEY")
DEFAULT_USER_MODEL = "gpt-5-mini"
DEFAULT_MODEL_SOURCE = "openai"

LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "federal_bills_summarize.log", mode="a"),
    ],
)
log = logging.getLogger(__name__)


def load_cache():
    if not CACHE_FILE.exists():
        raise FileNotFoundError(f"Cache not found: {CACHE_FILE}. Run build_federal_bills.py --incremental first.")
    df = pd.read_parquet(CACHE_FILE)
    if "summary_threads" in df.columns and "short_summary" not in df.columns:
        df = df.rename(columns={"summary_threads": "short_summary"})
    if "short_title" in df.columns:
        df = df.drop(columns=["short_title"])
    return df


def save_cache(df):
    df.to_parquet(CACHE_FILE, index=False)


def finalize_dataset(df):
    """Apply the same schema cleanup and vote rollups as the builder."""
    from build_federal_bills import VOTE_SUMMARY_COLS, build_vote_aggregates, order_dataset_columns

    df = df.copy()
    if "pdf_url" in df.columns:
        df = df.drop(columns=["pdf_url"])
    if "summary_report" in df.columns:
        df = df.drop(columns=["summary_report"])
    if "summary_threads" in df.columns and "short_summary" not in df.columns:
        df = df.rename(columns={"summary_threads": "short_summary"})
    if "short_title" in df.columns:
        df = df.drop(columns=["short_title"])
    if "text" in df.columns:
        before = len(df)
        df = df[df["text"].fillna("").astype(str).str.strip() != ""].copy()
        dropped = before - len(df)
        if dropped:
            log.info(f"Dropped {dropped} bills with empty text before save")

    vote_rollups = build_vote_aggregates()
    if not vote_rollups.empty:
        df["bill_number"] = df["bill_number"].astype(str)
        df["congress"] = df["congress"].astype(str)
        df = df.drop(columns=[c for c in VOTE_SUMMARY_COLS if c in df.columns])
        df = df.merge(
            vote_rollups,
            on=["bill_type", "bill_number", "congress"],
            how="left",
        )

    return order_dataset_columns(df)


def push_to_hf(df):
    from datasets import Dataset
    if not HF_TOKEN:
        log.error("No HuggingFace token found. Set CATLLM_HUGGINGFACE_TOKEN or HUGGINGFACE_TOKEN in .env")
        return
    ds = Dataset.from_pandas(df)
    ds.push_to_hub(HF_REPO, token=HF_TOKEN, private=False)
    log.info(f"Pushed {len(df)} rows to https://huggingface.co/datasets/{HF_REPO}")


def summarize_batch(
    df,
    col,
    format,
    description,
    api_key,
    batch_size,
    user_model=DEFAULT_USER_MODEL,
    model_source=DEFAULT_MODEL_SOURCE,
):
    """Find bills missing `col` summary, summarize up to batch_size, write back to df."""
    if col not in df.columns:
        df[col] = None

    needs = df[df[col].isna() & (df["text"].str.len() > 50)]
    total_missing = len(needs)

    if total_missing == 0:
        log.info(f"[{col}] All bills summarized. Up to date.")
        return df

    if len(needs) > batch_size:
        needs = needs.sort_values("date_updated", ascending=False).head(batch_size)
        log.info(f"[{col}] Backlog: {total_missing} missing — summarizing {batch_size} most recently updated")
    else:
        log.info(f"[{col}] Summarizing all {total_missing} remaining bills")

    import cat_pol
    result = cat_pol.summarize(
        input_data=needs["text"].tolist(),
        format=format,
        tone="eli5",
        description=description,
        api_key=api_key,
        user_model=user_model,
        model_source=model_source,
        batch_mode=True,
        creativity=0,
    )
    for i, (orig_idx, _) in enumerate(needs.iterrows()):
        if i < len(result) and result.iloc[i].get("processing_status") == "success":
            df.at[orig_idx, col] = result.iloc[i]["summary"]

    succeeded = (result["processing_status"] == "success").sum()
    log.info(f"[{col}] Generated {succeeded}/{len(needs)} summaries")
    return df


def main():
    parser = argparse.ArgumentParser(description="Summarize federal bills (backlog backfill)")
    parser.add_argument("--dry-run", action="store_true", help="Skip HuggingFace push")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE,
                        help=f"Max bills to summarize per run (default: {BATCH_SIZE})")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    api_key = OPENAI_API_KEY
    if not api_key:
        log.error("No OpenAI credential found (OPENAI_API_KEY or OPENAI_APIKEY). Exiting.")
        return

    log.info("=" * 60)
    log.info(f"Federal Bills summarizer starting (batch_size={args.batch_size})")

    df = load_cache()
    log.info(f"Loaded {len(df)} bills from cache")
    log.info(f"  short_summary: {df['short_summary'].notna().sum() if 'short_summary' in df.columns else 0} / {len(df)}")
    log.info(f"  summary_bullets: {df['summary_bullets'].notna().sum() if 'summary_bullets' in df.columns else 0} / {len(df)}")

    try:
        df = summarize_batch(df, "short_summary", "threads", "U.S. federal bills", api_key, args.batch_size)
    except Exception as e:
        log.warning(f"Threads summarization failed: {e}")

    try:
        df = summarize_batch(df, "summary_bullets", "bullets", "U.S. federal bills in the 119th Congress", api_key, args.batch_size)
    except Exception as e:
        log.warning(f"Bullet summarization failed: {e}")

    df = finalize_dataset(df)
    save_cache(df)
    log.info(f"Cache saved ({len(df)} bills)")
    log.info(f"  short_summary: {df['short_summary'].notna().sum() if 'short_summary' in df.columns else 0} / {len(df)}")
    log.info(f"  summary_bullets: {df['summary_bullets'].notna().sum()} / {len(df)}")

    if not args.dry_run:
        push_to_hf(df)
    else:
        log.info("Dry run — skipping HuggingFace push")

    log.info("Done.")


if __name__ == "__main__":
    main()
