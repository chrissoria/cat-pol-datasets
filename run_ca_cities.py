#!/usr/bin/env python3
"""
The daily run of California's city councils and city ordinances, a routine of its own (docs/cloud_routine.md).

The councils go into chrissoria/ca-city-councils (San Diego by build_sd_council.py; Oakland, Fresno and Salinas by
build_legistar_council.py; Long Beach is not here, its record in Legistar ending in 2023), and Berkeley's ordinances
into berkeley-ordinances. Each step's failure stops that step only. Each logs its own RESULT line, and this script
ends with one of its own:

    RESULT: ca-cities steps=<n> failed=<names> pushed=<True|False>

    python3 run_ca_cities.py
"""

import logging
import sys

import local_steps

log = logging.getLogger(__name__)

STEPS = (
    ("build_sd_council", [], "San Diego City Council tables"),
    ("build_legistar_council", ["--city", "oakland"], "Oakland council tables"),
    ("build_legistar_council", ["--city", "fresno"], "Fresno council tables"),
    ("build_legistar_council", ["--city", "salinas"], "Salinas council tables"),
    ("build_berkeley", [], "Berkeley ordinances"),
)


def main(argv=None):
    return local_steps.run("ca-cities", STEPS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(main())
