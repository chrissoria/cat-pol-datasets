#!/usr/bin/env python3
"""
The bodies that make law and that these scripts hold records of: Congress, a
state's legislature, a county's board, a city's council. They are listed once,
in bodies.json, and everything else reads that list:

    build_places.py            the `bodies` table of us-places, the counts on each
                               place's row, and world/bodies.json, which Capitol
                               World reads to know which places have a room
    build_chamber_snapshot.py  where a body's tables are, to write its room's file

To add a body, add an entry to bodies.json. Each has:

    id, place     a short name of its own, and the Census code of the place it governs
    name, body    "San Diego City Council" and "City Council"
    datasets      the datasets with its records: `records` is the table with one row
                  per ordinance, bill or item, `date` its date column, and `meetings`
                  and `votes` the tables of those, if there are any

and, once it has a room in Capitol World:

    world         "chamber" for a board or council in one room; a world's own key otherwise
    chamber       where its tables are published and kept here, and what its table of
                  members is called; and, for a record too long to load as one file,
                  the day its room starts (`from`) and the most letters a title is
                  shown at (`titles`)
    short, room, member, seat, timezone, site, url, since
                  how the room words things: "the Council", "Council Chambers",
                  "Councilmember", "District", its time zone, what its own site is
                  called and where it is, and how far back the record goes
    surnames      family names of more than one word, by the member's name
"""

import json
from pathlib import Path

FILE = Path(__file__).resolve().parent / "bodies.json"


def read_bodies(path=FILE):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def chambers(path=FILE):
    """The bodies that have a room of their own, by id: {"sd-county": {"repo", "folder", "members", "surnames"}}."""
    return {body["id"]: {**body["chamber"], "surnames": body.get("surnames", {})} for body in read_bodies(path) if body.get("chamber")}
