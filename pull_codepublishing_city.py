#!/usr/bin/env python3
"""Generic puller for Code Publishing city code datasets."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from lib.document_text import jittered_sleep
from lib.hf_utils import load_hf_dataset, push_hf_dataset

SCRIPT_DIR = Path(__file__).resolve().parent
CHECKPOINT_DIR = SCRIPT_DIR / "checkpoints"

CODEPUB_CITIES = {
    "clovis": {
        "name": "Clovis",
        "state": "CA",
        "prefix": "Clovis",
        "repo": "chrissoria/clovis-ordinances",
        "cache": SCRIPT_DIR / ".clovis_cache.parquet",
        "titles": list(range(1, 11)),
    },
    "nb": {
        "name": "Newport Beach",
        "state": "CA",
        "prefix": "NewportBeach",
        "repo": "chrissoria/newport-beach-ordinances",
        "cache": SCRIPT_DIR / ".nb_cache.parquet",
        "titles": list(range(1, 22)),
    },
}


def pull_codepublishing_city(city_key: str, log: logging.Logger, dry_run: bool = False) -> int:
    """Incremental update for a Code Publishing city."""
    cfg = CODEPUB_CITIES[city_key]
    tag = f"[{cfg['name']}]"
    log.info("=" * 50)
    log.info(f"{tag} Starting update ({'DRY RUN' if dry_run else 'LIVE'})")

    existing_df = load_hf_dataset(cfg["repo"], cfg["cache"], log)
    if existing_df.empty:
        cp = CHECKPOINT_DIR / city_key / f"{city_key}_final_dataset.parquet"
        if cp.exists():
            existing_df = pd.read_parquet(cp)
            log.info(f"{tag} Loaded {len(existing_df)} sections from checkpoint")
        else:
            log.error(f"{tag} No existing dataset. Run build_codepublishing_dataset.py first.")
            return 1

    existing_urls = set(existing_df["url"].tolist())
    log.info(f"{tag} Existing: {len(existing_df)} sections")

    session = requests.Session()
    base = f"https://www.codepublishing.com/{cfg['state']}/{cfg['prefix']}/html"
    new_rows = []

    for title_num in cfg["titles"]:
        title_dir = f"{cfg['prefix']}{title_num:02d}"
        for chapter in range(1, 100):
            url = f"{base}/{title_dir}/{title_dir}{chapter:02d}.html"
            if url in existing_urls:
                continue
            try:
                resp = session.get(url, headers={"User-Agent": "cat-pol-updater/1.0"}, timeout=15)
                if resp.status_code == 404:
                    if chapter > 5:
                        break
                    continue
                if resp.status_code != 200:
                    break
            except Exception:
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            content = soup.find("div", id="mainContent")
            if not content:
                continue

            text = content.get_text(separator="\n").strip()
            if len(text) < 20:
                continue

            h1 = content.find("h1")
            section_title = h1.get_text(strip=True) if h1 else ""
            filename = url.split("/")[-1].replace(".html", "")

            ord_refs = re.findall(
                r'(?:Ord\.|Ordinance)\s*([\d]+[-\w]*)'
                r'(?:.*?(?:eff\.?|effective)\s*(\w+\.?\s*\d{1,2},?\s*\d{4}))?',
                text,
            )
            ord_ref_strs = [
                f"Ord. {num} (eff. {date})" if date else f"Ord. {num}"
                for num, date in ord_refs
            ]

            new_rows.append({
                "section_id": filename,
                "title_num": str(title_num),
                "chapter": str(chapter),
                "section_title": section_title,
                "text": text,
                "ordinance_refs": "; ".join(ord_ref_strs),
                "url": url,
            })

            jittered_sleep(0.5)

    if not new_rows:
        log.info(f"{tag} No new sections. Up to date.")
        return 0

    new_df = pd.DataFrame(new_rows)
    log.info(f"{tag} Found {len(new_df)} new sections")

    if dry_run:
        for _, row in new_df.head(10).iterrows():
            log.info(f"  {row['section_id']} | {row['section_title'][:50]}")
        return 0

    updated = pd.concat([new_df, existing_df], ignore_index=True)
    updated = updated.drop_duplicates(subset=["url"], keep="first").reset_index(drop=True)

    push_hf_dataset(updated, cfg["repo"], cfg["cache"], log)
    log.info(f"{tag} Done. {len(updated)} total sections (+{len(new_df)} new)")
    return 0
