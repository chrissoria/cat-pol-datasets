#!/usr/bin/env python3
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import requests

from lib.document_text import extract_pdf_text, jittered_sleep
from lib.hf_utils import load_hf_dataset, push_hf_dataset

SCRIPT_DIR = Path(__file__).resolve().parent
CHECKPOINT_DIR = SCRIPT_DIR / "checkpoints"
SD_REPO = "chrissoria/san-diego-ordinances"
SD_CACHE = SCRIPT_DIR / ".sd_cache.parquet"
SD_MAX_PAGES = 20
PAGE_DELAY = 2.0
PDF_DELAY = 1.0


def pull_san_diego(log: logging.Logger, dry_run: bool = False) -> int:
    from build_san_diego_dataset import scrape_page as sd_scrape_page

    tag = "[San Diego]"
    log.info("=" * 50)
    log.info(f"{tag} Starting update ({'DRY RUN' if dry_run else 'LIVE'})")
    existing_df = load_hf_dataset(SD_REPO, SD_CACHE, log)
    if existing_df.empty:
        fallback = CHECKPOINT_DIR / "final_dataset.parquet"
        if fallback.exists():
            existing_df = pd.read_parquet(fallback)
            log.info(f"{tag} Loaded {len(existing_df)} rows from build checkpoint")
        else:
            log.error(f"{tag} No existing dataset. Run build_san_diego_dataset.py first.")
            return 1

    existing_ids = set(existing_df["doc_num"].tolist())
    session = requests.Session()
    new_rows = []
    for page_num in range(SD_MAX_PAGES):
        log.info(f"{tag} Scraping page {page_num}...")
        try:
            rows = sd_scrape_page(page_num, session)
        except Exception as e:
            log.error(f"{tag} Page {page_num} failed: {e}")
            jittered_sleep(PAGE_DELAY * 3)
            continue
        if not rows:
            break
        page_new = [r for r in rows if r["doc_num"] not in existing_ids]
        page_overlap = len(rows) - len(page_new)
        for row in page_new:
            if row["pdf_url"]:
                row["text"] = extract_pdf_text(row["pdf_url"], session)
                jittered_sleep(PDF_DELAY)
        new_rows.extend(page_new)
        if page_overlap == len(rows) or (page_overlap > len(rows) * 0.5 and page_num > 0):
            break
        jittered_sleep(PAGE_DELAY)
    if not new_rows:
        log.info(f"{tag} No new entries. Up to date.")
        return 0
    new_df = pd.DataFrame(new_rows)
    if dry_run:
        return 0
    updated = pd.concat([new_df, existing_df], ignore_index=True)
    updated = updated.drop_duplicates(subset=["doc_num"], keep="first")
    updated = updated.sort_values("date", ascending=False).reset_index(drop=True)
    push_hf_dataset(updated, SD_REPO, SD_CACHE, log)
    return 0
