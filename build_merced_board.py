#!/usr/bin/env python3
"""
Build chrissoria/merced-county-board: the meetings of the Merced County Board
of Supervisors, what was on each agenda, what the Board did with it, and how
each supervisor voted.

One source: the County's own agenda pages (web2.co.merced.ca.us/boardagenda).
A page for each year lists that year's meetings, and each meeting has its
agenda as a page of HTML whose items link the papers filed with them. The
agendas go back to July 2008.

The minutes ("Summary Action Minutes") are not linked from a meeting. They
are papers filed with a later meeting's item "Approve the Summary Action
Minutes - Final for the February 10, 2026 Board of Supervisors meeting", so
they are found by looking through every agenda from 2019 on for such an item
and following it. Which meeting a set of minutes is of is read off its own
head. The Board began approving its minutes this way in 2020, for the meetings
from September 2019. Those of September 2019 to November 2020 are scans;
nothing is read off the picture of a page, so they are counted and left. No
agenda has the minutes of the thirteen months after. The votes here begin
with the first minutes that carry their own text, of January 2022.

The minutes are the agenda printed again with what was done set under each
item, in capitals, and the vote beside it by the number of each supervisor's
district:

    CONSENT CALENDAR (Items No. 1-13)
    APPROVED AS RECOMMENDED AYES: ALL
    ...
    24. 1) Introduce an ordinance entitled ...
    APPROVED AS RECOMMENDED AYES: 2, 3, 4 NOES: 1, 5
    ...
    APPROVED AS RECOMMENDED AYES: 1, 2, 4, 5 NOT PRESENT: 3

The head of the same minutes prints the Board with its districts ("Josh
Pedrozo, District 2"), and that is the roll the numbers are read against.
`established` on each vote says how it is known:

  `numbers`  The line gives districts. It is read only if every number is one
             of 1 to 5, none is given twice, and together they are all five.
             Each supervisor then has the word their number stands under:
             AYE, NO, or the minutes' own (NOT PRESENT, ABSTAIN, ...).
  `all`      The line says "AYES: ALL". Every supervisor on the roll voted
             aye, unless the minutes have one of them out of the room at that
             point (the sentence that says how the Board came back from its
             closed session, or one that says a supervisor left), in which
             case nothing is read.
  `names`    The line names the supervisors under each word (once, in 2022).
             It is read only if each name is on the roll and all five are
             named.

The consent calendar is adopted by one vote, printed under its heading, so
that vote is on the calendar's own line and its items point to it. The same
goes for the letters "accepted and placed on file" together, and once for a
department's items voted on under the department's name.

A vote is read whole or not at all. One that is not read stays in agenda_items
with what stopped it (`problem`) and has no rows in votes.

The dataset has the five tables every council's and board's dataset has
(council_tables.py), in data/:
  items.parquet          every item acted on in minutes that were read
  meetings.parquet       one row per meeting of the Board listed
  agenda_items.parquet   one row per line of a meeting's agenda, with what was done
  votes.parquet          one row per supervisor and motion voted on
  members.parquet        one row per supervisor with a vote here
They are kept here in minutes_pdf/merced-county/, with what was fetched beside
them in text/ (each agenda's lines, the papers listed under each item that
approves minutes, and the text of each set of minutes), so a page or a PDF is
fetched once.

Two ways to run it:

    python build_merced_board.py
        The routine run. Starts from the published tables, lists every meeting
        again, and reads the agendas and minutes not read before and those of
        meetings in the last 90 days (an agenda is amended up to its meeting,
        and minutes are approved a month or so after theirs).

    python build_merced_board.py --base
        The same, starting from the tables written here. It fetches the newest
        first and can be stopped and started again. Whatever is kept in text/
        is read again on every run; that takes no request.

    --since YEAR  read no meeting before this year (default 2008, where the listing begins)
    --max N       agendas, and sets of minutes, to fetch in one run (default 0, for all)
    --all         fetch again every agenda and set of minutes not kept here, read before or not
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
from urllib.parse import quote, urljoin

import pandas as pd
import requests

import build_federal_bills as bills
import build_sd_county as county
import council_tables
from build_sd_county import clean, today

log = logging.getLogger(__name__)

HF_REPO = "chrissoria/merced-county-board"
OUT_DIR = bills.SCRIPT_DIR / "minutes_pdf" / "merced-county"
CARD_FILE = bills.SCRIPT_DIR / "README_merced_board.md"
TABLES = council_tables.TABLES
BODY = "Board of Supervisors"

HOST = "https://web2.co.merced.ca.us"
BASE = f"{HOST}/boardagenda"
FIRST_YEAR = 2008  # the listing begins in July 2008
ASP_FROM = 2025  # a year's listing is Meetings2024.htm, and from this year Meetings2025.asp
MINUTES_FROM = 2019  # no agenda before 2020 approves minutes; the first to do so approves those of September 2019
SEATS = 5  # a county's board of supervisors (Government Code 25000), and Merced's five districts
RECENT_DAYS = 90  # meetings this recent are fetched again
SERVING_DAYS = 120  # a supervisor whose last vote is this recent is taken to be serving
LAYER_CHARS = 200  # minutes with fewer characters of their own than this are a scan
PAUSE = 1.0  # seconds after each request

# The listing has every body the supervisors sit as. A meeting is the Board's own unless its label names another:
# the In-Home Supportive Services authority, the redevelopment agency, a groundwater sustainability agency, the claims
# board, the public facilities corporation, the flood control district, a hearing of the State's water board. What is
# kept is then labelled "Board" (or nothing, or "BD", in the first years), "Board (Amended)", "Addendum", "Special
# Meeting", "Study Session", the budget hearings ("Budget", "Proposed Budget", "Final Budget Hearing"), a joint
# meeting with the Planning Commission, and a Board meeting with something added ("Board & Proposed Budget",
# "Board & Redistricting Public Hearing", "Board + 2:00pm ARPA Hearing").
_OTHER_BODY = re.compile(r"\b(?:IHSS|RDA|Redevelopment|GSA|Groundwater|Claims\s+Board|Public\s+Facilities|PFC|Flood\s+Control"
                         r"|Water\s+Resources|In-Home|Successor\s+Agency)\b", re.I)

MEETING_COLUMNS = council_tables.COLUMNS["meetings"] + [
    "name", "agenda", "minutes", "minutes_from", "approved", "pages", "roll", "present", "motions", "motions_read", "note"]
AGENDA_COLUMNS = council_tables.COLUMNS["agenda_items"] + [
    "heading", "section", "section_id", "department", "motions", "motions_read", "votes_read", "problem", "how", "established",
    "voted_with", "doc_type", "number", "documents_url", "source", "motion_log"]
VOTE_COLUMNS = council_tables.COLUMNS["votes"] + ["district", "motion", "motion_text", "established"]
ITEM_COLUMNS = council_tables.COLUMNS["items"] + ["item_id", "meeting_id", "section", "department", "action_on", "votes_read", "number"]

# How a vote came to be known: from the districts' numbers on its line, from "AYES: ALL", or (once) from names.
NUMBERS, ALL, NAMES = "numbers", "all", "names"


class Refused(Exception):
    """The host answered with a check, a login or a refusal. It is not asked again in this run."""


_refused = threading.Event()
_CHECK = re.compile(r"captcha|cf-challenge|are you a human|access denied|you have been blocked|sign in to continue", re.I)
_session = requests.Session()


def fetch(url, tries=4):
    """One answer from the County's host, and a pause after it. A refusal is not tried again, and nothing more is
    asked of the host in this run."""
    if _refused.is_set():
        raise Refused("the host refused an earlier request")
    for attempt in range(tries):
        try:
            answer = _session.get(url, headers=county.HEADERS, timeout=(20, 180))
            time.sleep(PAUSE)
            page = "html" in answer.headers.get("content-type", "") and answer.content[:4] != b"%PDF"
            if answer.status_code in (401, 403, 429) or (page and _CHECK.search(answer.text[:20000])):
                _refused.set()
                raise Refused(f"{answer.status_code} from {url}")
            answer.raise_for_status()
            return answer
        except (requests.RequestException, OSError) as e:
            # A host that is not allowed will not be allowed on a second asking; a page that is not there is not there.
            gone = isinstance(e, requests.HTTPError) and e.response is not None and e.response.status_code == 404
            if attempt == tries - 1 or gone or isinstance(e, requests.exceptions.ProxyError):
                raise
            time.sleep(3 * (attempt + 1))


def decoded(body):
    """A page's text. The agendas are saved from Word in Windows' letters; the newer pages are UTF-8."""
    if body[:3] == b"\xef\xbb\xbf":
        return body[3:].decode("utf-8", "replace")
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("cp1252", "replace")


def address(base, link):
    """A link on a page as an address that can be asked for: file names here have spaces and commas in them."""
    return quote(urljoin(base, html.unescape(link).strip()), safe="/:%#?=&")


# ---------------------------------------------------------------------------
# The listing
# ---------------------------------------------------------------------------

_ANCHOR = re.compile(r'<a\s[^>]*?href\s*=\s*"([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
_LABEL = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}:\d{2})\s*([ap])\.?\s*m\.?\s*(.*)$", re.I)
_LABEL_WORDS = re.compile(r"^(.*?)\s+for\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})\s+(\d{1,2}:\d{2})\s*([ap])\.?\s*m\.?$", re.I)  # two of 2009


def year_url(year):
    return f"{BASE}/Meetings{year}.{'asp' if year >= ASP_FROM else 'htm'}"


def rows_of(page, year):
    """The Board's own meetings on one year's listing, in the listing's order.

    A meeting is known by the folder its agenda is kept in ("20260317Board", "MG154354"), or by the name of the file
    where the listing links a PDF that stands in no folder of its own. Two entries for one folder (a budget hearing
    in the afternoon of a Board meeting, on the same agenda) are one meeting.
    """
    rows = {}
    for link, label in _ANCHOR.findall(page):
        label = clean(html.unescape(re.sub(r"<[^>]+>", " ", label)))
        found, words = _LABEL.match(label), _LABEL_WORDS.match(label)
        if found:
            date = f"{int(found[3]):04d}-{int(found[1]):02d}-{int(found[2]):02d}"
            hour, name = f"{found[4]} {found[5].upper()}M", clean(found[6])
        elif words:
            try:
                date = datetime.strptime(clean(words[2]), "%B %d, %Y").strftime("%Y-%m-%d")
            except ValueError:
                continue
            hour, name = f"{words[3]} {words[4].upper()}M", clean(words[1])
        else:
            continue
        if _OTHER_BODY.search(name):
            continue
        path = html.unescape(link).split("#")[0].split("?")[0].strip()
        parts = [part for part in path.split("/") if part]
        page_of = re.fullmatch(r"agenda\.html?", parts[-1], re.I)
        folder = parts[-2] if page_of or (len(parts) >= 3 and not path.startswith("/")) else re.sub(r"\.\w+$", "", parts[-1])
        if folder in rows:
            continue
        rows[folder] = {"meeting_id": folder, "date": date, "time": hour, "name": name,
                        "agenda": address(year_url(year), path), "kind": "html" if page_of else "pdf"}
    return list(rows.values())


def listed(first=FIRST_YEAR, last=None):
    """Every meeting of the Board the site lists from `first` on, a year to a request."""
    last = last or datetime.now(timezone.utc).year
    rows = {}
    for year in range(max(first, FIRST_YEAR), last + 1):
        try:
            page = decoded(fetch(year_url(year)).content)
        except requests.HTTPError:
            if year == last:
                continue  # early in January the new year's page may not be up
            raise
        for row in rows_of(page, year):
            rows.setdefault(row["meeting_id"], row)
    return list(rows.values())


def meetings_table(rows):
    """One row per meeting listed. What a reading adds (`minutes` and the columns after it) is filled in by build()."""
    out = [{
        "meeting_id": row["meeting_id"], "date": row["date"], "time": row["time"], "body": BODY, "location": "",
        "url": year_url(int(row["date"][:4])), "agenda_url": row["agenda"], "minutes_url": "", "items": 0,
        "name": row["name"], "agenda": row["kind"], "minutes": "", "minutes_from": "", "approved": "", "pages": 0, "roll": "",
        "present": "", "motions": 0, "motions_read": 0, "note": "",
    } for row in rows]
    return pd.DataFrame(out, columns=MEETING_COLUMNS).sort_values(["date", "meeting_id"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# An agenda
# ---------------------------------------------------------------------------
#
# An agenda is a document saved from Word as HTML: one paragraph to an item, with the item's number, and its words as
# a link to the page that lists the papers filed with it ("350338/350339/350383/Documents.htm": the calendar, the
# department and the item). The last number of the link is the item's own, and is its `matter_id`. A department's
# name is a paragraph of its own above its items; the consent calendar and the other parts of the meeting are too.

_PARAGRAPH = re.compile(r"<p\b([^>]*)>(.*?)</p\s*>", re.S | re.I)
_NOT_TEXT = re.compile(r"<(script|style|head)\b.*?</\1\s*>|<!--.*?-->", re.S | re.I)
_PICTURE = re.compile(r'src\s*=\s*"data:[^"]*"', re.I)
_CLASS = re.compile(r"""class\s*=\s*["']?([\w-]+)""", re.I)
_PAPERS = re.compile(r"""href\s*=\s*["']([^"']*documents\.html?)["']""", re.I)
_NUMBERED = re.compile(r"^(\d{1,3})\.\s+(\S.*)$")
# The parts of a meeting that an agenda and its minutes both print as a heading of their own: the name, and at most
# what it covers in brackets ("CONSENT CALENDAR (Items No. 1-13)") and a colon. The same words opening a sentence
# ("SCHEDULED ITEMS – These items are noticed hearings ...") are not a heading.
_ALONE = r"\s*(?:\([^)]*\))?\s*:?\s*$"
_PARTS = (("consent", re.compile(rf"^CONSENT\s+(?:AGENDA\s+)?CALENDAR{_ALONE}", re.I)),
          ("regular", re.compile(rf"^REGULAR\s+CALENDAR{_ALONE}", re.I)),
          ("action", re.compile(rf"^BOARD\s+ACTION{_ALONE}", re.I)),
          ("information", re.compile(rf"^BOARD\s+INFORMATION(?:\s*(?:&|AND)\s*POSSIBLE\s+ACTION)?{_ALONE}", re.I)),
          ("scheduled", re.compile(rf"^SCHEDULED\s+ITEMS?{_ALONE}", re.I)),
          ("budget", re.compile(rf"^BUDGET\s+CALENDAR{_ALONE}", re.I)),
          ("reports", re.compile(rf"^REPORTS\s*/\s*BOARD\s+DIRECTION{_ALONE}", re.I)))
_HOUR_FIRST = re.compile(r"^\d{1,2}:\d{2}\s*[AP]\.?\s?M\.?\s*[–-]?\s*", re.I)
_HEAD_LENGTH = 90  # a department's name is shorter than this
_LEFT_IN = re.compile(r"\(Placeholder Section\)")  # a line of the form the agenda is made from, left in it
_APPROVES = re.compile(r"\bApprov\w*\b[^.]{0,80}?\bMinutes\b", re.I)


def part_of(text):
    """Which part of a meeting a heading opens ("consent", "regular", ...), or "" if the words are not such a heading.
    A heading may open with its hour ("3:00 PM - SCHEDULED ITEMS:")."""
    text = _HOUR_FIRST.sub("", text)
    return next((name for name, pattern in _PARTS if pattern.match(text)), "")


def paragraphs(page):
    """An agenda's paragraphs in order, each as (its class, the papers it links, its words)."""
    page = _PICTURE.sub("", _NOT_TEXT.sub(" ", page))
    out = []
    for attributes, inside in _PARAGRAPH.findall(page):
        text = clean(html.unescape(re.sub(r"<[^>]+>", "", inside)))
        if not text:
            continue
        kind, papers = _CLASS.search(attributes), _PAPERS.search(inside)
        out.append((kind[1] if kind else "", html.unescape(papers[1]).strip() if papers else "", text))
    return out


def agenda_of(meeting, out_dir, fresh=False):
    """A meeting's agenda as its paragraphs: from the copy kept here, or fetched and kept."""
    kept = Path(out_dir) / "text" / "agendas" / f"{meeting['meeting_id']}.txt"
    if kept.exists() and not fresh:
        return [tuple(line.split("\t", 2)) for line in kept.read_text(encoding="utf-8").split("\n") if line.count("\t") >= 2]
    found = paragraphs(decoded(fetch(meeting["agenda_url"]).content))
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text("\n".join("\t".join(part.replace("\t", " ") for part in one) for one in found), encoding="utf-8")
    return found


def agenda_lines(found):
    """The lines of an agenda: its parts and departments (headings) and its items, in order.

    An item is a paragraph that links its papers. Most have a number; a hearing set for an hour has none, and the
    paragraphs under it that say what it is about are part of it. A numbered paragraph with no link is an item too
    where the page marks it as one or its number is the next ("27. PULLED": an item taken off the agenda keeps its
    place). A heading is one of the parts of a meeting, or a short paragraph with no link that the page marks as a
    department's name or that stands right above a numbered item.
    """
    found = [one for one in found if not _LEFT_IN.search(one[2])]
    lines, part, department, hearing, last = [], "", "", None, 0

    def item_at(index):
        if index >= len(found):
            return False
        kind, papers, text = found[index]
        numbered = _NUMBERED.match(text)
        return bool(papers) or bool(numbered and (kind == "Items" or (part in _NUMBERED_PARTS and int(numbered[1]) == last + 1)))

    for at, (kind, papers, text) in enumerate(found):
        opens = part_of(text) if not papers and len(text) < _HEAD_LENGTH else ""
        if opens:
            part, department, hearing = opens, "", None
            lines.append({"kind": "part", "part": opens, "number": "", "title": text, "head": "", "matter_id": "", "papers": "", "department": ""})
            continue
        numbered = _NUMBERED.match(text)
        if item_at(at):
            folders = papers.replace("\\", "/").split("/")
            line = {"kind": "item", "part": part, "number": numbered[1] if numbered else "", "title": clean(numbered[2]) if numbered else text,
                    "head": "" if numbered else text, "matter_id": folders[-2] if len(folders) >= 2 else "", "papers": papers,
                    "department": department if numbered else ""}
            lines.append(line)
            last = int(numbered[1]) if numbered else last
            hearing = None if numbered else line
            continue
        heads = kind == "CCSection" or (item_at(at + 1) and bool(_NUMBERED.match(found[at + 1][2])))
        if lines and len(text) < _HEAD_LENGTH and heads and not numbered:
            department, hearing = text, None
            lines.append({"kind": "department", "part": part, "number": "", "title": text, "head": "", "matter_id": "", "papers": "", "department": text})
        elif hearing is not None:
            hearing["title"] = clean(hearing["title"] + " " + text)
    return lines


# ---------------------------------------------------------------------------
# Finding the minutes
# ---------------------------------------------------------------------------

_PAPER = re.compile(r'<a\s[^>]*?href\s*=\s*"([^"]+\.pdf)"[^>]*>(.*?)</a>', re.S | re.I)
_ITEM_PAPER = re.compile(r"^ITEM\s*#?\s*\d+\w?$", re.I)  # the letter that asks the Board to approve the minutes
_MONTHS = "Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
_DAY_NAMED = re.compile(rf"\b({_MONTHS})\.?\s+(\d{{1,2}})\s*,?\s*(\d{{4}})\b", re.I)
_WEEKDAY = re.compile(rf"\b(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day\s*,?\s*({_MONTHS})\s+(\d{{1,2}})\s*,?\s*(\d{{4}})\b", re.I)


def day_in(text, weekday=False):
    """The first day written out in some words ("FEBRUARY 10, 2026") as 2026-02-10, or ""."""
    found = (_WEEKDAY if weekday else _DAY_NAMED).search(text)
    if not found:
        return ""
    try:
        return datetime.strptime(f"{found[1][:3].title()} {int(found[2])} {found[3]}", "%b %d %Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def papers_of(page, base):
    """The PDFs a page of papers lists, as (the name the page gives each, its address)."""
    return [(clean(html.unescape(re.sub(r"<[^>]+>", "", name))), address(base, link)) for link, name in _PAPER.findall(page)]


def papers_listed(meeting_id, matter_id, url, out_dir, fresh=False):
    """The papers filed with an item that approves minutes: from the copy kept here, or fetched and kept."""
    kept = Path(out_dir) / "text" / "documents" / f"{meeting_id}-{matter_id}.txt"
    if kept.exists() and not fresh:
        return [tuple(line.split("\t", 1)) for line in kept.read_text(encoding="utf-8").split("\n") if "\t" in line]
    found = papers_of(decoded(fetch(url).content), url)
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text("\n".join(f"{name}\t{link}" for name, link in found), encoding="utf-8")
    return found


def paper_id(url):
    """What a paper is known by: the number of the folder it is kept in ("350201" of ".../350201/MINUTES350201.pdf")."""
    parts = [part for part in url.split("/") if part]
    return re.sub(r"[^A-Za-z0-9]+", "", parts[-2] if len(parts) >= 2 else parts[-1])


def pdf_text(body):
    """The text a PDF carries, a page at a time. Nothing is read off the picture of a page."""
    import pdfplumber
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    with pdfplumber.open(io.BytesIO(body)) as document:
        return [page.extract_text() or "" for page in document.pages]


def text_of(url, out_dir, fresh=False):
    """The text of a set of minutes, pages parted by form feeds: from the copy kept here, or fetched and kept.
    A scan is kept too, as the little it has, so it is not fetched again."""
    kept = Path(out_dir) / "text" / f"{paper_id(url)}.txt"
    if kept.exists() and not fresh:
        return kept.read_text(encoding="utf-8")
    body = fetch(url).content
    if body[:4] != b"%PDF":
        raise ValueError("the site sent a page in place of the minutes")
    text = "\n\f".join(pdf_text(body))
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(text, encoding="utf-8")
    return text


# ---------------------------------------------------------------------------
# Who a name is
# ---------------------------------------------------------------------------

# One supervisor's surname is printed two ways, year about: "Espinoza" in the minutes of 2022, "Espinosa" from 2023.
SPELLED = {"espinosa": "espinoza"}
_SUFFIX = re.compile(r",?\s*\b(?:Jr|Sr|II|III)\b\.?", re.I)
_OFFICE = r"(?:SUPERVISORS?|BOARD\s+CHAIR(?:MAN|WOMAN|PERSON)?|VICE[- ]CHAIR(?:MAN|WOMAN|PERSON)?|CHAIR(?:MAN|WOMAN|PERSON)?)"
_SURNAME = r"[A-Z][A-Z’'.-]+(?:,?\s+JR\.?)?"


def letters(text):
    return re.sub(r"[^a-z]", "", str(text or "").lower())


def surname_of(name):
    """What every printing of a supervisor shares: the letters of the surname ("pareira" of "Lloyd Pareira, Jr.",
    of "SUPERVISOR PAREIRA" and of "Pareira, Jr.")."""
    words = _SUFFIX.sub("", str(name or "")).replace(",", " ").split()
    key = letters(words[-1]) if words else ""
    return SPELLED.get(key, key)


def key_of(name):
    """A supervisor as the head of the minutes prints them, apart from a middle initial, "Jr." and the spelling:
    "Scott M. Silveira" and "Scott Silveira" are one."""
    words = _SUFFIX.sub("", str(name or "")).replace(",", " ").split()
    return f"{letters(words[0])} {surname_of(name)}" if words else ""


def who(name, roll):
    """The supervisor on a meeting's roll that a surname in the minutes is, or None if it is nobody's or two people's."""
    key = surname_of(name)
    found = [member for member in roll if surname_of(member["name"]) == key]
    return found[0] if key and len(found) == 1 else None


def names_in(text):
    """The surnames in "SUPERVISOR PAREIRA, SUPERVISOR PEDROZO AND BOARD CHAIR MCDANIEL" or "Pareira, Jr., Silveira"."""
    text = re.sub(rf"\b{_OFFICE}\s+", "", _SUFFIX.sub("", clean(text)), flags=re.I)
    return [clean(part) for part in re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+|\s*&\s*", text, flags=re.I) if clean(part)]


# ---------------------------------------------------------------------------
# A set of minutes: its head
# ---------------------------------------------------------------------------

_ROSTER = re.compile(r"^(?:(?P<role>Vice[- ]?Chair(?:man|woman|person)?|Chair(?:man|woman|person)?)\s+)?"
                     r"(?P<name>[A-Z][A-Za-z.'’ -]+?(?:,\s*(?:Jr|Sr)\.?)?)\s*,\s*District\s*(?P<district>[1-5])$")
_RUNNING = re.compile(r"Summary\s+Action\s+Minutes\s*[–-]\s*(?:Final|Draft)\b.*\b\d{4}\b", re.I)  # the line at the top of each page
_HEAD_LINES = 16  # the Board is printed within this many lines of the top of the first page


def roster_of(page):
    """The Board as the top of a page prints it: [{name, district, role}], or [] if the page is not the head of minutes."""
    lines = [clean(line) for line in page.split("\n") if clean(line)][:_HEAD_LINES]
    found = [_ROSTER.match(line) for line in lines]
    return [{"name": clean(one["name"]), "district": int(one["district"]), "role": clean(one["role"] or "")} for one in found if one]


def sets_in(text):
    """The sets of minutes in one PDF's text. A PDF is as a rule one meeting's minutes; a few hold a whole season's,
    the Board's and other bodies', one after another. A set begins on a page that prints the Board at its top; a
    page before the first of them (a table of contents) is of none."""
    pages = text.split("\f")
    starts = [at for at, page in enumerate(pages) if len(roster_of(page)) >= 3]
    if not starts:
        return [text] if len(re.sub(r"\s", "", text)) >= LAYER_CHARS else []
    return ["\f".join(pages[start:end]) for start, end in zip(starts, starts[1:] + [len(pages)])]


def kind_of(words):
    """What sort of meeting a label of the listing, or the top of a set of minutes, says it is."""
    if re.search(r"addendum", words, re.I):
        return "addendum"
    if re.search(r"budget\s+hearing|^\s*(?:final\s+|proposed\s+)?budget\b", words, re.I):
        return "budget"
    if re.search(r"special|study\s+session|workshop|town\s+hall|joint", words, re.I) and not re.match(r"\s*Board\b", words, re.I):
        return "special"
    return "regular"


def head_of(text):
    """What the first page of a set of minutes says of itself: the Board with its districts, the day, what sort of
    meeting it was, and whether it is another body's (the supervisors sitting as an agency) or a draft.

    These are read from the lines around the Board's names: from "BOARD OF SUPERVISORS" above them (another body is
    named there: "SITTING AS THE PUBLIC FACILITIES CORPORATION") to a few lines below the day, and the line that
    runs along the top of the page.
    """
    first = text.split("\f")[0]
    lines = [clean(line) for line in first.split("\n") if clean(line)]
    named = next((at for at, line in enumerate(lines[:_HEAD_LINES]) if _ROSTER.match(line)), 0)
    begins = next((at for at in range(named, max(named - 6, -1), -1) if re.fullmatch(r"BOARD OF SUPERVISORS", lines[at])), named) if lines else 0
    day = next((at for at in range(named, len(lines)) if day_in(lines[at], weekday=True)), None)
    top = [line for line in lines[begins:(day + 4 if day is not None else begins + 24)] if not _ROSTER.match(line)]
    if lines and _RUNNING.search(lines[0]):
        top.insert(0, lines[0])
    top = " ".join(top)
    date = day_in(lines[day], weekday=True) if day is not None else day_in(top)
    # "Regular Meeting & Proposed Budget" is a regular meeting; a budget hearing has minutes of its own.
    return {"roster": roster_of(first), "date": date, "other": bool(_OTHER_BODY.search(top)),
            "kind": kind_of(re.sub(r"(?i)regular\s+meeting.{0,12}?budget", "", top)), "draft": bool(re.search(r"MINUTES\s*[–-]\s*DRAFT", top))}


# ---------------------------------------------------------------------------
# A set of minutes: its votes
# ---------------------------------------------------------------------------
#
# A vote is printed after what was done, on the same line or the next:
#
#     APPROVED AS RECOMMENDED AYES: ALL
#     AUTHORIZED CONTRACT NO. 2019276 AS RECOMMENDED AYES: 1, 2, 4, 5 NOT
#     PRESENT: 3
#     APPROVED AS RECOMMENDED AYES: 2,3,4,5 ABSTENTIONS: 1
#     AYES: SUPERVISOR PAREIRA, SUPERVISOR PEDROZO ... ABSTAIN: SUPERVISOR ESPINOZA
#
# "AYES:" and then, for each word (AYES, NOES, NOT PRESENT, ...), who: ALL, districts' numbers, or names.

_AYES = re.compile(r"\bA\s?YES\s*:")  # one PDF prints "A YES:"
_WORD = re.compile(r"[\s_]*(NOES|NAYS|NOT\s+PRESENT|ABSENT|ABSTAIN(?:ED|S)?|ABSTENTIONS?|RECUS(?:ED|ALS?))\s*[:;]")  # "2,3,4,5___" / "NOT PRESENT: 1"; once "NOT PRESENT; 5"
_SAYS_ALL = re.compile(r"\s*A\s?LL\b")
_SAYS_NONE = re.compile(r"\s*NONE\b")
_SAYS_NUMBERS = re.compile(r"\s*(\d+(?:\s*(?:,|&|\bAND\b)\s*\d+)*)\s*,?")
_SAYS_NAMES = re.compile(rf"\s*((?:{_OFFICE}\s+{_SURNAME}\s*(?:,\s*AND\s+|,\s*|\s+AND\s+)?)+)")
# The minutes' words for what a supervisor did other than vote aye or no, and the word the tables have for each.
_OWN_WORDS = (("NOT", "NOT PRESENT"), ("ABSENT", "ABSENT"), ("ABST", "ABSTAIN"), ("RECUS", "RECUSED"))
# What a line that says what was done opens with. A vote's words are taken back to the line that opens so.
_DONE = re.compile(r"^(?:MOTION\b|THE\s+BOARD\b|BOARD\s+PROVIDED\b|RECOMMENDATION\b|AMENDED\b|AFTER\s+DISCUSSION\b|ALL\s+ITEMS\b|ITEM\b|APPROVED|ADOPTED|AUTHORIZED|ACCEPTED|DENIED|CONTINUED|RATIFIED|CONFIRMED|WAIVED|INTRODUCED|RECEIVED"
                   r"|REFERRED|UPHELD|REJECTED|APPOINTED|REAPPOINTED|DIRECTED|TABLED|FAILED|FOUND\b|DETERMINED|ADDED|NOMINATED|ELECTED)")
_PASSED = re.compile(r"^(?:MOTION\b.*?\b)?(?:APPROVED|ADOPTED|AUTHORIZED|ACCEPTED|RATIFIED|CONFIRMED)\b")
_COUNT_ONLY = re.compile(r"\b(?:ROLL\s+CALL\s+)?VOTE\s+(?:OF\s+)?\d\s*-\s*\d\b|\b\d\s*-\s*\d\s+VOTE\b")
_ONE_GIVEN = r"\d[\w-]*(?:\s*BGT)?(?:\s*\([^)]*\))?"
_GIVEN = re.compile(rf"\b(RESOLUTION|ORDINANCE|CONTRACT)S?\s+N[Oo][Ss]?\.?\s*({_ONE_GIVEN}(?:\s*(?:,\s*(?:AND|&)?|&|AND)\s*{_ONE_GIVEN})*)")


def table_word(word):
    """The tables' word for one of the minutes': AYE, NO, or the minutes' own in capitals."""
    word = clean(word).upper()
    if word in ("AYES", "NOES", "NAYS"):
        return council_tables.vote_word(word)
    return next((own for stem, own in _OWN_WORDS if word.startswith(stem)), word)


def vote_at(text, at):
    """The vote printed from `at`, just after "AYES:", as ([(word, how, who)], where it ends, what is wrong with it).

    `how` is "all", "numbers" (who is then the districts), "names" (the surnames) or "none".
    """
    parts, word = [], council_tables.AYE
    while True:
        everyone, nobody = _SAYS_ALL.match(text, at), _SAYS_NONE.match(text, at)
        numbers, names = _SAYS_NUMBERS.match(text, at), _SAYS_NAMES.match(text, at)
        if everyone or nobody:
            parts.append((word, "all" if everyone else "none", []))
            at = (everyone or nobody).end()
        elif numbers:
            parts.append((word, "numbers", [int(number) for number in re.findall(r"\d+", numbers[1])]))
            at = numbers.end()
        elif names:
            parts.append((word, "names", names_in(names[1])))
            at = names.end()
        else:
            return parts, at, f"nothing that can be read after {word}:"
        following = _WORD.match(text, at)
        if not following:
            return parts, at, ""
        word, at = table_word(following[1]), following.end()


def decide(parts, roll, away=(), noted=()):
    """Every supervisor's vote on a motion as ([(supervisor, word, established)], ""), or (None, why it cannot be told).

    `roll` is the Board as the head of the same minutes prints it; `away` those the minutes have out of the room at
    this point, by surname; `noted` those a page appended to the minutes has not present, of whose coming and going
    the minutes say nothing. Nothing is filled in on a likelihood.
    """
    districts = sorted(member["district"] for member in roll)
    if districts != list(range(1, SEATS + 1)):
        return None, f"the head of the minutes gives districts {districts or 'none'}, not the five"
    if not parts:
        return None, "no vote can be read"
    parts = [part for part in parts if part[1] != "none"]  # "NOES: NONE" says nothing of anyone
    ways = {how for _, how, _ in parts}
    if "all" in ways:
        if len(parts) > 1 or parts[0][0] != council_tables.AYE:
            return None, "ALL, and something more"
        out = sorted({(who(name, roll) or {"name": name})["name"] for name in list(away) + list(noted)})
        if out:
            return None, "ALL, and the minutes have " + ", ".join(out) + " not present"
        return [(member["name"], council_tables.AYE, ALL) for member in roll], ""
    if len(ways) != 1:
        return None, "the vote is given two ways"
    cast, seen = [], set()
    for word, how, given in parts:
        for one in given:
            if how == "numbers":
                member = next((member for member in roll if member["district"] == one), None)
                if member is None:
                    return None, f"not a district: {one}"
            else:
                member = who(one, roll)
                if member is None:
                    return None, f"not on the roll: {one}"
            if member["name"] in seen:
                return None, f"given twice: {'district ' + str(one) if how == 'numbers' else member['name']}"
            seen.add(member["name"])
            cast.append((member["name"], word, NUMBERS if how == "numbers" else NAMES))
    missing = [member for member in roll if member["name"] not in seen]
    if missing:
        return None, "nothing is said of " + ", ".join(f"district {member['district']}" if ways == {"numbers"} else member["name"] for member in missing)
    return cast, ""


# ---------------------------------------------------------------------------
# A set of minutes: its lines
# ---------------------------------------------------------------------------

_TIME_HEAD = re.compile(r"^\d{1,2}:\d{2}\s*[AP]\.?\s?M\.?(?:\s|$)")  # "8:30 A.M. – CLOSED SESSION"
_ADJOURNED = re.compile(r"\bADJOURNED\s+THE\s+MEETING\b")
_HEARING = re.compile(r"^[A-Z][A-Z0-9 &/,.'’()-]*\s[–-]\s(?:CONTINUED\s+)?PUBLIC\s+HEARING\b")
_NOT_A_HEAD = re.compile(rf"^(?:THE\s|{_OFFICE}\s|OPPORTUNITY\b|NO\s+INTERESTED\b|RECOMMENDATION|PUBLIC\s+COMMENT|ALL\s)|A\s?YES\s*:|\bCOMMENTS\.?$")
_SPOKE = re.compile(r"\bCOMMENTS?\.?$|\bADDRESSED\s+THE\s+BOARD\.?$|\bTHE\s+PUBLIC\s+HEARING\.?$|\bPRESENTATION\.?$|\bRECESS\.?$")
_PULLED = re.compile(r"^(?:\d{1,3}\.\s+)?PULLED\b|\b(?:HAS\s+BEEN|WAS|IS)\s+PULLED\b")
_NO_ACTION = re.compile(r"\bNO\s+ACTION\s+(?:WAS\s+)?TAKEN\b")
# The parts of a meeting whose items are numbered. A hearing set for an hour has no number, and what it recommends
# is a numbered list that is not items.
_NUMBERED_PARTS = ("consent", "regular", "action", "information", "budget")
# A part adopted by one vote, printed under its heading: the vote is the heading's, and its items point to it.
_VOTED_AS_ONE = ("consent", "information")
_STEP = 3  # how far a number may run on from the last and still be taken for the next item's

_ONE = rf"(?:{_OFFICE}\s+)?{_SURNAME}"
_SOME = rf"{_OFFICE}\s+{_SURNAME}(?:\s*(?:,\s*AND\s+|,\s*|\s+AND\s+){_ONE})*"
_WITH = re.compile(rf"\bWITH\s+(?:(?P<all>ALL\s+(?:BOARD\s+)?MEMBERS)|(?P<who>{_SOME}))\s+(?P<state>NOT\s+PRESENT|PRESENT|ABSENT)\b")
_CAME = re.compile(rf"\b(?P<who>{_OFFICE}\s+{_SURNAME})\s+(?:RETURNED|ARRIVED|JOINED|REJOINED|ENTERED)\b")
_WENT = re.compile(rf"\b(?P<who>{_OFFICE}\s+{_SURNAME})\s+(?:LEFT|DEPARTED|EXITED|WAS\s+EXCUSED|STEPPED\s+(?:OUT|AWAY|DOWN))\b")
_RECESSED = re.compile(r"\bTHE\s+BOARD\s+RECESSED\b[^\n]*(?:\n(?!\d{1,2}:\d{2}|GOVERNMENT\s+CODE)[A-Z0-9][^\n]*){0,3}")
_PRESENT = re.compile(r"^Present\s*:\s*(.+)$")
_NOT_PRESENT = re.compile(r"^(?:Not\s+Present|Absent)\s*:\s*(.+)$")
_ORDER = re.compile(r"^(?:ACTION|CONSENT)\s+ITEM\s+NO\.?\s*(\d{1,3})\b")
_ORDER_VOTE = re.compile(r"^(Ayes|Noes|Absent|Not\s+Present|Abstain(?:ed)?|Recused?)\s*:\s*(.*)$")


def caps(line):
    """Whether a line is printed in capitals, as what was done and who spoke are, and an item's own words are not."""
    return bool(re.search(r"[A-Z]", line)) and line == line.upper()


def shouted_line(line):
    """Whether a line is printed in capitals but for a letter or two ("AUTHORIZED CONTRACT NOs. 2020248 & 2021264")."""
    letters_in = [letter for letter in line if letter.isalpha()]
    return len(letters_in) >= 3 and sum(letter.isupper() for letter in letters_in) >= 0.8 * len(letters_in)


def near(text):
    """The letters and digits of some words, for telling whether two printings of a title are the same."""
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def lines_of(text):
    """A set of minutes as its lines, without the line that runs along the top of each page and the page's number."""
    out = []
    for page in text.split("\f"):
        rows = [clean(row) for row in page.split("\n") if clean(row)]
        if rows and _RUNNING.search(rows[0]):
            rows = rows[1:]
        if rows and rows[-1].isdigit():
            rows = rows[:-1]
        out.extend(rows)
    return out


def comings(text):
    """Where the minutes say who is in the room, as [(place in the text, what, surnames)], in order.

    "set" is a sentence that says how the Board went into or came out of a closed session ("RECONVENED AT 10:00 A.M.
    WITH SUPERVISOR MCDANIEL NOT PRESENT", "WITH ALL MEMBERS PRESENT"): those it names are out and nobody else is.
    "went" and "came" are a supervisor leaving and returning.
    """
    found = []
    for one in _WITH.finditer(text):
        if one["all"] and clean(one["state"]) == "PRESENT":
            found.append((one.start(), "set", []))
        elif one["who"] and clean(one["state"]) != "PRESENT":
            found.append((one.start(), "set", names_in(one["who"])))
    found += [(one.start(), "came", names_in(one["who"])) for one in _CAME.finditer(text)]
    found += [(one.start(), "went", names_in(one["who"])) for one in _WENT.finditer(text)]
    return sorted(found)


def away_at(place, events):
    """The surnames the minutes have out of the room at a place in their text."""
    away = set()
    for at, what, names in events:
        if at >= place:
            break
        keys = {surname_of(name) for name in names}
        away = keys if what == "set" else away | keys if what == "went" else away - keys
    return sorted(away)


def scan(text, numbered=None, hearings=(), departments=None):
    """A set of minutes as the lines the Board acted on, each with the votes printed under it, before anyone in it
    is taken to be a supervisor.

    `numbered` is the agenda's {number: title}, and `hearings` the first words of each of its items that has no
    number: with them an item is known for the one on the agenda, and without them by its number running on from the
    last, or by the look of its line. A record is a part of the meeting (`part`), a numbered `item`, a `hearing`, or
    what stands before the first part (`opening`). Each has its `motions`: what was done, the vote as printed, the
    vote in pieces, and who the minutes then had out of the room.

    Once in the minutes read a department's items are voted on as one, with the vote under the department's name
    ("BOARD APPOINTMENTS" / "APPROVED AS RECOMMENDED AYES: 1,2,3,4 NOES: 5" / "43. ..."). That is a record of its own
    (`group`), told by `departments`, the agenda's {number: department}: the name, a vote, and then the first item
    the agenda has under that name.
    """
    departments = {str(number): near(name) for number, name in (departments or {}).items()}
    numbered = {str(number): near(title) for number, title in (numbered or {}).items()}
    wanted = [near(head) for head in hearings]
    lines = lines_of(text)
    start = next((at for at, line in enumerate(lines) if _TIME_HEAD.match(line) or (len(line) < _HEAD_LENGTH and part_of(line))), 0)
    adjourned = next((at for at in range(start, len(lines)) if _ADJOURNED.search(lines[at])), None)
    end = len(lines) if adjourned is None else adjourned + 1
    while adjourned is not None and end < len(lines) and end - adjourned <= 2 and caps(lines[end]) and not _TIME_HEAD.match(lines[end]) \
            and not re.search(r"[AP]\.?M\.?$", lines[end - 1]):
        end += 1  # "... UNTIL TUESDAY, MARCH 3," / "2026 AT 10:00 A.M."
    main, appended = lines[start:end], lines[end:]

    records, part, last, used = [], "", 0, set()
    current = {"kind": "opening", "part": "", "number": "", "first": 0, "hearing": None}
    records.append(current)
    for at, line in enumerate(main):
        following = main[at + 1] if at + 1 < len(main) else ""
        opens = part_of(line) if len(line) < _HEAD_LENGTH else ""
        item = _NUMBERED.match(line)
        if opens:
            part = opens
            current = {"kind": "part", "part": part, "number": "", "first": at, "hearing": None}
            records.append(current)
            continue
        after = _NUMBERED.match(main[at + 2]) if at + 2 < len(main) else None
        if caps(line) and after and int(after[1]) > last and departments.get(after[1]) == near(line) and near(line) \
                and _DONE.match(following) and _AYES.search(following):
            current = {"kind": "group", "part": part, "number": "", "first": at, "hearing": None}
            records.append(current)
            continue
        if item and int(item[1]) > last:
            number = int(item[1])
            same = len(near(item[2])) >= 10 and numbered.get(str(number), "")[:10] == near(item[2])[:10]
            if same or (part in _NUMBERED_PARTS and number - last <= _STEP):
                last = number
                current = {"kind": "item", "part": part, "number": str(number), "first": at, "hearing": None}
                records.append(current)
                continue
        key = near(line)
        listed_as = next((index for index, head in enumerate(wanted) if index not in used and key and caps(line)
                          and (head == key or (len(head) >= 12 and (key.startswith(head) or (key + near(following)).startswith(head) and head.startswith(key))))),
                         None)
        opens_hearing = listed_as is not None or bool(_HEARING.match(line))
        if not opens_hearing and part == "scheduled" and caps(line) and not _NOT_A_HEAD.search(line) and not _DONE.match(line):
            voted = any(_AYES.search(row) for row in main[current["first"]:at])
            opens_hearing = (current["kind"] == "part" or voted) and bool(following) and not caps(following) and not following[0].isdigit()
        if opens_hearing:
            used.add(listed_as)
            current = {"kind": "hearing", "part": part, "number": "", "first": at, "hearing": listed_as}
            records.append(current)
    for record, after in zip(records, records[1:] + [{"first": len(main)}]):
        record["lines"] = main[record["first"]:after["first"]]

    offsets, total = [], 0
    for line in main:
        offsets.append(total)
        total += len(line) + 1
    whole = "\n".join(main)
    events = comings(whole)
    for record in records:
        block, begins = "\n".join(record["lines"]), offsets[record["first"]] if record["lines"] else 0
        found = []
        for said in _AYES.finditer(block):
            parts, ends, problem = vote_at(block, said.end())
            found.append({"at": said.start(), "text": done_before(block, said.start()), "printed": clean(block[said.start():ends].replace("_", " ")).rstrip(" ,"),
                          "parts": parts, "problem": problem, "away": away_at(begins + said.start(), events)})
        for row_at, row in enumerate(record["lines"]):
            if _COUNT_ONLY.search(row) and not _AYES.search(row):
                found.append({"at": sum(len(one) + 1 for one in record["lines"][:row_at]), "text": row, "printed": _COUNT_ONLY.search(row)[0],
                              "parts": [], "problem": "a count, and no word of who voted how", "away": []})
        record["motions"] = sorted(found, key=lambda motion: motion["at"])
        opened = _NUMBERED.match(record["lines"][0])[2] if record["kind"] == "item" else ""
        shouted = ([opened] if caps(opened) else []) + [row for row in record["lines"][1:] if caps(row) or shouted_line(row)]
        record["pulled"] = next((row for row in shouted if _PULLED.search(row)), "") if record["kind"] in ("item", "hearing") else ""
        record["outcome"] = record["pulled"] or next((row for row in shouted if _NO_ACTION.search(row)), "")
        given = [(kind.title(), ", ".join(re.findall(r"\d[\w-]*(?:\s*BGT)?", re.sub(r"\([^)]*\)", " ", numbers))))
                 for kind, numbers in _GIVEN.findall(" ".join(row for row in shouted if shouted_line(row)))]
        record["number_given"] = "; ".join(dict.fromkeys(f"{kind} {clean(numbers)}" for kind, numbers in given))
        words = [opened] if record["kind"] == "item" else record["lines"][:1]
        for row in ([] if caps(opened) else record["lines"][1:]):
            if caps(row) or _AYES.search(row) or row.startswith("RECOMMENDATION"):
                break
            words.append(row)
        record["title"] = clean(" ".join(words))

    present, noted, orders, order, last_said = [], [], {}, None, ""
    for line in appended:
        headed, said, there, gone = _ORDER.match(line), _ORDER_VOTE.match(line), _PRESENT.match(line), _NOT_PRESENT.match(line)
        if headed:
            order, last_said = headed[1], ""
        elif said and (clean(said[1]).lower() == "ayes" or last_said == "order"):
            if clean(said[1]).lower() == "ayes":
                orders.setdefault(order or "", []).append({})
            if orders.get(order or ""):
                orders[order or ""][-1][table_word(said[1])] = names_in(said[2])
            last_said = "order"
        elif there:
            present.append(names_in(there[1]))
            last_said = "present"
        elif gone:
            noted.extend(names_in(gone[1]))
            last_said = "present"
        else:
            last_said = ""
    recess = _RECESSED.search(whole)
    return {"records": records, "events": events, "present": present, "noted": noted, "orders": orders,
            "recess": clean(recess[0]) if recess else "", "pages": text.count("\f") + 1}


def done_before(block, at):
    """What was done, as the minutes print it before a vote: the words on the vote's line, taken back over the lines
    above where they do not open as such words do ("ADOPTED RESOLUTION NO. 2022-33 AS" / "RECOMMENDED AYES: ALL").
    A line that says who spoke, or another vote, is not gone back over."""
    before = block[:at].split("\n")
    own, above = clean(before[-1]), before[:-1]
    words = own
    for _ in range(4):
        if _DONE.match(words) or not above or not shouted_line(above[-1]) or _AYES.search(above[-1]) or _SPOKE.search(above[-1]):
            break
        words = clean(above.pop() + " " + words)
    if _DONE.match(words):
        return words
    return own or (clean(before[-2]) if len(before) > 1 and shouted_line(before[-2]) and not _AYES.search(before[-2]) else "")


# ---------------------------------------------------------------------------
# A meeting: its agenda, and its minutes laid on it
# ---------------------------------------------------------------------------

PART_NAMES = {"consent": "Consent Calendar", "regular": "Regular Calendar", "action": "Board Action",
              "information": "Board Information & Possible Action", "scheduled": "Scheduled Items", "budget": "Budget Calendar",
              "reports": "Reports/Board Direction"}


def laid(agenda, scanned):
    """A meeting's lines: those of its agenda in the agenda's order, each with the record of the minutes that is of
    it, and after them what the minutes have and the agenda has not (a vote before the first part of the meeting, an
    item pulled from the agenda before the page was last saved).

    A numbered item of the minutes is the agenda's item of that number only in the same part of the meeting, or in
    another part whose items are numbered.
    """
    records = scanned["records"] if scanned else []
    by_number, by_part, by_group, by_hearing, taken = {}, {}, {}, {}, set()
    for index, record in enumerate(records):
        if record["kind"] == "item":
            by_number.setdefault(record["number"], []).append(index)
        elif record["kind"] == "part":
            by_part.setdefault(record["part"], []).append(index)
        elif record["kind"] == "group":
            by_group.setdefault(near(record["lines"][0]), []).append(index)
        elif record["kind"] == "hearing" and record["hearing"] is not None:
            by_hearing[record["hearing"]] = index
    out, unnumbered = [], 0
    for line in agenda:
        index = None
        if line["kind"] == "part" and by_part.get(line["part"]):
            index = by_part[line["part"]].pop(0)
        elif line["kind"] == "item" and line["number"]:
            index = next((one for one in by_number.get(line["number"], []) if one not in taken and (
                records[one]["part"] == line["part"] or {records[one]["part"], line["part"]} <= set(_NUMBERED_PARTS))), None)
        elif line["kind"] == "department":
            index = next((one for one in by_group.get(near(line["title"]), []) if one not in taken and records[one]["part"] == line["part"]), None)
        elif line["kind"] == "item":
            index, unnumbered = by_hearing.get(unnumbered), unnumbered + 1
        if index is not None:
            taken.add(index)
        out.append({**line, "record": records[index] if index is not None else None})
    # A vote that stands under no item (before the first part of the meeting, or under a heading that is not voted
    # on as one) is a line of its own, known by what was done.
    for line in list(out):
        record = line["record"]
        if record and line["kind"] == "part" and line["part"] not in _VOTED_AS_ONE and record["motions"]:
            line["record"] = {**record, "motions": []}
            out.extend(loose(record, line["part"]))
    for index, record in enumerate(records):
        if index in taken:
            continue
        if record["kind"] in ("item", "hearing"):
            out.append({"kind": "item", "part": record["part"], "number": record["number"], "title": record["title"], "head": "",
                        "matter_id": "", "papers": "", "department": "", "record": record, "added": True})
        elif record["kind"] == "part" and record["part"] in _VOTED_AS_ONE and record["motions"]:
            out.append({"kind": "part", "part": record["part"], "number": "", "title": record["lines"][0], "head": "", "matter_id": "",
                        "papers": "", "department": "", "record": record, "added": True})
        elif record["kind"] == "group" and record["motions"]:
            out.append({"kind": "department", "part": record["part"], "number": "", "title": record["lines"][0], "head": "", "matter_id": "",
                        "papers": "", "department": record["lines"][0], "record": record, "added": True})
        elif record["motions"]:
            out.extend(loose(record, record["part"]))
    return out


def loose(record, part):
    """A line for each vote of a record that is no item's."""
    return [{"kind": "item", "part": part, "number": "", "title": motion["text"] or motion["printed"], "head": "", "matter_id": "",
             "papers": "", "department": "", "added": True,
             "record": {**record, "kind": "loose", "motions": [motion], "pulled": "", "outcome": "", "number_given": ""}}
            for motion in record["motions"]]


def read_meeting(meeting, agenda, scanned=None, roll=(), minutes_url=""):
    """One meeting's lines, and the votes on each motion that could be read whole. With no minutes read (`scanned` is
    None) the lines are the agenda's, with nothing done."""
    meeting_id, date = meeting["meeting_id"], meeting["date"]
    roll = list(roll)
    lines = laid(agenda, scanned)
    used, counts = set(), Counter()
    for line in lines:
        if line["kind"] == "part":
            base = f"{meeting_id}-{line['part']}"
        elif line["kind"] == "department":
            counts["d"] += 1
            base = f"{meeting_id}-d{counts['d']}"
        elif line["number"]:
            # A presentation numbered before the first part of the meeting is not item 1 of the consent calendar.
            base = f"{meeting_id}-{line['number']}" if line["part"] else f"{meeting_id}-opening{line['number']}"
        else:
            counts["u"] += 1
            base = f"{meeting_id}-u{counts['u']}"
        item_id, again = base, 1
        while item_id in used:  # a number the agenda uses twice
            again += 1
            item_id = f"{base}-{again}"
        used.add(item_id)
        line["item_id"] = item_id
    # The line whose one vote took an item in: the part of the meeting it stands in (the consent calendar), or, once,
    # its department.
    part_line, voted_as_one, department = {}, {}, None
    for line in lines:
        if line["kind"] == "part":
            part_line.setdefault(line["part"], line)
            department = None
        elif line["kind"] == "department":
            department = line if line.get("record") and line["record"]["motions"] and not line.get("added") else None
        elif department is not None and not line.get("added"):
            voted_as_one[line["item_id"]] = department
    for line in lines:
        if line["kind"] == "item" and line["part"] in _VOTED_AS_ONE and line["part"] in part_line:
            voted_as_one.setdefault(line["item_id"], part_line[line["part"]])

    noted = []
    if scanned:
        # Those a page appended to the minutes has not present (by name, or by leaving them out of who was), where
        # the minutes themselves say nothing of their coming or going.
        said_of = {surname_of(name) for _, _, names in scanned["events"] for name in names}
        short = [surname_of(member["name"]) for there in scanned["present"] if len(there) < len(roll)
                 for member in roll if surname_of(member["name"]) not in {surname_of(name) for name in there}]
        noted = sorted({key for key in [surname_of(name) for name in scanned["noted"]] + short if key not in said_of})
    district = {member["name"]: member["district"] for member in roll}
    rows, votes, facts = [], [], {"motions": 0, "motions_read": 0}
    for sequence, line in enumerate(lines, 1):
        record, heading = line.get("record"), line["kind"] != "item"
        motions = record["motions"] if record else []
        matter_id = "" if heading else line["matter_id"]
        log_of = []
        for number, motion in enumerate(motions, 1):
            cast, problem = (None, motion["problem"]) if motion["problem"] else decide(motion["parts"], roll, motion["away"], noted)
            order = scanned["orders"].get(line["number"]) if line["number"] else None
            if cast and order and len(order) == 1 and len(motions) == 1 and not agrees(cast, order[0], roll):
                cast, problem = None, "the Board Order appended to the minutes has the vote otherwise"
            motion = {**motion, "cast": cast or [], "read": cast is not None, "problem": problem}
            log_of.append(motion)
            for member, word, established in motion["cast"]:
                votes.append({"item_id": line["item_id"], "meeting_id": meeting_id, "date": date, "matter_id": matter_id, "matter_file": "",
                              "member": member, "vote": word, "district": district[member], "motion": number,
                              "motion_text": motion["text"], "established": established})
        last = log_of[-1] if log_of else None
        cast = [word for _, word, _ in last["cast"]] if last else []
        ways = sorted({established for motion in log_of for _, _, established in motion["cast"]})
        over = voted_as_one.get(line["item_id"]) if not heading else None
        under = bool(over and over.get("record") and over["record"]["motions"] and record and not motions and not record["outcome"])
        section = part_line.get(line["part"])
        text = last["text"] if last else record["outcome"] if record else ""
        rows.append({
            "item_id": line["item_id"], "meeting_id": meeting_id, "date": date, "body": BODY,
            "agenda_number": line["number"], "sequence": sequence, "matter_id": matter_id, "matter_file": "",
            "title": line["title"], "action": text,
            "result": "Fail" if last and re.search(r"\bFAILED\b", last["text"]) else "Pass" if last and _PASSED.match(last["text"]) else "",
            "mover": "", "seconder": "",
            "ayes": cast.count(council_tables.AYE), "noes": cast.count(council_tables.NO),
            "not_voting": sum(word not in (council_tables.AYE, council_tables.NO) for word in cast),
            "heading": heading,
            "section": PART_NAMES.get(line["part"], "") if not heading else "",
            "section_id": section["item_id"] if section and not heading else "",
            "department": line["department"] if line["kind"] == "item" else "",
            "motions": len(log_of), "motions_read": sum(motion["read"] for motion in log_of),
            "votes_read": all(motion["read"] for motion in log_of) if log_of else None,
            "problem": next((motion["problem"] for motion in log_of if not motion["read"]), ""),
            "how": last["printed"] if last else "",
            "established": ways[0] if len(ways) == 1 else "",
            "voted_with": line["item_id"] if log_of else over["item_id"] if under else "",
            "doc_type": "" if heading else county.doc_type_of(line["title"]),
            "number": record["number_given"] if record else "",
            "documents_url": address(meeting["agenda_url"], line["papers"]) if line["papers"] else "",
            "source": "minutes" if line.get("added") else "agenda, minutes" if record else "agenda",
            "motion_log": json.dumps([{"motion": number, "action": motion["text"], "how": motion["printed"], "read": motion["read"],
                                       "problem": motion["problem"]} for number, motion in enumerate(log_of, 1)],
                                     ensure_ascii=False, separators=(",", ":")) if log_of else "",
        })
        facts["motions"] += len(log_of)
        facts["motions_read"] += sum(motion["read"] for motion in log_of)
    if scanned:
        facts.update(minutes="read", pages=scanned["pages"], present=scanned["recess"], minutes_url=minutes_url,
                     roll=json.dumps(roll, ensure_ascii=False, separators=(",", ":")))
    return rows, votes, facts


def agrees(cast, order, roll):
    """Whether a vote read off its line is the vote a Board Order appended to the same minutes gives by name. An
    order names the ayes and the noes; whoever it does not name, or names as absent, did not vote."""
    aye_no = (council_tables.AYE, council_tables.NO)
    said = {}
    for word, names in order.items():
        for name in names:
            member = who(name, roll)
            if member is None:
                return False
            said[member["name"]] = word if word in aye_no else ""
    return all(said.get(member, "") == (word if word in aye_no else "") for member, word, _ in cast)


def placed(kind, on_day):
    """Which of a day's meetings a set of minutes of some sort is of, or "" where that cannot be told."""
    same = [row for row in on_day if kind_of(row["name"]) == kind]
    if len(same) == 1:
        return same[0]["meeting_id"]
    if not same and len(on_day) == 1 and kind != "addendum":
        return on_day[0]["meeting_id"]
    return ""


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------

def items_table(agenda, meetings):
    """Every item of a meeting whose minutes were read, with what was done with it: by a vote of its own, or by the
    one vote of the part of the meeting it stood in (the consent calendar).

    The site has no record of an item apart from its line on an agenda, so an item is here once for each meeting it
    came to.
    """
    read = meetings[meetings["minutes"] == "read"]
    minutes = dict(zip(read["meeting_id"], read["minutes_url"]))
    of = agenda.set_index("item_id")
    rows = []
    for line in agenda[~agenda["heading"] & agenda["meeting_id"].isin(set(minutes))].itertuples(index=False):
        own = line.motions > 0
        over = of.loc[line.voted_with] if not own and line.voted_with else None
        vote = line._asdict() if own else over.to_dict() if over is not None else None
        rows.append({
            "date": line.date, "matter_id": line.matter_id or line.item_id, "matter_file": "", "doc_type": line.doc_type, "title": line.title,
            "body": line.body, "status": "", "year": int(line.date[:4]), "subject": line.department, "agenda_date": line.date,
            "passed_date": "", "last_action": line.action or (vote["action"] if vote else ""), "last_action_date": line.date,
            "result": vote["result"] if vote else "",
            "ayes": int(vote["ayes"]) if vote else 0, "noes": int(vote["noes"]) if vote else 0, "mover": "", "seconder": "",
            "times_on_agenda": 1, "url": minutes.get(line.meeting_id, ""),
            "item_id": line.item_id, "meeting_id": line.meeting_id, "section": line.section, "department": line.department,
            "action_on": "item" if own else "section" if over is not None else "",
            "votes_read": bool(vote["votes_read"]) if vote else None,
            "number": line.number,
        })
    out = pd.DataFrame(rows, columns=ITEM_COLUMNS)
    out["votes_read"] = out["votes_read"].astype("boolean")
    return out.sort_values(["date", "meeting_id", "item_id"], ascending=[False, False, True]).reset_index(drop=True)


def members_table(votes, meetings, asof=None):
    """Everyone who voted on two days or more, with the district the head of the minutes gives them. `serving` is
    true for those whose last vote is within SERVING_DAYS of the day of the run, and `role` is then the office the
    newest minutes read give them. The minutes give no terms of office."""
    since = (datetime.strptime(asof or today(), "%Y-%m-%d") - timedelta(days=SERVING_DAYS)).strftime("%Y-%m-%d")
    seats, offices = {}, {}
    for meeting in meetings[meetings["roll"] != ""].sort_values("date").itertuples(index=False):
        offices = {}
        for member in json.loads(meeting.roll):
            seats[member["name"]] = member["district"]
            offices[member["name"]] = member["role"]
    cast = votes.groupby("member")["date"].agg(["min", "max", "size", "nunique"]) if len(votes) else pd.DataFrame()
    rows = [{"name": name, "district": seats.get(name), "role": offices.get(name, "") if cast.loc[name, "max"] >= since else "",
             "start": "", "end": "", "serving": cast.loc[name, "max"] >= since, "first_vote": cast.loc[name, "min"],
             "last_vote": cast.loc[name, "max"], "votes": int(cast.loc[name, "size"])}
            for name in sorted(cast.index) if cast.loc[name, "nunique"] >= 2]
    out = pd.DataFrame(rows, columns=council_tables.COLUMNS["members"])
    out["district"] = out["district"].astype("Int64")
    out["serving"] = out["serving"].astype(bool)
    out["votes"] = out["votes"].astype(int)
    return out.sort_values(["first_vote", "district", "name"]).reset_index(drop=True)


def joined(held, new):
    """Two tables of the same columns as one. An empty one adds nothing, and is left out so it cannot change a column's kind."""
    some = [table for table in (held, new) if len(table)]
    return pd.concat(some, ignore_index=True) if some else held


def typed(agenda, votes):
    for table, columns in ((agenda, ("sequence", "ayes", "noes", "not_voting", "motions", "motions_read")), (votes, ("motion",))):
        for column in columns:
            table[column] = table[column].astype(int)
    agenda["heading"] = agenda["heading"].astype(bool)
    agenda["votes_read"] = agenda["votes_read"].astype("boolean")
    votes["district"] = votes["district"].astype("Int64")
    return agenda, votes


FACTS = (("minutes_url", ""), ("minutes", ""), ("minutes_from", ""), ("approved", ""), ("pages", 0), ("roll", ""), ("present", ""),
         ("motions", 0), ("motions_read", 0), ("note", ""))


def build(base, everything, out_dir, since=FIRST_YEAR, limit=0):
    rows = listed(since)
    log.info(f"Merced County: {len(rows)} meetings of the Board listed")
    if len(rows) < 20:
        raise RuntimeError("the listing of meetings came back nearly empty")
    meetings = meetings_table(rows)

    agenda, votes, before_meetings = (council_tables.held(HF_REPO, out_dir, name, base) for name in ("agenda_items", "votes", "meetings"))
    before = 0 if votes is None else len(votes)
    if agenda is None or votes is None or before_meetings is None:
        agenda, votes = pd.DataFrame(columns=AGENDA_COLUMNS), pd.DataFrame(columns=VOTE_COLUMNS)
        before_meetings = pd.DataFrame(columns=MEETING_COLUMNS)
    found = {row["meeting_id"]: {name: row.get(name, empty) for name, empty in FACTS} for row in before_meetings.to_dict("records")}
    held_lines = set(agenda["meeting_id"])
    recent = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    text = Path(out_dir) / "text"
    listing = meetings.to_dict("records")
    pages = [row for row in listing if row["agenda"] == "html"]
    kept = lambda row: (text / "agendas" / f"{row['meeting_id']}.txt").exists()

    # First the agendas: those of the last months again (an agenda is amended up to its meeting), and those not read
    # before. Each is kept as it comes, so a run that is stopped has lost nothing.
    wanted = [row for row in pages if row["date"] >= recent or (not kept(row) and (everything or row["meeting_id"] not in held_lines))]
    wanted.sort(key=lambda row: (row["date"], row["meeting_id"]), reverse=True)  # the newest first
    log.info(f"Fetching {len(wanted[:limit] if limit else wanted)} agendas of {len(wanted)} not yet read or to be read again")
    fetched = {"agendas": 0, "minutes": 0}
    for row in (wanted[:limit] if limit else wanted):
        try:
            agenda_of(row, out_dir, fresh=True)
            fetched["agendas"] += 1
        except Refused as e:
            log.error(f"The host refused a request ({e}): no more is asked of it in this run")
            break
        except Exception as e:
            log.warning(f"agenda of {row['meeting_id']}: {type(e).__name__}: {e}")
    lines = {row["meeting_id"]: agenda_lines(agenda_of(row, out_dir)) for row in pages if kept(row)}

    # Then the minutes. Every agenda from MINUTES_FROM on is looked through for an item that approves minutes; the
    # papers filed with it are listed, and each that is not another body's by its name is fetched and its own head
    # read for the day and the sort of meeting it is of. A later approval of the same meeting's minutes stands.
    on_day = {}
    for row in listing:
        on_day.setdefault(row["date"], []).append(row)
    approving = []
    for row in sorted(listing, key=lambda row: (row["date"], row["meeting_id"])):
        if row["date"] < f"{MINUTES_FROM}-01-01":
            continue
        if row["meeting_id"] in lines:
            approving += [(row, line["matter_id"], address(row["agenda_url"], line["papers"])) for line in lines[row["meeting_id"]]
                          if line["kind"] == "item" and line["papers"] and _APPROVES.search(line["title"])]
        else:
            of = agenda[(agenda["meeting_id"] == row["meeting_id"]) & (agenda["documents_url"] != "")]
            approving += [(row, one.matter_id, one.documents_url) for one in of.itertuples(index=False) if _APPROVES.search(one.title)]
    approved, sets, scans = {}, {}, {}
    for row, matter_id, url in approving:
        here = (text / "documents" / f"{row['meeting_id']}-{matter_id}.txt").exists()
        again = row["date"] >= recent and not _refused.is_set()
        if not here and not again and not everything and found.get(row["meeting_id"], {}).get("approved"):
            continue  # looked at in an earlier run, whose findings are held
        try:
            papers = papers_listed(row["meeting_id"], matter_id, url, out_dir, fresh=again)
        except Refused as e:
            log.error(f"The host refused a request ({e}): no more is asked of it in this run")
            papers = papers_listed(row["meeting_id"], matter_id, url, out_dir) if here else []
        except Exception as e:
            log.warning(f"papers of {row['meeting_id']} item {matter_id}: {type(e).__name__}: {e}")
            continue
        entries = approved.setdefault(row["meeting_id"], [])
        for name, link in papers:
            if _ITEM_PAPER.match(name):
                continue
            if _OTHER_BODY.search(name):
                entries.append({"name": name, "url": link, "minutes": "another body", "date": "", "meeting_id": ""})
                continue
            if not (text / f"{paper_id(link)}.txt").exists():
                if _refused.is_set() or (limit and fetched["minutes"] >= limit):
                    entries.append({"name": name, "url": link, "minutes": "not fetched", "date": "", "meeting_id": ""})
                    continue
                try:
                    text_of(link, out_dir)
                    fetched["minutes"] += 1
                except Exception as e:
                    log.warning(f"minutes {name} of {row['meeting_id']}: {type(e).__name__}: {e}")
                    entries.append({"name": name, "url": link, "minutes": "not fetched", "date": "", "meeting_id": ""})
                    continue
            whole = text_of(link, out_dir)
            parts = sets_in(whole)
            if not parts:  # a scan: its day and sort are known only by the name the page gives it
                date = day_in(name)
                meeting_id = placed(kind_of(name), on_day.get(date, [])) if date else ""
                entries.append({"name": name, "url": link, "minutes": "no text layer", "date": date, "meeting_id": meeting_id})
                if meeting_id:
                    scans[meeting_id] = {"url": link, "from": row["meeting_id"], "pages": whole.count("\f") + 1}
                continue
            for part in parts:
                head = head_of(part)
                entry = {"name": name, "url": link, "minutes": "another body" if head["other"] else "", "date": head["date"], "meeting_id": ""}
                entries.append(entry)
                if head["other"]:
                    continue
                entry["meeting_id"] = placed(head["kind"], on_day.get(head["date"], [])) if head["date"] else ""
                entry["minutes"] = "read" if entry["meeting_id"] else "no meeting listed" if head["date"] else "no date"
                if entry["meeting_id"]:
                    sets[entry["meeting_id"]] = {"text": part, "head": head, "url": link, "from": row["meeting_id"]}
    log.info(f"Merced County: {fetched['agendas']} agendas and {fetched['minutes']} sets of minutes fetched; "
             f"minutes at hand for {len(sets)} meetings, scans for {len(scans)}")

    # A supervisor is printed more than one way from one year's minutes to the next; the way most often printed stands.
    forms = {}
    for one in sets.values():
        for member in one["head"]["roster"]:
            forms.setdefault(key_of(member["name"]), Counter())[member["name"]] += 1
    for meeting_id, facts in found.items():
        if meeting_id not in sets:
            for member in json.loads(facts.get("roll") or "[]"):
                forms.setdefault(key_of(member["name"]), Counter())[member["name"]] += 1
    names = {key: sorted(counts.items(), key=lambda form: (-form[1], form[0]))[0][0] for key, counts in forms.items()}

    # Then every meeting whose agenda is at hand is read, old and new, and with it its minutes where they are at hand.
    # A meeting whose minutes were read in an earlier run and are not kept here stays as it was read then.
    new_agenda, new_votes, rebuilt = [], [], set()
    for row in listing:
        meeting_id = row["meeting_id"]
        one, was = sets.get(meeting_id), found.get(meeting_id, {})
        if meeting_id not in lines and not one:
            continue
        if not one and was.get("minutes") == "read" and meeting_id in held_lines:
            continue
        of = lines.get(meeting_id, [])
        scanned, roll = None, []
        if one:
            roll = [{**member, "name": names[key_of(member["name"])]} for member in one["head"]["roster"]]
            items = [line for line in of if line["kind"] == "item"]
            scanned = scan(one["text"], {line["number"]: line["title"] for line in items if line["number"]},
                           [line["head"] for line in items if not line["number"]],
                           {line["number"]: line["department"] for line in items if line["number"]})
        reading = read_meeting(row, of, scanned, roll, one["url"] if one else "")
        new_agenda.extend(reading[0])
        new_votes.extend(reading[1])
        rebuilt.add(meeting_id)
        facts = {**dict(FACTS), **reading[2], "approved": was.get("approved", "")}
        if one:
            facts.update(minutes_from=one["from"], note="the minutes are marked a draft" if one["head"]["draft"] else "")
        elif meeting_id in scans:
            facts.update(minutes="no text layer", minutes_url=scans[meeting_id]["url"], minutes_from=scans[meeting_id]["from"],
                         pages=scans[meeting_id]["pages"], note="the minutes are a scan, and are not read")
        found[meeting_id] = facts
    for meeting_id, entries in approved.items():
        found.setdefault(meeting_id, dict(FACTS))["approved"] = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
    agenda = joined(agenda[~agenda["meeting_id"].isin(rebuilt)], pd.DataFrame(new_agenda, columns=AGENDA_COLUMNS))
    votes = joined(votes[~votes["meeting_id"].isin(rebuilt)], pd.DataFrame(new_votes, columns=VOTE_COLUMNS))
    listed_ids = set(meetings["meeting_id"])
    agenda = agenda[agenda["meeting_id"].isin(listed_ids)].sort_values(["date", "meeting_id", "sequence"]).reset_index(drop=True)
    votes = votes[votes["meeting_id"].isin(listed_ids)].sort_values(["date", "meeting_id", "item_id", "motion", "district"]).reset_index(drop=True)
    agenda, votes = typed(agenda, votes)
    for name, empty in FACTS:
        meetings[name] = [found.get(meeting_id, {}).get(name, empty) for meeting_id in meetings["meeting_id"]]
    count = agenda[~agenda["heading"]].groupby("meeting_id").size() if len(agenda) else {}
    meetings["items"] = meetings["meeting_id"].map(count).fillna(0).astype(int)
    for column in ("pages", "motions", "motions_read"):
        meetings[column] = meetings[column].fillna(0).astype(int)

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
    ways = votes["established"].value_counts() if len(votes) else {}
    facts = {
        "repo": HF_REPO, "first_listed": meetings["date"].min() if len(meetings) else "",
        "first_meeting": read["date"].min() if len(read) else "", "last_meeting": read["date"].max() if len(read) else "",
        "first_vote": votes["date"].min() if len(votes) else "", "last_vote": votes["date"].max() if len(votes) else "",
        "n_read": f"{len(read):,}", "n_scans": f"{int((meetings['minutes'] == 'no text layer').sum()):,}",
        "n_motions": f"{motions:,}", "n_motions_read": f"{motions_read:,}", "n_unread": f"{motions - motions_read:,}",
        "share_read": f"{100 * motions_read / motions:.1f}" if motions else "0", "recent_days": RECENT_DAYS, "first_year": FIRST_YEAR,
        "minutes_from": MINUTES_FROM,
        **{f"n_{way}": f"{int(ways.get(way, 0)):,}" for way in (NUMBERS, ALL, NAMES)},
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
        log.error(f"Merced County tables not uploaded: {e}")
        return False
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the Merced County Board's meetings, agendas, actions and votes")
    parser.add_argument("--base", action="store_true", help="start from the tables written here, not the published ones")
    parser.add_argument("--all", action="store_true", help="fetch again every agenda and set of minutes not kept here")
    parser.add_argument("--since", type=int, default=FIRST_YEAR, help="read no meeting before this year")
    parser.add_argument("--max", type=int, default=0, help="agendas, and sets of minutes, to fetch in one run (0 for all)")
    parser.add_argument("--out", default="", help="directory to write the tables into (minutes_pdf/merced-county if not given)")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the tables only")

    out_dir = Path(args.out) if args.out else OUT_DIR
    try:
        tables, fetched = build(args.base, args.all, out_dir, args.since, args.max)
    except Exception as e:
        log.error(f"Merced County tables not built: {type(e).__name__}: {e}")
        return 1
    pushed = False if args.no_upload else upload(tables, out_dir, args.write_card)
    meetings, agenda, votes, members = tables["meetings"], tables["agenda_items"], tables["votes"], tables["members"]
    motions, motions_read = int(agenda["motions"].sum()), int(agenda["motions_read"].sum())
    ways = votes["established"].value_counts() if len(votes) else {}
    log.info(f"RESULT: merced-board items={len(tables['items'])} meetings={len(meetings)} "
             f"minutes_read={int((meetings['minutes'] == 'read').sum())} "
             f"no_text_layer={int((meetings['minutes'] == 'no text layer').sum())} agenda_items={len(agenda)} "
             f"motions={motions} motions_read={motions_read} motions_unread={motions - motions_read} votes={len(votes)} "
             f"numbers={int(ways.get(NUMBERS, 0))} all={int(ways.get(ALL, 0))} names={int(ways.get(NAMES, 0))} "
             f"members={len(members)} serving={int(members['serving'].sum())} "
             f"agendas_fetched={fetched['agendas']} minutes_fetched={fetched['minutes']} "
             f"first_vote={votes['date'].min() if len(votes) else ''} last_vote={votes['date'].max() if len(votes) else ''} "
             f"refused={_refused.is_set()} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
