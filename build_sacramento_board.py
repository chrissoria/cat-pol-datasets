#!/usr/bin/env python3
"""
Build chrissoria/sacramento-county-board: the meetings of the Sacramento County
Board of Supervisors, what was on each agenda, what the Board did with it, and
how each supervisor voted.

One source: the County's meeting system ("AgendaNet", at
agendanet.saccounty.gov/BoardofSupervisors). It lists the meetings as a page of
HTML and keeps, for each, an action summary as a PDF. The system has no record
of a vote apart from that document, so the votes here are read from its text:
each motion voted on is followed by a block that names every supervisor

    AYES: Phil Serna, Patrick Kennedy, Rosario Rodriguez, Pat Hume
    NOES: None
    ABSTAIN: None
    ABSENT: Rich Desmond
    RECUSAL: None

A block is read whole or not at all. Every name in it must be a supervisor
listed at the head of that summary, and every supervisor listed there must be
in it once. A block that does not pass is left out of the votes: the motion is
kept, with what stopped the reading (`problem`), and counted as unread.

The dataset has the five tables every council's and board's dataset has
(council_tables.py), in data/:
  items.parquet          every item on the agenda of a meeting whose summary was read
  meetings.parquet       one row per meeting listed
  agenda_items.parquet   one row per line of a summary, headings too, with what was done
  votes.parquet          one row per supervisor and motion voted on
  members.parquet        one row per supervisor seen in a block
They are kept here in minutes_pdf/sacramento-county/, with the text of each
summary beside them in text/, so a summary is fetched once.

Two ways to run it:

    python build_sacramento_board.py
        The routine run. Starts from the published tables, lists every meeting
        again, and reads the summaries not read before and those of meetings
        in the last 90 days (a summary is posted weeks after its meeting, and
        is sometimes revised).

    python build_sacramento_board.py --base
        The same, starting from the tables written here. It reads the newest
        meeting first and can be stopped and started again.

    --since YEAR  read no meeting before this year (default 2006, where the listing begins)
    --max N       summaries to read in one run (default 0, for all)
    --all         read every summary again, from the text kept here where there is some
    --out DIR     where to write the tables
    --no-upload   write the tables but do not publish them
    --write-card  publish the dataset card as well as the tables

Needs pdfplumber. Only a PDF's own text is read: a summary that is a scan is
counted and left.
"""

import argparse
import html
import io
import json
import logging
import re
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests

import build_federal_bills as bills
import build_sd_county as county
import council_tables
from build_sd_county import clean, today

log = logging.getLogger(__name__)

HF_REPO = "chrissoria/sacramento-county-board"
OUT_DIR = bills.SCRIPT_DIR / "minutes_pdf" / "sacramento-county"
CARD_FILE = bills.SCRIPT_DIR / "README_sacramento_board.md"
TABLES = council_tables.TABLES
BODY = "Board of Supervisors"

HOST = "https://agendanet.saccounty.gov/BoardofSupervisors"
MEETING_TYPE = 106  # the system's number for "BOARD OF SUPERVISORS MEETING", the only kind it lists
FIRST_YEAR = 2006  # the listing begins here
RECENT_DAYS = 90  # meetings this recent are read again: the summary comes weeks later and is sometimes revised
LAYER_CHARS = 200  # a summary with fewer characters of its own than this is a scan
AGENDA, SUMMARY, PACKET = 1, 2, 5  # the system's numbers for a meeting's three documents

MEETING_COLUMNS = council_tables.COLUMNS["meetings"] + ["name", "packet_url", "summary", "pages", "roll", "vote_blocks", "blocks_read"]
AGENDA_COLUMNS = council_tables.COLUMNS["agenda_items"] + [
    "heading", "section", "section_id", "group", "motions", "vote_blocks", "blocks_read", "votes_read", "problem",
    "voted_with", "action_time", "districts", "doc_type", "subject", "number", "motion_log"]
VOTE_COLUMNS = council_tables.COLUMNS["votes"] + ["motion", "motion_text"]
ITEM_COLUMNS = council_tables.COLUMNS["items"] + ["item_id", "meeting_id", "section", "group", "action_on", "votes_read", "number"]

# A supervisor the summaries' headings spell two ways, and the one spelling kept here.
SPELLED = {"Jimmie R. Yee": "Jimmie Yee"}

# The words a block sorts the supervisors under, in the order it prints them. The last came in during 2016.
LABELS = ("AYES", "NOES", "ABSTAIN", "ABSENT", "RECUSAL")
NEEDED = LABELS[:4]

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_FOOTER = re.compile(rf"^\d{{1,3}}\s+(?:{_MONTHS})\s+\d{{1,2}},\s+\d{{4}}$", re.I)  # the foot of each page: its number and the day
_SECTION = re.compile(r"^Section\s+([IVXLC]+)\s*[-–—:]\s*(.*)$", re.I)
_OPENING = re.compile(r"^(ROLL CALL|PLEDGE OF ALLEGIANCE)\b")
_CLOSING = re.compile(r"^(Adjourned (in|at)\b|Respectfully Submitted\b)", re.I)
_ITEM = re.compile(r"^(\d{1,3})\.\s+(\S.*)$")
_ACTION = re.compile(r"^(?:(\d{1,2}\s?:\s?\d{2}\s?[AP]\.?M\.?)\s*[-–]?\s*)?Board Action\s*:\s*(.*)$", re.I)
_LABEL = re.compile(r"^(AYES|NOES|ABSTAIN|ABSENT|RECUSAL)\s*:\s*(.*)$")
_NONE = re.compile(r"^\(?\s*none\s*\)?\.?$", re.I)
_SEATED = re.compile(r"((?:[A-Z][\w.'’-]*\s+){1,3}[A-Z][\w'’-]*)\s*[–—-]\s*District\s+(\d)\s*(?:\(([^)]*)\))?")  # "Phil Serna – District 1 (Chair)"
_SUPERVISORS = re.compile(r"^Supervisors\s*:\s*(.*)$", re.I)  # before 2014: "Supervisors: Illa Collin, Roger Dickinson, ..."
_MOVED = re.compile(r"^([A-Z][A-Za-z.' ]{2,40}?)\s*/\s*([A-Z][A-Za-z.' ]{2,40}?)\s+[-–—]+\s*(.*)$")  # "Pat Hume / Phil Serna - Approved"
_RANGE = re.compile(r"\bItems?\s+(\d+)\s*(?:through|thru|to|-|–)\s*(\d+)", re.I)
_EXCEPT = re.compile(r"\bexcept|\bexclud|\bother than\b|\bpulled\b|\bremov", re.I)  # where a consent motion begins to say what it left out
_TALLY = re.compile(r"\b(\d)\s*[-–]\s*(\d)\s+vote\b|\bvote\s+of\s+(\d)\s*[-–]\s*(\d)\b|\bvote\s+of\s+(\d)\s+to\s+(\d)\b", re.I)
_NUMBER = re.compile(r"\b(Resolution|Ordinance)\s+Nos?\.?\s*((?:[A-Z]{2,5}[- ]?)?\d[\w-]*\d)", re.I)
_DISTRICTS = re.compile(r"^Supervisorial\s+Districts?(?:\(s\))?\s*:\s*(.*)$", re.I)
_IMPACT = re.compile(r"^Impact\s+Areas?(?:\(s\))?\s*:", re.I)
_APART = re.compile(r"CLOSED SESSION|NOT ON THE POSTED AGENDA|OFF[- ]AGENDA")  # headings of matters that have no number
_OF_THE_ITEM = re.compile(r"\bSEE\b|MOTION")  # lines in capitals that are about the item above them
_NOT_A_GROUP = re.compile(r"\bSEE\b|SESSION|MATTERS|PLEDGE|ROLL CALL|ADJOURN|[0-9:*.]")


class Refused(Exception):
    """The host answered with a check, a login or a refusal. It is not asked again in this run."""


_refused = threading.Event()
_CHECK = re.compile(r"captcha|cf-challenge|are you a human|access denied|sign in to continue", re.I)


def fetch(url, tries=4, **params):
    """One answer from the County's system. A refusal is not tried again, and nothing more is asked of the host in this run."""
    if _refused.is_set():
        raise Refused("the host refused an earlier request")
    for attempt in range(tries):
        try:
            answer = requests.get(url, params=params or None, headers=county.HEADERS, timeout=120)
            page = "html" in answer.headers.get("content-type", "") and answer.content[:4] != b"%PDF"
            if answer.status_code in (401, 403, 429) or (page and _CHECK.search(answer.text[:20000])):
                _refused.set()
                raise Refused(f"{answer.status_code} from {url.split('?')[0]}")
            answer.raise_for_status()
            return answer
        except requests.RequestException as e:
            # A host that is not allowed will not be allowed on a second asking.
            if attempt == tries - 1 or isinstance(e, requests.exceptions.ProxyError):
                raise
            time.sleep(2 * (attempt + 1))


def document_url(name, meeting_id, kind):
    """Where a meeting's agenda, summary or packet is served as the PDF itself."""
    return (f"{HOST}/Documents/ViewDocument/{quote(name)}?meetingId={meeting_id}&documentType={kind}"
            "&itemId=0&publishId=0&isSection=false") if name else ""


# ---------------------------------------------------------------------------
# The listing
# ---------------------------------------------------------------------------

_ROW = re.compile(r'<tr id="meeting-(\d+)-row".*?</tr>', re.S)
_CELL = r'data-sortable-type="{}"[^>]*>([^<]*)<'
_FILE = re.compile(r'/Documents/Download[Ff]ile/([^"?]+)\?documentType=(\d)')
_WHEN = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d\d)(?::\d\d)?\s*([AP]M)")


def rows_of(page):
    """The meetings on one page of the listing, as the system has them."""
    rows = []
    for found in _ROW.finditer(page):
        row = found[0]
        cell = lambda kind: clean(html.unescape((re.search(_CELL.format(kind), row) or ["", ""])[1]))
        when = _WHEN.search(cell("mtgTime"))
        if not when:
            continue
        files = {int(kind): html.unescape(name) for name, kind in _FILE.findall(row)}
        rows.append({"meeting_id": found[1], "name": cell("mtgName"),
                     "date": f"{when[3]}-{int(when[1]):02d}-{int(when[2]):02d}",
                     "time": f"{int(when[4])}:{when[5]} {when[6]}",
                     "agenda": files.get(AGENDA, ""), "summary": files.get(SUMMARY, ""), "packet": files.get(PACKET, "")})
    return rows


def listed(first=FIRST_YEAR, last=None):
    """Every meeting the system lists, two years to a request. A page of twenty years is too large for it to send."""
    last = last or datetime.now(timezone.utc).year + 1  # meetings to come are listed too
    rows = {}
    for year in range(first, last + 1, 2):
        page = fetch(f"{HOST}/Meetings/Search", dropid=11, mtids=MEETING_TYPE,
                     dropsv=f"01/01/{year} 00:00:00", dropev=f"12/31/{min(year + 1, last)} 23:59:59").text
        for row in rows_of(page):
            rows[row["meeting_id"]] = row
        time.sleep(0.5)
    return list(rows.values())


def meetings_table(rows):
    """One row per meeting listed. What a reading adds (`summary`, `pages`, `roll` and the counts) is filled in by build()."""
    out = [{
        "meeting_id": row["meeting_id"], "date": row["date"], "time": row["time"], "body": BODY, "location": "",
        "url": f"{HOST}/Meetings/ViewMeeting?id={row['meeting_id']}&doctype={AGENDA}",
        "agenda_url": document_url(row["agenda"], row["meeting_id"], AGENDA),
        "minutes_url": document_url(row["summary"], row["meeting_id"], SUMMARY),
        "items": 0, "name": row["name"],
        "packet_url": document_url(row["packet"], row["meeting_id"], PACKET),
        "summary": "", "pages": 0, "roll": "", "vote_blocks": 0, "blocks_read": 0,
    } for row in rows]
    return pd.DataFrame(out, columns=MEETING_COLUMNS).sort_values(["date", "meeting_id"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# A summary's text
# ---------------------------------------------------------------------------

def pdf_text(body):
    """The text a PDF carries, a page at a time. Nothing is read off the picture of a page."""
    import pdfplumber
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    with pdfplumber.open(io.BytesIO(body)) as document:
        return [page.extract_text() or "" for page in document.pages]


def text_of(meeting, out_dir, fresh=False):
    """The text of a meeting's summary, pages parted by form feeds: from the copy kept here, or fetched and kept."""
    kept = Path(out_dir) / "text" / f"{meeting['meeting_id']}.txt"
    if kept.exists() and not fresh:
        return kept.read_text(encoding="utf-8")
    time.sleep(0.3)
    body = fetch(meeting["minutes_url"]).content
    if body[:4] != b"%PDF":
        raise ValueError("the system sent a page in place of the summary")  # its error page comes with a 200
    text = "\f".join(pdf_text(body))
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(text, encoding="utf-8")
    return text


def lines_of(text):
    """A summary's lines in order, without the foot of each page: a block or a title often runs over a page's end."""
    lines = (clean(line) for line in text.replace("\f", "\n").split("\n"))
    return [line for line in lines if line and not _FOOTER.match(line)]


# ---------------------------------------------------------------------------
# Who sits on the Board, and who a name is
# ---------------------------------------------------------------------------

def key_of(name):
    """What two spellings of a supervisor's name share: the surname and the first letter. "Pat Hume" is "Patrick Hume"."""
    words = re.findall(r"[A-Za-z][A-Za-z'’-]*", str(name or ""))
    return (words[0][0].lower(), words[-1].lower()) if len(words) >= 2 else None


def roll_of(lines):
    """The supervisors listed at the head of a summary, each with the district and the office printed there.

    Since 2014 they stand above the title, one to a line as a rule, with their districts. Before that they are on
    one line, with no districts. An empty list if neither is found, or if two of them could be taken for each other.
    """
    top = next((index for index, line in enumerate(lines[:20]) if "ACTION SUMMARY" in line), 8)
    roll = [{"name": clean(name), "district": int(district), "role": clean(role)}
            for name, district, role in _SEATED.findall(" ".join(lines[:top]))]
    for index, line in enumerate(lines[:40]):
        named = _SUPERVISORS.match(line)
        if named and not roll:
            names = named[1]
            if names.rstrip().endswith(",") and index + 1 < len(lines) and not lines[index + 1].startswith("("):
                names += " " + lines[index + 1]  # the list ran on to a second line
            roll = [{"name": clean(name), "district": None, "role": ""} for name in names.split(",") if clean(name)]
    for member in roll:
        member["name"] = SPELLED.get(member["name"], member["name"])
    keys = [key_of(member["name"]) for member in roll]
    return roll if roll and None not in keys and len(set(keys)) == len(keys) else []


def who(name, roll):
    """The supervisor on the roll that a printed name is, or None.

    A name is two words, or three with an initial between them, and nothing else: "Phil Serna Patrick Kennedy", where
    the clerk left out a comma, is nobody.
    """
    words = clean(name).split()
    plain = all(re.fullmatch(r"[A-Za-z][A-Za-z'’-]*\.?", word) for word in words)
    if not plain or not (len(words) == 2 or (len(words) == 3 and len(words[1].rstrip(".")) == 1)):
        return None
    key = key_of(name)
    found = [member["name"] for member in roll if key_of(member["name"]) == key]
    return found[0] if len(found) == 1 else None


def only_names(line, roll):
    """Whether a line is nothing but names from the roll: the rest of a list of names that ran over the line's end."""
    known = {word.lower() for member in roll for word in re.findall(r"[A-Za-z'’-]+", member["name"])}
    words = re.findall(r"[A-Za-z'’-]+", line)
    return bool(words) and not re.search(r"[^A-Za-z'’., -]", line) and all(
        word.lower() in known or (len(word) >= 3 and any(name.startswith(word.lower()) for name in known)) for word in words)


def read_block(lines, roll):
    """One block of votes: ([(supervisor, word), ...], "") if it reads cleanly, or (None, why not).

    `lines` are the block's own: each begins with one of LABELS, or is the rest of the list of names above it.
    Clean means: the words stand once each and in their order; every name is one supervisor on the roll; nobody is
    named twice; and nobody on the roll is left out. So a block cut short, or run into the text after it, is not read.
    """
    if not roll:
        return None, "no roll at the head of the summary"
    named, order = {}, []
    for line in lines:
        label = _LABEL.match(line)
        if label:
            if label[1] in named:
                return None, f"{label[1]} twice"
            order.append(label[1])
            named[label[1]] = label[2]
        elif order:
            named[order[-1]] += " " + line
        else:
            return None, "no AYES"
    if order != [word for word in LABELS if word in named] or any(word not in named for word in NEEDED):
        return None, "words missing or out of order: " + " ".join(order)
    cast, seen = [], set()
    for word in order:
        names = clean(named[word])
        if _NONE.match(names) or not names:
            continue
        for name in names.split(","):
            if not clean(name):
                continue  # a comma left at the end of the list
            member = who(name, roll)
            if member is None:
                return None, f"not on the roll: {clean(name)[:60]}"
            if member in seen:
                return None, f"named twice: {member}"
            seen.add(member)
            cast.append((member, council_tables.vote_word(word)))
    if len(seen) != len(roll):
        return None, f"{len(seen)} of {len(roll)} supervisors named"
    return cast, ""


# ---------------------------------------------------------------------------
# Reading a summary
# ---------------------------------------------------------------------------

def capitals(line):
    """Whether a line is a heading set in capitals (COUNTY EXECUTIVE), which ends the title or the action above it.

    A run of file numbers (P000527, P000528) has no small letters either, and is not one.
    """
    letters = len(re.findall(r"[A-Z]", line))
    return letters >= 4 and not re.search(r"[a-z]", line) and not line[0].isdigit() and letters >= 0.6 * len(re.sub(r"\s", "", line))


def moved(text, roll):
    """(mover, seconder, the rest) of an action that begins "Pat Hume / Phil Serna - Approved", else ("", "", text)."""
    found = _MOVED.match(text)
    if found:
        mover, seconder = who(found[1], roll), who(found[2], roll)
        if mover and seconder:
            return mover, seconder, found[3]
    return "", "", text


def tally_of(text):
    """The count an action states in words ("by a 3-2 vote"), as (ayes, noes), or None. Few do."""
    found = _TALLY.search(text)
    if not found:
        return None
    pair = [int(digit) for digit in found.groups() if digit is not None]
    return pair[0], pair[1]


def parse(text):
    """A summary's text as (roll, lines). Each line is a heading or an item, with the motions made on it.

    The summary is a run of numbered items under headings ("Section III - Consent Matters"). What the Board did
    follows each as "Board Action:", and a vote by name follows that as a block. A consent agenda is voted on as one,
    so its action and block stand under its heading, before its items. A matter with no number (the election of
    the chair, a closed session) is a line of its own, with no `agenda_number`.

    An item begins at a line that opens with a number higher than the last item's. Three things make that less
    simple than it sounds, and each leaves a mark (`doubt`) on the lines it touches, whose blocks are then not read:
      - The text sometimes loses an item's number. The item's action and block then follow on from the item before
        as if they were its own, so where the numbers skip, everything since the last numbered item is in doubt.
      - Points inside an action are numbered too ("1. Approve the rates. 2. Enact ..."). They start again from 1,
        which tells them apart, unless the list is as long as the item's number is high.
      - A title may break before a number ("Reclamation District / 813. This item ..."). The numbering then
        resumes below it, which shows it up; if it happens to be the next number, the true item shows up as a
        second line with that number.
    """
    lines = lines_of(text)
    roll = roll_of(lines)
    # The summary opens with how to address the Board, which may be set out in numbered points. The business begins
    # at the roll call, the pledge or the first heading; a workshop's summary has none of them and begins at once.
    opening = next((index for index, line in enumerate(lines) if _SECTION.match(line) or _OPENING.match(line)), 0)
    out, current, section, group = [], None, None, ""
    part = ""  # what the lines now being read belong to: "title", "action", "block" or nothing
    last, point, since = 0, 0, 0  # the last item's number; the last numbered point's; where in `out` the last item is
    loose = ""  # headings in capitals met since the line's last words: an action after them is not that line's
    block = None

    def close():
        """End the block being gathered and read it."""
        nonlocal block
        if block is None:
            return
        motion, block_lines = block
        block = None
        cast, problem = read_block(block_lines, roll)
        stated = tally_of(motion["text"])
        if cast is not None and stated is not None:
            counted = (sum(word == council_tables.AYE for _, word in cast), sum(word == council_tables.NO for _, word in cast))
            if counted != stated:
                cast, problem = None, f"the action says {stated[0]}-{stated[1]} and the block has {counted[0]}-{counted[1]}"
        motion.update(block=True, cast=cast or [], read=cast is not None, problem=problem)

    def begin(heading, number, title):
        nonlocal current, part, point, loose
        close()
        current = {"heading": heading, "number": number, "title": title, "section": None if heading else section,
                   "group": "" if heading else group, "districts": "", "motions": [], "doubt": ""}
        part, point, loose = "title", 0, ""
        out.append(current)

    def doubt(why, doubted):
        for line in doubted:
            line["doubt"] = line["doubt"] or why

    for index, text_line in enumerate(lines):
        if index < opening:
            continue
        heading, item, action, label = _SECTION.match(text_line), _ITEM.match(text_line), _ACTION.match(text_line), _LABEL.match(text_line)
        if heading:
            begin(True, "", clean(f"Section {heading[1].upper()} - {heading[2]}"))
            section, group = current, ""
            continue
        if item:
            number = int(item[1])
            listed = part in ("title", "action") and number == point + 1 and (point > 0 or last >= 1)
            opens, unsure = False, []
            if number > last and listed:
                # The next item's number and the next point's are the same.
                opens, unsure = looks_like_item(lines, index), [current]
            elif number == last + 1:
                opens = True
            elif number > last + 1:
                opens = not resumes_below(lines, index, last, number)
            elif not listed and current is not None:
                doubt(f"a second line numbered {number}", [current])
            if opens:
                skipped = out[since:] if number > last + 1 else []
                begin(False, str(number), item[2])
                doubt(f"no item numbered {last + 1}: it may have run on from the one before", skipped)
                doubt("an item or a numbered point: the numbering does not say", unsure and unsure + [current])
                last, since = number, len(out) - 1
                continue
            if listed:
                point = number
        apart = action and _APART.search(loose)
        if (action or label) and (current is None or apart):
            # A matter with no number (the election of the chair, a closed session): what stands above the action
            # is all the title it has.
            above = lines[index - 1] if index > opening and not (_LABEL.match(lines[index - 1]) or _OPENING.match(lines[index - 1])) else ""
            begin(False, "", loose if apart else above)
        if current is None:
            continue  # the head of the summary: the roll, and how to address the Board
        if action:
            close()
            mover, seconder, rest = moved(clean(action[2]), roll)
            current["motions"].append({"time": re.sub(r"\s*:\s*", ":", clean(action[1])), "text": rest, "mover": mover,
                                       "seconder": seconder, "block": False, "cast": [], "read": False, "problem": "",
                                       "doubt": "a heading in capitals stands between the item and this action" if loose else "",
                                       "unsplit": not mover})
            part, point, loose = "action", 0, ""
            continue
        if label:
            if label[1] == "AYES" or block is None:
                close()
                motion = current["motions"][-1] if current["motions"] and not current["motions"][-1]["block"] else None
                if motion is None:
                    # Names with no action of their own before them: a second block under one action. Which of the
                    # two is the vote on it the summary does not say, so neither is read.
                    if current["motions"]:
                        current["motions"][-1]["doubt"] = "two blocks under one action"
                    motion = {"time": "", "text": "", "mover": "", "seconder": "", "block": False, "cast": [], "read": False,
                              "problem": "", "doubt": "a block with no action of its own before it", "unsplit": False}
                    current["motions"].append(motion)
                block = (motion, [])
                part = "block"
            block[1].append(text_line)
            continue
        if part == "block":
            # The rest of a list of names that ran over the line's end: names from the roll, or whatever stands
            # between two of the block's words (names of another board's directors, which stop the block being read).
            within = index + 1 < len(lines) and _LABEL.match(lines[index + 1]) and not lines[index + 1].startswith("AYES")
            if only_names(text_line, roll) or within:
                block[1].append(text_line)
                continue
            close()
            part = ""
        if _CLOSING.match(text_line):
            part = ""  # the meeting's end and the Clerk's signature are no part of the last item
            continue
        districts = _DISTRICTS.match(text_line)
        if districts and part != "title" and current["motions"]:
            # An item's districts where no item began: the text has lost the item's number. What follows is that
            # item's and not the one before's, and its title has gone into the words above.
            begin(False, "", "")
            doubt("an item whose number the text has lost", [current])
            current["districts"], part = clean(districts[1]), ""
            continue
        if part == "title":
            if districts:
                current["districts"], part = clean(districts[1]), ""
                continue
            if not (_IMPACT.match(text_line) or text_line.startswith("(Directors:")
                    or (capitals(text_line) and re.search(r"[a-z]", current["title"]))):
                current["title"] += " " + text_line
                continue
            part = ""
        elif part == "action":
            motion = current["motions"][-1]
            if motion["unsplit"]:
                # The movers' names may run over the line's end: look again with the next line joined on.
                mover, seconder, rest = moved(clean(motion["text"] + " " + text_line), roll)
                motion["unsplit"] = False
                if mover:
                    motion.update(mover=mover, seconder=seconder, text=rest)
                    continue
            said = index + 1 < len(lines) and _LABEL.match(lines[index + 1])  # MOTION FAILED, just above the block
            if said or not (capitals(text_line) and re.search(r"[a-z]", motion["text"])):
                motion["text"] = clean(motion["text"] + " " + text_line)
                continue
            part = ""
        if capitals(text_line) and not text_line.startswith("("):
            if current["motions"] and not _OF_THE_ITEM.search(text_line):
                loose = clean(f"{loose} {text_line}")[:300]
            if not _NOT_A_GROUP.search(text_line):
                group = text_line  # whose business follows: COUNTY EXECUTIVE, SACRAMENTO COUNTY WATER AGENCY
    close()
    return roll, out


def looks_like_item(lines, index):
    """Whether the numbered line at `index` opens an item: an item has its districts or its own action before the next block."""
    for line in lines[index + 1:index + 40]:
        if _DISTRICTS.match(line) or _ACTION.match(line):
            return True
        if _LABEL.match(line) or _ITEM.match(line) or _SECTION.match(line):
            return False
    return False


def resumes_below(lines, index, last, number):
    """Whether the numbering picks up again under `number`: the line at `index` is then a title broken before a number."""
    for line in lines[index + 1:]:
        found = _ITEM.match(line)
        if found and int(found[1]) > last:
            return int(found[1]) < number
    return False


def covered(line, lines):
    """The heading whose one vote took in this item: a consent agenda's, unless the motion left the item out."""
    heading = line["section"]
    if heading is None or line["heading"] or any(motion["block"] for motion in line["motions"]):
        return None
    voted = [motion for motion in heading["motions"] if motion["block"]]
    if len(voted) != 1 or not line["number"].isdigit():
        return None
    text, number = voted[0]["text"], int(line["number"])
    span = _RANGE.search(text)
    if not span or not int(span[1]) <= number <= int(span[2]):
        return None
    # What the motion left out is said many ways ("with the exception of Items 2 and 36", "with the exceptions of 34
    # and 36", "excluding Item 7"), so every number after the word is taken to be left out. That leaves out too much
    # now and then (a date the item was continued to), and never too little.
    left_out = {int(digits) for digits in re.findall(r"\d+", text[_EXCEPT.search(text).start():])} if _EXCEPT.search(text) else set()
    return None if number in left_out else heading


def read_meeting(meeting, out_dir, fresh=False):
    """One meeting's summary: its lines, the votes on each motion whose block read cleanly, and what the reading found."""
    text = text_of(meeting, out_dir, fresh)
    pages = text.count("\f") + 1
    facts = {"summary": "read", "pages": pages, "roll": "", "vote_blocks": 0, "blocks_read": 0}
    if len(re.sub(r"\s", "", text)) < LAYER_CHARS:
        return [], [], {**facts, "summary": "no text layer"}
    roll, lines = parse(text)
    facts["roll"] = json.dumps(roll, ensure_ascii=False, separators=(",", ":"))
    meeting_id, date = meeting["meeting_id"], meeting["date"]
    agenda, votes, sections, unnumbered = [], [], 0, 0
    for line in lines:
        if line["heading"]:
            sections += 1
            line["item_id"] = f"{meeting_id}-s{sections}"
        elif line["number"]:
            line["item_id"] = f"{meeting_id}-{line['number']}"
        else:
            unnumbered += 1
            line["item_id"] = f"{meeting_id}-u{unnumbered}"
    for sequence, line in enumerate(lines, 1):
        item_id, heading = line["item_id"], line["heading"]
        matter_id = "" if heading else item_id
        for motion in line["motions"]:
            doubt = line["doubt"] or motion["doubt"]
            if motion["block"] and doubt:
                motion.update(cast=[], read=False, problem=doubt)
        for number, motion in enumerate(line["motions"], 1):
            for member, word in motion["cast"]:
                votes.append({"item_id": item_id, "meeting_id": meeting_id, "date": date, "matter_id": matter_id, "matter_file": "",
                              "member": member, "vote": word, "motion": number, "motion_text": motion["text"]})
        blocks = [motion for motion in line["motions"] if motion["block"]]
        # What is said of the line is its last vote, or with no vote its last action.
        last = blocks[-1] if blocks else line["motions"][-1] if line["motions"] else None
        cast = [word for _, word in last["cast"]] if last else []
        over = covered(line, lines)
        title = clean(line["title"])
        texts = " ".join(motion["text"] for motion in line["motions"])
        numbered = _NUMBER.search(texts)
        subject = re.search(r"\(([^()]*[a-z][^()]*)\)$", title)
        agenda.append({
            "item_id": item_id, "meeting_id": meeting_id, "date": date, "body": BODY,
            "agenda_number": line["number"], "sequence": sequence, "matter_id": matter_id, "matter_file": "", "title": title,
            "action": last["text"] if last else "",
            "result": "Fail" if last and "MOTION FAILED" in last["text"] else "",  # a motion that carried is not marked
            "mover": last["mover"] if last else "", "seconder": last["seconder"] if last else "",
            "ayes": cast.count(council_tables.AYE), "noes": cast.count(council_tables.NO),
            "not_voting": sum(word not in (council_tables.AYE, council_tables.NO) for word in cast),
            "heading": heading,
            "section": line["section"]["title"] if line["section"] else "",
            "section_id": line["section"]["item_id"] if line["section"] else "",
            "group": line["group"],
            "motions": len(line["motions"]), "vote_blocks": len(blocks), "blocks_read": sum(motion["read"] for motion in blocks),
            "votes_read": all(motion["read"] for motion in blocks) if blocks else None,
            "problem": next((motion["problem"] for motion in blocks if not motion["read"]), ""),
            "voted_with": item_id if blocks else over["item_id"] if over else "",
            "action_time": last["time"] if last else "",
            "districts": line["districts"],
            "doc_type": "" if heading else numbered[1].lower() if numbered else county.doc_type_of(title),
            "subject": "" if heading or not subject or subject[1].lower().startswith(("copies", "continued", "waived")) else subject[1],
            "number": clean(numbered[2]) if numbered else "",
            "motion_log": json.dumps([{"motion": number, "time": motion["time"], "action": motion["text"], "mover": motion["mover"],
                                       "seconder": motion["seconder"], "block": motion["block"], "read": motion["read"],
                                       "problem": motion["problem"]} for number, motion in enumerate(line["motions"], 1)],
                                     ensure_ascii=False, separators=(",", ":")),
        })
        facts["vote_blocks"] += len(blocks)
        facts["blocks_read"] += sum(motion["read"] for motion in blocks)
    return agenda, votes, facts


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------

def items_table(agenda, meetings):
    """Every item on a summary, with what was done with it: by a vote of its own, or failing that by its heading's.

    The system has no record of an item apart from its line in a summary, so an item is here once for each meeting
    it came to.
    """
    of, summary = agenda.set_index("item_id"), dict(zip(meetings["meeting_id"], meetings["minutes_url"]))
    rows = []
    for line in agenda[~agenda["heading"]].itertuples(index=False):
        own = line.vote_blocks > 0
        over = of.loc[line.voted_with] if not own and line.voted_with else None
        vote = line._asdict() if own else over.to_dict() if over is not None else None
        rows.append({
            "date": line.date, "matter_id": line.item_id, "matter_file": "", "doc_type": line.doc_type, "title": line.title,
            "body": line.body, "status": "", "year": int(line.date[:4]), "subject": line.subject, "agenda_date": line.date,
            "passed_date": "",
            "last_action": line.action or (vote["action"] if vote else ""),
            "last_action_date": line.date if line.action or vote else "",
            "result": "",
            "ayes": int(vote["ayes"]) if vote else 0, "noes": int(vote["noes"]) if vote else 0,
            "mover": vote["mover"] if vote else "", "seconder": vote["seconder"] if vote else "",
            "times_on_agenda": 1, "url": summary.get(line.meeting_id, ""),
            "item_id": line.item_id, "meeting_id": line.meeting_id, "section": line.section, "group": line.group,
            "action_on": "item" if own else "section" if over is not None else "",
            "votes_read": bool(vote["votes_read"]) if vote else None,
            "number": line.number,
        })
    out = pd.DataFrame(rows, columns=ITEM_COLUMNS)
    out["votes_read"] = out["votes_read"].astype("boolean")
    return out.sort_values(["date", "meeting_id", "matter_id"], ascending=[False, False, True]).reset_index(drop=True)


def members_table(votes, meetings):
    """Everyone named in a block that was read. The district and the office are those printed at the head of the newest
    summary that lists them; the summaries give no terms of office."""
    seat, newest = {}, []
    for meeting in meetings[meetings["roll"] != ""].sort_values("date").itertuples(index=False):
        newest = json.loads(meeting.roll)
        for member in newest:
            seat[member["name"]] = member if member["district"] else {**member, "district": seat.get(member["name"], {}).get("district")}
    serving = {member["name"]: member["role"] for member in newest}
    cast = votes.groupby("member")["date"].agg(["min", "max", "size"]) if len(votes) else pd.DataFrame()
    rows = [{"name": name, "district": seat.get(name, {}).get("district"), "role": serving.get(name, ""), "start": "", "end": "",
             "serving": name in serving, "first_vote": cast.loc[name, "min"], "last_vote": cast.loc[name, "max"],
             "votes": int(cast.loc[name, "size"])} for name in sorted(cast.index)]
    out = pd.DataFrame(rows, columns=council_tables.COLUMNS["members"])
    out["district"] = out["district"].astype("Int64")
    out["serving"] = out["serving"].astype(bool)
    out["votes"] = out["votes"].astype(int)
    return out.sort_values(["first_vote", "name"]).reset_index(drop=True)


def joined(held, new):
    """Two tables of the same columns as one. An empty one adds nothing, and is left out so it cannot change a column's kind."""
    some = [table for table in (held, new) if len(table)]
    return pd.concat(some, ignore_index=True) if some else held


def typed(agenda, votes):
    for table, columns in ((agenda, ("sequence", "ayes", "noes", "not_voting", "motions", "vote_blocks", "blocks_read")), (votes, ("motion",))):
        for column in columns:
            table[column] = table[column].astype(int)
    agenda["heading"] = agenda["heading"].astype(bool)
    agenda["votes_read"] = agenda["votes_read"].astype("boolean")
    return agenda, votes


def build(base, everything, out_dir, since=FIRST_YEAR, limit=0, every=40):
    rows = listed()
    log.info(f"Sacramento County: {len(rows)} meetings listed")
    if len(rows) < 100:
        raise RuntimeError("the listing of meetings came back nearly empty")
    meetings = meetings_table(rows)

    agenda, votes, before_meetings = (council_tables.held(HF_REPO, out_dir, name, base) for name in ("agenda_items", "votes", "meetings"))
    before = 0 if votes is None else len(votes)
    if agenda is None or votes is None or before_meetings is None:
        agenda, votes = pd.DataFrame(columns=AGENDA_COLUMNS), pd.DataFrame(columns=VOTE_COLUMNS)
        before_meetings = pd.DataFrame(columns=MEETING_COLUMNS)
    found = {row["meeting_id"]: {name: row[name] for name in ("summary", "pages", "roll", "vote_blocks", "blocks_read")}
             for row in before_meetings[before_meetings["summary"] != ""].to_dict("records")}
    recent = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    wanted = [row for row in meetings.to_dict("records") if row["minutes_url"] and row["date"] >= f"{since}-01-01"
              and (everything or row["meeting_id"] not in found or row["date"] >= recent)]
    wanted.sort(key=lambda row: (row["date"], row["meeting_id"]), reverse=True)  # the newest first: a room shows those
    waiting = len(wanted)
    wanted = wanted[:limit] if limit else wanted
    log.info(f"Reading the summaries of {len(wanted)} meetings of {waiting} not yet read or to be read again")

    def fill():
        for name, empty in (("summary", ""), ("pages", 0), ("roll", ""), ("vote_blocks", 0), ("blocks_read", 0)):
            meetings[name] = [found.get(meeting_id, {}).get(name, empty) for meeting_id in meetings["meeting_id"]]
        count = agenda[~agenda["heading"].astype(bool)].groupby("meeting_id").size() if len(agenda) else {}
        meetings["items"] = meetings["meeting_id"].map(count).fillna(0).astype(int)

    read = 0
    for start in range(0, max(len(wanted), 1), every):
        some = wanted[start:start + every]
        new_agenda, new_votes, done = [], [], set()
        readings = county.together(lambda row: read_meeting(row, out_dir, fresh=not everything and row["date"] >= recent), some, "meeting")
        for row, reading in zip(some, readings):
            if reading is None:
                continue  # what is held for it stands, and the next run asks again
            done.add(row["meeting_id"])
            new_agenda.extend(reading[0])
            new_votes.extend(reading[1])
            found[row["meeting_id"]] = reading[2]
        agenda = joined(agenda[~agenda["meeting_id"].isin(done)], pd.DataFrame(new_agenda, columns=AGENDA_COLUMNS))
        votes = joined(votes[~votes["meeting_id"].isin(done)], pd.DataFrame(new_votes, columns=VOTE_COLUMNS))
        agenda = agenda.sort_values(["date", "meeting_id", "sequence"]).reset_index(drop=True)
        votes = votes.sort_values(["date", "meeting_id", "item_id", "motion", "member"]).reset_index(drop=True)
        agenda, votes = typed(agenda, votes)
        fill()
        council_tables.write_tables({"agenda_items": agenda, "votes": votes, "meetings": meetings}, out_dir)
        read += len(done)
        log.info(f"Sacramento County: {min(start + every, len(wanted))} of {len(wanted)} summaries asked for, {len(votes)} votes held")
        if _refused.is_set():
            log.error("The host refused a request: no more is asked of it in this run")
            break

    fill()
    tables = council_tables.standard({
        "items": items_table(agenda, meetings), "meetings": meetings, "agenda_items": agenda, "votes": votes,
        "members": members_table(votes, meetings),
    })
    council_tables.write_tables(tables, out_dir)
    if len(votes) < before * 0.98:
        raise RuntimeError(f"only {len(votes)} votes where there were {before}; not publishing")
    return tables, read


def card(tables):
    """The dataset card, with the counts of this reading written in."""
    meetings, agenda, votes = tables["meetings"], tables["agenda_items"], tables["votes"]
    read = meetings[meetings["summary"] == "read"]
    blocks, clean_blocks = int(agenda["vote_blocks"].sum()), int(agenda["blocks_read"].sum())
    facts = {
        "repo": HF_REPO, "first_meeting": read["date"].min() if len(read) else "", "last_meeting": read["date"].max() if len(read) else "",
        "first_vote": votes["date"].min() if len(votes) else "", "last_vote": votes["date"].max() if len(votes) else "",
        "n_read": f"{len(read):,}", "n_scans": f"{int((meetings['summary'] == 'no text layer').sum()):,}",
        "n_blocks": f"{blocks:,}", "n_blocks_read": f"{clean_blocks:,}", "n_unread": f"{blocks - clean_blocks:,}",
        "share_read": f"{100 * clean_blocks / blocks:.1f}" if blocks else "0", "recent_days": RECENT_DAYS,
        **{f"n_{name}": f"{len(tables[name]):,}" for name in TABLES},
    }
    text = CARD_FILE.read_text(encoding="utf-8")
    for fact, value in facts.items():
        text = text.replace("{" + fact + "}", str(value))
    return text


def upload(tables, out_dir, with_card):
    try:
        council_tables.publish(HF_REPO, out_dir, card(tables) if CARD_FILE.exists() else "", with_card, f"Update the tables ({today()})")
    except PermissionError as e:
        log.error(f"Sacramento County tables not uploaded: {e}")
        return False
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the Sacramento County Board's meetings, agendas and votes")
    parser.add_argument("--base", action="store_true", help="start from the tables written here, not the published ones")
    parser.add_argument("--all", action="store_true", help="read every summary again")
    parser.add_argument("--since", type=int, default=FIRST_YEAR, help="read no meeting before this year")
    parser.add_argument("--max", type=int, default=0, help="summaries to read in one run (0 for all)")
    parser.add_argument("--out", default="", help="directory to write the tables into (minutes_pdf/sacramento-county if not given)")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the tables only")

    out_dir = Path(args.out) if args.out else OUT_DIR
    try:
        tables, read = build(args.base, args.all, out_dir, args.since, args.max)
    except Exception as e:
        log.error(f"Sacramento County tables not built: {type(e).__name__}: {e}")
        return 1
    pushed = False if args.no_upload else upload(tables, out_dir, args.write_card)
    meetings, agenda, votes, members = tables["meetings"], tables["agenda_items"], tables["votes"], tables["members"]
    blocks, clean_blocks = int(agenda["vote_blocks"].sum()), int(agenda["blocks_read"].sum())
    log.info(f"RESULT: sacramento-county items={len(tables['items'])} meetings={len(meetings)} "
             f"meetings_with_summary={int((meetings['minutes_url'] != '').sum())} "
             f"summaries_read={int((meetings['summary'] == 'read').sum())} "
             f"no_text_layer={int((meetings['summary'] == 'no text layer').sum())} agenda_items={len(agenda)} "
             f"votes={len(votes)} vote_blocks={blocks} blocks_read={clean_blocks} blocks_unread={blocks - clean_blocks} "
             f"members={len(members)} serving={int(members['serving'].sum())} meetings_read={read} "
             f"first_vote={votes['date'].min() if len(votes) else ''} last_vote={votes['date'].max() if len(votes) else ''} "
             f"refused={_refused.is_set()} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
