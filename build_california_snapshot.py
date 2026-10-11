#!/usr/bin/env python3
"""
Build the map files for California's Capitol World from the california-bills tables.

They have the shapes build_world_snapshot.py gives Congress's, so the app reads
a state legislature with the code it reads Congress with. The Assembly fills
the place the House has there: `chamber` is "House" for the Assembly and
"Senate" for the Senate, and the app shows each house under its own name.

Written beside the dataset, in world/ for the session in progress and in
world/archive/<year>/ for a finished one:

    world.json.gz         legislators, committees, the measures on the map and
                          where each one is, and the moves of the last week
    search.json.gz        every measure of the session, as column arrays
    committees.json.gz    who sits on each committee
    text/<n>.json.gz      the Legislative Counsel's digests at greater length
    world/sessions.json   which sessions can be opened

A measure's place is read from its history, where the Legislature records the
house and the place each action left it in. Nothing is guessed from wording.

build_california_bills.py calls main() after a successful push. A failure here
never affects the dataset.

Usage:
    python build_california_snapshot.py                  # the session in progress
    python build_california_snapshot.py --session 2023   # a finished session
    python build_california_snapshot.py --no-upload      # write the files only
"""

import argparse
import gzip
import json
import logging
import re
import sys
from pathlib import Path

import pandas as pd

import build_california_bills as ca
import build_federal_bills as bills
from build_world_snapshot import ACTION_CHARS, EVENT_DAYS, FATES, SCHEMA, SILENT_DAYS, STAGES, SUMMARY_CHARS, TEXT_CHARS, \
    TEXT_FILES, TITLE_CHARS, WORLD_DAYS, WORLD_TITLE_CHARS, clipped, location_key

log = logging.getLogger("california_snapshot")

OUT_DIR = bills.SCRIPT_DIR / "california" / "world"
FIRST_WITH_PLACES = 2007  # earlier sessions' histories do not say where an action left the measure
SLOT = {"Assembly": "House", "Senate": "Senate"}  # the app's two wings
OTHER = {"House": "Senate", "Senate": "House"}
PARTY = {"Democratic": "D", "Republican": "R", "Independent": "I"}
BILL_TYPES = ("AB", "SB")  # what becomes law; the rest are resolutions and constitutional amendments
ONE_HOUSE = ("HR", "SR")  # resolutions of a single house
COLUMNS = ["bill_id", "session", "bill_number", "measure_type", "measure_number", "special_session", "title", "date",
           "origin_chamber", "sponsor_name", "sponsor_ids", "sponsor_party", "coauthor_count", "status", "last_action_date",
           "last_action", "digest", "url", "chapter"]


def measure_id(year, kind, number, special=0):
    """'2025-ab-679'; a bill of an extraordinary session is '2025-abx1-3'."""
    return f"{year}-{kind.lower()}{f'x{special}' if int(special or 0) else ''}-{number}"


def finished(year, today=None):
    """Whether a session's record is settled: from the October after the Governor's last day to sign or veto."""
    today = today or pd.Timestamp.now(tz="America/Los_Angeles").strftime("%Y-%m-%d")
    return today >= f"{year + 1}-10-01"


def place_after(action, kind):
    """Where an action leaves a measure, as a map location, or None if it does not move it.

    `action` has the history's own columns: house, location, location_detail,
    committee_code and status_after. `kind` is the measure's type.
    """
    house, where, detail, after = action["house"], action["location"], action["location_detail"], action["status_after"]

    def loc(place, chamber="", committee=""):
        return {"kind": place, "chamber": chamber, "committee": committee}

    done = "law" if kind in BILL_TYPES else "adopted"
    if after == "Vetoed":
        return loc("vetoed")
    if house == "Secretary of State":
        return loc(done)
    if house == "Governor":
        return loc("president")
    slot = SLOT.get(house)
    if not slot or after in ("Died", "Failed", "Failed Passage in Committee"):
        return None  # it stays where it was; its fate says the rest
    if where == "Committee":
        return loc("committee", slot, action["committee_code"]) if action["committee_code"] else loc("referral_desk", slot)
    if where == "Rules":
        return loc("referral_desk", slot)
    if where == "Floor":
        return loc("floor" if detail in ("Third Reading", "Unfinished Business") else "calendar", slot)
    if where == "E&E":
        if detail == "Enrollment":
            return loc("conference")  # passed by both houses and being enrolled for the Governor
        return loc("other_chamber", OTHER[slot]) if after == "Passed" and kind not in ONE_HOUSE else None
    if where == "Desk":
        if after == "Passed":
            return loc("adopted") if kind in ONE_HOUSE else loc("other_chamber", OTHER[slot])
        if after == "In Floor Process":
            return loc("other_chamber", slot)  # back in its own house, the other's amendments waiting
        if after in ("Pending Referral", "In Desk Process"):
            return loc("referral_desk", slot)
    return None


def walk(history, kind, origin):
    """A measure's journey: each change of place, the houses that passed it, and whether it left committee."""
    moves, passed, left_committee, here = [], set(), False, None
    for action in history:
        if action["status_after"] == "Passed" and action["house"] in SLOT and action["action_status"] != "Rescinded":
            passed.add(action["house"])
        found = place_after(action, kind)
        if not found:
            continue
        key = location_key(found)
        if key != here:
            moves.append((action, found))
            here = key
        if found["kind"] in ("calendar", "floor"):
            left_committee = True
    final = moves[-1][1] if moves else {"kind": "referral_desk", "chamber": SLOT.get(origin, "House"), "committee": ""}
    return moves, final, passed, left_committee


def stage_of(kind, place, status, passed, left_committee):
    """Index into STAGES: how far a measure got."""
    if place == "law":
        return 5
    if place in ("president", "vetoed", "conference") or len(passed) >= 2 or (place == "adopted" and kind not in ONE_HOUSE):
        return 4
    if passed or place in ("other_chamber", "adopted"):
        return 3
    if status == "Failed":
        return 2
    return 1 if left_committee or place in ("calendar", "floor") else 0


def fate_of(kind, place, status, stage, passed, last_date, final, silent_before):
    """One key of FATES, or "." for a measure that is not dead."""
    if place == "vetoed" or status == "Vetoed":
        return "v"
    if place in ("law", "adopted"):
        return "."
    if status == "Failed":
        return "f"
    if final or status in ("Died", "Failed Passage in Committee"):
        if stage == 4:
            return "b"
        if passed:
            return "o"
        return "w" if place in ("calendar", "floor") else "c"
    return "s" if last_date and last_date < silent_before else "."


def area_of(history):
    """The first committee a measure was sent to for its subject. California gives measures no policy area; this stands in."""
    first = ""
    for action in history:
        name = action["committee"]
        if not name:
            continue
        if name != "Rules" and "Appropriations" not in name:
            return name
        first = first or name
    return first if first != "Rules" else ""


def committee_seats(votes, member_votes, known):
    """Who sits on each committee: everyone listed on its most recent roll call, which names every member."""
    in_committee = votes[votes["location_code"].str.match(r"^C[SX]\d+$")]
    if in_committee.empty:
        return {}
    newest = in_committee.sort_values("date").groupby("location_code").tail(1)
    seats = {}
    cast = member_votes[member_votes["vote_id"].isin(set(newest["vote_id"]))]
    by_vote = {vote_id: group for vote_id, group in cast.groupby("vote_id")}
    for code, vote_id in zip(newest["location_code"], newest["vote_id"]):
        listed = by_vote.get(vote_id)
        if listed is not None:
            seats[code] = [key for key in dict.fromkeys(listed["legislator_id"]) if key in known]
    return seats


def read_tables(session, tables_dir=None):
    """The tables of one session, from a directory of them or from the published dataset."""
    out = {}
    for name in ("bills", "actions", "votes", "member_votes", "legislators", "committees"):
        local = Path(tables_dir) / name / f"{session}.parquet" if tables_dir else None
        if local is None or not local.exists():
            from huggingface_hub import hf_hub_download
            local = hf_hub_download(ca.HF_REPO, f"data/{name}/{session}.parquet", repo_type="dataset", token=bills.HF_TOKEN)
        out[name] = pd.read_parquet(local, columns=COLUMNS if name == "bills" else None)
    return out


def build(tables, final, world_days=WORLD_DAYS):
    """The map file, the search index, the committee file and the long digests for one session."""
    measures = tables["bills"].fillna("")
    session = measures["session"].iloc[0]
    year = int(session[:4])
    has_places = year >= FIRST_WITH_PLACES
    world_days = None if final else world_days

    people = tables["legislators"]
    party = {key: PARTY.get(name, "I") for key, name in zip(people["legislator_id"], people["party"])}
    members = [{
        "id": row.legislator_id,
        "name": row.name,
        "party": party[row.legislator_id],
        # The seat stands where a member of Congress has a state: "AD 28" is the 28th Assembly District.
        "state": f"{'AD' if row.chamber == 'Assembly' else 'SD'} {int(row.district)}",
        "district": None,
        "chamber": SLOT.get(row.chamber, ""),
        "role": "" if row.serving else "Left the seat during the session",
    } for row in people.itertuples(index=False)]
    known = {member["id"] for member in members}

    histories = {bill_id: group.to_dict("records") for bill_id, group in tables["actions"].groupby("bill_id", sort=False)}
    data_through = measures["last_action_date"].max()
    day = pd.Timestamp(data_through)
    world_since = "" if world_days is None else (day - pd.Timedelta(days=world_days)).strftime("%Y-%m-%d")
    event_since = (day - pd.Timedelta(days=EVENT_DAYS)).strftime("%Y-%m-%d")
    silent_before = (day - pd.Timedelta(days=SILENT_DAYS)).strftime("%Y-%m-%d")

    world_bills, events, used, texts, rows = [], [], {}, {}, []
    for row in measures.sort_values(["last_action_date", "measure_type", "measure_number"], ascending=[False, True, True]) \
            .to_dict("records"):
        kind = row["measure_type"]
        history = histories.get(row["bill_id"], [])
        moves, loc, passed, left_committee = walk(history, kind, row["origin_chamber"])
        if not has_places:
            # An older session says only how each measure ended. It is laid where that puts it.
            ended = {"Chaptered": "law" if kind in BILL_TYPES else "adopted", "Vetoed": "vetoed", "Passed": "adopted"}
            loc = {"kind": ended.get(row["status"], "referral_desk"),
                   "chamber": "" if row["status"] in ended else SLOT.get(row["origin_chamber"], "House"), "committee": ""}
        stage = stage_of(kind, loc["kind"], row["status"], passed, left_committee)
        fate = fate_of(kind, loc["kind"], row["status"], stage, passed, row["last_action_date"], final, silent_before)
        sponsors = [key for key in row["sponsor_ids"].split("; ") if key in known]
        sponsor = sponsors[0] if sponsors else ""
        area = area_of(history)
        key = measure_id(year, kind, row["measure_number"], row["special_session"])
        rows.append({"id": key, "title": row["title"], "sponsor": sponsor, "status": row["status"], "area": area,
                     "date": row["last_action_date"], "introduced": row["date"], "stage": stage, "fate": fate,
                     "party": party.get(sponsor, "?")})
        if row["last_action_date"] < world_since:
            continue
        if loc["committee"]:
            used[loc["committee"]] = used.get(loc["committee"], 0) + 1
        digest = row["digest"].replace("\n", " ").strip()
        if len(digest) > SUMMARY_CHARS:
            texts.setdefault(int(row["measure_number"]) % TEXT_FILES, {})[key] = clipped(row["digest"].strip(), TEXT_CHARS)
        world_bills.append({
            "id": key,
            "type": kind if not int(row["special_session"]) else f"{kind}X{row['special_session']}",
            "number": str(row["measure_number"]),
            "title": clipped(row["title"], WORLD_TITLE_CHARS),
            "sponsor": sponsor,
            **({} if sponsor else {"author": row["sponsor_name"]}),
            "cosponsors": int(row["coauthor_count"]) + max(len(sponsors) - 1, 0),
            "policy_area": area,
            "status": row["status"],
            "loc": loc,
            "last_action": {"date": row["last_action_date"], "text": row["last_action"][:ACTION_CHARS]},
            "introduced": row["date"],
            "summary": clipped(digest, SUMMARY_CHARS),
            "url": row["url"],
            **({"fate": fate} if fate != "." else {}),
        })
        previous = None
        for action, found in moves:
            here = location_key(found)
            if action["date"] >= event_since:
                events.append({"bill": key, "date": action["date"], "from": previous, "to": here,
                               "text": action["action"][:140], "actor": sponsor or None if previous is None else None,
                               "actor_role": "author" if previous is None and sponsor else None})
            previous = here
    events.sort(key=lambda event: event["date"])
    for seq, event in enumerate(events):
        event["seq"] = seq

    index = pd.DataFrame(rows)
    in_world = pd.Series([bill["sponsor"] for bill in world_bills]).value_counts().to_dict()
    in_total = index["sponsor"].value_counts().to_dict()
    for member in members:
        member["n_world"] = int(in_world.get(member["id"], 0))
        member["n_total"] = int(in_total.get(member["id"], 0))

    rooms = tables["committees"]
    rooms = rooms[rooms["kind"] == "committee"]
    committees = [{"code": code, "name": name, "chamber": SLOT.get(chamber, ""), "n_bills": used.get(code, 0)}
                  for code, name, chamber, active in zip(rooms["committee_code"], rooms["name"], rooms["chamber"], rooms["active"])
                  if active or used.get(code)]

    fates = "".join(index["fate"])
    world = {
        "schema": SCHEMA,
        "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_through": data_through,
        "congress": year,
        "years": [year, year + 1],
        "window": {"world_since": world_since, "events_since": event_since},
        "counts": {
            "total": int(len(measures)),
            "world": len(world_bills),
            "events": len(events),
            "guessed_locations": 0 if has_places else len(world_bills),
            "by_status": {k: int(v) for k, v in measures["status"].value_counts().items() if k},
            "by_kind": pd.Series([bill["loc"]["kind"] for bill in world_bills]).value_counts().to_dict(),
            "dead": {code: fates.count(code) for code in FATES if code in fates},
            "pending": 0,
        },
        "roles": {"chairs": {}, "leaders": {}},
        "members": members,
        "committees": committees,
        "bills": world_bills,
        "events": events,
        "summary_source": "digest",
        **({"final": True} if final else {}),
    }

    names = {member["id"]: f"{member['name']} ({member['party']}-{member['state']})" for member in members}
    sponsors = sorted(set(index["sponsor"]) & known)
    sponsor_index = {key: i for i, key in enumerate(sponsors)}
    statuses = sorted(s for s in index["status"].unique() if s)
    areas = sorted(a for a in index["area"].unique() if a)
    search = {
        "schema": SCHEMA,
        "data_through": data_through,
        "pending": 0,
        "sponsors": sponsors,
        "sponsor_names": [names[key] for key in sponsors],
        "fates": FATES,
        "statuses": statuses,
        "policy_areas": areas,
        "stages": list(STAGES),
        "id": index["id"].tolist(),
        "title": [title[:TITLE_CHARS] for title in index["title"]],
        "sponsor": [sponsor_index.get(key, -1) for key in index["sponsor"]],
        "status": [statuses.index(s) if s in statuses else -1 for s in index["status"]],
        "policy_area": [areas.index(a) if a in areas else -1 for a in index["area"]],
        "date": index["date"].tolist(),
        "introduced": index["introduced"].tolist(),
        "party": "".join(index["party"]),
        "stage": "".join(str(stage) for stage in index["stage"]),
        "fate": fates,
    }

    seats = committee_seats(tables["votes"], tables["member_votes"], known)
    majority = pd.Series([member["party"] for member in members]).mode()[0]
    committee_file = {
        "schema": SCHEMA,
        "generated_at": world["generated_at"],
        "committees": {
            room["code"]: {
                "name": room["name"],
                "chamber": room["chamber"],
                "members": [{"id": key, "side": "majority" if party[key] == majority else "minority", "rank": rank, "title": ""}
                            for rank, key in enumerate(seats.get(room["code"], []), 1)],
                "subcommittees": {},
                "n_meetings": 0,
                "meetings": [],
            } for room in committees
        },
    }
    return world, search, committee_file, texts


def write(out, world, search, committee_file, texts):
    out.mkdir(parents=True, exist_ok=True)
    files = []

    def put(name, value):
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
        files.append(path)

    put("world.json.gz", world)
    put("search.json.gz", search)
    put("committees.json.gz", committee_file)
    for number in range(TEXT_FILES):
        put(f"text/{number}.json.gz", texts.get(number, {}))
    return files


def session_entry(world):
    counts = world["counts"]
    return {"congress": world["congress"], "years": world["years"], "bills": counts["total"],
            "laws": int(counts["by_status"].get("Chaptered", 0)), "data_through": world["data_through"],
            "final": bool(world.get("final"))}


def read_sessions(api):
    try:
        from huggingface_hub import hf_hub_download
        return json.loads(Path(hf_hub_download(ca.HF_REPO, "world/sessions.json", repo_type="dataset",
                                               token=bills.HF_TOKEN, force_download=True)).read_text())
    except Exception:
        return {"current": None, "archive": []}


def upload(files, out, folder, entry, current):
    from huggingface_hub import CommitOperationAdd, HfApi
    api = HfApi(token=bills.HF_TOKEN)
    sessions = read_sessions(api)
    before = sessions.get("current")
    if current:
        sessions["current"] = entry
        sessions["archive"] = [item for item in sessions["archive"] if item["congress"] != entry["congress"]]
    else:
        sessions["archive"] = sorted([item for item in sessions["archive"] if item["congress"] != entry["congress"]] + [entry],
                                     key=lambda item: -item["congress"])
    operations = [CommitOperationAdd(path_in_repo=f"{folder}/{path.relative_to(out).as_posix()}", path_or_fileobj=str(path))
                  for path in files]
    operations.append(CommitOperationAdd(path_in_repo="world/sessions.json",
                                         path_or_fileobj=json.dumps(sessions, separators=(",", ":")).encode()))
    api.create_commit(repo_id=ca.HF_REPO, repo_type="dataset", operations=operations,
                      commit_message=f"Update {folder} ({entry['data_through']})")
    log.info(f"Uploaded {len(operations)} map files to {ca.HF_REPO}/{folder}")
    return before


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the California map files")
    parser.add_argument("--session", type=int, help="the odd year a finished session began; the session in progress if absent")
    parser.add_argument("--tables", help="directory holding the dataset's tables (default: the published ones)")
    parser.add_argument("--out", default=str(OUT_DIR), help="directory to write into")
    parser.add_argument("--no-upload", action="store_true", help="write the files but do not upload them")
    args = parser.parse_args(argv)

    current = args.session is None
    if current:
        sessions = sorted(path.stem for path in (Path(args.tables) / "bills").glob("*.parquet")) if args.tables else []
        if not sessions:
            from huggingface_hub import HfApi
            listed = HfApi(token=bills.HF_TOKEN).list_repo_files(ca.HF_REPO, repo_type="dataset")
            sessions = sorted(Path(name).stem for name in listed if re.match(r"data/bills/\d{4}-\d{4}\.parquet$", name))
        session = sessions[-1]
    else:
        session = f"{args.session}-{args.session + 1}"
    year = int(session[:4])
    world, search, committee_file, texts = build(read_tables(session, args.tables), final=not current or finished(year))
    out = Path(args.out) if current else Path(args.out) / "archive" / str(year)
    files = write(out, world, search, committee_file, texts)
    counts = world["counts"]
    size = sum(path.stat().st_size for path in files) // 1024
    pushed = False
    if not args.no_upload:
        if not bills.HF_TOKEN:
            log.error("No Hugging Face token; map files written locally but not uploaded")
            return 1
        before = upload(files, out, "world" if current else f"world/archive/{year}", session_entry(world), current)
        pushed = True
        if current and before and before["congress"] < year:
            # A new session has opened. The one that was in progress takes its place among the finished ones.
            main(["--session", str(before["congress"]), "--out", args.out])
    log.info(f"RESULT: california-map session={session} final={bool(world.get('final'))} on_map={counts['world']} "
             f"of={counts['total']} events={counts['events']} members={len(world['members'])} "
             f"committees={len(world['committees'])} kilobytes={size} pushed={pushed}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(main())
