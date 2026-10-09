#!/usr/bin/env python3
"""Classify unclassified ordinance rows in existing dataset caches and optionally publish them."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from lib.hf_utils import get_hf_api_key, load_hf_dataset, push_hf_dataset
from lib.logging_utils import setup_logging

CLASSIFY_CATEGORIES = [
    "Community Plan Updates (e.g., comprehensive plans, neighborhood plans)",
    "Contract Amendments (e.g., modifications, revisions)",
    "Environmental Compliance (e.g., stormwater regulations, habitat protections)",
    "Infrastructure Projects (e.g., road improvements, water systems)",
    "Public Safety Communications (e.g., emergency response systems, communication networks)",
    "Construction Management Services (e.g., project oversight, coordination)",
    "Rezoning (e.g., residential to commercial, density adjustments)",
    "Historical Preservation (e.g., landmark designation, restoration projects)",
    "Health and Safety Applications (e.g., permits, inspections)",
    "Public Art Projects (e.g., murals, sculptures)",
    "Parking Management Services (e.g., lot management, enforcement)",
    "Housing Development (e.g., affordable housing, new construction)",
]

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_DIR = SCRIPT_DIR / "logs"


def _build_city_configs() -> dict[str, dict]:
    return {
        "sd": {
            "label": "SD",
            "repo": "chrissoria/san-diego-ordinances",
            "cache": SCRIPT_DIR / ".sd_cache.parquet",
            "filter": lambda df: (df["doc_type"] == "ordinance") & (df["text"].fillna("").str.len() > 0),
        },
        "sf": {
            "label": "SF",
            "repo": "chrissoria/sf-ordinances",
            "cache": SCRIPT_DIR / ".sf_cache.parquet",
            "filter": lambda df: df["text"].fillna("").str.len() > 0,
        },
        "sal": {
            "label": "SAL",
            "repo": "chrissoria/salinas-ordinances",
            "cache": SCRIPT_DIR / ".sal_cache.parquet",
            "filter": lambda df: (df["doc_type"] == "ordinance") & (df["text"].fillna("").str.len() > 0),
        },
    }


def classify_updated_ordinances(
    log: logging.Logger,
    city_configs: dict[str, dict] | None = None,
    dry_run: bool = False,
) -> int:
    """Classify unclassified ordinance rows in the configured datasets."""
    hf_key = get_hf_api_key()
    if not hf_key:
        log.info("[Classify] No HuggingFace credential found, skipping classification.")
        return 0

    import cat_pol as pol

    city_configs = city_configs or _build_city_configs()
    result_code = 0

    for city_key, config in city_configs.items():
        tag = f"[Classify-{config['label']}]"
        try:
            existing_df = load_hf_dataset(config["repo"], config["cache"], log)
            if existing_df.empty:
                continue

            if "classification_status" not in existing_df.columns:
                log.info(f"{tag} Initializing classification columns (first run).")
                existing_df["classification_status"] = pd.NA

            mask = config["filter"](existing_df) & (
                existing_df["classification_status"].isna()
                | (existing_df["classification_status"] == "")
            )
            unclassified = existing_df[mask]

            if len(unclassified) == 0:
                log.info(f"{tag} All ordinances classified. Up to date.")
                continue

            log.info(f"{tag} Found {len(unclassified)} unclassified ordinances.")
            results = pol.classify(
                input_data=unclassified["text"].tolist(),
                categories=CLASSIFY_CATEGORIES,
                document_context=f"{config['label']} city ordinances",
                api_key=hf_key,
                user_model="qwen/qwen2.5-vl-72b-instruct:novita",
                model_source="huggingface",
                add_other=True,
                check_verbosity=False,
            )

            if results is None or results.empty:
                log.warning(f"{tag} Classification returned no results.")
                continue

            cat_cols = [col for col in results.columns if col.startswith("category_")]
            for i, (orig_idx, _) in enumerate(unclassified.iterrows()):
                if i >= len(results):
                    break
                for col in cat_cols:
                    if col in results.columns:
                        existing_df.at[orig_idx, col] = results.iloc[i][col]
                existing_df.at[orig_idx, "classification_status"] = results.iloc[i]["processing_status"]

            classified = int((results["processing_status"] == "success").sum())
            log.info(f"{tag} Classified {classified}/{len(unclassified)} new ordinances.")

            if dry_run:
                log.info(f"{tag} Dry run: skipping dataset push.")
                continue

            push_hf_dataset(existing_df, config["repo"], config["cache"], log)
            log.info(f"{tag} Pushed updated dataset.")
        except Exception as e:
            result_code = 1
            log.error(f"{tag} Classification failed: {e}")

    return result_code


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify unclassified ordinance rows for existing datasets")
    parser.add_argument(
        "--city",
        choices=["sd", "sf", "sal", "all"],
        default="all",
        help="Dataset to classify",
    )
    parser.add_argument("--dry-run", action="store_true", help="Classify but skip dataset push")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    log = setup_logging(LOG_DIR, logger_name="ordinance_classify")
    city_configs = _build_city_configs()
    if args.city != "all":
        city_configs = {args.city: city_configs[args.city]}
    return classify_updated_ordinances(log, city_configs=city_configs, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
