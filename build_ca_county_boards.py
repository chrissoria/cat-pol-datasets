#!/usr/bin/env python3
"""
Build chrissoria/ca-county-boards: the boards of supervisors of California's
counties in one dataset, one shape, to be filtered by county.

Each county's record is read by the reader for the system that county keeps it
in (build_legistar_council.py, build_civicclerk_board.py, build_iqm2_board.py,
build_primegov_board.py, build_destiny_board.py, and the readers of PDF
minutes), which writes that county's five tables in a folder here. This script
reads nothing from a county: it takes those folders and writes

    data/<table>/<county>.parquet   the five tables, one file a county, every
                                    file of a table with the same columns:
                                    `county` and `county_fips`, the columns
                                    every council and board has
                                    (council_tables.py), and those most readers
                                    add (ADDED)
    data/counties.parquet           one row a county: its system, how its votes
                                    were read, how far its record goes, and
                                    what to know before setting it beside
                                    another
    raw/<county>/<table>.parquet    each reader's own tables as it wrote them,
                                    with the columns only it has. A reader
                                    picks up from these on its next run.

A county has a file of its own within a table so that reading one county again
rewrites that county's files and no other's.

    python build_ca_county_boards.py --no-upload            # every county, written here
    python build_ca_county_boards.py --county fresno        # one county's files, and the counties table
    python build_ca_county_boards.py --write-card           # publish the card too
    python build_ca_county_boards.py --read --minutes 30    # the daily run's part: see read_some

A reader publishes its county here itself when it is run without --no-upload
(council_tables.publish sends it on to publish_county), so reading a county
again is one command: `python build_legistar_council.py --city fresno-county`.
"""

import argparse
import importlib
import logging
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import bodies
import build_federal_bills as bills
import council_tables

log = logging.getLogger(__name__)

REPO = "chrissoria/ca-county-boards"
OUT_DIR = bills.SCRIPT_DIR / "ca_county_boards"
CARD_FILE = bills.SCRIPT_DIR / "README_ca_county_boards.md"
TABLES = council_tables.TABLES
ROOM = "https://christophersoria.com/capitol-world/?world=chamber&place={fips}"

# How a vote came to be in the table.
SYSTEM = "system"              # the clerk entered each member's vote in the county's meeting system
PAGE = "minutes page"          # read from the words of minutes the county publishes as a web page
TEXT = "minutes text"          # read from the text of a PDF of the minutes
CODE = "margin code"           # read from a row of digits in the margin of the minutes, by the key the minutes print

# The columns every file of a table has after the shared ones: what most of the readers add. A reader that does not
# have one leaves it empty. Two are here though only the readers of PDF minutes have them, because a row cannot be
# read rightly without them: `votes_read` is false, and `problem` says why, where a vote was taken and could not be read.
ADDED = {
    "items": ["item_id", "meeting_id", "section", "action_on", "number", "attachments"],
    "meetings": ["name", "packet_url", "video_url"],
    "agenda_items": ["heading", "section", "section_id", "motions", "doc_type", "subject", "description", "status", "number",
                     "attachments", "votes_read", "problem"],
    "votes": ["vote_kind", "motion", "motion_text", "read_from"],
    "members": [],
}
WHOLE = {"year", "ayes", "noes", "not_voting", "times_on_agenda", "items", "sequence", "motions", "motion", "district", "votes"}
YES_NO = {"serving", "heading", "votes_read"}

# A clerk's word for a vote that is neither aye nor no, in one of a few kinds. `vote` keeps the word itself.
ABSTAIN, ABSENT, RECUSED, OTHER = "ABSTAIN", "ABSENT", "RECUSED", "OTHER"
VOTE_KINDS = {"ABSTAIN": ABSTAIN, "ABSTAINED": ABSTAIN, "ABSTENTION": ABSTAIN, "PRESENT": ABSTAIN,
              "ABSENT": ABSENT, "NOT PRESENT": ABSENT, "AWAY": ABSENT, "EXCUSED": ABSENT, "LATE": ABSENT,
              "RECUSED": RECUSED, "RECUSE": RECUSED, "RECUSAL": RECUSED, "DISQUALIFIED": RECUSED}


def vote_kind(word):
    """AYE, NO, ABSTAIN, ABSENT, RECUSED, or OTHER for a word that is none of these (a vacant seat, a blank)."""
    return word if word in (council_tables.AYE, council_tables.NO) else VOTE_KINDS.get(word, OTHER)


# `daily` is for a county the daily run reads again (read_some): its system answers from the cloud, where the run is.
LEGISTAR = {"system": "Legistar", "read_from": SYSTEM, "builder": "build_legistar_council.py", "folder": "legistar/{key}", "daily": True}
# The readers the daily run can call for one county, and what each takes the county's name with.
READERS = {"build_legistar_council.py": ("build_legistar_council", "--city")}
CIVICCLERK = {"system": "CivicClerk", "read_from": SYSTEM, "builder": "build_civicclerk_board.py", "folder": "civicclerk/{key}"}
IQM2 = {"system": "IQM2", "read_from": SYSTEM, "builder": "build_iqm2_board.py", "folder": "iqm2/{key}"}
PDF = {"read_from": TEXT, "folder": "minutes_pdf/{key}"}

# Each county here: the body's id in bodies.json, then how its record is kept and read, and what to know of it.
COUNTIES = {
    "sd-county": {**LEGISTAR, "builder": "build_sd_county.py", "folder": "sdcounty", "raw": False,  # read by its own step of the daily run
                  "drop": {"items": ["text"]},
                  "note": "Its own dataset, sd-county-ordinances, has these tables and the text of each ordinance and resolution besides; "
                          "they are copied here from it each day."},
    "los-angeles-county": {**PDF, "system": "Statements of Proceedings (PDF)", "builder": "build_la_county_board.py",
                           "site": "https://lacounty.gov/government/board-of-supervisors/statement-of-proceedings/",
                           "note": "Votes are read from the text of each statement. A vote block is read whole or not at all: where it "
                                   "could not be, `votes_read` is false and the line has no votes."},
    "orange-county": {**PDF, "system": "Agenda system, minutes as PDF", "builder": "build_orange_board.py",
                      "note": "Until April 2026 the minutes print a vote as five digits in the margin, read by the key each set of "
                              "minutes prints (`read_from` is `margin code`); a mark typed by hand under the wrong digit would name "
                              "the wrong supervisor. Since then votes are printed by name."},
    "sacramento-county": {**PDF, "system": "AgendaNet, action summaries as PDF", "builder": "build_sacramento_board.py",
                          "note": "Votes are read from the text of each action summary; about 92% of vote blocks could be read whole, "
                                  "and the rest are marked `votes_read` false."},
    "santa-clara-county": {**IQM2, "note": "The County's portal withholds its regular meetings of January to May 2024, which have "
                                           "no lines and no votes here."},
    "san-bernardino-county": {**LEGISTAR, "note": "Meetings are listed from 1980 and agendas from 1996; votes by member begin in July 2019."},
    "contra-costa-county": {**LEGISTAR, "note": "The County took up this system in September 2023; earlier years are not in it."},
    "fresno-county": {**LEGISTAR},
    "san-joaquin-county": {**IQM2},
    "san-mateo-county": {**LEGISTAR, "note": "The list of items goes back to the 1880s; agendas and votes begin in 2017."},
    "sonoma-county": {**LEGISTAR},
    "tulare-county": {"system": "PrimeGov", "read_from": PAGE, "builder": "build_primegov_board.py", "folder": "primegov/{key}",
                      "note": "Votes are read from the minutes the County publishes as pages, from October 2020."},
    "santa-barbara-county": {**LEGISTAR},
    "placer-county": {**LEGISTAR, "note": "The County took up this system in July 2026. What it holds from before is practice entered "
                                          "while it was set up, and is left out."},
    "santa-cruz-county": {**IQM2, "site": "https://santacruzcountyca.iqm2.com/Citizens/",
                          "note": "Ends in December 2024, when the County left this system."},
    "yolo-county": {"system": "Destiny Hosted", "read_from": PAGE, "builder": "build_destiny_board.py", "folder": "destiny/{key}",
                    "note": "Votes are read from the words of the minutes: pages from 2016, the text of PDF minutes before."},
    "el-dorado-county": {**LEGISTAR},
    "humboldt-county": {**LEGISTAR},
    "napa-county": {**LEGISTAR, "note": "Thin: the clerk enters an action and a vote for about one agenda line in ten, in 2021 to 2024 "
                                        "and again from March 2026, and for almost none in 2025."},
    "nevada-county": {**LEGISTAR, "note": "The clerk enters what was done, and the votes, some months after a meeting."},
    "sutter-county": {**IQM2},
    "mendocino-county": {**LEGISTAR},
    "lake-county": {**LEGISTAR, "note": "Votes by member are entered for May 2014 to 2021, and rarely since."},
    "tehama-county": {**LEGISTAR, "note": "Meetings are listed from 1964 and agendas from 2013; votes by member begin in December 2023."},
    "tuolumne-county": {**CIVICCLERK}, "lassen-county": {**LEGISTAR}, "del-norte-county": {**CIVICCLERK}, "colusa-county": {**CIVICCLERK},
    "plumas-county": {**CIVICCLERK}, "mariposa-county": {**CIVICCLERK}, "modoc-county": {**CIVICCLERK}, "alpine-county": {**CIVICCLERK},
}
CIVICCLERK_NOTE = "Votes begin the month the clerk began entering them in this system; earlier years are in PDF minutes, not read."


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def facts_of(key, listed=None):
    """What is known of one county before its tables are read: its names, its code, where its tables are and how they were read."""
    body = (listed or {body["id"]: body for body in bodies.read_bodies()})[key]
    county = COUNTIES[key]
    name = body["name"].replace(" County Board of Supervisors", "")
    slug = name.lower().replace(" ", "-")
    return {
        "key": key, "county": name, "slug": slug, "county_fips": body["place"], "body": body["body"],
        "system": county["system"], "builder": county["builder"], "site": county.get("site") or body.get("url", ""),
        "folder": county["folder"].format(key=key), "raw": county.get("raw", True), "daily": county.get("daily", False),
        "drop": county.get("drop", {}), "read_from": county["read_from"],
        "room": ROOM.format(fips=body["place"]) if body.get("world") == "chamber" else "",
        "note": county.get("note") or (CIVICCLERK_NOTE if county["system"] == "CivicClerk" else ""),
    }


def read_from(facts, votes, meetings):
    """How each vote was read. It is one way a county, but for two that changed the way they print a vote."""
    if facts["key"] == "orange-county" and "code" in votes.columns:
        return votes["code"].fillna("").map(lambda code: CODE if code else TEXT)
    if facts["key"] == "yolo-county" and "source" in meetings.columns:
        source = votes["meeting_id"].map(dict(zip(meetings["meeting_id"], meetings["source"]))).fillna("")
        return source.map(lambda kind: TEXT if kind == "minutes document" else PAGE)
    return pd.Series(facts["read_from"], index=votes.index)


def one_shape(name, table, facts):
    """A reader's table with the columns every county's has, in order and of one kind each; what only that reader has is left to raw/."""
    wanted = council_tables.COLUMNS[name] + ADDED[name]
    out = pd.DataFrame(index=table.index)
    out["county"], out["county_fips"] = facts["county"], facts["county_fips"]
    for column in wanted:
        values = table[column] if column in table.columns else pd.Series(pd.NA, index=table.index, dtype=object)
        if column in WHOLE:
            out[column] = pd.to_numeric(values, errors="coerce").astype("Int64")
        elif column in YES_NO:
            out[column] = values.astype("boolean")
        else:
            out[column] = values.map(lambda value: "" if value is None or value is pd.NA or value != value else str(value))
    # A reader with no headings among its lines has skipped them: every line it has is an item.
    if name == "agenda_items" and "heading" not in table.columns:
        out["heading"] = pd.array([False] * len(out), dtype="boolean")
    return out.reset_index(drop=True)


def schema_of(name):
    import pyarrow as pa
    kind = lambda column: pa.int64() if column in WHOLE else pa.bool_() if column in YES_NO else pa.string()
    return pa.schema([("county", pa.string()), ("county_fips", pa.string())]
                     + [(column, kind(column)) for column in council_tables.COLUMNS[name] + ADDED[name]])


def write(table, path, name=None):
    import pyarrow as pa
    import pyarrow.parquet as pq
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(table, schema=schema_of(name), preserve_index=False) if name else
                   pa.Table.from_pandas(table, preserve_index=False), path, compression="zstd")


def county_row(facts, tables, read_on):
    """One county's line in the counties table, counted from its tables."""
    meetings, votes, members = tables["meetings"], tables["votes"], tables["members"]
    soon = (datetime.now(timezone.utc) + pd.Timedelta(days=366)).strftime("%Y-%m-%d")  # a stray date a century on is not the end
    held = meetings[(meetings["items"] > 0) & (meetings["date"] <= soon) & (meetings["date"] != "")]
    ways = [way for way in (SYSTEM, PAGE, TEXT, CODE) if (votes["read_from"] == way).any()] or [facts["read_from"]]
    return {
        "county": facts["county"], "county_fips": facts["county_fips"], "body": facts["body"], "system": facts["system"],
        "read_from": ", ".join(ways), "site": facts["site"],
        "first_meeting": held["date"].min() if len(held) else "", "last_meeting": held["date"].max() if len(held) else "",
        "first_vote": votes["date"].min() if len(votes) else "", "last_vote": votes["date"].max() if len(votes) else "",
        **{name: len(tables[name]) for name in TABLES},
        "serving": int(members["serving"].fillna(False).sum()),
        "kept_current": "daily run" if facts["daily"] else "by hand", "read_on": read_on,
        "room": facts["room"], "builder": facts["builder"], "note": facts["note"],
    }


COUNTY_COLUMNS = ["county", "county_fips", "body", "system", "read_from", "site", "first_meeting", "last_meeting", "first_vote",
                  "last_vote", *TABLES, "serving", "kept_current", "read_on", "room", "builder", "note"]


def build_county(key, out_dir, listed=None, folder=None):
    """One county's files, from the folder its reader wrote (its usual one, unless told another). Returns its line for the counties table."""
    facts = facts_of(key, listed)
    folder = Path(folder) if folder else bills.SCRIPT_DIR / facts["folder"]
    own = {name: pd.read_parquet(folder / f"{name}.parquet") for name in TABLES}
    tables = {}
    for name in TABLES:
        table = own[name].drop(columns=[column for column in facts["drop"].get(name, []) if column in own[name].columns])
        if name == "votes":
            table = table.assign(read_from=read_from(facts, table, own["meetings"]), vote_kind=table["vote"].fillna("").map(vote_kind))
        tables[name] = one_shape(name, table, facts)
        write(tables[name], out_dir / "data" / name / f"{facts['slug']}.parquet", name)
        if facts["raw"]:
            (out_dir / "raw" / facts["slug"]).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(folder / f"{name}.parquet", out_dir / "raw" / facts["slug"] / f"{name}.parquet")
    read_on = datetime.fromtimestamp((folder / "votes.parquet").stat().st_mtime, timezone.utc).strftime("%Y-%m-%d")
    return county_row(facts, tables, read_on)


def counties_table(rows, held=None):
    """The counties table: the lines just made, over those held for the counties not built this time."""
    table = pd.DataFrame(rows, columns=COUNTY_COLUMNS)
    if held is not None and len(held):
        table = pd.concat([held[~held["county_fips"].isin(table["county_fips"])], table], ignore_index=True)
    return table.sort_values("votes", ascending=False).reset_index(drop=True)


def card(counties):
    """The dataset card, with the counties and the counts written in."""
    listed = ["| County | Read from | Votes | Votes from | to | Room |", "|---|---|---|---|---|---|"]
    for row in counties.sort_values("county").itertuples():
        room = f"[open]({row.room})" if row.room else ""
        listed.append(f"| {row.county} | {row.system} | {row.votes:,} | {row.first_vote} | {row.last_vote} | {room} |")
    said = {}  # counties that share a note are named together
    for row in counties.sort_values("county").itertuples():
        if row.note:
            said.setdefault(row.note, []).append(row.county)
    notes = [f"- **{', '.join(names)}.** {note}" for note, names in sorted(said.items(), key=lambda pair: pair[1])]
    facts = {
        "repo": REPO, "n_counties": len(counties), "county_list": "\n".join(listed), "county_notes": "\n".join(notes),
        "first_vote": counties.loc[counties["first_vote"] != "", "first_vote"].min(), "last_vote": counties["last_vote"].max(),
        **{f"n_{name}": f"{int(counties[name].sum()):,}" for name in TABLES},
    }
    text = CARD_FILE.read_text(encoding="utf-8")
    for fact, value in facts.items():
        text = text.replace("{" + fact + "}", str(value))
    return text


def held_counties(out_dir):
    """The counties table to add a county's line to: as published, or failing that as last written here."""
    try:
        from huggingface_hub import hf_hub_download
        return pd.read_parquet(hf_hub_download(REPO, "data/counties.parquet", repo_type="dataset", token=bills.HF_TOKEN))
    except Exception:
        path = Path(out_dir) / "data" / "counties.parquet"
        return pd.read_parquet(path) if path.exists() else None


def publish_county(key, folder, out_dir=OUT_DIR):
    """Publish one county from the tables its reader has just written in `folder`. Every reader of a county board ends here."""
    if key not in COUNTIES:
        raise ValueError(f"{key} is not among the counties of {REPO}: add it to COUNTIES in build_ca_county_boards.py")
    problem = bills.hf_write_problem(REPO)
    if problem:
        raise PermissionError(problem)
    out_dir = Path(out_dir)
    counties = counties_table([build_county(key, out_dir, folder=folder)], held_counties(out_dir))
    write(counties, out_dir / "data" / "counties.parquet")
    return upload(out_dir, [facts_of(key)["slug"]], True, counties)


def read_some(minutes, out_dir=OUT_DIR):
    """The daily run's part. San Diego County's tables, if its own step wrote them today, are copied in. Then the counties
    marked `daily` are read again by their readers, the one longest unread first, until `minutes` are used: a county's
    turn comes every few days, which is as often as a board meets. Each publishes itself as it is read."""
    problem = bills.hf_write_problem(REPO)
    if problem:
        log.error(f"County boards not read: {problem}")
        log.info("RESULT: county-boards read=0 failed=0 waiting=0 minutes=0 pushed=False")
        return 1
    started, read, failed = time.time(), [], []
    counties = held_counties(out_dir)
    last = dict(zip(counties["county_fips"], counties["read_on"])) if counties is not None else {}
    listed = {body["id"]: body for body in bodies.read_bodies()}
    san_diego = bills.SCRIPT_DIR / COUNTIES["sd-county"]["folder"]
    written = san_diego / "votes.parquet"
    if written.exists() and datetime.fromtimestamp(written.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d") == today():
        try:
            publish_county("sd-county", san_diego, out_dir)
            read.append("sd-county")
        except Exception as e:
            log.error(f"sd-county not copied: {type(e).__name__}: {e}")
            failed.append("sd-county")
    due = sorted((key for key, county in COUNTIES.items() if county.get("daily") and county["builder"] in READERS),
                 key=lambda key: last.get(listed[key]["place"], ""))
    waiting = len(due)
    for key in due:
        if time.time() - started > minutes * 60:
            break
        module, flag = READERS[COUNTIES[key]["builder"]]
        waiting -= 1
        try:
            code = importlib.import_module(module).main([flag, key])
        except (Exception, SystemExit) as e:
            code = e
        if code:
            log.error(f"{key} not read: {code}")
            failed.append(key)
        else:
            read.append(key)
    log.info(f"RESULT: county-boards read={len(read)} failed={len(failed)} waiting={waiting} minutes={(time.time() - started) / 60:.0f} "
             f"counties={','.join(read)} pushed={bool(read)}")
    return 1 if failed else 0


def upload(out_dir, slugs, with_card, counties):
    """Publish the files of the counties built, the counties table, and the card if asked or if there is none."""
    problem = bills.hf_write_problem(REPO)
    if problem:
        log.error(f"Not uploaded: {problem}")
        return False
    from huggingface_hub import CommitOperationAdd, HfApi
    api = HfApi(token=bills.HF_TOKEN)
    api.create_repo(REPO, repo_type="dataset", exist_ok=True)
    files = [out_dir / "data" / "counties.parquet"]
    for slug in slugs:
        files += [out_dir / "data" / name / f"{slug}.parquet" for name in TABLES]
        files += sorted((out_dir / "raw" / slug).glob("*.parquet"))
    operations = [CommitOperationAdd(path_in_repo=str(path.relative_to(out_dir)), path_or_fileobj=str(path)) for path in files]
    if with_card or not api.file_exists(REPO, "README.md", repo_type="dataset"):
        operations.append(CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=card(counties).encode("utf-8")))
    api.create_commit(REPO, operations=operations, repo_type="dataset",
                      commit_message=f"Update {', '.join(slugs) if len(slugs) <= 3 else f'{len(slugs)} counties'}")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Put the county boards' tables in one dataset")
    parser.add_argument("--county", nargs="+", help="the counties to build, by name or body id (default: every one)")
    parser.add_argument("--out", default=str(OUT_DIR), help="directory to write the dataset's files into")
    parser.add_argument("--no-upload", action="store_true", help="write the files but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    parser.add_argument("--read", action="store_true", help="the daily run's part: read again the counties longest unread, and publish each")
    parser.add_argument("--minutes", type=float, default=30, help="with --read, stop starting counties after this many minutes")
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    if args.read:
        return read_some(args.minutes, out_dir)
    listed = {body["id"]: body for body in bodies.read_bodies()}
    by_slug = {facts_of(key, listed)["slug"]: key for key in COUNTIES}
    keys = [by_slug.get(name, name) for name in args.county] if args.county else list(COUNTIES)
    unknown = [key for key in keys if key not in COUNTIES]
    if unknown:
        parser.error(f"no such county: {', '.join(unknown)}")
    rows, failed = [], []
    for key in keys:
        try:
            rows.append(build_county(key, out_dir, listed))
        except Exception as e:
            log.error(f"{key} not built: {type(e).__name__}: {e}")
            failed.append(key)
    path = out_dir / "data" / "counties.parquet"
    counties = counties_table(rows, pd.read_parquet(path) if args.county and path.exists() else None)
    write(counties, path)
    (out_dir / "README.md").write_text(card(counties), encoding="utf-8")
    slugs = [facts_of(key, listed)["slug"] for key in keys if key not in failed]
    pushed = False if args.no_upload or not slugs else upload(out_dir, slugs, args.write_card, counties)
    log.info(f"RESULT: ca-county-boards counties={len(counties)} built={len(slugs)} failed={len(failed)} "
             f"{' '.join(f'{name}={int(counties[name].sum())}' for name in TABLES)} pushed={pushed}")
    return 1 if failed or not (args.no_upload or pushed) else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(main())
