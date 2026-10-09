#!/usr/bin/env python3
"""Generic incremental puller for Legistar-backed city datasets."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import requests

from lib.document_text import extract_pdf_text, jittered_sleep
from lib.hf_utils import load_hf_dataset, push_hf_dataset

SCRIPT_DIR = Path(__file__).resolve().parent
CHECKPOINT_DIR = SCRIPT_DIR / "checkpoints"
PDF_DELAY = 1.0
LEGISTAR_API = "https://webapi.legistar.com/v1"

LEGISTAR_CITIES = {
    "oak": {
        "name": "Oakland",
        "slug": "oakland",
        "repo": "chrissoria/oakland-ordinances",
        "cache": SCRIPT_DIR / ".oak_cache.parquet",
        "types": ["Ordinance"],
    },
    "lb": {
        "name": "Long Beach",
        "slug": "longbeach",
        "repo": "chrissoria/long-beach-ordinances",
        "cache": SCRIPT_DIR / ".lb_cache.parquet",
        "types": ["Ordinance", "Resolution"],
    },
    "fre": {
        "name": "Fresno",
        "slug": "fresno",
        "repo": "chrissoria/fresno-ordinances",
        "cache": SCRIPT_DIR / ".fre_cache.parquet",
        "types": ["Ordinance", "Resolution"],
    },
}


def legistar_fetch_recent(city_slug: str, matter_type: str) -> list[dict]:
    """Fetch recent matters from a Legistar city API."""
    resp = requests.get(
        f"{LEGISTAR_API}/{city_slug}/matters",
        params={
            "$filter": f"MatterTypeName eq '{matter_type}'",
            "$top": 200,
            "$orderby": "MatterIntroDate desc",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def legistar_get_attachment(city_slug: str, matter_id: int) -> str:
    """Get the best PDF attachment URL for a Legistar matter."""
    try:
        resp = requests.get(f"{LEGISTAR_API}/{city_slug}/matters/{matter_id}/attachments", timeout=30)
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


def pull_legistar_city(city_key: str, log: logging.Logger, dry_run: bool = False) -> int:
    """Generic incremental update for any Legistar city."""
    cfg = LEGISTAR_CITIES[city_key]
    tag = f"[{cfg['name']}]"

    log.info("=" * 50)
    log.info(f"{tag} Starting update ({'DRY RUN' if dry_run else 'LIVE'})")

    existing_df = load_hf_dataset(cfg["repo"], cfg["cache"], log)
    if existing_df.empty:
        fallback = CHECKPOINT_DIR / f"{cfg['slug']}_final_dataset.parquet"
        if fallback.exists():
            existing_df = pd.read_parquet(fallback)
            log.info(f"{tag} Loaded {len(existing_df)} rows from build checkpoint")
        else:
            log.error(f"{tag} No existing dataset. Run build_legistar_dataset.py {cfg['slug']} first.")
            return 1

    existing_ids = set(existing_df["matter_id"].astype(str).tolist())
    log.info(f"{tag} Existing: {len(existing_df)} rows, {len(existing_ids)} unique")

    session = requests.Session()
    new_rows: list[dict] = []

    for matter_type in cfg["types"]:
        doc_type = matter_type.lower()
        log.info(f"{tag} Fetching recent {matter_type}s...")
        try:
            matters = legistar_fetch_recent(cfg["slug"], matter_type)
        except Exception as e:
            log.error(f"{tag} API failed for {matter_type}: {e}")
            continue

        type_new = []
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

            attachment_url = legistar_get_attachment(cfg["slug"], matter["MatterId"])
            jittered_sleep(0.3)

            row = {
                "date": date,
                "matter_id": mid,
                "matter_file": matter.get("MatterFile", ""),
                "enactment_number": matter.get("MatterEnactmentNumber", "") or "",
                "doc_type": doc_type,
                "title": matter.get("MatterTitle", ""),
                "text": "",
                "attachment_url": attachment_url,
                "year": year,
            }

            if attachment_url:
                row["text"] = extract_pdf_text(attachment_url, session)
                jittered_sleep(PDF_DELAY)

            type_new.append(row)

        log.info(f"{tag}   {len(type_new)} new {doc_type}s")
        new_rows.extend(type_new)

    if not new_rows:
        log.info(f"{tag} No new entries. Up to date.")
        return 0

    new_df = pd.DataFrame(new_rows)
    log.info(f"{tag} Found {len(new_df)} new entries ({new_df['date'].min()} to {new_df['date'].max()})")

    if dry_run:
        for _, row in new_df.iterrows():
            log.info(f"  {row['date']} | {row['matter_file']} | {row['title'][:60]}")
        return 0

    updated = pd.concat([new_df, existing_df], ignore_index=True)
    updated = updated.drop_duplicates(subset=["matter_id"], keep="first")
    updated = updated.sort_values("date", ascending=False).reset_index(drop=True)

    push_hf_dataset(updated, cfg["repo"], cfg["cache"], log)
    log.info(f"{tag} Done. {len(updated)} total rows (+{len(new_df)} new)")
    return 0
