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
SDCO_REPO = "chrissoria/sd-county-ordinances"
SDCO_CACHE = SCRIPT_DIR / ".sdco_cache.parquet"


def pull_sd_county(log: logging.Logger, dry_run: bool = False) -> int:
    existing_df = load_hf_dataset(SDCO_REPO, SDCO_CACHE, log)
    if existing_df.empty:
        fallback = CHECKPOINT_DIR / "sdcounty" / "sdcounty_final_dataset.parquet"
        if fallback.exists():
            existing_df = pd.read_parquet(fallback)
        else:
            return 1
    existing_ids = set(existing_df["matter_id"].astype(str).tolist())
    session = requests.Session()
    new_rows = []
    for keyword, doc_type in [("ORDINANCE", "ordinance"), ("RESOLUTION", "resolution")]:
        try:
            resp = requests.get("https://webapi.legistar.com/v1/sdcounty/matters", params={"$filter": f"substringof('{keyword}',MatterTitle)", "$top": 200, "$orderby": "MatterIntroDate desc"}, timeout=30)
            resp.raise_for_status()
            matters = resp.json()
        except Exception:
            continue
        for matter in matters:
            mid = str(matter["MatterId"])
            if mid in existing_ids:
                continue
            intro_date = matter.get("MatterIntroDate", "") or ""
            date = intro_date[:10] if intro_date else ""
            try:
                year = int(date[:4]) if date else 0
            except ValueError:
                year = 0
            att_url = ""
            try:
                att_resp = requests.get(f"https://webapi.legistar.com/v1/sdcounty/matters/{matter['MatterId']}/attachments", timeout=15)
                atts = att_resp.json()
                for a in atts:
                    url = a.get("MatterAttachmentHyperlink", "")
                    if url.endswith(".pdf") or url.endswith(".docx"):
                        att_url = url
                        break
                if not att_url:
                    for a in atts:
                        url = a.get("MatterAttachmentHyperlink", "")
                        if url:
                            att_url = url
                            break
            except Exception:
                pass
            jittered_sleep(0.3)
            text = extract_pdf_text(att_url, session) if att_url else ""
            if att_url:
                jittered_sleep(0.5)
            new_rows.append({"date": date, "matter_id": mid, "matter_file": matter.get("MatterFile", ""), "doc_type": doc_type, "title": matter.get("MatterTitle", "").strip(), "text": text, "attachment_url": att_url, "body": matter.get("MatterBodyName", ""), "status": matter.get("MatterStatusName", ""), "year": year})
    if not new_rows:
        return 0
    new_df = pd.DataFrame(new_rows)
    if dry_run:
        return 0
    updated = pd.concat([new_df, existing_df], ignore_index=True)
    updated = updated.drop_duplicates(subset=["matter_id"], keep="first")
    updated = updated.sort_values("date", ascending=False).reset_index(drop=True)
    push_hf_dataset(updated, SDCO_REPO, SDCO_CACHE, log)
    return 0
