#!/usr/bin/env python3
"""
Build chrissoria/executive-branch-roster: who holds the senior posts of the
sitting administration.

Two sources, kept apart in the `source` column:

  - Cabinet and cabinet-level posts come from the Senate's nominations, through
    the Congress.gov API. That is the official record of who was confirmed to
    what, when, and by what vote. The latest person confirmed to a post holds
    it; whoever was confirmed before is listed as a former holder, with the
    successor's confirmation date as the day they were replaced.
  - Senior White House posts (chief of staff, counselors, advisers) are not
    confirmed by the Senate, so they come from Wikidata, which is edited by
    volunteers. Only a fixed list of posts is read, only for real people who
    are United States citizens, and only where a start date within this
    presidency is recorded. Treat these rows as less authoritative.

Neither source records an acting official, and a resignation shows up only
when a successor is confirmed.

Writes the table and world/roster.json (for Capitol World's White House map)
and publishes both. Meant to run weekly.

Usage:
    python build_executive_roster.py
    python build_executive_roster.py --no-upload
"""

import argparse
import json
import logging
import re
import sys
from datetime import date

import pandas as pd
import requests

import build_federal_bills as bills

log = logging.getLogger(__name__)

HF_REPO = "chrissoria/executive-branch-roster"
OUT_DIR = bills.SCRIPT_DIR / "roster"
CARD_FILE = bills.SCRIPT_DIR / "README_executive_roster.md"
SPARQL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "cat-pol-dataset-builder/1.0 (academic research)"}
NOMINATIONS = "Congress.gov nominations"
WIKIDATA = "Wikidata"

# (what the nomination says after "to be", the post's name, its group, the department's code on the map)
CABINET = [
    (r"Secretary of State", "Secretary of State", "Cabinet", "state"),
    (r"Secretary of the Treasury", "Secretary of the Treasury", "Cabinet", "treasury"),
    (r"Secretary of (?:Defense|War)", "Secretary of Defense", "Cabinet", "defense"),
    (r"Attorney General", "Attorney General", "Cabinet", "justice"),
    (r"Secretary of the Interior", "Secretary of the Interior", "Cabinet", "interior"),
    (r"Secretary of Agriculture", "Secretary of Agriculture", "Cabinet", "agriculture"),
    (r"Secretary of Commerce", "Secretary of Commerce", "Cabinet", "commerce"),
    (r"Secretary of Labor", "Secretary of Labor", "Cabinet", "labor"),
    (r"Secretary of Health and Human Services", "Secretary of Health and Human Services", "Cabinet", "health"),
    (r"Secretary of Housing and Urban Development", "Secretary of Housing and Urban Development", "Cabinet", "housing"),
    (r"Secretary of Transportation", "Secretary of Transportation", "Cabinet", "transportation"),
    (r"Secretary of Energy", "Secretary of Energy", "Cabinet", "energy"),
    (r"Secretary of Education", "Secretary of Education", "Cabinet", "education"),
    (r"Secretary of Veterans Affairs", "Secretary of Veterans Affairs", "Cabinet", "veterans"),
    (r"Secretary of Homeland Security", "Secretary of Homeland Security", "Cabinet", "homeland"),
    (r"Administrator of the Environmental Protection Agency", "Administrator of the Environmental Protection Agency", "Cabinet-level", ""),
    (r"Director of the Office of Management and Budget", "Director of the Office of Management and Budget", "Cabinet-level", ""),
    (r"Director of National Intelligence", "Director of National Intelligence", "Cabinet-level", ""),
    (r"Director of the Central Intelligence Agency", "Director of the Central Intelligence Agency", "Cabinet-level", ""),
    (r"United States Trade Representative", "United States Trade Representative", "Cabinet-level", ""),
    (r"(?:the )?Representative of the United States of America to the United Nations", "Ambassador to the United Nations", "Cabinet-level", ""),
    (r"Administrator of the Small Business Administration", "Administrator of the Small Business Administration", "Cabinet-level", ""),
]
_CABINET = [(re.compile(rf"\bto be {pattern}(?=[,.;]| with\b| vice\b|$)"), post, group, code) for pattern, post, group, code in CABINET]
# A deputy or an assistant is nominated in almost the same words.
_LESSER = re.compile(r"\b(?:Under|Assistant|Deputy|Associate|Principal Deputy) (?:Secretary|Attorney|Administrator|Director|Representative|United States)|Deputy Representative|Sessions of the General Assembly", re.I)

# The White House posts read from Wikidata, by their exact English label there.
WHITE_HOUSE = [
    "Vice President of the United States",
    "White House Chief of Staff",
    "White House Deputy Chief of Staff",
    "United States National Security Advisor",
    "Homeland Security Advisor",
    "Counselor to the President",
    "Senior Advisor to the President of the United States",
    "White House Counsel",
    "White House Press Secretary",
    "White House Communications Director",
    "Director of the National Economic Council",
    "Director of the Domestic Policy Council",
    "Chair of the Council of Economic Advisers",
    "Director of the Office of Science and Technology Policy",
]

COLUMNS = ["name", "position", "group", "department_code", "organization", "status", "start_date", "end_date",
           "confirmation_vote", "nomination", "nomination_url", "source", "wikidata_id", "term_start", "updated"]


def term_start(today=None):
    """The inauguration day that began the presidential term now under way."""
    today = today or date.today()
    year = today.year - ((today.year - 1) % 4)  # 2025, 2029, …
    if (today.month, today.day) < (1, 20) and today.year == year:
        year -= 4
    return f"{year}-01-20"


def congresses_since(day):
    """The Congresses that have sat since `day`: a term begun in 2025 spans the 119th and the 120th."""
    first = (int(day[:4]) - 1789) // 2 + 1
    return list(range(first, int(bills.CONGRESS) + 1))


def fetch_nominations(congress):
    found, offset = [], 0
    while True:
        data = bills.api_get(f"/nomination/{congress}", {"limit": 250, "offset": offset})
        page = (data or {}).get("nominations") or []
        found.extend(page)
        offset += 250
        if len(page) < 250:
            break
    return found


def post_of(description):
    """(post, group, department code) for a cabinet or cabinet-level nomination; None for any other."""
    if _LESSER.search(description or ""):
        return None
    for pattern, post, group, code in _CABINET:
        if pattern.search(description or ""):
            return post, group, code
    return None


def vote_of(action):
    """"52-48" from "Confirmed by the Senate by Yea-Nay Vote. 52 - 48. Record Vote Number: 52.", or "voice vote"."""
    counted = re.search(r"(\d+)\s*-\s*(\d+)", action or "")
    if counted:
        return f"{counted.group(1)}-{counted.group(2)}"
    return "voice vote" if re.search(r"voice vote", action or "", re.I) else ""


def confirmation_in(nomination):
    """The step at which the Senate confirmed a nomination, from its full history; None if it has not."""
    number = f"{nomination.get('number')}"
    if nomination.get("partNumber") not in (None, "", "00"):
        number += f"-{nomination.get('partNumber')}"
    data = bills.api_get(f"/nomination/{nomination.get('congress')}/{number}/actions", {"limit": 100})
    return next((step for step in (data or {}).get("actions") or [] if (step.get("text") or "").startswith("Confirmed")), None)


def cabinet_rows(nominations, since):
    """One row per person confirmed or nominated to a cabinet post since `since`."""
    by_post = {}
    for nomination in nominations:
        description = nomination.get("description") or ""
        post = post_of(description)
        received = nomination.get("receivedDate") or ""
        if not post or received < since:
            continue
        action = nomination.get("latestAction") or {}
        text = action.get("text") or ""
        if not text.startswith("Confirmed") and re.search(r"withdraw|returned to the President", text, re.I):
            continue
        if not text.startswith("Confirmed"):
            # The latest step is not always the vote: a motion to reconsider is often tabled after it.
            action = confirmation_in(nomination) or action
            text = action.get("text") or ""
        confirmed = text.startswith("Confirmed")
        by_post.setdefault(post, []).append({
            "name": re.sub(r"\s+", " ", description.split(", of ")[0]).strip(),
            "position": post[0],
            "group": post[1],
            "department_code": post[2],
            "organization": nomination.get("organization") or "",
            "status": "serving" if confirmed else "nominated",
            "start_date": action.get("actionDate") or "" if confirmed else "",
            "end_date": "",
            "confirmation_vote": vote_of(text) if confirmed else "",
            "nomination": nomination.get("citation") or "",
            "nomination_url": f"https://www.congress.gov/nomination/{nomination.get('congress')}th-congress/{nomination.get('number')}"
                              + (f"/{nomination.get('partNumber')}" if nomination.get("partNumber") not in (None, "", "00") else ""),
            "source": NOMINATIONS,
            "wikidata_id": "",
        })
    rows = []
    for holders in by_post.values():
        confirmed = sorted((h for h in holders if h["status"] == "serving"), key=lambda h: h["start_date"])
        for earlier, later in zip(confirmed, confirmed[1:]):
            earlier["status"] = "former"
            earlier["end_date"] = later["start_date"]  # replaced on the day the successor was confirmed
        # A person nominated again to the post they hold is not a second row.
        names = {h["name"] for h in confirmed}
        rows.extend(confirmed + [h for h in holders if h["status"] == "nominated" and h["name"] not in names])
    return rows


def white_house_rows(since):
    """Holders of the posts in WHITE_HOUSE according to Wikidata. Raises if it cannot be reached."""
    labels = " ".join(f'"{label}"@en' for label in WHITE_HOUSE)
    query = f"""SELECT ?person ?personLabel ?posLabel ?start WHERE {{
      VALUES ?label {{ {labels} }}
      ?pos rdfs:label ?label .
      ?person wdt:P31 wd:Q5 ; wdt:P27 wd:Q30 ; p:P39 ?statement .
      ?statement ps:P39 ?pos ; pq:P580 ?start .
      FILTER NOT EXISTS {{ ?statement pq:P582 ?end }}
      FILTER(?start >= "{since}T00:00:00Z"^^xsd:dateTime)
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}"""
    response = requests.get(SPARQL, params={"query": query, "format": "json"}, headers=HEADERS, timeout=90)
    response.raise_for_status()
    rows, seen = [], set()
    for item in response.json()["results"]["bindings"]:
        name, post = item["personLabel"]["value"], item["posLabel"]["value"]
        if (name, post) in seen or re.fullmatch(r"Q\d+", name):
            continue
        seen.add((name, post))
        rows.append({
            "name": name, "position": post, "group": "White House", "department_code": "", "organization": "Executive Office of the President",
            "status": "serving", "start_date": item["start"]["value"][:10], "end_date": "", "confirmation_vote": "",
            "nomination": "", "nomination_url": "", "source": WIKIDATA, "wikidata_id": item["person"]["value"].rsplit("/", 1)[-1],
        })
    return rows


def read_published():
    try:
        from huggingface_hub import hf_hub_download
        return pd.read_parquet(hf_hub_download(HF_REPO, "data/train-00000-of-00001.parquet", repo_type="dataset", token=bills.HF_TOKEN))
    except Exception:
        return pd.DataFrame(columns=COLUMNS)


def app_file(df, since):
    """world/roster.json: the people now serving or nominated, for the White House map."""
    order = {"Cabinet": 0, "Cabinet-level": 1, "White House": 2}
    posts = [post for _, post, _, _ in CABINET] + WHITE_HOUSE
    current = df[df["status"] != "former"].copy()
    current["_rank"] = [order.get(group, 9) * 100 + (posts.index(post) if post in posts else 99) for group, post in zip(current["group"], current["position"])]
    people = [{"name": row["name"], "position": row["position"], "group": row["group"], "department": row["department_code"],
               "status": row["status"], "since": row["start_date"], "vote": row["confirmation_vote"], "source": row["source"],
               "url": row["nomination_url"] or (f"https://www.wikidata.org/wiki/{row['wikidata_id']}" if row["wikidata_id"] else "")}
              for row in current.sort_values(["_rank", "start_date"]).to_dict("records")]
    former = [{"name": row["name"], "position": row["position"], "from": row["start_date"], "to": row["end_date"]}
              for row in df[df["status"] == "former"].sort_values("end_date", ascending=False).to_dict("records")]
    return {"schema": 1, "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"), "term_start": since,
            "people": people, "former": former}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the executive branch roster")
    parser.add_argument("--no-upload", action="store_true", help="write the files but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="also publish README_executive_roster.md as the dataset card")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if not args.no_upload:
        problem = "no Hugging Face token" if not bills.HF_TOKEN else bills.hf_write_problem(HF_REPO)
        if problem:
            log.error(f"Roster not updated: {problem}")
            return 1
    since = term_start()
    nominations = [n for congress in congresses_since(since) for n in fetch_nominations(congress)]
    cabinet = cabinet_rows(nominations, since)
    serving = sum(1 for row in cabinet if row["group"] == "Cabinet" and row["status"] == "serving")
    log.info(f"Nominations read: {len(nominations)}; cabinet and cabinet-level rows: {len(cabinet)} ({serving} cabinet secretaries serving)")
    existing = read_published()
    if serving < 10 and int((existing.get("group", pd.Series(dtype=str)) == "Cabinet").sum()) >= 10:
        log.error(f"Roster not updated: only {serving} cabinet secretaries found, which looks like a failed listing")
        return 1

    try:
        staff = white_house_rows(since)
        log.info(f"White House posts from Wikidata: {len(staff)}")
    except Exception as e:
        # Keep what was published last time rather than drop the White House from the roster.
        staff = existing[existing["source"] == WIKIDATA].to_dict("records") if "source" in existing else []
        log.warning(f"Wikidata could not be read ({e}); keeping the {len(staff)} White House rows already published")

    today = date.today().isoformat()
    df = pd.DataFrame(cabinet + staff)
    for column in COLUMNS:
        if column not in df.columns:
            df[column] = ""
    df["term_start"], df["updated"] = since, today
    df = df[COLUMNS].fillna("").astype(str)
    rank = {"Cabinet": 0, "Cabinet-level": 1, "White House": 2}
    df = df.sort_values(by=["group", "position", "start_date"], key=lambda col: col.map(rank) if col.name == "group" else col).reset_index(drop=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_DIR / "roster.parquet", index=False)
    snapshot = OUT_DIR / "roster.json"
    snapshot.write_text(json.dumps(app_file(df, since), ensure_ascii=False, separators=(",", ":")))

    pushed = False
    if not args.no_upload:
        from datasets import Dataset
        from huggingface_hub import HfApi
        ds = Dataset.from_pandas(df, preserve_index=False)
        ds.push_to_hub(HF_REPO, token=bills.HF_TOKEN, private=False)
        bills.sync_card_features(ds, HF_REPO)
        api = HfApi(token=bills.HF_TOKEN)
        api.upload_file(path_or_fileobj=str(snapshot), path_in_repo="world/roster.json", repo_id=HF_REPO, repo_type="dataset",
                        commit_message="Update world/roster.json")
        if args.write_card and CARD_FILE.exists():
            from huggingface_hub import DatasetCard
            card = DatasetCard.load(HF_REPO, token=bills.HF_TOKEN)
            card.text = CARD_FILE.read_text()
            card.data["pretty_name"] = "U.S. Executive Branch Roster"
            card.push_to_hub(HF_REPO, token=bills.HF_TOKEN, commit_message="Describe the dataset")
        pushed = True
    counts = df["status"].value_counts().to_dict()
    log.info(f"RESULT: executive-branch-roster rows={len(df)} serving={counts.get('serving', 0)} former={counts.get('former', 0)} "
             f"nominated={counts.get('nominated', 0)} white_house={int((df['group'] == 'White House').sum())} pushed={pushed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
