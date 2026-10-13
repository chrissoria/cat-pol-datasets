#!/usr/bin/env python3
"""
Build chrissoria/los-angeles-county-board: the meetings of the Los Angeles
County Board of Supervisors, what came before each, what the Board did with it,
and how each supervisor voted.

One source: the Board's Statements of Proceedings, the Executive Office's own
record of each meeting, kept as PDFs on file.lacounty.gov. The County's page
for them (lacounty.gov/sop) fills its list from a search index, and the list
here is asked of that index as the page asks it. The County's Legistar API has
about fifty of the Board's meetings and hardly a vote, so nothing is taken
from it.

From 17 February 2009 a statement is printed out of the County's agenda system
in one form: each matter ends with its file number, then what was done, then
the vote by name with a count before each list

    ... as requested at the Board meeting of October 3, 2023. (23-3603)
    On motion of Supervisor Horvath, seconded by Supervisor Solis, this item was
    continued to June 3, 2025.
    Ayes: 4 - Supervisor Solis, Supervisor Mitchell, Supervisor
    Horvath and Supervisor Barger
    Absent: 1 - Supervisor Hahn
    Attachments: Public Comment/Correspondence

A block is read whole or not at all. Each list must be nothing but supervisors
and as many as its count; every name must be on the roll at the head of that
statement (those present and those absent); nobody may be named twice. A block
that does not pass, or one that does not stand where a vote stands (after its
matter's file number and before its attachments), is left out of the votes:
the motion is kept, with what stopped the reading (`problem`), and counted as
unread.

Earlier statements are listed and not read. From 21 October 2008 to 10
February 2009 they name who voted, but in an earlier form of the page: a
matter's attachments stand before what was done with it, and the names are set
around their count ("Supervisor Molina, Supervisor Yaroslavsky," / "Ayes: 4 -"
/ "Supervisor Antonovich and Supervisor Burke"), so that a list cannot be told
from the line beside it. Before 21 October 2008 a statement says "Vote:
Unanimously carried" and names nobody but the absent.

The dataset has the five tables every council's and board's dataset has
(council_tables.py), in data/:
  items.parquet          every matter (file number) in a statement that was read
  meetings.parquet       one row per statement listed
  agenda_items.parquet   one row per matter in a statement, headings too, with what was done
  votes.parquet          one row per supervisor and motion voted on
  members.parquet        one row per supervisor seen in a block
They are kept here in minutes_pdf/los-angeles-county/, with the text of each
statement beside them in text/, so a statement is fetched once.

Two ways to run it:

    python build_la_county_board.py
        The routine run. Starts from the published tables, lists every
        statement again, and reads those not read before and those of
        meetings in the last 60 days (a statement is posted a week or two
        after its meeting, and a signed copy may replace it).

    python build_la_county_board.py --base
        The same, starting from the tables written here. It reads the newest
        meeting first and can be stopped and started again.

    --since DAY   read no meeting before this day or year (default 2009-02-17, where the form begins)
    --max N       statements to read in one run (default 0, for all)
    --all         read every statement again, from the text kept here where there is some
    --out DIR     where to write the tables
    --no-upload   write the tables but do not publish them
    --write-card  publish the dataset card as well as the tables

Needs pdfplumber. Only a PDF's own text is read: a statement that is a scan is
counted and left.
"""

import argparse
import concurrent.futures
import io
import json
import logging
import re
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd
import requests

import build_federal_bills as bills
import build_sd_county as county
import council_tables
from build_sd_county import clean, today

log = logging.getLogger(__name__)

HF_REPO = "chrissoria/los-angeles-county-board"
OUT_DIR = bills.SCRIPT_DIR / "minutes_pdf" / "los-angeles-county"
CARD_FILE = bills.SCRIPT_DIR / "README_la_county_board.md"
TABLES = council_tables.TABLES
BODY = "Board of Supervisors"

PAGE = "https://lacounty.gov/government/board-of-supervisors/statement-of-proceedings/"  # the County's list of statements
FILES = "https://file.lacounty.gov/SDSInter/bos/sop/"  # where every statement is kept; nothing is fetched from anywhere else
FIRST_DAY = "2009-02-17"  # the first statement printed in the form read here
RECENT_DAYS = 60  # meetings this recent are read again: a signed copy may replace the first one posted
LAYER_CHARS = 200  # a statement with fewer characters of its own than this is a scan
WINDOW = 1000  # the most rows the index gives to one question

MEETING_COLUMNS = council_tables.COLUMNS["meetings"] + ["name", "kind", "listed_date", "file", "summary", "pages", "roll",
                                                        "vote_blocks", "blocks_read"]
AGENDA_COLUMNS = council_tables.COLUMNS["agenda_items"] + [
    "heading", "section", "group", "text", "motions", "vote_blocks", "blocks_read", "votes_read", "problem", "doc_type",
    "motion_log"]
VOTE_COLUMNS = council_tables.COLUMNS["votes"] + ["motion", "motion_text"]
ITEM_COLUMNS = council_tables.COLUMNS["items"] + ["item_id", "meeting_id", "votes_read"]

# A statement names a supervisor by surname alone. These are the full names and the districts of everyone who has sat
# on the Board since the statements began to name who voted (October 2008); a surname not listed is kept as the
# statement prints it.
KNOWN = {
    "Molina": ("Gloria Molina", 1), "Solis": ("Hilda L. Solis", 1),
    "Burke": ("Yvonne B. Burke", 2), "Ridley-Thomas": ("Mark Ridley-Thomas", 2), "Mitchell": ("Holly J. Mitchell", 2),
    "Yaroslavsky": ("Zev Yaroslavsky", 3), "Kuehl": ("Sheila Kuehl", 3), "Horvath": ("Lindsey P. Horvath", 3),
    "Knabe": ("Don Knabe", 4), "Hahn": ("Janice Hahn", 4),
    "Antonovich": ("Michael D. Antonovich", 5), "Barger": ("Kathryn Barger", 5),
}

# The words a block sorts the supervisors under, and the word each is here. Ayes and noes are spelled as every
# council's are (council_tables.vote_word); the others are the Board's own, in the form the other boards' have.
# The statements of the budget deliberations say Aye, No and Abstain.
LABELS = {"Ayes": "AYES", "Aye": "AYES", "Noes": "NOES", "No": "NOES", "Abstentions": "ABSTAIN", "Abstain": "ABSTAIN",
          "Absent": "ABSENT", "Recuse": "RECUSED"}
OPENING = ("Ayes", "Aye")  # the word a block begins with

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_FOOT = re.compile(r"^County of Los Angeles Page \d+$")  # the foot of each page
# and its top: "Board of Supervisors Statement Of Proceedings May 6, 2025", "Budget Deliberation Statement Of Proceedings - Final June 23, 2014"
_TOP = re.compile(rf"^(?:[A-Za-z][A-Za-z-]* ){{0,8}}Statement Of Proceedings(?: - Final)?(?: ?(?:{_MONTHS}) ?\d{{1,2}}\b.{{0,40}}\d{{4}})?$")
_DAY = re.compile(rf"^(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day, ({_MONTHS}) (\d{{1,2}}), (\d{{4}})$")
_TIME = re.compile(r"^(\d{1,2}:\d{2}) ?([AP])\.?M\.?$", re.I)
_KIND = re.compile(r"STATEMENT OF PROCEEDINGS FOR THE (.+?) OF THE BOARD OF SUPERVISORS")
_ROLL = re.compile(r"^(Present|Absent)\s*:\s*(Supervisor\b.*)$")
_SECTION = re.compile(r"^([IVX]{1,5})\.\s*([A-Z][A-Z0-9 ,/&'’().:-]{4,}?)(?:\s+(\d+(?:-[A-Z])?(?:\s*-\s*\d+(?:-[A-Z])?)?))?$")
_GROUP = re.compile(r"^([A-Z][A-Z ,/&'’-]{6,}?)\s+\d+(?:-[A-Z])?(?:\s*-\s*\d+(?:-[A-Z])?)?$")  # "ADMINISTRATIVE MATTERS 24 - 63"
# A matter's file number, which ends what the statement says the matter is. A standing matter (the local emergencies
# continued from meeting to meeting, the report of the closed session) has letters and a number in its place: (A-1),
# (CSR-12). Once the brackets were printed with half the number: (24-).
_FILE = re.compile(r"\((\d{2}-\d{4}|(?:A|CSR)-\d{1,3}|\d{2}-)\)$")
_FILE_BROKEN = re.compile(r"\(\d{2}-$")  # a file number that the line's end has cut in two
# What a matter opens with: 12. 2a. S-1. CS-2. 1-D. 1-PA. 65-A. and "Set Matter 1.", which is printed several ways.
_NUMBERED = re.compile(r"^(?:(Set Matter)\s*-?\s*(\d{1,2})\.?|([A-Z]{1,2}-\d{1,2}|\d{1,3}-[A-Z]{1,2}|\d{1,3}[a-z]?)\.(?!\d))\s*(.*)$")
_LABEL = re.compile(r"^([A-Z][a-z]+)\s*:\s*(\d+)\s*-\s*(.*)$")  # "Ayes: 4 - Supervisor Solis, ..."
_TITLED = re.compile(r",\s*(?:Chair(?:man|woman)?|Mayor)(?: Pro Tem)?\s*$")  # the office printed after the last name on a roll
_ATTACHED = re.compile(r"^Attachments\s*:")
_NAME = re.compile(r"Supervisor ([A-Z][A-Za-z'’.-]*(?: [A-Z][A-Za-z'’.-]*){0,2})")
_OPEN = re.compile(r"(?:,|\band|\bSupervisor|-)$")  # a list of names that has not ended where its line ends
_MOVED = re.compile(r"[Oo]n motion of Supervisor ([A-Z][A-Za-z'’-]+),? (?:and )?seconded by Supervisor ([A-Z][A-Za-z'’-]+)")
_ACTED = re.compile(r"(?:(?:After|Following)(?: further| a)? discussion, |Later in the meeting, )?(?:[Oo]n motion of|[Bb]y Common Consent)")
_FAILED = re.compile(r"\bfailed to carry\b|\bmotion failed\b|\bfailed for lack\b|\bfailed by the following vote\b", re.I)
_RECOMMENDED = re.compile(r"^(?:Revised |Substitute |Joint )?[Rr]ecommendation\b")


class Refused(Exception):
    """A host answered with a check, a login or a refusal. It is not asked again in this run."""


_refused = set()  # the hosts that have refused
_CHECK = re.compile(r"captcha|cf-challenge|are you a human|access denied|incident id|request unsuccessful|sign in to continue", re.I)


def fetch(url, tries=4, post=None, headers=None):
    """One answer from one of the County's hosts. A refusal is not tried again, and nothing more is asked of that host in this run."""
    host = urlsplit(url).netloc
    if host in _refused:
        raise Refused(f"{host} refused an earlier request")
    for attempt in range(tries):
        try:
            sent = {**county.HEADERS, **(headers or {})}
            answer = requests.post(url, json=post, headers=sent, timeout=120) if post is not None else requests.get(url, headers=sent, timeout=120)
            if answer.status_code in (401, 403, 429):
                _refused.add(host)
                raise Refused(f"{answer.status_code} from {host}")
            answer.raise_for_status()
            return answer
        except requests.RequestException as e:
            # A host that is not allowed will not be allowed on a second asking.
            if attempt == tries - 1 or isinstance(e, requests.exceptions.ProxyError):
                raise
            time.sleep(2 * (attempt + 1))


def challenged(answer, url):
    """Stop asking a host that sent a page where a document was due, if the page is a check of who is asking."""
    if _CHECK.search(answer.text[:20000]):
        host = urlsplit(url).netloc
        _refused.add(host)
        raise Refused(f"a check from {host}")


# ---------------------------------------------------------------------------
# The listing
# ---------------------------------------------------------------------------

_SEARCH = re.compile(r"algoliasearch\(\s*'([A-Za-z0-9]+)'\s*,\s*'([A-Za-z0-9]+)'\s*\)")
_INDEX = re.compile(r"indexNames\s*=\s*\[\s*'([A-Za-z0-9_-]+)'")
_LISTED_DAY = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})\b")
_WANTED = ["sds_doc_id", "sds_title", "sds_document_dt", "date", "sds_published_url", "object_name"]


def index_of(page):
    """Where the County's page asks for its list: (the search's address, what it sends with each question).

    The page is public and carries the name of its search and a key that can only read; they are taken from the page
    each run and kept nowhere.
    """
    search, index = _SEARCH.search(page), _INDEX.search(page)
    if not search or not index:
        return None
    return (f"https://{search[1]}-dsn.algolia.net/1/indexes/{index[1]}/query",
            {"X-Algolia-Application-Id": search[1], "X-Algolia-API-Key": search[2]})


def row_of(hit):
    """One statement as the index has it, or None if it has no day or is not one of the County's files."""
    when = _LISTED_DAY.match(str(hit.get("sds_document_dt") or ""))
    if when:
        date = f"{when[3]}-{int(when[1]):02d}-{int(when[2]):02d}"
    elif str(hit.get("date") or "").lstrip("-").isdigit():
        date = (datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=int(hit["date"]))).strftime("%Y-%m-%d")
    else:
        return None
    url = str(hit.get("sds_published_url") or "")
    if not hit.get("sds_doc_id") or not (url.startswith(FILES) and url.lower().endswith(".pdf")):
        return None
    return {"meeting_id": str(hit["sds_doc_id"]), "name": clean(hit.get("sds_title")), "date": date, "minutes_url": url,
            "file": clean(hit.get("object_name"))}


def stamp(year):
    return int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def listed():
    """Every statement the County's page can list, whatever its year.

    The index gives a thousand rows to a question at most, so a span of days that holds more is cut in two and each
    half asked for.
    """
    page = fetch(PAGE)
    where = index_of(page.text)
    if where is None:
        challenged(page, PAGE)
        raise RuntimeError("the County's page no longer says where its list is kept")
    address, sent = where
    rows, spans = {}, [(stamp(1900), stamp(datetime.now(timezone.utc).year + 2))]
    while spans:
        first, last = spans.pop()
        answer = fetch(address, headers=sent, post={
            "query": "", "hitsPerPage": WINDOW, "attributesToRetrieve": _WANTED, "attributesToHighlight": [], "attributesToSnippet": [],
            "filters": f'sds_org_subfolder:"SOP" AND date >= {first} AND date < {last}'}).json()
        if answer.get("nbHits", 0) > len(answer.get("hits", [])) and last - first > 86400000:
            middle = (first + last) // 2
            spans += [(first, middle), (middle, last)]
            continue
        for hit in answer.get("hits", []):
            row = row_of(hit)
            if row:
                rows[row["meeting_id"]] = row
        time.sleep(0.3)
    return list(rows.values())


def meetings_table(rows):
    """One row per statement listed. What a reading adds (the time, `kind`, `summary`, `roll` and the counts) is filled in by build()."""
    out = [{
        "meeting_id": row["meeting_id"], "date": row["date"], "time": "", "body": BODY, "location": "", "url": PAGE,
        "agenda_url": "", "minutes_url": row["minutes_url"], "items": 0, "name": row["name"], "kind": "",
        "listed_date": row["date"], "file": row["file"], "summary": "", "pages": 0, "roll": "", "vote_blocks": 0, "blocks_read": 0,
    } for row in rows]
    return pd.DataFrame(out, columns=MEETING_COLUMNS).sort_values(["date", "meeting_id"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# A statement's text
# ---------------------------------------------------------------------------

def pdf_text(body):
    """The text a PDF carries, a page at a time. Nothing is read off the picture of a page."""
    import pdfplumber
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    with pdfplumber.open(io.BytesIO(body)) as document:
        return [page.extract_text() or "" for page in document.pages]


_readers, _readers_lock = None, threading.Lock()


def pages_of(body):
    """pdf_text(), done in another process: reading a PDF is slow work, and four at once in one process go no faster than one."""
    global _readers
    with _readers_lock:
        if _readers is None:
            _readers = concurrent.futures.ProcessPoolExecutor(county.WORKERS)
    return _readers.submit(pdf_text, body).result(timeout=900)


def text_of(meeting, out_dir, fresh=False):
    """The text of a meeting's statement, pages parted by form feeds: from the copy kept here, or fetched and kept."""
    kept = Path(out_dir) / "text" / f"{meeting['meeting_id']}.txt"
    if kept.exists() and not fresh:
        return kept.read_text(encoding="utf-8")
    url = meeting["minutes_url"]
    if not url.startswith(FILES):
        raise ValueError("not one of the County's files")
    time.sleep(0.3)
    answer = fetch(url)
    if answer.content[:4] != b"%PDF":
        challenged(answer, url)
        raise ValueError("the County sent a page in place of the statement")
    text = "\f".join(pages_of(answer.content))
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(text, encoding="utf-8")
    return text


def lines_of(text):
    """A statement's lines in order, without the top and the foot of each page: a block or a title often runs over a page's end.

    A matter set for a time has its number printed in a narrow column, and the text takes it apart:
    "Set <title>" / "Matter" / "1. <what is asked>". The three are put back together as "Set Matter 1. <title>".
    A file number cut in two by the end of a line is put back together too.
    """
    lines = (clean(line) for line in text.replace("\f", "\n").split("\n"))
    lines = [line for line in lines if line and not _FOOT.match(line) and not _TOP.match(line)]
    out, index = [], 0
    while index < len(lines):
        line = lines[index]
        numbered = re.match(r"^(\d{1,2})\.\s*(.*)$", lines[index + 2]) if index + 2 < len(lines) else None
        if line.startswith("Set ") and lines[index + 1:index + 2] == ["Matter"] and numbered:
            out += [f"Set Matter {numbered[1]}. {line[4:]}"] + ([numbered[2]] if numbered[2] else [])
            index += 3
            continue
        if _FILE_BROKEN.search(line) and index + 1 < len(lines) and re.match(r"\d{4}\)", lines[index + 1]):
            line, lines[index + 1] = line + lines[index + 1][:5], lines[index + 1][5:].strip()  # "(26-" / "6112)"
        if line:
            out.append(line)
        index += 1
    return out


# ---------------------------------------------------------------------------
# Who sits on the Board, and who a name is
# ---------------------------------------------------------------------------

def names_of(text):
    """The supervisors a list names, as printed, or None if it is anything but a list of them.

    "Supervisor Solis, Supervisor Hahn and Supervisor Barger" is three. A list with other words in it, or one that
    has run into the line after it, is nobody.
    """
    names = []
    for part in re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+", clean(text)):
        found = _NAME.fullmatch(part)
        if not found:
            return None
        names.append(found[1])
    return names


def surname(name):
    return clean(name).split()[-1] if clean(name) else ""


def member_of(name):
    """The name a supervisor has in the tables: in full where KNOWN has it, else as printed."""
    return KNOWN.get(surname(name), (clean(name), None))[0]


def joined_list(text, line):
    """A list of names with the next line of it joined on. A surname broken at its hyphen is joined without a space."""
    return text + line if re.search(r"[A-Za-z]-$", text) else f"{text} {line}"


def head_of(lines):
    """What the head of a statement says of the meeting: its day, its time, what kind it was, and the roll.

    The roll is everyone the head lists, present or absent, as (surname, "Present" or "Absent"). It is empty if the
    head has no list of those present, or if a list is anything but supervisors, or if someone is on it twice.
    `lines` are the places of the head's own lines, which are no part of the meeting's business: the title down to
    the day, the time, and the roll.
    """
    head = {"date": "", "time": "", "kind": "", "roll": [], "lines": set()}
    top = lines[:40]
    kind = _KIND.search(" ".join(top[:8]))
    head["kind"] = clean(kind[1]).title() if kind else ""
    roll, broken = [], False
    index = 0
    while index < len(top):
        line = top[index]
        day, hour, listing = _DAY.match(line), _TIME.match(line), _ROLL.match(line)
        if day and not head["date"]:
            head["date"] = datetime.strptime(f"{day[1]} {day[2]} {day[3]}", "%B %d %Y").strftime("%Y-%m-%d")
            head["lines"].update(range(index + 1))
        if hour and head["date"] and not head["time"]:
            head["time"] = f"{hour[1]} {hour[2].upper()}M"
            head["lines"].add(index)
        if listing and not any(word == listing[1] for _, word in roll):
            names = listing[2]
            head["lines"].add(index)
            # The list runs on where it has not ended, and where the next line is one word: the surname of a
            # supervisor named in full ("... and Supervisor Zev" / "Yaroslavsky").
            while index + 1 < len(top) and (_OPEN.search(names) or top[index + 1].startswith("and Supervisor")
                                            or re.fullmatch(r"[A-Z][A-Za-z'’-]+", top[index + 1])):
                index += 1
                names = joined_list(names, top[index])
                head["lines"].add(index)
            found = names_of(_TITLED.sub("", names))
            broken = broken or found is None
            roll += [(surname(name), listing[1]) for name in found or []]
        index += 1
    seated = [name for name, _ in roll]
    present = any(word == "Present" for _, word in roll)
    head["roll"] = roll if present and not broken and len(set(seated)) == len(seated) else []
    return head


def read_block(entries, roll):
    """One block of votes: ([(supervisor, word), ...], "") if it reads cleanly, or (None, why not).

    `entries` are the block's lists as printed: (the word, the count before the list, the list). Clean means: each
    word is one of LABELS and stands once; each list is nothing but supervisors, and as many as its count; every name
    is on the roll; nobody is named twice; and nobody on the roll is left out. So a block cut short, or run into the
    text after it, is not read, nor is one that leaves a supervisor to be accounted for in words ("Supervisor Kuehl
    declared a conflict and recused herself from the vote").
    """
    seated = [name for name, _ in roll]
    if not seated:
        return None, "no roll at the head of the statement"
    cast, seen, words = [], set(), set()
    for label, count, text in entries:
        if label not in LABELS:
            return None, f"a word not known: {label}"
        if label in words:
            return None, f"{label} twice"
        words.add(label)
        names = names_of(text)
        if names is None:
            return None, f"not a list of supervisors: {clean(text)[:60]}"
        if len(names) != int(count):
            return None, f"{label} says {int(count)} and names {len(names)}"
        for name in names:
            if surname(name) not in seated:
                return None, f"not on the roll: {name}"
            if surname(name) in seen:
                return None, f"named twice: {name}"
            seen.add(surname(name))
            cast.append((member_of(name), council_tables.vote_word(LABELS[label])))
    if len(seen) != len(seated):
        return None, f"{len(seen)} of {len(seated)} supervisors named"
    return cast, ""


# ---------------------------------------------------------------------------
# Reading a statement
# ---------------------------------------------------------------------------

def moved(text):
    """(mover, seconder) of an action that says "On motion of Supervisor Hahn, seconded by Supervisor Solis", else ("", "")."""
    found = _MOVED.search(text)
    return (member_of(found[1]), member_of(found[2])) if found else ("", "")


def action_of(said):
    """What was done, out of everything that stands between a matter and its vote: from the last "On motion of" or
    "By Common Consent", leaving out who spoke before it. All of it where neither is said."""
    found = list(_ACTED.finditer(said))
    return clean(said[found[-1].start():]) if found else clean(said)


def parse(text):
    """A statement's text as (head, lines). Each line is a heading or a matter, with the motions made on it.

    A statement is a run of matters under headings ("II. CONSENT CALENDAR"). A matter opens with its number
    ("12.", "S-1.", "CS-2.", "1-D."), says what is asked, and ends with its file number in brackets. What the Board
    did follows, then the vote by name, then the list of the matter's documents ("Attachments:"). Where the Board
    acted on a matter twice, the matter is printed again for the second action, without its number. So a vote
    belongs to the matter whose file number was the last before it, and that is all it is taken to belong to.

    Where the text does not keep that order, the vote is not read, and the motion says why (`doubt`):
      - A vote that comes before its matter's file number: the number has been lost from the text, and with it
        the certainty of which matter the vote is on.
      - A vote that comes after a matter's attachments: it may be on a matter whose number and file number are
        both lost.
      - A vote that comes after a line which may have opened a matter (the next number, a number with a letter
        such as 6-A, or any number once the matter has been voted on) with no file number after it, unless a
        matter of that number opens elsewhere in the statement.

    A line that opens with a number is not always a matter. Points inside what was done are numbered too ("the
    Board took the following actions: 1. Closed the hearing; 2. Adopted ..."), and a sentence may break before a
    number ("Rules 2, 6, 7, 8, 10, and / 11. This ordinance ..."). After a file number such a line opens a matter
    only if it comes to a file number of its own before any vote or attachment, and only if the numbering does not
    pick up again below it from where it was.
    """
    lines = lines_of(text)
    head = head_of(lines)
    roll = head["roll"]
    out, current, section, group = [], None, "", ""
    filed_as = {}  # the matters met so far, by file number
    part = ""  # what the lines now being read belong to: "body" (what is asked), "tail" (what was done), "attached" or nothing
    last, point = 0, 0  # the highest matter's number so far, and the last numbered point's since the last matter
    voted = False  # whether a vote has been met since the last file number
    said, loose = [], []  # what was done, since the file number or the last vote; and lines that belong to nothing yet
    capitals = False  # whether the line before this one was a heading in capitals
    block = None

    def close():
        """End the block being gathered and read it."""
        nonlocal block
        if block is None:
            return
        motion, entries = block
        block = None
        cast, problem = read_block(entries, roll)
        motion.update(cast=cast or [], read=cast is not None, problem=problem)

    def settle():
        """Keep what was done with the matter where no vote followed it."""
        nonlocal said
        if current is not None and said and _ACTED.search(" ".join(said)):
            words = " ".join(said)
            mover, seconder = moved(action_of(words))
            current["motions"].append({"text": action_of(words), "mover": mover, "seconder": seconder, "block": False,
                                       "cast": [], "read": False, "problem": "", "doubt": ""})
        said = []

    def begin(number, first):
        nonlocal current, part, point, loose
        close()
        settle()
        current = {"heading": False, "number": number, "body": [first] if first else [], "file": "", "section": section,
                   "group": group, "motions": [], "doubt": "", "maybe": set()}
        part, point, loose = "body", 0, []
        out.append(current)

    for index, line in enumerate(lines):
        if index in head["lines"]:
            continue
        label = label_of(line)
        was_capitals, capitals = capitals, False
        if block is not None and not label:
            # The rest of a list of names that ran over the line's end.
            entries = block[1]
            if _OPEN.search(entries[-1][2]) or line.startswith("and Supervisor"):
                entries[-1] = (entries[-1][0], entries[-1][1], joined_list(entries[-1][2], line))
                continue
            close()
        if label:
            if block is None or label[0] in OPENING:
                close()
                doubt = ""
                if current is None:
                    begin("", " ".join(loose))
                    doubt, part = "a vote with no matter before it", "tail"
                elif part == "body":
                    doubt, part = "a vote before the matter's file number", "tail"
                elif part == "attached":
                    doubt = "a vote after the matter's attachments"
                words = " ".join(said)
                mover, seconder = moved(action_of(words))
                motion = {"text": action_of(words), "mover": mover, "seconder": seconder, "block": True, "cast": [], "read": False,
                          "problem": "", "doubt": doubt or current["doubt"], "maybe": set() if doubt else set(current["maybe"])}
                current["motions"].append(motion)
                block, said, voted = (motion, []), [], True
            block[1].append(label)
            continue
        heading = _SECTION.match(line)
        if heading and not re.search(r"[a-z]", line):
            close()
            settle()
            current, part, section, group, loose = None, "", clean(f"{heading[1]}. {heading[2]}"), "", []
            out.append({"heading": True, "number": "", "body": [line], "file": "", "section": "", "group": "", "motions": [], "doubt": ""})
            continue
        numbered = numbered_of(line) if part != "body" else None
        if numbered and part:
            # After a file number, a line that opens with a number is the next matter or a line of what was done.
            number = int(numbered[0]) if numbered[0].isdigit() else None
            ahead = file_ahead(lines, index)
            fresh = bool(ahead) and ahead not in filed_as  # it comes to a file number no matter has had yet
            # The numbers do not say by themselves: they start again for the districts' boards, and "SEPARATE MATTERS
            # 24 and 25" are printed after matter 32. A file number of its own shows a matter, unless the numbering
            # jumps and then picks up again below from where it was.
            opens = fresh and not (number is not None and number > last + 1 and resumes_below(lines, index, last, number))
            if not opens:
                listed = number is not None and number == point + 1
                if part == "tail" and not listed and (number is None or voted or number == last + 1):
                    # It has the look of the next matter and no file number: a matter whose file number is lost, or
                    # a line of what was done. Which, is settled below if that matter opens somewhere else.
                    current["doubt"] = "a line that may open a matter, with no file number after it"
                    current["maybe"].add(numbered[0])
                point = number if number is not None else point
                numbered = None
        if numbered:
            line = numbered[1]
            begin(numbered[0], line)
            last = max(last, int(numbered[0])) if numbered[0].isdigit() else last
            if not _FILE.search(line):
                continue
            current["body"] = []
        filed = _FILE.search(line)
        if filed:
            number = "" if filed[1].endswith("-") else filed[1]  # "(24-)": the brackets are there and the number is not
            again = filed_as.get(number) if part != "body" else None
            if again is not None:
                # The matter printed again, for a second thing done with it: what follows is that matter's too.
                close()
                settle()
                current, loose = again, []
                current["doubt"], current["maybe"] = "", set()
            else:
                if part != "body":
                    # A file number with no matter's number before it: what opens the meeting (the invocation, the
                    # presentations), or a matter whose number the text has lost.
                    begin("", " ".join(loose) if part != "attached" else "")
                current["body"].append(clean(line[:filed.start()]))
                current["file"] = number
                if number:
                    filed_as.setdefault(number, current)
            part, said, voted = "tail", [], False
            continue
        if _ATTACHED.match(line):
            close()
            settle()
            part, loose = "attached", []
            continue
        if part == "body":
            current["body"].append(line)
        elif part == "tail":
            if _GROUP.match(line):
                group = line
            else:
                said.append(line)
        elif not re.search(r"[a-z]", line) and len(re.findall(r"[A-Z]", line)) >= 6:
            group = clean(f"{group} {line}") if was_capitals else line  # whose business follows, in capitals over a line or more
            capitals = True
        elif not part:
            loose.append(line)
    close()
    settle()
    # A line that had the look of matter 12 was not matter 12 if matter 12 opens elsewhere, with a file number of its own.
    opened = {line["number"] for line in out if line["number"] and line["file"]}
    for line in out:
        for motion in line["motions"]:
            if motion.get("maybe") and motion["maybe"] <= opened:
                motion["doubt"] = ""
    return head, out


def label_of(line):
    """A line of a block, as (the word, the count, the list), else None.

    The word is one of LABELS, or any word that stands as they do before a count and a supervisor: a word not known
    stops its block being read, where a line of prose that happens to look alike ("Sections: 1 - 5 ...") is passed by.
    """
    found = _LABEL.match(line)
    if found and not _ATTACHED.match(line) and (found[1] in LABELS or found[3].startswith("Supervisor")):
        return found[1], found[2], found[3]
    return None


def numbered_of(line):
    """(the number, the rest of the line) where a line opens as a matter does, else None."""
    found = _NUMBERED.match(line)
    if not found:
        return None
    return (f"Set Matter {found[2]}" if found[1] else found[3]), found[4]


def file_ahead(lines, index):
    """The file number the numbered line at `index` comes to before any vote or attachment, or "" if it comes to none.

    A matter comes to its own. A point in what was done comes to the vote, or to the same matter printed again for a
    second action, whose file number is the one it already has.
    """
    for line in lines[index:index + 400]:
        filed = _FILE.search(line)
        if filed:
            return filed[1]
        if label_of(line) or _ATTACHED.match(line) or (_SECTION.match(line) and not re.search(r"[a-z]", line)):
            return ""
    return ""


def resumes_below(lines, index, last, number):
    """Whether the numbering picks up again under `number`: the line at `index` is then no matter, but a sentence
    broken before a number, or a point in a long list."""
    for line in lines[index + 1:]:
        found = numbered_of(line)
        if found and found[0].isdigit() and int(found[0]) > last:
            return int(found[0]) < number
    return False


def read_meeting(meeting, out_dir, fresh=False):
    """One meeting's statement: its lines, the votes on each motion whose block read cleanly, and what the reading found."""
    text = text_of(meeting, out_dir, fresh)
    pages = text.count("\f") + 1
    facts = {"summary": "read", "pages": pages, "roll": "", "vote_blocks": 0, "blocks_read": 0, "date": "", "time": "", "kind": ""}
    if len(re.sub(r"\s", "", text)) < LAYER_CHARS:
        return [], [], {**facts, "summary": "no text layer"}
    head, lines = parse(text)
    facts.update(date=head["date"], time=head["time"], kind=head["kind"])
    facts["roll"] = json.dumps([{"name": member_of(name), "district": KNOWN.get(name, ("", None))[1], "present": word == "Present"}
                                for name, word in head["roll"]], ensure_ascii=False, separators=(",", ":"))
    if not head["roll"]:
        facts["roll"] = ""
    meeting_id, date = meeting["meeting_id"], head["date"] or meeting["date"]  # the day the statement prints, before the listing's
    agenda, votes, used, sections, unnumbered = [], [], {}, 0, 0
    for line in lines:
        if line["heading"]:
            sections += 1
            line["item_id"] = f"{meeting_id}-s{sections}"
        elif line["number"]:
            number = line["number"].replace(" ", "-")
            used[number] = used.get(number, 0) + 1
            line["item_id"] = f"{meeting_id}-{number}" + (f"~{used[number]}" if used[number] > 1 else "")  # a number met twice
        else:
            unnumbered += 1
            line["item_id"] = f"{meeting_id}-u{unnumbered}"
    for sequence, line in enumerate(lines, 1):
        item_id, heading = line["item_id"], line["heading"]
        matter_id = "" if heading else line["file"] or item_id
        for number, motion in enumerate(line["motions"], 1):
            if motion["block"] and motion["doubt"]:
                motion.update(cast=[], read=False, problem=motion["doubt"])
            for member, word in motion["cast"]:
                votes.append({"item_id": item_id, "meeting_id": meeting_id, "date": date, "matter_id": matter_id,
                              "matter_file": line["file"], "member": member, "vote": word, "motion": number,
                              "motion_text": motion["text"]})
        blocks = [motion for motion in line["motions"] if motion["block"]]
        # What is said of the line is its last vote, or with no vote its last action.
        last = blocks[-1] if blocks else line["motions"][-1] if line["motions"] else None
        cast = [word for _, word in last["cast"]] if last else []
        body = [part for part in line["body"] if part]
        asked = next((index for index, part in enumerate(body) if _RECOMMENDED.match(part)), 0)
        full = clean(" ".join(body))
        agenda.append({
            "item_id": item_id, "meeting_id": meeting_id, "date": date, "body": BODY,
            "agenda_number": line["number"], "sequence": sequence, "matter_id": matter_id, "matter_file": line["file"],
            # A matter has a short title of its own since 2019, above what is recommended. Before that it is all one.
            "title": clean(" ".join(body[:asked])) if asked else full,
            "action": last["text"] if last else "",
            "result": "Fail" if last and _FAILED.search(last["text"]) else "",  # a motion that carried is not marked
            "mover": last["mover"] if last else "", "seconder": last["seconder"] if last else "",
            "ayes": cast.count(council_tables.AYE), "noes": cast.count(council_tables.NO),
            "not_voting": sum(word not in (council_tables.AYE, council_tables.NO) for word in cast),
            "heading": heading, "section": line["section"], "group": line["group"], "text": "" if heading else full,
            "motions": len(line["motions"]), "vote_blocks": len(blocks), "blocks_read": sum(motion["read"] for motion in blocks),
            "votes_read": all(motion["read"] for motion in blocks) if blocks else None,
            "problem": next((motion["problem"] for motion in blocks if not motion["read"]), ""),
            "doc_type": "" if heading else county.doc_type_of(full),
            "motion_log": json.dumps([{"motion": number, "action": motion["text"], "mover": motion["mover"],
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
    """Every matter in the statements read, once, with what was last done with it.

    A matter keeps its file number from one meeting to the next (a report continued for a year is one file), so a
    matter here is a file number, and its row is drawn from the newest statement it stands in. A line whose file
    number the text has lost is a matter by itself.
    """
    statement = dict(zip(meetings["meeting_id"], meetings["minutes_url"]))
    lines = agenda[~agenda["heading"]].sort_values(["date", "meeting_id", "sequence"])
    rows = []
    for matter_id, held in lines.groupby("matter_id", sort=False):
        newest = held.iloc[-1]
        acted = held[held["action"] != ""]
        done = acted.iloc[-1] if len(acted) else None
        voted = held[held["vote_blocks"] > 0]
        vote = voted.iloc[-1] if len(voted) else None
        rows.append({
            "date": held["date"].iloc[0], "matter_id": matter_id, "matter_file": newest["matter_file"], "doc_type": newest["doc_type"],
            "title": newest["title"], "body": BODY, "status": "", "year": int(held["date"].iloc[0][:4]), "subject": "",
            "agenda_date": newest["date"], "passed_date": "",
            "last_action": done["action"] if done is not None else "", "last_action_date": done["date"] if done is not None else "",
            "result": done["result"] if done is not None else "",
            "ayes": int(vote["ayes"]) if vote is not None else 0, "noes": int(vote["noes"]) if vote is not None else 0,
            "mover": vote["mover"] if vote is not None else "", "seconder": vote["seconder"] if vote is not None else "",
            "times_on_agenda": int(held["meeting_id"].nunique()), "url": statement.get(newest["meeting_id"], ""),
            "item_id": newest["item_id"], "meeting_id": newest["meeting_id"],
            "votes_read": bool(vote["votes_read"]) if vote is not None else None,
        })
    out = pd.DataFrame(rows, columns=ITEM_COLUMNS)
    out["votes_read"] = out["votes_read"].astype("boolean")
    for column in ("year", "ayes", "noes", "times_on_agenda"):
        out[column] = out[column].astype(int)
    return out.sort_values(["agenda_date", "meeting_id", "matter_id"], ascending=[False, False, True]).reset_index(drop=True)


def members_table(votes, meetings):
    """Everyone named in a block that was read. The district is KNOWN's; the statements give no terms of office.

    `serving` is true for those on the roll of the newest statement read.
    """
    rolls = meetings[meetings["roll"] != ""].sort_values(["date", "meeting_id"])
    serving = {member["name"] for member in json.loads(rolls["roll"].iloc[-1])} if len(rolls) else set()
    district = {name: seat for name, seat in KNOWN.values()}
    cast = votes.groupby("member")["date"].agg(["min", "max", "size"]) if len(votes) else pd.DataFrame()
    rows = [{"name": name, "district": district.get(name), "role": "", "start": "", "end": "", "serving": name in serving,
             "first_vote": cast.loc[name, "min"], "last_vote": cast.loc[name, "max"], "votes": int(cast.loc[name, "size"])}
            for name in sorted(cast.index)]
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


def since_day(since):
    """`--since` as a day: a year alone is its first day."""
    since = str(since or FIRST_DAY)
    return f"{since}-01-01" if re.fullmatch(r"\d{4}", since) else since


def build(base, everything, out_dir, since=FIRST_DAY, limit=0, every=40):
    rows = listed()
    log.info(f"Los Angeles County: {len(rows)} statements listed")
    if len(rows) < 1000:
        raise RuntimeError("the listing of statements came back short")
    meetings = meetings_table(rows)

    agenda, votes, before_meetings = (council_tables.held(HF_REPO, out_dir, name, base) for name in ("agenda_items", "votes", "meetings"))
    if agenda is None or votes is None or before_meetings is None:
        agenda, votes = pd.DataFrame(columns=AGENDA_COLUMNS), pd.DataFrame(columns=VOTE_COLUMNS)
        before_meetings = pd.DataFrame(columns=MEETING_COLUMNS)
    # A statement that is no longer listed has been taken down or put up again under another number: what was read
    # from it goes, or its votes would stand twice.
    listed_now = set(meetings["meeting_id"])
    gone = set(agenda["meeting_id"]) - listed_now
    if len(gone) > max(3, 0.02 * agenda["meeting_id"].nunique()):
        raise RuntimeError(f"{len(gone)} statements read before are no longer listed: the listing may be short")
    if gone:
        log.info(f"Los Angeles County: {len(gone)} statements read before are no longer listed, and are left out")
        agenda, votes = agenda[agenda["meeting_id"].isin(listed_now)], votes[votes["meeting_id"].isin(listed_now)]
    before = len(votes)
    kept = ("summary", "pages", "roll", "vote_blocks", "blocks_read", "date", "time", "kind")
    found = {row["meeting_id"]: {name: row[name] for name in kept}
             for row in before_meetings[before_meetings["summary"] != ""].to_dict("records") if row["meeting_id"] in listed_now}
    recent = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    first = since_day(since)
    wanted = [row for row in meetings.to_dict("records") if row["minutes_url"] and row["date"] >= first
              and (everything or row["meeting_id"] not in found or row["date"] >= recent)]
    wanted.sort(key=lambda row: (row["date"], row["meeting_id"]), reverse=True)  # the newest first: a room shows those
    waiting = len(wanted)
    wanted = wanted[:limit] if limit else wanted
    log.info(f"Reading the statements of {len(wanted)} meetings of {waiting} not yet read or to be read again")

    def fill():
        for name, empty in (("summary", ""), ("pages", 0), ("roll", ""), ("vote_blocks", 0), ("blocks_read", 0), ("time", ""), ("kind", "")):
            meetings[name] = [found.get(meeting_id, {}).get(name, empty) for meeting_id in meetings["meeting_id"]]
        # The day a statement prints at its head is the meeting's; the listing's is kept beside it.
        meetings["date"] = [found.get(meeting_id, {}).get("date") or listed_day
                            for meeting_id, listed_day in zip(meetings["meeting_id"], meetings["listed_date"])]
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
        log.info(f"Los Angeles County: {min(start + every, len(wanted))} of {len(wanted)} statements asked for, {len(votes)} votes held")
        if _refused:
            log.error(f"Refused by {', '.join(sorted(_refused))}: no more is asked of it in this run")
            break

    fill()
    meetings = meetings.sort_values(["date", "meeting_id"]).reset_index(drop=True)
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
        "first_listed": meetings["date"].min() if len(meetings) else "",
        "first_vote": votes["date"].min() if len(votes) else "", "last_vote": votes["date"].max() if len(votes) else "",
        "n_read": f"{len(read):,}", "n_scans": f"{int((meetings['summary'] == 'no text layer').sum()):,}",
        "n_blocks": f"{blocks:,}", "n_blocks_read": f"{clean_blocks:,}", "n_unread": f"{blocks - clean_blocks:,}",
        "share_read": f"{100 * clean_blocks / blocks:.1f}" if blocks else "0", "recent_days": RECENT_DAYS, "first_day": FIRST_DAY,
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
        log.error(f"Los Angeles County tables not uploaded: {e}")
        return False
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the Los Angeles County Board's meetings, agendas and votes")
    parser.add_argument("--base", action="store_true", help="start from the tables written here, not the published ones")
    parser.add_argument("--all", action="store_true", help="read every statement again")
    parser.add_argument("--since", default=FIRST_DAY, help="read no meeting before this day (2024-01-01) or year (2024)")
    parser.add_argument("--max", type=int, default=0, help="statements to read in one run (0 for all)")
    parser.add_argument("--out", default="", help="directory to write the tables into (minutes_pdf/los-angeles-county if not given)")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the tables only")

    out_dir = Path(args.out) if args.out else OUT_DIR
    try:
        tables, read = build(args.base, args.all, out_dir, args.since, args.max)
    except Exception as e:
        log.error(f"Los Angeles County tables not built: {type(e).__name__}: {e}")
        return 1
    pushed = False if args.no_upload else upload(tables, out_dir, args.write_card)
    meetings, agenda, votes, members = tables["meetings"], tables["agenda_items"], tables["votes"], tables["members"]
    blocks, clean_blocks = int(agenda["vote_blocks"].sum()), int(agenda["blocks_read"].sum())
    log.info(f"RESULT: los-angeles-county items={len(tables['items'])} meetings={len(meetings)} "
             f"statements_read={int((meetings['summary'] == 'read').sum())} "
             f"no_text_layer={int((meetings['summary'] == 'no text layer').sum())} agenda_items={len(agenda)} "
             f"votes={len(votes)} vote_blocks={blocks} blocks_read={clean_blocks} blocks_unread={blocks - clean_blocks} "
             f"members={len(members)} serving={int(members['serving'].sum())} meetings_read={read} "
             f"first_vote={votes['date'].min() if len(votes) else ''} last_vote={votes['date'].max() if len(votes) else ''} "
             f"refused={','.join(sorted(_refused)) or False} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
