#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-present Christopher Soria <chrissoria@berkeley.edu>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
One-off backfill for missing federal bill bullet summaries.

This script only targets rows where `summary_bullets` is null. In conversation
we may call this "bullet_points", but the dataset column name is
`summary_bullets`.

Usage:
    python backfill_federal_bills_bullets.py
    python backfill_federal_bills_bullets.py --batch-size 300
    python backfill_federal_bills_bullets.py --dry-run
    python backfill_federal_bills_bullets.py --model-source openai --user-model gpt-5-mini
"""

import argparse
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from summarize_federal_bills import finalize_dataset, load_cache, push_to_hf, save_cache, summarize_batch

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
load_dotenv(PROJECT_ROOT / ".env", override=True)
LOG_DIR = SCRIPT_DIR / "logs"
BATCH_SIZE = 300
DEFAULT_MODEL_SOURCE = "openai"
DEFAULT_USER_MODEL = "gpt-5-mini"
HF_API_KEY = (
    os.getenv("HUGGINGFACE_API_KEY")
    or os.getenv("HF_API_KEY")
    or os.getenv("CATLLM_HUGGINGFACE_TOKEN")
    or os.getenv("HUGGINGFACE_TOKEN")
)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_APIKEY")

LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "federal_bills_bullets_backfill.log", mode="a"),
    ],
)
log = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="One-off backfill for missing federal bill bullet summaries")
    parser.add_argument("--dry-run", action="store_true", help="Skip HuggingFace push")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help=f"Max missing bullet summaries to backfill (default: {BATCH_SIZE})",
    )
    parser.add_argument(
        "--model-source",
        default=DEFAULT_MODEL_SOURCE,
        choices=["openai", "huggingface"],
        help=f"Model provider to use (default: {DEFAULT_MODEL_SOURCE})",
    )
    parser.add_argument(
        "--user-model",
        default=DEFAULT_USER_MODEL,
        help=f"Model name to use for summarization (default: {DEFAULT_USER_MODEL})",
    )
    args = parser.parse_args()

    if args.model_source == "openai":
        api_key = OPENAI_API_KEY
        if not api_key:
            log.error("No OpenAI credential found (OPENAI_API_KEY or OPENAI_APIKEY).")
            return
    else:
        api_key = HF_API_KEY
        if not api_key:
            log.error(
                "No HuggingFace credential found "
                "(HUGGINGFACE_API_KEY, HF_API_KEY, CATLLM_HUGGINGFACE_TOKEN, or HUGGINGFACE_TOKEN)."
            )
            return

    log.info("=" * 60)
    log.info(
        "Federal bill bullets one-off backfill starting "
        f"(batch_size={args.batch_size}, model_source={args.model_source}, user_model={args.user_model})"
    )

    df = load_cache()
    before = int(df["summary_bullets"].notna().sum()) if "summary_bullets" in df.columns else 0
    log.info(f"Loaded {len(df)} bills from cache")
    log.info(f"  summary_bullets before: {before} / {len(df)}")

    df = summarize_batch(
        df,
        "summary_bullets",
        "bullets",
        "U.S. federal bills in the 119th Congress",
        api_key,
        args.batch_size,
        user_model=args.user_model,
        model_source=args.model_source,
    )

    df = finalize_dataset(df)
    after = int(df["summary_bullets"].notna().sum()) if "summary_bullets" in df.columns else 0

    save_cache(df)
    log.info(f"Cache saved ({len(df)} bills)")
    log.info(f"  summary_bullets after: {after} / {len(df)}")

    if not args.dry_run:
        push_to_hf(df)
    else:
        log.info("Dry run — skipping HuggingFace push")

    log.info("Done.")


if __name__ == "__main__":
    main()
