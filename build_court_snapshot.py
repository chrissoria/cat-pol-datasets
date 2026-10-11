#!/usr/bin/env python3
"""
Build the data files for Capitol World's Supreme Court map from the tables of
chrissoria/supreme-court-cases (build_supreme_court.py).

  world/court.json.gz        every term since 1946: who sat, each case with where
                             it stands and how the justices voted, and the
                             applications that were more than routine
  world/text/<term>.json.gz  the words for one term's cards: the question each
                             case asked and what was held; what each application
                             asked and how it was answered

The first is read once, so it carries no long text; the second is fetched for
the term on show. Routine applications (more time to file, a longer brief) are
counted but not listed: there are over a thousand a term.

Runs after the tables are built, and uploads both next to the dataset.

Usage:
    python build_court_snapshot.py                 # from the published tables
    python build_court_snapshot.py --tables scotus # from local ones
    python build_court_snapshot.py --no-upload
"""

import argparse
import gzip
import json
import logging
import sys
from pathlib import Path

import pandas as pd

import build_federal_bills as bills
import build_supreme_court as court

log = logging.getLogger(__name__)

SCHEMA = 1
OUT_FILE = bills.SCRIPT_DIR / "world" / "court.json.gz"
TEXT_DIR = bills.SCRIPT_DIR / "world" / "court_text"
ROUTINE = ("extension of time", "word or page limit")
QUESTION_CHARS = 1200
ENTRY_CHARS = 600
# How a justice stood in a case, one letter each, in the order of the term's justices.
WROTE_FOR_COURT, WITH_MAJORITY, CONCURRED, DISSENTED, WROTE_DISSENT, ABSENT = "W", "M", "C", "D", "X", "-"


def clipped(text, limit):
    text = text or ""
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def coded(values):
    """A column as (the distinct values, each row's index into them): long columns repeat a few strings."""
    names = sorted({value for value in values if value})
    index = {name: number for number, name in enumerate(names)}
    return names, [index.get(value, -1) for value in values]


def people(justices, votes):
    """The justices the map can show: everyone with a vote on record and everyone now sitting, by seniority."""
    wanted = set(votes["justice_id"]) | set(justices[justices["serving"]]["justice_id"])
    rows = []
    for justice_id, held in justices[justices["justice_id"].isin(wanted)].groupby("justice_id", sort=False):
        held = held.sort_values("start")
        first, last = held.iloc[0], held.iloc[-1]
        chief = held[held["title"] == "Chief Justice"]
        rows.append({
            "id": justice_id,
            "name": last["name"],
            "last_name": last["last_name"],
            "appointed_by": first["appointed_by"],
            "party": first["appointing_party"],
            "start": first["start"],
            "end": last["end"],
            "chief_from": chief["start"].iloc[0] if len(chief) else "",
            "born": last["born"],
            "senate_vote": last["senate_vote"],
        })
    return sorted(rows, key=lambda row: row["start"])


def vote_letter(side, wrote, is_author):
    if is_author:
        return WROTE_FOR_COURT
    if side == "majority":
        return CONCURRED if wrote else WITH_MAJORITY
    if side == "dissent":
        return WROTE_DISSENT if wrote else DISSENTED
    return ABSENT


def build(tables):
    """Returns the map file and {term: that term's text file}."""
    cases, votes, justices = tables["cases"], tables["votes"], tables["justices"]
    applications, entries, terms = tables["applications"], tables["docket_entries"], tables["terms"]
    cases = cases.sort_values(["term", "date_decided", "date_argued", "id"]).reset_index(drop=True)

    bench = people(justices, votes)
    seat = {person["id"]: number for number, person in enumerate(bench)}
    sitting_now = [seat[justice_id] for justice_id in justices[justices["serving"]].sort_values("start")["justice_id"] if justice_id in seat]

    # Who sat each term: whoever voted in it; for a term with no votes yet, the Court as it is today.
    voted = votes.groupby("term")["justice_id"].agg(lambda ids: sorted(set(ids), key=lambda who: seat.get(who, 999))).to_dict()
    term_rows, sat = [], {}
    for row in terms.to_dict("records"):
        term = int(row["term"])
        members = [seat[who] for who in voted.get(term, []) if who in seat] or sitting_now
        chief = next((number for number in members if bench[number]["chief_from"] and bench[number]["last_name"] == row["chief_justice"]), -1)
        if chief < 0:  # a term in progress carries the last Chief's name forward; fall back to whoever holds the chair
            chief = next((number for number in members if bench[number]["chief_from"]), -1)
        members = ([chief] if chief >= 0 else []) + [number for number in members if number != chief]
        sat[term] = members
        mine = applications[applications["term"] == term] if len(applications) else applications
        term_rows.append({
            "term": term,
            "chief": chief,
            "justices": members,
            "paid_petitions": None if pd.isna(row["paid_petitions"]) else int(row["paid_petitions"]),
            "ifp_petitions": None if pd.isna(row["ifp_petitions"]) else int(row["ifp_petitions"]),
            "applications": None if pd.isna(row["applications"]) else int(row["applications"]),
            "routine_applications": int(mine["kind"].isin(ROUTINE).sum()) if len(mine) else 0,
        })

    cast = {}
    for case_id, justice_id, side, wrote in zip(votes["case_id"], votes["justice_id"], votes["side"], votes["wrote_opinion"]):
        cast.setdefault(case_id, {})[justice_id] = (side, bool(wrote))
    lines = []
    for case_id, term, author in zip(cases["id"], cases["term"], cases["majority_author"]):
        mine = cast.get(case_id, {})
        lines.append("".join(
            vote_letter(*mine[bench[number]["id"]], bench[number]["id"] == author) if bench[number]["id"] in mine else ABSENT
            for number in sat.get(int(term), [])) if mine else "")

    dispositions, disposition = coded(cases["disposition"])
    areas, area = coded(cases["issue_area"])
    issues, issue = coded(cases["issue"])
    laws, law = coded(cases["law"])
    courts, lower = coded(cases["lower_court"])
    kinds, decision_type = coded(cases["decision_type"])

    shown = applications[~applications["kind"].isin(ROUTINE)].reset_index(drop=True) if len(applications) else applications
    app_kinds, app_kind = coded(shown["kind"]) if len(shown) else ([], [])
    app_courts, app_lower = coded(shown["lower_court"]) if len(shown) else ([], [])

    data_through = max([day for day in list(cases["date_decided"]) + list(cases["date_argued"]) + list(entries["date"] if len(entries) else []) if day] or [""])
    world = {
        "schema": SCHEMA,
        "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_through": min(data_through, court.today()),  # a docket can carry the date of a hearing still to come
        "current_term": court.current_term(),
        "justices": bench,
        "terms": term_rows,
        "dispositions": dispositions,
        "issue_areas": areas,
        "issues": issues,
        "laws": laws,
        "lower_courts": courts,
        "decision_types": kinds,
        # One entry per case in each list below, by term and then by date decided.
        "cases": {
            "id": cases["id"].tolist(),
            "term": cases["term"].astype(int).tolist(),
            "docket": cases["docket"].tolist(),
            "name": cases["name"].tolist(),
            "stage": cases["stage"].tolist(),
            "granted": cases["date_granted"].tolist(),
            "argued": cases["date_argued"].tolist(),
            "decided": cases["date_decided"].tolist(),
            "citation": cases["citation"].tolist(),
            "disposition": disposition,
            "winner": [value[:1] for value in cases["winner"]],  # p, r, u or nothing
            "majority": cases["majority_votes"].astype(int).tolist(),
            "minority": cases["minority_votes"].astype(int).tolist(),
            "author": [seat.get(who, -1) for who in cases["majority_author"]],
            "area": area,
            "issue": issue,
            "law": law,
            "unconstitutional": cases["declared_unconstitutional"].tolist(),
            "precedent_altered": cases["precedent_altered"].astype(int).tolist(),
            "lower_court": lower,
            "decision_type": decision_type,
            "votes": lines,
            "url": cases["oyez_url"].where(cases["oyez_url"] != "", cases["justia_url"].where(cases["justia_url"] != "", cases["docket_url"])).tolist(),
        },
        "application_kinds": app_kinds,
        "application_courts": app_courts,
        "applications": {
            "docket": shown["docket"].tolist(),
            "term": shown["term"].astype(int).tolist(),
            "title": shown["title"].tolist(),
            "kind": app_kind,
            "filed": shown["date_filed"].tolist(),
            "outcome": shown["outcome"].tolist(),
            "decided_by": shown["decided_by"].tolist(),
            "resolved": shown["date_resolved"].tolist(),
            "referred": shown["referred_to_court"].astype(int).tolist(),
            "capital": shown["capital_case"].astype(int).tolist(),
            "lower_court": app_lower,
            "url": shown["url"].tolist(),
        } if len(shown) else {},
    }

    # The words, a file to a term.
    texts = {}
    for term, case_id, question, description in zip(cases["term"], cases["id"], cases["question"], cases["description"]):
        if question or description:
            texts.setdefault(int(term), {"cases": {}, "applications": {}})["cases"][case_id] = [clipped(question, QUESTION_CHARS), clipped(description, QUESTION_CHARS)]
    if len(shown):
        lines_of = {docket: rows.sort_values("seq") for docket, rows in entries[entries["docket"].isin(set(shown["docket"]))].groupby("docket")}
        for term, docket, resolved in zip(shown["term"], shown["docket"], shown["date_resolved"]):
            rows = lines_of.get(docket)
            if rows is None or rows.empty:
                continue
            asked = rows["text"].iloc[0]
            answer = rows[rows["date"] == resolved]["text"].iloc[-1] if resolved and (rows["date"] == resolved).any() else ""
            texts.setdefault(int(term), {"cases": {}, "applications": {}})["applications"][docket] = [clipped(asked, ENTRY_CHARS), clipped(answer, ENTRY_CHARS)]
    return world, texts


def write(world, texts):
    """Write the files locally. Returns [(path on the Hub, local path)]."""
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT_FILE, "wt", encoding="utf-8") as handle:
        json.dump(world, handle, ensure_ascii=False, separators=(",", ":"))
    files = [("world/court.json.gz", OUT_FILE)]
    for term, content in sorted(texts.items()):
        path = TEXT_DIR / f"{term}.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            json.dump(content, handle, ensure_ascii=False, separators=(",", ":"))
        files.append((f"world/text/{term}.json.gz", path))
    return files


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the Supreme Court map's data files")
    parser.add_argument("--tables", help="read the tables from this directory instead of the published dataset")
    parser.add_argument("--no-upload", action="store_true", help="write the files but do not upload them")
    args = parser.parse_args(argv)

    if args.tables:
        tables = {name: pd.read_parquet(Path(args.tables) / f"{name}.parquet") for name in court.TABLES}
    else:
        tables = court.read_published()
    world, texts = build(tables)
    files = write(world, texts)
    counts = world["cases"]
    log.info(f"Court snapshot: {len(counts['id'])} cases in {len(world['terms'])} terms, {len(world['justices'])} justices, "
             f"{len(world['applications'].get('docket', []))} applications listed; court.json.gz {OUT_FILE.stat().st_size // 1024} KB, "
             f"{len(files) - 1} text files")
    if args.no_upload:
        return 0
    if not bills.HF_TOKEN:
        log.error("No Hugging Face token; snapshot written locally but not uploaded")
        return 1
    from huggingface_hub import CommitOperationAdd, HfApi
    # One commit, so the map file and the text files never disagree.
    operations = [CommitOperationAdd(path_in_repo=target, path_or_fileobj=str(path)) for target, path in files]
    HfApi(token=bills.HF_TOKEN).create_commit(repo_id=court.HF_REPO, repo_type="dataset", operations=operations,
                                             commit_message="Update world/court.json.gz and world/text")
    log.info(f"Uploaded {len(operations)} map files to {court.HF_REPO}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(main())
