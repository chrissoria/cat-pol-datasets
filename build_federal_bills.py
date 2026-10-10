#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-present Christopher Soria <chrissoria@berkeley.edu>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Fetch and update bill metadata for the federal-bills-active dataset.

THIS SCRIPT ONLY HANDLES BILL FETCHING — NOT SUMMARIZATION.
For summarization, run summarize_federal_bills.py separately.

IMPORTANT — ALWAYS USE --incremental:
    As of April 2026, the cache already contains all 14,671 bills from the
    119th Congress. Running without --incremental will re-fetch every single
    bill from the Congress.gov API (thousands of requests, ~15 minutes of
    rate-limited pagination) and gain nothing. There is no reason to do a
    full re-fetch. ALWAYS run with --incremental.

Usage:
    python build_federal_bills.py --incremental          # Standard — fetch only updated bills
    python build_federal_bills.py --incremental --dry-run  # Test without pushing to HuggingFace

Data source: https://api.congress.gov/v3/
HuggingFace repo: chrissoria/federal-bills-active
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
load_dotenv(PROJECT_ROOT / ".env", override=True)
CACHE_FILE = SCRIPT_DIR / ".federal_bills_cache.parquet"
VOTES_CACHE = SCRIPT_DIR / ".federal_votes_cache.parquet"
CHECKPOINT_DIR = SCRIPT_DIR / "checkpoints" / "federal_bills"
LOG_DIR = SCRIPT_DIR / "logs"
HF_REPO = "chrissoria/federal-bills-active"
CONGRESS = 119  # 119th Congress (2025-2026), started Jan 3 2025 (Trump inauguration Jan 20 2025)
SINCE_DATE = "2025-01-20"  # Trump inauguration
API_BASE = "https://api.congress.gov/v3"
API_KEY = os.getenv("CONGRESS_API_KEY") or os.getenv("GOVINFO_API_KEY") or os.getenv("DATA_GOV_API_KEY") or "DEMO_KEY"
HF_TOKEN = os.getenv("CATLLM_HUGGINGFACE_TOKEN") or os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_TOKEN")
VOTES_REPO = "chrissoria/federal-votes"

LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "federal_bills.log", mode="a"),
    ],
)
log = logging.getLogger(__name__)


VOTE_SUMMARY_COLS = [
    "republican_yeas",
    "democrat_yeas",
    "republican_nays",
    "democrat_nays",
    "total_yeas",
    "total_nays",
    "republican_support_pct",
    "democrat_support_pct",
    "is_bipartisan",
]

LEADING_COL_ORDER = [
    "date_last_action",
    "date_introduced",
    "title",
    "text",
    "policy_area",
    "summary_bullets",
    "short_summary",
    "sponsor_full_name",
    "sponsor_party",
    "sponsor_state",
    "num_cosponsors",
    "chamber_of_origin",
    *VOTE_SUMMARY_COLS,
]


API_FAILURES = 0  # requests that failed after all retries; the fetch loop watches this


def api_get(endpoint, params=None, retries=3):
    """Make a Congress.gov API request with retry logic."""
    global API_FAILURES
    params = params or {}
    params["api_key"] = API_KEY
    params["format"] = "json"

    for attempt in range(retries):
        try:
            resp = requests.get(f"{API_BASE}{endpoint}", params=params, timeout=30)
            if resp.status_code == 429:
                wait = 2 ** (attempt + 1)
                log.warning(f"Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            if attempt < retries - 1:
                time.sleep(2)
                continue
            log.error(f"API request failed: {endpoint} — {e}")
            API_FAILURES += 1
            return None
    API_FAILURES += 1
    return None


def fetch_bill_list(congress=CONGRESS, limit=250, offset=0, from_date=None):
    """Fetch a page of bills from Congress.gov."""
    params = {"limit": limit, "offset": offset}
    if from_date:
        params["fromDateTime"] = f"{from_date}T00:00:00Z"
    data = api_get(f"/bill/{congress}", params=params)
    if data and "bills" in data:
        return data["bills"], data.get("pagination", {}).get("count", 0)
    return [], 0


def fetch_bill_detail(congress, bill_type, bill_number):
    """Fetch detailed info for a single bill."""
    data = api_get(f"/bill/{congress}/{bill_type.lower()}/{bill_number}")
    if data and "bill" in data:
        return data["bill"]
    return None


def fetch_bill_text(congress, bill_type, bill_number):
    """Fetch the latest text version of a bill."""
    data = api_get(f"/bill/{congress}/{bill_type.lower()}/{bill_number}/text")
    if data and "textVersions" in data:
        versions = data["textVersions"]
        if versions:
            # Get the latest version
            latest = versions[0]
            for fmt in latest.get("formats", []):
                if fmt.get("type") == "Formatted Text":
                    clean = fetch_formatted_text(fmt["url"])
                    if clean:
                        return clean, latest.get("type", "")
    return "", ""


def fetch_formatted_text(url):
    """Download a bill's formatted text, falling back to GovInfo.

    www.congress.gov can refuse requests from cloud IP addresses. GovInfo serves
    the same file by package id (the file name) with the same API key.
    """
    import re
    candidates = [url]
    package_id = url.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    if package_id.startswith("BILLS-"):
        candidates.append(f"https://api.govinfo.gov/packages/{package_id}/htm")
    for candidate in candidates:
        try:
            resp = requests.get(candidate, timeout=30, params={"api_key": API_KEY})
        except requests.RequestException:
            continue
        # A block page can come back as 200, so require the text wrapper.
        if resp.status_code == 200 and "<pre>" in resp.text:
            return re.sub(r'<html><body><pre>|</pre></body></html>', '', resp.text).strip()
    return ""


def fetch_bill_subjects(congress, bill_type, bill_number):
    """Fetch subjects/topics for a bill."""
    data = api_get(f"/bill/{congress}/{bill_type.lower()}/{bill_number}/subjects")
    if data and "subjects" in data:
        subjects = data["subjects"]
        if "legislativeSubjects" in subjects:
            return [s["name"] for s in subjects["legislativeSubjects"]]
    return []


def fetch_bill_actions(congress, bill_type, bill_number):
    """Fetch action history for a bill."""
    data = api_get(f"/bill/{congress}/{bill_type.lower()}/{bill_number}/actions",
                   params={"limit": 100})
    if data and "actions" in data:
        return data["actions"]
    return []


def determine_status(actions):
    """Determine bill status from its action history."""
    if not actions:
        return "Introduced"

    action_texts = [a.get("text", "").lower() for a in actions]

    for text in action_texts:
        if "became public law" in text or "signed by president" in text:
            return "Signed into Law"
        if "passed/agreed to in senate" in text and "passed/agreed to in house" in text:
            return "Passed Both Chambers"
        if "presented to president" in text or "sent to president" in text:
            return "Sent to President"
        if "vetoed" in text:
            return "Vetoed"

    for text in action_texts:
        if "passed/agreed to in senate" in text:
            return "Passed Senate"
        if "passed/agreed to in house" in text or "passed house" in text:
            return "Passed House"
        if "cloture" in text:
            return "Senate Floor"
        if "placed on" in text and "calendar" in text:
            return "Calendared"
        if "reported by" in text or "ordered to be reported" in text:
            return "Reported from Committee"

    for text in action_texts:
        if "referred to" in text and "committee" in text:
            return "In Committee"

    return "Introduced"


# ── Bill location (where a bill physically sits in the process) ───────────────
# `status` above is kept as published. `location_*` is a separate, stricter reading
# of the action history, used by the Capitol World map (build_world_snapshot.py).

LOCATION_KINDS = (
    "hopper",         # introduced, not yet referred
    "committee",      # referred to, or being worked on by, a committee
    "referral_desk",  # referred, but the committee could not be identified
    "calendar",       # placed on a chamber calendar
    "floor",          # under consideration on the floor
    "other_chamber",  # passed one chamber; received or waiting in the other
    "conference",     # the chambers are resolving differences
    "president",      # passed both chambers; at or on its way to the President
    "law",            # signed or enacted
    "vetoed",
    "adopted",        # a simple or concurrent resolution that was agreed to
)
RECENT_ACTIONS_KEPT = 15
_PASSED = re.compile(
    r"passed/agreed to in (house|senate)|passed (house|senate)|on passage passed|"
    r"agreed to in (house|senate)|resolution agreed to|considered, and agreed to|"
    r"on agreeing to the resolution agreed to|on motion to suspend the rules and (pass|agree)[^.]*agreed to",
    re.I,
)
_TRANSPARENT = re.compile(r"^message on (house|senate) action sent|motion to reconsider|^pursuant to|^sponsor introductory remarks", re.I)
_COMMITTEE_NAME = re.compile(r"(?:Committee on|Subcommittee on) (?:the )?([A-Z][A-Za-z,'\- ]+?)(?:\.|,? and in addition| by | for a period|$)")


def _action_chamber(action):
    """Which chamber took an action: 'House', 'Senate' or ''."""
    source = ((action.get("sourceSystem") or {}).get("name") or "").lower()
    code = str(action.get("actionCode") or "")
    if source.startswith("house") or code.startswith("H"):
        return "House"
    if source == "senate" or code.startswith("S"):
        return "Senate"
    text = action.get("text") or ""
    in_senate, in_house = "Senate" in text, "House" in text
    if in_senate != in_house:
        return "Senate" if in_senate else "House"
    return ""


def _ordered_committee_codes(committees, text):
    """Parent-committee codes for an action, primary first.

    The API does not list the primary committee first, but the action text names
    it first ("Referred to the Committee on Energy and Commerce, and in addition to ...").
    """
    low = text.lower()
    ranked = []
    for index, committee in enumerate(committees or []):
        code = committee.get("systemCode") or ""
        if not code:
            continue
        name = re.sub(r"\b(house|senate|committee|subcommittee|on|the)\b", " ", (committee.get("name") or "").lower())
        name = re.sub(r"\s+", " ", name).strip()
        position = low.find(name) if name else -1
        ranked.append((position if position >= 0 else 10_000 + index, code[:4] + "00"))
    return list(dict.fromkeys(code for _, code in sorted(ranked)))


def compact_actions(actions, keep=None):
    """Reduce API action items to the fields the map needs, newest first, without duplicates.

    Congress.gov lists most actions twice, once from the chamber and once from the
    Library of Congress, and lists a referral to several committees once per
    committee with the same text. Copies are merged into one item.
    """
    seen, out, raw_committees = {}, [], []
    for action in actions or []:
        text = (action.get("text") or "").strip()
        key = (action.get("actionDate") or "", re.sub(r"\W+", "", text.lower()))
        chamber = _action_chamber(action)
        if key in seen:
            kept = out[seen[key]]
            if not kept["chamber"] and chamber:
                kept["chamber"] = chamber
            raw_committees[seen[key]].extend(action.get("committees") or [])
            continue
        seen[key] = len(out)
        raw_committees.append(list(action.get("committees") or []))
        out.append({
            "date": action.get("actionDate") or "",
            "type": action.get("type") or "",
            "code": str(action.get("actionCode") or ""),
            "committees": [],
            "chamber": chamber,
            "text": text,
        })
    for item, committees in zip(out, raw_committees):
        item["committees"] = _ordered_committee_codes(committees, item["text"])
    return out[:keep] if keep else out


def classify_location(actions, bill_type="", origin_chamber=""):
    """Say where a bill sits, from its compact action list (newest first).

    Returns {"kind", "chamber", "committee_code", "committee_name", "extra_referrals"}.
    `kind` is one of LOCATION_KINDS, or "" when the list gives no answer.
    """
    bill_type = (bill_type or "").upper()
    resolution_one_chamber = bill_type in ("HRES", "SRES")
    resolution_both = bill_type in ("HCONRES", "SCONRES")
    other = {"House": "Senate", "Senate": "House"}

    def result(kind, chamber="", committees=(), name=""):
        committees = list(dict.fromkeys(committees))
        return {
            "kind": kind,
            "chamber": chamber,
            "committee_code": committees[0] if committees else "",
            "committee_name": name,
            "extra_referrals": max(len(committees) - 1, 0),
        }

    for index, action in enumerate(actions or []):
        text = action.get("text") or ""
        low = text.lower()
        kind = action.get("type") or ""
        chamber = action.get("chamber") or ""
        if _TRANSPARENT.search(text):
            continue
        if "became public law" in low or "signed by president" in low or "became private law" in low:
            return result("law")
        if kind == "Veto" or "vetoed by president" in low:
            return result("vetoed")
        if "presented to president" in low:
            return result("president")
        if kind == "ResolvingDifferences" or "conference report" in low or "conferees" in low or "resolving differences" in low:
            return result("conference", chamber)
        if _PASSED.search(text):
            if resolution_one_chamber:
                return result("adopted", chamber)
            if not chamber or not origin_chamber or chamber == origin_chamber:
                return result("other_chamber", other.get(chamber or origin_chamber, ""))
            if resolution_both:
                return result("adopted", chamber)
            if "with an amendment" in low or "with amendments" in low or "as amended" in low:
                return result("conference", origin_chamber)
            return result("president")
        if kind == "Calendars" or ("placed on" in low and "calendar" in low):
            return result("calendar", chamber)
        if kind == "Discharge":
            return result("floor", chamber)
        if kind == "Committee" or "referred to" in low or "rereferred to" in low:
            committees = action.get("committees") or []
            if not committees:
                # A subcommittee referral often names no committee code; the bill is
                # still with the committee that an earlier action in this chamber named.
                for earlier in actions[index + 1:]:
                    same_chamber = not chamber or not earlier.get("chamber") or earlier["chamber"] == chamber
                    if earlier.get("committees") and same_chamber:
                        committees = earlier["committees"]
                        break
            found = _COMMITTEE_NAME.search(text)
            name = found.group(1).strip() if found else ""
            if not chamber and committees:
                chamber = "House" if committees[0].startswith("h") else "Senate"
            if committees or name:
                return result("committee", chamber, committees, name)
            return result("referral_desk", chamber)
        if low.startswith("received in the ") or low.startswith("held at the desk"):
            return result("other_chamber", chamber)
        if kind == "Floor":
            return result("floor", chamber)
        if low.startswith("introduced in") or low.startswith("submitted in"):
            return result("hopper", chamber or origin_chamber)
    return result("")


def build_bill_row(bill_summary, detail, text_content, text_version, subjects, actions):
    """Build a row dict mirroring the federal_laws schema + status columns."""
    sponsor = detail.get("sponsors", [{}])[0] if detail.get("sponsors") else {}
    policy_area = detail.get("policyArea", {})
    latest_action = detail.get("latestAction", {})

    bill_type = bill_summary.get("type", "HR").lower()
    bill_number = bill_summary.get("number", "")
    origin_chamber = detail.get("originChamber", bill_summary.get("originChamber", ""))
    history = compact_actions(actions)
    location = classify_location(history, bill_type, origin_chamber)

    return {
        # Dates
        "date_last_action": latest_action.get("actionDate", ""),
        "date_introduced": detail.get("introducedDate", ""),
        # The listing's updateDate counts text changes, so store the later of the two
        # detail timestamps; otherwise a text-only update is re-fetched on every run.
        "date_updated": max(str(detail.get("updateDateIncludingText") or ""), str(detail.get("updateDate") or ""))
                        or bill_summary.get("updateDate", ""),
        # Bill identity
        "bill_type": bill_summary.get("type", ""),
        "bill_number": bill_number,
        "congress": str(detail.get("congress", CONGRESS)),
        "title": detail.get("title", bill_summary.get("title", "")),
        "status": determine_status(actions),
        "last_action_text": latest_action.get("text", ""),
        # Sponsor
        "sponsor_full_name": sponsor.get("fullName", ""),
        "sponsor_party": sponsor.get("party", ""),
        "sponsor_state": sponsor.get("state", ""),
        "num_cosponsors": detail.get("cosponsors", {}).get("count", 0),
        "chamber_of_origin": detail.get("originChamber", bill_summary.get("originChamber", "")),
        # Classification
        "policy_area": policy_area.get("name", "") if isinstance(policy_area, dict) else "",
        "subjects": "; ".join(subjects) if subjects else "",
        # Vote data (populated later)
        "republican_yeas": None,
        "democrat_yeas": None,
        "republican_nays": None,
        "democrat_nays": None,
        "total_yeas": None,
        "total_nays": None,
        "republican_support_pct": None,
        "democrat_support_pct": None,
        "is_bipartisan": None,
        # Text and metadata
        "text": text_content,
        "bill_text_version": text_version,
        "url": detail.get("legislationUrl", f"https://www.congress.gov/bill/{CONGRESS}th-congress/{bill_type}-bill/{bill_number}"),
        "doc_type": "bill",
        "public_law_number": "",
        "package_id": "",
        "pages": "",
        "source": "federal_bills_active",
        # Map fields (see classify_location)
        "sponsor_bioguide_id": sponsor.get("bioguideId", ""),
        "recent_actions": json.dumps(history[:RECENT_ACTIONS_KEPT], ensure_ascii=False),
        "location_kind": location["kind"],
        "location_chamber": location["chamber"],
        "location_committee_code": location["committee_code"],
        "location_committee_name": location["committee_name"],
    }


def bootstrap_cache_from_hub(repo_id, cache_file):
    """Seed a missing local cache from the published dataset (fresh clone, cloud run)."""
    if cache_file.exists():
        return
    try:
        from datasets import load_dataset
        log.info(f"No local {cache_file.name}; downloading {repo_id}")
        df = load_dataset(repo_id, split="train", token=HF_TOKEN).to_pandas()
        df.to_parquet(cache_file, index=False)
        log.info(f"Seeded {cache_file.name} with {len(df)} rows from {repo_id}")
    except Exception as e:
        log.error(f"Could not download {repo_id}: {e}")


def select_bills_to_fetch(all_bills, existing, max_bills=None):
    """Pick the bills whose listing is newer than the cached copy.

    Each bill is compared with its own cached row, so a capped or interrupted
    run leaves the rest for the next run. The listing gives a date and the cache
    a timestamp, so both are compared as dates. A bill updated today or
    yesterday is fetched again even when the dates match, because it may have
    changed after that day's fetch.
    """
    cached = {
        (bill_type, str(number)): str(updated or "")[:10]
        for bill_type, number, updated in zip(
            existing["bill_type"], existing["bill_number"], existing["date_updated"]
        )
    }
    newest_cached = max(cached.values(), default="")
    recent_cutoff = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    updated, new, retry = [], [], []
    for bill in all_bills:
        key = (bill.get("type", ""), str(bill.get("number", "")))
        listed = str(bill.get("updateDate", ""))[:10]
        if key not in cached:
            # Missing and older than the newest cached update: an earlier run
            # fetched it and dropped it because it had no text yet.
            (retry if listed < newest_cached else new).append(bill)
        elif listed > cached[key] or (listed == cached[key] and listed >= recent_cutoff):
            updated.append(bill)

    def by_date(bill):
        return str(bill.get("updateDate", ""))

    ordered = sorted(updated + new, key=by_date) + sorted(retry, key=by_date, reverse=True)
    log.info(f"Incremental: {len(updated)} updated, {len(new)} new, {len(retry)} retries without text")
    if max_bills and len(ordered) > max_bills:
        log.info(f"Capped at {max_bills} bills; {len(ordered) - max_bills} left for the next run")
        ordered = ordered[:max_bills]
    return ordered


def hf_write_problem():
    """Return why the token cannot write to the dataset, or None if it looks able to.

    Checked before fetching, because a push refused at the end wastes the whole run.
    Only a clear answer stops the run; an unfamiliar response lets it proceed.
    """
    try:
        from huggingface_hub import HfApi
        info = HfApi(token=HF_TOKEN).whoami()
    except Exception as e:
        return f"Hugging Face rejected the token: {e}"
    token = ((info.get("auth") or {}).get("accessToken")) or {}
    if token.get("role") == "read":
        return "the token is read-only"
    scoped = (token.get("fineGrained") or {}).get("scoped")
    if token.get("role") == "fineGrained" and scoped:
        owner = HF_REPO.split("/")[0]
        granted = set()
        for scope in scoped:
            entity = scope.get("entity") or {}
            if entity.get("name") in (HF_REPO, owner):
                granted |= set(scope.get("permissions") or [])
        if "repo.write" not in granted:
            return (f"the fine-grained token has no write permission on {HF_REPO} "
                    f"(it has: {sorted(granted) or 'nothing for this repo'})")
    return None


def load_cache():
    """Load existing cached data."""
    bootstrap_cache_from_hub(HF_REPO, CACHE_FILE)
    if CACHE_FILE.exists():
        df = pd.read_parquet(CACHE_FILE)
        if "summary_threads" in df.columns and "short_summary" not in df.columns:
            df = df.rename(columns={"summary_threads": "short_summary"})
        if "short_title" in df.columns:
            df = df.drop(columns=["short_title"])
        return df
    return pd.DataFrame()


def save_cache(df):
    """Save data to local cache."""
    df.to_parquet(CACHE_FILE, index=False)


def order_dataset_columns(df):
    """Move the highest-value fields to the front while preserving the rest."""
    if "summary_threads" in df.columns and "short_summary" not in df.columns:
        df = df.rename(columns={"summary_threads": "short_summary"})
    if "short_title" in df.columns:
        df = df.drop(columns=["short_title"])
    leading = [col for col in LEADING_COL_ORDER if col in df.columns]
    trailing = [col for col in df.columns if col not in leading]
    return df[leading + trailing]


def vote_type_priority(vote_type):
    """Rank roll calls by how representative they are for a bill-level summary."""
    vote_type = (vote_type or "").strip()
    priorities = {
        "On Passage": 0,
        "On Motion to Suspend the Rules and Pass": 1,
        "On Motion to Suspend the Rules and Pass, as Amended": 2,
        "On Passage of the Bill": 3,
        "On the Joint Resolution": 4,
        "On the Concurrent Resolution": 5,
        "On Agreeing to the Resolution": 6,
        "On Agreeing to the Resolution, as Amended": 7,
        "Passage, Objections of the President To The Contrary Notwithstanding": 8,
        "On Motion to Concur in the Senate Amendment": 9,
        "On Motion to Recede and Concur in the Senate Amendment": 10,
        "On the Conference Report": 11,
        "On the Conference Report, as Amended": 12,
        "On the Motion": 20,
        "On the Motion to Proceed": 21,
        "On Cloture on the Motion to Proceed": 22,
        "On the Cloture Motion": 23,
        "On Motion to Recommit": 24,
        "On Motion to Commit with Instructions": 25,
        "On Ordering the Previous Question": 26,
    }
    return priorities.get(vote_type, 50)


def build_vote_aggregates():
    """Build bill-level vote summary columns from the individual federal votes cache."""
    bootstrap_cache_from_hub(VOTES_REPO, VOTES_CACHE)
    if not VOTES_CACHE.exists():
        log.warning("Votes cache not found; skipping vote aggregation")
        return pd.DataFrame()

    votes = pd.read_parquet(VOTES_CACHE)
    if votes.empty:
        log.warning("Votes cache is empty; skipping vote aggregation")
        return pd.DataFrame()

    votes = votes.copy()
    votes["bill_number"] = votes["bill_number"].astype(str)
    votes["congress"] = votes["congress"].astype(str)
    votes["vote_type"] = votes["vote_type"].fillna("")
    votes["date_of_vote"] = votes["date_of_vote"].fillna("")
    votes["roll_call_number"] = pd.to_numeric(votes["roll_call_number"], errors="coerce")

    rollup_keys = ["bill_type", "bill_number", "congress", "date_of_vote", "chamber", "roll_call_number", "vote_type"]

    def count_votes(frame, party, choices):
        mask = frame["party"].eq(party) & frame["vote"].isin(choices)
        return int(mask.sum())

    rows = []
    for keys, frame in votes.groupby(rollup_keys, dropna=False):
        bill_type, bill_number, congress, date_of_vote, chamber, roll_call_number, vote_type = keys
        republican_yeas = count_votes(frame, "R", {"Yea", "Aye"})
        democrat_yeas = count_votes(frame, "D", {"Yea", "Aye"})
        republican_nays = count_votes(frame, "R", {"Nay", "No"})
        democrat_nays = count_votes(frame, "D", {"Nay", "No"})

        republican_total = republican_yeas + republican_nays
        democrat_total = democrat_yeas + democrat_nays

        rows.append({
            "bill_type": bill_type,
            "bill_number": bill_number,
            "congress": congress,
            "date_of_vote": date_of_vote,
            "chamber": chamber,
            "roll_call_number": roll_call_number,
            "vote_type": vote_type,
            "republican_yeas": republican_yeas,
            "democrat_yeas": democrat_yeas,
            "republican_nays": republican_nays,
            "democrat_nays": democrat_nays,
            "total_yeas": republican_yeas + democrat_yeas + int((frame["party"].eq("I") & frame["vote"].isin({"Yea", "Aye"})).sum()),
            "total_nays": republican_nays + democrat_nays + int((frame["party"].eq("I") & frame["vote"].isin({"Nay", "No"})).sum()),
            "republican_support_pct": round((100.0 * republican_yeas / republican_total), 1) if republican_total else None,
            "democrat_support_pct": round((100.0 * democrat_yeas / democrat_total), 1) if democrat_total else None,
            "is_bipartisan": (100.0 * republican_yeas / republican_total) > 10.0 and (100.0 * democrat_yeas / democrat_total) > 10.0
                if republican_total and democrat_total else None,
        })

    if not rows:
        log.warning("No vote rows available for aggregation")
        return pd.DataFrame()

    rollups = pd.DataFrame(rows)
    rollups["_priority"] = rollups["vote_type"].map(vote_type_priority)
    rollups = rollups.sort_values(
        ["bill_type", "bill_number", "congress", "_priority", "date_of_vote", "roll_call_number"],
        ascending=[True, True, True, True, False, False],
        na_position="last",
    )

    best = rollups.drop_duplicates(subset=["bill_type", "bill_number", "congress"], keep="first").copy()
    counts_by_priority = best["_priority"].value_counts().sort_index().to_dict()
    log.info(f"Aggregated vote summaries for {len(best)} bills from votes cache")
    log.info(f"Selected vote priorities: {counts_by_priority}")

    return best.drop(columns=["_priority", "date_of_vote", "chamber", "roll_call_number", "vote_type"])


def push_to_hf(df):
    """Push dataset to HuggingFace."""
    from datasets import Dataset
    if not HF_TOKEN:
        log.error("No HuggingFace token found. Set CATLLM_HUGGINGFACE_TOKEN, HUGGINGFACE_TOKEN or HF_TOKEN")
        return False
    ds = Dataset.from_pandas(df)
    ds.push_to_hub(HF_REPO, token=HF_TOKEN, private=False)
    log.info(f"Pushed {len(df)} rows to https://huggingface.co/datasets/{HF_REPO}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Build federal-bills-active dataset")
    parser.add_argument("--incremental", action="store_true",
                        help="Only fetch recently updated bills")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't push to HuggingFace")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max bills to fetch (for testing)")
    parser.add_argument("--max-bills", type=int, default=None,
                        help="With --incremental: fetch at most this many bills, oldest update first; "
                             "the rest wait for the next run")
    parser.add_argument("--max-minutes", type=float, default=None,
                        help="Stop fetching after this many minutes and publish what was fetched; "
                             "the rest wait for the next run")
    args = parser.parse_args()
    started = time.monotonic()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    log.info("=" * 60)
    log.info(f"Federal Bills builder starting (congress={CONGRESS})")

    existing = load_cache()
    existing_bills = set()
    if not existing.empty and "bill_number" in existing.columns and "bill_type" in existing.columns:
        existing_bills = set(zip(existing["bill_type"], existing["bill_number"]))
    log.info(f"Existing cache: {len(existing)} bills")

    if args.incremental and existing.empty:
        # An empty cache would turn this into a full rebuild whose push drops every summary.
        log.error("--incremental found no cache and could not download the dataset; stopping")
        sys.exit(1)
    if not args.dry_run and not HF_TOKEN:
        log.error("No HuggingFace token found; stopping before fetching anything")
        sys.exit(1)
    if not args.dry_run:
        problem = hf_write_problem()
        if problem:
            log.error(f"Cannot publish: {problem}. Stopping before fetching anything.")
            sys.exit(1)

    # Fetch bill listing from Congress.gov
    all_bills = []
    offset = 0
    page_size = 250
    total = None

    while True:
        bills, count = fetch_bill_list(congress=CONGRESS, limit=page_size, offset=offset)
        if total is None:
            total = count
            log.info(f"Total bills in {CONGRESS}th Congress: {total}")

        if not bills:
            break

        all_bills.extend(bills)
        offset += page_size
        log.info(f"Fetched {len(all_bills)}/{total} bill listings...")

        if args.limit and len(all_bills) >= args.limit:
            all_bills = all_bills[:args.limit]
            break

        if offset >= total:
            break

        time.sleep(0.5)  # Rate limiting

    log.info(f"Total bill listings: {len(all_bills)}")

    # Filter to bills needing detail fetch
    if args.incremental and not existing.empty:
        bills_to_fetch = select_bills_to_fetch(all_bills, existing, args.max_bills)
    else:
        bills_to_fetch = all_bills

    # Fetch details for each bill
    rows = []
    failed_in_a_row = 0
    for i, bill in enumerate(bills_to_fetch):
        bill_type = bill.get("type", "HR").lower()
        bill_number = bill.get("number", "")

        if i > 0 and i % 50 == 0:
            log.info(f"Processing {i}/{len(bills_to_fetch)}...")

        if args.max_minutes and (time.monotonic() - started) / 60 >= args.max_minutes:
            log.warning(f"Time budget of {args.max_minutes:g} minutes reached after {i} bills; "
                        f"{len(bills_to_fetch) - i} left for the next run")
            break
        if failed_in_a_row >= 10:
            log.error(f"10 bills in a row failed; Congress.gov looks down. Stopping after {i} bills; "
                      f"{len(bills_to_fetch) - i} left for the next run")
            break

        failures_before = API_FAILURES
        detail = fetch_bill_detail(CONGRESS, bill_type, bill_number)
        if not detail:
            failed_in_a_row += 1
            continue

        time.sleep(0.3)

        text_content, text_version = fetch_bill_text(CONGRESS, bill_type, bill_number)
        time.sleep(0.3)

        subjects = fetch_bill_subjects(CONGRESS, bill_type, bill_number)
        time.sleep(0.3)

        actions = fetch_bill_actions(CONGRESS, bill_type, bill_number)
        time.sleep(0.3)

        if API_FAILURES > failures_before:
            # A failed text, subjects or actions call would store a wrong status or
            # empty fields under a fresh update date. Leave the bill for the next run.
            log.warning(f"Skipping {bill_type.upper()} {bill_number}: a request failed; it will be retried")
            failed_in_a_row += 1
            continue
        failed_in_a_row = 0

        row = build_bill_row(bill, detail, text_content, text_version, subjects, actions)
        rows.append(row)

        # Checkpoint every 100 bills
        if len(rows) % 100 == 0:
            checkpoint_df = pd.DataFrame(rows)
            checkpoint_df.to_parquet(CHECKPOINT_DIR / f"checkpoint_{len(rows)}.parquet", index=False)
            log.info(f"Checkpoint: {len(rows)} bills processed")

    if not rows:
        log.info("No new bills to process.")
        log.info(f"RESULT: federal-bills fetched=0 total={len(existing)} pushed=False")
        return

    new_df = pd.DataFrame(rows)
    log.info(f"Fetched details for {len(new_df)} bills")

    # Merge with existing data
    if not existing.empty:
        # A failed text download must not erase text the dataset already has.
        old_text = existing.set_index(["bill_type", "bill_number"])[["text", "bill_text_version"]]
        old_text = old_text[~old_text.index.duplicated(keep="last")]
        keys = pd.MultiIndex.from_frame(new_df[["bill_type", "bill_number"]].astype(str))
        known = keys.isin(old_text.index)
        lost_text = known & (new_df["text"].fillna("").astype(str).str.strip() == "").to_numpy()
        if known.sum() >= 20 and lost_text.sum() > 0.5 * known.sum():
            log.error(f"{lost_text.sum()} of {known.sum()} updated bills came back without text; "
                      "the text source looks blocked. Nothing saved or pushed.")
            sys.exit(1)
        if lost_text.any():
            new_df.loc[lost_text, ["text", "bill_text_version"]] = old_text.loc[keys[lost_text]].to_numpy()
            log.warning(f"Kept the existing text for {lost_text.sum()} bills whose text download failed")

        # Preserve existing summaries before merge — the API-fetched row has no
        # summary fields, so drop_duplicates(keep="last") would otherwise wipe them.
        summary_cols = ["short_summary", "summary_bullets"]
        existing_summaries = existing.set_index(["bill_type", "bill_number"])[
            [c for c in summary_cols if c in existing.columns]
        ]
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined = combined.drop_duplicates(
            subset=["bill_type", "bill_number"], keep="last"
        )
        combined = combined.set_index(["bill_type", "bill_number"])
        for col in summary_cols:
            if col in existing_summaries.columns and col in combined.columns:
                mask = combined[col].isna()
                combined.loc[mask, col] = existing_summaries[col]
        combined = combined.reset_index()
    else:
        combined = new_df

    vote_rollups = build_vote_aggregates()
    if not vote_rollups.empty:
        combined["bill_number"] = combined["bill_number"].astype(str)
        combined["congress"] = combined["congress"].astype(str)
        combined = combined.drop(columns=[c for c in VOTE_SUMMARY_COLS if c in combined.columns])
        combined = combined.merge(
            vote_rollups,
            on=["bill_type", "bill_number", "congress"],
            how="left",
        )

    # Normalize column name: API may use either variant
    if "last_action_date" in combined.columns and "date_last_action" not in combined.columns:
        combined = combined.rename(columns={"last_action_date": "date_last_action"})
    if "pdf_url" in combined.columns:
        combined = combined.drop(columns=["pdf_url"])
    if "summary_report" in combined.columns:
        combined = combined.drop(columns=["summary_report"])
    if "summary_threads" in combined.columns and "short_summary" not in combined.columns:
        combined = combined.rename(columns={"summary_threads": "short_summary"})
    if "short_title" in combined.columns:
        combined = combined.drop(columns=["short_title"])
    if "text" in combined.columns:
        before = len(combined)
        combined = combined[combined["text"].fillna("").astype(str).str.strip() != ""].copy()
        dropped = before - len(combined)
        if dropped:
            log.info(f"Dropped {dropped} bills with empty text")
    combined = combined.sort_values("date_last_action", ascending=False).reset_index(drop=True)
    combined = order_dataset_columns(combined)

    # Status summary
    if "status" in combined.columns:
        log.info("Status breakdown:")
        for status, count in combined["status"].value_counts().items():
            log.info(f"  {status}: {count}")

    # Never publish a dataset that lost rows or summaries.
    if not existing.empty:
        def filled(df, col):
            return int((df[col].fillna("").astype(str).str.strip() != "").sum()) if col in df.columns else 0

        if len(combined) < 0.98 * len(existing):
            log.error(f"Row count fell from {len(existing)} to {len(combined)}. Nothing saved or pushed.")
            sys.exit(1)
        for col in ("short_summary", "summary_bullets"):
            if filled(combined, col) < 0.98 * filled(existing, col):
                log.error(f"{col} fell from {filled(existing, col)} to {filled(combined, col)} rows. "
                          "Nothing saved or pushed.")
                sys.exit(1)

    # Summarization is handled separately — run summarize_federal_bills.py
    save_cache(combined)
    log.info(f"Cached {len(combined)} total bills")

    pushed = False
    if not args.dry_run:
        try:
            pushed = push_to_hf(combined)
        except Exception as e:
            log.error(f"HuggingFace push failed: {e}")
        if not pushed:
            log.info(f"RESULT: federal-bills fetched={len(new_df)} total={len(combined)} pushed=False")
            sys.exit(1)
    else:
        log.info("Dry run — skipping HuggingFace push")

    if pushed:
        # The map snapshot is a by-product; it must never fail the dataset run.
        try:
            import build_world_snapshot
            build_world_snapshot.main([])
        except Exception as e:
            log.warning(f"World snapshot not updated: {e}")

    log.info(f"RESULT: federal-bills fetched={len(new_df)} total={len(combined)} pushed={pushed}")
    log.info("Done.")


if __name__ == "__main__":
    main()
