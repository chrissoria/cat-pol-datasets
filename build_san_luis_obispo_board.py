#!/usr/bin/env python3
"""
Build chrissoria/san-luis-obispo-county-board: the meetings of the San Luis
Obispo County Board of Supervisors, what the Board did at each, and how each
supervisor voted.

Two hosts hold the record, and the County's own page of meetings shows the
first of them:

  slocounty.granicus.com   The archive (ViewPublisher.php?view_id=46) lists
      every meeting since July 2006 in one page, each with its agenda and its
      minutes. Where the minutes are kept changed twice. Until the end of 2011
      they are a web page on Granicus. From 2012 the listing's link is sent on
      to the County's agenda portal. From 2022 it is sent to a PDF on Granicus.

  agenda.slocounty.ca.gov  The agenda portal (a Provox system), from 2012. A
      meeting has a page there with the minutes as a PDF and the agenda's
      items, each with its file number (87/2011) and the portal's own number
      for the item. It also has a page of votes for each item until about
      2021; those are not read (one request an item is too many), but the
      count the meeting's page shows beside an item is kept (`portal_tally`).

Both hosts' robots.txt disallow everything to every reader. The owner of this
project decided on 2026-10-13 that such a blanket file does not bind a named
reader of public records that reads slowly, so these two hosts are read: one
request a second at most, under this project's name. A refusal (401, 403, 429,
a bot check, a login) is not worked around: nothing more is asked of that host
in that run.

Every vote is in the minutes by name, in one of two forms.

  2006 to 2011, the web page:

      Thereafter, on motion of Supervisor Jerry Lenthall, seconded by
      Supervisor Shirley Bianchi, and on the following roll call vote:
      AYES:    Supervisors: Jerry Lenthall, Shirley Bianchi, James R. Patterson, Chairperson K.H. 'Katcho' Achadjian
      NOES:    None
      ABSENT:  Supervisor: Harry L. Ovitt

  2012 on, the PDF: a grid under the motion, a row to a supervisor with an X
  under AYES, NOES, ABSTAIN or RECUSE:

      Motion by: Bruce S. Gibson
      Second by: Adam Hill
      SUPERVISORS                        AYES  NOES  ABSTAIN  RECUSE
      Patterson, James R. (Chairperson)   x
      Mecham, Frank R. (Board Member)           x

  Which word an X stands under is a matter of where it is on the page, so the
  text kept of a PDF has a grid's cells parted by tabs.

Nothing is worked out: a vote row says what the minutes print beside that
name, and `established` is always "named". What is checked is that the names
are the Board. The head of each set of minutes says who was PRESENT and who
ABSENT. A motion is read only if every name in it is one of those, each once,
and every one of them is accounted for: in the vote, or, for a grid (which
leaves out whoever is not in the room), named by the minutes as absent, at
the head, in a sentence above the motion ("Supervisor Compton is now
absent") or in the first words under it ("(SUPERVISOR ADAM HILL IS NOW
PRESENT.)"). Such a supervisor has a row ABSENT. A motion that does not come
out whole puts nothing in `votes`: its line stays in agenda_items with
`votes_read` false and what stopped it in `problem`. A web page whose head
prints no roll (21 of them) takes the roll of the minutes before and after
it, where those agree.

The consent agenda is passed by one motion, printed under "This is the time
set for consideration of the Consent Agenda". That vote is on a line of its
own (`heading` true) and the items it covers point to it. An item taken off
the consent agenda is printed again further down with a motion of its own.
Where the minutes add that a supervisor voted no on one item of the consent
agenda, or abstained ("Supervisor Mecham: votes no on Item No. 20"), that item
has a vote of its own here: the consent agenda's with that supervisor's word
changed. If such words cannot be tied to an item and a supervisor, the consent
motion is not read.

The dataset has the five tables every council's and board's dataset has
(council_tables.py), in data/:
  items.parquet          every item in minutes that were read
  meetings.parquet       one row per meeting the archive lists
  agenda_items.parquet   one row per item in a meeting's minutes, and one per consent agenda voted on
  votes.parquet          one row per supervisor and motion read
  members.parquet        one row per supervisor with votes here
They are kept here in minutes_pdf/san-luis-obispo-county/. Beside them in
text/ are the text of each set of minutes (<meeting>.txt) and where it was
found and what the portal's page lists (<meeting>.json), so nothing is fetched
twice.

Two ways to run it:

    python build_san_luis_obispo_board.py
        The routine run. Starts from the published tables, lists every meeting
        again, and fetches the meetings not read before and those of the last
        90 days (minutes are posted after the meeting, first as a draft).

    python build_san_luis_obispo_board.py --base
        The same, starting from the tables written here. It fetches the newest
        meeting first, writes the tables every hundred meetings, and can be
        stopped and started again. Meetings kept here are read again on every
        run; that takes no request.

    --since YEAR  read no meeting before this year (default 2006, where the archive begins)
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
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pandas as pd
import requests

import build_federal_bills as bills
import build_sd_county as county
import council_tables
from build_sd_county import clean, today

log = logging.getLogger(__name__)

HF_REPO = "chrissoria/san-luis-obispo-county-board"
OUT_DIR = bills.SCRIPT_DIR / "minutes_pdf" / "san-luis-obispo-county"
CARD_FILE = bills.SCRIPT_DIR / "README_san_luis_obispo_board.md"
TABLES = council_tables.TABLES
BODY = "Board of Supervisors"

GRANICUS = "https://slocounty.granicus.com"
VIEW = 46  # the Board's archive on Granicus
PORTAL = "https://agenda.slocounty.ca.gov/IIP/sanluisobispo"
PORTAL_HOST = "agenda.slocounty.ca.gov"
FIRST_YEAR = 2006  # the archive's first meeting is of July 2006
PORTAL_FROM = 2012  # the portal's first meeting is of January 2012
RECENT_DAYS = 90  # meetings this recent are fetched again
SERVING_DAYS = 120  # a supervisor whose last vote is this recent is serving
PAUSE = 1.0  # seconds after each request: one request a second at most
WRITE_EVERY = 100  # meetings fetched between two writings of the tables
LAYER_CHARS = 200  # minutes with fewer characters of their own than this are a scan
SMALLEST = 4  # type smaller than this is not on the page to be read
INDENT = 6  # points to one space of a line's distance in from the margin
SEATS = 5  # a county's board of supervisors (Government Code 25000)
LENT_DAYS = 60  # minutes with no roll at their head take that of minutes no further off than this, before and after

MEETING_COLUMNS = council_tables.COLUMNS["meetings"] + [
    "name", "note", "video_url", "document_url", "portal_id", "format", "minutes", "pages", "present", "roll", "motions", "motions_read"]
AGENDA_COLUMNS = council_tables.COLUMNS["agenda_items"] + [
    "heading", "section", "section_id", "motions", "motions_read", "votes_read", "problem", "doc_type", "number", "portal_tally",
    "motion_log"]
VOTE_COLUMNS = council_tables.COLUMNS["votes"] + ["motion", "motion_text", "established"]
ITEM_COLUMNS = council_tables.COLUMNS["items"] + ["item_id", "meeting_id", "section", "action_on", "votes_read", "number"]

NAMED = "named"  # how every vote here is known: the minutes print the supervisor's name with it

# The minutes' words over a column or a list of names, and the word the tables have for each.
WORDS = {"AYES": council_tables.AYE, "AYE": council_tables.AYE, "YES": council_tables.AYE,
         "NOES": council_tables.NO, "NOE": council_tables.NO, "NO": council_tables.NO, "NAYS": council_tables.NO,
         "ABSENT": "ABSENT", "ABSTAIN": "ABSTAIN", "ABSTAINED": "ABSTAIN", "ABSTAINING": "ABSTAIN",
         "RECUSE": "RECUSED", "RECUSED": "RECUSED", "NOT PARTICIPATING": "NOT PARTICIPATING"}
NOBODY = ("", "none", "none.", "n/a", "na", "0", "-")

_LABEL = r"(?:AYES?|YES|NOES?|NO|NAYS|ABSTAIN(?:ED|ING)?|RECUSED?|ABSENT|NOT\s+PARTICIPATING)"
_COLUMN = re.compile(rf"^{_LABEL}\s*:?$", re.I)
_LIST = re.compile(rf"^({_LABEL})\s*:\s*(.*)$")
_PAGE_HEAD = re.compile(r"^Board\s+of\s+Supervisors\b.{0,20}?\b(?:Page\s+)?\d+\s+of\s+\d+$", re.I)
_OFFICE = r"(?:Vice[- ]?Chair(?:person|man|woman)?|Chair(?:person|man|woman)?|Board\s+Members?|Supervisors?)"
_PRESENT = re.compile(r"^PRESENT\s*:\s*(.*)$")
_ABSENT = re.compile(r"^ABSENT\s*:\s*(.*)$")
_HOUR = re.compile(r"\bmet\s+in\s+(?P<kind>[a-z ]+?)\s+session\s+at\s+(?P<hour>\d{1,2}:\d{2}\s*[AaPp]\.?\s*[Mm]\.?)")
_MOVER = re.compile(r"^Motion\s+by\s*:\s*(.*)$", re.I)
_SECONDER = re.compile(r"^Second(?:ed)?\s+by\s*:\s*(.*)$", re.I)
_ON_MOTION = re.compile(r"\bon\s+motion\s+of\s+Supervisor\s*(?P<mover>.*?),\s*seconded\s+by\s+Supervisor\s*(?P<seconder>.*?),?\s*and\s+on\s+the\s+"
                        r"following\s+roll\s+call\s+vote", re.I)
# What an item is called where it begins: "1.", "12", "01", and for the consent agenda "1-27.", "1–36, 46", "02-36 &".
_ITEM = re.compile(r"^(?P<label>\d{1,3}(?:\.?\s*(?:[-–—,&]|and|through)\s*\d{0,3})*)(?P<dot>\.)?(?:\s+(?P<rest>[A-Z(\"“‘'].*)|\s*)$")
_GRID_NAME = re.compile(rf"^[A-Z][A-Za-z.'’ ,-]+\((?:{_OFFICE})")
# "This is the time set for consideration of the Consent Agenda", and the clerks' other ways of saying it: "the set
# time for", "set of consideration", "time set for the Consent Agenda", "Consideration of the Consent Agenda".
_CONSENT = re.compile(r"\b(?:time\s+(?:set\s+)?|set\s+time\s+)(?:for|of)\s+(?:the\s+)?(?:consideration\s+(?:of|for)\s+)?(?:the\s+)?(?:remaining\s+)?Consent\s+Agenda\b"
                      r"|\bconsideration\s+(?:of|for)\s+(?:the\s+)?(?:remaining\s+)?Consent\s+Agenda\b", re.I)
_CONSENT_RANGE = re.compile(r"\bconsideration\s+(?:of|for)\s+the\s+agenda\b", re.I)  # with "1-17" before it: the consent agenda, miscalled
_COVERED = re.compile(r"Consent\s+Agenda(?:\s*[-–—]\s*[A-Za-z ]{0,40}?)?\s+Items?\b(.*?)(?:\bon\s+the\s+following\s+vote\b|\bis\s+indicated\b|\bare\s+indicated\b|\bare\s+approved\b|$)", re.I | re.S)
_FAILS = re.compile(r"\bmotion\b[^.;]{0,40}\bfail(?:s|ed)\b", re.I)
_FAILED = re.compile(r"^(?:The\s+)?(?:tentative\s+)?motion\b[^.;]{0,30}\bfail(?:s|ed)\b", re.I)  # a paragraph that says nothing else first
# What the minutes put under a consent item that the consent motion did not pass.
_TAKEN_OFF = re.compile(r"\b(?:pulls?\s+this\s+item|pulled\s+for\s+separate|is\s+withdrawn|was\s+withdrawn|withdraws?\s+this\s+item"
                        r"|(?:is|was)\s+continued\s+to|continues?\s+this\s+item|is\s+removed\s+from\s+the|no\s+action\s+(?:is\s+)?taken)\b", re.I)
_DONE = re.compile(r"^(?:(?:TENTATIVE\s+)?MOTION\s*:|The\s+Board\b|The\s+actions?\s+taken\b|RESOLUTION\s+NOS?\b|ORDINANCE\s+NOS?\b|This\s+item\s+is\b|No\s+action\b)", re.I)
_NUMBER = re.compile(r"\b(RESOLUTION|ORDINANCE)\s+(?:NOS?\.?|NUMBERS?)\s*(\d{4}\s?-\s?\d{1,4}|\d{3,5})", re.I)
_NAMES = r"[A-Z][A-Za-z.'’-]*(?:\s+[A-Z][A-Za-z.'’-]*){0,3}(?:(?:\s*,\s*|\s+and\s+|\s*,\s*and\s+)[A-Z][A-Za-z.'’-]*(?:\s+[A-Z][A-Za-z.'’-]*){0,3})*"
_DID = r"vot(?:es|ed|ing)\s+(?:no|nay|against)|abstain\w*|recus\w*"
_ITEMS = r"(?:[A-Z]{1,2}-)?\d{1,3}(?:-?[A-Za-z])?(?:\s*(?:,|,?\s*and|&)\s*(?:[A-Z]{1,2}-)?\d{1,3}(?:-?[A-Za-z])?)*"
# "Supervisor Mecham: votes no on Item No. 20", "Supervisor Hill: states he will be abstaining from voting on Item
# Nos. 38 and 39", "(SUPERVISOR GIBSON VOTED NO ON ITEM A-18-F)": a supervisor, what they did, the items.
# Between the name and what was done: "states she will need to", "opens the floor to public comment. Additionally,
# states he will be". No colon, so no one else has begun to speak, and no other supervisor.
_BETWEEN = r"(?:(?!Supervisor|Chairperson)[^:()]){0,120}?"
_ASIDE = re.compile(rf"(?i:Supervisors?|Vice[- ]?Chairpersons?|Chairpersons?)\s+(?P<who>{_NAMES})\s*:?\s*(?i:{_BETWEEN}\b"
                    rf"(?P<did>{_DID})[^.;()]{{0,60}}?\bItems?\s*(?:Nos?\.?|Numbers?|#)?\s*)(?P<items>{_ITEMS})", re.S)
# "Item A-18-G is approved ... (with Supervisor Gibson abstaining)": the item, then the supervisor.
_ASIDE_AFTER = re.compile(rf"(?i:Items?\s*(?:Nos?\.?)?\s*)(?P<items>(?:[A-Z]{{1,2}}-)?\d{{1,3}}(?:-?[A-Za-z])?)\s+(?i:is|was)\s[^.()]{{0,300}}?\((?i:with\s+Supervisor)\s+"
                          rf"(?P<who>{_NAMES})\s+(?i:(?P<did>abstaining|voting\s+no|recus\w+))\)", re.S)
# Under an item of the consent agenda: "Supervisor Hill: abstains from voting on this item."
_ON_THIS = re.compile(rf"(?i:Supervisors?|Vice[- ]?Chairpersons?|Chairpersons?)\s+(?P<who>{_NAMES})\s*:?\s*(?i:{_BETWEEN}\b(?P<did>{_DID})"
                      rf"[^.;()]{{0,40}}?\bon\s+this\s+item)", re.S)
_OF_A_VOTE = re.compile(rf"\b(?:{_DID}|dissent\w*)\b", re.I)
# "Supervisor Compton is now present.", "Supervisors Compton: states she is recusing herself ... and is now absent.",
# "CHAIRPERSON PAULDING STEPS DOWN AND IS NOW ABSENT."
_NOW = re.compile(r"\b(?:is|are)\s+now\s+(absent|present)\b", re.I)
_OFFICED = re.compile(r"\b(?:Sup[a-z]{3,10}rs?|Vice[- ]?Chair(?:person|man|woman)?s?|Chair(?:person|man|woman)?s?)\b", re.I)  # "SUPERVISIOR" too
UNSURE = "?"  # in the list of who is away: the minutes said someone came or went, and who could not be read


class Refused(Exception):
    """The host answered with a check, a login or a refusal. It is not asked again in this run."""


REFUSED = set()  # hosts that have answered so
_session = requests.Session()
_CHECK = re.compile(r"captcha|cf-challenge|cf-chl|are you a human|access denied|you have been blocked|sign in to continue", re.I)


def fetch(url, tries=3):
    """One answer from one of the two hosts, with a pause after it. A redirect is not followed: where it leads is for
    the caller to look at. A refusal is not tried again, and nothing more is asked of that host in this run."""
    host = urlsplit(url).netloc
    if host not in (urlsplit(GRANICUS).netloc, PORTAL_HOST):
        raise ValueError(f"{host} is not one of the County's two hosts")
    for attempt in range(tries):
        if host in REFUSED:
            raise Refused(f"{host} refused an earlier request")
        try:
            answer = _session.get(url, headers=county.HEADERS, timeout=(20, 180), allow_redirects=False)
            time.sleep(PAUSE)
            page = "html" in answer.headers.get("content-type", "") and answer.content[:4] != b"%PDF"
            if answer.status_code in (401, 403, 429) or (page and answer.status_code == 200 and _CHECK.search(answer.text[:3000])):
                REFUSED.add(host)
                raise Refused(f"{answer.status_code} from {url.split('?')[0]}")
            if answer.status_code >= 400:
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

_MONTHS = {name: number for number, name in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
_ROW = re.compile(r"(?i)<tr\b")
_CELL = re.compile(r"(?is)<td\b[^>]*>(.*?)</td>")
_VIEWER = re.compile(r'(?is)(?:href|value)="([^"]*MinutesViewer\.php[^"]*)"[^>]*>(.*?)<')
_NOT_MINUTES = re.compile(r"(?i)^(?:item|agenda)\b")  # "Item Documents" is the agenda with its staff reports
_ADDENDUM = re.compile(r"(?i)^addend")  # a change to an agenda, listed as a row of its own: it has no minutes


def plain(markup):
    """A piece of a page as its words."""
    return clean(html.unescape(re.sub(r"<[^>]+>", " ", str(markup or ""))).replace("\xa0", " "))


def absolute(link, host=GRANICUS):
    link = html.unescape(link)
    return "https:" + link if link.startswith("//") else link if link.startswith("http") else f"{host}/{link.lstrip('/')}"


def date_of(text):
    """"Aug 8, 2006" as "2006-08-08"."""
    found = re.search(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),\s+(\d{4})", text)
    return f"{found[3]}-{_MONTHS[found[1].lower()]:02d}-{int(found[2]):02d}" if found and found[1].lower() in _MONTHS else ""


def clock(hour):
    """An hour as every board's table has it: "9:00 AM"."""
    found = re.search(r"(\d{1,2}):(\d{2})\s*([AaPp])\.?\s*[Mm]\.?", clean(hour))
    return f"{int(found[1])}:{found[2]} {found[3].upper()}M" if found else ""


def rows_of(page):
    """The Board's meetings on the archive's page, known by the number Granicus gives each recording.

    A row's documents are "Item Documents" (the agenda) and the minutes, which the clerks have labelled "Minutes",
    "Generated HTML" or with the day ("12-16-08 BOS"): the minutes are the document that is not the first kind.
    A row for an addendum to an agenda is not a meeting.
    """
    rows, seen = [], set()
    for row in _ROW.split(page):
        clip = re.search(r"clip_id=(\d+)", row)
        cells = _CELL.findall(row)
        if not clip or len(cells) < 2 or clip[1] in seen or 'headers="Name"' not in row:
            continue  # a heading of the listing, or a meeting to come with nothing filed yet
        name, day = plain(cells[0]), date_of(plain(cells[1]))
        if not day or _ADDENDUM.match(name):
            continue
        seen.add(clip[1])
        documents = [(plain(label), absolute(link)) for link, label in _VIEWER.findall(row)]
        minutes = [link for label, link in documents if label.lower().startswith("minute")] or \
                  [link for label, link in documents if not _NOT_MINUTES.match(label)]
        agenda = re.search(r'href="([^"]*AgendaViewer\.php[^"]*)"', row)
        rows.append({"meeting_id": clip[1], "date": day, "name": name,
                     "agenda": absolute(agenda[1]) if agenda else "", "minutes": minutes[0] if minutes else "",
                     "video": f"{GRANICUS}/MediaPlayer.php?view_id={VIEW}&clip_id={clip[1]}" if "MediaPlayer.php" in row else ""})
    return rows


def listed():
    """Every meeting the archive lists: one request."""
    return rows_of(fetch(f"{GRANICUS}/ViewPublisher.php?view_id={VIEW}").text)


def meetings_table(rows):
    """One row per meeting listed. What its minutes add is filled in by read_all()."""
    out = [{
        "meeting_id": row["meeting_id"], "date": row["date"], "time": "", "body": BODY, "location": "",
        "url": row["video"] or f"{GRANICUS}/ViewPublisher.php?view_id={VIEW}", "agenda_url": row["agenda"], "minutes_url": row["minutes"],
        "items": 0, "name": row["name"], "note": "", "video_url": row["video"], "document_url": "", "portal_id": "", "format": "",
        "minutes": "", "pages": 0, "present": "", "roll": "", "motions": 0, "motions_read": 0,
    } for row in rows]
    table = pd.DataFrame(out, columns=MEETING_COLUMNS)
    return table.sort_values(["date", "meeting_id"], key=lambda column: column if column.name == "date" else column.astype(int)
                             ).reset_index(drop=True)


# ---------------------------------------------------------------------------
# The portal
# ---------------------------------------------------------------------------

_FILES = re.compile(r"Meeting files:(.*?)</div>", re.S)
_FILE_LINK = re.compile(r'<a\b[^>]*aria-label="([^"]+)"[^>]*href="([^"]+)"', re.S)
_TOPIC = re.compile(r'<div class="topic">')
_TOPIC_NAME = re.compile(r"<strong>(.*?)</strong>", re.S)
_LINE = re.compile(r'<div class="meetingitem\b')
_LINE_NUMBER = re.compile(r'class="agendanumber">(.*?)</div>', re.S)
_LINE_TITLE = re.compile(r'<div style="width:70%;[^"]*">(.*?)</div>', re.S)
_LINE_ITEM = re.compile(r"agendaitem/details/(\d+)", re.I)
_LINE_FILE = re.compile(r'id="agendaitemnumber"[^>]*>\s*(?:Agenda\s+)?([^<]*?)\s*<', re.S)
_LINE_TALLY = re.compile(r"Voted for:\s*(\d+).{0,12}?Voted against:\s*(\d+).{0,12}?Did not vote:\s*(\d+)", re.S)
_OLD_MINUTES = re.compile(r"/agenda/sanluisobispo/(\d+)/[^/]+/\d+/n/(\d+)\.docx?$", re.I)  # where the archive sent a reader until about 2019
_GETFILE = re.compile(r"/iip/sanluisobispo/file/getfile/(\d+)", re.I)


def events_of(events):
    """{day: [the portal's numbers for the Board's meetings of that day]} from the portal calendar's answer. The
    calendar has other bodies' meetings too, and a row for each addendum to an agenda; neither is one of these."""
    days = {}
    for event in events:
        day = str(event.get("start") or "")[:10]
        if re.search(r"^by:\s*Board of Supervisors\s*$", str(event.get("description") or ""), re.M) and event.get("id") is not None:
            days.setdefault(day, []).append(str(event["id"]))
    return days


def calendar():
    """The portal's calendar, from its first year to the end of next year: one request."""
    last = datetime.now(timezone.utc).year + 1
    answer = fetch(f"{PORTAL}/meeting/ShowEvents?start={PORTAL_FROM}-01-01T00:00:00-08:00&end={last}-12-31T00:00:00-08:00")
    return events_of(json.loads(answer.text))


def file_number(text):
    """A file number as the portal has it, "87/2011"; "" if it is not one."""
    found = re.fullmatch(r"(\d{1,4})\s?/\s?(\d{4})", clean(text))
    return f"{int(found[1])}/{found[2]}" if found else ""


def page_of(markup):
    """What the portal's page of a meeting says: the documents it links and the agenda's lines.

    A line has its place on the agenda, its words, its file number and the portal's number for the item. The page
    prints the lines twice where there are minutes, once as the agenda and once as the minutes, the second time with
    the count of the vote beside the item ("Voted for: 5 / Voted against: 0 / Did not vote: 0").
    """
    if "Meeting files:" not in markup:
        return {"found": False, "files": {}, "lines": []}
    files = {}
    for label, link in _FILE_LINK.findall((_FILES.search(markup) or ["", ""])[1]):
        label = label.lower()
        kind = ("minutes" if label == "minutes" else "private minutes" if "minutes" in label else
                "agenda" if label == "invitation" else "private agenda" if "invitation" in label else "")
        if kind and "/file/getfile/" in link.lower():
            files.setdefault(kind, absolute(link, f"https://{PORTAL_HOST}"))
    start, end = markup.find('id="agenda"'), markup.find('id="minutes"')
    parts = (markup[start:end if end > start else len(markup)] if start >= 0 else "", markup[end:] if end >= 0 else "")
    lines, tallies = [], {}
    for part, is_minutes in zip(parts, (False, True)):
        for topic in _TOPIC.split(part)[1:]:
            name = plain((_TOPIC_NAME.search(topic) or ["", ""])[1]).rstrip(":")
            for piece in _LINE.split(topic)[1:]:
                of = lambda pattern: (pattern.search(piece) or ["", ""])[1]
                item, tally = of(_LINE_ITEM), _LINE_TALLY.search(html.unescape(piece))
                if is_minutes:
                    if item and tally:
                        tallies[item] = "-".join(tally.groups())
                    continue
                lines.append({"section": name, "number": plain(of(_LINE_NUMBER)), "title": plain(of(_LINE_TITLE)),
                              "file": file_number(plain(of(_LINE_FILE))), "item": item, "tally": ""})
    for line in lines:
        line["tally"] = tallies.get(line["item"], "")
    return {"found": True, "files": files, "lines": lines}


# ---------------------------------------------------------------------------
# The text of a set of minutes
# ---------------------------------------------------------------------------

def pdf_text(body):
    """The text a PDF carries, a page at a time. Nothing is read off the picture of a page.

    Three things about where words stand are kept, since the minutes say with them what the words do not. A line is
    set in by one space for every INDENT points it stands in from the margin. An empty line marks a gap the page
    leaves between two paragraphs. And a grid of votes has its cells parted by tabs: the line of column heads
    ("SUPERVISORS<tab>AYES<tab>NOES<tab>ABSTAIN<tab>RECUSE") and under it each line with an X on it, the X in the cell
    of the column head it stands nearest under, with any words that follow it on the line ("X (Item 27 Only)"). An X
    that stands under no column is kept as "?".
    """
    import pdfplumber
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    pages = []
    with pdfplumber.open(io.BytesIO(body)) as document:
        for page in document.pages:
            words = [word for word in page.extract_words(extra_attrs=["size"]) if (word.get("size") or 12) >= SMALLEST]
            rows = []
            for word in sorted(words, key=lambda word: (round(word["top"]), word["x0"])):
                if rows and abs(rows[-1][0]["top"] - word["top"]) <= 3:
                    rows[-1].append(word)
                else:
                    rows.append([word])
            pages.append([sorted(row, key=lambda word: word["x0"]) for row in rows])
    # The margin is the leftmost place lines begin at, leaving out a stray line or two that stands further left.
    begun = Counter(round(row[0]["x0"]) for rows in pages for row in rows)
    enough = max(3, 0.02 * sum(begun.values()))
    margin = min((x for x, count in begun.items() if count >= enough), default=min(begun, default=0))
    out, columns = [], None
    kind = lambda word: word["text"].rstrip(":").upper()[:3].replace("YES", "AYE").replace("NO", "NOE")[:3]
    for rows in pages:
        text, foot, skip = [], None, set()
        for index, row in enumerate(rows):
            if index in skip:
                continue
            if foot is not None and row[0]["top"] - foot > 0.6 * (row[0]["bottom"] - row[0]["top"]):
                text.append("")
            foot = max(word["bottom"] for word in row)
            lead = " " * max(0, round((row[0]["x0"] - margin) / INDENT))
            words = " ".join(word["text"] for word in row)
            heads = []
            for word in reversed(row):  # the column heads are the words a line ends with
                if not _COLUMN.match(word["text"]):
                    break
                heads.insert(0, word)
            if len(heads) >= 2 and heads[0]["text"][0].upper() in "AY":
                first = " ".join(word["text"] for word in row[:len(row) - len(heads)])
                # A column head too long for its cell ("ABSTAIN:") stands half a line above the others, its colon
                # half a line below: both are of this line.
                above = rows[index - 1] if index else []
                below = rows[index + 1] if index + 1 < len(rows) else []
                if above and all(_COLUMN.match(word["text"]) for word in above) and text and text[-1].strip() == " ".join(word["text"] for word in above):
                    heads, _ = heads + above, text.pop()
                if below and all(word["text"] == ":" or _COLUMN.match(word["text"]) for word in below):
                    heads = heads + [word for word in below if word["text"] != ":"]
                    skip.add(index + 1)
                heads.sort(key=lambda word: word["x0"])
                kinds = [kind(word) for word in heads]
                if len(heads) >= 4 and len(set(kinds)) == len(kinds) and {"AYE", "NOE"} <= set(kinds):
                    columns = [word["x0"] for word in heads]
                    text.append(lead + "\t".join([first] + [word["text"] for word in heads]))
                    continue
                columns = None  # heads that are not a whole row of them: nothing under them can be placed
            if columns and not _PAGE_HEAD.match(words):
                half = min(right - left for left, right in zip(columns, columns[1:])) / 2
                first = next((at for at, word in enumerate(row) if word["text"] in ("X", "x") and word["x0"] > columns[0] - half), None)
                rest = row if first is None else row[:first]
                in_name_column = all(word["x1"] < columns[0] + half for word in rest)
                if first is not None and in_name_column:
                    # What follows an X on its line is a note on it: "X (Item 27 Only)" stays in that X's cell.
                    cells, at = [""] * len(columns), 0
                    for word in row[first:]:
                        if word["text"] in ("X", "x"):
                            at = min(range(len(columns)), key=lambda index: abs(columns[index] - word["x0"]))
                            cells[at] = (cells[at] + " " + (word["text"] if abs(columns[at] - word["x0"]) < half else "?")).strip()
                        else:
                            cells[at] += " " + word["text"]
                    text.append(lead + "\t".join([" ".join(word["text"] for word in rest)] + cells))
                    continue
                if not (in_name_column and ("(" in words or ")" in words)):
                    columns = None  # the grid is over
            text.append(lead + words)
        out.append("\n".join(text))
    return out


_SCRIPT = re.compile(r"(?is)<(script|style)\b.*?</\1\s*>|<!--.*?-->")
_TIME = re.compile(r"(?is)<span[^>]*COLOR:\s*red[^>]*>\s*\(\d{1,2}:\d{2}\s*[AP]M\)\s*</span>")
_IN_CELL = r"((?:(?!</t[dr]>).)*)"  # what a cell holds, and nothing of the next
_ITEM_ROW = re.compile(rf"(?is)<tr\s+vAlign=top\s+align=left>\s*<td\s+width=40>{_IN_CELL}</td>\s*<td\s+width=40>{_IN_CELL}</td>\s*"
                       r"<td\b[^>]*>((?:(?!</tr>).)*?)</td>\s*</tr>")
_LIST_ROW = re.compile(r"(?is)<tr>\s*<td\b[^>]*>\s*<div>\s*<strong>\s*([A-Za-z ]{2,20}):\s*</strong>\s*</div>\s*</td>\s*<td\b[^>]*>((?:(?!</tr>).)*?)</td>\s*</tr>")
_BREAK = re.compile(r"(?i)<(?:br|/?p|/?div|/?tr|/?td|/?li|/?table|/?blockquote|/?h\d|/?title)\b[^>]*>")
ITEM_MARK = "§"  # what a line of the kept text of a web page opens with where it is a line of the agenda


def page_text(markup):
    """The minutes Granicus keeps as a web page, as lines of text.

    The page is a run of small tables. A line of the agenda is a row of three cells: its place in the meeting, its
    number on the agenda (A-12), and its words; it is kept as "§<tab>place<tab>number<tab>words", and a heading
    between items is such a line with neither number. A row that is a label and what it labels ("AYES:" and the
    names) is kept as one line, a tab between the two. The hour printed in red after a title is left out.
    """
    markup = _TIME.sub(" ", _SCRIPT.sub(" ", markup))
    markup = _ITEM_ROW.sub(lambda row: f"<br>{ITEM_MARK}\t{plain(row[1])}\t{plain(row[2])}\t{plain(row[3])}<br>", markup)
    markup = _LIST_ROW.sub(lambda row: f"<br>{plain(row[1]).upper()}:\t{plain(row[2])}<br>", markup)
    lines = []
    for line in _BREAK.sub("\n", markup).split("\n"):
        line = "\t".join(plain(cell) for cell in line.split("\t")) if "\t" in line else plain(line)
        if line.strip():
            lines.append(line)
    return "\n".join(lines)


def lines_of(text):
    """The kept text's lines in order, each with how far in it begins, its cells where it has tabs, whether a gap
    stands above it, whether it is the first of its page (where a gap cannot be seen), and how far in the leftmost
    line of its page begins (`floor`). The line at the head of each page ("Board of Supervisors Page 3 of 9") is left
    out."""
    out = []
    for page in text.split("\f"):
        gap, top, begun = False, True, len(out)
        for raw in page.split("\n"):
            if not raw.strip():
                gap = True
                continue
            if _PAGE_HEAD.match(clean(raw)):
                continue
            cells = [clean(cell) for cell in raw.split("\t")] if "\t" in raw else None
            out.append({"indent": len(raw) - len(raw.lstrip(" ")), "text": clean(raw.replace("\t", " ")), "cells": cells,
                        "gap": gap and not top, "top": top})
            gap, top = False, False
        floor = min((line["indent"] for line in out[begun:]), default=0)
        for line in out[begun:]:
            line["floor"] = floor
    return out


# ---------------------------------------------------------------------------
# Who a name is
# ---------------------------------------------------------------------------

def shown(name):
    """A supervisor's name as the tables have it, from any way the minutes print it: "Gibson, Bruce S (Board Member)",
    "BRUCE S. GIBSON", "Chairperson Bruce S. Gibson" are all "Bruce S. Gibson"."""
    name = clean(re.sub(r"\([^)]*\)?", " ", str(name or ""))).strip(" .,;:")
    name = re.sub(r"(?<=[a-z])-\s+(?=[A-Z])", "-", name)  # "Ortiz- Legg", where the line broke
    name = re.sub(rf"^(?:(?:{_OFFICE})\s*:?\s+)+", "", name, flags=re.I)
    if "," in name:
        last, _, first = name.partition(",")
        name = clean(f"{first} {last}")
    if name.isupper():
        name = name.title()
    return clean(re.sub(r"\b([A-Z])(?=\s|$)", r"\1.", name)).replace("\\", "").strip(" ,;:")


def key_of(name):
    """What two printings of a supervisor's name share: the letters of the surname. That is the name's last word,
    or the last that is not an initial ("Frank Mecham R.", as one summer's grids have it)."""
    words = [word for word in shown(name).split() if not re.fullmatch(r"[A-Z]\.?", word)] or shown(name).split()
    return re.sub(r"[^a-z]", "", words[-1].lower()) if words else ""


def role_of(name):
    """The office the minutes print with a name: "Chairperson", "Vice-Chairperson" or ""."""
    found = re.search(r"\b(Vice)?[- ]?Chair(?:person|man|woman)?\b", str(name or ""), re.I)
    return "" if not found else "Vice-Chairperson" if found[1] else "Chairperson"


def district_of(name):
    found = re.search(r"\bDistrict\s+(\d)\b", str(name or ""))
    return int(found[1]) if found else None


def names_in(text):
    """The names in "Supervisors: Bruce S. Gibson, Adam Hill, and Chairperson Frank Mecham", as printed; none for
    "None". A piece left empty ("Supervisors: , , Shirley Bianchi") is not a name and is left out."""
    text = clean(re.sub(r"^\s*Supervisors?\s*:", " ", clean(text), flags=re.I)).strip(" .;:,")
    if text.lower() in NOBODY:
        return []
    return [clean(part) for part in re.split(r"\s*[,;]\s*(?:and\s+)?|\s+and\s+|\s+and$", text) if shown(part) and shown(part).lower() not in NOBODY]


def near(one, other):
    """Whether two surnames are one name misspelled: a letter more, less or changed, or two letters changed round
    ("ANROLD"). Only for names long enough that this cannot make one supervisor of two."""
    if min(len(one), len(other)) < 5 or abs(len(one) - len(other)) > 1:
        return False
    if len(one) == len(other):
        differ = [at for at, (a, b) in enumerate(zip(one, other)) if a != b]
        return len(differ) <= 1 or (len(differ) == 2 and differ[1] == differ[0] + 1 and one[differ[0]] == other[differ[1]] and one[differ[1]] == other[differ[0]])
    short, long = sorted((one, other), key=len)
    return any(long[:at] + long[at + 1:] == short for at in range(len(long)))


def who(name, roll):
    """The supervisor on the roll that a printed name is, or None: the one with that surname, if there is one only.
    Failing that, the one whose surname is that name misspelled ("Anrold" at the head of a set of minutes), if there
    is one only."""
    key = key_of(name)
    found = [member for member in roll if key_of(member) == key] if key else []
    if not found and key:
        found = [member for member in roll if near(key, key_of(member))]
    return found[0] if len(found) == 1 else None


# ---------------------------------------------------------------------------
# Reading a set of minutes
# ---------------------------------------------------------------------------

def parted_names(names, known):
    """The names of a head, with two that the Clerk ran together parted: "Lynn Compton Debbie Arnold" (a comma left
    out, in some minutes of 2022) is two supervisors where each half is a name other minutes print. `known` is those
    names."""
    out = []
    for name in names:
        words = name.split()
        cut = next((at for at in range(2, len(words) - 1) if shown(" ".join(words[:at])) in known and shown(" ".join(words[at:])) in known), None)
        out.extend([name] if cut is None or shown(name) in known else [" ".join(words[:cut]), " ".join(words[cut:])])
    return out


def head_of(lines, known=()):
    """What the head of the minutes says: who was present and who absent (as printed), the hour, the kind of session,
    the offices it names, and the line the minutes proper begin at."""
    present, absent, said, begins, hour, kind = [], [], [], 0, "", ""
    for at, line in enumerate(lines[:40]):
        met = _HOUR.search(line["text"])
        if met and not hour:
            hour, kind = clock(met["hour"]), clean(met["kind"])
        if _PRESENT.match(line["text"]):
            block, at, one_line = [_PRESENT.match(line["text"])[1]], at + 1, bool(line["cells"])  # a web page's row is whole
            while not one_line and at < len(lines) and not _ABSENT.match(lines[at]["text"]) and not lines[at]["gap"] and len(block) < 4:
                block.append(lines[at]["text"])
                at += 1
            present = parted_names(names_in(" ".join(block)), known)
            said.append("PRESENT: " + clean(" ".join(block)))
            while at < len(lines) and at < 40 and not _ABSENT.match(lines[at]["text"]):
                at += 1
            if at < len(lines) and _ABSENT.match(lines[at]["text"]):
                block, at, one_line = [_ABSENT.match(lines[at]["text"])[1]], at + 1, bool(lines[at]["cells"])
                while not one_line and at < len(lines) and not lines[at]["gap"] and len(block) < 3 and not lines[at]["text"].isupper() \
                        and not lines[at]["text"].startswith(ITEM_MARK):
                    block.append(lines[at]["text"])
                    at += 1
                absent = parted_names(names_in(" ".join(block)), known)
                said.append("ABSENT: " + clean(" ".join(block)))
            begins = at
            break
    roles = {key_of(name): role_of(name) for name in present + absent if role_of(name)}
    seen, roll = set(), []
    for name in present + absent:  # a name the head prints twice is one supervisor
        if key_of(name) not in seen:
            seen.add(key_of(name))
            roll.append(shown(name))
    away = [shown(name) for name in absent if key_of(name) not in {key_of(one) for one in present}]
    return {"roll": roll, "absent": away, "present": "; ".join(said), "hour": hour, "session": kind, "roles": roles, "begins": begins}


def covered(text):
    """The items a consent motion covers, as the numbers in "items 1 through 9, 11 through 18 and 22 through 39" or in
    the agenda's own "1–36, 46"."""
    numbers = set()
    text = re.sub(r"(\d+)\.?\s*,?\s*(?:through|thru|to|[-–—])\s*(\d+)",
                  lambda found: " ".join(str(number) for number in range(int(found[1]), int(found[2]) + 1)) if int(found[2]) - int(found[1]) < 200 else " ",
                  text)
    numbers.update(int(number) for number in re.findall(r"\b\d{1,3}\b", text))
    return numbers


def new_entry(kind, number="", label="", title="", section=""):
    return {"kind": kind, "number": number, "label": label, "title": title, "section": section, "paragraphs": [], "motions": [],
            "consent": False, "covers": None, "under": None}


def new_motion(text, mover="", seconder=""):
    return {"text": clean(re.sub(r"^(?:TENTATIVE\s+)?MOTION\s*:\s*", "", clean(text), flags=re.I)), "mover": clean(mover), "seconder": clean(seconder),
            "kind": "", "rows": [], "notes": [], "problem": "", "away": [], "after": "", "failed": bool(_FAILS.search(text))}


def moved_text(entry):
    """The words of a motion that is about to be printed under an item: the last paragraph above it that says what
    the Board did ("MOTION: The Board approves ...", "RESOLUTION NO. 2012-175, ... adopted."), looking no further up
    than the motion before; failing that the paragraph just above; failing that the item's title."""
    since = entry.get("since", 0)
    above = entry["paragraphs"][since:]
    entry["since"] = len(entry["paragraphs"])
    done = [paragraph for paragraph in above if _DONE.match(paragraph)]
    return done[-1] if done else above[-1] if above else entry["title"]


def grid_at(lines, at):
    """The grid whose line of column heads is line `at`, as ([(name as printed, the column's word)], [(name, the
    column's word, a note beside that X)], what is wrong with it or "", the next line).

    As a rule a line of the grid is a name and its X, and the X is that name's: one X to a name, or the grid is not
    read. But a name too long for its cell runs on to a second line, and its X then stands between the two, so the
    Xs below it are no longer on the lines of their names. In such a grid the names are taken in order and the Xs in
    order, which holds only if there are as many of one as of the other and no line has two. An X with words after
    it ("X (Item 27 Only)") is not one of these: it says something of part of the motion, and is given back apart
    with the name on its line.
    """
    columns = [clean(cell).rstrip(":").upper() for cell in lines[at]["cells"][1:]]
    rows, notes, open_name, problem, at = [], [], "", "", at + 1  # rows: [the piece of a name on a line, the Xs on it]
    while at < len(lines):
        line = lines[at]
        if line["cells"] and len(line["cells"]) == len(columns) + 1 and not _COLUMN.match(line["cells"][1] or "-"):
            piece, marks = line["cells"][0], []
            for index, cell in enumerate(line["cells"][1:]):
                noted = re.fullmatch(r"[Xx]\s+\((.*)\)", cell)
                if cell in ("X", "x"):
                    marks.append(columns[index])
                elif noted and piece and not open_name and piece.count("(") <= piece.count(")"):
                    notes.append((piece, WORDS.get(columns[index], columns[index]), clean(noted[1])))
                elif cell:
                    problem = problem or f"a cell of the grid says {cell[:40]}"
        elif not line["cells"] and (open_name or _GRID_NAME.match(line["text"])) and len(line["text"]) < 80:
            piece, marks = line["text"], []
        else:
            break
        at += 1
        if open_name and _GRID_NAME.match(piece):
            open_name = ""  # the name above was left without its closing bracket; this is the next
        rows.append((piece, marks, bool(open_name)))
        if piece:
            open_name = clean(f"{open_name} {piece}")
            open_name = "" if open_name.count("(") <= open_name.count(")") else open_name
    names, name = [], ""
    for piece, _, runs_on in rows:
        if name and not runs_on:
            names.append(name)
            name = ""
        name = clean(f"{name} {piece}")
        if piece and name.count("(") <= name.count(")"):
            names.append(name)
            name = ""
    if name:
        names.append(name)
    marks = [mark for _, on_line, _ in rows for mark in on_line]
    whole = all(piece and not runs_on and piece.count("(") <= piece.count(")") for piece, _, runs_on in rows)
    if not names:
        problem = "a grid with no names"
    elif not marks and not notes:
        problem = problem or "a grid with no marks: the minutes do not say how anyone voted"
    elif whole and any(len(on_line) != 1 for _, on_line, _ in rows):
        piece, on_line, _ = next(row for row in rows if len(row[1]) != 1)
        problem = problem or f"the grid has {'no mark' if not on_line else 'two marks'} beside {shown(piece)}"
    elif len(marks) != len(names) or any(len(on_line) > 1 for _, on_line, _ in rows):
        problem = problem or f"the grid has {len(marks)} marks for {len(names)} names"
    cast = [(name, WORDS.get(word, word)) for name, word in zip(names, marks)] if not problem else [(name, "") for name in names]
    return cast, notes, problem, at


def comings(text, roll):
    """What a paragraph says of supervisors coming and going, as [(the supervisor, or UNSURE, "absent" or "present")]:
    "Supervisor Compton is now absent", "(SUPERVISOR HILL AND CHAIRPERSON PATTERSON ARE NOW PRESENT.)". Who is meant
    is whoever on the roll is named, by surname, just after a "Supervisor" or "Chairperson" in the sentence. With no
    such word it is someone else who came or went ("The Appellant is now absent"). With one and no name of the roll
    after it, who is meant cannot be read: UNSURE."""
    out, start = [], 0
    for found in _NOW.finditer(text):
        offices = list(_OFFICED.finditer(text, start, found.start()))
        start = found.end()
        if not offices:
            continue
        offices = [office for office in offices if office.start() >= offices[-1].start() - 60]  # "Supervisor Hill and Chairperson Patterson"
        words = [word for office in offices for word in re.findall(r"[a-z’'-]{3,}", text[office.end():office.end() + 60].lower().replace("-", ""))]
        members = [member for member in roll if any(word == key_of(member) or near(word, key_of(member)) for word in words)]
        out.extend((member, found[1].lower()) for member in members or [UNSURE])
    return out


def now_away(text, away, roll):
    """Who the minutes have out of the room after a paragraph: "is now absent" takes a supervisor out and "is now
    present" brings them back. Where who is meant cannot be read, UNSURE is added to those away: from then on the
    minutes' word for who is in the room cannot be relied on."""
    for member, state in comings(text, roll):
        away.add(member) if state == "absent" or member == UNSURE else away.discard(member)


def scan_pdf(text, known=(), roll=()):
    """A set of minutes kept from a PDF, as its head and what stands under each item, in order.

    An item begins at the margin with its number, after a gap, and runs to the next. Its first paragraph is its
    title. A motion is "Motion by:", "Second by:" and a grid; its words are the paragraph above it ("MOTION: The
    Board approves ..."), and what stands under the grid may say it failed. A heading between items is a short
    paragraph at the margin that ends with a colon.
    """
    lines = lines_of(text)
    head = head_of(lines, known)
    head.update(roll=head["roll"] or list(roll), lent=bool(roll) and not head["roll"])
    roll, away = head["roll"], set(head["absent"])
    # Where items begin, and how their numbers are printed. Until 2018 a number has a full stop after it ("12.") and
    # since then none ("12"); a page now and then stands further in than the rest; and a list inside an item ("34. A
    # resolution ...", set in, under the formal presentations) is numbered the other way and is not a run of items.
    # So a number printed the other way begins an item only at the left edge of its own page.
    starts = [(line["indent"], bool(found["dot"])) for line in lines if (line["gap"] or line["top"]) and not line["cells"]
              for found in [_ITEM.match(line["text"])] if found and found["rest"]]
    margin = Counter(indent for indent, _ in starts).most_common(1)[0][0] if starts else 0
    dotted = Counter(dot for indent, dot in starts if indent == margin).most_common(1)[0][0] if starts else False
    often = Counter(indent for indent, dot in starts if dot == dotted)
    margins = {margin} | {indent for indent, count in often.items() if count >= max(3, 0.1 * len(starts))}
    entries, current, section, paragraph, motion, graded = [], None, "", [], None, None
    titled, opened = True, True  # `opened`: the line above was a heading or a grid, so what follows begins something

    def flush():
        nonlocal paragraph, titled, graded
        said, paragraph = clean(" ".join(paragraph)), []
        if not said:
            return
        now_away(said, away, roll)
        if graded is not None and not graded["after"]:  # the first words under a grid
            graded["after"], graded["failed"] = said, graded["failed"] or bool(_FAILS.search(said))
        elif graded is not None and _FAILED.match(said):  # or a paragraph further down, before the next motion
            graded["failed"] = True
        if current is None:
            return
        if not titled:
            current["title"], titled = clean(f"{current['title']} {said}"), True
        else:
            current["paragraphs"].append(said)

    def target():
        nonlocal current, titled
        if current is None:  # a motion above every item
            current, titled = new_entry("heading", title=section, section=section), True
            entries.append(current)
        return current

    at = head["begins"]
    while at < len(lines):
        line = lines[at]
        words = line["text"]
        if line["cells"] and len(line["cells"]) >= 4 and all(_COLUMN.match(cell or "") for cell in line["cells"][1:]):
            flush()
            entry = target()
            if motion is None:
                motion = new_motion(moved_text(entry))
            motion["rows"], motion["notes"], motion["problem"], at = grid_at(lines, at)
            for name, _ in motion["rows"]:
                away.discard(who(name, roll))  # whoever is in a grid is in the room, whatever was said before
            motion["kind"], motion["away"] = "grid", sorted(away)
            entry["motions"].append(motion)
            graded, motion, opened = motion, None, True
            continue
        at += 1
        was_opened, opened = opened, False
        if _MOVER.match(words) and not line["cells"]:
            flush()
            entry = target()
            if motion is not None:  # a motion with no grid under it
                motion["problem"] = "no grid under the motion"
                entry["motions"].append(motion)
            motion, graded = new_motion(moved_text(entry), mover=_MOVER.match(words)[1]), None
            continue
        if _SECONDER.match(words) and motion is not None:
            motion["seconder"] = clean(_SECONDER.match(words)[1])
            continue
        at_margin = any(abs(line["indent"] - one) <= 2 for one in margins) and not line["cells"]  # a page may stand a little in or out
        ended = not paragraph or bool(re.search(r"[.:)]$", paragraph[-1]))  # the paragraph above has come to its end
        fresh = line["gap"] or was_opened or (line["top"] and ended)
        item = _ITEM.match(words) if at_margin and (fresh or ended) else None
        # The number of a consent agenda may run on to a second line of its cell: "1-" and under it "37."
        more = lines[at] if item and at < len(lines) and re.search(r"(?:[-–—,&]|and)$", item["label"]) else None
        more = more if more and re.fullmatch(r"\d{1,3}\.?", more["text"]) else None
        if item and bool(item["dot"] or (more and more["text"].endswith("."))) != dotted and line["indent"] - line["floor"] > 2:
            item = None
        # "10." may stand alone at the foot of a page, its words on the next
        if item and ((item["rest"] and fresh) or (not item["rest"] and words.endswith("."))):
            flush()
            if motion is not None:
                motion["problem"] = "no grid under the motion"
                target()["motions"].append(motion)
                motion = None
            label, rest = clean(item["label"]), item["rest"] or ""
            if more:
                label, at = f"{label} {more['text'].rstrip('.')}", at + 1
            current = new_entry("item", number=str(int(re.match(r"\d+", label)[0])), label=label, title="", section=section)
            current["consent"] = bool(_CONSENT.search(rest) or (re.search(r"\d\s*[-–—]\s*\d", label) and _CONSENT_RANGE.search(rest)))
            entries.append(current)
            paragraph, titled, graded = [rest] if rest else [], False, None
            continue
        # A heading stands apart as a rule; one in capitals with its colon is a heading wherever a sentence has ended.
        shouted = words.isupper() and len(re.sub(r"[^A-Z]", "", words)) >= 6 and not words.startswith("(") and not _NOW.search(words)
        if not item and (fresh or ended) and re.match(r"^This\s+is\s+(?:the|a)\s+time\s+set\s+for\s+(?:the\s+)?consideration\s+(?:of|for)\s+the\s+Consent\s+Agenda\b", words, re.I) \
                and "CONSENT" in section.upper() and current is None:
            flush()  # the consent agenda's own line, printed without its number
            current = new_entry("item", section=section)
            current["consent"] = True
            entries.append(current)
            paragraph, titled, graded = [words], False, None
            continue
        heading = at_margin and not item and len(words) < 160 and not _PRESENT.match(words) and not _ABSENT.match(words) and (
            (fresh and words.endswith(":") and not re.search(r":\s", words)) or (fresh and shouted and not words.endswith("."))
            or (ended and shouted and words.endswith(":") and not re.search(r":\s", words)))
        if heading and motion is None:
            flush()
            section, current, graded, opened = words.rstrip(":"), None, None, True
            while at < len(lines) and not lines[at]["gap"] and not lines[at]["top"] and abs(lines[at]["indent"] - line["indent"]) <= 2 and \
                    not lines[at]["cells"] and not _ITEM.match(lines[at]["text"]) and (lines[at]["text"].isupper() or lines[at]["text"].endswith(":")):
                section, at = clean(f"{section} {lines[at]['text']}").rstrip(":"), at + 1  # a heading of two lines
            continue
        if re.match(r"^(?:On\s+motion\s+duly\s+made|I,\s+[A-Z][A-Z .]+,\s+(?:County|Ex-Officio))", words) and at_margin:
            break  # the adjournment and the Clerk's certificate
        if line["gap"] or (line["top"] and ended):
            flush()
        paragraph.append(words)
    flush()
    if motion is not None:
        motion["problem"] = "no grid under the motion"
        target()["motions"].append(motion)
    return finish(head, parted(entries))


# A name in a list with words after it that say the vote was on part of the motion only.
_LIST_NOTE = re.compile(r"^(?P<name>.+?)\s*(?:\(\s*(?P<in>[^)]*)\)|\s(?P<after>(?:votes?\s+\w+\s+)?on\s+Items?\b.*?))\s*\.?$", re.I)
_APPROVED = re.compile(r"\bConsent\s+Agenda\s+Items?\s+[A-Z]{1,2}-\d+\s+(?:through|thru|to)\s+(?:[A-Z]{1,2}-)?\d+[^.]{0,80}\bare\s+approved\b", re.I)
_SUB = re.compile(r"^([A-Z]{1,4})\.$")  # a lettered line under an item of the agenda: "A." under A-18 is A-18-A
_DOCUMENT = re.compile(r"^(?:Amended\s+)?(?:Staff\s+)?Reports?(?:\s+\d+)?$|^Attachment\b.{0,40}$|^Power\s?Point\b.{0,40}$", re.I)


def scan_page(text, known=(), roll=()):
    """A set of minutes kept from a web page, as its head and what stands under each line of the agenda, in order.

    A motion is the sentence "Thereafter, on motion of Supervisor ..., seconded by Supervisor ..., and on the
    following roll call vote:" with a list of names under each of AYES, NOES, ABSENT and now and then ABSTAIN. Its
    words are the paragraph under the lists ("RESOLUTION NO. 2006-270, ... adopted."). One motion in eight has the
    mover and the seconder left empty ("on motion of Supervisor , seconded by Supervisor ,") and the names all the
    same; it is read like any other, and has no mover.
    """
    lines = lines_of(text)
    head = head_of(lines, known)
    head.update(roll=head["roll"] or list(roll), lent=bool(roll) and not head["roll"])
    entries, current, section, motion, parent, wants_text, placed = [], None, "", None, "", False, None
    for line in lines[head["begins"]:]:
        cells, words = line["cells"], line["text"]
        if cells and cells[0] == ITEM_MARK and len(cells) == 4:
            place, number, title = cells[1], cells[2], cells[3]
            motion, wants_text = None, False
            if not place and not number:
                if title.endswith(":"):  # "Administrative Office Items:"; any other such line is a note between items
                    section, current = title.rstrip(":"), None
                continue
            if place:
                section = ""  # a line with its place in the meeting is not under the heading above it
            sub = _SUB.match(number)
            if sub and parent:
                number = f"{parent}-{sub[1]}"
            elif number:
                number = parent = re.sub(r"^0+(?=\d)", "", number.rstrip("."))  # "12." in the last months of 2011
            current = new_entry("item", number=number or place, label=number or place, title=title, section=section)
            current["consent"] = bool(_CONSENT.search(title))
            # A line with its place in the meeting stands for itself; the lines after it with none are printed under it.
            placed = len(entries) if place else placed
            current["key"], current["within"] = len(entries), None if place else placed
            entries.append(current)
            continue
        if re.match(r"^On\s+motion\s+duly\s+made\b", words):
            break  # the adjournment and the Clerk's certificate
        if current is None:
            continue
        moved = _ON_MOTION.search(words)
        if moved:
            motion = new_motion("", mover=moved["mover"], seconder=moved["seconder"])
            motion["kind"], motion["lists"] = "lists", []
            current["motions"].append(motion)
            wants_text = False
            continue
        listed_ = _LIST.match(words)
        if listed_ and motion is not None and not motion["text"]:
            motion["lists"].append((clean(listed_[1]).upper(), listed_[2]))
            wants_text = True
            continue
        if motion is not None and motion["lists"] and not listed_ and wants_text is True and motion["lists"][-1][1] == "" and not cells:
            motion["lists"][-1] = (motion["lists"][-1][0], words)  # a label alone on its line, and the names under it
            continue
        if _DOCUMENT.match(words):
            continue
        if motion is not None and wants_text and not re.match(r"^[^:]{3,80}:\s", words):
            motion["text"], wants_text = words, False  # the first paragraph under the lists, unless someone speaks
            motion["failed"] = bool(_FAILS.search(words))
            current["paragraphs"].append(words)
            continue
        wants_text = False
        current["paragraphs"].append(words)
    for entry in entries:
        for motion in entry["motions"]:
            if not motion["text"]:
                motion["text"] = entry["title"]
            for label, names in motion.pop("lists"):
                for name in names_in(names):
                    note = _LIST_NOTE.match(name)  # "Frank Mecham (on Item A-6 only)", "Bruce S. Gibson on Item A-6"
                    if note:
                        motion["notes"].append((note["name"], WORDS.get(label, label), clean(note["in"] or note["after"])))
                    else:
                        motion["rows"].append((name, WORDS.get(label, label)))
        # In 2006 the consent agenda is passed under the line for the public's comment on it: the motion's own words
        # say what it is ("Consent Agenda Items B-1 through B-18 are approved").
        entry["consent"] = entry["consent"] or any(_APPROVED.search(motion["text"]) for motion in entry["motions"])
    entries = parted(entries)
    for entry in entries:
        if entry["consent"] and not entry["covers"] and len(entry["parts"]) == 1:
            # Its words name no items: they are the lines printed under it, to the next line with a place of its own.
            entry["covers"] = {other["number"] for other in entries if other.get("within") == entry["key"] and not other["consent"]}
    return finish(head, entries)


def covers_of(said, label):
    """The items a consent motion covers, from its own words (`said`) and the consent agenda's number on the agenda.

    Until 2011 the items are lettered: "Consent Agenda Items A-1 through A-30 are approved". Since then they are
    numbers, and the agenda's own "1-28" stands beside the motion's "items 1 through 28": where there are both, an
    item is covered if both have it (one set of minutes says "1 through 38" of a consent agenda of 28). A number
    alone on the agenda ("02") is where the consent agenda stands, not what it covers.
    """
    ranges = re.findall(r"\b([A-Z]{1,2})-(\d+)\s+(?:through|thru|to)\s+(?:[A-Z]{1,2}-)?(\d+)", said)
    if ranges:
        return {f"{letter}-{number}" for letter, first, last in ranges for number in range(int(first), int(last) + 1) if int(last) - int(first) < 200}
    if not re.match(r"\d", label):
        return set()  # a lettered consent agenda (CA-1) whose motion names no items: scan_page() takes the lines under it
    words, own = covered(said), covered(label)
    return {str(number) for number in (words & own if words and len(own) > 1 else words or own)}


def parted(entries):
    """The entries, with a consent agenda passed by two motions ("Item 2 on the following vote", then "Items 3
    through 42 and added 54") as two, each with the items its own motion covers."""
    out = []
    for entry in entries:
        if not entry["consent"]:
            out.append(entry)
            continue
        parts = []
        for motion in entry["motions"]:
            said = _COVERED.search(motion["text"]) or (None if parts else _COVERED.search(" ".join(entry["paragraphs"])))
            if said or not parts:
                parts.append({**entry, "paragraphs": entry["paragraphs"] if not parts else [], "motions": [],
                              "covers": covers_of(said[1] if said else "", entry["label"])})
            parts[-1]["motions"].append(motion)
        parts = parts or [{**entry, "covers": covers_of("", entry["label"])}]
        for part in parts:
            part["parts"] = parts
        out.extend(parts)
    return out


def under_of(number, covers):
    """Whether an item's number is one a consent motion covers: A-18-G is under A-18."""
    return number in covers or re.sub(r"-[A-Z]$", "", number) in covers


def decide(motion, roll):
    """Every supervisor's vote on a motion as ([(the supervisor as the roll has them, the name as printed, the vote)],
    ""), or (None, why it is not read).

    Read only if the names are the roll: no one else, no one twice, and everyone accounted for. A grid leaves out
    whoever is not in the room, so someone it does not name is ABSENT if the minutes have said they are away (at the
    head, or "is now absent" above the motion, or "is now present" in the first words under it) and otherwise leaves
    the motion unread. A list of names under AYES, NOES and ABSENT must name everyone itself.
    """
    if motion["problem"]:
        return None, motion["problem"]
    if not 3 <= len(roll) <= SEATS:
        return None, "no roll at the head of the minutes" if not roll else f"the head of the minutes names {len(roll)} supervisors"
    if not motion["rows"]:
        return None, "no names in the vote"
    cast, seen, said = [], set(), set()
    for name, word in motion["rows"]:
        member = who(name, roll)
        if member is None:
            return None, f"not on the roll: {shown(name)}"
        if member in seen and ((member, word) not in said or motion["kind"] == "grid"):
            return None, f"named twice: {member}"
        if member not in seen:  # in a list, a name printed twice under one word says one thing
            cast.append((member, name, word))
        seen.add(member)
        said.add((member, word))
    missing = [member for member in roll if member not in seen]
    if missing and UNSURE in motion["away"]:
        return None, f"names {len(seen)} of the {len(roll)} on the roll, and who the minutes have away cannot be read"
    # The minutes of 2012 note a return under the vote it came after: "(SUPERVISOR ADAM HILL IS NOW PRESENT.)"
    back = {member for member, state in comings(motion["after"], roll) if state == "present"}
    if motion["kind"] == "grid" and all(member in motion["away"] or member in back for member in missing):
        return cast + [(member, "", "ABSENT") for member in missing], ""
    if missing:
        return None, f"names {len(seen)} of the {len(roll)} on the roll: no {', '.join(missing)}"
    return cast, ""


def finish(head, entries):
    """The scan of a set of minutes, with each motion decided against the roll and the consent agenda's items found."""
    for entry in entries:
        for motion in entry["motions"]:
            motion["cast"], motion["problem"] = decide(motion, head["roll"])
            if motion["notes"] and not entry["consent"]:
                # "X (Airports Fees Only)": the vote was not one vote, and which part is whose cannot be told.
                beside = "a mark in the grid" if motion["kind"] == "grid" else "a name in the vote"
                motion["cast"], motion["problem"] = None, f"a note beside {beside}: {motion['notes'][0][2][:60]}"
    # An item is under the consent motion that covers its number: the last one printed above it, or failing that the
    # first below (a consent agenda taken up late is printed after the items heard before it).
    consents = [(at, entry) for at, entry in enumerate(entries) if entry["consent"] and entry["motions"]]
    for at, entry in enumerate(entries):
        if entry["kind"] == "item" and not entry["consent"]:
            over = [(where_, consent) for where_, consent in consents if under_of(entry["number"], consent["covers"] or set())]
            above = [consent for where_, consent in over if where_ < at]
            entry["under"] = above[-1] if above else over[0][1] if over else None
    asides(entries, head["roll"])
    return {**head, "entries": entries}


def asides(entries, roll):
    """What the minutes add in a sentence to a consent agenda's vote: "Supervisor Mecham: votes no on Item No. 20".

    The item named gets a motion of its own, the consent agenda's with that supervisor's vote changed. Words of a
    vote under the consent agenda that cannot be tied to an item it covers and a supervisor on the roll leave the
    consent motion unread: it then says something of the vote that is not known. A consent agenda passed by two
    motions is taken as one for this: the sentence may stand under either.
    """
    word_of = lambda did: (council_tables.NO if did.lower().startswith("vot") else "ABSTAIN" if did.lower().startswith("abstain") else
                           "RECUSED" if did.lower().startswith("recus") else did)
    numbered = lambda text: [re.sub(r"^([A-Z]+-\d+)([A-Za-z])$", r"\1-\2", re.sub(r"^0+(?=\d)", "", clean(number))).upper()
                             for number in re.findall(r"(?:[A-Z]{1,2}-)?\d{1,3}(?:-?[A-Za-z])?", text)]
    done = set()
    for heading in entries:
        parts = heading.get("parts") or [heading]
        if not heading["consent"] or id(parts[0]) in done:
            continue
        done.add(id(parts[0]))
        motions = [part["motions"][0] for part in parts if part["motions"]]
        if not any(motion["cast"] is not None for motion in motions):
            continue
        under = {}
        for entry in entries:
            if any(entry["under"] is part for part in parts):
                under.setdefault(entry["number"], entry)
        # An item taken off the consent agenda and voted on apart is not this motion's: words about it are not either.
        apart = {entry["number"] for entry in entries if entry["kind"] == "item" and not entry["consent"]} - set(under)
        said = " ".join(paragraph for part in parts for paragraph in part["paragraphs"])
        said = " ".join([said] + [motion["text"] for motion in motions if motion["text"] not in said] + [motion["after"] for motion in motions])
        tied, rest, lost = [], said, False
        for motion in motions:
            for name, word, note in motion["notes"]:  # in the grid itself: an X under RECUSE with "(Item 27 Only)"
                only = re.fullmatch(rf"(?:(?:votes?\s+\w+\s+)?on\s+)?(?:Items?\s*(?:Nos?\.?|#)?|Nos?\.?|#)\s*({_ITEMS})(?:\s+only)?|({_ITEMS})\s+only", note, re.I)
                numbers = [number for number in numbered(only[1] or only[2]) if number not in apart] if only else []
                if who(name, roll) is None or not only or any(number not in under for number in numbers):
                    lost = True
                    continue
                tied.extend((under[number], who(name, roll), word, f"{shown(name)}: {word} ({note})") for number in numbers)
        for pattern in (_ASIDE, _ASIDE_AFTER):
            for found in pattern.finditer(said):
                members = [who(name, roll) for name in names_in(found["who"])]
                numbers = [number for number in numbered(found["items"]) if number not in apart]
                if not members or None in members or any(number not in under for number in numbers):
                    lost = True
                    continue
                tied.extend((under[number], member, word_of(found["did"]), clean(found[0])) for number in numbers for member in members)
                rest = rest.replace(found[0], " ")
        for entry in under.values():
            for paragraph in entry["paragraphs"]:
                for found in _ON_THIS.finditer(paragraph):
                    members = [who(name, roll) for name in names_in(found["who"])]
                    if not members or None in members:
                        lost = True
                        continue
                    tied.extend((entry, member, word_of(found["did"]), clean(found[0])) for member in members)
        if lost or _OF_A_VOTE.search(rest):
            for motion in motions:
                motion["cast"], motion["problem"] = None, "words of a vote under the consent agenda not tied to an item and a supervisor"
            continue
        said_of = {}
        for entry, member, word, _ in tied:
            said_of.setdefault((id(entry), member), set()).add(word)
        for entry, member, word, sentence in tied:
            over = entry["under"]["motions"][0] if entry["under"]["motions"] else None
            if over is None or over["cast"] is None or any(one["kind"] != "aside" for one in entry["motions"]):
                continue  # the motion over the item is not read; or the item was voted on apart, and its own grid says how
            if not entry["motions"]:
                entry["motions"].append({**new_motion(sentence, over["mover"], over["seconder"]), "kind": "aside", "cast": list(over["cast"])})
            elif sentence not in entry["motions"][0]["text"]:
                entry["motions"][0]["text"] += " " + sentence
            aside = entry["motions"][0]
            words = said_of[(id(entry), member)]
            if len(words) > 1:  # an X under NOES "(Item No. 14 only)" and a sentence that she recused herself
                aside["cast"], aside["problem"] = None, f"the minutes say two things of {member} on this item: {' and '.join(sorted(words))}"
            elif aside["cast"] is not None:
                aside["cast"] = [(name, printed, word if name == member else vote) for name, printed, vote in aside["cast"]]


def slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "-", str(text)).strip("-")


def same_title(one, other):
    """Whether two printings of an item's title are one title: their first letters and digits agree."""
    one, other = (re.sub(r"[^a-z0-9]", "", text.lower())[:40] for text in (one, other))
    return bool(one and other) and (one.startswith(other[:25]) or other.startswith(one[:25]))


def read_meeting(meeting, scanned, page=None, spelled=None, pages=0):
    """One meeting's minutes: a line for each item and each consent agenda voted on, and the votes on each motion read
    whole. `page` is what the portal lists for the meeting, if it has it: an item of the minutes that is the same
    number and the same words there takes its file number and the portal's number for it.

    An item printed twice in the minutes (under the consent agenda as taken off it, and again where it was voted on)
    is one line.
    """
    meeting_id, date = meeting["meeting_id"], meeting["date"]
    spelled = spelled or {}
    name_of = lambda member: spelled.get(key_of(member), member) if member else ""
    roll = scanned["roll"]
    on_page = {}
    for row in (page or {}).get("lines", []):
        if row["number"] and row["item"]:
            on_page.setdefault(re.sub(r"^0+(?=\d)", "", row["number"]), row)
    lines, by_number = [], {}
    for entry in scanned["entries"]:
        if entry["kind"] != "item" and not entry["motions"]:
            continue
        key = ("consent", id(entry)) if entry["consent"] or entry["kind"] != "item" else entry["number"]
        line = by_number.get(key)
        if line is None:
            line = by_number[key] = {"entry": entry, "heading": entry["consent"] or entry["kind"] != "item", "number": entry["number"],
                                     "label": entry["label"], "title": entry["title"], "section": entry["section"],
                                     "paragraphs": [], "motions": [], "under": entry["under"]}
            lines.append(line)
        line["paragraphs"].extend(entry["paragraphs"])
        line["motions"].extend(entry["motions"])
        line["under"] = line["under"] or entry["under"]

    used, of_entry = set(), {}
    for line in lines:
        base = f"{meeting_id}-{'consent' if line['entry']['consent'] else 'motion' if line['heading'] else slug(line['number']) or 'item'}"
        item_id, again = base, 1
        while item_id in used:  # a number the minutes use twice for two things, or a second consent agenda
            again += 1
            item_id = f"{base}-{again}"
        used.add(item_id)
        line["item_id"] = item_id
        of_entry[id(line["entry"])] = line

    agenda, votes = [], []
    facts = {"time": scanned["hour"], "minutes": "read", "pages": pages, "present": scanned["present"],
             "roll": json.dumps([{"name": name_of(member), "role": scanned["roles"].get(key_of(member), "")} for member in roll],
                                ensure_ascii=False, separators=(",", ":")) if roll else "",
             "motions": 0, "motions_read": 0}
    for sequence, line in enumerate(lines, 1):
        item_id, heading, motions = line["item_id"], line["heading"], line["motions"]
        listed_ = None if heading else on_page.get(line["number"])
        if listed_ is not None and not same_title(listed_["title"], line["title"]):
            listed_ = None
        matter_id = "" if heading else listed_["item"] if listed_ else item_id
        matter_file = listed_["file"] if listed_ else ""
        for number, motion in enumerate(motions, 1):
            motion["read"] = motion["cast"] is not None
            motion["moved"] = name_of(who(motion["mover"], roll)) or shown(motion["mover"])
            motion["seconded"] = name_of(who(motion["seconder"], roll)) or shown(motion["seconder"])
            for member, _, word in motion["cast"] or []:
                votes.append({"item_id": item_id, "meeting_id": meeting_id, "date": date, "matter_id": matter_id, "matter_file": matter_file,
                              "member": name_of(member), "vote": word, "motion": number, "motion_text": motion["text"], "established": NAMED})
        last = motions[-1] if motions else None
        cast = [word for _, _, word in last["cast"] or []] if last else []
        done = [paragraph for paragraph in line["paragraphs"] if _DONE.match(paragraph)]
        closing = re.search(r"No action (?:is |was )?taken\.?$", line["paragraphs"][-1]) if line["paragraphs"] else None
        action = last["text"] if last else clean(" ".join(done)) or (closing[0] if closing else "")
        action = clean(re.sub(r"^(?:TENTATIVE\s+)?MOTION\s*:\s*", "", action, flags=re.I))
        numbered = _NUMBER.search(action) or _NUMBER.search(" ".join(done)) or _NUMBER.search(line["title"])
        under = of_entry.get(id(line["under"])) if line["under"] is not None else None
        # An item is passed by the consent agenda's motion if that motion covers it, it has no motion of its own, and
        # the minutes do not say it was taken off.
        with_section = bool(under and under["motions"] and not motions and not _TAKEN_OFF.search(" ".join(line["paragraphs"])))
        agenda.append({
            "item_id": item_id, "meeting_id": meeting_id, "date": date, "body": BODY,
            "agenda_number": line["label"] if heading else line["number"], "sequence": sequence, "matter_id": matter_id,
            "matter_file": matter_file, "title": "Consent Agenda" if line["entry"]["consent"] else clean(line["title"]), "action": action,
            "result": "Fail" if last and last["failed"] else "",  # a motion that carried is not marked
            "mover": last["moved"] if last else "", "seconder": last["seconded"] if last else "",
            "ayes": cast.count(council_tables.AYE), "noes": cast.count(council_tables.NO),
            "not_voting": sum(word not in (council_tables.AYE, council_tables.NO) for word in cast),
            "heading": heading, "section": line["section"], "section_id": under["item_id"] if with_section else "",
            "motions": len(motions), "motions_read": sum(motion["read"] for motion in motions),
            "votes_read": all(motion["read"] for motion in motions) if motions else None,
            "problem": next((motion["problem"] for motion in motions if not motion["read"]), ""),
            "doc_type": "" if heading else numbered[1].lower() if numbered else county.doc_type_of(line["title"]),
            "number": re.sub(r"\s", "", numbered[2]) if numbered else "",
            "portal_tally": listed_["tally"] if listed_ else "",
            "motion_log": json.dumps([{"motion": number, "text": motion["text"], "mover": motion["mover"], "seconder": motion["seconder"],
                                       "kind": motion["kind"], "rows": [[shown(name), word] for name, word in motion["rows"]],
                                       "notes": [[shown(name), word, note] for name, word, note in motion["notes"]],
                                       "away": motion["away"], "after": motion["after"][:300], "failed": motion["failed"], "read": motion["read"],
                                       "problem": motion["problem"]}
                                      for number, motion in enumerate(motions, 1)], ensure_ascii=False, separators=(",", ":")) if motions else "",
        })
        facts["motions"] += len(motions)
        facts["motions_read"] += sum(motion["read"] for motion in motions)
    return agenda, votes, facts


def printed_names(scanned):
    """Each supervisor's name as a set of minutes prints it, at the head and in the votes: [(surname's letters, the
    name, the district printed with it or None)]."""
    out = [(key_of(name), name, None) for name in scanned["roll"]]
    for entry in scanned["entries"]:
        for motion in entry["motions"]:
            out.extend((key_of(name), shown(name), district_of(name)) for name, _ in motion["rows"] if key_of(name))
    return out


def one_spelling(forms):
    """The one name each supervisor has in the tables, from {surname's letters: Counter(names printed)}: the name most
    often printed ("Bruce S. Gibson", not the "Bruce Gibson" of a few sets of minutes). A surname that is another,
    printed at least ten times as often, misspelled is that one."""
    count = {key: sum(names.values()) for key, names in forms.items()}
    best = {}
    for key in forms:
        nearby = [other for other in forms if near(key, other) and count[other] >= 10 * count[key]]
        names = forms[nearby[0] if len(nearby) == 1 else key]
        best[key] = sorted(names.items(), key=lambda form: (-form[1], -len(form[0]), form[0]))[0][0]
    return best


# ---------------------------------------------------------------------------
# Fetching and keeping
# ---------------------------------------------------------------------------

def kept(meeting_id, out_dir):
    path = Path(out_dir) / "text" / f"{meeting_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def keep(meeting_id, facts, out_dir):
    path = Path(out_dir) / "text" / f"{meeting_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")


def text_path(meeting_id, out_dir):
    return Path(out_dir) / "text" / f"{meeting_id}.txt"


def whole(meeting, out_dir):
    """Whether a meeting is kept here whole: where its minutes are, for the link the archive now gives, and their text."""
    facts = kept(meeting["meeting_id"], out_dir)
    return facts is not None and facts.get("minutes_of") == meeting["minutes_url"] and \
        (facts["format"] not in ("html", "pdf") or text_path(meeting["meeting_id"], out_dir).exists())


def where(location):
    """Where the archive sends a reader for a meeting's minutes, as (what kind of place, the address to ask, the
    portal's number for the meeting or "").

    The archive wraps its own PDFs in a viewer of Google's; the PDF's own address is inside that link and is asked of
    Granicus. Minutes on the portal are asked for there. Anywhere else is not followed.
    """
    parts = urlsplit(location)
    if parts.netloc.endswith("google.com"):
        inner = parse_qs(parts.query).get("url", [""])[0]
        if urlsplit(inner).netloc == urlsplit(GRANICUS).netloc:
            return "granicus", inner, ""
        parts = urlsplit(inner)
    if parts.netloc == urlsplit(GRANICUS).netloc:
        return "granicus", parts.geturl(), ""
    if parts.netloc == PORTAL_HOST:
        old, new = _OLD_MINUTES.search(parts.path), _GETFILE.search(parts.path)
        if old:  # the old link is to the minutes as a Word file; the meeting's page links them as a PDF
            return "portal meeting", "", old[1]
        if new:
            return "portal file", f"{PORTAL}/file/getfile/{new[1]}", ""
    return "elsewhere", location, ""


def fetch_meeting(meeting, out_dir, days=None):
    """A meeting's minutes, found, fetched and kept: their text in <meeting>.txt, and in <meeting>.json where they
    were (`format`, `document`) and what the portal's page of the meeting lists (`page`). `days` is the portal's
    calendar, for a meeting the archive does not tie to the portal's number for it.
    """
    meeting_id = meeting["meeting_id"]
    facts = {"minutes_of": meeting["minutes_url"], "format": "", "document": "", "portal_id": "", "page": None, "pages": 0}
    answer = fetch(meeting["minutes_url"])
    portal_id = ""
    if answer.status_code == 200 and answer.content[:4] != b"%PDF":
        answer.encoding = "utf-8"
        facts.update(format="html", document=meeting["minutes_url"])
        text_path(meeting_id, out_dir).parent.mkdir(parents=True, exist_ok=True)
        text_path(meeting_id, out_dir).write_text(page_text(answer.text), encoding="utf-8")
        keep(meeting_id, facts, out_dir)
        return facts
    body = answer.content if answer.content[:4] == b"%PDF" else None
    document = meeting["minutes_url"]
    if body is None and answer.status_code in (301, 302, 303, 307, 308):
        kind, document, portal_id = where(answer.headers.get("location", ""))
        if kind == "elsewhere":
            facts.update(format="elsewhere", document=document)
            keep(meeting_id, facts, out_dir)
            return facts
    elif body is None:
        facts["format"] = f"answer {answer.status_code}"
        keep(meeting_id, facts, out_dir)
        return facts
    if not portal_id and meeting["date"] >= f"{PORTAL_FROM}-01-01" and days and len(days.get(meeting["date"], [])) == 1:
        portal_id = days[meeting["date"]][0]  # the Board's one meeting of that day on the portal
    if portal_id:
        try:
            facts["page"] = page_of(fetch(f"{PORTAL}/meeting/details/{portal_id}").text)
            facts["portal_id"] = portal_id
        except Refused:
            if not document:
                raise
        except requests.RequestException as e:
            log.warning(f"meeting {meeting_id}: the portal's page {portal_id}: {type(e).__name__}: {e}")
        if not document:
            files = (facts["page"] or {}).get("files", {})
            document = files.get("minutes") or files.get("private minutes") or ""
    if body is None and not document:
        facts["format"] = "no minutes on the portal's page"
        keep(meeting_id, facts, out_dir)
        return facts
    if body is None:
        body = fetch(document).content
    facts["document"] = document
    if body[:4] != b"%PDF":
        facts["format"] = "not a PDF"
        keep(meeting_id, facts, out_dir)
        return facts
    pages = pdf_text(body)
    facts.update(format="pdf", pages=len(pages))
    text_path(meeting_id, out_dir).parent.mkdir(parents=True, exist_ok=True)
    text_path(meeting_id, out_dir).write_text("\n\f".join(pages), encoding="utf-8")
    keep(meeting_id, facts, out_dir)
    return facts


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------

def items_table(agenda, meetings):
    """Every item in the minutes read, with what was last done with it: by a vote of its own, or by the consent
    agenda's. An item the portal knows by a number is here once, with the last meeting it came to; `times_on_agenda`
    counts the minutes it is in.
    """
    of, minutes = agenda.set_index("item_id"), dict(zip(meetings["meeting_id"], meetings["minutes_url"]))
    lines = agenda[~agenda["heading"]]
    times, first = lines.groupby("matter_id").size(), lines.groupby("matter_id")["date"].min()
    rows = []
    for line in lines.sort_values(["date", "meeting_id", "sequence"]).itertuples(index=False):
        own = line.motions > 0
        over = of.loc[line.section_id] if not own and line.section_id else None
        vote = line._asdict() if own else over.to_dict() if over is not None else None
        rows.append({
            "date": line.date, "matter_id": line.matter_id, "matter_file": line.matter_file, "doc_type": line.doc_type, "title": line.title,
            "body": line.body, "status": "", "year": int(line.date[:4]), "subject": line.section, "agenda_date": first[line.matter_id],
            "passed_date": "", "last_action": line.action, "last_action_date": line.date if line.action else "",
            "result": vote["result"] if vote else "",
            "ayes": int(vote["ayes"]) if vote else 0, "noes": int(vote["noes"]) if vote else 0,
            "mover": vote["mover"] if vote else "", "seconder": vote["seconder"] if vote else "",
            "times_on_agenda": int(times[line.matter_id]),
            "url": f"{PORTAL}/agendaitem/details/{line.matter_id}" if line.matter_id.isdigit() else minutes.get(line.meeting_id, ""),
            "item_id": line.item_id, "meeting_id": line.meeting_id, "section": line.section,
            "action_on": "item" if own else "section" if over is not None else "",
            "votes_read": None if vote is None or pd.isna(vote["votes_read"]) else bool(vote["votes_read"]),
            "number": line.number,
        })
    out = pd.DataFrame(rows, columns=ITEM_COLUMNS).drop_duplicates("matter_id", keep="last")
    out["votes_read"] = out["votes_read"].astype("boolean")
    return out.sort_values(["date", "meeting_id", "matter_id"], ascending=[False, False, True]).reset_index(drop=True)


def members_table(votes, meetings, districts=None, now=None):
    """Everyone who voted on two days or more. `district` is the one the minutes' grids most often print with the
    name (they print it from 2019), `serving` is true where the last vote is no more than SERVING_DAYS old, and
    `role` is the office the newest minutes give a serving supervisor. The minutes give no terms of office."""
    since = ((datetime.strptime(now, "%Y-%m-%d") if now else datetime.now(timezone.utc)) - timedelta(days=SERVING_DAYS)).strftime("%Y-%m-%d")
    offices = {}
    for meeting in meetings[meetings["roll"] != ""].sort_values("date").itertuples(index=False):
        offices = {member["name"]: member["role"] for member in json.loads(meeting.roll)}
    cast = votes.groupby("member")["date"].agg(["min", "max", "size", "nunique"]) if len(votes) else pd.DataFrame()
    rows = [{"name": name, "district": (districts or {}).get(key_of(name)),
             "role": offices.get(name, "") if cast.loc[name, "max"] >= since else "", "start": "", "end": "",
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
    agenda["heading"] = agenda["heading"].astype(bool)
    agenda["votes_read"] = agenda["votes_read"].astype("boolean")
    return agenda, votes


FACTS = (("time", ""), ("document_url", ""), ("portal_id", ""), ("format", ""), ("note", ""), ("minutes", ""), ("pages", 0), ("present", ""),
         ("roll", ""), ("motions", 0), ("motions_read", 0))


def lent_roll(date, rolls, days=LENT_DAYS):
    """The roll for a set of minutes whose head prints none (some web pages of 2010 and 2011 leave it out): that of
    the nearest minutes before it and the nearest after, if both are within `days` and name the same supervisors.
    Otherwise none, and nothing in those minutes is read. `rolls` is {meeting: (date, the roll at its head)}."""
    day = datetime.strptime(date, "%Y-%m-%d")
    near_by = lambda other: abs((datetime.strptime(other, "%Y-%m-%d") - day).days) <= days
    before = max(((other, roll) for other, roll in rolls.values() if roll and other < date and near_by(other)), default=None)
    after = min(((other, roll) for other, roll in rolls.values() if roll and other > date and near_by(other)), default=None)
    same = before and after and {key_of(name) for name in before[1]} == {key_of(name) for name in after[1]}
    return list(before[1]) if same else []


def read_all(meetings, agenda, votes, found, out_dir):
    """The five tables, from the meetings listed, the tables held, and every set of minutes kept here.

    Every meeting kept here is read, old and new: a supervisor has the one name the minutes most often print, and
    that is known only with all of them. Two rows of the archive that lead to one set of minutes (a meeting recorded
    in two parts) are read once, under the first.
    """
    found = dict(found)
    scans, forms, districts, first_of, texts, heads = {}, {}, {}, {}, {}, Counter()
    for member in votes["member"] if len(votes) else []:
        forms.setdefault(key_of(member), Counter())[member] += 1
    rows = []
    for row in meetings.to_dict("records"):
        facts = kept(row["meeting_id"], out_dir)
        if facts is None or facts.get("minutes_of") != row["minutes_url"]:
            continue
        rows.append((row, facts))
        if facts["format"] in ("html", "pdf") and text_path(row["meeting_id"], out_dir).exists():
            texts[row["meeting_id"]] = text_path(row["meeting_id"], out_dir).read_text(encoding="utf-8")
            heads.update(head_of(lines_of(texts[row["meeting_id"]]))["roll"])
    known = {name for name, count in heads.items() if count >= 3 and len(name.split()) <= 3} | set(votes["member"] if len(votes) else [])
    rolls = {meeting_id: (date, head_of(lines_of(text), known)["roll"]) for meeting_id, text, date in
             ((row["meeting_id"], texts[row["meeting_id"]], row["date"]) for row, _ in rows if row["meeting_id"] in texts)}
    for row, facts in rows:
        state = {"document_url": facts["document"], "portal_id": facts["portal_id"], "format": facts["format"], "pages": facts["pages"]}
        scanned = None
        if row["meeting_id"] in texts:
            text = texts[row["meeting_id"]]
            first = first_of.setdefault(facts["document"], row["meeting_id"])
            if first != row["meeting_id"]:
                state["minutes"] = f"same as {first}"
            elif len(re.sub(r"\s", "", text)) < LAYER_CHARS:
                state["minutes"] = "no text layer" if facts["format"] == "pdf" else "an empty page"
            else:
                lent = [] if rolls[row["meeting_id"]][1] else lent_roll(row["date"], rolls)
                scanned = scan_pdf(text, known, lent) if facts["format"] == "pdf" else scan_page(text, known, lent)
                state["note"] = "; ".join(note for note, said in (("draft", re.search(r"BOARD OF SUPERVISORS\b.{0,6}\bDRAFT\b", text)),
                                                                  ("no roll at the head: that of the minutes before and after", scanned["lent"])) if said)
                for key, name, district in printed_names(scanned):
                    forms.setdefault(key, Counter())[name] += 1
                    if district:
                        districts.setdefault(key, Counter())[district] += 1
        else:
            state["minutes"] = facts["format"]
        scans[row["meeting_id"]] = (row, facts, scanned, state)
    spelled = one_spelling(forms)
    new_agenda, new_votes = [], []
    for meeting_id, (row, facts, scanned, state) in scans.items():
        if scanned is not None:
            reading = read_meeting(row, scanned, facts.get("page"), spelled, facts["pages"])
            new_agenda.extend(reading[0])
            new_votes.extend(reading[1])
            state = {**state, **reading[2]}
        found[meeting_id] = {**dict(FACTS), **state}
    agenda = joined(agenda[~agenda["meeting_id"].isin(set(scans))], pd.DataFrame(new_agenda, columns=AGENDA_COLUMNS))
    votes = joined(votes[~votes["meeting_id"].isin(set(scans))], pd.DataFrame(new_votes, columns=VOTE_COLUMNS))
    listed_ids = set(meetings["meeting_id"])
    agenda, votes = agenda[agenda["meeting_id"].isin(listed_ids)], votes[votes["meeting_id"].isin(listed_ids)]
    order = lambda column: column.astype(int) if column.name == "meeting_id" else column
    agenda = agenda.sort_values(["date", "meeting_id", "sequence"], key=order).reset_index(drop=True)
    votes = votes.sort_values(["date", "meeting_id", "item_id", "motion", "member"], key=order).reset_index(drop=True)
    agenda, votes = typed(agenda, votes)
    meetings = meetings.copy()
    for name, empty in FACTS:
        meetings[name] = [found.get(meeting_id, {}).get(name, empty) for meeting_id in meetings["meeting_id"]]
    count = agenda[~agenda["heading"]].groupby("meeting_id").size() if len(agenda) else {}
    meetings["items"] = meetings["meeting_id"].map(count).fillna(0).astype(int)
    district = {key: seen.most_common(1)[0][0] for key, seen in districts.items()}
    tables = council_tables.standard({
        "items": items_table(agenda, meetings), "meetings": meetings, "agenda_items": agenda, "votes": votes,
        "members": members_table(votes, meetings, district),
    })
    council_tables.write_tables(tables, out_dir)
    return tables


def build(base, everything, out_dir, since=FIRST_YEAR, limit=0):
    rows = [row for row in listed() if row["date"] >= f"{since}-01-01"]
    log.info(f"San Luis Obispo County: {len(rows)} meetings listed")
    if len(rows) < 20:
        raise RuntimeError("the listing of meetings came back nearly empty")
    meetings = meetings_table(rows)

    agenda, votes, before_meetings = (council_tables.held(HF_REPO, out_dir, name, base) for name in ("agenda_items", "votes", "meetings"))
    before = 0 if votes is None else len(votes)
    if agenda is None or votes is None or before_meetings is None:
        agenda, votes = pd.DataFrame(columns=AGENDA_COLUMNS), pd.DataFrame(columns=VOTE_COLUMNS)
        before_meetings = pd.DataFrame(columns=MEETING_COLUMNS)
    found = {row["meeting_id"]: {name: row.get(name, empty) for name, empty in FACTS}
             for row in before_meetings[before_meetings["format"] != ""].to_dict("records")}
    recent = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    with_minutes = [row for row in meetings.to_dict("records") if row["minutes_url"]]
    wanted = [row for row in with_minutes
              if row["date"] >= recent or (not whole(row, out_dir) and (everything or row["meeting_id"] not in found))]
    wanted.sort(key=lambda row: (row["date"], int(row["meeting_id"])), reverse=True)  # the newest first: a room shows those
    waiting = len(wanted)
    wanted = wanted[:limit] if limit else wanted
    log.info(f"Fetching {len(wanted)} meetings of {waiting} not yet read or to be read again")

    # First where each meeting's minutes are and their text, which is the only part that asks anything of the two
    # hosts: one request after another. They are kept as they come, so a run that is stopped has lost nothing, and the
    # tables are written now and then on the way.
    fetched, days, tables = 0, None, None
    for count, row in enumerate(wanted, 1):
        try:
            if days is None and row["date"] >= f"{PORTAL_FROM}-01-01" and PORTAL_HOST not in REFUSED:
                try:
                    days = calendar()
                except (Refused, requests.RequestException, ValueError) as e:
                    log.warning(f"the portal's calendar: {type(e).__name__}: {e}")
                    days = {}
            fetch_meeting(row, out_dir, days)
            fetched += 1
        except Refused as e:
            log.error(f"A host refused a request ({e}): no more is asked of it in this run")
            if urlsplit(GRANICUS).netloc in REFUSED:
                break
        except KeyboardInterrupt:
            log.warning("Stopped: writing the tables from what is kept")
            break
        except Exception as e:
            log.warning(f"meeting {row['meeting_id']}: {type(e).__name__}: {e}")
        if count % 25 == 0:
            log.info(f"San Luis Obispo County: {count} of {len(wanted)} meetings asked for")
        if count % WRITE_EVERY == 0:
            tables = read_all(meetings, agenda, votes, found, out_dir)

    tables = read_all(meetings, agenda, votes, found, out_dir)
    if len(tables["votes"]) < before * 0.98:
        raise RuntimeError(f"only {len(tables['votes'])} votes where there were {before}; not publishing")
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
        "n_pages": f"{int((read['format'] == 'html').sum()):,}", "n_pdfs": f"{int((read['format'] == 'pdf').sum()):,}",
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
        log.error(f"San Luis Obispo County tables not uploaded: {e}")
        return False
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the San Luis Obispo County Board's meetings, actions and votes")
    parser.add_argument("--base", action="store_true", help="start from the tables written here, not the published ones")
    parser.add_argument("--all", action="store_true", help="fetch every meeting not kept here whole, read before or not")
    parser.add_argument("--since", type=int, default=FIRST_YEAR, help="read no meeting before this year")
    parser.add_argument("--max", type=int, default=0, help="meetings to fetch in one run (0 for all)")
    parser.add_argument("--out", default="", help="directory to write the tables into (minutes_pdf/san-luis-obispo-county if not given)")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the tables only")

    out_dir = Path(args.out) if args.out else OUT_DIR
    try:
        tables, fetched = build(args.base, args.all, out_dir, args.since, args.max)
    except Exception as e:
        log.error(f"San Luis Obispo County tables not built: {type(e).__name__}: {e}")
        return 1
    pushed = False if args.no_upload else upload(tables, out_dir, args.write_card)
    meetings, agenda, votes, members = tables["meetings"], tables["agenda_items"], tables["votes"], tables["members"]
    motions, motions_read = int(agenda["motions"].sum()), int(agenda["motions_read"].sum())
    log.info(f"RESULT: san-luis-obispo-board items={len(tables['items'])} meetings={len(meetings)} "
             f"meetings_with_minutes={int((meetings['minutes_url'] != '').sum())} "
             f"minutes_read={int((meetings['minutes'] == 'read').sum())} "
             f"no_text_layer={int((meetings['minutes'] == 'no text layer').sum())} agenda_items={len(agenda)} "
             f"motions={motions} motions_read={motions_read} motions_unread={motions - motions_read} votes={len(votes)} "
             f"members={len(members)} serving={int(members['serving'].sum())} meetings_fetched={fetched} "
             f"first_vote={votes['date'].min() if len(votes) else ''} last_vote={votes['date'].max() if len(votes) else ''} "
             f"refused={bool(REFUSED)} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
