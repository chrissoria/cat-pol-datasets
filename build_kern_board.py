#!/usr/bin/env python3
"""
Build chrissoria/kern-county-board: the meetings of the Kern County Board of
Supervisors, what the Board did at each, and how each supervisor voted, read
from the Board's Summaries of Proceedings (its minutes).

One source: the County's listing of the Board's meetings in Granicus
(kern.granicus.com/ViewPublisher.php?view_id=58), one page of HTML with every
meeting since September 2006. Each row links the meeting's minutes
(AgendaViewer.php?clip_id=N, which sends a visitor on to a PDF on the same
host) and its video. The system keeps no vote apart from the minutes, so the
votes here are read from them.

The minutes have been set out the same way since 2006. The head names the
Board, by family name, and says who answered the roll:

    Supervisors: Peters, Parlier, Couch, Flores, Perez
    ROLL CALL: All Present            (or "4 Present; 1 Absent - Perez")

Each item is its words, then what the Board did in capitals, then the vote on
a line of its own: who moved, who seconded, and how it went.

    CA-11) Proposed retroactive Cooperative Agreement with the California
    Department of Food and Agriculture ... - APPROVED; AUTHORIZED CHAIRMAN
    TO SIGN AGREEMENT 433-2026
    Perez-Flores: All Ayes
    Rubio-Watson: 3 Ayes; 2 Noes - Maben, Maggard
    McQuiston-Maben: 4 Ayes; 1 Absent - Maggard
    Rubio-McQuiston: 3 Ayes; 1 Absent - Perez; 1 Abstained - Scrivner

The items marked "CA" or "C" (in 2006 and 2007 "*" or "#") are the consent
agenda, approved by one motion, but each still has its vote line, and is read
as its own.

`established` on each vote says how it is known:

  named   the line names the supervisor, with a word ("2 Noes - Maben,
          Maggard": Maben and Maggard voted no).
  count   the line gives a count of ayes and names everyone who was not one.
          The ayes are the supervisors at the head left over, and they must be
          as many as the count says.
  all     the line says "All Ayes": every supervisor present at that point
          voted aye. Who was present is the roll call, changed by what the
          minutes note on the way ("NOTE: SUPERVISOR WATSON LEFT THE MEETING
          PRIOR TO THE VOTE ON ITEM NO. 4", "RECONVENED WITH ALL MEMBERS
          PRESENT"). A supervisor away at that point is ABSENT.

The consent agenda is approved by one motion, and its vote is printed again
under each of its items (those pulled from it and voted on apart have another
mover and seconder), wherever they stand; when it was taken is not printed.
Its "All Ayes" are read against the Board in the room then: the one a note
gives ("Supervisor Perez arrived prior to consideration of the consent
agenda"), or else the only one, of those the roll call and the notes have in
the room during the meeting, that its own lines agree with (its mover and
seconder there, anyone a line names absent away). Where that leaves more than
one, or none, they are not read.

"All Ayes" is not read where who was in the room cannot be told: where the
minutes' own votes (a mover or seconder, a named absence) have a supervisor
there whom the roll call and the notes have away, or the other way round
(someone came or went unnoted, at some point after the last note of them, so
no "All Ayes" from that note on is read); where a note says a supervisor
abstained or was away for part of the item; or where the head has no roll
call that adds up to its Board.

A vote is read whole or not at all. A line whose names are not all on the
Board at the head, whose counts do not add up to that Board, or that is told
in words the reader does not know, puts nothing in votes: its item stays in
agenda_items with `votes_read` false and what stopped it in `problem`.

`action` is the Board's action as the minutes print it in capitals
("APPROVED; AUTHORIZED CHAIRMAN TO SIGN AGREEMENT 433-2026"). `result` is
filled only where they say a motion carried or failed.

Meetings the listing has with another body (the joint meetings with the
Bakersfield City Council, the Civil Service Commission or the Planning
Commission, and the one multi-jurisdictional forum) are not the Board's own,
are kept in other forms, and are left out.

The dataset has the five tables every council's and board's dataset has
(council_tables.py), in data/:
  items.parquet          every item in minutes that were read
  meetings.parquet       one row per meeting of the Board listed
  agenda_items.parquet   one row per item of the minutes, with what was done
  votes.parquet          one row per supervisor and motion voted on
  members.parquet        one row per supervisor with votes on two days or more
They are kept here in minutes_pdf/kern-county/, with the text of each set of
minutes beside them in text/, so a PDF is fetched once.

Two ways to run it:

    python build_kern_board.py
        The routine run. Starts from the published tables, reads the listing
        again, and fetches the minutes not read before and those of meetings
        in the last 90 days (minutes are posted once the Board approves them).

    python build_kern_board.py --base
        The same, starting from the tables written here. It fetches the newest
        minutes first, writes the tables every 20 documents, and can be stopped
        and started again: minutes whose text is kept here are read again on
        every run, which asks nothing of the host.

    --since YEAR  read no meeting before this year (default 2006, where the listing begins)
    --max N       minutes to fetch in one run (default 0, for all)
    --all         fetch again every set of minutes, whether its text is kept here or not
    --out DIR     where to write the tables
    --no-upload   write the tables but do not publish them
    --write-card  publish the dataset card as well as the tables

Needs pdfplumber. Only a PDF's own text is read: minutes that are a scan are
counted and left.

The host's robots file disallows everything to everyone. Chris decided on
2026-10-13 that a vendor's blanket robots file does not bind a named reader of
public records that reads slowly: this asks for one thing a second at most,
follows a redirect only on the same host, and stops at the first refusal.
www.kerncounty.com, which refuses us, is never asked.
"""

import argparse
import html
import io
import json
import logging
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests

import build_federal_bills as bills
import build_sd_county as county
import council_tables
from build_sd_county import clean, today

log = logging.getLogger(__name__)

HF_REPO = "chrissoria/kern-county-board"
OUT_DIR = bills.SCRIPT_DIR / "minutes_pdf" / "kern-county"
CARD_FILE = bills.SCRIPT_DIR / "README_kern_board.md"
TABLES = council_tables.TABLES
BODY = "Board of Supervisors"

HOST = "kern.granicus.com"
VIEW = 58  # the Board's listing. The County's old view 2 sends a visitor to a page of refusal, and is never asked for.
LISTING = f"https://{HOST}/ViewPublisher.php?view_id={VIEW}"
# Rows of the listing that are meetings with another body, kept in other forms: not the Board's own.
OTHERS = re.compile(r"\bJoint\b|Multi-Jurisdictional|Civil Service Commission", re.I)
FIRST_YEAR = 2006  # the listing begins in September 2006
SEATS = 5  # a county's board of supervisors (Government Code 25000)
RECENT_DAYS = 90  # meetings this recent are fetched again
SERVING_DAYS = 120  # the minutes keep no terms of office: a supervisor who voted this recently is taken to be serving
SEEN_DAYS = 2  # someone is a member if they vote on this many days: once may be a clerk's slip
LAYER_CHARS = 200  # minutes with fewer characters of their own than this are a scan
PAUSE = 1.0  # seconds after every request
EVERY = 20  # documents fetched between one writing of the tables and the next
DISTRICT_SHARE = 0.9  # the share of the minutes' mentions of a supervisor's district that must agree
DESCRIPTION = 4000  # the most of an item's words that are kept with it

MEETING_COLUMNS = council_tables.COLUMNS["meetings"] + [
    "name", "video_url", "minutes", "pages", "roll", "present", "chair", "motions", "motions_read"]
AGENDA_COLUMNS = council_tables.COLUMNS["agenda_items"] + [
    "heading", "section", "section_id", "department", "consent", "motions", "motions_read", "votes_read", "problem",
    "established", "vote_line", "doc_type", "number", "motion_log"]
VOTE_COLUMNS = council_tables.COLUMNS["votes"] + ["motion", "motion_text", "established"]
ITEM_COLUMNS = council_tables.COLUMNS["items"] + ["item_id", "meeting_id", "agenda_number", "section", "department", "consent",
                                                  "action_on", "votes_read", "number"]

AYE, NO = council_tables.AYE, council_tables.NO
NAMED, COUNT, ALL = "named", "count", "all"
ABSENT = "ABSENT"
VACANT = "vacant"

# The minutes' words in a vote line, by their letters, and the word the tables have for each.
WORDS = {"ayes": AYE, "aye": AYE, "noes": NO, "noe": NO, "no": NO, "nays": NO, "nay": NO, "absent": ABSENT,
         "abstained": "ABSTAIN", "abstain": "ABSTAIN", "abstaining": "ABSTAIN", "abstention": "ABSTAIN", "abstentions": "ABSTAIN",
         "recused": "RECUSED", "notpresent": "NOT PRESENT", "notvoting": "NOT VOTING", "excused": "EXCUSED"}
_WORD = r"Ayes?|Noes?|No|Nays?|Absent|Abstain(?:ed|ing)?|Abstentions?|Recused|Not\s+Present|Not\s+Voting|Excused"
_VACANCY = re.compile(r"^(\d)\s+Vacan(?:t|cy|cies)$", re.I)
_PART = re.compile(rf"^(\d)\s+({_WORD})\b\s*(?:[-–—:]\s*(.*))?$", re.I)

_SURNAME = r"[A-Z](?:\s?[A-Za-z’']+){1,3}"  # "McQuiston", now and then "Mc Quiston" or "G leason" in a page's text
# "Perez-Flores: All Ayes", "Rubio-Watson: 3 Ayes; 2 Noes - Maben, Maggard"
_VOTE = re.compile(rf"^(?:(?P<mover>{_SURNAME})\s?[-–]\s?(?P<seconder>{_SURNAME})\s*:\s*)?(?P<how>(?:All\s+Ayes?|\d\s+Ayes?)\b.*)$")
_SPLIT_VOTE = re.compile(rf"^(?P<mover>{_SURNAME})\s?[-–]\s?(?P<seconder>{_SURNAME})\s*:\s*(?P<how>\S.*)$")
# An item: "CA-11)", "3)", "C-4)", "*5)" (the consent mark of 2006 and 2007), "#12)".
_ITEM = re.compile(r"^(?P<mark>CA|C|S|\*|#)?\s?-?\s?(?P<number>\d{1,3}[A-Za-z]?)\)\s*(?P<rest>.*)$")
# The same with the bracket left out ("CA-47 Proposed letter ..."), or over a budget unit ("CA-93 8999 WASTE MANAGEMENT ...")
_ITEM_BARE = re.compile(r"^(?P<mark>CA|C)-(?P<number>\d{1,3})\s+(?P<rest>(?:[A-Z][a-z]|\d{4}\s+[A-Z]{2}|[A-Z]{3,}\s).*)$")
# A budget unit at the budget hearings: "C 9144 KERN SANITATION AUTHORITY 272 Hitchcock", "2210 SHERIFF/CORONER 78 Quigley",
# and in 2008 the page first: "147 2750 PLANNING BARAJAS"
_UNIT = re.compile(r"^(?:(?P<mark>CA|C)\s+)?(?:\d{1,3}\s+)?(?P<number>\d{4})\s+(?P<rest>[A-Z][A-Z0-9 .,'’&/()–-]{2,}?)(?:\s+\d{1,3})?(?:\s+[A-Z][a-z]+)?$")
_PROCEDURE = re.compile(r"^(?:BOARD\s+)?(?:ADJOURNED\s+AS|RECONVENED\s+AS)\b")
_ROLL = re.compile(r"^R\s?OLL\s*CALL\s*:?\s*(.*)$", re.I)  # now and then "R OLL CALL"
_BOARD_LINE = re.compile(r"^Supervisors\s*:\s*(.+)$")
_ALL_BACK = re.compile(r"\bRECONVENED\b.{0,60}?\bWITH\s+ALL\s+(?:BOARD\s+)?MEMBERS\b", re.I)
_NOTE = re.compile(r"^NOTE\s*:\s*(.*)$", re.I)
CONSENT = ("CA", "C", "*", "#")
_CONSENT_TIME = re.compile(r"\b(PRIOR\s+TO|BEFORE|FOLLOWING|AFTER)\s+(?:THE\s+)?(?:CONSIDERATION|APPROVAL|VOTE|ADOPTION)?\s*(?:OF|ON)?\s*(?:THE\s+)?CONSENT\s+(?:AGENDA|CALENDAR)", re.I)  # the marks of the consent agenda's items
_GONE = r"LEFT|DEPARTED|EXITED|STEPPED\s+(?:OUT|AWAY|DOWN)|WAS\s+EXCUSED|EXCUSED\s+HIMSELF|EXCUSED\s+HERSELF"
_BACK = r"ARRIVED|RETURNED|REJOINED|RE-?ENTERED|WAS\s+(?:PRESENT|SEATED)|JOINED\s+THE\s+MEETING"
_MOVE = re.compile(rf"\b(?:CHAIRMAN\s+|CHAIRWOMAN\s+|VICE[- ]CHAIRMAN\s+)?SUPERVISORS?\s+(?P<who>[A-Z][A-Z’']+(?:\s*(?:,|AND)\s*(?:SUPERVISOR\s+)?[A-Z][A-Z’']+)*)"
                   rf"(?:\s+(?:RECUSED|EXCUSED)\s+(?:HIMSELF|HERSELF)(?:\s+AND)?)?\s+(?:(?P<gone>{_GONE})|(?P<back>{_BACK}))\b", re.I)
# A note that a supervisor took no part in a vote: "NOTE: SUPERVISOR COUCH ABSTAINED ...", "... RECUSED HIMSELF ..."
_APART = re.compile(r"\b(?:ABSTAIN\w*|RECUS\w*|DID\s+NOT\s+(?:VOTE|PARTICIPATE)|NOT\s+PARTICIPATING|DISQUALIF\w*)\b", re.I)
_CHAIR = re.compile(r"/s/\s*([A-Z][A-Za-z.’' -]+?)\s*(?:,\s*Chairman\b|\n\s*Chairman, Board of Supervisors)")
_ORDINAL = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
_DISTRICT = re.compile(r"\b((?i:First|Second|Third|Fourth|Fifth))\s+(?i:District\s+Supervisor),?\s+((?:[A-Za-z.’'\"“”]+\s+){0,3}[A-Za-z’']+)")
_NUMBER = re.compile(r"\b(AGREEMENTS?|RESOLUTIONS?|ORDINANCES?)\s+(?:NOS?\.?\s*)?([A-Z]{0,2}-?\d[\d-]*\d)")
_TOLD = re.compile(r"^MOTION\s+(FAILED|CARRIED)(?!\s+(?:DUE|FOR)\b)\s*(?:;\s*(\S.*))?$")  # under a vote line
_CARRIED = re.compile(r"\bMOTION\b[^;]{0,80}?\b(CARRIED|FAILED)\b|\b(FAILED|CARRIED)\b\s*$")
# A line that is the page's, not the minutes': the running head of a page and its number.
_FURNITURE = re.compile(
    r"^(?:Summary of Proceedings\b.*\bPage\s*\d+|Board of Supervisors\b.{0,80}\b\d{1,2}/\d{1,2}/\d{4}|Budget Hearings? [A-Z][a-z]+ [\d &,-]+\d{4}"
    r"|Budget\s+Budget|Beg\.\s+Budget\s+Staff|Unit\s*#.*|Page\s*#.*|Sep\.|Page \d+(?: of \d+)?|\d{1,3})$")
# The parts of the minutes, under which the departments stand.
SECTIONS = ("RESOLUTIONS/PROCLAMATIONS", "RESOLUTIONS AND PROCLAMATIONS", "PROCLAMATIONS", "RESOLUTIONS", "APPOINTMENTS",
            "PUBLIC PRESENTATIONS", "PUBLIC REQUESTS", "SCHEDULED PUBLIC REQUESTS", "BOARD MEMBER ANNOUNCEMENTS OR REPORTS",
            "DEPARTMENTAL REQUESTS", "HEARINGS", "CONTINUED HEARINGS", "GENERAL PLAN AMENDMENT HEARINGS", "CLOSED SESSION",
            "CLOSED SESSIONS", "REPORT ON ACTIONS TAKEN IN CLOSED SESSION", "RESULTS OF CLOSED SESSION",
            "MATTERS FOR EXECUTIVE APPROVAL", "DOCUMENTS FOR FILING", "BOARD OF SUPERVISORS", "PRESENTATIONS",
            "CONSENT AGENDA", "PUBLIC HEARINGS", "MISCELLANEOUS LETTERS AND DOCUMENTS FOR FILING", "MISCELLANEOUS")


class Refused(Exception):
    """The host answered with a check, a login or a refusal. It is not asked again in this run."""


class NotPDF(Exception):
    """What the listing links as a meeting's minutes is not a PDF."""


_refused = set()
_session = requests.Session()
_CHECK = re.compile(r"captcha|cf-challenge|are you a human|access denied|just a moment|you have been blocked|PermissionDenied", re.I)
_LOGIN = re.compile(r"PermissionDenied|/login|signin|Login\.php", re.I)


def fetch(url, hops=4, tries=3):
    """One answer from the host, a second after the one before.

    A redirect is followed by hand, and only on the same host: the minutes are sent on to DocumentViewer.php there. One
    sent on to another host is not followed (NotPDF). A refusal, a check, a login or the system's page of refused
    permission ends the run's asking: nothing more is asked of the host.
    """
    for _ in range(hops):
        host = urlparse(url).netloc
        if host != HOST:
            raise NotPDF(f"the minutes are sent on to another host ({host}), which is not asked")
        if host in _refused:
            raise Refused(f"{host} refused an earlier request")
        if _LOGIN.search(url):
            _refused.add(host)
            raise Refused(f"sent to a login or refusal page ({url.split('?')[0]})")
        for attempt in range(tries):
            try:
                answer = _session.get(url, headers=county.HEADERS, timeout=(20, 180), allow_redirects=False)
                break
            except (requests.RequestException, OSError) as e:
                # A host that is not allowed will not be allowed on a second asking.
                if attempt == tries - 1 or isinstance(e, requests.exceptions.ProxyError):
                    raise
                time.sleep(5 * (attempt + 1))
            finally:
                time.sleep(PAUSE)
        page = "html" in answer.headers.get("content-type", "") and answer.content[:4] != b"%PDF"
        if answer.status_code in (401, 403, 429) or (page and _CHECK.search(answer.text[:20000])):
            _refused.add(host)
            raise Refused(f"{answer.status_code} from {url.split('?')[0]}")
        if answer.status_code in (301, 302, 303, 307, 308):
            url = urljoin(url, answer.headers.get("location", ""))
            continue
        answer.raise_for_status()
        return answer
    raise requests.TooManyRedirects(url.split("?")[0])


# ---------------------------------------------------------------------------
# The listing
# ---------------------------------------------------------------------------

_CELL = lambda name: re.compile(rf'(?s)class="meeting{name}"[^>]*>(.*?)</td>')
_CELL_DATE, _CELL_NAME = _CELL("Date"), _CELL("Name")
_WHEN = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2})(?:\s*@\s*(\d{1,2}):(\d\d)\s*([AP]M))?", re.I)
_MINUTES = re.compile(r'href="([^"]*AgendaViewer\.php\?[^"]*clip_id=(\d+)[^"]*)"')


def plain(text):
    """A piece of a page as text."""
    return clean(html.unescape(re.sub(r"<[^>]+>", " ", str(text or ""))).replace("\xa0", " "))


def rows_of(page):
    """The Board's meetings on the listing. A meeting is known by the number of its recording (clip_id); one to come
    has none yet and is not one. A row is on the page once for every tab it is under."""
    rows = {}
    for row in re.split(r"(?i)<tr\b", page):
        name, day = _CELL_NAME.search(row), _CELL_DATE.search(row)
        clip = re.search(r"clip_id=(\d+)", row)
        when = _WHEN.search(plain(day[1])) if day else None
        if not (name and when and clip) or OTHERS.search(plain(name[1])):
            continue
        minutes = _MINUTES.search(row)
        found = {"meeting_id": clip[1], "name": plain(name[1]),
                 "date": f"20{when[3]}-{int(when[1]):02d}-{int(when[2]):02d}",
                 "time": f"{int(when[4])}:{when[5]} {when[6].upper()}" if when[4] else "",
                 "minutes": ("https:" + html.unescape(minutes[1])) if minutes and minutes[1].startswith("//") else
                            html.unescape(minutes[1]) if minutes else "",
                 "video": "MediaPlayer.php" in row}
        if clip[1] not in rows or (found["minutes"] and not rows[clip[1]]["minutes"]):
            rows[clip[1]] = found
    return list(rows.values())


def listed():
    """Every meeting of the Board the listing has. It is one page, of everything since 2006."""
    return rows_of(fetch(LISTING).text)


def meetings_table(rows):
    """One row per meeting listed. What a reading adds is filled in by build()."""
    out = [{
        "meeting_id": row["meeting_id"], "date": row["date"], "time": row["time"], "body": BODY, "location": "",
        "url": LISTING, "agenda_url": "", "minutes_url": row["minutes"], "items": 0, "name": row["name"],
        "video_url": f"https://{HOST}/MediaPlayer.php?view_id={VIEW}&clip_id={row['meeting_id']}" if row["video"] else "",
        **dict(FACTS),
    } for row in rows]
    out = pd.DataFrame(out, columns=MEETING_COLUMNS)
    out["order"] = out["meeting_id"].astype(int)
    return out.sort_values(["date", "order"]).drop(columns="order").reset_index(drop=True)


# ---------------------------------------------------------------------------
# The text of a set of minutes
# ---------------------------------------------------------------------------

def pdf_text(body):
    """The text a PDF carries, a page at a time. Nothing is read off the picture of a page."""
    import pdfplumber
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    with pdfplumber.open(io.BytesIO(body)) as document:
        return [page.extract_text() or "" for page in document.pages]


def text_of(meeting, out_dir, fresh=False):
    """The text of a meeting's minutes, pages parted by form feeds, and whether it was fetched: from the copy kept
    here, or fetched and kept."""
    kept = Path(out_dir) / "text" / f"{meeting['meeting_id']}.txt"
    if kept.exists() and not fresh:
        return kept.read_text(encoding="utf-8"), False
    body = fetch(meeting["minutes_url"]).content
    if body[:4] != b"%PDF":
        raise NotPDF("the listing sent something that is not a PDF")
    text = "\n\f".join(pdf_text(body))
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(text, encoding="utf-8")
    return text, True


def lines_of(text):
    """The minutes' lines in order, without the running head and number of each page."""
    return [line for line in (clean(row) for row in text.replace("\f", "\n").split("\n")) if line and not _FURNITURE.match(line)]


# ---------------------------------------------------------------------------
# Who a name is
# ---------------------------------------------------------------------------

def key_of(name):
    """What two printings of a name share: its letters. "Mc Quiston" is "McQuiston"."""
    return re.sub(r"[^a-z]", "", str(name or "").lower())


def names_in(text):
    """The names in a list: "Maben, Maggard" or "McQuiston, Watson and Rubio"."""
    text = clean(text).strip(" .;,")
    return [clean(piece).strip(" .") for piece in re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+|\s*&\s*", text) if clean(piece).strip(" .")]


def who(name, roll):
    """The supervisor on the roll that a printed name is, or None. The minutes print family names only."""
    key = key_of(re.sub(r"^(?:Supervisors?|Chair\w*|Vice[- ]?Chair\w*)\s+", "", clean(name), flags=re.I))
    found = [member for member in roll if key_of(member) == key]
    return found[0] if len(found) == 1 else None


def board_of(line):
    """The Board a "Supervisors:" line names, as [names], a seat called vacant as VACANT."""
    names = []
    for name in names_in(line):
        # A comma left out between two family names ("Scrivner Maggard"); "Mc Quiston" is one.
        words = name.split()
        # A name the page's text breaks ("Mc Quiston", "G leason") is put back together.
        names.extend(words if len(words) > 1 and all(len(word) > 3 and word[0].isupper() for word in words) else ["".join(words)])
    return [VACANT if key_of(name).startswith(VACANT) else name for name in names]


def present_of(said, roll):
    """Who answered the roll, by "All Present" or "4 Present; 1 Absent - Perez", as (set, "", the Board), or (None, why
    not, the Board).

    Now and then the head names only those present ("Supervisors: Peters, Parlier, Couch, Perez" over "ROLL CALL: 4
    Present; 1 Absent - Flores"): the Board is then those and the ones the roll call has absent, where that makes five.
    """
    seated = [name for name in roll if name != VACANT]
    said = clean(said).strip(" .")
    if re.fullmatch(r"All\s+(?:Members\s+)?Present", said, re.I):
        return set(seated), "", roll
    found = re.fullmatch(r"(?:(\d)\s+Present\s*[;,]\s*)?(\d)\s+Absent\s*[-–—:,]\s*(.+?)(?:\s*;\s*\d\s+Vacan\w+)?", said, re.I)
    if not found:
        return None, f"a roll call the reader does not know: {said[:60]}", roll
    printed = names_in(found[3].replace(";", ","))
    missing = [name for name in printed if who(name, seated) is None]
    if missing and len(seated) + len(missing) == SEATS and VACANT not in roll and all(re.fullmatch(r"[A-Z][a-z’']+", name) for name in missing):
        roll = roll + missing
        seated = seated + missing
    away = [who(name, seated) for name in printed]
    if None in away or len(set(away)) != int(found[2]) or (found[1] and int(found[1]) + int(found[2]) != len(seated)):
        return None, f"the roll call does not add up to the Board: {said[:60]}", roll
    return set(seated) - set(away), "", roll


# ---------------------------------------------------------------------------
# A vote line
# ---------------------------------------------------------------------------

def decide(how, roll, present):
    """Every supervisor's vote on a line as ([(supervisor, word, established)], ""), or (None, why it is not read).

    `roll` is the Board at the head, `present` who was there at that point by the roll call and the notes, or None
    where that cannot be told.
    """
    seated = [name for name in roll if name != VACANT]
    if not seated:
        return None, "no Board at the head of the minutes"
    how = clean(how).strip(" .")
    if re.fullmatch(r"All\s+Ayes?", how, re.I):
        if present is None:
            return None, "All Ayes, where who was there at that point cannot be told"
        return [(name, AYE if name in present else ABSENT, ALL) for name in seated], ""
    # The text of a page now and then sets a count after the semicolon before it, or drops the semicolon:
    # "1 Absent - Perez 1; Abstained - Maggard", "1 Absent - Gleason 1 Abstained - Scrivner".
    how = re.sub(rf"([a-z])\s+(\d)\s*;?\s*(?=(?:{_WORD})\b)", r"\1; \2 ", how)
    parts = [clean(part) for part in re.split(r"\s*;\s*", how) if clean(part)]
    cast, counted, vacancies, ayes = [], 0, 0, None
    for part in parts:
        vacant = _VACANCY.match(part)
        if vacant:
            vacancies += int(vacant[1])
            continue
        found = _PART.match(part)
        if not found:
            return None, f"words the reader does not know: {part[:60]}"
        number, word, names = int(found[1]), WORDS[key_of(found[2])], names_in(found[3] or "")
        counted += number
        if word == AYE and not names:
            ayes = (ayes or 0) + number
            continue
        if len(names) != number:
            return None, f"{number} {found[2]} and {len(names)} named"
        for name in names:
            member = who(name, seated)
            if member is None:
                return None, f"not on the Board: {name}"
            cast.append((member, word, NAMED))
    if counted != len(seated):
        return None, f"the line counts {counted} and the Board has {len(seated)}"
    if vacancies and vacancies != roll.count(VACANT):
        return None, f"the line has {vacancies} vacant and the head {roll.count(VACANT)}"
    if len({member for member, _, _ in cast}) != len(cast):
        return None, "a supervisor named twice"
    if ayes:
        rest = [name for name in seated if name not in {member for member, _, _ in cast}]
        if len(rest) != ayes:
            return None, f"{ayes} ayes and {len(rest)} supervisors left"
        cast += [(name, AYE, COUNT) for name in rest]
    order = {name: place for place, name in enumerate(seated)}
    return sorted(cast, key=lambda vote: order[vote[0]]), ""


# ---------------------------------------------------------------------------
# Reading a set of minutes
# ---------------------------------------------------------------------------

def capitals(text):
    """Whether a line is in capitals (the Board's action, or a heading): it has letters and none of them small."""
    return bool(re.search(r"[A-Z]{2}", text)) and not re.search(r"[a-z]", re.sub(r"\b(?:a\.m\.|p\.m\.|No\.|Nos\.)", "", text))


def note_of(lines, at):
    """A note and the lines it runs on to, as (its words, the place after it). A note ends where an item, a vote, a
    roll call or another note begins, or where a line is not in capitals (a note of an absence is in capitals, and
    since 2024 in a sentence of its own)."""
    words, place = [_NOTE.match(lines[at])[1]], at + 1
    while place < len(lines) and len(words) < 5:
        line = lines[place]
        if _NOTE.match(line) or _ITEM.match(line) or _VOTE.match(line) or _ROLL.match(line) or _BOARD_LINE.match(line):
            break
        if capitals(words[0]) != capitals(line) or (not capitals(words[0]) and words[-1].rstrip().endswith(".")):
            break
        words.append(line)
        place += 1
    return clean(" ".join(words)), place


def moves_in(words, roll):
    """Who a note has coming or going: [(supervisor, True if they came, False if they went, None if they went and came
    back within the note: "left the dais at the beginning of Item No. 13 and returned following the vote")]. A name not on
    the Board is left out."""
    out, words = [], words.upper()
    for found in _MOVE.finditer(words):
        back = bool(found["back"])
        came_back = not back and re.search(rf"\bAND\s+(?:{_BACK}|CAME\s+BACK)\b", words[found.end():found.end() + 200])
        for name in names_in(re.sub(r"\bSUPERVISORS?\s+", "", found["who"]).replace(" AND ", ", ")):
            member = who(name, roll)
            if member:
                out.append((member, None if came_back else back))
    return out


def scan(text):
    """A set of minutes as its sessions (each a roll call and the Board at the head), its items, and the vote lines
    under each, with who the roll call and the notes have present at each vote.

    An item is a numbered line ("CA-11)", "3)"), a budget unit at the budget hearings, or a step of procedure that has a
    vote of its own ("ADJOURNED AS BOARD OF SUPERVISORS; RECONVENED AS ..."). What stands in capitals above a vote is
    the action it was on; what stands in capitals between a vote and the next item is the heading the item is under.
    """
    lines = lines_of(text)
    budget = any(re.search(r"\bUnit\s*#", row) for row in text.split("\n"))  # the budget hearings' column heads
    sessions, items = [], []
    session, item = None, None
    section, department, headings = "", "", []
    seen, highest, opened, loose = set(), 0, True, []  # the items so far in a session; whether an item may begin here
    noted = ""  # the words of a note since the last vote
    ahead = {}  # the same, for an item a note names that is not printed yet
    upcoming, partly = [], []  # notes of an abstention, or of an absence for part of an item, that stand before the item
    at = 0

    def begin(kind, mark, number, words):
        nonlocal item, headings, section, department
        for heading in headings:
            if heading in SECTIONS or heading.rstrip(":") in SECTIONS:
                section, department = heading.rstrip(":"), ""
            elif not re.match(r"^S\.\s?D\.\s?#", heading):
                department = heading
        headings = []
        if session is not None:
            session["business"] = True
        item = {"kind": kind, "mark": mark or "", "number": number, "lines": [words] if words else [], "votes": [],
                "section": section, "department": department, "session": session, "after_vote": False, "apart": list(upcoming), "partly": list(partly)}
        upcoming.clear()
        partly.clear()
        for name, notes in ahead.pop(number, {}).items():
            item[name].extend(notes)
        items.append(item)

    def aimed(words, kind, waiting):
        """Where a note of a supervisor away or taking no part belongs: the item it names ("PRIOR TO THE VOTE ON ITEM
        NO. 10"), if that has been printed in this session; else the item it stands in, if no vote is printed under it
        yet; else the next one."""
        named = re.search(r"\bITEM\s+(?:NO\.?\s*)?([A-Z]{0,2}-?\d{1,3})\b", words.upper())
        if named:
            number = re.sub(r"^[A-Z]{1,2}-?", "", named[1])
            done = [one for one in items if one["session"] is session and one["number"] == number]
            return done[-1][kind] if done else ahead.setdefault(number, {"partly": [], "apart": []})[kind]
        return item[kind] if item is not None and not item["votes"] and item["kind"] != "other" else waiting

    while at < len(lines):
        line = lines[at]
        board = _BOARD_LINE.match(line)
        if board:
            session = {"roll": board_of(board[1]), "present": None, "problem": "no roll call under the Board at the head",
                       "changed": False, "votes": 0, "called": "", "since": {}, "states": []}
            if _ALL_BACK.search(" ".join(lines[max(0, at - 2):at])):
                # "BOARD RECONVENED WITH ALL MEMBERS PRESENT" over the Board, with no roll call under it
                session["present"], session["problem"] = {name for name in session["roll"] if name != VACANT}, ""
                session["states"] = [frozenset(session["present"])]
            sessions.append(session)
            seen, highest, opened, loose = set(), 0, True, []
            at += 1
            continue
        roll = _ROLL.match(line)
        if roll and session is not None:
            session["present"], session["problem"], session["roll"] = present_of(roll[1], session["roll"])
            session["called"] = clean(roll[1])
            session["states"] = [] if session["present"] is None else [frozenset(session["present"])]
            opened = True
            at += 1
            continue
        if _NOTE.match(line):
            words, after = note_of(lines, at)
            if session is not None and session["present"] is not None:
                before = frozenset(session["present"])
                timed = _CONSENT_TIME.search(words)
                for member, came in moves_in(words, session["roll"]):
                    session["since"][member] = session["votes"]
                    session["changed"] = session["changed"] or session["votes"] > 0
                    if came is None:  # away for part of an item: the item the note stands in, or the next one
                        aimed(words, "partly", partly).append(member)
                    elif came != (member in session["present"]):
                        session["present"] = session["present"] | {member} if came else session["present"] - {member}
                        # A Board in the room only before the first item (an arrival "following roll call") took no vote.
                        session["states"] = session["states"] if session.get("business") else []
                        session["states"].append(frozenset(session["present"]))
                if timed and moves_in(words, session["roll"]):
                    # "arrived prior to consideration of the consent agenda", "left following approval of the consent agenda"
                    session["consent_hint"] = frozenset(session["present"]) if timed[1].upper() in ("PRIOR TO", "BEFORE") else before
            if _APART.search(words) and moves_in(re.sub(_APART, " LEFT", words.upper()), session["roll"] if session else []):
                # A supervisor who abstained or took no part: the item the note stands in, or the next one.
                aimed(words, "apart", upcoming).append(words)
            opened, noted = True, words
            at = after
            continue
        if session is not None and line.upper().startswith(("RECONVENED", "BOARD RECONVENED")) and _ALL_BACK.search(" ".join(lines[at:at + 2])):
            if session["present"] is not None:
                everyone = {name for name in session["roll"] if name != VACANT}
                session["changed"] = session["changed"] or (session["present"] != everyone and session["votes"] > 0)
                for member in everyone - session["present"]:
                    session["since"][member] = session["votes"]
                if session["present"] != everyone:
                    session["states"].append(frozenset(everyone))
                session["present"] = everyone
            opened = True
            at += 1
            continue
        vote = _VOTE.match(line)
        if not vote and session is not None:
            split = _SPLIT_VOTE.match(line)
            vote = split if split and who(split["mover"], session["roll"]) and who(split["seconder"], session["roll"]) else None
        if vote and session is not None:
            printed = line
            # A vote line that runs on to the next: "3 Ayes; 1 Absent – Perez; 1" / "Abstained - Scrivner".
            while at + 1 < len(lines) and (printed.rstrip().endswith((";", ",", "-", "–")) or re.search(r";\s*\d$", printed)) \
                    and re.match(rf"^(?:\d\s+)?(?:{_WORD}|[A-Z][a-z]+)\b", lines[at + 1]) and not _ITEM.match(lines[at + 1]):
                at += 1
                printed = f"{printed} {lines[at]}"
            vote = _VOTE.match(printed) or _SPLIT_VOTE.match(printed)
            # A vote under a note, with no item begun since the vote before ("NOTE: CHAIRMAN MAGGARD INTRODUCED ...
            # SUPERVISOR GOH HEARD ...; REFERRED TO ..."), is on what the note tells, not a second motion on the item above,
            # unless the note names that item ("... LEFT THE MEETING DURING REFERRAL DISCUSSION ON ITEM NO. 32").
            about = re.findall(r"\bITEM\s+(?:NOS?\.?\s*)?(?:[A-Z]{1,2}-)?(\d{1,3}[A-Z]?)\b", noted.upper())
            if item is not None and item["after_vote"] and item["kind"] == "item" and noted and item["number"].upper() not in about:
                told = [noted] + item.pop("pending", [])
                begin("other", "", "", "")
                item["lines"], words, headings = list(told), list(told), []
            elif item is None or item["session"] is not session or (item["after_vote"] and item["kind"] != "item"):
                words = (item or {}).pop("pending", None) if item is not None and item["session"] is session else None
                words = words or headings or [row for row in loose[-6:] if capitals(row)]
                headings = []
                begin("other", "", "", "")
                item["lines"], words = list(words), list(words)
            else:
                words = item.pop("pending", None)
                if words is None:
                    words = list(item["lines"]) if not item["votes"] else []
            item["votes"].append({"printed": clean(printed), "mover": clean(vote["mover"] or ""), "seconder": clean(vote["seconder"] or ""),
                                  "how": clean(vote["how"]), "words": words,
                                  "present": None if session["present"] is None else set(session["present"]),
                                  "changed": session["changed"], "session": session, "index": session["votes"],
                                  "since": dict(session["since"])})
            session["votes"] += 1
            item["after_vote"], opened, loose, noted = True, True, [], ""
            at += 1
            continue
        told = _TOLD.match(line)
        if told and item is not None and item["votes"] and item["after_vote"] and not item.get("pending"):
            # "MOTION FAILED" printed under the vote it tells of
            item["votes"][-1]["outcome"] = told[1].lower()
            if told[2]:
                lines[at] = told[2]
                continue
            at += 1
            continue
        numbered = _ITEM.match(line) or (_ITEM_BARE.match(line) if opened else None)
        unit = _UNIT.match(line) if budget else None
        name = f"{numbered['mark'] or ''}{numbered['number']}" if numbered else ""
        if numbered and name not in seen and (opened or int(re.match(r"\d+", numbered["number"])[0]) > highest):
            seen.add(name)
            highest = max(highest, int(re.match(r"\d+", numbered["number"])[0]))
            begin("item", numbered["mark"], numbered["number"], numbered["rest"])
            opened, loose = False, []
        elif unit and not re.search(r"[a-z]{3}", unit["rest"]):
            begin("unit", unit["mark"], unit["number"], line)
            item["unit"] = clean(unit["rest"])
            opened, loose = False, []
        elif _PROCEDURE.match(line) and item is not None and item["after_vote"]:
            begin("other", "", "", line)
            item["after_vote"], opened = False, False
        elif (line.rstrip(":") in SECTIONS or (headings and capitals(line))) and not (
                item is not None and item["kind"] == "other" and not item["after_vote"]):  # "... RECONVENED AS" / "BOARD OF SUPERVISORS"
            headings.append(line)
            opened = True
        elif item is not None and item["after_vote"]:
            # In capitals after a vote: the words of the next motion on the item if a vote follows before the next item,
            # or else a heading.
            following = next((row for row in lines[at + 1:at + 12] if _ITEM.match(row) or _VOTE.match(row)
                              or (budget and _UNIT.match(row)) or _NOTE.match(row)), "")
            if _VOTE.match(following) and line.rstrip(":") not in SECTIONS:
                item.setdefault("pending", []).append(line)
            else:
                headings.append(line)
                opened = True
        elif item is not None:
            item["lines"].append(line)
            opened = False
        else:
            loose.append(line)
        at += 1
    chair = _CHAIR.findall(text)
    return {"sessions": sessions, "items": items, "budget": budget, "chair": clean(chair[-1]) if chair else ""}


def parted(item):
    """An item's words as (title, action): what the Board was asked, and what it did, which the minutes print in capitals
    after a dash ("... (Fiscal Impact: None) - APPROVED; AUTHORIZED CHAIRMAN TO SIGN AGREEMENT 121-2011")."""
    words = clean(" ".join(item["lines"]))
    if item["kind"] == "other":
        return words, words
    if item["kind"] == "unit":  # the unit's name, then what was done, in capitals
        return item.get("unit", ""), clean(" ".join(item["lines"][1:]))
    # The action is the last part after a dash with no small letters in it.
    for found in re.finditer(r"\s[-–—]\s*", words):
        rest = words[found.end():]
        if capitals(rest) and not re.search(r"[a-z]", rest):
            return clean(words[:found.start()]), clean(rest)
    return words, ""


def number_in(action):
    """The agreement's, resolution's or ordinance's number the action gives: "Agreement 433-2026", or ""."""
    found = _NUMBER.search(action or "")
    return f"{found[1].rstrip('S').title()} {found[2]}" if found else ""


def read_meeting(meeting, scanned, pages=0):
    """One meeting's minutes: its items, the votes on each line that could be read whole, and what the reading found."""
    meeting_id, date = str(meeting["meeting_id"]), meeting["date"]
    first = scanned["sessions"][0] if scanned["sessions"] else None
    facts = {"minutes": "read", "pages": pages,
             "roll": json.dumps(first["roll"], ensure_ascii=False) if first else "",
             "present": first.get("called", "") if first else "",
             "chair": scanned["chair"], "motions": 0, "motions_read": 0}
    agenda, votes, used = [], [], set()
    for sequence, item in enumerate(scanned["items"], 1):
        mark = item["mark"]
        number = f"{mark}-{item['number']}" if mark in ("CA", "C", "S") else f"{mark}{item['number']}"
        base = f"{meeting_id}-{number}" if item["kind"] != "other" else f"{meeting_id}-x{sequence}"
        item_id, again = base, 1
        while item_id in used:  # a number the minutes use twice (a second session in one set)
            again += 1
            item_id = f"{base}-{again}"
        used.add(item_id)
        consent = mark in CONSENT
        title, action = parted(item)
        log_, read_all, problems, ways = [], True, [], set()
        # A supervisor the minutes' own votes put in the room against what the notes say, or out of it: from there on,
        # "All Ayes" in that session rests on nothing.
        for place, motion in enumerate(item["votes"], 1):
            session = motion["session"]
            roll = session["roll"]
            present = motion["present"]
            taken = motion.get("consent_motion", False)  # the consent agenda's one motion, not an item pulled from it
            if taken:
                present = session["consent"]
            all_ayes = motion["how"].lower().startswith("all")
            if all_ayes and taken and session["unsure_consent"] and session["states"]:
                cast, problem = None, "the consent agenda's All Ayes, and its own lines or the notes leave who was there when it was taken unknown"
            elif all_ayes and present is None:
                cast, problem = None, session["problem"] or "All Ayes, where who was there at that point cannot be told"
            elif all_ayes and not taken and motion["index"] >= session.get("unsure_from", 10 ** 6):
                cast, problem = None, "All Ayes, and the minutes' own votes disagree with the roll call and notes on who was there"
            elif all_ayes and item["apart"]:
                cast, problem = None, "All Ayes, and a note says a supervisor took no part"
            elif all_ayes and item["partly"]:
                cast, problem = None, "All Ayes, and a note has a supervisor away for part of the item"
            else:
                cast, problem = decide(motion["how"], roll, present)
            mover, seconder = who(motion["mover"], roll) or motion["mover"], who(motion["seconder"], roll) or motion["seconder"]
            motion_text = clean(" ".join(motion["words"])) if place > 1 else action or title
            for member, word, established in cast or []:
                votes.append({"item_id": item_id, "meeting_id": meeting_id, "date": date, "matter_id": item_id, "matter_file": "",
                              "member": member, "vote": word, "motion": place, "motion_text": motion_text, "established": established})
                ways.add(established)
            read_all = read_all and cast is not None
            if problem:
                problems.append(problem)
            log_.append({"motion": place, "line": motion["printed"], "text": motion_text, "mover": mover, "seconder": seconder,
                         "outcome": motion.get("outcome", ""), "read": cast is not None, "problem": problem})
            motion.update(cast=cast or [], mover_is=mover, seconder_is=seconder)
        last = item["votes"][-1] if item["votes"] else None
        cast = [word for _, word, _ in last["cast"]] if last else []
        said = clean(" ".join(item["votes"][-1]["words"])) if last and len(item["votes"]) > 1 else action
        outcome = _CARRIED.search(said or "")
        printed_outcome = last.get("outcome", "") if last else ""
        agenda.append({
            "item_id": item_id, "meeting_id": meeting_id, "date": date, "body": BODY, "agenda_number": number if item["kind"] != "other" else "",
            "sequence": sequence, "matter_id": item_id, "matter_file": "", "title": title[:DESCRIPTION],
            "action": action if len(item["votes"]) < 2 else "; ".join(filter(None, [action] + [clean(" ".join(m["words"])) for m in item["votes"][1:]])),
            "result": printed_outcome or ((outcome[1] or outcome[2]).lower() if outcome else ""),
            "mover": last["mover_is"] if last else "", "seconder": last["seconder_is"] if last else "",
            "ayes": cast.count(AYE), "noes": cast.count(NO), "not_voting": sum(word not in (AYE, NO) for word in cast),
            "heading": False, "section": item["section"], "section_id": "", "department": item["department"], "consent": consent,
            "motions": len(item["votes"]), "motions_read": sum(entry["read"] for entry in log_),
            "votes_read": read_all if item["votes"] else None, "problem": problems[0] if problems else "",
            "established": "" if not ways else NAMED if ways == {NAMED} else ALL if ALL in ways else COUNT,
            "vote_line": " | ".join(motion["printed"] for motion in item["votes"]),
            "doc_type": county.doc_type_of(f"{title} {action}"), "number": number_in(action),
            "motion_log": json.dumps(log_, ensure_ascii=False, separators=(",", ":")) if log_ else "",
        })
        facts["motions"] += len(item["votes"])
        facts["motions_read"] += sum(entry["read"] for entry in log_)
    return agenda, votes, facts


def evidence(motion, roll):
    """Who a vote line shows in the room and out of it: (there, away). A mover and a seconder are there; a line that
    names its votes shows everyone it names, and those it has absent away."""
    there = {who(motion["mover"], roll), who(motion["seconder"], roll)} - {None}
    cast, _ = decide(motion["how"], roll, None) if not motion["how"].lower().startswith("all") else (None, "")
    return there | {member for member, word, _ in cast or [] if word != ABSENT}, {member for member, word, _ in cast or [] if word == ABSENT}


def checked(scanned):
    """Marks where "All Ayes" rest on nothing.

    The consent agenda is one motion, whose vote is printed under each of its items (the items pulled from it and voted
    on apart have another mover and seconder). Where a note says a supervisor came or went before or after the consent
    agenda, who was there is the Board the note leaves; otherwise when it was taken is not printed, and who was there is
    the one Board, of those the roll call and the notes have in the room at some point of the session, that its own lines
    agree with (its mover and seconder there, anyone a line names absent away). If none or more than one is, its "All
    Ayes" are not read (`unsure_consent`); nor are they where a supervisor came or went unnoted (below), unless its own
    lines show where that supervisor was.

    A session's `unsure_from` is set where the minutes' own votes on other items have someone in or out of the room
    against what the roll call and notes say: that supervisor came or went unnoted at some point after the last note of
    them, so no "All Ayes" from there on is read.
    """
    for session in scanned["sessions"]:
        roll = session["roll"]
        lines = [motion for item in scanned["items"] if item["mark"] in CONSENT for motion in item["votes"] if motion["session"] is session]
        pairs = Counter((key_of(motion["mover"]), key_of(motion["seconder"])) for motion in lines)
        pair = pairs.most_common(1)[0][0] if pairs else None
        main = [motion for motion in lines if (key_of(motion["mover"]), key_of(motion["seconder"])) == pair]
        for motion in main:
            motion["consent_motion"] = True
        shown = [evidence(motion, roll) for motion in main]
        hinted = {session["consent_hint"]} if session.get("consent_hint") else set(session["states"])
        fits = {state for state in hinted if all(there <= state and not (away & state) for there, away in shown)}
        session["consent"] = set(next(iter(fits))) if len(fits) == 1 else None
        session["unsure_consent"] = len(fits) != 1
    for item in scanned["items"]:
        for motion in item["votes"]:
            session, present = motion["session"], motion["present"]
            if present is None or motion.get("consent_motion"):
                continue
            there, away = evidence(motion, session["roll"])
            for member in ((there - present) | (away & present)) - set(item["partly"]):
                start = motion["since"].get(member, 0)
                session["unsure_from"] = min(session.get("unsure_from", start), start)
                session.setdefault("unnoted", set()).add(member)
    for session in scanned["sessions"]:
        # Where someone came or went unnoted, the Boards the notes give are not all there were, and the consent agenda's
        # "All Ayes" rest on nothing, unless its own lines show where each such supervisor was when it was taken.
        shown = set()
        for item in scanned["items"]:
            for motion in item["votes"]:
                if motion.get("consent_motion") and motion["session"] is session:
                    shown |= set().union(*evidence(motion, session["roll"]))
        if session.get("unnoted", set()) - shown:
            session["unsure_consent"] = True
    return scanned


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------

def items_table(agenda, meetings):
    """Every item in the minutes read, with what was done with it. The system has no record of an item apart from its
    line in the minutes, so an item is here once for each meeting it came to."""
    minutes = dict(zip(meetings["meeting_id"], meetings["minutes_url"]))
    rows = []
    for line in agenda[agenda["agenda_number"] != ""].itertuples(index=False):
        voted = line.motions > 0
        rows.append({
            "date": line.date, "matter_id": line.item_id, "matter_file": "", "doc_type": line.doc_type, "title": line.title,
            "body": line.body, "status": "", "year": int(line.date[:4]), "subject": line.department, "agenda_date": line.date,
            "passed_date": "", "last_action": line.action, "last_action_date": line.date if line.action else "", "result": line.result,
            "ayes": int(line.ayes), "noes": int(line.noes), "mover": line.mover, "seconder": line.seconder,
            "times_on_agenda": 1, "url": minutes.get(line.meeting_id, ""),
            "item_id": line.item_id, "meeting_id": line.meeting_id, "agenda_number": line.agenda_number, "section": line.section,
            "department": line.department, "consent": bool(line.consent), "action_on": "item" if voted else "",
            "votes_read": bool(line.votes_read) if voted else None, "number": line.number,
        })
    out = pd.DataFrame(rows, columns=ITEM_COLUMNS)
    out["votes_read"] = out["votes_read"].astype("boolean")
    out["consent"] = out["consent"].astype(bool)
    return out.sort_values(["date", "meeting_id"], ascending=False, kind="stable").reset_index(drop=True)


def districts_of(texts):
    """{family name's letters: district} from the minutes' own words ("Led by Second District Supervisor Zack
    Scrivner"). A name is any of the next few words; members_table() keeps only those of supervisors. A supervisor is
    given the district nearly every mention gives them (a slip now and then names another): DISTRICT_SHARE of them."""
    seen = {}
    for text in texts:
        for ordinal, name in _DISTRICT.findall(clean(text)):
            for word in name.split():
                seen.setdefault(key_of(word), Counter())[_ORDINAL[ordinal.lower()]] += 1
    out = {}
    for name, counts in seen.items():
        district, times = counts.most_common(1)[0]
        if times >= 2 and times >= DISTRICT_SHARE * sum(counts.values()):
            out[name] = district
    return out


def members_table(votes, meetings, districts):
    """Everyone with votes here on several days. The minutes keep no terms of office. `district` is the one the minutes'
    own words give the supervisor; `role` is Chairman for the one who signed the newest minutes read as Chairman."""
    days = votes.groupby("member")["date"].nunique() if len(votes) else pd.Series(dtype=int)
    cast = votes.groupby("member")["date"].agg(["min", "max", "size"]) if len(votes) else pd.DataFrame()
    since = (datetime.now(timezone.utc) - timedelta(days=SERVING_DAYS)).strftime("%Y-%m-%d")
    read = meetings[(meetings["minutes"] == "read") & (meetings["chair"] != "")].sort_values("date")
    chair = key_of(read["chair"].iloc[-1].split()[-1]) if len(read) else ""
    rows = []
    for name in sorted(days[days >= SEEN_DAYS].index):
        serving = bool(cast.loc[name, "max"] >= since)
        rows.append({"name": name, "district": districts.get(key_of(name)),
                     "role": "Chairman" if serving and key_of(name) == chair else "", "start": "", "end": "", "serving": serving,
                     "first_vote": cast.loc[name, "min"], "last_vote": cast.loc[name, "max"], "votes": int(cast.loc[name, "size"])})
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
    for column in ("heading", "consent"):
        agenda[column] = agenda[column].astype(bool)
    agenda["votes_read"] = agenda["votes_read"].astype("boolean")
    return agenda, votes


FACTS = (("minutes", ""), ("pages", 0), ("roll", ""), ("present", ""), ("chair", ""), ("motions", 0), ("motions_read", 0))


def read_all(meetings, out_dir, since):
    """Every set of minutes whose text is kept here: (agenda rows, vote rows, what was found of each meeting, the
    meetings read, {family name: district})."""
    agenda, votes, found, texts = [], [], {}, {}
    for row in meetings.to_dict("records"):
        kept = Path(out_dir) / "text" / f"{row['meeting_id']}.txt"
        if row["minutes_url"] and row["date"] >= f"{since}-01-01" and kept.exists():
            texts[row["meeting_id"]] = (row, kept.read_text(encoding="utf-8"))
    for meeting_id, (row, text) in texts.items():
        pages = text.count("\f") + 1
        if len(re.sub(r"\s", "", text)) < LAYER_CHARS:
            found[meeting_id] = {**dict(FACTS), "minutes": "no text layer", "pages": pages}
            continue
        try:
            scanned = checked(scan(text))
            if not scanned["sessions"]:
                found[meeting_id] = {**dict(FACTS), "minutes": "not read: no roll of the Board at the head", "pages": pages}
                continue
            reading = read_meeting(row, scanned, pages)
        except Exception as e:  # minutes the reader cannot take in are marked and left; the rest are still read
            log.warning(f"Meeting {meeting_id} of {row['date']}: its minutes could not be read ({type(e).__name__}: {e})")
            found[meeting_id] = {**dict(FACTS), "minutes": f"not read: {type(e).__name__}", "pages": pages}
            continue
        agenda.extend(reading[0])
        votes.extend(reading[1])
        found[meeting_id] = reading[2]
    return agenda, votes, found, set(texts), districts_of(text for _, text in texts.values())


def tables_of(meetings, agenda, votes, found, districts):
    """The five tables, from what has been read so far."""
    meetings = meetings.copy()
    for name, empty in FACTS:
        meetings[name] = [found.get(meeting_id, {}).get(name, empty) for meeting_id in meetings["meeting_id"]]
    for table in (agenda, votes):
        table["order"] = table["meeting_id"].astype(int) if len(table) else 0
    agenda = agenda.sort_values(["date", "order", "sequence"]).drop(columns="order").reset_index(drop=True)
    votes = votes.sort_values(["date", "order", "item_id", "motion", "member"]).drop(columns="order").reset_index(drop=True)
    agenda, votes = typed(agenda, votes)
    count = agenda[agenda["agenda_number"] != ""].groupby("meeting_id").size() if len(agenda) else {}
    meetings["items"] = meetings["meeting_id"].map(count).fillna(0).astype(int)
    for column in ("pages", "motions", "motions_read"):
        meetings[column] = meetings[column].astype(int)
    return council_tables.standard({
        "items": items_table(agenda, meetings), "meetings": meetings, "agenda_items": agenda, "votes": votes,
        "members": members_table(votes, meetings, districts),
    })


def build(base, everything, out_dir, since=FIRST_YEAR, limit=0):
    rows = listed()
    meetings = meetings_table(rows)
    log.info(f"Kern County: {len(meetings)} meetings of the Board listed, {int((meetings['minutes_url'] != '').sum())} with minutes")
    if len(meetings) < 20:
        raise RuntimeError("the listing of meetings came back nearly empty")

    agenda, votes, before_meetings = (council_tables.held(HF_REPO, out_dir, name, base) for name in ("agenda_items", "votes", "meetings"))
    before = 0 if votes is None else len(votes)
    if agenda is None or votes is None or before_meetings is None:
        agenda, votes = pd.DataFrame(columns=AGENDA_COLUMNS), pd.DataFrame(columns=VOTE_COLUMNS)
        before_meetings = pd.DataFrame(columns=MEETING_COLUMNS)
    held = {row["meeting_id"]: {name: row.get(name, empty) for name, empty in FACTS}
            for row in before_meetings[before_meetings["minutes"] != ""].to_dict("records")}
    recent = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    kept = lambda row: (Path(out_dir) / "text" / f"{row['meeting_id']}.txt").exists()
    with_minutes = [row for row in meetings.to_dict("records") if row["minutes_url"] and row["date"] >= f"{since}-01-01"]
    wanted = [row for row in with_minutes if everything or row["date"] >= recent or (not kept(row) and row["meeting_id"] not in held)]
    wanted.sort(key=lambda row: (row["date"], int(row["meeting_id"])), reverse=True)  # the newest first
    waiting = len(wanted)
    wanted = wanted[:limit] if limit else wanted
    log.info(f"Fetching the minutes of {len(wanted)} meetings of {waiting} not yet read or to be read again")

    def written():
        """Everything whose text is here is read, old and new, and the tables are written. That asks nothing of the host."""
        new_agenda, new_votes, found, read, districts = read_all(meetings, out_dir, since)
        facts = {**{meeting_id: facts for meeting_id, facts in held.items() if meeting_id not in found}, **elsewhere, **found}
        tables = tables_of(meetings,
                           joined(agenda[~agenda["meeting_id"].isin(read)], pd.DataFrame(new_agenda, columns=AGENDA_COLUMNS)),
                           joined(votes[~votes["meeting_id"].isin(read)], pd.DataFrame(new_votes, columns=VOTE_COLUMNS)), facts, districts)
        council_tables.write_tables(tables, out_dir)
        return tables

    fetched, refused, started, elsewhere = 0, False, time.time(), {}
    for at, row in enumerate(wanted, 1):
        try:
            _, asked = text_of(row, out_dir, fresh=everything or row["date"] >= recent)
            fetched += asked
        except Refused as e:
            log.error(f"{e}: nothing more is asked of the host in this run")
            refused = True
            break
        except NotPDF as e:
            log.warning(f"Meeting {row['meeting_id']} of {row['date']}: {e}")
            elsewhere[row["meeting_id"]] = {**dict(FACTS), "minutes": f"not read: {e}"}
        except Exception as e:  # one set of minutes that cannot be had or opened does not stop the rest
            log.warning(f"Meeting {row['meeting_id']} of {row['date']}: {type(e).__name__}: {e}")
        if at % EVERY == 0:
            tables = written()
            log.info(f"Kern County: {at} of {len(wanted)} minutes asked for, {fetched} fetched, {len(tables['votes'])} votes held, "
                     f"{round((time.time() - started) / 60)} minutes")
    tables = written()
    if len(tables["votes"]) < before * 0.98:
        raise RuntimeError(f"only {len(tables['votes'])} votes where there were {before}; not publishing")
    return tables, fetched, refused


def card(tables):
    """The dataset card, with the counts of this reading written in."""
    meetings, agenda, votes = tables["meetings"], tables["agenda_items"], tables["votes"]
    read = meetings[meetings["minutes"] == "read"]
    motions, motions_read = int(agenda["motions"].sum()), int(agenda["motions_read"].sum())
    ways = votes["established"].value_counts() if len(votes) else {}
    facts = {
        "repo": HF_REPO, "first_meeting": read["date"].min() if len(read) else "", "last_meeting": read["date"].max() if len(read) else "",
        "first_listed": meetings["date"].min(), "last_listed": meetings["date"].max(),
        "first_vote": votes["date"].min() if len(votes) else "", "last_vote": votes["date"].max() if len(votes) else "",
        "n_with_minutes": f"{int((meetings['minutes_url'] != '').sum()):,}",
        "n_read": f"{len(read):,}", "n_scans": f"{int((meetings['minutes'] == 'no text layer').sum()):,}",
        "n_motions": f"{motions:,}", "n_motions_read": f"{motions_read:,}", "n_unread": f"{motions - motions_read:,}",
        "share_read": f"{100 * motions_read / motions:.1f}" if motions else "0",
        "recent_days": RECENT_DAYS, "serving_days": SERVING_DAYS, "seen_days": SEEN_DAYS,
        **{f"n_{way}": f"{int(ways.get(way, 0)):,}" for way in (NAMED, COUNT, ALL)},
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
        log.error(f"Kern County tables not uploaded: {e}")
        return False
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the Kern County Board's meetings, actions and votes from its minutes")
    parser.add_argument("--base", action="store_true", help="start from the tables written here, not the published ones")
    parser.add_argument("--all", action="store_true", help="fetch every set of minutes again, kept here or not")
    parser.add_argument("--since", type=int, default=FIRST_YEAR, help="read no meeting before this year")
    parser.add_argument("--max", type=int, default=0, help="minutes to fetch in one run (0 for all)")
    parser.add_argument("--out", default="", help="directory to write the tables into (minutes_pdf/kern-county if not given)")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the tables only")

    out_dir = Path(args.out) if args.out else OUT_DIR
    try:
        tables, fetched, refused = build(args.base, args.all, out_dir, args.since, args.max)
    except Exception as e:
        log.error(f"Kern County tables not built: {type(e).__name__}: {e}")
        return 1
    pushed = False if args.no_upload or refused else upload(tables, out_dir, args.write_card)
    meetings, agenda, votes, members = tables["meetings"], tables["agenda_items"], tables["votes"], tables["members"]
    motions, motions_read = int(agenda["motions"].sum()), int(agenda["motions_read"].sum())
    ways = votes["established"].value_counts() if len(votes) else {}
    log.info(f"RESULT: kern-board items={len(tables['items'])} meetings={len(meetings)} "
             f"meetings_with_minutes={int((meetings['minutes_url'] != '').sum())} "
             f"minutes_read={int((meetings['minutes'] == 'read').sum())} "
             f"no_text_layer={int((meetings['minutes'] == 'no text layer').sum())} agenda_items={len(agenda)} "
             f"motions={motions} motions_read={motions_read} motions_unread={motions - motions_read} votes={len(votes)} "
             f"named={int(ways.get(NAMED, 0))} count={int(ways.get(COUNT, 0))} all={int(ways.get(ALL, 0))} "
             f"members={len(members)} serving={int(members['serving'].sum())} minutes_fetched={fetched} "
             f"first_vote={votes['date'].min() if len(votes) else ''} last_vote={votes['date'].max() if len(votes) else ''} "
             f"refused={refused} pushed={pushed}")
    return 0 if (args.no_upload or pushed) and not refused else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
