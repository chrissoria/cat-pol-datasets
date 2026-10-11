#!/usr/bin/env python3
"""
Build chrissoria/congress-members: everyone who has served in the U.S. Congress,
when they entered and left, and the main facts about them.

Two tables:

  - members: one row per person. Who they are (name, birth date, gender), the
    seat they hold or last held (chamber, state, district, party), when they
    first entered and last left, how many terms and days they have served, a
    leadership post if they hold one, and, for people now serving, the official
    website, contact form, phone, office and social media accounts.
  - terms: one row per term served, back to 1789.

Sources, all public:

  - Nearly everything comes from the congress-legislators project
    (github.com/unitedstates/congress-legislators, CC0), which volunteers keep
    up to date from official records.
  - `race_ethnicity` comes only from the three lists the House's Office of the
    Historian publishes: Black Americans, Hispanic Americans, and Asian and
    Pacific Islander Americans in Congress. A member on none of them has an
    empty value, which says nothing about them: no list of white, Native
    American or Middle Eastern members is published. Nothing is inferred from
    a name, a district or a caucus.

Why someone left (lost, retired, resigned, died) is in neither source. The
table records only whether the last term ran to the end of a Congress, and
before about 1990 the source often gives the day a term was due to end even
when the member died or resigned earlier.

Writes the two tables and world/members.json (for the member card in Capitol
World, limited to people who have served since the 113th Congress) and
publishes them. Meant to run weekly.

Usage:
    python build_congress_members.py
    python build_congress_members.py --no-upload
    python build_congress_members.py --write-card
"""

import argparse
import html
import json
import logging
import re
import sys
import unicodedata
from datetime import date

import pandas as pd
import requests

import build_federal_bills as bills
import build_world_snapshot as snapshot

log = logging.getLogger(__name__)

HF_REPO = "chrissoria/congress-members"
OUT_DIR = bills.SCRIPT_DIR / "members"
APP_FILE = bills.SCRIPT_DIR / "world" / "members.json"
CARD_FILE = bills.SCRIPT_DIR / "README_congress_members.md"
HEADERS = {"User-Agent": "cat-pol-dataset-builder/1.0 (academic research)"}

# The project publishes the same files on its website and in its repository.
LEGISLATOR_HOSTS = (snapshot.ROLES_SOURCE, "https://raw.githubusercontent.com/unitedstates/congress-legislators/gh-pages/")
LEGISLATOR_FILES = ("legislators-current.json", "legislators-historical.json", "legislators-social-media.json")

# (the value written in `race_ethnicity`, the Historian's name for the list, its page)
HISTORIAN = "https://history.house.gov/Exhibitions-and-Publications/"
HISTORIAN_LISTS = [
    ("Black", "Black Americans in Congress",
     HISTORIAN + "BAIC/Historical-Data/Black-American-Representatives-and-Senators-by-Congress/"),
    ("Hispanic", "Hispanic Americans in Congress",
     HISTORIAN + "HAIC/Historical-Data/Hispanic-American-Representatives,-Senators,-Delegates,-and-Resident-Commissioners-by-Congress/"),
    ("Asian or Pacific Islander", "Asian and Pacific Islander Americans in Congress",
     HISTORIAN + "APA/Historical-Data/By-Congress/"),
]
RACE_SOURCE = "U.S. House, Office of the Historian: "
MATCHED_SHARE = 0.9  # of the people on a list; fewer found among the members means the page has changed

FIRST_APP_CONGRESS = 113  # the earliest Congress Capitol World shows
BREAK_DAYS = 31  # a longer gap between two terms in a chamber is a break in service
CHAMBER = {"rep": "House", "sen": "Senate"}
# Seats in the House that are not a state's. A territory that later became a state shares the
# state's code in the source, so its delegates cannot be told from representatives here.
NON_VOTING = {"AS": "Delegate", "DC": "Delegate", "GU": "Delegate", "MP": "Delegate", "VI": "Delegate", "DK": "Delegate",
              "OL": "Delegate", "PR": "Resident Commissioner", "PI": "Resident Commissioner"}
SOCIAL = ("twitter", "facebook", "instagram", "youtube", "youtube_id", "mastodon")

MEMBER_COLUMNS = [
    "bioguide_id", "name", "first_name", "middle_name", "last_name", "suffix", "nickname", "birth_date", "gender",
    "race_ethnicity", "race_ethnicity_source", "status", "position", "chamber", "state", "district", "party", "caucus",
    "senate_class", "state_rank", "first_entered", "last_exit", "exit_timing", "current_service_start", "n_terms",
    "house_terms", "senate_terms", "days_served", "leadership_position", "leadership_history", "website", "contact_form",
    "phone", "office_address", *SOCIAL, "govtrack_id", "icpsr_id", "lis_id", "wikidata_id", "wikipedia",
    "opensecrets_id", "fec_ids", "house_history_id", "updated",
]
TERM_COLUMNS = ["bioguide_id", "name", "term_number", "chamber", "position", "start", "end", "congress_first", "congress_last",
                "state", "district", "party", "caucus", "senate_class", "state_rank", "how", "days", "serving", "url"]


def get(url, timeout=120):
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response


def fetch_legislators():
    """(people now serving, people who served before, social media accounts), as the project's files list them."""
    problem = None
    for host in LEGISLATOR_HOSTS:
        try:
            return tuple(get(host + name).json() for name in LEGISLATOR_FILES)
        except Exception as e:
            problem = e
            log.warning(f"Could not read the legislators files from {host}: {e}")
    raise problem


def congress_start(congress):
    """The day a Congress began: March 4 until the 73rd, January 3 since the 74th (1935)."""
    year = 1789 + 2 * (int(congress) - 1)
    return f"{year}-01-03" if congress >= 74 else f"{year}-03-04"


def congress_of(day):
    """The Congress sitting on a day: 119 for 2026-10-10."""
    guess = (int(day[:4]) - 1789) // 2 + 1
    return guess if day >= congress_start(guess) else guess - 1


def days_between(start, end):
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def position_of(term):
    return "Senator" if term["type"] == "sen" else NON_VOTING.get(term["state"], "Representative")


def last_stretch_start(terms):
    """The start of the last unbroken run of terms in one chamber: Cantwell's is 2001, not her House term of 1993."""
    start = terms[-1]["start"]
    for earlier, later in zip(terms[-2::-1], terms[::-1]):
        if earlier["type"] != later["type"] or days_between(earlier["end"], later["start"]) > BREAK_DAYS:
            break
        start = earlier["start"]
    return start


def exit_timing(end):
    """Whether a last term ran out with its Congress. All the sources say about how someone left."""
    # Before about 1990 the source often dates a term to its scheduled end, so "end of a Congress" is overstated there.
    year, month_day = int(end[:4]), end[5:]
    with_congress = month_day == "01-03" if year >= 1935 else month_day in ("03-03", "03-04")
    return "end of a Congress" if with_congress and year % 2 else "during a Congress"


def display_name(name):
    if name.get("official_full"):
        return name["official_full"]
    return " ".join(part for part in (name.get("first"), name.get("last"), name.get("suffix")) if part)


def term_rows(person, serving, today):
    """One row per term a person has served."""
    rows = []
    for number, term in enumerate(person["terms"], 1):
        end = term["end"]
        rows.append({
            "bioguide_id": person["id"]["bioguide"],
            "name": display_name(person["name"]),
            "term_number": number,
            "chamber": CHAMBER[term["type"]],
            "position": position_of(term),
            "start": term["start"],
            "end": end,
            "congress_first": congress_of(term["start"]),
            # A term that ends on the day a Congress does belongs to that Congress, not the next.
            "congress_last": max(congress_of(term["start"]), congress_of(end) - (1 if end == congress_start(congress_of(end)) else 0)),
            "state": term["state"],
            "district": term.get("district") if term["type"] == "rep" else None,
            "party": term.get("party") or "",
            "caucus": term.get("caucus") or "",
            "senate_class": term.get("class"),
            "state_rank": term.get("state_rank") or "",
            "how": term.get("how") or "",
            "days": max(0, days_between(term["start"], min(end, today))),
            "serving": bool(serving and number == len(person["terms"]) and end > today),
            "url": term.get("url") or "",
        })
    return rows


def member_row(person, serving, social, today):
    """One row for a person: who they are, their seat, and their service added up."""
    ids, name, terms = person["id"], person["name"], person["terms"]
    last = terms[-1]
    roles = person.get("leadership_roles") or []
    held = [role["title"] for role in roles if not role.get("end") or role["end"] > today] if serving else []
    row = {
        "bioguide_id": ids["bioguide"],
        "name": display_name(name),
        "first_name": name.get("first") or "",
        "middle_name": name.get("middle") or "",
        "last_name": name.get("last") or "",
        "suffix": name.get("suffix") or "",
        "nickname": name.get("nickname") or "",
        "birth_date": (person.get("bio") or {}).get("birthday") or "",
        "gender": (person.get("bio") or {}).get("gender") or "",
        "race_ethnicity": "",
        "race_ethnicity_source": "",
        "status": "serving" if serving else "former",
        "position": position_of(last),
        "chamber": CHAMBER[last["type"]],
        "state": last["state"],
        "district": last.get("district") if last["type"] == "rep" else None,
        "party": last.get("party") or "",
        "caucus": last.get("caucus") or "",
        "senate_class": last.get("class"),
        "state_rank": last.get("state_rank") or "",
        "first_entered": terms[0]["start"],
        "last_exit": "" if serving else last["end"],
        "exit_timing": "" if serving else exit_timing(last["end"]),
        "current_service_start": last_stretch_start(terms) if serving else "",
        "n_terms": len(terms),
        "house_terms": sum(1 for term in terms if term["type"] == "rep"),
        "senate_terms": sum(1 for term in terms if term["type"] == "sen"),
        "days_served": sum(max(0, days_between(term["start"], min(term["end"], today))) for term in terms),
        "leadership_position": "; ".join(held),
        "leadership_history": "; ".join(f"{role['title']} ({role['start']} to {role.get('end') or 'now'})" for role in roles),
        # An address or a phone number is only any use while the person holds the seat.
        "website": last.get("url") or "" if serving else "",
        "contact_form": last.get("contact_form") or "" if serving else "",
        "phone": last.get("phone") or "" if serving else "",
        "office_address": last.get("address") or "" if serving else "",
        "govtrack_id": ids.get("govtrack"),
        "icpsr_id": ids.get("icpsr"),
        "lis_id": ids.get("lis") or "",
        "wikidata_id": ids.get("wikidata") or "",
        "wikipedia": ids.get("wikipedia") or "",
        "opensecrets_id": ids.get("opensecrets") or "",
        "fec_ids": ";".join(ids.get("fec") or []),
        "house_history_id": ids.get("house_history"),
    }
    for account in SOCIAL:
        row[account] = str((social or {}).get(account) or "") if serving else ""
    return row


# ----- race and ethnicity, from the House Historian's lists

_ROW = re.compile(r'<tr class="(?:odd|even)">(.*?)</tr>', re.S)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)


def name_key(text):
    """'Watson Coleman' and 'WATSON COLEMAN' -> 'watsoncoleman'; accents dropped."""
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", plain.lower())


def name_parts(*texts):
    """The words of one or more names, as keys: {'marie', 'gluesenkamp'}. Initials are left out."""
    words = re.split(r"[\s(),]+", " ".join(text for text in texts if text))
    return {name_key(word) for word in words if len(name_key(word)) > 1}


def parse_historian(page):
    """The people on one of the Historian's by-Congress lists.

    Returns {the Historian's id for the person: {"last", "given", "seats": {(congress, chambers, state)}}},
    where chambers is "House", "Senate" or "House Senate" for someone who sat in both in one Congress.
    """
    listed = {}
    for row in _ROW.findall(page):
        link = re.search(r"/People/Detail/(\d+)", row)
        cells = [" ".join(html.unescape(re.sub(r"<sup>.*?</sup>|<[^>]+>", " ", cell, flags=re.S)).split()) for cell in _CELL.findall(row)]
        congress = re.match(r"(\d+)", cells[0] if cells else "")
        if not link or not congress or len(cells) < 5 or "," not in cells[1]:
            continue
        last, given = cells[1].split(",", 1)
        person = listed.setdefault(int(link.group(1)), {"last": last.strip(), "given": given.strip(), "seats": set()})
        person["seats"].add((int(congress.group(1)), "House Senate" if cells[4] == "Both" else cells[4], cells[2]))
    return listed


def seats_held(entry, person):
    """How many of the seats a list gives for someone a member held; 0 unless their names agree as well.

    Surnames agree when one holds all the words of the other ("Perez" and "Gluesenkamp Perez").
    Given names agree when any two begin alike ("Joseph" and "Joe"), since the Historian writes
    full names and the legislators file the name a member goes by.
    """
    names = person["name"]
    surname, theirs = name_parts(entry["last"]), name_parts(names.get("last"))
    if not surname or not (surname <= theirs or theirs <= surname):
        return 0
    given = name_parts(entry["given"]) | (surname ^ theirs)
    known = name_parts(names.get("first"), names.get("nickname"), names.get("middle"), names.get("official_full"))
    if not any(a[:2] == b[:2] for a in given for b in known):
        return 0
    held = 0
    for congress, chambers, state in entry["seats"]:
        opened, closed = congress_start(congress), congress_start(congress + 1)
        held += any(CHAMBER[term["type"]] in chambers and term["state"] == state and term["start"] < closed and term["end"] > opened
                    for term in person["terms"])
    return held


def match_historian(listed, people):
    """{Historian id: bioguide id} for the listed people who can be told apart among the members.

    The Historian's own id is used where the legislators file records it. Otherwise a listed
    person is matched to the one member of that name who sat for that state, in that chamber,
    in every Congress the list gives; failing that (the two sources can date a first or last
    term a day apart), to the one who sat in any of them. Anyone left over, or with two such
    members, is not matched.
    """
    by_historian = {}
    for person in people:
        for key in ("house_history", "house_history_alternate"):
            if person["id"].get(key):
                by_historian[int(person["id"][key])] = person["id"]["bioguide"]
    found = {}
    for historian_id, entry in listed.items():
        if historian_id in by_historian:
            found[historian_id] = by_historian[historian_id]
            continue
        held = {person["id"]["bioguide"]: seats_held(entry, person) for person in people}
        for enough in (len(entry["seats"]), 1):
            candidates = [bioguide for bioguide, count in held.items() if count >= enough]
            if candidates:
                break
        if len(candidates) == 1:
            found[historian_id] = candidates[0]
    return found


def race_from_historian(people):
    """{bioguide id: [list labels]} from the Historian's lists. Raises if a list cannot be read or has changed shape."""
    labels = {}
    for label, title, url in HISTORIAN_LISTS:
        listed = parse_historian(get(url).text)
        found = match_historian(listed, people)
        missing = [f"{entry['last']}, {entry['given']}" for key, entry in listed.items() if key not in found]
        log.info(f"{title}: {len(listed)} people listed, {len(found)} matched to a member"
                 + (f"; not matched: {'; '.join(missing[:20])}" if missing else ""))
        if len(listed) < 20 or len(found) < MATCHED_SHARE * len(listed):
            raise ValueError(f"the list '{title}' gave {len(listed)} people and {len(found)} matches, which looks like a changed page")
        for bioguide in found.values():
            labels.setdefault(bioguide, []).append(label)
    return labels


# ----- tables and the app's file

def build_tables(current, historical, social, today=None):
    """(members, terms) as data frames, from the legislators files. Race is added separately."""
    today = today or date.today().isoformat()
    accounts = {entry["id"]["bioguide"]: entry.get("social") or {} for entry in social}
    members, terms = [], []
    for serving, people in ((True, current), (False, historical)):
        for person in people:
            members.append(member_row(person, serving, accounts.get(person["id"]["bioguide"]), today))
            terms.extend(term_rows(person, serving, today))
    members = pd.DataFrame(members)
    members["updated"] = today
    members = members[MEMBER_COLUMNS].sort_values(["last_name", "first_name", "bioguide_id"]).reset_index(drop=True)
    terms = pd.DataFrame(terms)[TERM_COLUMNS].sort_values(["bioguide_id", "term_number"]).reset_index(drop=True)
    for frame, columns in ((members, ("district", "senate_class", "govtrack_id", "icpsr_id", "house_history_id")),
                           (terms, ("district", "senate_class"))):
        for column in columns:
            frame[column] = frame[column].astype("Int64")
    return members, terms


def add_race(members, labels):
    """Fill `race_ethnicity` and its source from {bioguide id: [labels]}, in the order of HISTORIAN_LISTS."""
    titles = {label: title for label, title, _ in HISTORIAN_LISTS}
    order = [label for label, _, _ in HISTORIAN_LISTS]
    found = [sorted(labels.get(bioguide, []), key=order.index) for bioguide in members["bioguide_id"]]
    members["race_ethnicity"] = ["; ".join(labels_of) for labels_of in found]
    members["race_ethnicity_source"] = ["; ".join(RACE_SOURCE + titles[label] for label in labels_of) for labels_of in found]
    return members


def app_file(current, historical, today=None, since_congress=FIRST_APP_CONGRESS):
    """world/members.json: what the member card in Capitol World shows, for everyone who has served since `since_congress`."""
    today = today or date.today().isoformat()
    opened = congress_start(since_congress)
    out = {}
    for serving, people in ((True, current), (False, historical)):
        for person in people:
            terms = person["terms"]
            last = terms[-1]
            if last["end"] <= opened:
                continue
            out[person["id"]["bioguide"]] = {
                "url": last.get("url") or "" if serving else "",
                "contact_form": last.get("contact_form") or "" if serving else "",
                "email": "",  # no source gives a public address: members are written to through their forms
                "phone": last.get("phone") or "" if serving else "",
                "office": last.get("office") or last.get("address") or "" if serving else "",
                "since": last_stretch_start(terms),
                "first_entered": terms[0]["start"],
                "terms": [{"chamber": CHAMBER[term["type"]], "start": term["start"], "end": term["end"], "state": term["state"],
                           "district": term.get("district") if term["type"] == "rep" else None, "party": term.get("party") or ""}
                          for term in terms],
                "born": (person.get("bio") or {}).get("birthday") or "",
                "gender": (person.get("bio") or {}).get("gender") or "",
            }
    return {"schema": 1, "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
            "members": dict(sorted(out.items()))}


def read_published():
    try:
        from huggingface_hub import hf_hub_download
        return pd.read_parquet(hf_hub_download(HF_REPO, "data/members.parquet", repo_type="dataset", token=bills.HF_TOKEN))
    except Exception:
        return pd.DataFrame(columns=MEMBER_COLUMNS)


def problem_with(members, terms, existing):
    """Why these tables should not replace the published ones, or None."""
    serving = int((members["status"] == "serving").sum())
    if not 500 <= serving <= 541:
        return f"{serving} people are listed as serving, and Congress has 541 seats"
    if members["bioguide_id"].duplicated().any():
        return "a person appears twice"
    if len(members) < len(existing):
        return f"{len(members)} people, fewer than the {len(existing)} already published"
    if len(terms) < 3 * len(members):  # three and a half terms a person, over the whole history
        return f"only {len(terms)} terms for {len(members)} people"
    return None


def upload(write_card):
    from huggingface_hub import CommitOperationAdd, HfApi
    api = HfApi(token=bills.HF_TOKEN)
    api.create_repo(HF_REPO, repo_type="dataset", private=False, exist_ok=True)
    operations = [CommitOperationAdd(path_in_repo="data/members.parquet", path_or_fileobj=str(OUT_DIR / "members.parquet")),
                  CommitOperationAdd(path_in_repo="data/terms.parquet", path_or_fileobj=str(OUT_DIR / "terms.parquet")),
                  CommitOperationAdd(path_in_repo="world/members.json", path_or_fileobj=str(APP_FILE))]
    # The card names the two tables, so the first upload needs it whether or not it was asked for.
    if CARD_FILE.exists() and (write_card or not api.file_exists(HF_REPO, "README.md", repo_type="dataset")):
        operations.append(CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=str(CARD_FILE)))
    api.create_commit(repo_id=HF_REPO, repo_type="dataset", operations=operations,
                      commit_message=f"Update members and terms ({date.today().isoformat()})")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the members of Congress tables")
    parser.add_argument("--no-upload", action="store_true", help="write the files but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="also publish README_congress_members.md as the dataset card")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if not args.no_upload:
        problem = "no Hugging Face token" if not bills.HF_TOKEN else bills.hf_write_problem(HF_REPO)
        if problem:
            log.error(f"Members not updated: {problem}")
            return 1
    try:
        current, historical, social = fetch_legislators()
    except Exception as e:
        log.error(f"Members not updated: the legislators files could not be read ({e})")
        return 1
    members, terms = build_tables(current, historical, social)
    log.info(f"Legislators read: {len(current)} serving, {len(historical)} former, {len(terms)} terms")

    existing = read_published()
    try:
        members = add_race(members, race_from_historian(current + historical))
    except Exception as e:
        # Keep what was published last time rather than blank the column.
        kept = existing[existing["race_ethnicity"].fillna("") != ""] if len(existing) else existing
        log.warning(f"The Historian's lists could not be used ({e}); keeping the {len(kept)} values already published")
        for column in ("race_ethnicity", "race_ethnicity_source"):
            members[column] = members["bioguide_id"].map(dict(zip(kept["bioguide_id"], kept[column]))).fillna("")

    problem = problem_with(members, terms, existing)
    if problem:
        log.error(f"Members not updated: {problem}, which looks like a failed or partial listing")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    members.to_parquet(OUT_DIR / "members.parquet", index=False)
    terms.to_parquet(OUT_DIR / "terms.parquet", index=False)
    APP_FILE.parent.mkdir(parents=True, exist_ok=True)
    for_app = app_file(current, historical)
    APP_FILE.write_text(json.dumps(for_app, ensure_ascii=False, separators=(",", ":")))
    log.info(f"Member file for the map: {len(for_app['members'])} people, {APP_FILE.stat().st_size // 1024} KB")

    pushed = False
    if not args.no_upload:
        upload(args.write_card)
        pushed = True
    serving = members[members["status"] == "serving"]
    log.info(f"RESULT: congress-members members={len(members)} serving={len(serving)} terms={len(terms)} "
             f"with_website={int((serving['website'] != '').sum())} race_listed={int((members['race_ethnicity'] != '').sum())} "
             f"app_members={len(for_app['members'])} pushed={pushed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
