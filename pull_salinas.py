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
SAL_REPO = "chrissoria/salinas-ordinances"
SAL_CACHE = SCRIPT_DIR / ".sal_cache.parquet"
SAL_API_BASE = "https://webapi.legistar.com/v1/salinas"
PDF_DELAY = 1.0


def sal_fetch_recent_matters(matter_type: str) -> list[dict]:
    resp = requests.get(f"{SAL_API_BASE}/matters", params={"$filter": f"MatterTypeName eq '{matter_type}'", "$top": 200, "$orderby": "MatterIntroDate desc"}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def sal_get_attachment_url(matter_id: int) -> str:
    try:
        resp = requests.get(f"{SAL_API_BASE}/matters/{matter_id}/attachments", timeout=30)
        resp.raise_for_status()
        attachments = resp.json()
    except Exception:
        return ""
    for att in attachments:
        url = att.get("MatterAttachmentHyperlink", "")
        name = att.get("MatterAttachmentName", "").lower()
        if url.endswith(".pdf") and ("ordinance" in name or "resolution" in name):
            return url
    for att in attachments:
        url = att.get("MatterAttachmentHyperlink", "")
        if url.endswith(".pdf"):
            return url
    for att in attachments:
        url = att.get("MatterAttachmentHyperlink", "")
        if url:
            return url
    return ""


def pull_salinas(log: logging.Logger, dry_run: bool = False) -> int:
    existing_df = load_hf_dataset(SAL_REPO, SAL_CACHE, log)
    if existing_df.empty:
        fallback = CHECKPOINT_DIR / "salinas_final_dataset.parquet"
        if fallback.exists():
            existing_df = pd.read_parquet(fallback)
        else:
            return 1
    existing_ids = set(existing_df["matter_id"].astype(str).tolist())
    session = requests.Session()
    new_rows = []
    for matter_type, doc_type in [("Ordinance", "ordinance"), ("Resolution", "resolution")]:
        try:
            matters = sal_fetch_recent_matters(matter_type)
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
            attachment_url = sal_get_attachment_url(matter["MatterId"])
            jittered_sleep(0.3)
            row = {"date": date, "matter_id": mid, "matter_file": matter.get("MatterFile", ""), "enactment_number": matter.get("MatterEnactmentNumber", "") or "", "doc_type": doc_type, "title": matter.get("MatterTitle", ""), "text": "", "attachment_url": attachment_url, "year": year}
            if attachment_url:
                row["text"] = extract_pdf_text(attachment_url, session)
                jittered_sleep(PDF_DELAY)
            new_rows.append(row)
    if not new_rows:
        return 0
    new_df = pd.DataFrame(new_rows)
    if dry_run:
        return 0
    updated = pd.concat([new_df, existing_df], ignore_index=True)
    updated = updated.drop_duplicates(subset=["matter_id"], keep="first")
    updated = updated.sort_values("date", ascending=False).reset_index(drop=True)
    push_hf_dataset(updated, SAL_REPO, SAL_CACHE, log)
    return 0
