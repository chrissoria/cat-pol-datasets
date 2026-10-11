#!/usr/bin/env python3
"""
Build chrissoria/california-bills: every measure before the California
Legislature, with its text, authors, history and votes, one session at a time.

One source: the Legislature's own export of its bill database, published at
downloads.leginfo.legislature.ca.gov and in the public domain. Each night it
writes the whole session in progress to a zip file of tab-separated tables,
with every version of every bill beside them as XML:

  pubinfo_daily_<Day>.zip   the session in progress, whole, as of that evening
  pubinfo_<year>.zip        one session whole, named for the odd year it began

The file is over a gigabyte, nearly all of it committee analyses this dataset
does not carry. So it is not downloaded: the list of what is in it is read
from its end, and then only the tables and the bill texts wanted are asked
for, each by its own range of bytes. A daily run moves about fifteen megabytes.

Tables, in data/<table>/<session>.parquet:
  bills          one row per measure: where it stands, who wrote it, its digest and text
  actions        one row per entry in a measure's history, with where it left the measure
  votes          one row per roll call, in committee or on the floor
  member_votes   one row per legislator and roll call
  legislators    one row per person who held a seat in the session
  committees     one row per committee, and one for each floor
  hearings       one row per measure and committee hearing it was set for

Two ways to run it:

    python build_california_bills.py
        The daily run: the session in progress, from the newest nightly file.
        A bill's text is asked for only when its newest version is not the one
        already published. A minute or two.

    python build_california_bills.py --session 2023
        One session whole, from pubinfo_2023.zip. Run by hand, once for each
        finished session, 1999-2000 or later. Two minutes, most of it the bill
        texts. (The files for earlier sessions hold only the measures that were
        chaptered, with no history and no votes, and are not used.)

    --zip FILE     read a copy of the export on disk instead of the server's
    --no-upload    write the tables but do not publish them
    --write-card   publish the dataset card as well as the tables
"""

import argparse
import concurrent.futures
import html
import io
import logging
import re
import struct
import sys
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
import zlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import pandas as pd
import requests

import build_federal_bills as bills

log = logging.getLogger(__name__)

HF_REPO = "chrissoria/california-bills"
OUT_DIR = bills.SCRIPT_DIR / "california"
CARD_FILE = bills.SCRIPT_DIR / "README_california_bills.md"
TABLES = ("bills", "actions", "votes", "member_votes", "legislators", "committees", "hearings")
LEGACY_FILE = "data/train-00000-of-00001.parquet"  # the one table this dataset used to be

SOURCE = "https://downloads.leginfo.legislature.ca.gov"
BILL_PAGE = "https://leginfo.legislature.ca.gov/faces/billTextClient.xhtml?bill_id={bill_id}"
HEADERS = {"User-Agent": "cat-pol-datasets (+https://github.com/chrissoria/cat-pol-datasets)"}
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
FIRST_SESSION = 1999  # the files for earlier sessions hold only what was chaptered, with no history or votes
WORKERS = 4  # texts asked for at once
BLOCK = 1 << 20  # bytes asked for at a time while reading the list of members

# The columns of each .dat file, in the order the Legislature's own load scripts give them (pubinfo_load.zip).
COLUMNS = {
    "BILL_TBL": ["bill_id", "session_year", "session_num", "measure_type", "measure_num", "measure_state", "chapter_year",
                 "chapter_type", "chapter_session_num", "chapter_num", "latest_bill_version_id", "active_flg", "trans_uid",
                 "trans_update", "current_location", "current_secondary_loc", "current_house", "current_status",
                 "days_31st_in_print"],
    "BILL_VERSION_TBL": ["bill_version_id", "bill_id", "version_num", "bill_version_action_date", "bill_version_action",
                         "request_num", "subject", "vote_required", "appropriation", "fiscal_committee", "local_program",
                         "substantive_changes", "urgency", "taxlevy", "bill_xml", "active_flg", "trans_uid", "trans_update"],
    "BILL_VERSION_AUTHORS_TBL": ["bill_version_id", "type", "house", "name", "contribution", "committee_members",
                                 "active_flg", "trans_uid", "trans_update", "primary_author_flg"],
    "BILL_HISTORY_TBL": ["bill_id", "bill_history_id", "action_date", "action", "trans_uid", "trans_update_dt",
                         "action_sequence", "action_code", "action_status", "primary_location", "secondary_location",
                         "ternary_location", "end_status"],
    "BILL_SUMMARY_VOTE_TBL": ["bill_id", "location_code", "vote_date_time", "vote_date_seq", "motion_id", "ayes", "noes",
                              "abstain", "vote_result", "trans_uid", "trans_update", "file_item_num", "file_location",
                              "display_lines", "session_date"],
    "BILL_DETAIL_VOTE_TBL": ["bill_id", "location_code", "legislator_name", "vote_date_time", "vote_date_seq", "vote_code",
                             "motion_id", "trans_uid", "trans_update", "member_order", "session_date", "speaker"],
    "BILL_MOTION_TBL": ["motion_id", "motion_text", "trans_uid", "trans_update"],
    "LEGISLATOR_TBL": ["district", "session_year", "legislator_name", "house_type", "author_name", "first_name", "last_name",
                       "middle_initial", "name_suffix", "name_title", "web_name_title", "party", "active_flg", "trans_uid",
                       "trans_update", "active_legislator"],
    "LOCATION_CODE_TBL": ["session_year", "location_code", "location_type", "consent_calendar_code", "description",
                          "long_description", "active_flg", "trans_uid", "trans_update", "inactive_file_flg"],
    "COMMITTEE_HEARING_TBL": ["bill_id", "committee_type", "committee_nr", "hearing_date", "location_code", "trans_uid",
                              "trans_update_date"],
    "VETO_MESSAGE_TBL": ["bill_id", "veto_date", "message", "trans_uid", "trans_update"],
}

DOC_TYPES = {
    "AB": "assembly_bill", "SB": "senate_bill",
    "ACA": "assembly_constitutional_amendment", "SCA": "senate_constitutional_amendment",
    "ACR": "assembly_concurrent_resolution", "SCR": "senate_concurrent_resolution",
    "AJR": "assembly_joint_resolution", "SJR": "senate_joint_resolution",
    "HR": "house_resolution", "SR": "senate_resolution",
}
ASSEMBLY_TYPES = {"AB", "ACA", "ACR", "AJR", "HR"}  # a House Resolution is the Assembly's
SENATE_TYPES = {"SB", "SCA", "SCR", "SJR", "SR"}
CHAMBERS = {"A": "Assembly", "S": "Senate", "ASSEMBLY": "Assembly", "SENATE": "Senate"}
PARTIES = {"DEM": "Democratic", "REP": "Republican", "IND": "Independent"}
ROLES = {"LEAD_AUTHOR": "sponsor", "PRINCIPAL_COAUTHOR": "principal_coauthor", "COAUTHOR": "coauthor"}

BILL_COLUMNS = [
    "date", "session", "bill_number", "bill_id", "doc_type", "title", "text", "url", "origin_chamber", "sponsor_name",
    "status", "current_house", "current_committee", "vote_requirement", "urgency", "fiscal_committee",
    # everything above is what the dataset had when it was one table; what follows was added with the others
    "special_session", "measure_type", "measure_number", "long_title", "digest", "sponsor_ids", "sponsor_party",
    "principal_coauthors", "coauthors", "coauthor_count", "measure_state", "current_location", "current_location_detail",
    "current_committee_code", "last_action_date", "last_action", "chapter", "chapter_year", "appropriation",
    "local_program", "tax_levy", "versions", "text_version_id", "text_version", "text_date", "veto_date", "veto_message",
    "roll_calls",
]
KEPT_TEXT = ["text_version_id", "text_version", "text_date", "long_title", "digest", "text"]


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def today_year():
    return datetime.now(timezone.utc).year


def session_label(session_year):
    """'20252026' as people write it: '2025-2026'."""
    year = str(session_year or "")
    return f"{year[:4]}-{year[4:]}" if len(year) == 8 else year


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")


def day_of(stamp):
    return str(stamp)[:10] if stamp else ""


# ---------------------------------------------------------------------------
# The export
# ---------------------------------------------------------------------------

class _Ranged(io.RawIOBase):
    """A file on a web server, read in blocks as they are asked for. Enough for zipfile to find the list of members."""

    def __init__(self, export):
        self.export, self.position, self.blocks = export, 0, {}

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        self.position = offset if whence == 0 else self.position + offset if whence == 1 else self.export.size + offset
        return self.position

    def readinto(self, buffer):
        if self.position >= self.export.size:
            return 0
        index = self.position // BLOCK
        if index not in self.blocks:
            self.blocks[index] = self.export.fetch(index * BLOCK, min((index + 1) * BLOCK, self.export.size))
        piece = self.blocks[index][self.position - index * BLOCK:][:len(buffer)]
        buffer[:len(piece)] = piece
        self.position += len(piece)
        return len(piece)


class Export:
    """One of the Legislature's zip files, on its server or on disk, read a member at a time."""

    def __init__(self, source):
        self.source = str(source)
        self.remote = self.source.startswith("http")
        self.moved = 0  # bytes asked of the server
        self._own = threading.local()
        if self.remote:
            self.size = self._size()
            self.zip = zipfile.ZipFile(io.BufferedReader(_Ranged(self), BLOCK))
        else:
            self.zip = zipfile.ZipFile(self.source)
        self.members = {info.filename: info for info in self.zip.infolist()}

    def _session(self):
        if not hasattr(self._own, "session"):
            self._own.session = requests.Session()
            self._own.session.headers.update(HEADERS)
        return self._own.session

    def _size(self, tries=4):
        for attempt in range(tries):
            try:
                answer = self._session().head(self.source, timeout=60)
                answer.raise_for_status()
                return int(answer.headers["Content-Length"])
            except requests.RequestException as e:
                # A host that is not allowed, or a file that is not there, will not be there on a second asking.
                if attempt == tries - 1 or isinstance(e, (requests.exceptions.ProxyError, requests.HTTPError)):
                    raise
                self._own.__dict__.pop("session", None)
                time.sleep(2 * (attempt + 1))

    def fetch(self, start, end, tries=5):
        """The bytes from `start` up to `end`."""
        for attempt in range(tries):
            try:
                answer = self._session().get(self.source, headers={"Range": f"bytes={start}-{end - 1}"}, timeout=120,
                                             stream=True)
                if answer.status_code != 206:  # anything else would be the whole gigabyte, or an error page
                    answer.close()
                    raise IOError(f"HTTP {answer.status_code} for a range of {self.source}")
                body = answer.content
                if len(body) != end - start:
                    raise IOError(f"{len(body)} bytes came back for a range of {end - start}")
                self.moved += len(body)
                return body
            except (requests.RequestException, IOError) as e:
                if attempt == tries - 1:
                    raise
                log.debug(f"range {start}-{end} failed ({e}); trying again")
                self._own.__dict__.pop("session", None)
                time.sleep(2 * (attempt + 1))

    def read(self, name):
        """One member, whole."""
        if not self.remote:
            return self.zip.read(name)
        info = self.members[name]
        guess = 30 + len(info.filename.encode()) + 128  # the header before the data, whose length is in the header
        raw = self.fetch(info.header_offset, min(info.header_offset + guess + info.compress_size, self.size))
        name_length, extra_length = struct.unpack("<HH", raw[26:30])
        begins = 30 + name_length + extra_length
        if len(raw) < begins + info.compress_size:
            raw += self.fetch(info.header_offset + len(raw), info.header_offset + begins + info.compress_size)
        data = raw[begins:begins + info.compress_size]
        body = zlib.decompress(data, -15) if info.compress_type == zipfile.ZIP_DEFLATED else data
        if zlib.crc32(body) != info.CRC:
            raise IOError(f"{name} did not arrive whole")
        return body

    def read_many(self, names, what="files"):
        """Several members, as {name: bytes}. One that cannot be read is left out, to be asked for on the next run."""
        names = [name for name in dict.fromkeys(names) if name in self.members]
        out = {}

        def one(name):
            try:
                return self.read(name)
            except Exception as e:
                log.warning(f"{name} not read: {e}")
                return None

        with concurrent.futures.ThreadPoolExecutor(WORKERS if self.remote else 1) as pool:
            for count, (name, body) in enumerate(zip(names, pool.map(one, names)), 1):
                if body is not None:
                    out[name] = body
                if count % 1000 == 0:
                    log.info(f"  {count} of {len(names)} {what} read")
        return out


def newest_daily(tries=4):
    """The address of the most recent nightly file. There is one for each day of the week, written that evening."""
    session = requests.Session()
    session.headers.update(HEADERS)
    found, problem = [], None
    for day in DAYS:
        url = f"{SOURCE}/pubinfo_daily_{day}.zip"
        for attempt in range(tries):
            try:
                answer = session.head(url, timeout=60)
                if answer.ok and answer.headers.get("Last-Modified"):
                    found.append((parsedate_to_datetime(answer.headers["Last-Modified"]), url))
                break
            except requests.RequestException as e:
                problem = e
                if isinstance(e, requests.exceptions.ProxyError):  # the host is not allowed; asking again changes nothing
                    raise
                time.sleep(2 * (attempt + 1))
    if not found:
        raise problem or IOError("no nightly file answered")
    return max(found)[1]


def records(text, width):
    """The rows of a .dat file: tabs between fields, backticks round text, NULL for nothing."""
    held = None
    for line in text.split("\n"):
        line = line.rstrip("\r")
        if held is not None:
            line = f"{held}\n{line}"
        elif not line:
            continue
        fields = line.split("\t")
        if len(fields) < width:  # a line break inside a text field: the row carries on below
            held = line
            continue
        held = None
        yield [None if field == "NULL" else field.strip("`").strip() for field in fields[:width]]


def table(export, name):
    columns = COLUMNS[name]
    member = f"{name}.dat"
    if member not in export.members:
        return pd.DataFrame(columns=columns, dtype=object)
    text = export.read(member).decode("utf-8", errors="replace")
    return pd.DataFrame(list(records(text, len(columns))), columns=columns, dtype=object)  # object: nothing stays None


# ---------------------------------------------------------------------------
# Bill text
# ---------------------------------------------------------------------------

_SPACE = re.compile(r"\s+")
_TAG = re.compile(r"<[^>]+>")
_BLOCKS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "br", "div", "li", "tr", "table", "Num", "Preamble", "Content",
           "BillSection", "Resolved", "Whereas", "ActionLine", "LawHeading", "LawSection", "Title", "DigestText"}


def plain(element):
    """An element's text with one paragraph to a line."""
    if element is None:
        return ""
    parts = []

    def walk(node):
        tag = node.tag.rsplit("}", 1)[-1] if isinstance(node.tag, str) else ""
        block = tag in _BLOCKS
        if block:
            parts.append("\n")
        elif tag in ("td", "th") or "Space" in (node.get("class") or ""):
            parts.append(" ")
        if node.text:
            parts.append(_SPACE.sub(" ", node.text))
        for child in node:
            walk(child)
            if child.tail:
                parts.append(_SPACE.sub(" ", child.tail))
        if block:
            parts.append("\n")

    walk(element)
    lines = (_SPACE.sub(" ", line).strip() for line in "".join(parts).split("\n"))
    return "\n".join(line for line in lines if line)


def read_measure(body):
    """What one version's file says: the formal title, the Legislative Counsel's digest, and the text itself."""
    raw = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    try:
        root = ET.fromstring(raw.encode("utf-8"))
    except ET.ParseError:
        # Older sessions keep some versions as loose markup. The words are still there.
        text = "\n".join(line.strip() for line in html.unescape(_TAG.sub("\n", raw)).split("\n") if line.strip())
        return {"long_title": "", "digest": "", "text": text}
    found = {"long_title": "", "digest": "", "text": ""}
    body_parts = []
    for part in root:
        tag = part.tag.rsplit("}", 1)[-1]
        if tag == "Description":
            for item in part:
                kind = item.tag.rsplit("}", 1)[-1]
                if kind == "Title":
                    found["long_title"] = plain(item).replace("\n", " ")
                elif kind == "DigestText":
                    found["digest"] = plain(item)
        else:
            body_parts.append(plain(part))
    found["text"] = "\n".join(part for part in body_parts if part)
    return found


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------

def bill_number(measure_type, measure_num, session_num="0"):
    """'AB-679', or 'ABX1-3' for a bill of the first extraordinary session."""
    special = str(session_num or "0")
    return f"{measure_type}{'' if special == '0' else 'X' + special}-{measure_num}"


def origin_chamber(measure_type):
    return "Assembly" if measure_type in ASSEMBLY_TYPES else "Senate" if measure_type in SENATE_TYPES else ""


def chamber_of_location(code):
    """The house a place belongs to, from its code: AFLOOR and CX25 are the Assembly's, SFLOOR and CS61 the Senate's."""
    code = str(code or "")
    if code.startswith(("AF", "CX")):
        return "Assembly"
    if code.startswith(("SF", "CS")):
        return "Senate"
    return "Conference" if code.startswith("CONF") else ""


_COMMITTEE_CODE = re.compile(r"^C[SX]\d+$")


def full_name(listed, suffix=None):
    """'Ward, Christopher M.' the way it is said: 'Christopher M. Ward'."""
    last, _, first = str(listed or "").partition(",")
    name = f"{first.strip()} {last.strip()}".strip()
    return f"{name} {suffix}" if suffix else name


def legislators_table(raw, session):
    people = raw[raw["legislator_name"].notna()].copy()  # a row with no name is a seat standing empty
    out = pd.DataFrame({
        "legislator_id": [f"{district}-{slug(name)}" for district, name in zip(people["district"], people["author_name"])],
        "session": session,
        "chamber": people["house_type"].map(CHAMBERS).fillna(""),
        "district": pd.to_numeric(people["district"].str[2:], errors="coerce").astype("Int64"),
        "name": [full_name(name, suffix) for name, suffix in zip(people["legislator_name"], people["name_suffix"])],
        "last_name": people["last_name"].fillna(""),
        "first_name": people["first_name"].fillna(""),
        "author_name": people["author_name"].fillna(""),
        "party": people["party"].map(PARTIES).fillna(people["party"]).fillna(""),
        "title": people["name_title"].fillna(""),
        "serving": (people["active_legislator"] == "Y").to_numpy(),
    })
    return out.drop_duplicates("legislator_id").sort_values(["chamber", "district", "serving"]).reset_index(drop=True)


def committees_table(raw, session):
    """The committees, and the floors: the places a vote is taken. The rest of the codes are pages of the Daily File."""
    places = raw[raw["location_type"].isin(["B", "V"])]
    out = pd.DataFrame({
        "session": session,
        "committee_code": places["location_code"],
        "chamber": places["location_code"].map(chamber_of_location),
        "name": places["long_description"].fillna(places["description"]).fillna(""),
        "kind": places["location_type"].map({"B": "committee", "V": "floor"}),
        "active": (places["active_flg"] == "Y").to_numpy(),
    })
    out.loc[out["committee_code"].str.startswith("CONF"), "kind"] = "conference"
    return out.drop_duplicates("committee_code").sort_values(["chamber", "name"]).reset_index(drop=True)


def actions_table(raw, session, committee_names):
    code = raw["ternary_location"].where(raw["ternary_location"].fillna("").str.match(_COMMITTEE_CODE), "")
    out = pd.DataFrame({
        "bill_id": raw["bill_id"],
        "session": session,
        "seq": pd.to_numeric(raw["action_sequence"], errors="coerce").fillna(0).astype(int),
        "date": raw["action_date"].map(day_of),
        "action": raw["action"].fillna("").map(lambda text: _SPACE.sub(" ", text).strip()),
        "action_code": raw["action_code"].fillna(""),
        "action_status": raw["action_status"].fillna(""),
        "house": raw["primary_location"].fillna(""),
        "location": raw["secondary_location"].fillna(""),
        "location_detail": raw["ternary_location"].fillna(""),
        "committee_code": code,
        "committee": code.map(committee_names).fillna(""),
        "status_after": raw["end_status"].fillna(""),
    })
    out = out[out["bill_id"].notna()]
    return out.sort_values(["bill_id", "date", "seq"]).reset_index(drop=True)


def vote_ids(frame):
    """One name for a roll call, the same in both vote tables."""
    text = frame.astype(str)  # as text whatever the frame holds, so that a session with no roll calls still adds up
    return (text["bill_id"] + "." + text["location_code"] + "." + text["vote_date_time"].str[:10].str.replace("-", "")
            + "." + text["vote_date_seq"] + "." + text["motion_id"])


def votes_table(raw, motions, session, committee_names):
    motion_text = dict(zip(motions["motion_id"], motions["motion_text"]))
    out = pd.DataFrame({
        "vote_id": vote_ids(raw),
        "bill_id": raw["bill_id"],
        "session": session,
        "date": raw["vote_date_time"].map(day_of),
        "date_time": raw["vote_date_time"].fillna(""),
        "chamber": raw["location_code"].map(chamber_of_location),
        "location_code": raw["location_code"],
        "location": raw["location_code"].map(committee_names).fillna(""),
        "motion": raw["motion_id"].map(motion_text).fillna("").map(lambda text: _SPACE.sub(" ", text).strip()),
        "ayes": pd.to_numeric(raw["ayes"], errors="coerce").fillna(0).astype(int),
        "noes": pd.to_numeric(raw["noes"], errors="coerce").fillna(0).astype(int),
        "not_voting": pd.to_numeric(raw["abstain"], errors="coerce").fillna(0).astype(int),
        "result": raw["vote_result"].fillna("").str.strip("()"),
        "file_item": raw["file_item_num"].fillna(""),
    })
    return out.drop_duplicates("vote_id").sort_values(["date_time", "bill_id"]).reset_index(drop=True)


def member_votes_table(raw, session, legislators):
    by_name = {(chamber, name): key for chamber, name, key in
               zip(legislators["chamber"], legislators["author_name"], legislators["legislator_id"])}
    chamber = raw["location_code"].map(chamber_of_location)

    def who(house, name):
        if house == "Conference":  # which seats members of both houses
            return by_name.get(("Assembly", name)) or by_name.get(("Senate", name)) or ""
        return by_name.get((house, name), "")

    out = pd.DataFrame({
        "vote_id": vote_ids(raw),
        "bill_id": raw["bill_id"],
        "session": session,
        "date": raw["vote_date_time"].map(day_of),
        "legislator": raw["legislator_name"].fillna(""),
        "legislator_id": [who(house, name) for house, name in zip(chamber, raw["legislator_name"])],
        "vote": raw["vote_code"].fillna(""),
    })
    return out.drop_duplicates(["vote_id", "legislator"]).sort_values(["date", "vote_id"]).reset_index(drop=True)


def hearings_table(raw, session, committee_names):
    out = pd.DataFrame({
        "bill_id": raw["bill_id"],
        "session": session,
        "date": raw["hearing_date"].map(day_of),
        "committee_code": raw["location_code"].fillna(""),
        "committee": raw["location_code"].map(committee_names).fillna(""),
        "chamber": raw["location_code"].map(chamber_of_location),
    })
    out = out[out["bill_id"].notna()].drop_duplicates()
    return out.sort_values(["date", "committee_code", "bill_id"]).reset_index(drop=True)


def authors_of(authors, legislators):
    """For each version of a bill, who wrote it: {version: {"sponsor": [...], "principal_coauthor": [...], "coauthor": [...]}}."""
    people = {(chamber, name): (key, full, party) for chamber, name, key, full, party in
              zip(legislators["chamber"], legislators["author_name"], legislators["legislator_id"], legislators["name"],
                  legislators["party"])}
    out = {}
    for version, kind, house, name, contribution in zip(authors["bill_version_id"], authors["type"], authors["house"],
                                                        authors["name"], authors["contribution"]):
        role = ROLES.get(contribution)
        if not role or not name:
            continue
        chamber = CHAMBERS.get(str(house or "").upper(), "")
        key, full, party = people.get((chamber, name), ("", "", ""))
        if kind == "Committee" or not full:
            full = name if kind != "Committee" or name.lower().startswith("committee") else f"Committee on {name}"
        out.setdefault(version, {}).setdefault(role, []).append((full, key, party))
    return out


def chapter_of(kind, number, year):
    if not number:
        return ""
    return f"{'Resolution Chapter' if kind == 'CHR' else 'Chapter'} {number}, Statutes of {year}"


def bills_table(raw, versions, authors, actions, votes, legislators, committee_names, session):
    version = versions.set_index("bill_version_id")
    wrote = authors_of(authors, legislators)
    introduced = versions[versions["bill_version_action"] == "Introduced"].groupby("bill_id")["bill_version_action_date"].min()
    how_many = versions.groupby("bill_id").size()
    last = actions.groupby("bill_id").tail(1).set_index("bill_id")
    first_action = actions.groupby("bill_id")["date"].min()
    roll_calls = votes.groupby("bill_id").size()

    rows = []
    for bill in raw.itertuples(index=False):
        latest = version.loc[bill.latest_bill_version_id] if bill.latest_bill_version_id in version.index else None
        field = (lambda name: (latest[name] or "") if latest is not None else "")
        people = wrote.get(bill.latest_bill_version_id, {})
        sponsors = people.get("sponsor", [])
        coauthors = people.get("coauthor", [])
        detail = bill.current_location or ""
        committee_code = detail if _COMMITTEE_CODE.match(detail) else ""
        rows.append({
            "date": day_of(introduced.get(bill.bill_id)) or first_action.get(bill.bill_id, ""),
            "session": session,
            "bill_number": bill_number(bill.measure_type, bill.measure_num, bill.session_num),
            "bill_id": bill.bill_id,
            "doc_type": DOC_TYPES.get(bill.measure_type, "other"),
            "title": field("subject"),
            "text": "",
            "url": BILL_PAGE.format(bill_id=bill.bill_id),
            "origin_chamber": origin_chamber(bill.measure_type),
            "sponsor_name": "; ".join(name for name, _, _ in sponsors),
            "status": bill.current_status or "",
            "current_house": bill.current_house or "",
            "current_committee": committee_names.get(committee_code, ""),
            "vote_requirement": field("vote_required"),
            "urgency": field("urgency"),
            "fiscal_committee": field("fiscal_committee"),
            "special_session": int(bill.session_num or 0),
            "measure_type": bill.measure_type,
            "measure_number": int(bill.measure_num),
            "long_title": "",
            "digest": "",
            "sponsor_ids": "; ".join(key for _, key, _ in sponsors if key),
            "sponsor_party": "; ".join(dict.fromkeys(party for _, _, party in sponsors if party)),
            "principal_coauthors": "; ".join(name for name, _, _ in people.get("principal_coauthor", [])),
            "coauthors": "; ".join(name for name, _, _ in coauthors),
            "coauthor_count": len(coauthors) + len(people.get("principal_coauthor", [])),
            "measure_state": bill.measure_state or "",
            "current_location": bill.current_secondary_loc or "",
            "current_location_detail": detail,
            "current_committee_code": committee_code,
            "last_action_date": last["date"].get(bill.bill_id, ""),
            "last_action": last["action"].get(bill.bill_id, ""),
            "chapter": chapter_of(bill.chapter_type, bill.chapter_num, bill.chapter_year),
            "chapter_year": bill.chapter_year or "",
            "appropriation": field("appropriation"),
            "local_program": field("local_program"),
            "tax_levy": field("taxlevy"),
            "versions": int(how_many.get(bill.bill_id, 0)),
            "text_version_id": "",
            "text_version": "",
            "text_date": "",
            "veto_date": "",
            "veto_message": "",
            "roll_calls": int(roll_calls.get(bill.bill_id, 0)),
        })
    out = pd.DataFrame(rows, columns=BILL_COLUMNS)
    order = out["measure_type"].map({kind: place for place, kind in enumerate(DOC_TYPES)}).fillna(99)
    return out.assign(_order=order).sort_values(["special_session", "_order", "measure_number"]).drop(columns="_order") \
        .reset_index(drop=True)


def settle_statuses(table_, actions):
    """Say where each measure ended, for a session whose export does not (those before 2007-2008).

    The chapter and the history are there even so: a chaptered measure became law or was adopted, a
    bill the Governor returned was vetoed, a house resolution its house adopted passed. Everything
    else died with the session.
    """
    words = actions["action"].str
    vetoed = set(actions.loc[words.contains("Vetoed by Governor", case=False), "bill_id"])
    adopted = set(actions.loc[words.contains(r"\badopted\b", case=False), "bill_id"])

    def status(bill_id, kind, chapter):
        if chapter:
            return "Chaptered"
        if bill_id in vetoed:
            return "Vetoed"
        return "Passed" if kind in ("HR", "SR") and bill_id in adopted else "Died"

    table_["status"] = [status(*row) for row in zip(table_["bill_id"], table_["measure_type"], table_["chapter"])]
    return table_


def add_texts(table_, raw, versions, export, previous):
    """Fill in each bill's digest and text from its newest version, asking only for versions not already held."""
    newest = dict(zip(raw["bill_id"], raw["latest_bill_version_id"]))
    version = versions.set_index("bill_version_id")
    held = {}
    if previous is not None and "text_version_id" in previous.columns:
        held = {row["bill_id"]: row for row in previous[["bill_id"] + KEPT_TEXT].to_dict("records")}

    wanted = {}  # bill -> the member holding its newest version
    for bill_id in table_["bill_id"]:
        version_id = newest.get(bill_id)
        if not version_id or version_id not in version.index:
            continue
        if held.get(bill_id, {}).get("text_version_id") == version_id:
            continue
        member = version.at[version_id, "bill_xml"]
        if member:
            wanted[bill_id] = member
    if wanted:
        log.info(f"Reading the text of {len(wanted)} bills")
    bodies = export.read_many(wanted.values(), "texts")

    table_ = table_.set_index("bill_id", drop=False)
    fetched = 0
    for bill_id in table_.index:
        member = wanted.get(bill_id)
        if member in bodies:
            version_id = newest[bill_id]
            found = read_measure(bodies[member])
            found.update(text_version_id=version_id, text_version=version.at[version_id, "bill_version_action"] or "",
                         text_date=day_of(version.at[version_id, "bill_version_action_date"]))
            fetched += 1
        elif bill_id in held:
            found = held[bill_id]  # its newest version is the one held, or could not be read this time
        else:
            continue
        for column in KEPT_TEXT:
            table_.at[bill_id, column] = found[column] or ""
    # A house resolution is given no subject line; what it is "relative to" stands in for one.
    untitled = table_["title"] == ""
    table_.loc[untitled, "title"] = table_.loc[untitled, "long_title"].str.replace(r"^Relative to\s+", "", regex=True) \
        .str.rstrip(". ").map(lambda text: text[:1].upper() + text[1:])
    return table_.reset_index(drop=True), fetched


def add_vetoes(table_, vetoes, export, previous):
    """The Governor's message for each bill returned unsigned."""
    if vetoes.empty:
        return table_
    held = {}
    if previous is not None and "veto_message" in previous.columns:
        held = {bill_id: message for bill_id, message in zip(previous["bill_id"], previous["veto_message"]) if message}
    vetoes = vetoes.sort_values("veto_date").drop_duplicates("bill_id", keep="last")
    bodies = export.read_many([member for bill_id, member in zip(vetoes["bill_id"], vetoes["message"])
                               if member and bill_id not in held], "veto messages")
    table_ = table_.set_index("bill_id", drop=False)
    for bill_id, when, member in zip(vetoes["bill_id"], vetoes["veto_date"], vetoes["message"]):
        if bill_id not in table_.index:
            continue
        message = held.get(bill_id) or bodies.get(member, b"").decode("utf-8", errors="replace")
        table_.at[bill_id, "veto_date"] = day_of(when)
        table_.at[bill_id, "veto_message"] = "\n".join(line.strip() for line in message.split("\n") if line.strip())
    return table_.reset_index(drop=True)


def published(name, session, out_dir):
    """The table as last published for a session, or as last written here, or None."""
    try:
        from huggingface_hub import hf_hub_download
        return pd.read_parquet(hf_hub_download(HF_REPO, f"data/{name}/{session}.parquet", repo_type="dataset",
                                               token=bills.HF_TOKEN))
    except Exception as e:
        local = Path(out_dir) / name / f"{session}.parquet"
        if local.exists():
            return pd.read_parquet(local)
        if "404" not in str(e) and "EntryNotFound" not in type(e).__name__:
            log.warning(f"Published {name} table for {session} not read: {e}")
        return None


def build(export, out_dir):
    """Every table for the session the export holds."""
    raw = {name: table(export, name) for name in COLUMNS}
    measures = raw["BILL_TBL"]
    measures = measures[(measures["active_flg"] == "Y") & measures["measure_type"].isin(list(DOC_TYPES) + ["GRP"])]
    if measures.empty:
        raise RuntimeError("the export lists no measures")
    session_year = measures["session_year"].mode()[0]
    measures = measures[measures["session_year"] == session_year]
    session = session_label(session_year)
    in_session = set(measures["bill_id"])
    log.info(f"Session {session}: {len(measures)} measures")

    def ours(frame, flag=None):
        frame = frame[frame["bill_id"].isin(in_session)]
        return frame[frame[flag] == "Y"] if flag else frame

    versions = ours(raw["BILL_VERSION_TBL"], "active_flg")
    authors = raw["BILL_VERSION_AUTHORS_TBL"]
    authors = authors[(authors["active_flg"] == "Y") & authors["bill_version_id"].isin(set(versions["bill_version_id"]))]
    seats = raw["LEGISLATOR_TBL"]
    seats = seats[(seats["session_year"] == session_year) & (seats["active_flg"] == "Y")]
    places = raw["LOCATION_CODE_TBL"]
    places = places[places["session_year"] == session_year]

    tables = {"legislators": legislators_table(seats, session), "committees": committees_table(places, session)}
    committee_names = dict(zip(tables["committees"]["committee_code"], tables["committees"]["name"]))
    tables["actions"] = actions_table(ours(raw["BILL_HISTORY_TBL"]), session, committee_names)
    tables["votes"] = votes_table(ours(raw["BILL_SUMMARY_VOTE_TBL"]), raw["BILL_MOTION_TBL"], session, committee_names)
    tables["member_votes"] = member_votes_table(ours(raw["BILL_DETAIL_VOTE_TBL"]), session, tables["legislators"])
    tables["hearings"] = hearings_table(ours(raw["COMMITTEE_HEARING_TBL"]), session, committee_names)

    previous = published("bills", session, out_dir)
    found = bills_table(measures, versions, authors, tables["actions"], tables["votes"], tables["legislators"],
                        committee_names, session)
    if (found["status"] == "").all():
        found = settle_statuses(found, tables["actions"])
    found, fetched = add_texts(found, measures, versions, export, previous)
    tables["bills"] = add_vetoes(found, ours(raw["VETO_MESSAGE_TBL"]), export, previous)

    with_text = int((tables["bills"]["text"].str.len() > 0).sum())
    if previous is not None:
        had_text = int((previous["text"].fillna("").str.len() > 0).sum()) if "text_version_id" in previous.columns else 0
        if len(tables["bills"]) < len(previous) * 0.98 or with_text < had_text * 0.98:
            raise RuntimeError(f"the rebuilt bills table is smaller than the published one "
                               f"({len(tables['bills'])} rows, {with_text} with text; was {len(previous)}, {had_text})")
    if with_text < len(tables["bills"]) * 0.9:
        raise RuntimeError(f"only {with_text} of {len(tables['bills'])} bills have text; not publishing")
    return session, tables, {"fetched": fetched, "with_text": with_text}


def write_tables(tables, session, out_dir):
    for name in TABLES:
        path = Path(out_dir) / name / f"{session}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        tables[name].to_parquet(path, index=False)


def upload(session, out_dir, with_card):
    problem = bills.hf_write_problem(HF_REPO)
    if problem:
        log.error(f"California tables not uploaded: {problem}")
        return False
    from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi
    api = HfApi(token=bills.HF_TOKEN)
    operations = [CommitOperationAdd(path_in_repo=f"data/{name}/{session}.parquet",
                                     path_or_fileobj=str(Path(out_dir) / name / f"{session}.parquet")) for name in TABLES]
    listed = set(api.list_repo_files(HF_REPO, repo_type="dataset"))
    first = LEGACY_FILE in listed
    if first:  # the old single table gives way to the new ones, and the card has to say where they are
        operations.append(CommitOperationDelete(path_in_repo=LEGACY_FILE))
    if (with_card or first or "README.md" not in listed) and CARD_FILE.exists():
        operations.append(CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=str(CARD_FILE)))
    api.create_commit(repo_id=HF_REPO, repo_type="dataset", operations=operations,
                      commit_message=f"Update California tables, session {session} ({today()})")
    log.info(f"Uploaded {len(operations)} files to {HF_REPO}")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the California bills dataset")
    parser.add_argument("--session", type=int, choices=range(FIRST_SESSION, today_year() + 1, 2), metavar="YEAR",
                        help=f"the odd year a finished session began (2023 for 2023-2024), {FIRST_SESSION} or later")
    parser.add_argument("--zip", help="a copy of the export on disk, instead of the server's")
    parser.add_argument("--out", default=str(OUT_DIR), help="directory to write the tables into")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the tables only")

    try:
        source = args.zip or (f"{SOURCE}/pubinfo_{args.session}.zip" if args.session else newest_daily())
        log.info(f"Reading {source}")
        export = Export(source)
    except Exception as e:
        # A ProxyError here means downloads.leginfo.legislature.ca.gov is not on the network allowlist.
        log.error(f"California export not reached: {type(e).__name__}: {e}")
        return 1
    try:
        session, tables, counts = build(export, args.out)
    except Exception as e:
        log.error(f"California tables not built: {e}")
        return 1
    write_tables(tables, session, args.out)
    pushed = False if args.no_upload else upload(session, args.out, args.write_card)
    found = tables["bills"]
    log.info(f"RESULT: california-bills session={session} bills={len(found)} with_text={counts['with_text']} "
             f"chaptered={int((found['status'] == 'Chaptered').sum())} actions={len(tables['actions'])} "
             f"votes={len(tables['votes'])} member_votes={len(tables['member_votes'])} "
             f"legislators={len(tables['legislators'])} texts_read={counts['fetched']} "
             f"megabytes={export.moved / 1e6:.0f} source={source.rsplit('/', 1)[-1]} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(main())
