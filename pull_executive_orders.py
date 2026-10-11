#!/usr/bin/env python3
"""The executive orders step of the weekly local updater (update_datasets.py).

The work is done by update_executive_orders.py, which the daily cloud run also
calls. The step used to rebuild the table from the Federal Register's latest
100 listings, which cut the published dataset from 10,780 rows to 101.
"""

from __future__ import annotations

import logging


def pull_executive_orders(log: logging.Logger, dry_run: bool = False) -> int:
    import update_executive_orders

    try:
        return update_executive_orders.main(["--no-upload"] if dry_run else [])
    except Exception as e:
        log.error(f"Executive orders not updated: {e}")
        return 1
