#!/usr/bin/env python3
from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from lib.hf_utils import load_hf_dataset, push_hf_dataset

SCRIPT_DIR = Path(__file__).resolve().parent
EO_REPO = "chrissoria/executive-orders"
EO_CACHE = SCRIPT_DIR / ".eo_cache.parquet"


def pull_executive_orders(log: logging.Logger, dry_run: bool = False) -> int:
    existing_df = load_hf_dataset(EO_REPO, EO_CACHE, log)
    if existing_df.empty:
        return 1
    existing_ids = set(existing_df["document_number"].astype(str).tolist()) if "document_number" in existing_df.columns else set(existing_df["url"].astype(str).tolist())
    try:
        resp = requests.get("https://www.federalregister.gov/api/v1/documents.json", params={"conditions[type]": "PRESDOCU", "conditions[presidential_document_type]": "executive_order", "per_page": 100, "page": 1}, timeout=60)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return 1
    new_rows = []
    for doc in data.get("results", []):
        doc_num = doc.get("document_number", "")
        if doc_num in existing_ids:
            continue
        president = doc.get("president", {})
        president_name = president.get("name", "") if isinstance(president, dict) else str(president)
        text = ""
        body_url = doc.get("body_html_url", "")
        if body_url:
            try:
                tr = requests.get(body_url, timeout=60)
                if tr.status_code == 200:
                    soup = BeautifulSoup(tr.text, "html.parser")
                    text = re.sub(r"\n{3,}", "\n\n", soup.get_text(separator="\n")).strip()
            except Exception:
                pass
        new_rows.append({"date": doc.get("publication_date", ""), "title": doc.get("title", ""), "executive_order_number": str(doc.get("executive_order_number", "")), "president": president_name, "document_number": doc_num, "text": text, "html_url": doc.get("html_url", ""), "pdf_url": doc.get("pdf_url", ""), "signing_date": doc.get("signing_date", "")})
    if not new_rows:
        return 0
    new_df = pd.DataFrame(new_rows)
    if dry_run:
        return 0
    updated = pd.concat([new_df, existing_df], ignore_index=True)
    id_col = "document_number" if "document_number" in updated.columns else "url"
    updated = updated.drop_duplicates(subset=[id_col], keep="first")
    updated = updated.sort_values("date", ascending=False).reset_index(drop=True)
    push_hf_dataset(updated, EO_REPO, EO_CACHE, log)
    return 0
