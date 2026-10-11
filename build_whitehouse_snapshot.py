#!/usr/bin/env python3
"""
Build the White House world's data file from chrissoria/executive-orders.

Capitol World's second map is about executive orders rather than bills. An
order does not travel through stages the way a bill does, so the map places it
by what can be read from the order itself:

  - who signed it and when;
  - which departments it gives directions to, counted from the text ("the
    Secretary of State shall…", "the Department of Energy");
  - which earlier orders it says it revokes or amends, and so which later
    orders revoked it.

All three are plain readings of the text by the rules in this file, not
judgements. They are approximate in the ways noted beside each rule.

Writes world/whitehouse.json.gz and uploads it next to the dataset. Run after
update_executive_orders.py, which calls it whenever the table changes.

Usage:
    python build_whitehouse_snapshot.py
    python build_whitehouse_snapshot.py --no-upload
"""

import argparse
import gzip
import json
import logging
import re
import sys
from pathlib import Path

import pandas as pd

import build_federal_bills as bills

log = logging.getLogger(__name__)

HF_REPO = "chrissoria/executive-orders"
OUT_FILE = bills.SCRIPT_DIR / "world" / "whitehouse.json.gz"
SCHEMA = 1
EXCERPT_CHARS = 260
TITLE_CHARS = 180

# The departments an order can be addressed to: (code, name on the map, what to look for).
# Each stands for its predecessors too, so that two centuries fit on one map.
DEPARTMENTS = [
    ("state", "State", r"Secretary of State|Department of State|State Department"),
    ("treasury", "Treasury", r"Secretary of the Treasury|Department of the Treasury|Treasury Department"),
    ("defense", "Defense", r"Secretary of (?:Defense|War|the Navy|the Army|the Air Force)|Department of (?:Defense|War|the Navy|the Army|the Air Force)|(?:War|Navy) Department"),
    ("justice", "Justice", r"Attorney General|Department of Justice"),
    ("interior", "Interior", r"Secretary of the Interior|Department of the Interior|Interior Department"),
    ("agriculture", "Agriculture", r"Secretary of Agriculture|Department of Agriculture"),
    ("commerce", "Commerce", r"Secretary of Commerce|Department of Commerce"),
    ("labor", "Labor", r"Secretary of Labor|Department of Labor"),
    ("health", "Health and Human Services", r"Secretary of Health|Department of Health"),
    ("housing", "Housing and Urban Development", r"Secretary of Housing|Department of Housing"),
    ("transportation", "Transportation", r"Secretary of Transportation|Department of Transportation"),
    ("energy", "Energy", r"Secretary of Energy|Department of Energy"),
    ("education", "Education", r"Secretary of Education|Department of Education"),
    ("veterans", "Veterans Affairs", r"Secretary of Veterans Affairs|Department of Veterans Affairs|Veterans(?:'|’)? Administration|Administrator of Veterans"),
    ("homeland", "Homeland Security", r"Secretary of Homeland Security|Department of Homeland Security"),
]
_DEPARTMENT = [(code, re.compile(pattern)) for code, _, pattern in DEPARTMENTS]

# Reading which earlier orders an order acts on. Precision comes first: a wrong "revoked by" on a
# public map is worse than a missing one, so only a few unambiguous wordings count.
#   "Executive Order 13166 of August 11, 2000 (Improving Access…), is hereby revoked"
#   "I hereby revoke Executive Order 13166"       "Amending Executive Order 12866" (a title)
#   "The following are revoked: (a) Executive Order 13985 …; (b) Executive Order 13986 …"
# Dates and bracketed titles are dropped first, so a year is not taken for an order, and so is
# "which amended Executive Order N", which describes an order rather than acting on it.
_DATE = re.compile(r",?\s+of\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4}")
_BRACKETS = re.compile(r"\s*\([^()]{4,300}\)")
_ASIDE = re.compile(r",?\s*(?:which|that)\s+(?:amend\w*|revok\w*|supersed\w*)\s+Executive Orders?[^,;.]*,?", re.I)
_NUMS = r"\d{3,5}(?:-[A-Z])?"
_REFS = rf"(?:Executive Orders?(?:\s+(?:Nos?|Numbered)\.?)?\s+{_NUMS}(?:(?:,\s*(?:and\s+)?|\s+and\s+)(?:Executive Orders?\s+)?(?:(?:Nos?)\.?\s+)?{_NUMS})*)"
_VERBS = {"revokes": r"revok\w*|rescind\w*|supersed\w*", "amends": r"amend\w*"}
_PASSIVE = {kind: re.compile(rf"({_REFS})[^.;:]{{0,90}}?\b(?:is|are|be)\s+(?:hereby\s+|further\s+)?(?:{verbs})\b", re.I)
            for kind, verbs in _VERBS.items()}
_ACTIVE = {kind: re.compile(rf"\b(?:{verbs})(?:\s+(?:of|to|the|certain|and\s+\w+ing))*\s+({_REFS})", re.I)
           for kind, verbs in _VERBS.items()}
_LIST_HEAD = {kind: re.compile(rf"\bfollowing\b[^.;]{{0,160}}\b(?:{verbs})\b[^.;]{{0,40}}[:.]?\s*$", re.I) for kind, verbs in _VERBS.items()}
_LIST_ITEM = re.compile(rf"^\(?[a-z]{{1,3}}\)\s*({_REFS})", re.I)
_NEGATED = re.compile(r"\bnot\s+(?:be\s+\w+\s+to\s+)?(?:supersed|revok|rescind|amend)|\bwithout\s+(?:supersed|revok|amend)", re.I)
_SENTENCE = re.compile(r"(?<=[.;:])\s+")


def departments_in(text):
    """[(code, times named)] for the departments an order names, most-named first, then first-named."""
    seen = []
    for code, pattern in _DEPARTMENT:
        hits = [match.start() for match in pattern.finditer(text or "")]
        if hits:
            seen.append((-len(hits), hits[0], code))
    return [(code, -count) for count, _, code in sorted(seen)]


def lead_of(named):
    """The department an order is mostly addressed to: named at least twice, and more than any other."""
    if not named or named[0][1] < 2 or (len(named) > 1 and named[1][1] == named[0][1]):
        return None
    return named[0][0]


def relations_in(text, own_number="", title=""):
    """Earlier orders this one says it revokes or amends: {"revokes": [...], "amends": [...]}.

    "Revokes" includes superseding and rescinding, and an order revoked in part. Only orders
    with a lower number are kept: an order cannot act on a later one.
    """
    found = {"revokes": [], "amends": []}
    own = int(own_number) if str(own_number).isdigit() else None

    def note(kind, refs):
        for number in re.findall(_NUMS, refs):
            if own is not None and int(number.split("-")[0]) >= own:
                continue
            if number not in found["revokes"] and number not in found["amends"]:
                found[kind].append(number)

    listing = None  # inside "the following are revoked: (a) … (b) …"
    for raw in [title or ""] + _SENTENCE.split(text or ""):
        if "Executive Order" not in raw and not listing and "following" not in raw:
            continue
        sentence = _ASIDE.sub(" ", _BRACKETS.sub("", _DATE.sub("", raw))).strip()
        item = _LIST_ITEM.match(sentence)
        if listing and item:
            note(listing, item.group(1))
            continue
        if listing and re.match(r"^\(?[a-z]{1,3}\)", sentence):
            continue  # a list item that is not an order (a memorandum, say)
        listing = None
        if _NEGATED.search(sentence):
            continue
        for kind in ("revokes", "amends"):
            if _LIST_HEAD[kind].search(sentence):
                listing = kind
            for pattern in (_PASSIVE[kind], _ACTIVE[kind]):
                for match in pattern.finditer(sentence):
                    note(kind, match.group(1))
    return found


def excerpt_of(text):
    """The start of what the order says, after the "By the authority vested in me…" formula."""
    body = re.sub(r"\s+", " ", text or "").strip()
    start = re.search(r"it is (?:hereby )?ordered(?: as follows)?[:.]?\s*", body[:1500], re.I)
    if start:
        body = body[start.end():]
    body = re.sub(r"\s+([.,;:])", r"\1", body)
    body = re.sub(r"^(?:Section|Sec\.?)\s*1\s*\.?\s*", "", body).lstrip(" .")
    return body[:EXCERPT_CHARS].rstrip() + ("…" if len(body) > EXCERPT_CHARS else "")


def build(df):
    df = df.sort_values(["date", "executive_order_number"]).reset_index(drop=True)
    numbers = df["executive_order_number"].fillna("").astype(str)
    ids = [number if number and count == 1 else f"x{index}"
           for index, (number, count) in enumerate(zip(numbers, numbers.map(numbers.value_counts())))]

    presidents, president_index = [], {}
    for name, group in df.groupby("president", sort=False):
        president_index[name] = len(presidents)
        presidents.append({"name": name, "party": group["party"].iloc[0], "first": group["date"].min(),
                           "last": group["date"].max(), "n": int(len(group))})
    codes = [code for code, _, _ in DEPARTMENTS]
    lead, named, relations = [], [], []
    for text, number, title in zip(df["text"], numbers, df["title"]):
        found = departments_in(text)
        named.append([codes.index(code) for code, _ in found])
        top = lead_of(found)
        lead.append(codes.index(top) if top else -1)
        relations.append(relations_in(text, number, title))

    # Who did what to whom, read the other way round.
    acted_on = {}
    for order_id, links in zip(ids, relations):
        for target in links["revokes"]:
            acted_on.setdefault(target, []).append(order_id)
    known = set(ids)
    revoked_by = [[other for other in acted_on.get(order_id, []) if other in known] for order_id in ids]

    department_counts = pd.Series([code for row in named for code in row]).value_counts().to_dict()
    lead_counts = pd.Series([code for code in lead if code >= 0]).value_counts().to_dict()
    data_through = df["date"].max()
    world = {
        "schema": SCHEMA,
        "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_through": data_through,
        "counts": {
            "total": int(len(df)),
            "revoked": int(sum(1 for others in revoked_by if others)),
            "with_department": int(sum(1 for code in lead if code >= 0)),
        },
        "presidents": presidents,
        "departments": [{"code": code, "name": name, "named_in": int(department_counts.get(index, 0)),
                         "lead_of": int(lead_counts.get(index, 0))} for index, (code, name, _) in enumerate(DEPARTMENTS)],
        # One entry per order in each list below, oldest first.
        "id": ids,
        "number": numbers.tolist(),
        "date": df["date"].tolist(),
        "title": [re.sub(r"^\s*Executive Order(\s+\d+[\w-]*)?\s*[—–-]+\s*", "", title or "")[:TITLE_CHARS] for title in df["title"]],
        "president": [president_index[name] for name in df["president"]],
        "lead": lead,
        "departments_named": named,
        "revokes": [links["revokes"] for links in relations],
        "amends": [links["amends"] for links in relations],
        "revoked_by": revoked_by,
        "excerpt": [excerpt_of(text) for text in df["text"]],
        "url": df["federal_register_url"].where(df["federal_register_url"] != "", df["url"]).tolist(),
    }
    return world


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the White House world's data file")
    parser.add_argument("--table", help="read the orders from this parquet instead of the published dataset")
    parser.add_argument("--no-upload", action="store_true", help="write the file but do not upload it")
    args = parser.parse_args(argv)

    import update_executive_orders as orders
    df = orders.read_published(args.table)
    world = build(df)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT_FILE, "wt", encoding="utf-8") as handle:
        json.dump(world, handle, ensure_ascii=False, separators=(",", ":"))
    counts = world["counts"]
    log.info(f"White House snapshot: {counts['total']} orders, {len(world['presidents'])} presidents, "
             f"{counts['revoked']} revoked by a later order, {counts['with_department']} naming a department; "
             f"{OUT_FILE.name} {OUT_FILE.stat().st_size // 1024} KB")
    if args.no_upload:
        return 0
    if not bills.HF_TOKEN:
        log.error("No Hugging Face token; snapshot written locally but not uploaded")
        return 1
    from huggingface_hub import HfApi
    HfApi(token=bills.HF_TOKEN).upload_file(path_or_fileobj=str(OUT_FILE), path_in_repo="world/whitehouse.json.gz",
                                           repo_id=HF_REPO, repo_type="dataset",
                                           commit_message="Update world/whitehouse.json.gz")
    log.info(f"Uploaded world/whitehouse.json.gz to {HF_REPO}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(main())
