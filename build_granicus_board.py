#!/usr/bin/env python3
"""
Build, for a county board of supervisors that keeps its record in Granicus's
older system (not Legistar), what a room in Capitol World is made from: its
meetings, what was on each agenda, what the board did with it, and how each
member voted where the minutes say so by name.

One source: the county's pages on granicus.com. ViewPublisher.php lists every
meeting, and MinutesViewer.php gives a meeting's minutes, which are the agenda
with what was done written under each line. Only minutes kept as a web page
are read: a county that files its minutes as a PDF for some years has those
meetings listed here with nothing under them. What differs from one county to
the next is set out in BOARDS.

Each has a dataset of its own (chrissoria/<county>-county-board), with the five
tables every council's and board's dataset has (council_tables.py), in data/:
  items.parquet          every item in a meeting's minutes
  meetings.parquet       one row per meeting the county lists
  agenda_items.parquet   one row per numbered line of a meeting's minutes, headings too, with what was done
  votes.parquet          one row per member and motion, where the minutes name who voted
  members.parquet        one row per member seen voting at the board
They are kept here in granicus/<county>/.

Two ways to run it:

    python build_granicus_board.py --county glenn-county
        The routine run. Starts from the published tables, lists every meeting
        again, and reads the minutes of meetings in the last 60 days and any
        not read before, the newest first.

    python build_granicus_board.py --county glenn-county --base
        The same, starting from the tables written here. A meeting is one
        request, four at a time: some minutes for a county with a few hundred.

    --all        read every meeting's minutes again, not only the recent and the unread
    --out DIR    where to write the tables
    --no-upload  write the tables but do not publish them
    --write-card publish the dataset card as well as the tables
"""

import argparse
import html
import json
import logging
import re
import sys
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

OUT_DIR = bills.SCRIPT_DIR / "granicus"
CARD_FILE = bills.SCRIPT_DIR / "README_granicus_board.md"  # one card for every county, with the county's own facts written in
TABLES = council_tables.TABLES
RECENT_DAYS = 60  # meetings this recent are read again: minutes are posted, and corrected, after the meeting
SEEN_DAYS = 2  # someone is a member if they vote at the board's meetings on this many days: once may be a clerk's slip
# The minutes keep no terms of office; a member who voted this recently is taken to be serving. It is half a year and
# not a season because the minutes name who voted on few motions: months can pass between two that do.
SERVING_DAYS = 180
DESCRIPTION = 4000  # the most of what the minutes say under a line that is kept with it

# `host` and `view` are where the county's listing is; `board` is how the listing names the board of supervisors.
# `numbers` is how the county numbers the lines of its agenda, the outermost first: a line of a page that is only such
# a number begins a line of the agenda, and the line under it is its title. The rest is what one clerk does and
# another does not:
#   top_motions  motions are written at the foot of a numbered item, after the lettered lines under it, and are the item's
#   lift         a line with this title is where the vote on the heading above it is written
#   inline       a line of the agenda whose number and title are written together
#   end          where the agenda stops and the notes printed at the foot of every page begin
#   skip         rows of the listing that are not meetings
BOARDS = {
    "glenn-county": {"host": "glenncounty.granicus.com", "view": 9, "name": "Glenn", "board": r"Board of Supervisors|^Special Meeting$",
                     "numbers": [r"\d+\.", r"[a-z]{1,2}\."], "top_motions": True, "skip": r"^Technical Testing$"},
    # Butte's minutes are a web page only from June 2021 to May 2024: before that they are PDFs, which are not read,
    # the last meetings here have none, and from August 2024 the County's record is in CivicClerk
    # (build_civicclerk_board.py).
    # In the one dataset of county boards its tables are the earlier part of Butte's (`repo`), before CivicClerk's.
    "butte-county": {"host": "buttecounty.granicus.com", "view": 2, "name": "Butte", "board": r"Board of Supervisors|Board Meeting",
                     "repo": "chrissoria/butte-county-earlier-board",
                     "numbers": [r"\d+[A-Z]?\.", r"\d+\.\d+\.?", r"[A-Z]\.", r"\d+\)"],
                     "lift": r"(?i)^adopt(ion of)?( the)? consent agenda",
                     "end": r"^(Consent Agenda: [Tt]hese (are )?items|Meeting Information:|Agenda Format and Meeting Order:)"},
    # Marin's minutes are not prose where it matters: each motion is a line "M/s <mover> - <seconder> to ...", and the
    # vote is under it as "AYES:", "NOES:" and "ABSENT:" with the names, or "AYES: ALL". The Board's budget hearings
    # are listed apart, as "Budget 2025"; the Spanish recording of a meeting is listed as a meeting of its own.
    "marin-county": {"host": "marin.granicus.com", "view": 33, "name": "Marin", "board": r"Board of Supervisors|BOS|^Budget \d{4}$",
                     "numbers": [r"\d+\.", r"C[AB]-?\d+\.", r"[a-z]{1,3}\."],
                     "inline": r"(C[AB] ?- ?\d+)\.\s+(\S.*)", "skip": r"^Spanish Audio Files$"},
}

ITEM_COLUMNS = council_tables.COLUMNS["items"] + ["item_id", "meeting_id", "agenda_number", "section", "action_on", "number",
                                                  "unanimous", "tally", "named"]
MEETING_COLUMNS = council_tables.COLUMNS["meetings"] + ["name", "minutes_format"]
AGENDA_COLUMNS = council_tables.COLUMNS["agenda_items"] + ["heading", "section", "section_id", "motions", "motions_named", "unanimous",
                                                           "tally", "named", "description", "doc_type", "number", "motion_log"]
VOTE_COLUMNS = council_tables.COLUMNS["votes"] + ["motion", "motion_text"]


class Refused(Exception):
    """The host answered with a bot check, a login or a refusal. Nothing more is asked of it in this run."""


REFUSED = set()  # hosts that have answered so
_CHALLENGE = re.compile(r"captcha|just a moment|cf-chl|challenge-platform|access denied|you have been blocked", re.I)


def repo_of(key):
    return BOARDS[key].get("repo") or f"chrissoria/{key}-board"


def fetch(url, tries=4):
    """A page of the county's as text, or "" where what is there is not a web page (minutes filed as a PDF).

    A PDF is not downloaded: only what kind of thing it is is asked for.
    """
    host = urlsplit(url).netloc
    for attempt in range(tries):
        if host in REFUSED:
            raise Refused(host)
        try:
            with requests.get(url, headers=county.HEADERS, timeout=90, stream=True) as answer:
                if answer.status_code in (401, 403, 429):
                    REFUSED.add(host)
                    raise Refused(f"{host} answered {answer.status_code}")
                answer.raise_for_status()
                if "html" not in answer.headers.get("content-type", "").lower():
                    return ""
                answer.encoding = answer.encoding or "utf-8"
                page = answer.text
            if _CHALLENGE.search(page[:3000]) and "granicus" not in page[:3000].lower():
                REFUSED.add(host)
                raise Refused(f"{host} answered with a challenge")
            return page
        except requests.RequestException as e:
            # A host that is not allowed will not be allowed on a second asking.
            if attempt == tries - 1 or isinstance(e, requests.exceptions.ProxyError):
                raise
            time.sleep(2 * (attempt + 1))


# ---------------------------------------------------------------------------
# The listing of meetings
# ---------------------------------------------------------------------------

_MONTHS = {name: number for number, name in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}


def plain(text):
    """A piece of a page as text."""
    return clean(html.unescape(re.sub(r"<[^>]+>", " ", str(text or ""))).replace("\xa0", " "))


def date_of(text):
    """`Aug 18, 2026` or `06/23/26` as `2026-08-18`: each county's listing writes its dates its own way."""
    found = re.search(r"([A-Za-z]{3})[a-z]*\.? +(\d{1,2}), +(\d{4})", text)
    if found and found[1].lower() in _MONTHS:
        return f"{found[3]}-{_MONTHS[found[1].lower()]:02d}-{int(found[2]):02d}"
    found = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\b", text)
    if found:
        return f"{int(found[3]) % 100 + 2000}-{int(found[1]):02d}-{int(found[2]):02d}"
    return ""


def time_of(text):
    found = re.search(r"\b(\d{1,2}):(\d\d) ?([AP]M)\b", text, re.I)
    return f"{int(found[1])}:{found[2]} {found[3].upper()}" if found else ""


def link_of(row, viewer):
    found = re.search(rf'href="([^"]*{viewer}\.php[^"]*)"', row)
    return ("https:" if found[1].startswith("//") else "") + html.unescape(found[1]) if found else ""


def meetings_table(key, page):
    """Every meeting on the county's listing: a row of the page each, known by the number Granicus gives its recording."""
    board, rows, seen = BOARDS[key], [], set()
    for row in re.split(r"(?i)<tr\b", page):
        clip = re.search(r"clip_id=(\d+)", row)
        names = re.findall(r'(?s)headers="Name"[^>]*>(.*?)</td>', row)  # where there are two, the first is the month
        day = re.search(r'headers="Date[^"]*"[^>]*>(.*?)</td>', row, re.S)
        if not clip or not names or not day or clip[1] in seen:
            continue  # a heading of the listing, or a meeting to come with nothing filed yet, or a row printed twice
        name = plain(names[-1])
        if board.get("skip") and re.search(board["skip"], name):
            continue
        seen.add(clip[1])
        when = plain(re.sub(r"(?is)<span[^>]*display:\s*none[^>]*>.*?</span>", " ", day[1]))  # a hidden number to sort by
        rows.append({
            "meeting_id": clip[1], "date": date_of(when), "time": time_of(when),
            "body": "Board of Supervisors" if re.search(board["board"], name) else name,
            "location": "",
            "url": f"https://{board['host']}/MediaPlayer.php?view_id={board['view']}&clip_id={clip[1]}",
            "agenda_url": link_of(row, "AgendaViewer"), "minutes_url": link_of(row, "MinutesViewer"),
            "items": 0, "name": name, "minutes_format": "",
        })
    out = pd.DataFrame(rows, columns=MEETING_COLUMNS)
    return out.sort_values(["date", "meeting_id"], key=lambda column: column if column.name == "date" else column.astype(int)
                           ).reset_index(drop=True)


# ---------------------------------------------------------------------------
# A meeting's minutes
# ---------------------------------------------------------------------------

_TAG = re.compile(r"(?is)<(script|style)\b.*?</\1\s*>|<!--.*?-->|<(/?)([a-z][a-z0-9]*)\b[^>]*>")
_BLOCK = {"br", "div", "p", "tr", "td", "th", "li", "ul", "ol", "table", "tbody", "blockquote", "title", "h1", "h2", "h3", "h4", "h5"}

_TITLE = (r"(?:Su?p[a-z]*[vr][a-z]*s[a-z]*|Commissioners?|Directors?|Vice[- ]?Chair(?:man|woman|person)?|Chair(?:man|woman|person)?"
          r"|Vice[- ]President|President|Board Members?|Members?)")  # "Spervisors", "Superisor", "Supervsor": the clerks' own
_NAME = r"[A-Z][A-Za-z'’]+(?:-[A-Z][A-Za-z'’]+)?"  # a surname, as the minutes give it
_PERSON = rf"(?:{_TITLE}\s+)+({_NAME})"
# The words a vote is listed under, and the one word each is kept as before council_tables.vote_word has it.
_VOTE_LABEL = r"ayes?|yeas?|noe?s?|naye?s?|absent|abstain(?:ed|ing|s)?|abstentions?|recused?|recusals?"
# Where a list of votes begins on a line: at its head, or after a stop, a count ("Vote 4-0-1 Ayes:") or the word "vote".
_VOTES = re.compile(rf"(?i)(?:^|[(:;.,]\s*|\d\s+|\bvotes?\s+)\b({_VOTE_LABEL})\s*:\s*")
_MORE_VOTES = re.compile(rf"(?i)\b({_VOTE_LABEL})\s*:\s*")  # and the labels after the first, however they are set off
_LABEL_ALONE = re.compile(rf"(?i)^(motion/second|order|vote|{_VOTE_LABEL})\s*:$")
_NUMBER_LIKE = re.compile(r"(?:C[AB]-?\d+|\d+[A-Z]?|\d+\.\d+|[A-Za-z]{1,2})[.)]")
_LABELLED = re.compile(rf"(?i)^(motion/second|order|vote|motion(?:ed)?|second(?:ed)?|action|{_VOTE_LABEL})\s*:")
_NOBODY = re.compile(r"(?i)^(none|n/?a|0|-+)?$")
_EVERYBODY = re.compile(r"(?i)^(all|unanimous\w*)$")
_TALLY = re.compile(r"\b(\d)\s*-\s*(\d)(?:\s*-\s*(\d))?(?:\s*-\s*(\d))?\b")
_CARRIED = re.compile(r"(?i)^(?:[a-z]{1,2}\. )?(?:(?:the )?motion(?:ed)?\b[^.;]*?\b(?:passed|carried|carries|passes|approved|adopted|failed|fails|denied|died|dies)\b"
                      r"|unanimously (?:approved|passed|carried|adopted)\b)")
_FOLLOWING = re.compile(r"(?i)[,:;]?\s*(?:by|with) the following (?:roll[- ]call )?votes?\s*[:;.]?\s*$")  # "... by the following vote:"
_FAILED = re.compile(r"(?i)\b(failed|fails|denied|died|dies)\b")
_ON_MOTION = re.compile(rf"(?i:\bon (?:a )?motion (?:of|by)) {_PERSON}(.*?)(?i:,?\s*second(?:ed)?,? by) {_PERSON},?\s*(.*)$")
_MOVED_BY = re.compile(rf"(?i:\b(?:moved|motioned)(?: [a-z ]{{1,30}})? by) {_PERSON}\s*[;,.]?\s*(?i:and )?(?i:second(?:ed)?(?: by)?) (?:{_TITLE}\s+)*({_NAME})")
_ROLL = re.compile(rf"(?:[a-z]{{1,2}}\. )?{_PERSON}\s*[-–—:]\s*(?i:(ayes?|yes|yeas?|nays?|noe?s?|abstain\w*|absent|recus\w*))\s*[.;,]?")
_MOVED = re.compile(rf"^{_PERSON} (?i:moved|made a motion|motioned)\b(.*?)(?:[;,.]\s*{_PERSON} (?i:seconded).*)?$")
_MS = re.compile(rf"^M/[Ss]\s*(?:{_PERSON})?\s*-\s*(?:{_PERSON})?\s*(.*)$")
_NAMED_LINE = re.compile(r"^(?:Items? (?:No\.? )?)?((?:C[AB]-?)?\d+(?:\.\d+)?[A-Za-z]?)\.?(?=\s|$)\s*(.*)$")
_NUMBERED = re.compile(r"\b(Resolution|Ordinance)(?: (?:No\.?|Number|#))? ?(\d{2,4}-\d{1,4}|\d{3,5})\b", re.I)


def lines_of(page):
    """A page of minutes as its lines of text, a label that stands alone joined to what it labels."""
    lines, buffer, position = [], [], 0

    def end_line():
        text = clean(html.unescape("".join(buffer)).replace("\xa0", " "))
        if text:
            lines.append(text)
        buffer.clear()

    for tag in _TAG.finditer(page):
        buffer.append(page[position:tag.start()])
        position = tag.end()
        if tag.group(1) or (tag.group(3) or "").lower() in _BLOCK:
            end_line()
    buffer.append(page[position:])
    end_line()

    joined = []
    for line in lines:
        # "Vote:" and under it "Unanimous."; "AYES:" and under it the names. Not "Order:" left empty above "Vote:", and
        # not the number of the next line of the agenda.
        above = joined[-1] if joined else ""
        if (_LABEL_ALONE.match(above) and not _NUMBER_LIKE.fullmatch(line)
                and (not _LABELLED.match(line) or (above.lower() == "vote:" and _VOTES.match(line)))):
            joined[-1] = f"{above} {line}"
        else:
            joined.append(line)
    return joined


def person(text):
    """The name in `Supervisor Rossman` or `Vice-Chair Teeter`, or "" if what is there is not one name."""
    text = clean(text).strip(" .,;:)(")
    name = re.sub(rf"^(?:{_TITLE}\s+)+", "", text.title() if text.isupper() else text)  # "SUPERVISOR RODONI"
    return name if re.fullmatch(_NAME, name) else ""


def names_of(text):
    """The people listed after `Ayes:`, and whether the list says who: `None` names nobody, and `ALL` does not say who.

    A piece of the list that is not a name is left out, not guessed at.
    """
    text = clean(re.sub(r"\([^)]*\)?", " ", text)).strip(" .;,)")
    if _NOBODY.match(text):
        return [], True
    if _EVERYBODY.match(text):
        return [], False
    names = [person(piece) for piece in re.split(r",|;|&|/|\band\b|\.\s", text)]
    return [name for name in names if name], True


def votes_in(line):
    """The votes a line lists, as (word, names, whether it says who) for each label on it."""
    first = _VOTES.search(line)
    labels = [first] + [label for label in _MORE_VOTES.finditer(line) if label.start() >= first.end()] if first else []
    found = []
    for label, following in zip(labels, labels[1:] + [None]):
        word = label.group(1).upper()
        word = ("ABSTAIN" if word.startswith("ABST") else "RECUSED" if word.startswith("RECUS") else
                "NOES" if word.startswith("N") else "AYES" if word == "AYE" else word)
        names, says_who = names_of(line[label.end():following.start() if following else len(line)])
        found.append((council_tables.vote_word(word), names, says_who))
    return found


def outcome(words):
    """What a line says became of a motion: `Pass` or `Fail` or "", the count if it gives one, and whether it says all agreed."""
    said = {}
    if _FAILED.search(words) and not re.search(r"(?i)\bit was (?:\w+ )?order", words):
        said["result"] = "Fail"
    elif re.search(r"(?i)\b(passed|carried|carries|passes|approved|adopted|unanimous\w*|(?:it was|was|were) (?:so )?order\w*)\b", words):
        said["result"] = "Pass"
    tally = _TALLY.search(words)
    if tally:
        said["tally"] = "-".join(part for part in tally.groups() if part is not None)
    if re.search(r"(?i)\bunanim", words):
        said["unanimous"] = True
    return said


def said_in(line):
    """What a line of minutes says of a motion: who moved and seconded it, its words, what became of it, who voted how.

    Empty for a line that is about something else. The forms are the ones these counties' clerks write:
      Motion/Second: Supervisor Rossman/Supervisor Withrow      Order: Approve the Consent Calendar.      Vote: Unanimous.
      On motion of Supervisor Arnold, seconded by Supervisor Rossman, it was ordered to ... by the following Roll Call Vote:
      Motion: Supervisor Teeter      Seconded: Supervisor Durfee      Motion passed 4-0-1      Ayes: ... Nays: ... Recused: ...
      Motion moved by Supervisor Lucero; Seconded by Supervisor Ritter.
      M/s Supervisor Kinsey - Supervisor Sears to accept report ...      Vote: Motion carried 3-1      AYES: ...      NOES: ...
    """
    said = {}
    words = line  # what is left of the line to look for an outcome and votes in
    found = _ROLL.fullmatch(line)
    if found:  # a roll call written one member to a line: "Supervisor Corum - Nay"
        word = found[2].upper()
        word = ("AYES" if word[0] in "AY" and word != "ABSENT" and not word.startswith("ABST") else "NOES" if word[0] == "N" else
                "ABSTAIN" if word.startswith("ABST") else "RECUSED" if word.startswith("RECUS") else word)
        return {"votes": [(council_tables.vote_word(word), [found[1]], True)], "roll": True}
    if re.search(r"(?i)\bpresent\s*:", line):
        return {}  # who was at the meeting, and who was absent from it, is not a vote
    found = re.match(r"(?i)^motion/second\s*:\s*(.*)$", line)
    if found:
        mover, _, seconder = found[1].partition("/")
        return {"mover": person(mover), "seconder": person(seconder), "begins": True}
    found = re.match(r"(?i)^order\s*:\s*(.*)$", line)
    if found:
        return {"text": clean(found[1]), "more_text": True}
    found = re.match(r"(?i)^vote\s*:\s*(.*)$", line)
    if found:
        words, said["vote"] = found[1], True
    elif _ON_MOTION.search(line):
        found = _ON_MOTION.search(line)
        words = clean(f"{found[2]} {found[4]}").lstrip(", ")
        text = _VOTES.split(words)[0]
        text = _FOLLOWING.sub("", text).strip(" ;:,")
        said.update(mover=found[1], seconder=found[3], text=text, begins=True, **outcome(text))
    elif _MS.match(line):
        found = _MS.match(line)
        return {"mover": found[1] or "", "seconder": found[2] or "", "text": clean(found[3]), "begins": True}
    elif _MOVED_BY.search(line):
        found = _MOVED_BY.search(line)
        before = re.sub(r"(?i)^motion\s*:?\s*", "", line[:found.start()]).strip(" .;,")
        said.update(mover=found[1], seconder=found[2], begins=True)
        if re.match(r"(?i)to\b", before):
            said["text"] = before
        words = line[found.end():]
        said["vote"] = bool(outcome(words))
    elif re.match(rf"(?i)^motion(?:ed)?\s*:\s*{_PERSON}", line):
        found = re.match(rf"(?i:^motion(?:ed)?\s*:\s*){_PERSON}(.*)$", line)
        said.update(mover=found[1], begins=True)
        if clean(found[2]).strip(" ."):
            said["text"] = clean(f"{found[1]} {found[2]}")
        return said
    elif re.match(rf"(?i)^second(?:ed)?(?: by)?\s*:\s*{_PERSON}", line):
        return {"seconder": re.match(rf"(?i:^second(?:ed)?(?: by)?\s*:\s*){_PERSON}", line)[1]}
    elif _MOVED.match(line) and re.search(r"(?i)\bseconded\b", line):
        found = _MOVED.match(line)
        return {"mover": found[1], "seconder": found[3] or "", "text": clean(found[2]).strip(" .;,"), "begins": True}
    elif _CARRIED.match(line):
        said["vote"] = True
        about = _FOLLOWING.sub("", _MORE_VOTES.split(line)[0]).strip(" ;:,")
        if re.search(r"(?i)\bmotion to\b", about):
            said["about"] = re.sub(r"^[a-z]{1,2}\. ", "", about)
    elif re.match(r"(?i)^(?:motion|action)\s*:\s*\S", line) or re.match(r"(?i)^motion to \S", line):
        return {"text": re.sub(r"(?i)^(?:motion|action)\s*:\s*", "", line), "begins": True}
    elif not _VOTES.search(line):
        return {}
    else:  # a list of votes, with or without what became of the motion written before it on the line
        before = line[:_VOTES.search(line).start()].strip(" (;:,")
        said["vote"] = bool(outcome(before))
        words = line if said["vote"] else line[_VOTES.search(line).start():]
        if said["vote"] and len(before) > 40:
            said["about"] = before

    if said.get("vote"):
        said.update(outcome(words))
    votes = votes_in(words)
    if votes:
        said["votes"] = votes
    if said.get("vote") and not votes and "result" not in said and "tally" not in said and not said.get("unanimous"):
        said["note"] = clean(words)
    return said


def voted(motion):
    """Whether the minutes have got as far as the vote on a motion."""
    return bool(motion and (motion["result"] or motion["votes"] or motion["unanimous"] or motion["tally"]))


def read_minutes(key, meeting, page):
    """One meeting's minutes: the lines of its agenda, and the votes on each motion the minutes name the voters of.

    A motion is kept on the line it is written under. Where the minutes say a motion carried, or carried unanimously,
    and do not say who voted, the line has what was done and the count if one is given, and there are no votes for it:
    nobody is put down as voting aye because they were at the meeting.
    """
    board = BOARDS[key]
    meeting_id, date = str(meeting["meeting_id"]), meeting["date"]
    levels = [re.compile(pattern) for pattern in board["numbers"]]
    inline = re.compile(board["inline"]) if board.get("inline") else None
    end = re.compile(board["end"]) if board.get("end") else None
    lift = re.compile(board["lift"]) if board.get("lift") else None

    entries, motions = [], []  # the lines of the agenda, and every motion with the place in `entries` of the line it is on
    path = []  # the line being read and the headings it sits under, outermost first
    motion, last, wants_title = None, "", False

    def close():
        nonlocal motion
        # A line of words with nobody moving it, no outcome and no votes is what was asked for, not a motion.
        if motion and (motion["mover"] or voted(motion)):
            if motion["unanimous"] and not motion["result"]:
                motion["result"] = "Pass"  # "AYES: ALL"
            motions.append(motion)
        motion = None

    def begin(number, title=""):
        nonlocal wants_title, path
        level = next((place for place, pattern in enumerate(levels) if pattern.fullmatch(number)), len(levels))
        # A motion moved under a heading and voted on at the foot of it, after the items the heading holds, is still
        # open when those items begin.
        if not (motion and motion["mover"] and not voted(motion) and level > entries[motion["on"]]["level"]):
            close()
        path = [entry for entry in path if entry["level"] < level]
        entry = {"number": number.rstrip(".").replace(" ", ""), "title": title, "level": level, "said": [],
                 "over": path[-1] if path else None, "place": len(entries)}
        entries.append(entry)
        path.append(entry)
        wants_title = not title

    lines = lines_of(page)
    # What is written above the first numbered line, or all of it where the minutes number nothing (a budget hearing),
    # is kept as a line of its own if a motion is written there, under the page's own heading.
    entries.append({"number": "", "title": lines[0] if lines else "", "level": 0, "said": [], "over": None, "place": 0})
    for line in lines:
        if end and end.match(line):
            if wants_title:  # the number of the first of the notes at the foot of the page
                entries.pop()
            break
        if any(pattern.fullmatch(line) for pattern in levels):
            begin(line)
            continue
        if inline and inline.fullmatch(line):
            begin(inline.fullmatch(line)[1] + ".", inline.fullmatch(line)[2])
            continue
        entry = entries[-1]
        if wants_title:
            entry["title"], wants_title = line, False
            continue
        said = said_in(line)
        if not said:
            if voted(motion):
                close()  # the vote is over where the minutes go on to something else
            elif motion and motion["more_text"] and len(motion["text"]) < 1500:
                motion["text"] = clean(f"{motion['text']} {line}")
            if not motion or not motion["more_text"]:
                entry["said"].append(line)
            last = line
            continue

        labels = {word for word, _, _ in said.get("votes", [])}
        cast = labels & {council_tables.AYE, council_tables.NO}
        # The line ends the motion being read and starts the next where it moves a motion and this one has a mover
        # already or has been voted on; where it gives an outcome, or a list of ayes, and this one has one already;
        # or where it gives a seconder or a motion's words after the vote.
        if motion and ((said.get("begins") and (voted(motion) or (said.get("mover") and motion["mover"])))
                       or (said.get("vote") and (motion["result"] or motion["tally"]))
                       or (cast & motion["labels"] and not (said.get("roll") and motion["roll"]))
                       or (voted(motion) and ("seconder" in said or "text" in said) and not said.get("vote"))):
            close()
        if motion is None:
            if not (said.get("begins") or said.get("vote") or cast or "text" in said or said.get("mover")):
                entry["said"].append(line)  # "Absent: None" under the roll call, or a seconder with no motion
                last = line
                continue
            on = path[0] if board.get("top_motions") and path else entry
            if lift and lift.match(on["title"]) and on["over"]:
                on = on["over"]
            before = motions[-1] if motions else None
            alone = not said.get("begins") and not said.get("vote") and "text" not in said  # a list of votes and no more
            if (alone and before and before["on"] == on["place"] and not before["votes"] and not before["unanimous"]
                    and re.search(r"(?i)\bmotion\b", last)):
                # "On motion of ..., it was ordered to approve", then discussion, then "the motion passed with the
                # following roll call vote:" and the names: the vote is that motion's.
                motion = motions.pop()
                motion.update(outcome(last))
            else:
                motion = {"on": on["place"], "text": "", "mover": "", "seconder": "", "result": "", "tally": "", "unanimous": False,
                          "votes": [], "labels": set(), "named": False, "note": "", "more_text": False, "roll": False}
                if alone and re.search(r"(?i)\bvotes?\s*[:;.]?$", last):
                    # "It was the consensus of the Board to continue discussions by the following vote:" above the names.
                    motion["text"] = re.sub(r"^[a-z]{1,2}\. ", "", _FOLLOWING.sub("", last).strip(" ;:,"))
                elif not said.get("begins") and "text" not in said and re.match(r"(?i)^items? ", last) and len(last) < 200:
                    # "Item 3.24" above "Motion passed 4-0-1": a vote taken apart from the one before it, with no mover written.
                    motion["text"] = last
        motion["more_text"] = bool(said.get("more_text"))
        motion["roll"] = bool(said.get("roll"))
        for field in ("mover", "seconder", "result", "tally", "note"):
            if said.get(field):
                motion[field] = said[field]
        if said.get("text") or (said.get("about") and not motion["text"]):
            motion["text"] = said.get("text") or said["about"]
        motion["unanimous"] = motion["unanimous"] or bool(said.get("unanimous"))
        for word, names, says_who in said.get("votes", []):
            motion["labels"].add(word)
            if not says_who and word == council_tables.AYE:
                motion["unanimous"] = True  # "AYES: ALL"
            for name in names:
                if (name, word) not in motion["votes"]:  # the same vote written twice
                    motion["votes"].append((name, word))
        last = line
    close()

    # A motion that names another line of the agenda is that line's: "Item 3.24" under the consent agenda's vote, or
    # "3. Consent Calendar A" where the page prints a heading's motion after the items under it.
    by_number = {}
    for entry in entries:
        by_number.setdefault(entry["number"].upper(), entry)
    for motion in motions:
        found = _NAMED_LINE.match(motion["text"])
        named = by_number.get(found[1].upper()) if found else None
        if named and (re.match(r"(?i)^items? ", motion["text"]) or (found[2] and named["title"].startswith(found[2][:40]))):
            motion["on"] = named["place"]

    if not any(motion["on"] == 0 for motion in motions):
        entries[0]["left_out"] = True  # nothing was moved above the first numbered line: it is the head of the page
    heads = {entry["over"]["place"] for entry in entries if entry["over"]}
    agenda, votes, sequence = [], [], 0
    for entry in entries:
        if entry.get("left_out"):
            continue
        sequence += 1
        item_id = f"{meeting_id}-{sequence}"
        entry["item_id"] = item_id
        heading = entry["place"] in heads
        own = [motion for motion in motions if motion["on"] == entry["place"]]
        log_of = []
        for number, motion in enumerate(own, 1):
            motion["named"] = bool(motion["votes"])
            for name, word in motion["votes"]:
                votes.append({"item_id": item_id, "meeting_id": meeting_id, "date": date, "matter_id": "" if heading else item_id,
                              "matter_file": "", "member": name, "vote": word, "motion": number, "motion_text": motion["text"]})
            log_of.append({"motion": number, "text": motion["text"], "mover": motion["mover"], "seconder": motion["seconder"],
                           "result": motion["result"], "tally": motion["tally"], "unanimous": motion["unanimous"],
                           "named": motion["named"], "note": motion["note"]})
        final = own[-1] if own else None
        ayes, noes, others = counted(final) if final else (0, 0, 0)
        words = "\n".join(entry["said"])
        numbered = _NUMBERED.search(" ".join([entry["title"], words] + [motion["text"] for motion in own]))
        agenda.append({
            "item_id": item_id, "meeting_id": meeting_id, "date": date, "body": meeting["body"],
            "agenda_number": entry["number"], "sequence": sequence, "matter_id": "" if heading else item_id, "matter_file": "",
            "title": entry["title"], "action": final["text"] if final else "", "result": final["result"] if final else "",
            "mover": final["mover"] if final else "", "seconder": final["seconder"] if final else "",
            "ayes": ayes, "noes": noes, "not_voting": others,
            "heading": heading, "section": entry["over"]["title"] if entry["over"] else "",
            "section_id": entry["over"]["item_id"] if entry["over"] else "",
            "motions": len(own), "motions_named": sum(motion["named"] for motion in own),
            "unanimous": bool(final and final["unanimous"]), "tally": final["tally"] if final else "",
            "named": bool(final and final["named"]),
            "description": words[:DESCRIPTION],
            "doc_type": "" if heading else county.doc_type_of(entry["title"]),
            "number": f"{numbered[1].title()} {numbered[2]}" if numbered else "",
            "motion_log": json.dumps(log_of, ensure_ascii=False, separators=(",", ":")) if log_of else "",
        })
    return agenda, votes


def counted(motion):
    """A motion's ayes, noes and others: counted from the names where the minutes give them, and otherwise the count they give."""
    if motion["votes"]:
        words = [word for _, word in motion["votes"]]
        ayes, noes = words.count(council_tables.AYE), words.count(council_tables.NO)
        return ayes, noes, len(words) - ayes - noes
    parts = [int(part) for part in motion["tally"].split("-")] if motion["tally"] else []
    return (parts[0], parts[1], sum(parts[2:])) if len(parts) >= 2 else (0, 0, 0)


def read_meeting(key, meeting):
    """A meeting's minutes read from the county's page: what kind of thing they are, the agenda's lines, and the votes."""
    page = fetch(meeting["minutes_url"])
    if not page:
        return "pdf", [], []
    agenda, votes = read_minutes(key, meeting, page)
    # A page with no line of an agenda on it is a page that came back wrong as often as minutes with nothing in them:
    # it is not put down as read, and the next run asks for it again.
    return ("html" if agenda else ""), agenda, votes


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------

def items_table(agenda, meetings):
    """Every item in a meeting's minutes, with what was done with it: on its own motion, or failing that on the motion
    of the nearest heading above it that has one.

    The minutes have no record of an item apart from its line, so an item is here once for each meeting it came to.
    """
    of = agenda.set_index("item_id")
    page_of = meetings.set_index("meeting_id")["minutes_url"].to_dict()
    rows = []
    for line in agenda[~agenda["heading"]].itertuples(index=False):
        done, over = (line._asdict() if line.motions > 0 else None), line.section_id
        while done is None and over in of.index:
            done, over = (of.loc[over].to_dict() if of.loc[over, "motions"] > 0 else None), of.loc[over, "section_id"]
        rows.append({
            "date": line.date, "matter_id": line.item_id, "matter_file": "", "doc_type": line.doc_type, "title": line.title,
            "body": line.body, "status": "", "year": int(line.date[:4]) if line.date[:4].isdigit() else 0,
            "subject": "", "agenda_date": line.date,
            "passed_date": "",  # the system has no day an item passed: a motion that carried may have been one to deny or put off
            "last_action": done["action"] if done else "", "last_action_date": line.date if done else "",
            "result": done["result"] if done else "",
            "ayes": int(done["ayes"]) if done else 0, "noes": int(done["noes"]) if done else 0,
            "mover": done["mover"] if done else "", "seconder": done["seconder"] if done else "",
            "times_on_agenda": 1, "url": page_of.get(line.meeting_id, ""),
            "item_id": line.item_id, "meeting_id": line.meeting_id, "agenda_number": line.agenda_number, "section": line.section,
            "action_on": "" if done is None else "item" if line.motions > 0 else "section",
            "number": line.number, "unanimous": bool(done["unanimous"]) if done else False,
            "tally": done["tally"] if done else "", "named": bool(done["named"]) if done else False,
        })
    out = pd.DataFrame(rows, columns=ITEM_COLUMNS)
    return out.sort_values(["date", "meeting_id"], ascending=False, kind="stable").reset_index(drop=True)


def members_table(votes, meetings):
    """Everyone named as voting at the board's own meetings on several days. The minutes give a surname, and no terms or districts."""
    sat = set(meetings.loc[meetings["body"] == "Board of Supervisors", "meeting_id"])
    days = votes[votes["meeting_id"].isin(sat)].groupby("member")["date"].nunique()
    cast = votes.groupby("member")["date"].agg(["min", "max", "size"])
    since = (datetime.now(timezone.utc) - timedelta(days=SERVING_DAYS)).strftime("%Y-%m-%d")
    rows = [{"name": name, "district": None, "role": "", "start": "", "end": "",
             "serving": bool(cast.loc[name, "max"] >= since),
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


def build(key, base, everything, out_dir, every=100):
    board = BOARDS[key]
    meetings = meetings_table(key, fetch(f"https://{board['host']}/ViewPublisher.php?view_id={board['view']}"))
    log.info(f"{board['name']}: {len(meetings)} meetings listed, {int((meetings['minutes_url'] != '').sum())} with minutes")
    if len(meetings) < 10:
        raise RuntimeError("the listing of meetings came back nearly empty")

    agenda, votes, before_meetings = (council_tables.held(repo_of(key), out_dir, name, base) for name in ("agenda_items", "votes", "meetings"))
    before = 0 if votes is None else len(votes)
    if agenda is None or votes is None or before_meetings is None:
        agenda, votes = pd.DataFrame(columns=AGENDA_COLUMNS), pd.DataFrame(columns=VOTE_COLUMNS)
    else:
        # What kind of thing a meeting's minutes were found to be is what says they were read: minutes that are a
        # PDF leave no lines behind.
        meetings["minutes_format"] = meetings["meeting_id"].map(before_meetings.set_index("meeting_id")["minutes_format"]).fillna("")
    recent = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    wanted = meetings[(meetings["minutes_url"] != "")
                      & (everything | (meetings["minutes_format"] == "") | (meetings["date"] >= recent))]
    wanted = wanted.sort_values("date", ascending=False, kind="stable").to_dict("records")  # the newest first: a room shows those
    log.info(f"Reading the minutes of {len(wanted)} meetings")

    read = 0
    for start in range(0, max(len(wanted), 1), every):
        some = wanted[start:start + every]
        new_agenda, new_votes, done = [], [], {}
        for meeting, found in zip(some, county.together(lambda meeting: read_meeting(key, meeting), some, "meeting")):
            if found is None:
                continue  # what is held for it stands, and the next run asks again
            done[meeting["meeting_id"]] = found[0]
            new_agenda.extend(found[1])
            new_votes.extend(found[2])
        new_agenda = pd.DataFrame(new_agenda, columns=AGENDA_COLUMNS)
        new_votes = pd.DataFrame(new_votes, columns=VOTE_COLUMNS)
        agenda = joined(agenda[~agenda["meeting_id"].isin(done)], new_agenda)
        votes = joined(votes[~votes["meeting_id"].isin(done)], new_votes)
        agenda = agenda.sort_values(["date", "meeting_id", "sequence"]).reset_index(drop=True)
        votes = votes.sort_values(["date", "meeting_id", "item_id", "motion", "member"]).reset_index(drop=True)
        for table, columns in ((agenda, ("sequence", "ayes", "noes", "not_voting", "motions", "motions_named")), (votes, ("motion",))):
            for column in columns:
                table[column] = table[column].astype(int)
        for column in ("heading", "unanimous", "named"):
            agenda[column] = agenda[column].astype(bool)
        meetings["minutes_format"] = meetings["meeting_id"].map(done).fillna(meetings["minutes_format"])
        # Which body a meeting was of is the listing's to say, and is said again each run.
        agenda["body"] = agenda["meeting_id"].map(meetings.set_index("meeting_id")["body"]).fillna(agenda["body"])
        meetings["items"] = meetings["meeting_id"].map(agenda[~agenda["heading"]].groupby("meeting_id").size()).fillna(0).astype(int)
        council_tables.write_tables({"meetings": meetings, "agenda_items": agenda, "votes": votes}, out_dir)
        read += len(done)
        log.info(f"{board['name']}: {min(start + every, len(wanted))} of {len(wanted)} meetings asked for, {len(votes)} votes held")
        if REFUSED:
            raise Refused(f"{', '.join(sorted(REFUSED))} answered with a bot check or a refusal; stopped there")

    tables = council_tables.standard({
        "items": items_table(agenda, meetings), "meetings": meetings, "agenda_items": agenda, "votes": votes,
        "members": members_table(votes, meetings),
    })
    council_tables.write_tables(tables, out_dir)
    if len(votes) < before * 0.98:
        raise RuntimeError(f"only {len(votes)} votes where there were {before}; not publishing")
    return tables, read


def motions_of(agenda):
    """How many motions the minutes record, and how many of them name who voted."""
    return int(agenda["motions"].sum()), int(agenda["motions_named"].sum())


def card(key, tables):
    """The dataset card: the one every county has, with this one's name, addresses and counts written in."""
    board, meetings, votes, agenda = BOARDS[key], tables["meetings"], tables["votes"], tables["agenda_items"]
    read = meetings[meetings["items"] > 0]
    motions, named = motions_of(agenda)
    pdfs = int((meetings["minutes_format"] == "pdf").sum())
    span = (f"Votes by member run from {votes['date'].min()} to {votes['date'].max()}." if len(votes) else
            "No motion in the minutes read names who voted, so the `votes` and `members`\ntables are empty.")
    facts = {
        "title": f"{board['name']} County Board of Supervisors", "place": board["name"], "repo": repo_of(key),
        "host": board["host"], "view": board["view"],
        "first_meeting": read["date"].min() if len(read) else "", "last_meeting": read["date"].max() if len(read) else "",
        "first_listed": meetings["date"].min(), "last_listed": meetings["date"].max(),
        "vote_span": span, "bodies": f"{meetings['body'].nunique():,}", "serving_days": SERVING_DAYS, "seen_days": SEEN_DAYS,
        "n_read": f"{len(read):,}", "n_pdf": f"{pdfs:,}", "n_motions": f"{motions:,}", "n_named": f"{named:,}",
        "share_named": f"{named / motions:.0%}" if motions else "0%",
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
    parser = argparse.ArgumentParser(description="Build a Granicus county's meetings, minutes and votes")
    parser.add_argument("--county", "--body", required=True, choices=sorted(BOARDS), help="the county whose board to read")
    parser.add_argument("--base", action="store_true", help="start from the tables written here, not the published ones")
    parser.add_argument("--all", action="store_true", help="read every meeting's minutes again")
    parser.add_argument("--out", default="", help="directory to write the tables into (granicus/<county> if not given)")
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
    motions, named = motions_of(agenda)
    log.info(f"RESULT: granicus-{args.county} items={len(tables['items'])} meetings={len(meetings)} "
             f"meetings_with_minutes_read={agenda['meeting_id'].nunique()} minutes_as_pdf={int((meetings['minutes_format'] == 'pdf').sum())} "
             f"agenda_items={len(agenda)} motions={motions} motions_named={named} votes={len(votes)} "
             f"members={len(members)} serving={int(members['serving'].sum())} "
             f"voters_not_members={len(set(votes['member']) - set(members['name']))} meetings_read={read} "
             f"first_vote={votes['date'].min() if len(votes) else ''} last_vote={votes['date'].max() if len(votes) else ''} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
