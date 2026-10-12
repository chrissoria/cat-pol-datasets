#!/usr/bin/env python3
"""Generic puller for municipal.codes cities that require Playwright scraping."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from lib.document_text import jittered_sleep
from lib.hf_utils import load_hf_dataset, push_hf_dataset

SCRIPT_DIR = Path(__file__).resolve().parent
CHECKPOINT_DIR = SCRIPT_DIR / "checkpoints"

MUNICIPAL_CODES_CITIES = {
    "ber": {
        "name": "Berkeley",
        "repo": "chrissoria/berkeley-ordinances",
        "cache": SCRIPT_DIR / ".ber_cache.parquet",
        "base_url": "https://berkeley.municipal.codes",
        "fallback": CHECKPOINT_DIR / "berkeley_final_dataset.parquet",
        "max_pages": 5,
    },
    "bak": {
        "name": "Bakersfield",
        "repo": "chrissoria/bakersfield-ordinances",
        "cache": SCRIPT_DIR / ".bak_cache.parquet",
        "base_url": "https://bakersfield.municipal.codes",
        "fallback": CHECKPOINT_DIR / "bakersfield_final_dataset.parquet",
        "max_pages": 3,
    },
}


def pull_municipal_codes_city(city_key: str, log: logging.Logger, dry_run: bool = False) -> int:
    """Incremental update for a municipal.codes city."""
    cfg = MUNICIPAL_CODES_CITIES[city_key]
    tag = f"[{cfg['name']}]"

    log.info("=" * 50)
    log.info(f"{tag} Starting update ({'DRY RUN' if dry_run else 'LIVE'})")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error(f"{tag} Playwright not installed. Skipping.")
        return 1

    existing_df = load_hf_dataset(cfg["repo"], cfg["cache"], log)
    if existing_df.empty:
        if cfg["fallback"].exists():
            existing_df = pd.read_parquet(cfg["fallback"])
            log.info(f"{tag} Loaded {len(existing_df)} rows from build checkpoint")
        else:
            log.error(f"{tag} No existing dataset. Run the corresponding build script first.")
            return 1

    existing_ords = set(existing_df["ordinance_number"].astype(str).tolist())
    log.info(f"{tag} Existing: {len(existing_df)} rows")

    new_rows = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()
            page.goto(f"{cfg['base_url']}/enactments", timeout=60000)
            page.wait_for_timeout(5000)

            found_existing = False
            for page_num in range(1, cfg["max_pages"] + 1):
                url = f"{cfg['base_url']}/enactments?page={page_num}"
                page.goto(url, timeout=30000)
                page.wait_for_timeout(2000)

                tables = page.query_selector_all("table")
                if len(tables) < 2:
                    if page_num == 1:
                        # No listing at all: a bot check or block page, not "nothing new"
                        raise RuntimeError("no enactments table on page 1 (bot check or block page?)")
                    break

                rows = tables[1].query_selector_all("tr")
                page_new = 0

                for row in rows:
                    cells = row.query_selector_all("td")
                    if len(cells) < 4:
                        continue

                    a_tag = cells[0].query_selector("a")
                    ord_num = a_tag.inner_text().strip() if a_tag else cells[0].inner_text().strip()
                    detail_url = ""
                    if a_tag:
                        detail_path = a_tag.get_attribute("href") or ""
                        detail_url = f"{cfg['base_url']}{detail_path}" if detail_path.startswith("/") else detail_path

                    # Rows of other tables on the page (the reader's settings) have no enactment link
                    if "/enactments/" not in detail_url:
                        continue

                    if ord_num in existing_ords:
                        found_existing = True
                        continue

                    # A year-only cell gives the year and no date; "—" gives neither.
                    date_raw = cells[2].inner_text().strip()
                    date = ""
                    year = 0
                    try:
                        dt = datetime.strptime(date_raw, "%m/%d/%Y")
                        date = dt.strftime("%Y-%m-%d")
                        year = dt.year
                    except (ValueError, TypeError):
                        if date_raw.isdigit() and len(date_raw) == 4:
                            year = int(date_raw)

                    num_lower = ord_num.lower()
                    doc_type = "resolution" if "res" in num_lower else "ordinance"

                    entry = {
                        "date": date,
                        "ordinance_number": ord_num,
                        "doc_type": doc_type,
                        "title": cells[1].inner_text().strip(),
                        "text": "",
                        "disposition": cells[3].inner_text().strip(),
                        "effective_date": "",
                        "url": detail_url,
                        "year": year,
                    }

                    if detail_url:
                        try:
                            page.goto(detail_url, timeout=30000)
                            page.wait_for_timeout(1500)
                            main = page.query_selector("#main-column, main, article")
                            entry["text"] = main.inner_text().strip() if main else page.inner_text("body").strip()
                            eff = re.search(r"Effective From\n\s*(\d{1,2}/\d{1,2}/\d{4})", entry["text"])
                            if eff:
                                entry["effective_date"] = datetime.strptime(eff.group(1), "%m/%d/%Y").strftime("%Y-%m-%d")
                        except Exception as e:
                            log.warning(f"{tag} Detail page failed for {ord_num}: {e}")
                        jittered_sleep(2.0)

                    new_rows.append(entry)
                    page_new += 1

                log.info(f"{tag} Page {page_num}: {page_new} new entries")
                if found_existing and page_new == 0:
                    break
                jittered_sleep(3.0)

            browser.close()
    except Exception as e:
        log.error(f"{tag} Playwright scraping failed: {e}")
        if not new_rows:
            return 1

    if not new_rows:
        log.info(f"{tag} No new entries. Up to date.")
        return 0

    new_df = pd.DataFrame(new_rows)
    log.info(f"{tag} Found {len(new_df)} new entries")

    if dry_run:
        for _, row in new_df.iterrows():
            log.info(f"  {row['date']} | {row['ordinance_number']} | {row['title'][:60]}")
        return 0

    updated = pd.concat([new_df, existing_df], ignore_index=True)
    updated = updated.drop_duplicates(subset=["ordinance_number"], keep="first")
    updated = updated.sort_values("date", ascending=False).reset_index(drop=True)

    push_hf_dataset(updated, cfg["repo"], cfg["cache"], log)
    log.info(f"{tag} Done. {len(updated)} total rows (+{len(new_df)} new)")
    return 0
