#!/usr/bin/env python3
"""
Build chrissoria/san-diego-council: what came before the San Diego City
Council, what the Council did with it, and how each member voted.

One source: the City Clerk's agenda site (OnBase Agenda Online) at
sandiego.hylandcloud.com/211agendaonlinecouncil, which has every council
meeting since 2010. Two documents of each meeting are read:

  the agenda           for who sat on the Council that day, and in which seat
  the results summary  the Clerk's table of what was done with each item: the
                       action, the ordinance or resolution number it was given,
                       who moved and seconded, and the vote

The summary gives a vote by district ("12356789-yea; 4-nay"), and the agenda
says who held each district, so the two together give each member's vote. The
minutes, which name the members, are not read; they follow months later.

Tables, in data/:
  items.parquet         one row per thing before the Council: an ordinance or
                        resolution by its draft number (O-2025-91), which is the
                        same at its introduction and its adoption, or else one
                        docket entry
  meetings.parquet      one row per meeting that has a results summary
  agenda_items.parquet  one row per item on a meeting's docket, with what was done
  votes.parquet         one row per member and item voted on
  members.parquet       one row per member and seat, with the dates they are seen

    python build_sd_council.py            # the meetings of the last 120 days again
    python build_sd_council.py --base     # every meeting since 2010 not yet read

    --since YEAR   with --base, the first year to read (default 2010)
    --no-upload    write the tables but do not publish them
    --write-card   publish the dataset card as well as the tables
"""

import argparse
import concurrent.futures
import logging
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

import build_federal_bills as bills
import council_tables

log = logging.getLogger(__name__)

HF_REPO = "chrissoria/san-diego-council"
OUT_DIR = bills.SCRIPT_DIR / "sdcouncil"
CARD_FILE = bills.SCRIPT_DIR / "README_sd_council.md"
TABLES = council_tables.TABLES  # the five every council's and board's dataset has; the Council's own columns come after the shared ones

SITE = "https://sandiego.hylandcloud.com/211agendaonlinecouncil"
MEETING_PAGE = SITE + "/Meetings/ViewMeeting?id={id}&doctype={doctype}&site=council"
HEADERS = {"User-Agent": "cat-pol-datasets (+https://github.com/chrissoria/cat-pol-datasets; chrissoria@berkeley.edu)"}
FIRST_YEAR = 2010
RECENT_DAYS = 120  # a summary is posted days after its meeting and corrected for a while after
WORKERS = 3
BODY = "City Council"

MEETING_COLUMNS = ["meeting_id", "date", "time", "body", "name", "location", "url", "agenda_url", "minutes_url", "items"]
AGENDA_COLUMNS = ["item_id", "meeting_id", "date", "body", "agenda_number", "sequence", "matter_id", "matter_file", "title", "action",
                  "result", "doc_type", "doc_num", "mover", "seconder", "ayes", "noes", "not_voting", "vote_text"]
VOTE_COLUMNS = ["item_id", "meeting_id", "date", "matter_id", "matter_file", "member", "district", "vote"]
ITEM_COLUMNS = ["date", "matter_id", "matter_file", "doc_type", "doc_num", "title", "body", "status", "year", "subject", "agenda_date",
                "passed_date", "last_action", "last_action_date", "result", "ayes", "noes", "mover", "seconder", "times_on_agenda", "url"]
COUNCIL_COLUMNS = ["name", "district", "role", "start", "end", "serving", "first_vote", "last_vote", "votes", "meetings"]

ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9}
# What the Clerk writes of a vote, and what it is called here.
VOTE_WORDS = {"yea": "AYE", "nay": "NO", "not present": "NOT PRESENT", "recused": "RECUSED", "ineligible": "INELIGIBLE", "absent": "ABSENT",
              "abstain": "ABSTAIN", "abstained": "ABSTAIN", "vacant": "VACANT"}
PASSED = re.compile(r"\b(adopted|approved|introduced|confirmed|granted|accepted|ratified|appointed)\b", re.I)
FAILED = re.compile(r"^(failed|denied|rejected|not adopted|not approved)", re.I)
# One person under two names on the agendas: an accent left off, and a name changed on marriage.
ALIASES = {"Georgette Gomez": "Georgette Gómez", "Monica Montgomery": "Monica Montgomery Steppe"}
MIN_SEATS = 6  # fewer than this read from an agenda means its head was not read, not that the Council was that small

_session = None


def fetch(url, tries=5, **kwargs):
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
    for attempt in range(tries):
        try:
            response = _session.request(kwargs.pop("method", "GET"), url, timeout=120, **kwargs)
            response.raise_for_status()
            return response.text
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(4 * (attempt + 1))


def clean(text):
    """One line, single spaces, and none before the marks a split word leaves them before."""
    text = re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()
    return re.sub(r"\s+([,;:.)])", r"\1", text)


def day_of(text):
    """'3/25/2025' as 2025-03-25."""
    found = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", (text or "").strip())
    return f"{found.group(3)}-{int(found.group(1)):02d}-{int(found.group(2)):02d}" if found else ""


# ---------------------------------------------------------------------------
# The list of meetings
# ---------------------------------------------------------------------------


def listed(html):
    """The meetings a search shows: id, date, what the Clerk calls it, and which documents it has (1 agenda, 2 minutes, 3 summary)."""
    from bs4 import BeautifulSoup
    found = {}
    for link in BeautifulSoup(html, "html.parser").find_all("a"):
        match = re.search(r"id=(\d+)&doctype=(\d)", link.get("href") or "")
        if not match:
            continue
        box = link
        for _ in range(5):
            box = box.parent
        parts = [part.strip() for part in box.get_text("|", strip=True).split("|")]
        entry = found.setdefault(match.group(1), {"meeting_id": match.group(1), "date": day_of(parts[0]), "name": clean(parts[1] if len(parts) > 1 else ""), "docs": set()})
        entry["docs"].add(int(match.group(2)))
    return list(found.values())


def search(start, end):
    """Every meeting between two days, as 'mm/dd/yyyy'."""
    page = fetch(f"{SITE}/Meetings")
    token = re.search(r'name="__RequestVerificationToken" type="hidden" value="([^"]+)"', page).group(1)
    return listed(fetch(f"{SITE}/Meetings", method="POST", data={
        "__RequestVerificationToken": token, "Keywords": "", "MeetingTypeIDs": "", "DateRangeOptionID": "11",
        "DateRangeCustomStartDate": start, "DateRangeCustomEndDate": end}))


def document(meeting_id, kind):
    doctype = {"agenda": 1, "minutes": 2, "summary": 3}[kind]
    return fetch(f"{SITE}/Documents/ViewAgenda", params={"meetingId": meeting_id, "type": kind, "doctype": doctype})


# ---------------------------------------------------------------------------
# Reading the two documents
# ---------------------------------------------------------------------------


def lines_of(html):
    """The document's paragraphs, each on one line. Words the page splits across pieces are put back together."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    blocks = soup.find_all(["p", "h1", "h2", "h3", "h4", "li", "td"])
    lines = [clean(block.get_text("")) for block in blocks if not block.find(["p", "table"])]
    return [line for line in lines if line]


def roster_of(agenda_html):
    """Who sat in each district, from the head of an agenda: [{district, name, role}].

    The head is a list of names, each followed by its district. Where the page sets two names side by side their districts follow
    together, so names wait in a line and each district takes the one at the front of it."""
    lines = lines_of(agenda_html)
    # A memorandum is sometimes bound in ahead of the agenda; the list starts under the agenda's own title.
    start = next((n + 1 for n, line in enumerate(lines[:400]) if re.fullmatch(r"COUNCIL (AGENDA|DOCKET)", line, re.I)), 0)
    roster, waiting, role = [], [], "Councilmember"
    for line in lines[start:start + 70]:
        if re.search(r"Independent|City Attorney|Budget Analyst|City Clerk", line):
            break
        for part in (piece.strip() for piece in line.split("•")):
            if not part:
                continue
            upper = part.upper()
            if upper in ("COUNCIL PRESIDENT", "COUNCIL PRESIDENT PRO TEM", "COUNCILMEMBERS", "COUNCILMEMBER", "COUNCIL MEMBERS"):
                role = {"COUNCIL PRESIDENT": "Council President", "COUNCIL PRESIDENT PRO TEM": "Council President Pro Tem"}.get(upper, "Councilmember")
                continue
            # A note can follow the district: "First District (Rev. 12/11/23)".
            seat = re.match(r"(?:(.+?)\s+)?(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth)\s+district\b", part, re.I)
            if seat:
                if seat.group(1):
                    waiting.append((clean(seat.group(1)), role))
                    role = "Councilmember"
                if waiting:
                    name, held = waiting.pop(0)
                    if not re.search(r"vacant", name, re.I):
                        roster.append({"district": ORDINALS[seat.group(2).lower()], "name": ALIASES.get(name, name), "role": held})
                continue
            if not re.search(r"\d|AGENDA|DOCKET|CITY OF|REVISED", part) and len(part.split()) <= 6:
                waiting.append((clean(part), role))
                role = "Councilmember"
    return sorted(roster, key=lambda seat: seat["district"])


def time_of(agenda_html):
    """When the meeting was called for, from the head of its agenda: "10:00 AM"."""
    head = " ".join(lines_of(agenda_html)[:120])
    found = re.search(r"\bAT\s+(\d{1,2}):(\d{2})\s*([AP])\.?\s*M\.?", head, re.I)
    return f"{int(found.group(1))}:{found.group(2)} {found.group(3).upper()}M" if found else ""


def districts(text):
    """'12356789' as [1, 2, 3, 5, 6, 7, 8, 9]: each district is one figure."""
    return [int(figure) for figure in re.sub(r"\D", "", text or "")]


def read_vote(text, seats):
    """What each district did, from the Clerk's words: {district: vote}. Empty when no vote was taken or the words are not a count."""
    lower = clean(text).lower()
    named = {}
    # The figures before a word are that word's and no others': in "123468, 5-nay" only the fifth district voted no.
    for figures, word in re.findall(r"(\d+(?: \d+)*)\s*[-–]?\s*(yea|nay|not present|recused|ineligible|absent|abstain(?:ed)?|vacant)", lower):
        for district in districts(figures):
            named[district] = VOTE_WORDS[word]
    for word, figures in re.findall(r"\b(yea|nay)\s*-\s*(\d+)", lower):  # the other way round: "Yea-12345679; Nay-8"
        for district in districts(figures):
            named[district] = VOTE_WORDS[word]
    bare = re.match(r"\s*(\d{2,9})\s*[,;]", lower)  # the yeas with their word left off: "1245679; 8-nay; 3-not present"
    if bare and "NO" in named.values():
        for district in districts(bare.group(1)):
            named.setdefault(district, "AYE")
    if re.search(r"\buna\w*mous", lower):  # everyone not named otherwise voted for it
        return {district: named.get(district, "AYE") for district in seats}
    if named and any(vote in ("AYE", "NO") for vote in named.values()):
        return {district: named[district] for district in seats if district in named}
    return {}


def tidy_action(action):
    """The Clerk's word for what was done, with the same thing always said the same way."""
    action = clean(action).rstrip(".;:")
    lower = action.lower()
    if lower.startswith("continued"):
        return "Continued"
    if "removed from the" in lower or lower.startswith("withdrawn"):
        return "Removed from the docket"
    if lower.startswith("returned to"):
        return "Returned to Staff"
    return re.sub(r"\b(as amended|with direction|by interlineation)\b", lambda found: found.group(1).title().replace("As ", "as ").replace("With ", "with ").replace("By ", "by "), action, flags=re.I)


def read_action(lines):
    """The Clerk's cell for an item, as the action, the draft number and the words: the first line is "Adopted as Amended (R-2025-424 Rev.)"
    and the rest say what was adopted."""
    if not lines:
        return "", "", ""
    first, rest = lines[0], [line for line in lines[1:] if line]
    found = re.match(r"^(.*?)\s*\(([^)]*)\)\s*(.*)$", first)
    action, inside, after = (found.group(1), found.group(2), found.group(3)) if found else (first, "", "")
    draft = re.search(r"\b([ORM]|RR)\s*-\s*(\d{4})\s*-\s*(\d+)", inside, re.I)
    if not rest and not found and len(first) > 60:  # no action is written, only what the item is
        return "", "", first
    if after:
        rest.insert(0, after)
    return tidy_action(action), f"{draft.group(1).upper()}-{draft.group(2)}-{draft.group(3)}" if draft else "", clean(" ".join(rest))


def cell_lines(cell):
    """A cell's paragraphs, each on one line."""
    paragraphs = [clean(paragraph.get_text("")) for paragraph in cell.find_all("p")]
    return [line for line in paragraphs if line] or [clean(cell.get_text(""))]


def read_summary(html, meeting, roster):
    """The rows of a results summary: one agenda entry each, and the votes on those that were voted on."""
    from bs4 import BeautifulSoup
    seats = {seat["district"]: seat["name"] for seat in roster}
    entries, votes = [], []
    for row in BeautifulSoup(html, "html.parser").find_all("tr"):
        found = row.find_all(["td", "th"])
        cells = [clean(cell.get_text("")) for cell in found]
        if len(cells) < 6 or cells[0].upper().startswith("ITEM") or not re.fullmatch(r"[A-Z]{0,2}\s*-?\s*\d+\s*[A-Z]?", cells[0]):
            continue
        number = re.sub(r"\s", "", cells[0])
        action, draft, title = read_action(cell_lines(found[1]))
        cells[5] = clean(" ".join(cell_lines(found[5])))
        kind = cells[2].upper()
        doc_num = f"{kind}-{re.sub(r'[^0-9]', '', cells[3])}" if kind in ("O", "R") and re.search(r"\d", cells[3]) else ""
        movers = districts(cells[4])
        cast = read_vote(cells[5], seats)
        item_id = f"{meeting['meeting_id']}-{number}"
        entries.append({
            "item_id": item_id, "meeting_id": meeting["meeting_id"], "date": meeting["date"], "body": BODY, "agenda_number": number,
            "sequence": len(entries) + 1, "matter_id": draft or item_id, "matter_file": draft or f"Item {number}", "title": title, "action": action,
            "result": "Fail" if FAILED.match(action) else "Pass" if PASSED.search(action) else "",
            "doc_type": {"O": "ordinance", "R": "resolution"}.get(kind, "ordinance" if draft.startswith("O") else "resolution" if draft.startswith("R") else "other"),
            "doc_num": doc_num,
            "mover": seats.get(movers[0], "") if movers else "", "seconder": seats.get(movers[1], "") if len(movers) > 1 else "",
            "ayes": sum(vote == "AYE" for vote in cast.values()), "noes": sum(vote == "NO" for vote in cast.values()),
            "not_voting": sum(vote not in ("AYE", "NO") for vote in cast.values()), "vote_text": cells[5],
        })
        for district, vote in sorted(cast.items()):
            votes.append({"item_id": item_id, "meeting_id": meeting["meeting_id"], "date": meeting["date"], "matter_id": draft or item_id,
                          "matter_file": draft or f"Item {number}", "member": seats.get(district, ""), "district": district, "vote": vote})
    return entries, votes


def read_meeting(meeting):
    """One meeting's roster, entries and votes; None if its documents could not be read."""
    try:
        agenda = document(meeting["meeting_id"], "agenda")
        roster = roster_of(agenda)
        meeting = {**meeting, "time": time_of(agenda)}
        summary = document(meeting["meeting_id"], "summary")
        entries, votes = read_summary(summary, meeting, roster)
    except Exception as e:
        log.warning(f"meeting {meeting['meeting_id']} of {meeting['date']} not read: {type(e).__name__}: {e}")
        return None
    return {"meeting": meeting, "roster": roster, "entries": entries, "votes": votes, "summary": summary if len(roster) < MIN_SEATS else ""}


def borrow_rosters(read, known):
    """A meeting whose agenda's head could not be read takes the Council of the nearest meeting before it, and its votes are read again."""
    seated = sorted([(one["meeting"]["date"], one["roster"]) for one in read if len(one["roster"]) >= MIN_SEATS] + known, key=lambda pair: pair[0])
    for one in read:
        if len(one["roster"]) >= MIN_SEATS or not seated:
            continue
        earlier = [roster for date, roster in seated if date <= one["meeting"]["date"]]
        one["roster"] = earlier[-1] if earlier else seated[0][1]
        one["entries"], one["votes"] = read_summary(one["summary"], one["meeting"], one["roster"])
    return read


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------


def meetings_table(read):
    rows = [{
        "meeting_id": one["meeting"]["meeting_id"], "date": one["meeting"]["date"], "time": one["meeting"].get("time", ""), "body": BODY, "name": one["meeting"]["name"],
        "location": "City Administration Building, Council Chambers, 12th Floor",
        "url": MEETING_PAGE.format(id=one["meeting"]["meeting_id"], doctype=3),
        "agenda_url": MEETING_PAGE.format(id=one["meeting"]["meeting_id"], doctype=1),
        "minutes_url": MEETING_PAGE.format(id=one["meeting"]["meeting_id"], doctype=2) if 2 in one["meeting"]["docs"] else "",
        "items": len(one["entries"]),
    } for one in read]
    return pd.DataFrame(rows, columns=MEETING_COLUMNS)


def rosters_table(read):
    """One row per meeting and seat: who sat where that day. Kept so the council table can be made again without the agendas."""
    return pd.DataFrame([{"meeting_id": one["meeting"]["meeting_id"], "date": one["meeting"]["date"], **seat} for one in read for seat in one["roster"]],
                        columns=["meeting_id", "date", "district", "name", "role"])


def council_table(rosters, votes):
    """Each member's time in a seat, as the agendas show it: the first and last meeting they are listed at."""
    if rosters.empty:
        return pd.DataFrame(columns=COUNCIL_COLUMNS)
    latest = rosters["date"].max()
    cast = votes[votes["vote"].isin(["AYE", "NO"])].groupby("member").agg(first_vote=("date", "min"), last_vote=("date", "max"), votes=("vote", "size"))
    rows = []
    for (name, district), seen in rosters.groupby(["name", "district"]):
        last = seen.sort_values("date").iloc[-1]
        serving = bool(seen["date"].max() == latest)
        rows.append({"name": name, "district": int(district), "role": last["role"] if serving else "Member", "start": seen["date"].min(),
                     "end": "" if serving else seen["date"].max(), "serving": serving,
                     "first_vote": cast["first_vote"].get(name, ""), "last_vote": cast["last_vote"].get(name, ""), "votes": int(cast["votes"].get(name, 0)),
                     "meetings": int(seen["meeting_id"].nunique())})
    table = pd.DataFrame(rows, columns=COUNCIL_COLUMNS).sort_values(["serving", "district", "start"], ascending=[False, True, True]).reset_index(drop=True)
    table["district"] = table["district"].astype("Int64")
    return table


def items_table(agenda):
    """One row per thing before the Council, from every time it was on a docket."""
    rows = []
    for matter, seen in agenda.sort_values(["date", "sequence"]).groupby("matter_id", sort=False):
        first, last = seen.iloc[0], seen.iloc[-1]
        acted = seen[seen["action"] != ""]
        final = acted.iloc[-1] if len(acted) else last
        numbered = seen[seen["doc_num"] != ""]
        title = max(seen["title"], key=len)
        rows.append({
            "date": first["date"], "matter_id": matter, "matter_file": first["matter_file"], "doc_type": final["doc_type"],
            "doc_num": numbered.iloc[-1]["doc_num"] if len(numbered) else "", "title": title, "body": BODY,
            "status": final["action"] or "On the docket", "year": int(first["date"][:4]), "subject": "", "agenda_date": last["date"],
            "passed_date": numbered.iloc[-1]["date"] if len(numbered) else "", "last_action": final["action"],
            "last_action_date": final["date"] if final["action"] else "", "result": final["result"], "ayes": int(final["ayes"]), "noes": int(final["noes"]),
            "mover": final["mover"], "seconder": final["seconder"], "times_on_agenda": len(seen),
            "url": MEETING_PAGE.format(id=last["meeting_id"], doctype=3),
        })
    return pd.DataFrame(rows, columns=ITEM_COLUMNS).sort_values(["date", "matter_id"], ascending=[False, False]).reset_index(drop=True)


def published(name):
    """A table as published: this reader's own, kept in the one dataset of city councils."""
    return council_tables.published(HF_REPO, name)


def before(name, out_dir):
    """A table as last published, or as last written here."""
    table = published(name)
    if table is None and (Path(out_dir) / f"{name}.parquet").exists():
        table = pd.read_parquet(Path(out_dir) / f"{name}.parquet")
    return table


def wanted(base, since, known, today=None):
    """The meetings to read: those with a results summary, all of them not yet read on a whole run, and otherwise the recent ones again."""
    today = today or datetime.now(timezone.utc).date()
    found = []
    if base:
        for year in range(since, today.year + 1):
            found.extend(search(f"01/01/{year}", f"12/31/{year}"))
            time.sleep(1)
    else:
        start = today - timedelta(days=RECENT_DAYS)
        found = search(start.strftime("%m/%d/%Y"), (today + timedelta(days=30)).strftime("%m/%d/%Y"))
    cutoff = (today - timedelta(days=RECENT_DAYS)).isoformat()
    return [meeting for meeting in found if 3 in meeting["docs"] and meeting["date"] and (meeting["meeting_id"] not in known or meeting["date"] >= cutoff)]


def build(base, since, out_dir, limit=0):
    old = {name: before(name, out_dir) for name in ("meetings", "agenda_items", "votes", "rosters")}
    known = set(old["meetings"]["meeting_id"]) if old["meetings"] is not None else set()
    todo = wanted(base or not known, since, known)
    if limit:
        todo = sorted(todo, key=lambda meeting: meeting["date"], reverse=True)[:limit]
    log.info(f"Reading {len(todo)} meetings")
    with concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
        read = [one for one in pool.map(read_meeting, todo) if one]
    held = [] if old["rosters"] is None else [(date, seats.to_dict("records")) for date, seats in old["rosters"][["date", "district", "name", "role"]].groupby("date")]
    read = [one for one in borrow_rosters(read, held) if one["entries"] and one["roster"]]
    done = {one["meeting"]["meeting_id"] for one in read}
    new = {"meetings": meetings_table(read), "rosters": rosters_table(read),
           "agenda_items": pd.DataFrame([entry for one in read for entry in one["entries"]], columns=AGENDA_COLUMNS),
           "votes": pd.DataFrame([vote for one in read for vote in one["votes"]], columns=VOTE_COLUMNS)}
    tables = {}
    for name, table in new.items():
        kept = old[name][~old[name]["meeting_id"].isin(done)] if old[name] is not None else None
        tables[name] = pd.concat([kept, table], ignore_index=True) if kept is not None and len(kept) else table
    tables["meetings"] = tables["meetings"].sort_values(["date", "meeting_id"]).reset_index(drop=True)
    tables["agenda_items"] = tables["agenda_items"].sort_values(["date", "meeting_id", "sequence"]).reset_index(drop=True)
    tables["votes"] = tables["votes"].sort_values(["date", "meeting_id", "item_id", "district"]).reset_index(drop=True)
    tables["items"] = items_table(tables["agenda_items"])
    tables["members"] = council_table(tables["rosters"], tables["votes"])
    if old["meetings"] is not None and len(tables["meetings"]) < len(old["meetings"]):
        raise RuntimeError(f"only {len(tables['meetings'])} meetings where there were {len(old['meetings'])}; not publishing")
    return council_tables.standard(tables), {"read": len(read), "asked": len(todo)}


def write_tables(tables, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        table.to_parquet(out_dir / f"{name}.parquet", index=False)


def upload(out_dir, with_card):
    """Publish the tables as San Diego's files in the one dataset of city councils (council_tables.publish sends them)."""
    try:
        return council_tables.publish(HF_REPO, out_dir, None, with_card, "Update San Diego City Council tables")
    except PermissionError as e:
        log.error(f"San Diego council tables not uploaded: {e}")
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the San Diego City Council dataset")
    parser.add_argument("--base", action="store_true", help="read every meeting not yet read, not only the recent ones")
    parser.add_argument("--since", type=int, default=FIRST_YEAR, help="with --base, the first year to read")
    parser.add_argument("--limit", type=int, default=0, help="read at most this many meetings, the newest first")
    parser.add_argument("--out", default=str(OUT_DIR), help="directory to write the tables into")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the tables only")
    out_dir = Path(args.out)
    try:
        tables, counts = build(args.base, args.since, out_dir, args.limit)
    except Exception as e:
        # A ProxyError here means sandiego.hylandcloud.com is not on the network allowlist.
        log.error(f"San Diego council tables not built: {type(e).__name__}: {e}")
        return 1
    write_tables(tables, out_dir)
    pushed = False if args.no_upload else upload(out_dir, args.write_card)
    if pushed:  # the file Capitol World reads for the Council's chamber is made from these tables; never fatal
        try:
            import build_chamber_snapshot
            build_chamber_snapshot.main(["--body", "sd-council", "--tables", str(out_dir), "--out", str(out_dir)])
        except Exception as e:
            log.error(f"Chamber file not updated: {type(e).__name__}: {e}")
    votes = tables["votes"]
    log.info(f"RESULT: sd-council meetings={len(tables['meetings'])} agenda_items={len(tables['agenda_items'])} items={len(tables['items'])} "
             f"votes={len(votes)} noes={int((votes['vote'] == 'NO').sum())} members={len(tables['members'])} "
             f"serving={int(tables['members']['serving'].sum())} meetings_read={counts['read']} of={counts['asked']} "
             f"newest={tables['meetings']['date'].max() if len(tables['meetings']) else ''} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(main())
