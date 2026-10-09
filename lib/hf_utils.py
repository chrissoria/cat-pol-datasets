from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pandas as pd


def get_hf_token() -> str | None:
    """Return the Hugging Face repo token used for dataset reads and writes."""
    return os.getenv("CATLLM_HUGGINGFACE_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")


def get_hf_api_key() -> str | None:
    """Return the Hugging Face-compatible API key used by enrichment jobs."""
    return os.getenv("HUGGINGFACE_API_KEY") or os.getenv("HF_API_KEY") or get_hf_token()


def load_hf_dataset(repo_id: str, cache_path: Path, log: logging.Logger) -> pd.DataFrame:
    """Load dataset from Hugging Face with local caching."""
    try:
        from datasets import load_dataset
    except ImportError:
        log.error("datasets package not installed: pip install datasets")
        sys.exit(1)

    if cache_path.exists():
        log.info(f"Loading from cache: {cache_path}")
        return pd.read_parquet(cache_path)

    log.info(f"Downloading from HuggingFace: {repo_id}")
    try:
        ds = load_dataset(repo_id, split="train")
        df = ds.to_pandas()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache_path, index=False)
        log.info(f"Cached {len(df)} rows")
        return df
    except Exception as e:
        log.error(f"Failed to load {repo_id}: {e}")
        return pd.DataFrame()


def push_hf_dataset(df: pd.DataFrame, repo_id: str, cache_path: Path, log: logging.Logger) -> None:
    """Push dataset to Hugging Face and update the local cache."""
    try:
        from datasets import Dataset
        from huggingface_hub import HfApi
    except ImportError:
        log.error("datasets/huggingface_hub not installed")
        return

    token = get_hf_token()
    if not token:
        log.error("No HuggingFace token. Set CATLLM_HUGGINGFACE_TOKEN or HUGGINGFACE_TOKEN in .env")
        return

    HfApi(token=token)
    ds = Dataset.from_pandas(df)
    ds.push_to_hub(repo_id, token=token, private=False)
    log.info(f"Pushed {len(df)} rows to https://huggingface.co/datasets/{repo_id}")

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache_path, index=False)
