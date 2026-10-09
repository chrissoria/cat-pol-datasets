#!/usr/bin/env python3
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from lib.document_text import jittered_sleep
from lib.hf_utils import load_hf_dataset, push_hf_dataset

SCRIPT_DIR = Path(__file__).resolve().parent
CHECKPOINT_DIR = SCRIPT_DIR / "checkpoints"
FED_REPO = "chrissoria/federal-public-laws"
FED_CACHE = SCRIPT_DIR / ".fed_cache.parquet"
GOVINFO_BASE = "https://api.govinfo.gov"


def pull_federal_laws(log: logging.Logger, dry_run: bool = False) -> int:
    api_key = os.getenv("GOVINFO_API_KEY") or os.getenv("DATA_GOV_API_KEY") or "DEMO_KEY"
    existing_df = load_hf_dataset(FED_REPO, FED_CACHE, log)
    if existing_df.empty:
        fallback = CHECKPOINT_DIR / "federal" / "federal_final_dataset.parquet"
        if fallback.exists():
            existing_df = pd.read_parquet(fallback)
        else:
            return 1
    existing_ids = set(existing_df["package_id"].astype(str).tolist())
    since_str = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT00:00:00Z")
    try:
        all_pkgs = []
        offset = 0
        while True:
            resp = requests.get(f"{GOVINFO_BASE}/collections/PLAW/{since_str}", params={"offset": offset, "pageSize": 100, "api_key": api_key}, headers={"User-Agent": "cat-pol-updater/1.0"}, timeout=60)
            if resp.status_code == 429:
                import time
                time.sleep(60)
                continue
            resp.raise_for_status()
            data = resp.json()
            pkgs = data.get("packages", [])
            if not pkgs:
                break
            all_pkgs.extend(pkgs)
            offset += 100
            if not data.get("nextPage"):
                break
            jittered_sleep(0.5)
    except Exception:
        return 1
    public_pkgs = [p for p in all_pkgs if p.get("docClass", "").upper() == "PUBLIC"]
    new_pkgs = [p for p in public_pkgs if p["packageId"] not in existing_ids]
    if not new_pkgs:
        return 0
    new_rows = []
    for pkg in new_pkgs:
        pid = pkg["packageId"]
        match = re.match(r"PLAW-(\d+)publ(\d+)", pid)
        congress_num = match.group(1) if match else ""
        law_num = match.group(2) if match else ""
        short_title = pages = pdf_url = ""
        try:
            sr = requests.get(f"{GOVINFO_BASE}/packages/{pid}/summary", params={"api_key": api_key}, timeout=60)
            if sr.status_code == 200:
                sd = sr.json()
                st = sd.get("shortTitle", [])
                if st and isinstance(st, list):
                    short_title = st[0].get("title", "")
                pages = str(sd.get("pages", ""))
                pdf_url = sd.get("download", {}).get("pdfLink", "")
            jittered_sleep(0.5)
        except Exception:
            pass
        text = ""
        try:
            tr = requests.get(f"{GOVINFO_BASE}/packages/{pid}/htm", params={"api_key": api_key}, timeout=120)
            if tr.status_code == 200:
                soup = BeautifulSoup(tr.text, "html.parser")
                for t in soup(["script", "style"]):
                    t.decompose()
                text = re.sub(r"\n{3,}", "\n\n", soup.get_text(separator="\n")).strip()
            jittered_sleep(1.0)
        except Exception:
            pass
        new_rows.append({"date": pkg.get("dateIssued", "")[:10], "congress": str(congress_num), "law_number": f"Pub.L. {congress_num}-{law_num}" if law_num else "", "package_id": pid, "doc_type": "public_law", "title": pkg.get("title", ""), "short_title": short_title, "pages": pages, "text": text, "url": f"https://www.govinfo.gov/app/details/{pid}", "pdf_url": pdf_url})
    new_df = pd.DataFrame(new_rows)
    if dry_run:
        return 0
    updated = pd.concat([new_df, existing_df], ignore_index=True)
    updated = updated.drop_duplicates(subset=["package_id"], keep="first")
    updated = updated.sort_values("date", ascending=False).reset_index(drop=True)
    push_hf_dataset(updated, FED_REPO, FED_CACHE, log)
    return 0
