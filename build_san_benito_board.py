#!/usr/bin/env python3
"""
Build chrissoria/san-benito-county-board: the meetings of the San Benito County
Board of Supervisors, what was on each agenda, what the Board did with it, and
how each supervisor voted.

One source: the County's listing of its meetings in Granicus
(cosb.granicus.com/ViewPublisher.php?view_id=1), one page of HTML that links
each meeting's agenda and, for some, its minutes as a PDF. The system has no
record of a vote apart from the minutes, so the votes here are read from them.

From 2022 the minutes are the agenda with what was done written under each
line, and every vote is printed the same way, with everyone on the Board named:

    Moved by Angela Curro; seconded by Dom Zanger to approve contract per
    staff recommendation.
    Motion : 4 - 0 - 0
    Voting For: Dom Zanger, Kollin Kosmicki, Mindy Sotelo, Angela Curro
    Voting Against: None
    Voting Abstain: None
    Absent: Bea Gonzales

The head of the minutes prints the Board, a supervisor to a district. A motion
is read only if the names under it are exactly that Board, none of them twice,
and as many under each word as the count above them says. Nothing is filled
in: a supervisor the minutes do not name under a motion is not put down as
absent because the head says so. `established` on every vote is `named`.

A vote is read whole or not at all. A motion that is not read stays in
agenda_items with what stopped it (`problem`) and has no rows in votes.

The consent agenda is voted on as one, so its vote is on its own line
(`heading`) and the items under it point to it, except those the motion leaves
out ("except for item #1.7"), which have a motion of their own or none.

The dataset has the five tables every council's and board's dataset has
(council_tables.py), in data/:
  items.parquet          every item in the minutes that were read
  meetings.parquet       one row per meeting of the Board listed
  agenda_items.parquet   one row per line of the minutes, headings too, with what was done
  votes.parquet          one row per supervisor and motion voted on
  members.parquet        one row per supervisor seen voting on several days
They are kept here in minutes_pdf/san-benito-county/, with the text of each
set of minutes beside them in text/, so a PDF is fetched once.

Two ways to run it:

    python build_san_benito_board.py
        The routine run. Starts from the published tables, reads the listing
        again, and reads the minutes not read before and those of meetings in
        the last 90 days (minutes are posted after the next meeting approves
        them, and are now and then replaced by an amended set).

    python build_san_benito_board.py --base
        The same, starting from the tables written here. It fetches the newest
        minutes first and can be stopped and started again. Minutes whose text
        is kept here are read again on every run; that takes no request.

    --since YEAR  read no meeting before this year (default 2015, where the listing begins)
    --max N       sets of minutes to fetch in one run (default 0, for all)
    --all         fetch every set of minutes whose text is not kept here, read before or not
    --out DIR     where to write the tables
    --no-upload   write the tables but do not publish them
    --write-card  publish the dataset card as well as the tables

Needs pdfplumber. Only a document's own text is read: minutes that are a scan
(nearly all of 2015 to 2019, and the signed copies filed for much of 2026) are
counted and left. Five sets of 2022 are kept as a page of HTML, not a PDF, and
are read the same way.

The host's robots file disallows everything to everyone. Chris decided on
2026-10-13 that a vendor's blanket robots file does not bind a named reader of
public records that reads slowly: this asks for one thing a second at most, and
stops at the first refusal.
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
from urllib.parse import urljoin

import pandas as pd
import requests

import build_federal_bills as bills
import build_sd_county as county
import council_tables
from build_sd_county import clean, today

log = logging.getLogger(__name__)

HF_REPO = "chrissoria/san-benito-county-board"
OUT_DIR = bills.SCRIPT_DIR / "minutes_pdf" / "san-benito-county"
CARD_FILE = bills.SCRIPT_DIR / "README_san_benito_board.md"
TABLES = council_tables.TABLES
BODY = "Board of Supervisors"

HOST = "https://cosb.granicus.com"
VIEW = 1  # the County's one listing, of the Board and of its commissions and committees
BOARD = re.compile(r"Board of Supervisors|Board Retreat")  # the rows of the listing that are the Board's own meetings
FIRST_YEAR = 2015  # the listing begins in October 2015
SEATS = 5  # a county's board of supervisors (Government Code 25000)
RECENT_DAYS = 90  # meetings this recent are fetched again
SERVING_DAYS = 120  # the minutes keep no terms of office: a supervisor who voted this recently is taken to be serving
SEEN_DAYS = 2  # someone is a member if they vote on this many days: once may be a clerk's slip
LAYER_CHARS = 200  # minutes with fewer characters of their own than this are a scan
PAUSE = 1.0  # seconds after every request
DESCRIPTION = 4000  # the most of what the minutes say under a line that is kept with it
MOTION_LINES = 40  # a motion's words run no longer than this before its count

MEETING_COLUMNS = council_tables.COLUMNS["meetings"] + [
    "name", "note", "video_url", "minutes", "pages", "seats", "roll", "chair", "motions", "motions_read"]
AGENDA_COLUMNS = council_tables.COLUMNS["agenda_items"] + [
    "heading", "section", "section_id", "motions", "motions_read", "votes_read", "problem", "count", "voted_with", "department",
    "file_number", "description", "doc_type", "number", "motion_log"]
VOTE_COLUMNS = council_tables.COLUMNS["votes"] + ["motion", "motion_text", "established"]
ITEM_COLUMNS = council_tables.COLUMNS["items"] + ["item_id", "meeting_id", "agenda_number", "section", "action_on", "votes_read",
                                                  "number", "department", "file_number"]

NAMED = "named"  # how every vote here is established: the minutes print the supervisor's name under the word
VACANT = "vacant"

# The words a vote's names are listed under, and the word the tables have for each. The second set is that of the one
# set of minutes typed by hand (the budget hearing of 26 June 2023).
WORDS = {"voting for": council_tables.AYE, "voting against": council_tables.NO, "voting abstain": "ABSTAIN", "absent": "ABSENT",
         "ayes": council_tables.AYE, "noes": council_tables.NO, "abstain": "ABSTAIN", "recused": "RECUSED"}
_LABEL = re.compile(r"^(Voting For|Voting Against|Voting Abstain|Ayes|Noes|Abstain|Absent|Recused)(?:ed|ing)?\s*:\s*(.*)$", re.I)
_MOVED = re.compile(r"^Moved by\s+(.+?)\s*[;,]\s*(?:and\s+)?seconded by\s+(.*)$", re.I)
_MADE_BY = re.compile(r"\bmade by (?:Supervisor |Chair |Vice[- ]Chair )?(.+?),? and seconded by (?:Supervisor |Chair |Vice[- ]Chair )?([^:.,]+)", re.I)
_MOTION_WORDS = re.compile(r"^Motion(?:\s*:|\s+to\b)\s*(.*)$")  # "Motion to acknowledge ... made by Supervisor Gonzales and seconded by ..."
_COUNT = re.compile(r"^Motion\s*:\s*(\d)\s*[-–—]\s*(\d)(?:\s*[-–—]\s*(\d))?\s*$", re.I)
_NAME = re.compile(r"[A-Z][A-Za-z’'.-]*(?: [A-Za-z][A-Za-z’'.-]*){0,3}")
_NOBODY = re.compile(r"^(none|n/?a|0|-+)?\.?$", re.I)
# The headings of the minutes: the agenda's own parts, with or without a number before them. "FUTURE AGENDA ITEMS"
# without a number is not one: it stands inside the call to order, over the supervisors' announcements.
_PART = r"C ?ALL TO ORDER|ADJOURNMENT|CONSENT AGENDA|REGULAR AGENDA|PUBLIC HEARINGS?|CLOSED SESSION"
_SECTION = re.compile(rf"^(?:(\d{{1,2}})\.\s*([A-Z][A-Z /&,'’:()–-]{{3,80}}?)|({_PART})):?$")
_ITEM = re.compile(r"^(\d{1,2})\.(\d{1,2})(?:\s+(?![a-z])(\S.*))?$")  # "1.17 RESOURCE MANAGEMENT AGENCY- A. PRADO", or the number alone
_LETTERED = re.compile(r"^([a-z])\.\s+(\S.*)$")  # "b. Acknowledge Certificate of Posting", under the call to order
_FILE = re.compile(r"\s*\bSBC FIL(?:E|ING) N[A-Z]*\.?\s*:?\s*([\d., ]*\d)?\.?\s*", re.I)  # "SBC FILE NUMBER: 105.3", "SBC FILE NO.: 119"
_NUMBER = re.compile(r"\b(RESOLUTION|ORDINANCE)S?\.?\s*(?:N(?:O|OS|UMBERS?)\b\.?)?\s*:?\s*(\d[\d-]*(?:\s*(?:,|&|and)\s*\d[\d-]*)*)")
_DISTRICTS = re.compile(r"DistrictNo\.?(\d)|District(\d)")  # in a line with its spaces taken out: "D istrict No. 5"
# "DISTRICT 4 - Angela Curro Board of Supervisors Vanessa Delgado", in a line with its spaces taken out
_SEAT = re.compile(r"^DISTRICT(\d)[-–—:](.+)$")
_INLINE_COUNT = re.compile(r"^(.*\S)\s+(Motion\s*:\s*\d\s*[-–—]\s*\d(?:\s*[-–—]\s*\d)?)$")  # "Posting. Motion : 5 - 0 - 0"
_CHAIR = re.compile(r"called to order at .{3,14}? by ((?:Vice[- ]?)?Chair(?:man|woman|person)?)\s+([A-Z][A-Za-z’' -]+?)[.,]")
_EXCEPT = re.compile(r"\b(?:except|excluding|with the exception|minus|less)\b(.*)$", re.I | re.S)


class Refused(Exception):
    """The host answered with a check, a login or a refusal. It is not asked again in this run."""


class NotPDF(Exception):
    """What the listing links as a meeting's minutes is neither a PDF nor a page of minutes."""


_refused = set()  # hosts that have answered so
_session = requests.Session()
_CHECK = re.compile(r"captcha|cf-challenge|are you a human|access denied|just a moment|you have been blocked", re.I)


def fetch(url, hops=5, tries=3):
    """One answer from the County's listing or from where it keeps a document, a second after the one before.

    A redirect is followed by hand, so that each address asked is asked slowly and looked at. A refusal is not tried
    again, and nothing more is asked of that host in this run; a document that sits behind a login is not public.
    """
    for _ in range(hops):
        host = requests.utils.urlparse(url).netloc
        if host in _refused:
            raise Refused(f"{host} refused an earlier request")
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
        if answer.status_code in (401, 403, 429) or (page and _CHECK.search(answer.text[:20000]) and "granicus" not in answer.text[:3000].lower()):
            _refused.add(host)
            raise Refused(f"{answer.status_code} from {url.split('?')[0]}")
        if answer.status_code in (301, 302, 303, 307, 308):
            url = urljoin(url, answer.headers.get("location", ""))
            if "/account/login" in url:
                raise NotPDF("the document is behind a login")
            continue
        answer.raise_for_status()
        return answer
    raise requests.TooManyRedirects(url.split("?")[0])


# ---------------------------------------------------------------------------
# The listing
# ---------------------------------------------------------------------------

_MONTHS = {name: number for number, name in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
_CELL_NAME = re.compile(r'(?s)headers="Name"[^>]*>(.*?)</td>')
_CELL_DAY = re.compile(r'(?s)headers="Date[^"]*"[^>]*>(.*?)</td>')
_WHEN = re.compile(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),\s+(\d{4})(?:\s*-\s*(\d{1,2}):(\d\d)\s*([AP]M))?", re.I)
_LINK = re.compile(r'(?s)href="([^"]+)"[^>]*>\s*([^<]*?)\s*<')


def plain(text):
    """A piece of a page as text."""
    return clean(html.unescape(re.sub(r"<[^>]+>", " ", str(text or ""))).replace("\xa0", " "))


def rows_of(page):
    """The Board's meetings on the listing, as the system has them. A meeting is known by the number of its recording.

    A row is on the page once for every tab it is under; a meeting to come has no recording yet and is not one.
    """
    rows = {}
    for row in re.split(r"(?i)<tr\b", page):
        name, day, clip = _CELL_NAME.search(row), _CELL_DAY.search(row), re.search(r"clip_id=(\d+)", row)
        when = _WHEN.search(plain(day[1])) if day else None
        if not (name and when and clip) or when[1].lower() not in _MONTHS or not BOARD.search(plain(name[1])):
            continue
        links = [(("https:" if link.startswith("//") else "") + html.unescape(link), clean(words)) for link, words in _LINK.findall(row)]
        minutes = next(((link, words) for link, words in links if words.lower().startswith("minutes")), ("", ""))
        found = {"meeting_id": clip[1], "name": plain(name[1]),
                 "date": f"{when[3]}-{_MONTHS[when[1].lower()]:02d}-{int(when[2]):02d}",
                 "time": f"{int(when[4])}:{when[5]} {when[6].upper()}" if when[4] else "",
                 "agenda": next((link for link, words in links if "AgendaViewer.php" in link), ""),
                 "minutes": minutes[0], "note": "" if minutes[1].lower() == "minutes" else minutes[1],
                 "video": "MediaPlayer.php" in row}
        if clip[1] not in rows or (found["minutes"] and not rows[clip[1]]["minutes"]):
            rows[clip[1]] = found
    return list(rows.values())


def listed():
    """Every meeting of the Board the system lists. The listing is one page, of everything since 2015."""
    return rows_of(fetch(f"{HOST}/ViewPublisher.php?view_id={VIEW}").text)


def meetings_table(rows):
    """One row per meeting listed. What a reading adds (`minutes`, `pages`, `roll` and the counts) is filled in by build()."""
    out = [{
        "meeting_id": row["meeting_id"], "date": row["date"], "time": row["time"], "body": BODY, "location": "",
        "url": f"{HOST}/ViewPublisher.php?view_id={VIEW}", "agenda_url": row["agenda"], "minutes_url": row["minutes"], "items": 0,
        "name": row["name"], "note": row["note"],
        "video_url": f"{HOST}/MediaPlayer.php?view_id={VIEW}&clip_id={row['meeting_id']}" if row["video"] else "",
        "minutes": "", "pages": 0, "seats": 0, "roll": "", "chair": "", "motions": 0, "motions_read": 0,
    } for row in rows]
    out = pd.DataFrame(out, columns=MEETING_COLUMNS)
    return out.sort_values(["date", "meeting_id"], key=lambda column: column if column.name == "date" else column.astype(int)
                           ).reset_index(drop=True)


# ---------------------------------------------------------------------------
# The text of a set of minutes
# ---------------------------------------------------------------------------

def pdf_text(body):
    """The text a PDF carries, a page at a time. Nothing is read off the picture of a page."""
    import pdfplumber
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    with pdfplumber.open(io.BytesIO(body)) as document:
        return [page.extract_text() or "" for page in document.pages]


_TAG = re.compile(r"(?is)<(script|style|title)\b.*?</\1\s*>|<!--.*?-->|<(/?)([a-z][a-z0-9]*)\b[^>]*>")
_BLOCK = {"br", "div", "p", "tr", "td", "th", "li", "ul", "ol", "table", "header", "h1", "h2", "h3", "h4", "h5"}


def html_text(page):
    """The text of minutes kept as a page of HTML (five sets of 2022 are), a line for each block of the page."""
    lines, buffer, position = [], [], 0
    for tag in _TAG.finditer(page):
        buffer.append(page[position:tag.start()])
        position = tag.end()
        if tag.group(1) or (tag.group(3) or "").lower() in _BLOCK:
            lines.append(clean(html.unescape("".join(buffer)).replace("\xa0", " ")))
            buffer = []
    lines.append(clean(html.unescape("".join(buffer + [page[position:]])).replace("\xa0", " ")))
    out = []
    for line in filter(None, lines):
        # The page sets a line's number in a column of its own: it is put back before its line, as a PDF has it.
        if out and re.fullmatch(r"\d{1,2}\.(?:\d{1,2})?", out[-1]):
            out[-1] = f"{out[-1]} {line}"
        else:
            out.append(line)
    return "\n".join(out)


def text_of(meeting, out_dir, fresh=False):
    """The text of a meeting's minutes, pages parted by form feeds: from the copy kept here, or fetched and kept."""
    kept = Path(out_dir) / "text" / f"{meeting['meeting_id']}.txt"
    if kept.exists() and not fresh:
        return kept.read_text(encoding="utf-8")
    body = fetch(meeting["minutes_url"]).content
    if body[:4] == b"%PDF":
        text = "\n\f".join(pdf_text(body))
    elif re.match(rb"\s*<(?:!doctype|html)", body[:200], re.I) and b"Voting For" in body:
        text = html_text(body.decode("utf-8", "replace"))
    else:
        raise NotPDF("the listing sent something that is neither a PDF nor a page of minutes")
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(text, encoding="utf-8")
    return text


def lines_of(text):
    """The minutes' lines in order, with nothing for an empty one. The minutes print no page numbers."""
    return [clean(line) for line in text.replace("\f", "\n").split("\n") if clean(line)]


# ---------------------------------------------------------------------------
# Who a name is, and who sits on the Board
# ---------------------------------------------------------------------------

def key_of(name):
    """What two printings of a name share: its letters. "A ngela Curro" is "Angela Curro"."""
    return re.sub(r"[^a-z]", "", str(name or "").lower())


def names_in(text):
    """The names listed after "Voting For:", as printed, and whether every piece of the list is a name.

    "None" names nobody. A piece that is not a name ("Zanger Gonzales and staff") is kept as printed, and is then on
    no roll.
    """
    text = clean(text).strip(" .;,")
    if _NOBODY.match(text):
        return []
    return [clean(piece).strip(" .") for piece in re.split(r"\s*[,;]\s*(?:and\s+)?|\s+and\s+", text) if clean(piece).strip(" .")]


def spelled(known):
    """{letters: the name as most often printed} of the names printed under votes. Only a name of two words or more
    is one the head of the minutes can be read with."""
    forms = {}
    for name, times in Counter(known).items():
        if len(name.split()) >= 2 and _NAME.fullmatch(name):
            forms.setdefault(key_of(name), Counter())[name] += times
    return {key: sorted(form.items(), key=lambda pair: (-pair[1], pair[0]))[0][0] for key, form in forms.items()}


def board_of(lines, known):
    """The Board the head of the minutes prints: [(district, name)], a seat called vacant as (district, VACANT).

    Empty where the head cannot be read whole. `known` is the names the minutes print under their votes. The head sets
    the Board out as a table, a district to a column, which the text of a PDF runs together ("Dom Zanger Kollin
    Kosmicki Mindy Sotelo ..." over "District No. 1 District No. 2 ..."), with now and then a space inside a word and
    half of a long name on a line of its own. So the row of names is read as those names end to end and nothing else:
    each whole, or the part of it that fits its column where the other part stands elsewhere in the head.
    """
    names = spelled(known)
    keys = sorted(names.items(), key=lambda pair: -len(pair[0]))
    seats = []
    for line in lines:
        seat = _SEAT.match(line.replace(" ", ""))
        if seat:  # the head of 2026: a district to a line, with the next column's words after the name
            rest = key_of(seat[2])
            name = VACANT if rest.startswith(VACANT) else next((name for key, name in keys if rest.startswith(key)), None)
            if name is None:
                return []
            seats.append((int(seat[1]), name))
    if seats:
        return seats if len({district for district, _ in seats}) == len(seats) else []

    block = []
    for line in lines[:24]:
        if re.search(r"Chambers|MINUTES|Hollister", line):
            break
        block.append(line)
    districts = sorted(int(a or b) for line in block for a, b in _DISTRICTS.findall(line.replace(" ", "")))
    if len(districts) < 3 or districts != list(range(1, len(districts) + 1)):
        return []
    # Minutes kept as a page of HTML have a name to a line, over its district.
    above = [(int(seat[1] or seat[2]), dict(keys + [(VACANT, VACANT)]).get(key_of(name)))
             for name, line in zip(block, block[1:]) for seat in [_DISTRICTS.fullmatch(line.replace(" ", ""))] if seat]
    if len(above) == len(districts):
        return sorted(above) if all(name for _, name in above) else []
    # The halves of each name, for one that is split between two lines: (the half in the row, the half elsewhere).
    halves = [(key_of(" ".join(words[:cut])), key_of(" ".join(words[cut:])), name) for name in names.values()
              for words in [name.split()] for cut in range(1, len(words))]
    for place, row in enumerate(block):
        elsewhere = "".join(key_of(_DISTRICTS.sub("", line.replace(" ", ""))) for at, line in enumerate(block) if at != place)
        rest, found = key_of(row), []
        while rest:
            name, key = next(((name, key) for key, name in keys + [(VACANT, VACANT)] if rest.startswith(key)), (None, ""))
            if name is None:
                split = {(name, here) for first, last, name in halves for here, there in ((first, last), (last, first))
                         if rest.startswith(here) and there in elsewhere}
                if len(split) != 1:
                    break
                name, key = split.pop()
            if name in found and name != VACANT:
                break
            found.append(name)
            rest = rest[len(key):]
        if not rest and len(found) == len(districts):
            return list(zip(districts, found))
    return []


def who(name, roll):
    """The supervisor on the roll that a printed name is, or None.

    A surname or a first name alone ("Sotelo", "Ignacio") is one if it is the name of only one on the roll.
    """
    key = key_of(re.sub(r"^(?:Supervisors?|Vice[- ]?Chair\w*|Chair\w*)\s+", "", clean(name)))
    if not key:
        return None
    whole = [member for member in roll if key_of(member) == key]
    if whole:
        return whole[0]
    part = [member for member in roll if key in (key_of(member.split()[0]), key_of(member.split()[-1]))
            or (len(member.split()) > 2 and key_of(member).endswith(key) and len(key) > 5)]
    return part[0] if len(part) == 1 else None


# ---------------------------------------------------------------------------
# What is printed under a motion
# ---------------------------------------------------------------------------

def decide(motion, roll):
    """Every supervisor's vote on a motion as ([(supervisor, word)], ""), or (None, why it is not read).

    `roll` is the Board the head of the minutes prints. The names under the motion must be exactly that Board, none
    twice, and as many under each word as the count says.
    """
    if not roll:
        return None, "the Board at the head of the minutes could not be read"
    if not any(names for _, names in motion["cast"]):
        return None, "no names under the motion"
    if motion["broken"]:
        return None, motion["broken"]
    cast, seen = [], set()
    for word, names in motion["cast"]:
        for name in names:
            member = who(name, roll)
            if member is None:
                return None, f"not on the Board: {name}"
            if member in seen:
                return None, f"named twice: {member}"
            seen.add(member)
            cast.append((member, word))
    missing = [member for member in roll if member not in seen]
    if missing:
        return None, "no vote printed for: " + ", ".join(missing)
    if motion["count"]:
        words = [word for _, word in cast]
        named = (words.count(council_tables.AYE), words.count(council_tables.NO), words.count("ABSTAIN"))
        wanted = tuple(number for number in motion["count"] if number is not None)
        if named[:len(wanted)] != wanted:
            return None, f"the count says {' - '.join(map(str, wanted))} and {' - '.join(map(str, named[:len(wanted)]))} are named"
    return cast, ""


# ---------------------------------------------------------------------------
# Reading a set of minutes
# ---------------------------------------------------------------------------

def scan(text, known=()):
    """A set of minutes as the Board its head prints and its lines, each with the motions written under it.

    A line is a part of the agenda ("1. CONSENT AGENDA"), an item ("1.7", or "b." under the call to order), or what
    stands above the first heading where a motion is written there. A motion is "Moved by ...; seconded by ... to
    ...", the count on the line after its words, and the names under each word after that. `known` is names printed
    under the votes of other minutes, for a supervisor the head names and no vote of these minutes does.
    """
    lines = lines_of(text)
    out = [{"kind": "top", "number": "", "title": "", "said": [], "motions": [], "over": None}]
    part, current, motion, label = None, out[0], None, None
    letters, inner = "", ""  # the letters of the items so far under this heading, and of a list set inside one of them
    numbered = 0  # the number of the last numbered part: the next is one more
    printed = Counter()

    def close():
        nonlocal motion, label
        if motion is not None:
            if not motion["count"] and not motion["cast"]:
                # Nothing was printed under it (a motion withdrawn, or one that died): its words end with its sentence.
                end = next((place for place, words in enumerate(motion["words"]) if words.rstrip().endswith(".")), 0)
                motion["on"]["said"].extend(motion["words"][end + 1:])
                motion["words"] = motion["words"][:end + 1]
            motion["text"] = re.sub(r"\s+([.,;])", r"\1", clean(" ".join(motion["words"])))
            moved = _MOVED.match(motion["text"]) or _MADE_BY.search(motion["text"])
            if moved and not motion["mover"]:
                motion["mover"], rest = clean(moved[1]), clean(moved[2])
                second = _NAME.match(rest)
                motion["seconder"] = clean(second[0]) if second else ""
                if moved.re is _MOVED and second:  # the seconder's name ends where the motion's "to ..." begins
                    cut = re.search(r"\s+(?:to|that|for|and)\b", rest)
                    motion["seconder"] = clean(rest[:cut.start()]) if cut else motion["seconder"]
            current_line = motion.pop("on")
            current_line["motions"].append(motion)
        motion, label = None, None

    def begin(line, kind, number, title, over):
        nonlocal current
        close()
        current = {"kind": kind, "number": number, "title": title, "said": [], "motions": [], "over": over}
        out.append(current)
        return current

    rows = []
    for line in lines:
        inline = _INLINE_COUNT.match(line)
        rows.extend([inline[1], inline[2]] if inline else [line])
    for place, line in enumerate(rows):
        # Under a motion: its count, then the names under each word.
        found = _LABEL.match(line)
        count = _COUNT.match(line)
        if count:
            if motion is None or motion["count"] or motion["cast"]:
                close()  # a count with no "Moved by" above it: the words above are too long to be told from the minutes'
                motion = {"on": current, "words": [], "mover": "", "seconder": "", "count": None, "printed": "", "cast": [], "broken": ""}
            motion["count"] = (int(count[1]), int(count[2]), int(count[3]) if count[3] else None)
            motion["printed"] = clean(line.split(":", 1)[1])
            label = None
            continue
        if found and (motion is not None or found[1].lower() in ("voting for", "ayes")):
            word = WORDS[found[1].lower()]
            if motion is None or word in [said for said, _ in motion["cast"]]:
                close()
                motion = {"on": current, "words": [], "mover": "", "seconder": "", "count": None, "printed": "", "cast": [], "broken": ""}
            names = names_in(found[2])
            motion["cast"].append((word, names))
            printed.update(names)
            label = (word, found[2])
            continue
        if motion is not None and label is not None:
            # A list of names that runs on to a second line: where the line above ends in a comma, or where another
            # of the vote's words follows it ("... Angela Curro, Ignacio" / "Velazquez" / "Voting Against: None").
            word, so_far = label
            more = names_in(line)
            follows = place + 1 < len(rows) and _LABEL.match(rows[place + 1])
            if ((so_far.rstrip().endswith(",") or follows) and more and len(line) < 90
                    and all(_NAME.fullmatch(name) for name in more) and not _MOVED.match(line) and not _SECTION.match(line)):
                so_far = f"{so_far} {line}"  # a name may itself be cut in two by the end of the line
                printed.subtract(motion["cast"][-1][1])
                motion["cast"][-1] = (word, names_in(so_far))
                printed.update(motion["cast"][-1][1])
                label = (word, so_far)
                continue
            close()
        opens = _MOVED.match(line) or (_MOTION_WORDS.match(line) and not count)
        if opens:
            close()
            motion = {"on": current, "words": [line], "mover": "", "seconder": "", "count": None, "printed": "", "cast": [], "broken": ""}
            continue

        # A heading or an item ends whatever motion is open above it.
        section = _SECTION.match(line)
        if section and (section[3] or int(section[1]) in (numbered + 1, numbered + 2)):
            numbered = int(section[1]) if section[1] else numbered
            title = clean(section[2] or section[3])
            part = begin(line, "part", section[1] or "", "CALL TO ORDER" if key_of(title) == "calltoorder" else title, None)
            letters, inner = "", ""
            continue
        item = _ITEM.match(line)
        if item and part is not None and not part["number"] and item[2] == "1" and int(item[1]) == numbered + 1 and "last" not in part:
            part["number"], numbered = item[1], numbered + 1  # a heading printed without its number: its first item gives it
        if item and part is not None and part["number"] == item[1] and int(item[2]) > part.get("last", 0):
            part["last"] = int(item[2])
            begin(line, "item", f"{item[1]}.{item[2]}", "", part)
            if item[3]:
                current["said"].append(clean(item[3]))
            continue
        lettered = _LETTERED.match(line)
        if lettered and part is not None and not part["number"] and motion is None:
            letter = lettered[1]
            next_outer = chr(ord(letters[-1]) + 1) if letters else "a"
            next_inner = chr(ord(inner[-1]) + 1) if inner else ""
            if letter == next_inner:
                inner += letter  # the next of a list set inside an item
            elif letter == next_outer:
                letters, inner = letters + letter, ""
                begin(line, "item", letter, clean(lettered[2]), part)
                continue
            elif letter == "a" and letters:
                inner = "a"  # a list inside an item starts again at a

        if motion is not None:
            if len(motion["words"]) >= MOTION_LINES:
                close()  # a motion with no count under it: its words stop here, and it has no vote to read
                current["said"].append(line)
            else:
                motion["words"].append(line)
        else:
            current["said"].append(line)
    close()

    head = []
    for line in lines[:40]:
        if _SECTION.match(line) and key_of(line).endswith("calltoorder"):
            break
        head.append(line)
    board = board_of(head, +printed + Counter(known))
    chair = _CHAIR.search(clean(" ".join(lines[:400])))
    return {"board": board, "lines": out, "printed": sorted(+printed), "chair": (clean(chair[1]), clean(chair[2])) if chair else ("", "")}


def parted(line):
    """An item's words as (department, title, file number, number, what the minutes say under it).

    The agenda prints an item as the department in capitals, what the Board is asked to do, and "SBC FILE NUMBER:"
    with the number of the County's file for that kind of business; a resolution's or ordinance's number follows where
    one was given. What stands after those is the minutes' own account.
    """
    said = list(line["said"])
    if line["kind"] != "item" or not re.fullmatch(r"\d+\.\d+", line["number"]):
        return "", line["title"], "", "", "\n".join(said)
    department = []
    while said and re.search(r"[A-Z]{4}", said[0]) and not re.search(r"[a-z]{2}", said[0]) and not _FILE.search(said[0]) and len(department) < 3:
        department.append(said.pop(0))
    title, file_number, at = [], "", None
    for place, words in enumerate(said):
        found = _FILE.search(words)
        if found:
            title.append(words[:found.start()])
            file_number, at = clean(found[1] or ""), place
            after = clean(words[found.end():])
            said = said[:place + 1] + ([after] if after else []) + said[place + 1:]
            break
        title.append(words)
    if title and department:
        # A department's name that runs on to the line the title begins on: "ADMINISTRATOR Accept presentation ...".
        run_on = re.match(r"^((?:[A-Z]{5,}[,-]?\s+)+)(?=[A-Z][a-z])", title[0])
        if run_on:
            department.append(run_on[1])
            title[0] = title[0][run_on.end():]
    if at is None:
        # No file number to say where the agenda's words end: they are taken to end with their first sentence.
        end = next((place for place, words in enumerate(title) if words.rstrip().endswith(".")), len(title) - 1)
        return (clean(" ".join(department)), clean(" ".join(title[:end + 1])) or clean(" ".join(department)), "", "",
                "\n".join(title[end + 1:]))
    rest = said[at + 1:]
    numbers = []
    while rest and _NUMBER.match(rest[0]) and len(rest[0]) < 80:
        numbers.append(rest.pop(0))
    return (clean(" ".join(department)), clean(" ".join(title)) or clean(" ".join(department)), file_number,
            number_in(" ".join(numbers)), "\n".join(rest))


def number_in(text):
    """"Resolution 2026-115, 2026-116" of "RESOLUTION NUMBERS: 2026-115, 2026-116", or ""."""
    found = _NUMBER.search(text)
    if not found:
        return ""
    numbers = clean(re.sub(r"\s*(?:,|&|and)\s*", ", ", found[2]))
    return f"{found[1].title()} {numbers}"


def left_out(text):
    """The items a consent agenda's motion leaves out: ["1.7"] of "to approve Consent Agenda except for item #1.7."."""
    found = _EXCEPT.search(text)
    return re.findall(r"\d{1,2}\.\d{1,2}", found[1]) if found else []


def read_meeting(meeting, scanned, pages=0):
    """One meeting's minutes against the Board its head prints: its lines, the votes on each motion that could be
    read whole, and what the reading found."""
    meeting_id, date = str(meeting["meeting_id"]), meeting["date"]
    roll = [name for _, name in scanned["board"] if name != VACANT]
    chair = who(scanned["chair"][1], roll) if scanned["chair"][1] else None
    facts = {"minutes": "read", "pages": pages, "seats": len(roll),
             "roll": json.dumps([{"name": name, "district": district} for district, name in scanned["board"]],
                                ensure_ascii=False, separators=(",", ":")),
             "chair": json.dumps({"name": chair, "role": scanned["chair"][0]}, ensure_ascii=False, separators=(",", ":")) if chair else "",
             "motions": 0, "motions_read": 0}
    lines = [line for line in scanned["lines"] if line["kind"] != "top" or line["motions"]]
    heads = {id(line["over"]) for line in lines if line["over"] is not None}
    used, parts = set(), 0
    for line in lines:
        if line["kind"] == "part":
            parts += 1
        base = f"{meeting_id}-" + ("top" if line["kind"] == "top" else f"s{parts}" if line["kind"] == "part" else line["number"])
        item_id, again = base, 1
        while item_id in used:  # a number the minutes use twice
            again += 1
            item_id = f"{base}-{again}"
        used.add(item_id)
        line["item_id"] = item_id
    agenda, votes = [], []
    for sequence, line in enumerate(lines, 1):
        item_id = line["item_id"]
        consent = line["kind"] == "part" and "consentagenda" in key_of(line["title"])
        heading = id(line) in heads or consent
        matter_id = "" if heading else item_id
        for number, motion in enumerate(line["motions"], 1):
            cast, problem = decide(motion, roll)
            motion.update(read=cast is not None, problem=problem, votes=cast or [],
                          moved=who(motion["mover"], roll) or motion["mover"], seconded=who(motion["seconder"], roll) or motion["seconder"])
            for member, word in motion["votes"]:
                votes.append({"item_id": item_id, "meeting_id": meeting_id, "date": date, "matter_id": matter_id, "matter_file": "",
                              "member": member, "vote": word, "motion": number, "motion_text": motion["text"], "established": NAMED})
        last = line["motions"][-1] if line["motions"] else None
        cast = [word for _, word in last["votes"]] if last else []
        over = line["over"]
        # An item of the consent agenda is voted on with it, unless the agenda's motion leaves it out.
        shared = over is not None and "consentagenda" in key_of(over["title"]) and not line["motions"] and next(
            (one for one in over["motions"] if "consent" in one["text"].lower() and line["number"] not in left_out(one["text"])), None)
        department, title, file_number, number, description = parted(line)
        agenda.append({
            "item_id": item_id, "meeting_id": meeting_id, "date": date, "body": BODY,
            "agenda_number": line["number"], "sequence": sequence, "matter_id": matter_id, "matter_file": "", "title": title,
            "action": last["text"] if last else "", "result": "",  # the minutes print a count, not what became of the motion
            "mover": last["moved"] if last else "", "seconder": last["seconded"] if last else "",
            "ayes": cast.count(council_tables.AYE), "noes": cast.count(council_tables.NO),
            "not_voting": sum(word not in (council_tables.AYE, council_tables.NO) for word in cast),
            "heading": heading, "section": over["title"] if over else "", "section_id": over["item_id"] if over else "",
            "motions": len(line["motions"]), "motions_read": sum(motion["read"] for motion in line["motions"]),
            "votes_read": all(motion["read"] for motion in line["motions"]) if line["motions"] else None,
            "problem": next((motion["problem"] for motion in line["motions"] if not motion["read"]), ""),
            "count": last["printed"] if last else "",
            "voted_with": item_id if line["motions"] else over["item_id"] if shared else "",
            "department": department, "file_number": file_number, "description": description[:DESCRIPTION],
            "doc_type": "" if heading else county.doc_type_of(f"{title} {number}"), "number": number,
            "motion_log": json.dumps([{"motion": place, "text": motion["text"], "mover": motion["mover"], "seconder": motion["seconder"],
                                       "count": motion["printed"], "read": motion["read"], "problem": motion["problem"]}
                                      for place, motion in enumerate(line["motions"], 1)], ensure_ascii=False, separators=(",", ":"))
            if line["motions"] else "",
        })
        facts["motions"] += len(line["motions"])
        facts["motions_read"] += sum(motion["read"] for motion in line["motions"])
    return agenda, votes, facts


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------

def items_table(agenda, meetings):
    """Every item in the minutes read, with what was done with it: by a vote of its own, or by its consent agenda's.

    The system has no record of an item apart from its line in the minutes, so an item is here once for each meeting
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
            "body": line.body, "status": "", "year": int(line.date[:4]), "subject": line.department, "agenda_date": line.date,
            "passed_date": "",  # the minutes print a count and not what became of a motion: it may have been one to deny or put off
            "last_action": vote["action"] if vote else "", "last_action_date": line.date if vote else "", "result": "",
            "ayes": int(vote["ayes"]) if vote else 0, "noes": int(vote["noes"]) if vote else 0,
            "mover": vote["mover"] if vote else "", "seconder": vote["seconder"] if vote else "",
            "times_on_agenda": 1, "url": minutes.get(line.meeting_id, ""),
            "item_id": line.item_id, "meeting_id": line.meeting_id, "agenda_number": line.agenda_number, "section": line.section,
            "action_on": "item" if own else "section" if over is not None else "",
            "votes_read": bool(vote["votes_read"]) if vote else None,
            "number": line.number, "department": line.department, "file_number": line.file_number,
        })
    out = pd.DataFrame(rows, columns=ITEM_COLUMNS)
    out["votes_read"] = out["votes_read"].astype("boolean")
    return out.sort_values(["date", "meeting_id"], ascending=False, kind="stable").reset_index(drop=True)


def members_table(votes, meetings):
    """Everyone with votes here on several days. The district is the one the head of the newest minutes gives them,
    and `role` the office (Chair) those minutes say called the meeting to order. The minutes keep no terms of office."""
    districts, role, newest = {}, {}, ""
    for meeting in meetings[meetings["roll"] != ""].sort_values("date").itertuples(index=False):
        for seat in json.loads(meeting.roll):
            districts[seat["name"]] = seat["district"]
        if meeting.chair:
            role, newest = json.loads(meeting.chair), meeting.date
    days = votes.groupby("member")["date"].nunique() if len(votes) else pd.Series(dtype=int)
    cast = votes.groupby("member")["date"].agg(["min", "max", "size"]) if len(votes) else pd.DataFrame()
    since = (datetime.now(timezone.utc) - timedelta(days=SERVING_DAYS)).strftime("%Y-%m-%d")
    rows = []
    for name in sorted(days[days >= SEEN_DAYS].index):
        serving = bool(cast.loc[name, "max"] >= since)
        rows.append({"name": name, "district": districts.get(name),
                     "role": role.get("role", "") if serving and role.get("name") == name and newest >= since else "",
                     "start": "", "end": "", "serving": serving, "first_vote": cast.loc[name, "min"],
                     "last_vote": cast.loc[name, "max"], "votes": int(cast.loc[name, "size"])})
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


FACTS = (("minutes", ""), ("pages", 0), ("seats", 0), ("roll", ""), ("chair", ""), ("motions", 0), ("motions_read", 0))


def build(base, everything, out_dir, since=FIRST_YEAR, limit=0):
    rows = listed()
    log.info(f"San Benito County: {len(rows)} meetings of the Board listed, {sum(bool(row['minutes']) for row in rows)} with minutes")
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
    wanted.sort(key=lambda row: (row["date"], int(row["meeting_id"])), reverse=True)  # the newest first: a room shows those
    waiting = len(wanted)
    wanted = wanted[:limit] if limit else wanted
    log.info(f"Fetching the minutes of {len(wanted)} meetings of {waiting} not yet read or to be read again")

    # First the text of each, one at a time and slowly: it is the only part that asks anything of the host. It is
    # kept as it comes, so a run that is stopped has lost nothing.
    fetched, refused = 0, False
    for place, row in enumerate(wanted, 1):
        try:
            text_of(row, out_dir, fresh=row["date"] >= recent)
            fetched += 1
        except Refused as e:
            log.error(f"{e}: no more is asked in this run")
            refused = True
            break
        except NotPDF as e:
            found[row["meeting_id"]] = {**dict(FACTS), "minutes": f"not read: {e}"}
        except Exception as e:
            log.warning(f"minutes of {row['date']} ({row['meeting_id']}): {type(e).__name__}: {e}")
        if place % 25 == 0:
            log.info(f"San Benito County: {place} of {len(wanted)} minutes asked for")

    # Then every set of minutes whose text is here is read, old and new: it takes no request, and a name the head of
    # one set prints may be known only from the votes of another.
    texts = {row["meeting_id"]: (row, text_of(row, out_dir)) for row in with_minutes if kept(row)}
    known = Counter()
    for _, text in texts.values():
        for line in lines_of(text):
            label = _LABEL.match(line)
            if label and label[1].lower().startswith("voting"):
                known.update(names_in(label[2]))
    known = Counter({name: times for name, times in known.items() if times >= 3})  # a name printed once or twice may be a slip
    new_agenda, new_votes = [], []
    for meeting_id, (row, text) in texts.items():
        pages = text.count("\f") + 1
        if len(re.sub(r"\s", "", text)) < LAYER_CHARS:
            found[meeting_id] = {**dict(FACTS), "minutes": "no text layer", "pages": pages}
            continue
        reading = read_meeting(row, scan(text, known), pages)
        new_agenda.extend(reading[0])
        new_votes.extend(reading[1])
        found[meeting_id] = reading[2]
    agenda = joined(agenda[~agenda["meeting_id"].isin(set(texts))], pd.DataFrame(new_agenda, columns=AGENDA_COLUMNS))
    votes = joined(votes[~votes["meeting_id"].isin(set(texts))], pd.DataFrame(new_votes, columns=VOTE_COLUMNS))
    agenda["order"], votes["order"] = agenda["meeting_id"].astype(int), votes["meeting_id"].astype(int)
    agenda = agenda.sort_values(["date", "order", "sequence"]).drop(columns="order").reset_index(drop=True)
    votes = votes.sort_values(["date", "order", "item_id", "motion", "member"]).drop(columns="order").reset_index(drop=True)
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
    return tables, fetched, refused


def card(tables):
    """The dataset card, with the counts of this reading written in."""
    meetings, agenda, votes = tables["meetings"], tables["agenda_items"], tables["votes"]
    read = meetings[meetings["minutes"] == "read"]
    motions, motions_read = int(agenda["motions"].sum()), int(agenda["motions_read"].sum())
    facts = {
        "repo": HF_REPO, "first_meeting": read["date"].min() if len(read) else "", "last_meeting": read["date"].max() if len(read) else "",
        "first_listed": meetings["date"].min(), "last_listed": meetings["date"].max(),
        "first_vote": votes["date"].min() if len(votes) else "", "last_vote": votes["date"].max() if len(votes) else "",
        "n_with_minutes": f"{int((meetings['minutes_url'] != '').sum()):,}",
        "n_read": f"{len(read):,}", "n_scans": f"{int((meetings['minutes'] == 'no text layer').sum()):,}",
        "n_motions": f"{motions:,}", "n_motions_read": f"{motions_read:,}", "n_unread": f"{motions - motions_read:,}",
        "share_read": f"{100 * motions_read / motions:.1f}" if motions else "0",
        "recent_days": RECENT_DAYS, "serving_days": SERVING_DAYS, "seen_days": SEEN_DAYS,
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
        log.error(f"San Benito County tables not uploaded: {e}")
        return False
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the San Benito County Board's meetings, actions and votes")
    parser.add_argument("--base", action="store_true", help="start from the tables written here, not the published ones")
    parser.add_argument("--all", action="store_true", help="fetch every set of minutes whose text is not kept here")
    parser.add_argument("--since", type=int, default=FIRST_YEAR, help="read no meeting before this year")
    parser.add_argument("--max", type=int, default=0, help="minutes to fetch in one run (0 for all)")
    parser.add_argument("--out", default="", help="directory to write the tables into (minutes_pdf/san-benito-county if not given)")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the tables only")

    out_dir = Path(args.out) if args.out else OUT_DIR
    try:
        tables, fetched, refused = build(args.base, args.all, out_dir, args.since, args.max)
    except Exception as e:
        log.error(f"San Benito County tables not built: {type(e).__name__}: {e}")
        return 1
    pushed = False if args.no_upload else upload(tables, out_dir, args.write_card)
    meetings, agenda, votes, members = tables["meetings"], tables["agenda_items"], tables["votes"], tables["members"]
    motions, motions_read = int(agenda["motions"].sum()), int(agenda["motions_read"].sum())
    log.info(f"RESULT: san-benito-board items={len(tables['items'])} meetings={len(meetings)} "
             f"meetings_with_minutes={int((meetings['minutes_url'] != '').sum())} "
             f"minutes_read={int((meetings['minutes'] == 'read').sum())} "
             f"no_text_layer={int((meetings['minutes'] == 'no text layer').sum())} agenda_items={len(agenda)} "
             f"motions={motions} motions_read={motions_read} motions_unread={motions - motions_read} votes={len(votes)} "
             f"members={len(members)} serving={int(members['serving'].sum())} "
             f"voters_not_members={len(set(votes['member']) - set(members['name']))} minutes_fetched={fetched} "
             f"first_vote={votes['date'].min() if len(votes) else ''} last_vote={votes['date'].max() if len(votes) else ''} "
             f"refused={refused} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
