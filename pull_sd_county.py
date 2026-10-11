#!/usr/bin/env python3
"""The old name of the San Diego County update. build_sd_county.py does the work now.

Kept so that `update_datasets.py --city sdco`, and the schedule that runs it, build the
whole dataset rather than publishing the one partial table it used to be.
"""

from __future__ import annotations

import logging

import build_sd_county


def pull_sd_county(log: logging.Logger, dry_run: bool = False) -> int:
    return build_sd_county.main(["--no-upload"] if dry_run else [])
