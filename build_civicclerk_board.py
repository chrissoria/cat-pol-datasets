#!/usr/bin/env python3
"""
Build, for a county board of supervisors that keeps its record in CivicClerk,
what a room in Capitol World is made from: its meetings, what was on each
agenda, what the board did with it, and how each member voted.

One source: the county's meeting system (CivicClerk, by CivicPlus), through
the public API its own meeting portal reads, at
<county>.api.civicclerk.com/v1. What differs from one county to the next is
set out in BOARDS.

Each has a dataset of its own (chrissoria/<county>-county-board), with the five
tables every council's and board's dataset has (council_tables.py), in data/:
  items.parquet          every item put on an agenda
  meetings.parquet       one row per meeting of the board and the county's other bodies
  agenda_items.parquet   one row per line of a meeting's agenda, headings too, with what was done
  votes.parquet          one row per member and motion voted on
  members.parquet        one row per member seen voting at the board
They are kept here in civicclerk/<county>/.

Two ways to run it:

    python build_civicclerk_board.py --county del-norte-county
        The routine run. Starts from the published tables, lists every meeting
        again, and reads again the agendas and votes of meetings in the last
        60 days and those to come, and any not read before.

    python build_civicclerk_board.py --county del-norte-county --base
        The same, starting from the tables written here. Minutes for a county
        with a few hundred meetings: a meeting is one request.

    --all        read every meeting again, not only the recent and the unread
    --out DIR    where to write the tables
    --no-upload  write the tables but do not publish them
    --write-card publish the dataset card as well as the tables
"""

import argparse
import html
import json
import logging
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

import build_federal_bills as bills
import build_sd_county as county
import council_tables
from build_sd_county import clean, day_of, today

log = logging.getLogger(__name__)

OUT_DIR = bills.SCRIPT_DIR / "civicclerk"
CARD_FILE = bills.SCRIPT_DIR / "README_civicclerk_board.md"  # one card for every county, with the county's own facts written in
TABLES = council_tables.TABLES
RECENT_DAYS = 60  # meetings this recent are read again: minutes and votes are entered after the meeting
SEEN_DAYS = 2  # someone is a member if they vote at the board's meetings on this many days: once may be a clerk's slip
SERVING_DAYS = 120  # the system keeps no terms of office; a member who voted this recently is taken to be serving

# `tenant` is the county's name in the API's address; `board` is what the system calls the board of supervisors.
# Clerks began entering votes by member at different times, and some stopped: the last four here have them for a few
# months only (Trinity in 2024, Butte in 2024, Inyo in 2019) or hardly at all (Mono), and otherwise in the minutes'
# document alone.
BOARDS = {
    "alpine-county": {"tenant": "alpinecoca", "name": "Alpine", "board": ["Board of Supervisors"]},
    "colusa-county": {"tenant": "colusacoca", "name": "Colusa", "board": ["Board of Supervisors"]},
    "del-norte-county": {"tenant": "delnortecoca", "name": "Del Norte", "board": ["Board of Supervisors"]},
    "mariposa-county": {"tenant": "mariposacoca", "name": "Mariposa", "board": ["Board of Supervisors"]},
    "modoc-county": {"tenant": "modoccoca", "name": "Modoc", "board": ["Board of Supervisors"]},
    "plumas-county": {"tenant": "plumascoca", "name": "Plumas", "board": ["Board of Supervisors"]},
    "tuolumne-county": {"tenant": "tuolumnecoca", "name": "Tuolumne", "board": ["Board of Supervisors"]},
    "butte-county": {"tenant": "buttecoca", "name": "Butte", "board": ["Butte County Board of Supervisors"]},
    "inyo-county": {"tenant": "inyococa", "name": "Inyo", "board": ["Board of Supervisors"]},
    "mono-county": {"tenant": "monococa", "name": "Mono", "board": ["Board of Supervisors"]},
    "trinity-county": {"tenant": "trinitycoca", "name": "Trinity", "board": ["Board of Supervisors"]},
}

# The clerk's mark on a motion. Many motions that carried are left unmarked (-1), so the count of names says more.
RESULTS = {1: "Pass", 0: "Fail"}

ITEM_COLUMNS = council_tables.COLUMNS["items"] + ["item_id", "meeting_id", "section", "action_on", "number", "attachments"]
MEETING_COLUMNS = council_tables.COLUMNS["meetings"] + ["name", "agenda_id", "packet_url", "agenda_read"]
AGENDA_COLUMNS = council_tables.COLUMNS["agenda_items"] + ["heading", "section", "section_id", "motions", "pass_flag", "description",
                                                           "doc_type", "status", "subject", "number", "attachments"]
VOTE_COLUMNS = council_tables.COLUMNS["votes"] + ["motion", "motion_text"]


def repo_of(key):
    return f"chrissoria/{key}-board"


def api_of(key):
    return f"https://{BOARDS[key]['tenant']}.api.civicclerk.com/v1"


def fetch(url, tries=5, **params):
    """One answer from the API, as parsed JSON."""
    for attempt in range(tries):
        try:
            answer = requests.get(url, params=params or None, headers=county.HEADERS, timeout=90)
            answer.raise_for_status()
            return answer.json()
        except (requests.RequestException, ValueError) as e:
            # A host that is not allowed will not be allowed on a second asking.
            if attempt == tries - 1 or isinstance(e, requests.exceptions.ProxyError):
                raise
            time.sleep(2 * (attempt + 1))


def listed(key):
    """Every meeting the system lists, of any body, a page at a time."""
    events, url, params = [], f"{api_of(key)}/Events", {"$orderby": "startDateTime asc, id asc"}
    while url:
        page = fetch(url, **params)
        events.extend(page.get("value") or [])
        url, params = page.get("@odata.nextLink"), {}  # the next page's address carries the question with it
    return events


def plain(text):
    """An item's words as text: the system keeps some as HTML."""
    return clean(html.unescape(re.sub(r"<[^>]+>", " ", str(text or ""))))


def time_of(stamp):
    """`2026-09-08T10:00:00Z` as `10:00 AM`. The system labels the county's own clock time as if it were UTC."""
    found = re.match(r"\d{4}-\d\d-\d\dT(\d\d):(\d\d)", str(stamp or ""))
    if not found:
        return ""
    hour, minute = int(found[1]), found[2]
    return f"{hour % 12 or 12}:{minute} {'AM' if hour < 12 else 'PM'}"


def file_url(key, files, kind):
    """The address of a meeting's agenda, packet or minutes, from the files the system lists for it."""
    for file in files or []:
        if clean(file.get("type")).lower() == kind and file.get("fileId"):
            return f"{api_of(key)}/Meetings/GetMeetingFileStream(fileId={file['fileId']},plainText=false)"
    return ""


def meeting_page(key, meeting_id):
    return f"https://{BOARDS[key]['tenant']}.portal.civicclerk.com/event/{meeting_id}/files"


def meetings_table(key, events):
    rows = []
    for event in events:
        place = event.get("eventLocation") or {}
        files = event.get("publishedFiles")
        rows.append({
            "meeting_id": str(event["id"]),
            "date": day_of(event.get("startDateTime") or event.get("eventDate")),
            "time": time_of(event.get("startDateTime")),
            "body": clean(event.get("categoryName") or event.get("eventCategoryName")),
            "location": ", ".join(part for part in (clean(place.get(name)) for name in ("address1", "address2", "city")) if part),
            "url": meeting_page(key, event["id"]),
            "agenda_url": file_url(key, files, "agenda"),
            "minutes_url": file_url(key, files, "minutes"),
            "items": 0,
            "name": clean(event.get("eventName")),
            "agenda_id": str(event.get("agendaId") or ""),
            "packet_url": file_url(key, files, "agenda packet"),
            "agenda_read": False,
        })
    return pd.DataFrame(rows, columns=MEETING_COLUMNS).sort_values(["date", "meeting_id"]).reset_index(drop=True)


def lines_of(items, section=None, out=None):
    """An agenda's lines in order, each with the heading it sits under: the system keeps them as a tree."""
    out = [] if out is None else out
    for item in sorted(items or [], key=lambda item: item.get("sortOrder") or 0):
        out.append((item, section))
        lines_of(item.get("childItems"), item if item.get("isSection") else section, out)
    return out


def read_meeting(key, event):
    """One meeting's agenda: its lines, and the votes on each motion the clerk entered names for.

    A motion sits on the line it was made on. A consent agenda is voted on as one, so its motion is on its heading and
    not on the items under it. The system does not list a member who was absent.
    """
    meeting_id, date = str(event["id"]), day_of(event.get("startDateTime") or event.get("eventDate"))
    body = clean(event.get("categoryName") or event.get("eventCategoryName"))
    agenda, votes = [], []
    lines = lines_of(fetch(f"{api_of(key)}/Meetings/{event['agendaId']}").get("items"))
    for sequence, (item, section) in enumerate(lines, 1):
        item_id, heading = str(item["id"]), bool(item.get("isSection"))
        matter_id, file = ("" if heading else item_id), clean(item.get("agendaObjectItemNumber"))
        motions, last = item.get("minutesItemVotes") or [], {}
        for number, motion in enumerate(motions, 1):
            cast, seen = {}, set()
            for names, word in ((motion.get("yesVotes"), council_tables.AYE), (motion.get("noVotes"), council_tables.NO),
                                (motion.get("abstainVotes"), "ABSTAIN")):
                for name in names or []:
                    name = clean(name)
                    if not name or (name, word) in seen:
                        continue  # the same vote entered twice
                    seen.add((name, word))
                    cast[word] = cast.get(word, 0) + 1
                    votes.append({"item_id": item_id, "meeting_id": meeting_id, "date": date, "matter_id": matter_id,
                                  "matter_file": file, "member": name, "vote": word, "motion": number,
                                  "motion_text": clean(motion.get("motionName"))})
            last = {"action": clean(motion.get("motionName")), "mover": clean(motion.get("initiatedBy")),
                    "seconder": clean(motion.get("secondedBy")), "pass_flag": motion.get("passFail"), "cast": cast}
        cast = last.get("cast", {})
        flag = last.get("pass_flag")
        ordinance, resolution = clean(item.get("ordinanceFormattedNumber")), clean(item.get("resolutionFormattedNumber"))
        agenda.append({
            "item_id": item_id, "meeting_id": meeting_id, "date": date, "body": body,
            "agenda_number": clean(item.get("agendaObjectItemOutlineNumber")).rstrip("."),
            "sequence": sequence, "matter_id": matter_id, "matter_file": file,
            "title": plain(item.get("agendaObjectItemName")),
            "action": last.get("action", ""),
            "result": RESULTS.get(flag, ""),
            "mover": last.get("mover", ""), "seconder": last.get("seconder", ""),
            "ayes": cast.get(council_tables.AYE, 0), "noes": cast.get(council_tables.NO, 0),
            "not_voting": sum(count for word, count in cast.items() if word not in (council_tables.AYE, council_tables.NO)),
            "heading": heading,
            "section": plain(section.get("agendaObjectItemName")) if section else "",
            "section_id": str(section["id"]) if section else "",
            "motions": len(motions),
            "pass_flag": None if flag is None else int(flag),
            "description": plain(item.get("agendaObjectItemDescription")),
            "doc_type": "" if heading else "ordinance" if ordinance else "resolution" if resolution
                        else county.doc_type_of(plain(item.get("agendaObjectItemName"))),
            "status": clean(item.get("agendaObjItemStatusName")),
            "subject": clean(item.get("agendaObjItemCategoryTypeDesc")),
            "number": ordinance or resolution,
            "attachments": json.dumps([
                {"name": clean(paper.get("fileName")),
                 "url": clean(paper.get("linkToItem")) if paper.get("isLink") else
                        f"{api_of(key)}/Meetings/GetAttachmentFile(fileId={paper['id']})"}
                for paper in item.get("attachmentsList") or [] if paper.get("isPublished", True)],
                ensure_ascii=False, separators=(",", ":")),
        })
    return agenda, votes


def items_table(key, agenda):
    """Every item put on an agenda, with what was done with it: on its own motion, or failing that on its section's.

    The system has no record of an item apart from its line on an agenda, so an item is here once for each agenda it
    is on.
    """
    voted = {(line.meeting_id, line.item_id): line._asdict() for line in agenda[agenda["motions"] > 0].itertuples(index=False)}
    rows = []
    for line in agenda[~agenda["heading"]].itertuples(index=False):
        own, over = voted.get((line.meeting_id, line.item_id)), voted.get((line.meeting_id, line.section_id))
        done = own or over
        rows.append({
            "date": line.date, "matter_id": line.item_id, "matter_file": line.matter_file,
            "doc_type": line.doc_type, "title": line.title, "body": line.body, "status": line.status,
            "year": int(line.date[:4]) if line.date[:4].isdigit() else 0,
            "subject": line.subject, "agenda_date": line.date,
            "passed_date": "",  # the system has no day an item passed: a motion that carried may have been one to deny or put off
            "last_action": done["action"] if done else "", "last_action_date": line.date if done else "",
            "result": done["result"] if done else "",
            "ayes": int(done["ayes"]) if done else 0, "noes": int(done["noes"]) if done else 0,
            "mover": done["mover"] if done else "", "seconder": done["seconder"] if done else "",
            "times_on_agenda": 1, "url": meeting_page(key, line.meeting_id),
            "item_id": line.item_id, "meeting_id": line.meeting_id, "section": line.section,
            "action_on": "item" if own else "section" if over else "",
            "number": line.number, "attachments": line.attachments,
        })
    out = pd.DataFrame(rows, columns=ITEM_COLUMNS)
    return out.sort_values(["date", "meeting_id", "matter_id"], ascending=[False, False, True]).reset_index(drop=True)


def members_table(votes, meetings, board):
    """Everyone seen voting at the board's own meetings on several days. The system keeps no terms and no districts."""
    sat = set(meetings.loc[meetings["body"].isin(board), "meeting_id"])
    days = votes[votes["meeting_id"].isin(sat)].groupby("member")["date"].nunique()
    cast = votes.groupby("member")["date"].agg(["min", "max", "size"])
    since = (datetime.now(timezone.utc) - timedelta(days=SERVING_DAYS)).strftime("%Y-%m-%d")
    rows = [{"name": name, "district": None, "role": "", "start": "", "end": "",
             "serving": bool(cast.loc[name, "max"] >= since),
             "first_vote": cast.loc[name, "min"], "last_vote": cast.loc[name, "max"], "votes": int(cast.loc[name, "size"])}
            for name in sorted(days[days >= SEEN_DAYS].index) if name]
    out = pd.DataFrame(rows, columns=council_tables.COLUMNS["members"])
    out["district"] = out["district"].astype("Int64")
    out["serving"] = out["serving"].astype(bool)
    out["votes"] = out["votes"].astype(int)
    return out.sort_values(["first_vote", "name"]).reset_index(drop=True)


def joined(held, new):
    """Two tables of the same columns as one. An empty one adds nothing, and is left out so it cannot change a column's kind."""
    some = [table for table in (held, new) if len(table)]
    return pd.concat(some, ignore_index=True) if some else held


def build(key, base, everything, out_dir, every=400):
    board = BOARDS[key]
    events = listed(key)
    log.info(f"{board['name']}: {len(events)} meetings listed")
    if len(events) < 10:
        raise RuntimeError("the listing of meetings came back nearly empty")
    meetings = meetings_table(key, events)

    agenda, votes = (council_tables.held(repo_of(key), out_dir, name, base) for name in ("agenda_items", "votes"))
    before = 0 if votes is None else len(votes)
    if agenda is None or votes is None:
        agenda, votes = pd.DataFrame(columns=AGENDA_COLUMNS), pd.DataFrame(columns=VOTE_COLUMNS)
    # An agenda may be listed and hold nothing (a meeting brought over from an older system has only its packet), so
    # which were read is kept with the meetings, not told from which have lines.
    was = council_tables.held(repo_of(key), out_dir, "meetings", base)
    read_before = set(agenda["meeting_id"]) | (set(was.loc[was["agenda_read"], "meeting_id"])
                                              if was is not None and "agenda_read" in was.columns else set())
    recent = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    wanted = [event for event in events if event.get("agendaId")
              and (everything or str(event["id"]) not in read_before or day_of(event.get("startDateTime")) >= recent)]
    wanted.sort(key=lambda event: str(event.get("startDateTime")), reverse=True)  # the newest first: a room shows those
    log.info(f"Reading the agendas of {len(wanted)} meetings")

    read, answered = 0, set(read_before)
    for start in range(0, max(len(wanted), 1), every):
        some = wanted[start:start + every]
        new_agenda, new_votes, done = [], [], set()
        for event, found in zip(some, county.together(lambda event: read_meeting(key, event), some, "meeting")):
            if found is None:
                continue  # what is held for it stands, and the next run asks again
            done.add(str(event["id"]))
            new_agenda.extend(found[0])
            new_votes.extend(found[1])
        new_agenda = pd.DataFrame(new_agenda, columns=AGENDA_COLUMNS)
        new_votes = pd.DataFrame(new_votes, columns=VOTE_COLUMNS)
        agenda = joined(agenda[~agenda["meeting_id"].isin(done)], new_agenda)
        votes = joined(votes[~votes["meeting_id"].isin(done)], new_votes)
        agenda = agenda.sort_values(["date", "meeting_id", "sequence"]).reset_index(drop=True)
        votes = votes.sort_values(["date", "meeting_id", "item_id", "motion", "member"]).reset_index(drop=True)
        for table, columns in ((agenda, ("sequence", "ayes", "noes", "not_voting", "motions")), (votes, ("motion",))):
            for column in columns:
                table[column] = table[column].astype(int)
        agenda["heading"] = agenda["heading"].astype(bool)
        agenda["pass_flag"] = agenda["pass_flag"].astype("Int64")
        answered |= done
        meetings["agenda_read"] = meetings["meeting_id"].isin(answered)
        council_tables.write_tables({"agenda_items": agenda, "votes": votes, "meetings": meetings}, out_dir)
        read += len(done)
        log.info(f"{board['name']}: {min(start + every, len(wanted))} of {len(wanted)} meetings asked for, {len(votes)} votes held")

    meetings["items"] = meetings["meeting_id"].map(agenda[~agenda["heading"]].groupby("meeting_id").size()).fillna(0).astype(int)
    tables = council_tables.standard({
        "items": items_table(key, agenda), "meetings": meetings, "agenda_items": agenda, "votes": votes,
        "members": members_table(votes, meetings, {clean(name) for name in board["board"]}),
    })
    council_tables.write_tables(tables, out_dir)
    if len(votes) < before * 0.98:
        raise RuntimeError(f"only {len(votes)} votes where there were {before}; not publishing")
    return tables, read


def card(key, tables):
    """The dataset card: the one every county has, with this one's name, addresses and counts written in."""
    board, meetings, votes = BOARDS[key], tables["meetings"], tables["votes"]
    soon = (datetime.now(timezone.utc) + timedelta(days=366)).strftime("%Y-%m-%d")  # a stray meeting dated years on is not the end of the record
    read = meetings[(meetings["items"] > 0) & (meetings["date"] <= soon)]
    span = (f"Votes by member are here from {votes['date'].min()} to {votes['date'].max()}: the\nstretch for which the clerk "
            "entered them in this system. For a meeting outside\nit, and for any motion entered without names, who voted "
            "how is only in the\nminutes' document (`minutes_url`), which is not read here."
            if len(votes) else
            "The clerk does not enter votes in this system, so the `votes` and `members`\ntables are empty: who voted how is only "
            "in each meeting's minutes document\n(`minutes_url`), which is not read here.")
    facts = {
        "title": f"{board['name']} County Board of Supervisors", "place": board["name"], "repo": repo_of(key),
        "tenant": board["tenant"], "board_names": " or ".join(f'"{clean(name)}"' for name in board["board"]),
        "first_meeting": read["date"].min() if len(read) else "", "last_meeting": read["date"].max() if len(read) else "",
        "vote_span": span, "bodies": f"{meetings['body'].nunique():,}", "serving_days": SERVING_DAYS, "seen_days": SEEN_DAYS,
        **{f"n_{name}": f"{len(tables[name]):,}" for name in TABLES},
    }
    text = CARD_FILE.read_text(encoding="utf-8")
    for fact, value in facts.items():
        text = text.replace("{" + fact + "}", str(value))
    return text


def upload(key, tables, out_dir, with_card):
    try:
        council_tables.publish(repo_of(key), out_dir, card(key, tables) if CARD_FILE.exists() else "", with_card,
                               f"Update the tables ({today()})")
    except PermissionError as e:
        log.error(f"{key} tables not uploaded: {e}")
        return False
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a CivicClerk county's meetings, agendas and votes")
    parser.add_argument("--county", "--body", required=True, choices=sorted(BOARDS), help="the county whose board to read")
    parser.add_argument("--base", action="store_true", help="start from the tables written here, not the published ones")
    parser.add_argument("--all", action="store_true", help="read every meeting again")
    parser.add_argument("--out", default="", help="directory to write the tables into (civicclerk/<county> if not given)")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the tables only")

    out_dir = Path(args.out) if args.out else OUT_DIR / args.county
    try:
        tables, read = build(args.county, args.base, args.all, out_dir)
    except Exception as e:
        log.error(f"{args.county} tables not built: {type(e).__name__}: {e}")
        return 1
    pushed = False if args.no_upload else upload(args.county, tables, out_dir, args.write_card)
    agenda, votes, members = tables["agenda_items"], tables["votes"], tables["members"]
    log.info(f"RESULT: civicclerk-{args.county} items={len(tables['items'])} meetings={len(tables['meetings'])} "
             f"meetings_with_agenda={agenda['meeting_id'].nunique()} agenda_items={len(agenda)} votes={len(votes)} "
             f"motions_voted_on={len(votes.drop_duplicates(['item_id', 'motion']))} members={len(members)} "
             f"serving={int(members['serving'].sum())} voters_not_members={len(set(votes['member']) - set(members['name']))} "
             f"meetings_read={read} first_vote={votes['date'].min() if len(votes) else ''} "
             f"last_vote={votes['date'].max() if len(votes) else ''} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
