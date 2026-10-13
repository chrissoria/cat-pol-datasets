#!/usr/bin/env python3
"""
Build chrissoria/alameda-county-board: the meetings of the Alameda County Board
of Supervisors, what was on each agenda, what the Board did with it, and how
each supervisor voted.

One source: the County's listing of its meetings in Granicus
(alamedacounty.granicus.com/ViewPublisher.php?view_id=2), one page of HTML that
links each meeting's agenda and its minutes as PDFs. The system has no record
of a vote apart from the minutes, so the votes here are read from them.

The minutes print a vote as two short rows in the left margin, beside what the
Board did, and a key at their foot that says what the rows are made of:

    32451   Approved as recommended                    ** KEY **
    32X51                                              Left Margin Notes
                                                       1 President Haubert      A Abstained
                                                       2 Supervisor Márquez     X Excused
                                                       3 Supervisor Tam         N No
                                                       4 Supervisor Miley
                                                       5 Supervisor Fortunato Bas

The first row is the supervisors' numbers. The second has, under each number,
that number again or the letter for what that supervisor did instead of voting
aye. So this one is four ayes with Supervisor Miley excused. Which number a
letter stands under is a matter of where it is on the page, which the plain
text of a PDF does not keep, so the rows are read from the place of each
character (layout() below).

From 2025 some minutes also say the vote in words ("The motion passed with 4
Ayes: Supervisors Márquez, Miley, Tam and President Haubert; 1 Excused:
Supervisor Fortunato Bas"). Those are read too, and where a motion has both,
the two must agree.

A vote is read whole or not at all. Rows that do not pass (one row with no
second, a mark the key does not give, minutes with no key or with a key that
names someone the head of the minutes does not) put nothing in the votes: the
motion is kept, with what stopped the reading (`problem`), and counted as
unread.

The dataset has the five tables every council's and board's dataset has
(council_tables.py), in data/:
  items.parquet          every item in the minutes that were read
  meetings.parquet       one row per meeting of the Board listed
  agenda_items.parquet   one row per item of the minutes, with what was done
  votes.parquet          one row per supervisor and motion voted on
  members.parquet        one row per supervisor seen in a vote that was read
They are kept here in minutes_pdf/alameda-county/, with the text of each set of
minutes beside them in text/, so minutes are fetched once.

Two ways to run it:

    python build_alameda_board.py
        The routine run. Starts from the published tables, reads the listing
        again, and reads the minutes not read before and those of meetings in
        the last 90 days (minutes are posted weeks after their meeting).

    python build_alameda_board.py --base
        The same, starting from the tables written here. It reads the newest
        meeting first and can be stopped and started again.

    --since YEAR  read no meeting before this year (default 2014, where the listing begins)
    --max N       sets of minutes to read in one run (default 0, for all)
    --all         read every set of minutes again, from the text kept here where there is some
    --out DIR     where to write the tables
    --no-upload   write the tables but do not publish them
    --write-card  publish the dataset card as well as the tables

Needs pypdfium2. Only a PDF's own text is read: minutes that are a scan are
counted and left.
"""

import argparse
import html
import json
import logging
import re
import sys
import threading
import time
import unicodedata
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

import build_federal_bills as bills
import build_sd_county as county
import council_tables
from build_sd_county import clean, today

log = logging.getLogger(__name__)

HF_REPO = "chrissoria/alameda-county-board"
OUT_DIR = bills.SCRIPT_DIR / "minutes_pdf" / "alameda-county"
CARD_FILE = bills.SCRIPT_DIR / "README_alameda_board.md"
TABLES = council_tables.TABLES
BODY = "Board of Supervisors"

HOST = "https://alamedacounty.granicus.com"
VIEW = 2  # the County's one listing, of the Board and of its committees and commissions
# The headings of the listing under which the Board itself meets. The rest are its committees and other bodies.
SECTIONS = ("BOS Regular Meetings", "BOS Planning Meetings", "Special Meetings", "Special Meeting - Agendas Only",
            "Budget Meetings", "Redistricting Public Hearings and Meetings")
FIRST_YEAR = 2014  # the listing begins here
RECENT_DAYS = 90  # meetings this recent are read again: the minutes come weeks later
LAYER_CHARS = 200  # a PDF with fewer characters of its own than this is a scan

MEETING_COLUMNS = council_tables.COLUMNS["meetings"] + ["name", "kind", "minutes", "pages", "roll", "key", "vote_blocks", "blocks_read"]
AGENDA_COLUMNS = council_tables.COLUMNS["agenda_items"] + [
    "section", "motions", "vote_blocks", "blocks_read", "votes_read", "problem", "mover_from", "doc_type", "number", "notes", "motion_log"]
VOTE_COLUMNS = council_tables.COLUMNS["votes"] + ["district", "motion", "motion_text", "source"]
ITEM_COLUMNS = council_tables.COLUMNS["items"] + ["item_id", "meeting_id", "section", "votes_read", "mover_from", "number", "notes"]

# What the key at the foot of the minutes says each letter in the margin is, and the word kept for it here.
MARKS = {"A": "ABSTAIN", "X": "EXCUSED", "N": council_tables.NO}
# The words the minutes use when they say a vote in a sentence.
SAID = {"excused": "EXCUSED", "recused": "RECUSED", "abstain": "ABSTAIN", "abstained": "ABSTAIN", "abstention": "ABSTAIN",
        "abstentions": "ABSTAIN", "no": council_tables.NO, "noes": council_tables.NO, "nay": council_tables.NO,
        "nays": council_tables.NO, "absent": "ABSENT"}
# Where a vote was read from. The last is a vote in the margin that leaves a supervisor out, with words beside it that
# say the supervisor stood aside.
MARGIN, WORDS, BOTH, ASIDE = "margin", "words", "margin and words", "margin, recusal in words"


class Refused(Exception):
    """The host answered with a check, a login or a refusal. It is not asked again in this run."""


class NotPDF(Exception):
    """What the listing links as a meeting's minutes is a page of HTML: a few special meetings have only that."""


_refused = threading.Event()
_CHECK = re.compile(r"captcha|cf-challenge|are you a human|access denied|sign in to continue", re.I)


def fetch(url, tries=4):
    """One answer from the County's listing. A refusal is not tried again, and nothing more is asked of the host in this run."""
    if _refused.is_set():
        raise Refused("the host refused an earlier request")
    for attempt in range(tries):
        try:
            # The host now and then leaves a connection hanging, so the wait to connect is short.
            answer = requests.get(url, headers=county.HEADERS, timeout=(20, 180))
            page = "html" in answer.headers.get("content-type", "") and answer.content[:4] != b"%PDF"
            if answer.status_code in (401, 403, 429) or (page and _CHECK.search(answer.text[:20000])):
                _refused.set()
                raise Refused(f"{answer.status_code} from {url.split('?')[0]}")
            answer.raise_for_status()
            return answer
        except requests.RequestException as e:
            # A host that is not allowed will not be allowed on a second asking.
            if attempt == tries - 1 or isinstance(e, requests.exceptions.ProxyError):
                raise
            time.sleep(2 * (attempt + 1))


# ---------------------------------------------------------------------------
# The listing
# ---------------------------------------------------------------------------

_HEADING = re.compile(r"<h3>(.*?)</h3>", re.S)
_ROW = re.compile(r'<tr class="(?:odd|even)".*?</tr>', re.S)
_NAME = re.compile(r'scope="row">(.*?)</td>', re.S)
_DAY = re.compile(r'display:none;">\d+</span>\s*([A-Z][a-z]{2})(?:&nbsp;|\s)+(\d{1,2}),(?:&nbsp;|\s)+(\d{4})')
_CLIP = re.compile(r"clip_id=(\d+)")
_MINUTES = re.compile(r"MinutesViewer\.php\?view_id=\d+&(?:amp;)?clip_id=\d+&(?:amp;)?doc_id=([0-9a-fA-F-]+)")


def rows_of(page):
    """The Board's meetings on the listing, as the system has them. A meeting is known by the number of its recording."""
    headings = [(found.start(), clean(re.sub(r"<[^>]+>", "", found[1]))) for found in _HEADING.finditer(page)]
    rows = {}
    for (start, kind), (end, _) in zip(headings, headings[1:] + [(len(page), "")]):
        if kind not in SECTIONS:
            continue
        for row in _ROW.findall(page[start:end]):
            name, day, clip, minutes = _NAME.search(row), _DAY.search(row), _CLIP.search(row), _MINUTES.search(row)
            if not (day and clip) or clip[1] in rows:
                continue
            try:
                date = datetime.strptime(f"{day[1]} {day[2]} {day[3]}", "%b %d %Y").strftime("%Y-%m-%d")
            except ValueError:
                continue
            rows[clip[1]] = {"meeting_id": clip[1], "name": clean(html.unescape(re.sub(r"<[^>]+>", "", name[1]))) if name else "",
                             "kind": kind, "date": date, "agenda": "AgendaViewer.php" in row, "video": "MediaPlayer.php" in row,
                             "doc": minutes[1] if minutes else ""}
    return list(rows.values())


def listed():
    """Every meeting of the Board the system lists. The listing is one page, of everything since 2014."""
    return rows_of(fetch(f"{HOST}/ViewPublisher.php?view_id={VIEW}").text)


def meetings_table(rows):
    """One row per meeting listed. What a reading adds (`minutes`, `pages`, `roll`, `key` and the counts) is filled in by build()."""
    of = lambda page, row: f"{HOST}/{page}.php?view_id={VIEW}&clip_id={row['meeting_id']}"
    out = [{
        "meeting_id": row["meeting_id"], "date": row["date"], "time": "", "body": BODY, "location": "",
        "url": of("MediaPlayer", row) if row["video"] else of("AgendaViewer", row) if row["agenda"] else "",
        "agenda_url": of("AgendaViewer", row) if row["agenda"] else "",
        "minutes_url": f"{of('MinutesViewer', row)}&doc_id={row['doc']}" if row["doc"] else "",
        "items": 0, "name": row["name"], "kind": row["kind"],
        "minutes": "", "pages": 0, "roll": "", "key": "", "vote_blocks": 0, "blocks_read": 0,
    } for row in rows]
    return pd.DataFrame(out, columns=MEETING_COLUMNS).sort_values(["date", "meeting_id"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# The text of the minutes, with the margins kept apart
# ---------------------------------------------------------------------------
#
# A page of the minutes has three columns: the votes in the left margin, in small type; what the item is and what was
# done with it; and file, contract and resolution numbers on the right. layout() writes a page as lines of
#
#     left <tab> middle <tab> right
#
# (a line with nothing in either margin is the middle alone), with a space before the middle where the line is set in
# from the left edge, which is how a title's second line is told from a heading. The two rows of a vote are written as
# one, `32451/32X51`:
# the first row, a stroke, and the second set under the first, with a dot where nothing stands under a number
# (`32451/..X..`) and a question mark where a character of the second row stands under none of them.

SMALL = 10.0  # type smaller than this, in points, is the margin's; the rest of the minutes is in 11 and 12
MARGIN_WIDTH = 45.0  # a row in the margin is no wider than this
MARGIN_LEFT = 90.0  # and begins left of here
NOTES_LEFT = 465.0  # the notes on the right begin right of here
UNDER = 1.7  # how far left or right of a number a character under it may stand
INSET = 10.0  # a line that begins this far right of the items' numbers is set in
_NOTE = re.compile(r"(?:FILE\b|(?:C|R|O|BO|LIB)\s?-\s?\w)")
_NUMBER_ALONE = re.compile(r"\d{1,3}(?:\.\d{1,2})?\s?\.")
_pdfium = threading.Lock()  # pdfium is not safe to use from two threads at once


def characters(page):
    """A page's characters as (character, left, right, baseline, size), in points from the page's lower left."""
    import ctypes
    import pypdfium2.raw as raw
    text = page.get_textpage()
    left, right, bottom, top, x, y = (ctypes.c_double() for _ in range(6))
    out = []
    for index in range(text.count_chars()):
        character = chr(raw.FPDFText_GetUnicode(text.raw, index))
        if character in "\r\n\x00￾":
            continue
        raw.FPDFText_GetCharBox(text.raw, index, left, right, bottom, top)
        raw.FPDFText_GetCharOrigin(text.raw, index, x, y)
        out.append((character, left.value, right.value, y.value, raw.FPDFText_GetFontSize(text.raw, index)))
    return out


def rows_at(chars, within):
    """Characters as rows by their baselines, the top of the page first, each row from left to right."""
    rows = []
    for char in sorted(chars, key=lambda char: -char[3]):
        if rows and abs(rows[-1][0] - char[3]) <= within:
            rows[-1][1].append(char)
        else:
            rows.append([char[3], [char]])
    for row in rows:
        row[1].sort(key=lambda char: char[1])
    return rows


def margin_rows(chars):
    """(the rows in the left margin, the other characters). A row in the margin is a few small characters at the left
    edge, each a supervisor's number, a letter of the key, or a character the PDF gives no letter for. Small type that
    runs on across the page (the notice on the first page) or is something else (the typist's initials) is not the
    margin's."""
    small = rows_at([char for char in chars if 2 < char[4] < SMALL and char[0].strip()], 1.5)
    rows = [(base, row) for base, row in small if row[0][1] < MARGIN_LEFT and row[-1][2] - row[0][1] <= MARGIN_WIDTH and len(row) <= 8
            and all(char[0] in "12345AXNaxn" or not char[0].isprintable() for char in row)]
    taken = {id(char) for _, row in rows for char in row}
    return rows, [char for char in chars if id(char) not in taken]


def spoken(row):
    """A row of characters as text. A space is put where the characters stand apart, and two where they stand far apart."""
    out, before = "", None
    for char in row:
        if char[0].isspace():
            out += " "
            continue
        gap = char[1] - before[2] if before else 0
        if gap > 12:
            out = out.rstrip() + "  "
        elif before and gap > 0.25 * max(char[4], before[4], 6) and not out.endswith(" "):
            out += " "
        out += char[0]
        before = char
    return re.sub(r"(?<! ) (?! )| {3,}", lambda found: " " if len(found[0]) == 1 else "  ", out).strip()


def printable(text):
    """A margin row as text. A character the PDF gives no letter for is a question mark."""
    return "".join(char if char.isprintable() and not char.isspace() else "?" for char in text)


def set_under(top, under):
    """The second row of a vote set under the first: one character for each of the first row's, a dot where nothing
    stands under it. With a question mark in front, as it is printed, if a character stands under none of them or two
    stand under one."""
    raw = printable("".join(char[0] for char in under))
    if len(under) == len(top) and all(abs(below[1] - above[1]) <= 2 * UNDER + 0.2 for above, below in zip(top, under)):
        return raw  # five under five: each under its own, give or take the width of a letter
    slots = ["."] * len(top)
    for char in under:
        nearest = min(range(len(top)), key=lambda index: abs(top[index][1] - char[1]))
        if abs(top[nearest][1] - char[1]) > UNDER or slots[nearest] != ".":
            return "?" + raw
        slots[nearest] = printable(char[0])
    return "".join(slots)


def pitch_of(pages):
    """How far the second row of a vote stands below the first in this document, in points: the commonest distance
    between a row of numbers in the margin and the row under it. It is 9 in most minutes and 12 to 15 in some."""
    seen = Counter()
    for rows in pages:
        for (base, row), (below, _) in zip(rows, rows[1:]):
            if 6 <= base - below <= 16 and re.fullmatch(r"[1-5]{3,5}", "".join(char[0] for char in row)):
                seen[round(2 * (base - below)) / 2] += 1
    return seen.most_common(1)[0][0] if seen else None


def margin_notes(rows, pitch):
    """The margin's rows as [(baseline, text)]: each vote's two rows as one.

    A row with numbers and letters in it (`1345X`) can only be a second row, and goes with the row of numbers just
    above it. Rows of numbers alone that follow one another at the document's pitch are a vote's two; where three do,
    or five, the page does not say which two belong together, and each is written with a question mark so that none
    is read. A row of letters alone (`X`) is the second row of the numbers just above it, however near it was set;
    under numbers that already have a second row it is a mark the reader can make nothing of, and spoils them.
    """
    texts = [printable("".join(char[0] for char in row)) for _, row in rows]
    kinds = ["numbers" if re.fullmatch(r"[1-5]+", text) else "both" if re.search(r"[1-5]", text) else "letters" for text in texts]
    pairs, paired = [], set()
    for index in range(1, len(rows)):
        if kinds[index] == "both" and kinds[index - 1] == "numbers" and index - 1 not in paired and 3 <= rows[index - 1][0] - rows[index][0] <= 16:
            pairs.append((index - 1, index))
            paired.update((index - 1, index))
    # each note: [baseline, first row, second row, the lowest baseline it reaches, its text if it is not to be read]
    notes = [[rows[top][0], rows[top][1], rows[under][1], rows[under][0], ""] for top, under in pairs]
    notes += [[rows[index][0], rows[index][1], None, rows[index][0], ""] for index, kind in enumerate(kinds) if kind == "both" and index not in paired]
    alone, at = [index for index, kind in enumerate(kinds) if kind == "numbers" and index not in paired], 0
    while at < len(alone):
        run = [alone[at]]
        while pitch and at + len(run) < len(alone) and abs(rows[run[-1]][0] - rows[alone[at + len(run)]][0] - pitch) <= 1.5:
            run.append(alone[at + len(run)])
        at += len(run)
        if len(run) % 2:
            notes.extend([rows[index][0], rows[index][1], None, rows[index][0], "?" + texts[index] if len(run) > 1 else ""] for index in run)
        else:
            notes.extend([rows[top][0], rows[top][1], rows[under][1], rows[under][0], ""] for top, under in zip(run[::2], run[1::2]))
    for index, kind in enumerate(kinds):
        if kind != "letters":
            continue
        base, row = rows[index]
        above = [note for note in notes if 0 < note[3] - base <= 16]
        note = min(above, key=lambda note: note[3] - base) if above else None
        if note is None:
            notes.append([base, row, None, base, ""])
        elif note[2] is None and not note[4] and re.fullmatch(r"[1-5]+", "".join(char[0] for char in note[1])):
            note[2], note[3] = row, base
        else:
            note[4] = (note[4] or "?" + printable("".join(char[0] for char in note[1]))) + "?" + texts[index]
            note[3] = base
    out = []
    for base, top, under, _, unread in notes:
        first = printable("".join(char[0] for char in top))
        out.append((base, unread or (first if under is None else first + "/" + set_under(top, under))))
    return sorted(out, key=lambda note: -note[0])


def page_lines(chars, rows, pitch):
    """One page as lines, each [baseline, left, middle, right, where the middle begins]."""
    lines = []
    for _, row in rows_at([char for char in chars if char[0].strip() or char[4] > 2], 3.0):
        base = sorted(char[3] for char in row)[len(row) // 2]
        cut = next((index for index, char in enumerate(row) if char[1] >= NOTES_LEFT and char[0].strip()
                    and (index == 0 or row[index - 1][0].isspace() or char[1] - row[index - 1][2] > 1 or char[0] == "F")
                    and _NOTE.match(spoken(row[index:]))), None)
        right = spoken(row[cut:]) if cut is not None else ""
        middle = spoken(row[:cut] if cut is not None else row)
        if middle or right:  # a row of spaces alone is nothing
            lines.append([base, "", middle, right, next((char[1] for char in row if char[0].strip()), row[0][1])])
    for alone in [line for line in lines if _NUMBER_ALONE.fullmatch(line[2]) and not line[3]]:
        # An item's number set a little above or below its title's first line: the two are one line.
        beside = min((line for line in lines if line is not alone), key=lambda line: abs(line[0] - alone[0]), default=None)
        if beside is not None and abs(beside[0] - alone[0]) <= 8 and not _NUMBER_ALONE.match(beside[2]):
            beside[2], beside[4] = f"{alone[2]} {beside[2]}", alone[4]
            lines.remove(alone)
    for base, text in margin_notes(rows, pitch):
        beside = min(lines, key=lambda line: abs(line[0] - base)) if lines else None
        if beside is not None and abs(beside[0] - base) <= 5 and not beside[1]:
            beside[1] = text
        else:
            lines.append([base, text, "", "", 0])
    lines.sort(key=lambda line: -line[0])
    return [line for line in lines if any(line[1:4])]


def edge_of(pages):
    """Where the items' numbers stand in this document, in points from the left: the commonest place a line that
    opens with a number begins. None if no line does."""
    seen = Counter(round(line[4]) for lines in pages for line in lines if _NUMBER_ALONE.match(line[2]))
    return seen.most_common(1)[0][0] if seen else None


def written(lines, edge):
    """A page's lines as text. A line set in from where the items' numbers stand (the rest of a title, what was done
    with the item) has a space before its middle column; a heading, like a number, stands at the edge and has none."""
    out = []
    for _, left, middle, right, begins in lines:
        middle = (" " if edge is not None and middle and begins > edge + INSET else "") + middle
        out.append(f"{left}\t{middle}\t{right}" if left or right else middle)
    return "\n".join(out)


def layout(body):
    """The text a PDF carries, a page at a time, the margins kept apart. Nothing is read off the picture of a page."""
    import pypdfium2
    with _pdfium:
        document = pypdfium2.PdfDocument(body)
        try:
            pages = [margin_rows(characters(page)) for page in document]
        finally:
            document.close()
    pitch = pitch_of([rows for rows, _ in pages])
    pages = [page_lines(rest, rows, pitch) for rows, rest in pages]
    edge = edge_of(pages)
    return [written(lines, edge) for lines in pages]


def text_of(meeting, out_dir, fresh=False):
    """The text of a meeting's minutes, pages parted by form feeds: from the copy kept here, or fetched and kept."""
    kept = Path(out_dir) / "text" / f"{meeting['meeting_id']}.txt"
    if kept.exists() and not fresh:
        return kept.read_text(encoding="utf-8")
    time.sleep(0.3)
    body = fetch(meeting["minutes_url"]).content
    if body[:4] != b"%PDF":
        raise NotPDF("the system sent a page in place of the minutes")
    text = "\f".join(layout(body))
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(text, encoding="utf-8")
    return text


_FURNITURE = re.compile(r"MINUTES\s*[-–]\s*BOARD OF SUPERVISORS.{0,90}?PAGE\s*\d+|SUMMARY\s?AC\s?TION MINUTE\s?S", re.I)


def lines_of(text, set_in=False):
    """The minutes' lines in order as (left, middle, right), without the head and foot of each page. With `set_in`,
    each also says whether it is set in from the left edge."""
    out = []
    for line in text.replace("\f", "\n").split("\n"):
        left, middle, right = line.split("\t") if line.count("\t") == 2 else ("", line, "")
        inset, middle = middle.startswith(" "), _FURNITURE.sub(" ", middle).strip()
        if left or middle or right:
            out.append((left.strip(), middle, right.strip()) + ((inset,) if set_in else ()))
    return out


# ---------------------------------------------------------------------------
# Who sits on the Board, and which number each is
# ---------------------------------------------------------------------------

_KEY = re.compile(r"\*\s*\*\s*KEY\s*\*\s*\*", re.I)
_KEY_LINE = re.compile(r"^([1-5])\.?\s+((?:Vice[- ]*)?President|Supervis[oe]r)\s+(\S.*?)(?=\s+(?:A:?\s+Abst|X:?\s+Exc|N:?\s+N\s?o\b|BO:?\s+Board)|$)")
_LETTERS = (re.compile(r"\bA:?\s+Abstained\b"), re.compile(r"\bX:?\s+Excused\b"), re.compile(r"\bN:?\s+N\s?o\b"))
_SEAT = re.compile(r"^(.*?)(?:,\s*((?:VICE[- ]*)?PRESIDENT))?\s*(?:DISTRICT\s+([1-5]))?$")
_HEAD_END = re.compile(r"^(MISSION|VISION|CALL(ED)? TO ORDER)\b")
_EMPTY_SEAT = re.compile(r"^(of\s*District\b|Vacant\b)", re.I)
_TITLE = r"(?:(?:vice[- ]*)?president|supervisors?)"


def plain(text):
    """Text without accents or capitals, a character for a character: Márquez is spelled both ways in the minutes."""
    return "".join(unicodedata.normalize("NFD", char)[0] for char in str(text or "")).lower()


def named(name):
    """A name set in capitals at the head of the minutes, as it is written elsewhere: ELISA MÁRQUEZ is Elisa Márquez."""
    return " ".join(word.capitalize() for word in clean(name).split())


def office_of(word):
    word = plain(word)
    return "Vice President" if word.startswith("vice") else "President" if word.startswith("president") else ""


def head_of(lines):
    """What stands at the head of the minutes, a piece at a time: [(words in capitals, office, district, line)].

    The head has the place of the meeting on the left, the supervisors in the middle and their districts on the right.
    The three are told apart by the wide gaps between them. A district is given only where it stands on its
    supervisor's own line, which it does not always: in some minutes that column sits a line higher or lower.
    """
    end = next((index for index, (_, middle, _) in enumerate(lines[:40]) if _HEAD_END.match(middle)), min(len(lines), 16))
    pieces = []
    for line, (_, middle, _) in enumerate(lines[:end]):
        parts = [part.strip() for part in re.split(r"\s{2,}", middle) if part.strip()]
        for index, part in enumerate(parts):
            seat = _SEAT.match(part)
            beside = re.fullmatch(r"DISTRICT\s+([1-5])", parts[index + 1]) if index + 1 < len(parts) else None
            if seat[1].strip() and re.fullmatch(r"[A-ZÀ-Ý][A-ZÀ-Ý.'’ -]+", seat[1].strip()):
                pieces.append((seat[1].strip(), office_of(seat[2] or ""), int(seat[3] or (beside[1] if beside else 0)), line))
    return pieces


def key_of(lines):
    """The key at the foot of the minutes: ({number: surname}, {number: office}, where it begins), or ({}, {}, None).

    A seat that stands empty is in the key with no name ("2 Supervisor of District 2"), and is left out here.
    """
    start = next((index for index, (_, middle, _) in enumerate(lines) if _KEY.search(middle)), None)
    if start is None:
        return {}, {}, None
    foot = [clean(middle) for _, middle, _ in lines[start:start + 12]]
    if not all(letter.search(" ".join(foot)) for letter in _LETTERS):
        return {}, {}, start  # a key that does not say what A, X and N are fixes nothing
    surnames, offices = {}, {}
    for line in foot:
        found = _KEY_LINE.match(line)
        if found and int(found[1]) not in offices:
            offices[int(found[1])] = office_of(found[2])
            if not _EMPTY_SEAT.match(found[3]):
                surnames[int(found[1])] = clean(found[3])
    return surnames, offices, start


def roll_of(lines):
    """Who sat on the Board that day, from the minutes themselves: (roll, seats, why not).

    `roll` is the supervisors, each {name, district, role}, by which a vote said in words is read. `seats` is
    {number: name}, by which the margin is read. The key at the foot gives each number a surname, and the head of the
    minutes has the names in full, in capitals, in the order of their districts; a supervisor's name here is the
    forename from the head and the surname as the key writes it. `seats` is empty, with the reason in `why not`,
    unless every surname in the key is at the head, in the same order. Minutes are sometimes written up after the
    Board has changed, with the new Board's key under the old Board's head; the numbers in such minutes are not read.

    Where the key cannot be used, the roll is those at the head with an office or a district on their own line.
    """
    head = head_of(lines)
    alone = [{"name": named(words), "district": district or None, "role": office} for words, office, district, _ in head
             if (office or district) and words != "VACANT" and 2 <= len(words.split()) <= 4]
    surnames, offices, start = key_of(lines)
    if start is None:
        return alone, {}, "no key in the minutes" if alone else "no supervisors at the head of the minutes"
    if len(surnames) < 3 or len(offices) < 5:
        return alone, {}, "the key does not give five numbers and the letters"
    roll, place = [], (-1, -1)
    for number in sorted(surnames):
        surname = surnames[number]
        at = [(line, index) for index, (words, _, _, line) in enumerate(head)
              if re.search(rf"^\S+( \S+)? {re.escape(plain(surname))}$", plain(words))]
        if len(at) != 1:
            return alone, {}, f"the key gives {number} to {surname}, who is not at the head of the minutes"
        if at[0] < place:
            return alone, {}, f"the key gives {number} to {surname}, whom the head of the minutes lists out of that order"
        place = at[0]
        words, office = head[place[1]][:2]
        roll.append({"name": clean(f"{named(words[:len(words) - len(surname)])} {surname}"), "district": number,
                     "role": offices[number] or office})
    return roll, {member["district"]: member["name"] for member in roll}, ""


def who_at(text, at, roll):
    """(the supervisor named in `text` at `at`, where the name ends), or (None, at). An office may stand before the name.

    A supervisor is named by a surname: the last word of the name at the head, or the last two or three.
    """
    lowered = plain(text)
    start = re.compile(rf"\s*(?:{_TITLE}\s*)?").match(lowered, at).end()
    best = (None, at, 0)
    for member in roll:
        words = plain(member["name"]).split()
        for count in range(len(words), 0, -1):
            found = re.compile(r"\s*".join(re.escape(word) for word in words[-count:]) + r"(?![a-z])").match(lowered, start)
            if found and count > best[2]:
                best = (member["name"], found.end(), count)
    return best[:2]


# ---------------------------------------------------------------------------
# Reading a vote
# ---------------------------------------------------------------------------

def read_margin(code, seats):
    """A vote in the margin: ({supervisor: word}, why it is not whole, who moved, who seconded).

    `code` is the two rows as layout() writes them, `32451/32X51`. The vote is whole, and "" is returned for the reason,
    when the first row is supervisors' numbers, none twice; the second has under each number that number or a letter
    of the key, or nothing; the numbers that are in the second row are just those of the first that have no letter
    under them; and every supervisor in the key is in the first row. In most minutes until 2020 the second row has the
    numbers of those who voted aye in rising order, and since 2021 in the order of the first row; either passes, and a
    row that says one thing by its numbers and another by where its letters stand does not.

    A vote that is not whole comes back with what it does say, so that words beside it can be held to it, or with None
    if it says nothing that can be relied on.
    """
    top, stroke, under = code.partition("/")
    if not seats:
        return None, "no key to read the margin by", "", ""
    if not re.fullmatch(r"[1-5]{2,5}", top) or len(set(top)) != len(top) or any(int(digit) not in seats for digit in top):
        return None, f"not supervisors' numbers: {code[:20]}", "", ""
    mover, seconder = seats[int(top[0])], seats[int(top[1])]
    if not stroke:
        return None, "one row in the margin and no second", mover, seconder
    under = under.upper()
    if len(under) != len(top) or not re.fullmatch(r"[1-5AXN.]+", under):
        return None, f"the second row does not stand under the first: {code[:20]}", mover, seconder
    marked = {digit: mark for digit, mark in zip(top, under) if mark in MARKS}
    numbers = [mark for mark in under if mark.isdigit()]
    if numbers and sorted(numbers) != sorted(set(top) - set(marked)):
        return None, f"the numbers of the second row are not those left unmarked in the first: {code[:20]}", mover, seconder
    if not numbers and not marked:
        return None, f"nothing in the second row: {code[:20]}", mover, seconder
    cast = {seats[int(digit)]: MARKS[marked[digit]] if digit in marked else council_tables.AYE for digit in top}
    out = sorted(set(seats) - {int(digit) for digit in top})
    if out:
        return cast, f"{' and '.join(str(number) for number in out)} not in the margin", mover, seconder
    return cast, "", mover, seconder


_AYES = re.compile(r"(\d)\s*ayes?\b\s*:?", re.I)
_OTHERS = re.compile(r"\s*[;,.]?\s*(?:and\s+)?(\d)\s*(excused|recused|abstain(?:ed)?|abstentions?|no(?:es)?|nays?|absent)\b\s*:?", re.I)
_BETWEEN = re.compile(r"\s*(?:,\s*and\b|,|\band\b|&)?\s*")
_OUTCOME = re.compile(r"\bmotion\s*(passed|carried|failed)", re.I)
_SECONDED = re.compile(r"seconded\s*by", re.I)


def names_at(text, at, roll):
    """(the supervisors listed in `text` from `at`, where the list ends)."""
    listed, end = [], at
    while True:
        name, after = who_at(text, _BETWEEN.match(text, end).end(), roll)
        if name is None:
            return listed, end
        listed.append(name)
        end = after


def read_words(text, roll):
    """The votes a passage says in words, in order: [{cast, problem, ayes, result, start, end}].

    "The motion passed with 4 Ayes: Supervisors Márquez, Miley, Tam and President Haubert; 1 Excused: Supervisor
    Fortunato Bas". Such a vote is whole when each count is followed by that many supervisors of the roll, nobody is
    named twice, and everybody on the roll is named. "Passed unanimously with 5 Ayes", with nobody named, is whole when
    the roll has five. `cast` is None, and `problem` says why, when it is not whole; `ayes` is the count stated.
    """
    out, at = [], 0
    while True:
        found = _AYES.search(text, at)
        if not found:
            return out
        groups = [(council_tables.AYE, int(found[1])) + names_at(text, found.end(), roll)]
        end = groups[0][3]
        while True:
            more = _OTHERS.match(text, end)
            if not more:
                break
            groups.append((SAID[more[2].lower()], int(more[1])) + names_at(text, more.end(), roll))
            end = groups[-1][3]
        cast, problem = {}, ""
        if not roll:
            problem = "no supervisors at the head of the minutes"
        elif len(groups) == 1 and not groups[0][2] and groups[0][1] == len(roll) == 5:
            cast = {member["name"]: council_tables.AYE for member in roll}  # all five, with nobody named
        else:
            for word, count, names, _ in groups:
                if count != len(names):
                    problem = problem or f"the words say {count} {word} and name {len(names)}"
                for name in names:
                    if name in cast:
                        problem = problem or f"named twice in the words: {name}"
                    cast[name] = word
            if not problem and len(cast) != len(roll):
                problem = f"the words name {len(cast)} of {len(roll)} supervisors"
        outcome = _OUTCOME.findall(text[max(at, found.start() - 90):found.start()])
        out.append({"cast": None if problem else cast, "problem": problem, "ayes": int(found[1]),
                    "result": "" if not outcome else "Fail" if outcome[-1].lower() == "failed" else "Pass",
                    "start": found.start(), "end": end})
        at = end


def moved_in(text, roll):
    """(who moved, who seconded) where a passage says so: "A motion was made by Supervisor Tam, seconded by Supervisor
    Miley", "Supervisor Tam moved, seconded by ...". ("", "") where it does not. The last such before the vote is the one."""
    said = list(_SECONDED.finditer(text))
    if not said:
        return "", ""
    found = said[-1]  # a passage may tell of a motion that got no vote before the one that did
    seconder, _ = who_at(text, found.end(), roll)
    before = text[max(0, found.start() - 90):found.start()]
    movers = [name for at in range(len(before)) for name, end in [who_at(before, at, roll)]
              if name and end > at and (at == 0 or not plain(before[at - 1]).isalpha())]
    return (movers[-1] if movers else ""), seconder or ""


_RECUSED = re.compile(r"\brecus(?:ed|ing)\s+(?:himself|herself|themselves)", re.I)


def recused_in(text, roll):
    """The supervisors a passage says stood aside: "President Miley and Supervisor Márquez recused themselves from
    discussing or voting on the item". The names are those that run up to the word, and nothing between."""
    out = set()
    for found in _RECUSED.finditer(text):
        before = text[max(0, found.start() - 90):found.start()]
        for at in (0, *(space.end() for space in re.finditer(r"\s+", before))):
            names, end = names_at(before, at, roll)
            if names and not before[end:].strip():
                out.update(names)
                break
    return out


def decide(code, text, roll, seats, why):
    """What one passage of the minutes says of a vote, from its margin, its words or both.

    Returns the motion as the tables keep it: whether it has a vote at all (`block`), the vote if it was read whole
    (`cast`, `read`), what stopped the reading if it was not (`problem`), and where it was read from (`source`).
    Where the margin and the words both speak they must say the same, supervisor for supervisor.
    """
    said = read_words(text, roll)
    words = said[0] if said else None
    motion = {"text": clean(text), "code": code, "block": bool(code or words), "cast": {}, "read": False, "problem": "",
              "source": "", "mover": "", "seconder": "", "mover_from": "", "result": words["result"] if words else "", "order": ""}
    if not motion["block"]:
        return motion
    mover, seconder = moved_in(text[:words["start"]] if words else text, roll)
    margin, trouble, first, second = read_margin(code, seats) if code else (None, "", "", "")
    if code and not seats:
        trouble = why or trouble
    aside = set(seats.values()) - set(margin) if margin is not None and trouble.endswith("not in the margin") else set()
    if aside and aside == recused_in(text, roll):
        # A supervisor who stood aside is left out of the margin, and the passage says who it was.
        margin, trouble = {**margin, **{name: "RECUSED" for name in aside}}, ""
    # Who moved is taken from the words where they say. Where they do not, it is taken to be the first number of the
    # margin's first row, and who seconded the second: the key does not say so, but where the words name the two as
    # well, those are nearly always the two (`order` keeps whether they were).
    motion.update(mover=mover or first, seconder=seconder if mover else second, mover_from=WORDS if mover else MARGIN if first else "",
                  order="" if not (first and mover and seconder) else "same" if (mover, seconder) == (first, second) else "differs")
    if len(said) > 1:
        motion["problem"] = "two votes in words in one passage"
    elif words and words["cast"] is not None:
        differ = margin is not None and any(words["cast"].get(name) != word for name, word in margin.items())
        if differ:
            motion["problem"] = "the margin and the words differ"
        else:
            motion.update(cast=words["cast"], read=True, source=BOTH if margin is not None and not trouble else WORDS)
    elif margin is not None and not trouble:
        if words and words["ayes"] != sum(word == council_tables.AYE for word in margin.values()):
            motion["problem"] = "the margin and the words differ"
        else:
            motion.update(cast=margin, read=True, source=ASIDE if aside else MARGIN)
    else:
        motion["problem"] = (words["problem"] if words and not code else trouble) or "not read"
    return motion


# ---------------------------------------------------------------------------
# Reading the minutes
# ---------------------------------------------------------------------------

_ITEM = re.compile(r"^(\d{1,3})(?:\.(\d{1,2}))?\s?\.(?:\s+|(?=\D))(\S.*)$")  # "12. Sheriff - ...", "31.1. ...", and "3 . ..." as some print it
_ATTACHMENT = re.compile(r"^Attachments?\b")
_CLOSING = re.compile(r"^(REVIEWED BY\b|No further business appearing)", re.I)
_OPENING = re.compile(r"^CALL(ED)? TO ORDER\b")
_FAR = 12  # an item's number is no more than this above the last item's
_IN_LINE = re.compile(r"^([1-5]{3,4} ?[1-5]{1,2})(?:\s+(\S.*))?$")  # until July 2014: "1235 4 Approved as recommended"


def capitals(line):
    """Whether a line is a heading set in capitals (PUBLIC ASSISTANCE, 10:45 A.M. - SET MATTERS)."""
    letters = len(re.findall(r"[A-Z]", line))
    return letters >= 4 and not re.search(r"[a-z]", line) and letters >= 0.5 * len(re.sub(r"\s", "", line))


def parse(text):
    """The minutes' text as (roll, seats, why, items). Each item has the passages that say what was done with it.

    The minutes are a run of numbered items under headings in capitals (PUBLIC ASSISTANCE). An item is its title, a
    line "Attachment 12", and then what the Board did, with the vote in the margin beside it. Each vote in the margin
    begins a passage; what is said before the first is a passage of its own. A matter with no number (the approval of
    the minutes, the regular calendar taken as one) is kept under its heading if it was voted on.

    An item begins at a line that opens with a number higher than the last item's and not far above it. A heading is a
    line in capitals that stands at the left edge, where the items' numbers stand; capitals set in from there are the
    rest of a title or what was done. The consent calendar is voted on as one, as item 1, and its items are printed
    further down with the same rows in their margins.
    """
    lines = lines_of(text, set_in=True)
    roll, seats, why = roll_of([line[:3] for line in lines])
    opening = next((index for index, line in enumerate(lines[:80]) if _OPENING.match(line[1])), 0)
    closing = next((index for index, line in enumerate(lines) if _KEY.search(line[1])), len(lines))
    items, current, section, part, last = [], None, "", "", (0, 0)

    def begin(number, title, heading=False):
        nonlocal current, part
        current = {"number": number, "title": title, "section": "" if heading else section, "heading": heading,
                   "passages": [], "notes": []}
        part = "action" if heading else "title"
        items.append(current)

    def passage(code, words):
        current["passages"].append({"code": code, "text": words})

    for left, middle, right, inset in lines[opening:closing]:
        if _CLOSING.match(middle):
            break
        in_line = _IN_LINE.match(middle) if not left and not inset else None
        if in_line and len(set(in_line[1].replace(" ", ""))) == len(in_line[1].replace(" ", "")) >= 4:
            # Until July 2014 the numbers are in the type of the text and on its line, with any letter under them in
            # the line below. That is one row as far as this reader can tell, and is kept as one, which is not read.
            left, middle = in_line[1].replace(" ", ""), in_line[2] or ""
        numbered = _ITEM.match(middle)
        if numbered:
            number = (int(numbered[1]), int(numbered[2] or 0))
            if last < number and number[0] <= last[0] + _FAR:
                begin(numbered[1] + (f".{numbered[2]}" if numbered[2] else ""), numbered[3])
                last = number
                if right:
                    current["notes"].append(right)
                if left:  # the vote stands beside the item's first line: the title is that line
                    passage(left, "")
                    part = "action"
                continue
        if capitals(middle) and not numbered and (not inset or (left and (current is None or current["heading"]))):
            # A heading: capitals at the left edge. Capitals set in are the rest of a title, or what was done, unless
            # they have a vote beside them and no item above to belong to (APPROVED MINUTES, at the head of a meeting).
            if middle.startswith("(") and current is not None and current["heading"] and not current["passages"] and not left:
                section = current["title"] = f"{current['title']} {middle}"  # a heading's second line, in brackets
                continue
            # Something voted on under a heading with no number of its own is kept as a line with the heading for title.
            section = middle
            begin("", middle, heading=True)
            if left:
                passage(left, "")
            continue
        if current is None:
            continue  # the head of the minutes
        if right:
            current["notes"].append(right)
        if part == "title":
            if _ATTACHMENT.match(middle):
                part = "action"
                middle = ""
            elif left:
                part = "action"
            else:
                current["title"] = clean(f"{current['title']} {middle}")
                continue
        if left:
            passage(left, middle)
        elif middle:
            if not current["passages"]:
                passage("", middle)
            else:
                current["passages"][-1]["text"] += " " + middle
    for item in items:
        item["motions"] = [motion for found in item.pop("passages") for motion in motions_of(found, roll, seats, why)]
    return roll, seats, why, [item for item in items if not item["heading"] or any(motion["block"] for motion in item["motions"])]


def motions_of(found, roll, seats, why):
    """A passage as its motions: one, or one for each vote it says in words. The margin's rows go with the first."""
    text, code, out, at = found["text"], found["code"], [], 0
    said = read_words(text, roll)
    for index, vote in enumerate(said):
        end = len(text) if index == len(said) - 1 else vote["end"]  # what is said after the last vote is about it
        out.append(decide(code if index == 0 else "", text[at:end], roll, seats, why))
        at = end
    return out or [decide(code, text, roll, seats, why)]


def read_meeting(meeting, out_dir, fresh=False):
    """One meeting's minutes: its items, the votes on each motion read whole, and what the reading found."""
    facts = {"minutes": "read", "pages": 0, "roll": "", "key": "", "vote_blocks": 0, "blocks_read": 0, "time": ""}
    try:
        text = text_of(meeting, out_dir, fresh)
    except NotPDF:
        return [], [], {**facts, "minutes": "not a PDF"}
    facts["pages"] = text.count("\f") + 1
    if len(re.sub(r"\s", "", text)) < LAYER_CHARS:
        return [], [], {**facts, "minutes": "no text layer"}
    if sum(not char.isprintable() and char not in "\n\t\f" for char in text) > 0.02 * len(text):
        return [], [], {**facts, "minutes": "text not legible"}  # a PDF whose letters are not given as letters
    roll, seats, why, items = parse(text)
    if not roll and not items:
        return [], [], {**facts, "minutes": "other document"}  # slides, or the Budget Workgroup's own minutes, posted where the Board's go
    district = {name: number for number, name in seats.items()}
    facts["roll"] = json.dumps(roll, ensure_ascii=False, separators=(",", ":"))
    facts["key"] = why or "read"
    started = re.search(r"^(\d{1,2}:\d\d)\s*([AaPp])\.?\s?[Mm]\.?$", "\n".join(middle for _, middle, _ in lines_of(text)[:8]), re.M)
    facts["time"] = f"{started[1]} {started[2].upper()}M" if started else ""
    meeting_id, date = meeting["meeting_id"], meeting["date"]
    agenda, votes, seen = [], [], Counter()
    for sequence, item in enumerate(items, 1):
        seen[item["number"]] += 1
        # A matter with no number is known by its place; a number met twice, by its number and which time it is.
        item_id = f"{meeting_id}-{item['number']}" if item["number"] else f"{meeting_id}-u{seen['']}"
        item_id += f"-{seen[item['number']]}" if item["number"] and seen[item["number"]] > 1 else ""
        for number, motion in enumerate(item["motions"], 1):
            for member, word in motion["cast"].items():
                votes.append({"item_id": item_id, "meeting_id": meeting_id, "date": date, "matter_id": item_id, "matter_file": "",
                              "member": member, "vote": council_tables.vote_word(word), "district": district.get(member),
                              "motion": number, "motion_text": motion["text"], "source": motion["source"]})
        blocks = [motion for motion in item["motions"] if motion["block"]]
        # What is said of the item is its last vote, or with no vote the last thing said.
        final = blocks[-1] if blocks else item["motions"][-1] if item["motions"] else None
        cast = list(final["cast"].values()) if final else []
        notes = list(dict.fromkeys(clean(note) for note in item["notes"]))
        numbered = next((re.sub(r"\s", "", note) for note in notes if re.match(r"[OR]\s?-", note)), "")
        agenda.append({
            "item_id": item_id, "meeting_id": meeting_id, "date": date, "body": BODY,
            "agenda_number": item["number"], "sequence": sequence, "matter_id": item_id, "matter_file": "", "title": clean(item["title"]),
            "action": final["text"] if final else "",
            "result": final["result"] if final else "",  # only where the minutes say in words that the motion passed or failed
            "mover": final["mover"] if final else "", "seconder": final["seconder"] if final else "",
            "ayes": cast.count(council_tables.AYE), "noes": cast.count(council_tables.NO),
            "not_voting": sum(word not in (council_tables.AYE, council_tables.NO) for word in cast),
            "section": item["section"],
            "motions": len(item["motions"]), "vote_blocks": len(blocks), "blocks_read": sum(motion["read"] for motion in blocks),
            "votes_read": all(motion["read"] for motion in blocks) if blocks else None,
            "problem": next((motion["problem"] for motion in blocks if not motion["read"]), ""),
            "mover_from": final["mover_from"] if final else "",
            "doc_type": "ordinance" if numbered.startswith("O") else "resolution" if numbered.startswith("R") else county.doc_type_of(item["title"]),
            "number": numbered, "notes": "; ".join(notes),
            "motion_log": json.dumps([{"motion": number, "action": motion["text"], "margin": motion["code"], "mover": motion["mover"],
                                       "seconder": motion["seconder"], "mover_from": motion["mover_from"], "block": motion["block"], "read": motion["read"],
                                       "source": motion["source"], "order": motion["order"], "problem": motion["problem"]}
                                      for number, motion in enumerate(item["motions"], 1)], ensure_ascii=False, separators=(",", ":")),
        })
        facts["vote_blocks"] += len(blocks)
        facts["blocks_read"] += sum(motion["read"] for motion in blocks)
    return agenda, votes, facts


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------

def items_table(agenda, meetings):
    """Every item in the minutes, with what was done with it. The system has no record of an item apart from its place
    in the minutes, so an item is here once for each meeting it came to."""
    minutes = dict(zip(meetings["meeting_id"], meetings["minutes_url"]))
    rows = [{
        "date": line.date, "matter_id": line.item_id, "matter_file": "", "doc_type": line.doc_type, "title": line.title,
        "body": line.body, "status": "", "year": int(line.date[:4]), "subject": line.section, "agenda_date": line.date,
        "passed_date": "", "last_action": line.action, "last_action_date": line.date if line.action else "",
        "result": line.result, "ayes": int(line.ayes), "noes": int(line.noes), "mover": line.mover, "seconder": line.seconder,
        "times_on_agenda": 1, "url": minutes.get(line.meeting_id, ""),
        "item_id": line.item_id, "meeting_id": line.meeting_id, "section": line.section,
        "votes_read": None if pd.isna(line.votes_read) else bool(line.votes_read), "mover_from": line.mover_from,
        "number": line.number, "notes": line.notes,
    } for line in agenda.itertuples(index=False)]
    out = pd.DataFrame(rows, columns=ITEM_COLUMNS)
    out["votes_read"] = out["votes_read"].astype("boolean")
    return out.sort_values(["date", "meeting_id", "matter_id"], ascending=[False, False, True]).reset_index(drop=True)


def members_table(votes, meetings):
    """Everyone in a vote that was read. The district and the office are those of the newest minutes that list the
    supervisor; the minutes give no terms of office."""
    seat, newest = {}, []
    for meeting in meetings[meetings["roll"] != ""].sort_values("date").itertuples(index=False):
        newest = json.loads(meeting.roll)
        for member in newest:
            known = seat.get(member["name"], {})
            seat[member["name"]] = {**member, "district": member["district"] or known.get("district")}
    serving = {member["name"]: member["role"] for member in newest}
    cast = votes.groupby("member")["date"].agg(["min", "max", "size"]) if len(votes) else pd.DataFrame()
    rows = [{"name": name, "district": seat.get(name, {}).get("district"), "role": serving.get(name, ""), "start": "", "end": "",
             "serving": name in serving, "first_vote": cast.loc[name, "min"], "last_vote": cast.loc[name, "max"],
             "votes": int(cast.loc[name, "size"])} for name in sorted(cast.index)]
    out = pd.DataFrame(rows, columns=council_tables.COLUMNS["members"])
    out["district"] = out["district"].astype("Int64")
    out["serving"] = out["serving"].astype(bool)
    out["votes"] = out["votes"].astype(int)
    return out.sort_values(["first_vote", "name"]).reset_index(drop=True)


def one_spelling(agenda, votes, meetings):
    """A supervisor's name spelled one way throughout: the way the keys spell it, and of those the commonest.

    Minutes with no key have the name only in capitals at their head, some without its accent (ELISA MARQUEZ), so the
    same supervisor would otherwise be two members.
    """
    in_keys, in_all = Counter(), Counter()
    for roll, key in zip(meetings["roll"], meetings["key"]):
        for member in json.loads(roll) if roll else []:
            in_all[member["name"]] += 1
            in_keys[member["name"]] += key == "read"
    best = {}
    for name in sorted(in_all, key=lambda name: (-in_keys[name], -in_all[name], name)):
        best.setdefault(plain(name), name)
    same = lambda name: best.get(plain(name), name) if name else name
    votes["member"] = votes["member"].map(same)
    for column in ("mover", "seconder"):
        agenda[column] = agenda[column].map(same)
    meetings["roll"] = [json.dumps([{**member, "name": same(member["name"])} for member in json.loads(roll)], ensure_ascii=False,
                                   separators=(",", ":")) if roll else "" for roll in meetings["roll"]]
    return agenda, votes, meetings


def joined(held, new):
    """Two tables of the same columns as one. An empty one adds nothing, and is left out so it cannot change a column's kind."""
    some = [table for table in (held, new) if len(table)]
    return pd.concat(some, ignore_index=True) if some else held


def typed(agenda, votes):
    for table, columns in ((agenda, ("sequence", "ayes", "noes", "not_voting", "motions", "vote_blocks", "blocks_read")), (votes, ("motion",))):
        for column in columns:
            table[column] = table[column].astype(int)
    agenda["votes_read"] = agenda["votes_read"].astype("boolean")
    votes["district"] = votes["district"].astype("Int64")
    return agenda, votes


READING = ("minutes", "pages", "roll", "key", "vote_blocks", "blocks_read", "time")  # what a reading adds to a meeting's row
_EMPTY = {"minutes": "", "pages": 0, "roll": "", "key": "", "vote_blocks": 0, "blocks_read": 0, "time": ""}


def build(base, everything, out_dir, since=FIRST_YEAR, limit=0, every=40):
    rows = listed()
    log.info(f"Alameda County: {len(rows)} meetings of the Board listed")
    if len(rows) < 100:
        raise RuntimeError("the listing of meetings came back nearly empty")
    meetings = meetings_table(rows)

    agenda, votes, before_meetings = (council_tables.held(HF_REPO, out_dir, name, base) for name in ("agenda_items", "votes", "meetings"))
    before = 0 if votes is None else len(votes)
    if agenda is None or votes is None or before_meetings is None:
        agenda, votes = pd.DataFrame(columns=AGENDA_COLUMNS), pd.DataFrame(columns=VOTE_COLUMNS)
        before_meetings = pd.DataFrame(columns=MEETING_COLUMNS)
    found = {row["meeting_id"]: {name: row[name] for name in READING}
             for row in before_meetings[before_meetings["minutes"] != ""].to_dict("records")}
    recent = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    wanted = [row for row in meetings.to_dict("records") if row["minutes_url"] and row["date"] >= f"{since}-01-01"
              and (everything or row["meeting_id"] not in found or row["date"] >= recent)]
    wanted.sort(key=lambda row: (row["date"], int(row["meeting_id"])), reverse=True)  # the newest first: a room shows those
    waiting = len(wanted)
    wanted = wanted[:limit] if limit else wanted
    log.info(f"Reading the minutes of {len(wanted)} meetings of {waiting} not yet read or to be read again")

    def fill():
        for name in READING:
            meetings[name] = [found.get(meeting_id, {}).get(name, _EMPTY[name]) for meeting_id in meetings["meeting_id"]]
        meetings["items"] = meetings["meeting_id"].map(agenda.groupby("meeting_id").size() if len(agenda) else {}).fillna(0).astype(int)

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
        log.info(f"Alameda County: {min(start + every, len(wanted))} of {len(wanted)} sets of minutes asked for, {len(votes)} votes held")
        if _refused.is_set():
            log.error("The host refused a request: no more is asked of it in this run")
            break

    fill()
    agenda, votes, meetings = one_spelling(agenda, votes, meetings)
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
    read = meetings[meetings["minutes"] == "read"]
    blocks, whole = int(agenda["vote_blocks"].sum()), int(agenda["blocks_read"].sum())
    logged = lambda words: f"{int(agenda['motion_log'].str.count(re.escape(words)).sum()) if len(agenda) else 0:,}"  # in the motions' log
    status = lambda *names: f"{int(meetings['minutes'].isin(names).sum()):,}"
    facts = {
        "n_agree": logged(f'"source":"{BOTH}"'), "n_differ": logged("the margin and the words differ"),
        "n_lone": logged("one row in the margin and no second"),
        "n_order_same": logged('"order":"same"'), "n_order_differs": logged('"order":"differs"'),
        "n_illegible": status("text not legible"), "n_other": status("other document", "not a PDF"),
        "repo": HF_REPO, "first_meeting": read["date"].min() if len(read) else "", "last_meeting": read["date"].max() if len(read) else "",
        "first_vote": votes["date"].min() if len(votes) else "", "last_vote": votes["date"].max() if len(votes) else "",
        "n_read": f"{len(read):,}", "n_scans": f"{int((meetings['minutes'] == 'no text layer').sum()):,}",
        "n_no_key": f"{int(((meetings['minutes'] == 'read') & (meetings['key'] != 'read')).sum()):,}",
        "n_blocks": f"{blocks:,}", "n_blocks_read": f"{whole:,}", "n_unread": f"{blocks - whole:,}",
        "share_read": f"{100 * whole / blocks:.1f}" if blocks else "0", "recent_days": RECENT_DAYS,
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
        log.error(f"Alameda County tables not uploaded: {e}")
        return False
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the Alameda County Board's meetings, agendas and votes")
    parser.add_argument("--base", action="store_true", help="start from the tables written here, not the published ones")
    parser.add_argument("--all", action="store_true", help="read every set of minutes again")
    parser.add_argument("--since", type=int, default=FIRST_YEAR, help="read no meeting before this year")
    parser.add_argument("--max", type=int, default=0, help="sets of minutes to read in one run (0 for all)")
    parser.add_argument("--out", default="", help="directory to write the tables into (minutes_pdf/alameda-county if not given)")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the tables only")

    out_dir = Path(args.out) if args.out else OUT_DIR
    try:
        tables, read = build(args.base, args.all, out_dir, args.since, args.max)
    except Exception as e:
        log.error(f"Alameda County tables not built: {type(e).__name__}: {e}")
        return 1
    pushed = False if args.no_upload else upload(tables, out_dir, args.write_card)
    meetings, agenda, votes, members = tables["meetings"], tables["agenda_items"], tables["votes"], tables["members"]
    blocks, whole = int(agenda["vote_blocks"].sum()), int(agenda["blocks_read"].sum())
    log.info(f"RESULT: alameda-county items={len(tables['items'])} meetings={len(meetings)} "
             f"meetings_with_minutes={int((meetings['minutes_url'] != '').sum())} "
             f"minutes_read={int((meetings['minutes'] == 'read').sum())} "
             f"no_text_layer={int((meetings['minutes'] == 'no text layer').sum())} "
             f"not_pdf={int((meetings['minutes'] == 'not a PDF').sum())} "
             f"other_documents={int((meetings['minutes'] == 'other document').sum())} "
             f"not_legible={int((meetings['minutes'] == 'text not legible').sum())} agenda_items={len(agenda)} "
             f"votes={len(votes)} vote_blocks={blocks} blocks_read={whole} blocks_unread={blocks - whole} "
             f"members={len(members)} serving={int(members['serving'].sum())} meetings_read={read} "
             f"first_vote={votes['date'].min() if len(votes) else ''} last_vote={votes['date'].max() if len(votes) else ''} "
             f"refused={_refused.is_set()} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
