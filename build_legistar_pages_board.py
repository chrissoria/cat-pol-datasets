#!/usr/bin/env python3
"""
Build, for a board of supervisors whose Legistar has no working API, what a
room in Capitol World is made from: its meetings, what was on each agenda,
what the board did with it, and how each member voted.

One source: the pages of the board's own Legistar site (<name>.legistar.com),
the ones a visitor sees. Legistar's API answers for most places and
build_legistar_council.py reads it; for San Francisco it has been broken on
the City's side for years (its list of meetings answers with an error about a
setting, and what does answer stops in 2020), so the pages are read instead.
They hold the same record. What differs from one board to the next is set out
in BOARDS.

Three kinds of page:

  Calendar.aspx        the meetings of one body in one year. Which body and
                       year is a setting the site keeps in a cookie, so it is
                       sent with the request.
  MeetingDetail.aspx   one meeting: a line for each item, with what was done.
  HistoryDetail.aspx   one line's "Action details": who moved, the result,
                       and how each member voted.

Each has a dataset of its own (chrissoria/<county>-county-board), with the five
tables every council's and board's dataset has (council_tables.py), in data/:
  items.parquet          every item on an agenda read here, once
  meetings.parquet       one row per meeting of the board
  agenda_items.parquet   one row per line of a meeting's agenda, with what was done
  votes.parquet          one row per member and line voted on
  members.parquet        one row per member seen voting at the board
They are kept here in legistar_pages/<county>/.

A meeting is one page, and each line acted on one more: forty or so requests
for a meeting. So what is read is written every --every meetings, the newest
meetings first, and a meeting once read is not asked for again.

Two ways to run it:

    python build_legistar_pages_board.py --county san-francisco-county
        The routine run. Starts from the published tables, lists this year's
        meetings again, and reads again the agendas and votes of meetings in
        the last 60 days and those to come, and any not read before.

    python build_legistar_pages_board.py --county san-francisco-county --base
        The same, starting from the tables written here and listing every
        year's meetings again. Hours; it can be stopped and started again.

    --all          read every meeting again
    --since DAY    only meetings on or after this day (YYYY-MM-DD)
    --limit N      read no more than the N newest of the meetings wanted
    --minutes M    stop asking for more meetings after M minutes
    --every N      meetings to read between one writing of the tables and the next
    --out DIR      where to write the tables
    --no-upload    write the tables but do not publish them
    --write-card   publish the dataset card as well as the tables
"""

import argparse
import html
import logging
import re
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

import build_federal_bills as bills
import build_sd_county as county
import council_tables
from build_sd_county import clean, today

log = logging.getLogger(__name__)

OUT_DIR = bills.SCRIPT_DIR / "legistar_pages"
CARD_FILE = bills.SCRIPT_DIR / "README_legistar_pages_board.md"  # one card for every board, with the board's own facts written in
TABLES = council_tables.TABLES
RECENT_DAYS = 60  # meetings this recent are read again: actions and votes are entered after the meeting
SEEN_DAYS = 2  # someone is a member if they vote at the board's meetings on this many days: once may be a clerk's slip
SERVING_DAYS = 120  # the pages keep no terms of office; a member who voted this recently is taken to be serving
PAUSE = 0.3  # seconds a reader waits after each page: four read at once

# `host` is the board's site. `setting` is the number the site puts in the names of its cookies ("Setting-60-Calendar
# Year"), and `body_id` the calendar's own number for the board among the bodies it lists: both are on the calendar's
# page. `first` is the first year the calendar offers. `title` is the board's name where it is not "<name> County
# Board of Supervisors".
BOARDS = {
    "san-francisco-county": {"host": "sfgov.legistar.com", "name": "San Francisco", "title": "San Francisco Board of Supervisors",
                             "setting": 60, "body_id": 7374, "body": "Board of Supervisors", "first": 1998},
}

ITEM_COLUMNS = council_tables.COLUMNS["items"] + ["action_on", "file_type", "version"]
MEETING_COLUMNS = council_tables.COLUMNS["meetings"] + ["name", "guid", "read_on"]
AGENDA_COLUMNS = council_tables.COLUMNS["agenda_items"] + ["heading", "motions", "doc_type", "subject", "status", "file_type",
                                                           "version", "action_text", "guid", "matter_guid"]
VOTE_COLUMNS = council_tables.COLUMNS["votes"] + ["motion", "motion_text"]

REFUSED = {}  # host -> why it turned us away. Nothing more is asked of a host once it is here.
_local = threading.local()


class Refused(Exception):
    """The host answered with a bot check, a login or a refusal. It is not asked again in this run."""


def repo_of(key):
    return f"chrissoria/{key}-board"


def site_of(key):
    return f"https://{BOARDS[key]['host']}"


def meeting_page(key, meeting_id, guid):
    return f"{site_of(key)}/MeetingDetail.aspx?ID={meeting_id}&GUID={guid}"


def item_page(key, matter_id, guid):
    return f"{site_of(key)}/LegislationDetail.aspx?ID={matter_id}&GUID={guid}" if matter_id else ""


def fetch(url, tries=4, settings=None):
    """One page of the site, as text. `settings` are the site's own settings for the page, sent as its cookies.
    Raises Refused if the host turns us away."""
    host = urlparse(url).netloc
    for attempt in range(tries):
        if host in REFUSED:
            raise Refused(REFUSED[host])
        try:
            if not hasattr(_local, "session"):
                _local.session = requests.Session()
                _local.session.headers.update(county.HEADERS)
            cookie = "; ".join(f"{name}={value}" for name, value in (settings or {}).items())
            answer = _local.session.get(url, headers={"Cookie": cookie} if cookie else None, timeout=150)
            text = answer.text
            ours = "ContentPlaceHolder1" in text  # any page of the site has this
            if answer.status_code in (401, 403, 429) or (
                    not ours and re.search(r"captcha|challenge-platform|cf-chl|attention required|access denied", text, re.I)):
                REFUSED[host] = f"HTTP {answer.status_code} at {answer.url.split('?')[0]}"
                raise Refused(REFUSED[host])
            answer.raise_for_status()
            if not ours:
                raise requests.RequestException(f"not a page of the site: {url}")
            time.sleep(PAUSE)
            return text
        except Refused:
            raise
        except requests.RequestException as e:
            # A host that is not allowed will not be allowed on a second asking.
            if attempt == tries - 1 or isinstance(e, requests.exceptions.ProxyError):
                raise
            time.sleep(3 * (attempt + 1))


# ---------------------------------------------------------------------------
# The pages' tables
# ---------------------------------------------------------------------------

def grid(page, name):
    """A table of a page as (the page parsed, [{column heading: its cell}]). `name` is the table's own, "gridCalendar"."""
    soup = BeautifulSoup(page, "html.parser")
    table = soup.find(id=f"ctl00_ContentPlaceHolder1_{name}_ctl00")
    if table is None or table.find("thead") is None:
        return soup, []
    # A heading is "File #" with a space that does not break; a table's last headings may have no words at all.
    names = [clean(cell.get_text(" ").replace("\xa0", " ")) for cell in table.find("thead").find_all("th")]
    rows = []
    for row in table.find_all("tr", id=re.compile(rf"{name}_ctl00__\d+$")):
        cells = row.find_all("td")
        if len(cells) == len(names):
            rows.append(dict(zip(names, cells)))
    return soup, rows


def words(cell):
    return clean(cell.get_text(" ").replace("\xa0", " ")) if cell is not None else ""


_PAGE_ID = re.compile(r"\bID=(\d+)&(?:amp;)?GUID=([0-9A-Fa-f-]{36})")


def linked(cell, page):
    """(id, guid) of the page of the kind `page` ("MeetingDetail") that a cell links to, in its address or in what a click runs."""
    for link in cell.find_all("a") if cell is not None else []:
        for where in (link.get("href") or "", link.get("onclick") or ""):
            if f"{page}.aspx" in where:
                found = _PAGE_ID.search(html.unescape(where))
                if found:
                    return found[1], found[2].upper()
    return "", ""


def paper(key, cell):
    """The address of the document a cell links to (an agenda, the minutes), or "" where it has none yet."""
    link = cell.find("a", href=re.compile(r"View\.ashx\?")) if cell is not None else None
    return f"{site_of(key)}/{html.unescape(link['href'])}" if link is not None else ""


def calendar_rows(key, page):
    """The meetings on the calendar's page. One with no page of its own (it was cancelled, or is not set up yet) is left out."""
    rows = []
    for row in grid(page, "gridCalendar")[1]:
        meeting_id, guid = linked(row.get("Meeting Details"), "MeetingDetail")
        try:
            day = datetime.strptime(words(row.get("Meeting Date")), "%m/%d/%Y").strftime("%Y-%m-%d")
        except ValueError:
            continue
        if not meeting_id:
            continue
        # Under the place the cell says, in italics, what kind of meeting it is: "Regular Meeting".
        place = row.get("Meeting Location")
        kind = place.find("em") if place is not None else None
        name = words(kind)
        if kind is not None:
            kind.extract()
        rows.append({
            "meeting_id": meeting_id, "guid": guid, "date": day, "time": words(row.get("Meeting Time")), "body": words(row.get("Name")),
            "location": words(place), "name": name, "agenda_url": paper(key, row.get("Agenda")),
            "minutes_url": paper(key, row.get("Minutes")),
        })
    return rows


def listed_year(key, year):
    """Every meeting of the board the calendar lists in a year."""
    board = BOARDS[key]
    name = f"Setting-{board['setting']}-Calendar"
    page = fetch(f"{site_of(key)}/Calendar.aspx", settings={f"{name} Year": year, f"{name} Body": board["body_id"], f"{name} Options": "info|"})
    soup = BeautifulSoup(page, "html.parser")
    # The page says which body and year it is showing. If it is not what was asked for, the setting did not take.
    shown = {part: (soup.find(id=f"ctl00_ContentPlaceHolder1_lst{part}_Input") or {}).get("value", "") for part in ("Years", "Bodies")}
    if shown["Years"] != str(year) or clean(shown["Bodies"]) != board["body"]:
        raise RuntimeError(f"asked the calendar for {board['body']} in {year}, and it shows {shown['Bodies']!r} in {shown['Years']!r}")
    if re.search(r"Page \d+ of [2-9]", words(soup.find(class_="rgInfoPart"))):
        raise RuntimeError(f"the calendar for {year} runs to a second page, which is not read")
    return calendar_rows(key, page)


def meetings_table(key, rows):
    out = pd.DataFrame([{
        "meeting_id": row["meeting_id"], "date": row["date"], "time": row["time"], "body": row["body"], "location": row["location"],
        "url": meeting_page(key, row["meeting_id"], row["guid"]), "agenda_url": row["agenda_url"], "minutes_url": row["minutes_url"],
        "items": 0, "name": row["name"], "guid": row["guid"], "read_on": "",
    } for row in rows], columns=MEETING_COLUMNS)
    return out.drop_duplicates("meeting_id").sort_values(["date", "meeting_id"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# A meeting's pages
# ---------------------------------------------------------------------------

def lines_of(page):
    """The lines of a meeting's page, in order: each item's file, what it is, and what was done with it."""
    lines = []
    for row in grid(page, "gridMain")[1]:
        matter_id, matter_guid = linked(row.get("File #"), "LegislationDetail")
        item_id, guid = linked(row.get("Action Details"), "HistoryDetail")
        lines.append({
            "item_id": item_id, "guid": guid, "matter_id": matter_id, "matter_guid": matter_guid, "matter_file": words(row.get("File #")),
            "version": words(row.get("Ver.")), "agenda_number": words(row.get("Agenda #")), "subject": words(row.get("Name")),
            "file_type": words(row.get("Type")), "status": words(row.get("Status")), "title": words(row.get("Title")),
            "action": words(row.get("Action")), "result": words(row.get("Result")),
        })
    return lines


def read_action(page):
    """A line's "Action details": who moved and seconded, what was done and with what result, and each member's vote."""
    soup, rows = grid(page, "gridVote")
    said = lambda *names: next((words(found) for found in (soup.find(id=f"ctl00_ContentPlaceHolder1_{name}") for name in names)
                                if found is not None and words(found)), "")
    votes = [(words(row.get("Person Name")), council_tables.vote_word(words(row.get("Vote")))) for row in rows]
    return {
        "mover": said("hypMover", "lblMover"), "seconder": said("hypSeconder", "lblSeconder"), "result": said("lblResult"),
        "action": said("lblAction"), "action_text": said("lblActionText"), "file": said("hypFile", "lblFile"),
        "votes": [(name, word) for name, word in votes if name and word],
    }


def doc_type_of(file_type, title):
    kind = file_type.lower()
    return "ordinance" if "ordinance" in kind else "resolution" if "resolution" in kind else "other" if kind else county.doc_type_of(title)


def read_meeting(key, meeting):
    """One meeting's agenda: its lines, and the votes on each line the clerk entered an action for.

    A line with nothing done has no action details worth asking for: its page is not fetched.
    """
    meeting_id, date, body = str(meeting["meeting_id"]), meeting["date"], meeting["body"]
    agenda, votes, used = [], [], set()
    for sequence, line in enumerate(lines_of(fetch(meeting_page(key, meeting_id, meeting["guid"]))), 1):
        found = {}
        if line["item_id"] and (line["action"] or line["result"]):
            found = read_action(fetch(f"{site_of(key)}/HistoryDetail.aspx?ID={line['item_id']}&GUID={line['guid']}"))
            if found["file"] and line["matter_file"] and found["file"] != line["matter_file"]:
                raise RuntimeError(f"meeting {meeting_id}: the action details of {line['matter_file']} are those of {found['file']}")
        item_id = line["item_id"] or f"{meeting_id}-{sequence}"
        while item_id in used:
            item_id += "x"
        used.add(item_id)
        cast = found.get("votes", [])
        for name, word in cast:
            votes.append({"item_id": item_id, "meeting_id": meeting_id, "date": date, "matter_id": line["matter_id"],
                          "matter_file": line["matter_file"], "member": name, "vote": word, "motion": 1,
                          "motion_text": found.get("action_text", "")})
        ayes, noes = (sum(word == which for _, word in cast) for which in (council_tables.AYE, council_tables.NO))
        agenda.append({
            "item_id": item_id, "meeting_id": meeting_id, "date": date, "body": body, "agenda_number": line["agenda_number"],
            "sequence": sequence, "matter_id": line["matter_id"], "matter_file": line["matter_file"], "title": line["title"],
            "action": line["action"] or found.get("action", ""), "result": line["result"] or found.get("result", ""),
            "mover": found.get("mover", ""), "seconder": found.get("seconder", ""), "ayes": ayes, "noes": noes,
            "not_voting": len(cast) - ayes - noes, "heading": False, "motions": 1 if cast else 0,
            "doc_type": doc_type_of(line["file_type"], line["title"]), "subject": line["subject"], "status": line["status"],
            "file_type": line["file_type"], "version": line["version"], "action_text": found.get("action_text", ""),
            "guid": line["guid"], "matter_guid": line["matter_guid"],
        })
    return agenda, votes


# ---------------------------------------------------------------------------
# The tables made from what was read
# ---------------------------------------------------------------------------

def items_table(key, agenda):
    """Every item on an agenda read here, once, with the last thing done to it at a meeting of the board."""
    lines = agenda[agenda["matter_id"] != ""].sort_values(["date", "meeting_id", "sequence"])
    acted = lines[lines["action"] != ""].groupby("matter_id").tail(1).set_index("matter_id")
    first, times = lines.groupby("matter_id")["date"].min(), lines.groupby("matter_id").size()
    rows = []
    for line in lines.groupby("matter_id").tail(1).itertuples(index=False):
        done = acted.loc[line.matter_id] if line.matter_id in acted.index else None
        date = first[line.matter_id]
        rows.append({
            "date": date, "matter_id": line.matter_id, "matter_file": line.matter_file, "doc_type": line.doc_type,
            "title": line.title, "body": line.body, "status": line.status,
            "year": int(date[:4]) if date[:4].isdigit() else 0, "subject": line.subject, "agenda_date": line.date,
            "passed_date": "",  # the pages have no day an item passed: a motion that carried may have been one to deny or put off
            "last_action": done["action"] if done is not None else "",
            "last_action_date": done["date"] if done is not None else "",
            "result": done["result"] if done is not None else "",
            "ayes": int(done["ayes"]) if done is not None else 0, "noes": int(done["noes"]) if done is not None else 0,
            "mover": done["mover"] if done is not None else "", "seconder": done["seconder"] if done is not None else "",
            "times_on_agenda": int(times[line.matter_id]), "url": item_page(key, line.matter_id, line.matter_guid),
            "action_on": "" if done is None else "item", "file_type": line.file_type, "version": line.version,
        })
    out = pd.DataFrame(rows, columns=ITEM_COLUMNS)
    return out.sort_values(["date", "matter_id"], ascending=[False, False]).reset_index(drop=True)


def members_table(votes):
    """Everyone seen voting at the board's meetings on several days. The pages keep no terms of office and give no district."""
    days = votes.groupby("member")["date"].nunique()
    cast = votes.groupby("member")["date"].agg(["min", "max", "size"])
    since = (datetime.now(timezone.utc) - timedelta(days=SERVING_DAYS)).strftime("%Y-%m-%d")
    rows = [{"name": name, "district": None, "role": "", "start": "", "end": "", "serving": bool(cast.loc[name, "max"] >= since),
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


def build(key, base, everything, out_dir, since="", limit=0, minutes=0, every=20):
    board, started = BOARDS[key], time.time()
    held = council_tables.held(repo_of(key), out_dir, "meetings", base)
    recent = (pd.Timestamp(today()) - pd.Timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    # A whole run lists every year. The routine run lists this year's meetings again, and the last's while they are
    # recent; the years before stand as they were.
    first = board["first"] if held is None or base or everything else int(recent[:4])
    years = list(range(first, int(today()[:4]) + 1))
    found = county.together(lambda year: listed_year(key, year), years, f"{board['name']} calendar for")
    if any(rows is None for rows in found):
        raise RuntimeError(f"the calendar could not be listed for {[year for year, rows in zip(years, found) if rows is None]}")
    meetings = meetings_table(key, [row for rows in found for row in rows])
    log.info(f"{board['name']}: {len(meetings)} meetings listed for {years[0]} to {years[-1]}")
    if held is None and len(meetings) < 10:
        raise RuntimeError("the listing of meetings came back nearly empty")
    if held is not None:
        meetings["read_on"] = meetings["meeting_id"].map(dict(zip(held["meeting_id"], held["read_on"]))).fillna("")
        kept = held[(held["date"] < f"{years[0]}-01-01") & ~held["meeting_id"].isin(set(meetings["meeting_id"]))]
        meetings = joined(kept, meetings).sort_values(["date", "meeting_id"]).reset_index(drop=True)

    agenda, votes = (council_tables.held(repo_of(key), out_dir, name, base) for name in ("agenda_items", "votes"))
    before = 0 if votes is None else len(votes)
    if agenda is None or votes is None:
        agenda, votes = pd.DataFrame(columns=AGENDA_COLUMNS), pd.DataFrame(columns=VOTE_COLUMNS)
    wanted = meetings[(meetings["date"] >= since) & (everything | (meetings["read_on"] == "") | (meetings["date"] >= recent))]
    wanted = wanted.sort_values(["date", "meeting_id"], ascending=False)  # the newest first: a room shows those
    unread = len(wanted)
    wanted = (wanted.head(limit) if limit else wanted).to_dict("records")
    log.info(f"Reading the agendas of {len(wanted)} meetings of {unread} wanted")

    read = 0
    for start in range(0, max(len(wanted), 1), every):
        if minutes and time.time() - started > minutes * 60 or board["host"] in REFUSED:
            break
        some = {meeting["meeting_id"]: meeting for meeting in wanted[start:start + every]}
        new_agenda, new_votes, done = [], [], set()
        for meeting_id, found in zip(some, county.together(lambda meeting_id: read_meeting(key, some[meeting_id]), some, "meeting")):
            if found is None:
                continue  # what is held for it stands, and the next run asks again
            done.add(meeting_id)
            new_agenda.extend(found[0])
            new_votes.extend(found[1])
        agenda = joined(agenda[~agenda["meeting_id"].isin(done)], pd.DataFrame(new_agenda, columns=AGENDA_COLUMNS))
        votes = joined(votes[~votes["meeting_id"].isin(done)], pd.DataFrame(new_votes, columns=VOTE_COLUMNS))
        agenda = agenda.sort_values(["date", "meeting_id", "sequence"]).reset_index(drop=True)
        votes = votes.drop_duplicates(["item_id", "motion", "member", "vote"])
        votes = votes.sort_values(["date", "meeting_id", "item_id", "motion", "member"]).reset_index(drop=True)
        for table, columns in ((agenda, ("sequence", "ayes", "noes", "not_voting", "motions")), (votes, ("motion",))):
            for column in columns:
                table[column] = table[column].astype(int)
        agenda["heading"] = agenda["heading"].astype(bool)
        meetings.loc[meetings["meeting_id"].isin(done), "read_on"] = today()
        council_tables.write_tables({"meetings": meetings, "agenda_items": agenda, "votes": votes}, out_dir)
        read += len(done)
        log.info(f"{board['name']}: {min(start + every, len(wanted))} of {len(wanted)} meetings asked for, {len(votes)} votes held, "
                 f"{round((time.time() - started) / 60)} minutes")
    if board["host"] in REFUSED:
        log.error(f"{board['host']} turned us away ({REFUSED[board['host']]}); nothing more was asked of it")

    meetings["items"] = meetings["meeting_id"].map(agenda.groupby("meeting_id").size()).fillna(0).astype(int)
    tables = council_tables.standard({
        "items": items_table(key, agenda), "meetings": meetings, "agenda_items": agenda, "votes": votes, "members": members_table(votes),
    })
    council_tables.write_tables(tables, out_dir)
    if len(votes) < before * 0.98:
        raise RuntimeError(f"only {len(votes)} votes where there were {before}; not publishing")
    return tables, read, unread - read


def card(key, tables):
    """The dataset card: the one every board read this way has, with this one's name, addresses and counts written in."""
    board, meetings, votes = BOARDS[key], tables["meetings"], tables["votes"]
    read = meetings[meetings["items"] > 0]
    facts = {
        "title": board.get("title") or f"{board['name']} County Board of Supervisors", "place": board["name"], "repo": repo_of(key),
        "host": board["host"], "first_meeting": read["date"].min() if len(read) else "",
        "last_meeting": read["date"].max() if len(read) else "", "listed_from": meetings["date"].min() if len(meetings) else "",
        "first_vote": votes["date"].min() if len(votes) else "", "last_vote": votes["date"].max() if len(votes) else "",
        "serving_days": SERVING_DAYS, "seen_days": SEEN_DAYS, **{f"n_{name}": f"{len(tables[name]):,}" for name in TABLES},
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
    parser = argparse.ArgumentParser(description="Build a board's meetings, agendas and votes from the pages of its Legistar site")
    parser.add_argument("--county", "--body", required=True, choices=sorted(BOARDS), help="the county whose board to read")
    parser.add_argument("--base", action="store_true", help="start from the tables written here, not the published ones")
    parser.add_argument("--all", action="store_true", help="read every meeting again")
    parser.add_argument("--since", default="", help="only meetings on or after this day")
    parser.add_argument("--limit", type=int, default=0, help="read no more than this many of the newest meetings wanted")
    parser.add_argument("--minutes", type=float, default=0, help="stop asking for more meetings after this many minutes")
    parser.add_argument("--every", type=int, default=20, help="meetings to read between one writing of the tables and the next")
    parser.add_argument("--out", default="", help="directory to write the tables into (legistar_pages/<county> if not given)")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the tables only")

    out_dir = Path(args.out) if args.out else OUT_DIR / args.county
    try:
        tables, read, unread = build(args.county, args.base, args.all, out_dir, args.since, args.limit, args.minutes, args.every)
    except Exception as e:
        log.error(f"{args.county} tables not built: {type(e).__name__}: {e}")
        return 1
    refused = BOARDS[args.county]["host"] in REFUSED
    pushed = False if args.no_upload or refused else upload(args.county, tables, out_dir, args.write_card)
    agenda, votes, members = tables["agenda_items"], tables["votes"], tables["members"]
    log.info(f"RESULT: legistar-pages-{args.county} items={len(tables['items'])} meetings={len(tables['meetings'])} "
             f"meetings_with_agenda={agenda['meeting_id'].nunique()} agenda_items={len(agenda)} votes={len(votes)} "
             f"lines_voted_on={len(votes.drop_duplicates(['item_id', 'motion']))} members={len(members)} "
             f"serving={int(members['serving'].sum())} voters_not_members={len(set(votes['member']) - set(members['name']))} "
             f"meetings_read={read} meetings_unread={unread} first_vote={votes['date'].min() if len(votes) else ''} "
             f"last_vote={votes['date'].max() if len(votes) else ''} refused={refused} pushed={pushed}")
    return 0 if (args.no_upload or pushed) and not refused else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
