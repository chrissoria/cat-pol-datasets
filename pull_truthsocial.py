#!/usr/bin/env python3
"""Pull and normalize Trump Truth Social posts without enrichment or publishing."""

from __future__ import annotations

import argparse
import logging
from html import unescape
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from lib.hf_utils import load_hf_dataset
from lib.logging_utils import setup_logging

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_DIR = SCRIPT_DIR / "logs"
CHECKPOINT_DIR = SCRIPT_DIR / "checkpoints" / "truthsocial"
TS_REPO = "chrissoria/trump-truth-social"
TS_CACHE = SCRIPT_DIR / ".ts_cache.parquet"
TS_ARCHIVE_URL = "https://ix.cnn.io/data/truth-social/truth_archive.json"

_TRUMP_TERMS = [
    ("2017-01-20", "2021-01-20"),
    ("2025-01-20", None),
]

_TRUMP_ELECT_TERMS = [
    ("2016-11-08", "2017-01-20"),
    ("2024-11-05", "2025-01-20"),
]


def is_president(date_str: str) -> bool:
    """Return True if the given date falls within a Trump presidential term."""
    if not date_str or len(date_str) < 10:
        return False
    day = date_str[:10]
    for start, end in _TRUMP_TERMS:
        if day >= start and (end is None or day < end):
            return True
    return False


def is_president_elect(date_str: str) -> bool:
    """Return True if the given date falls within a Trump president-elect period."""
    if not date_str or len(date_str) < 10:
        return False
    day = date_str[:10]
    for start, end in _TRUMP_ELECT_TERMS:
        if day >= start and day < end:
            return True
    return False


def html_to_text(html: str) -> str:
    """Convert stored post HTML into plain text."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    return unescape(soup.get_text()).strip()


def pull_truthsocial_dataset(
    log: logging.Logger,
    repo_id: str = TS_REPO,
    cache_path: Path = TS_CACHE,
    archive_url: str = TS_ARCHIVE_URL,
    checkpoint_path: Path = CHECKPOINT_DIR / "trump_truths.parquet",
    dry_run: bool = False,
) -> tuple[int, pd.DataFrame, pd.DataFrame]:
    """Fetch the Truth Social archive, normalize rows, and merge with existing data."""
    tag = "[TruthSocial]"
    log.info("=" * 50)
    log.info(f"{tag} Starting pull ({'DRY RUN' if dry_run else 'LIVE'})")

    existing_df = load_hf_dataset(repo_id, cache_path, log)
    if existing_df.empty and checkpoint_path.exists():
        existing_df = pd.read_parquet(checkpoint_path)
        log.info(f"{tag} Loaded {len(existing_df)} posts from local checkpoint")

    existing_ids = set()
    if not existing_df.empty:
        existing_ids = set(existing_df["post_id"].astype(str).tolist())
    log.info(f"{tag} Existing: {len(existing_ids)} posts")

    log.info(f"{tag} Fetching archive from CNN...")
    try:
        resp = requests.get(archive_url, timeout=60)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.error(f"{tag} Failed to fetch archive: {e}")
        return 1, existing_df, pd.DataFrame()

    log.info(f"{tag} Archive contains {len(data)} posts")

    new_rows: list[dict] = []
    for post in data:
        pid = str(post.get("id", ""))
        if pid in existing_ids:
            continue

        content_html = post.get("content", "")
        media = post.get("media", [])
        media_urls = [
            item.get("url", "") if isinstance(item, dict) else str(item)
            for item in media
            if item
        ]
        created = post.get("created_at", "")

        links = []
        if content_html:
            try:
                soup = BeautifulSoup(content_html, "html.parser")
                links = [a["href"] for a in soup.find_all("a", href=True)]
            except Exception:
                pass

        new_rows.append({
            "date": created[:10] if created else "",
            "datetime": created,
            "text": html_to_text(content_html),
            "content_html": content_html,
            "url": post.get("url", ""),
            "post_id": pid,
            "replies_count": post.get("replies_count", 0),
            "reblogs_count": post.get("reblogs_count", 0),
            "favourites_count": post.get("favourites_count", 0),
            "media_urls": "; ".join(media_urls) if media_urls else "",
            "links": "; ".join(links) if links else "",
            "has_media": len(media_urls) > 0,
            "is_president": is_president(created),
            "is_president_elect": is_president_elect(created),
            "day_of_week": pd.Timestamp(created).day_name() if created else "",
            "time": created[11:19] if created and len(created) >= 19 else "",
        })

    new_df = pd.DataFrame(new_rows) if new_rows else pd.DataFrame()
    log.info(f"{tag} Found {len(new_df)} new posts")

    if dry_run:
        if not new_df.empty:
            for _, row in new_df.head(10).iterrows():
                log.info(f"  {row['date']} | {row['text'][:60]}")
        else:
            log.info(f"{tag} No new posts. Up to date.")
        return 0, existing_df, new_df

    if not existing_df.empty:
        archive_map = {str(post["id"]): post for post in data}
        for idx, row in existing_df.iterrows():
            pid = str(row["post_id"])
            if pid in archive_map:
                post = archive_map[pid]
                existing_df.at[idx, "replies_count"] = post.get("replies_count", 0)
                existing_df.at[idx, "reblogs_count"] = post.get("reblogs_count", 0)
                existing_df.at[idx, "favourites_count"] = post.get("favourites_count", 0)
                media = post.get("media", [])
                urls = [
                    item.get("url", "") if isinstance(item, dict) else str(item)
                    for item in media
                    if item
                ]
                existing_df.at[idx, "media_urls"] = "; ".join(urls) if urls else ""
                existing_df.at[idx, "has_media"] = len(urls) > 0

    updated = pd.concat([new_df, existing_df], ignore_index=True) if not new_df.empty else existing_df.copy()
    updated = updated.drop_duplicates(subset=["post_id"], keep="first")
    updated = updated.sort_values("datetime", ascending=False).reset_index(drop=True)
    updated["is_president"] = updated["date"].apply(is_president)
    updated["is_president_elect"] = updated["date"].apply(is_president_elect)
    updated["day_of_week"] = pd.to_datetime(updated["date"], errors="coerce").dt.day_name()
    updated["time"] = pd.to_datetime(updated["datetime"], errors="coerce").dt.strftime("%H:%M:%S").fillna("")

    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    updated.to_parquet(checkpoint_path, index=False)
    log.info(f"{tag} Saved normalized checkpoint: {checkpoint_path}")
    return 0, updated, new_df


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull and normalize Truth Social posts")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and inspect without writing checkpoint")
    args = parser.parse_args()

    log = setup_logging(LOG_DIR, logger_name="truthsocial_pull")
    rc, _, _ = pull_truthsocial_dataset(log, dry_run=args.dry_run)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
