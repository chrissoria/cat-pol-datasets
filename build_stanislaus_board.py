#!/usr/bin/env python3
"""
Build chrissoria/stanislaus-county-board: the meetings of the Stanislaus County
Board of Supervisors, what the Board did at each, and how each supervisor
voted.

One source: the County's own site (stancounty.com/bos). It lists the meetings
of a year on one page and keeps the minutes of each as a PDF. A vote is
recorded nowhere else, so the votes here are read from the minutes' text. The
minutes are short. Each motion is one paragraph that opens with who moved and
seconded and how the vote went:

    Withrow/B. Condit unan. Adopted the consent calendar
    Chiesa/Withrow (4-1)(C. Condit opposed) 5.B.1 Approved the Agreement with ...
    B. Condit/Grewal (4-0)(Chiesa absent) 7.2 Conducted a public hearing ...

They never list the ayes, and they print no roll of the Board. So two things
are worked out, and a motion is read only if both come out whole:

  Who sits on the Board that day. A supervisor is on a meeting's roll if the
  minutes name them (moving, seconding, in a vote, absent, arriving, leaving,
  or as the chair) at that meeting, or at both an earlier and a later one no
  more than a year apart. The roll must have a name for every seat: five, less
  any seat the minutes call vacant.

  How each of them voted. With a count, "(4-1)(C. Condit opposed)": everyone
  outside the ayes must be named, and the numbers must add up to the seats;
  the rest are the ayes. With "unan." and no count: everyone on the roll voted
  aye, unless the minutes have a supervisor away at that point (absent at the
  head with no arrival since, or gone from the room and not back), in which
  case nothing is read. `established` on each vote says which: `named`,
  `count` or `unanimous`.

A motion is read whole or not at all. One that is not read stays in
agenda_items with what stopped it (`problem`) and has no rows in votes.

The dataset has the five tables every council's and board's dataset has
(council_tables.py), in data/:
  items.parquet          every item acted on in minutes that were read
  meetings.parquet       one row per meeting listed
  agenda_items.parquet   one row per item, and one per consent calendar, with what was done
  votes.parquet          one row per supervisor and motion voted on
  members.parquet        one row per supervisor with a vote here
They are kept here in minutes_pdf/stanislaus-county/, with the text of each
set of minutes beside them in text/, so a PDF is fetched once.

Two ways to run it:

    python build_stanislaus_board.py
        The routine run. Starts from the published tables, lists every meeting
        again, and reads the minutes not read before and those of meetings in
        the last 90 days (minutes are posted after the meeting, and the last
        meetings' rolls wait on the next ones).

    python build_stanislaus_board.py --base
        The same, starting from the tables written here. It fetches the newest
        minutes first and can be stopped and started again. Minutes whose text
        is kept here are read again on every run; that takes no request.

    --since YEAR  read no meeting before this year (default 2004: before then the minutes are set out differently)
    --max N       minutes to fetch in one run (default 0, for all)
    --all         fetch every set of minutes whose text is not kept here, read before or not
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
from datetime import date as day_type
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

HF_REPO = "chrissoria/stanislaus-county-board"
OUT_DIR = bills.SCRIPT_DIR / "minutes_pdf" / "stanislaus-county"
CARD_FILE = bills.SCRIPT_DIR / "README_stanislaus_board.md"
TABLES = council_tables.TABLES
BODY = "Board of Supervisors"

SITE = "https://www.stancounty.com"
FIRST_YEAR = 2004  # before this the minutes give movers by initial and use "unan." with a supervisor absent
LISTED_FROM = 1999  # the year pages under /bos/agenda/ begin here; earlier years are under /bos/minutes/
SEATS = 5  # a county's board of supervisors (Government Code 25000)
RECENT_DAYS = 90  # meetings this recent are fetched again
APART_DAYS = 366  # two namings of a supervisor further apart than this say nothing of the time between them
LAYER_CHARS = 200  # minutes with fewer characters of their own than this are a scan
SMALLEST = 4  # type smaller than this is not on the page to be read: some PDFs carry a second, hidden copy of the text
INDENT = 6  # points to one space of a line's distance in from the margin
SET_IN = 2  # a line this many spaces in is part of a list, not a paragraph at the margin

MEETING_COLUMNS = council_tables.COLUMNS["meetings"] + [
    "name", "note", "video_url", "minutes", "pages", "present", "seats", "roll", "named", "spoken", "motions", "motions_read"]
AGENDA_COLUMNS = council_tables.COLUMNS["agenda_items"] + [
    "heading", "section", "section_id", "motions", "motions_read", "votes_read", "problem", "how", "established", "voted_with",
    "doc_type", "subject", "number", "motion_log"]
VOTE_COLUMNS = council_tables.COLUMNS["votes"] + ["motion", "motion_text", "established"]
ITEM_COLUMNS = council_tables.COLUMNS["items"] + ["item_id", "meeting_id", "section", "action_on", "votes_read", "number"]

# How a vote came to be known. The minutes name a supervisor only when they did something other than vote aye.
NAMED, COUNT, UNANIMOUS = "named", "count", "unanimous"

# Misspellings of a supervisor's name met in the minutes (as letters only), and the name as the minutes otherwise have it.
SPELLED = {"montieth": "Monteith", "montheith": "Monteith", "cheisa": "Chiesa", "whithrow": "Withrow", "wthrow": "Withrow"}

# The minutes' words for what a supervisor did other than vote aye, and the word the tables have for each.
WORDS = (("oppos", council_tables.NO), ("absent", "ABSENT"), ("abstain", "ABSTAIN"), ("recus", "RECUSED"))
UNKNOWN = "?"  # someone the minutes speak of without a name that can be read ("District 4 Supervisor")

_TITLE = r"(?:Vice[- ]?Chair(?:man|woman|person)?|Chair(?:man|woman|person)?|Supervisors?)"
_NAME = r"(?:[A-Z]\.\s?)?(?:De\s)?[A-Z][A-Za-z’']+"  # Chiesa, B. Condit, O’Brien, De Martini
_NTH = r"(?:First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth)\s+Vote"
_NUMBER_OF = r"\d{1,2}\.\d{1,2}[a-z]?"
_PREFIX = (rf"(?:(?:{_NUMBER_OF}\s+)?[Cc]losed\s+[Ss]ession\s+[Aa]nnouncement(?:\s+[A-Z])?\s*:\s*(?:{_NUMBER_OF}\s+)?"
           rf"|{_NTH}\s*:\s*|[IVX]+\.?\s+)")
_MOTION = re.compile(rf"^(?P<prefix>{_PREFIX})?(?:{_TITLE}\s+)?(?P<mover>{_NAME}|[A-Z])\.?\s*/\s*(?:{_TITLE}\s+)?"
                     rf"(?P<seconder>{_NAME}|[A-Z])\.?\s*(?P<rest>(?:\(|[Uu]nan).*)$")
_UNAN = re.compile(r"\s*(?:\(\s*[Uu]nan\.?\s*\)|[Uu]nan\b)\.?")
_PAREN = re.compile(r"\s*\(([^()]*)\)\.?")
_TALLY = re.compile(r"^\s*(\d)\s*-\s*(\d)(?:\s*-\s*(\d))?\s*(.*)$")
_NOTE = re.compile(r"^(.*?)\s*\b(oppos\w*|absent|abstain\w*|recus\w*|vacant)\s*$", re.I)
_VACANT = re.compile(r"^District\s+\w+$", re.I)
# What an item is called at the head of what was done with it: 7.1, 6.B.17, *B5a, B8, a public hearing's hour, IX.
_ITEM = re.compile(r"^(\d{1,2}\.[A-Z]\.\d{1,2}[a-z]?|\d{1,2}\.\d{1,2}[a-z]?|\*?[A-Z]-?\d{1,2}[a-z]?|\d{1,2}:\d{2}\s?[ap]\.?\s?m\.?"
                   r"|\([IVX]+-[A-Z]\*?\)|[IVX]+\.|\d{1,2}\.)(?=\s|$)\s*(.*)$")
_PARAGRAPH = re.compile(rf"^(Corr\.?\s*\d+|\d{{1,2}}\.[A-Z]\.\d{{1,2}}[a-z]?|{_NUMBER_OF}|\d{{1,2}}\.|\*?[A-Z]\d{{1,2}}[a-z]?)\s+([A-Z].*)$")  # business with a number and no motion: a letter referred, a closed session
_CONSENT = re.compile(r"^(?:[IVX]+\.\s*)?(?:Adopted|Approved)\s+the\s+consent\s+calendar\b", re.I)
_FAILED = re.compile(r"\bmotion\b[^.;]{0,80}\bfailed\b", re.I)
_WHO = rf"(?:{_TITLE}\s+)?{_NAME}(?:\s*(?:,\s*(?:and\s+)?|\s+and\s+)(?:{_TITLE}\s+)?{_NAME})*"
_CAME = re.compile(rf"^(?P<who>{_WHO})\s+(?:arrived|returned|rejoined|joined\s+the\s+meeting)\b")
_WENT = re.compile(rf"^(?P<who>{_WHO})\s+(?:left|departed|exited|stepped\s+(?:out|away|down)|was\s+excused)\b")
_RECUSED = re.compile(rf"^(?P<who>{_WHO})\s+recused\s+(?:him|her|them)sel(?:f|ves)\b(?P<rest>.*)$")
_ALL_PRESENT = re.compile(r"^All\s+Supervisors\s+Present\b", re.I)
_ABSENT = re.compile(r"^(.*?)\s+(?:is\s+|was\s+|are\s+|were\s+)?absent\b", re.I)
_HEAD_VACANT = re.compile(r"^District\s+\w+\s+Vacant\b", re.I)
_SESSION = re.compile(r"^(.*?\bSession)\b\s*(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day\b", re.I)
_STARTS = re.compile(r"^(?:Recessed|Reconvened|Adjourned|Convened|ATTESTED|Corr\b)")  # a paragraph of its own, wherever it stands
_SPOKEN = re.compile(rf"^(?:Vice[- ]?)?Chair(?:man|woman|person)\s+({_NAME})\s+[a-z]")  # "Chairwoman Olsen acknowledged ..."
_ROLE = re.compile(rf"\b(Vice[- ]?Chair(?:man|woman|person)?|Chair(?:man|woman|person)?)\s+({_NAME})")
_NUMBER = re.compile(r"\b(Resolution|Ordinance)\s+(?:No\.?\s*)?((?:C\.?S\.?\s*)?\d[\w-]*\d)", re.I)
_DEPARTMENT = re.compile(r"\s[–—-]\s*([A-Z][A-Za-z/&’' .,-]{1,60}?)(?:\s+(?:\d{4}-\d{1,4}|[A-Z]{1,4}-\d[\w-]*))*\s*$")


class Refused(Exception):
    """The host answered with a check, a login or a refusal. It is not asked again in this run."""


_refused = threading.Event()
_CHECK = re.compile(r"captcha|cf-challenge|are you a human|access denied|sign in to continue", re.I)


def fetch(url, tries=4):
    """One answer from the County's site. A refusal is not tried again, and nothing more is asked of the host in this run."""
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
        except (requests.RequestException, OSError) as e:
            # A host that is not allowed will not be allowed on a second asking; a page that is not there is not there.
            gone = isinstance(e, requests.HTTPError) and e.response is not None and e.response.status_code == 404
            if attempt == tries - 1 or gone or isinstance(e, requests.exceptions.ProxyError):
                raise
            time.sleep(3 * (attempt + 1))


# ---------------------------------------------------------------------------
# The listing
# ---------------------------------------------------------------------------

_COMMENT = re.compile(r"<!--.*?-->", re.S)  # the page keeps rows it no longer shows, as comments
_ROW = re.compile(r'<ul class="list-inline agendalist">(.*?)</ul>', re.S)
_DAY = re.compile(r"<strong>\s*(\d{1,2})/(\d{1,2})\s*</strong>")
_CELL = re.compile(r"<li[^>]*>(.*?)</li>", re.S)
_LINK = re.compile(r'href="([^"]+)"')
_HOUR = re.compile(r"\d{1,2}:\d\d\s*[ap]\.?m\.?", re.I)
_NO_MEETING = re.compile(r"no meeting|cancel", re.I)
_SUFFIX = re.compile(r"min\d\d-\d\d-\d\d\s*([A-Za-z]+)\.pdf$", re.I)  # min12-06-16special.pdf


def year_url(year):
    return f"{SITE}/bos/agenda/{year}/" if year >= LISTED_FROM else f"{SITE}/bos/minutes/{year}/"


def rows_of(page, year):
    """The meetings on one year's page, as the site has them. A day marked "No Meeting" is not one."""
    rows = []
    for row in _ROW.findall(_COMMENT.sub("", page)):
        found = _DAY.search(row)
        if not found:
            continue
        cells = [clean(html.unescape(re.sub(r"<[^>]+>", " ", cell))) for cell in _CELL.findall(row)]
        if any(_NO_MEETING.search(cell) for cell in cells):
            continue
        links = [html.unescape(link) for link in _LINK.findall(row)]
        of = lambda part, end: next((SITE + quote(link, safe="/:%") for link in links
                                     if link.lower().startswith(f"/bos/{part}/{year}/") and link.lower().endswith(end)), "")
        minutes = of("minutes", ".pdf")
        suffix = _SUFFIX.search(minutes.replace("%20", " "))
        date = f"{year}-{int(found[1]):02d}-{int(found[2]):02d}"
        rows.append({"meeting_id": date + (f"-{suffix[1].lower()}" if suffix else ""), "date": date,
                     "time": next((cell for cell in cells if _HOUR.fullmatch(cell)), ""),
                     "note": "; ".join(cell for cell in cells[1:] if cell and not _HOUR.fullmatch(cell)
                                       and cell.split()[0] not in ("Agenda", "Minutes", "Video", "Audio", "Español")),
                     "agenda": of("agenda", ".pdf"), "minutes": minutes,
                     "video": next((SITE + link for link in links if link.lower().startswith("/bos/video/")), "")})
    return rows


def listed(first=FIRST_YEAR, last=None):
    """Every meeting the site lists from `first` on, a year to a request."""
    last = last or datetime.now(timezone.utc).year
    rows = {}
    for year in range(first, last + 1):
        try:
            page = fetch(year_url(year)).text
        except requests.HTTPError:
            if year == last:
                continue  # early in January the new year's page may not be up
            raise
        for row in rows_of(page, year):
            if row["meeting_id"] not in rows or row["minutes"]:
                rows[row["meeting_id"]] = row
        time.sleep(0.4)
    return list(rows.values())


def meetings_table(rows):
    """One row per meeting listed. What a reading adds (`minutes`, `pages`, `present`, `roll` and the counts) is filled in by build()."""
    out = [{
        "meeting_id": row["meeting_id"], "date": row["date"], "time": row["time"], "body": BODY, "location": "",
        "url": year_url(int(row["date"][:4])), "agenda_url": row["agenda"], "minutes_url": row["minutes"], "items": 0,
        "name": "", "note": row["note"], "video_url": row["video"],
        "minutes": "", "pages": 0, "present": "", "seats": 0, "roll": "", "named": "", "spoken": "", "motions": 0, "motions_read": 0,
    } for row in rows]
    return pd.DataFrame(out, columns=MEETING_COLUMNS).sort_values(["date", "meeting_id"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# The text of a set of minutes
# ---------------------------------------------------------------------------

def pdf_text(body):
    """The text a PDF carries, a page at a time. Nothing is read off the picture of a page.

    Two things about where a line stands are kept, since the minutes say with them what the words do not: a line is
    set in by one space for every INDENT points it stands in from the margin (the items of a consent calendar are set
    in, a motion is not), and an empty line marks a gap the page leaves between two paragraphs.
    """
    import pdfplumber
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    with pdfplumber.open(io.BytesIO(body)) as document:
        pages = [page.filter(lambda thing: thing.get("object_type") != "char" or thing.get("size", 12) >= SMALLEST)
                 .extract_text_lines(return_chars=False) for page in document.pages]
    # The margin is the leftmost place lines begin at, leaving out a stray line or two that stands further left.
    begun = Counter(round(line["x0"]) for lines in pages for line in lines)
    enough = max(3, 0.02 * sum(begun.values()))
    margin = min((x for x, count in begun.items() if count >= enough), default=min(begun, default=0))
    out = []
    for lines in pages:
        text, foot = [], None
        for line in lines:
            if foot is not None and line["top"] - foot > 0.6 * (line["bottom"] - line["top"]):
                text.append("")
            text.append(" " * max(0, round((line["x0"] - margin) / INDENT)) + line["text"])
            foot = line["bottom"]
        out.append("\n".join(text))
    return out


def text_of(meeting, out_dir, fresh=False):
    """The text of a meeting's minutes, pages parted by form feeds: from the copy kept here, or fetched and kept."""
    kept = Path(out_dir) / "text" / f"{meeting['meeting_id']}.txt"
    if kept.exists() and not fresh:
        return kept.read_text(encoding="utf-8")
    time.sleep(0.3)
    body = fetch(meeting["minutes_url"]).content
    if body[:4] != b"%PDF":
        raise ValueError("the site sent a page in place of the minutes")
    text = "\n\f".join(pdf_text(body))
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(text, encoding="utf-8")
    return text


def lines_of(text):
    """The minutes' lines in order, each with how far it is set in, whether a gap stands above it, and whether it is
    the first of its page (where a gap cannot be seen). The number at the foot of a page is left out."""
    out = []
    for page in text.split("\f"):
        rows = page.split("\n")
        while rows and (not rows[-1].strip() or rows[-1].strip().isdigit()):
            rows.pop()
        gap, top = False, True
        for row in rows:
            if not row.strip():
                gap = True
                continue
            out.append({"indent": len(row) - len(row.lstrip(" ")), "text": clean(row), "gap": gap and not top, "top": top})
            gap, top = False, False
    return out


# ---------------------------------------------------------------------------
# Who a name is, and who sits on the Board
# ---------------------------------------------------------------------------

def key_of(name):
    """What two printings of a supervisor's name share: its letters. "B.Condit" is "B. Condit", "De Martini" is "DeMartini"."""
    return re.sub(r"[^a-z]", "", str(name or "").lower())


def printed(name):
    """A supervisor's name as the minutes print it, without the office before it and with its spacing made one way."""
    name = re.sub(rf"^{_TITLE}\s+", "", clean(name)).rstrip(".").replace("'", "’")
    name = re.sub(r"^([A-Z])\.\s*", r"\1. ", name)
    return SPELLED.get(key_of(name), name)


def names_in(text):
    """The names in "Chairman Grover and Supervisor Simon" or "O’Brien, Monteith and Mayfield", as printed.

    A part that is not a name ("District 4 Supervisor") comes back as UNKNOWN: somebody is meant and cannot be told.
    """
    parts = [clean(part) for part in re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+", clean(text)) if clean(part)]
    return [printed(part) if re.fullmatch(rf"(?:{_TITLE}\s+)?{_NAME}\.?", part) else UNKNOWN for part in parts]


def roll_index(namings):
    """Where each supervisor is named, from {meeting: (date, [names in a vote], [names as the chair])}:
    {key: (the name most often printed, [days named in a vote], [days named at all])}.

    "In a vote" is short for every place only a supervisor's name can stand: moving, seconding, in a vote's brackets,
    absent at the head, coming or going. "As the chair" is a paragraph that opens "Chairman Grover stated ...".
    """
    forms, voting, at_all = {}, {}, {}
    for date, named, *spoken in namings.values():
        for name in named:
            key = key_of(name)
            if len(key) > 1:
                forms.setdefault(key, Counter())[name] += 1
                voting.setdefault(key, set()).add(date[:10])
        for name in list(named) + (list(spoken[0]) if spoken else []):
            if len(key_of(name)) > 1:
                at_all.setdefault(key_of(name), set()).add(date[:10])
    return {key: (sorted(forms[key].items(), key=lambda form: (-form[1], form[0]))[0][0], sorted(voting[key]), sorted(at_all[key]))
            for key in forms}


def roll_on(date, index):
    """The supervisors on the Board on a day, by the minutes' own naming of them: named that day, or on both an earlier
    and a later day no more than APART_DAYS apart.

    A chair in the last months of a term moves nothing and is absent from nothing, so being named as the chair counts
    too, for someone named in a vote within APART_DAYS of the day. A new supervisor not yet named, and one not named
    again before leaving, are not on the roll; it is then short and nothing is read with it.
    """
    day = day_type.fromisoformat(date[:10])
    apart = lambda seen: abs((day_type.fromisoformat(seen) - day).days)
    roll = []
    for key, (name, voting, at_all) in index.items():
        before = max((seen for seen in at_all if seen <= date[:10]), default=None)
        after = min((seen for seen in at_all if seen >= date[:10]), default=None)
        if before and after and apart(before) + apart(after) <= APART_DAYS and any(apart(seen) <= APART_DAYS for seen in voting):
            roll.append(name)
    return sorted(roll)


def who(name, roll):
    """The supervisor on the roll that a printed name is, or None. An initial alone is one if only one name begins with it."""
    name = clean(name)
    if len(name.rstrip(".")) == 1:
        found = [member for member in roll if re.sub(r"^[A-Z]\. ", "", member).startswith(name[0])]
        return found[0] if len(found) == 1 else None
    key = key_of(printed(name))
    return next((member for member in roll if key_of(member) == key), None)


# ---------------------------------------------------------------------------
# What a motion's line says of the vote
# ---------------------------------------------------------------------------

def notation(rest):
    """What stands between the movers and what was done, as (how, the words after it).

    `how` has: `unanimous` (the line says "unan."), `tally` ((ayes, noes) of "(4-1)", or None), `notes` ([(names as
    printed, the tables' word)] of "(C. Condit opposed)"), `vacant` (seats called vacant) and `printed` (all of it as
    it stands). A bracket that is none of these is the first of the words after ("(VI-C) Accepted ...").
    """
    how = {"unanimous": False, "tally": None, "twice": False, "notes": [], "vacant": 0, "printed": ""}
    at = 0
    while True:
        said = _UNAN.match(rest, at)
        if said:
            how["unanimous"] = True
            at = said.end()
            continue
        bracket = _PAREN.match(rest, at)
        if not bracket:
            break
        inside = bracket[1]
        count = _TALLY.match(inside)
        if count:
            how["twice"] = how["twice"] or how["tally"] is not None
            how["tally"] = (int(count[1]), int(count[2]))
            inside = count[4]  # "(4-1 DeMartini opposed)"
            if not clean(inside):
                at = bracket.end()
                continue
        note = _NOTE.match(clean(inside))
        if not note:
            if count:
                at = bracket.end()  # a count with words after it that say nothing of anyone: the count stands
                continue
            break
        word = note[2].lower()
        if word == "vacant" and _VACANT.match(clean(note[1])):
            how["vacant"] += 1  # "(District Four vacant)"
        elif word == "vacant":
            how["notes"].append(([UNKNOWN], "VACANT"))
        else:
            how["notes"].append((names_in(note[1]) or [UNKNOWN], next(table for stem, table in WORDS if word.startswith(stem))))
        at = bracket.end()
    how["printed"] = clean(rest[:at])
    return how, clean(rest[at:].lstrip(". "))


def decide(how, roll, vacant=0, known=True, away=(), excused=()):
    """Every supervisor's vote on a motion as ([(supervisor, word, established)], ""), or (None, why it cannot be told).

    `roll` is the Board that day; `vacant` the seats the head of the minutes calls vacant; `known` whether the head
    says who was present; `away` those the minutes have out of the room at this point; `excused` those the minutes
    say took no part in this item. Nothing is filled in on a likelihood: each test here is one way the minutes' own
    words could leave a supervisor's vote open.
    """
    seats = SEATS - max(vacant, how["vacant"])
    if len(roll) != seats:
        return None, f"the minutes around this day name {len(roll)} supervisors for {seats} seats"
    if how["twice"]:
        return None, "two counts on one motion"
    cast, seen = [], set()
    for names, word in how["notes"]:
        for name in names:
            member = who(name, roll) if name != UNKNOWN else None
            if member is None:
                return None, f"not on the roll: {name if name != UNKNOWN else 'someone the minutes do not name'}"
            if member in seen:
                return None, f"named twice: {member}"
            seen.add(member)
            cast.append((member, council_tables.vote_word(word), NAMED))
    noes = sum(word == council_tables.NO for _, word, _ in cast)
    rest = [member for member in roll if member not in seen]
    if how["tally"]:
        ayes, against = how["tally"]
        if how["unanimous"] and against:
            return None, f"the line says {ayes}-{against} and unanimous both"
        if noes != against:
            return None, f"the count has {against} against and {noes} are named"
        if ayes + against + (len(cast) - noes) != seats:
            return None, f"{ayes}-{against} and {len(cast) - noes} named as not voting do not make {seats}"
        return cast + [(member, council_tables.AYE, COUNT) for member in rest], ""
    if not how["unanimous"]:
        return None, "neither a count nor unanimous"
    if noes:
        return None, "unanimous, with a supervisor opposed"
    if not known:
        return None, "unanimous, and the head of the minutes does not say who was present"
    out = sorted({name if name == UNKNOWN or who(name, roll) is None else who(name, roll) for name in list(away) + list(excused)} - seen)
    if out:
        return None, "unanimous, and the minutes have " + ", ".join("someone unnamed" if name == UNKNOWN else name for name in out) + " away"
    return cast + [(member, council_tables.AYE, UNANIMOUS) for member in rest], ""


# ---------------------------------------------------------------------------
# Reading a set of minutes
# ---------------------------------------------------------------------------

def head_of(lines):
    """What the head of the minutes says of who was there: (the session's name, the line as printed, whether it says,
    those absent as printed, seats vacant)."""
    session, said, known, away, vacant = "", [], False, [], 0
    for line in lines[:10]:
        words = line["text"].rstrip("*").strip()
        named = _SESSION.match(words)
        if named and not session:
            session = clean(named[1])
        if _ALL_PRESENT.match(words):
            known = True
            said.append(words)
        elif _HEAD_VACANT.match(words):
            known, vacant = True, vacant + 1
            said.append(words)
        elif len(words) < 80 and _ABSENT.match(words) and not _MOTION.match(words):
            known = True
            away.extend(names_in(_ABSENT.match(words)[1]) or [UNKNOWN])
            said.append(words)
    return session, "; ".join(said), known, away, vacant


def starts(words):
    """Whether a line at the head of a page opens a paragraph of its own. A gap cannot be seen there, so the words must say."""
    return bool(_STARTS.match(words) or _CAME.match(words) or _WENT.match(words) or _RECUSED.match(words) or _PARAGRAPH.match(words))


def numbered(text):
    """(the item's number, the rest) of "7.1 Conducted a public hearing ...", or ("", text) where it has none."""
    found = _ITEM.match(text)
    return (clean(found[1]), clean(found[2])) if found and found[2] else ("", text)


def scan(text):
    """A set of minutes as its head and its lines, before anyone in it is taken to be a supervisor.

    A line is a consent calendar (`heading`), an item, or a numbered piece of business with no motion. Each motion
    has its movers and the names in its vote as printed, what it says of the vote (`how`), and who the minutes then
    had out of the room (`away`). `named` is everyone the minutes name where only a supervisor can stand: moving,
    seconding, in a vote, absent, coming or going. `spoken` is whoever a paragraph opens by calling the chair.

    A motion is a paragraph at the margin that opens "Name/Name" and then "unan." or a bracket. The items of a consent
    calendar follow its motion set in from the margin, each opening with its number. The calendar is voted on as one,
    so its vote is on the calendar's line and its items point to it.
    """
    lines = lines_of(text)
    session, present, known, absent, vacant = head_of(lines)
    away, excused, named, spoken, roles = set(absent), {}, [name for name in absent if name != UNKNOWN], [], {}
    out, by_number, part, current, motion, consent, last_numbered = [], {}, "", None, None, None, None

    def line_for(number, title, heading=False, section=None):
        line = {"heading": heading, "number": number, "title": title, "section": section, "motions": []}
        out.append(line)
        return line

    for at, row in enumerate(lines):
        words, set_in = row["text"], row["indent"] >= SET_IN
        for office, name in _ROLE.findall(words):
            roles[printed(name)] = office
        if row["gap"] and not set_in and _SPOKEN.match(words):
            spoken.append(printed(_SPOKEN.match(words)[1]))
        if part in ("consent", "listed"):
            if set_in:
                item = _ITEM.match(words)
                if item and item[2]:
                    current = line_for(clean(item[1]), clean(item[2]), section=consent)
                    part = "listed"
                elif part == "listed":
                    current["title"] = clean(current["title"] + " " + words)
                else:
                    motion["text"] = clean(motion["text"] + " " + words)
                continue
            if part == "consent" and not row["gap"] and not _MOTION.match(words):
                motion["text"] = clean(motion["text"] + " " + words)  # the calendar's own words run on at the margin
                continue
            part = ""
        found = None if set_in else _MOTION.match(words)
        how, said = notation(found["rest"]) if found else (None, "")
        if found and (how["unanimous"] or how["tally"] or how["notes"] or how["vacant"]):
            mover, seconder = printed(found["mover"]), printed(found["seconder"])
            named.extend(name for name in (mover, seconder) if len(key_of(name)) > 1)
            named.extend(name for names, _ in how["notes"] for name in names if name != UNKNOWN)
            number, title = numbered(said)
            motion = {"mover": mover, "seconder": seconder, "how": how, "text": said, "prefix": clean(found["prefix"] or ""),
                      "away": sorted(away), "number": number}
            nth = re.match(_NTH, motion["prefix"])
            if _CONSENT.match(title):
                consent = current = line_for("", "Consent calendar", heading=True)
                part = "consent"
            else:
                if number and number in by_number:
                    current = by_number[number]  # a second motion on an item
                elif nth and not number and last_numbered is not None and last_numbered is out[-1]:
                    current = last_numbered  # "First Vote:", "Second Vote:" under the item they are votes on
                else:
                    current = line_for(number, title)
                    if number:
                        by_number[number] = current
                if nth and not number:
                    last_numbered = current
                part = "motion"
            current["motions"].append(motion)
            continue
        if part in ("motion", "paragraph") and not row["gap"] and not (row["top"] and starts(words)):
            if part == "motion":
                motion["text"] = clean(motion["text"] + " " + words)
                if len(current["motions"]) == 1 and not current["heading"]:
                    current["title"] = numbered(motion["text"])[1]
            else:
                current["title"] = clean(current["title"] + " " + words)
            continue
        part = ""
        if set_in:
            continue
        came, went, recused = _CAME.match(words), _WENT.match(words), _RECUSED.match(words)
        if came or went:
            names = names_in((came or went)["who"])
            named.extend(name for name in names if name != UNKNOWN)
            away = away - set(names) if came else away | set(names)
            if came:
                excused = {name: items for name, items in excused.items() if name not in names}
            continue
        if recused:
            # "Supervisor Withrow recused himself from Item 8.1": the item's own line says so too as a rule. If it
            # does not, a bare "unan." on that item is not read. With no item named, he is out until he is back.
            if "closed session" not in recused["rest"].lower():
                items = re.findall(rf"{_NUMBER_OF}|\d{{1,2}}\.[A-Z]\.\d{{1,2}}[a-z]?|\*?[A-Z]\d{{1,2}}[a-z]?", recused["rest"])
                for name in names_in(recused["who"]):
                    if items:
                        excused.setdefault(name, set()).update(items)
                    else:
                        away.add(name)
            continue
        paragraph = _PARAGRAPH.match(words)
        if paragraph:
            current = line_for(clean(paragraph[1]), clean(paragraph[2]))
            by_number.setdefault(current["number"], current)
            last_numbered, part = current, "paragraph"
    for line in out:
        for one in line["motions"]:
            one["excused"] = sorted(name for name, items in excused.items() if one["number"] in items)
    return {"session": session, "present": present, "known": known, "vacant": vacant, "lines": out,
            "named": sorted(set(named)), "spoken": sorted(set(spoken)), "roles": roles}


def slug(number):
    return re.sub(r"[^A-Za-z0-9]+", "", number)


def read_meeting(meeting, scanned, roll, pages=0):
    """One meeting's minutes against the Board of that day: its lines, the votes on each motion that could be read
    whole, and what the reading found."""
    meeting_id, date = meeting["meeting_id"], meeting["date"]
    roles = {member: scanned["roles"][name] for name in scanned["roles"] for member in [who(name, roll)] if member}
    facts = {"minutes": "read", "pages": pages, "name": scanned["session"], "present": scanned["present"],
             "seats": SEATS - scanned["vacant"],
             "roll": json.dumps([{"name": member, "role": roles.get(member, "")} for member in roll], ensure_ascii=False, separators=(",", ":")),
             "named": json.dumps(scanned["named"], ensure_ascii=False, separators=(",", ":")),
             "spoken": json.dumps(scanned["spoken"], ensure_ascii=False, separators=(",", ":")), "motions": 0, "motions_read": 0}
    agenda, votes, used, calendars, loose = [], [], set(), 0, 0
    for line in scanned["lines"]:
        if line["heading"]:
            calendars += 1
            base = f"{meeting_id}-c{calendars}"
        elif line["number"] and slug(line["number"]):
            base = f"{meeting_id}-{slug(line['number'])}"
        else:
            loose += 1
            base = f"{meeting_id}-u{loose}"
        item_id, again = base, 1
        while item_id in used:  # a number the minutes use twice
            again += 1
            item_id = f"{base}-{again}"
        used.add(item_id)
        line["item_id"] = item_id
    for sequence, line in enumerate(scanned["lines"], 1):
        item_id, heading = line["item_id"], line["heading"]
        matter_id = "" if heading else item_id
        for number, motion in enumerate(line["motions"], 1):
            cast, problem = decide(motion["how"], roll, scanned["vacant"], scanned["known"], motion["away"], motion["excused"])
            motion.update(cast=cast or [], read=cast is not None, problem=problem,
                          moved=who(motion["mover"], roll) or "", seconded=who(motion["seconder"], roll) or "")
            for member, word, established in motion["cast"]:
                votes.append({"item_id": item_id, "meeting_id": meeting_id, "date": date, "matter_id": matter_id, "matter_file": "",
                              "member": member, "vote": word, "motion": number, "motion_text": motion["text"],
                              "established": established})
        last = line["motions"][-1] if line["motions"] else None
        cast = [word for _, word, _ in last["cast"]] if last else []
        ways = sorted({established for motion in line["motions"] for _, _, established in motion["cast"]} - {NAMED})
        title = clean(line["title"])
        text = last["text"] if last else title
        numbered_as, department = _NUMBER.search(text), _DEPARTMENT.search(title)
        section = line["section"]
        agenda.append({
            "item_id": item_id, "meeting_id": meeting_id, "date": date, "body": BODY,
            "agenda_number": line["number"], "sequence": sequence, "matter_id": matter_id, "matter_file": "", "title": title,
            "action": text,
            "result": "Fail" if last and _FAILED.search(last["text"][:200]) else "",  # a motion that carried is not marked
            "mover": last["moved"] if last else "", "seconder": last["seconded"] if last else "",
            "ayes": cast.count(council_tables.AYE), "noes": cast.count(council_tables.NO),
            "not_voting": sum(word not in (council_tables.AYE, council_tables.NO) for word in cast),
            "heading": heading,
            "section": section["title"] if section else "", "section_id": section["item_id"] if section else "",
            "motions": len(line["motions"]), "motions_read": sum(motion["read"] for motion in line["motions"]),
            "votes_read": all(motion["read"] for motion in line["motions"]) if line["motions"] else None,
            "problem": next((motion["problem"] for motion in line["motions"] if not motion["read"]), ""),
            "how": last["how"]["printed"] if last else "",
            "established": ways[0] if len(ways) == 1 else "",
            "voted_with": item_id if line["motions"] else section["item_id"] if section else "",
            "doc_type": "" if heading else numbered_as[1].lower() if numbered_as else county.doc_type_of(text),
            "subject": "" if heading or not department else clean(department[1]),
            "number": clean(numbered_as[2]) if numbered_as else "",
            "motion_log": json.dumps([{"motion": number, "action": motion["text"], "mover": motion["mover"], "seconder": motion["seconder"],
                                       "how": motion["how"]["printed"], "read": motion["read"], "problem": motion["problem"]}
                                      for number, motion in enumerate(line["motions"], 1)], ensure_ascii=False, separators=(",", ":")),
        })
        facts["motions"] += len(line["motions"])
        facts["motions_read"] += sum(motion["read"] for motion in line["motions"])
    return agenda, votes, facts


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------

def items_table(agenda, meetings):
    """Every item in the minutes read, with what was done with it: by a vote of its own, or by its consent calendar's.

    The site has no record of an item apart from its line in the minutes, so an item is here once for each meeting
    it came to.
    """
    of, minutes = agenda.set_index("item_id"), dict(zip(meetings["meeting_id"], meetings["minutes_url"]))
    rows = []
    for line in agenda[~agenda["heading"]].itertuples(index=False):
        own = line.motions > 0
        over = of.loc[line.voted_with] if not own and line.voted_with else None
        vote = line._asdict() if own else over.to_dict() if over is not None else None
        rows.append({
            "date": line.date, "matter_id": line.item_id, "matter_file": "", "doc_type": line.doc_type, "title": line.title,
            "body": line.body, "status": "", "year": int(line.date[:4]), "subject": line.subject, "agenda_date": line.date,
            "passed_date": "", "last_action": line.action, "last_action_date": line.date, "result": line.result,
            "ayes": int(vote["ayes"]) if vote else 0, "noes": int(vote["noes"]) if vote else 0,
            "mover": vote["mover"] if vote else "", "seconder": vote["seconder"] if vote else "",
            "times_on_agenda": 1, "url": minutes.get(line.meeting_id, ""),
            "item_id": line.item_id, "meeting_id": line.meeting_id, "section": line.section,
            "action_on": "item" if own else "section" if over is not None else "",
            "votes_read": bool(vote["votes_read"]) if vote else None,
            "number": line.number,
        })
    out = pd.DataFrame(rows, columns=ITEM_COLUMNS)
    out["votes_read"] = out["votes_read"].astype("boolean")
    return out.sort_values(["date", "meeting_id", "matter_id"], ascending=[False, False, True]).reset_index(drop=True)


def members_table(votes, meetings):
    """Everyone with a vote here. The minutes give no districts and no terms of office. `serving` is true for those on
    the roll of the newest meeting whose roll is whole, and `role` is the office the minutes of that year last gave them."""
    read = meetings[meetings["roll"] != ""].sort_values("date")
    newest, newest_date, offices = [], "", {}
    for meeting in read.itertuples(index=False):
        roll = json.loads(meeting.roll)
        if len(roll) == meeting.seats:
            if newest and meeting.date[:4] != newest_date[:4]:
                offices = {}  # the chair is chosen for a year
            newest, newest_date = roll, meeting.date
            offices.update({member["name"]: member["role"] for member in roll if member["role"]})
    serving = {member["name"] for member in newest}
    cast = votes.groupby("member")["date"].agg(["min", "max", "size"]) if len(votes) else pd.DataFrame()
    rows = [{"name": name, "district": None, "role": offices.get(name, "") if name in serving else "", "start": "", "end": "",
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
    for table, columns in ((agenda, ("sequence", "ayes", "noes", "not_voting", "motions", "motions_read")), (votes, ("motion",))):
        for column in columns:
            table[column] = table[column].astype(int)
    agenda["heading"] = agenda["heading"].astype(bool)
    agenda["votes_read"] = agenda["votes_read"].astype("boolean")
    return agenda, votes


FACTS = (("minutes", ""), ("pages", 0), ("name", ""), ("present", ""), ("seats", 0), ("roll", ""), ("named", ""), ("spoken", ""),
         ("motions", 0), ("motions_read", 0))


def build(base, everything, out_dir, since=FIRST_YEAR, limit=0):
    rows = listed(since)
    log.info(f"Stanislaus County: {len(rows)} meetings listed")
    if len(rows) < 20:
        raise RuntimeError("the listing of meetings came back nearly empty")
    meetings = meetings_table(rows)

    agenda, votes, before_meetings = (council_tables.held(HF_REPO, out_dir, name, base) for name in ("agenda_items", "votes", "meetings"))
    before = 0 if votes is None else len(votes)
    if agenda is None or votes is None or before_meetings is None:
        agenda, votes = pd.DataFrame(columns=AGENDA_COLUMNS), pd.DataFrame(columns=VOTE_COLUMNS)
        before_meetings = pd.DataFrame(columns=MEETING_COLUMNS)
    found = {row["meeting_id"]: {name: row.get(name, empty) for name, empty in FACTS}
             for row in before_meetings[before_meetings["minutes"] != ""].to_dict("records")}
    recent = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    kept = lambda row: (Path(out_dir) / "text" / f"{row['meeting_id']}.txt").exists()
    with_minutes = [row for row in meetings.to_dict("records") if row["minutes_url"] and row["date"] >= f"{since}-01-01"]
    wanted = [row for row in with_minutes if row["date"] >= recent or (not kept(row) and (everything or row["meeting_id"] not in found))]
    wanted.sort(key=lambda row: (row["date"], row["meeting_id"]), reverse=True)  # the newest first: a room shows those
    waiting = len(wanted)
    wanted = wanted[:limit] if limit else wanted
    log.info(f"Fetching the minutes of {len(wanted)} meetings of {waiting} not yet read or to be read again")

    # First the text of each, which is the only part that asks anything of the site. It is kept as it comes, so a
    # run that is stopped has lost nothing.
    fetched = 0
    for start in range(0, len(wanted), 40):
        some = wanted[start:start + 40]
        texts = county.together(lambda row: text_of(row, out_dir, fresh=row["date"] >= recent), some, "minutes")
        fetched += sum(text is not None for text in texts)
        log.info(f"Stanislaus County: {min(start + 40, len(wanted))} of {len(wanted)} minutes asked for")
        if _refused.is_set():
            log.error("The host refused a request: no more is asked of it in this run")
            break

    # Then every set of minutes whose text is here is read, old and new: who is on the Board on a day depends on the
    # minutes before and after it, so a meeting read before its neighbours were may read differently now.
    scans = {}
    namings = {meeting_id: (meeting_id[:10], json.loads(facts["named"] or "[]"), json.loads(facts.get("spoken") or "[]"))
               for meeting_id, facts in found.items()}
    for row in with_minutes:
        if not kept(row):
            continue
        text = text_of(row, out_dir)
        pages = text.count("\f") + 1
        if len(re.sub(r"\s", "", text)) < LAYER_CHARS:
            found[row["meeting_id"]] = {**dict(FACTS), "minutes": "no text layer", "pages": pages}
            scans[row["meeting_id"]] = None
            continue
        scans[row["meeting_id"]] = (row, scan(text), pages)
        namings[row["meeting_id"]] = (row["date"], scans[row["meeting_id"]][1]["named"], scans[row["meeting_id"]][1]["spoken"])
    index = roll_index(namings)
    new_agenda, new_votes = [], []
    for meeting_id, scanned in scans.items():
        if scanned is None:
            continue
        row, minutes, pages = scanned
        reading = read_meeting(row, minutes, roll_on(row["date"], index), pages)
        new_agenda.extend(reading[0])
        new_votes.extend(reading[1])
        found[meeting_id] = reading[2]
    agenda = joined(agenda[~agenda["meeting_id"].isin(set(scans))], pd.DataFrame(new_agenda, columns=AGENDA_COLUMNS))
    votes = joined(votes[~votes["meeting_id"].isin(set(scans))], pd.DataFrame(new_votes, columns=VOTE_COLUMNS))
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
    ways = votes["established"].value_counts() if len(votes) else {}
    facts = {
        "repo": HF_REPO, "first_meeting": read["date"].min() if len(read) else "", "last_meeting": read["date"].max() if len(read) else "",
        "first_vote": votes["date"].min() if len(votes) else "", "last_vote": votes["date"].max() if len(votes) else "",
        "n_read": f"{len(read):,}", "n_scans": f"{int((meetings['minutes'] == 'no text layer').sum()):,}",
        "n_motions": f"{motions:,}", "n_motions_read": f"{motions_read:,}", "n_unread": f"{motions - motions_read:,}",
        "share_read": f"{100 * motions_read / motions:.1f}" if motions else "0", "recent_days": RECENT_DAYS, "first_year": FIRST_YEAR,
        **{f"n_{way}": f"{int(ways.get(way, 0)):,}" for way in (NAMED, COUNT, UNANIMOUS)},
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
        log.error(f"Stanislaus County tables not uploaded: {e}")
        return False
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the Stanislaus County Board's meetings, actions and votes")
    parser.add_argument("--base", action="store_true", help="start from the tables written here, not the published ones")
    parser.add_argument("--all", action="store_true", help="fetch every set of minutes whose text is not kept here")
    parser.add_argument("--since", type=int, default=FIRST_YEAR, help="read no meeting before this year")
    parser.add_argument("--max", type=int, default=0, help="minutes to fetch in one run (0 for all)")
    parser.add_argument("--out", default="", help="directory to write the tables into (minutes_pdf/stanislaus-county if not given)")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the tables only")

    out_dir = Path(args.out) if args.out else OUT_DIR
    try:
        tables, fetched = build(args.base, args.all, out_dir, args.since, args.max)
    except Exception as e:
        log.error(f"Stanislaus County tables not built: {type(e).__name__}: {e}")
        return 1
    pushed = False if args.no_upload else upload(tables, out_dir, args.write_card)
    meetings, agenda, votes, members = tables["meetings"], tables["agenda_items"], tables["votes"], tables["members"]
    motions, motions_read = int(agenda["motions"].sum()), int(agenda["motions_read"].sum())
    ways = votes["established"].value_counts() if len(votes) else {}
    log.info(f"RESULT: stanislaus-county items={len(tables['items'])} meetings={len(meetings)} "
             f"meetings_with_minutes={int((meetings['minutes_url'] != '').sum())} "
             f"minutes_read={int((meetings['minutes'] == 'read').sum())} "
             f"no_text_layer={int((meetings['minutes'] == 'no text layer').sum())} agenda_items={len(agenda)} "
             f"votes={len(votes)} motions={motions} motions_read={motions_read} motions_unread={motions - motions_read} "
             f"named={int(ways.get(NAMED, 0))} count={int(ways.get(COUNT, 0))} unanimous={int(ways.get(UNANIMOUS, 0))} "
             f"members={len(members)} serving={int(members['serving'].sum())} minutes_fetched={fetched} "
             f"first_vote={votes['date'].min() if len(votes) else ''} last_vote={votes['date'].max() if len(votes) else ''} "
             f"refused={_refused.is_set()} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
