#!/usr/bin/env python3
"""Classify remaining ordinances for SD and SF, merge results, and push to Hugging Face."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
from datasets import Dataset, load_dataset
from dotenv import load_dotenv
from huggingface_hub import HfApi

import cat_pol as pol

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "checkpoints" / "classifications"

load_dotenv(PROJECT_ROOT / ".env", override=True)

CATEGORIES = [
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

CAT_COLS = [f"category_{i}" for i in range(1, 14)]
CAT_NAMES = [c.split("(")[0].strip() for c in CATEGORIES] + ["Other"]

CITY_CONFIG = {
    "sd": {
        "repo": "chrissoria/san-diego-ordinances",
        "context": "San Diego city ordinances",
        "seed_csv": SCRIPT_DIR / "checkpoints" / "classifications" / "sd_classified_1000.csv",
        "filter": lambda df: (df["doc_type"] == "ordinance") & (df["text"].fillna("").str.len() > 0),
        "sort_desc": True,
    },
    "sf": {
        "repo": "chrissoria/sf-ordinances",
        "context": "San Francisco city ordinances",
        "seed_csv": SCRIPT_DIR / "checkpoints" / "classifications" / "sf_classified_1000.csv",
        "filter": lambda df: df["text"].fillna("").str.len() > 0,
        "sort_desc": False,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify remaining SD or SF ordinances")
    parser.add_argument("city", choices=sorted(CITY_CONFIG), nargs="?", default="sd")
    parser.add_argument(
        "--existing-csv",
        type=Path,
        help="Optional CSV with existing classifications to seed the merge",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for batch CSV output (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the merged dataset but skip the Hugging Face push",
    )
    return parser.parse_args()


def load_existing_seed(path: Path | None) -> pd.DataFrame:
    if path is None:
        return pd.DataFrame()
    if not path.exists():
        print(f"Seed CSV not found, starting fresh: {path}")
        return pd.DataFrame()
    return pd.read_csv(path)


def get_text_subset(df: pd.DataFrame, city: str) -> pd.DataFrame:
    config = CITY_CONFIG[city]
    subset = df[config["filter"](df)]
    if config["sort_desc"]:
        subset = subset.sort_values("date", ascending=False)
    return subset.reset_index(drop=True)


def main() -> int:
    args = parse_args()
    config = CITY_CONFIG[args.city]
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY not found in .env")
        return 1

    token = os.getenv("CATLLM_HUGGINGFACE_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
    if not args.dry_run and not token:
        print("Hugging Face token not found in .env")
        return 1

    existing_csv = args.existing_csv or config["seed_csv"]

    print(f"Loading {args.city.upper()} dataset...")
    ds = load_dataset(config["repo"], split="train")
    df = ds.to_pandas()
    ords = get_text_subset(df, args.city)
    print(f"Total ordinances with text: {len(ords)}")

    existing = load_existing_seed(existing_csv)
    already_done = min(len(existing), len(ords))
    print(f"Already classified: {already_done}")

    remaining = ords.iloc[already_done:]
    print(f"Remaining: {len(remaining)}")

    if len(remaining) == 0:
        print("All done!")
        return 0

    print(f"\nClassifying {len(remaining)} remaining ordinances (batch mode)...")
    new_results = pol.classify(
        input_data=remaining["text"].tolist(),
        categories=CATEGORIES,
        document_context=config["context"],
        api_key=api_key,
        add_other=True,
        check_verbosity=False,
        batch_mode=True,
        filename=f"{args.city}_remaining_{len(remaining)}.csv",
        save_directory=str(output_dir),
    )

    print(f"New results: {new_results.shape}")
    print(f"Status: {new_results['processing_status'].value_counts().to_dict()}")
    print("\nMerging classifications onto full dataset...")

    for col in CAT_COLS:
        ords[col] = pd.NA
    ords["classification_status"] = ""

    for i in range(already_done):
        for col in CAT_COLS:
            if col in existing.columns:
                ords.at[i, col] = existing.at[i, col]
        if "processing_status" in existing.columns:
            ords.at[i, "classification_status"] = existing.at[i, "processing_status"]

    for i, (_, row) in enumerate(new_results.iterrows()):
        orig_idx = already_done + i
        if orig_idx >= len(ords):
            break
        for col in CAT_COLS:
            if col in new_results.columns:
                ords.at[orig_idx, col] = row[col]
        ords.at[orig_idx, "classification_status"] = row["processing_status"]

    classified_count = (ords["classification_status"] == "success").sum()
    print(f"Total classified: {classified_count}/{len(ords)}")

    for col in CAT_COLS + ["classification_status"]:
        df[col] = pd.NA

    text_indices = get_text_subset(df, args.city).index.tolist()
    for ords_idx in range(len(ords)):
        if ords_idx < len(text_indices):
            df_idx = text_indices[ords_idx]
            for col in CAT_COLS + ["classification_status"]:
                df.at[df_idx, col] = ords.at[ords_idx, col]

    rename_map = {f"category_{i + 1}": name for i, name in enumerate(CAT_NAMES)}
    df = df.rename(columns=rename_map)

    print(f"\nFull dataset with classifications: {df.shape}")
    classified_in_full = (df["classification_status"] == "success").sum()
    print(f"Classified rows in full dataset: {classified_in_full}")

    if args.dry_run:
        print("Dry run: skipping Hugging Face push")
        return 0

    api = HfApi(token=token)
    api.whoami()
    ds_out = Dataset.from_pandas(df)
    ds_out.push_to_hub(config["repo"], token=token, private=False)
    print(f"Pushed {len(df)} rows to {config['repo']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
