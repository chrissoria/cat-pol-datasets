#!/usr/bin/env python3
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from lib.document_text import extract_pdf_text, jittered_sleep
from lib.hf_utils import load_hf_dataset, push_hf_dataset

SCRIPT_DIR = Path(__file__).resolve().parent
CHECKPOINT_DIR = SCRIPT_DIR / "checkpoints"
SF_REPO = "chrissoria/sf-ordinances"
SF_CACHE = SCRIPT_DIR / ".sf_cache.parquet"
SF_BASE_URL = "https://www.sfbos.org"
SF_HEADERS = {"User-Agent": "cat-pol-dataset-builder/1.0 (academic research; chrissoria@berkeley.edu)"}
PAGE_DELAY = 2.0
PDF_DELAY = 1.0


def sf_scrape_year(year: int, session: requests.Session) -> list[dict]:
    resp = session.get(f"{SF_BASE_URL}/ordinances-{year}", headers=SF_HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table")
    if not table:
        return []
    rows = []
    for tr in table.find_all("tr")[1:]:
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        file_number = tds[0].get_text(strip=True)
        a_tag = tds[1].find("a")
        if a_tag:
            enactment_number = a_tag.get_text(strip=True)
            pdf_path = a_tag.get("href", "")
            pdf_url = f"{SF_BASE_URL}{pdf_path}" if pdf_path.startswith("/") else pdf_path
        else:
            enactment_number = tds[1].get_text(strip=True)
            pdf_url = ""
        date_raw = tds[2].get_text(strip=True)
        title = tds[3].get_text(strip=True)
        date = ""
        for fmt in ("%m/%d/%Y", "%m/%d/%y"):
            try:
                date = datetime.strptime(date_raw, fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                continue
        rows.append({"date": date, "file_number": file_number, "enactment_number": enactment_number, "doc_type": "ordinance", "title": title, "text": "", "pdf_url": pdf_url, "year": year})
    return rows


def pull_san_francisco(log: logging.Logger, dry_run: bool = False) -> int:
    tag = "[San Francisco]"
    existing_df = load_hf_dataset(SF_REPO, SF_CACHE, log)
    if existing_df.empty:
        fallback = CHECKPOINT_DIR / "sf_final_dataset.parquet"
        if fallback.exists():
            existing_df = pd.read_parquet(fallback)
        else:
            return 1
    existing_ids = set(existing_df["enactment_number"].tolist())
    session = requests.Session()
    now = datetime.now()
    years_to_check = [now.year] + ([now.year - 1] if now.month == 1 else [])
    new_rows = []
    for year in years_to_check:
        try:
            rows = sf_scrape_year(year, session)
        except Exception:
            continue
        page_new = [r for r in rows if r["enactment_number"] not in existing_ids]
        for row in page_new:
            if row["pdf_url"]:
                row["text"] = extract_pdf_text(row["pdf_url"], session)
                jittered_sleep(PDF_DELAY)
        new_rows.extend(page_new)
        jittered_sleep(PAGE_DELAY)
    if not new_rows:
        return 0
    new_df = pd.DataFrame(new_rows)
    if dry_run:
        return 0
    updated = pd.concat([new_df, existing_df], ignore_index=True)
    updated = updated.drop_duplicates(subset=["enactment_number"], keep="first")
    updated = updated.sort_values("date", ascending=False).reset_index(drop=True)
    push_hf_dataset(updated, SF_REPO, SF_CACHE, log)
    return 0
