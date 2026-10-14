#!/usr/bin/env python3
"""
Build chrissoria/sierra-county-board: the meetings of the Sierra County Board
of Supervisors, what was on each agenda, what the Board did with it, and how
each supervisor voted.

One source: the County's own site (sierracounty.ca.gov/AgendaCenter, the
Board of Supervisors' category). It lists the meetings of a year on one page
and keeps, for each, the agenda as a page of HTML and the minutes as a PDF.
The agenda gives the lines: a number, a title, and how far in the line stands
(1. a section, 6.A. an item, 11.B.i. a part of one). A vote is recorded nowhere
but in the minutes, so what was done and who voted are read from the minutes'
text and set on the agenda's lines by the item's number, never by its place:
the minutes take the consent agenda first and the timed items when they came.

The minutes print a roll at their head, with each supervisor's district:

    ROLL CALL
    Present:  Lee Adams, Supervisor, Chair, District #1
              Lila Heuer, Supervisor, Vice Chair, District #2
              ...
    Absent:   Sharon Dryden, Supervisor, District #5

and under an item what was done, who moved and seconded, and a count:

    ADOPTED, Resolution 2019-103. Motion: Adams/Dryden/Unanimous Roll Call Vote: 5/0
    APPROVED. Motion: Huebner/Roen/Majority Roll Call Vote: 4/1 (Supervisor Beard NO)
    FAILED. Motion: Heuer/Adams/Failed Roll Call Vote: 2/2/1 (Supervisors LeBlanc and
    Dryden NO and Supervisor Roen ABSENT)

The count is ayes/noes, and after them how many did not vote. The line names
only those who did not vote aye. So the ayes are worked out: everyone the roll
has present, less anyone the line names. A motion is read only if that comes
to the count as printed (the ayes, the noes, and the third number where there
is one) and every name on the line, the mover's and seconder's too, is on the
roll of those minutes. `established` on each vote says how it is known:
`named` for a supervisor the line names, `count` for the rest.

A motion is read whole or not at all. One that is not read stays in
agenda_items with what stopped it (`problem`) and has no rows in votes.

The consent agenda is passed by one motion, printed at the head of the minutes
before the list of its items. That vote is on the consent agenda's own line,
and the items the minutes list under it point to it. An item taken off the
consent agenda is not in that list; if the Board took it up, the minutes give
it a new number in the regular agenda, and it is a line of its own here.

The dataset has the five tables every council's and board's dataset has
(council_tables.py), in data/:
  items.parquet          every item on the agenda of a meeting whose minutes were read
  meetings.parquet       one row per meeting of the Board listed
  agenda_items.parquet   one row per line of an agenda, with what was done
  votes.parquet          one row per supervisor and motion voted on
  members.parquet        one row per supervisor with votes here
They are kept here in minutes_pdf/sierra-county/, with the text of each set of
minutes and the lines of each agenda beside them in text/, so a document is
fetched once.

Two ways to run it:

    python build_sierra_board.py
        The routine run. Starts from the published tables, lists every meeting
        again (a request a year), and fetches the agendas and minutes not read
        before and those of meetings in the last 90 days (an agenda is amended
        and minutes are posted after the meeting).

    python build_sierra_board.py --base
        The same, starting from the tables written here. It fetches the newest
        meetings first and can be stopped and started again. Every document
        kept here is read again on each run; that takes no request.

    --since YEAR  read no meeting before this year (default 2013, where the listing begins)
    --max N       meetings to fetch in one run (default 0, for all)
    --all         fetch every document not kept here, read before or not
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

import pandas as pd
import requests

import build_federal_bills as bills
import build_sd_county as county
import council_tables
from build_sd_county import clean, today

log = logging.getLogger(__name__)

HF_REPO = "chrissoria/sierra-county-board"
OUT_DIR = bills.SCRIPT_DIR / "minutes_pdf" / "sierra-county"
CARD_FILE = bills.SCRIPT_DIR / "README_sierra_board.md"
TABLES = council_tables.TABLES
BODY = "Board of Supervisors"

SITE = "https://www.sierracounty.ca.gov"
CATEGORY = 5  # the Board of Supervisors in the County's AgendaCenter; its committees and commissions have others
LISTING = f"{SITE}/AgendaCenter/Board-of-Supervisors-{CATEGORY}"
FIRST_YEAR = 2013  # the listing begins in June 2013
RECENT_DAYS = 90  # meetings this recent are fetched again
SERVING_DAYS = 120  # a supervisor whose last vote is this recent is taken to be serving
LAYER_CHARS = 200  # minutes with fewer characters of their own than this are a scan
UNMAPPED = 0.02  # minutes with this share of characters the PDF gives no letter for are not legible
PAUSE = 0.7  # seconds after each request
INDENT = 6  # points to one space of a line's distance in from the margin
LABEL_NEAR = 9  # a label of the roll ("Absent:") this many points above or below a name is on that name's line

MEETING_COLUMNS = council_tables.COLUMNS["meetings"] + [
    "name", "kind", "cancelled", "packet_url", "video_url", "agenda", "minutes", "pages", "session", "roll", "motions",
    "motions_read"]
AGENDA_COLUMNS = council_tables.COLUMNS["agenda_items"] + [
    "heading", "level", "section", "section_id", "time", "description", "subject", "source", "motions", "motions_read",
    "votes_read", "problem", "outcome", "how", "voted_with", "moved_from", "moved_to", "doc_type", "number", "motion_log"]
VOTE_COLUMNS = council_tables.COLUMNS["votes"] + ["motion", "motion_text", "established"]
ITEM_COLUMNS = council_tables.COLUMNS["items"] + ["item_id", "meeting_id", "section", "action_on", "votes_read", "number"]

# How a vote came to be known: the line names the supervisor, or the supervisor is one of the ayes the count leaves.
NAMED, COUNT = "named", "count"
# Some minutes put the numbers after the ayes in another order ("4/1/0 (Supervisor Roen ABSENT)") or count an
# abstention where the noes go ("4/1 (Supervisor Huebner ABSTAINED)"). With this set, such a motion is read when the
# ayes come to the count's first number and everyone the other numbers count is named with a word. Unset, it is not.
ANY_ORDER = True

# The minutes' words for what a supervisor did, and the word the tables have for each.
WORDS = (("NO", council_tables.NO), ("NAY", council_tables.NO), ("OPPOS", council_tables.NO), ("ABSENT", "ABSENT"),
         ("ABSTAIN", "ABSTAIN"), ("ABSTENTION", "ABSTAIN"), ("RECUS", "RECUSED"), ("EXCUSED", "EXCUSED"),
         ("AYE", council_tables.AYE), ("YES", council_tables.AYE))
# Misspellings of a supervisor's surname met in the minutes (as letters only), and the surname as the roll has it.
SPELLED = {"adam": "adams", "leblance": "leblanc", "huenber": "huebner"}
# What the minutes say was done, where the word alone says whether the motion carried.
CARRIED, LOST = ("APPROVED", "ADOPTED"), ("FAILED",)
# Other words the minutes open what was done with. A line in capitals that opens with one of these is not a heading.
DONE_WORDS = CARRIED + LOST + ("DENIED", "CONTINUED", "TABLED", "ACCEPTED", "REJECTED", "RECEIVED", "AUTHORIZED", "WITHDRAWN",
                               "PULLED", "POSTPONED", "REFERRED", "RESCINDED", "WAIVED")


class Refused(Exception):
    """The host answered with a check, a login or a refusal. It is not asked again in this run."""


class NotPDF(Exception):
    """What the listing links as a meeting's minutes is a page of HTML: the site has no file behind the link."""


_refused = threading.Event()
_session = requests.Session()
_CHECK = re.compile(r"captcha|cf-challenge|are you a human|access denied|sign in to continue", re.I)


def fetch(url, tries=4):
    """One answer from the County's site, and a pause after it. A refusal is not tried again, and nothing more is
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
                raise Refused(f"{answer.status_code} from {url.split('?')[0]}")
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

_KEY = re.compile(r"/AgendaCenter/ViewFile/Agenda/(_(\d{2})(\d{2})(\d{4})-(\d+))")
_LINK = re.compile(r'aria-describedby="[^"]*">\s*(.*?)\s*</a>', re.S)
_VIDEO = re.compile(r"/CivicMedia\?VID=\d+")
# Rows of the Board's category that are not meetings of the Board: a recording, a notice that a meeting was adjourned
# to another day, and the meetings of the County Service Areas' board of directors.
_NOT_BOARD = re.compile(r"\baudio\b|\bnotice\b|\bCSA\b|County Service Area", re.I)
_CANCELLED = re.compile(r"cancel", re.I)


def year_url(year):
    """One year of the Board's meetings. The site's search by dates gives it with a plain request; a span of more than
    a year comes back as its last year only."""
    return f"{SITE}/AgendaCenter/Search/?term=&CIDs={CATEGORY},&startDate=01/01/{year}&endDate=12/31/{year}&dateRange=&dateSelector="


def clock(hour):
    """An hour as every board's table has it: "9:00 AM" for the County's "9:00 a.m." and "10:00AM"."""
    found = re.search(r"(\d{1,2}:\d{2})\s*([ap])\.?\s*m\b\.?", clean(hour), re.I)
    return f"{found[1]} {found[2].upper()}M" if found else ""


def rows_of(page):
    """The Board's meetings on one year's page, as the site has them. A meeting is known by the number the
    AgendaCenter gives it: the 1024 of `_09152026-1024`."""
    rows = []
    for row in re.split(r'<tr id="row', page)[1:]:
        key = _KEY.search(row)
        if not key:
            continue
        link = _LINK.search(row)
        name = clean(html.unescape(re.sub(r"<[^>]+>", " ", link[1]))) if link else ""
        if _NOT_BOARD.search(name):
            continue
        video = _VIDEO.search(row)
        rows.append({
            "meeting_id": key[5], "date": f"{key[4]}-{key[2]}-{key[3]}", "name": name,
            "kind": "special" if "special" in name.lower() else "regular", "cancelled": bool(_CANCELLED.search(name)),
            "html": f"{key[1]}?html=true" in row, "agenda": f"{SITE}/AgendaCenter/ViewFile/Agenda/{key[1]}",
            "minutes": f"{SITE}/AgendaCenter/ViewFile/Minutes/{key[1]}" if f"/AgendaCenter/ViewFile/Minutes/{key[1]}" in row else "",
            "packet": f"{SITE}/AgendaCenter/ViewFile/Agenda/{key[1]}?packet=true" if f"{key[1]}?packet=true" in row else "",
            "video": SITE + video[0] if video else "",
        })
    return rows


def listed(first=FIRST_YEAR, last=None):
    """Every meeting of the Board the site lists from `first` on, a year to a request."""
    last = last or datetime.now(timezone.utc).year
    rows = {}
    for year in range(max(first, FIRST_YEAR), last + 1):
        for row in rows_of(fetch(year_url(year)).text):
            rows[row["meeting_id"]] = row
    return list(rows.values())


def meetings_table(rows):
    """One row per meeting listed. What a reading adds (the hour, the place, `agenda`, `minutes`, `roll` and the
    counts) is filled in by build()."""
    out = [{
        "meeting_id": row["meeting_id"], "date": row["date"], "time": "", "body": BODY, "location": "", "url": LISTING,
        "agenda_url": row["agenda"] + ("?html=true" if row["html"] else ""), "minutes_url": row["minutes"], "items": 0,
        "name": row["name"], "kind": row["kind"], "cancelled": row["cancelled"], "packet_url": row["packet"],
        "video_url": row["video"], "agenda": "", "minutes": "", "pages": 0, "session": "", "roll": "", "motions": 0,
        "motions_read": 0,
    } for row in rows]
    out = pd.DataFrame(out, columns=MEETING_COLUMNS)
    out["cancelled"] = out["cancelled"].astype(bool)
    order = sorted(range(len(out)), key=lambda at: (out["date"].iloc[at], int(out["meeting_id"].iloc[at])))
    return out.iloc[order].reset_index(drop=True)


# ---------------------------------------------------------------------------
# An agenda
# ---------------------------------------------------------------------------

_LINE = re.compile(r'<div class="item level(\d)">(.*?)(?=<div class="item level\d">|\Z)', re.S)
_BULLET = re.compile(r'<div class="bullet">\s*<span>(.*?)</span>', re.S)
_AT = re.compile(r'<span class="time">(.*?)</span>', re.S)
_TITLE = re.compile(r'<(\w+) class="title">(.*?)</\1>', re.S)
_DESCRIPTION = re.compile(r'<div class="desc">(.*?)</div>\s*<div class="documents">', re.S)
# "will meet in regular session commencing at 9:00 a.m. on June 18, 2019 in the Loyalton Social Hall, ..., Loyalton, CA."
# and "met in a special teleconference meeting held at 9:00 a.m. on Tuesday, September 24, 2013."
_HELD = re.compile(r"\b(?:will\s+meet|met)\s+in\s+(?:an?\s+)?[A-Za-z ]+?\s+(?:session|meeting),?\s+(?:commencing|held)\s+at\s+(?P<hour>\d{1,2}:\d{2}\s*[ap]\.?\s*m\.?),?"
                   r"\s+on\s+(?:[A-Z][a-z]+day,?\s+)?(?P<day>[A-Z][a-z]+\s+\d{1,2},\s*\d{4}),?\s*(?:(?:in|at)\s+(?P<place>.{3,160}?(?:,\s*(?:CA|California)\b|\.(?=\s|$))))?", re.S)


def words_of(markup):
    """What a piece of a page says, without its tags. The parts of a list are parted by semicolons."""
    markup = re.sub(r"</li>\s*<li[^>]*>", "; ", markup)
    return clean(html.unescape(re.sub(r"<[^>]+>", " ", markup))).replace("\xad", "")


def held_at(text):
    """(the hour, the place, the day) a meeting was called for or held at, from the sentence that opens its agenda and
    its minutes. The day is "" where the sentence gives none that can be read."""
    found = _HELD.search(clean(text))
    if not found:
        return "", "", ""
    place = re.sub(r"^the\s+", "", clean(found["place"] or "").rstrip("."))
    try:
        day = datetime.strptime(re.sub(r"\s+", " ", found["day"].replace(",", ", ")), "%B %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        day = ""
    return clock(found["hour"]), place, day


def agenda_of(page):
    """An agenda as {time, location, lines}. Each line has its number as printed ("6.A."), how far in it stands
    (1 a section, 2 an item, 3 a part of an item), its title, an hour if it was set for one, and what the agenda
    says under it."""
    hour, place, _ = held_at(words_of(page[:page.find('<div class="item level')] if '<div class="item level' in page else page))
    lines = []
    for level, piece in _LINE.findall(page):
        bullet, title, at, description = _BULLET.search(piece), _TITLE.search(piece), _AT.search(piece), _DESCRIPTION.search(piece)
        lines.append({"number": words_of(bullet[1]) if bullet else "", "level": int(level), "title": words_of(title[2]) if title else "",
                      "time": clock(words_of(at[1])) if at else "", "description": words_of(description[1]) if description else ""})
    return {"time": hour, "location": place, "lines": lines}


def agenda_kept(meeting, out_dir, fresh=False):
    """A meeting's agenda, from the copy kept here, or fetched and kept."""
    kept = Path(out_dir) / "text" / f"{meeting['meeting_id']}.agenda.json"
    if kept.exists() and not fresh:
        return json.loads(kept.read_text(encoding="utf-8"))
    agenda = agenda_of(fetch(meeting["agenda_url"]).text)
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(json.dumps(agenda, ensure_ascii=False, indent=0), encoding="utf-8")
    return agenda


# ---------------------------------------------------------------------------
# The text of a set of minutes
# ---------------------------------------------------------------------------

_LABEL_ALONE = re.compile(r"^(?:Present|Absent|Staff)\s*:$", re.I)
_LONG_DATE = re.compile(r"^(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s*\d{4}$", re.I)


def labelled(lines):
    """A page's lines with each label of the roll on the line of the name it stands beside.

    The roll is two columns, the labels (Present:, Absent:, Staff:) and the names. In some minutes a label is set a
    few points above or below its name and comes out as a line of its own, so that the plain order of the lines no
    longer says whether a name is under "Absent:" or over it. Where each stands on the page does.
    """
    out = [dict(line) for line in lines]
    for label in [line for line in out if _LABEL_ALONE.match(line["text"].strip())]:
        beside = [line for line in out if line is not label and not _LABEL_ALONE.match(line["text"].strip())
                  and line["x0"] > label["x1"] - 2 and abs(line["top"] - label["top"]) < LABEL_NEAR]
        if beside:
            name = min(beside, key=lambda line: abs(line["top"] - label["top"]))
            name["text"], name["x0"] = f"{label['text'].strip()} {name['text'].strip()}", label["x0"]
            out.remove(label)
    return out


def pdf_text(body):
    """The text a PDF carries, a page at a time. Nothing is read off the picture of a page.

    A line is set in by one space for every INDENT points it stands in from the margin, since the minutes say with
    that what the words do not: a section and what was done stand at the margin, an item's number is set in, and the
    rest of its title is set in further. The date at the head of a page and the number at its foot are left out.
    """
    import pdfplumber
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    with pdfplumber.open(io.BytesIO(body)) as document:
        pages = [(page.height, labelled(page.extract_text_lines(return_chars=False))) for page in document.pages]
    # The margin is the leftmost place lines begin at, leaving out a stray line or two that stands further left.
    begun = Counter(round(line["x0"]) for _, lines in pages for line in lines)
    enough = max(3, 0.02 * sum(begun.values()))
    margin = min((x for x, count in begun.items() if count >= enough), default=min(begun, default=0))
    out = []
    for height, lines in pages:
        text = []
        for line in lines:
            words = line["text"].strip()
            if (words.isdigit() and line["top"] > 0.85 * height) or (_LONG_DATE.match(words) and line["top"] < 0.1 * height):
                continue
            text.append(" " * max(0, round((line["x0"] - margin) / INDENT)) + words)
        out.append("\n".join(text))
    return out


def text_of(meeting, out_dir, fresh=False):
    """The text of a meeting's minutes, pages parted by form feeds: from the copy kept here, or fetched and kept."""
    kept = Path(out_dir) / "text" / f"{meeting['meeting_id']}.txt"
    if kept.exists() and not fresh:
        return kept.read_text(encoding="utf-8")
    body = fetch(meeting["minutes_url"]).content
    if body[:4] != b"%PDF":
        raise NotPDF("the site sent a page in place of the minutes")
    text = "\n\f".join(pdf_text(body))
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(text, encoding="utf-8")
    return text


def legible(text):
    """Why a set of minutes cannot be read at all, or "": a scan has no text of its own, and some PDFs give numbers
    in place of their letters ("(cid:36)(cid:51)")."""
    plain = re.sub(r"\(cid:\d+\)|\s", "", text)
    if len(plain) < LAYER_CHARS and "(cid:" not in text:
        return "no text layer"
    unmapped = len(re.findall(r"\(cid:\d+\)", text)) + sum(not char.isprintable() for char in plain)
    return "text not legible" if unmapped > UNMAPPED * (len(plain) + unmapped) else ""


def lines_of(text):
    """The minutes' lines in order as (how far each is set in, its words)."""
    return [(len(row) - len(row.lstrip(" ")), clean(row)) for row in text.replace("\f", "\n").split("\n") if row.strip()]


# ---------------------------------------------------------------------------
# Who sits on the Board, and who a name is
# ---------------------------------------------------------------------------

_ROLL = re.compile(r"^ROLL\s+CALL\b", re.I)
_LABEL = re.compile(r"^(Present|Absent|Staff)\s*:\s*(.*)$", re.I)
_SEAT = re.compile(r"^(?P<name>[A-Z][A-Za-z.’' -]+?)\s*,\s*(?P<office>.*?)\bDistrict\s*#?\s*(?P<district>[1-5])\b")
_OFFICE = r"(?:Supervisors?|Vice[- ]?Chair(?:man|woman|person)?|Chair(?:man|woman|person)?)"
_ROLL_ENDS = re.compile(r"^(?:APPROVAL\s+OF\b|REGULAR\s+AGENDA\b|CONSENT\s+AGENDA\b|\d{1,2}\.\s+[A-Z]{2})")
_SUPERVISOR = rf"{_OFFICE},?"


def key_of(name):
    """What two printings of a name share: its letters. "Le Blanc" is "LeBlanc"."""
    return re.sub(r"[^a-z]", "", str(name or "").lower())


def surname(name):
    """The name a motion's line calls a supervisor by: the last word of the name on the roll."""
    return clean(name).split(" ")[-1] if clean(name) else ""


def office_of(words):
    return "Vice-Chair" if re.search(r"vice[- ]?chair", words, re.I) else "Chair" if re.search(r"chair", words, re.I) else ""


def roll_of(lines):
    """The roll at the head of the minutes: (the supervisors, each {name, district, role, present}, where the roll
    ends, why it cannot be used). The supervisors are the lines that give a district; the rest are the staff."""
    start = next((index for index, (_, words) in enumerate(lines) if _ROLL.match(words)), None)
    if start is None:
        return [], 0, "no roll at the head of the minutes"
    roll, under, end = [], "present", start + 1
    for end in range(start + 1, min(len(lines), start + 60)):
        words = lines[end][1]
        if _ROLL_ENDS.match(words):
            break
        if _ROLL.match(words):
            roll, under = [], "present"  # the roll called again, after a site visit: the later one is the meeting's
            continue
        label = _LABEL.match(words)
        if label:
            under, words = label[1].lower(), label[2]
        seat = _SEAT.match(words)
        if seat:
            if under == "staff":
                return roll, end, "a supervisor is listed among the staff"
            # "Chair Adams, Supervisor, Chair, District #1": the office before a name is not part of it.
            name = clean(re.sub(rf"^{_OFFICE}\s+", "", clean(seat["name"])))
            roll.append({"name": name, "district": int(seat["district"]), "role": office_of(seat["name"] + " " + seat["office"]),
                         "present": under != "absent"})
    else:
        end = min(len(lines), start + 60)
    if len(roll) < 3:
        return roll, end, f"the roll names {len(roll)} supervisors"
    if len({member["district"] for member in roll}) != len(roll) or len({key_of(surname(member["name"])) for member in roll}) != len(roll):
        return roll, end, "the roll has a district or a surname twice"
    return roll, end, ""


def who(name, roll):
    """The supervisor on the roll that a motion's line means by a surname, or None."""
    key = key_of(re.sub(rf"^{_SUPERVISOR}\s+", "", clean(name)))
    key = key_of(SPELLED.get(key, key))
    for part in (surname, lambda name: name, lambda name: clean(name).split(" ")[0]):  # a surname; failing that the whole name, or the first
        found = [member["name"] for member in roll if key and key == key_of(part(member["name"]))]
        if found:
            return found[0] if len(found) == 1 else None
    return None


# ---------------------------------------------------------------------------
# What a motion's line says of the vote
# ---------------------------------------------------------------------------

_NAME = r"[A-Z][A-Za-z’'-]+"
# "Motion:" opens the movers. Some lines have "Motion." or "Motion;" there; a sentence that ends "... the motion." does not.
_MARK = re.compile(rf"\bMotion\s*(?:[:;]|\.(?=\s*(?:$|{_NAME}\s*/)))")
# Some lines leave "Motion:" out: "APPROVED, Agreement 2015-086. Adams/Roen/Unanimous Roll Call Vote: 5/0".
_SIGNED = re.compile(rf"(?<![\w/’'-])(?={_NAME}\s*/+\s*{_NAME}\s*/+\s*(?:(?i:unanimous|majority|passed|failed|consensus|tie)\b|Roll\s*Call))")
_MARKED = re.compile(r"\bMotion\s*[:;.]\s*(?:Motion\s*[:;.]\s*)?(?:Roll\s*Call\s*Vote\s*:?\s*)?$")


def moved(words):
    """Whether a line has a motion's movers on it."""
    return bool(_MARK.search(words) or _SIGNED.search(words))


def motions_on(words, above=""):
    """Where the motions on a line begin, as [(where what was done ends, where the movers begin)]. `above` is the
    line before: movers that open a line may be those of a "Motion:" that ends the one above."""
    out = [(mark.start(), mark.end()) for mark in _MARK.finditer(words)]
    for bare in _SIGNED.finditer(words):
        if not _MARKED.search(f"{above} {words[:bare.start()]}".rstrip()):
            out.append((bare.start(), bare.start()))
    return sorted(out)
_VOTE = re.compile(rf"\s*(?:Roll\s*Call\s*Vote\s*:\s*)?(?P<mover>{_NAME})\s*/+\s*(?P<seconder>{_NAME})\s*/*\s*(?P<outcome>(?!Roll\b)[A-Za-z]+)?\.?\s*(?:Roll\s*(?:Call\s*)?Vote)?"
                   r"\s*[:;.,]?\s*(?P<count>\d\s*/+\s*\d(?:\s*/+\s*\d){0,2})?\s*(?P<notes>\([^()]*\))?")
_WORD = r"(?:NO|NOES|NAY|OPPOSED|ABSENT|ABSTAIN(?:ED|ING|S)?|ABSTENTION|RECUSED?|EXCUSED|AYE|YES)"
_NOTE = re.compile(rf"\s*(?:and\s+|[,;/]\s*(?:and\s+)?)?(?P<who>\S.*?)\s+(?:voting\s+|voted\s+|was\s+|were\s+)?(?P<word>{_WORD})\b[.,;]?\s*", re.I)
_DONE = re.compile(r"^[A-Z]{4,}\b")  # what was done opens its line in capitals: APPROVED, ADOPTED, FAILED, DENIED
_NUMBER = re.compile(r"\b(CSA\s+)?(Resolution|Agreement|Ordinance)(\s+CSA)?\s*(?:No\.?\s*|-\s*)?(\d{2,5}\s?-\s?\d{1,4}|\d{1,4})\b", re.I)


def names_in(text):
    """The surnames in "Supervisors LeBlanc and Dryden" or "Supervisor Beard", as printed; None if a part is not a name."""
    text = re.sub(rf"^{_SUPERVISOR}\s+", "", clean(text))
    parts = [re.sub(rf"^{_SUPERVISOR}\s+", "", clean(part)) for part in re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+|\s*&\s*", text) if clean(part)]
    return parts if parts and all(re.fullmatch(rf"{_NAME}(?: {_NAME})?", part) for part in parts) else None


def notes_in(bracket):
    """What the bracket after a count says, as [(surnames as printed, the tables' word)]; None if it cannot be read.

    "(Supervisors LeBlanc and Dryden NO and Supervisor Roen ABSENT)" is [(["LeBlanc", "Dryden"], "NO"), (["Roen"], "ABSENT")].
    """
    inside, out, at = clean(bracket.strip("()")), [], 0
    while at < len(inside):
        found = _NOTE.match(inside, at)
        names = names_in(found["who"]) if found else None
        if not names:
            return None
        out.append((names, next(table for stem, table in WORDS if found["word"].upper().startswith(stem))))
        at = found.end()
    return out or None


def motions_in(rows):
    """The motions among the lines under an item, in order.

    Each has what was done as printed (`action`: "ADOPTED, Resolution 2019-103"), the mover and seconder as printed,
    the word the line gives the vote (`outcome`: Unanimous, Majority, Passed, Failed), the count as numbers, those the
    bracket names (`notes`, None if it could not be read), the line from "Motion:" on as printed (`how`), and the
    Board's motion in words where the paragraph above says it ("The Board moved to adopt the resolution ...").
    """
    out, text = [], [words for _, words in rows]
    for at, (_, words) in enumerate(rows):
        for done, begins_at in motions_on(words, text[at - 1] if at else ""):
            # Some PDFs carry a hyphen inside a word where the typist's page had none: "U‐nanimous".
            tail = re.sub(r"(?<=[A-Za-z])[\u2010\u2011\u00ad](?=[a-z])", "", clean(" ".join([words[begins_at:]] + text[at + 1:at + 4])))
            vote = _VOTE.match(tail)
            if _MARK.match(tail.lstrip()) or (vote and not vote["count"] and _MARK.match(tail[vote.end():].lstrip())):
                continue  # "Motion: Motion: ...", or the movers printed twice: the second printing has the vote
            # What was done opens a line at the margin, in capitals, on the motion's line or a line or two above it.
            first = at
            for line in range(at, max(at - 3, -1), -1):
                if line < at and moved(text[line]):
                    break  # the motion before this one
                if rows[line][0] == 0 and _DONE.match(text[line]):
                    first = line
                    break
            action = re.sub(r"[\s.,;:]*\bMotion$", "", clean(" ".join(text[first:at] + [words[:done]])).rstrip(" .,;:"))
            # The Board's motion in words is the nearest paragraph above that says the Board moved. A paragraph's
            # first line is set in and the rest stand at the margin; where none is set in, it is whatever stands
            # between the item's title and what was done.
            said, foot = "", first
            for line in range(first - 1, max(first - 13, -1), -1):
                if moved(text[line]):
                    break
                if rows[line][0] > 0 or line == 0:
                    paragraph = clean(" ".join(text[line:foot]))
                    if re.search(r"\bmov(?:ed|es?)\b", paragraph, re.I):
                        said = paragraph
                        break
                    foot = line
            motion = {"action": action, "said": said,
                      "mover": vote["mover"] if vote else "", "seconder": vote["seconder"] if vote else "",
                      "outcome": (vote["outcome"] or "") if vote else "", "count": None, "notes": [], "bracket": "",
                      "how": clean(("Motion: " if begins_at > done else "") + (tail[:vote.end()] if vote else tail[:80]))}
            if vote and vote["count"]:
                motion["count"] = tuple(int(number) for number in re.findall(r"\d", vote["count"]))
            if vote and vote["notes"]:
                motion["bracket"], motion["notes"] = vote["notes"], notes_in(vote["notes"])
            out.append(motion)
    return out


def decide(motion, roll, why=""):
    """Every supervisor's vote on a motion as ([(supervisor, word, established)], ""), or (None, why it cannot be told).

    `roll` is the roll at the head of the minutes; `why` is why that roll cannot be used, if it cannot. The line
    names those who did not vote aye, and the ayes are those the roll has present, less anyone named. That must come
    to the count as printed: the ayes, the noes, and where the count has a third number, those who did not vote. A
    supervisor the roll has absent is counted by that third number or not at all: if the count covers them they are
    ABSENT here, and if it leaves them out they have no row. Where the numbers after the ayes are not in that order,
    the motion is read only if every supervisor they count is named with a word (ANY_ORDER).
    """
    if why:
        return None, why
    if not motion["mover"]:
        return None, "the line after Motion: is not movers and a vote"
    if motion["count"] is None:
        return None, "no count on the motion's line"
    if motion["notes"] is None:
        return None, f"the bracket is not read: {motion['bracket'][:60]}"
    for name in (motion["mover"], motion["seconder"]):
        if who(name, roll) is None:
            return None, f"not on the roll: {name}"
    cast, seen = [], set()
    for names, word in motion["notes"]:
        for name in names:
            member = who(name, roll)
            if member is None:
                return None, f"not on the roll: {name}"
            if member in seen:
                return None, f"named twice: {member}"
            seen.add(member)
            cast.append((member, word, NAMED))
    ayes = [member["name"] for member in roll if member["present"] and member["name"] not in seen]
    away = [member["name"] for member in roll if not member["present"] and member["name"] not in seen]
    said_aye = sum(word == council_tables.AYE for _, word, _ in cast)
    noes = sum(word == council_tables.NO for _, word, _ in cast)
    others = len(cast) - noes - said_aye
    count = motion["count"]
    if len(ayes) + said_aye != count[0]:
        return None, f"the count has {count[0]} ayes and the roll and the names give {len(ayes) + said_aye}"
    if motion["outcome"].lower() == "unanimous" and noes:
        return None, "unanimous, with a supervisor named as voting no"
    cast += [(member, council_tables.AYE, COUNT) for member in ayes]
    rest = sum(count[2:])
    if noes == count[1] and (len(count) == 2 or rest in (others, others + len(away))):
        if len(count) > 2 and away and rest == others + len(away):
            cast += [(member, "ABSENT", COUNT) for member in away]  # absent at the head, and the count has them
        return cast, ""
    if ANY_ORDER and noes + others and sum(count[1:]) == noes + others:
        return cast, ""  # "4/1/0 (Supervisor Roen ABSENT)", "4/1 (Supervisor Huebner ABSTAINED)"
    if noes != count[1]:
        return None, f"the count has {count[1]} noes and {noes} are named"
    return None, f"the count has {rest} not voting and the roll and the names give {others + len(away)}"


# ---------------------------------------------------------------------------
# Reading a set of minutes
# ---------------------------------------------------------------------------

# "6.A.", "12.A.i.", "6.", and as the minutes sometimes have them "6 .A.", "7.C..", "13.A" with no full stop after it.
_ITEM = re.compile(r"^(?P<number>\d{1,2}\s?\.(?:\s?[A-Z]{1,2}\s?\.+(?:\s?(?:[ivxl]{1,5}|\d{1,2})\.)?|[A-Z]{1,2}(?=\s))?)\s*(?P<rest>\S.*)$")
_RESUMED = re.compile(r"^Item\s+(?P<number>\d{1,2}\.\s?[A-Z]{1,2})\.?\s*(?:[-–]\s*)?(?:Closed\s+Session\s*[-–]\s*)?continued\b", re.I)
_SECTION = re.compile(r"^(?P<number>\d{1,2})\s+(?P<rest>[A-Z]{2}.*)$")  # a section whose number lost its full stop: "12 CLOSED SESSION"
_TIMED = re.compile(r"^(?P<hour>\d{1,2}:\d{2}\s?[AP]\.?M\.?)\s*(?:[-–]\s*)?(?P<rest>[A-Z].*)$")
_CONSENT_VOTE = re.compile(r"^APPROVAL\s+OF\s+(?:THE\s+)?CONSENT\s+(?:AGENDA|ITEMS?|CALENDAR)\b", re.I)
_REGULAR_VOTE = re.compile(r"^APPROVAL\s+OF\s+(?:THE\s+)?(?:REGULAR\s+)?AGENDA\b", re.I)
_REGULAR = re.compile(r"^REGULAR\s+AGENDA\s*:?$", re.I)
_CONSENT = re.compile(r"\bCONSENT\s+AGENDA\b", re.I)
_CLOSING = re.compile(r"^(?:ATTEST\b|[A-Z][A-Z.’' -]+,\s*(?:VICE[- ]?)?CHAIR(?:MAN|WOMAN|PERSON)?\b)")
_FROM_CONSENT = re.compile(r"\(\s*Consent\s+(?:Agenda\s+)?Item\s+(\d{1,2}\.\s?[A-Z]{1,2})\.?\s*\)", re.I)
_NUMBERS = r"(?:\d{1,2}\.\s?[A-Z]{1,2}\.?(?:\s*,\s*(?:and\s+)?|\s+and\s+)?)+"
# "Consent Items 13.H. and 13.J. were moved to the Regular Agenda as Items 6.C. and 6.D."
_RENUMBERED = re.compile(rf"(?P<was>{_NUMBERS})\s*(?:was|were)\s+moved\s+to\s+the\s+Regular\s+Agenda\s+as\s+(?:Items?\s+)?(?P<now>{_NUMBERS})", re.I)


def number_of(number):
    """An item's number as it is matched by: "13.A." and "13. A" are "13.A"."""
    return re.sub(r"\.{2,}", ".", re.sub(r"\s", "", str(number or ""))).rstrip(".")


def level_of(key):
    return key.count(".") + 1 if key else 0


def order_of(key):
    """Where a number stands among the others: 13.A.ii as (13, 1, 2)."""
    parts, out = key.split("."), []
    for at, part in enumerate(parts):
        if part.isdigit():
            out.append(int(part))
        elif at == 1:
            out.append(sum((ord(letter) - 64) * 26 ** place for place, letter in enumerate(reversed(part.upper()))))
        else:
            values, total = {"i": 1, "v": 5, "x": 10, "l": 50}, 0
            for letter, after in zip(part.lower(), part.lower()[1:] + " "):
                total += -values.get(letter, 0) if values.get(after, 0) > values.get(letter, 0) else values.get(letter, 0)
            out.append(total)
    return tuple(out)


def capitals(words):
    """Whether a line is a heading set in capitals (CLOSED SESSION STATEMENT)."""
    letters = re.sub(r"[^A-Za-z]", "", words)
    return len(letters) >= 6 and letters.isupper() and len(words.split()) >= 2


def begins(found):
    """Whether a line that opens with a number opens an item. A sentence that runs on from the line above can open
    with one too ("6.C. and 6.D.", "7. The Board"): a title opens with a capital or a figure, and a section's title
    with a word in capitals."""
    rest = found["rest"]
    if not (rest[0].isupper() or rest[0].isdigit() or rest[0] in "\"“‘'$("):
        return False
    if level_of(number_of(found["number"])) == 1:
        return bool(re.match(r"(?:\d{1,2}:\d{2}\s?[AP]\.?M\.?\s*(?:[-–]\s*)?)?[A-Z][A-Z&/’'.-]+(?:\s|$)", rest))
    return True


def scan(text):
    """A set of minutes as its head and its blocks, before any vote is worked out.

    The minutes run: the head and the roll; "APPROVAL OF THE CONSENT AGENDA", with the one motion that passed it;
    the consent agenda's number and the list of its items, each with the resolution or agreement it became; "APPROVAL
    OF THE REGULAR AGENDA", with its motion; and the regular agenda, a section at a time. A block is one of those
    two approvals, a numbered line with what is said under it, or a heading with no number. An item printed inside
    an approval is one the Board took off that agenda, shown for the record, and is not an item there.
    """
    lines = lines_of(text)
    roll, end, why = roll_of(lines)
    head = lines[:end] if end else lines[:80]
    hour, place, day = held_at(" ".join(words for _, words in head))
    session = next((words for _, words in head if re.fullmatch(r"[A-Z ]*MEETING", words)), "")
    blocks, current, part, consent = [], None, "", ""

    def begin(kind, number="", title="", indent=0, hour=""):
        nonlocal current
        current = {"kind": kind, "number": number, "key": number_of(number), "title": title, "indent": indent, "time": hour,
                   "listed": part == "consent", "shown": [], "rows": []}
        blocks.append(current)

    for indent, words in lines[end:]:
        if _CLOSING.match(words) and indent == 0:
            break
        if _CONSENT_VOTE.match(words):
            part = "consent vote"
            begin("consent vote", title=words)
            continue
        if _REGULAR_VOTE.match(words):
            part = "regular vote"
            begin("regular vote", title=words)
            continue
        if _REGULAR.match(words):
            # Where the minutes have had no "APPROVAL OF THE REGULAR AGENDA", this heading is where they approve it.
            part = "regular" if any(block["kind"] == "regular vote" for block in blocks) else "regular vote"
            begin("regular vote", title=words)
            continue
        resumed = _RESUMED.match(words)
        if resumed:
            part = "regular"
            begin("line", resumed["number"] + ".", "", indent)  # "Item 8.A. continued from earlier in the meeting."
            continue
        found = _ITEM.match(words) or (_SECTION.match(words) if indent == 0 and capitals(words) else None)
        if found and begins(found):
            key = number_of(found["number"])
            if level_of(key) == 1 and _CONSENT.search(found["rest"]):
                part, consent = "consent", key
                begin("line", found["number"], found["rest"], indent)
                current["listed"] = False
                continue
            if part in ("consent vote", "regular vote") and level_of(key) > 1:
                # An item printed in an approval is one taken off that agenda or added to it, shown for the record.
                # The approval runs on to the next section's line.
                current["shown"].append(key)
                current["rows"].append((indent, words))
                continue
            if part != "consent" or not key.startswith(consent + "."):
                part = "regular"
            begin("line", found["number"], found["rest"], indent)
            continue
        timed = _TIMED.match(words) if indent == 0 else None
        if timed and capitals(timed["rest"]):
            part = "regular" if part.endswith("vote") else part
            begin("heading", title=timed["rest"], hour=clock(timed["hour"]))
            continue
        if (indent == 0 and capitals(words) and not re.search(r"\d|\.$", words) and words.split()[0].strip(".,:;") not in DONE_WORDS
                and not moved(words)):
            # A heading of the minutes' own: SELECTION OF VICE-CHAIR, CLOSED SESSION STATEMENT.
            part = "regular" if part.endswith("vote") else part
            begin("heading", title=words)
            continue
        if current is None:
            begin("heading")  # what is said before the first heading
        current["rows"].append((indent, words))

    for block in blocks:
        rows = block["rows"]
        if block["kind"] == "line":
            # The rest of a title is set in further than its first line; what is said of the item is not.
            more, section = 0, level_of(block["key"]) == 1
            while (more < len(rows) and rows[more][0] > block["indent"] and not moved(rows[more][1])
                   and (not section or not re.search(r"[a-z]", rows[more][1]))):
                more += 1
            title = clean(" ".join([block["title"]] + [words for _, words in rows[:more]]))
            was = _FROM_CONSENT.search(title)
            block["moved_from"] = number_of(was[1]) if was else ""
            block["title"], rows = clean(_FROM_CONSENT.sub(" ", title)), rows[more:]
        block["motions"] = motions_in(rows)
        # An approval says which items it moved, and to what numbers; they are kept where the two lists pair off.
        block["renumbered"] = []
        if block["kind"].endswith("vote"):
            for found in _RENUMBERED.finditer(clean(" ".join(words for _, words in rows))):
                was, now = (re.findall(r"\d{1,2}\.\s?[A-Z]{1,2}", found[group]) for group in ("was", "now"))
                if len(was) == len(now):
                    block["renumbered"] += [(number_of(old), number_of(new)) for old, new in zip(was, now)]
        # With no motion of its own, what was done is the line in capitals under the item: "ADOPTED, Resolution 2013-080".
        done = next((at for at, (indent, words) in enumerate(rows) if indent == 0 and _DONE.match(words)), None)
        block["done"] = clean(" ".join(words for _, words in rows[done:])) if done is not None and not block["motions"] and block["listed"] else ""
        del block["rows"]
    return {"roll": roll, "why": why, "time": hour, "location": place, "day": day, "session": session, "blocks": blocks, "consent": consent}


def slug(number):
    return re.sub(r"[^A-Za-z0-9]+", "", number)


def person(name):
    """What the printings of one supervisor's name share: the surname and the first letter ("Peter W. Huebner", "Peter Huebner")."""
    return key_of(surname(name)) + ":" + clean(name)[:1].lower()


def names_as(roll, spelling):
    """A roll with each supervisor's name written the one way it is written throughout (`spelling`)."""
    return [{**member, "name": spelling.get(member["name"], member["name"])} for member in roll]


def result_of(motion):
    """Pass or Fail where the minutes' own words say so: FAILED is Fail; APPROVED or ADOPTED, on a motion the line
    calls unanimous, a majority's or passed, is Pass. Anything else (DENIED, a word this reader does not know) is left."""
    done, outcome = re.sub(r"[\u2010\u2011\u00ad]", "", motion["action"]).upper(), motion["outcome"].lower()
    if done.startswith(LOST):
        return "Fail"
    return "Pass" if done.startswith(CARRIED) and outcome in ("unanimous", "majority", "passed") else ""


def numbers_in(text):
    """The resolutions, agreements and ordinances a line's action names: "Resolution 2021-059; Agreement 2021-037".
    Those of the County Service Areas' board are numbered apart and keep their "CSA"."""
    text = re.sub(r"[\u2010-\u2013]", "-", text or "")
    found = [f"{'CSA ' if before or after else ''}{kind.capitalize()} {re.sub(' ', '', number)}" for before, kind, after, number in _NUMBER.findall(text)]
    return "; ".join(dict.fromkeys(found))


def read_meeting(meeting, agenda, scanned, spelling=None, pages=0):
    """One meeting as its agenda's lines, with what the minutes say was done set on each by its number: the lines,
    the votes on each motion that could be read whole, and what the reading found.

    `agenda` is the agenda's lines (None where there is no agenda to read) and `scanned` the minutes (None where
    there are none). A numbered line the minutes have and the agenda has not (an item taken off the consent agenda
    and given a new number, an item added) is a line here too, after the lines whose numbers come before its own.
    """
    meeting_id, date = meeting["meeting_id"], meeting["date"]
    roll = names_as(scanned["roll"], spelling or {}) if scanned else []
    facts = {"agenda": "read" if agenda and agenda["lines"] else "", "minutes": "read" if scanned else "", "pages": pages,
             "session": scanned["session"] if scanned else "",
             "time": (scanned["time"] if scanned else "") or (agenda["time"] if agenda else ""),
             "location": (scanned["location"] if scanned else "") or (agenda["location"] if agenda else ""),
             "roll": json.dumps(roll, ensure_ascii=False, separators=(",", ":")) if roll else "", "motions": 0, "motions_read": 0}
    blocks = scanned["blocks"] if scanned else []
    numbered = [block for block in blocks if block["kind"] == "line"]

    def line_for(number, level, title, source, order, hour="", description=""):
        return {"number": number, "key": number_of(number), "level": level, "title": title, "time": hour, "description": description,
                "source": source, "order": order, "motions": [], "done": "", "listed": False, "moved_from": "", "moved_to": "",
                "in_minutes": False, "loose": False, "under": None}

    lines = [line_for(row["number"], row["level"], row["title"], "agenda", (at,), row["time"], row["description"])
             for at, row in enumerate(agenda["lines"] if agenda else [])]
    if not lines:  # no agenda to read: the lines are the minutes' own, in the order of their numbers
        seen = {}
        for block in sorted(numbered, key=lambda block: order_of(block["key"])):
            seen.setdefault(block["key"], line_for(block["number"], level_of(block["key"]), block["title"], "minutes", (len(seen),)))
        lines = list(seen.values())
    by_key = {}
    for line in lines:
        by_key.setdefault(line["key"], line)
    last, count = None, 0
    standing = next((line for line in lines if line["level"] == 1 and "STANDING" in line["title"].upper()), None)
    for block in blocks:
        count += 1
        if block["kind"] == "line":
            line = by_key.get(block["key"])
            if line is None:
                under = max((at for at, other in enumerate(lines) if len(other["order"]) == 1 and other["key"]
                             and order_of(other["key"]) <= order_of(block["key"])), default=-1)
                line = line_for(block["number"], level_of(block["key"]), block["title"], "minutes", (under, 1) + order_of(block["key"]))
                lines.append(line)
                by_key[block["key"]] = line
            if not line["title"]:
                line["title"] = block["title"]
            line["motions"] += block["motions"]
            line["done"] = line["done"] or block["done"]
            line["listed"] = line["listed"] or block["listed"]
            line["moved_from"] = line["moved_from"] or block["moved_from"]
            line["in_minutes"] = True
            last = line
        elif block["motions"]:
            calendar = (by_key.get(scanned["consent"]) if scanned["consent"] else None) or next(
                (line for line in lines if line["level"] == 1 and _CONSENT.search(line["title"])), None)
            if block["kind"] == "consent vote" and calendar is not None:
                calendar["motions"] += block["motions"]
                calendar["in_minutes"] = True
                continue
            # A motion under no number: the approval of the regular agenda, which belongs to the standing orders (and
            # stands first where the agenda has none), or one under a heading of the minutes' own, which is a line
            # after the numbered line it follows in the minutes.
            after = standing if block["kind"] == "regular vote" else last
            title = "CONSENT AGENDA" if block["kind"] == "consent vote" else block["title"]
            line = line_for("", 1 if block["kind"] == "consent vote" else 0, title, "minutes",
                            (after["order"] if after is not None else (-1,)) + (0, count), block["time"])
            line.update(motions=list(block["motions"]), in_minutes=True, loose=True,
                        under=standing if block["kind"] == "regular vote" else None)
            lines.append(line)
    for block in blocks:
        for old, new in block["renumbered"]:
            if new in by_key and not by_key[new]["moved_from"]:
                by_key[new]["moved_from"] = old
    for line in lines:  # an item the minutes give a new number points back to the item it was, and that one on to it
        was = by_key.get(line["moved_from"]) if line["moved_from"] else None
        if was is not None and was is not line:
            was["moved_to"] = line["key"]
    lines.sort(key=lambda line: line["order"])

    agenda_rows, votes, used, loose = [], [], set(), 0
    sections = {line["key"]: line for line in lines if line["level"] == 1 and line["key"]}
    for line in lines:
        if line["key"] and slug(line["key"]):
            base = f"{meeting_id}-{slug(line['key'])}"
        else:
            loose += 1
            base = f"{meeting_id}-u{loose}"
        item_id, again = base, 1
        while item_id in used:  # a number the agenda uses twice
            again += 1
            item_id = f"{base}-{again}"
        used.add(item_id)
        line["item_id"] = item_id
    under = Counter(line["key"].split(".")[0] for line in lines if line["level"] > 1)
    for sequence, line in enumerate(lines, 1):
        item_id = line["item_id"]
        over = line["under"] if line["loose"] else sections.get(line["key"].split(".")[0]) if line["level"] > 1 else None
        # A section's line is a heading. A line of the first rank with nothing under it that the Board voted on is an item.
        heading = line["level"] == 1 and not (line["motions"] and not under[line["key"]] and not _CONSENT.search(line["title"]))
        matter_id = "" if heading else item_id
        for number, motion in enumerate(line["motions"], 1):
            cast, problem = decide(motion, roll, scanned["why"])
            motion.update(cast=cast or [], read=cast is not None, problem=problem,
                          moved=who(motion["mover"], roll) or motion["mover"], seconded=who(motion["seconder"], roll) or motion["seconder"])
            for member, word, established in motion["cast"]:
                votes.append({"item_id": item_id, "meeting_id": meeting_id, "date": date, "matter_id": matter_id, "matter_file": "",
                              "member": member, "vote": council_tables.vote_word(word), "motion": number,
                              "motion_text": motion["said"] or motion["action"], "established": established})
        final = line["motions"][-1] if line["motions"] else None
        cast = [word for _, word, _ in final["cast"]] if final else []
        calendar = over if over is not None and line["listed"] and over["motions"] and _CONSENT.search(over["title"]) else None
        action = final["action"] if final else line["done"]
        title = clean(line["title"])
        department = re.search(r"\(([A-Z][A-Z /&,.’'-]+)\)\.?$", title)
        agenda_rows.append({
            "item_id": item_id, "meeting_id": meeting_id, "date": date, "body": BODY,
            "agenda_number": line["number"], "sequence": sequence, "matter_id": matter_id, "matter_file": "", "title": title,
            "action": action, "result": result_of(final) if final else "",
            "mover": final["moved"] if final else "", "seconder": final["seconded"] if final else "",
            "ayes": cast.count(council_tables.AYE), "noes": cast.count(council_tables.NO),
            "not_voting": sum(word not in (council_tables.AYE, council_tables.NO) for word in cast),
            "heading": heading, "level": line["level"],
            "section": over["title"] if over is not None else "", "section_id": over["item_id"] if over is not None else "",
            "time": line["time"], "description": line["description"], "subject": clean(department[1]) if department and not heading else "",
            "source": "agenda and minutes" if line["source"] == "agenda" and line["in_minutes"] else line["source"],
            "motions": len(line["motions"]), "motions_read": sum(motion["read"] for motion in line["motions"]),
            "votes_read": all(motion["read"] for motion in line["motions"]) if line["motions"] else None,
            "problem": next((motion["problem"] for motion in line["motions"] if not motion["read"]), ""),
            "outcome": final["outcome"] if final else "", "how": final["how"] if final else "",
            "voted_with": item_id if line["motions"] else calendar["item_id"] if calendar is not None else "",
            "moved_from": line["moved_from"], "moved_to": line["moved_to"],
            "doc_type": "" if heading else next((kind for kind in ("ordinance", "resolution") if kind in numbers_in(action).lower()), county.doc_type_of(title)),
            "number": numbers_in(action),
            "motion_log": json.dumps([{"motion": number, "action": motion["action"], "said": motion["said"], "mover": motion["mover"],
                                       "seconder": motion["seconder"], "outcome": motion["outcome"], "how": motion["how"],
                                       "read": motion["read"], "problem": motion["problem"]}
                                      for number, motion in enumerate(line["motions"], 1)], ensure_ascii=False, separators=(",", ":")) if line["motions"] else "",
        })
        facts["motions"] += len(line["motions"])
        facts["motions_read"] += sum(motion["read"] for motion in line["motions"])
    return agenda_rows, votes, facts


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------

def items_table(agenda, meetings):
    """Every item on the agenda of a meeting whose minutes were read, with what was done with it: by a vote of its
    own, or by the consent agenda's.

    The site has no record of an item apart from its line on an agenda, so an item is here once for each meeting it
    came to.
    """
    of = agenda.set_index("item_id")
    minutes = dict(zip(meetings["meeting_id"], meetings["minutes_url"]))
    read = set(meetings.loc[meetings["minutes"] == "read", "meeting_id"])
    rows = []
    for line in agenda[~agenda["heading"] & agenda["meeting_id"].isin(read)].itertuples(index=False):
        own = line.motions > 0
        over = of.loc[line.voted_with] if not own and line.voted_with else None
        vote = line._asdict() if own else over.to_dict() if over is not None else None
        rows.append({
            "date": line.date, "matter_id": line.item_id, "matter_file": "", "doc_type": line.doc_type, "title": line.title,
            "body": line.body, "status": "", "year": int(line.date[:4]), "subject": line.subject, "agenda_date": line.date,
            "passed_date": "", "last_action": line.action or (vote["action"] if vote else ""),
            "last_action_date": line.date if vote else "", "result": vote["result"] if vote else "",
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
    for column in ("year", "ayes", "noes", "times_on_agenda"):
        out[column] = out[column].astype(int)
    return out.sort_values(["date", "meeting_id", "matter_id"], ascending=[False, False, True]).reset_index(drop=True)


def members_table(votes, meetings, on=None):
    """Everyone with votes on two days or more. The district is the roll's; the office is the one the newest roll
    that lists them gives. The minutes give no terms of office, so `serving` goes by how lately they voted."""
    seat = {}
    for meeting in meetings[meetings["roll"] != ""].sort_values("date").itertuples(index=False):
        for member in json.loads(meeting.roll):
            seat[member["name"]] = member
    cast = votes.groupby("member")["date"].agg(["min", "max", "size", "nunique"]) if len(votes) else pd.DataFrame()
    since = (day_type.fromisoformat(on or today()) - timedelta(days=SERVING_DAYS)).isoformat()
    rows = []
    for name in sorted(cast.index):
        if cast.loc[name, "nunique"] < 2:
            continue  # a name with votes on one day only is more likely a misprint than a supervisor
        serving = cast.loc[name, "max"] >= since
        rows.append({"name": name, "district": seat.get(name, {}).get("district"), "role": seat.get(name, {}).get("role", "") if serving else "",
                     "start": "", "end": "", "serving": serving, "first_vote": cast.loc[name, "min"], "last_vote": cast.loc[name, "max"],
                     "votes": int(cast.loc[name, "size"])})
    out = pd.DataFrame(rows, columns=council_tables.COLUMNS["members"])
    out["district"] = out["district"].astype("Int64")
    out["serving"] = out["serving"].astype(bool)
    out["votes"] = out["votes"].astype(int)
    return out.sort_values(["first_vote", "name"]).reset_index(drop=True)


def spelling_of(rolls):
    """The one way each supervisor's name is written, for every way the rolls print it: of the full names of one
    person ("Peter W. Huebner", "Peter Huebner"), the commonest. A roll that has a surname alone ("Adams") or a name
    run together ("LeeAdams") means the one supervisor of that name, where there is only one."""
    printed = Counter(member["name"] for roll in rolls for member in roll)
    people = {}
    for name, count in printed.items():
        if " " in name:
            people.setdefault(person(name), Counter())[name] += count
    best = {key: sorted(seen.items(), key=lambda form: (-form[1], form[0]))[0][0] for key, seen in people.items()}
    out = {}
    for name in printed:
        if " " in name:
            out[name] = best[person(name)]
            continue
        fits = {best[key] for key, seen in people.items() for full in seen if key_of(name) in (key_of(surname(full)), key_of(full))}
        if len(fits) == 1:
            out[name] = fits.pop()
    return out


def joined(held, new):
    """Two tables of the same columns as one. An empty one adds nothing, and is left out so it cannot change a column's kind."""
    some = [table for table in (held, new) if len(table)]
    return pd.concat(some, ignore_index=True) if some else held


def typed(agenda, votes):
    for table, columns in ((agenda, ("sequence", "ayes", "noes", "not_voting", "level", "motions", "motions_read")), (votes, ("motion",))):
        for column in columns:
            table[column] = table[column].astype(int)
    agenda["heading"] = agenda["heading"].astype(bool)
    agenda["votes_read"] = agenda["votes_read"].astype("boolean")
    return agenda, votes


FACTS = (("agenda", ""), ("minutes", ""), ("pages", 0), ("session", ""), ("time", ""), ("location", ""), ("roll", ""),
         ("motions", 0), ("motions_read", 0))


def build(base, everything, out_dir, since=FIRST_YEAR, limit=0):
    rows = listed(since)
    log.info(f"Sierra County: {len(rows)} meetings of the Board listed")
    if len(rows) < 20 and since <= datetime.now(timezone.utc).year - 1:
        raise RuntimeError("the listing of meetings came back nearly empty")
    meetings = meetings_table(rows)

    agenda, votes, before_meetings = (council_tables.held(HF_REPO, out_dir, name, base) for name in ("agenda_items", "votes", "meetings"))
    before = 0 if votes is None else len(votes)
    if agenda is None or votes is None or before_meetings is None:
        agenda, votes = pd.DataFrame(columns=AGENDA_COLUMNS), pd.DataFrame(columns=VOTE_COLUMNS)
        before_meetings = pd.DataFrame(columns=MEETING_COLUMNS)
    found = {row["meeting_id"]: {name: row.get(name, empty) for name, empty in FACTS}
             for row in before_meetings[(before_meetings["minutes"] != "") | (before_meetings["agenda"] != "")].to_dict("records")}
    recent = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    kept = lambda row, what: (Path(out_dir) / "text" / f"{row['meeting_id']}{what}").exists()
    wants = lambda row, what, was: row["date"] >= recent or (not kept(row, what) and (everything or not found.get(row["meeting_id"], {}).get(was)))
    with_agenda = lambda row: row["agenda_url"].endswith("?html=true") and not row["cancelled"]
    with_minutes = lambda row: bool(row["minutes_url"]) and not row["cancelled"]
    listed_rows = [row for row in meetings.to_dict("records") if row["date"] >= f"{since}-01-01"]
    wanted = [row for row in listed_rows if (with_agenda(row) and wants(row, ".agenda.json", "agenda"))
              or (with_minutes(row) and wants(row, ".txt", "minutes"))]
    wanted.sort(key=lambda row: (row["date"], int(row["meeting_id"])), reverse=True)  # the newest first: a room shows those
    waiting = len(wanted)
    wanted = wanted[:limit] if limit else wanted
    log.info(f"Fetching the agendas and minutes of {len(wanted)} meetings of {waiting} not yet read or to be read again")

    # First the documents, which is the only part that asks anything of the site: one request at a time, a pause after
    # each. Each is kept as it comes, so a run that is stopped has lost nothing.
    fetched = 0
    for at, row in enumerate(wanted, 1):
        fresh = row["date"] >= recent
        for wanted_here, what, was, get in ((with_agenda(row), ".agenda.json", "agenda", agenda_kept), (with_minutes(row), ".txt", "minutes", text_of)):
            if not wanted_here or not wants(row, what, was):
                continue
            try:
                get(row, out_dir, fresh=fresh)
                fetched += 1
            except Refused:
                break
            except NotPDF:
                found[row["meeting_id"]] = {**dict(FACTS), **found.get(row["meeting_id"], {}), "minutes": "not a PDF"}
            except Exception as e:
                log.warning(f"{what.strip('.')} of meeting {row['meeting_id']} ({row['date']}): {type(e).__name__}: {e}")
        if _refused.is_set():
            log.error("The host refused a request: no more is asked of it in this run")
            break
        if at % 40 == 0:
            log.info(f"Sierra County: {at} of {len(wanted)} meetings asked for")

    # Then every meeting with a document kept here is read, old and new. Minutes are not read where they have no text
    # of their own, where the PDF gives no letters for its characters, where they are the minutes of another day
    # (posted on the wrong meeting's row), and where they are a second copy of minutes already read.
    scans, texts = {}, {}
    for row in sorted(listed_rows, key=lambda row: int(row["meeting_id"])):
        lines = agenda_kept(row, out_dir) if with_agenda(row) and kept(row, ".agenda.json") else None
        if not (with_minutes(row) and kept(row, ".txt")):
            if lines is not None:
                scans[row["meeting_id"]] = (row, lines, None, 0, found.get(row["meeting_id"], {}).get("minutes", ""))
            continue
        text = text_of(row, out_dir)
        pages, unread, minutes = text.count("\f") + 1, legible(text), None
        if not unread:
            minutes = scan(text)
            if minutes["day"] and minutes["day"] != row["date"]:
                unread, minutes = f"minutes of another day ({minutes['day']})", None
            elif text in texts:
                unread, minutes = f"the same minutes as meeting {texts[text]}", None
            else:
                texts[text] = row["meeting_id"]
        scans[row["meeting_id"]] = (row, lines, minutes, pages, unread)
    # A name is written one way throughout: by the rolls read now, and by those of meetings read before and held.
    spelling = spelling_of([minutes["roll"] for _, _, minutes, _, _ in scans.values() if minutes]
                           + [json.loads(facts["roll"]) for meeting_id, facts in found.items() if meeting_id not in scans and facts.get("roll")])
    new_agenda, new_votes = [], []
    for meeting_id, (row, lines, minutes, pages, unread) in scans.items():
        reading = read_meeting(row, lines, minutes, spelling, pages)
        new_agenda.extend(reading[0])
        new_votes.extend(reading[1])
        found[meeting_id] = {**reading[2], "minutes": unread or reading[2]["minutes"]}
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
        "n_agendas": f"{int((meetings['agenda'] == 'read').sum()):,}", "n_cancelled": f"{int(meetings['cancelled'].sum()):,}",
        "n_motions": f"{motions:,}", "n_motions_read": f"{motions_read:,}", "n_unread": f"{motions - motions_read:,}",
        "share_read": f"{100 * motions_read / motions:.1f}" if motions else "0", "recent_days": RECENT_DAYS, "first_year": FIRST_YEAR,
        "serving_days": SERVING_DAYS,
        **{f"n_{way}": f"{int(ways.get(way, 0)):,}" for way in (NAMED, COUNT)},
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
        log.error(f"Sierra County tables not uploaded: {e}")
        return False
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the Sierra County Board's meetings, agendas, actions and votes")
    parser.add_argument("--base", action="store_true", help="start from the tables written here, not the published ones")
    parser.add_argument("--all", action="store_true", help="fetch every document not kept here, read before or not")
    parser.add_argument("--since", type=int, default=FIRST_YEAR, help="read no meeting before this year")
    parser.add_argument("--max", type=int, default=0, help="meetings to fetch in one run (0 for all)")
    parser.add_argument("--out", default="", help="directory to write the tables into (minutes_pdf/sierra-county if not given)")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the tables only")

    out_dir = Path(args.out) if args.out else OUT_DIR
    try:
        tables, fetched = build(args.base, args.all, out_dir, args.since, args.max)
    except Exception as e:
        log.error(f"Sierra County tables not built: {type(e).__name__}: {e}")
        return 1
    pushed = False if args.no_upload else upload(tables, out_dir, args.write_card)
    meetings, agenda, votes, members = tables["meetings"], tables["agenda_items"], tables["votes"], tables["members"]
    motions, motions_read = int(agenda["motions"].sum()), int(agenda["motions_read"].sum())
    ways = votes["established"].value_counts() if len(votes) else {}
    log.info(f"RESULT: sierra-board items={len(tables['items'])} meetings={len(meetings)} "
             f"meetings_with_minutes={int((meetings['minutes_url'] != '').sum())} "
             f"minutes_read={int((meetings['minutes'] == 'read').sum())} "
             f"no_text_layer={int((meetings['minutes'] == 'no text layer').sum())} "
             f"agendas_read={int((meetings['agenda'] == 'read').sum())} agenda_items={len(agenda)} "
             f"motions={motions} motions_read={motions_read} motions_unread={motions - motions_read} votes={len(votes)} "
             f"named={int(ways.get(NAMED, 0))} count={int(ways.get(COUNT, 0))} "
             f"members={len(members)} serving={int(members['serving'].sum())} documents_fetched={fetched} "
             f"first_vote={votes['date'].min() if len(votes) else ''} last_vote={votes['date'].max() if len(votes) else ''} "
             f"refused={_refused.is_set()} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
