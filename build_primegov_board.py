#!/usr/bin/env python3
"""
Build, for a county board of supervisors that keeps its record in PrimeGov,
what a room in Capitol World is made from: its meetings, what was on each
agenda, what the board did with it, and how each member voted.

One source: the county's meeting system (PrimeGov, also sold as Granicus
OneMeeting), at <county>.primegov.com. The list of meetings is read through the
public API its own portal reads (/api/v2/PublicPortal). What was on an agenda
and what was done with it are read from the meeting's page (/Portal/Meeting):
the minutes where the county publishes them as a page, the agenda otherwise.
Nothing is read from a PDF. What differs from one county to the next is set
out in BOARDS.

Each has a dataset of its own (chrissoria/<county>-county-board), with the five
tables every council's and board's dataset has (council_tables.py), in data/:
  items.parquet          every item put on an agenda
  meetings.parquet       one row per meeting of the board and the county's other bodies
  agenda_items.parquet   one row per line of a meeting's agenda, headings too, with what was done
  votes.parquet          one row per member and motion voted on
  members.parquet        one row per member seen voting at the board
They are kept here in primegov/<county>/.

Two ways to run it:

    python build_primegov_board.py --county tulare-county
        The routine run. Starts from the published tables, lists every meeting
        again, and reads again the pages of meetings in the last 60 days and
        those to come, any not read before, and any whose page has changed
        (minutes take the place of an agenda months after the meeting).

    python build_primegov_board.py --county tulare-county --base
        The same, starting from the tables written here. It can be stopped and
        started: the newest meetings are read first and what is read is kept.

    --all        read every meeting again, not only the recent, the unread and the changed
    --out DIR    where to write the tables
    --no-upload  write the tables but do not publish them
    --write-card publish the dataset card as well as the tables
"""

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup, Comment, NavigableString

import build_federal_bills as bills
import build_sd_county as county
import council_tables
from build_sd_county import clean, day_of, today

log = logging.getLogger(__name__)

OUT_DIR = bills.SCRIPT_DIR / "primegov"
CARD_FILE = bills.SCRIPT_DIR / "README_primegov_board.md"  # one card for every county, with the county's own facts written in
TABLES = council_tables.TABLES
RECENT_DAYS = 60  # meetings this recent are read again: minutes are published after the meeting
SEEN_DAYS = 2  # someone is a member if they vote at the board's meetings on this many days: once may be a clerk's slip
SERVING_DAYS = 120  # the system keeps no terms of office; a member who voted this recently is taken to be serving

# `host` is the county's name in the system's address; `board` is the system's numbers for the board of supervisors
# among the county's bodies. In the counties marked so, the minutes are published only as PDFs, which are not read
# here: the agendas are read and the votes table is empty.
BOARDS = {
    "tulare-county": {"host": "tularecounty", "name": "Tulare", "board": [25]},
    "ventura-county": {"host": "ventura", "name": "Ventura", "board": [1], "votes": False},
    "shasta-county": {"host": "shastacounty", "name": "Shasta", "board": [3], "votes": False},
}

ITEM_COLUMNS = council_tables.COLUMNS["items"] + ["item_id", "meeting_id", "section", "action_on", "number", "attachments"]
MEETING_COLUMNS = council_tables.COLUMNS["meetings"] + ["name", "committee_id", "packet_url", "video_url", "state", "document",
                                                        "document_id", "document_date", "document_read"]
AGENDA_COLUMNS = council_tables.COLUMNS["agenda_items"] + ["heading", "section", "section_id", "consent_id", "motions", "tally",
                                                           "description", "minutes_text", "doc_type", "status", "subject",
                                                           "number", "attachments"]
VOTE_COLUMNS = council_tables.COLUMNS["votes"] + ["motion", "motion_text"]


def repo_of(key):
    return f"chrissoria/{key}-board"


def site_of(key):
    return f"https://{BOARDS[key]['host']}.primegov.com"


# ---------------------------------------------------------------------------
# Asking
# ---------------------------------------------------------------------------

class Refused(RuntimeError):
    """The host answered with a login, a bot check or a plain no. Nothing more is asked of it in this run."""


_refused = set()
_CHALLENGE = re.compile(r"<title>[^<]*(just a moment|attention required|access denied|request rejected|captcha|log ?in|sign ?in)",
                        re.I)


def fetch(url, tries=5):
    """One page or one answer from the API, as text. A host that refuses is not asked again."""
    host = url.split("/")[2]
    for attempt in range(tries):
        if host in _refused:
            raise Refused(f"{host} refused an earlier request")
        try:
            answer = requests.get(url, headers=county.HEADERS, timeout=120)
            if answer.status_code in (401, 403, 407, 429) or _CHALLENGE.search(answer.text[:3000]):
                _refused.add(host)
                raise Refused(f"{host} answered {answer.status_code} to {url}")
            answer.raise_for_status()
            return answer.text
        except requests.RequestException as e:
            # A host that is not allowed will not be allowed on a second asking.
            if attempt == tries - 1 or isinstance(e, requests.exceptions.ProxyError):
                raise
            time.sleep(2 * (attempt + 1))


def asked(key, path):
    """One answer from the portal's API, as parsed JSON."""
    return json.loads(fetch(f"{site_of(key)}/api/{path}"))


def listed(key):
    """Every meeting the system lists, of any body: those to come, then each year's, the newest year first."""
    events = {event["id"]: event for event in asked(key, "v2/PublicPortal/ListUpcomingMeetings")}
    for year in sorted(asked(key, "v2/PublicPortal/GetArchivedMeetingYears"), reverse=True):
        events.update((event["id"], event) for event in asked(key, f"v2/PublicPortal/ListArchivedMeetings?year={year}"))
    return list(events.values())


def bodies(key):
    """The county's bodies by the system's number for each."""
    return {body["id"]: clean(body.get("name")) for body in asked(key, "committee/GetCommitteeesListByShowInPublicPortal?showInactive=true")}


# ---------------------------------------------------------------------------
# Meetings
# ---------------------------------------------------------------------------

def kind_of(name):
    """What a meeting's document is, from the name the clerk gave it. A cancellation notice is none of them."""
    name = str(name or "").lower()
    return "minutes" if "minute" in name else "packet" if "packet" in name else "agenda" if "agenda" in name else ""


def address_of(key, paper):
    """Where a document is: elsewhere if the system only links to it, else as a page (3) or a file (1, a PDF)."""
    if paper.get("link"):
        return clean(paper["link"])
    if paper.get("compileOutputType") == 3:
        return f"{site_of(key)}/Portal/Meeting?meetingTemplateId={paper['templateId']}"
    return f"{site_of(key)}/Public/CompiledDocument?meetingTemplateId={paper['templateId']}&compileOutputType={paper.get('compileOutputType')}"


def is_page(paper):
    return paper.get("compileOutputType") == 3 and not paper.get("link")


def paper_of(event, kind):
    """A meeting's document of one kind: the page if there is one, since that is what can be read, else the file."""
    found = [paper for paper in event.get("documentList") or [] if kind_of(paper.get("templateName")) == kind]
    return next((paper for paper in found if is_page(paper)), found[0] if found else None)


def page_of(event):
    """The page a meeting's lines are read from: its minutes, or failing that its agenda, or failing that its packet."""
    for kind in ("minutes", "agenda", "packet"):
        paper = paper_of(event, kind)
        if paper and is_page(paper):
            return paper
    return None


def meetings_table(key, events, names):
    rows = []
    for event in events:
        papers = {kind: paper_of(event, kind) for kind in ("agenda", "minutes", "packet")}
        urls = {kind: address_of(key, paper) if paper else "" for kind, paper in papers.items()}
        page = page_of(event)
        rows.append({
            "meeting_id": str(event["id"]),
            "date": day_of(event.get("dateTime")),
            "time": clean(event.get("time")).lstrip("0"),
            # A body the portal does not list by name is known only by what its meetings are called.
            "body": names.get(event.get("committeeId")) or clean(event.get("title")),
            "location": clean(event.get("location")),
            "url": address_of(key, page) if page else urls["agenda"] or urls["minutes"] or f"{site_of(key)}/public/portal",
            "agenda_url": urls["agenda"],
            "minutes_url": urls["minutes"],
            "items": 0,
            "name": clean(event.get("title")),
            "committee_id": str(event.get("committeeId") or ""),
            "packet_url": urls["packet"],
            "video_url": clean(event.get("videoUrl")),
            "state": event.get("meetingState"),
            "document": clean(page.get("templateName")) if page else "",
            "document_id": str(page["templateId"]) if page else "",
            "document_date": clean(page.get("publishDate")) if page else "",
            "document_read": "",
        })
    out = pd.DataFrame(rows, columns=MEETING_COLUMNS).sort_values(["date", "meeting_id"]).reset_index(drop=True)
    out["state"] = out["state"].astype("Int64")
    return out


def stamp_of(meeting):
    """What says a meeting's page is the one read before: which document it is and when it was last published."""
    return f"{meeting['document_id']} {meeting['document_date']}".strip()


# ---------------------------------------------------------------------------
# A meeting's page
# ---------------------------------------------------------------------------

_BLOCKS = {"address", "blockquote", "div", "dd", "dl", "dt", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "li", "ol", "p",
           "table", "td", "th", "tr", "ul"}
# What the page puts around an item that is not the item: the list of its papers, and buttons to share or download it.
_FURNITURE = {"item_contents", "attachment-cell", "attachmentCell", "attachment-icon-holder", "optionalButtonsCell",
              "optionalButtons", "shareButtons_display", "elipsisMenu"}
_UNSAID = {"script", "style", "s", "strike", "del"}  # the last three are words a clerk struck out in correcting the minutes
_INLINE_PICTURE = re.compile(r'src="data:[^"]*"')  # a seal or a signature written into the page, most of its weight


def is_furniture(tag):
    return bool(_FURNITURE.intersection(tag.get("class") or [])) or str(tag.get("id") or "").startswith("attachment-icon-")


def lines_in(node, skip=lambda tag: False):
    """The words under `node` as lines, with an empty line wherever the page leaves one.

    A new line starts where the page starts one: at a line break, and at the edge of a paragraph, a table's cell or
    any other block. An empty line is two line breaks running, or a block the clerk left empty to make a space
    (the page writes that with a no-break space in it; a block with nothing in it at all is only the page's frame).
    """
    parts = []

    def walk(tag):
        for child in tag.children:
            if isinstance(child, NavigableString):
                if not isinstance(child, Comment):
                    parts.append(re.sub(r"[\u200b\ufeff\x00]", "", re.sub(r"[ \t\r\n\f\v]+", " ", str(child))))
            elif child.name == "br":
                parts.append("\n")
            elif child.name not in _UNSAID and not is_furniture(child) and not skip(child):
                edge = "\x00" if child.name in _BLOCKS else ""
                parts.append(edge)
                walk(child)
                parts.append(edge)

    walk(node)
    lines = []
    for run in "".join(parts).split("\n"):
        nothing = True
        for piece in run.split("\x00"):
            if piece.strip():
                lines.append(clean(piece))
                nothing = False
            elif "\xa0" in piece:
                lines.append("")
        if nothing:
            lines.append("")
    return lines


def spoken(lines):
    """Lines with the empty ones at either end taken off, and no more than one empty line running."""
    out = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return out[:-1] if out and not out[-1] else out


_NUMBER = re.compile(r"^(\d{1,3}[a-z]?\.|\(?[A-Za-z0-9]{1,3}\)|[A-Z]\.)\s+(?=\S)")  # `12. `, `(A) `, `B. ` before a line's words
_ONLY_NUMBER = re.compile(r"^(ITEM [A-Z]{1,2}|\d{1,3}[a-z]?\.?|\(?[A-Za-z0-9]{1,3}\)|[A-Z]\.)$")  # a line that is a number and no more
_RUNS_ON = re.compile(r"(?:\b(?:a|an|and|by|for|in|of|on|or|the|to|with)|[,&])$", re.I)  # a first line broken off mid-phrase
_ENACTED = re.compile(r"\b(?:Resolution|Ordinance)\s+No\.?\s*:?\s*([A-Z]{0,5}\s?\d[\w-]*)", re.I)


def papers_of(key, tag):
    """The papers filed with a line, as the page lists them."""
    return json.dumps([{"name": clean(link.get_text(" ")), "url": requests.compat.urljoin(site_of(key) + "/", link["href"])}
                       for link in tag.select(".attachment-holder a[href]") if clean(link.get_text(" "))],
                      ensure_ascii=False, separators=(",", ":"))


def lines_of(key, page):
    """A page's headings and items in order, each as a dict of what the page says of it.

    The system writes a page in two ways. One is its own: a block for each heading with its items inside it. The other
    is made from the clerk's Word document: a table for each heading and each item, one after the other. In both an
    item carries the system's number for it. What the minutes add (the motion, the votes, who spoke) follows the
    item's words inside its block, or follows a heading's words where the vote was on the heading.
    """
    soup = BeautifulSoup(_INLINE_PICTURE.sub('src=""', page), "html.parser")
    marked = lambda tag: tag.has_attr("data-sectionid") or tag.has_attr("data-itemid")

    def numbered(lines, number=""):
        """A line's number, its title (its first line of words) and the rest of what the agenda says of it.

        An agenda brought over from an older system has the number in the words, or as a line of its own before them.
        """
        said = [line for line in lines if line]
        if not number and len(said) > 1 and _ONLY_NUMBER.match(said[0]):
            number, said = said[0], said[1:]
        elif not number and said and _NUMBER.match(said[0]):
            number, said = _NUMBER.match(said[0])[1], [_NUMBER.sub("", said[0])] + said[1:]
        while len(said) > 1 and _RUNS_ON.search(said[0]):  # `INVOCATION AND`, then `PLEDGE OF ALLEGIANCE` on the next line
            said = [f"{said[0]} {said[1]}"] + said[2:]
        return number.rstrip("."), said[0] if said else "", "\n".join(said[1:])

    out = []
    for tag in soup.find_all(marked):
        if tag.has_attr("data-itemid") and tag.find_parent(attrs={"data-itemid": tag["data-itemid"]}) is not None:
            continue  # the cell of an item's words inside the item's own table
        # In a page made from a Word document a line is a row of cells: its number, if it has one, then its words.
        cells = ([td for td in tag.find("tr").find_all("td", recursive=False) if not is_furniture(td)]
                 if "item-table-fromdocx" in (tag.get("class") or []) and tag.find("tr") else [])
        if tag.has_attr("data-itemid"):
            words = cells[-1] if cells else tag.find(id=f"AgendaItem_{tag['data-itemid']}") or tag
            cell = cells[0] if len(cells) > 1 else tag.find(class_="number-cell")
            number, title, description = numbered(lines_in(words, lambda child: child is cell),
                                                  clean(cell.get_text(" ")) if cell is not None else "")
            section = tag.find_parent(attrs={"data-sectionid": True})
            line = {"id": str(tag["data-itemid"]), "heading": False,
                    "minutes": lines_in(tag, lambda child: child is words or child is cell) if words is not tag else [],
                    "section": f"s{section['data-sectionid']}" if section is not None else None,
                    "attachments": papers_of(key, tag)}
        else:
            head = tag.find("tr", class_="section-row") or tag
            number, title, description = numbered(lines_in(head, marked))
            line = {"id": f"s{tag['data-sectionid']}", "heading": True,
                    "minutes": lines_in(tag, lambda child: child is head or marked(child)) if head is not tag else [],
                    "section": None, "attachments": "[]"}
        if title or description or any(line["minutes"]):  # a line that says nothing is a gap in the page, not a line
            out.append({**line, "number": number, "title": title, "description": description})
    under = None
    for line in out:  # in a page made from a Word document an item is not inside its heading but after it
        if line["heading"]:
            under = line["id"]
        elif line["section"] is None:
            line["section"] = under
    return out


# ---------------------------------------------------------------------------
# Motions and votes
# ---------------------------------------------------------------------------

_MOVED = re.compile(r"\b(?:Moved|Motion(?: made)?) by (.+?)(?:,? (?:and )?[Ss]econded by (.+?))? to (.*)$")
_OPEN = re.compile(r"\b(?:Moved|Motion(?: made)?) by\b(?!.*\bto \S)")  # a motion whose words run on into the next line
_CAST = re.compile(r"\b(AYES?|YEAS?|NOES|NAYS?|ABSENT|ABSTAIN(?:ED|S)?|RECUSED?|Final Result)\s*:")
_TALLY = re.compile(r"^\s*(\d+)\s*[-–—]\s*(\d+)\s*(Pass|Fail)?", re.I)
_WORDS = {"ABSTAINED": "ABSTAIN", "ABSTAINS": "ABSTAIN", "RECUSE": "RECUSED"}


def people(text):
    """The names in a list of them as the minutes write it (`A, B and C`). Words that are not a name are not taken."""
    names = []
    for name in re.split(r",|;|&|\band\b", text):
        name = clean(name).strip(". ")
        if name and name.lower() not in ("none", "n/a") and len(name.split()) <= 4 and not re.search(r"\d", name):
            names.append(name)
    return names


def motions_in(lines):
    """The motions in what the minutes say under a line, in order, each with who voted how.

    The system writes a motion as `Moved by A, seconded by B to Approved.`, then a line for each way of voting with
    the names (`AYES: A, B`), then `Final Result: 4 - 1 Passed`. A clerk who types one by hand keeps to the same
    words more or less. The same list of names may be written out several times over; a vote is kept once. A motion
    with a tally and no names has no votes.
    """
    motions, now = [], None

    def new(**given):
        motions.append({"mover": "", "seconder": "", "action": "", "tally": "", "result": "", "votes": [], **given})
        return motions[-1]

    whole = []
    for line in lines:
        if whole and line and _OPEN.search(whole[-1]) and not _CAST.search(line):
            whole[-1] = f"{whole[-1]} {line}"  # the page sets what was moved as a paragraph of its own
        elif line:
            whole.append(line)
    for line in whole:
        moved = _MOVED.search(line)
        if moved:
            now = new(mover=clean(moved[1]), seconder=clean(moved[2]), action=clean(moved[3]))
            continue
        marks = list(_CAST.finditer(line))
        for mark, after in zip(marks, marks[1:] + [None]):
            rest = line[mark.end():after.start() if after else len(line)]
            if mark[1] == "Final Result":
                tally = _TALLY.match(rest)
                if now is None or now["tally"]:
                    now = new()
                now["tally"] = f"{tally[1]}-{tally[2]}" if tally else clean(rest)
                now["result"] = {"pass": "Pass", "fail": "Fail"}.get((tally[3] or "").lower(), "") if tally else ""
                continue
            word = council_tables.vote_word(_WORDS.get(mark[1], mark[1]))
            if word in (council_tables.AYE, council_tables.NO) and (now is None or now["tally"]):
                now = new()  # a vote with no motion written before it
            if now is None:
                continue  # who was absent from the meeting, not from a vote
            for name in people(rest):
                if (name, word) not in now["votes"]:  # the same vote written twice
                    now["votes"].append((name, word))
    return motions


_RUN = re.compile(r"numbers?\s*#?\s*(\d+)(?:\s*(?:through|though|thru|to|-|–)\s*#?\s*(\d+))?", re.I)


def covered(title, action, first=None):
    """The agenda numbers a consent calendar's one motion took in: the run it names, less those it says were pulled.

    The heading names the run and so, most often, does the motion. Where the two differ one of them is a slip: the one
    that starts at `first`, the number of the first item after the heading, is taken, and if that does not settle it
    only the numbers both name.
    """
    if not re.search(r"consent", f"{title} {action}", re.I):
        return set()
    named = _RUN.search(action)
    runs = [set(range(int(run[1]), int(run[2] or run[1]) + 1)) for run in (named, _RUN.search(title))
            if run and 0 <= int(run[2] or run[1]) - int(run[1]) < 500]
    if not runs:
        return set()
    starting = [run for run in runs if min(run) == first]
    numbers = starting[0] if len(starting) == 1 else set.intersection(*runs)
    pulled = re.split(r"\bexcept", action[named.end():] if named else action, maxsplit=1, flags=re.I)
    for one, last in re.findall(r"(\d+)(?:\s*[-–]\s*(\d+))?", pulled[1] if len(pulled) > 1 else ""):
        numbers = numbers - set(range(int(one), int(last or one) + 1))
    return numbers


def read_meeting(key, meeting):
    """One meeting's page: its lines, and the votes on each motion the minutes name the voters of.

    A motion sits on the line it was made on. A consent calendar is voted on as one, so its motion is on its heading;
    each item the motion took in has that heading as its `consent_id`.
    """
    meeting_id, date, body = meeting["meeting_id"], meeting["date"], meeting["body"]
    lines = lines_of(key, fetch(f"{site_of(key)}/Portal/Meeting?meetingTemplateId={meeting['document_id']}"))
    titles = {line["id"]: line["title"] for line in lines if line["heading"]}
    agenda, votes = [], []
    for sequence, line in enumerate(lines, 1):
        item_id, matter_id = line["id"], "" if line["heading"] else line["id"]
        motions = motions_in(line["minutes"])
        for number, motion in enumerate(motions, 1):
            votes.extend({"item_id": item_id, "meeting_id": meeting_id, "date": date, "matter_id": matter_id, "matter_file": "",
                          "member": name, "vote": word, "motion": number, "motion_text": motion["action"]}
                         for name, word in motion["votes"])
        last = motions[-1] if motions else {"mover": "", "seconder": "", "action": "", "tally": "", "result": "", "votes": []}
        cast = [word for _, word in last["votes"]]
        enacted = _ENACTED.search(f"{line['title']}\n{line['description']}")
        agenda.append({
            "item_id": item_id, "meeting_id": meeting_id, "date": date, "body": body,
            "agenda_number": line["number"], "sequence": sequence, "matter_id": matter_id, "matter_file": "",
            "title": line["title"], "action": last["action"], "result": last["result"],
            "mover": last["mover"], "seconder": last["seconder"],
            "ayes": cast.count(council_tables.AYE), "noes": cast.count(council_tables.NO),
            "not_voting": sum(1 for word in cast if word not in (council_tables.AYE, council_tables.NO)),
            "heading": line["heading"],
            "section": titles.get(line["section"], ""), "section_id": line["section"] or "",
            "consent_id": "", "motions": len(motions), "tally": last["tally"],
            "description": line["description"], "minutes_text": "\n".join(spoken(line["minutes"])),
            "doc_type": "" if line["heading"] else county.doc_type_of(line["title"]),
            "status": "", "subject": "", "number": clean(enacted[1]) if enacted else "", "attachments": line["attachments"],
        })
    # Which items a consent calendar's motion took in: those after its heading whose numbers it names, as far as the
    # numbers run on, and which had no motion of their own.
    for place, heading in enumerate(agenda):
        after = next((int(line["agenda_number"]) for line in agenda[place + 1:]
                      if not line["heading"] and line["agenda_number"].isdigit()), None)
        numbers = covered(heading["title"], heading["action"], after) if heading["heading"] and heading["motions"] else set()
        for line in agenda[place + 1:] if numbers else []:
            if line["heading"]:
                if line["motions"]:
                    break  # another calendar's motion
                continue
            if not line["agenda_number"].isdigit():
                continue
            if int(line["agenda_number"]) not in numbers:
                if int(line["agenda_number"]) > max(numbers):
                    break
                continue
            if not line["motions"]:
                line["consent_id"] = heading["item_id"]
    return agenda, votes


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------

def items_table(key, agenda, meetings):
    """Every item put on an agenda, with what was done with it: on its own motion, or failing that on its consent calendar's.

    An item is here once for each agenda it is on: the system gives it a new number each time.
    """
    page = meetings.set_index("meeting_id")["url"]
    of = agenda.drop_duplicates(["meeting_id", "item_id"]).set_index(["meeting_id", "item_id"])
    rows = []
    for line in agenda[~agenda["heading"]].itertuples(index=False):
        own = line.motions > 0
        over = of.loc[(line.meeting_id, line.consent_id)] if not own and (line.meeting_id, line.consent_id) in of.index else None
        done = line._asdict() if own else over.to_dict() if over is not None else None
        rows.append({
            "date": line.date, "matter_id": line.item_id, "matter_file": line.matter_file,
            "doc_type": line.doc_type, "title": line.title, "body": line.body, "status": line.status,
            "year": int(line.date[:4]) if line.date[:4].isdigit() else 0,
            "subject": line.subject, "agenda_date": line.date,
            "passed_date": "",  # the system has no day an item passed: a motion that carried may have been one to deny or put off
            "last_action": done["action"] if done else "", "last_action_date": line.date if done else "",
            "result": done["result"] if done else "",
            "ayes": int(done["ayes"]) if done else 0, "noes": int(done["noes"]) if done else 0,
            "mover": done["mover"] if done else "", "seconder": done["seconder"] if done else "",
            "times_on_agenda": 1, "url": page.get(line.meeting_id, ""),
            "item_id": line.item_id, "meeting_id": line.meeting_id, "section": line.section,
            "action_on": "item" if own else "consent" if over is not None else "",
            "number": line.number, "attachments": line.attachments,
        })
    out = pd.DataFrame(rows, columns=ITEM_COLUMNS)
    return out.sort_values(["date", "meeting_id", "matter_id"], ascending=[False, False, True]).reset_index(drop=True)


def members_table(votes, meetings, board):
    """Everyone seen voting at the board's own meetings on several days. The system publishes no terms and no districts."""
    sat = set(meetings.loc[meetings["committee_id"].isin(board), "meeting_id"])
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
    events = listed(key)
    log.info(f"{board['name']}: {len(events)} meetings listed")
    if len(events) < 10:
        raise RuntimeError("the listing of meetings came back nearly empty")
    meetings = meetings_table(key, events, bodies(key))

    agenda, votes = (council_tables.held(repo_of(key), out_dir, name, base) for name in ("agenda_items", "votes"))
    before = 0 if votes is None else len(votes)
    if agenda is None or votes is None:
        agenda, votes = pd.DataFrame(columns=AGENDA_COLUMNS), pd.DataFrame(columns=VOTE_COLUMNS)
    # A page may hold nothing (a meeting brought over from an older system has only its files), and minutes take the
    # place of an agenda long after the meeting, so which page was read is kept with the meetings.
    was = council_tables.held(repo_of(key), out_dir, "meetings", base)
    read_before = dict(zip(was["meeting_id"], was["document_read"])) if was is not None and "document_read" in was.columns else {}
    meetings["document_read"] = [read_before.get(meeting_id) or "" for meeting_id in meetings["meeting_id"]]
    recent = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    wanted = [meeting for meeting in meetings.to_dict("records") if meeting["document_id"]
              and (everything or meeting["document_read"] != stamp_of(meeting) or meeting["date"] >= recent)]
    wanted.sort(key=lambda meeting: (meeting["date"], meeting["meeting_id"]), reverse=True)  # the newest first: a room shows those
    log.info(f"Reading the pages of {len(wanted)} meetings")

    read = 0
    for start in range(0, max(len(wanted), 1), every):
        some = wanted[start:start + every]
        new_agenda, new_votes, done = [], [], {}
        for meeting, found in zip(some, county.together(lambda meeting: read_meeting(key, meeting), some, "meeting")):
            if found is None:
                continue  # what is held for it stands, and the next run asks again
            done[meeting["meeting_id"]] = stamp_of(meeting)
            new_agenda.extend(found[0])
            new_votes.extend(found[1])
        new_agenda = pd.DataFrame(new_agenda, columns=AGENDA_COLUMNS)
        new_votes = pd.DataFrame(new_votes, columns=VOTE_COLUMNS)
        agenda = joined(agenda[~agenda["meeting_id"].isin(done)], new_agenda)
        votes = joined(votes[~votes["meeting_id"].isin(done)], new_votes)
        agenda = agenda.sort_values(["date", "meeting_id", "sequence"]).reset_index(drop=True)
        votes = votes.sort_values(["date", "meeting_id", "item_id", "motion", "vote", "member"]).reset_index(drop=True)
        for table, columns in ((agenda, ("sequence", "ayes", "noes", "not_voting", "motions")), (votes, ("motion",))):
            for column in columns:
                table[column] = table[column].astype(int)
        agenda["heading"] = agenda["heading"].astype(bool)
        meetings["document_read"] = [done.get(meeting_id, read) for meeting_id, read in zip(meetings["meeting_id"], meetings["document_read"])]
        meetings["items"] = meetings["meeting_id"].map(agenda[~agenda["heading"]].groupby("meeting_id").size()).fillna(0).astype(int)
        council_tables.write_tables({"agenda_items": agenda, "votes": votes, "meetings": meetings}, out_dir)
        read += len(done)
        log.info(f"{board['name']}: {min(start + every, len(wanted))} of {len(wanted)} meetings asked for, {len(votes)} votes held")
        if _refused:
            raise Refused(f"{', '.join(sorted(_refused))} refused; stopped with {read} meetings read, which are kept")

    tables = council_tables.standard({
        "items": items_table(key, agenda, meetings), "meetings": meetings, "agenda_items": agenda, "votes": votes,
        "members": members_table(votes, meetings, {str(number) for number in board["board"]}),
    })
    council_tables.write_tables(tables, out_dir)
    if len(votes) < before * 0.98:
        raise RuntimeError(f"only {len(votes)} votes where there were {before}; not publishing")
    return tables, read


def card(key, tables):
    """The dataset card: the one every county has, with this one's name, addresses and counts written in."""
    board, meetings, votes = BOARDS[key], tables["meetings"], tables["votes"]
    soon = (datetime.now(timezone.utc) + timedelta(days=366)).strftime("%Y-%m-%d")  # a stray meeting dated years on is not the end of the record
    read = meetings[(meetings["items"] > 0) & (meetings["date"] <= soon)]
    span = (f"Votes are recorded from {votes['date'].min()} to {votes['date'].max()}: the meetings whose minutes the County\n"
            "publishes as a page. For any other meeting, and for any motion the minutes give\nno names for, who voted how "
            "is only in the minutes' PDF (`minutes_url`), which is\nnot read here."
            if len(votes) else
            "The County publishes its minutes only as PDFs, which are not read here, so the\n`votes` and `members` tables "
            "are empty: who voted how is in each meeting's\nminutes (`minutes_url`).")
    facts = {
        "title": f"{board['name']} County Board of Supervisors", "place": board["name"], "repo": repo_of(key),
        "host": board["host"], "board_ids": " or ".join(str(number) for number in board["board"]),
        "first_meeting": read["date"].min() if len(read) else "", "last_meeting": read["date"].max() if len(read) else "",
        "vote_span": span, "bodies": f"{meetings['body'].nunique():,}", "serving_days": SERVING_DAYS, "seen_days": SEEN_DAYS,
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
    parser = argparse.ArgumentParser(description="Build a PrimeGov county's meetings, agendas and votes")
    parser.add_argument("--county", "--body", required=True, choices=sorted(BOARDS), help="the county whose board to read")
    parser.add_argument("--base", action="store_true", help="start from the tables written here, not the published ones")
    parser.add_argument("--all", action="store_true", help="read every meeting again")
    parser.add_argument("--out", default="", help="directory to write the tables into (primegov/<county> if not given)")
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
    log.info(f"RESULT: primegov-{args.county} items={len(tables['items'])} meetings={len(meetings)} "
             f"meetings_with_agenda={agenda['meeting_id'].nunique()} meetings_with_votes={votes['meeting_id'].nunique()} "
             f"agenda_items={len(agenda)} votes={len(votes)} "
             f"motions_voted_on={len(votes.drop_duplicates(['meeting_id', 'item_id', 'motion']))} members={len(members)} "
             f"serving={int(members['serving'].sum())} voters_not_members={len(set(votes['member']) - set(members['name']))} "
             f"meetings_read={read} first_vote={votes['date'].min() if len(votes) else ''} "
             f"last_vote={votes['date'].max() if len(votes) else ''} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
