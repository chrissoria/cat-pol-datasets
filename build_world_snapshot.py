#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-present Christopher Soria <chrissoria@berkeley.edu>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Build the Capitol World snapshot from the federal-bills-active cache.

Writes two files and uploads them next to the dataset on Hugging Face:

    world/world.json       members, committees, the bills with an action in the
                           last 30 days and where each one sits, and the moves
                           of the last 7 days
    world/search.json.gz   every bill, as column arrays, for the search box

build_federal_bills.py calls main() after a successful push. A failure here
never affects the dataset.

Usage:
    python build_world_snapshot.py                 # build and upload
    python build_world_snapshot.py --no-upload     # build into ./world only
    python build_world_snapshot.py --cache other.parquet --out /tmp/world --no-upload
"""

import argparse
import gzip
import json
import logging
import re
import unicodedata
from pathlib import Path

import pandas as pd

import build_federal_bills as bills

log = logging.getLogger("world_snapshot")
SCHEMA = 1
WORLD_DAYS = 30
EVENT_DAYS = 7
SUMMARY_CHARS = 320
TITLE_CHARS = 160

STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
    "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
    "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
    "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
    "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY", "District of Columbia": "DC", "Puerto Rico": "PR", "Guam": "GU",
    "American Samoa": "AS", "Virgin Islands": "VI", "Northern Mariana Islands": "MP",
}
PARTY = {"Republican": "R", "Democratic": "D", "Independent": "I"}
# Used only for bills fetched before the location columns existed.
STATUS_FALLBACK = {
    "Introduced": ("hopper", "origin"),
    "In Committee": ("committee", "origin"),
    "Reported from Committee": ("committee", "origin"),
    "Calendared": ("calendar", "origin"),
    "Senate Floor": ("floor", "Senate"),
    "Passed House": ("other_chamber", "Senate"),
    "Passed Senate": ("other_chamber", "House"),
    "Passed Both Chambers": ("president", ""),
    "Sent to President": ("president", ""),
    "Signed into Law": ("law", ""),
    "Vetoed": ("vetoed", ""),
}
SPONSOR = re.compile(r"^(?:Rep\.|Sen\.|Del\.|Resident Commissioner|Rescom\.)?\s*(.+?)\s*\[([A-Z]+)-([A-Z]{2})(?:-(\d+|At Large))?\]\s*$")


def text_of(value):
    return "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)


def name_key(last_first):
    """'Cole, Tom' -> a loose key for joining roster names to sponsor names."""
    last = unicodedata.normalize("NFKD", last_first.split(",")[0])
    return re.sub(r"[^a-z]", "", last.lower())


def display_name(last_first):
    parts = [part.strip() for part in last_first.split(",", 1)]
    return f"{parts[1]} {parts[0]}" if len(parts) == 2 else last_first


def fetch_roster():
    """Members of this Congress from Congress.gov."""
    members, offset = [], 0
    while True:
        data = bills.api_get(f"/member/congress/{bills.CONGRESS}", {"limit": 250, "offset": offset, "currentMember": "false"})
        page = (data or {}).get("members") or []
        members.extend(page)
        offset += 250
        if len(page) < 250:
            break
    roster = []
    for member in members:
        terms = (member.get("terms") or {}).get("item") or []
        chamber = (terms[-1].get("chamber") if terms else "") or ""
        roster.append({
            "id": member.get("bioguideId") or "",
            "name": display_name(member.get("name") or ""),
            "sort": member.get("name") or "",
            "party": PARTY.get(member.get("partyName") or "", (member.get("partyName") or "?")[:1]),
            "state": STATES.get(member.get("state") or "", member.get("state") or ""),
            "district": member.get("district"),
            "chamber": "House" if "House" in chamber else ("Senate" if "Senate" in chamber else ""),
        })
    return [member for member in roster if member["id"]]


def fetch_committees():
    """Full committees of this Congress: {code: {name, chamber}}."""
    found, offset = {}, 0
    while True:
        data = bills.api_get(f"/committee/{bills.CONGRESS}", {"limit": 250, "offset": offset})
        page = (data or {}).get("committees") or []
        for committee in page:
            code = committee.get("systemCode") or ""
            if code.endswith("00") and not committee.get("parent"):
                found[code] = {"name": committee.get("name") or code, "chamber": committee.get("chamber") or ""}
        offset += 250
        if len(page) < 250:
            break
    return found


ROLES_SOURCE = "https://unitedstates.github.io/congress-legislators/"
LEADER_TITLES = {
    "Speaker of the House": "speaker",
    "House Majority Leader": "House",
    "Senate Majority Leader": "Senate",
}


def fetch_roles():
    """Committee chairs and chamber leaders from the public-domain congress-legislators project.

    Returns {"chairs": {committee code: bioguide id}, "leaders": {"House"|"Senate"|"speaker": id}}.
    Any failure (the host is not on the cloud allowlist, say) returns empty maps: the map
    then shows robots where it would have shown a chair or leader.
    """
    import requests

    roles = {"chairs": {}, "leaders": {}}
    try:
        committees = requests.get(ROLES_SOURCE + "committee-membership-current.json", timeout=20).json()
        for code, people in committees.items():
            if len(code) != 4:
                continue  # subcommittee
            for person in people:
                if (person.get("title") or "") in ("Chair", "Chairman", "Chairwoman") and person.get("bioguide"):
                    roles["chairs"][code.lower() + "00"] = person["bioguide"]
        legislators = requests.get(ROLES_SOURCE + "legislators-current.json", timeout=30).json()
        for legislator in legislators:
            for role in legislator.get("leadership_roles") or []:
                slot = LEADER_TITLES.get(role.get("title") or "")
                if slot and not role.get("end"):
                    roles["leaders"][slot] = legislator["id"]["bioguide"]
    except Exception as e:
        log.info(f"Chairs and leaders not available ({e}); the map will use robots for those moves")
    return roles


def role_actor(previous, roles):
    """Who would carry a bill out of `previous` (a location key): (member id, role label) or (None, None)."""
    parts = (previous or "").split(":")
    kind = parts[0]
    if kind == "committee":
        chair = roles["chairs"].get(parts[-1])
        return (chair, "committee chair") if chair else (None, None)
    if kind in ("calendar", "floor"):
        chamber = next((part for part in parts if part in ("House", "Senate")), "")
        leader = roles["leaders"].get(chamber)
        return (leader, "majority leader") if leader else (None, None)
    return None, None


def committee_key(name):
    name = re.sub(r"\b(house|senate|committee|subcommittee|on|the|and)\b", " ", name.lower())
    return re.sub(r"[^a-z]", "", name)


def resolve_sponsors(df, roster):
    """Return (member list, sponsor id per row). Sponsors missing from the roster get an 'x-' id."""
    by_id = {member["id"]: member for member in roster}
    by_key = {}
    for member in roster:
        by_key.setdefault((name_key(member["sort"]), member["state"]), []).append(member)

    extra, cache, ids = {}, {}, []
    bioguide = df["sponsor_bioguide_id"] if "sponsor_bioguide_id" in df.columns else [None] * len(df)
    for full, known in zip(df["sponsor_full_name"], bioguide):
        full, known = text_of(full), text_of(known)
        if known in by_id:
            ids.append(known)
            continue
        if full in cache:
            ids.append(cache[full])
            continue
        match = SPONSOR.match(full)
        member_id = ""
        if match:
            name, party, state, district = match.groups()
            candidates = by_key.get((name_key(name), state), [])
            if len(candidates) > 1 and district and district.isdigit():
                candidates = [c for c in candidates if str(c["district"]) == district] or candidates
            if len(candidates) > 1:
                first = name.split(",", 1)[1].strip().split(" ")[0].lower() if "," in name else ""
                candidates = [c for c in candidates if c["name"].lower().startswith(first)] or candidates
            if candidates:
                member_id = candidates[0]["id"]
            else:
                member_id = "x-" + re.sub(r"[^a-z0-9]+", "-", f"{name} {state}".lower()).strip("-")
                extra.setdefault(member_id, {
                    "id": member_id, "name": display_name(name), "sort": name, "party": party[:1], "state": state,
                    "district": int(district) if district and district.isdigit() else None,
                    "chamber": "House" if full.startswith(("Rep.", "Del.", "Res")) else "Senate",
                })
        cache[full] = member_id
        ids.append(member_id)
    return list(by_id.values()) + list(extra.values()), ids


def location_key(loc):
    return ":".join(part for part in (loc["kind"], loc["chamber"], loc["committee"]) if part)


def row_location(row, committees_by_key):
    """Where a bill sits: the stored location if there is one, else a guess from its status."""
    kind = text_of(row.get("location_kind"))
    if kind:
        return {
            "kind": kind,
            "chamber": text_of(row.get("location_chamber")),
            "committee": text_of(row.get("location_committee_code")),
        }, False
    origin = text_of(row.get("chamber_of_origin"))
    kind, chamber = STATUS_FALLBACK.get(text_of(row.get("status")), ("referral_desk", "origin"))
    chamber = origin if chamber == "origin" else chamber
    if kind == "other_chamber" and text_of(row.get("bill_type")) in ("HRES", "SRES"):
        kind, chamber = "adopted", origin  # a one-chamber resolution has nowhere else to go
    committee = ""
    if kind == "committee":
        action = text_of(row.get("last_action_text"))
        found = bills._COMMITTEE_NAME.search(action)
        in_senate = "Senate" in action or (origin == "Senate" and "House" not in action)
        if found:
            committee = committees_by_key.get(("Senate" if in_senate else "House", committee_key(found.group(1))), "")
        if committee:
            chamber = "Senate" if committee.startswith("s") else "House"
        else:
            kind = "referral_desk"
    return {"kind": kind, "chamber": chamber, "committee": committee}, True


NAMED_SENATOR = re.compile(r"Senator ([A-Z][\w'\-]+(?: [A-Z][\w'\-]+)?)")
NAMED_MEMBER = re.compile(r"\b(?:Mr|Ms|Mrs|Miss)\. ([A-Z][\w'\-]+(?: [A-Z][\w'\-]+)?)(?: \(([A-Z]{2})\))?")


def make_actor_finder(members):
    """Return find(texts) -> member id for a legislator the action text names, when the name is unambiguous."""
    by_name = {}
    for member in members:
        last = name_key(member["sort"]) if member.get("sort") else re.sub(r"[^a-z]", "", member["name"].split(" ")[-1].lower())
        by_name.setdefault((member["chamber"], last), []).append(member)

    def find(texts):
        for text in texts:
            for pattern, chamber in ((NAMED_SENATOR, "Senate"), (NAMED_MEMBER, "House")):
                for match in pattern.finditer(text):
                    key = re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", match.group(1)).lower())
                    candidates = by_name.get((chamber, key), [])
                    state = match.group(2) if pattern is NAMED_MEMBER else None
                    if state:
                        candidates = [c for c in candidates if c["state"] == state]
                    if len(candidates) == 1:
                        return candidates[0]["id"]
        return None

    return find


def bill_events(bill_id, row, final, since, find_actor=None, roles=None):
    """Moves in the last EVENT_DAYS days: one event each time the bill's location changes.

    `actor` is the legislator who carried it: the sponsor when the bill is introduced,
    otherwise a member named in that day's action text, otherwise None.
    """
    sponsor = text_of(row.get("sponsor_id")) or None
    try:
        history = json.loads(text_of(row.get("recent_actions")) or "[]")
    except ValueError:
        history = []
    if not history:
        if text_of(row.get("date_last_action")) >= since:
            return [{"bill": bill_id, "date": text_of(row.get("date_last_action")), "from": None,
                     "to": location_key(final), "text": text_of(row.get("last_action_text"))[:140],
                     "actor": None, "actor_role": None}]
        return []
    bill_type, origin = text_of(row.get("bill_type")), text_of(row.get("chamber_of_origin"))
    events, previous = [], None
    oldest_first = history[::-1]
    for count in range(1, len(oldest_first) + 1):
        seen = oldest_first[:count][::-1]
        found = bills.classify_location(seen, bill_type, origin)
        if not found["kind"]:
            continue
        key = location_key({"kind": found["kind"], "chamber": found["chamber"], "committee": found["committee_code"]})
        action = oldest_first[count - 1]
        if key != previous:
            if action["date"] >= since:
                if previous is None:
                    actor, actor_role = sponsor, "sponsor"
                else:
                    same_day = [a["text"] for a in oldest_first[:count] if a["date"] == action["date"]][::-1]
                    actor = find_actor(same_day) if find_actor else None
                    actor_role = "named in the record" if actor else None
                    if not actor and roles:
                        actor, actor_role = role_actor(previous, roles)
                events.append({"bill": bill_id, "date": action["date"], "from": previous, "to": key,
                               "text": action["text"][:140], "actor": actor, "actor_role": actor_role})
            previous = key
    return events


def build(cache_file, roster=None, committees=None, roles=None):
    wanted = [
        "bill_type", "bill_number", "congress", "title", "status", "last_action_text", "date_last_action",
        "date_introduced", "sponsor_full_name", "sponsor_party", "sponsor_state", "num_cosponsors",
        "chamber_of_origin", "policy_area", "short_summary", "url", "sponsor_bioguide_id", "recent_actions",
        "location_kind", "location_chamber", "location_committee_code", "location_committee_name",
    ]
    import pyarrow.parquet as pq
    available = set(pq.ParquetFile(cache_file).schema.names)
    df = pd.read_parquet(cache_file, columns=[c for c in wanted if c in available])
    df = df.sort_values(["date_last_action", "bill_type", "bill_number"], ascending=[False, True, True]).reset_index(drop=True)

    roster = fetch_roster() if roster is None else roster
    committees = fetch_committees() if committees is None else committees
    if not roster:
        raise RuntimeError("member roster came back empty")
    committees_by_key = {(info["chamber"], committee_key(info["name"])): code for code, info in committees.items()}

    members, sponsor_ids = resolve_sponsors(df, roster)
    df["sponsor_id"] = sponsor_ids
    df["id"] = [f"{c}-{t.lower()}-{n}" for c, t, n in zip(df["congress"], df["bill_type"], df["bill_number"])]

    data_through = text_of(df["date_last_action"].max())
    world_since = (pd.Timestamp(data_through) - pd.Timedelta(days=WORLD_DAYS)).strftime("%Y-%m-%d")
    event_since = (pd.Timestamp(data_through) - pd.Timedelta(days=EVENT_DAYS)).strftime("%Y-%m-%d")

    find_actor = make_actor_finder(members)
    roles = fetch_roles() if roles is None else roles
    known = {member["id"] for member in members}
    roles = {
        "chairs": {code: who for code, who in roles["chairs"].items() if who in known},
        "leaders": {slot: who for slot, who in roles["leaders"].items() if who in known},
    }
    world_bills, events, used_committees, guessed = [], [], {}, 0
    for row in df[df["date_last_action"] >= world_since].to_dict("records"):
        loc, was_guess = row_location(row, committees_by_key)
        guessed += was_guess
        if loc["committee"]:
            used_committees[loc["committee"]] = used_committees.get(loc["committee"], 0) + 1
        summary = text_of(row.get("short_summary")).strip()
        world_bills.append({
            "id": row["id"],
            "type": row["bill_type"],
            "number": text_of(row["bill_number"]),
            "title": text_of(row.get("title"))[:TITLE_CHARS],
            "sponsor": row["sponsor_id"],
            "cosponsors": int(row.get("num_cosponsors") or 0),
            "policy_area": text_of(row.get("policy_area")),
            "status": text_of(row.get("status")),
            "loc": loc,
            "last_action": {"date": text_of(row.get("date_last_action")), "text": text_of(row.get("last_action_text"))[:200]},
            "introduced": text_of(row.get("date_introduced")),
            "summary": summary[:SUMMARY_CHARS] + ("…" if len(summary) > SUMMARY_CHARS else ""),
            "url": text_of(row.get("url")),
        })
        events.extend(bill_events(row["id"], row, loc, event_since, find_actor, roles))
    events.sort(key=lambda event: event["date"])
    for seq, event in enumerate(events):
        event["seq"] = seq

    in_world = pd.Series([bill["sponsor"] for bill in world_bills]).value_counts().to_dict()
    in_total = df["sponsor_id"].value_counts().to_dict()
    committee_names = {code: info["name"] for code, info in committees.items()}
    titles = {}
    for code, who in roles["chairs"].items():
        titles.setdefault(who, f"Chair, {committee_names.get(code, code)}")
    for slot, who in roles["leaders"].items():
        titles[who] = "Speaker of the House" if slot == "speaker" else f"{slot} Majority Leader"
    for member in members:
        member["n_world"] = int(in_world.get(member["id"], 0))
        member["n_total"] = int(in_total.get(member["id"], 0))
        member["role"] = titles.get(member["id"], "")
        member.pop("sort", None)
    committee_list = [
        {"code": code, "name": info["name"], "chamber": info["chamber"], "n_bills": used_committees.get(code, 0)}
        for code, info in sorted(committees.items())
    ]
    for code, count in used_committees.items():
        if code not in committees:
            committee_list.append({"code": code, "name": code, "chamber": "Senate" if code.startswith("s") else "House",
                                   "n_bills": count})

    world = {
        "schema": SCHEMA,
        "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_through": data_through,
        "congress": int(bills.CONGRESS),
        "window": {"world_since": world_since, "events_since": event_since},
        "counts": {
            "total": int(len(df)),
            "world": len(world_bills),
            "events": len(events),
            "guessed_locations": int(guessed),
            "by_status": {k: int(v) for k, v in df["status"].value_counts().items()},
            "by_kind": pd.Series([bill["loc"]["kind"] for bill in world_bills]).value_counts().to_dict(),
        },
        "roles": roles,
        "members": members,
        "committees": committee_list,
        "bills": world_bills,
        "events": events,
    }

    sponsors = sorted({member["id"] for member in members if member["n_total"]})
    sponsor_index = {member_id: i for i, member_id in enumerate(sponsors)}
    statuses = sorted(df["status"].dropna().unique())
    areas = sorted(a for a in df["policy_area"].fillna("").unique() if a)
    search = {
        "schema": SCHEMA,
        "data_through": data_through,
        "sponsors": sponsors,
        "statuses": statuses,
        "policy_areas": areas,
        "id": df["id"].tolist(),
        "title": [text_of(t)[:TITLE_CHARS] for t in df["title"]],
        "sponsor": [sponsor_index.get(s, -1) for s in df["sponsor_id"]],
        "status": [statuses.index(s) if s in statuses else -1 for s in df["status"]],
        "policy_area": [areas.index(a) if a in areas else -1 for a in df["policy_area"].fillna("")],
        "date": df["date_last_action"].fillna("").tolist(),
    }
    return world, search


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the Capitol World snapshot")
    parser.add_argument("--cache", default=str(bills.CACHE_FILE), help="bills parquet to read")
    parser.add_argument("--out", default=str(bills.SCRIPT_DIR / "world"), help="directory to write into")
    parser.add_argument("--no-upload", action="store_true", help="write the files but do not upload them")
    args = parser.parse_args(argv)

    world, search = build(args.cache)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    world_file, search_file = out / "world.json", out / "search.json.gz"
    world_file.write_text(json.dumps(world, ensure_ascii=False, separators=(",", ":")))
    with gzip.open(search_file, "wt", encoding="utf-8") as handle:
        json.dump(search, handle, ensure_ascii=False, separators=(",", ":"))
    counts = world["counts"]
    log.info(f"World snapshot: {counts['world']} bills, {len(world['members'])} members, {counts['events']} events, "
             f"{counts['guessed_locations']} guessed locations; world.json {world_file.stat().st_size // 1024} KB, "
             f"search.json.gz {search_file.stat().st_size // 1024} KB")

    if args.no_upload:
        return 0
    if not bills.HF_TOKEN:
        log.error("No HuggingFace token; snapshot written locally but not uploaded")
        return 1
    from huggingface_hub import HfApi
    api = HfApi(token=bills.HF_TOKEN)
    for path in (world_file, search_file):
        api.upload_file(path_or_fileobj=str(path), path_in_repo=f"world/{path.name}", repo_id=bills.HF_REPO,
                        repo_type="dataset", commit_message=f"Update world/{path.name}")
    log.info(f"Uploaded world snapshot to {bills.HF_REPO}/world")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(main())
