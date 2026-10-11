#!/usr/bin/env python3
"""The old name of the California bills update. build_california_bills.py does the work now.

Kept so that the old command, and a schedule still pointing at it, run the new
build rather than the one that published a partial table.

    python update_california_bills.py             # the same as: python build_california_bills.py
    python update_california_bills.py --dry-run   # the same as: python build_california_bills.py --no-upload
"""

import logging
import sys

import build_california_bills

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asked = [arg for arg in sys.argv[1:] if arg != "--full"]  # every run reads the whole session now
    sys.exit(build_california_bills.main(["--no-upload" if arg == "--dry-run" else arg for arg in asked]))
