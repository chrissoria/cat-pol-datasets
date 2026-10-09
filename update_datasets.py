#!/usr/bin/env python3
"""Weekly incremental updater for all datasets."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from classify_ordinances import classify_updated_ordinances
from classify_truthsocial import classify_truthsocial_posts
from enrich_truthsocial_media import enrich_truthsocial_media
from lib.hf_utils import get_hf_api_key
from lib.logging_utils import setup_logging as build_logger
from publish_dataset import validate_and_publish_dataset
from pull_codepublishing_city import CODEPUB_CITIES as FAMILY_CODEPUB_CITIES, pull_codepublishing_city
from pull_executive_orders import pull_executive_orders
from pull_federal_laws import pull_federal_laws
from pull_la import pull_la
from pull_legistar_city import LEGISTAR_CITIES as FAMILY_LEGISTAR_CITIES, pull_legistar_city
from pull_municipal_codes_city import MUNICIPAL_CODES_CITIES, pull_municipal_codes_city
from pull_presidential_speeches import pull_presidential_speeches
from pull_salinas import pull_salinas
from pull_san_diego import pull_san_diego
from pull_san_francisco import pull_san_francisco
from pull_sd_county import pull_sd_county
from pull_truthsocial import pull_truthsocial_dataset

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).parent
LOG_DIR = SCRIPTS_DIR / "logs"
CHECKPOINT_DIR = SCRIPTS_DIR / "checkpoints"

load_dotenv(PROJECT_ROOT / ".env", override=True)

HF_API_KEY = get_hf_api_key()

SD_REPO = "chrissoria/san-diego-ordinances"
SD_CACHE = SCRIPTS_DIR / ".sd_cache.parquet"
SF_REPO = "chrissoria/sf-ordinances"
SF_CACHE = SCRIPTS_DIR / ".sf_cache.parquet"
SAL_REPO = "chrissoria/salinas-ordinances"
SAL_CACHE = SCRIPTS_DIR / ".sal_cache.parquet"

TS_REPO = "chrissoria/trump-truth-social"
TS_CACHE = SCRIPTS_DIR / ".ts_cache.parquet"
TS_ARCHIVE_URL = "https://ix.cnn.io/data/truth-social/truth_archive.json"

ALL_CITIES = [
    "sd", "sf", "sal", "oak", "lb", "fre", "ber", "bak",
    "la", "clovis", "nb", "sdco", "fed", "eo", "speeches", "ts",
]


def setup_logging():
    return build_logger(LOG_DIR, logger_name="dataset_updater")


def update_trump_truths(log, dry_run: bool = False) -> int:
    """Run the staged Truth Social pipeline."""
    tag = "[TruthSocial]"
    checkpoint_path = CHECKPOINT_DIR / "truthsocial" / "trump_truths.parquet"
    rc, updated, new_df = pull_truthsocial_dataset(
        log,
        repo_id=TS_REPO,
        cache_path=TS_CACHE,
        archive_url=TS_ARCHIVE_URL,
        checkpoint_path=checkpoint_path,
        dry_run=dry_run,
    )
    if rc != 0:
        return rc
    if dry_run:
        return 0
    if updated.empty:
        log.info(f"{tag} No posts available after pull stage.")
        return 0

    ts_checkpoint_dir = CHECKPOINT_DIR / "truthsocial"
    updated = enrich_truthsocial_media(updated, log, ts_checkpoint_dir, HF_API_KEY, tag=tag)
    updated = classify_truthsocial_posts(updated, log, ts_checkpoint_dir, HF_API_KEY, tag=tag)

    cat_cols = sorted([col for col in updated.columns if col.startswith("cat_")])
    col_order = [
        "date", "time", "day_of_week", "datetime",
        "text", "content_html", "url",
    ] + cat_cols + [
        "post_id",
        "is_president", "is_president_elect",
        "replies_count", "reblogs_count", "favourites_count",
        "media_urls", "links", "has_media", "image_alt_text",
    ]
    col_order += [col for col in updated.columns if col not in col_order]
    col_order = [col for col in col_order if col in updated.columns]
    updated = updated[col_order]

    rc = validate_and_publish_dataset(
        df=updated,
        repo=TS_REPO,
        cache_path=TS_CACHE,
        log=log,
        key_columns=["post_id"],
        required_columns=["date", "datetime", "text", "post_id", "url"],
        dry_run=False,
    )
    if rc != 0:
        return rc

    log.info(f"{tag} Done. {len(updated)} total posts (+{len(new_df)} new)")
    return 0


def build_ordinance_classify_configs(cities: list[str]) -> dict[str, dict]:
    """Build configs for the post-update ordinance classification stage."""
    active = sorted({"sd", "sf", "sal"} & set(cities))
    return {
        city: {
            "label": city.upper(),
            "repo": {"sd": SD_REPO, "sf": SF_REPO, "sal": SAL_REPO}[city],
            "cache": {"sd": SD_CACHE, "sf": SF_CACHE, "sal": SAL_CACHE}[city],
            "filter": {
                "sd": lambda df: (df["doc_type"] == "ordinance") & (df["text"].fillna("").str.len() > 0),
                "sf": lambda df: df["text"].fillna("").str.len() > 0,
                "sal": lambda df: (df["doc_type"] == "ordinance") & (df["text"].fillna("").str.len() > 0),
            }[city],
        }
        for city in active
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly dataset updater for all cities")
    parser.add_argument("--dry-run", action="store_true", help="Scrape but don't push")
    parser.add_argument("--city", choices=ALL_CITIES + ["all"], default="all", help="Which city to update")
    parser.add_argument("--exclude", nargs="+", choices=ALL_CITIES, default=[], help="Sources to exclude")
    args = parser.parse_args()

    log = setup_logging()
    log.info("=" * 60)
    log.info(f"Dataset updater starting at {datetime.now(timezone.utc).isoformat()}")

    results: dict[str, int] = {}
    cities = ALL_CITIES if args.city == "all" else [args.city]
    cities = [city for city in cities if city not in args.exclude]

    for city in cities:
        if city == "sd":
            results["San Diego"] = pull_san_diego(log, dry_run=args.dry_run)
        elif city == "sf":
            results["San Francisco"] = pull_san_francisco(log, dry_run=args.dry_run)
        elif city == "sal":
            results["Salinas"] = pull_salinas(log, dry_run=args.dry_run)
        elif city in MUNICIPAL_CODES_CITIES:
            cfg = MUNICIPAL_CODES_CITIES[city]
            results[cfg["name"]] = pull_municipal_codes_city(city, log, dry_run=args.dry_run)
        elif city == "la":
            results["Los Angeles"] = pull_la(log, dry_run=args.dry_run)
        elif city == "sdco":
            results["SD County"] = pull_sd_county(log, dry_run=args.dry_run)
        elif city in FAMILY_CODEPUB_CITIES:
            cfg = FAMILY_CODEPUB_CITIES[city]
            results[cfg["name"]] = pull_codepublishing_city(city, log, dry_run=args.dry_run)
        elif city == "fed":
            results["Federal"] = pull_federal_laws(log, dry_run=args.dry_run)
        elif city == "eo":
            results["Executive Orders"] = pull_executive_orders(log, dry_run=args.dry_run)
        elif city == "speeches":
            results["Speeches"] = pull_presidential_speeches(log, dry_run=args.dry_run)
        elif city == "ts":
            results["TruthSocial"] = update_trump_truths(log, dry_run=args.dry_run)
        elif city in FAMILY_LEGISTAR_CITIES:
            cfg = FAMILY_LEGISTAR_CITIES[city]
            results[cfg["name"]] = pull_legistar_city(city, log, dry_run=args.dry_run)

    log.info("=" * 60)
    for city, rc in results.items():
        status = "OK" if rc == 0 else f"FAILED ({rc})"
        log.info(f"  {city}: {status}")
    log.info("All updates complete.")

    if not args.dry_run:
        city_configs = build_ordinance_classify_configs(cities)
        if city_configs:
            classify_updated_ordinances(log, city_configs=city_configs, dry_run=False)

    sys.exit(max(results.values()) if results else 0)


if __name__ == "__main__":
    main()
