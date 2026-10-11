#!/usr/bin/env python3
"""
Build chrissoria/supreme-court-cases: the Supreme Court's decided cases since
1946, the cases it is hearing now, and the emergency applications put to it.

Three sources, each used for what only it has:

  The Supreme Court Database (scdb.wustl.edu, Washington University)
      Every case decided from the 1946 term on, coded by hand: the issue, the
      outcome, how each justice voted. Released about once a year, so it stops
      at the last finished term. Licence: CC BY-NC 3.0 US.
  Oyez (api.oyez.org)
      The question each case asks, a one-line account of what was held, and the
      dates it was granted, argued and decided; for the term in progress, the
      cases themselves and the justices' votes as they come. Licence: CC BY-NC.
  The Court's own docket (supremecourt.gov)
      One file per docket number, from the 2017 term on, listing every filing
      and order. It is where a pending case's stage is read from, and the only
      source for emergency applications (docket numbers such as 25A400).

And the justices come from the Federal Judicial Center's biographical
directory (fjc.gov), which is in the public domain.

Tables, in data/:
  cases.parquet            one row per case
  votes.parquet            one row per case and justice
  justices.parquet         one row per appointment to the Court, 1789 on
  applications.parquet     one row per application, 2017 on
  docket_entries.parquet   the dated filings and orders of cases and applications, 2017 on
  terms.parquet            one row per term: how much came in, how much was decided

Two ways to run it:

    python build_supreme_court.py --base
        Everything from scratch: reads the database's files (downloading them
        if they are not in --raw), every term's list from Oyez, and every
        docket file since 2017. Takes an hour or two, nearly all of it the
        dockets. Run it by hand when the database publishes a new release.

    python build_supreme_court.py
        The daily run: starts from the published tables and refreshes only what
        can change: the terms the database does not cover yet, the dockets of
        cases still pending, and applications that are new or unresolved. A few
        minutes. If the Court's site cannot be reached the rest still runs.

    --no-upload    write the tables but do not publish them
    --write-card   publish the dataset card as well as the tables
"""

import argparse
import concurrent.futures
import html
import json
import logging
import re
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

import build_federal_bills as bills

log = logging.getLogger(__name__)

HF_REPO = "chrissoria/supreme-court-cases"
OUT_DIR = bills.SCRIPT_DIR / "scotus"
CARD_FILE = bills.SCRIPT_DIR / "README_supreme_court.md"
TABLES = ("cases", "votes", "justices", "applications", "docket_entries", "terms")

SCDB_RELEASE = "2026_01"  # the release --base reads; change it when a new one is published
SCDB_FILE = "http://scdb.wustl.edu/_brickFiles/{release}/SCDB_{release}_{kind}Centered_Citation.dta.zip"
FJC_FILE = "https://www.fjc.gov/sites/default/files/history/judges.csv"
OYEZ = "https://api.oyez.org"
OYEZ_FIRST_TERM = 1955  # earlier cases are kept under one heading
OYEZ_EARLY = "1940-1955"
DOCKET_FILE = "https://www.supremecourt.gov/RSS/Cases/JSON/{number}.json"
DOCKET_PAGE = "https://www.supremecourt.gov/search.aspx?filename=/docket/docketfiles/html/public/{number}.html"
FIRST_DOCKET_SERIES = 17  # the Court publishes docket files from the 2017 term on
HEADERS = {"User-Agent": "cat-pol-datasets (+https://github.com/chrissoria/cat-pol-datasets)"}
DOCKET_PAUSE = 0.15  # seconds between docket files, each worker
MISSES_TO_STOP = 15  # docket numbers in a row with no file before a series is taken to have ended
RECENT_DAYS = 45  # a resolved application or decided case is looked at again for this long

CASE_COLUMNS = [
    "id", "term", "docket", "name", "stage", "date_granted", "date_argued", "date_decided", "citation",
    "decision_type", "disposition", "winner", "majority_votes", "minority_votes", "majority_author",
    "issue_area", "issue", "law_type", "law", "declared_unconstitutional", "precedent_altered",
    "lower_court", "jurisdiction", "chief_justice", "scdb_direction", "question", "description",
    "executive_orders", "oyez_url", "justia_url", "docket_url", "scdb_id", "source",
]
VOTE_COLUMNS = ["case_id", "term", "justice_id", "side", "vote", "wrote_opinion", "scdb_direction", "source"]
APPLICATION_COLUMNS = [
    "docket", "term", "title", "applicant", "respondent", "kind", "capital_case", "date_filed", "submitted_to",
    "referred_to_court", "outcome", "decided_by", "date_resolved", "lower_court", "lower_court_case", "linked",
    "executive_orders", "n_entries", "last_entry_date", "url",
]
ENTRY_COLUMNS = ["docket", "kind", "seq", "date", "text"]

# The database's codes, in words. The long lists (issues, laws, courts) are read from its own labels.
ISSUE_AREAS = {
    1: "Criminal procedure", 2: "Civil rights", 3: "First Amendment", 4: "Due process", 5: "Privacy",
    6: "Attorneys", 7: "Unions", 8: "Economic activity", 9: "Judicial power", 10: "Federalism",
    11: "Interstate relations", 12: "Federal taxation", 13: "Miscellaneous", 14: "Private action",
}
DISPOSITIONS = {
    1: "stay, petition or motion granted", 2: "affirmed", 3: "reversed", 4: "reversed and remanded",
    5: "vacated and remanded", 6: "affirmed and reversed in part", 7: "affirmed and reversed in part, and remanded",
    8: "vacated", 9: "petition denied or appeal dismissed", 10: "certification to or from a lower court",
    11: "no disposition",
}
DECISION_TYPES = {
    1: "opinion of the Court", 2: "per curiam, without oral argument", 4: "decree", 5: "equally divided vote",
    6: "per curiam, after oral argument", 7: "judgment of the Court", 8: "seriatim",
}
WINNERS = {0: "respondent", 1: "petitioner", 2: "unclear"}
JURISDICTIONS = {
    1: "certiorari", 2: "appeal", 3: "bail", 4: "certification", 5: "docketing fee", 6: "rehearing or reargument",
    7: "injunction", 8: "mandamus", 9: "original", 10: "prohibition", 12: "stay", 13: "writ of error",
    14: "habeas corpus", 15: "other",
}
LAW_TYPES = {
    1: "Constitution", 2: "constitutional amendment", 3: "federal statute", 4: "court rules", 5: "other",
    6: "infrequently litigated statute", 7: "infrequently litigated statute", 8: "state or local law",
    9: "no legal provision",
}
UNCONSTITUTIONAL = {1: "", 2: "federal law", 3: "state law", 4: "local law"}
DIRECTIONS = {1: "conservative", 2: "liberal", 3: "unspecifiable"}
VOTES = {
    1: "majority", 2: "dissent", 3: "regular concurrence", 4: "special concurrence", 5: "judgment of the Court",
    6: "dissent from denial of certiorari", 7: "jurisdictional dissent", 8: "equally divided",
}


class Unreachable(RuntimeError):
    """A host did not answer, or refused: not the same as a file that does not exist."""


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def current_term(day=None):
    """The term in progress: it opens on the first Monday of October and is named for that year."""
    day = day or today()
    year, month = int(day[:4]), int(day[5:7])
    return year if month >= 10 else year - 1


def get_json(url, retries=3, timeout=30):
    """The JSON at `url`; None if there is no such file. Raises Unreachable when the host will not answer."""
    problem = ""
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=HEADERS, timeout=timeout)
            if response.status_code == 404:
                return None
            if response.status_code == 200:
                return response.json()
            problem = f"HTTP {response.status_code}"
        except (requests.RequestException, ValueError) as e:
            problem = type(e).__name__
        time.sleep(2 * (attempt + 1))
    raise Unreachable(f"{url.split('/')[2]}: {problem}")


def plain(markup):
    """Text out of a snippet of HTML."""
    text = re.sub(r"<[^>]+>", " ", markup or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def docket_key(docket):
    """A docket number as both sources would write it: "22O141", "No. 141, Orig." and "141-orig" all agree."""
    text = str(docket).strip().lower()
    original = re.fullmatch(r"(?:no\.\s*)?(?P<prefix>22\s*o\s*)?(?P<number>\d+)\s*,?\s*-?\s*(?P<word>orig\.?)?", text)
    if original and (original.group("prefix") or original.group("word")):
        return f"{int(original.group('number'))}-orig"
    return re.sub(r"[^a-z0-9-]+", "", text)


_ORDER = re.compile(r"\b(?:Executive Order|E\.\s?O\.)(?:\s+No\.?)?\s+(\d{4,5})\b", re.I)


def orders_in(*texts):
    """Executive order numbers named in the text, as a JSON list: the thread to the White House data."""
    found = sorted({number for text in texts for number in _ORDER.findall(text or "")}, key=int)
    return json.dumps(found)


def iso(value):
    """A date in any of the forms the sources use, as YYYY-MM-DD; "" if there is none."""
    if value is None or value == "" or (isinstance(value, float) and value != value):
        return ""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d")
    stamp = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(stamp) else stamp.strftime("%Y-%m-%d")


# ── The Supreme Court Database ───────────────────────────────────────────────


def download_scdb(raw_dir):
    """Fetch the release's two files into raw_dir unless they are there. Returns their paths."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for kind in ("case", "justice"):
        name = f"SCDB_{SCDB_RELEASE}_{kind}Centered_Citation.dta"
        paths[kind] = raw_dir / name
        if paths[kind].exists():
            continue
        archive = raw_dir / f"{name}.zip"
        response = requests.get(SCDB_FILE.format(release=SCDB_RELEASE, kind=kind), headers=HEADERS, timeout=180)
        response.raise_for_status()
        archive.write_bytes(response.content)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extract(name, raw_dir)
        log.info(f"Downloaded {name}")
    return paths


def read_stata(path, columns=None):
    """A Stata file as it is stored (codes, not labels), with its sets of value labels."""
    with pd.read_stata(path, iterator=True) as reader:
        return reader.read(convert_categoricals=False, columns=columns), reader.value_labels()


def worded(series, words):
    """Codes into words; a code with no word, or no code at all, becomes ""."""
    clean = {int(code): text.replace("Â¤", "§").replace("¤", "§").strip() for code, text in words.items()}
    return series.map(lambda code: clean.get(int(code), "") if code == code and code is not None else "")


def scdb_cases(path):
    """The database's cases in this dataset's columns. Returns the table and {database id: case id}."""
    df, labels = read_stata(path)
    df = df.sort_values(["dateDecision", "caseId"]).reset_index(drop=True)
    docket = df["docket"].fillna("").astype(str).str.strip()
    ids, seen = [], {}
    for term, number, scdb_id in zip(df["term"], docket, df["caseId"]):
        base = f"{int(term)}-{slug(number)}" if number else f"scdb-{scdb_id}"
        seen[base] = seen.get(base, 0) + 1  # the same number twice in a term: a case decided in two parts
        ids.append(base if seen[base] == 1 else f"{base}-{'abcdefgh'[seen[base] - 1]}")
    citation = df["usCite"].where(df["usCite"].fillna("") != "", df["sctCite"]).fillna("")
    cases = pd.DataFrame({
        "id": ids,
        "term": df["term"].astype(int),
        "docket": docket,
        "name": df["caseName"].fillna("").map(tidy_name),
        "stage": "decided",
        "date_granted": "",
        "date_argued": df["dateArgument"].map(iso),
        "date_decided": df["dateDecision"].map(iso),
        "citation": citation,
        "decision_type": worded(df["decisionType"], DECISION_TYPES),
        "disposition": worded(df["caseDisposition"], DISPOSITIONS),
        "winner": worded(df["partyWinning"], WINNERS),
        "majority_votes": df["majVotes"].fillna(0).astype(int),
        "minority_votes": df["minVotes"].fillna(0).astype(int),
        "majority_author": worded(df["majOpinWriter"], labels["varJustices"]),
        "issue_area": worded(df["issueArea"], ISSUE_AREAS),
        "issue": worded(df["issue"], labels["varIssues"]),
        "law_type": worded(df["lawType"], LAW_TYPES),
        "law": worded(df["lawSupp"], labels["varLegalProvisions"]),
        "declared_unconstitutional": worded(df["declarationUncon"], UNCONSTITUTIONAL),
        "precedent_altered": df["precedentAlteration"].fillna(0).astype(int).astype(bool),
        "lower_court": worded(df["caseSource"], labels["varCaseSources"]),
        "jurisdiction": worded(df["jurisdiction"], JURISDICTIONS),
        "chief_justice": df["chief"].fillna(""),
        "scdb_direction": worded(df["decisionDirection"], DIRECTIONS),
        "question": "",
        "description": "",
        "executive_orders": "[]",
        "oyez_url": "",
        "justia_url": "",
        "docket_url": "",
        "scdb_id": df["caseId"],
        "source": "scdb",
    })
    return cases[CASE_COLUMNS], dict(zip(df["caseId"], ids))


def tidy_name(name):
    """ "LEARNING RESOURCES, INC. v. TRUMP" as "Learning Resources, Inc. v. Trump"."""
    capitals, small_letters = sum(ch.isupper() for ch in name), sum(ch.islower() for ch in name)
    if small_letters > capitals * 0.3:
        return name  # already in mixed case; "v." and "et al." in a name set in capitals do not make it so
    small = {"v.", "of", "the", "and", "for", "in", "on", "et", "al.", "ex", "rel.", "de", "la", "a", "to"}
    words = []
    for index, word in enumerate(name.lower().split()):
        if word in small and index:
            words.append(word)
        elif re.fullmatch(r"(?:[a-z]\.)+,?", word) or word.rstrip(",.") in {"u.s", "usa", "llc", "nlrb", "ins", "fcc", "epa", "irs", "sec", "ftc", "icc", "ii", "iii", "iv"} or ("&" in word and len(word.rstrip(",.")) <= 5):  # AT&T
            words.append(word.upper())
        else:
            word = re.sub(r"(^|[-(/])([a-z])", lambda m: m.group(1) + m.group(2).upper(), word)
            words.append(re.sub(r"^(Mc|[OD]')([a-z])", lambda m: m.group(1) + m.group(2).upper(), word))  # McCarthy, O'Connor
    return " ".join(words)


def scdb_votes(path, case_ids):
    df, _ = read_stata(path, columns=["caseId", "term", "justiceName", "vote", "opinion", "direction", "majority"])
    df = df[df["caseId"].isin(case_ids)]
    votes = pd.DataFrame({
        "case_id": df["caseId"].map(case_ids),
        "term": df["term"].astype(int),
        "justice_id": df["justiceName"],
        "side": df["majority"].map({1: "dissent", 2: "majority"}).fillna(""),
        "vote": worded(df["vote"], VOTES),
        "wrote_opinion": df["opinion"].fillna(1).astype(int) >= 2,
        "scdb_direction": worded(df["direction"], {1: "conservative", 2: "liberal"}),
        "source": "scdb",
    })
    return votes[VOTE_COLUMNS].reset_index(drop=True)


# ── The justices ─────────────────────────────────────────────────────────────


def justice_key(first, middle, last):
    """ "Sandra", "Day", "O'Connor" as the database writes her: SDOConnor."""
    initials = "".join(part[0] for part in f"{first} {middle}".replace(".", " ").split() if part)
    return initials + re.sub(r"[^A-Za-z]", "", last)


def justices_table(csv_path, scdb_names):
    """One row per appointment to the Court. A justice the database knows keeps the database's name for them."""
    people = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig").fillna("")
    people = people.apply(lambda column: column.str.strip())
    rows = []
    for person in people.to_dict("records"):
        for slot in range(1, 7):
            if person.get(f"Court Name ({slot})") != "Supreme Court of the United States":
                continue
            last = re.sub(r"[^A-Za-z]", "", person["Last Name"])
            # A justice who retires takes senior status rather than leaving the bench outright.
            retired = iso(person.get(f"Senior Status Date ({slot})"))
            ended = iso(person.get(f"Termination Date ({slot})")) or retired
            # The database's name ends in the surname and starts with the first initial; two justices
            # can share both (the Harlans), so the one who sat after 1946 is the one it means.
            matches = [name for name in scdb_names
                       if re.sub(r"\d+$", "", name).endswith(last) and name[0] == person["First Name"][:1]
                       and len(re.sub(r"\d+$", "", name)) - len(last) <= 3]
            known = matches[0] if len(matches) == 1 and (not ended or ended >= "1946") else ""
            rows.append({
                "justice_id": known or justice_key(person["First Name"], person["Middle Name"], person["Last Name"]),
                "name": " ".join(part for part in (person["First Name"], person["Middle Name"], person["Last Name"]) if part)
                        + (f", {person['Suffix']}" if person["Suffix"] else ""),
                "last_name": person["Last Name"],
                "title": person.get(f"Appointment Title ({slot})", ""),
                "appointed_by": person.get(f"Appointing President ({slot})", ""),
                "appointing_party": person.get(f"Party of Appointing President ({slot})", ""),
                "nominated": iso(person.get(f"Nomination Date ({slot})")),
                "confirmed": iso(person.get(f"Confirmation Date ({slot})")),
                "senate_vote": person.get(f"Ayes/Nays ({slot})", ""),
                "start": iso(person.get(f"Commission Date ({slot})")) or iso(person.get(f"Recess Appointment Date ({slot})")),
                "end": ended,
                "how_ended": person.get(f"Termination ({slot})", "") or ("Retirement" if retired else ""),
                "serving": not ended,
                "born": person["Birth Year"],
                "died": person["Death Year"],
                "gender": person["Gender"],
                "race_ethnicity": person["Race or Ethnicity"],
                "in_database": bool(known),
            })
    table = pd.DataFrame(rows).sort_values(["start", "last_name"]).reset_index(drop=True)
    # Someone made Chief Justice from within the Court has two rows; only the later one is still running.
    later = table.groupby("justice_id")["start"].transform("max")
    table["serving"] = table["serving"] & (table["start"] == later)
    return table


def justice_for(name, justices, on=""):
    """The id of the justice Oyez calls `name` ("John G. Roberts, Jr."), among those sitting on the day."""
    words = re.sub(r",.*$", "", name).replace(".", " ").split()
    if not words:
        return ""
    first, last = words[0], re.sub(r"[^A-Za-z]", "", words[-1])
    pool = justices[justices["last_name"].str.replace(r"[^A-Za-z]", "", regex=True) == last]
    if on:
        sitting = pool[(pool["start"] <= on) & ((pool["end"] == "") | (pool["end"] >= on))]
        pool = sitting if len(sitting) else pool
    exact = pool[pool["name"].str.startswith(first)]
    pool = exact if len(exact) else pool
    return pool["justice_id"].iloc[-1] if len(pool) else ""


# ── Oyez ─────────────────────────────────────────────────────────────────────


def oyez_list(term):
    return get_json(f"{OYEZ}/cases?per_page=0&filter=term:{term}", timeout=60) or []


def oyez_summary(item):
    """What the term list says of a case: its question, what was held, and when."""
    dates = {}
    for event in item.get("timeline") or []:
        if event and event.get("dates"):
            dates.setdefault(event.get("event", ""), iso(event["dates"][0]))
    docket = (item.get("docket_number") or "").strip()
    term = str(item.get("term") or "")
    decided = dates.get("Decided", "")
    if not term.isdigit():  # the early cases share a heading; take the term from the decision
        term = str(current_term(decided)) if decided else ""
    return {
        "term": int(term) if term.isdigit() else 0,
        "docket": docket,
        "key": docket_key(docket),
        "name": (item.get("name") or "").strip(),
        "question": plain(item.get("question")),
        "description": plain(item.get("description")),
        "date_granted": dates.get("Granted", "") or dates.get("Juris Postponed", ""),
        "date_argued": dates.get("Argued", ""),
        "date_decided": decided,
        "oyez_url": (item.get("href") or "").replace("api.oyez.org", "www.oyez.org"),
        "justia_url": item.get("justia_url") or "",
        "href": item.get("href") or "",
    }


def add_oyez(cases, summaries):
    """Fill in question, description, grant date and links for the database's cases, matched by term and docket."""
    by_key = {}
    for summary in summaries:
        if summary["key"]:
            by_key.setdefault((summary["term"], summary["key"]), summary)
    matched = 0
    columns = {name: cases[name].tolist() for name in ("question", "description", "date_granted", "oyez_url", "justia_url", "executive_orders")}
    for index, (term, docket, argued) in enumerate(zip(cases["term"], cases["docket"], cases["date_argued"])):
        key = docket_key(docket)
        # Oyez files a case under the term it was argued in, which can be the one before it was decided.
        found = by_key.get((term, key)) or by_key.get((term - 1, key)) if key else None
        if not found:
            continue
        matched += 1
        for name in ("question", "description", "date_granted", "oyez_url", "justia_url"):
            columns[name][index] = found[name]
        columns["executive_orders"][index] = orders_in(found["question"], found["description"])
    for name, values in columns.items():
        cases[name] = values
    return matched


def oyez_live_case(summary, justices):
    """A case the database does not have yet, from Oyez alone. Returns its row and its votes."""
    detail = get_json(summary["href"], timeout=60) or {}
    decision = next((d for d in detail.get("decisions") or [] if d), {})
    case_id = f"{summary['term']}-{slug(summary['docket'])}"
    votes, author = [], ""
    for cast in decision.get("votes") or []:
        who = justice_for((cast.get("member") or {}).get("name", ""), justices, summary["date_decided"])
        if not who:
            continue
        kind = (cast.get("opinion_type") or "none").lower()
        side = "majority" if cast.get("vote") == "majority" else "dissent" if cast.get("vote") == "minority" else ""
        if kind == "majority":
            author = who
        votes.append({
            "case_id": case_id, "term": summary["term"], "justice_id": who, "side": side,
            "vote": kind if kind != "none" else side, "wrote_opinion": kind != "none", "scdb_direction": "", "source": "oyez",
        })
    decided = bool(summary["date_decided"])
    facts, conclusion = plain(detail.get("facts_of_the_case")), plain(detail.get("conclusion"))
    winner = (decision.get("winning_party") or "").strip()
    first, second = (detail.get("first_party") or "").strip(), (detail.get("second_party") or "").strip()
    row = {
        "id": case_id,
        "term": summary["term"],
        "docket": summary["docket"],
        "name": summary["name"],
        "stage": "decided" if decided else "granted" if not summary["date_argued"] else "argued" if summary["date_argued"] <= today() else "set for argument",
        "date_granted": summary["date_granted"],
        "date_argued": summary["date_argued"],
        "date_decided": summary["date_decided"],
        "citation": "",
        "decision_type": (decision.get("decision_type") or "").strip(),
        "disposition": "",
        "winner": "petitioner" if winner and winner == first else "respondent" if winner and winner == second else "",
        "majority_votes": int(decision.get("majority_vote") or 0),
        "minority_votes": int(decision.get("minority_vote") or 0),
        "majority_author": author,
        "issue_area": "", "issue": "", "law_type": "", "law": "", "declared_unconstitutional": "",
        "precedent_altered": False,
        "lower_court": ((detail.get("lower_court") or {}).get("name") or "").strip(),
        "jurisdiction": plain(detail.get("manner_of_jurisdiction")).replace("Writ of ", "").lower(),
        "chief_justice": "",
        "scdb_direction": "",
        "question": summary["question"],
        "description": summary["description"] or plain(decision.get("description")),
        "executive_orders": orders_in(summary["question"], summary["description"], facts, conclusion),
        "oyez_url": summary["oyez_url"],
        "justia_url": summary["justia_url"],
        "docket_url": "",
        "scdb_id": "",
        "source": "oyez",
    }
    return row, votes


def live_cases(terms, justices, known_keys):
    """Cases of `terms` from Oyez that the database's rows do not already cover."""
    rows, votes = [], []
    for term in terms:
        for item in oyez_list(term):
            summary = oyez_summary(item)
            summary["term"] = summary["term"] or term
            if not summary["docket"] or (summary["term"], summary["key"]) in known_keys:
                continue
            row, cast = oyez_live_case(summary, justices)
            rows.append(row)
            votes.extend(cast)
    return pd.DataFrame(rows, columns=CASE_COLUMNS), pd.DataFrame(votes, columns=VOTE_COLUMNS)


# ── The Court's docket ───────────────────────────────────────────────────────


def docket_number(docket):
    """The docket number as the Court's file is named, or "" if it publishes none for it (before 2017)."""
    text = str(docket).strip().upper().replace(" ", "")
    original = re.fullmatch(r"(?:NO\.)?(\d+),?-?ORIG\.?", text)
    if original:
        return f"22O{original.group(1)}"  # original cases keep the prefix 22O whatever the year
    match = re.fullmatch(r"(\d\d)([-AOM])(\d+)", text)
    # Two digits are a year: 17 on is published, and "74-54" is a case of 1974, not of the future.
    if not match or (match.group(2) != "O" and not FIRST_DOCKET_SERIES <= int(match.group(1)) <= current_term() % 100 + 1):
        return ""
    return text


CACHE_DIR = None  # set for --base: docket files are kept here, so a run that stops can carry on
CACHE_DAYS = 3  # a kept file older than this is read again: dockets change


def fetch_docket(number):
    """One docket file, or None if the Court has none under that number."""
    kept = CACHE_DIR / f"{number}.json" if CACHE_DIR else None
    if kept is not None and kept.exists() and time.time() - kept.stat().st_mtime < CACHE_DAYS * 86400:
        return json.loads(kept.read_text())
    try:
        data = get_json(DOCKET_FILE.format(number=number))
    except Unreachable:
        time.sleep(20)  # one bad answer is not the site being down
        data = get_json(DOCKET_FILE.format(number=number))
    time.sleep(DOCKET_PAUSE)
    if kept is not None:
        kept.write_text(json.dumps(data))
    return data


def entries_of(number, data, kind):
    rows = []
    for seq, entry in enumerate(data.get("ProceedingsandOrder") or []):
        rows.append({"docket": number, "kind": kind, "seq": seq, "date": iso(entry.get("Date")), "text": plain(entry.get("Text"))})
    return rows


# How far a case has come, read from its docket. Later lines win; a motion being granted is not the petition.
_STAGES = [
    ("conference", re.compile(r"^DISTRIBUTED for Conference", re.I)),
    ("granted", re.compile(r"^Petition\b.*\bGRANTED|^Probable jurisdiction (?:is )?noted|jurisdiction is POSTPONED|"
                           r"^Application\b.*treated as a petition.*\bGRANTED|^Motion for leave to file a bill of complaint GRANTED", re.I)),
    ("set for argument", re.compile(r"^SET FOR (?:RE)?ARGUMENT", re.I)),
    ("argued", re.compile(r"^(?:Rea|A)rgued\b", re.I)),
    ("decided", re.compile(r"^(?:Judgment|Adjudged)\b.*\b(?:AFFIRMED|REVERSED|VACATED|DISMISSED|entered)|"
                           r"^Writ of certiorari\b.*\bDISMISSED|dismissed as improvidently granted|^Appeal\b.*\bDISMISSED|"
                           r"^Decree entered|^Exceptions? .*(?:overruled|sustained)", re.I)),
]
_DENIED = re.compile(r"^Petition\b.*\bDENIED|^Petition\b.*\bDISMISSED", re.I)
STAGE_ORDER = ["filed", "conference", "granted", "set for argument", "argued", "decided"]


def stage_of(entries):
    """(stage, {stage: the first date it was reached}) from a case's docket entries, oldest first."""
    reached = {"filed": entries[0]["date"]} if entries else {}
    denied = ""
    for entry in entries:
        for stage, pattern in _STAGES:
            if pattern.search(entry["text"]):
                reached.setdefault(stage, entry["date"])
        if _DENIED.search(entry["text"]):
            denied = entry["date"]
    furthest = max(reached, key=STAGE_ORDER.index) if reached else ""
    if denied and STAGE_ORDER.index(furthest or "filed") < STAGE_ORDER.index("granted"):
        return "denied", {**reached, "denied": denied}
    return furthest, reached


def ruling_in(entries):
    """(disposition, winner) as a case's docket records them, in the database's words; ("", "") if it records none.

    Where one entry disposes of several cases, the first ruling is the one for the docket it sits on.
    """
    for entry in entries:
        text = entry["text"]
        ruled = re.search(r"\b(AFFIRMED|REVERSED|VACATED|DISMISSED)\b", text)  # the docket sets the ruling in capitals
        if not ruled or not _STAGES[-1][1].search(text):
            continue
        clause = text[ruled.start():].split(";")[0]
        remanded = ", and remanded" if re.search(r"\bREMANDED\b", clause) else ""
        if re.search(r"\bin part\b", clause, re.I) and "AFFIRMED" in clause and re.search(r"REVERSED|VACATED", clause):
            return "affirmed and reversed in part" + remanded, ""
        word = ruled.group(1).lower()
        if word == "dismissed":
            return "petition denied or appeal dismissed", ""
        if word == "affirmed":
            return "affirmed", "respondent"
        return word + remanded.replace(", and", " and"), "petitioner"
    return "", ""


_KINDS = [
    ("extension of time", r"extend(?:ing)? the time|extension of time|further extend"),
    ("stay of execution", r"stay of execution"),
    ("stay", r"\bstay\b|recall and stay|stay(?:ing)? the mandate"),
    ("injunction", r"injuncti"),
    ("vacate", r"\bvacate\b"),
    ("bail", r"\bbail\b|release pending"),
    ("certificate of appealability", r"certificate of appealability"),
    ("word or page limit", r"word limit|page limit|in excess of"),
]
_JUSTICE = r"(?:The Chief Justice|Justice [A-Z][A-Za-z']+)"
_RULING = r"(granted in part|granted|denied|dismissed)"
# What became of an application, most certain reading first. "The stay granted by the Fifth Circuit" is not a ruling.
_RULINGS = [
    re.compile(rf"^Applications?(?: \([^)]+\))?(?: for [^,.]{{0,80}}?)?(?: \([^)]+\))? {_RULING}\b", re.I),
    re.compile(rf"referred to the Court,? (?:is |are )?{_RULING}\b", re.I),
    re.compile(rf"\b(?:application|motion)[^.]{{0,160}}\b(?:is|are) {_RULING}\b", re.I),
    re.compile(r"^Application(?: \([^)]+\))?[^.]{0,60}\b(withdrawn)\b", re.I),
    re.compile(r"\b(withdraw)(?:ing|s)? the application", re.I),
    re.compile(r"^Application(?: \([^)]+\))? (completed|closed)\b", re.I),  # ended with no ruling: overtaken by events
]
_OUTCOME_WORDS = {"withdraw": "withdrawn", "completed": "closed"}


def application_row(number, data):
    """An application in one row: what was asked, of whom, and what came of it."""
    entries = entries_of(number, data, "application")
    first = entries[0]["text"] if entries else ""
    kind = next((name for name, pattern in _KINDS if re.search(pattern, first, re.I)), "other")
    outcome = decided_by = resolved = submitted = ""
    referred = False
    for entry in entries:
        text = entry["text"]
        to = re.search(rf"(?:submitted|presented) to ({_JUSTICE})", text)
        if to and not submitted:
            submitted = to.group(1)
        if re.search(r"referred to the Court", text, re.I):
            referred = True
        if re.search(r"\bsubmitted to\b", text) and not re.search(r"referred to the Court", text, re.I):
            continue  # a filing, whatever it says about the order it complains of
        verdict = next((found for found in (pattern.search(text) for pattern in _RULINGS) if found), None)
        if verdict:
            outcome = _OUTCOME_WORDS.get(verdict.group(1).lower(), verdict.group(1).lower())
            by = re.search(rf"{re.escape(verdict.group(1))} by ({_JUSTICE}|the Court)", text, re.I)
            ruled = outcome not in ("withdrawn", "closed")
            decided_by = by.group(1) if by else "the Court" if ruled and (referred or "the Court" in text) else ""
            resolved = entry["date"]
    applicant = re.sub(r",?\s*(?:et al\.,?\s*)?Applicants?$", lambda m: ", et al." if "et al" in m.group(0) else "", data.get("PetitionerTitle") or "").strip()
    respondent = (data.get("RespondentTitle") or "").strip()
    return {
        "docket": number,
        "term": int(data.get("sJsonTerm") or 0),
        "title": f"{applicant} v. {respondent}" if respondent else applicant,
        "applicant": applicant,
        "respondent": respondent,
        "kind": kind,
        "capital_case": bool(data.get("bCapitalCase")),
        "date_filed": entries[0]["date"] if entries else iso(data.get("DocketedDate")),
        "submitted_to": submitted,
        "referred_to_court": referred,
        "outcome": outcome,
        "decided_by": decided_by,
        "date_resolved": resolved,
        "lower_court": (data.get("LowerCourt") or "").strip(),
        "lower_court_case": (data.get("LowerCourtCaseNumbers") or "").strip(" ()"),
        "linked": re.sub(r"^Linked with\s*", "", data.get("Links") or "").strip(),
        "executive_orders": orders_in(*(entry["text"] for entry in entries)),
        "n_entries": len(entries),
        "last_entry_date": entries[-1]["date"] if entries else "",
        "url": DOCKET_PAGE.format(number=number.lower()),
    }, entries


def fetch_many(numbers, workers=1):
    """{number: file or None} for many docket numbers. Raises Unreachable if the site stops answering."""
    if workers <= 1:
        return {number: fetch_docket(number) for number in numbers}
    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        return dict(zip(numbers, pool.map(fetch_docket, numbers)))


def new_applications(series, after, workers=1):
    """Applications of a series numbered above `after`, until the numbers run out."""
    found, number, misses = {}, after, 0
    while misses < MISSES_TO_STOP:
        batch = [f"{series}A{n}" for n in range(number + 1, number + 1 + max(workers * 5, MISSES_TO_STOP))]
        for name, data in fetch_many(batch, workers).items():
            if data is None:
                misses += 1
                if misses >= MISSES_TO_STOP:
                    break
            else:
                misses = 0
                found[name] = data
        number += len(batch)
    return found


def highest_number(series, first):
    """The highest docket number in use from `first` up in a series: how many petitions came in. 0 if none."""
    def used(n):
        return any(fetch_docket(f"{series}-{n + skip}") is not None for skip in range(3))  # a number can be skipped

    if not used(first):
        return 0
    low, step = first, 64
    while used(low + step):
        low += step
        step *= 2
    high = low + step
    while high - low > 1:
        middle = (low + high) // 2
        if used(middle):
            low = middle
        else:
            high = middle
    return low


# ── Putting it together ──────────────────────────────────────────────────────


def read_published():
    """The tables as published. Always from the Hub: a local copy may be older than yesterday's run."""
    from huggingface_hub import hf_hub_download
    return {name: pd.read_parquet(hf_hub_download(HF_REPO, f"data/{name}.parquet", repo_type="dataset", token=bills.HF_TOKEN))
            for name in TABLES}


def refresh_live(tables):
    """Rebuild the cases of the terms the database does not cover yet, from Oyez. Returns how many there are."""
    cases, votes = tables["cases"], tables["votes"]
    settled = cases[cases["source"] == "scdb"]
    last_coded = int(settled["term"].max())
    terms = list(range(last_coded + 1, current_term() + 1))
    known = {(term, docket_key(docket)) for term, docket in zip(settled["term"], settled["docket"])}
    known |= {(term + 1, key) for term, key in known}  # argued in one term, decided (and coded) in the next
    fresh, cast = live_cases(terms, tables["justices"], known)
    if terms and fresh.empty and not cases[cases["source"] == "oyez"].empty:
        raise RuntimeError("Oyez listed no cases for the terms in progress; keeping the ones already held")
    kept = cases[cases["source"] == "scdb"]
    kept_votes = votes[votes["source"] == "scdb"]
    tables["cases"] = pd.concat([kept, fresh], ignore_index=True) if len(fresh) else kept.reset_index(drop=True)
    tables["votes"] = pd.concat([kept_votes, cast], ignore_index=True) if len(cast) else kept_votes.reset_index(drop=True)
    return len(fresh)


def replace_entries(entries, fresh):
    """`entries` with every docket in `fresh` replaced by its new rows."""
    fresh = pd.DataFrame(fresh, columns=ENTRY_COLUMNS)
    if fresh.empty:
        return entries
    kept = entries[~entries["docket"].isin(set(fresh["docket"]))] if len(entries) else entries
    return pd.concat([kept, fresh], ignore_index=True)


def refresh_dockets(tables, everything=False, workers=1):
    """Read the Court's docket files into the tables: stages of pending cases, and applications.

    `everything` reads every file since 2017 (the first build); otherwise only what can have changed.
    Returns counts for the log. Raises Unreachable if the Court's site does not answer.
    """
    cases, applications, entries = tables["cases"], tables["applications"], tables["docket_entries"]
    recent = (pd.Timestamp(today()) - pd.Timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")

    # Cases: the docket says how far a pending one has come.
    wanted = {}
    first_term = 2000 + FIRST_DOCKET_SERIES
    for case_id, term, docket, stage, decided in zip(cases["id"], cases["term"], cases["docket"], cases["stage"], cases["date_decided"]):
        number = docket_number(docket) if term >= first_term else ""
        if number and (everything or stage != "decided" or decided >= recent):
            wanted[case_id] = number
    files = {number: data for number, data in fetch_many(sorted(set(wanted.values())), workers).items() if data}
    entries = replace_entries(entries, [row for number, data in files.items() for row in entries_of(number, data, "case")])
    fresh = []
    # A case the database has not coded yet is rebuilt from Oyez on every run, so what its docket adds is
    # read from the entries held here, not only from the files fetched today.
    for case_id, term, docket, source in zip(cases["id"], cases["term"], cases["docket"], cases["source"]):
        if source != "scdb" and term >= first_term and docket_number(docket):
            wanted.setdefault(case_id, docket_number(docket))
    held = entries[(entries["kind"] == "case") & entries["docket"].isin(set(wanted.values()))].sort_values(["docket", "seq"]) if len(entries) else entries
    by_number = {number: rows.to_dict("records") for number, rows in held.groupby("docket")} if len(held) else {}
    names = ("stage", "date_granted", "date_argued", "date_decided", "lower_court", "docket_url", "disposition", "winner")
    updates = {name: dict(zip(cases["id"], cases[name])) for name in names}
    for case_id, number in wanted.items():
        if number not in by_number:
            continue
        stage, reached = stage_of(by_number[number])
        updates["docket_url"][case_id] = DOCKET_PAGE.format(number=number.lower())
        for column, key in (("date_granted", "granted"), ("date_argued", "argued"), ("date_decided", "decided")):
            if not updates[column][case_id] and reached.get(key):
                updates[column][case_id] = reached[key]
        if not updates["lower_court"][case_id] and number in files:
            updates["lower_court"][case_id] = (files[number].get("LowerCourt") or "").strip()
        # The docket runs ahead of Oyez for a case in progress, never behind a decision already recorded.
        if updates["stage"][case_id] != "decided" and stage in STAGE_ORDER and STAGE_ORDER.index(stage) >= STAGE_ORDER.index("granted"):
            updates["stage"][case_id] = stage
        if updates["stage"][case_id] == "decided" and not updates["disposition"][case_id]:
            updates["disposition"][case_id], won = ruling_in(by_number[number])
            updates["winner"][case_id] = updates["winner"][case_id] or won
    cases = cases.assign(**{name: cases["id"].map(values) for name, values in updates.items()})

    # Applications: the unresolved, the lately resolved, and whatever has been filed since.
    series_now = current_term() % 100
    all_series = range(FIRST_DOCKET_SERIES, series_now + 1) if everything else (series_now - 1, series_now)
    held = {}
    if len(applications):
        for docket, outcome, last in zip(applications["docket"], applications["outcome"], applications["last_entry_date"]):
            held[docket] = bool(outcome) and last < recent
    again = [docket for docket, closed in held.items() if not closed and int(docket[:2]) in all_series]
    found = {number: data for number, data in fetch_many(again, workers).items() if data}
    for series in all_series:
        top = max((int(docket.split("A")[1]) for docket in held if docket.startswith(f"{series}A")), default=0)
        found.update(new_applications(series, top, workers))
    rows = []
    for number, data in found.items():
        row, its_entries = application_row(number, data)
        rows.append(row)
        fresh.extend(its_entries)
    new_rows = pd.DataFrame(rows, columns=APPLICATION_COLUMNS)
    if len(new_rows):
        kept = applications[~applications["docket"].isin(set(new_rows["docket"]))] if len(applications) else applications
        applications = pd.concat([kept, new_rows], ignore_index=True)
    applications = applications.assign(_series=applications["docket"].str[:2].astype(int), _n=applications["docket"].str.split("A").str[1].astype(int)) \
        .sort_values(["_series", "_n"]).drop(columns=["_series", "_n"]).reset_index(drop=True) if len(applications) else applications

    tables["cases"], tables["applications"] = cases, applications
    tables["docket_entries"] = replace_entries(entries, fresh).sort_values(["docket", "seq"]).reset_index(drop=True)
    return {"case_dockets": len(files), "applications_read": len(found), "new_applications": len(found) - len(again)}


def terms_table(tables, previous=None, count_petitions=()):
    """One row per term. Petition counts come from the docket numbers in use, for the series in `count_petitions`."""
    cases, applications = tables["cases"], tables["applications"]
    chiefs = cases[cases["chief_justice"] != ""].groupby("term")["chief_justice"].agg(lambda names: names.mode().iloc[0]).to_dict()
    decided = cases[cases["stage"] == "decided"].groupby("term").size().to_dict()
    listed = cases.groupby("term").size().to_dict()
    asked = applications.groupby("term").size().to_dict() if len(applications) else {}
    before = {} if previous is None or previous.empty else previous.set_index("term").to_dict("index")
    rows, last_chief = [], ""
    for term in sorted(set(listed) | set(asked)):
        if term < 1946:
            continue
        last_chief = chiefs.get(term, last_chief)
        was = before.get(term) or {}
        row = {"term": int(term), "chief_justice": last_chief, "cases": int(listed.get(term, 0)),
               "cases_decided": int(decided.get(term, 0)),
               # Empty, not zero, for the years before the Court published its docket files.
               "applications": int(asked.get(term, 0)) if term >= 2000 + FIRST_DOCKET_SERIES else None,
               "paid_petitions": None if pd.isna(was.get("paid_petitions")) else int(was["paid_petitions"]),
               "ifp_petitions": None if pd.isna(was.get("ifp_petitions")) else int(was["ifp_petitions"])}
        series = term % 100
        if term >= 2000 + FIRST_DOCKET_SERIES and series in count_petitions:
            row["paid_petitions"] = highest_number(series, 1)
            top = highest_number(series, 5001)
            row["ifp_petitions"] = top - 5000 if top else 0
        rows.append(row)
    table = pd.DataFrame(rows)
    for name in ("applications", "paid_petitions", "ifp_petitions"):
        table[name] = table[name].astype("Int64")
    return table


def build_base(raw_dir, workers):
    """Everything from the sources. Returns the tables."""
    global CACHE_DIR
    paths = download_scdb(raw_dir)
    CACHE_DIR = raw_dir / "dockets"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cases, case_ids = scdb_cases(paths["case"])
    votes = scdb_votes(paths["justice"], case_ids)
    log.info(f"Database: {len(cases)} cases, terms {cases['term'].min()} to {cases['term'].max()}; {len(votes)} votes")

    judges = raw_dir / "judges.csv"
    if not judges.exists():
        response = requests.get(FJC_FILE, headers=HEADERS, timeout=180)
        response.raise_for_status()
        judges.write_bytes(response.content)
    justices = justices_table(judges, sorted(votes["justice_id"].unique()))
    unmatched = sorted(set(votes["justice_id"]) - set(justices["justice_id"]))
    if unmatched:
        raise RuntimeError(f"justices in the database with no row in the directory: {unmatched}")
    log.info(f"Justices: {justices['justice_id'].nunique()} people, {len(justices)} appointments, {int(justices['serving'].sum())} serving")

    summaries = []
    for term in [OYEZ_EARLY] + list(range(OYEZ_FIRST_TERM, int(cases["term"].max()) + 1)):
        summaries.extend(oyez_summary(item) for item in oyez_list(term))
    matched = add_oyez(cases, summaries)
    log.info(f"Oyez: {len(summaries)} cases listed, {matched} matched to the database")

    tables = {
        "cases": cases, "votes": votes, "justices": justices,
        "applications": pd.DataFrame(columns=APPLICATION_COLUMNS),
        "docket_entries": pd.DataFrame(columns=ENTRY_COLUMNS),
        "terms": pd.DataFrame(),
    }
    live = refresh_live(tables)
    log.info(f"Terms in progress: {live} cases from Oyez")
    counts = refresh_dockets(tables, everything=True, workers=workers)
    log.info(f"Dockets: {counts}")
    tables["terms"] = terms_table(tables, count_petitions=range(FIRST_DOCKET_SERIES, current_term() % 100 + 1))
    return tables, "ok"


def build_daily():
    tables = read_published()
    before = {name: len(table) for name, table in tables.items()}
    refresh_live(tables)
    dockets = "ok"
    try:
        counts = refresh_dockets(tables)
        log.info(f"Dockets: {counts}")
        series = current_term() % 100
        tables["terms"] = terms_table(tables, tables["terms"], count_petitions=(series - 1, series))
    except Unreachable as e:
        # The Court's site turns some networks away. Oyez still tells us what was argued and decided.
        log.error(f"Docket files not read ({e}); stages and applications are as of the last run that reached them")
        dockets = "unreachable"
        tables["terms"] = terms_table(tables, tables["terms"])
    settled = int((tables["cases"]["source"] == "scdb").sum())
    if settled < before["cases"] * 0.9 or len(tables["applications"]) < before["applications"] * 0.98:
        raise RuntimeError("the rebuilt tables are smaller than the published ones; not publishing")
    return tables, dockets


def write_tables(tables, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in TABLES:
        tables[name].to_parquet(out_dir / f"{name}.parquet", index=False)


def upload(out_dir, with_card):
    problem = bills.hf_write_problem(HF_REPO)
    if problem:
        log.error(f"Supreme Court tables not uploaded: {problem}")
        return False
    from huggingface_hub import CommitOperationAdd, HfApi
    api = HfApi(token=bills.HF_TOKEN)
    api.create_repo(HF_REPO, repo_type="dataset", private=False, exist_ok=True)
    operations = [CommitOperationAdd(path_in_repo=f"data/{name}.parquet", path_or_fileobj=str(out_dir / f"{name}.parquet"))
                  for name in TABLES]
    if with_card and CARD_FILE.exists():
        operations.append(CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=str(CARD_FILE)))
    api.create_commit(repo_id=HF_REPO, repo_type="dataset", operations=operations,
                      commit_message=f"Update Supreme Court tables ({today()})")
    log.info(f"Uploaded {len(operations)} files to {HF_REPO}")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the Supreme Court cases dataset")
    parser.add_argument("--base", action="store_true", help="rebuild everything from the sources (slow; run by hand)")
    parser.add_argument("--raw", default=str(OUT_DIR / "raw"), help="where the database's files are kept, for --base")
    parser.add_argument("--out", default=str(OUT_DIR), help="directory to write the tables into")
    parser.add_argument("--workers", type=int, default=3, help="docket files read at once, for --base")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the tables only")

    out_dir = Path(args.out)
    try:
        tables, dockets = build_base(Path(args.raw), args.workers) if args.base else build_daily()
    except Exception as e:
        log.error(f"Supreme Court tables not built: {e}")
        return 1
    write_tables(tables, out_dir)
    pushed = False if args.no_upload else upload(out_dir, args.write_card or args.base)
    if pushed:
        try:  # the map's files are made from the tables just written; a failure here leaves the dataset as published
            import build_court_snapshot
            build_court_snapshot.main(["--tables", str(out_dir)])
        except Exception as e:
            log.error(f"Court map files not updated: {e}")
    cases = tables["cases"]
    pending = int((cases["stage"] != "decided").sum())
    log.info(f"RESULT: supreme-court-cases cases={len(cases)} pending={pending} votes={len(tables['votes'])} "
             f"applications={len(tables['applications'])} docket_entries={len(tables['docket_entries'])} "
             f"dockets={dockets} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(main())
