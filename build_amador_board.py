#!/usr/bin/env python3
"""
Build chrissoria/amador-county-board: the meetings of the Amador County Board
of Supervisors, what the Board did at each, and how each supervisor voted.

One source: the County's listing of its meetings in Granicus
(amador.granicus.com/ViewPublisher.php?view_id=1). It links each meeting's
agenda and no minutes. The minutes are there all the same: the Board approves
the minutes of a meeting at a later one, and the agenda of that later meeting
has them attached, as a PDF, to the item that approves them ("Review and
possible approval of the June 11, 2024 Board of Supervisors Meeting Minutes").
So they are the minutes as the Clerk drafted them and put them to the Board,
and each says so ("These minutes remain in Draft form until approved"). The
minutes as approved are on the County's own website, which is not read.
Attachments older than the autumn of 2023 are behind a login and are left.

The head of the minutes prints the roll ("Present on Roll Call:", a supervisor
and district to a line, and "Absent:"). A motion is one paragraph:

    MOTION: It was moved by Supervisor Forster, seconded by Supervisor Crew,
    and carried 3-2 to approve the Side Letter of Agreement.
    Ayes: Supervisors Crew, Forster, Brown
    Noes: Supervisor Oneto, Axe
    Absent: None

    MOTION: It was moved by Supervisor Axe, seconded by Supervisor Forster and
    carried unanimously, to approve the agenda as presented.

The names are listed where the Board divided, and under many motions where it
did not, but not under all. So a vote is read in one of three ways, and
`established` on each row says which:

  named      the names under the motion are exactly the roll at the head (those
             present and those absent), none twice, and the count agrees.
  unanimous  the motion says it carried unanimously and lists nobody. Every
             supervisor on the roll is put down as AYE, but only if the head
             has all five present and the minutes have nobody out of the room
             or standing aside at that point. Otherwise it is not read.
  count      the motion gives a count and lists nobody, at a meeting the head
             has a supervisor absent from: "carried 4-0-1" with four present
             and one absent. The four are AYE and the fifth ABSENT, under the
             same condition. A count that is not all of those present for the
             motion ("3-1") does not say who, and is not read.

A vote is read whole or not at all. A motion that is not read stays in
agenda_items with what stopped it (`problem`) and has no rows in votes.

The dataset has the five tables every council's and board's dataset has
(council_tables.py), in data/:
  items.parquet          every item in the minutes that were read
  meetings.parquet       one row per meeting of the Board listed
  agenda_items.parquet   one row per item of the minutes, the consent agenda and its items too
  votes.parquet          one row per supervisor and motion voted on
  members.parquet        one row per supervisor seen voting on several days
They are kept here in minutes_pdf/amador-county/, with the text of each set of
minutes beside them in text/ (and found.json, which says which agenda carries
which minutes), so a document is fetched once.

Two ways to run it:

    python build_amador_board.py
        The routine run. Starts from the published tables, reads the listing
        again, and reads the agendas not read before and those of the last 90
        days, and the minutes they carry.

    python build_amador_board.py --base
        The same, starting from the tables written here. It can be stopped and
        started again. Minutes whose text is kept here are read again on every
        run; that takes no request.

    --since YEAR  read no agenda before this year (default 2023: what older agendas carry is behind a login)
    --max N       agendas and minutes to fetch in one run (default 0, for all)
    --all         read every agenda again, read before or not
    --out DIR     where to write the tables
    --no-upload   write the tables but do not publish them
    --write-card  publish the dataset card as well as the tables

Needs pdfplumber. Only a PDF's own text is read: minutes that are a scan are
counted and left.

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

HF_REPO = "chrissoria/amador-county-board"
OUT_DIR = bills.SCRIPT_DIR / "minutes_pdf" / "amador-county"
CARD_FILE = bills.SCRIPT_DIR / "README_amador_board.md"
TABLES = council_tables.TABLES
BODY = "Board of Supervisors"

HOST = "https://amador.granicus.com"
VIEW = 1  # the County's one listing, of the Board and of three other bodies
FIRST_YEAR = 2023  # what the agendas of earlier years carry is behind a login
SEATS = 5  # a county's board of supervisors (Government Code 25000)
RECENT_DAYS = 90  # agendas this recent are read again: minutes are attached, and replaced, up to the meeting
SERVING_DAYS = 120  # the minutes keep no terms of office: a supervisor who voted this recently is taken to be serving
SEEN_DAYS = 2  # someone is a member if they vote on this many days: once may be a clerk's slip
LAYER_CHARS = 200  # a document with fewer characters of its own than this is a scan
LOGINS = 3  # this many documents in a row behind a login, newest first, and the older ones are not asked for
PAUSE = 1.0  # seconds after every request
DESCRIPTION = 4000  # the most of what the minutes say under an item that is kept with it

MEETING_COLUMNS = council_tables.COLUMNS["meetings"] + [
    "name", "listed", "packet_url", "minutes", "minutes_name", "minutes_in", "kind", "pages", "seats", "roll", "absent", "motions",
    "motions_read"]
AGENDA_COLUMNS = council_tables.COLUMNS["agenda_items"] + [
    "heading", "section", "section_id", "motions", "motions_read", "votes_read", "problem", "how", "established", "voted_with",
    "outcome", "description", "doc_type", "number", "motion_log"]
VOTE_COLUMNS = council_tables.COLUMNS["votes"] + ["motion", "motion_text", "established"]
ITEM_COLUMNS = council_tables.COLUMNS["items"] + ["item_id", "meeting_id", "agenda_number", "section", "action_on", "votes_read", "number"]

NAMED, UNANIMOUS, COUNT = "named", "unanimous", "count"  # how a vote came to be known

_MONTH = "January|February|March|April|May|June|July|August|September|October|November|December"
_MONTHS = {name[:3].lower(): number for number, name in enumerate(_MONTH.split("|"), 1)}
# The Board's own minutes among an agenda's attachments, by the file's name ("June_11__2024_DRAFT_Minutes.pdf"); the
# minutes of the Planning Commission and of committees are attached to other items. The document's head settles it.
_ATTACHED = re.compile(r"/(?:uploads/attachment|services/legistar/download)/pdf/(\d+)/([^\"'<>\s?#]+\.pdf)", re.I)
_OWN = re.compile(rf"^(?:\d+-_)?(?:(?:{_MONTH})_\d{{1,2}}__?\d{{4}}|\d{{1,2}}_\d{{1,2}}_\d{{2,4}})_.*Minutes", re.I)
_OTHERS = re.compile(r"PC_|Planning|LUC|Committee|Commission|Council|District|Excerpt|ACRA", re.I)

_TITLE = r"(?:Supervisors?|Vice[- ]?Chair(?:man|woman|person)?|Chair(?:man|woman|person)?)"
_NAME = r"[A-Z][A-Za-z’'.-]*(?: [A-Z][A-Za-z’'.-]*){0,3}"
# "Brian Oneto, District V – Chairman"; the last line of the roll is now and then printed twice over, run together
_SEATED = re.compile(rf"^({_NAME}),\s*District\s*(III|II|IV|I|V|\d)\s*(?:[-–—]\s*(Vice[- ]?Chair\w*|Chair\w*))?")
_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}
_DATE = re.compile(rf"^DATE:\s*(?:[A-Za-z]+,\s*)?({_MONTH})\s+(\d{{1,2}}),\s*(\d{{4}})", re.I)
_TIME = re.compile(r"^TIME:\s*(\d{1,2}):(\d\d)\s*([ap])\.?\s*m", re.I)
_FOOT = re.compile(rf"^(?:(?:{_MONTH})\s+\d{{1,2}},\s*\d{{4}},?\s*[-–—]?\s*(?:(?:AMENDED|DRAFT|FINAL|SPECIAL|MEETING)\s*[-–—]?\s*)*MINUTES\s*|Page\s+)?\d{{1,3}}$", re.I)
_ACTION = re.compile(r"^ACTION(?:\s*#?\s*(\d+))?\s*:\s*(.*)$")
_MOTION = re.compile(r"^MOTION(?:\s*#?\s*(\d+))?\s*:\s*(.*)$")
_LABEL = re.compile(r"^(Ayes?|Yeas?|Noes?|Nays?|Absent|Abstain(?:ed|ing)?|Abstentions?|Recused?)\s*:\s*(.*)$", re.I)
_MOVED = re.compile(rf"moved by\s*(?:{_TITLE}\s*)?({_NAME}?),?\s*(?:and\s+)?seconded by\s*(?:{_TITLE}\s*)?({_NAME}?)[,;]?\s*(?:and\s+)?(?=[a-z])")
_UNANIMOUS = re.compile(r"unanimous", re.I)
_COUNT = re.compile(r"\b(?:carried|passed|failed|vote of),?\s*(?:by a vote of\s*|by\s*)?\(?(\d)\s*[-–—]\s*(\d)(?:\s*[-–—]\s*(\d))?")
_PART = re.compile(r"^(CONSENT AGENDA|REGULAR AGENDA|PUBLIC HEARINGS?|CLOSED SESSION|ADJOURNMENT|AGENDA|PLEDGE OF ALLEGIANCE"
                   r"|PUBLIC MATTERS NOT ON THE AGENDA|REPORT OUT OF CLOSED SESSION|REGULAR SESSION)\b\s*:?\s*(.*)$")
_CONSENT_LIST = re.compile(rf"^(?:{_MONTH})\s+\d{{1,2}},\s*\d{{4}},?\s*CONSENT\s+(?:AGENDA\s+)?MINUTES\b", re.I)
_CONSENT_ITEM = re.compile(r"^(\d{1,2}\.[a-z]{1,2})\.?\s+(\S.*)$")
_GOES_ON = re.compile(r"^(?:Conditions?|Findings?|RESOLUTION|ORDINANCE|\d{1,2}[.)]|[a-z][.)]|•|[-–—])")  # what a motion sets out under itself
_NUMBER = re.compile(r"\b(Resolution|Ordinance)\s+(?:No\.?|Number|#)?\s*(\d[\w-]*\d|\d)", re.I)
# What the minutes say where a supervisor is out of the room, or stands aside from an item, and where one comes in.
_WENT = re.compile(r"\bleft the\b|\bexited\b|\bdeparted\b|\bstepped (?:out|down|away)\b|\bexcused\b|\bwas absent\b|\b(?:was|is) not present\b", re.I)
_ASIDE = re.compile(r"\brecus|\babstain|\bconflict of interest\b|\bdeferred to\b", re.I)
_CAME = re.compile(rf"\b{_TITLE}\s+({_NAME}?)\s+(?:arrived|returned|rejoined|joined the meeting)\b")
_SUPERVISOR = re.compile(rf"\b{_TITLE}\s+({_NAME}?)(?=[\s,.;:)]|$)(?!\s+(?:[A-Z][a-z]|and\s+{_TITLE}))")
_APART = re.compile(r"\babstain|\babstention|\brecus|\babsent\b|\bopposed\b|\bopposing\b|\bdissent|\bvoting no\b|\bnot voting\b", re.I)  # in a motion's own words
WORDS = {"a": council_tables.AYE, "y": council_tables.AYE, "n": council_tables.NO}


class Refused(Exception):
    """The host answered with a check or a refusal. It is not asked again in this run."""


class Closed(Exception):
    """A document that sits behind a login: it is not public, and is not asked for again."""


_refused = set()  # hosts that have answered so
_session = requests.Session()
_CHECK = re.compile(r"captcha|cf-challenge|are you a human|access denied|just a moment|you have been blocked", re.I)
_BUCKET = re.compile(r"^https://([a-z0-9.-]*_[a-z0-9._-]*)\.s3\.amazonaws\.com/")


def fetch(url, hops=5, tries=3):
    """One answer from the County's listing or from where it keeps a document, a second after the one before.

    A redirect is followed by hand, so that each address asked is asked slowly and looked at. A refusal is not tried
    again, and nothing more is asked of that host in this run. The agendas are kept in a store whose name has an
    underscore in it, which the store's certificate cannot name: it is asked for the same file by its path.
    """
    for _ in range(hops):
        url = _BUCKET.sub(r"https://s3.amazonaws.com/\1/", url)
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
                raise Closed("behind a login")
            continue
        answer.raise_for_status()
        return answer
    raise requests.TooManyRedirects(url.split("?")[0])


# ---------------------------------------------------------------------------
# The listing, and what an agenda has attached
# ---------------------------------------------------------------------------

_CELL_NAME = re.compile(r'(?s)headers="Name"[^>]*>(.*?)</td>')
_CELL_DAY = re.compile(r'(?s)headers="Date[^"]*"[^>]*>(.*?)</td>')
_WHEN = re.compile(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),\s+(\d{4})(?:\s*-\s*(\d{1,2}):(\d\d)\s*([AP]M))?", re.I)
_HREF = re.compile(r'href="([^"]+)"')


def plain(text):
    """A piece of a page as text."""
    return clean(html.unescape(re.sub(r"<[^>]+>", " ", str(text or ""))).replace("\xa0", " "))


def rows_of(page):
    """The Board's meetings on the listing, as the system has them. A meeting is known by the number the system gives it."""
    rows = {}
    for row in re.split(r"(?i)<tr\b", page):
        name, day, event = _CELL_NAME.search(row), _CELL_DAY.search(row), re.search(r"event_id=(\d+)", row)
        when = _WHEN.search(plain(day[1])) if day else None
        if not (name and when and event) or when[1].lower() not in _MONTHS or plain(name[1]) != BODY or event[1] in rows:
            continue
        links = [("https:" if link.startswith("//") else "") + html.unescape(link) for link in _HREF.findall(row)]
        rows[event[1]] = {"meeting_id": event[1], "name": plain(name[1]),
                          "date": f"{when[3]}-{_MONTHS[when[1].lower()]:02d}-{int(when[2]):02d}",
                          "time": f"{int(when[4])}:{when[5]} {when[6].upper()}" if when[4] else "",
                          "agenda": next((link for link in links if "AgendaViewer.php" in link), ""),
                          "packet": next((link for link in links if link.lower().endswith(".pdf")), "")}
    return list(rows.values())


def listed():
    """Every meeting of the Board the system lists. The listing is one page, of everything since 2017."""
    return rows_of(fetch(f"{HOST}/ViewPublisher.php?view_id={VIEW}").text)


def meetings_table(rows):
    """One row per meeting listed. What a reading adds (`minutes_url`, `minutes`, `roll` and the counts) is filled in by build()."""
    out = [{
        "meeting_id": row["meeting_id"], "date": row["date"], "time": row["time"], "body": BODY, "location": "",
        "url": f"{HOST}/ViewPublisher.php?view_id={VIEW}", "agenda_url": row["agenda"], "minutes_url": "", "items": 0,
        "name": row["name"], "listed": row.get("listed", True), "packet_url": row["packet"],
        "minutes": "", "minutes_name": "", "minutes_in": "", "kind": "", "pages": 0, "seats": 0, "roll": "", "absent": "",
        "motions": 0, "motions_read": 0,
    } for row in rows]
    out = pd.DataFrame(out, columns=MEETING_COLUMNS)
    out["listed"] = out["listed"].astype(bool)
    return out.sort_values(["date", "meeting_id"]).reset_index(drop=True)


def attached(links):
    """The Board's own minutes among the addresses an agenda links: [[the attachment's number, the file's name]]."""
    found = {}
    for link in links:
        document = _ATTACHED.search(link)
        if document and _OWN.match(document[2]) and not _OTHERS.search(document[2]):
            found[document[1]] = document[2]
    return [[number, name] for number, name in sorted(found.items(), key=lambda pair: int(pair[0]))]


def agenda_links(meeting):
    """Every address a meeting's agenda links. The agenda is a PDF, or from the summer of 2026 a page of HTML."""
    answer = fetch(meeting["agenda"])
    if answer.content[:4] != b"%PDF":
        return [html.unescape(link) for link in _HREF.findall(answer.text)]
    import pdfplumber
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    with pdfplumber.open(io.BytesIO(answer.content)) as document:
        return [link.get("uri") or "" for page in document.pages for link in page.hyperlinks]


def address(number, name):
    """Where the host gives out an attachment."""
    return f"{HOST}/services/legistar/download/pdf/{number}/{name}"


# ---------------------------------------------------------------------------
# The text of a set of minutes
# ---------------------------------------------------------------------------

def pdf_text(body):
    """The text a PDF carries, a page at a time, with an empty line where the page leaves a gap between two
    paragraphs. Nothing is read off the picture of a page.

    The lines are put together from the page's words, a space between two: set out by where each character stands,
    these minutes lose the spaces of their narrow type ("carried unanimouslyto approve"). A character printed twice
    in one place (the last name on the roll is) is read once.
    """
    import pdfplumber
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    out = []
    with pdfplumber.open(io.BytesIO(body)) as document:
        for page in document.pages:
            rows = []
            for word in sorted(page.dedupe_chars().extract_words(), key=lambda word: (round(word["top"]), word["x0"])):
                if rows and abs(word["top"] - rows[-1]["top"]) <= 3:
                    rows[-1]["words"].append(word)
                    rows[-1]["bottom"] = max(rows[-1]["bottom"], word["bottom"])
                else:
                    rows.append({"top": word["top"], "bottom": word["bottom"], "words": [word]})
            text, foot = [], None
            for row in rows:
                if foot is not None and row["top"] - foot > 0.6 * (row["bottom"] - row["top"]):
                    text.append("")
                text.append(" ".join(word["text"] for word in sorted(row["words"], key=lambda word: word["x0"])))
                foot = row["bottom"]
            out.append("\n".join(text))
    return out


def text_of(number, name, out_dir):
    """The text of an attachment, pages parted by form feeds: from the copy kept here, or fetched and kept."""
    kept = Path(out_dir) / "text" / f"{number}.txt"
    if kept.exists():
        return kept.read_text(encoding="utf-8")
    body = fetch(address(number, name)).content
    if body[:4] != b"%PDF":
        raise ValueError("the host sent a page in place of the document")
    text = "\n\f".join(pdf_text(body))
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(text, encoding="utf-8")
    return text


def paragraphs_of(text):
    """The minutes as paragraphs, each a list of its lines. The line at the foot of a page is left out.

    A paragraph ends at a gap on the page, and before a line that opens with ACTION, MOTION, or one of the words a
    vote's names are listed under. A gap cannot be seen at the head of a page, so a paragraph runs on there unless the
    words say otherwise.
    """
    out, top = [], False
    for page in text.split("\f"):
        rows = page.split("\n")
        while rows and (not rows[-1].strip() or _FOOT.match(clean(rows[-1]))):
            rows.pop()
        gap, top = True, bool(out)
        for row in rows:
            words = clean(row)
            if not words:
                gap = True
                continue
            opens = _ACTION.match(words) or _MOTION.match(words) or _LABEL.match(words) or _PART.match(words) or _CONSENT_LIST.match(words) \
                or _CONSENT_ITEM.match(words)
            if out and not opens and (not gap or (top and not re.match(r"[A-Z]", words))):
                out[-1].append(words)
            elif out and not opens and top and not out[-1][-1].rstrip().endswith((".", ":", "?")):
                out[-1].append(words)  # a sentence that runs over the page
            else:
                out.append([words])
            gap, top = False, False
    return out


# ---------------------------------------------------------------------------
# Who a name is, and the roll at the head
# ---------------------------------------------------------------------------

def key_of(name):
    """What two printings of a name share: its letters."""
    return re.sub(r"[^a-z]", "", str(name or "").lower())


def names_in(text):
    """The names in "Supervisors Crew, Forster, Brown", as printed. "None" names nobody."""
    text = re.sub(rf"\b{_TITLE}(?=[A-Z\s]|$)\s*", "", clean(text)).strip(" .;,*")  # "SupervisorOneto": the minutes drop a space now and then
    if re.fullmatch(r"(?:none|n/?a|0|-+)?", text, re.I):
        return []
    return [clean(piece).strip(" .") for piece in re.split(r"\s*[,;&]\s*(?:and\s+)?|\s+and\s+", text) if clean(piece).strip(" .")]


def who(name, roll):
    """The supervisor on the roll that a printed name is, or None. The minutes name a supervisor by surname."""
    key = key_of(re.sub(rf"^(?:{_TITLE}(?=[A-Z\s])\s*)+", "", clean(name)))
    if not key:
        return None
    whole = [member for member in roll if key_of(member) == key]
    if whole:
        return whole[0]
    part = [member for member in roll if key == key_of(member.split()[-1]) or key == key_of(member.split()[0] + member.split()[-1])]
    return part[0] if len(part) == 1 else None


def named(name, roll):
    """A mover or seconder as the roll has them, or as printed. "Brownand carried" is Brown: the minutes drop a space now and then."""
    return who(name, roll) or who(re.sub(r"and$", "", name), roll) or name


def head_of(text):
    """What the head of a document says it is: the day, hour and kind of meeting, the roll (each supervisor present,
    with district and office) and those absent. Empty where it is not the Board's minutes."""
    lines = [clean(line) for line in text.split("\f")[0].split("\n") if clean(line)]
    if not any(re.search(r"Amador County Board of Supervisors", line, re.I) for line in lines[:6]) \
            or not any(re.search(r"\bMINUTES\b", line) for line in lines[:8]):
        return {}
    head = {"date": "", "time": "", "kind": "", "roll": [], "absent": [], "said": False}
    part = ""
    for line in lines[:45]:
        date, hour = _DATE.match(line), _TIME.match(line)
        if date and not head["date"]:
            head["date"] = f"{date[3]}-{_MONTHS[date[1][:3].lower()]:02d}-{int(date[2]):02d}"
        elif hour and not head["time"]:
            head["time"] = f"{int(hour[1])}:{hour[2]} {hour[3].upper()}M"
        elif re.fullmatch(r"[A-Z ]*MEETING[A-Z ]*", line) and not head["kind"]:
            head["kind"] = line
        elif re.match(r"Present on Roll Call", line, re.I):
            part = "present"
        elif re.match(r"Staff\b", line):
            part = "staff"
        elif re.match(r"Absent\s*:", line):
            head["said"] = True
            rest = clean(line.split(":", 1)[1])
            seated = _SEATED.match(rest)
            head["absent"].extend([clean(seated[1])] if seated else names_in(rest))
            part = "absent"
        elif re.match(r"NOTE\s*:", line):
            break
        elif part in ("present", "absent"):
            seated = _SEATED.match(line)
            if seated and part == "present":
                head["roll"].append({"name": clean(seated[1]), "district": _ROMAN.get(seated[2], int(seated[2]) if seated[2].isdigit() else None),
                                     "role": clean(seated[3] or "")})
            elif seated:
                head["absent"].append(clean(seated[1]))
    return head


# ---------------------------------------------------------------------------
# What a motion says of the vote
# ---------------------------------------------------------------------------

def said_of(words):
    """What a motion's paragraph says: who moved and seconded, whether it carried unanimously, and the count if one is given."""
    moved, count = _MOVED.search(words), _COUNT.search(words)
    return {"mover": clean(moved[1]) if moved else "", "seconder": clean(moved[2]) if moved else "",
            "unanimous": bool(_UNANIMOUS.search(words)),
            "count": tuple(int(number) for number in count.groups() if number is not None) if count else None}


def decide(motion, roll, absent=(), said=True, away=()):
    """Every supervisor's vote on a motion as ([(supervisor, word, established)], ""), or (None, why it is not read).

    `roll` is those the head has present, `absent` those it has absent, `said` whether the head says who was absent,
    and `away` those the minutes have had leave, arrive, recuse or abstain up to here. Nothing is filled in on a
    likelihood: each test here is one way the minutes' own words could leave a supervisor's vote open.
    """
    board = list(roll) + [name for name in absent if who(name, roll) is None]
    count = motion["count"]
    printed = "-".join(map(str, count)) if count else ""
    if not roll:
        return None, "the head of the minutes prints no roll"
    if len(board) > SEATS:
        return None, f"the roll has {len(board)} names for {SEATS} seats"
    if any(names for _, names in motion["cast"]):
        cast, seen = [], set()
        for word, names in motion["cast"]:
            for name in names:
                member = who(name, board)
                if member is None:
                    return None, f"not on the roll: {name}"
                if member in seen:
                    return None, f"named twice: {member}"
                seen.add(member)
                cast.append((member, word, NAMED))
        missing = [member for member in board if member not in seen]
        if missing:
            return None, "no vote printed for: " + ", ".join(missing)
        words = [word for _, word, _ in cast]
        ayes, noes, gone = words.count(council_tables.AYE), words.count(council_tables.NO), words.count("ABSENT")
        # A count of two numbers is ayes and noes. One of three the Clerk writes as ayes, noes and the rest, or as
        # ayes, the rest and noes, with those absent in it or left out: the first must be the ayes, and the other
        # two the noes and the rest in either order.
        rest = len(words) - ayes - noes
        agrees = not count or (count[0] == ayes and (
            count[1:] == (noes,) if len(count) == 2 else
            sorted(count[1:]) in (sorted((noes, rest)), sorted((noes, rest - gone)))))
        if not agrees:
            return None, f"the count says {printed} and {ayes} ayes, {noes} noes and {rest} others are named"
        if motion["unanimous"] and noes:
            return None, "unanimous, with a supervisor named against"
        return cast, ""
    if not motion["unanimous"] and not count:
        return None, "neither names, a count nor unanimous"
    if _APART.search(motion["text"]):
        return None, "nobody named, and the motion's words set a supervisor apart"
    if not said:
        return None, "nobody named, and the head of the minutes does not say who was absent"
    if len(board) != SEATS:
        return None, f"nobody named, and the roll has {len(board)} names for {SEATS} seats"
    out = sorted({who(name, board) or name for name in away})
    if out:
        return None, "nobody named, and the minutes have " + ", ".join(out) + " away, late or standing aside"
    if count:
        # "carried 4-0-1" at a meeting the head has one supervisor absent from: four ayes of four present.
        if count[0] != len(roll) or sum(count[1:]) not in (0, len(absent)) or (len(count) > 1 and count[1] not in (0, len(absent))):
            return None, f"a count of {printed} and no names, with {len(roll)} present and {len(absent)} absent at the head"
        return ([(member, council_tables.AYE, COUNT) for member in roll]
                + [(who(name, board), "ABSENT", COUNT) for name in absent]), ""
    if absent:
        return None, "unanimous, and the head has " + ", ".join(absent) + " absent"
    return [(member, council_tables.AYE, UNANIMOUS) for member in roll], ""


# ---------------------------------------------------------------------------
# Reading a set of minutes
# ---------------------------------------------------------------------------

def scan(text):
    """A set of minutes as its head and its lines, each with the motions written under it.

    The minutes number nothing but the consent agenda's items, so an item is known by where it stands: its first
    paragraph opens it, what the minutes tell of it follows, and "ACTION:" and "MOTION:" close it. A paragraph after
    a motion that sets out its conditions or findings, or a resolution's number, is still that item's, and so is
    "MOTION #2:" where "MOTION #1:" was. The consent agenda is voted on as one, on its own line; its items are listed
    at the foot of the minutes, each with what was done, and point to that line unless the minutes say the item was
    pulled.
    """
    head = head_of(text)
    paragraphs = paragraphs_of(text)
    start = next((place for place, lines in enumerate(paragraphs) if re.match(r"NOTE\s*:", lines[0])), None)
    body = paragraphs[start + 1:] if start is not None else paragraphs
    out, part, current, motion, closed, listing, away, aside, pulled = [], None, None, None, True, False, set(), set(), set()
    stood = False  # whether a motion has been taken since a supervisor stood aside
    under = None  # the part of the agenda the items being read stand under: "REGULAR AGENDA", "PUBLIC HEARING 10:30 A.M."

    def line_for(kind, number, title, over=None):
        nonlocal current, motion
        current = {"kind": kind, "number": number, "title": title, "said": [], "motions": [], "outcomes": [], "over": over, "nth": 0}
        out.append(current)
        motion = None
        return current

    def nth(number):
        """"ACTION #2:" under an item opened since "MOTION #1:" is the earlier item's: the two are put back together."""
        nonlocal current
        number = int(number or 0)
        if number >= 2 and current is not None and not current["motions"] and not current["outcomes"] and len(out) >= 2 \
                and out[-1] is current and out[-2]["nth"] in (number - 1, number) and out[-2]["kind"] == "item":
            out.pop()
            out[-1]["said"].extend([current["title"]] + current["said"])
            current = out[-1]
        if current is not None:
            current["nth"] = max(current["nth"], number)

    for lines in body:
        first, words = lines[0], clean(" ".join(lines))
        if _CONSENT_LIST.match(first):
            listing, part, closed = True, next((line for line in out if line["kind"] == "consent"), None), True
            continue
        if _LABEL.match(first) and motion is not None:
            rest = []
            for place, row in enumerate(lines):  # "Ayes: ...", "Noes: ..." and "Absent: ..." a line each
                found = _LABEL.match(row)
                if found:
                    word = found[1].lower()
                    word = ("ABSENT" if word.startswith("abse") else "ABSTAIN" if word.startswith("abst") else
                            "RECUSED" if word.startswith("rec") else WORDS[word[0]])
                    motion["cast"].append((word, names_in(found[2])))
                    last = found[2]
                elif last.rstrip().endswith(",") and all(re.fullmatch(_NAME, name) for name in names_in(row)):
                    motion["cast"][-1] = (motion["cast"][-1][0], motion["cast"][-1][1] + names_in(row))  # a list that runs over the line
                    last = row
                else:
                    rest = lines[place:]  # the minutes go on to something else without a gap
                    break
            if rest:
                current["said"].append(clean(" ".join(rest)))
            continue
        consent_item = _CONSENT_ITEM.match(first) if listing else None
        if consent_item:
            line_for("item", consent_item[1], clean(" ".join([consent_item[2]] + lines[1:])), part)
            closed = False
            continue
        action, moved = _ACTION.match(first), _MOTION.match(first)
        if (action or moved) and bool(re.search(r"\bmoved by\b", words)) != bool(moved):
            action, moved = moved, action  # "ACTION #2: It was moved by ..." over "MOTION #1: Direction given ...": the two labels changed places
        if (action or moved) and current is None:
            line_for("item", "", "")
        if action:
            nth(action[1])
            current["outcomes"].append(clean(re.sub(r"^(?:ACTION|MOTION)(?:\s*#?\s*\d+)?\s*:\s*", "", words)))
            closed, motion = True, None
            continue
        if moved:
            nth(moved[1])
            said = clean(re.sub(r"^(?:ACTION|MOTION)(?:\s*#?\s*\d+)?\s*:\s*", "", words))
            motion = {"text": said, "cast": [], "away": sorted(away | aside), **said_of(said)}
            current["motions"].append(motion)
            closed, stood = True, stood or bool(aside)
            continue
        if listing:
            if current is not None and current["over"] is part and not closed:
                current["title"] = clean(f"{current['title']} {words}")
            continue
        heading = _PART.match(first)
        if heading:
            if stood:
                aside, stood = set(), False
            if heading[1] == "CONSENT AGENDA":
                part, under = line_for("consent", "", heading[1]), None
                current["said"].extend(filter(None, [clean(" ".join([heading[2]] + lines[1:]))]))
                closed = False
            elif heading[1] in ("REGULAR AGENDA", "PUBLIC HEARING", "PUBLIC HEARINGS", "REGULAR SESSION", "CLOSED SESSION") \
                    and len(words) < 400 and not re.search(r"\bACTION\b", words):
                under = line_for("part", "", words if len(words) < 60 else heading[1])
                current["said"].extend([words] if len(words) >= 60 else [])
                closed = True
            else:
                under = None
                line_for("item", "", words)  # "AGENDA: Approval of agenda for this date ...", with its motion under it
                closed = False
        elif closed and current is not None and current["motions"] and (
                _GOES_ON.match(first) or (current["said"] and re.fullmatch(r"(?:RESOLUTION|ORDINANCE) NO\.? ?[\w-]+", current["said"][-1]))):
            current["said"].append(words)  # what the motion sets out under itself, and a resolution's name under its number
        elif closed or current is None:
            if stood:
                aside, stood = set(), False
            line_for("item", "", words, under)
            closed = False
        else:
            current["said"].append(words)
        # A supervisor the minutes have out of the room is not known to be in a vote that lists nobody from there on,
        # until they have them back; one who stands aside from an item, or says he will from the next, until the item
        # that is then voted on is done. One the head has absent who comes in makes the roll at the head no guide.
        came = {clean(name) for name in _CAME.findall(words)}
        for name in came:
            if who(name, head.get("absent", [])):
                away.add(name)
            else:
                away, aside = {one for one in away if key_of(one) != key_of(name)}, {one for one in aside if key_of(one) != key_of(name)}
        people = {clean(name) for name in _SUPERVISOR.findall(words)} - came
        if people and _WENT.search(words):
            away |= people
        elif people and _ASIDE.search(words):
            aside |= people
        if re.search(r"\bpull(?:ed|ing)?\b|\bremov(?:e|ed|ing)\b", words, re.I) and re.search(r"consent", words, re.I):
            pulled.update(re.findall(r"\b\d{1,2}\.[a-z]{1,2}\b", words))

    for line in out:
        line["pulled"] = line["number"] in pulled
    return {"head": head, "lines": out}


def read_meeting(meeting, scanned, pages=0):
    """One meeting's minutes against the roll at their head: its lines, the votes on each motion that could be read
    whole, and what the reading found."""
    meeting_id, date, head = str(meeting["meeting_id"]), meeting["date"], scanned["head"]
    present = [seat["name"] for seat in head.get("roll", [])]
    absent = [name for name in head.get("absent", [])]
    facts = {"minutes": "read", "kind": head.get("kind", ""), "pages": pages, "seats": len(present) + len(absent),
             "roll": json.dumps(head.get("roll", []), ensure_ascii=False, separators=(",", ":")),
             "absent": json.dumps(absent, ensure_ascii=False, separators=(",", ":")), "motions": 0, "motions_read": 0}
    lines = scanned["lines"]
    loose, parts = 0, 0
    for line in lines:
        if line["number"]:
            line["item_id"] = f"{meeting_id}-{line['number']}"
        elif line["kind"] in ("part", "consent"):
            parts += 1
            line["item_id"] = f"{meeting_id}-s{parts}"
        else:
            loose += 1
            line["item_id"] = f"{meeting_id}-u{loose}"
    agenda, votes = [], []
    for sequence, line in enumerate(lines, 1):
        item_id, heading = line["item_id"], line["kind"] in ("part", "consent")
        matter_id = "" if heading else item_id
        for number, motion in enumerate(line["motions"], 1):
            cast, problem = decide(motion, present, absent, head.get("said", False), motion["away"])
            motion.update(read=cast is not None, problem=problem, votes=cast or [],
                          moved=named(motion["mover"], present), seconded=named(motion["seconder"], present))
            for member, word, established in motion["votes"]:
                votes.append({"item_id": item_id, "meeting_id": meeting_id, "date": date, "matter_id": matter_id, "matter_file": "",
                              "member": member, "vote": word, "motion": number, "motion_text": motion["text"], "established": established})
        last = line["motions"][-1] if line["motions"] else None
        cast = [word for _, word, _ in last["votes"]] if last else []
        ways = sorted({established for motion in line["motions"] for _, _, established in motion["votes"]})
        over = line["over"]
        shared = over is not None and over["kind"] == "consent" and not line["motions"] and not line["pulled"] and bool(over["motions"])
        told = "\n".join(line["said"])
        numbered = _NUMBER.search(" ".join(line["outcomes"])) or _NUMBER.search(told) or (_NUMBER.search(last["text"]) if last else None)
        agenda.append({
            "item_id": item_id, "meeting_id": meeting_id, "date": date, "body": BODY,
            "agenda_number": line["number"], "sequence": sequence, "matter_id": matter_id, "matter_file": "", "title": line["title"],
            "action": last["text"] if last else " ".join(line["outcomes"]),
            "result": "",  # "carried" is in the motion's words; what became of the item is in `outcome`, as the minutes put it
            "mover": last["moved"] if last else "", "seconder": last["seconded"] if last else "",
            "ayes": cast.count(council_tables.AYE), "noes": cast.count(council_tables.NO),
            "not_voting": sum(word not in (council_tables.AYE, council_tables.NO) for word in cast),
            "heading": heading, "section": over["title"] if over else "", "section_id": over["item_id"] if over else "",
            "motions": len(line["motions"]), "motions_read": sum(motion["read"] for motion in line["motions"]),
            "votes_read": all(motion["read"] for motion in line["motions"]) if line["motions"] else None,
            "problem": next((motion["problem"] for motion in line["motions"] if not motion["read"]), ""),
            "how": ("unanimous" if last["unanimous"] else "-".join(map(str, last["count"])) if last["count"] else "") if last else "",
            "established": ways[0] if len(ways) == 1 else "",
            "voted_with": item_id if line["motions"] else over["item_id"] if shared else "",
            "outcome": " | ".join(line["outcomes"]), "description": told[:DESCRIPTION],
            "doc_type": "" if heading else county.doc_type_of(f"{line['title']} {' '.join(line['outcomes'])}"),
            "number": f"{numbered[1].title()} {numbered[2]}" if numbered else "",
            "motion_log": json.dumps([{"motion": place, "text": motion["text"], "mover": motion["mover"], "seconder": motion["seconder"],
                                       "unanimous": motion["unanimous"], "count": list(motion["count"] or []), "read": motion["read"],
                                       "problem": motion["problem"]} for place, motion in enumerate(line["motions"], 1)],
                                     ensure_ascii=False, separators=(",", ":")) if line["motions"] else "",
        })
        facts["motions"] += len(line["motions"])
        facts["motions_read"] += sum(motion["read"] for motion in line["motions"])
    return agenda, votes, facts


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------

def items_table(agenda, meetings):
    """Every item in the minutes read, with what was done with it: by a vote of its own, or by its consent agenda's.

    The system has no record of an item apart from its place in the minutes, so an item is here once for each meeting
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
            "body": line.body, "status": "", "year": int(line.date[:4]), "subject": "", "agenda_date": line.date,
            "passed_date": "",  # a motion that carried may have been one to deny or put off
            "last_action": line.action if own or line.outcome else vote["action"] if vote else "",
            "last_action_date": line.date if own or line.outcome or vote else "", "result": "",
            "ayes": int(vote["ayes"]) if vote else 0, "noes": int(vote["noes"]) if vote else 0,
            "mover": vote["mover"] if vote else "", "seconder": vote["seconder"] if vote else "",
            "times_on_agenda": 1, "url": minutes.get(line.meeting_id, ""),
            "item_id": line.item_id, "meeting_id": line.meeting_id, "agenda_number": line.agenda_number, "section": line.section,
            "action_on": "item" if own else "section" if over is not None else "",
            "votes_read": bool(vote["votes_read"]) if vote else None, "number": line.number,
        })
    out = pd.DataFrame(rows, columns=ITEM_COLUMNS)
    out["votes_read"] = out["votes_read"].astype("boolean")
    return out.sort_values(["date", "meeting_id"], ascending=False, kind="stable").reset_index(drop=True)


def members_table(votes, meetings):
    """Everyone with votes here on several days, by the name, district and office the roll of the newest minutes gives them."""
    seats = {}
    for meeting in meetings[meetings["roll"] != ""].sort_values("date").itertuples(index=False):
        for seat in json.loads(meeting.roll):
            seats[seat["name"]] = seat
    days = votes.groupby("member")["date"].nunique() if len(votes) else pd.Series(dtype=int)
    cast = votes.groupby("member")["date"].agg(["min", "max", "size"]) if len(votes) else pd.DataFrame()
    since = (datetime.now(timezone.utc) - timedelta(days=SERVING_DAYS)).strftime("%Y-%m-%d")
    rows = []
    for name in sorted(days[days >= SEEN_DAYS].index):
        serving = bool(cast.loc[name, "max"] >= since)
        rows.append({"name": name, "district": seats.get(name, {}).get("district"),
                     "role": seats.get(name, {}).get("role", "") if serving else "", "start": "", "end": "", "serving": serving,
                     "first_vote": cast.loc[name, "min"], "last_vote": cast.loc[name, "max"], "votes": int(cast.loc[name, "size"])})
    out = pd.DataFrame(rows, columns=council_tables.COLUMNS["members"])
    out["district"] = out["district"].astype("Int64")
    out["serving"] = out["serving"].astype(bool)
    out["votes"] = out["votes"].astype(int)
    return out.sort_values(["first_vote", "name"]).reset_index(drop=True)


def typed(agenda, votes):
    for table, columns in ((agenda, ("sequence", "ayes", "noes", "not_voting", "motions", "motions_read")), (votes, ("motion",))):
        for column in columns:
            # Its votes are held back, so it is published with its counts emptied (without_votes), and its tables are
            # taken back from there: an empty count is 0 here, and is emptied again when published.
            table[column] = table[column].fillna(0).astype(int)
    agenda["heading"] = agenda["heading"].astype(bool)
    agenda["votes_read"] = agenda["votes_read"].astype("boolean")
    return agenda, votes


def matched(heads, rows):
    """Which document is the minutes of which meeting: ({meeting: the attachment's number}, the meetings not listed).

    `heads` is {number: head} of the documents kept. A document is a meeting's if its head gives that meeting's day,
    and its hour too where two meetings are listed that day; where two are listed at one hour, the minutes of a
    regular meeting are those of the one the system numbered first, the other being a session added to the day. Of
    several documents for one meeting (a draft, then an amended or a final one) the last attached is taken. The
    listing leaves some meetings out; minutes of a day it does not have make a meeting of their own, known by the day.
    """
    by_day = {}
    for row in rows:
        by_day.setdefault(row["date"], []).append(row)
    out, unlisted = {}, {}
    for number in sorted(heads, key=int):
        head = heads[number]
        if not head.get("date"):
            continue
        same = by_day.get(head["date"], [])
        if not same:
            meeting_id = "d" + head["date"].replace("-", "") + ("" if "SPECIAL" not in head.get("kind", "") else "s")
            unlisted[meeting_id] = {"meeting_id": meeting_id, "name": "", "date": head["date"], "time": head.get("time", ""),
                                    "agenda": "", "packet": "", "listed": False}
            out[meeting_id] = number
            continue
        if len(same) > 1:
            same = [row for row in same if row["time"] == head.get("time")]
        if len(same) > 1 and "REGULAR" in head.get("kind", ""):
            same = [min(same, key=lambda row: int(row["meeting_id"]))]
        if len(same) == 1:
            out[same[0]["meeting_id"]] = number
    return out, list(unlisted.values())


FACTS = (("minutes", ""), ("kind", ""), ("pages", 0), ("seats", 0), ("roll", ""), ("absent", ""), ("motions", 0), ("motions_read", 0))


def build(base, everything, out_dir, since=FIRST_YEAR, limit=0):
    rows = listed()
    log.info(f"Amador County: {len(rows)} meetings of the Board listed")
    if len(rows) < 20:
        raise RuntimeError("the listing of meetings came back nearly empty")

    before_votes = council_tables.held(HF_REPO, out_dir, "votes", base)
    before = 0 if before_votes is None else len(before_votes)
    state = Path(out_dir) / "text" / "found.json"
    found = json.loads(state.read_text(encoding="utf-8")) if state.exists() else {}
    found = {"agendas": found.get("agendas", {}), "documents": found.get("documents", {}), "floor": int(found.get("floor", 0))}

    def keep():
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps(found, indent=1, sort_keys=True), encoding="utf-8")

    # First the agendas, which say what minutes there are; then the minutes. Each is asked for once and slowly, and
    # what is learned is kept as it comes, so a run that is stopped has lost nothing.
    recent = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    wanted = [row for row in rows if row["agenda"] and row["date"] >= f"{since}-01-01"
              and (everything or row["meeting_id"] not in found["agendas"] or row["date"] >= recent)]
    wanted.sort(key=lambda row: (row["date"], int(row["meeting_id"])), reverse=True)  # the newest first
    wanted = wanted[:limit] if limit else wanted
    log.info(f"Reading the agendas of {len(wanted)} meetings for the minutes attached to them")
    fetched, refused = 0, False
    try:
        for place, row in enumerate(wanted, 1):
            try:
                found["agendas"][row["meeting_id"]] = attached(agenda_links(row))
            except Refused:
                raise
            except Exception as e:
                log.warning(f"agenda of {row['date']} ({row['meeting_id']}): {type(e).__name__}: {e}")
            if place % 25 == 0:
                keep()
                log.info(f"Amador County: {place} of {len(wanted)} agendas read")
        keep()

        carried = {number: (name, meeting_id) for meeting_id, documents in found["agendas"].items() for number, name in documents}
        asking = sorted((number for number in carried if number not in found["documents"] and int(number) > found["floor"]), key=int, reverse=True)
        asking = asking[:limit] if limit else asking
        log.info(f"Fetching {len(asking)} sets of minutes not fetched before")
        logins = 0
        for number in asking:
            name, meeting_id = carried[number]
            try:
                text = text_of(number, name, out_dir)
                found["documents"][number] = {"name": name, "in": meeting_id, "status": "kept"}
                fetched, logins = fetched + 1, 0
            except Closed:
                found["documents"][number] = {"name": name, "in": meeting_id, "status": "behind a login"}
                logins += 1
                if logins >= LOGINS:
                    # Attachments are numbered as they are filed, and the old ones are closed: the rest are older still.
                    found["floor"] = max(found["floor"], int(number))
                    log.info(f"{LOGINS} documents in a row are behind a login; nothing older is asked for")
                    break
            except Refused:
                raise
            except Exception as e:
                log.warning(f"minutes {number} ({name}): {type(e).__name__}: {e}")
            keep()
    except Refused as e:
        log.error(f"{e}: no more is asked in this run")
        refused = True
    keep()

    # Then every set of minutes whose text is here is read, old and new: it takes no request.
    texts, heads = {}, {}
    for number, document in found["documents"].items():
        kept = Path(out_dir) / "text" / f"{number}.txt"
        if document["status"] == "kept" and kept.exists():
            texts[number] = kept.read_text(encoding="utf-8")
            heads[number] = head_of(texts[number]) if len(re.sub(r"\s", "", texts[number])) >= LAYER_CHARS else {}
    of, unlisted = matched({number: head for number, head in heads.items() if head}, rows)
    rows = rows + unlisted
    meetings = meetings_table(rows)
    facts, new_agenda, new_votes, urls, names, carriers = {}, [], [], {}, {}, {}
    by_id = {row["meeting_id"]: row for row in rows}
    for meeting_id, number in of.items():
        text = texts[number]
        reading = read_meeting(by_id[meeting_id], scan(text), text.count("\f") + 1)
        new_agenda.extend(reading[0])
        new_votes.extend(reading[1])
        facts[meeting_id] = reading[2]
        urls[meeting_id], names[meeting_id], carriers[meeting_id] = address(number, found["documents"][number]["name"]), \
            found["documents"][number]["name"], found["documents"][number]["in"]
    # A meeting whose minutes could not be had: by the day in the file's name, which is all that is known of them.
    for number, document in found["documents"].items():
        day = re.match(rf"(?:\d+-_)?({_MONTH})_(\d{{1,2}})__?(\d{{4}})", document["name"], re.I)
        if not day or (document["status"] == "kept" and heads.get(number)):
            continue
        date = f"{day[3]}-{_MONTHS[day[1][:3].lower()]:02d}-{int(day[2]):02d}"
        same = [row for row in rows if row["date"] == date]
        if len(same) == 1 and same[0]["meeting_id"] not in facts:
            why = document["status"] if document["status"] != "kept" else "no text layer" if number in texts and not heads[number] else ""
            facts[same[0]["meeting_id"]] = {**dict(FACTS), "minutes": why}
            urls[same[0]["meeting_id"]], names[same[0]["meeting_id"]], carriers[same[0]["meeting_id"]] = \
                address(number, document["name"]), document["name"], document["in"]

    agenda, votes = typed(pd.DataFrame(new_agenda, columns=AGENDA_COLUMNS), pd.DataFrame(new_votes, columns=VOTE_COLUMNS))
    agenda = agenda.sort_values(["date", "meeting_id", "sequence"]).reset_index(drop=True)
    votes = votes.sort_values(["date", "meeting_id", "item_id", "motion", "member"]).reset_index(drop=True)
    for name, empty in FACTS:
        meetings[name] = [facts.get(meeting_id, {}).get(name, empty) for meeting_id in meetings["meeting_id"]]
    meetings["minutes_url"] = meetings["meeting_id"].map(urls).fillna("")
    meetings["minutes_name"] = meetings["meeting_id"].map(names).fillna("")
    meetings["minutes_in"] = meetings["meeting_id"].map(carriers).fillna("")
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
    ways = votes["established"].value_counts() if len(votes) else {}
    facts = {
        "repo": HF_REPO, "first_meeting": read["date"].min() if len(read) else "", "last_meeting": read["date"].max() if len(read) else "",
        "first_listed": meetings["date"].min(), "last_listed": meetings["date"].max(),
        "first_vote": votes["date"].min() if len(votes) else "", "last_vote": votes["date"].max() if len(votes) else "",
        "n_read": f"{len(read):,}", "n_closed": f"{int((meetings['minutes'] == 'behind a login').sum()):,}",
        "n_motions": f"{motions:,}", "n_motions_read": f"{motions_read:,}", "n_unread": f"{motions - motions_read:,}",
        "share_read": f"{100 * motions_read / motions:.1f}" if motions else "0",
        "recent_days": RECENT_DAYS, "serving_days": SERVING_DAYS, "seen_days": SEEN_DAYS, "first_year": FIRST_YEAR,
        **{f"n_{way}": f"{int(ways.get(way, 0)):,}" for way in (NAMED, UNANIMOUS, COUNT)},
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
        log.error(f"Amador County tables not uploaded: {e}")
        return False
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the Amador County Board's meetings, actions and votes")
    parser.add_argument("--base", action="store_true", help="start from the tables written here, not the published ones")
    parser.add_argument("--all", action="store_true", help="read every agenda again")
    parser.add_argument("--since", type=int, default=FIRST_YEAR, help="read no agenda before this year")
    parser.add_argument("--max", type=int, default=0, help="agendas and minutes to fetch in one run (0 for all)")
    parser.add_argument("--out", default="", help="directory to write the tables into (minutes_pdf/amador-county if not given)")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the tables only")

    out_dir = Path(args.out) if args.out else OUT_DIR
    try:
        tables, fetched, refused = build(args.base, args.all, out_dir, args.since, args.max)
    except Exception as e:
        log.error(f"Amador County tables not built: {type(e).__name__}: {e}")
        return 1
    pushed = False if args.no_upload else upload(tables, out_dir, args.write_card)
    meetings, agenda, votes, members = tables["meetings"], tables["agenda_items"], tables["votes"], tables["members"]
    motions, motions_read = int(agenda["motions"].sum()), int(agenda["motions_read"].sum())
    ways = votes["established"].value_counts() if len(votes) else {}
    log.info(f"RESULT: amador-board items={len(tables['items'])} meetings={len(meetings)} listed={int(meetings['listed'].sum())} "
             f"minutes_found={int((meetings['minutes_url'] != '').sum())} minutes_read={int((meetings['minutes'] == 'read').sum())} "
             f"behind_login={int((meetings['minutes'] == 'behind a login').sum())} agenda_items={len(agenda)} "
             f"motions={motions} motions_read={motions_read} motions_unread={motions - motions_read} votes={len(votes)} "
             f"named={int(ways.get(NAMED, 0))} unanimous={int(ways.get(UNANIMOUS, 0))} count={int(ways.get(COUNT, 0))} "
             f"members={len(members)} serving={int(members['serving'].sum())} "
             f"voters_not_members={len(set(votes['member']) - set(members['name']))} minutes_fetched={fetched} "
             f"first_vote={votes['date'].min() if len(votes) else ''} last_vote={votes['date'].max() if len(votes) else ''} "
             f"refused={refused} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
