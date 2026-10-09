#!/usr/bin/env python3
from __future__ import annotations

import logging
from pathlib import Path

from lib.hf_utils import load_hf_dataset

SCRIPT_DIR = Path(__file__).resolve().parent
SPEECH_REPO = "chrissoria/presidential-speeches"
SPEECH_CACHE = SCRIPT_DIR / ".speech_cache.parquet"


def pull_presidential_speeches(log: logging.Logger, dry_run: bool = False) -> int:
    existing_df = load_hf_dataset(SPEECH_REPO, SPEECH_CACHE, log)
    return 0 if not existing_df.empty else 1
