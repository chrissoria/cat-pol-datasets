#!/usr/bin/env python3
"""
Committee-level data for the current Congress, as three tables:

  committees.parquet          one row per committee and subcommittee
  committee_members.parquet   one row per seat on a committee
  committee_meetings.parquet  one row per hearing, markup or business meeting,
                              past and scheduled

Meetings and the committee list come from the Congress.gov API. Membership
comes from the public-domain congress-legislators project, because the API does
not publish rosters.

Usage:
    python3 build_committees.py                 # fetch what is new or changed
    python3 build_committees.py --max-minutes 30
    python3 build_committees.py --full          # ignore the local copy and refetch everything
    python3 build_committees.py --no-upload     # write the tables locally only

The tables are written to ./committees/ and published as the Hugging Face
dataset chrissoria/federal-committees (configs: meetings, committees, members).
"""

import argparse
import json
import logging
import re
import time
from pathlib import Path

import pandas as pd
import requests

import build_federal_bills as bills

log = logging.getLogger("build_committees")

OUT_DIR = bills.SCRIPT_DIR / "committees"
HF_REPO = "chrissoria/federal-committees"
CARD_FILE = bills.SCRIPT_DIR / "README_federal_committees.md"
TABLES = ("committee_meetings.parquet", "committees.parquet", "committee_members.parquet")
MEMBERSHIP_URL = "https://unitedstates.github.io/congress-legislators/committee-membership-current.json"
CHAMBERS = ("house", "senate")


def as_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


# ── Committees ───────────────────────────────────────────────────────────────

def fetch_committee_list(congress=bills.CONGRESS):
    """Every committee and subcommittee of the Congress."""
    rows, offset = [], 0
    while True:
        data = bills.api_get(f"/committee/{congress}", {"limit": 250, "offset": offset})
        page = (data or {}).get("committees", [])
        for item in page:
            parent = item.get("parent") or {}
            rows.append({
                "committee_code": item.get("systemCode", ""),
                "name": item.get("name", ""),
                "chamber": item.get("chamber", ""),
                "committee_type": item.get("committeeTypeCode", ""),
                "parent_code": parent.get("systemCode", ""),
                "parent_name": parent.get("name", ""),
                "n_subcommittees": len(item.get("subcommittees") or []),
                "congress": congress,
                "update_date": item.get("updateDate", ""),
                "url": f"https://www.congress.gov/committee/{item.get('chamber', '').lower()}/{item.get('systemCode', '')}",
            })
        offset += 250
        if len(page) < 250:
            break
    return pd.DataFrame(rows).drop_duplicates("committee_code").reset_index(drop=True)


def system_code(thomas_id):
    """congress-legislators writes HSIF and HSIF02; the API writes hsif00 and hsif02."""
    code = thomas_id.lower()
    return code + "00" if len(code) == 4 else code


def fetch_members():
    """Who sits on each committee. Empty, not fatal, when the file cannot be reached."""
    try:
        response = requests.get(MEMBERSHIP_URL, timeout=30)
        response.raise_for_status()
        membership = response.json()
    except Exception as e:
        log.warning(f"Committee membership unavailable: {e}")
        return pd.DataFrame()
    rows = []
    for thomas_id, seats in membership.items():
        for seat in seats:
            rows.append({
                "committee_code": system_code(thomas_id),
                "bioguide_id": seat.get("bioguide", ""),
                "name": seat.get("name", ""),
                "side": seat.get("party", ""),       # "majority" or "minority"
                "rank": seat.get("rank"),
                "title": seat.get("title", ""),      # Chair, Ranking Member, Vice Chair, Ex Officio, or blank
            })
    return pd.DataFrame(rows)


# ── Meetings ─────────────────────────────────────────────────────────────────

def list_meetings(chamber, congress=bills.CONGRESS):
    """[(event_id, update_date)] for every meeting of one chamber's committees."""
    found, offset = [], 0
    while True:
        data = bills.api_get(f"/committee-meeting/{congress}/{chamber}", {"limit": 250, "offset": offset})
        page = (data or {}).get("committeeMeetings", [])
        found.extend((str(item.get("eventId", "")), item.get("updateDate", "")) for item in page)
        offset += 250
        if len(page) < 250:
            break
    return [entry for entry in found if entry[0]]


def meeting_row(detail, chamber, congress=bills.CONGRESS):
    location = detail.get("location") or {}
    address = location.get("address")
    if isinstance(address, str):  # field hearings carry a JSON string
        try:
            address = json.loads(address)
        except ValueError:
            address = {"building_name": address}
    address = address or {}
    committees = {c.get("systemCode", ""): c.get("name", "") for c in detail.get("committees") or [] if c.get("systemCode")}
    related = detail.get("relatedItems") or {}
    related_bills = [f"{b.get('congress')}-{str(b.get('type', '')).lower()}-{b.get('number')}" for b in related.get("bills") or []]
    documents = [{"name": d.get("name") or d.get("description") or "", "type": d.get("documentType", ""), "url": d.get("url", "")}
                 for d in detail.get("meetingDocuments") or []]
    witnesses = [{"name": w.get("name", ""), "position": w.get("position", ""), "organization": w.get("organization", "")}
                 for w in detail.get("witnesses") or []]
    event_id = str(detail.get("eventId", ""))
    return {
        "event_id": event_id,
        "chamber": detail.get("chamber") or chamber.title(),
        "congress": congress,
        "date": detail.get("date", ""),                      # start, in UTC
        "meeting_type": detail.get("type", ""),
        "status": detail.get("meetingStatus", ""),
        "title": (detail.get("title") or "").strip(),
        "committee_codes": as_json(list(committees)),
        "committee_names": as_json(list(committees.values())),
        "building": location.get("building") or address.get("building_name", ""),
        "room": location.get("room", ""),
        "city": address.get("city", ""),
        "state": address.get("state", ""),
        "bills": as_json(sorted(set(related_bills))),
        "n_nominations": len(related.get("nominations") or []),
        "n_treaties": len(related.get("treaties") or []),
        "witnesses": as_json(witnesses),
        "documents": as_json(documents),
        "n_witness_documents": len(detail.get("witnessDocuments") or []),
        "videos": as_json([v.get("url", "") for v in detail.get("videos") or [] if v.get("url")]),
        "has_transcript": bool(detail.get("hearingTranscript")),
        "update_date": detail.get("updateDate", ""),
        "url": f"https://www.congress.gov/event/{congress}th-congress/{chamber}-event/{event_id}",
    }


def fetch_meetings(existing, max_minutes=None, congress=bills.CONGRESS):
    """Fetch new and changed meetings; keep the rest of `existing` as it is."""
    known = {} if existing.empty else dict(zip(existing["event_id"], existing["update_date"]))
    todo = []
    listed = set()
    for chamber in CHAMBERS:
        for event_id, updated in list_meetings(chamber, congress):
            listed.add(event_id)
            if known.get(event_id) != updated:
                todo.append((chamber, event_id))
    log.info(f"Meetings listed: {len(listed)}; to fetch: {len(todo)}")
    deadline = time.time() + max_minutes * 60 if max_minutes else None
    rows, failed_in_a_row = [], 0
    for index, (chamber, event_id) in enumerate(todo):
        if deadline and time.time() > deadline:
            log.warning(f"Time limit reached with {len(todo) - index} meetings left for the next run")
            break
        data = bills.api_get(f"/committee-meeting/{congress}/{chamber}/{event_id}")
        detail = (data or {}).get("committeeMeeting")
        if not detail:
            failed_in_a_row += 1
            if failed_in_a_row >= 10:
                log.error("Ten meetings in a row failed; stopping")
                break
            continue
        failed_in_a_row = 0
        rows.append(meeting_row(detail, chamber, congress))
        if (index + 1) % 250 == 0:
            log.info(f"Fetched {index + 1}/{len(todo)} meetings")
    fresh = pd.DataFrame(rows)
    if existing.empty:
        combined = fresh
    elif fresh.empty:
        combined = existing
    else:
        combined = pd.concat([existing[~existing["event_id"].isin(fresh["event_id"])], fresh], ignore_index=True)
    if combined.empty:
        return combined, len(rows)
    return combined.sort_values(["date", "event_id"], ascending=[False, True]).reset_index(drop=True), len(rows)


def bootstrap_from_hub(out):
    """Seed a missing local copy of the meetings from the published dataset (fresh clone, cloud run)."""
    target = out / TABLES[0]
    if target.exists():
        return
    try:
        from huggingface_hub import hf_hub_download
        path = hf_hub_download(HF_REPO, f"data/{TABLES[0]}", repo_type="dataset", token=bills.HF_TOKEN)
        pd.read_parquet(path).to_parquet(target, index=False)
        log.info(f"Seeded {target.name} from {HF_REPO}")
    except Exception as e:
        log.info(f"No published meetings to start from ({type(e).__name__}); fetching everything")


def write_problem():
    """Why the token cannot write to the committee dataset, or None if it looks able to."""
    try:
        from huggingface_hub import HfApi
        token = ((HfApi(token=bills.HF_TOKEN).whoami().get("auth") or {}).get("accessToken")) or {}
    except Exception as e:
        return f"Hugging Face rejected the token: {e}"
    if token.get("role") == "read":
        return "the token is read-only"
    scoped = (token.get("fineGrained") or {}).get("scoped")
    if token.get("role") == "fineGrained" and scoped:
        granted = set()
        for scope in scoped:
            if (scope.get("entity") or {}).get("name") in (HF_REPO, HF_REPO.split("/")[0]):
                granted |= set(scope.get("permissions") or [])
        if "repo.write" not in granted:
            return f"the fine-grained token has no write permission on {HF_REPO}"
    return None


def upload(out):
    """Publish the three tables and the dataset card. Returns True when everything went up."""
    if not bills.HF_TOKEN:
        log.error("No HuggingFace token; tables written locally but not uploaded")
        return False
    problem = write_problem()
    if problem:
        log.error(f"Committee tables not uploaded: {problem}")
        return False
    from huggingface_hub import CommitOperationAdd, HfApi
    api = HfApi(token=bills.HF_TOKEN)
    api.create_repo(HF_REPO, repo_type="dataset", private=False, exist_ok=True)
    operations = [CommitOperationAdd(path_in_repo=f"data/{name}", path_or_fileobj=str(out / name))
                  for name in TABLES if (out / name).exists()]
    if CARD_FILE.exists():
        operations.append(CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=str(CARD_FILE)))
    api.create_commit(repo_id=HF_REPO, repo_type="dataset", operations=operations,
                      commit_message=f"Update committee tables ({pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d')})")
    log.info(f"Uploaded {len(operations)} files to {HF_REPO}")
    return True


# Document titles that record what a meeting decided ("ordered to be reported by a recorded vote of 47 YEAS and 2 NAYS").
_OUTCOME = re.compile(r"ordered to be reported|ordered reported|was agreed to|was adopted|not agreed to|was forwarded|"
                      r"was not adopted|failed by|by a recorded vote|by voice vote|by unanimous consent", re.I)


def outcomes(documents_json, limit=10):
    seen, found = set(), []
    for document in json.loads(documents_json):
        name = " ".join((document.get("name") or "").split())
        if name and name not in seen and _OUTCOME.search(name):
            seen.add(name)
            found.append(name[:260])
    return found[:limit]


def app_snapshot(committees, members, meetings, recent=20):
    """What the Capitol World map needs for each full committee: its roster and its latest and coming meetings."""
    now = pd.Timestamp.now(tz="UTC")
    soon = (now - pd.Timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    full = committees[committees["committee_code"].str.endswith("00")]
    subs = committees[~committees["committee_code"].str.endswith("00")]
    by_parent = {}
    for row in meetings.to_dict("records") if not meetings.empty else []:
        codes = json.loads(row["committee_codes"])
        for parent in {code[:4] + "00" for code in codes}:
            by_parent.setdefault(parent, []).append((row, codes))
    out = {}
    for committee in full.to_dict("records"):
        code = committee["committee_code"]
        roster = members[members["committee_code"] == code] if not members.empty else pd.DataFrame()
        held = sorted(by_parent.get(code, []), key=lambda pair: pair[0]["date"], reverse=True)
        upcoming = [pair for pair in held if pair[0]["date"] >= soon and pair[0]["status"] not in ("Canceled", "Postponed")]
        past = [pair for pair in held if pair[0]["date"] < soon and pair[0]["status"] not in ("Canceled", "Postponed")]
        detailed = len(upcoming) + recent
        listed = []
        for position, (row, codes) in enumerate(upcoming[::-1] + past):
            related = json.loads(row["bills"])
            sub = next((c for c in codes if c != code and c[:4] == code[:4]), "")
            if position >= detailed:
                # Older meetings in brief, for the wall calendar in the committee's room. The page address
                # is left out; it follows from the chamber and the id.
                listed.append({"id": row["event_id"], "date": row["date"], "type": row["meeting_type"], "title": row["title"][:110],
                               "n_bills": len(related), "n_witnesses": len(json.loads(row["witnesses"])), "sub": sub, "brief": True})
                continue
            listed.append({
                "id": row["event_id"],
                "date": row["date"],
                "type": row["meeting_type"],
                "title": row["title"][:220],
                "place": " ".join(part for part in (row["room"], row["building"]) if part) or ", ".join(part for part in (row["city"], row["state"]) if part),
                "bills": related[:12],
                "n_bills": len(related),
                "n_witnesses": len(json.loads(row["witnesses"])),
                "outcomes": outcomes(row["documents"]),
                "sub": sub,
                "url": row["url"],
            })
        out[code] = {
            "name": committee["name"],
            "chamber": committee["chamber"],
            "members": [{"id": seat["bioguide_id"], "side": seat["side"], "rank": int(seat["rank"] or 0), "title": seat["title"] or ""}
                        for seat in roster.sort_values(["side", "rank"]).to_dict("records")] if not roster.empty else [],
            "subcommittees": {sub["committee_code"]: sub["name"] for sub in subs[subs["parent_code"] == code].to_dict("records")},
            "n_meetings": len(held),
            "meetings": listed,
        }
    return {"schema": 1, "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "committees": out}


def write_app_snapshot(committees, members, meetings, upload_it):
    """world/committees.json, beside the map's other files in the bills dataset. Never fatal."""
    try:
        target = bills.SCRIPT_DIR / "world" / "committees.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(app_snapshot(committees, members, meetings), ensure_ascii=False, separators=(",", ":")))
        log.info(f"Committee snapshot for the map: {target.stat().st_size // 1024} KB")
        if upload_it and bills.HF_TOKEN:
            from huggingface_hub import HfApi
            HfApi(token=bills.HF_TOKEN).upload_file(path_or_fileobj=str(target), path_in_repo="world/committees.json",
                                                    repo_id=bills.HF_REPO, repo_type="dataset",
                                                    commit_message="Update world/committees.json")
            log.info(f"Uploaded world/committees.json to {bills.HF_REPO}")
    except Exception as e:
        log.warning(f"Committee snapshot for the map not updated: {e}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the committee tables")
    parser.add_argument("--out", default=str(OUT_DIR), help="directory to write the tables into")
    parser.add_argument("--max-minutes", type=float, default=None, help="stop fetching meetings after this long")
    parser.add_argument("--full", action="store_true", help="refetch every meeting")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    meetings_file = out / "committee_meetings.parquet"
    if not args.full:
        bootstrap_from_hub(out)
    existing = pd.read_parquet(meetings_file) if meetings_file.exists() and not args.full else pd.DataFrame()

    committees = fetch_committee_list()
    if committees.empty:
        log.error("The committee list came back empty; nothing written")
        return 1
    members = fetch_members()
    if not members.empty:
        counts = members.groupby("committee_code").size()
        committees["n_members"] = committees["committee_code"].map(counts).fillna(0).astype(int)
        for title, column in (("Chair", "chair_bioguide_id"), ("Ranking Member", "ranking_member_bioguide_id")):
            holders = members[members["title"].fillna("").str.startswith(title)].drop_duplicates("committee_code")
            committees[column] = committees["committee_code"].map(dict(zip(holders["committee_code"], holders["bioguide_id"]))).fillna("")
        members.to_parquet(out / "committee_members.parquet", index=False)
    committees.to_parquet(out / "committees.parquet", index=False)

    meetings, fetched = fetch_meetings(existing, args.max_minutes)
    # Never replace the published meetings with a shorter list: a partial listing is an API hiccup, not news.
    shrank = len(meetings) < 0.98 * len(existing)
    if not meetings.empty and not shrank:
        meetings.to_parquet(meetings_file, index=False)
    pushed = False
    if shrank:
        log.error(f"Meetings fell from {len(existing)} to {len(meetings)}; keeping the previous table and not uploading")
    elif not args.no_upload:
        pushed = upload(out)
    if not shrank:
        write_app_snapshot(committees, members, meetings, upload_it=not args.no_upload)
    log.info(f"RESULT: federal-committees committees={len(committees)} seats={len(members)} meetings={len(meetings)} "
             f"fetched={fetched} pushed={pushed}")
    return 1 if shrank else 0


if __name__ == "__main__":
    raise SystemExit(main())
