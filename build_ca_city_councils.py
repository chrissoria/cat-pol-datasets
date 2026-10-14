#!/usr/bin/env python3
"""
Build chrissoria/ca-city-councils: the city councils of California in one
dataset, one shape, to be filtered by city.

It is made the way chrissoria/ca-county-boards is, by the same code
(build_ca_county_boards.py), and kept apart from it: a council's rows say
`city` and `city_fips` where a board's say `county` and `county_fips`, the
table of them is `data/cities.parquet`, and each city keeps its own room.
Each council's record is read by its reader (build_sd_council.py,
build_legistar_council.py), which writes the city's five tables in a folder
here; this script takes those folders and writes

    data/<table>/<city>.parquet     the five tables, one file a city
    data/cities.parquet             one row a city
    raw/<city>/<table>.parquet      each reader's own tables as it wrote them
    world/<city>/chamber.json.gz    the city's room in Capitol World, where it has one

    python build_ca_city_councils.py --no-upload            # every city, written here
    python build_ca_city_councils.py --city oakland         # one city's files, and the cities table
    python build_ca_city_councils.py --write-card           # publish the card too

A reader publishes its city here itself when it is run without --no-upload
(council_tables.publish sends it on to publish_city).
"""

import logging
import sys

import build_ca_county_boards as boards
import build_federal_bills as bills

log = logging.getLogger(__name__)

REPO = "chrissoria/ca-city-councils"
OUT_DIR = bills.SCRIPT_DIR / "ca_city_councils"
CARD_FILE = bills.SCRIPT_DIR / "README_ca_city_councils.md"

LEGISTAR = {"system": "Legistar", "read_from": boards.SYSTEM, "builder": "build_legistar_council.py"}

# `daily` is for a council the daily run reads again, each by its own step (docs/cloud_routine.md).
# Each council here: its id in bodies.json, then how its record is kept and read, and what to know of it. `repo` is the
# name its reader still publishes under, which council_tables sends here.
CITIES = {
    "sd-council": {"system": "OnBase Agenda Online (results summaries)", "read_from": boards.DISTRICTS, "builder": "build_sd_council.py",
                   "folder": "sdcouncil", "repo": "chrissoria/san-diego-council", "daily": True, "extra": ["rosters"],
                   "note": "Votes are read from the Clerk's results summary of each meeting, which gives the vote by district "
                           "(\"12356789-yea; 4-nay\"); the agenda says who held each district that day. The minutes, which "
                           "name the members, are not read."},
    "oakland-council": {**LEGISTAR, "folder": "legistar/oakland", "repo": "chrissoria/oakland-council", "daily": True},
    "long-beach-council": {**LEGISTAR, "folder": "legistar/long-beach", "repo": "chrissoria/long-beach-council",
                           "note": "Its record in Legistar ends in 2023, when the City left that system."},
    "fresno-council": {**LEGISTAR, "folder": "legistar/fresno", "repo": "chrissoria/fresno-council", "daily": True},
    "salinas-council": {**LEGISTAR, "folder": "legistar/salinas", "repo": "chrissoria/salinas-council", "daily": True},
}

CITY = boards.Collection(REPO, OUT_DIR, CARD_FILE, CITIES, "city", "cities", (" City Council",))


def city_of(repo):
    """The council whose tables a reader's dataset name is for ("oakland-council"), or None."""
    return next((key for key, city in CITIES.items() if city["repo"] == repo), None)


def slug_of(key):
    """The name a city's files go by here ("san-diego"), from its body's name in bodies.json."""
    return boards.facts_of(key, kind=CITY)["slug"]


def publish_city(key, folder, out_dir=OUT_DIR):
    """Publish one city from the tables its reader has just written in `folder`. Every reader of a city council ends here."""
    return boards.publish_county(key, folder, out_dir, kind=CITY)


def main(argv=None):
    return boards.main(argv, kind=CITY)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(main())
