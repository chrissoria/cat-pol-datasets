#!/usr/bin/env python3
"""
Write the file Capitol World reads for a county board or a city council: one
body that meets in one room.

It is made from the tables a local body's dataset has (build_sd_county.py
writes them for the San Diego County Board of Supervisors): items, meetings,
agenda_items, votes and the members. The file is world/chamber.json.gz beside
the dataset, and holds everything the app shows, in lists that run in
parallel:

    members   everyone who has sat on the body, with their seat and dates
    items     everything filed: its number, title, kind, subject, and the last
              thing done with it
    meetings  every meeting, newest first
    agenda    one entry per item on a meeting's agenda: what was done, the
              tally, and how each member voted, as one letter per member in
              the order of `members` (see VOTE_LETTERS)

    python build_chamber_snapshot.py                      # San Diego County, published
    python build_chamber_snapshot.py --body sd-council    # the San Diego City Council
    python build_chamber_snapshot.py --tables sdcounty --no-upload
"""

import argparse
import gzip
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import bodies
import build_federal_bills as bills

log = logging.getLogger(__name__)

FILE = "world/chamber.json.gz"
TABLES = ("items", "meetings", "agenda_items", "votes")
# The bodies that have a file: where each one's tables are published and kept here, and what its table of members is called.
BODIES = bodies.chambers()
PLAIN_ROLES = ("Member", "Councilmember", "Supervisor")  # a role that says no more than that the person sits on the body

# One letter for each way a member's vote is recorded; "-" where the record has none for them.
VOTE_LETTERS = {"AYE": "A", "NO": "N", "ABSENT": "X", "NOT PRESENT": "X", "EXCUSED": "X", "RECUSED": "R", "ABSTAIN": "S", "ABSTAINED": "S",
                "NON-VOTING": "V"}
RESULT_LETTERS = {"Pass": "P", "Fail": "F"}


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def listed(values):
    """The different values of a column, commonest first, and each row's place in that list."""
    values = values.fillna("").astype(str)
    names = values.value_counts().index.tolist()
    place = {name: index for index, name in enumerate(names)}
    return names, [place[value] for value in values]


def members_of(table, surnames=None):
    """
    One entry a person. Someone who has held two seats is given the later one, and the whole of their time. A family name of
    more than one word cannot be told from the name, so it is given: {"Marni von Wilpert": "von Wilpert"}.
    """
    people, surnames = [], {slug(name): surname for name, surname in (surnames or {}).items()}
    for name, seats in table.groupby("name", sort=False):
        seats = seats.sort_values(["serving", "start"])
        last = seats.iloc[-1]
        serving = bool(seats["serving"].any())
        ends = [end for end in seats["end"].fillna("") if end]
        firsts = [day for day in seats["first_vote"].fillna("") if day]
        lasts = [day for day in seats["last_vote"].fillna("") if day]
        people.append({
            "id": slug(name),
            "name": name,
            "surname": surnames.get(slug(name)) or name.split(" ")[-1],
            "seat": None if pd.isna(last["district"]) else int(last["district"]),
            "role": "" if last["role"] in PLAIN_ROLES or not serving and len(seats) > 1 else last["role"],
            "start": min(seats["start"].fillna("")) or "",
            "end": (last["end"] or "") if serving else (max(ends) if ends else ""),
            "serving": serving,
            "first_vote": min(firsts) if firsts else "",
            "last_vote": max(lasts) if lasts else "",
            "votes": int(seats["votes"].max()),
        })
    return sorted(people, key=lambda person: (not person["serving"], person["seat"] or 0, person["start"]))


def votes_by_item(votes, members):
    """For each agenda entry, one letter per member."""
    seat = {member["name"]: index for index, member in enumerate(members)}
    cast = {}
    for item_id, name, vote in zip(votes["item_id"], votes["member"], votes["vote"]):
        if name not in seat:
            continue
        letters = cast.setdefault(item_id, ["-"] * len(members))
        letters[seat[name]] = VOTE_LETTERS.get(vote, "-")
    return {item_id: "".join(letters) for item_id, letters in cast.items()}


def build(tables, today=None, surnames=None):
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    items, meetings, agenda, votes = (tables[name].fillna("") for name in TABLES[:4])
    members = members_of(tables["members"], surnames)
    person = {member["name"]: index for index, member in enumerate(members)}

    items = items.sort_values(["date", "matter_id"], ascending=[False, False]).reset_index(drop=True)
    at = {matter: index for index, matter in enumerate(items["matter_id"])}
    meetings = meetings.sort_values(["date", "meeting_id"], ascending=[False, False]).reset_index(drop=True)
    meeting_at = {meeting: index for index, meeting in enumerate(meetings["meeting_id"])}
    agenda = agenda[agenda["meeting_id"].isin(meeting_at)].copy()
    agenda["meeting"] = agenda["meeting_id"].map(meeting_at)
    agenda = agenda.sort_values(["meeting", "sequence"]).reset_index(drop=True)
    cast = votes_by_item(votes, members)

    # The lists of names are made once the rows are in their final order, since each row keeps its place in them.
    kinds, kind = listed(items["doc_type"])
    statuses, status = listed(items["status"])
    bodies, body = listed(pd.concat([items["body"], meetings["body"]], ignore_index=True))
    subjects, subject = listed(items["subject"])
    actions, action = listed(pd.concat([items["last_action"], agenda["action"]], ignore_index=True))

    acted = agenda.loc[agenda["action"] != "", "date"]
    data_through = max([d for d in acted if d <= today] or [d for d in meetings["date"] if d <= today] or [today])
    return {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_through": data_through,
        "vote_letters": {letter: name.title() for name, letter in VOTE_LETTERS.items() if name != "NOT PRESENT"},
        "members": members,
        "kinds": kinds, "statuses": statuses, "bodies": bodies, "subjects": subjects, "actions": actions,
        "items": {
            "id": items["matter_id"].tolist(),
            "file": items["matter_file"].tolist(),
            "title": items["title"].tolist(),
            "kind": kind,
            "status": status,
            "body": body[:len(items)],
            "subject": subject,
            "filed": items["date"].tolist(),
            "agenda": items["agenda_date"].tolist(),
            "acted": items["last_action_date"].tolist(),
            "action": action[:len(items)],
            "result": [RESULT_LETTERS.get(value, "") for value in items["result"]],
            "ayes": [int(n) for n in items["ayes"]],
            "noes": [int(n) for n in items["noes"]],
            "mover": [person.get(name, -1) for name in items["mover"]],
            "seconder": [person.get(name, -1) for name in items["seconder"]],
            "times": [int(n) for n in items["times_on_agenda"]],
            "has_text": [1 if text else 0 for text in items["text"]] if "text" in items.columns else [0] * len(items),
            "url": items["url"].tolist(),
        },
        "meetings": {
            "id": meetings["meeting_id"].tolist(),
            "date": meetings["date"].tolist(),
            "time": meetings["time"].tolist(),
            "body": body[len(items):],
            "place": meetings["location"].tolist(),
            "url": meetings["url"].tolist(),
            "agenda_url": meetings["agenda_url"].tolist(),
            "minutes_url": meetings["minutes_url"].tolist(),
            "items": [int(n) for n in meetings["items"]],
        },
        "agenda": {
            "meeting": [int(n) for n in agenda["meeting"]],
            "item": [at.get(matter, -1) for matter in agenda["matter_id"]],
            "number": agenda["agenda_number"].tolist(),
            "action": action[len(items):],
            "result": [RESULT_LETTERS.get(value, "") for value in agenda["result"]],
            "ayes": [int(n) for n in agenda["ayes"]],
            "noes": [int(n) for n in agenda["noes"]],
            "votes": [cast.get(item_id, "") for item_id in agenda["item_id"]],
        },
    }


def read_tables(body, folder=None):
    """A body's tables as last written here, or as published. Its table of members is given the one name, "members"."""
    files = {**{name: name for name in TABLES}, "members": body["members"]}
    if folder:
        return {name: pd.read_parquet(Path(folder) / f"{file}.parquet") for name, file in files.items()}
    from huggingface_hub import hf_hub_download
    return {name: pd.read_parquet(hf_hub_download(body["repo"], f"data/{file}.parquet", repo_type="dataset", token=bills.HF_TOKEN))
            for name, file in files.items()}


def write(snapshot, out_dir):
    path = Path(out_dir) / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, separators=(",", ":"))
    return path


def upload(path, repo):
    problem = bills.hf_write_problem(repo)
    if problem:
        log.error(f"Chamber file not uploaded: {problem}")
        return False
    from huggingface_hub import HfApi
    HfApi(token=bills.HF_TOKEN).upload_file(path_or_fileobj=str(path), path_in_repo=FILE, repo_id=repo, repo_type="dataset",
                                            commit_message="Update the file Capitol World reads")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Write the file Capitol World reads for a local body")
    parser.add_argument("--body", choices=sorted(BODIES), default="sd-county", help="whose file to write")
    parser.add_argument("--tables", help="directory holding the tables (default: read them as published)")
    parser.add_argument("--out", help="directory to write world/chamber.json.gz under (default: the body's own)")
    parser.add_argument("--no-upload", action="store_true", help="write the file but do not publish it")
    args = parser.parse_args(argv)
    body = BODIES[args.body]
    try:
        snapshot = build(read_tables(body, args.tables), surnames=body["surnames"])
    except Exception as e:
        log.error(f"Chamber file not built: {type(e).__name__}: {e}")
        return 1
    path = write(snapshot, args.out or bills.SCRIPT_DIR / body["folder"])
    pushed = False if args.no_upload else upload(path, body["repo"])
    log.info(f"RESULT: chamber-file body={args.body} members={len(snapshot['members'])} items={len(snapshot['items']['id'])} "
             f"meetings={len(snapshot['meetings']['id'])} agenda={len(snapshot['agenda']['item'])} "
             f"through={snapshot['data_through']} kilobytes={path.stat().st_size // 1024} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(main())
