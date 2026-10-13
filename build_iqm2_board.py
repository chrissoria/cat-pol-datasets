#!/usr/bin/env python3
"""
Build, for a county board of supervisors that keeps its record in IQM2
(MinuteTraq), what a room in Capitol World is made from: its meetings, what was
on each agenda, what the board did with it, and how each member voted.

One source: the county's meeting portal (IQM2, also sold as MinuteTraq, now
Granicus's), at <county>.iqm2.com/Citizens. It has no API; the pages a visitor
sees are read. What differs from one county to the next is set out in BOARDS.

Each has a dataset of its own (chrissoria/<county>-county-board), with the five
tables every council's and board's dataset has (council_tables.py), in data/:
  items.parquet          every item that has a page of its own, once
  meetings.parquet       one row per meeting of the board and the county's other bodies
  agenda_items.parquet   one row per line of a meeting's agenda, headings too, with what was done
  votes.parquet          one row per member and motion voted on
  members.parquet        one row per member seen voting at the board
They are kept here in iqm2/<county>/.

A meeting is one page, and each item on it one more: sixty or eighty requests
for a meeting of the board. So what is read is written every --every meetings,
the newest meetings first, and a meeting once read is not asked for again.

Two ways to run it:

    python build_iqm2_board.py --county sutter-county
        The routine run. Starts from the published tables, lists this year's
        meetings again, and reads again the agendas and votes of meetings in
        the last 60 days and those to come, and any not read before.

    python build_iqm2_board.py --county sutter-county --base
        The same, starting from the tables written here and listing every
        year's meetings again. Hours for a county with ten years of items; it
        can be stopped and started again.

    --all          read every meeting again
    --since DAY    only meetings on or after this day (YYYY-MM-DD)
    --limit N      read no more than the N newest of the meetings wanted
    --minutes M    stop asking for more meetings after M minutes
    --every N      meetings to read between one writing of the tables and the next
    --all-bodies   read the agendas of the county's other bodies too, not only the board's
    --out DIR      where to write the tables
    --no-upload    write the tables but do not publish them
    --write-card   publish the dataset card as well as the tables
"""

import argparse
import json
import logging
import re
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

import build_federal_bills as bills
import build_sd_county as county
import council_tables
from build_sd_county import clean, day_of, today

log = logging.getLogger(__name__)

OUT_DIR = bills.SCRIPT_DIR / "iqm2"
CARD_FILE = bills.SCRIPT_DIR / "README_iqm2_board.md"  # one card for every county, with the county's own facts written in
TABLES = council_tables.TABLES
RECENT_DAYS = 60  # meetings this recent are read again: minutes and votes are entered after the meeting
SEEN_DAYS = 2  # someone is a member if they vote at the board's meetings on this many days: once may be a clerk's slip
SERVING_DAYS = 120  # the system keeps no terms of office; a member who voted this recently is taken to be serving
PAUSE = 0.5  # seconds a reader waits after each page: four read at once, and these are small counties' portals

# `host` is the county's portal; `board` is what its calendar calls the board of supervisors; `first` is the first year
# its calendar is asked for. `ends` marks a county that has moved its record elsewhere, and where.
BOARDS = {
    "santa-clara-county": {"host": "sccgov.iqm2.com", "name": "Santa Clara", "board": ["Board of Supervisors"], "first": 1995},
    "san-joaquin-county": {"host": "sanjoaquincountyca.iqm2.com", "name": "San Joaquin", "board": ["Board of Supervisors"],
                           "first": 2003},
    "sutter-county": {"host": "suttercountyca.iqm2.com", "name": "Sutter", "board": ["Board of Supervisors"], "first": 2000},
    "santa-cruz-county": {"host": "santacruzcountyca.iqm2.com", "name": "Santa Cruz", "board": ["Board of Supervisors"],
                          "first": 1998,
                          "ends": "The County moved to another system (PrimeGov) in January 2025, and its record here ends there."},
}
# The pages give a member's district in their title ("Vice Chair, District 4") except in Santa Clara, where it is typed
# in here by the name the pages give, from the County's own pages and what is commonly recorded of the Board.
DISTRICTS = {
    "santa-clara-county": {
        "Mike Wasserman": 1, "Sylvia Arenas": 1,
        "Cindy Chavez": 2, "Betty Duong": 2,
        "Dave Cortese": 3, "Otto Lee": 3,
        "Ken Yeager": 4, "Susan Ellenberg": 4,
        "S. Joseph Simitian": 5, "Joe Simitian": 5, "Margaret Abe-Koga": 5,
    },
}
# The kinds of line that are not an item with a page of its own: the portal numbers them, and these three were never
# seen with a vote (a procedural step, a heading or comment, the roll call), so their pages are not asked for.
NO_VOTE_KINDS = {"50", "70", "80"}

ITEM_COLUMNS = council_tables.COLUMNS["items"] + ["action_on", "department", "file_type", "attachments"]
MEETING_COLUMNS = council_tables.COLUMNS["meetings"] + ["name", "status", "packet_url", "summary_url", "read_on"]
AGENDA_COLUMNS = council_tables.COLUMNS["agenda_items"] + [
    "heading", "level", "kind", "section", "section_id", "motions", "tally", "mover_title", "seconder_title", "comments",
    "description", "doc_type", "status", "subject", "department", "file_type", "attachments"]
VOTE_COLUMNS = council_tables.COLUMNS["votes"] + ["motion", "motion_text"]

REFUSED = {}  # host -> why it turned us away. Nothing more is asked of a host once it is here.
_local = threading.local()


class Refused(Exception):
    """The host answered with a bot check, a login or a refusal. It is not asked again in this run."""


class NoPage(Exception):
    """The portal has no such page, cannot make it, or says it is not published for viewing yet."""


def repo_of(key):
    return f"chrissoria/{key}-board"


def site_of(key):
    return f"https://{BOARDS[key]['host']}/Citizens"


def meeting_page(key, meeting_id):
    return f"{site_of(key)}/Detail_Meeting.aspx?ID={meeting_id}"


def item_page(key, matter_id):
    return f"{site_of(key)}/Detail_LegiFile.aspx?ID={matter_id}"


def fetch(url, tries=4, **params):
    """One page of the portal, as text. Raises Refused if the host turns us away, NoPage if it has no such page.

    The portal sends a visitor to its login page in two cases. One is a page not yet open to the public, the minutes of
    a meeting before they are published, and it says so: that is no page. Any other is a refusal.
    """
    host = urlparse(url).netloc
    for attempt in range(tries):
        if host in REFUSED:
            raise Refused(REFUSED[host])
        try:
            if not hasattr(_local, "session"):
                _local.session = requests.Session()
                _local.session.headers.update(county.HEADERS)
            answer = _local.session.get(url, params=params or None, timeout=150)
            text = answer.text
            ours = "ContentPlaceholder1" in text or "MainLayout" in text  # any page of the portal has these
            login = "Login.aspx" in urlparse(answer.url).path
            said = clean(" ".join(parse_qs(urlparse(answer.url).query).get("Message", []))) if login else ""
            if login and "not been published" in said:
                raise NoPage(said)
            if answer.status_code in (401, 403, 429) or login or (
                    not ours and re.search(r"captcha|challenge-platform|cf-chl|attention required|access denied", text, re.I)):
                REFUSED[host] = (f"HTTP {answer.status_code} at {answer.url.split('?')[0]}{f' ({said})' if said else ''}, "
                                 f"asked for {url.rsplit('/', 1)[1]} {params or ''}")
                raise Refused(REFUSED[host])
            answer.raise_for_status()
            if "Oops.. an error occured" in text:
                raise NoPage(url)
            time.sleep(PAUSE)
            return text
        except (Refused, NoPage):
            raise
        except requests.RequestException as e:
            # A host that is not allowed will not be allowed on a second asking.
            if attempt == tries - 1 or isinstance(e, requests.exceptions.ProxyError):
                raise
            time.sleep(3 * (attempt + 1))


# ---------------------------------------------------------------------------
# The calendar
# ---------------------------------------------------------------------------

def calendar_rows(page):
    """The meetings on one page of the calendar. Each has its day and time, its body, its kind and its papers."""
    rows = []
    for row in BeautifulSoup(page, "html.parser").find_all("div", class_="MeetingRow"):
        link = row.find("a", href=re.compile(r"Detail_Meeting\.aspx\?ID=\d+", re.I))
        if link is None:
            continue
        # The link's note has the body, the kind of meeting, its status and then the place, a line each.
        note = [clean(line) for line in str(link.get("title") or "").replace("\t", " ").split("\r")]
        said = {name: clean(line[len(name) + 1:]) for line in note for name in ("Board", "Type", "Status") if line.startswith(name + ":")}
        place = [line for line in note[1:] if line and not re.match(r"(Board|Type|Status):", line)]
        words = clean(link.get_text(" "))  # "Jan 5, 2026 3:30 PM", or the day alone where no time was entered
        try:
            when = datetime.strptime(words, "%b %d, %Y %I:%M %p" if ":" in words else "%b %d, %Y")
        except ValueError:
            continue
        papers = {clean(paper.get_text(" ")).lower(): paper.get("href") for paper in row.select("div.MeetingLinks a") if paper.get("href")
                  and re.match(r"File(Open|View)\.aspx", paper.get("href"), re.I)}
        rows.append({
            "meeting_id": re.search(r"ID=(\d+)", link["href"])[1],
            "date": day_of(when.isoformat()),
            "time": when.strftime("%I:%M %p").lstrip("0") if ":" in words else "",
            "body": said.get("Board", ""),
            "location": ", ".join(dict.fromkeys(place)),
            "name": said.get("Type", ""),
            "status": said.get("Status", ""),
            "papers": papers,
        })
    return rows


def listed_year(key, year):
    """Every meeting the calendar lists in a year, of any body. A year too long for the portal to answer is asked for by month."""
    ask = lambda start, end, tries: calendar_rows(fetch(f"{site_of(key)}/Calendar.aspx", tries=tries, From=start, To=end))
    try:
        return ask(f"1/1/{year}", f"12/31/{year}", 2)
    except (NoPage, requests.RequestException):
        months = [pd.Timestamp(year, month, 1) + pd.offsets.MonthEnd(0) for month in range(1, 13)]
        return [row for end in months for row in ask(f"{end.month}/1/{year}", f"{end.month}/{end.day}/{year}", 4)]


def meetings_table(key, rows):
    site = site_of(key)
    paper = lambda row, *names: next((f"{site}/{row['papers'][name]}" for name in names if name in row["papers"]), "")
    out = pd.DataFrame([{
        "meeting_id": row["meeting_id"], "date": row["date"], "time": row["time"], "body": row["body"],
        "location": row["location"], "url": meeting_page(key, row["meeting_id"]),
        "agenda_url": paper(row, "agenda"), "minutes_url": paper(row, "minutes"), "items": 0,
        "name": row["name"], "status": row["status"], "packet_url": paper(row, "agenda packet"),
        # What a county calls its short minutes: Summary, Summary of Proceedings, Summary Minutes.
        "summary_url": paper(row, *[name for name in row["papers"] if name.startswith("summary")]),
        "read_on": "",
    } for row in rows], columns=MEETING_COLUMNS)
    return out.drop_duplicates("meeting_id").sort_values(["date", "meeting_id"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# A meeting's pages
# ---------------------------------------------------------------------------

_SUFFIX = re.compile(r"^(jr|sr|ii|iii|iv)\.?$", re.I)
_DETAIL = re.compile(r"Detail_(LegiFile|Motion|Communication)\.aspx", re.I)
_PAPER = re.compile(r"File(Open|View)\.aspx", re.I)


def names_of(text):
    """The members named in a list, "A, B, C". A "Jr." after a comma belongs to the name before it."""
    names = []
    for part in (clean(part) for part in str(text or "").split(",")):
        if part and names and _SUFFIX.match(part):
            names[-1] += ", " + part
        elif part:
            names.append(part)
    return names


def person_of(text, voters):
    """A mover as the page gives them, "Karm Bains, Vice Chair, District 4", as a name and a title."""
    for name in sorted(voters, key=len, reverse=True):
        if text == name or text.startswith(name + ","):
            return name, clean(text[len(name):].lstrip(","))
    name, _, title = text.partition(",")
    return clean(name), clean(title)


def decided(words):
    """A result as the clerk gives it, "ADOPTED [4 TO 1]", as the word and the count."""
    found = re.match(r"(.*?)\s*\[([^\]]*)\]\s*$", clean(words))
    return (clean(found[1]), clean(found[2])) if found else (clean(words), "")


def result_of(action, tally, ayes, noes):
    """Whether a motion carried. The clerk's word says what was done, not always whether: see the card."""
    if re.match(r"(failed|defeated)", action, re.I):
        return "Fail"
    counted = re.match(r"(\d+) TO (\d+)$", tally, re.I)
    if tally.upper() == "UNANIMOUS" or (counted and int(counted[1]) > int(counted[2])):
        return "Pass"
    return ""  # no count from the clerk: the names can be counted, but what number carries a motion depends on the motion


def lines_of(page):
    """A meeting's page as the lines of its agenda, in order. A line that is an item or a motion has a page of its own."""
    table = BeautifulSoup(page, "html.parser").find("table", id="MeetingDetail")
    lines = []
    for row in table.find_all("tr") if table else []:
        cells = row.find_all("td", recursive=False)
        note, title = row.find("td", class_="Comments"), row.find("td", class_="Title")
        if note is not None and lines:
            lines[-1]["description"] = clean(lines[-1]["description"] + " " + note.get_text(" "))
        if title is None:
            continue
        link = title.find("a", href=_DETAIL)
        if link is None and title.find("a", href=_PAPER):
            continue  # a paper filed with the line above
        outcome = title.find("span", class_="ItemVoteResult")
        for extra in title.find_all(["span", "a"], class_=["ItemVoteResult", "DiscussionLink"]):
            extra.extract()
        words = clean((link if link is not None else title).get_text(" "))
        if not words:
            continue
        number = row.find("td", class_="Num")
        number = clean(number.get_text(" ")) if number is not None else ""
        if not number and re.match(r"\d{1,3}[.)]\s", words):  # an older agenda has the number in the words
            number, words = words.split(None, 1)
        href = link["href"] if link is not None else ""
        kind = _DETAIL.search(href)[1].lower() if href else "text"
        page_id, page_kind = re.search(r"[?&]ID=(\d+)", href), re.search(r"[?&]Type=(\d+)", href)
        lines.append({
            "kind": "item" if kind == "legifile" else kind, "page_id": page_id[1] if page_id else "",
            "page_kind": page_kind[1] if page_kind else "", "agenda_number": number.rstrip(".)"), "title": words,
            "heading": title.find("strong") is not None,
            "level": next((place for place, cell in enumerate(cells) if "Num" in (cell.get("class") or [])), 0),
            "outcome": clean(outcome.get_text(" ")) if outcome is not None else "", "description": "",
        })
    # Santa Clara's older agendas link an item as "###" and give its words on the line below.
    out = []
    for line in lines:
        last = out[-1] if out else None
        if last and last["kind"] == "item" and not last["title"].strip("# ") and line["kind"] == "text" and not line["heading"]:
            last["title"] = line["title"]
        else:
            out.append(line)
    return out


def motion_of(table):
    """One vote on an item's page: what was decided, who moved and seconded, and how each member voted."""
    motion = {"words": "", "mover": "", "seconder": "", "votes": []}
    seen = set()
    for row in table.find_all("tr"):
        cells = [clean(cell.get_text(" ")) for cell in row.find_all("td")]
        if len(cells) < 2:
            continue
        role = cells[0].rstrip(": ").upper()
        if role == "RESULT":
            motion["words"] = cells[1]
        elif role in ("MOVER", "SECONDER"):
            motion[role.lower()] = cells[1]
        else:
            for name in names_of(cells[1]):
                if (name, role) in seen:
                    continue  # the same vote entered twice
                seen.add((name, role))
                motion["votes"].append((name, council_tables.vote_word(role)))
    voters = [name for name, word in motion["votes"]]
    for role in ("mover", "seconder"):
        motion[role], motion[role + "_title"] = person_of(motion[role], voters) if motion[role] else ("", "")
    return motion


def read_item(page, meeting_id):
    """An item's page: what the item is, and what was done with it at this meeting.

    The page has every meeting the item came before, each with its own votes. Only this meeting's are taken.
    """
    soup = BeautifulSoup(page, "html.parser")
    if soup.find(id="ContentPlaceholder1_pnlMain") is None:
        raise ValueError("not an item's page")
    nothing = soup.new_tag("span")
    said = lambda name: clean((soup.find(id=f"ContentPlaceholder1_{name}") or nothing).get_text(" "))
    facts = {}
    for label in (soup.find(id="tblLegiFileInfo") or nothing).find_all("th"):
        value = label.find_next_sibling("td")
        facts[clean(label.get_text(" ")).rstrip(" :").lower()] = clean(value.get_text(" ")) if value is not None else ""
    papers = [{"name": clean(paper.get_text(" ")), "url": paper["href"]} for paper in soup.select("li.snapShotListItem a[href]")]
    here, comments, motions = False, [], []
    for row in (soup.find(id="ContentPlaceholder1_divHistory") or nothing).find_all("tr", class_=["HeaderRow", "VoteResultRow"]):
        if "HeaderRow" in row["class"]:
            link = row.find("a", href=re.compile(r"Detail_Meeting\.aspx\?ID=\d+", re.I))
            here = link is not None and re.search(r"ID=(\d+)", link["href"])[1] == str(meeting_id)
        elif here:
            note = row.find("div", class_="Comments")
            comments.append(clean(note.get_text(" ")) if note is not None else "")
            for table in row.find_all("table", class_="VoteRecord"):
                motion = motion_of(table)
                if motion not in motions:  # the same motion entered twice
                    motions.append(motion)
    return {"title": said("lblLegiFileTitle"), "file_type": said("lblLegiFileType"), "number": said("lblResNum"),
            "status": said("lblStatus"), "department": facts.get("department", ""), "subject": facts.get("category", ""),
            "attachments": papers, "comments": clean(" ".join(comments)), "motions": motions}


def read_motion(page):
    """A motion's page: a consent calendar, the approval of minutes, or a motion that is no item. One vote, named by member."""
    soup = BeautifulSoup(page, "html.parser")
    motion = {"words": "", "mover": "", "seconder": "", "mover_title": "", "seconder_title": "", "votes": []}
    seen = set()
    for row in (soup.find(id="ContentPlaceholder1_lblVote") or soup.new_tag("span")).find_all("tr"):
        cells = [clean(cell.get_text(" ")) for cell in row.find_all("td")]
        if len(cells) != 3 or not cells[0] or not cells[2]:
            continue
        name, role, word = cells
        if role.lower() in ("mover", "seconder"):
            motion[role.lower()] = name
        if (name, word) in seen:
            continue  # the same vote entered twice
        seen.add((name, word))
        motion["votes"].append((name, council_tables.vote_word(word.split("/")[0])))  # "Yes/Aye", "No/Nay"
    comments = []
    for row in (soup.find(id="ContentPlaceholder1_lblHistory") or soup.new_tag("span")).find_all("tr"):
        day = row.find("strong")
        if day is not None and not motion["words"]:
            day.extract()
            motion["words"] = clean(row.get_text(" "))
        elif day is None:
            comments.append(clean(row.get_text(" ")))
    return {"comments": clean(" ".join(comments)), "motions": [motion] if motion["votes"] else []}


def read_meeting(key, meeting):
    """One meeting's agenda: its lines, and the votes on each motion the clerk entered names for.

    A vote is on the line it was taken on. An item's own page says how each member voted on it, a consent item's too;
    the consent calendar as a whole, the minutes and a motion that is no item have a motion's page instead.
    """
    meeting_id, date, body = str(meeting["meeting_id"]), meeting["date"], meeting["body"]
    site, agenda, votes, used, section = site_of(key), [], [], set(), None
    for sequence, line in enumerate(lines_of(fetch(meeting_page(key, meeting_id))), 1):
        kind, found = line["kind"], {}
        if kind == "item":
            try:
                found = read_item(fetch(f"{site}/Detail_LegiFile.aspx", MeetingID=meeting_id, ID=line["page_id"]), meeting_id)
            except NoPage as e:
                log.warning(f"{key} meeting {meeting_id}: item {line['page_id']} has no page ({e})")
        elif kind == "motion" and line["page_kind"] not in NO_VOTE_KINDS:
            try:
                found = read_motion(fetch(f"{site}/Detail_Motion.aspx", MeetingID=meeting_id, ID=line["page_id"], Type=line["page_kind"]))
            except NoPage as e:
                log.warning(f"{key} meeting {meeting_id}: motion {line['page_id']} has no page ({e})")
        mark = {"item": "", "motion": "m", "communication": "c"}.get(kind, "t")
        item_id = f"{meeting_id}-{mark}{line['page_id'] or sequence}"
        while item_id in used:  # the same item twice on one agenda
            item_id += "x"
        used.add(item_id)
        matter_id = line["page_id"] if kind == "item" else ""
        # A county numbers its files ("DOC-2023-35") or does not, and then the page gives the item's own id again.
        named = re.match(r"([A-Z][A-Za-z]*-\d{2,4}-\d+[A-Za-z]?) : (.*)", line["title"])
        file = found.get("number", "") if found.get("number", "") != matter_id else ""
        file, title = file or (named[1] if named else ""), named[2] if named else line["title"]
        if found.get("title", "").strip("# "):
            title = found["title"]
        motions, last = found.get("motions", []), {}
        for number, motion in enumerate(motions, 1):
            cast = defaultdict(int)
            for name, word in motion["votes"]:
                cast[word] += 1
                votes.append({"item_id": item_id, "meeting_id": meeting_id, "date": date, "matter_id": matter_id, "matter_file": file,
                              "member": name, "vote": word, "motion": number, "motion_text": motion["words"]})
            last = {**motion, "cast": cast}
        cast = last.get("cast", {})
        ayes, noes = cast.get(council_tables.AYE, 0), cast.get(council_tables.NO, 0)
        # With no vote on its page, what the meeting's own page says was done with the line.
        action, tally = decided(last["words"] if last else line["outcome"])
        file_type, subject = found.get("file_type", ""), found.get("subject", "")
        kinds = f"{file_type} {subject}".lower()
        if line["level"] == 0:
            section = None
        agenda.append({
            "item_id": item_id, "meeting_id": meeting_id, "date": date, "body": body,
            "agenda_number": line["agenda_number"], "sequence": sequence, "matter_id": matter_id, "matter_file": file,
            "title": title, "action": action, "result": result_of(action, tally, ayes, noes) if action else "",
            "mover": last.get("mover", ""), "seconder": last.get("seconder", ""), "ayes": ayes, "noes": noes,
            "not_voting": sum(count for word, count in cast.items() if word not in (council_tables.AYE, council_tables.NO)),
            "heading": line["heading"], "level": line["level"], "kind": kind,
            "section": section["title"] if section else "", "section_id": section["item_id"] if section else "",
            "motions": len(motions), "tally": tally,
            "mover_title": last.get("mover_title", ""), "seconder_title": last.get("seconder_title", ""),
            "comments": found.get("comments", ""), "description": line["description"],
            "doc_type": "" if kind != "item" else "ordinance" if "ordinance" in kinds else "resolution" if "resolution" in kinds
                        else county.doc_type_of(title),
            "status": found.get("status", ""), "subject": subject, "department": found.get("department", ""),
            "file_type": file_type,
            "attachments": json.dumps([{"name": paper["name"], "url": urljoin(f"{site}/", paper["url"])}
                                       for paper in found.get("attachments", [])], ensure_ascii=False, separators=(",", ":")),
        })
        if line["level"] == 0:
            section = agenda[-1]
    return agenda, votes


# ---------------------------------------------------------------------------
# The tables made from what was read
# ---------------------------------------------------------------------------

def fuller_names(names):
    """Where a member is named with a middle name and without, the shorter name and the fuller one it stands for.

    A motion's page says "Steven Ding" where an item's page says "Steven J. Ding". Only where one fuller name fits.
    """
    full = defaultdict(set)
    for name in names:
        parts = name.split()
        if len(parts) > 2:
            full[(parts[0].lower(), parts[-1].lower())].add(name)
    out = {}
    for name in names:
        parts = name.split()
        if len(parts) == 2 and len(full.get((parts[0].lower(), parts[1].lower()), ())) == 1:
            out[name] = next(iter(full[(parts[0].lower(), parts[1].lower())]))
    return out


def one_name(agenda, votes):
    """The agenda and the votes with each member under one name."""
    names = fuller_names(set(votes["member"]) | set(agenda["mover"]) | set(agenda["seconder"]))
    if names:
        votes["member"] = votes["member"].replace(names)
        agenda["mover"], agenda["seconder"] = agenda["mover"].replace(names), agenda["seconder"].replace(names)
    return agenda, votes


def items_table(key, agenda):
    """Every item with a page of its own, once, with the last thing done to it at a meeting read here.

    An item passed with the consent calendar may have no vote on its own page. The members' vote is then on the
    calendar's line, the section it sits under, and the count and the mover here are that line's.
    """
    of = agenda.set_index("item_id")
    lines = agenda[agenda["matter_id"] != ""].sort_values(["date", "meeting_id", "sequence"])
    acted = lines[lines["action"] != ""].groupby("matter_id").tail(1).set_index("matter_id")
    first, times = lines.groupby("matter_id")["date"].min(), lines.groupby("matter_id").size()
    rows = []
    for line in lines.groupby("matter_id").tail(1).itertuples(index=False):
        done = acted.loc[line.matter_id] if line.matter_id in acted.index else None
        whole = (done is not None and done["motions"] == 0 and "consent vote" in done["action"].lower()
                 and done["section_id"] in of.index and of.loc[done["section_id"], "motions"] > 0)
        voted = of.loc[done["section_id"]] if whole else done
        date = first[line.matter_id]
        rows.append({
            "date": date, "matter_id": line.matter_id, "matter_file": line.matter_file, "doc_type": line.doc_type,
            "title": line.title, "body": line.body, "status": line.status,
            "year": int(date[:4]) if date[:4].isdigit() else 0, "subject": line.subject, "agenda_date": line.date,
            "passed_date": "",  # the system has no day an item passed: a motion that carried may have been one to deny or put off
            "last_action": done["action"] if done is not None else "",
            "last_action_date": done["date"] if done is not None else "",
            "result": done["result"] if done is not None else "",
            "ayes": int(voted["ayes"]) if done is not None else 0, "noes": int(voted["noes"]) if done is not None else 0,
            "mover": voted["mover"] if done is not None else "", "seconder": voted["seconder"] if done is not None else "",
            "times_on_agenda": int(times[line.matter_id]), "url": item_page(key, line.matter_id),
            "action_on": "" if done is None else "section" if whole else "item",
            "department": line.department, "file_type": line.file_type, "attachments": line.attachments,
        })
    out = pd.DataFrame(rows, columns=ITEM_COLUMNS)
    return out.sort_values(["date", "matter_id"], ascending=[False, False]).reset_index(drop=True)


def district_of(title):
    """The district in a member's title: "District 2 - Chair", "Vice Chair,Third District Supervisor"."""
    found = re.search(r"\bDistrict\s+(\d+)\b|\b(\d+)(?:st|nd|rd|th)\s+District\b", title, re.I)
    if found:
        return int(found[1] or found[2])
    found = re.search(r"\b(First|Second|Third|Fourth|Fifth)\s+District\b", title, re.I)
    return ["first", "second", "third", "fourth", "fifth"].index(found[1].lower()) + 1 if found else None


def members_table(agenda, votes, meetings, board, districts=None):
    """Everyone seen voting at the board's own meetings on several days. The system keeps no terms of office.

    A member's role is the title they last moved or seconded a motion under, and their district is read from it.
    """
    districts = districts or {}
    sat = set(meetings.loc[meetings["body"].isin(board), "meeting_id"])
    days = votes[votes["meeting_id"].isin(sat)].groupby("member")["date"].nunique()
    cast = votes.groupby("member")["date"].agg(["min", "max", "size"])
    titles = defaultdict(list)
    for line in agenda[agenda["mover"] != ""].sort_values("date").itertuples(index=False):
        for name, title in ((line.mover, line.mover_title), (line.seconder, line.seconder_title)):
            if name and title and title not in cast.index:  # a page now and then has another member's name where the title goes
                titles[name].append(title)
    since = (datetime.now(timezone.utc) - timedelta(days=SERVING_DAYS)).strftime("%Y-%m-%d")
    rows = [{"name": name,
             "district": districts.get(name, next((district_of(title) for title in reversed(titles[name]) if district_of(title)), None)),
             "role": titles[name][-1] if titles[name] else "", "start": "", "end": "",
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


def build(key, base, everything, out_dir, since="", limit=0, minutes=0, all_bodies=False, every=20):
    board, started = BOARDS[key], time.time()
    held = council_tables.held(repo_of(key), out_dir, "meetings", base)
    recent = (pd.Timestamp(today()) - pd.Timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    # A whole run lists every year. The routine run lists this year's meetings again, and the last's while they are
    # recent; the years before stand as they were.
    first = board["first"] if held is None or base or everything else int(recent[:4])
    years = list(range(first, int(today()[:4]) + 2))
    found = county.together(lambda year: listed_year(key, year), years, f"{board['name']} calendar for")
    if any(rows is None for rows in found):
        raise RuntimeError(f"the calendar could not be listed for {[year for year, rows in zip(years, found) if rows is None]}")
    meetings = meetings_table(key, [row for rows in found for row in rows])
    log.info(f"{board['name']}: {len(meetings)} meetings listed for {years[0]} to {years[-1]}")
    if held is None and len(meetings) < 10:
        raise RuntimeError("the listing of meetings came back nearly empty")
    if held is not None:
        meetings["read_on"] = meetings["meeting_id"].map(dict(zip(held["meeting_id"], held["read_on"]))).fillna("")
        kept = held[(held["date"] < f"{years[0]}-01-01") & ~held["meeting_id"].isin(set(meetings["meeting_id"]))]
        meetings = joined(kept, meetings).sort_values(["date", "meeting_id"]).reset_index(drop=True)

    agenda, votes = (council_tables.held(repo_of(key), out_dir, name, base) for name in ("agenda_items", "votes"))
    before = 0 if votes is None else len(votes)
    if agenda is None or votes is None:
        agenda, votes = pd.DataFrame(columns=AGENDA_COLUMNS), pd.DataFrame(columns=VOTE_COLUMNS)
    names = {clean(name) for name in board["board"]}
    wanted = meetings[(all_bodies | meetings["body"].isin(names)) & (meetings["status"] != "Cancelled") & (meetings["date"] >= since)
                      & (everything | (meetings["read_on"] == "") | (meetings["date"] >= recent))]
    wanted = wanted.sort_values(["date", "meeting_id"], ascending=False)  # the newest first: a room shows those
    unread = len(wanted)
    wanted = (wanted.head(limit) if limit else wanted).to_dict("records")
    log.info(f"Reading the agendas of {len(wanted)} meetings of {unread} wanted")

    read = 0
    for start in range(0, max(len(wanted), 1), every):
        if minutes and time.time() - started > minutes * 60 or BOARDS[key]["host"] in REFUSED:
            break
        some = {meeting["meeting_id"]: meeting for meeting in wanted[start:start + every]}
        new_agenda, new_votes, done = [], [], set()
        for meeting_id, found in zip(some, county.together(lambda meeting_id: read_meeting(key, some[meeting_id]), some, "meeting")):
            if found is None:
                continue  # what is held for it stands, and the next run asks again
            done.add(meeting_id)
            new_agenda.extend(found[0])
            new_votes.extend(found[1])
        new_agenda = pd.DataFrame(new_agenda, columns=AGENDA_COLUMNS)
        new_votes = pd.DataFrame(new_votes, columns=VOTE_COLUMNS)
        agenda = joined(agenda[~agenda["meeting_id"].isin(done)], new_agenda)
        votes = joined(votes[~votes["meeting_id"].isin(done)], new_votes)
        agenda, votes = one_name(agenda, votes)
        agenda = agenda.sort_values(["date", "meeting_id", "sequence"]).reset_index(drop=True)
        # A page may list one member twice under two forms of the name; once they are one name, the vote is here once.
        votes = votes.drop_duplicates(["item_id", "motion", "member", "vote"])
        votes = votes.sort_values(["date", "meeting_id", "item_id", "motion", "member"]).reset_index(drop=True)
        for table, columns in ((agenda, ("sequence", "ayes", "noes", "not_voting", "motions", "level")), (votes, ("motion",))):
            for column in columns:
                table[column] = table[column].astype(int)
        agenda["heading"] = agenda["heading"].astype(bool)
        meetings.loc[meetings["meeting_id"].isin(done), "read_on"] = today()
        council_tables.write_tables({"meetings": meetings, "agenda_items": agenda, "votes": votes}, out_dir)
        read += len(done)
        log.info(f"{board['name']}: {min(start + every, len(wanted))} of {len(wanted)} meetings asked for, {len(votes)} votes held, "
                 f"{round((time.time() - started) / 60)} minutes")
    if BOARDS[key]["host"] in REFUSED:
        log.error(f"{board['host']} turned us away ({REFUSED[board['host']]}); nothing more was asked of it")

    meetings["items"] = meetings["meeting_id"].map(agenda[~agenda["heading"]].groupby("meeting_id").size()).fillna(0).astype(int)
    tables = council_tables.standard({
        "items": items_table(key, agenda), "meetings": meetings, "agenda_items": agenda, "votes": votes,
        "members": members_table(agenda, votes, meetings, names, DISTRICTS.get(key)),
    })
    council_tables.write_tables(tables, out_dir)
    if len(votes) < before * 0.98:
        raise RuntimeError(f"only {len(votes)} votes where there were {before}; not publishing")
    return tables, read, unread - read


def card(key, tables):
    """The dataset card: the one every county has, with this one's name, addresses and counts written in."""
    board, meetings, votes = BOARDS[key], tables["meetings"], tables["votes"]
    soon = (datetime.now(timezone.utc) + timedelta(days=366)).strftime("%Y-%m-%d")  # a stray meeting dated years on is not the end of the record
    read = meetings[(meetings["items"] > 0) & (meetings["date"] <= soon)]
    span = (f"Votes by member are recorded from {votes['date'].min()} to {votes['date'].max()}. Before the clerk began entering\n"
            "them in this system, who voted how is only in the minutes' document\n(`minutes_url`), which is not read here."
            if len(votes) else
            "No votes by member have been read yet.")
    district = ("The pages do not say which district a member sits for. `district` is\n  typed in, from the County's own pages "
                "and what is commonly recorded of the\n  Board, and is empty for a member not typed in."
                if key in DISTRICTS else
                "`district` is read from the title the pages give a member (\"Vice Chair,\n  District 4\"), and is empty where "
                "no title of theirs says.")
    facts = {
        "title": f"{board['name']} County Board of Supervisors", "place": board["name"], "repo": repo_of(key),
        "host": board["host"], "board_names": " or ".join(f'"{clean(name)}"' for name in board["board"]),
        "first_meeting": read["date"].min() if len(read) else "", "last_meeting": read["date"].max() if len(read) else "",
        "listed_from": meetings["date"].min() if len(meetings) else "",
        "vote_span": span, "ends": board.get("ends", ""), "district_note": district,
        "bodies": f"{meetings['body'].nunique():,}", "serving_days": SERVING_DAYS, "seen_days": SEEN_DAYS,
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
    parser = argparse.ArgumentParser(description="Build an IQM2 county's meetings, agendas and votes")
    parser.add_argument("--county", "--body", required=True, choices=sorted(BOARDS), help="the county whose board to read")
    parser.add_argument("--base", action="store_true", help="start from the tables written here, not the published ones")
    parser.add_argument("--all", action="store_true", help="read every meeting again")
    parser.add_argument("--since", default="", help="only meetings on or after this day")
    parser.add_argument("--limit", type=int, default=0, help="read no more than this many of the newest meetings wanted")
    parser.add_argument("--minutes", type=float, default=0, help="stop asking for more meetings after this many minutes")
    parser.add_argument("--every", type=int, default=20, help="meetings to read between one writing of the tables and the next")
    parser.add_argument("--all-bodies", action="store_true", help="read the agendas of the county's other bodies too")
    parser.add_argument("--out", default="", help="directory to write the tables into (iqm2/<county> if not given)")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the tables only")

    out_dir = Path(args.out) if args.out else OUT_DIR / args.county
    try:
        tables, read, unread = build(args.county, args.base, args.all, out_dir, args.since, args.limit, args.minutes,
                                     args.all_bodies, args.every)
    except Exception as e:
        log.error(f"{args.county} tables not built: {type(e).__name__}: {e}")
        return 1
    refused = BOARDS[args.county]["host"] in REFUSED
    pushed = False if args.no_upload or refused else upload(args.county, tables, out_dir, args.write_card)
    agenda, votes, members = tables["agenda_items"], tables["votes"], tables["members"]
    log.info(f"RESULT: iqm2-{args.county} items={len(tables['items'])} meetings={len(tables['meetings'])} "
             f"meetings_with_agenda={agenda['meeting_id'].nunique()} agenda_items={len(agenda)} votes={len(votes)} "
             f"motions_voted_on={len(votes.drop_duplicates(['item_id', 'motion']))} members={len(members)} "
             f"serving={int(members['serving'].sum())} voters_not_members={len(set(votes['member']) - set(members['name']))} "
             f"meetings_read={read} meetings_unread={unread} first_vote={votes['date'].min() if len(votes) else ''} "
             f"last_vote={votes['date'].max() if len(votes) else ''} refused={refused} pushed={pushed}")
    return 0 if (args.no_upload or pushed) and not refused else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
