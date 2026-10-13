#!/usr/bin/env python3
"""
Build chrissoria/orange-county-board: the meetings of the Orange County
(California) Board of Supervisors, what was on each agenda, what the Board did
with it, and how each supervisor voted.

One source: the County's own agenda system (ocagendaext.oc.gov). It lists the
meetings as pages of HTML and keeps, for each, its minutes as a PDF. The system
has no record of a vote apart from that document, so the votes here are read
from it. The minutes print a vote in one of two ways.

Since 28 April 2026, by name, under the motion:

    ON THE MOTION OF CHAIR CHAFFEE, SECONDED BY SUPERVISOR WAGNER,
    APPROVED ITEM AS RECOMMENDED
    Ayes: Nguyen, Wagner and Chaffee
    Noes: Sarmiento and Foley

Before that, back to 2007, as a code in the left margin beside the action,
with marks under it:

    52134  MOTION TO APPROVE ITEM AS RECOMMENDED FAILED TO CARRY
      ANN

and a key at the foot of the same minutes that says what the code means:

    1. = Supervisor Nguyen      A. = Abstained
    2. = Supervisor Sarmiento   X. = Excused
    3. = Supervisor Wagner      N. = No
    4. = Supervisor Chaffee     BO = Board Order
    5. = Supervisor Foley
    Above numbers refer to Supervisorial Districts
    (1st number = Moved by; 2nd number = Seconded by)

So 52134 over ANN is: moved by Foley, seconded by Sarmiento, Nguyen abstained,
Wagner and Chaffee voted no. The key names the supervisor for each number, the
first two places, and the three marks. Two things it leaves unsaid are taken
as read here, and said on the card: that a mark belongs to the number it is
printed under (the margin is set in a typewriter face, so a mark stands
exactly under one number), and that a number with no mark under it voted aye.

A vote is read whole or not at all. A block of names is read only if every
name is one supervisor listed at the head of those minutes and every
supervisor listed there is in it once. A code is read only if those minutes
print the key, the key and the head of the minutes name the same supervisors,
the code has each seated district once, and every mark stands under one of its
numbers other than the first two (the mover and the seconder). Neither is read
if it has a supervisor voting whom the head of the minutes has excused for the
day. A vote that does not pass is left out of the votes: the motion is kept,
with what stopped the reading (`problem`), and counted as unread.

The dataset has the five tables every council's and board's dataset has
(council_tables.py), in data/:
  items.parquet          every item in minutes that were read
  meetings.parquet       one row per meeting listed
  agenda_items.parquet   one row per line of the minutes, headings too, with what was done
  votes.parquet          one row per supervisor and motion voted on
  members.parquet        one row per supervisor seen in a vote that was read
They are kept here in minutes_pdf/orange-county/, with what was read out of
each PDF beside them in text/, so a document is fetched once.

The archive lists a meeting once for each recording of it (morning, afternoon,
read-out), each with its own address for the same minutes. A day's rows are
read together, and rows whose minutes are the same document are one meeting.

Two ways to run it:

    python build_orange_board.py
        The routine run. Starts from the published tables, lists every meeting
        again, and reads the minutes not read before and those of meetings in
        the last 90 days (minutes are posted after the meeting, and are
        sometimes revised).

    python build_orange_board.py --base
        The same, starting from the tables written here. It reads the newest
        meeting first and can be stopped and started again.

    --since YEAR  read no meeting before this year (default 2007, where the listing begins)
    --max N       days of meetings to read in one run (default 0, for all)
    --all         read every document again, from what is kept here where there is some
    --out DIR     where to write the tables
    --no-upload   write the tables but do not publish them
    --write-card  publish the dataset card as well as the tables

Needs pdfplumber. Only a PDF's own text is read: minutes that are a scan are
counted and left.
"""

import argparse
import collections
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

import pandas as pd
import requests

import build_federal_bills as bills
import build_sd_county as county
import council_tables
from build_sd_county import clean, today

log = logging.getLogger(__name__)

HF_REPO = "chrissoria/orange-county-board"
OUT_DIR = bills.SCRIPT_DIR / "minutes_pdf" / "orange-county"
CARD_FILE = bills.SCRIPT_DIR / "README_orange_board.md"
TABLES = council_tables.TABLES
BODY = "Board of Supervisors"

HOST = "https://ocagendaext.oc.gov"
# The three pages the County's site is made from: the archive (2007 to April 2026), the meetings since, and those to come.
LISTINGS = ("ArchivedBosMeetings", "bosmeetingd", "bosmeetingc")
FIRST_YEAR = 2007  # the archive begins here
RECENT_DAYS = 90  # meetings this recent are read again: the minutes come after the meeting and are sometimes revised
LAYER_CHARS = 200  # minutes with fewer characters of their own than this are a scan

MEETING_COLUMNS = council_tables.COLUMNS["meetings"] + [
    "name", "kind", "video_url", "documents", "summary", "format", "pages", "roll", "vote_blocks", "blocks_read", "problem"]
AGENDA_COLUMNS = council_tables.COLUMNS["agenda_items"] + [
    "heading", "section", "section_id", "group", "motions", "vote_blocks", "blocks_read", "votes_read", "problem",
    "voted_with", "doc_type", "number", "motion_log"]
VOTE_COLUMNS = council_tables.COLUMNS["votes"] + ["motion", "motion_text", "code", "marks"]
ITEM_COLUMNS = council_tables.COLUMNS["items"] + ["item_id", "meeting_id", "section", "group", "action_on", "votes_read", "number"]

# A supervisor the heads of the minutes spell more than one way, and the one spelling kept here.
SPELLED = {"Donald Wagner": "Donald P. Wagner", "John M.W. Moorlach": "John M. W. Moorlach", "John W. M. Moorlach": "John M. W. Moorlach",
           "Johm M. W. Moorlach": "John M. W. Moorlach"}

# The marks under a code, and the word the minutes' key gives each. A number with no mark under it is an aye.
MARKS = {"N": "No", "A": "Abstained", "X": "Excused"}
NO_MARK = "."
# The words a block of names sorts the supervisors under, in the order it prints them.
LABELS = ("Ayes", "Noes", "Abstained", "Excused")

# What is kept of a PDF is its lines, each as: what stands in the left margin, where the line begins (in points from
# the left edge), whether it is all in bold, and its words. A wide gap in a line is kept as a tab.
MARGIN = 0.25  # the margin's notes are in a typewriter face and begin within this share of the page's width
PITCH = 4  # two things this close in height are on one line; the lines are 12 points apart
GAP = 15  # a gap this wide parts two columns
NEAR = 1.0  # two lines begin at the same place if they begin within this of each other
LEFT, CENTRE = 180, 330  # where the left-hand and the middle column of the head of the minutes end

_ROLE = {"CHAIR", "CHAIRMAN", "CHAIRWOMAN", "VICE", "SUPERVISOR"}
_DISTRICT = re.compile(r"(First|Second|Third|Fourth|Fifth) District")
_ORDINAL = {"First": 1, "Second": 2, "Third": 3, "Fourth": 4, "Fifth": 5}
_TITLE = re.compile(r"^(?:(?:Vice|Supervisor|Chairman|Chairwoman|Chair)\s+)+", re.I)
_HEAD_END = re.compile(r"^(ATTENDANCE|EXCUSED|PRESENT)\s*:")
_WHEN = re.compile(r"(\d{1,2})\s*:\s*(\d{2})\s*([AP])\.?\s*M", re.I)
_KIND = re.compile(r"^([A-Z][A-Z ]*?)\s*MEETING OF THE BOARD OF SUPERVISORS", re.I)
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
_DAY = re.compile(rf"\b({'|'.join(_MONTHS)})\s+(\d{{1,2}}),\s+(\d{{4}})", re.I)
_PAGE_FURNITURE = re.compile(r"^(S U M M A R Y A C T I O N M I N U T E S|MINUTES - BOARD OF SUPERVISORS.* - PAGE \d+|Document Last Updated:.*)$", re.I)
_KEY = re.compile(r"^\*+\s*KEY\s*\*+$")
_KEY_ENTRY = re.compile(r"(?<![\w.])(?:([1-5])\.|([AXN])\.(?=\s*(?:Abstained|Excused|No)\b)|(BO|ORD\.|RESO\.|Above)(?!\w))")
_KEY_ORDER = re.compile(r"1st\s+number\s+Moved\s+by\W+2nd\s+number\s+Seconded\s+by", re.I)
_CELL = re.compile(r"[.AXN?]{5}")  # a row of marks, as kept: one place for each column of the margin
_CODE = re.compile(r"[1-5]{1,5}")
_ORDER = re.compile(r"B\.?O\.?")
_NUMBER = r"(?:S|CS[-\xad]?|SCS[-\xad]?)?\d+[A-Z]?"
_ITEM_NOTE = re.compile(rf"({_NUMBER})\.")  # an item's number in the margin
_ITEM_OPEN = re.compile(r"(?:S|CS[-\xad]?|SCS[-\xad]?)\d*[A-Z]?")  # one that ran over the margin's end: "CS-" above "6."
_ITEM_REST = re.compile(r"\d*[A-Z]?\.")
_ITEM_LINE = re.compile(rf"^({_NUMBER})\s?\.\s+(\S.*)$")  # an item's number at the start of a line
_SECTION = re.compile(r"^([IVX]{1,5})\.\s+(\S.*)$")
_PLAIN_SECTION = re.compile(r"^(CONSENT CALENDAR|DISCUSSION ITEMS?|PUBLIC HEARINGS?|CLOSED SESSION|PRESENTATIONS|INVOCATION|PUBLIC|BOARD COMMENTS|"
                            r"COUNTY EXECUTIVE OFFICER COMMENTS|CEO)\b")
_RANGE = re.compile(r"\(Items?\s+(\d+)\s*[-–]\s*(\d+)")
_EXCEPT = re.compile(r"\bEXCEPTION|\bEXCEPT\b|\bEXCLUD|\bOTHER THAN\b|\bPULLED\b|\bDELETED\b|\bCONTINUED\b", re.I)  # where a consent motion begins to say what it left out
_DATED = re.compile(r"\d+/\d+(?:/\d+)?|\d+\s*:\s*\d+")  # days and times in a motion, which are not items' numbers
_ADJOURNED = re.compile(r"^ADJOURNED\s*:", re.I)  # the meeting's end, and the time
_NUMBERED = re.compile(r"^(RESO|ORD|Resolution|Ordinance)\b[^:\d]{0,12}[:.]?\s*(\d.*)$")  # the number an item was adopted under
_LABEL = re.compile(r"^(Ayes|Noes|Abstained|Excused)\s*:\s*(.*)$")
_MOTION = re.compile(r"^ON THE MOTION OF\s+(.+?),\s*SECONDED BY\s+(.+?),\s*(.*)$", re.S)
_FAILED = re.compile(r"\bFAILED\b", re.I)
# The link the new minutes print after an item's title, whole or broken over a line's end.
_LINK = re.compile(r"\s*\(Click(?: to(?: View(?: Files\)?)?)?)?$|^(?:(?:to )?View )?Files\)\s*")


class Refused(Exception):
    """The host answered with a check, a login or a refusal. It is not asked again in this run."""


_refused = threading.Event()
_CHECK = re.compile(r"captcha|cf-challenge|are you a human|access denied|sign in to continue", re.I)


def fetch(url, tries=4):
    """One answer from the County's system. A refusal is not tried again, and nothing more is asked of the host in this run."""
    if _refused.is_set():
        raise Refused("the host refused an earlier request")
    for attempt in range(tries):
        try:
            answer = requests.get(url, headers=county.HEADERS, timeout=120)
            page = "html" in answer.headers.get("content-type", "") and answer.content[:4] != b"%PDF"
            if answer.status_code in (401, 403, 429) or (page and _CHECK.search(answer.text[:20000])):
                _refused.set()
                raise Refused(f"{answer.status_code} from {url}")
            answer.raise_for_status()
            return answer
        except requests.RequestException as e:
            # A host that is not allowed will not be allowed on a second asking.
            if attempt == tries - 1 or isinstance(e, requests.exceptions.ProxyError):
                raise
            time.sleep(2 * (attempt + 1))


# ---------------------------------------------------------------------------
# The listing
# ---------------------------------------------------------------------------

_ROW = re.compile(r"<tr>.*?</tr>", re.S)
_TD = re.compile(r'<td[^>]*data-label="([^"]*)"[^>]*>(.*?)</td>', re.S)
_DOCUMENT = re.compile(r'href="(https?://[^"]*/(?:Ext|Legacy)DocViewer/([0-9A-Fa-f-]{36}))"')
_HREF = re.compile(r'href="(https?://[^"]+)"')
_LISTED_DAY = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})(?:,\s*(\d{1,2}):(\d\d)\s*([AP]M))?")


def rows_of(page, listing=""):
    """The rows of one of the County's listings. A row is one recording of a meeting, or a meeting to come."""
    rows = []
    for found in _ROW.finditer(page):
        cells = dict(_TD.findall(found[0]))
        words = {label: clean(html.unescape(re.sub(r"<[^>]+>", " ", cell))) for label, cell in cells.items()}
        when = _LISTED_DAY.search(words.get("Meeting Date", "") or words.get("Meeting Date/Time", ""))
        if not when:
            continue
        minutes = _DOCUMENT.search(next((cell for label, cell in cells.items() if label.startswith("Accessible Minutes")), ""))
        agenda = _DOCUMENT.search(cells.get("Agenda", ""))
        video = _HREF.search(cells.get("Board Meeting Video", ""))
        rows.append({
            "key": minutes[2].lower() if minutes else "", "title": words.get("Meeting Title", ""),
            "date": f"{when[3]}-{int(when[1]):02d}-{int(when[2]):02d}",
            "time": f"{int(when[4])}:{when[5]} {when[6]}" if when[4] else "",
            "location": words.get("Meeting Location", ""), "listing": listing,
            "minutes_url": minutes[1] if minutes else "", "agenda_url": agenda[1] if agenda else "",
            "video_url": video[1] if video else "",
        })
    return rows


def listed():
    """Every row the County lists, in its order: the newest first within each listing."""
    rows = []
    for listing in LISTINGS:
        rows.extend(rows_of(fetch(f"{HOST}/{listing}").text, listing))
        time.sleep(0.5)
    return rows


def days_of(rows):
    """The rows by the day of their meeting. A day's rows are read together: most are one meeting listed more than once."""
    days = {}
    for row in rows:
        days.setdefault(row["date"], []).append(row)
    return days


def unread(date, rows):
    """A day's line in the meetings table before its minutes are read: one meeting, whatever the listing has for it."""
    first = next((row for row in rows if row["minutes_url"]), rows[0])
    return {"meeting_id": date, "date": date, "time": first["time"], "body": BODY, "location": first["location"],
            "url": f"{HOST}/{first['listing']}", "agenda_url": next((row["agenda_url"] for row in rows if row["agenda_url"]), ""),
            "minutes_url": first["minutes_url"], "items": 0, "name": "; ".join(dict.fromkeys(row["title"] for row in rows)),
            "kind": "", "video_url": first["video_url"], "documents": "[]", "summary": "", "format": "", "pages": 0, "roll": "",
            "vote_blocks": 0, "blocks_read": 0, "problem": ""}


# ---------------------------------------------------------------------------
# What a PDF says
# ---------------------------------------------------------------------------

Line = collections.namedtuple("Line", "margin x0 bold text parts page")


def pdf_text(body):
    """The lines a PDF carries, a page at a time, as text. Nothing is read off the picture of a page.

    A line is kept as its margin note, where it begins, "b" if it is all in bold, and its words, with tabs between
    them. A row of marks is kept by where its marks stand: `..X.N` is an X in the third column and an N in the fifth,
    counted from where the code above it begins. A mark that stands in no column makes the row `?????`, which is not read.
    """
    import pdfplumber
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    pages = []
    with pdfplumber.open(io.BytesIO(body)) as document:
        for page in document.pages:
            edge = MARGIN * float(page.width)
            note = lambda thing: "Courier" in thing["fontname"] and thing["x0"] < edge
            rows = []  # each: its height on the page, its words, the characters of its margin note

            def place(thing, slot):
                near = min(rows, key=lambda row: abs(row[0] - thing["top"]), default=None)
                if near is None or abs(near[0] - thing["top"]) > PITCH:
                    near = [thing["top"], [], []]
                    rows.append(near)
                near[slot].append(thing)

            for word in sorted(page.extract_words(extra_attrs=["fontname"], x_tolerance=1.5), key=lambda word: (word["top"], word["x0"])):
                if not note(word):
                    place(word, 1)
            for char in sorted(page.chars, key=lambda char: (char["top"], char["x0"])):
                if char["text"].strip() and note(char):
                    place(char, 2)
            rows.sort(key=lambda row: row[0])
            for row in rows:
                row[1].sort(key=lambda word: word["x0"])
                row[2].sort(key=lambda char: char["x0"])
            pages.append(rows)
    out, code = [], None  # the code last passed: where it begins, and how wide a number is
    for rows in pages:
        lines = []
        for top, words, chars in rows:
            margin = "".join(char["text"] for char in chars)
            if re.fullmatch(r"[1-5]{3,5}", margin):
                code = (chars[0]["x0"], chars[0]["x1"] - chars[0]["x0"])
            elif margin and all(char in MARKS for char in margin):
                cell = [NO_MARK] * 5
                for char in chars:
                    column = (char["x0"] - code[0]) / code[1] if code else -1
                    if abs(column - round(column)) > 0.2 or not 0 <= round(column) < 5 or cell[round(column)] != NO_MARK:
                        cell = ["?"] * 5
                        break
                    cell[round(column)] = char["text"]
                margin = "".join(cell)
            parts = []
            for word in words:
                if parts and word["x0"] - parts[-1][1] <= GAP:
                    parts[-1][0].append(word["text"])
                    parts[-1][1] = word["x1"]
                else:
                    parts.append([[word["text"]], word["x1"]])
            bold = bool(words) and all("bold" in word["fontname"].lower() for word in words)
            x0 = f"{words[0]['x0']:.1f}" if words else "0"
            lines.append("\t".join([margin, x0, "b" if bold else "-"] + [" ".join(part[0]) for part in parts]))
        out.append("\n".join(lines))
    return "\f".join(out)


def lines_of(text):
    """The lines kept of a PDF, in order, without the head and foot of each page: a title or an action runs over a page's end."""
    lines = []
    for page, kept_page in enumerate(text.split("\f"), 1):
        for kept in kept_page.split("\n"):
            fields = kept.split("\t")
            if len(fields) < 3:
                continue
            parts = [clean(part) for part in fields[3:] if clean(part)]
            line = Line(fields[0].strip(), float(fields[1] or 0), fields[2] == "b", " ".join(parts), parts, page)
            if (line.margin or line.text) and not _PAGE_FURNITURE.match(line.text):
                lines.append(line)
    return lines


_STAMPS = re.compile(rb"/ModDate\s*\(D:[^)]*\)|xmp:(?:Modify|Metadata)Date=\"[^\"]*\"|/ID\s*\[\s*<[0-9A-Fa-f]*>\s*<[0-9A-Fa-f]*>\s*\]")


def same_bytes(one, other):
    """Whether two PDFs are one document sent twice: the system stamps each answer with the time it was sent, and with
    a number of its own, and nothing else differs. Two that differ anywhere else are compared by what they say."""
    return len(one) == len(other) and _STAMPS.sub(b"", one) == _STAMPS.sub(b"", other)


class NotPdf(ValueError):
    """The system answered, and what it sent is not a PDF: a line of words, a page, a document of another kind."""


def fetch_pdf(url):
    time.sleep(0.3)
    body = fetch(url).content
    if body[:4] != b"%PDF":
        sent = "a Word document" if body[:2] == b"PK" else repr(clean(re.sub(r"[^ -~]", " ", body[:60].decode("latin-1"))))
        raise NotPdf(f"the system sent {sent} in place of the minutes")  # with a 200
    return body


# ---------------------------------------------------------------------------
# Who sits on the Board, and who a name or a number is
# ---------------------------------------------------------------------------

def named(words):
    """A name set in capitals, as it is written: JOHN M.W. MOORLACH is John M.W. Moorlach."""
    name = re.sub(r"[A-Za-z]+", lambda word: word[0] if len(word[0]) == 1 else word[0].capitalize(), clean(words))
    return SPELLED.get(name, name)


def surname(name):
    words = re.findall(r"[A-Za-z][A-Za-z'’-]*", _TITLE.sub("", clean(name)))
    return words[-1].lower() if words else ""


def seats_of(lines):
    """The supervisors at the head of the minutes, each with the district and the office printed there.

    The head is a table: the chair in the middle, then the others two to a row, each as a name, an office and a
    district, any of which may run over a line. A line's first part is the left-hand column's and its second the
    right-hand one's; a part alone on its line belongs to the column it begins in. A seat printed as VACANT is not
    one of them.
    """
    cells, seats = {}, []
    for line in lines[:60]:
        if _HEAD_END.match(line.text):
            break
        if len(line.parts) > 2:
            continue
        for place, part in enumerate(line.parts):
            column = (0 if place == 0 else 2) if len(line.parts) == 2 else 0 if line.x0 < LEFT else 1 if line.x0 < CENTRE else 2
            district = _DISTRICT.fullmatch(part)
            if not district and re.search(r"[a-z0-9,]", part):
                cells.clear()  # the day, the room, the street: the names come after them
                continue
            if not district:
                cells.setdefault(column, []).append(part)
                continue
            above, role, name = cells.pop(column, []), [], []
            while above and set(above[-1].split()) <= _ROLE:
                role.insert(0, above.pop())
            name = above
            if name and " ".join(name) != "VACANT":
                office = " ".join(role).title()
                seats.append({"name": named(" ".join(name)), "district": _ORDINAL[district[1]], "role": "" if office == "Supervisor" else office})
    return sorted(seats, key=lambda seat: seat["district"])


def key_of(lines):
    """The key at the foot of minutes that print codes: ({district: surname, or None for a vacant seat}, whether it
    says what the marks and the first two places mean), or (None, False) where the minutes print none."""
    at = next((index for index, line in enumerate(lines) if _KEY.match(line.text)), None)
    if at is None:
        return None, False
    # Each entry is a number or a letter, a sign (an equals sign, in one face or another, or a bracket) and what it stands for.
    text = clean(re.sub(r"[=(\uf03d]", " ", " ".join(line.text for line in lines[at + 1:at + 40])))
    entries = list(_KEY_ENTRY.finditer(text))
    seated, marks = {}, {}
    for entry, after in zip(entries, entries[1:] + [None]):
        said = clean(text[entry.end():after.start() if after else entry.end() + 80])
        if entry[1] and int(entry[1]) not in seated:
            who_sits = _TITLE.sub("", said)
            seated[int(entry[1])] = None if not who_sits or who_sits.lower() == "vacant" else surname(who_sits)
        elif entry[2]:
            marks[entry[2]] = said.split()[0] if said else ""
    return seated, marks == MARKS and bool(_KEY_ORDER.search(text))


def roll_of(lines, form):
    """(the supervisors a vote in these minutes is held to, why not if there are none).

    Minutes that name the voters are held to the head of the minutes. Minutes that print codes are held to the key,
    and to the head as well: the key gives a surname for each district and the head a full name, and where the two
    are not the same person nothing is read.
    """
    seats = seats_of(lines)
    if len({surname(seat["name"]) for seat in seats}) != len(seats):
        return [], "two supervisors at the head of the minutes share a surname"
    if form != "codes":
        return (seats, "") if len(seats) >= 3 else ([], "no supervisors found at the head of the minutes")
    seated, whole = key_of(lines)
    if seated is None:
        return [], "the minutes print no key to their codes"
    if not whole or set(seated) != {1, 2, 3, 4, 5}:
        return [], "the key does not say what every number and mark means"
    by_district = {seat["district"]: seat for seat in seats}
    roll = []
    for district, name in sorted(seated.items()):
        if name is None:
            continue
        if district not in by_district or surname(by_district[district]["name"]) != name:
            return [], f"the key and the head of the minutes name different supervisors for district {district}"
        roll.append(by_district[district])
    return (roll, "") if len(roll) >= 3 else ([], "the key names fewer than three supervisors")


def away_of(lines, roll):
    """The supervisors the head of the minutes says were excused for the day, where it says that and no more.

    "EXCUSED: Supervisor Nelson" is one; "EXCUSED: Supervisor Bates arrived during Public Comments" is none, since she
    was there for some of it.
    """
    said = next((_HEAD_END.sub("", line.text) for line in lines[:60] if line.text.startswith("EXCUSED")), "")
    away = [member["name"] for member in roll if re.search(rf"\b{re.escape(surname(member['name']))}\b", said.lower())]
    rest = re.sub(r"\b(?:supervisors?|vice|chair(?:man|woman)?|and|" + "|".join(re.escape(surname(name)) for name in away) + r")\b", " ", said.lower()) if away else ""
    return away if away and not re.search(r"[a-z0-9]", rest) else []


def who(name, roll):
    """The supervisor on the roll that a printed surname is ("Nguyen", "SUPERVISOR NGUYEN", "Vice Chair Foley"), or None."""
    words = _TITLE.sub("", clean(name)).split()
    if not words or len(words) > 3 or not all(re.fullmatch(r"[A-Za-z][A-Za-z'’.-]*", word) for word in words):
        return None
    found = [member["name"] for member in roll if surname(member["name"]) == surname(name)]
    return found[0] if len(found) == 1 else None


def read_code(code, marks, roll):
    """One vote printed as a code: ([(supervisor, word), ...], "") if it reads cleanly, or (None, why not).

    Clean means: the code has each seated district once and nothing else, and the row of marks under it has a mark
    under none but its numbers, and under neither of the first two. Those moved and seconded; and a row of marks typed
    at the margin's edge, and not under the numbers it is meant for, begins under them (two noes under the mover
    and the seconder of a motion that carried), so a mark there is taken to be out of its place.
    """
    if not roll:
        return None, "no roll to hold the code to"
    seated = {str(member["district"]): member["name"] for member in roll}
    if sorted(code) != sorted(seated):
        return None, f"the code {code} does not have each seated district once"
    marks = marks or NO_MARK * 5
    if not _CELL.fullmatch(marks) or "?" in marks:
        return None, "a mark stands under no number"
    if marks[len(code):].strip(NO_MARK):
        return None, f"a mark stands beyond the end of the code {code}"
    if marks[:2].strip(NO_MARK):
        return None, f"the code {code} has a mark under its mover or seconder"
    return [(seated[district], council_tables.AYE if mark == NO_MARK else council_tables.vote_word(MARKS[mark]))
            for district, mark in zip(code, marks)], ""


def only_names(text, roll):
    """Whether a line is nothing but surnames from the roll: the rest of a list of names that ran over the line's end."""
    words = re.findall(r"[A-Za-z'’-]+", text)
    known = {surname(member["name"]) for member in roll} | {"and"}
    return bool(words) and not re.search(r"[^A-Za-z'’., -]", text) and all(word.lower() in known for word in words)


def read_block(block, roll):
    """One vote printed as names: ([(supervisor, word), ...], "") if it reads cleanly, or (None, why not).

    `block` is its lines: each begins with one of LABELS, or is the rest of the list of names above it. Clean means:
    the words stand once each and in their order, beginning with Ayes; every name is one supervisor on the roll;
    nobody is named twice; and nobody on the roll is left out. So a block cut short, or run into the text after it,
    is not read.
    """
    if not roll:
        return None, "no roll to hold the names to"
    listed_under, order = {}, []
    for text in block:
        label = _LABEL.match(text)
        if label:
            if label[1] in listed_under:
                return None, f"{label[1]} twice"
            order.append(label[1])
            listed_under[label[1]] = label[2]
        elif order:
            listed_under[order[-1]] += " " + text
        else:
            return None, "no Ayes"
    if order != [word for word in LABELS if word in listed_under] or "Ayes" not in listed_under:
        return None, "words missing or out of order: " + " ".join(order)
    cast, seen = [], set()
    for word in order:
        names = clean(listed_under[word])
        if not names or names.lower().strip("().") == "none":
            continue
        for name in re.split(r",|\band\b|&", names):
            if not clean(name):
                continue
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
# Reading the minutes
# ---------------------------------------------------------------------------

def capitals(text):
    """Whether a line is set in capitals, as an action is: APPROVED AS RECOMMENDED; CONTINUED TO 7/19/11, 9:30 A.M."""
    return len(re.findall(r"[A-Z]", text)) >= 4 and not re.search(r"[a-z]", text)


def form_of(lines):
    """How these minutes print a vote: "names", "codes", or "" where they print none (or are not minutes)."""
    names = sum(line.text.startswith("Ayes") and bool(_LABEL.match(line.text)) for line in lines)
    codes = sum(bool(_CODE.fullmatch(line.margin)) and len(line.margin) >= 3 for line in lines) + any(_KEY.match(line.text) for line in lines)
    return "names" if names > codes else "codes" if codes else ""


def new_line(heading, number, title, section, group):
    return {"heading": heading, "number": number, "title": title, "section": None if heading else section,
            "group": "" if heading else group, "motions": [], "doubt": "", "numbers": "", "numbered": ""}


def new_motion(text="", code="", block=False, doubt=""):
    return {"text": text, "mover": "", "seconder": "", "code": code, "marks": "", "block": block, "names": [], "cast": [],
            "read": False, "problem": "", "doubt": doubt, "page": 0}


def parse_codes(lines):
    """Minutes that print codes, as a list of lines: headings and items, each with the motions made on it.

    The left margin holds an item's number beside its title, and beside what the Board did either a code (a vote) or
    B.O. (a board order, with no vote); a row of marks may stand under a code. What is not in the margin is told apart
    by where it begins: a title or an action runs on in lines that begin where it began, and a heading does not. A
    consent calendar is voted on as one, so its code stands under its heading, before its items.

    Four things leave a mark (`doubt`) on a motion, whose vote is then not read: a second row of marks under one
    code; marks with no code above them; marks at the top of the page after their code's (one such row was seen
    to have lost its place); and a code that ran over the margin's end onto a second line.
    """
    out, current, section = [], None, None
    major = minor = ""
    minor_at = None  # where the items under a department's own heading ("Sheriff-Coroner:") begin
    part, at = "", 0.0  # what the lines now being read belong to ("title", "action" or nothing), and where it began
    voted = None  # the motion a row of marks would now stand under
    pending = False  # an item's number has run over the margin's end

    def begin(heading, number, title):
        nonlocal current, part, voted
        current = new_line(heading, number, title, section, " - ".join(filter(None, (major, minor))))
        part, voted = "title", None
        out.append(current)

    start = next((index for index, line in enumerate(lines) if _HEAD_END.match(line.text)), 0)
    for line in lines[start:]:
        margin, text = line.margin, line.text
        if _KEY.match(text):
            break
        if margin and _CELL.fullmatch(margin):
            if voted is not None and not voted["marks"]:
                voted["marks"] = margin
                if line.page != voted["page"]:
                    voted["doubt"] = "the marks stand on the page after their code's"
            elif voted is not None:
                voted["doubt"] = "two rows of marks under one code"
            elif current is not None and current["motions"]:
                current["motions"][-1]["doubt"] = "marks with no code above them"
        elif margin and _CODE.fullmatch(margin):
            if voted is not None and not text and len(margin) < 3 and len(voted["code"]) < 5:
                voted["doubt"] = "the code ran over the margin onto a second line"  # 2345 above 1
                continue
            if current is None:
                begin(False, "", "")
            # One or two numbers are a mover, or a mover and a seconder, of a motion that was not put to a vote.
            motion = new_motion(text, margin, block=len(margin) >= 3)
            motion["page"] = line.page
            current["motions"].append(motion)
            voted, part, at, text = (motion if motion["block"] else None), "action", line.x0, ""
        elif margin and _ORDER.fullmatch(margin):
            if current is None:
                begin(False, "", "")
            current["motions"].append(new_motion(text))
            voted, part, at, text = None, "action", line.x0, ""
        elif margin and _ITEM_NOTE.fullmatch(margin):
            number = _ITEM_NOTE.fullmatch(margin)[1].replace("\xad", "-")
            begin(False, number, text)
            at, text, pending = line.x0, "", False
            if minor_at is None and minor:
                minor_at = line.x0
            elif minor_at is not None and line.x0 < minor_at - 5:
                minor = ""  # an item set further left than the department's own: its heading has ended
                minor_at = None
                current["group"] = major
        elif margin and _ITEM_OPEN.fullmatch(margin):
            begin(False, margin.replace("\xad", "-"), text)
            at, text, pending = line.x0, "", True
        elif margin and pending and _ITEM_REST.fullmatch(margin):
            current["number"] += margin.rstrip(".")
            pending = False
        elif margin:
            if current is not None:
                current["doubt"] = current["doubt"] or f"a note in the margin that is not understood: {margin[:20]}"
        if not text:
            continue
        heading = _SECTION.match(text) if not line.margin and (line.bold or capitals(text)) else None
        if heading:
            major = minor = ""
            minor_at = None
            begin(True, "", text)
            section = current
            continue
        if _ADJOURNED.match(text) and not line.margin:
            # The meeting's end. A motion to adjourn in someone's memory follows it, with a code of its own.
            begin(False, "", text)
            part = ""
            continue
        numbered = _NUMBERED.match(text)
        if numbered and current is not None and (part != "title" or numbered[1].isupper()):
            current["numbers"] = clean(f"{current['numbers']} {numbered[2]}")
            current["numbered"] = current["numbered"] or ("resolution" if numbered[1][0] == "R" else "ordinance")
            part = ""
            continue
        if part == "action" and (abs(line.x0 - at) <= NEAR or not current["motions"][-1]["text"]):
            motion = current["motions"][-1]
            if not motion["text"]:
                at = line.x0
            motion["text"] = clean(f"{motion['text']} {text}")
            continue
        if part == "title" and abs(line.x0 - at) <= NEAR and not current["heading"]:
            if line.bold and capitals(text) and current["title"]:
                current["motions"].append(new_motion(text))  # what was done, with neither a code nor B.O. beside it
                voted, part = None, "action"
            else:
                current["title"] = clean(f"{current['title']} {text}")
            continue
        if part == "title" and not current["heading"] and not current["title"]:
            current["title"], at = text, line.x0  # a title that begins on the line under its number
            continue
        # A heading: whose business follows (ELECTED DEPARTMENT HEADS), or within that a department's own (Sheriff-Coroner:).
        part, voted = "", None
        if line.bold and capitals(text) and section is not None and "COMMENTS" not in text:
            major, minor, minor_at = text, "", None
        elif line.bold and text.endswith(":") and len(text) < 60 and major:
            minor, minor_at = text.rstrip(":"), None
    return out


def parse_names(lines, roll):
    """Minutes that name the voters, as a list of lines: headings and items, each with the motions made on it.

    An item begins at a line that opens with its number. What the Board did follows in capitals, with or without
    "ON THE MOTION OF ..., SECONDED BY ...,", and a vote follows that as a block that begins "Ayes:". The consent
    calendar has a vote under its heading, and in these minutes each of its items has one as well.
    """
    out, current, section = [], None, None
    group = apart = ""
    part, at = "", 0.0  # what the lines now being read belong to ("title", "action", "block" or nothing), and where it began
    edge = min((line.x0 for line in lines if _ITEM_LINE.match(line.text)), default=0.0)  # where an item's number stands

    def begin(heading, number, title):
        nonlocal current, part, apart
        current = new_line(heading, number, title, section, group)
        part, apart = "title", ""
        out.append(current)

    start = next((index for index, line in enumerate(lines) if _HEAD_END.match(line.text)), 0)
    for line in lines[start:]:
        text = _LINK.sub("", line.text)
        if not text:
            continue
        label = _LABEL.match(text)
        if label and current is not None:
            motion = current["motions"][-1] if current["motions"] else None
            if label[1] == "Ayes" or part != "block":
                if motion is None or motion["block"]:
                    # Names with no action of their own before them: a second block under one action. Which of the
                    # two is the vote on it the minutes do not say, so neither is read.
                    if motion is not None:
                        motion["doubt"] = "two blocks under one action"
                    motion = new_motion(doubt="a block with no action of its own before it")
                    current["motions"].append(motion)
                motion["block"] = True
                part = "block"
            motion["names"].append(text)
            continue
        if part == "block":
            if only_names(text, roll):
                current["motions"][-1]["names"].append(text)
                continue
            part = ""
        item = _ITEM_LINE.match(text) if abs(line.x0 - edge) <= NEAR else None
        if item:
            begin(False, re.sub(r"\s", "", item[1]).replace("\xad", "-"), item[2])
            continue
        if line.bold and abs(line.x0 - edge) <= NEAR and _PLAIN_SECTION.match(text):
            group = ""
            begin(True, "", text)
            section = current
            continue
        if part == "action" and abs(line.x0 - at) <= NEAR and (capitals(text) or line.bold) and not text.startswith("ON THE MOTION OF"):
            current["motions"][-1]["text"] = clean(f"{current['motions'][-1]['text']} {text}")
            continue
        if abs(line.x0 - edge) <= NEAR and capitals(text) and text.endswith(":"):
            apart, part = text, ""  # MEMORIAL ADJOURNMENTS:, under which a motion to adjourn in someone's memory stands
            continue
        if text.startswith("END OF CONSENT CALENDAR") or current is None:
            part = "" if current is not None else part
            continue
        numbered = _NUMBERED.match(text)
        if numbered and (part != "title" or numbered[1].isupper()):
            current["numbers"] = clean(f"{current['numbers']} {numbered[2]}")
            current["numbered"] = current["numbered"] or ("resolution" if numbered[1][0] == "R" else "ordinance")
            part = ""
            continue
        # What was done: a motion, or under an item's title a line in capitals set in from the margin (BOARD ORDER, DELETED).
        if text.startswith("ON THE MOTION OF") or (part == "title" and not current["heading"] and capitals(text) and line.x0 - edge > NEAR):
            if abs(line.x0 - edge) <= NEAR and (current["number"] or apart or (current["heading"] and part != "title")):
                begin(False, "", apart)  # a motion set at the margin, and not under a heading, is no item's: its title is the words above it
            current["motions"].append(new_motion(text))
            part, at = "action", line.x0
            continue
        if part == "title" and not current["heading"] and abs(line.x0 - edge) > NEAR:
            current["title"] = clean(f"{current['title']} {text}")
            continue
        part = ""
        if abs(line.x0 - edge) <= NEAR and capitals(text) and len(text) < 60:
            group = text  # whose business follows: ELECTED DEPARTMENTS, BOARD APPOINTMENTS
    return out


def settle(lines, roll, why, away=()):
    """Read every vote in the lines of a meeting against its roll, and say who moved and seconded each motion.

    `away` are those the head of the minutes has excused for the day. A vote that has one of them voting is not read:
    the minutes say two things, and a mark has been seen to stand under the wrong number in just such a vote.
    """
    for line in lines:
        for motion in line["motions"]:
            moved = _MOTION.match(motion["text"])
            if moved:
                mover, seconder = who(moved[1], roll), who(moved[2], roll)
                if mover and seconder:
                    motion.update(mover=mover, seconder=seconder, text=clean(moved[3]))
            if not motion["block"]:
                if motion["code"] and roll:  # a mover, or a mover and a seconder, of a motion that was not put to a vote
                    seated = {str(member["district"]): member["name"] for member in roll}
                    motion["mover"] = seated.get(motion["code"][0], "")
                    motion["seconder"] = seated.get(motion["code"][1:2], "")
                continue
            if motion["code"]:
                cast, problem = read_code(motion["code"], motion["marks"], roll)
                if cast is not None:
                    motion["mover"], motion["seconder"] = cast[0][0], cast[1][0]
            else:
                cast, problem = read_block(motion["names"], roll)
            doubt = why or line["doubt"] or motion["doubt"]
            here = [member for member, word in cast or [] if member in away and word != council_tables.vote_word(MARKS["X"])]
            if doubt:
                cast, problem = None, doubt
            elif here:
                cast, problem = None, f"the head of the minutes has {here[0]} excused for the day, and this vote does not"
            motion.update(cast=cast or [], read=cast is not None, problem=problem)
    return lines


def covered(line):
    """The heading whose one vote took in this item: the consent calendar's, unless the motion left the item out."""
    heading = line["section"]
    if heading is None or line["heading"] or any(motion["block"] for motion in line["motions"]):
        return None
    voted = [motion for motion in heading["motions"] if motion["block"]]
    span = _RANGE.search(heading["title"])
    if len(voted) != 1 or not span or not line["number"].isdigit() or "CONSENT" not in heading["title"].upper():
        return None
    text, number = voted[0]["text"], int(line["number"])
    if not int(span[1]) <= number <= int(span[2]):
        return None
    # What the motion left out is said many ways ("WITH THE EXCEPTION OF ITEM 26 WHICH RECEIVED AN ABSTENTION ...;
    # ITEM 18 WHICH WAS CONTINUED TO 8/23/11; AND ITEMS 2, 3 & 17 WHICH WERE PULLED"), so every number after the
    # first such word is taken to be left out, days and times apart. That leaves out too much now and then, and
    # never too little.
    left_out = {int(digits) for digits in re.findall(r"\d+", _DATED.sub(" ", text[_EXCEPT.search(text).start():]))} if _EXCEPT.search(text) else set()
    return None if number in left_out else heading


def head_of(lines):
    """What the head of the minutes says of the meeting: its kind (Regular, Special), its day and the time it began."""
    top = " ".join(line.text for line in lines[:12])
    kind = next((_KIND.match(line.text)[1].title() for line in lines[:6] if _KIND.match(line.text)), "")
    day, when = _DAY.search(top), _WHEN.search(top)
    return {"kind": kind, "date": f"{day[3]}-{_MONTHS.index(day[1].lower()) + 1:02d}-{int(day[2]):02d}" if day else "",
            "time": f"{int(when[1])}:{when[2]} {when[3].upper()}M" if when else ""}


def read_minutes(text, meeting_id, date):
    """One meeting's minutes: its lines, the votes on each motion that read cleanly, and what the reading found."""
    facts = {"summary": "read", "format": "", "pages": text.count("\f") + 1, "roll": "", "vote_blocks": 0, "blocks_read": 0,
             "problem": "", "kind": "", "time": ""}
    lines = lines_of(text)
    if len(re.sub(r"\s", "", "".join(line.text for line in lines))) < LAYER_CHARS:
        return [], [], {**facts, "summary": "no text layer"}
    head = head_of(lines)
    facts.update(kind=head["kind"], time=head["time"])
    if any(re.sub(r"\s", "", line.text).upper().startswith("AGENDA") for line in lines[:3]):
        # A few of the archive's rows lead to the agenda, or to the list of what was added to it.
        return [], [], {**facts, "summary": "an agenda, not minutes"}
    if head["date"] and head["date"] != date:
        return [], [], {**facts, "summary": "minutes of another day", "problem": f"the minutes are headed {head['date']}"}
    form = form_of(lines)
    roll, why = roll_of(lines, form) if form else (seats_of(lines), "")
    facts.update(format=form, problem=why, roll=json.dumps(roll, ensure_ascii=False, separators=(",", ":")) if roll else "")
    parsed = settle(parse_names(lines, roll) if form == "names" else parse_codes(lines), roll, why, away_of(lines, roll))

    agenda, votes, sections, unnumbered, seen = [], [], 0, 0, collections.Counter()
    for line in parsed:
        if line["heading"]:
            sections += 1
            line["item_id"] = f"{meeting_id}-s{sections}"
        elif line["number"]:
            seen[line["number"]] += 1  # a number printed twice in one meeting's minutes is two lines
            line["item_id"] = f"{meeting_id}-{line['number']}" + (f"-{seen[line['number']]}" if seen[line["number"]] > 1 else "")
        else:
            unnumbered += 1
            line["item_id"] = f"{meeting_id}-u{unnumbered}"
    for sequence, line in enumerate(parsed, 1):
        item_id, heading = line["item_id"], line["heading"]
        matter_id = "" if heading else item_id
        for number, motion in enumerate(line["motions"], 1):
            for member, word in motion["cast"]:
                votes.append({"item_id": item_id, "meeting_id": meeting_id, "date": date, "matter_id": matter_id, "matter_file": "",
                              "member": member, "vote": word, "motion": number, "motion_text": motion["text"],
                              "code": motion["code"], "marks": motion["marks"] if motion["code"] else ""})
        blocks = [motion for motion in line["motions"] if motion["block"]]
        # What is said of the line is its last vote, or with no vote its last action.
        last = blocks[-1] if blocks else line["motions"][-1] if line["motions"] else None
        cast = [word for _, word in last["cast"]] if last else []
        over = covered(line)
        title = clean(line["title"])
        agenda.append({
            "item_id": item_id, "meeting_id": meeting_id, "date": date, "body": BODY,
            "agenda_number": line["number"], "sequence": sequence, "matter_id": matter_id, "matter_file": "", "title": title,
            "action": last["text"] if last else "",
            "result": "Fail" if last and _FAILED.search(last["text"]) else "",  # a motion that carried is not marked
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
            "doc_type": "" if heading else line["numbered"] or county.doc_type_of(title),
            "number": line["numbers"],
            "motion_log": json.dumps([{"motion": number, "action": motion["text"], "mover": motion["mover"], "seconder": motion["seconder"],
                                       "code": motion["code"], "marks": motion["marks"], "names": " ".join(motion["names"]),
                                       "block": motion["block"], "read": motion["read"], "problem": motion["problem"]}
                                      for number, motion in enumerate(line["motions"], 1)], ensure_ascii=False, separators=(",", ":")),
        })
        facts["vote_blocks"] += len(blocks)
        facts["blocks_read"] += sum(motion["read"] for motion in blocks)
    return agenda, votes, facts


def read_day(date, rows, out_dir, fresh=False):
    """One day's rows of the listing: (its meetings, their lines, their votes), or None if no document could be had.

    Each row's minutes are fetched (or taken from what is kept here), and rows with the same minutes are one meeting.
    A row whose document could not be had is in no meeting's `documents`, so the day is read again on the next run.
    A row the system answers with something that is not a PDF is kept as that ("!" and what was sent), and not asked
    for again: it is listed with the day's first meeting, or as a meeting whose minutes are `not a PDF`.
    """
    kept_in = Path(out_dir) / "text"
    kept_in.mkdir(parents=True, exist_ok=True)
    documents = []  # each: the key of its first row, its rows, its text, and its bytes if fetched in this reading
    others = []  # rows whose document is not a PDF, each with what was sent
    for row in rows:
        if not row["minutes_url"]:
            continue
        kept = kept_in / f"{row['key']}.txt"
        try:
            if kept.exists() and not fresh:
                text, body = kept.read_text(encoding="utf-8"), None
            else:
                body = fetch_pdf(row["minutes_url"])
                twin = next((document for document in documents if document["body"] is not None and same_bytes(document["body"], body)), None)
                text = f"={twin['key']}" if twin else pdf_text(body)
        except Refused:
            raise
        except NotPdf as e:
            log.warning(f"{date} {row['title']}: {e}")
            text, body = f"!{e}", None
        except Exception as e:
            log.warning(f"{date} {row['title']}: {type(e).__name__}: {e}")
            continue
        if text.startswith("!"):
            others.append((row, text[1:]))
            kept.write_text(text, encoding="utf-8")
            continue
        # A row kept as "=" and a key is the same document as that row's.
        twin = next((document for document in documents if text in (f"={document['key']}", document["text"])), None)
        if twin:
            twin["rows"].append(row)
            text = f"={twin['key']}"
        elif text.startswith("="):
            continue  # the same as a document that could not be had this time
        else:
            documents.append({"key": row["key"], "rows": [row], "text": text, "body": body})
        kept.write_text(text, encoding="utf-8")
    if not documents and others:
        return [{**unread(date, [row for row, _ in others]), "documents": json.dumps([row["key"] for row, _ in others]),
                 "summary": "not a PDF", "problem": others[0][1]}], [], []
    if not documents:
        return None
    # A day's meetings are its documents that are minutes: the regular meeting's first, then as the listing has them.
    # A document that is something else (an agenda, a scan) is a meeting only where the day has no minutes.
    for document in documents:
        document["facts"] = read_minutes(document["text"], date, date)[2]
    documents.sort(key=lambda document: (document["facts"]["summary"] != "read", document["facts"]["kind"] != "Regular"))
    beside = [row for document in documents[1:] if document["facts"]["summary"] != "read" for row in document["rows"]] + [row for row, _ in others]
    documents = [document for place, document in enumerate(documents) if place == 0 or document["facts"]["summary"] == "read"]
    meetings, agenda, votes = [], [], []
    for place, document in enumerate(documents):
        meeting_id = date if place == 0 else f"{date}-{place + 1}"  # a second meeting on one day
        lines, cast, facts = read_minutes(document["text"], meeting_id, date)
        first = document["rows"][0]
        document["rows"] = document["rows"] + (beside if place == 0 else [])
        titles = [row["title"] for row in document["rows"]] + ([row["title"] for row in rows if not row["minutes_url"]] if place == 0 else [])
        meetings.append({**unread(date, [first]), "meeting_id": meeting_id, "time": first["time"] or facts["time"],
                         "items": sum(not line["heading"] for line in lines), "name": "; ".join(dict.fromkeys(titles)),
                         "kind": facts["kind"], "documents": json.dumps([row["key"] for row in document["rows"]]),
                         **{name: facts[name] for name in ("summary", "format", "pages", "roll", "vote_blocks", "blocks_read", "problem")}})
        agenda.extend(lines)
        votes.extend(cast)
    return meetings, agenda, votes


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------

def items_table(agenda, meetings):
    """Every item in the minutes, with what was done with it: by a vote of its own, or failing that by its heading's.

    The system has no record of an item apart from its line in the minutes, so an item is here once for each meeting
    it came to.
    """
    of, minutes = agenda.set_index("item_id"), dict(zip(meetings["meeting_id"], meetings["minutes_url"]))
    rows = []
    for line in agenda[~agenda["heading"]].itertuples(index=False):
        own = line.vote_blocks > 0
        over = of.loc[line.voted_with] if not own and line.voted_with else None
        vote = line._asdict() if own else over.to_dict() if over is not None else None
        rows.append({
            "date": line.date, "matter_id": line.item_id, "matter_file": "", "doc_type": line.doc_type, "title": line.title,
            "body": line.body, "status": "", "year": int(line.date[:4]), "subject": line.group, "agenda_date": line.date,
            "passed_date": "",
            "last_action": line.action or (vote["action"] if vote else ""),
            "last_action_date": line.date if line.action or vote else "",
            "result": line.result,
            "ayes": int(vote["ayes"]) if vote else 0, "noes": int(vote["noes"]) if vote else 0,
            "mover": vote["mover"] if vote else "", "seconder": vote["seconder"] if vote else "",
            "times_on_agenda": 1, "url": minutes.get(line.meeting_id, ""),
            "item_id": line.item_id, "meeting_id": line.meeting_id, "section": line.section, "group": line.group,
            "action_on": "item" if own else "section" if over is not None else "",
            "votes_read": bool(vote["votes_read"]) if vote else None,
            "number": line.number,
        })
    out = pd.DataFrame(rows, columns=ITEM_COLUMNS)
    out["votes_read"] = out["votes_read"].astype("boolean")
    return out.sort_values(["date", "meeting_id", "matter_id"], ascending=[False, False, True]).reset_index(drop=True)


def members_table(votes, meetings):
    """Everyone in a vote that was read. The district and the office are those printed at the head of the newest
    minutes that list them; the minutes give no terms of office."""
    seat, newest = {}, []
    for meeting in meetings[meetings["roll"] != ""].sort_values("date").itertuples(index=False):
        newest = json.loads(meeting.roll)
        for member in newest:
            seat[member["name"]] = member
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
    days = days_of(rows)
    log.info(f"Orange County: {len(rows)} rows listed, for meetings on {len(days)} days")
    if len(days) < 100:
        raise RuntimeError("the listing of meetings came back nearly empty")

    agenda, votes, before_meetings = (council_tables.held(HF_REPO, out_dir, name, base) for name in ("agenda_items", "votes", "meetings"))
    before = 0 if votes is None else len(votes)
    if agenda is None or votes is None or before_meetings is None:
        agenda, votes = pd.DataFrame(columns=AGENDA_COLUMNS), pd.DataFrame(columns=VOTE_COLUMNS)
        before_meetings = pd.DataFrame(columns=MEETING_COLUMNS)
    found = {}  # the meetings read on each day
    for meeting in before_meetings[before_meetings["summary"] != ""].to_dict("records"):
        found.setdefault(meeting["date"], []).append(meeting)
    done = lambda date: {key for meeting in found.get(date, []) for key in json.loads(meeting["documents"])}
    recent = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    wanted = [date for date, listed_rows in days.items() if date >= f"{since}-01-01" and any(row["minutes_url"] for row in listed_rows)
              and (everything or date >= recent or not {row["key"] for row in listed_rows if row["minutes_url"]} <= done(date))]
    wanted.sort(reverse=True)  # the newest first: a room shows those
    waiting = len(wanted)
    wanted = wanted[:limit] if limit else wanted
    log.info(f"Reading the minutes of {len(wanted)} days of {waiting} not yet read or to be read again")

    def meetings_table():
        out = [meeting for date, listed_rows in days.items() for meeting in (found.get(date) or [unread(date, listed_rows)])]
        table = pd.DataFrame(out, columns=MEETING_COLUMNS).sort_values(["date", "meeting_id"]).reset_index(drop=True)
        count = agenda[~agenda["heading"].astype(bool)].groupby("meeting_id").size() if len(agenda) else {}
        table["items"] = table["meeting_id"].map(count).fillna(0).astype(int)
        for column in ("pages", "vote_blocks", "blocks_read"):
            table[column] = table[column].astype(int)
        return table

    read = 0
    for start in range(0, max(len(wanted), 1), every):
        some = wanted[start:start + every]
        new_agenda, new_votes, read_now = [], [], set()
        readings = county.together(lambda date: read_day(date, days[date], out_dir, fresh=not everything and date >= recent), some, "day")
        for date, reading in zip(some, readings):
            if reading is None:
                continue  # what is held for it stands, and the next run asks again
            read_now.add(date)
            found[date] = reading[0]
            new_agenda.extend(reading[1])
            new_votes.extend(reading[2])
        agenda = joined(agenda[~agenda["date"].isin(read_now)], pd.DataFrame(new_agenda, columns=AGENDA_COLUMNS))
        votes = joined(votes[~votes["date"].isin(read_now)], pd.DataFrame(new_votes, columns=VOTE_COLUMNS))
        agenda = agenda.sort_values(["date", "meeting_id", "sequence"]).reset_index(drop=True)
        votes = votes.sort_values(["date", "meeting_id", "item_id", "motion", "member"]).reset_index(drop=True)
        agenda, votes = typed(agenda, votes)
        council_tables.write_tables({"agenda_items": agenda, "votes": votes, "meetings": meetings_table()}, out_dir)
        read += len(read_now)
        log.info(f"Orange County: {min(start + every, len(wanted))} of {len(wanted)} days asked for, {len(votes)} votes held")
        if _refused.is_set():
            log.error("The host refused a request: no more is asked of it in this run")
            break

    meetings = meetings_table()
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
    names = votes[votes["code"] == ""] if len(votes) else votes
    facts = {
        "repo": HF_REPO, "first_meeting": read["date"].min() if len(read) else "", "last_meeting": read["date"].max() if len(read) else "",
        "first_vote": votes["date"].min() if len(votes) else "", "last_vote": votes["date"].max() if len(votes) else "",
        "first_named": names["date"].min() if len(names) else "",
        "n_read": f"{len(read):,}", "n_scans": f"{int((meetings['summary'] == 'no text layer').sum()):,}",
        "n_agendas": f"{int((meetings['summary'] == 'an agenda, not minutes').sum()):,}",
        "n_other": f"{int(meetings['summary'].isin(['not a PDF', 'minutes of another day']).sum()):,}",
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
        log.error(f"Orange County tables not uploaded: {e}")
        return False
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the Orange County Board's meetings, agendas and votes")
    parser.add_argument("--base", action="store_true", help="start from the tables written here, not the published ones")
    parser.add_argument("--all", action="store_true", help="read every document again")
    parser.add_argument("--since", type=int, default=FIRST_YEAR, help="read no meeting before this year")
    parser.add_argument("--max", type=int, default=0, help="days of meetings to read in one run (0 for all)")
    parser.add_argument("--out", default="", help="directory to write the tables into (minutes_pdf/orange-county if not given)")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the tables only")

    out_dir = Path(args.out) if args.out else OUT_DIR
    try:
        tables, read = build(args.base, args.all, out_dir, args.since, args.max)
    except Exception as e:
        log.error(f"Orange County tables not built: {type(e).__name__}: {e}")
        return 1
    pushed = False if args.no_upload else upload(tables, out_dir, args.write_card)
    meetings, agenda, votes, members = tables["meetings"], tables["agenda_items"], tables["votes"], tables["members"]
    blocks, clean_blocks = int(agenda["vote_blocks"].sum()), int(agenda["blocks_read"].sum())
    log.info(f"RESULT: orange-county items={len(tables['items'])} meetings={len(meetings)} "
             f"meetings_with_minutes={int((meetings['minutes_url'] != '').sum())} "
             f"minutes_read={int((meetings['summary'] == 'read').sum())} "
             f"no_text_layer={int((meetings['summary'] == 'no text layer').sum())} "
             f"agendas_not_minutes={int((meetings['summary'] == 'an agenda, not minutes').sum())} "
             f"not_a_pdf={int((meetings['summary'] == 'not a PDF').sum())} "
             f"another_days={int((meetings['summary'] == 'minutes of another day').sum())} agenda_items={len(agenda)} "
             f"votes={len(votes)} vote_blocks={blocks} blocks_read={clean_blocks} blocks_unread={blocks - clean_blocks} "
             f"members={len(members)} serving={int(members['serving'].sum())} days_read={read} "
             f"first_vote={votes['date'].min() if len(votes) else ''} last_vote={votes['date'].max() if len(votes) else ''} "
             f"refused={_refused.is_set()} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
