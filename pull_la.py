#!/usr/bin/env python3
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from lib.document_text import extract_pdf_text, jittered_sleep
from lib.hf_utils import load_hf_dataset, push_hf_dataset

SCRIPT_DIR = Path(__file__).resolve().parent
CHECKPOINT_DIR = SCRIPT_DIR / "checkpoints"
LA_REPO = "chrissoria/la-ordinances"
LA_CACHE = SCRIPT_DIR / ".la_cache.parquet"


def pull_la(log: logging.Logger, dry_run: bool = False) -> int:
    existing_df = load_hf_dataset(LA_REPO, LA_CACHE, log)
    if existing_df.empty:
        fallback = CHECKPOINT_DIR / "la" / "la_final_dataset.parquet"
        if fallback.exists():
            existing_df = pd.read_parquet(fallback)
        else:
            return 1
    existing_ords = set(existing_df["ordinance_number"].astype(str).tolist())
    max_ord = max(int(o) for o in existing_ords if o.isdigit())
    session = requests.Session()
    search_url = "https://cityclerk.lacity.org/lacityclerkconnect/index.cfm"
    new_rows = []
    for prefix in range(max_ord // 10, max_ord // 10 + 10):
        query = f"{prefix}*"
        try:
            resp = session.post(f"{search_url}?fa=vord.doSearch&s=2", data={"DOCIDSearch": query, "StartDate": "", "EndDate": ""}, headers={"User-Agent": "cat-pol-updater/1.0"}, timeout=60)
            resp.raise_for_status()
        except Exception:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 4:
                    continue
                ord_num = cells[0].get_text(strip=True)
                if not ord_num or not ord_num[0].isdigit() or ord_num in existing_ords:
                    continue
                date_raw = cells[3].get_text(strip=True)
                try:
                    from datetime import datetime as _dt
                    date = _dt.strptime(date_raw, "%m/%d/%Y").strftime("%Y-%m-%d")
                except (ValueError, TypeError):
                    date = date_raw
                pdf_url = ""
                pdf_link = cells[0].find("a")
                if pdf_link and pdf_link.get("href", "").endswith(".pdf"):
                    pdf_url = pdf_link["href"]
                    if not pdf_url.startswith("http"):
                        pdf_url = f"https://cityclerk.lacity.org{pdf_url}"
                cf_url = ""
                cf_link = cells[1].find("a")
                if cf_link and cf_link.get("href"):
                    href = cf_link["href"]
                    cf_url = f"https://cityclerk.lacity.org/lacityclerkconnect/{href}" if not href.startswith("http") else href
                new_rows.append({"date": date, "ordinance_number": ord_num, "council_file": cells[1].get_text(strip=True), "doc_type": "ordinance", "title": cells[2].get_text(strip=True), "text": "", "pdf_url": pdf_url, "council_file_url": cf_url})
        jittered_sleep(3.0)
    if not new_rows:
        return 0
    for row in new_rows:
        if row["pdf_url"]:
            row["text"] = extract_pdf_text(row["pdf_url"], session)
            jittered_sleep(0.3)
    new_df = pd.DataFrame(new_rows)
    if dry_run:
        return 0
    updated = pd.concat([new_df, existing_df], ignore_index=True)
    updated = updated.drop_duplicates(subset=["ordinance_number"], keep="first")
    updated = updated.sort_values("date", ascending=False).reset_index(drop=True)
    push_hf_dataset(updated, LA_REPO, LA_CACHE, log)
    return 0
