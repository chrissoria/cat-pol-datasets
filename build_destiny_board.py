#!/usr/bin/env python3
"""
Build, for a county board of supervisors that keeps its record in Destiny
Hosted (AgendaQuick), what a room in Capitol World is made from: its meetings,
what was on each agenda, what the board did with it, and how each member voted.

One source: the county's pages on the system's public site, at
public.destinyhosted.com/agenda_publish.cfm?id=<county>. The system has no API:
a month's meetings are a page, and so are a meeting's agenda and its minutes.
In the minutes the clerk's entry sits under the line it is about, and a vote is
that entry's own words ("MOVED BY: ... AYES: ... NOES: ..."), read here by
their labels. For the years before the minutes were pages they are documents
with the same words in them, and are read the same way from their text. What
differs from one county to the next is set out in BOARDS.

Each has a dataset of its own (chrissoria/<county>-board), with the five tables
every council's and board's dataset has (council_tables.py), in data/:
  items.parquet          every item put on an agenda
  meetings.parquet       one row per meeting of the board
  agenda_items.parquet   one row per line of a meeting's agenda or minutes, headings too, with what was done
  votes.parquet          one row per member and motion voted on
  members.parquet        one row per member seen voting at the board
They are kept here in destiny/<county>/.

Two ways to run it:

    python build_destiny_board.py --county yolo-county
        The routine run. Starts from the published tables, lists every month
        again, and reads again the meetings of the last 60 days and those to
        come, any not read before, and any whose minutes have come in since.

    python build_destiny_board.py --county yolo-county --base
        The same, starting from the tables written here. It can be stopped and
        started: the newest meetings are read first and what is read is kept.

    --all        read every meeting again, not only the recent and the unread
    --out DIR    where to write the tables
    --no-upload  write the tables but do not publish them
    --write-card publish the dataset card as well as the tables
"""

import argparse
import io
import logging
import re
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import pandas as pd
import pdfplumber
import requests
from bs4 import BeautifulSoup

import build_federal_bills as bills
import build_sd_county as county
import council_tables
from build_sd_county import clean, today

log = logging.getLogger(__name__)

HOST = "https://public.destinyhosted.com"
OUT_DIR = bills.SCRIPT_DIR / "destiny"
CARD_FILE = bills.SCRIPT_DIR / "README_destiny_board.md"  # one card for every county, with the county's own facts written in
TABLES = council_tables.TABLES
RECENT_DAYS = 60  # meetings this recent are read again: minutes are put up weeks after the meeting
SEEN_DAYS = 2  # someone is a member if they are named in votes on this many days: once may be a clerk's slip
SERVING_DAYS = 120  # the system keeps no terms of office; a member named in a vote this recently is taken to be serving

# `id` is the county's number in the system's addresses; `type` is the system's code for the board's meetings in its
# list of meeting types, under which it also files the board's special meetings and budget hearings; `body` is what
# the tables call them all.
BOARDS = {
    "yolo-county": {"id": "96561", "name": "Yolo", "type": "BOS", "body": "Board of Supervisors"},
}

ITEM_COLUMNS = council_tables.COLUMNS["items"] + ["item_id", "meeting_id", "section", "action_on", "minute_order"]
MEETING_COLUMNS = council_tables.COLUMNS["meetings"] + ["name", "video_url", "agenda_kind", "minutes_kind", "source"]
AGENDA_COLUMNS = council_tables.COLUMNS["agenda_items"] + ["heading", "section", "section_id", "subject", "motions", "minute_order",
                                                           "minutes", "doc_type", "url"]
VOTE_COLUMNS = council_tables.COLUMNS["votes"] + ["district", "motion", "motion_text", "minute_order", "name_in_minutes"]


def repo_of(key):
    return f"chrissoria/{key}-board"


def page_of(key, **query):
    """The address of one of the county's pages: a month's list, an agenda (`dsp="ag"`), minutes (`"min"`) or an item (`"agm"`)."""
    return f"{HOST}/agenda_publish.cfm?" + "&".join(f"{name}={value}" for name, value in {"id": BOARDS[key]["id"], **query}.items())


class Refused(Exception):
    """The host will not answer us as we are. Nothing more is asked of it in this run."""


refused = threading.Event()


def fetch(url, tries=4, raw=False):
    """One page, as text, or one document as it is (`raw`). A refusal (a bot check, a login, a 403) is not asked twice, here or
    anywhere else in the run."""
    for attempt in range(tries):
        if refused.is_set():
            raise Refused(f"not asked after a refusal: {url}")
        try:
            answer = requests.get(url, headers=county.HEADERS, timeout=90)
            head = answer.text[:3000].lower() if "html" in answer.headers.get("content-type", "") else ""
            if answer.status_code in (401, 403, 407, 429) or any(mark in head for mark in ("captcha", "access denied", "just a moment")):
                refused.set()
                raise Refused(f"HTTP {answer.status_code} from {urlsplit(url).netloc}")
            answer.raise_for_status()
            return answer.content if raw else answer.text
        except requests.RequestException as e:
            # A host that is not allowed will not be allowed on a second asking.
            if attempt == tries - 1 or isinstance(e, requests.exceptions.ProxyError):
                raise
            time.sleep(2 * (attempt + 1))


def plain(node):
    """What a piece of a page says, as one line."""
    return clean(node.get_text(" ").replace("\xa0", " ")) if node is not None else ""


def asked(url, name):
    """One part of an address's question: `seq` of `...&dsp=ag&seq=3934` is `3934`."""
    return (parse_qs(urlsplit(url).query).get(name) or [""])[0]


# ---------------------------------------------------------------------------
# The list of meetings
# ---------------------------------------------------------------------------

def years_of(page):
    """The years the system's own menu offers: as far back as it goes."""
    menu = BeautifulSoup(page, "html.parser").find("select", attrs={"name": "get_year"})
    return sorted(int(option["value"]) for option in menu.find_all("option")) if menu else []


def month_meetings(key, page):
    """The meetings on one month's page.

    A meeting's agenda and minutes are each a page of the system (`page`), a document put up in its place (`document`:
    the older years), or not there.
    """
    table = BeautifulSoup(page, "html.parser").find("table", id="meeting-table")
    rows = []
    for row in (table.find("tbody") or table).find_all("tr") if table else []:
        cells = row.find_all("td", recursive=False)
        if len(cells) < 3:
            continue
        try:
            date = datetime.strptime(plain(cells[0]), "%B %d, %Y").strftime("%Y-%m-%d")
        except ValueError:
            continue
        links = [urljoin(f"{HOST}/", cell.find("a")["href"]) if cell.find("a", href=True) else "" for cell in cells[:4]] + [""]
        agenda, minutes, other = links[0], links[2], links[3]
        kind = lambda url, dsp: "" if not url else "page" if asked(url, "dsp") == dsp else "document"
        agenda_kind, minutes_kind = kind(agenda, "ag"), kind(minutes, "min")
        # The agenda's number is the meeting's. A meeting older than the system's own pages has the folder its documents are in.
        folder = re.search(r"/(\d{8}_\d+)/", agenda or minutes)
        meeting_id = asked(agenda, "seq") if agenda_kind == "page" else folder[1] if folder else ""
        if not meeting_id:
            continue
        rows.append({
            "meeting_id": meeting_id, "date": date, "time": "", "body": BOARDS[key]["body"], "location": "",
            "url": page_of(key, dsp="min", seq=asked(minutes, "seq")) if minutes_kind == "page" else
                   page_of(key, dsp="ag", seq=meeting_id) if agenda_kind == "page" else minutes or agenda,
            "agenda_url": page_of(key, dsp="ag", seq=meeting_id) if agenda_kind == "page" else agenda,
            "minutes_url": page_of(key, dsp="min", seq=asked(minutes, "seq")) if minutes_kind == "page" else minutes,
            "items": 0, "name": plain(cells[1]),
            "video_url": other if other and urlsplit(other).netloc != urlsplit(HOST).netloc else "",  # the recording is kept elsewhere
            "agenda_kind": agenda_kind, "minutes_kind": minutes_kind, "source": "",
        })
    return rows


def listed(key):
    """Every meeting of the board the system lists, a month's page at a time."""
    board = BOARDS[key]
    years = years_of(fetch(page_of(key, mt=board["type"])))
    months = [(year, month) for year in years for month in range(1, 13)]
    pages = county.together(lambda at: fetch(page_of(key, mt=board["type"], get_month=at[1], get_year=at[0])), months, "month")
    if refused.is_set() or any(page is None for page in pages):
        raise RuntimeError(f"{sum(page is None for page in pages)} of {len(months)} months could not be listed")
    rows = [row for page in pages for row in month_meetings(key, page)]
    return list({row["meeting_id"]: row for row in rows}.values())


def meetings_table(rows):
    return pd.DataFrame(rows, columns=MEETING_COLUMNS).sort_values(["date", "meeting_id"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# A meeting's page
# ---------------------------------------------------------------------------

NUMBER = re.compile(r"^[0-9A-Za-z]{1,4}(?:\.[0-9A-Za-z]{1,3})*\.?$")  # 6. or 6.1 or A.
SEAT = re.compile(r"^(?:(?:VICE[- ]?)?CHAIR(?:MAN|WOMAN|PERSON)?\s*[,:]?\s*)?([A-Z][A-Za-z.'\- ]*?)\s*,?\s+DISTRICT\s+(\d+)$", re.I)


def text_of(node):
    """What a piece of a page says, with its own line breaks kept: a vote's labels each begin a line."""
    for string in node.find_all(string=True):
        string.replace_with(re.sub(r"\s+", " ", string.replace("\xa0", " ")))  # a break in the page's source is not one in its words
    for br in node.find_all("br"):
        br.replace_with("\n")
    for block in node.find_all(["p", "div", "li", "tr"]):
        block.insert_before("\n")
        block.append("\n")
    lines = (clean(line) for line in node.get_text(" ").split("\n"))
    return "\n".join(line for line in lines if line)


def lines_of(page):
    """A page's lines in order, [{kind, number, line, memo, title, entries}], and the words at its head.

    The agenda and the minutes are laid out the same way, as rows of a table. A row with a number is an item; a row
    that is one cell across is a heading, a main one (CONSENT AGENDA) where it is set in a box; and in the minutes a
    row set in from the left is what the clerk entered about the line above it.
    """
    lines, head = [], []
    for row in BeautifulSoup(page, "html.parser").find_all("tr"):
        if row.find_parent("td") is not None:
            continue  # a row of a table inside a cell is the page's own lay-out
        cells = row.find_all(["td", "th"], recursive=False)
        if row.find_parent("thead") is not None:
            head.append(text_of(row))  # the minutes' title page: who sat
            continue
        if "upperleft" in (row.get("class") or []):
            text = text_of(cells[-1]) if cells else ""
            if text and lines:
                lines[-1]["entries"].append(text)
            continue
        said = [(cell, plain(cell)) for cell in cells]
        numbers = [at for at, (cell, text) in enumerate(said) if NUMBER.match(text) and not cell.get("colspan")]
        anchor = row.find("a", id=re.compile(r"^ReturnTo\d+$"))
        if numbers or anchor is not None:
            after = said[numbers[0] + 1:] if numbers else said[1:]
            memo = row.find("a", href=re.compile(r"dsp=agm"))
            lines.append({"kind": "item", "number": said[numbers[0]][1].rstrip(".") if numbers else "",
                          "line": anchor["id"][len("ReturnTo"):] if anchor is not None else "",
                          "memo": asked(memo["href"], "seq") if memo is not None else "",
                          "title": clean(" ".join(text for cell, text in after)), "entries": []})
        elif len(cells) == 1 and cells[0].get("colspan") and said[0][1]:
            if len(re.findall(r"\bDISTRICT\s+\d", said[0][1])) > 1:
                head.append(text_of(cells[0]))  # an agenda's title page is rows like any others, down to who sits
                lines.clear()
                continue
            if row.find("a", href=re.compile("print_prompt")) is not None:
                continue  # the page's own buttons
            lines.append({"kind": "section" if cells[0].find("table") is not None else "heading", "number": "", "line": "",
                          "memo": "", "title": said[0][1], "entries": []})
    return lines, "\n".join(head)


def roster_of(head):
    """Who sat in each district, from the head of the minutes or the agenda: [(name, district)]."""
    seats = (SEAT.match(clean(line)) for line in head.split("\n"))
    return [(clean(seat[1]), int(seat[2])) for seat in seats if seat and clean(seat[1]).upper() != "VACANT"]


def named(roster, typed):
    """A member as the head of the page has them, from the surname the clerk typed in a vote: (name, district).

    A vote gives a surname ("Sandy") and the head of the page says who sat that day ("GARY SANDY, DISTRICT 3"), so the
    two together say who voted: there have been two Sandys. A name that is nobody's at the head, or two members', is
    kept as typed, with no district.
    """
    typed = clean(typed)
    fits = [seat for seat in roster if typed and re.search(r"(^|[ .])" + re.escape(typed) + "$", seat[0], re.I)]
    if len(fits) != 1:
        return typed, None
    name, district = fits[0]
    # The head is in capitals. The clerk's own spelling of the surname is kept where it has one of its own (McGowan).
    own = typed not in (typed.upper(), typed.lower())
    return name[:len(name) - len(typed)].title() + (typed if own else typed.title()), district


# ---------------------------------------------------------------------------
# Minutes kept as a document
# ---------------------------------------------------------------------------

ITEM_ROW = re.compile(r"^(\d{1,2}\.\d{2}|\d{1,3}\.)\s*(\S.*)$")  # 12. Approve, or in the older years 2.05 Adopt
ITEM_HEAD = re.compile(r"^Agenda Item(?: No\.?)?\s*(\d{1,2}\.\d{2}(?:\s?[A-Z](?:-?\d)?)?|\d{1,3})$")  # the oldest: the number on a line of its own
MAIN = ("consent agenda", "regular agenda", "time set agenda", "closed session", "adjournment")  # the oldest do not set these in capitals


def document_text(content):
    """The words of a document of minutes, a line at a time, without what is printed at the head and foot of every page."""
    with pdfplumber.open(io.BytesIO(content)) as document:
        pages = [[line for line in map(clean, (page.extract_text() or "").split("\n")) if line] for page in document.pages]
    # A page's head and foot are its first and last lines, and the same on most pages but for the page's number.
    shape = lambda line: re.sub(r"[\d\s]+", "#", line)
    edges = [{shape(line) for line in page[:2] + page[-2:] if not LABEL.match(line)} for page in pages]
    on = Counter(edge for page in edges for edge in page)
    printed = {edge for edge, count in on.items() if count >= max(3, 0.6 * len(pages))}
    return "\n".join(line for page in pages for at, line in enumerate(page)
                     if not (shape(line) in printed and (at < 2 or at >= len(page) - 2)))


def follows(number, last):
    """Whether an item numbered so can come after the last one. The numbers of an agenda run on from each other, and a
    figure that happens to begin a line of running text does not."""
    new, old = [int(part) for part in number.split(".")], [int(part) for part in last.split(".")] if last else None
    if old is None:
        return new[0] == 1 and new[-1] <= 1
    if len(new) != len(old):
        return False
    if len(new) == 1:
        return old[0] < new[0] <= old[0] + 5
    return (new[0] == old[0] and old[1] < new[1] <= old[1] + 5) or (old[0] < new[0] <= old[0] + 2 and new[1] <= 3)


def document_lines(text):
    """The lines of a document of minutes, as lines_of gives a page's: items by their numbers, main headings by their capitals.

    A document does not say where an item's own words end and the clerk's begin, so the item is taken to end at the
    first line that ends a sentence and is not gone on with, or before the first order or vote. The smaller headings
    (a department's name) are not told from the words around them, and stay at the foot of the entry above.
    """
    rows = [row for row in map(clean, text.split("\n")) if row]
    # Where items are headed "Agenda Item No. 3.01", a number or capitals at the start of a line are an item's own words.
    lines, last, headed = [], "", sum(1 for row in rows if ITEM_HEAD.match(row)) > 2
    blank = lambda kind, number, own: {"kind": kind, "number": number, "line": "", "memo": "", "title": "", "entries": [], "rows": own}
    for row in rows:
        item, head = ITEM_ROW.match(row), ITEM_HEAD.match(row) if headed else None
        number = item[1].rstrip(".") if item else ""
        capitals = row == row.upper() and re.search(r"[A-Z]{4}", row) and len(row) < 90 and not LABEL.match(row) and row[-1] not in ",;"
        main = row.lower().startswith(MAIN) and len(row) < 70 and row[-1] not in ".,;:"
        if head:
            lines.append(blank("item", head[1].replace(" ", ""), []))
        elif item and not headed and (follows(number, last) or not last and lines):  # under a heading the first may be any: a special meeting's
            last = number
            lines.append(blank("item", number, [item[2]]))
        elif (main if headed else capitals) and (lines or re.search(r"CALL TO ORDER|AGENDA|SESSION", row)):  # not the title page's capitals
            lines.append(blank("section", "", [row]))
        elif lines:
            lines[-1]["rows"].append(row)
    for line in lines:
        own, cut = line["rows"], min(1, len(line["rows"]))  # a heading, or an item under a number on a line of its own, is one line
        for at, row in enumerate(own if line["kind"] == "item" and not headed else []):
            cut, after = at + 1, own[at + 1] if at + 1 < len(own) else ""
            if ORDER.match(after) or LABEL.match(after) or row[-1] in ".):" and not re.match(r"[(a-z]", after):
                break  # a line that begins in small letters or a bracket goes on with the item: "(No general fund impact)"
        line["title"] = clean(" ".join(own[:cut]))
        line["entries"] = ["\n".join(own[cut:])] if own[cut:] else []
    return lines


def under(agenda, document):
    """The lines of an agenda's page, with what a document of minutes says under each of them.

    The page has the lines as the county set them, with their headings and the numbers of their memos; the document
    has what was done. They meet at an item's number and a main heading's words. None where a vote in the document
    would be left out because its line is not on the page: the document's own lines are used then.
    """
    squeezed = lambda text: re.sub(r"\W+", "", text).lower()
    items = {line["number"]: line for line in document if line["kind"] == "item"}
    sections = [line for line in document if line["kind"] == "section"]
    out = []
    for at, line in enumerate(agenda):
        line, found = dict(line, entries=[]), None
        out.append(line)
        if line["kind"] == "item":
            found = items.pop(line["number"], None)
        elif line["kind"] == "section":
            found = next((section for section in sections if squeezed(section["title"]) == squeezed(line["title"])), None)
            sections = [section for section in sections if section is not found]
        if found is None:
            continue
        # The document repeats the item's words before the clerk's, and the headings of the next item after them.
        rows, title = list(found["rows"]), squeezed(line["title"])
        for cut in range(1, len(rows) + 1):
            if squeezed(" ".join(rows[:cut])) == title:
                rows = rows[cut:]
                break
        else:
            rows = found["entries"][0].split("\n") if found["entries"] else []
        ahead = []
        for later in agenda[at + 1:]:
            if later["kind"] == "item":
                break
            ahead.append(squeezed(later["title"]))
        while rows and squeezed(rows[-1]) in ahead:
            rows.pop()
        line["entries"] = ["\n".join(rows)] if rows else []
    left = list(items.values()) + sections
    return None if any(motions_of(entry) for line in left for entry in line["entries"]) else out


# ---------------------------------------------------------------------------
# The clerk's words for a vote
# ---------------------------------------------------------------------------

MOVER_LABELS = {"MOVED BY": "mover", "MOTION BY": "mover", "MOTION": "mover", "SECONDED BY": "seconder", "SECOND BY": "seconder",
                "SECONDED": "seconder", "SECOND": "seconder"}
# A label, and the word its votes are kept under where that is not the label itself: one spelling for each kind of vote.
VOTE_LABELS = {"AYES": "", "AYE": "", "YES": "", "YEAS": "", "NOES": "", "NAYS": "", "ABSTAIN": "", "ABSTAINED": "ABSTAIN",
               "ABSTAINS": "ABSTAIN", "ABTAIN": "ABSTAIN", "ABSTENTIONS": "ABSTAIN", "ABSENT": "", "ABSENTS": "ABSENT",
               "RECUSE": "RECUSED", "RECUSED": "", "RECUSAL": "RECUSED", "RECUSALS": "RECUSED", "NOT PRESENT": "", "NOT VOTING": ""}
COUNTED = ("AYES", "AYE", "YES", "YEAS", "NOES", "NAYS")
LABEL = re.compile(r"\b(" + "|".join(sorted(list(MOVER_LABELS) + list(VOTE_LABELS), key=len, reverse=True)) + r")\s*:", re.I)
ORDER = re.compile(r"Minute\s+Order\s+(?:No\.?\s*)?([0-9]{2,4}\s*-\s*[0-9]+[A-Za-z]?)\s*[:.]?", re.I)
NOBODY = {"", "none", "n/a", "na", "0", "-"}


def names_of(text):
    """The members a label names: "Saylor, Provenza and Chamberlain." as three; "None." as nobody.

    The names are on the label's own line, and on the next where that line breaks off at a comma. Words that are not
    a list of names (a sentence that ran on after the label) are nobody: better no vote than a wrong one.
    """
    rows, text = text.split("\n"), ""
    for row in rows:
        text = f"{text} {row}"
        if not re.search(r"(,|\band)\s*$", row):
            break
    text = re.sub(r"\([^)]*\)", " ", text)
    parts = (clean(part).strip(" .;:/") for part in re.split(r",|;|\band\b|&|(?<=[a-z]{2})\.\s+(?=[A-Z])", text))
    names = [re.sub(r"^(Supervisors?|Chair|Vice[- ]Chair)\s+", "", part) for part in parts if part.lower() not in NOBODY]
    return [] if any(len(name.split()) > 4 or re.search(r"[\d:]", name) for name in names) else names


def motions_of(entry):
    """The motions in one entry of the minutes: [{minute_order, text, mover, seconder, votes: [(member, word)]}].

    A motion is the words up to its labels, and then the labels: who moved and seconded, and the members under each
    of AYES, NOES and the rest. An entry with no count of ayes and noes in it has no motions: it is the clerk's note.
    """
    found = [(label.start(), label.end(), label[1].upper()) for label in LABEL.finditer(entry)]
    said = lambda at: entry[found[at][1]:found[at + 1][0] if at + 1 < len(found) else len(entry)]
    motions, at, done = [], 0, 0
    while at < len(found):
        # One motion's labels run on from each other, with only names between them.
        first, run = at, {}
        while at < len(found):
            label = MOVER_LABELS.get(found[at][2], found[at][2])
            if label in run or (found[at][2] in MOVER_LABELS and any(seen in VOTE_LABELS for seen in run)):
                break  # a label a second time, or a mover after a count, is the next motion's
            run[label] = said(at)
            at += 1
        if not any(label in COUNTED for label in run):
            continue  # "Motion:" in a sentence, or a roll call's PRESENT and ABSENT
        before = entry[done:found[first][0]]
        done = found[at - 1][1] + len(said(at - 1).split("\n")[0])
        order = ORDER.search(before)  # the first: an order named after it is one the motion speaks of
        motion = {"minute_order": re.sub(r"\s+", "", order[1]) if order else "",
                  "text": clean(before[order.end():] if order else before).strip(" /"), "mover": "", "seconder": "", "votes": []}
        for label, names in run.items():
            if label in ("mover", "seconder"):
                motion[label] = (names_of(names.split("\n")[0].split("/")[0]) or [""])[0]
                continue
            word = council_tables.vote_word(VOTE_LABELS[label] or label)
            for name in names_of(names):
                if (name, word) not in motion["votes"]:  # the same vote entered twice is kept once
                    motion["votes"].append((name, word))
        motions.append(motion)
    return motions


def best(meeting):
    """What a meeting is read from: its minutes if they are a page or a document with words in it, or else its agenda's page."""
    return ("minutes" if meeting["minutes_kind"] == "page" else
            "minutes document" if meeting["minutes_kind"] == "document" and urlsplit(meeting["minutes_url"]).path.lower().endswith(".pdf")
            else "agenda" if meeting["agenda_kind"] == "page" else "")


def read_meeting(key, meeting):
    """One meeting, from its minutes or, where there are none yet, its agenda: its lines, and each member's vote on each motion.

    A motion sits on the line the clerk entered it under. A consent agenda is voted on as one, so its motion is on its
    heading and not on the items under it.
    """
    meeting_id, date, body, source = meeting["meeting_id"], meeting["date"], meeting["body"], best(meeting)
    if source == "minutes":
        lines, head = lines_of(fetch(meeting["minutes_url"]))
    else:
        lines, head = lines_of(fetch(meeting["agenda_url"])) if meeting["agenda_kind"] == "page" else ([], "")
        if source == "minutes document":
            text = document_text(fetch(meeting["minutes_url"], raw=True))
            written = document_lines(text)
            lines = (under(lines, written) if lines else None) or written
            head = head if roster_of(head) else "\n".join(text.split("\n")[:60])
    roster = roster_of(head)
    minutes_id = asked(meeting["minutes_url"], "seq") if source == "minutes" else ""
    agenda, votes, section, subject = [], [], None, ""
    for sequence, line in enumerate(lines, 1):
        item_id, heading = f"{meeting_id}-{sequence}", line["kind"] != "item"
        if line["kind"] == "section":
            section, subject = {"item_id": item_id, "title": line["title"]}, ""
        elif heading:
            subject = line["title"]
        matter_id = "" if heading else line["memo"] or item_id
        motions, seen, reached, quoted = [], set(), (0, 0), False
        for entry in line["entries"]:
            for motion in motions_of(entry):
                mark = (motion["minute_order"], motion["text"], tuple(motion["votes"]))
                number = tuple(int(part) for part in re.findall(r"\d+", motion["minute_order"])[:2])
                if mark in seen:
                    continue  # the same motion entered twice is kept once
                if len(number) == 2 and number[0] == reached[0] and number[1] < reached[1]:
                    log.info(f"{date}: order {motion['minute_order']} set out again under a later one, and left out")
                    quoted = True
                    continue  # an earlier meeting's order, quoted where its minutes are corrected, is not a vote of this one
                seen.add(mark)
                motions.append(motion)
                reached = number if len(number) == 2 else reached
        if quoted:
            # Which names belong to this meeting's own motion and which to the orders quoted cannot be told apart for
            # sure, so no vote is read off such a line: what the clerk entered stays in `action` and `minutes`.
            log.info(f"{date}: line {line['number'] or sequence} quotes an earlier meeting's orders; its votes are not read")
            motions = []
        for number, motion in enumerate(motions, 1):
            for typed, word in motion["votes"]:
                name, district = named(roster, typed)
                votes.append({"item_id": item_id, "meeting_id": meeting_id, "date": date, "matter_id": matter_id, "matter_file": "",
                              "member": name, "vote": word, "district": district, "motion": number, "motion_text": motion["text"],
                              "minute_order": motion["minute_order"], "name_in_minutes": typed})
        last = motions[-1] if motions else {}
        cast = [word for name, word in last.get("votes", [])]
        ayes, noes = cast.count(council_tables.AYE), cast.count(council_tables.NO)
        entered = clean(" ".join(line["entries"]))
        agenda.append({
            "item_id": item_id, "meeting_id": meeting_id, "date": date, "body": body,
            "agenda_number": line["number"], "sequence": sequence, "matter_id": matter_id, "matter_file": "",
            "title": line["title"],
            "action": last["text"] if last else entered,  # where no names were entered, what was done and no votes
            "result": "",  # the minutes have no mark of a motion carrying, and what number carries one depends on the motion
            "mover": named(roster, last.get("mover", ""))[0], "seconder": named(roster, last.get("seconder", ""))[0],
            "ayes": ayes, "noes": noes, "not_voting": len(cast) - ayes - noes,
            "heading": heading,
            "section": section["title"] if section and line["kind"] != "section" else "",
            "section_id": section["item_id"] if section and line["kind"] != "section" else "",
            "subject": "" if heading else subject,
            "motions": len(motions), "minute_order": last.get("minute_order", ""), "minutes": entered,
            "doc_type": "" if heading else county.doc_type_of(line["title"]),
            "url": "" if not line["memo"] else
                   page_of(key, dsp="agm", seq=line["memo"], rev=0, min=minutes_id, ln=line["line"]) if source == "minutes" else
                   page_of(key, dsp="agm", seq=line["memo"], rev=0, ag=meeting_id, ln=line["line"]),
        })
    return agenda, votes, source


def items_table(agenda, meetings):
    """Every item put on an agenda, with what was done with it: on its own motion, or failing that on its section's.

    An item the county wrote a memo for has that memo's number, and is here once however many agendas it was on, with
    the last thing done. An item with no memo (a call to order, a closed session) is here once for its line.
    """
    of = agenda.set_index("item_id")
    page = dict(zip(meetings["meeting_id"], meetings["url"]))
    rows = {}
    for line in agenda[~agenda["heading"]].itertuples(index=False):  # in order of date, so the last word on an item is the latest
        own = line.motions > 0
        over = of.loc[line.section_id] if not own and line.section_id in of.index and of.loc[line.section_id, "motions"] > 0 else None
        done = line._asdict() if own else over.to_dict() if over is not None else None
        earlier = rows.get(line.matter_id)
        rows[line.matter_id] = {
            "date": earlier["date"] if earlier else line.date,
            "matter_id": line.matter_id, "matter_file": line.matter_file,
            "doc_type": line.doc_type, "title": line.title, "body": line.body, "status": "",
            "year": int(line.date[:4]) if line.date[:4].isdigit() else 0,
            "subject": line.subject, "agenda_date": line.date,
            "passed_date": "",  # the system has no day an item passed: a motion that carried may have been one to deny or put off
            "last_action": line.action, "last_action_date": line.date if line.action or done else "",
            "result": done["result"] if done else "",
            "ayes": int(done["ayes"]) if done else 0, "noes": int(done["noes"]) if done else 0,
            "mover": done["mover"] if done else "", "seconder": done["seconder"] if done else "",
            "times_on_agenda": earlier["times_on_agenda"] + 1 if earlier else 1,
            "url": line.url or page.get(line.meeting_id, ""),
            "item_id": line.item_id, "meeting_id": line.meeting_id, "section": line.section,
            "action_on": "item" if own else "section" if over is not None else "",
            "minute_order": done["minute_order"] if done else "",
        }
    out = pd.DataFrame(list(rows.values()), columns=ITEM_COLUMNS)
    return out.sort_values(["agenda_date", "meeting_id", "item_id"], ascending=[False, False, True]).reset_index(drop=True)


def members_table(votes):
    """Everyone named in the board's votes on several days, with the district the head of the minutes gives them.

    The system keeps no terms of office: when someone was first and last named in a vote is what there is.
    """
    days = votes.groupby("member")["date"].nunique()
    cast = votes.groupby("member")["date"].agg(["min", "max", "size"])
    seat = votes.dropna(subset=["district"]).groupby("member")["district"].last()
    since = (datetime.now(timezone.utc) - timedelta(days=SERVING_DAYS)).strftime("%Y-%m-%d")
    rows = [{"name": name, "district": seat.get(name), "role": "", "start": "", "end": "",
             "serving": bool(cast.loc[name, "max"] >= since),
             "first_vote": cast.loc[name, "min"], "last_vote": cast.loc[name, "max"], "votes": int(cast.loc[name, "size"])}
            for name in sorted(days[days >= SEEN_DAYS].index) if name]
    out = pd.DataFrame(rows, columns=council_tables.COLUMNS["members"])
    out["district"] = pd.to_numeric(out["district"], errors="coerce").astype("Int64")
    out["serving"] = out["serving"].astype(bool)
    out["votes"] = out["votes"].astype(int)
    return out.sort_values(["first_vote", "name"]).reset_index(drop=True)


def seated(agenda, votes, days=200):
    """The oldest minutes have no list of who sat at their head. Their members are named from the nearest meeting that has one.

    A surname with no district beside it is looked for among the votes of the meetings within `days` that do have
    one; the nearest says who it was. A name found in none of them (a clerk's slip) is left as it was typed.
    """
    known = votes.dropna(subset=["district"]).drop_duplicates(["date", "name_in_minutes"])
    known = {typed: rows for typed, rows in known.groupby("name_in_minutes")}
    stamp = lambda date: datetime.strptime(date, "%Y-%m-%d").toordinal()

    def nearest(date, typed):
        rows = known.get(typed)
        if rows is None:
            return None
        gap = (rows["date"].map(stamp) - stamp(date)).abs()
        return rows.loc[gap.idxmin()] if gap.min() <= days else None

    votes, agenda = votes.copy(), agenda.copy()
    bare = votes[votes["district"].isna()]
    for (date, typed), rows in bare.groupby(["date", "name_in_minutes"]):
        found = nearest(date, typed)
        if found is not None:
            votes.loc[rows.index, ["member", "district"]] = [found["member"], found["district"]]
    headless = set(bare["meeting_id"]) - set(votes.loc[votes["district"].notna() & ~votes.index.isin(bare.index), "meeting_id"])
    for at, line in agenda[agenda["meeting_id"].isin(headless) & (agenda["motions"] > 0)].iterrows():
        for column in ("mover", "seconder"):
            found = nearest(line["date"], line[column])
            if found is not None:
                agenda.loc[at, column] = found["member"]
    return agenda, votes


def time_of(title):
    """`9:00 A.M. CALL TO ORDER` as `9:00 AM`: the hour a meeting was called for is the first heading of its agenda."""
    found = re.match(r"(\d{1,2}:\d\d)\s*([AP])\.?\s*M\b", str(title or ""), re.I)
    return f"{found[1]} {found[2].upper()}M" if found else ""


def joined(held, new):
    """Two tables of the same columns as one. An empty one adds nothing, and is left out so it cannot change a column's kind."""
    some = [table for table in (held, new) if len(table)]
    return pd.concat(some, ignore_index=True) if some else held


def build(key, base, everything, out_dir, every=100):
    board = BOARDS[key]
    listing = listed(key)
    log.info(f"{board['name']}: {len(listing)} meetings listed")
    if len(listing) < 10:
        raise RuntimeError("the listing of meetings came back nearly empty")
    meetings = meetings_table(listing)

    was, agenda, votes = (council_tables.held(repo_of(key), out_dir, name, base) for name in ("meetings", "agenda_items", "votes"))
    before = 0 if votes is None else len(votes)
    if was is None or agenda is None or votes is None or "source" not in was.columns:
        was, agenda, votes = pd.DataFrame(columns=MEETING_COLUMNS), pd.DataFrame(columns=AGENDA_COLUMNS), pd.DataFrame(columns=VOTE_COLUMNS)
    # What each meeting was last read from. One read from its agenda is read again once its minutes are up.
    meetings["source"] = meetings["meeting_id"].map(dict(zip(was["meeting_id"], was["source"]))).fillna("")
    read_from = dict(zip(meetings["meeting_id"], meetings["source"]))
    recent = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    wanted = [meeting for meeting in listing if best(meeting)
              and (everything or read_from[meeting["meeting_id"]] != best(meeting) or meeting["date"] >= recent)]
    wanted.sort(key=lambda meeting: meeting["date"], reverse=True)  # the newest first: a room shows those
    log.info(f"Reading {len(wanted)} meetings")

    read = 0
    for start in range(0, max(len(wanted), 1), every):
        some = wanted[start:start + every]
        new_agenda, new_votes, done = [], [], {}
        for meeting, found in zip(some, county.together(lambda meeting: read_meeting(key, meeting), some, "meeting")):
            if found is None:
                continue  # what is held for it stands, and the next run asks again
            done[meeting["meeting_id"]] = found[2]
            new_agenda.extend(found[0])
            new_votes.extend(found[1])
        new_agenda = pd.DataFrame(new_agenda, columns=AGENDA_COLUMNS)
        new_votes = pd.DataFrame(new_votes, columns=VOTE_COLUMNS)
        agenda = joined(agenda[~agenda["meeting_id"].isin(done)], new_agenda)
        votes = joined(votes[~votes["meeting_id"].isin(done)], new_votes)
        agenda = agenda.sort_values(["date", "meeting_id", "sequence"]).reset_index(drop=True)
        votes["sequence"] = votes["item_id"].str.rsplit("-", n=1).str[-1].astype(int)
        votes = votes.sort_values(["date", "meeting_id", "sequence", "motion"], kind="stable").drop(columns="sequence").reset_index(drop=True)
        for table, columns in ((agenda, ("sequence", "ayes", "noes", "not_voting", "motions")), (votes, ("motion",))):
            for column in columns:
                table[column] = table[column].astype(int)
        agenda["heading"] = agenda["heading"].astype(bool)
        votes["district"] = pd.to_numeric(votes["district"], errors="coerce").astype("Int64")
        meetings["source"] = meetings["meeting_id"].map(done).fillna(meetings["source"])
        council_tables.write_tables({"meetings": meetings, "agenda_items": agenda, "votes": votes}, out_dir)
        read += len(done)
        log.info(f"{board['name']}: {min(start + every, len(wanted))} of {len(wanted)} meetings asked for, {len(votes)} votes held")
        if refused.is_set():
            raise RuntimeError("the host refused us; what was read before it did is kept")

    agenda, votes = seated(agenda, votes)
    meetings["items"] = meetings["meeting_id"].map(agenda[~agenda["heading"]].groupby("meeting_id").size()).fillna(0).astype(int)
    meetings["time"] = meetings["meeting_id"].map(agenda[agenda["heading"]].groupby("meeting_id")["title"].first().map(time_of)).fillna("")
    tables = council_tables.standard({
        "items": items_table(agenda, meetings), "meetings": meetings, "agenda_items": agenda, "votes": votes,
        "members": members_table(votes),
    })
    council_tables.write_tables(tables, out_dir)
    if len(votes) < before * 0.98:
        raise RuntimeError(f"only {len(votes)} votes where there were {before}; not publishing")
    return tables, read


def card(key, tables):
    """The dataset card: the one every county has, with this one's name, addresses and counts written in."""
    board, meetings, votes = BOARDS[key], tables["meetings"], tables["votes"]
    read, pages = meetings[meetings["items"] > 0], meetings[meetings["source"] == "minutes"]
    facts = {
        "title": f"{board['name']} County {board['body']}", "place": board["name"], "repo": repo_of(key), "id": board["id"],
        "type": board["type"], "body": board["body"],
        "first_listed": meetings["date"].min(), "last_listed": meetings["date"].max(),
        "first_meeting": read["date"].min() if len(read) else "", "last_meeting": read["date"].max() if len(read) else "",
        "first_page": pages["date"].min() if len(pages) else "",
        "first_vote": votes["date"].min() if len(votes) else "", "last_vote": votes["date"].max() if len(votes) else "",
        "vote_words": ", ".join(f"`{word}`" for word in votes["vote"].value_counts().index),
        "serving_days": SERVING_DAYS, "seen_days": SEEN_DAYS,
        **{f"n_{source.replace(' ', '_')}": f"{int((meetings['source'] == source).sum()):,}" for source in ("minutes", "minutes document", "agenda")},
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
    parser = argparse.ArgumentParser(description="Build a Destiny Hosted county's meetings, agendas and votes")
    parser.add_argument("--county", "--body", required=True, choices=sorted(BOARDS), help="the county whose board to read")
    parser.add_argument("--base", action="store_true", help="start from the tables written here, not the published ones")
    parser.add_argument("--all", action="store_true", help="read every meeting again")
    parser.add_argument("--out", default="", help="directory to write the tables into (destiny/<county> if not given)")
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
    agenda, votes, members, meetings = tables["agenda_items"], tables["votes"], tables["members"], tables["meetings"]
    log.info(f"RESULT: destiny-{args.county} items={len(tables['items'])} meetings={len(meetings)} "
             f"meetings_with_agenda={agenda['meeting_id'].nunique()} "
             f"from_minutes={int((meetings['source'] == 'minutes').sum())} "
             f"from_minutes_document={int((meetings['source'] == 'minutes document').sum())} "
             f"from_agenda={int((meetings['source'] == 'agenda').sum())} agenda_items={len(agenda)} votes={len(votes)} "
             f"motions_voted_on={len(votes.drop_duplicates(['item_id', 'motion']))} members={len(members)} "
             f"serving={int(members['serving'].sum())} voters_not_members={len(set(votes['member']) - set(members['name']))} "
             f"meetings_read={read} first_vote={votes['date'].min() if len(votes) else ''} "
             f"last_vote={votes['date'].max() if len(votes) else ''} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
