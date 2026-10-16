#!/usr/bin/env python3
"""
The daily run of California's county boards, a routine of its own (docs/cloud_routine.md).

San Diego County first (build_sd_county.py, which also feeds sd-county-ordinances), then the counties of
chrissoria/ca-county-boards with a reader the cloud can run, longest unread first, until `--minutes` are used
(build_ca_county_boards.read_some). Each step's failure stops that step only. Each step logs its own RESULT line,
and this script ends with one of its own:

    RESULT: ca-counties steps=<n> failed=<names> pushed=<True|False>

    python3 run_ca_counties.py --minutes 60
"""

import argparse
import logging
import sys

import local_steps

log = logging.getLogger(__name__)

STEPS = (
    ("build_sd_county", [], "San Diego County tables"),
    # Last, since it is the longest: San Diego County's tables copied into the one dataset of county boards, and the
    # counties longest unread read again. Each county's turn comes every few days.
    ("build_ca_county_boards", ["--read", "--minutes", "{minutes}"], "County boards"),
)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bring California's county boards up to date")
    parser.add_argument("--minutes", type=int, default=60, help="stop starting counties after this many minutes")
    args = parser.parse_args(argv)
    return local_steps.run("ca-counties", [(module, [part.format(minutes=args.minutes) for part in arguments], what)
                                           for module, arguments, what in STEPS])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(main())
