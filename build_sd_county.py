#!/usr/bin/env python3
"""
Build chrissoria/sd-county-ordinances: what comes before the San Diego County
Board of Supervisors, what the Board did with it, and how each supervisor voted.

One source: the County's legislative system (Legistar), through its public
API at webapi.legistar.com/v1/sdcounty. It goes back to June 2017. Documents
attached to an item (the ordinance itself, the board letter) are read from
sdcounty.legistar1.com.

Tables, in data/:
  ordinances.parquet     the items that are ordinances or resolutions: what the dataset
                         has always been, with the same first ten columns
  items.parquet          every item filed, of any kind
  meetings.parquet       one row per meeting of the Board and the bodies it sits as
  agenda_items.parquet   one row per item on a meeting's agenda, with what was done
  votes.parquet          one row per supervisor and item acted on
  supervisors.parquet    one row per supervisor's time on the Board

Two ways to run it:

    python build_sd_county.py
        The routine run. Lists every item again (eight requests), reads again
        the agendas and votes of meetings in the last 60 days and those to
        come, and reads the documents of items that are new or whose document
        has changed. A few minutes.

    python build_sd_county.py --base
        Every meeting since 2017 and every document not yet read. Run by hand,
        once; it can be stopped and started again, and --max-texts sets how
        many documents one run reads.

    --max-texts N  documents to read in one run (default 300; 0 for none)
    --no-upload    write the tables but do not publish them
    --write-card   publish the dataset card as well as the tables

PDF documents need pdfplumber. Without it they are left for a run that has it;
Word documents, which are most of them, are read with the standard library.
"""

import argparse
import concurrent.futures
import io
import json
import logging
import re
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

import build_federal_bills as bills

log = logging.getLogger(__name__)

HF_REPO = "chrissoria/sd-county-ordinances"
OUT_DIR = bills.SCRIPT_DIR / "sdcounty"
CARD_FILE = bills.SCRIPT_DIR / "README_sd_county.md"
TABLES = ("ordinances", "items", "meetings", "agenda_items", "votes", "supervisors")
LEGACY_FILE = "data/train-00000-of-00001.parquet"  # the one table this dataset used to be

API = "https://webapi.legistar.com/v1/sdcounty"
ITEM_PAGE = "https://sdcounty.legistar.com/LegislationDetail.aspx?ID={id}&GUID={guid}"
HEADERS = {"User-Agent": "cat-pol-datasets (+https://github.com/chrissoria/cat-pol-datasets)"}
PAGE = 1000
WORKERS = 4
RECENT_DAYS = 60  # meetings this recent are read again: minutes and votes are entered after the meeting
RETRY_DAYS = 30  # an item this recently changed whose document could not be read is tried again

LEGACY_COLUMNS = ["date", "matter_id", "matter_file", "doc_type", "title", "text", "attachment_url", "body", "status", "year"]
ITEM_COLUMNS = LEGACY_COLUMNS + [
    # everything above is what the dataset had when it was one table
    "subject", "agenda_date", "passed_date", "last_action", "last_action_date", "result", "ayes", "noes", "mover",
    "seconder", "times_on_agenda", "text_source", "attachments", "url", "last_modified",
]
MEETING_COLUMNS = ["meeting_id", "date", "time", "body", "location", "agenda_url", "minutes_url", "url", "agenda_status",
                   "minutes_status", "items", "last_modified"]
AGENDA_COLUMNS = ["item_id", "meeting_id", "date", "body", "agenda_number", "sequence", "matter_id", "matter_file", "title",
                  "action", "action_text", "result", "mover", "seconder", "ayes", "noes", "not_voting"]
VOTE_COLUMNS = ["item_id", "meeting_id", "date", "matter_id", "matter_file", "supervisor", "vote"]

# The source does not say which district a supervisor sits for. These are from the County's own pages.
DISTRICTS = {
    "Greg Cox": 1, "Nora Vargas": 1, "Paloma Aguirre": 1,
    "Dianne Jacob": 2, "Joel Anderson": 2,
    "Dave Roberts": 3, "Kristin Gaspar": 3, "Terra Lawson-Remer": 3,
    "Ron Roberts": 4, "Nathan Fletcher": 4, "Monica Montgomery Steppe": 4,
    "Bill Horn": 5, "Jim Desmond": 5,
}
# Papers filed with an item that are about the meeting, not the item itself.
_NOT_THE_DOCUMENT = re.compile(r"approval log|comment|communication|speaker|exhibit|minute order|presentation"
                               r"|proof of publication|notice of|affidavit", re.I)
_READABLE = (".docx", ".pdf")


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def day_of(stamp):
    return str(stamp)[:10] if stamp else ""


def clean(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


# ---------------------------------------------------------------------------
# The API
# ---------------------------------------------------------------------------

def api(path, tries=5, **params):
    """One answer from the API, as parsed JSON. `top=5` becomes `$top=5`; a capitalised name is passed as it is."""
    query = {(name if name[0].isupper() else f"${name}"): value for name, value in params.items()}
    for attempt in range(tries):
        try:
            answer = requests.get(f"{API}/{path}", params=query, headers=HEADERS, timeout=60)
            answer.raise_for_status()
            return answer.json()
        except (requests.RequestException, ValueError) as e:
            # A host that is not allowed will not be allowed on a second asking.
            if attempt == tries - 1 or isinstance(e, requests.exceptions.ProxyError):
                raise
            time.sleep(2 * (attempt + 1))


def paged(path, **params):
    """Every row of a listing, a thousand at a time."""
    rows = []
    while True:
        page = api(path, top=PAGE, skip=len(rows), **params)
        rows.extend(page)
        if len(page) < PAGE:
            return rows


def together(function, things, what):
    """`function` over `things`, a few at a time, as a list in the same order. A failure is None."""
    def one(thing):
        try:
            return function(thing)
        except Exception as e:
            log.warning(f"{what} {thing}: {type(e).__name__}: {e}")
            return None

    with concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
        return list(pool.map(one, things))


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

def doc_type_of(title):
    """What an item is, from its title. The County files everything under subject areas, not kinds of document."""
    lowered = str(title or "").lower()
    return "ordinance" if "ordinance" in lowered else "resolution" if "resolution" in lowered else "other"


def pick_document(doc_type, attachments, held=""):
    """The address of the attachment that is the item itself, or "" if none can be read.

    For an ordinance or resolution that is the ordinance; for anything else the board letter, in
    which staff set out what the Board is asked to do and what it costs. A choice already made
    is kept while that attachment is still on the item, so its text is not read twice.
    """
    listed = [(clean(a.get("name")), a.get("url") or "") for a in attachments if a.get("url")]
    if held and any(url == held for _, url in listed):
        return held
    readable = [(name, url) for name, url in listed if url.lower().endswith(_READABLE)]
    wanted = [r"ordinance|clean", r"resolution"] if doc_type != "other" else []
    wanted += [r"board ?letter|\bBL\b", r"agenda (item )?information sheet"]
    for pattern in wanted:
        for name, url in readable:
            if re.search(pattern, name, re.I) and not _NOT_THE_DOCUMENT.search(name):
                return url
    for name, url in readable:
        if not _NOT_THE_DOCUMENT.search(name):
            return url
    return ""


_WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_text(body):
    """The paragraphs of a Word document, with a blank line between them."""
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    paragraphs = []
    for paragraph in root.iter(f"{_WORD}p"):
        parts = []
        for node in paragraph.iter():
            if node.tag == f"{_WORD}t":
                parts.append(node.text or "")
            elif node.tag in (f"{_WORD}tab", f"{_WORD}br", f"{_WORD}cr"):
                parts.append("\t" if node.tag == f"{_WORD}tab" else "\n")
        text = "".join(parts)
        if text.strip():
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def pdf_reader():
    """pdfplumber if it is installed, or None: PDFs then wait for a run that has it."""
    try:
        import pdfplumber
        logging.getLogger("pdfminer").setLevel(logging.ERROR)
        return pdfplumber
    except ImportError:
        return None


def read_document(url, session, pdf):
    """The text of an attached document. "" when it cannot be read; None when it was not tried."""
    lowered = url.lower()
    if lowered.endswith(".pdf") and pdf is None:
        return None
    answer = session.get(url, headers=HEADERS, timeout=90)
    answer.raise_for_status()
    try:
        if lowered.endswith(".docx"):
            return docx_text(answer.content)
        with pdf.open(io.BytesIO(answer.content)) as document:
            pages = [page.extract_text() for page in document.pages]
        return "\n\n".join(page for page in pages if page)
    except Exception as e:
        log.debug(f"{url} not read: {e}")
        return ""


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------

def meetings_table(events):
    rows = [{
        "meeting_id": str(event["EventId"]),
        "date": day_of(event["EventDate"]),
        "time": clean(event.get("EventTime")),
        "body": clean(event.get("EventBodyName")),
        "location": clean(event.get("EventLocation")),
        "agenda_url": event.get("EventAgendaFile") or "",
        "minutes_url": event.get("EventMinutesFile") or "",
        "url": event.get("EventInSiteURL") or "",
        "agenda_status": clean(event.get("EventAgendaStatusName")),
        "minutes_status": clean(event.get("EventMinutesStatusName")),
        "items": 0,
        "last_modified": str(event.get("EventLastModifiedUtc") or "")[:19],
    } for event in events]
    return pd.DataFrame(rows, columns=MEETING_COLUMNS).sort_values(["date", "meeting_id"]).reset_index(drop=True)


def read_meeting(event):
    """One meeting's agenda: its items, the votes on those acted on, and the documents filed with each."""
    meeting_id, date, body = str(event["EventId"]), day_of(event["EventDate"]), clean(event.get("EventBodyName"))
    agenda, votes, papers = [], [], {}
    for item in api(f"events/{meeting_id}/eventitems", AgendaNote=1, MinutesNote=1, Attachments=1):
        matter_id = item.get("EventItemMatterId")
        if not matter_id:
            continue  # a heading, the roll call, the pledge
        matter_id, item_id = str(matter_id), str(item["EventItemId"])
        papers[matter_id] = [{"name": clean(a.get("MatterAttachmentName")), "url": a.get("MatterAttachmentHyperlink") or ""}
                             for a in item.get("EventItemMatterAttachments") or []]
        cast = api(f"eventitems/{item_id}/votes") if item.get("EventItemActionName") else []
        tally = {}
        for vote in cast:
            value = clean(vote.get("VoteValueName")).upper()
            tally[value] = tally.get(value, 0) + 1
            votes.append({"item_id": item_id, "meeting_id": meeting_id, "date": date, "matter_id": matter_id,
                          "matter_file": item.get("EventItemMatterFile") or "", "supervisor": clean(vote.get("VotePersonName")),
                          "vote": value})
        agenda.append({
            "item_id": item_id, "meeting_id": meeting_id, "date": date, "body": body,
            "agenda_number": clean(item.get("EventItemAgendaNumber")).rstrip("."),
            "sequence": int(item.get("EventItemAgendaSequence") or 0),
            "matter_id": matter_id, "matter_file": item.get("EventItemMatterFile") or "",
            "title": clean(item.get("EventItemTitle")),
            "action": clean(item.get("EventItemActionName")), "action_text": clean(item.get("EventItemActionText")),
            "result": clean(item.get("EventItemPassedFlagName")),
            "mover": clean(item.get("EventItemMover")), "seconder": clean(item.get("EventItemSeconder")),
            "ayes": tally.get("AYE", 0), "noes": tally.get("NOE", 0) + tally.get("NAY", 0) + tally.get("NO", 0),
            "not_voting": sum(count for value, count in tally.items() if value not in ("AYE", "NOE", "NAY", "NO")),
        })
    return agenda, votes, papers


def supervisors_table(records, votes):
    seats = [r for r in records if clean(r.get("OfficeRecordBodyName")) == "BOARD OF SUPERVISORS"
             and clean(r.get("OfficeRecordTitle")) == "Supervisor"]
    rows = [{
        "name": clean(seat["OfficeRecordFullName"]),
        "district": DISTRICTS.get(clean(seat["OfficeRecordFullName"])),
        "start": day_of(seat.get("OfficeRecordStartDate")),
        "end": day_of(seat.get("OfficeRecordEndDate")),
        "role": clean(seat.get("OfficeRecordMemberType")),
        "serving": day_of(seat.get("OfficeRecordStartDate")) <= today() <= (day_of(seat.get("OfficeRecordEndDate")) or "9999"),
    } for seat in seats]
    out = pd.DataFrame(rows, columns=["name", "district", "start", "end", "role", "serving"])
    out["district"] = out["district"].astype("Int64")
    # The record holds one term, not a whole time on the Board. The votes say when someone was first and last there.
    cast = votes.groupby("supervisor")["date"].agg(["min", "max", "size"])
    out["first_vote"] = out["name"].map(cast["min"]).fillna("")
    out["last_vote"] = out["name"].map(cast["max"]).fillna("")
    out["votes"] = out["name"].map(cast["size"]).fillna(0).astype(int)
    return out.drop_duplicates(["name", "start"]).sort_values(["start", "district"]).reset_index(drop=True)


def items_table(matters, agenda, papers, previous):
    """Every item filed, with the last thing done to it and the document chosen for it (not yet its text)."""
    held = {}
    if previous is not None:
        for row in previous.to_dict("records"):
            held[str(row["matter_id"])] = row
    acted = agenda[agenda["action"] != ""].sort_values(["date", "sequence"])
    last = acted.groupby("matter_id").tail(1).set_index("matter_id")
    times = agenda.groupby("matter_id").size()

    rows = []
    for matter in matters:
        matter_id = str(matter["MatterId"])
        before = held.get(matter_id, {})
        title = clean(matter.get("MatterTitle"))
        doc_type = doc_type_of(title)
        listed = papers.get(matter_id)
        if listed is None:  # not on an agenda read this time: what was known of its papers stands
            try:
                listed = json.loads(before.get("attachments") or "[]")
            except ValueError:
                listed = []
        url = pick_document(doc_type, listed, before.get("attachment_url") or "")
        if not url and not listed:
            url = before.get("attachment_url") or ""  # from the old table, which kept the address and not the list
        same = bool(url) and url == (before.get("attachment_url") or "")
        date = day_of(matter.get("MatterIntroDate"))
        done = last.loc[matter_id] if matter_id in last.index else None
        rows.append({
            "date": date,
            "matter_id": matter_id,
            "matter_file": matter.get("MatterFile") or "",
            "doc_type": doc_type,
            "title": title,
            "text": (before.get("text") or "") if same else "",
            "attachment_url": url,
            "body": clean(matter.get("MatterBodyName")),
            "status": clean(matter.get("MatterStatusName")),
            "year": int(date[:4]) if date[:4].isdigit() else 0,
            "subject": clean(matter.get("MatterTypeName")),
            "agenda_date": day_of(matter.get("MatterAgendaDate")),
            "passed_date": day_of(matter.get("MatterPassedDate")),
            "last_action": done["action"] if done is not None else "",
            "last_action_date": done["date"] if done is not None else "",
            "result": done["result"] if done is not None else "",
            "ayes": int(done["ayes"]) if done is not None else 0,
            "noes": int(done["noes"]) if done is not None else 0,
            "mover": done["mover"] if done is not None else "",
            "seconder": done["seconder"] if done is not None else "",
            "times_on_agenda": int(times.get(matter_id, 0)),
            # Which document `text` is: its address once read, "" until then. A legacy row's text was read from its address.
            "text_source": (before.get("text_source") or (url if before.get("text") else "")) if same else "",
            "attachments": json.dumps(listed, ensure_ascii=False, separators=(",", ":")),
            "url": ITEM_PAGE.format(id=matter_id, guid=matter.get("MatterGuid") or ""),
            "last_modified": str(matter.get("MatterLastModifiedUtc") or "")[:19],
        })
    out = pd.DataFrame(rows, columns=ITEM_COLUMNS)
    return out.sort_values(["date", "matter_id"], ascending=[False, False]).reset_index(drop=True)


def add_texts(items, limit):
    """Read the documents not yet read, newest items first, up to `limit`. Returns how many were read and whether PDFs were."""
    pdf = pdf_reader()
    recent = (datetime.now(timezone.utc) - timedelta(days=RETRY_DAYS)).strftime("%Y-%m-%d")
    unread = items[(items["attachment_url"] != "") & (items["text"] == "")
                   & ((items["text_source"] == "") | (items["last_modified"] >= recent))]
    if pdf is None:
        unread = unread[~unread["attachment_url"].str.lower().str.endswith(".pdf")]
    waiting = len(unread)
    unread = unread.head(limit)
    if unread.empty:
        return 0, waiting, pdf is not None
    log.info(f"Reading {len(unread)} of {waiting} documents not yet read")
    session = requests.Session()
    texts = together(lambda url: read_document(url, session, pdf), unread["attachment_url"].tolist(), "document")
    read = 0
    for index, url, text in zip(unread.index, unread["attachment_url"], texts):
        if text is None:
            continue
        items.at[index, "text"] = text
        items.at[index, "text_source"] = url  # even when nothing could be read from it, so it is not asked for every day
        read += bool(text)
    return read, waiting - len(unread), pdf is not None


def published(name):
    """A table as last published, or None."""
    try:
        from huggingface_hub import hf_hub_download
        return pd.read_parquet(hf_hub_download(HF_REPO, f"data/{name}.parquet", repo_type="dataset", token=bills.HF_TOKEN))
    except Exception:
        return None


def published_items(out_dir):
    """The items as last published: the new table, or the single one the dataset used to be, or what was last written here."""
    found = published("items")
    if found is None:
        local = Path(out_dir) / "items.parquet"
        if local.exists():
            return pd.read_parquet(local)
        try:
            from huggingface_hub import hf_hub_download
            found = pd.read_parquet(hf_hub_download(HF_REPO, LEGACY_FILE, repo_type="dataset", token=bills.HF_TOKEN))
        except Exception:
            return None
    return found


def build(base, max_texts, out_dir):
    events = paged("events", orderby="EventId")
    matters = paged("matters", orderby="MatterId")
    log.info(f"{len(matters)} items and {len(events)} meetings listed")
    if len(matters) < 100:
        raise RuntimeError("the listing of items came back nearly empty")
    meetings = meetings_table(events)

    before = {name: published(name) for name in ("agenda_items", "votes")}
    if any(table is None for table in before.values()):
        local = {name: Path(out_dir) / f"{name}.parquet" for name in before}
        before = {name: pd.read_parquet(path) if path.exists() else None for name, path in local.items()}
    known = set(before["agenda_items"]["meeting_id"]) if before["agenda_items"] is not None else set()
    since = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    wanted = [event for event in events
              if base and str(event["EventId"]) not in known or day_of(event["EventDate"]) >= since]
    if before["agenda_items"] is None and not base:
        wanted = events  # nothing has been read yet: the first run is a whole one
    log.info(f"Reading the agendas of {len(wanted)} meetings")
    agenda, votes, papers, read = [], [], {}, set()
    for event, found in zip(wanted, together(read_meeting, wanted, "meeting")):
        if found is None:
            continue  # what was published for it stands, and the next run asks again
        read.add(str(event["EventId"]))
        agenda.extend(found[0])
        votes.extend(found[1])
        papers.update(found[2])
    agenda = pd.DataFrame(agenda, columns=AGENDA_COLUMNS)
    votes = pd.DataFrame(votes, columns=VOTE_COLUMNS)
    if before["agenda_items"] is not None:
        agenda = pd.concat([before["agenda_items"][~before["agenda_items"]["meeting_id"].isin(read)], agenda], ignore_index=True)
        votes = pd.concat([before["votes"][~before["votes"]["meeting_id"].isin(read)], votes], ignore_index=True)
    agenda = agenda.sort_values(["date", "meeting_id", "sequence"]).reset_index(drop=True)
    votes = votes.sort_values(["date", "meeting_id", "item_id", "supervisor"]).reset_index(drop=True)
    meetings["items"] = meetings["meeting_id"].map(agenda.groupby("meeting_id").size()).fillna(0).astype(int)

    previous = published_items(out_dir)
    # An item not on any agenda read this time has its papers asked for directly: all such on a whole run,
    # and otherwise the ones lately changed, which are mostly new items not yet given a date.
    listed = set(previous.loc[previous["attachments"].fillna("") != "", "matter_id"].astype(str)) \
        if previous is not None and "attachments" in previous.columns else set()
    alone = [str(m["MatterId"]) for m in matters if str(m["MatterId"]) not in papers
             and (day_of(m.get("MatterLastModifiedUtc")) >= since or base and str(m["MatterId"]) not in listed)]
    if alone:
        log.info(f"Asking for the papers of {len(alone)} items not on those agendas")
        for matter_id, found in zip(alone, together(lambda key: api(f"matters/{key}/attachments"), alone, "papers of item")):
            if found is not None:
                papers[matter_id] = [{"name": clean(a.get("MatterAttachmentName")), "url": a.get("MatterAttachmentHyperlink") or ""}
                                     for a in found]
    items = items_table(matters, agenda, papers, previous)
    texts_read, waiting, pdfs = add_texts(items, max_texts)
    with_text = int((items["text"] != "").sum())
    if previous is not None:
        had = int((previous["text"].fillna("") != "").sum())
        if with_text < had * 0.98:
            raise RuntimeError(f"only {with_text} items have text where {had} did; not publishing")
        if "subject" in previous.columns and len(items) < len(previous) * 0.98:
            raise RuntimeError(f"only {len(items)} items where there were {len(previous)}; not publishing")
    tables = {
        "items": items,
        "ordinances": items[items["doc_type"] != "other"].reset_index(drop=True),
        "meetings": meetings,
        "agenda_items": agenda,
        "votes": votes,
        "supervisors": supervisors_table(api("officerecords"), votes),
    }
    return tables, {"read": texts_read, "waiting": waiting, "with_text": with_text, "pdf": "ok" if pdfs else "skipped",
                    "meetings_read": len(read)}


def write_tables(tables, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in TABLES:
        tables[name].to_parquet(out_dir / f"{name}.parquet", index=False)


def upload(out_dir, with_card):
    problem = bills.hf_write_problem(HF_REPO)
    if problem:
        log.error(f"San Diego County tables not uploaded: {problem}")
        return False
    from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi
    api_ = HfApi(token=bills.HF_TOKEN)
    operations = [CommitOperationAdd(path_in_repo=f"data/{name}.parquet", path_or_fileobj=str(out_dir / f"{name}.parquet"))
                  for name in TABLES]
    listed = set(api_.list_repo_files(HF_REPO, repo_type="dataset"))
    first = LEGACY_FILE in listed
    if first:  # the old single table gives way to the new ones, and the card has to say where they are
        operations.append(CommitOperationDelete(path_in_repo=LEGACY_FILE))
    if (with_card or first or "README.md" not in listed) and CARD_FILE.exists():
        operations.append(CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=str(CARD_FILE)))
    api_.create_commit(repo_id=HF_REPO, repo_type="dataset", operations=operations,
                       commit_message=f"Update San Diego County tables ({today()})")
    log.info(f"Uploaded {len(operations)} files to {HF_REPO}")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the San Diego County Board of Supervisors dataset")
    parser.add_argument("--base", action="store_true", help="read every meeting since 2017, not only the recent ones")
    parser.add_argument("--max-texts", type=int, default=300, help="documents to read in one run")
    parser.add_argument("--out", default=str(OUT_DIR), help="directory to write the tables into")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the tables only")

    out_dir = Path(args.out)
    try:
        tables, counts = build(args.base, args.max_texts, out_dir)
    except Exception as e:
        # A ProxyError here means webapi.legistar.com is not on the network allowlist.
        log.error(f"San Diego County tables not built: {type(e).__name__}: {e}")
        return 1
    write_tables(tables, out_dir)
    pushed = False if args.no_upload else upload(out_dir, args.write_card)
    if pushed:  # the file Capitol World reads for the Board's chamber is made from these tables; never fatal
        try:
            import build_chamber_snapshot
            build_chamber_snapshot.main(["--tables", str(out_dir), "--out", str(out_dir)])
        except Exception as e:
            log.error(f"Chamber file not updated: {type(e).__name__}: {e}")
    items = tables["items"]
    log.info(f"RESULT: sd-county items={len(items)} ordinances={int((items['doc_type'] == 'ordinance').sum())} "
             f"resolutions={int((items['doc_type'] == 'resolution').sum())} with_text={counts['with_text']} "
             f"meetings={len(tables['meetings'])} agenda_items={len(tables['agenda_items'])} votes={len(tables['votes'])} "
             f"meetings_read={counts['meetings_read']} texts_read={counts['read']} texts_waiting={counts['waiting']} "
             f"pdf={counts['pdf']} newest={items['date'].max()} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(main())
