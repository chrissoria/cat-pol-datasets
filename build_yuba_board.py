#!/usr/bin/env python3
"""
Build chrissoria/yuba-county-board: the meetings of the Yuba County Board of
Supervisors, what was on each agenda, what the Board did with it, and how each
supervisor voted.

One source: the County's agenda portal (agendasuite.org/iip/yuba, a Provox
system). Its calendar answers with every meeting since 2017 in one request.
Each meeting has a page that links the agenda, the minutes ("Private minutes"
on the page: the Clerk's Summary of Proceedings) and the agenda packet as PDFs,
and lists the agenda's items, each with its file number (473/2026) and the
portal's own number for the item. The portal has pages of votes for a few
motions of 2017 to 2019 and none after, so the votes here are all read from the
minutes' text.

The minutes print a motion as a block under the item it was made on:

    MOTION: Move to approve
    MOVED: Randy Fletcher SECOND: Gary Bradford
    AYES: Don Blaser, Gary Bradford, Randy Fletcher
    NOES: Andy Vasquez, Seth Fuhrer
    ABSENT: None
    ABSTAIN: None

The last three lines are also printed as one ("NOES: None ABSTAIN: None
ABSENT: Andy Vasquez") or folded into one ("NOES/ABSENT/ABSTAIN: None"), and
in the autumn of 2017 the first says "YES:". Some minutes of July 2017 to March
2018 have a grid in its place, a line to a supervisor with an X under YES, NO,
ABSTAIN or ABSENT; a grid with no X in it is the form left empty under an item
that had no motion of its own, and is not a vote. Nor is a motion that "died
for lack of a second".

Every supervisor is named in every motion, so nothing is worked out: a vote
row says what the minutes print beside that name (`established` is always
"named"). What is checked is that the names are the Board. Each set of minutes
has a line "ROLL CALL - Supervisors Vasquez, House, Fuhrer, Bradford, Messick"
(some list those who came and then say who was absent; both are the roll), and
a motion is read only if the names in it are exactly those, each once. One
that is not (a name short, a name twice, a name not on the roll, names under
"NOES/ABSENT/ABSTAIN" together, no AYES line at all) puts nothing in `votes`:
its line stays in agenda_items with `votes_read` false and what stopped it in
`problem`.

The consent agenda is passed by one motion, printed under the heading. That
vote is on the heading's own line (`heading` true), and the items listed under
it point to it. An item taken off the consent agenda is printed again further
down with a motion of its own. Now and then the minutes add a sentence under
the consent motion, "Supervisor Fuhrer voted No on item 289-2022": that item
then has a vote of its own here, the consent agenda's with that supervisor's
NO. If such a sentence cannot be tied to an item and a supervisor, the consent
motion is not read.

The dataset has the five tables every council's and board's dataset has
(council_tables.py), in data/:
  items.parquet          every item in minutes that were read
  meetings.parquet       one row per meeting the portal lists
  agenda_items.parquet   one row per item on a meeting's agenda, and one per heading voted on, with what was done
  votes.parquet          one row per supervisor and motion read
  members.parquet        one row per supervisor with votes here
They are kept here in minutes_pdf/yuba-county/. Beside them in text/ are the
text of each set of minutes (<meeting>.txt) and what the meeting's page lists
(<meeting>.json), so a PDF and a page are fetched once.

Two ways to run it:

    python build_yuba_board.py
        The routine run. Starts from the published tables, lists every meeting
        again, and fetches the meetings not read before and those of the last
        90 days and to come (minutes are posted after the meeting).

    python build_yuba_board.py --base
        The same, starting from the tables written here. It fetches the newest
        meeting first and can be stopped and started again. Meetings whose page
        is kept here are read again on every run; that takes no request.

    --since YEAR  read no meeting before this year (default 2017, where the portal begins)
    --max N       meetings to fetch in one run (default 0, for all)
    --all         fetch every meeting not kept here whole, read before or not
    --out DIR     where to write the tables
    --no-upload   write the tables but do not publish them
    --write-card  publish the dataset card as well as the tables

Needs pdfplumber. Only a PDF's own text is read: minutes that are a scan are
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
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

import build_federal_bills as bills
import build_sd_county as county
import council_tables
from build_sd_county import clean, today

log = logging.getLogger(__name__)

HF_REPO = "chrissoria/yuba-county-board"
OUT_DIR = bills.SCRIPT_DIR / "minutes_pdf" / "yuba-county"
CARD_FILE = bills.SCRIPT_DIR / "README_yuba_board.md"
TABLES = council_tables.TABLES
BODY = "Board of Supervisors"

PORTAL = "https://agendasuite.org/iip/yuba"
FIRST_YEAR = 2017  # the portal's first meeting is of January 2017, and its first minutes of July
RECENT_DAYS = 90  # meetings this recent, and those to come, are fetched again
SERVING_DAYS = 120  # a supervisor whose last vote is this recent is serving
PAUSE = 0.7  # seconds after each request
LAYER_CHARS = 200  # minutes with fewer characters of their own than this are a scan
SET_IN = 2  # a line this many columns in from the margin is not a heading or an item's first line

MEETING_COLUMNS = council_tables.COLUMNS["meetings"] + [
    "name", "note", "packet_url", "page", "minutes", "pages", "present", "roll", "motions", "motions_read"]
AGENDA_COLUMNS = council_tables.COLUMNS["agenda_items"] + [
    "heading", "section", "section_id", "motions", "motions_read", "votes_read", "problem", "doc_type", "subject", "number",
    "in_minutes", "document_url", "motion_log"]
VOTE_COLUMNS = council_tables.COLUMNS["votes"] + ["motion", "motion_text", "established"]
ITEM_COLUMNS = council_tables.COLUMNS["items"] + ["item_id", "meeting_id", "section", "action_on", "votes_read", "number"]

NAMED = "named"  # how every vote here is known: the minutes print the supervisor's name under the word

# The minutes' words over a list of names, and the word the tables have for each.
# ABTAIN, ABSNET and ASBENT are the minutes' own slips for ABSTAIN and ABSENT.
WORDS = {"AYES": council_tables.AYE, "AYE": council_tables.AYE, "YES": council_tables.AYE, "YEAS": council_tables.AYE,
         "NOES": council_tables.NO, "NOE": council_tables.NO, "NO": council_tables.NO, "NAYS": council_tables.NO,
         "ABSENT": "ABSENT", "ABSNET": "ABSENT", "ASBENT": "ABSENT", "ABSTAIN": "ABSTAIN", "ABTAIN": "ABSTAIN", "ABSTAINED": "ABSTAIN",
         "RECUSED": "RECUSED", "RECUSE": "RECUSED"}
NOBODY = ("", "none", "n/a", "na", "0", "-")

_WORD = r"(?:AYES?|YES|YEAS|NOES?|NO|NAYS|ABSENT|ABSNET|ASBENT|ABSTAIN(?:ED)?|ABTAIN|RECUSED?)"
_SAID = re.compile(rf"\b({_WORD}(?:\s*/\s*{_WORD})*)\s*:", re.I)  # "Absent:" is printed too
_SAID_LINE = re.compile(rf"^{_WORD}(?:\s*/\s*{_WORD})*\s*:", re.I)
_MOTION = re.compile(r"^M(?:OTION|otion)\s*:\s*(.*)$")
# "MOVED: Andy Vasquez SECOND: Gary Bradford"; also printed "MOVE:", "MOVED" with no colon, and "MOTION:" for "MOVED:".
_MOVED = re.compile(r"^(?:MOVED?\b\s*:?|MOTION\s*:(?=\s*[A-Z][a-z]+,?\s[A-Z][a-z]+\s+SECOND))\s*(.*?)\s*SECOND(?:ED)?(?:\s+BY)?\s*:\s*(.*)$")
_NO_SECOND = re.compile(r"\b(?:died|failed|fails|dies)\s+(?:for|due\s+to)\s+(?:a\s+)?lack\s+of\s+(?:a\s+)?second\b|\bno\s+second\b", re.I)
_GRID = re.compile(r"^YES\s+NO\s+ABSTAIN\s+ABSENT$")
_NAME_WORD = re.compile(r"[A-Z][a-z][A-Za-z’'.-]*")
# A file number that opens a line, with a title after it: not "471/2026, 495/2026 and 470/2026 to County Departments".
# It is printed "234-2020" now and then, and a few times with a digit of the year lost ("516/201"); "2019-2020" is a year.
_ITEM = re.compile(r"^(?!(?:19|20)\d\d\s?[-/])(\d{1,4})\s?(?:/\s?(\d{3,4})|-\s?(\d{4}))(?=\s+[^a-z\s]|\s*$)\s*(.*)$")
_HEADING = re.compile(r"^([A-Z][A-Z’'&/,.]*(?:\s+(?:[A-Z][A-Z’'&/,.]*|&))*)(?=$|\s*[–—:-]|\s+[a-z(]|\s+[A-Z][a-z])")
_TWO_COLUMNS = re.compile(r"\S\s{8,}\S")  # the head of the first page: "BOARD OF SUPERVISORS" with a notice set beside it
_FOOT = re.compile(r"^Page\s+\d+\s+of\s+\d+$", re.I)
_NO_LETTER = re.compile(r"\(cid:\d+\)")  # what the PDF reader writes for a character with no letter: a line's end, as a rule
_ROLL = re.compile(r"^ROLL\s+CALL\b\s*[–—:-]*\s*(?:Supervisors?\b:?\s*)?(.*)$", re.I)
_SURNAME = re.compile(r"[A-Z][A-Za-z’']+(?:[ -][A-Z][A-Za-z’']+)?")
_NUMBER = re.compile(r"\b(Resolution|Ordinance)\s+(?:Nos?\.?(?:[’']s)?|Numbers?|#)?\s*((?:\d[\w-]*\d|\d)(?:\s*(?:,|,?\s*and|&)\s*\d[\w-]*\d)*)", re.I)
_PERSON = r"[A-Z][A-Za-z’'-]+(?:\s[A-Z][A-Za-z’'-]+)?"
_FILE = r"\d{1,4}\s?[-/]\s?\d{4}"
# "Supervisor Fuhrer voted No on item 289-2022", under the motion that passed the consent agenda.
# and in other words: "Chair Fuhrer voted No on agenda item 500/2026", "Renick House abstained on agenda item 259/2025".
_ASIDE = re.compile(rf"(?:(?:Supervisors?|Vice[- ]Chair(?:man)?|Chair(?:man)?)\s+)?(?P<who>{_PERSON})\s+"
                    rf"(?P<did>(?i:voted\s+(?:no|nay|against|abstain|to\s+abstain)|opposed|abstained|recused\s+(?:him|her|them)self))\b[^.;:]{{0,40}}?"
                    rf"\b(?i:(?:agenda\s+)?items?)\s*:?\s*(?i:Nos?\.?|#|numbers?)?\s*(?P<files>{_FILE}(?:\s*(?:,|,?\s*and|&)\s*{_FILE})*)")
_OF_A_VOTE = re.compile(r"\b(?:voted|voting|abstain\w*|recus\w*|opposed|opposing|dissent\w*)\b", re.I)
# How the minutes say after a motion that it carried: "Motion Carried", "Approved", "Adopted Resolution No. 2026-80 via
# unanimous Vote", "Denied via Roll Call Vote" (of a motion to deny).
_CARRIED = re.compile(r"\bMotion\s+(?:Carried|Passed)\b|^(?:Approved|Adopted)\b"
                      r"|\b(?:via|by)\s+(?:an?\s+)?(?:unanimous\s+|majority\s+)?(?:roll\s+call\s+)?vote\b", re.I)
_FAILED = re.compile(r"\bMotion\s+Failed\b|\bmotion\b[^.;]{0,60}\bfail(?:ed|s)\b|\bFailed\b[^.;]{0,60}\b(?:via|by)\b[^.;]{0,30}\bVote\b", re.I)
# What the minutes put after a consent item that the consent motion did not pass.
_TAKEN_OFF = re.compile(r"^(?:Moved\s+to|Pulled|Removed|Continued|Withdrawn|Tabled|Item\s+(?:was\s+)?(?:pulled|removed|continued|withdrawn))\b", re.I)
# The words an item's action opens with, where the page has no title to tell where the title ends.
_DONE = re.compile(r"(?<=[.)])\s+(?=(?:Approved|Adopted|Accepted|Received|Denied|Continued|Pulled|Removed|Moved\s+to|Waived|Withdrawn|Tabled"
                   r"|No\s+action|Presented|Recognized|Appointed|Reappointed|Authorized|Held)\b)")


class Refused(Exception):
    """The host answered with a check, a login or a refusal. It is not asked again in this run."""


_refused = threading.Event()
_session = requests.Session()
_CHECK = re.compile(r"captcha|cf-challenge|are you a human|access denied|sign in to continue", re.I)


def fetch(url, tries=3):
    """One answer from the portal, with a pause after it. A refusal is not tried again, and nothing more is asked of the
    host in this run."""
    if _refused.is_set():
        raise Refused("the host refused an earlier request")
    for attempt in range(tries):
        try:
            answer = _session.get(url, headers=county.HEADERS, timeout=(20, 180))
            time.sleep(PAUSE)
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
            time.sleep(3 * (attempt + 1))


# ---------------------------------------------------------------------------
# The listing
# ---------------------------------------------------------------------------

def clock(hour):
    """An hour as every board's table has it: "9:00 AM"."""
    found = re.search(r"(\d{1,2}:\d{2})\s*([AaPp])\.?\s*[Mm]\.?", clean(hour))
    return f"{found[1]} {found[2].upper()}M" if found else ""


def rows_of(events):
    """The meetings in the calendar's answer, as the portal has them. A meeting is known by the portal's number for it.

    An event's description ends "Meeting: BOS - 18/2026 / by: Board of Supervisors / Begin: 9:00 AM / Room: Board
    Chambers". What stands before that is a note the Clerk put on the meeting ("Special Meeting", or how to join it).
    """
    rows = {}
    for event in events:
        said = str(event.get("description") or "")
        tail = list(re.finditer(r"(?:^|\n)Meeting:", said))
        note, rest = (said[:tail[-1].start()], said[tail[-1].end():]) if tail else (said, "")
        of = lambda label: clean((re.search(rf"^{label}:\s*(.*)$", rest, re.M) or ["", ""])[1])
        day = str(event.get("start") or "")[:10]
        if not re.fullmatch(r"\d{4}-\d\d-\d\d", day) or event.get("id") is None:
            continue
        cancelled = "❌" in str(event.get("title") or "")
        rows[str(event["id"])] = {
            "meeting_id": str(event["id"]), "date": day, "time": clock(of("Begin")), "location": of("Room"),
            "name": clean(rest.split("\n")[0]) if rest else "",
            "note": clean(("Cancelled. " if cancelled else "") + note.replace("🔔", " ").replace("❌", " ")),
        }
    return list(rows.values())


def listed(first=FIRST_YEAR, last=None):
    """Every meeting the portal's calendar has from `first` on, to the end of next year: one request."""
    last = last or datetime.now(timezone.utc).year + 1
    answer = fetch(f"{PORTAL}/meeting/ShowEvents?start={first}-01-01T00:00:00-08:00&end={last}-12-31T00:00:00-08:00")
    return rows_of(json.loads(answer.text))


def meeting_url(meeting_id):
    return f"{PORTAL}/meeting/details/{meeting_id}"


def meetings_table(rows):
    """One row per meeting listed. What its page and its minutes add is filled in by build()."""
    out = [{
        "meeting_id": row["meeting_id"], "date": row["date"], "time": row["time"], "body": BODY, "location": row["location"],
        "url": meeting_url(row["meeting_id"]), "agenda_url": "", "minutes_url": "", "items": 0,
        "name": row["name"], "note": row["note"], "packet_url": "",
        "page": "", "minutes": "", "pages": 0, "present": "", "roll": "", "motions": 0, "motions_read": 0,
    } for row in rows]
    return pd.DataFrame(out, columns=MEETING_COLUMNS).sort_values(["date", "meeting_id"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# A meeting's page
# ---------------------------------------------------------------------------

_FILES = re.compile(r"Meeting files:(.*?)</div>", re.S)
_FILE_LINK = re.compile(r'<a\b[^>]*aria-label="([^"]+)"[^>]*href="([^"]+)"', re.S)
_TOPIC = re.compile(r'<div class="topic">')
_TOPIC_NAME = re.compile(r"<strong>(.*?)</strong>", re.S)
_LINE = re.compile(r'<div class="meetingitem\b')
_LINE_NUMBER = re.compile(r'class="agendanumber">(.*?)</div>', re.S)
_LINE_TITLE = re.compile(r'<div style="width:70%;[^"]*">(.*?)</div>', re.S)
_LINE_ITEM = re.compile(r"agendaitem/details/(\d+)")
_LINE_FILE = re.compile(r'id="agendaitemnumber"[^>]*>\s*([^<]*?)\s*<', re.S)
_LINE_DOCUMENT = re.compile(r'aria-label="Agenda item document"[^>]*href="([^"]+)"', re.S)
_PARTICIPANTS = re.compile(r'<div class="participants\b(.*?)</table>', re.S)
_PARTICIPANT = re.compile(r"<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>", re.S)


def plain(markup):
    """A piece of a page as its words."""
    return clean(html.unescape(re.sub(r"<[^>]+>", " ", markup)))


def file_number(text):
    """A file number as the tables have it, "473/2026", from "473/2026" or the minutes' "289-2022"; "" if it is not one."""
    found = re.fullmatch(r"(\d{1,4})\s?[-/]\s?(\d{4})", clean(text))
    return f"{int(found[1])}/{found[2]}" if found else ""


def page_of(markup):
    """What a meeting's page says: the documents it links, who it lists as the Board, and the agenda's lines.

    The agenda is a run of topics (CONSENT AGENDA, COUNTY DEPARTMENTS), each with its lines. A line has its place on
    the agenda, its words, and for an item the file number and the portal's number for the item. A line with no file
    number is a note under the topic ("All matters listed under Consent Agenda are considered to be routine ...").
    """
    if "Id not found" in markup[:20000] and "Meeting files:" not in markup:
        return {"found": False, "files": {}, "participants": [], "lines": []}
    absolute = lambda link: link if link.startswith("http") else "https://agendasuite.org" + link
    files = {}
    for label, link in _FILE_LINK.findall((_FILES.search(markup) or ["", ""])[1]):
        kind = "packet" if "package" in label.lower() else "minutes" if "minutes" in label.lower() else "agenda" if "agenda" in label.lower() else ""
        if kind and "/file/getfile/" in link:
            files.setdefault(kind, absolute(html.unescape(link)))
    participants = [{"name": plain(name), "role": plain(role)}
                    for name, role in _PARTICIPANT.findall((_PARTICIPANTS.search(markup) or ["", ""])[1])]
    start, end = markup.find('id="agenda"'), markup.find('id="minutes"')
    agenda = markup[start:end if end > start else len(markup)] if start >= 0 else markup[end:] if end >= 0 else ""
    lines = []
    for topic in _TOPIC.split(agenda)[1:]:
        name = plain((_TOPIC_NAME.search(topic) or ["", ""])[1])
        for part in _LINE.split(topic)[1:]:
            of = lambda pattern: (pattern.search(part) or ["", ""])[1]
            document = of(_LINE_DOCUMENT)
            lines.append({"section": name, "number": plain(of(_LINE_NUMBER)), "title": plain(of(_LINE_TITLE)),
                          "file": file_number(plain(of(_LINE_FILE))), "item": of(_LINE_ITEM),
                          "document": absolute(html.unescape(document)) if document else ""})
    return {"found": True, "files": files, "participants": participants, "lines": lines}


def kept_page(meeting_id, out_dir):
    path = Path(out_dir) / "text" / f"{meeting_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def keep_page(meeting_id, page, out_dir):
    path = Path(out_dir) / "text" / f"{meeting_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(page, ensure_ascii=False, indent=1), encoding="utf-8")


def text_path(meeting_id, out_dir):
    return Path(out_dir) / "text" / f"{meeting_id}.txt"


def whole(meeting_id, out_dir):
    """Whether a meeting is kept here whole: its page, and the text of its minutes if the page links any."""
    page = kept_page(meeting_id, out_dir)
    return page is not None and (not page["files"].get("minutes") or
                                 (page.get("text_of") == page["files"]["minutes"] and text_path(meeting_id, out_dir).exists()))


# ---------------------------------------------------------------------------
# The text of a set of minutes
# ---------------------------------------------------------------------------

def pdf_text(body):
    """The text a PDF carries, a page at a time, set out as on the page: a line begins as far in as it stands there,
    and an X in a grid stands under its column. Nothing is read off the picture of a page."""
    import pdfplumber
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    with pdfplumber.open(io.BytesIO(body)) as document:
        pages = [page.extract_text(layout=True) or "" for page in document.pages]
    return ["\n".join(_NO_LETTER.sub("", line).rstrip() for line in page.split("\n")) for page in pages]


def fetch_meeting(meeting, out_dir, fresh=False):
    """A meeting's page and the text of its minutes, fetched and kept: a request for each, and none for what is here.

    The minutes are fetched again only if the page now links another file than the one whose text is kept.
    """
    meeting_id = meeting["meeting_id"]
    page = None if fresh else kept_page(meeting_id, out_dir)
    if page is None:
        before = kept_page(meeting_id, out_dir) or {}
        page = page_of(fetch(meeting_url(meeting_id)).text)
        page["text_of"] = before.get("text_of", "")
        keep_page(meeting_id, page, out_dir)
    minutes = page["files"].get("minutes", "")
    if minutes and not (page.get("text_of") == minutes and text_path(meeting_id, out_dir).exists()):
        body = fetch(minutes).content
        text = "\n\f".join(pdf_text(body)) if body[:4] == b"%PDF" else ""
        text_path(meeting_id, out_dir).write_text(text, encoding="utf-8")
        page["text_of"] = minutes
        keep_page(meeting_id, page, out_dir)
    return page


def lines_of(text):
    """The minutes' lines in order, each with how far in it begins, the line as it stands on the page (`raw`), whether
    a gap stands above it, and whether it is the first of its page (where a gap cannot be seen). "Page 3 of 9" at the
    foot of a page is left out."""
    out = []
    for page in text.split("\f"):
        gap, top = False, True
        for raw in page.split("\n"):
            raw = _NO_LETTER.sub("", raw)
            if not raw.strip():
                gap = True
                continue
            if _FOOT.match(raw.strip()):
                continue
            out.append({"indent": len(raw) - len(raw.lstrip(" ")), "raw": raw.rstrip(), "text": clean(raw), "gap": gap and not top, "top": top})
            gap, top = False, False
    return out


# ---------------------------------------------------------------------------
# Who a name is
# ---------------------------------------------------------------------------

def key_of(name):
    """What two printings of a name share: its letters."""
    return re.sub(r"[^a-z]", "", str(name or "").lower())


def near(one, other):
    """Whether two words are one slip apart: a letter more, a letter less, a letter changed, or two letters swapped."""
    if one == other or abs(len(one) - len(other)) > 1:
        return False
    if len(one) == len(other):
        apart = [at for at, (a, b) in enumerate(zip(one, other)) if a != b]
        return len(apart) == 1 or (len(apart) == 2 and apart[1] == apart[0] + 1 and one[apart[0]] == other[apart[1]] and one[apart[1]] == other[apart[0]])
    short, long = sorted((one, other), key=len)
    return any(long[:at] + long[at + 1:] == short for at in range(len(long)))


def names_in(text):
    """The names in "Andy Vasquez, Renick House, Seth Fuhrer", as printed; none for "None".

    The minutes now and then part two names with a full stop ("Don Blaser. Seth Fuhrer").
    """
    text = clean(text).strip(" .;,")
    if text.lower() in NOBODY:
        return []
    parts = re.split(r"\s*[,;]\s*(?:and\s+)?|\s+and\s+|\.\s+(?=[A-Z])", text)
    return [re.sub(r"^Supervisors?\s+", "", clean(part)).strip(" .") for part in parts if clean(part).strip(" .")]


def who(name, roll):
    """The supervisor on the roll that a printed name is, or None.

    The roll gives surnames; a name in a vote is "Andy Vasquez", and a mover in the minutes of 2017 "Vasquez, Andy".
    A surname one letter out ("Messsick") is that supervisor if no other on the roll is as near.
    """
    name = clean(name).strip(" .")
    if not name:
        return None
    keys = {key_of(member): member for member in roll}
    words = name.split(",")[0].split() if "," in name else name.split()
    ends = [" ".join(words[at:]) for at in range(len(words) - 1, -1, -1)] if "," not in name else [" ".join(words)]
    for end in ends:  # the surname is the name's last word, or its last words
        if key_of(end) in keys:
            return keys[key_of(end)]
    last = key_of(words[-1]) if words else ""
    found = [member for key, member in keys.items() if len(key) >= 5 and near(last, key)]
    return found[0] if len(found) == 1 else None


def roll_of(text):
    """(the surnames on a "ROLL CALL - Supervisors Vasquez, House, Fuhrer, Bradford, Messick – all present" line, the
    line as printed). No names if the line does not list them.

    Some minutes list only those who came and name the rest after: "Supervisors Vasquez, Blaser, Messick – Supervisors
    Fuhrer and Bradford were absent". Those named absent are on the Board, and so on the roll.
    """
    said = clean(text)
    found = _ROLL.match(said)
    if not found:
        return [], said
    listed_, _, rest = (re.split(r"(\s+[–—-]\s*|[–—-]\s+|\s*[–—]\s*|\.\s|\s+\()", found[1], maxsplit=1) + ["", ""])[:3]
    names = [clean(part).strip(" .") for part in re.split(r"\s*[,;]\s*(?:and\s+)?|\s+and\s+", listed_) if clean(part).strip(" .")]
    if len(names) < 3 or not all(_SURNAME.fullmatch(name) for name in names) or len({key_of(name) for name in names}) != len(names):
        return [], said
    away = re.match(rf"\s*(?:Supervisors?\s+)?({_PERSON}(?:\s*(?:,\s*(?:and\s+)?|\s+and\s+)(?:Supervisors?\s+)?{_PERSON})*)\s+"
                    r"(?:(?:was|were|is|are)\s+)?(?i:absent)\b", rest)
    for name in names_in(away[1]) if away else []:
        if who(name, names) is None and _SURNAME.fullmatch(name.split()[-1]):
            names.append(name.split()[-1])
    return names, said


# ---------------------------------------------------------------------------
# Reading a set of minutes
# ---------------------------------------------------------------------------

def heading_of(words):
    """The heading a line opens with ("CONSENT AGENDA", "ROLL CALL"), or "". A heading is words in capitals at the
    margin; what follows a dash after them is said under it."""
    found = _HEADING.match(words)
    if not found:
        return ""
    name = clean(found[1]).rstrip(",.")
    first = name.split()[0].rstrip(":")
    if len(re.sub(r"[^A-Z]", "", name)) < 6 or first in WORDS or first in ("MOTION", "MOVED", "SECOND"):
        return ""
    return name


def margin_of(lines):
    """How far in the items' numbers and the headings stand: where most lines that open with a file number begin."""
    begun = Counter(line["indent"] for line in lines if _ITEM.match(line["text"]))
    if not begun:
        begun = Counter(line["indent"] for line in lines if heading_of(line["text"]))
    return begun.most_common(1)[0][0] if begun else 0


def grid_rows(lines, at):
    """The lines of a grid whose head is line `at`, as ([(the words of a name on the line, the word its X stands under
    or "")], the next line). A line of the grid begins where the first does and has a name, or part of one, and at most
    one X; "Motion Carried" under the grid stands further in.

    Which word an X stands under is a matter of where it is on the line: the word whose middle is nearest.
    """
    columns = [(found.group(), (found.start() + found.end()) / 2) for found in re.finditer(r"\S+", lines[at]["raw"])]
    rows, at, indent = [], at + 1, None
    while at < len(lines):
        parts = list(re.finditer(r"\S+", lines[at]["raw"]))
        marks = [part for part in parts if part.group() in ("X", "x")]
        name = [part.group() for part in parts if part.group() not in ("X", "x")]
        if (len(marks) > 1 or not 1 <= len(name) <= 3 or not all(_NAME_WORD.fullmatch(word) for word in name)
                or heading_of(lines[at]["text"]) or (indent is not None and abs(lines[at]["indent"] - indent) > 1)):
            break
        indent = lines[at]["indent"] if indent is None else indent
        word = min(columns, key=lambda column: abs(column[1] - (marks[0].start() + 0.5)))[0] if marks else ""
        rows.append((" ".join(name), word))
        at += 1
    return rows, at


def motion_at(lines, at, margin):
    """The motion that begins at line `at` ("MOTION: ..."), as (the motion, the next line); the motion is None for the
    form left empty under an item that had no motion.

    A motion is its words, who moved and seconded as printed, and the names under each word of the vote: `said` is
    [(the words over a list, the names in it)] for "AYES: ... NOES: ...", and for a grid [((the word,), [the name on
    that line])], with an empty word for a line with no X. A sentence in place of a name ("ABSTAIN: Renick House
    abstained on agenda item 259/2025") is not a name: it is kept with what is said after the motion.
    """
    words, mover, seconder, kind, said, after = [], "", "", "", [], ""
    if not _MOVED.match(lines[at]["text"]):  # now and then a motion is printed from "MOVED:" on, with no words of its own
        words.append(_MOTION.match(lines[at]["text"])[1])
        at += 1
    while at < len(lines):
        text = lines[at]["text"]
        if _MOVED.match(text) or _SAID_LINE.match(text) or _GRID.match(text) or _MOTION.match(text) or begins(lines[at], margin):
            break
        if _NO_SECOND.search(text):
            break  # "Motion failed for lack of a second" is said after the motion, not in it
        words.append(text)
        at += 1
    if at < len(lines) and _MOVED.match(lines[at]["text"]):
        mover, seconder = (clean(part) for part in _MOVED.match(lines[at]["text"]).groups())
        at += 1
    if at < len(lines) and _GRID.match(lines[at]["text"]):
        rows, at = grid_rows(lines, at)
        kind, said = "grid", [((word,), [name]) for name, word in rows]
    else:
        block = []
        while at < len(lines) and (_SAID_LINE.match(lines[at]["text"]) or (block and block[-1].endswith(","))):
            block.append(lines[at]["text"])
            at += 1
        if block:
            parts = _SAID.split(" ".join(block))
            kind = "names"
            for index in range(1, len(parts) - 1, 2):
                over, under = tuple(clean(word).upper() for word in parts[index].split("/")), clean(parts[index + 1])
                if _OF_A_VOTE.search(under):
                    after, under = clean(f"{after} {under}"), ""
                said.append((over, names_in(under)))
    text = clean(" ".join(words))
    inline = re.search(r"\s+MOVED?\b\s*:?\s*(.*?)\s*SECOND(?:ED)?\s*:\s*(.*)$", text) if not mover and not seconder else None
    if inline:  # "MOTION: Move to approve MOVE: Andy Vasquez SECOND: Seth Fuhrer", all on one line
        text, mover, seconder = clean(text[:inline.start()]), clean(inline[1]), clean(inline[2])
    if not text and not mover and not seconder and kind != "names" and not any(words_[0] for words_, _ in said):
        return None, at
    return {"text": text, "mover": mover, "seconder": seconder, "kind": kind, "said": said, "after": after}, at


def begins(line, margin):
    """Whether a line begins something of its own: an item (a file number at the margin) or a heading."""
    return line["indent"] <= margin + SET_IN and bool(_ITEM.match(line["text"]) or heading_of(line["text"]))


def decide(motion, roll):
    """Every supervisor's vote on a motion as ([(the supervisor as the roll has them, the name as printed, the vote)],
    ""), or (None, why it is not read). Read only if the names are the roll: everyone on it, each once, and no one else."""
    if not roll:
        return None, "no roll call that names the Board"
    if not motion["kind"]:
        return None, "no names: the motion has no AYES line"
    named = []
    if motion["kind"] == "grid":
        named, problem = grid_votes(motion["said"], roll)
        if problem:
            return None, problem
    for words, names in motion["said"] if motion["kind"] == "names" else []:
        if len(words) > 1 and names:
            return None, f"names under {'/'.join(words)} together"
        named.extend((name, WORDS[words[0]]) for name in names)
    if not named:
        return None, "no names: every list is empty"
    cast, seen = [], set()
    for name, word in named:
        member = who(name, roll)
        if member is None:
            return None, f"not on the roll: {name}"
        if member in seen:
            return None, f"named twice: {member}"
        seen.add(member)
        cast.append((member, name, word))
    missing = [member for member in roll if member not in seen]
    if missing:
        return None, f"names {len(seen)} of the {len(roll)} on the roll: no {', '.join(missing)}"
    return cast, ""


def grid_votes(said, roll):
    """The names of a grid with the word each one's X stands under, as ([(name, vote)], ""), or ([], why not).

    Where every line has a whole name, a line's X is that supervisor's. In the grids of late 2017 a long name runs on
    to a second line while the X's stand one to a line from the top, so the lines are one more than the names: there
    the first X is the first supervisor's, the second the second's. That is read only if the X's are as many as the
    names and fill the grid's first lines.
    """
    names, marks, name = [], [words[0] for words, _ in said], ""
    for _, part in said:
        name = clean(f"{name} {part[0]}")
        if who(name, roll) is not None:
            names.append(name)
            name = ""
        elif len(name.split()) > 2:
            return [], f"not on the roll: {name}"
    if name:
        return [], f"not on the roll: {name}"
    if len(names) == len(said):
        blank = [name for name, mark in zip(names, marks) if not mark]
        return ([], f"the grid has no X for {', '.join(blank)}") if blank else ([(name, WORDS[mark]) for name, mark in zip(names, marks)], "")
    if not all(marks[:len(names)]) or any(marks[len(names):]):
        return [], "the grid's X's cannot be told one supervisor's from another's"
    return [(name, WORDS[mark]) for name, mark in zip(names, marks)], ""


def scan(text):
    """A set of minutes as its roll and what stands under each heading, in order.

    An entry is a heading ("CONSENT AGENDA", with what is said under it before the first item) or an item (a file
    number at the margin, with all that follows to the next item or heading). Each has its motions, and each motion
    what is said after it up to the next motion. A motion under a heading before any item is the heading's: that is
    where the consent agenda's stands. Each motion is decided against the roll call that stands above it.
    """
    lines = lines_of(text)
    margin = margin_of(lines)
    entries, section, current, roll, present, rolls, at = [], None, None, [], "", 0, 0
    while at < len(lines):
        line = lines[at]
        if _MOTION.match(line["text"]) or _MOVED.match(line["text"]):
            motion, at = motion_at(lines, at, margin)
            target = current or section
            if motion is None:
                continue
            unvoted = not motion["kind"] or (motion["kind"] == "grid" and not any(words[0] for words, _ in motion["said"]))
            if unvoted and target is not None and _NO_SECOND.search(f"{motion['text']} {lines[at]['text'] if at < len(lines) else ''}"):
                # "Motion died for lack of a second": nothing was voted on. Its words are kept with what was said.
                said = "MOTION: " + clean(f"{motion['text']} {motion['mover']}")
                if target["motions"]:
                    target["motions"][-1]["after"] = (target["motions"][-1]["after"] + "\n" + said).strip()
                else:
                    target["text"] = (target["text"] + "\n" + said).strip()
                continue
            if target is None:  # a motion above every heading
                target = section = {"kind": "heading", "name": "", "text": "", "motions": []}
                entries.append(target)
            motion["roll"] = rolls
            target["motions"].append(motion)
            continue
        at += 1
        at_margin = line["indent"] <= margin + SET_IN
        item = _ITEM.match(line["text"]) if at_margin else None
        if item:
            current = {"kind": "item", "file": f"{int(item[1])}/{item[2] or item[3]}", "text": item[4], "motions": [],
                       "section": section["name"] if section else "", "under": section}
            entries.append(current)
            continue
        name = heading_of(line["text"]) if at_margin and not _TWO_COLUMNS.search(line["raw"].strip()) else ""
        if name:
            section = {"kind": "heading", "name": name, "text": line["text"][len(_HEADING.match(line["text"])[1]):].lstrip(" –—:-"), "motions": []}
            current = None
            entries.append(section)
            if name == "ROLL CALL":
                section["first"], section["open"] = line["text"], True
                rolls += 1
            continue
        target = current or section
        if target is None:
            continue  # the head of the minutes
        join = "\n" if line["gap"] else " "
        if target.get("open") and not line["gap"]:
            target["first"] += " " + line["text"]  # the roll call runs on to a second line
        elif target.get("open"):
            target["open"] = False
        if target["motions"]:
            target["motions"][-1]["after"] = (target["motions"][-1]["after"] + join + line["text"]).strip()
        else:
            target["text"] = (target["text"] + join + line["text"]).strip()
    # The roll in force at a motion is that of the last roll call above it; above the first, the first.
    called = [roll_of(entry["first"]) for entry in entries if entry["kind"] == "heading" and entry.get("first") is not None]
    for entry in entries:
        for motion in entry["motions"]:
            motion["on_roll"] = called[max(motion.pop("roll") - 1, 0)][0] if called else []
            motion["cast"], motion["problem"] = decide(motion, motion["on_roll"])
    if called:
        roll, present = called[0]
    asides(entries)
    return {"roll": roll, "present": present, "entries": entries}


def asides(entries):
    """What the minutes add in a sentence under a heading's motion: "Supervisor Fuhrer voted No on item 289-2022".

    The item named gets a motion of its own, the heading's with that supervisor's vote changed. Words of a vote that
    cannot be tied to an item under the heading and a supervisor on the roll leave the heading's motion unread: it
    then says something of the vote that is not known.
    """
    word_of = lambda did: "ABSTAIN" if "abstain" in did.lower() else "RECUSED" if "recus" in did.lower() else council_tables.NO
    for heading in entries:
        if heading["kind"] != "heading":
            continue
        under = {entry["file"]: entry for entry in entries if entry["kind"] == "item" and entry["under"] is heading}
        for motion in heading["motions"]:
            said = motion["after"]
            if motion["cast"] is None or not _OF_A_VOTE.search(said):
                continue
            tied, rest = [], said
            for found in _ASIDE.finditer(said):
                member = who(found["who"], motion["on_roll"])
                files = [file_number(file) for file in re.findall(_FILE, found["files"])]
                if member is None or not files or any(file not in under or under[file]["motions"] for file in files):
                    tied = None
                    break
                tied.extend((under[file], member, word_of(found["did"]), clean(found[0])) for file in files)
                rest = rest.replace(found[0], " ")
            if tied is None or not tied or _OF_A_VOTE.search(rest):
                motion["cast"], motion["problem"] = None, "words after the vote not tied to an item and a supervisor: " + clean(said)[:120]
                continue
            for item, member, word, sentence in tied:
                if not item.get("aside"):
                    item["aside"] = {"text": sentence, "mover": motion["mover"], "seconder": motion["seconder"], "kind": "aside",
                                     "said": [], "after": "", "on_roll": motion["on_roll"], "problem": "", "cast": list(motion["cast"])}
                elif sentence not in item["aside"]["text"]:
                    item["aside"]["text"] += " " + sentence
                item["aside"]["cast"] = [(name, printed, word if name == member else vote) for name, printed, vote in item["aside"]["cast"]]
    for entry in entries:
        if entry.get("aside"):
            entry["motions"].append(entry.pop("aside"))


def split_title(text, title=""):
    """An item's paragraph in the minutes as (its title, what is said after it).

    The minutes print the agenda's title and go straight on: "... and authorize Chair to execute. Approved". Where the
    page gives the title, the paragraph is parted where that title ends, letters and digits alone being compared; if
    the minutes have mended a word of it, where its last words end. Where the page gives none, or the minutes word the
    title differently, it is parted at the first sentence that opens with a word for something done; failing that,
    all of it is the title.
    """
    text = clean(text)
    want = "".join(char.lower() for char in title if char.isalnum())
    if want:
        letters = [index for index, char in enumerate(text) if char.isalnum()]
        printed = "".join(text[index].lower() for index in letters)
        end = len(want) if printed.startswith(want) else 0
        if not end and len(want) >= 40:
            at = printed.find(want[-24:], len(want) // 2)
            end = at + 24 if 0 <= at <= len(want) * 1.25 else 0
        if end:
            index = letters[end - 1] + 1
            closing = re.match(r"[.)\"”’'\s]*", text[index:])[0]
            return clean(text[:index] + closing), clean(text[index + len(closing):])
    found = _DONE.search(text)
    return (clean(text[:found.start()]), clean(text[found.end():])) if found else (text, "")


def section_name(topic):
    """A topic of the page as the minutes' headings are named: its opening words in capitals."""
    return heading_of(clean(topic)) or clean(topic)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def read_meeting(meeting, page, scanned, spelled=None, pages=0):
    """One meeting: its agenda's lines from the page, with what the minutes say was done with each and the votes on
    each motion read whole. `scanned` is None for a meeting with no minutes to read: its lines then have nothing done.

    A line is an item of the page, an item the minutes have and the page does not, or a heading with a motion of its
    own. An item printed twice in the minutes (under the consent agenda as taken off it, and again where it was voted
    on) is one line. The lines stand in the agenda's order; one the page does not have stands after the last of the
    agenda's lines that the minutes have reached before it.
    """
    meeting_id, date = meeting["meeting_id"], meeting["date"]
    spelled = spelled or {}
    name_of = lambda member: spelled.get(key_of(member), member)
    lines, by_file = [], {}
    for place, row in enumerate((page or {}).get("lines", [])):
        if not row["file"]:
            continue  # a note under a topic, not an item
        line = {"place": float(place), "heading": False, "file": row["file"], "item": row["item"], "number": row["number"],
                "title": row["title"], "section": section_name(row["section"]), "document": row["document"],
                "texts": [], "motions": [], "under": None, "found": False}
        lines.append(line)
        by_file.setdefault(row["file"], line)
    place, tick, of_heading = -1.0, 0, {}
    for entry in (scanned or {}).get("entries", []):
        if entry["kind"] == "item":
            if entry["file"] not in by_file and len(entry["file"].split("/")[1]) < 4:
                same = [file for file in by_file if file.split("/")[0] == entry["file"].split("/")[0]]
                entry["file"] = same[0] if len(same) == 1 else entry["file"]  # "524/219" is the page's 524/2019
            line = by_file.get(entry["file"])
            if line is None:
                tick += 1
                line = {"place": place + tick * 1e-4, "heading": False, "file": entry["file"], "item": "", "number": "", "title": "",
                        "section": entry["section"], "document": "", "texts": [], "motions": [], "under": None, "found": False}
                lines.append(line)
                by_file[entry["file"]] = line
            elif line["place"] > place:
                place, tick = line["place"], 0  # the furthest the minutes have come down the agenda
            line["found"] = True
            line["texts"].append(entry["text"])
            line["motions"].extend(entry["motions"])
            # The agenda's own topic is kept for an item of the page: the minutes print a hearing held after the
            # closed session under CLOSED SESSION.
            line["section"], line["under"] = line["section"] or entry["section"], entry["under"]
        elif entry["motions"]:
            tick += 1
            # A motion above every heading has no heading to be named by: its own words are its title.
            line = {"place": place + tick * 1e-4, "heading": True, "file": "", "item": "", "number": "",
                    "title": entry["name"] or entry["motions"][0]["text"], "name": entry["name"],
                    "section": entry["name"], "document": "", "texts": [entry["text"]], "motions": entry["motions"], "under": None,
                    "found": True}
            lines.append(line)
            of_heading[id(entry)] = line
    lines.sort(key=lambda line: line["place"])

    used = set()
    for line in lines:
        if line["heading"]:
            base = f"{meeting_id}-{'consent' if 'CONSENT' in line['name'] else slug(line['name']) or 'motion'}"
        else:
            base = f"{meeting_id}-{line['file'].replace('/', '-')}"
        item_id, again = base, 1
        while item_id in used:  # a file number the page lists twice, or a heading printed twice
            again += 1
            item_id = f"{base}-{again}"
        used.add(item_id)
        line["item_id"] = item_id

    agenda, votes, roll = [], [], (scanned or {}).get("roll", [])
    roles = {key_of(member): person["role"] for person in (page or {}).get("participants", [])
             for member in [who(person["name"], roll)] if member and person["role"] not in ("", "Supervisors", "Supervisor")}
    facts = {"page": "read" if page and page.get("found") else "not found" if page else "",
             "agenda_url": (page or {}).get("files", {}).get("agenda", ""), "minutes_url": (page or {}).get("files", {}).get("minutes", ""),
             "packet_url": (page or {}).get("files", {}).get("packet", ""),
             "minutes": "read" if scanned else "", "pages": pages, "present": (scanned or {}).get("present", ""),
             "roll": json.dumps([{"name": name_of(member), "role": roles.get(key_of(member), "")} for member in roll],
                                ensure_ascii=False, separators=(",", ":")) if roll else "",
             "motions": 0, "motions_read": 0}
    for sequence, line in enumerate(lines, 1):
        item_id, heading = line["item_id"], line["heading"]
        matter_id = "" if heading else line["item"] or line["file"]
        # What the minutes say after the title, each time they print the item, and after each motion.
        said, title = [], line["title"]
        for text in line["texts"]:
            if heading:
                said.append(clean(text))
                continue
            printed, rest = split_title(text, line["title"])
            title = title or printed
            said.append(rest)
        motions = line["motions"]
        for number, motion in enumerate(motions, 1):
            said.append(clean(motion["after"]))
            motion["read"] = motion["cast"] is not None
            motion["moved"] = name_of(who(motion["mover"], motion["on_roll"]) or "") or motion["mover"]
            motion["seconded"] = name_of(who(motion["seconder"], motion["on_roll"]) or "") or motion["seconder"]
            for member, _, word in motion["cast"] or []:
                votes.append({"item_id": item_id, "meeting_id": meeting_id, "date": date, "matter_id": matter_id,
                              "matter_file": line["file"], "member": name_of(member), "vote": word, "motion": number,
                              "motion_text": motion["text"], "established": NAMED})
        action = clean(" ".join(part for part in said if part))
        last = motions[-1] if motions else None
        cast = [word for _, _, word in last["cast"] or []] if last else []
        outcome = clean(last["after"])[:300] if last else ""  # how the vote went, where the minutes say: it stands first after the motion
        numbered = _NUMBER.search(outcome) or _NUMBER.search(action)
        under = of_heading.get(id(line["under"])) if line["under"] is not None else None
        # An item is passed by the consent agenda's motion if it stands under it with no motion of its own and the
        # minutes do not say it was taken off.
        with_section = bool(under and "CONSENT" in under["name"] and not motions and not _TAKEN_OFF.match(action))
        agenda.append({
            "item_id": item_id, "meeting_id": meeting_id, "date": date, "body": BODY,
            "agenda_number": line["number"], "sequence": sequence, "matter_id": matter_id, "matter_file": line["file"],
            "title": clean(title), "action": action,
            "result": "" if not last else "Fail" if _FAILED.search(outcome) else "Pass" if _CARRIED.search(outcome) else "",
            "mover": last["moved"] if last else "", "seconder": last["seconded"] if last else "",
            "ayes": cast.count(council_tables.AYE), "noes": cast.count(council_tables.NO),
            "not_voting": sum(word not in (council_tables.AYE, council_tables.NO) for word in cast),
            "heading": heading, "section": line["section"], "section_id": under["item_id"] if with_section else "",
            "motions": len(motions), "motions_read": sum(motion["read"] for motion in motions),
            "votes_read": all(motion["read"] for motion in motions) if motions else None,
            "problem": next((motion["problem"] for motion in motions if not motion["read"]), ""),
            "doc_type": "" if heading else numbered[1].lower() if numbered else county.doc_type_of(title),
            "subject": "" if heading else subject_of(title),
            "number": "; ".join(re.findall(r"\d[\w-]*\d|\d", numbered[2])) if numbered else "",
            "in_minutes": line["found"], "document_url": line["document"],
            "motion_log": json.dumps([{"motion": number, "text": motion["text"], "mover": motion["mover"], "seconder": motion["seconder"],
                                       "said": [["/".join(words), names] for words, names in motion["said"]],
                                       "after": clean(motion["after"]), "read": motion["read"], "problem": motion["problem"]}
                                      for number, motion in enumerate(motions, 1)], ensure_ascii=False, separators=(",", ":")) if motions else "",
        })
        facts["motions"] += len(motions)
        facts["motions_read"] += sum(motion["read"] for motion in motions)
    return agenda, votes, facts


def subject_of(title):
    """The department an item's title opens with ("Sheriff-Coroner: Approve agreement ..."), or ""."""
    found = re.match(r"^([A-Z][A-Za-z/&’' ,.-]{2,70}?):\s", clean(title))
    return clean(found[1]) if found else ""


def printed_names(scanned):
    """Each supervisor's name as the votes of a set of minutes print it: [(the surname on the roll, the name printed)]."""
    return [(member, clean(re.sub(r"^(\S+),\s*(.+)$", r"\2 \1", name)))
            for entry in scanned["entries"] for motion in entry["motions"] for member, name, _ in motion["cast"] or []]


def one_spelling(forms):
    """The one name each supervisor has in the tables, from {surname's letters: Counter(names printed)}: the name most
    often printed. A surname one letter from another printed at least ten times as often is that one misspelled."""
    count = {key: sum(names.values()) for key, names in forms.items()}
    same = {}
    for key in forms:
        nearby = [other for other in forms if len(key) >= 5 and near(key, other) and count[other] >= 10 * count[key]]
        same[key] = nearby[0] if len(nearby) == 1 else key
    best = {}
    for key in forms:
        names = forms[same[key]]
        full = {name: seen for name, seen in names.items() if " " in name} or names
        best[key] = sorted(full.items(), key=lambda form: (-form[1], form[0]))[0][0]
    return best


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------

def items_table(agenda, meetings):
    """Every item in the minutes read, with what was last done with it: by a vote of its own, or by the consent
    agenda's.

    The portal knows an item by a number of its own, so an item that came to two meetings is here once, with the last
    of them; `times_on_agenda` counts the agendas it was on, read or not.
    """
    read = set(meetings.loc[meetings["minutes"] == "read", "meeting_id"])
    of = agenda.set_index("item_id")
    lines = agenda[~agenda["heading"]]
    times = lines.groupby("matter_id").size()
    first = lines.groupby("matter_id")["date"].min()
    rows = []
    for line in lines[lines["meeting_id"].isin(read) & lines["in_minutes"]].sort_values(["date", "meeting_id", "sequence"]).itertuples(index=False):
        own = line.motions > 0
        over = of.loc[line.section_id] if not own and line.section_id else None
        vote = line._asdict() if own else over.to_dict() if over is not None else None
        rows.append({
            "date": line.date, "matter_id": line.matter_id, "matter_file": line.matter_file, "doc_type": line.doc_type,
            "title": line.title, "body": line.body, "status": "", "year": int(line.date[:4]), "subject": line.subject,
            "agenda_date": first[line.matter_id], "passed_date": "", "last_action": line.action,
            "last_action_date": line.date if line.action else "", "result": vote["result"] if vote else "",
            "ayes": int(vote["ayes"]) if vote else 0, "noes": int(vote["noes"]) if vote else 0,
            "mover": vote["mover"] if vote else "", "seconder": vote["seconder"] if vote else "",
            "times_on_agenda": int(times[line.matter_id]),
            "url": f"{PORTAL}/agendaitem/details/{line.matter_id}" if line.matter_id.isdigit() else meeting_url(line.meeting_id),
            "item_id": line.item_id, "meeting_id": line.meeting_id, "section": line.section,
            "action_on": "item" if own else "section" if over is not None else "",
            "votes_read": None if vote is None or pd.isna(vote["votes_read"]) else bool(vote["votes_read"]),
            "number": line.number,
        })
    out = pd.DataFrame(rows, columns=ITEM_COLUMNS).drop_duplicates("matter_id", keep="last")
    out["votes_read"] = out["votes_read"].astype("boolean")
    return out.sort_values(["date", "meeting_id", "matter_id"], ascending=[False, False, True]).reset_index(drop=True)


def members_table(votes, meetings, now=None):
    """Everyone who voted on two days or more. The minutes give no districts and no terms of office. `serving` is true
    where the last vote is no more than SERVING_DAYS old, and `role` is the office the newest meeting's page gives."""
    since = ((datetime.strptime(now, "%Y-%m-%d") if now else datetime.now(timezone.utc)) - timedelta(days=SERVING_DAYS)).strftime("%Y-%m-%d")
    offices = {}
    for meeting in meetings[meetings["roll"] != ""].sort_values("date").itertuples(index=False):
        roll = json.loads(meeting.roll)
        if any(member["role"] for member in roll):
            offices = {member["name"]: member["role"] for member in roll}
    cast = votes.groupby("member")["date"].agg(["min", "max", "size", "nunique"]) if len(votes) else pd.DataFrame()
    rows = [{"name": name, "district": None, "role": offices.get(name, "") if cast.loc[name, "max"] >= since else "", "start": "", "end": "",
             "serving": cast.loc[name, "max"] >= since, "first_vote": cast.loc[name, "min"], "last_vote": cast.loc[name, "max"],
             "votes": int(cast.loc[name, "size"])} for name in sorted(cast.index) if cast.loc[name, "nunique"] >= 2]
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
    for table, columns in ((agenda, ("sequence", "ayes", "noes", "not_voting", "motions", "motions_read")), (votes, ("motion",))):
        for column in columns:
            table[column] = table[column].astype(int)
    for column in ("heading", "in_minutes"):
        agenda[column] = agenda[column].astype(bool)
    agenda["votes_read"] = agenda["votes_read"].astype("boolean")
    return agenda, votes


FACTS = (("page", ""), ("agenda_url", ""), ("minutes_url", ""), ("packet_url", ""), ("minutes", ""), ("pages", 0), ("present", ""),
         ("roll", ""), ("motions", 0), ("motions_read", 0))


def build(base, everything, out_dir, since=FIRST_YEAR, limit=0):
    rows = [row for row in listed(since) if row["date"] >= f"{since}-01-01"]
    log.info(f"Yuba County: {len(rows)} meetings listed")
    if len(rows) < 20:
        raise RuntimeError("the listing of meetings came back nearly empty")
    meetings = meetings_table(rows)

    agenda, votes, before_meetings = (council_tables.held(HF_REPO, out_dir, name, base) for name in ("agenda_items", "votes", "meetings"))
    before = 0 if votes is None else len(votes)
    if agenda is None or votes is None or before_meetings is None:
        agenda, votes = pd.DataFrame(columns=AGENDA_COLUMNS), pd.DataFrame(columns=VOTE_COLUMNS)
        before_meetings = pd.DataFrame(columns=MEETING_COLUMNS)
    found = {row["meeting_id"]: {name: row.get(name, empty) for name, empty in FACTS}
             for row in before_meetings[before_meetings["page"] != ""].to_dict("records")}
    recent = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    listed_rows = meetings.to_dict("records")
    wanted = [row for row in listed_rows
              if row["date"] >= recent or (not whole(row["meeting_id"], out_dir) and (everything or row["meeting_id"] not in found))]
    wanted.sort(key=lambda row: (row["date"], row["meeting_id"]), reverse=True)  # the newest first: a room shows those
    waiting = len(wanted)
    wanted = wanted[:limit] if limit else wanted
    log.info(f"Fetching {len(wanted)} meetings of {waiting} not yet read or to be read again")

    # First each meeting's page and the text of its minutes, which is the only part that asks anything of the portal:
    # one request after another. They are kept as they come, so a run that is stopped has lost nothing.
    fetched = 0
    for count, row in enumerate(wanted, 1):
        try:
            fetch_meeting(row, out_dir, fresh=row["date"] >= recent)
            fetched += 1
        except Refused as e:
            log.error(f"The host refused a request ({e}): no more is asked of it in this run")
            break
        except Exception as e:
            log.warning(f"meeting {row['meeting_id']}: {type(e).__name__}: {e}")
        if count % 25 == 0:
            log.info(f"Yuba County: {count} of {len(wanted)} meetings asked for")

    # Then every meeting whose page is here is read, old and new: a supervisor's name is spelled the way the minutes
    # most often spell it, and that is known only with all of them.
    scans, forms = {}, {}
    for member in votes["member"] if len(votes) else []:
        forms.setdefault(key_of(member.split()[-1]), Counter())[member] += 1
    for row in listed_rows:
        page = kept_page(row["meeting_id"], out_dir)
        if page is None:
            continue
        scanned, pages, state = None, 0, ""
        if page["files"].get("minutes") and page.get("text_of") == page["files"]["minutes"] and text_path(row["meeting_id"], out_dir).exists():
            text = text_path(row["meeting_id"], out_dir).read_text(encoding="utf-8")
            pages = text.count("\f") + 1 if text else 0
            if not text:
                state = "not a PDF"
            elif len(re.sub(r"\s", "", text)) < LAYER_CHARS:
                state = "no text layer"
            else:
                scanned = scan(text)
                for member, name in printed_names(scanned):
                    forms.setdefault(key_of(member), Counter())[name] += 1
        scans[row["meeting_id"]] = (row, page, scanned, pages, state)
    spelled = one_spelling(forms)
    new_agenda, new_votes = [], []
    for meeting_id, (row, page, scanned, pages, state) in scans.items():
        reading = read_meeting(row, page, scanned, spelled, pages)
        new_agenda.extend(reading[0])
        new_votes.extend(reading[1])
        found[meeting_id] = {**reading[2], "minutes": state or reading[2]["minutes"]}
    agenda = joined(agenda[~agenda["meeting_id"].isin(set(scans))], pd.DataFrame(new_agenda, columns=AGENDA_COLUMNS))
    votes = joined(votes[~votes["meeting_id"].isin(set(scans))], pd.DataFrame(new_votes, columns=VOTE_COLUMNS))
    listed_ids = set(meetings["meeting_id"])
    agenda, votes = agenda[agenda["meeting_id"].isin(listed_ids)], votes[votes["meeting_id"].isin(listed_ids)]
    agenda = agenda.sort_values(["date", "meeting_id", "sequence"]).reset_index(drop=True)
    votes = votes.sort_values(["date", "meeting_id", "item_id", "motion", "member"]).reset_index(drop=True)
    agenda, votes = typed(agenda, votes)
    for name, empty in FACTS:
        meetings[name] = [found.get(meeting_id, {}).get(name, empty) for meeting_id in meetings["meeting_id"]]
    count = agenda[~agenda["heading"]].groupby("meeting_id").size() if len(agenda) else {}
    meetings["items"] = meetings["meeting_id"].map(count).fillna(0).astype(int)

    tables = council_tables.standard({
        "items": items_table(agenda, meetings), "meetings": meetings, "agenda_items": agenda, "votes": votes,
        "members": members_table(votes, meetings),
    })
    council_tables.write_tables(tables, out_dir)
    if len(votes) < before * 0.98:
        raise RuntimeError(f"only {len(votes)} votes where there were {before}; not publishing")
    return tables, fetched


def card(tables):
    """The dataset card, with the counts of this reading written in."""
    meetings, agenda, votes = tables["meetings"], tables["agenda_items"], tables["votes"]
    read = meetings[meetings["minutes"] == "read"]
    motions, motions_read = int(agenda["motions"].sum()), int(agenda["motions_read"].sum())
    facts = {
        "repo": HF_REPO, "first_meeting": read["date"].min() if len(read) else "", "last_meeting": read["date"].max() if len(read) else "",
        "first_vote": votes["date"].min() if len(votes) else "", "last_vote": votes["date"].max() if len(votes) else "",
        "n_read": f"{len(read):,}", "n_scans": f"{int((meetings['minutes'] == 'no text layer').sum()):,}",
        "n_motions": f"{motions:,}", "n_motions_read": f"{motions_read:,}", "n_unread": f"{motions - motions_read:,}",
        "share_read": f"{100 * motions_read / motions:.1f}" if motions else "0", "recent_days": RECENT_DAYS, "first_year": FIRST_YEAR,
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
        log.error(f"Yuba County tables not uploaded: {e}")
        return False
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the Yuba County Board's meetings, actions and votes")
    parser.add_argument("--base", action="store_true", help="start from the tables written here, not the published ones")
    parser.add_argument("--all", action="store_true", help="fetch every meeting not kept here whole, read before or not")
    parser.add_argument("--since", type=int, default=FIRST_YEAR, help="read no meeting before this year")
    parser.add_argument("--max", type=int, default=0, help="meetings to fetch in one run (0 for all)")
    parser.add_argument("--out", default="", help="directory to write the tables into (minutes_pdf/yuba-county if not given)")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the tables only")

    out_dir = Path(args.out) if args.out else OUT_DIR
    try:
        tables, fetched = build(args.base, args.all, out_dir, args.since, args.max)
    except Exception as e:
        log.error(f"Yuba County tables not built: {type(e).__name__}: {e}")
        return 1
    pushed = False if args.no_upload else upload(tables, out_dir, args.write_card)
    meetings, agenda, votes, members = tables["meetings"], tables["agenda_items"], tables["votes"], tables["members"]
    motions, motions_read = int(agenda["motions"].sum()), int(agenda["motions_read"].sum())
    log.info(f"RESULT: yuba-board items={len(tables['items'])} meetings={len(meetings)} "
             f"meetings_with_minutes={int((meetings['minutes_url'] != '').sum())} "
             f"minutes_read={int((meetings['minutes'] == 'read').sum())} "
             f"no_text_layer={int((meetings['minutes'] == 'no text layer').sum())} agenda_items={len(agenda)} "
             f"motions={motions} motions_read={motions_read} motions_unread={motions - motions_read} votes={len(votes)} "
             f"members={len(members)} serving={int(members['serving'].sum())} meetings_fetched={fetched} "
             f"first_vote={votes['date'].min() if len(votes) else ''} last_vote={votes['date'].max() if len(votes) else ''} "
             f"refused={_refused.is_set()} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
