#!/usr/bin/env python3
"""
Build chrissoria/calaveras-county-board: the meetings of the Calaveras County
Board of Supervisors, what the Board did at each, and how each supervisor
voted, read from the minutes of each meeting.

One source: the County's meeting portal (IQM2), calaverascountyca.iqm2.com.
build_iqm2_board.py reads the same portal a page at a time, one page for every
agenda item, and most of those pages have no vote. The minutes of a meeting are
one document (FileOpen.aspx?Type=12), a PDF with its own text, and they have
the votes back to 2000. This reader lists the calendar as build_iqm2_board.py
does and reads the minutes.

The minutes print a vote in three ways, by when they were written:

  From 23 September 2014, the portal's own minutes (`format` "portal"). The
  head has a table of who was there (Attendee Name / Title / Status / Arrived),
  and each item ends in a block:

      RESULT: ADOPTED [4 TO 1]
      MOVER: Amanda Folendorf, Vice-Chair
      SECONDER: Gary Tofanelli, District 1 Supervisor
      AYES: Folendorf, Stopper, Andahl, Tofanelli
      NAYS: Huberty

  with ABSENT, ABSTAIN, RECUSED, AWAY and EXCUSED lines where there are any.

  From 11 June 2013 to 9 September 2014, a sentence (`format` "prose"), which
  until January 2014 gives a count in place of the names:

      Motion by Supervisor Spellman, second by Supervisor Edson. Unanimously
      approved by Supervisors Edson, Wright, Callaway, Ponte and Spellman.
      ... Approved by Supervisors Edson, Wright, Ponte and Spellman.
      Supervisor Callaway voted no.
      A motion by Supervisor Ponte, a second by Supervisor Wright. 5-0 approved.

  Before that, from 2000 to 28 May 2013, a line under the motion's words
  (`format` "moved"):

      Moved: Callaway Second: Tryon Approval: Unanimous
      ABSENT: Stein
      Moved: Stein Second: Callaway Approval: Majority NOES: Tryon

Who was there is at the head: the portal's table, or "PRESENT: Lucy Thein,
Chair; ... and Thomas Tryon, Supervisors; ..." and "ABSENT: None".

`established` on each vote says how it is known:

  named      the minutes name the supervisor on that motion, with a word.
  count      the minutes give a count ("5-0 approved", "4-1 approved,
             Supervisor Wright voted no") and name only those who were not
             ayes. The ayes are the supervisors left, and they must be as many
             as the count says.
  unanimous  the minutes say only "Unanimous". The ayes are those the head has
             present, less anyone the minutes have away at that point and
             anyone the line names.
  majority   the minutes say "Majority" and name who did not vote aye
             ("NOES: Tryon"). The ayes are worked out as for unanimous.

A motion is read whole or not at all. One whose names are not all on that
meeting's roll, whose count and names disagree, or that is told in words the
reader does not know, puts nothing in votes: its line stays in agenda_items
with `votes_read` false and what stopped it in `problem`.

The dataset has the five tables every council's and board's dataset has
(council_tables.py), in data/:
  items.parquet          every item in minutes that were read
  meetings.parquet       one row per meeting of the Board the calendar lists
  agenda_items.parquet   one row per item, and one per consent calendar voted on as one
  votes.parquet          one row per supervisor and motion voted on
  members.parquet        one row per supervisor with votes on two days or more
They are kept here in minutes_pdf/calaveras-county/, with the text of each set
of minutes beside them in text/, so a document is fetched once.

Two ways to run it:

    python build_calaveras_board.py
        The routine run. Starts from the published tables, lists the calendar
        again, and fetches the minutes not read before.

    python build_calaveras_board.py --base
        The same, starting from the tables written here. It fetches the newest
        minutes first, one a minute, writes the tables every 20 documents, and
        can be stopped and started again: minutes whose text is kept here are
        read again on every run, which asks nothing of the portal.

    --since YEAR  read no meeting before this year (default 2000, where the calendar begins)
    --max N       minutes to fetch in one run (default 0, for all)
    --all         fetch again every set of minutes, whether its text is kept here or not
    --out DIR     where to write the tables
    --no-upload   write the tables but do not publish them
    --write-card  publish the dataset card as well as the tables

Needs pdfplumber. Only a PDF's own text is read: minutes that are a scan are
counted and left.
"""

import argparse
import io
import json
import logging
import re
import sys
import time
from collections import Counter
from datetime import date as day_type
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import requests

import build_federal_bills as bills
import build_iqm2_board as iqm2
import build_sd_county as county
import council_tables
from build_sd_county import clean, today

log = logging.getLogger(__name__)

HF_REPO = "chrissoria/calaveras-county-board"
OUT_DIR = bills.SCRIPT_DIR / "minutes_pdf" / "calaveras-county"
CARD_FILE = bills.SCRIPT_DIR / "README_calaveras_board.md"
TABLES = council_tables.TABLES
BODY = "Board of Supervisors"

KEY = "calaveras-county"  # the County's name in build_iqm2_board.BOARDS, whose listing of the calendar is used here
# Seconds waited after each minutes document. The portal's robots.txt asks for "Crawl-delay: 60", and a whole read is
# a thousand documents, so it is kept to: about seventeen hours, once.
PAUSE = 60
EVERY = 20  # documents fetched between one writing of the tables and the next
FIRST_YEAR = iqm2.BOARDS[KEY]["first"]
SEATS = 5  # a county's board of supervisors (Government Code 25000)
QUORUM = 3
SERVING_DAYS = 120  # a supervisor who voted this close to the newest minutes read is taken to be serving
SEEN_DAYS = 2  # someone is a member if they vote on this many days: once may be a clerk's slip or a misread name
APART_DAYS = 366  # two heads naming a supervisor further apart than this say nothing of the time between them
LAYER_CHARS = 200  # minutes with fewer characters of their own than this are a scan
INDENT = 6  # points to one space of a line's distance in from the margin
WIDE = 36  # points between two words that stand in different columns of the page

MEETING_COLUMNS = council_tables.COLUMNS["meetings"] + [
    "name", "status", "packet_url", "summary_url", "minutes", "format", "pages", "roll", "roll_from", "letterhead", "motions", "motions_read"]
AGENDA_COLUMNS = council_tables.COLUMNS["agenda_items"] + [
    "heading", "section", "section_id", "motions", "motions_read", "votes_read", "problem", "outcome", "established", "voted_with",
    "doc_type", "file_type", "department", "number", "motion_log"]
VOTE_COLUMNS = council_tables.COLUMNS["votes"] + ["motion", "motion_text", "established"]
ITEM_COLUMNS = council_tables.COLUMNS["items"] + ["item_id", "meeting_id", "section", "action_on", "votes_read", "number"]

# The three ways the minutes are set out, and the four ways a vote is known.
PORTAL, PROSE, MOVED = "portal", "prose", "moved"
NAMED, COUNT, UNANIMOUS, MAJORITY = "named", "count", "unanimous", "majority"
AYE, NO = council_tables.AYE, council_tables.NO
OUT_OF_ROOM = ("ABSENT", "AWAY", "EXCUSED", "NOT PRESENT")

# The minutes' words for a vote, by their letters, and the word the tables have for each.
WORDS = {"ayes": AYE, "aye": AYE, "yeas": AYE, "yes": AYE, "noes": NO, "noe": NO, "no": NO, "nays": NO, "nay": NO,
         "dissenting": NO, "dissent": NO, "opposed": NO, "absent": "ABSENT", "abstain": "ABSTAIN", "abstained": "ABSTAIN",
         "abstaining": "ABSTAIN", "abstentions": "ABSTAIN", "abstention": "ABSTAIN", "recused": "RECUSED", "recuse": "RECUSED",
         "away": "AWAY", "excused": "EXCUSED", "notpresent": "NOT PRESENT", "notvoting": "NOT VOTING"}
ROLES = {"chair": "Chair", "chairman": "Chair", "chairwoman": "Chair", "chairperson": "Chair", "vicechair": "Vice-Chair",
         "vicechairman": "Vice-Chair", "vicechairwoman": "Vice-Chair", "vicechairperson": "Vice-Chair"}
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5}
# The clerk's words for a motion that carried. Any other word ("TABLED", "CONTINUED") is kept in `outcome` and not judged.
CARRIED = re.compile(r"^(?:adopted|approved|accepted|passed|carried|confirmed|ratified)\b", re.I)
LOST = re.compile(r"\b(?:failed|fails|defeated|did\s+not\s+carry)\b", re.I)

_OFFICE = r"(?:Supervisors?|Chair(?:man|woman|person)?|Vice[- ]?Chair(?:man|woman|person)?)"
_SURNAME = r"[A-Z][A-Za-z’'-]+"
_PEOPLE = rf"{_OFFICE}\s+{_SURNAME}(?:(?:\s*,\s*(?:and\s+)?|\s+and\s+)(?:{_OFFICE}\s+)?{_SURNAME})*"
_LOOSE = rf"(?:{_OFFICE}\s+)?{_SURNAME}(?:(?:\s*,\s*(?:and\s+)?|\s+and\s+)(?:{_OFFICE}\s+)?{_SURNAME})*"  # "Wright and Spellman voted no."

# A line that is the page's and not the minutes': the portal's stamp and running head, a page's number.
_FURNITURE = re.compile(
    r"^(?:Generated \d{1,2}/\d{1,2}/\d{4}.*|.{0,40}\b(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day, [A-Z][a-z]+ \d{1,2}, \d{4}\s+\d{1,2}:\d{2} [AP]M"
    r"|\d{1,3}\s?\|\s?P\s?a\s?g\s?e|\(?PAGE \d+ of \d+ ?\)?|\(continued to PAGE \d+\)|(?:\d{1,2}/\d{1,2}/\d{2,4} )?FINAL MINUTES"
    r"|[A-Z][a-z]+ \d{1,2}, \d{4}|\d{1,3}|\d{8}\w?(?: \S{1,12})?)$", re.I)
_CLOSES = re.compile(r"^(?:ADJOURNMENT\b|ATTEST\b|The meeting was closed at|THE BOARD REVIEWED THE FOLLOWING ITEMS OF CORRESPONDENCE)", re.I)
_HOUR = r"(?:\d{1,2}:\d{2}\s*[AP]\.?M\.?(?:\s*(?:TO|-|–)\s*\d{1,2}:\d{2}\s*[AP]\.?M\.?)?\s*:?\s*)"
# The parts a meeting's minutes are in, by the letters each one's line begins with.
SECTIONS = {"consentagenda": "Consent Agenda", "consentcalendar": "Consent Agenda", "regularagenda": "Regular Agenda",
            "closedsession": "Closed Session Agenda", "recognitionandacknowledg": "Recognition and Acknowledgments",
            "generalpubliccomment": "Public Comment", "publiccomment": "Public Comment", "publichearing": "Public Hearings",
            "supervisorannouncements": "Supervisor Announcements", "staffannouncements": "Staff Announcements",
            "announcements": "Announcements", "studysession": "Study Session", "itemspulledfrom": "Items Pulled from the Consent Agenda",
            "calltoorder": "Call to Order", "pledgeofallegiance": "Pledge of Allegiance"}
_NUMBERED = re.compile(r"^(\d{1,3}[a-z]?(?:\s?(?:&|,|and)\s?\d{1,3}[a-z]?)*)\s?\.\s+(\S.*)$")  # "9.", "17a.", "12 & 13."
# An item of the portal's minutes: "Agreement - Public Works (ID # 9118) Award ..." or "Resolution - Sheriff 20260526r025 Adopt ...".
_FILED = re.compile(r"^(?P<type>[A-Z][A-Za-z&/ ]{2,40}?) - (?P<department>.{2,90}?) (?:\(ID # ?(?P<id>\d+)\)|(?P<number>\d{8}[a-z]{1,2}\d+))(?:\s+(?P<title>.*))?$")
_ID = re.compile(r"\(ID # ?(\d+)\)")
_DEPARTMENT = re.compile(r"^([A-Z][A-Z&/,'’ -]{2,}?)(?:\.|\s-)?\s+(?=[A-Z][a-z]|\d|\()")  # "PUBLIC WORKS Approve ...", "SHERIFF. Adopt ..."
OF_ANOTHER = ("repealing", "rescinding", "amending", "of", "to", "under", "by", "in", "and", "with", "from")  # the word before a number that is another document's
_STOPPED = re.compile(r"^([A-Z][A-Z&/,'’ -]{2,60}?)\.\s+(?=\S)")
_BESIDE = re.compile(r"\s*\bNO\.\s*\d[\w-]*")
_TAPE = re.compile(r"\s*\((?:Digital\s+Recording\b|\d\d-\d+\w?\s*,)[^)]*\)?\s*$", re.I)  # "(10-22, I, 430)": where on the cassette
# A number the words give the item's own document: "Adopt Ordinance 3031 repealing Ordinance No. 2942" is 3031.
_NUMBER = (re.compile(r"\b(Resolution|Ordinance)\s+(?:No\.?\s*)?(\d[\w-]*\d)", re.I), re.compile(r"\b(\d{8}(?:r|o|mo|ag)\d+)\b", re.I),
           re.compile(r"\b(RESOLUTION|ORDINANCE)\b[^\n]*\n\s*NO\.\s*(\d[\w-]*)"))
# The portal's block under an item, a line to each fact.
_RESULT = re.compile(r"^RESULT\s*:\s*(.*)$")
_MOVER = re.compile(r"^(MOVER|SECONDER)\s*:\s*(.*)$")
_VOTED = re.compile(r"^(AYES?|YEAS?|NAYS?|NOES?|ABSTAIN(?:ED)?|ABSENT|AWAY|RECUSED?|EXCUSED|NOT PRESENT|NOT VOTING)\s*:\s*(.*)$")
_BRACKET = re.compile(r"^(.*?)\s*\[([^\]]*)\]\s*$")
# The line under a motion in the older minutes, and the lines that may follow it.
_MOVED = re.compile(r"^(?:Moved|Motion)\s*:\s*(?P<mover>.{0,30}?)\s*Second(?:ed)?\s*:\s*(?P<seconder>.{0,30}?)\s*Approv(?:al|ed)\s*:\s*(?P<how>.*)$", re.I)
_LABEL = re.compile(r"\b(AYES?|NOES?|NAYS?|ABSENT|ABSTAIN(?:ED|ING)?|ABSTENTIONS?|DISSENTING|OPPOSED|RECUSED?|EXCUSED|NOT PRESENT)\s*:\s*", re.I)
# A motion told in a sentence: who moved and who seconded.
_TOLD = (
    re.compile(rf"(?:\b(?:A|On\s+a|[Ww]ith\s+a)\s+)?\b[Mm]otion\b(?P<to>[^.]{{0,200}}?)\s*(?:was\s+)?(?:made\s+)?by\s+{_OFFICE}\s+(?P<mover>{_SURNAME})\b(?P<what>[^.]{{0,400}}?)[,;]?\s*"
               rf"(?:and\s+)?(?:with\s+)?(?:a\s+)?second(?:ed)?\s+by\s+{_OFFICE}\s+(?P<seconder>{_SURNAME})"),
    re.compile(rf"{_OFFICE}\s+(?P<mover>{_SURNAME})\s+(?:moved|motioned|made\s+a\s+motion)\b(?P<what>[^.]{{0,400}}?)[,;]?\s*(?:and\s+)?(?:was\s+)?"
               rf"second(?:ed)?\s+by\s+{_OFFICE}\s+(?P<seconder>{_SURNAME})"),
    re.compile(rf"\b[Uu]nanimous\s+vote\s+of\s+(?P<ayes>{_PEOPLE})"),
)
# What a sentence after it says of the vote: who, and the tables' word for what they did.
_SAID = (
    (AYE, re.compile(rf"(?:[Aa]pprov(?:ed|al)|[Aa]dopted|[Cc]arried|[Pp]assed|vote)\s+(?:unanimously\s+)?(?:by|of)\s+(?P<who>{_PEOPLE})")),
    (AYE, re.compile(rf"(?P<who>{_PEOPLE})\s+(?:unanimously\s+)?(?:approved|voted\s+(?:yes|aye|in\s+favor)|voting\s+(?:affirmatively|yes|aye|in\s+favor))")),
    (AYE, re.compile(rf"(?:(?<=[.;]\s)|^)(?P<who>{_LOOSE})\s+(?:voted\s+(?:yes|aye)|voting\s+(?:yes|aye))")),
    (NO, re.compile(rf"(?P<who>{_PEOPLE})\s+(?:voted\s+(?:no|against)|voting\s+(?:no|against)|dissent(?:ed|ing)|(?:was\s+|were\s+)?opposed)")),
    (NO, re.compile(rf"(?:(?<=[.;]\s)|^)(?P<who>{_LOOSE})\s+(?:voted\s+(?:no|against)|dissent(?:ed|ing))")),
    (NO, re.compile(rf"[Dd]issenting\s+(?:were|was|votes?(?:\s+were)?:?)\s+(?P<who>{_PEOPLE})")),
    ("ABSENT", re.compile(rf"(?P<who>{_PEOPLE})\s+(?:was|were|being)\s+absent")),
    ("ABSTAIN", re.compile(rf"(?P<who>{_PEOPLE})\s+abstain(?:ed|ing)")),
    ("RECUSED", re.compile(rf"(?P<who>{_PEOPLE})\s+(?:was\s+|were\s+)?recus(?:ed|ing)")),
)
_COUNTED = (re.compile(r"(?<![\d-])(\d)\s*-\s*(\d)(?:\s*-\s*(\d))?(?![\d-])\s*,?\s+(?:approved|approval|vote|failed)"),
            re.compile(r"\b(?:vote\s+(?:was|of)|voted)\s+(\d)\s*-\s*(\d)(?:\s*-\s*(\d))?(?![\d-])"))
_UNANIMOUS = re.compile(r"\bunanimous(?:ly)?\b", re.I)
# A supervisor coming or going, where the minutes say so in a sentence of its own.
_MOVE = re.compile(rf"(?P<who>{_PEOPLE})\s+(?:then\s+)?(?P<did>left|departed|exited|stepped\s+(?:out|away|down)|was\s+excused"
                   rf"|recused\s+\w+\s+from\s+the\s+(?:[Bb]oard\s+)?(?:chambers?|room|dais|meeting)|arrived|returned|rejoined|re-entered"
                   rf"|joined\s+the\s+meeting)\b(?P<rest>[^.]*)")
_BACK = re.compile(r"\band\s+(?:returned|came\s+back|rejoined|re-entered)\b")
# A report of a closed session held at an earlier meeting, and the words that end it. A vote told there was not taken today.
_MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}"
_EARLIER = re.compile(rf"\breport(?:ed|ing)?\s+out\b.{{0,60}}\b{_MONTH}|\bclosed\s+sessions?\s+(?:was\s+|were\s+)?held\s+(?:on\s+{_MONTH}|last\s+week)"
                      rf"|\b{_MONTH}\s+CLOSED\s+SESSION\b", re.I)
_TODAY = re.compile(r"\bconvened\s+(?:in)?to\s+closed\s+session\b|\bClosed\s+Session\s+Agenda\s+for\b", re.I)
# The head of the older minutes.
_PRESENT = re.compile(r"^PRESENT\s*:\s*(.*)$", re.I)
_HEAD_ENDS = re.compile(r"^(?:Meeting recorded|Digital Record|\d{1,2}:\s?\d{0,2}\s*[AaPp]\.?\s?[Mm]|Chair(?:man|woman)?\s+\w+\s+(?:called|cal led|reconvened|opened)"
                        r"|C\s?O\s?N\s?S\s?E\s?N\s?T|Pledge|Call to Order|THIS MEETING)", re.I)
_SUPERVISORS = re.compile(r",?\s*S\s?u\s?p\s?e\s?r\s?v\s?i\s?s\s?o\s?r\s?s\b", re.I)
_NAME_FORM = re.compile(r"[A-Z][A-Za-z’'.-]*(?: [A-Z][A-Za-z’'.-]*){1,2}$")
_ATTENDEE = re.compile(r"^(?P<name>[A-Z][\w.’'“”\" -]+?)\s+(?P<title>(?:District\s+\d\s+)?Supervisor|Board\s+Member|Vice[- ]?Chair(?:man|woman|person)?"
                       r"|Chair(?:man|woman|person)?)\s+(?P<status>[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)(?:\s+(?P<arrived>\d{1,2}:\d{2}\s*[AP]M))?$")


class NoDocument(Exception):
    """The portal has no minutes document to give: not published yet, or a page sent in its place."""


# ---------------------------------------------------------------------------
# The portal
# ---------------------------------------------------------------------------

_session = None


def fetch_document(url, tries=3):
    """One minutes document, as the bytes of a PDF. Raises iqm2.Refused if the portal turns us away (and nothing more is
    asked of it in this run), NoDocument if it has no document to give.

    The portal sends a visitor to its login page for minutes not yet published, and says so: that is no document, not a
    refusal. Now and then it answers with the page of its own viewer in place of the file; that is no document either,
    and the meeting is asked for again on a later run.
    """
    global _session
    host = urlparse(url).netloc
    for attempt in range(tries):
        if host in iqm2.REFUSED:
            raise iqm2.Refused(iqm2.REFUSED[host])
        try:
            if _session is None:
                _session = requests.Session()
                _session.headers.update(county.HEADERS)
            answer = _session.get(url, timeout=150)
            login = "Login.aspx" in urlparse(answer.url).path
            said = clean(" ".join(parse_qs(urlparse(answer.url).query).get("Message", []))) if login else ""
            if login and "not been published" in said:
                raise NoDocument(said)
            pdf = answer.content[:4] == b"%PDF"
            ours = pdf or "ContentPlaceholder1" in answer.text or "MainLayout" in answer.text  # any page of the portal has these
            if answer.status_code in (401, 403, 429) or login or (
                    not ours and re.search(r"captcha|challenge-platform|cf-chl|attention required|access denied", answer.text[:20000], re.I)):
                iqm2.REFUSED[host] = f"HTTP {answer.status_code} at {answer.url.split('?')[0]}{f' ({said})' if said else ''}"
                raise iqm2.Refused(iqm2.REFUSED[host])
            answer.raise_for_status()
            if not pdf:
                raise NoDocument(f"the portal sent a page in place of the document ({answer.url.split('/')[-1][:40]})")
            return answer.content
        except (iqm2.Refused, NoDocument):
            raise
        except requests.RequestException as e:
            # A host that is not allowed will not be allowed on a second asking.
            if attempt == tries - 1 or isinstance(e, requests.exceptions.ProxyError):
                raise
            time.sleep(PAUSE)


def board_meetings(rows):
    """The calendar's rows as the table of the Board's own meetings. What a reading adds is filled in by build()."""
    listed = iqm2.meetings_table(KEY, rows)
    listed = listed[listed["body"] == BODY].drop(columns=["read_on"])
    for name, empty in FACTS:
        listed[name] = empty
    return listed[MEETING_COLUMNS].sort_values(["date", "meeting_id"]).reset_index(drop=True)


def listed(first=FIRST_YEAR, last=None):
    """Every meeting the portal's calendar lists from `first` on, a year to a request, as build_iqm2_board lists them."""
    last = last or datetime.now(timezone.utc).year + 1  # the calendar has meetings to come
    rows = []
    for year in range(first, last + 1):
        rows.extend(iqm2.listed_year(KEY, year))
    return rows


# ---------------------------------------------------------------------------
# The text of a set of minutes
# ---------------------------------------------------------------------------

def spaced(line):
    """A line's words, with a tab where the page leaves a wide gap between two of them: the head of the portal's minutes
    has the supervisors down the left and the County's officers down the right, and plain text runs the two together."""
    text = line["text"]
    marks = [char for char in line["chars"] if not char["text"].isspace()]
    places = [at for at, letter in enumerate(text) if not letter.isspace()]
    if len(marks) != len(places):
        return text
    out, last = list(text), None
    for at, char in zip(places, marks):
        if last is not None and char["x0"] - last["x1"] > WIDE and at and text[at - 1].isspace():
            out[at - 1] = "\t"
        last = char
    return "".join(out)


def pdf_text(body):
    """The text a PDF carries, a page at a time. Nothing is read off the picture of a page.

    A line is set in by one space for every INDENT points it stands in from the margin: in the portal's minutes an item
    begins at the margin and what was said of it is set in, which is how a numbered item is told from a numbered list.
    """
    import pdfplumber
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    with pdfplumber.open(io.BytesIO(body)) as document:
        pages = [page.extract_text_lines(return_chars=True) for page in document.pages]
    # The margin is the leftmost place lines begin at, leaving out a stray line or two that stands further left.
    begun = Counter(round(line["x0"]) for lines in pages for line in lines if not _FURNITURE.match(clean(line["text"])))
    enough = max(3, 0.02 * sum(begun.values()))
    margin = min((x for x, count in begun.items() if count >= enough), default=min(begun, default=0))
    return ["\n".join(" " * max(0, round((line["x0"] - margin) / INDENT)) + spaced(line) for line in lines) for lines in pages]


def text_of(meeting, out_dir, fresh=False):
    """The text of a meeting's minutes, pages parted by form feeds, and whether it was fetched: from the copy kept here,
    or fetched and kept."""
    kept = Path(out_dir) / "text" / f"{meeting['meeting_id']}.txt"
    if kept.exists() and not fresh:
        return kept.read_text(encoding="utf-8"), False
    text = "\n\f".join(pdf_text(fetch_document(meeting["minutes_url"])))
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(text, encoding="utf-8")
    return text, True


def lines_of(text):
    """The minutes' lines in order, each with how far it is set in and its parts where the page sets them wide apart.
    The stamp, the running head and the number of a page are left out."""
    out = []
    for page in text.split("\f"):
        for row in page.split("\n"):
            words = clean(row)
            if words and not _FURNITURE.match(words):
                out.append({"indent": len(row) - len(row.lstrip(" ")), "text": words,
                            "cells": [clean(cell) for cell in row.split("\t") if clean(cell)]})
    return out


# ---------------------------------------------------------------------------
# Who a name is
# ---------------------------------------------------------------------------

def key_of(name):
    """What two printings of a name share: its letters. A scan's "Meri ta Callaway" is "Merita Callaway"."""
    return re.sub(r"[^a-z]", "", str(name or "").lower())


def tidy(name):
    """A name as the head of the minutes prints it, made one way: 'JOHN “JACK” GARAMENDI' is John Garamendi."""
    name = clean(re.sub(r"[\"“”][^\"“”]*[\"“”]", " ", str(name or ""))).strip(" ,;:")
    return name.title() if name.isupper() else name


def family(name):
    """The letters of a name's last word, which is what a vote's line gives of a supervisor."""
    words = [word for word in clean(name).split() if key_of(word) not in ("jr", "sr", "ii", "iii", "iv")]
    return key_of(words[-1]) if words else ""


def near(one, other):
    """Whether two words are one letter apart: a scan's misreading, or a clerk's slip."""
    if one == other or abs(len(one) - len(other)) > 1:
        return one == other
    if len(one) == len(other):
        return sum(a != b for a, b in zip(one, other)) == 1
    short, long = sorted((one, other), key=len)
    return any(long[:at] + long[at + 1:] == short for at in range(len(long)))


def who(printed, roll):
    """The supervisor on the roll that a printed name is, or None: by the whole name, by the family name alone, by an
    initial and the family name, or (for a name of five letters or more) by one letter's difference. Only where one fits."""
    printed = re.sub(rf"^{_OFFICE}\s+", "", clean(printed))
    key = key_of(printed)
    if not key:
        return None
    for fits in (lambda name: key_of(name) == key,
                 lambda name: family(name) == key,
                 lambda name: len(key) > len(family(name)) and key.endswith(family(name)) and key[0] == key_of(name)[0],
                 lambda name: len(key) >= 5 and (near(key, family(name)) or near(key, key_of(name)))):
        found = [name for name in roll if fits(name)]
        if found:
            return found[0] if len(found) == 1 else None
    return None


def one_name(forms):
    """{a name as some head prints it: the one name its person has here}, from how often each form is printed.

    Two forms are one person if their letters are the same, if they share a family name and a first initial ("Russ
    Thomas", "Russell Thomas"; "Michael Oliveira", "Michael C. Oliveira"), or if their letters are two apart or less.
    A family name alone is the one person who has it. The form printed most often is the name.
    """
    people = []
    for form, _ in sorted(forms.items(), key=lambda form: (-form[1], -len(form[0]), form[0])):
        key, alone = key_of(form), len(clean(form).split()) == 1
        if not key:
            continue
        for person in people:
            name = person[0]
            if key == key_of(name) or (alone and key == family(name)) or (
                    not alone and family(form) == family(name) and key[0] == key_of(name)[0]) or (
                    len(key) >= 8 and abs(len(key) - len(key_of(name))) <= 2 and apart(key, key_of(name)) <= 2):
                person.append(form)
                break
        else:
            people.append([form])
    return {form: person[0] for person in people for form in person}


def apart(one, other):
    """How many letters two words are apart (changed, added or dropped)."""
    row = list(range(len(other) + 1))
    for at, a in enumerate(one, 1):
        last, row[0] = row[0], at
        for to, b in enumerate(other, 1):
            last, row[to] = row[to], min(row[to] + 1, row[to - 1] + 1, last + (a != b))
    return row[-1]


def listed_names(words):
    """The names in "Edson, Wright, Ponte and Spellman" or "Supervisor Mills and Clapp", without the office before each."""
    parts = [re.sub(rf"^{_OFFICE}\s+", "", clean(part)) for part in re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+", clean(words))]
    return [part.strip(" .;:") for part in parts if key_of(part) and key_of(part) != "none"]


# ---------------------------------------------------------------------------
# The head of the minutes: who sits on the Board, and who was there
# ---------------------------------------------------------------------------

def said_names(words, known=()):
    """The supervisors in "Lucy Thein, Chair; Terri Bailey, Vice-Chair; Paul Stein, Merita Callaway and Thomas Tryon",
    each with the office and the district the words give them, and whether every part of the words was understood.

    `known` is the letters of names other heads print, by which a scan's broken name ("Meri ta Callaway") and two names
    run together ("Steve Wilensky Thomas Tryon") are still told.
    """
    out, whole = [], True
    for part in re.split(r"\s*[;,:]\s*|\s+and\s+", clean(words)):
        part = tidy(part)
        office = re.search(rf"\s+({_OFFICE})$", part, re.I)  # "Thomas Tryon Vice-Chair", the comma left out
        if office and key_of(office[1]) in ROLES and key_of(part[:office.start()]) and not re.fullmatch(_OFFICE, part, re.I):
            out.append({"name": part[:office.start()], "role": ROLES[key_of(office[1])], "district": None})
            continue
        key = key_of(part)
        district = re.search(r"District\s+([IV]+|\d)\b", part, re.I)
        if not key or key == "none":
            continue
        if key in ROLES or district or re.match(r"Supervisors?\b", part, re.I):
            if out and key in ROLES:
                out[-1]["role"] = ROLES[key]
            if out and district:
                out[-1]["district"] = int(district[1]) if district[1].isdigit() else ROMAN.get(district[1].lower())
            continue
        both = next(((part[:at], part[at + 1:]) for at, letter in enumerate(part)
                     if letter == " " and key_of(part[:at]) in known and key_of(part[at:]) in known), None)
        if key in known or _NAME_FORM.match(part):
            out.append({"name": part, "role": "", "district": None})
        elif both:
            out.extend({"name": name, "role": "", "district": None} for name in both)
        else:
            whole = False
    return out, whole


def typed_head(lines, known=()):
    """The head of the older minutes, "PRESENT: ...; ..., Supervisors; ..." and "ABSENT: ...", or None if there is none."""
    at = next((at for at, line in enumerate(lines[:40]) if _PRESENT.match(line["text"])), None)
    if at is None:
        return None
    said = [_PRESENT.match(lines[at]["text"])[1]]
    for line in lines[at + 1:at + 10]:
        if _HEAD_ENDS.match(line["text"]):
            break
        said.append(line["text"])
    said = clean(" ".join(said))
    there, _, away = re.split(r"\b(ABSENT)\s*:", said, maxsplit=1) if re.search(r"\bABSENT\s*:", said) else (said, "", "")
    cut = _SUPERVISORS.search(there)  # the County's officers follow the supervisors, and are not wanted
    present, whole = said_names(there[:cut.start()], known) if cut else ([], False)
    absent, clear = said_names(away, known)
    roll = [{**member, "status": "Present", "arrived": ""} for member in present]
    roll += [{**member, "status": "Absent", "arrived": ""} for member in absent]
    return {"roll": roll, "letterhead": [], "from": "present line", "known": whole and clear and len(present) >= QUORUM}


def portal_head(lines):
    """The head of the portal's minutes: the supervisors and their districts down the left of the letterhead, then the
    table of who attended.

    The letterhead is the Board of the day the document was made, which for the last meetings of a year is the next
    year's Board. So it is kept for the districts it gives and as names a vote may mean, and is not the meeting's roll.
    Minutes of 2014 and 2015 have no table, and so no roll: a vote in them is read only where it names everyone."""
    board, pending = [], None
    for line in lines[1:14]:
        first = line["cells"][0] if line["cells"] else ""
        district = re.match(r"DIS\w*T\s+(\d)\b", first)
        if district and pending:
            board.append({**pending, "district": int(district[1])})
            pending = None
        elif first.isupper() and "MINUTES" not in first and not district:
            name, _, role = re.split(r"\s+([–—-])\s+", first, maxsplit=1) if re.search(r"\s[–—-]\s", first) else (first, "", "")
            pending = {"name": tidy(name), "role": ROLES.get(key_of(role), "")}
    at = next((at for at, line in enumerate(lines[:40]) if key_of(line["text"]) == "attendeenametitlestatusarrived"), None)
    rows = []
    for line in lines[at + 1:at + 8] if at is not None else []:
        row = _ATTENDEE.match(line["text"])
        if not row:
            break
        printed = [member for member in board if who(row["name"], [member["name"]])]
        district = re.search(r"District\s+(\d)", row["title"])
        rows.append({"name": tidy(row["name"]), "role": ROLES.get(key_of(row["title"]), ""),
                     "district": int(district[1]) if district else printed[0]["district"] if len(printed) == 1 else None,
                     "status": row["status"], "arrived": clean(row["arrived"])})
    return {"roll": rows, "letterhead": board, "from": "attendee table" if rows else "", "known": len(rows) >= QUORUM}


def head_of(text, known=()):
    """How a set of minutes is set out, and what its head says of the Board: {"format", "roll", "letterhead", "from", "known"}.

    `roll` has each supervisor the head names with the office, district and status it gives them; `known` is whether the
    head says who was present, which a vote that names no ayes is read by.
    """
    lines = lines_of(text)
    marks = "\n".join(line["text"] for line in lines)
    portal = bool(re.search(r"^RESULT\s*:", marks, re.M)) or "Attendee Name" in marks or (
        bool(lines) and key_of(lines[0]["text"]).startswith("calaverascountyboardofsupervisors") and "DISTRICT 1" in marks[:600])
    if portal:
        return {"format": PORTAL, **portal_head(lines)}
    head = typed_head(lines, known) or {"roll": [], "letterhead": [], "from": "", "known": False}
    moved = any(_MOVED.match(line["text"]) for line in lines)
    told = any(pattern.search(marks.replace("\n", " ")) for pattern in _TOLD[:2])
    return {"format": MOVED if moved else PROSE if told or head["roll"] else "", **head}


# ---------------------------------------------------------------------------
# What the minutes say of a vote
# ---------------------------------------------------------------------------

def a_motion(how, **said):
    """A motion as it is carried from the page to the tables. `cast` has each name the minutes give with a vote, as
    printed, and the tables' word for it; `tally` is a count the minutes print, (ayes, noes); `away` is who the minutes
    then had out of the room."""
    return {"how": how, "mover": "", "seconder": "", "cast": [], "unanimous": False, "majority": False, "tally": None,
            "text": "", "outcome": "", "result": "", "away": [], **said}


def word_of(label):
    return WORDS.get(key_of(label), clean(label).upper())


def block_of(lines, at, roll):
    """The portal's block that begins at line `at`, "RESULT: ..." and the lines under it, as (motion, the line after it).

    A list of names too long for its line runs on to the next; a line is taken for that only if every word of it is a
    word of some supervisor's name. A block with a result and no vote ("RESULT: WITHDRAWN") is a motion with no one in it.
    """
    outcome = clean(_RESULT.match(lines[at]["text"])[1])
    bracket = _BRACKET.match(outcome)
    counted = re.fullmatch(r"(\d+) TO (\d+)", bracket[2].strip(), re.I) if bracket else None
    motion = a_motion("block", outcome=outcome, text=outcome,
                      unanimous=bool(bracket and bracket[2].strip().upper() == "UNANIMOUS"),
                      tally=(int(counted[1]), int(counted[2])) if counted else None)
    word = bracket[1] if bracket else outcome
    motion["result"] = "Fail" if LOST.search(word) else "Pass" if CARRIED.match(word) else ""
    parts = {key_of(part) for name in roll for part in name.split()}
    at, last = at + 1, None
    while at < len(lines):
        text = lines[at]["text"]
        mover, voted = _MOVER.match(text), _VOTED.match(text)
        if mover:
            motion[mover[1].lower()] = clean(mover[2].split(",")[0])
            last = None
        elif voted:
            last = [word_of(voted[1]), voted[2]]
            motion.setdefault("lists", []).append(last)
        elif re.match(r"Next\s*:", text, re.I):
            pass  # the day a tabled item comes back
        elif last is not None and not _RESULT.match(text) and all(key_of(part) in parts for part in re.split(r"[\s,]+", text) if key_of(part)):
            last[1] += " " + text
        else:
            break
        at += 1
    for word, names in motion.pop("lists", []):
        motion["cast"].extend((name, word) for name in iqm2.names_of(names) if key_of(name) != "none")
    return motion, at


def line_of(found, more=()):
    """The line under a motion in the older minutes, "Moved: Stein Second: Callaway Approval: Majority NOES: Tryon", with
    the lines that follow it ("ABSENT: Stein"), as a motion."""
    said = clean(" ".join([found["how"], *more]))
    labels = list(_LABEL.finditer(said))
    how = clean(said[:labels[0].start()] if labels else said)
    motion = a_motion("line", mover=clean(found["mover"]), seconder=clean(found["seconder"]), outcome=clean("Approval: " + said),
                      unanimous=key_of(how).startswith("unanim"), majority=key_of(how).startswith("majority"))
    counted = re.match(r"(\d)\s*-\s*(\d)", how)
    motion["tally"] = (int(counted[1]), int(counted[2])) if counted else None
    motion["result"] = "Fail" if LOST.search(how) or re.search(r"\bdenied\b", how, re.I) else "Pass" if motion["unanimous"] or motion["majority"] else ""
    for at, label in enumerate(labels):
        names = said[label.end():labels[at + 1].start() if at + 1 < len(labels) else len(said)]
        motion["cast"].extend((name, word_of(label[1])) for name in listed_names(names))
    if not re.fullmatch(r"(?:unanimous(?:ly)?|majority|\d\s*-\s*\d(?:\s*-\s*\d)?|failed|denied)?\.?", how, re.I):
        # "Unanimous (Callaway absent)", or anything else the line says in its own way: not to be read past.
        motion["at_odds"] = f"the line says more than the reader knows: {how[:60]}"
    return motion


def told_of(rest):
    """The sentences after "Motion by ..., second by ..." that tell of that motion: the first two, and those after them
    for as long as each says something of the vote."""
    sentences = re.split(r"(?<=[.;])\s+(?=[A-Z])", rest)
    kept = sentences[:2]
    for sentence in sentences[2:]:
        if not (any(pattern.search(sentence) for _, pattern in _SAID) or any(pattern.search(sentence) for pattern in _COUNTED)):
            break
        kept.append(sentence)
    return " ".join(kept)


def spoken(words, roll):
    """The motions a passage tells in sentences, in order, each with where in the passage it begins.

    A sentence may say who voted how ("Approved by Supervisors Edson, Wright, Ponte and Spellman. Supervisor Callaway
    voted no."), give a count ("4-1 approved"), or say only that the Board was unanimous. A clause whose names are not
    all supervisors is not taken for a vote; decide() then finds the motion short of someone and does not read it.
    """
    found = sorted((match for pattern in _TOLD for match in pattern.finditer(words)), key=lambda match: match.start())
    found = [match for at, match in enumerate(found) if not any(other.start() <= match.start() < other.end() for other in found[:at])]
    out = []
    for at, match in enumerate(found):
        end = found[at + 1].start() if at + 1 < len(found) else len(words)
        said = told_of(words[match.end():min(end, match.end() + 700)])
        parts = match.groupdict()
        told = clean((parts.get("what") or "") + " " + said)
        motion = a_motion("words", mover=parts.get("mover") or "", seconder=parts.get("seconder") or "",
                          text=clean(words[match.start():match.end()] + said), start=match.start())
        if parts.get("ayes"):
            motion["cast"].extend((name, AYE) for name in listed_names(parts["ayes"]))
            motion["unanimous"] = True
        for word, pattern in _SAID:
            for clause in pattern.finditer(told):
                names = listed_names(clause["who"])
                if names and all(who(name, roll) for name in names):
                    motion["cast"].extend((name, word) for name in names if (name, word) not in motion["cast"])
        counted = next((found for pattern in _COUNTED for found in [pattern.search(told)] if found), None)
        motion["tally"] = (int(counted[1]), int(counted[2])) if counted else None
        motion["unanimous"] = motion["unanimous"] or bool(_UNANIMOUS.search(told))
        motion["majority"] = bool(re.search(r"\bMajority\b", told))
        motion["result"] = ("Fail" if LOST.search(told) else
                            "Pass" if re.search(r"\bapprov(?:ed|al)\b|\bunanimous vote\b", told + " " + match[0], re.I) else "")
        out.append(motion)
    return out


def moves_in(lines, roll):
    """For each line, the comings and goings that begin on it: [(supervisors, whether they came)]. A sentence that has
    someone leave and return ("left the meeting at 1:36 PM and returned at 1:40 PM") changes nothing and is left out."""
    out = []
    for at, line in enumerate(lines):
        words = line["text"] + " " + (lines[at + 1]["text"] if at + 1 < len(lines) else "")
        here = []
        for move in _MOVE.finditer(words):
            if move.start() >= len(line["text"]) or "closed session" in move["rest"].lower():
                continue
            came = not re.match(r"left|departed|exited|stepped|was|recused", move["did"])
            if not came and _BACK.search(move["rest"]):
                continue
            members = [member for member in (who(name, roll) for name in listed_names(move["who"])) if member]
            if members:
                here.append((members, came))
        out.append(here)
    return out


def section_of(text):
    """The part of the meeting a line opens ("9:55 AM: Consent Agenda", "C O N S E N T A G E N D A"), or ""."""
    rest = re.sub(rf"^{_HOUR}", "", text, flags=re.I)
    # A heading is short or in capitals; a sentence that happens to open with the same words is neither.
    if rest.endswith(".") or _NUMBERED.match(rest) or len(key_of(rest)) > 60 or (len(rest.split()) > 7 and rest != rest.upper()):
        return ""
    key = key_of(rest)
    return next((name for begins, name in SECTIONS.items() if key.startswith(begins)), "")


def decide(motion, roll, wider=None, known=True, board=None):
    """Every vote on a motion as ([(supervisor, word, established)], ""), or (None, why it cannot be told).

    `roll` is the supervisors the head of the minutes names; `wider` is those and anyone else on the Board about then,
    whom a name may also be; `known` is whether the head says who was present; `board` is the whole Board where it is
    known, by which a vote told in a sentence is checked for anyone left out. Nothing is filled in on a likelihood: each
    test here is one way the minutes' own words could leave a supervisor's vote open.
    """
    wider = wider or roll
    board = roll if board is None else board
    cast, seen = [], {}
    for printed, word in motion["cast"]:
        member = who(printed, wider)
        if member is None:
            return None, f"not on the roll: {printed}"
        if member in seen and seen[member] != word:
            return None, f"named twice: {member}"
        if member not in seen:
            seen[member] = word
            cast.append((member, word, NAMED))
    for role in ("mover", "seconder"):
        member = who(motion[role], wider) if motion[role] else None
        if member and seen.get(member) in OUT_OF_ROOM:
            return None, f"the {role} is named {seen[member].lower()}: {member}"
    ayes, noes = (sum(word == which for word in seen.values()) for which in (AYE, NO))
    away = {who(name, wider) for name in motion["away"]}
    rest = [member for member in board if member not in seen and member not in away]
    tally = motion["tally"]
    if ayes:
        if motion["unanimous"] and noes:
            return None, "unanimous, with a supervisor opposed"
        if tally and tally != (ayes, noes):
            return None, f"the minutes count {tally[0]} to {tally[1]} and name {ayes} and {noes}"
        if motion["how"] == "words" and not tally:
            # A sentence is read clause by clause, and a clause can be missed. So everyone must be accounted for.
            if not board and len(seen) < SEATS:
                return None, "the minutes have no roll to check the names against"
            if rest:
                return None, "the vote does not say how " + ", ".join(rest) + " voted"
        return cast, ""
    if motion.get("at_odds"):
        return None, motion["at_odds"]
    if tally:
        if noes != tally[1]:
            return None, f"the count has {tally[1]} against and {noes} are named"
        if len(rest) != tally[0]:
            return None, f"the count has {tally[0]} ayes and the minutes have {len(rest)} supervisors not named"
        return cast + [(member, AYE, COUNT) for member in rest], ""
    if motion["unanimous"] or motion["majority"]:
        way = UNANIMOUS if motion["unanimous"] else MAJORITY
        there = [member for member in roll if member not in seen and member not in away]
        if motion["unanimous"] and noes:
            return None, "unanimous, with a supervisor opposed"
        if not motion["unanimous"] and not cast:
            return None, "majority, and nobody is named"
        if not known:
            return None, f"{way}, and the head of the minutes does not say who was present"
        if len(there) < QUORUM or len(there) <= noes:
            return None, f"{way}, and the minutes have {len(there)} supervisors present who are not named"
        return cast + [(member, AYE, way) for member in there], ""
    if cast:
        return None, "the minutes name no ayes and give no count"
    return None, "the vote is told in words the reader does not read"


# ---------------------------------------------------------------------------
# Reading a set of minutes
# ---------------------------------------------------------------------------

def titled(words, kind=PORTAL):
    """An item's words as (kind of file, department, the portal's id, a number, the title).

    The portal's minutes open an item with its department in capitals ("PUBLIC WORKS Approve ..."), and from 2019 with
    the kind of file and the item's id. The minutes of 2013 and 2014 end the department with a stop ("SHERIFF. Adopt
    ..."). The older ones head an item with its subjects and the place on the tape, which is left off."""
    portal = kind == PORTAL
    filed = _FILED.match(words) if portal else None
    if filed:
        return clean(filed["type"]), clean(filed["department"]), filed["id"] or "", filed["number"] or "", clean(filed["title"]) or words
    found = _ID.search(words) if portal else None
    title = clean(_ID.sub(" ", words)) if portal else clean(_TAPE.sub("", words))
    if kind == MOVED:  # a resolution's number stands in the margin beside its title, and plain text runs it into the title
        return "", "", "", "", clean(_BESIDE.sub(" ", title, count=1)) if re.match(r"(?:RESOLUTION|ORDINANCE)\b", title) else title
    department = (_DEPARTMENT if portal else _STOPPED).match(title)
    if department and len(department[1]) < 70 and clean(title[department.end():]):
        return "", clean(department[1]).rstrip("."), found[1] if found else "", "", clean(title[department.end():])
    return "", "", found[1] if found else "", "", title


def number_in(words):
    """(what kind of document, its number) where an item's words give one: "Resolution 2014-094", "NO. 10-089", "20260526r024"."""
    for pattern in _NUMBER:
        for found in pattern.finditer(words):
            before = re.search(r"(\w+)\W*$", words[:found.start()])
            if before and before[1].lower() in OF_ANOTHER:
                continue
            if len(found.groups()) == 2:
                return found[1].lower(), clean(found[2])
            kinds = {"r": "resolution", "o": "ordinance"}
            return kinds.get(re.search(r"[a-z]+", found[1].lower())[0], ""), found[1]
    return "", ""


def scan(text, known=(), about=()):
    """A set of minutes as its head and its lines: {"format", "roll", "from", "known", "lines"}.

    A line is an item, or a part of the meeting that was voted on as one (`heading`: the consent calendar). Each has
    its motions, in order, with the names in each as the minutes print them and who the minutes then had out of the
    room. `known` and `about` come from the other minutes read: the letters of names their heads print, and the
    supervisors other heads name within a year of this day, whom a name not in this head may be.
    """
    head = head_of(text, known)
    lines = lines_of(text)
    roll = [member["name"] for member in head["roll"]]
    wider = widened(roll, about)
    moves = moves_in(lines, wider)
    # Who is out of the room when the minutes begin: those the head has absent or late, and anyone the minutes later
    # have arriving without having said they left.
    away, out = {member["name"] for member in head["roll"] if member["status"] in ("Absent", "Late", "Excused")}, set()
    for here in moves:
        for members, came in here:
            for member in members:
                if came and member not in away | out:
                    away.add(member)
                out = out - {member} if came else out | {member}
    state = {"away": set(away), "gone": set(), "section": "", "consent": False, "pulled": False, "earlier": False, "target": None, "heading": None,
             "last": 0, "fresh": True}
    found = []
    portal = head["format"] == PORTAL

    def opened(number, words, heading=False):
        kind, department, matter, filed, title = ("", "", "", "", words) if heading else titled(words, head["format"])
        line = {"heading": heading, "number": number, "title": title, "section": state["section"], "under": state["heading"],
                "consent": state["consent"], "file_type": kind, "department": department, "matter_id": matter, "filed": filed,
                "motions": [], "prose": [], "titled": False, "blocked": False, "indent": 0, "outcome": ""}
        found.append(line)
        return line

    def here(motion, gone=None):
        """Whoever moves, seconds or votes on a motion is in the room from then on, whatever the head said of them:
        a supervisor the head has late or absent has come.

        Not so someone the minutes have said left the meeting and have not said returned. In the portal's block the
        clerk's entry of their vote stands. Elsewhere the minutes are at odds with themselves, and decide() does not
        read a motion that way unless it names its ayes."""
        gone = state["gone"] if gone is None else gone
        acted = [motion["mover"], motion["seconder"]] + [name for name, word in motion["cast"] if word not in OUT_OF_ROOM + ("RECUSED",)]
        members = {member for member in (who(name, wider) for name in acted if name) if member}
        if motion["how"] == "block":
            state["gone"] -= members
            return members
        if members & gone:
            motion["at_odds"] = "the minutes have " + ", ".join(sorted(members & gone)) + " gone from the meeting, and moving or voting here"
        return members - gone

    def item(number, words, indent):
        """An item begins: the one before it is done."""
        heading = state["heading"]
        closed(state["target"])
        line = state["target"] = opened(number, words)
        line["under"], line["indent"] = heading, indent
        line["prose"].append((words, set(state["away"]), set(state["gone"])))
        return line

    def closed(line):
        """An item is done: the motions its sentences tell are found, unless a line or a block has told them already."""
        if line is None:
            return
        words = " ".join(part for part, *_ in line["prose"])
        told = spoken(words, wider)
        if not portal and any(motion["how"] == "line" for motion in line["motions"]):
            told = []
        blocks = [(who(motion["mover"], wider), who(motion["seconder"], wider)) for motion in line["motions"] if motion["how"] == "block"]
        came = set()
        for motion in told:
            if (who(motion["mover"], wider), who(motion["seconder"], wider)) in blocks:
                continue  # the sentence tells of the motion the block under it records
            reached, start = 0, motion.pop("start")
            for part, then, gone in line["prose"]:
                reached += len(part) + 1
                motion["away"] = sorted(then - came)
                if reached > start:
                    break
            came |= here(motion, gone)
            motion["away"] = sorted(set(motion["away"]) - came)
            state["away"] -= came
            line["motions"].append(motion)
            if not line["heading"] and not line["titled"] and not portal:
                line["title"], line["titled"] = titled(clean(words[:start])[:700], head["format"])[4] or line["title"], True
        if not line["motions"] and not line["heading"] and not portal and len(line["prose"]) > 1:
            first = line["prose"][0][0]
            # An item of the consent calendar is its words, however many lines they take. Elsewhere a line in capitals
            # is a heading, and what follows is what was said.
            if line["consent"] or not re.fullmatch(r"[^a-z]*(?:\([^)]*\)?)?", first):
                line["title"] = titled(clean(words)[:700], head["format"])[4]

    at = 0
    while at < len(lines):
        text, indent = lines[at]["text"], lines[at]["indent"]
        for members, came in moves[at]:
            state["away"] = state["away"] - set(members) if came else state["away"] | set(members)
            state["gone"] = state["gone"] - set(members) if came else state["gone"] | set(members)
        if _CLOSES.match(text):
            break
        line = state["target"]
        if _RESULT.match(text):
            motion, at = block_of(lines, at, wider)
            if line is None:
                line = state["target"] = state["heading"] = opened("", state["section"] or "Motion", heading=True)
            if motion["cast"] or motion["mover"]:
                state["away"] -= here(motion)
                motion["away"] = sorted(state["away"])
                line["motions"].append(motion)
            line["outcome"], line["blocked"] = motion["outcome"], True
            continue
        moved = _MOVED.match(text)
        if moved:
            more = []
            while at + 1 < len(lines) and _LABEL.match(lines[at + 1]["text"]):
                at += 1
                more.append(lines[at]["text"])
            motion = line_of(moved, more)
            if line is None:
                line = state["target"] = state["heading"] = opened("", state["section"] or "Motion", heading=True)
            said = [part for part, *_ in line["prose"][line.get("cut", 0):]]
            # The motion's words stand above its line where the minutes give them ("Motion made to approve ..."); from
            # 2012 they give none, and the line is all there is.
            said = " ".join(said)
            begins = max((found.start() for found in re.finditer(r"(?:^|(?<=[.;:]\s))(?:A\s+)?Motion\b", said)), default=len(said))
            motion["text"] = clean(said[begins:] + " " + text + " " + " ".join(more))
            state["away"] -= here(motion)
            motion["away"] = sorted(state["away"])
            line["motions"].append(motion)
            line["cut"] = len(line["prose"])
            line["outcome"] = motion["outcome"]
            at += 1
            continue
        # In the portal's minutes a part of the meeting is named at the margin or in the middle of the page; "Public
        # Comment:" set in under an item is what was said of that item.
        part = "" if portal and (2 <= indent <= 11 or text.endswith(":")) else section_of(text)
        if part:
            closed(line)
            state.update(section=part, consent=part == "Consent Agenda", pulled=part.startswith("Items Pulled"), earlier=False, fresh=True)
            state["target"] = state["heading"] = opened("", part, heading=True)
            at += 1
            continue
        if _EARLIER.search(text + " " + (lines[at + 1]["text"] if at + 1 < len(lines) else "")):
            state["earlier"] = True
        elif _TODAY.search(text):
            state["earlier"] = False
        numbered, filed = _NUMBERED.match(text), _FILED.match(text)
        number = int(re.match(r"\d+", numbered[1])[0]) if numbered else 0
        if portal:
            opens = indent <= 1 and bool(numbered) and (number > state["last"] or state["fresh"] or bool(_ID.search(text)))
            # An item pulled from the consent calendar is taken up later under no number: it begins where the block
            # under the one before it ends.
            loose = not numbered and line is not None and (line["heading"] or line["blocked"]) and (state["pulled"] or bool(filed))
        else:
            opens = bool(numbered) and (state["consent"] or number == state["last"] + 1 or bool(re.match(r"[A-Z][A-Z&/]{2,}", numbered[2])))
            loose = False
        if opens or loose:
            item(numbered[1] if opens else "", numbered[2] if opens else text, indent)
            state.update(last=number or state["last"], fresh=False)
            at += 1
            continue
        if line is not None and not state["earlier"]:
            # An item's words run on to the lines under it, and end with their sentence.
            if portal and not line["heading"] and not line["titled"] and not line["motions"] and len(line["prose"]) < 9 \
                    and not line["prose"][-1][0].rstrip().endswith("."):
                kind, department, matter, filed_as, title = titled(clean(" ".join(part for part, *_ in line["prose"]) + " " + text), PORTAL)
                line.update(title=title, file_type=kind or line["file_type"], department=department or line["department"],
                            matter_id=matter or line["matter_id"], filed=filed_as or line["filed"])
            elif portal:
                line["titled"] = True
            line["prose"].append((text, set(state["away"]), set(state["gone"])))
        at += 1
    closed(state["target"])
    kept = [line for line in found if not line["heading"] or line["motions"]]
    return {**head, "lines": kept}


def widened(roll, about):
    """A meeting's roll with the others a name in its minutes may be, each person once: "Michael C. Oliveira" is not
    added beside a roll that has "Michael Oliveira", or a bare "Oliveira" would fit both and be read as no one."""
    same = lambda name, member: key_of(name) == key_of(member) or (
        family(name) == family(member) and key_of(name)[:1] == key_of(member)[:1])
    return roll + [name for name in about if not any(same(name, member) for member in roll)]


def slug(number):
    return re.sub(r"[^A-Za-z0-9]+", "", number)


def read_meeting(meeting, scanned, pages=0, about=(), around=(), name_of=None):
    """One meeting's minutes as the rows of the tables: its lines, the votes on each motion that could be read whole,
    and what the reading found.

    `about` is whom a name may be beside the meeting's own roll; `around` is the Board about that day, which stands for
    the roll where the minutes have none and it has a name for every seat; `name_of` gives a supervisor the one name
    they have in every meeting."""
    name_of = name_of or (lambda name: name)
    meeting_id, date = str(meeting["meeting_id"]), meeting["date"]
    roll = [member["name"] for member in scanned["roll"]]
    wider = widened(roll, about)
    board = roll if roll else list(around) if len(around) == SEATS else []
    packed = lambda members: json.dumps([{**member, "name": name_of(member["name"])} for member in members], ensure_ascii=False, separators=(",", ":"))
    facts = {"minutes": "read", "format": scanned["format"], "pages": pages, "roll_from": scanned["from"], "motions": 0, "motions_read": 0,
             "roll": packed(scanned["roll"]), "letterhead": packed(scanned["letterhead"])}
    agenda, votes, used, parts, loose = [], [], set(), 0, 0
    for line in scanned["lines"]:
        if line["heading"]:
            parts += 1
            base = f"{meeting_id}-c{parts}"
        elif slug(line["number"]):
            base = f"{meeting_id}-{slug(line['number'])}"
        else:
            loose += 1
            base = f"{meeting_id}-u{loose}"
        item_id, again = base, 1
        while item_id in used:  # a number the minutes use twice: an item pulled from the consent calendar and taken up after it
            again += 1
            item_id = f"{base}-{again}"
        used.add(item_id)
        line["item_id"] = item_id
    numbered = {}
    for line in scanned["lines"]:
        if line["motions"] and not line["heading"] and line["number"]:
            numbered.setdefault(line["number"], line["item_id"])
    for sequence, line in enumerate(scanned["lines"], 1):
        item_id, heading = line["item_id"], line["heading"]
        matter_id = "" if heading else line["matter_id"] or item_id
        for number, motion in enumerate(line["motions"], 1):
            cast, problem = decide(motion, roll, wider, scanned["known"], board)
            motion.update(read=cast is not None, problem=problem, cast_read=cast or [],
                          moved=name_of(who(motion["mover"], wider) or ""), seconded=name_of(who(motion["seconder"], wider) or ""))
            for member, word, established in motion["cast_read"]:
                votes.append({"item_id": item_id, "meeting_id": meeting_id, "date": date, "matter_id": matter_id, "matter_file": "",
                              "member": name_of(member), "vote": council_tables.vote_word(word), "motion": number,
                              "motion_text": motion["text"], "established": established})
        last = line["motions"][-1] if line["motions"] else None
        cast = [council_tables.vote_word(word) for _, word, _ in last["cast_read"]] if last else []
        ways = {established for motion in line["motions"] for _, _, established in motion["cast_read"]}
        title = clean(line["title"])
        words = "\n".join(part for part, *_ in line["prose"])
        kind, number = number_in(line["filed"] or title + "\n" + words)
        under = line["under"] if line["consent"] and line["under"] and line["under"]["motions"] and line["under"] is not line else None
        voted_with = item_id if line["motions"] else numbered.get(line["number"]) or (under["item_id"] if under else "")
        agenda.append({
            "item_id": item_id, "meeting_id": meeting_id, "date": date, "body": BODY, "agenda_number": line["number"],
            "sequence": sequence, "matter_id": matter_id, "matter_file": "", "title": title,
            "action": last["text"] if last else line["outcome"] or title,
            "result": last["result"] if last else "",  # only what the minutes say of it: never worked out from the names
            "mover": last["moved"] if last else "", "seconder": last["seconded"] if last else "",
            "ayes": cast.count(AYE), "noes": cast.count(NO), "not_voting": sum(word not in (AYE, NO) for word in cast),
            "heading": heading, "section": line["section"], "section_id": under["item_id"] if under else "",
            "motions": len(line["motions"]), "motions_read": sum(motion["read"] for motion in line["motions"]),
            "votes_read": all(motion["read"] for motion in line["motions"]) if line["motions"] else None,
            "problem": next((motion["problem"] for motion in line["motions"] if not motion["read"]), ""),
            "outcome": last["outcome"] if last else line["outcome"],
            "established": "" if not ways else NAMED if ways == {NAMED} else sorted(ways - {NAMED})[0],
            "voted_with": voted_with,
            "doc_type": "" if heading else kind if kind in ("resolution", "ordinance") else
                        line["file_type"].lower() if line["file_type"].lower() in ("resolution", "ordinance") else county.doc_type_of(title),
            "file_type": line["file_type"], "department": line["department"], "number": number,
            "motion_log": json.dumps([{"motion": number, "action": motion["text"], "mover": motion["mover"], "seconder": motion["seconder"],
                                       "outcome": motion["outcome"], "told_by": motion["how"], "read": motion["read"], "problem": motion["problem"]}
                                      for number, motion in enumerate(line["motions"], 1)], ensure_ascii=False, separators=(",", ":")),
        })
        facts["motions"] += len(line["motions"])
        facts["motions_read"] += sum(motion["read"] for motion in line["motions"])
    return agenda, votes, facts


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------

def items_table(agenda, meetings):
    """Every item in the minutes read, once, with what was last done with it: by a vote of its own, or by the vote on
    the consent calendar it stands under.

    An item is known by the portal's id where the minutes print one ("(ID # 9167)"), and may then come to more than one
    meeting. Where they print none, the item is its line in the minutes, and is here once for each meeting it came to.
    """
    of, minutes = agenda.set_index("item_id"), dict(zip(meetings["meeting_id"], meetings["minutes_url"]))
    lines = agenda[~agenda["heading"]].sort_values(["date", "meeting_id", "sequence"])
    times, first = lines.groupby("matter_id").size(), lines.groupby("matter_id")["date"].min()
    rows = []
    for line in lines.groupby("matter_id").tail(1).itertuples(index=False):
        own = line.motions > 0
        over = of.loc[line.voted_with] if not own and line.voted_with in of.index else None
        vote = line._asdict() if own else over.to_dict() if over is not None else None
        rows.append({
            "date": first[line.matter_id], "matter_id": line.matter_id, "matter_file": "", "doc_type": line.doc_type, "title": line.title,
            "body": line.body, "status": "", "year": int(line.date[:4]), "subject": line.department, "agenda_date": line.date,
            "passed_date": "", "last_action": line.action, "last_action_date": line.date,
            "result": vote["result"] if vote else "",
            "ayes": int(vote["ayes"]) if vote else 0, "noes": int(vote["noes"]) if vote else 0,
            "mover": vote["mover"] if vote else "", "seconder": vote["seconder"] if vote else "",
            "times_on_agenda": int(times[line.matter_id]), "url": minutes.get(line.meeting_id, ""),
            "item_id": line.item_id, "meeting_id": line.meeting_id, "section": line.section,
            "action_on": "item" if own or (over is not None and not over["heading"]) else "section" if over is not None else "",
            "votes_read": bool(vote["votes_read"]) if vote else None, "number": line.number,
        })
    out = pd.DataFrame(rows, columns=ITEM_COLUMNS)
    out["votes_read"] = out["votes_read"].astype("boolean")
    return out.sort_values(["date", "meeting_id", "matter_id"], ascending=[False, False, True]).reset_index(drop=True)


def members_table(votes, meetings):
    """Everyone with votes here on SEEN_DAYS days or more. The minutes give no terms of office.

    `district` is the one the head of the portal's minutes gives a supervisor (the older minutes give none), and `role`
    the office the newest minutes read give them. `serving` is true for those whose last vote is within SERVING_DAYS of
    the newest minutes read: minutes are published months after their meeting, so today's date would be no guide.
    """
    districts, offices = {}, {}
    for meeting in meetings[meetings["roll"] != ""].sort_values("date").itertuples(index=False):
        roll = json.loads(meeting.roll)
        for member in roll + json.loads(meeting.letterhead or "[]"):
            if member.get("district"):
                districts[member["name"]] = int(member["district"])
        if roll:
            offices = {member["name"]: member.get("role", "") for member in roll}  # the newest minutes read have the last word
    days = votes.groupby("member")["date"].nunique() if len(votes) else pd.Series(dtype=int)
    cast = votes.groupby("member")["date"].agg(["min", "max", "size"]) if len(votes) else pd.DataFrame()
    last = votes["date"].max() if len(votes) else ""
    since = (day_type.fromisoformat(last) - pd.Timedelta(days=SERVING_DAYS)).isoformat() if last else ""
    rows = [{"name": name, "district": districts.get(name), "role": offices.get(name, "") if cast.loc[name, "max"] >= since else "",
             "start": "", "end": "", "serving": bool(cast.loc[name, "max"] >= since),
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


def typed(agenda, votes):
    for table, columns in ((agenda, ("sequence", "ayes", "noes", "not_voting", "motions", "motions_read")), (votes, ("motion",))):
        for column in columns:
            table[column] = table[column].astype(int)
    agenda["heading"] = agenda["heading"].astype(bool)
    agenda["votes_read"] = agenda["votes_read"].astype("boolean")
    return agenda, votes


FACTS = (("minutes", ""), ("format", ""), ("pages", 0), ("roll", ""), ("roll_from", ""), ("letterhead", ""), ("motions", 0), ("motions_read", 0))


def serving_about(date, rolls, either=False):
    """The supervisors on the Board about a day, by the heads of the other minutes read: those named in a head both on
    or before the day and on or after it, no more than APART_DAYS apart. `rolls` is {meeting: (date, [names])}.

    With `either`, those named in a head within APART_DAYS on one side or the other: not the Board, but everyone a
    family name in that day's minutes could be."""
    day = day_type.fromisoformat(date[:10])
    apart_of = lambda seen: abs((day_type.fromisoformat(seen) - day).days)
    seen = {}
    for when, names in rolls.values():
        for name in names:
            seen.setdefault(name, []).append(when[:10])
    out = []
    for name, days in seen.items():
        before = max((when for when in days if when <= date[:10]), default=None)
        after = min((when for when in days if when >= date[:10]), default=None)
        if either and any(apart_of(when) <= APART_DAYS for when in days):
            out.append(name)
        elif before and after and apart_of(before) + apart_of(after) <= APART_DAYS:
            out.append(name)
    return sorted(out)


def read_all(meetings, held, out_dir, since):
    """Every set of minutes whose text is kept here, read against all the others: (agenda rows, vote rows, what was
    found of each meeting, the meetings read, {a name as printed: the one name its person has}).

    The heads are read first, all of them, since who a name is depends on the other minutes: a scan's broken name is
    told by its letters from a head that prints it whole, a name not in a meeting's own head may be someone on the Board
    about then, and a supervisor has one name here however the heads vary it.
    """
    texts = {}
    for row in meetings.to_dict("records"):
        kept = Path(out_dir) / "text" / f"{row['meeting_id']}.txt"
        if row["minutes_url"] and row["date"] >= f"{since}-01-01" and kept.exists():
            texts[row["meeting_id"]] = (row, kept.read_text(encoding="utf-8"))
    found = {}
    of_held = lambda part: [member["name"] for facts in held.values() for member in json.loads(facts.get(part) or "[]")]
    forms = Counter(of_held("roll") + of_held("letterhead"))
    for meeting_id, (row, text) in texts.items():
        if len(re.sub(r"\s", "", text)) < LAYER_CHARS:
            found[meeting_id] = {**dict(FACTS), "minutes": "no text layer", "pages": text.count("\f") + 1}
            continue
        try:
            head = head_of(text)
        except Exception as e:  # minutes the reader cannot take in are marked and left; the rest are still read
            log.warning(f"Meeting {meeting_id} of {row['date']}: its minutes could not be read ({type(e).__name__}: {e})")
            found[meeting_id] = {**dict(FACTS), "minutes": f"not read: {type(e).__name__}", "pages": text.count("\f") + 1}
            continue
        forms.update(member["name"] for member in head["roll"] + head["letterhead"])
    known = {key_of(form) for form, count in forms.items() if count >= 2 and len(form.split()) > 1}
    heads = {meeting_id: head_of(text, known) for meeting_id, (row, text) in texts.items() if meeting_id not in found}
    forms = Counter(of_held("roll") + of_held("letterhead"))
    forms.update(member["name"] for head in heads.values() for member in head["roll"] + head["letterhead"])
    names = one_name(forms)
    name_of = lambda name: names.get(name, name)
    rolls, printed = {}, {}  # who each meeting's head has on the Board, and who its letterhead names
    for meeting_id, facts in held.items():
        if meeting_id not in heads and facts.get("date"):
            rolls[meeting_id] = (facts["date"], [name_of(member["name"]) for member in json.loads(facts.get("roll") or "[]")])
            printed[meeting_id] = (facts["date"], [name_of(member["name"]) for member in json.loads(facts.get("letterhead") or "[]")])
    for meeting_id, head in heads.items():
        rolls[meeting_id] = (texts[meeting_id][0]["date"], [name_of(member["name"]) for member in head["roll"]])
        printed[meeting_id] = (texts[meeting_id][0]["date"], [name_of(member["name"]) for member in head["letterhead"]])
    either = {**{("roll", meeting_id): roll for meeting_id, roll in rolls.items()},
              **{("letterhead", meeting_id): roll for meeting_id, roll in printed.items()}}
    agenda, votes = [], []
    for meeting_id in heads:
        row, text = texts[meeting_id]
        about, around = serving_about(row["date"], either, either=True), serving_about(row["date"], rolls)
        try:
            reading = read_meeting(row, scan(text, known, about), text.count("\f") + 1, about, around, name_of)
        except Exception as e:
            log.warning(f"Meeting {meeting_id} of {row['date']}: its minutes could not be read ({type(e).__name__}: {e})")
            found[meeting_id] = {**dict(FACTS), "minutes": f"not read: {type(e).__name__}", "pages": text.count("\f") + 1}
            continue
        agenda.extend(reading[0])
        votes.extend(reading[1])
        found[meeting_id] = reading[2]
    return agenda, votes, found, set(texts), names


def tables_of(meetings, agenda, votes, found, names):
    """The five tables, from what has been read so far."""
    meetings = meetings.copy()
    for name, empty in FACTS:
        meetings[name] = [found.get(meeting_id, {}).get(name, empty) for meeting_id in meetings["meeting_id"]]
    if len(votes):
        votes["member"] = votes["member"].map(lambda name: names.get(name, name))
    for column in ("mover", "seconder"):
        if len(agenda):
            agenda[column] = agenda[column].map(lambda name: names.get(name, name))
    agenda = agenda.sort_values(["date", "meeting_id", "sequence"]).reset_index(drop=True)
    votes = votes.sort_values(["date", "meeting_id", "item_id", "motion", "member"]).reset_index(drop=True)
    agenda, votes = typed(agenda, votes)
    count = agenda[~agenda["heading"]].groupby("meeting_id").size() if len(agenda) else {}
    meetings["items"] = meetings["meeting_id"].map(count).fillna(0).astype(int)
    for column in ("pages", "motions", "motions_read"):
        meetings[column] = meetings[column].astype(int)
    return council_tables.standard({
        "items": items_table(agenda, meetings), "meetings": meetings, "agenda_items": agenda, "votes": votes,
        "members": members_table(votes, meetings),
    })


def build(base, everything, out_dir, since=FIRST_YEAR, limit=0):
    rows = listed(FIRST_YEAR)
    meetings = board_meetings(rows)
    log.info(f"Calaveras County: {len(meetings)} meetings of the Board listed, {int((meetings['minutes_url'] != '').sum())} with minutes")
    if len(meetings) < 20:
        raise RuntimeError("the listing of meetings came back nearly empty")

    agenda, votes, before_meetings = (council_tables.held(HF_REPO, out_dir, name, base) for name in ("agenda_items", "votes", "meetings"))
    before = 0 if votes is None else len(votes)
    if agenda is None or votes is None or before_meetings is None:
        agenda, votes = pd.DataFrame(columns=AGENDA_COLUMNS), pd.DataFrame(columns=VOTE_COLUMNS)
        before_meetings = pd.DataFrame(columns=MEETING_COLUMNS)
    held = {row["meeting_id"]: {"date": row["date"], **{name: row.get(name, empty) for name, empty in FACTS}}
            for row in before_meetings[before_meetings["minutes"] != ""].to_dict("records")}
    kept = lambda row: (Path(out_dir) / "text" / f"{row['meeting_id']}.txt").exists()
    with_minutes = [row for row in meetings.to_dict("records") if row["minutes_url"] and row["date"] >= f"{since}-01-01"]
    wanted = [row for row in with_minutes if everything or (not kept(row) and row["meeting_id"] not in held)]
    wanted.sort(key=lambda row: (row["date"], row["meeting_id"]), reverse=True)  # the newest first: a room shows those
    waiting = len(wanted)
    wanted = wanted[:limit] if limit else wanted
    log.info(f"Fetching the minutes of {len(wanted)} meetings of {waiting} not yet read, one every {PAUSE} seconds")

    def written():
        """Everything whose text is here is read, old and new, and the tables are written. That asks nothing of the portal."""
        new_agenda, new_votes, found, read, names = read_all(meetings, held, out_dir, since)
        facts = {**{meeting_id: facts for meeting_id, facts in held.items() if meeting_id not in found}, **found}
        tables = tables_of(meetings,
                           joined(agenda[~agenda["meeting_id"].isin(read)], pd.DataFrame(new_agenda, columns=AGENDA_COLUMNS)),
                           joined(votes[~votes["meeting_id"].isin(read)], pd.DataFrame(new_votes, columns=VOTE_COLUMNS)), facts, names)
        council_tables.write_tables(tables, out_dir)
        return tables

    fetched, started = 0, time.time()
    host = urlparse(iqm2.site_of(KEY)).netloc
    if wanted:
        tables = written()  # what is kept is read against the calendar as it now is, before anything is asked for
        log.info(f"Calaveras County: tables written from the minutes kept here, {len(tables['votes'])} votes held")
    for at, row in enumerate(wanted, 1):
        if host in iqm2.REFUSED:
            break
        try:
            _, asked = text_of(row, out_dir, fresh=everything)
            fetched += asked
        except iqm2.Refused as e:
            log.error(f"The portal turned us away ({e}); nothing more is asked of it in this run")
            break
        except NoDocument as e:
            log.warning(f"Meeting {row['meeting_id']} of {row['date']}: {e}")
            asked = True
        except Exception as e:  # one set of minutes that cannot be had or opened does not stop the rest
            log.warning(f"Meeting {row['meeting_id']} of {row['date']}: {type(e).__name__}: {e}")
            asked = True
        if at % EVERY == 0:
            tables = written()
            log.info(f"Calaveras County: {at} of {len(wanted)} minutes asked for, {fetched} fetched, {len(tables['votes'])} votes held, "
                     f"{round((time.time() - started) / 60)} minutes")
        if asked and at < len(wanted):
            time.sleep(PAUSE)
    tables = written()
    if len(tables["votes"]) < before * 0.98:
        raise RuntimeError(f"only {len(tables['votes'])} votes where there were {before}; not publishing")
    return tables, fetched


def card(tables):
    """The dataset card, with the counts of this reading written in."""
    meetings, agenda, votes = tables["meetings"], tables["agenda_items"], tables["votes"]
    read = meetings[meetings["minutes"] == "read"]
    motions, motions_read = int(agenda["motions"].sum()), int(agenda["motions_read"].sum())
    ways = votes["established"].value_counts() if len(votes) else {}
    facts = {
        "repo": HF_REPO, "first_meeting": read["date"].min() if len(read) else "", "last_meeting": read["date"].max() if len(read) else "",
        "first_vote": votes["date"].min() if len(votes) else "", "last_vote": votes["date"].max() if len(votes) else "",
        "n_read": f"{len(read):,}", "n_scans": f"{int((meetings['minutes'] == 'no text layer').sum()):,}",
        "n_with_minutes": f"{int((meetings['minutes_url'] != '').sum()):,}",
        "n_motions": f"{motions:,}", "n_motions_read": f"{motions_read:,}", "n_unread": f"{motions - motions_read:,}",
        "share_read": f"{100 * motions_read / motions:.1f}" if motions else "0", "pause": PAUSE,
        "serving_days": SERVING_DAYS, "seen_days": SEEN_DAYS,
        **{f"n_{way}": f"{int(ways.get(way, 0)):,}" for way in (NAMED, COUNT, UNANIMOUS, MAJORITY)},
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
        log.error(f"Calaveras County tables not uploaded: {e}")
        return False
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the Calaveras County Board's meetings, actions and votes from its minutes")
    parser.add_argument("--base", action="store_true", help="start from the tables written here, not the published ones")
    parser.add_argument("--all", action="store_true", help="fetch every set of minutes again, kept here or not")
    parser.add_argument("--since", type=int, default=FIRST_YEAR, help="read no meeting before this year")
    parser.add_argument("--max", type=int, default=0, help="minutes to fetch in one run (0 for all)")
    parser.add_argument("--out", default="", help="directory to write the tables into (minutes_pdf/calaveras-county if not given)")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the tables only")

    out_dir = Path(args.out) if args.out else OUT_DIR
    try:
        tables, fetched = build(args.base, args.all, out_dir, args.since, args.max)
    except Exception as e:
        log.error(f"Calaveras County tables not built: {type(e).__name__}: {e}")
        return 1
    refused = bool(iqm2.REFUSED)
    pushed = False if args.no_upload or refused else upload(tables, out_dir, args.write_card)
    meetings, agenda, votes, members = tables["meetings"], tables["agenda_items"], tables["votes"], tables["members"]
    motions, motions_read = int(agenda["motions"].sum()), int(agenda["motions_read"].sum())
    ways = votes["established"].value_counts() if len(votes) else {}
    log.info(f"RESULT: calaveras-board items={len(tables['items'])} meetings={len(meetings)} "
             f"meetings_with_minutes={int((meetings['minutes_url'] != '').sum())} "
             f"minutes_read={int((meetings['minutes'] == 'read').sum())} "
             f"no_text_layer={int((meetings['minutes'] == 'no text layer').sum())} agenda_items={len(agenda)} "
             f"motions={motions} motions_read={motions_read} motions_unread={motions - motions_read} votes={len(votes)} "
             f"named={int(ways.get(NAMED, 0))} count={int(ways.get(COUNT, 0))} unanimous={int(ways.get(UNANIMOUS, 0))} "
             f"majority={int(ways.get(MAJORITY, 0))} members={len(members)} serving={int(members['serving'].sum())} "
             f"minutes_fetched={fetched} first_vote={votes['date'].min() if len(votes) else ''} "
             f"last_vote={votes['date'].max() if len(votes) else ''} refused={refused} pushed={pushed}")
    return 0 if (args.no_upload or pushed) and not refused else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
