#!/usr/bin/env python3
"""
Build, for a city whose council keeps its record in Legistar, what a room in
Capitol World is made from: its meetings, what was on each agenda, what the
council did with it, and how each member voted.

One source: the city's legislative system, through the public API at
webapi.legistar.com/v1/<city>. It is the same system San Diego County uses, and
this reads it with build_sd_county's own functions pointed at another city.
What differs from one city to the next is set out in CITIES.

Each city has a dataset of its own, chrissoria/<city>-council, with the five
tables every council's and board's dataset has (council_tables.py), in data/:
  items.parquet          every item filed, of any kind
  meetings.parquet       one row per meeting of the council and its committees
  agenda_items.parquet   one row per item on a meeting's agenda, with what was done
  votes.parquet          one row per member and item acted on
  members.parquet        one row per member's time on the council
They are kept here in legistar/<city>/.

Two ways to run it:

    python build_legistar_council.py --city oakland
        The routine run. Starts from the published tables, lists every item
        and meeting again, and reads again the agendas and votes of meetings
        in the last 60 days and those to come. A minute or two.

    python build_legistar_council.py --city oakland --base
        Every meeting not yet read. Hours for a city with twenty years of
        meetings; what has been read is written every --every meetings, so it
        can be stopped and started again.

    --since YYYY-MM-DD  with --base, only meetings on or after this day
    --out DIR           where to write the tables
    --no-upload         write the tables but do not publish them
    --write-card        publish the dataset card as well as the tables

The text of ordinances and resolutions is in each city's ordinances dataset
(build_legistar_dataset.py) and is not read here.
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

import build_federal_bills as bills
import build_sd_county as county
import council_tables
from build_sd_county import clean, day_of

log = logging.getLogger(__name__)

OUT_DIR = bills.SCRIPT_DIR / "legistar"
CARD_FILE = bills.SCRIPT_DIR / "README_legistar_council.md"  # one card for every city, with the city's own facts written in
TABLES = council_tables.TABLES

# `client` is the city's name in the API's address; `council` is what the source calls the council when it sits. Oakland's
# sits under several names, as itself and as the agencies its members also are; a joint meeting with another body is not one.
CITIES = {
    "oakland": {"client": "oakland", "name": "Oakland", "council": [
        "Meeting of the Oakland City Council",
        "* Concurrent Meeting of the Oakland Redevelopment Successor Agency and the City Council",
        "Concurrent Meeting of the Oakland Redevelopment Agency / City Council",
        "Special Concurrent Meeting of the Oakland Redevelopment Successor Agency/City Council",
        "*Special Concurrent Meeting of the Oakland Redevelopment Agency/City Council",
    ]},
    "long-beach": {"client": "longbeach", "name": "Long Beach", "council": ["City Council"]},
    "fresno": {"client": "fresno", "name": "Fresno", "council": ["City Council"]},
    "salinas": {"client": "salinas", "name": "Salinas", "council": ["City Council"]},
}
# The source does not say which district a member sits for. These are typed in, by the name the source gives: those now
# serving from each city's own pages, the rest from Wikipedia and what is commonly recorded of each council. A member
# elected by the whole city (Oakland's at-large seat, a mayor who sits on the council) has no district and is not here.
# Long Beach's record names two members "Vice Mayor Lowenthal", of different districts, so that name has none either.
DISTRICTS = {
    "oakland": {
        "Jane Brunner": 1, "Dan Kalb": 1, "Zac Unger": 1,
        "Danny Wan": 2, "Wan, Danny": 2, "Patricia Kernighan": 2, "Abel J. Guillén": 2, "Nikki Fortunato Bas": 2, "Charlene Wang": 2,
        "Nancy Nadel": 3, "Lynette McElhaney": 3, "Carroll Fife": 3,
        "Dick Spees": 4, "Jean Quan": 4, "Libby Schaaf": 4, "Annie Campbell Washington": 4, "Sheng Thao": 4, "Janani Ramachandran": 4,
        "Ignacio De La Fuente": 5, "Noel Gallo": 5, "Noel Gallo --": 5,
        "Nate Miley": 6, "Moses Mayne": 6, "Desley Brooks": 6, "Loren Taylor": 6, "Kevin Jenkins": 6,
        "Laurence E. Reid": 7, "Larry Reid": 7, "Treva Reid": 7, "Ken Houston": 7,
    },
    "fresno": {
        "Blong Xiong": 1, "Esmeralda Z. Soria": 1, "Annalisa Perea": 1,
        "Steve Brandau": 2, "Mike Karbassi": 2,
        "Oliver L. Baines III": 3, "Miguel Angel Arias": 3,
        "Paul Caprioglio": 4, "Tyler Maxwell": 4,
        "Sal Quintero": 5, "Luis Chavez": 5, "Brandon Vang": 5,
        "Lee Brand": 6, "Garry Bredefeld": 6, "Nick Richardson": 6,
        "Clinton Olivier": 7, "Nelson Esparza": 7,
    },
    "salinas": {
        "Jose Castañeda": 1, "Scott Davis": 1, "Carla Viviana Gonzalez": 1, "Jose Barajas": 1,
        "Tony Barrera": 2,
        "Steve McShane": 3, "Jesus Valenzuela": 3, "Margaret D'Arrigo": 3,
        "Gloria De La Rosa": 4, "Orlando Osornio": 4,
        "Kimbley Craig": 5, "Christie Cromeenes": 5, "Jose Andrew Sandoval": 5,
        "Jyl Lutes": 6, "John Villegas": 6, "Anthony Rocha": 6, "Aurelio Salazar": 6,
    },
    "long-beach": {
        "Bonnie Lowenthal": 1, "Robert Garcia": 1, "Councilwoman Gonzalez": 1, "Councilwoman Zendejas": 1,
        "Dan Baker": 2, "Suja S. Lowenthal": 2, "Councilmember Pearce": 2, "Councilwoman Pearce": 2, "Councilwoman Allen": 2, "Vice Mayor Allen": 2,
        "Frank Colonna": 3, "Gary DeLong": 3, "Councilwoman Price": 3, "Councilmember Duggan": 3,
        "Dennis Carroll": 4, "Councilmember O'Donnell": 4, "Councilman Supernaw": 4,
        "Jackie Kell": 5, "Gerrie Schipske": 5, "Councilwoman Mungo": 5, "Councilwoman Kerr": 5,
        "Laura Richardson": 6, "Councilman Andrews": 6, "Dee Andrews": 6, "Councilwoman Saro": 6,
        "Tonia Reyes Uranga": 7, "James Johnson": 7, "Councilmember Uranga": 7,
        "Rob Webb": 8, "Rae Gabelich": 8, "Councilman Austin": 8,
        "Val Lerch": 9, "Steven Neal": 9, "Councilmember Richardson": 9, "Vice Mayor Richardson": 9, "Councilmember Ricks-Oddie": 9,
    },
}
GAP_DAYS = 31  # terms this close together are one time on the council: a member re-elected is sworn in a few days on

ITEM_COLUMNS = ["date", "matter_id", "matter_file", "doc_type", "title", "body", "status", "year", "subject", "agenda_date",
                "passed_date", "last_action", "last_action_date", "result", "ayes", "noes", "mover", "seconder",
                "times_on_agenda", "attachments", "url", "last_modified"]


def point_at(city):
    """Have the county's functions read this city's site instead."""
    county.API = f"https://webapi.legistar.com/v1/{city['client']}"
    county.ITEM_PAGE = f"https://{city['client']}.legistar.com/LegislationDetail.aspx?ID={{id}}&GUID={{guid}}"


def doc_type_of(kind, title):
    """What an item is. A city files an ordinance as one; where it does not say, the title does."""
    lowered = str(kind or "").lower()
    if "ordinance" in lowered or "resolution" in lowered:
        return "ordinance" if "ordinance" in lowered else "resolution"
    return county.doc_type_of(title)


def items_table(matters, agenda, papers, previous):
    """Every item filed, with the last thing done to it and the papers filed with it."""
    kept = dict(zip(previous["matter_id"].astype(str), previous["attachments"])) if previous is not None else {}
    acted = agenda[agenda["action"] != ""].sort_values(["date", "sequence"])
    last = acted.groupby("matter_id").tail(1).set_index("matter_id")
    times = agenda.groupby("matter_id").size()
    rows = []
    for matter in matters:
        matter_id, title = str(matter["MatterId"]), clean(matter.get("MatterTitle") or matter.get("MatterName"))
        date = day_of(matter.get("MatterIntroDate"))
        done = last.loc[matter_id] if matter_id in last.index else None
        listed = papers.get(matter_id)
        rows.append({
            "date": date,
            "matter_id": matter_id,
            "matter_file": matter.get("MatterFile") or "",
            "doc_type": doc_type_of(matter.get("MatterTypeName"), title),
            "title": title,
            "body": clean(matter.get("MatterBodyName")),
            "status": clean(matter.get("MatterStatusName")),
            "year": int(date[:4]) if date[:4].isdigit() else 0,
            "subject": clean(matter.get("MatterTypeName")),
            "agenda_date": day_of(matter.get("MatterAgendaDate")),
            "passed_date": day_of(matter.get("MatterPassedDate")),
            "last_action": done["action"] if done is not None else "",
            "last_action_date": done["date"] if done is not None else "",
            "result": done["result"] if done is not None else "",
            "ayes": int(done["ayes"]) if done is not None else 0,
            "noes": int(done["noes"]) if done is not None else 0,
            "mover": done["mover"] if done is not None else "",
            "seconder": done["seconder"] if done is not None else "",
            "times_on_agenda": int(times.get(matter_id, 0)),
            # Not on an agenda read this time: what was known of its papers stands.
            "attachments": json.dumps(listed, ensure_ascii=False, separators=(",", ":")) if listed is not None
                           else kept.get(matter_id) or "[]",
            "url": county.ITEM_PAGE.format(id=matter_id, guid=matter.get("MatterGuid") or ""),
            "last_modified": str(matter.get("MatterLastModifiedUtc") or "")[:19],
        })
    out = pd.DataFrame(rows, columns=ITEM_COLUMNS)
    return out.sort_values(["date", "matter_id"], ascending=[False, False]).reset_index(drop=True)


def terms_of(seats):
    """One row for each unbroken time a person sat: terms on record that overlap, or follow within a month, are one.

    The source keeps a term for each office held and each name the council sits under, so one time on the council is
    many records. The role is that of the record that starts last; a record with no end leaves the time open.
    """
    rows = []
    for seat in sorted(seats, key=lambda seat: (seat["name"], seat["start"])):
        last = rows[-1] if rows else None
        close = last and last["name"] == seat["name"] and (
            not last["end"] or seat["start"] <= (pd.Timestamp(last["end"]) + pd.Timedelta(days=GAP_DAYS)).strftime("%Y-%m-%d"))
        if close:
            last["end"] = "" if not last["end"] or not seat["end"] else max(last["end"], seat["end"])
            last["role"] = seat["role"] or last["role"]
        else:
            rows.append(dict(seat))
    return rows


def members_table(records, votes, meetings, bodies, districts=None):
    """Each time someone sat on the council, as the source's terms show it, with the district typed in for them.

    Someone who votes at the council's own meetings and has no term on record is a member too, with no dates. A mayor
    sits for the whole city, whatever district they sat for before.
    """
    districts = districts or {}
    rows = terms_of([{
        "name": clean(seat["OfficeRecordFullName"]),
        "district": None,
        "role": clean(seat.get("OfficeRecordTitle")) or clean(seat.get("OfficeRecordMemberType")),
        "start": day_of(seat.get("OfficeRecordStartDate")),
        "end": day_of(seat.get("OfficeRecordEndDate")),
    } for seat in records if clean(seat.get("OfficeRecordBodyName")) in bodies and seat.get("OfficeRecordStartDate")])
    for row in rows:
        row["serving"] = row["start"] <= county.today() <= (row["end"] or "9999")
        row["district"] = None if row["role"] == "Mayor" else districts.get(row["name"])
    sat = set(meetings.loc[meetings["body"].isin(bodies), "meeting_id"])
    known = {row["name"] for row in rows}
    rows += [{"name": name, "district": districts.get(name), "role": "", "start": "", "end": "", "serving": False}
             for name in sorted(set(votes.loc[votes["meeting_id"].isin(sat), "member"]) - known) if name]
    out = pd.DataFrame(rows, columns=council_tables.COLUMNS["members"][:6])
    out["district"] = out["district"].astype("Int64")
    cast = votes.groupby("member")["date"].agg(["min", "max", "size"])
    out["first_vote"] = out["name"].map(cast["min"]).fillna("")
    out["last_vote"] = out["name"].map(cast["max"]).fillna("")
    out["votes"] = out["name"].map(cast["size"]).fillna(0).astype(int)
    return out.sort_values(["start", "name"]).reset_index(drop=True)


def repo_of(key):
    return f"chrissoria/{key}-council"


def published(key, name):
    """A table as last published, or None."""
    try:
        from huggingface_hub import hf_hub_download
        return pd.read_parquet(hf_hub_download(repo_of(key), f"data/{name}.parquet", repo_type="dataset", token=bills.HF_TOKEN))
    except Exception:
        return None


def held(key, out_dir, name, base):
    """The table a run starts from: what is published, or failing that what was last written here.

    A whole run looks here first: it is run by hand and stopped and started, so what it has written is further on than
    what is published. The routine run looks at what is published first: it may be run where nothing was written before.
    """
    path = Path(out_dir) / f"{name}.parquet"
    local = lambda: pd.read_parquet(path) if path.exists() else None
    first, second = (local, lambda: published(key, name)) if base else (lambda: published(key, name), local)
    found = first()
    return found if found is not None else second()


def write_tables(tables, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        table.to_parquet(out_dir / f"{name}.parquet", index=False)


def build(key, base, since, out_dir, every=200):
    city = CITIES[key]
    point_at(city)
    events = county.paged("events", orderby="EventId")
    matters = county.paged("matters", orderby="MatterId")
    log.info(f"{city['name']}: {len(matters)} items and {len(events)} meetings listed")
    if len(matters) < 100:
        raise RuntimeError("the listing of items came back nearly empty")
    meetings = county.meetings_table(events)

    agenda, votes, items = (held(key, out_dir, name, base) for name in ("agenda_items", "votes", "items"))
    before = 0 if votes is None else len(votes)
    known = set(agenda["meeting_id"]) if agenda is not None else set()
    recent = (datetime.now(timezone.utc) - timedelta(days=county.RECENT_DAYS)).strftime("%Y-%m-%d")
    wanted = [event for event in events
              if base and str(event["EventId"]) not in known and day_of(event["EventDate"]) >= (since or "")
              or day_of(event["EventDate"]) >= recent]
    wanted.sort(key=lambda event: event["EventDate"], reverse=True)  # the newest first: a room shows those
    if agenda is None:
        agenda, votes = pd.DataFrame(columns=county.AGENDA_COLUMNS), pd.DataFrame(columns=county.VOTE_COLUMNS)
    log.info(f"Reading the agendas of {len(wanted)} meetings")

    tables, read = {}, 0
    for start in range(0, max(len(wanted), 1), every):
        some = wanted[start:start + every]
        new_agenda, new_votes, papers, done = [], [], {}, set()
        for event, found in zip(some, county.together(county.read_meeting, some, "meeting")):
            if found is None:
                continue  # what is held for it stands, and the next run asks again
            done.add(str(event["EventId"]))
            new_agenda.extend(found[0])
            new_votes.extend(found[1])
            papers.update(found[2])
        new_agenda = pd.DataFrame(new_agenda, columns=county.AGENDA_COLUMNS)
        new_votes = pd.DataFrame(new_votes, columns=county.VOTE_COLUMNS)
        agenda = pd.concat([agenda[~agenda["meeting_id"].isin(done)], new_agenda], ignore_index=True)
        votes = pd.concat([votes[~votes["meeting_id"].isin(done)], new_votes], ignore_index=True)
        agenda = agenda.sort_values(["date", "meeting_id", "sequence"]).reset_index(drop=True)
        votes = votes.sort_values(["date", "meeting_id", "item_id", "member"]).reset_index(drop=True)
        meetings["items"] = meetings["meeting_id"].map(agenda.groupby("meeting_id").size()).fillna(0).astype(int)
        items = items_table(matters, agenda, papers, items)
        tables = {"items": items, "meetings": meetings, "agenda_items": agenda, "votes": votes}
        write_tables(tables, out_dir)
        read += len(done)
        log.info(f"{city['name']}: {min(start + every, len(wanted))} of {len(wanted)} meetings asked for, {len(votes)} votes held")
    tables["members"] = members_table(county.paged("officerecords", orderby="OfficeRecordId"), votes, meetings,
                                      {clean(body) for body in city["council"]}, DISTRICTS.get(key))
    tables = council_tables.standard(tables)
    write_tables(tables, out_dir)
    if len(votes) < before * 0.98:
        raise RuntimeError(f"only {len(votes)} votes where there were {before}; not publishing")
    return tables, read


def card(key, tables):
    """The dataset card: the one every city has, with this city's name, addresses and counts written in."""
    city, meetings, votes = CITIES[key], tables["meetings"], tables["votes"]
    read = meetings[meetings["items"] > 0]
    facts = {
        "name": city["name"], "slug": key, "client": city["client"],
        "council": " or ".join(f'"{clean(body)}"' for body in city["council"]),
        "first_meeting": read["date"].min() if len(read) else "", "last_meeting": read["date"].max() if len(read) else "",
        "first_vote": votes["date"].min() if len(votes) else "", "last_vote": votes["date"].max() if len(votes) else "",
        "bodies": f"{meetings['body'].nunique():,}",
        **{f"n_{name}": f"{len(tables[name]):,}" for name in TABLES},
    }
    text = CARD_FILE.read_text(encoding="utf-8")
    for fact, value in facts.items():
        text = text.replace("{" + fact + "}", str(value))
    return text


def upload(key, tables, out_dir, with_card):
    from huggingface_hub import CommitOperationAdd, HfApi
    repo, hub = repo_of(key), HfApi(token=bills.HF_TOKEN)
    hub.create_repo(repo, repo_type="dataset", exist_ok=True)
    problem = bills.hf_write_problem(repo)
    if problem:
        log.error(f"{CITIES[key]['name']} council tables not uploaded: {problem}")
        return False
    operations = [CommitOperationAdd(path_in_repo=f"data/{name}.parquet", path_or_fileobj=str(out_dir / f"{name}.parquet"))
                  for name in TABLES]
    if (with_card or "README.md" not in set(hub.list_repo_files(repo, repo_type="dataset"))) and CARD_FILE.exists():
        operations.append(CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=card(key, tables).encode("utf-8")))
    hub.create_commit(repo_id=repo, repo_type="dataset", operations=operations,
                      commit_message=f"Update {CITIES[key]['name']} council tables ({county.today()})")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a Legistar city's meetings, agendas and votes")
    parser.add_argument("--city", required=True, choices=sorted(CITIES))
    parser.add_argument("--base", action="store_true", help="read every meeting not yet read, not only the recent ones")
    parser.add_argument("--since", default="", help="with --base, only meetings on or after this day")
    parser.add_argument("--every", type=int, default=200, help="meetings to read between one writing of the tables and the next")
    parser.add_argument("--out", default="", help="directory to write the tables into (legistar/<city> if not given)")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the tables only")

    out_dir = Path(args.out) if args.out else OUT_DIR / args.city
    try:
        tables, read = build(args.city, args.base, args.since, out_dir, args.every)
    except Exception as e:
        log.error(f"{args.city} tables not built: {type(e).__name__}: {e}")
        return 1
    pushed = False if args.no_upload else upload(args.city, tables, out_dir, args.write_card)
    agenda, votes, council = tables["agenda_items"], tables["votes"], tables["members"]
    voters = set(votes["member"])
    log.info(f"RESULT: legistar-{args.city} items={len(tables['items'])} meetings={len(tables['meetings'])} "
             f"meetings_with_agenda={agenda['meeting_id'].nunique()} agenda_items={len(agenda)} votes={len(votes)} "
             f"items_voted_on={votes['item_id'].nunique()} members={council['name'].nunique()} "
             f"serving={int(council['serving'].sum())} voters_not_on_council={len(voters - set(council['name']))} "
             f"meetings_read={read} first_vote={votes['date'].min() if len(votes) else ''} "
             f"last_vote={votes['date'].max() if len(votes) else ''} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
