#!/usr/bin/env python3
"""
Build the Capitol World files for a finished Congress.

The daily job (build_federal_bills.py) covers the current Congress through the
Congress.gov API, one bill at a time. A finished Congress never changes, so it
is built once from GovInfo's Bill Status bulk data: one zip per Congress and
bill type, with the same fields as the API (sponsor, policy area, actions,
official summaries). No API key is needed for the bills; the member roster and
committee list take a handful of Congress.gov calls.

For each Congress this writes:
  archive/bills_<congress>.parquet       every bill, in the columns the map uses
  archive/<congress>/world.json.gz       the map file, with every bill at the place it ended
  archive/<congress>/search.json.gz      the search index
and uploads the last two to world/archive/<congress>/ next to the live map
files, then refreshes world/congresses.json, the list the app's picker reads.

Usage:
    python build_congress_archive.py 118            # one Congress
    python build_congress_archive.py 113-118        # a range
    python build_congress_archive.py 118 --no-upload
"""

import argparse
import gzip
import html
import io
import json
import logging
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pandas as pd
import requests

import build_federal_bills as bills
import build_world_snapshot as snapshot

log = logging.getLogger(__name__)

BULK = "https://www.govinfo.gov/bulkdata/BILLSTATUS/{congress}/{kind}/BILLSTATUS-{congress}-{kind}.zip"
BILL_TYPES = ("hr", "s", "hjres", "sjres", "hconres", "sconres", "hres", "sres")
FIRST_BULK_CONGRESS = 108  # GovInfo has no Bill Status files before 2003
ARCHIVE_DIR = bills.SCRIPT_DIR / "archive"
URL_SLUG = {
    "hr": "house-bill", "s": "senate-bill", "hres": "house-resolution", "sres": "senate-resolution",
    "hjres": "house-joint-resolution", "sjres": "senate-joint-resolution",
    "hconres": "house-concurrent-resolution", "sconres": "senate-concurrent-resolution",
}
LEGISLATORS = ("legislators-current.json", "legislators-historical.json")


def ordinal(number):
    number = int(number)
    if 10 <= number % 100 <= 20:
        return f"{number}th"
    return f"{number}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(number % 10, 'th') }"


def download(congress, raw_dir):
    """Fetch the eight bulk zips of a Congress, skipping the ones already on disk."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for kind in BILL_TYPES:
        path = raw_dir / f"BILLSTATUS-{congress}-{kind}.zip"
        if not path.exists():
            url = BULK.format(congress=congress, kind=kind)
            response = requests.get(url, timeout=300)
            response.raise_for_status()
            path.write_bytes(response.content)
            log.info(f"Downloaded {path.name} ({len(response.content) // 1024} KB)")
        paths.append(path)
    return paths


def _text(node, path):
    found = node.find(path) if node is not None else None
    return (found.text or "").strip() if found is not None else ""


def plain(markup):
    """An official summary as plain text."""
    text = re.sub(r"<[^>]+>", " ", html.unescape(markup or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def api_actions(bill):
    """The bill's actions in the shape the Congress.gov API gives them, newest first."""
    actions = []
    for item in bill.findall("actions/item"):
        actions.append({
            "actionDate": _text(item, "actionDate"),
            "text": _text(item, "text"),
            "type": _text(item, "type"),
            "actionCode": _text(item, "actionCode"),
            "sourceSystem": {"name": _text(item, "sourceSystem/name")},
            "committees": [{"systemCode": _text(c, "systemCode"), "name": _text(c, "name")}
                           for c in item.findall("committees/item")],
        })
    # Already newest first; the stable sort only repairs a file that is not.
    return sorted(actions, key=lambda action: action["actionDate"], reverse=True)


def parse_bill(xml_bytes):
    """One Bill Status file as a row in the columns of federal-bills-active that the map reads."""
    if b"<!DOCTYPE" in xml_bytes or b"<!ENTITY" in xml_bytes:
        raise ValueError("unexpected document type declaration")
    bill = ElementTree.fromstring(xml_bytes).find("bill")
    if bill is None:
        raise ValueError("no <bill> element")
    kind = (_text(bill, "type") or _text(bill, "billType")).upper()
    number = _text(bill, "number") or _text(bill, "billNumber")
    congress = _text(bill, "congress")
    origin = _text(bill, "originChamber")
    actions = api_actions(bill)
    history = bills.compact_actions(actions)
    location = bills.classify_location(history, kind, origin)
    sponsor = bill.find("sponsors/item")
    summaries = bill.findall("summaries/summary") or bill.findall("summaries/billSummaries/item")
    latest_summary = max(summaries, key=lambda s: (_text(s, "actionDate"), _text(s, "updateDate")), default=None)
    summary = plain(_text(latest_summary, "cdata/text") or _text(latest_summary, "text"))
    laws = [f"{_text(law, 'type')} {_text(law, 'number')}".strip() for law in bill.findall("laws/item")]
    url = _text(bill, "legislationUrl") or (
        f"https://www.congress.gov/bill/{ordinal(congress)}-congress/{URL_SLUG.get(kind.lower(), 'bill')}/{number}")
    return {
        "date_last_action": _text(bill, "latestAction/actionDate") or (actions[0]["actionDate"] if actions else ""),
        "date_introduced": _text(bill, "introducedDate"),
        "bill_type": kind,
        "bill_number": number,
        "congress": congress,
        "title": _text(bill, "title"),
        "status": bills.determine_status(actions),
        "last_action_text": _text(bill, "latestAction/text") or (actions[0]["text"] if actions else ""),
        "sponsor_full_name": _text(sponsor, "fullName"),
        "sponsor_party": _text(sponsor, "party"),
        "sponsor_state": _text(sponsor, "state"),
        "num_cosponsors": len(bill.findall("cosponsors/item")),
        "chamber_of_origin": origin,
        "policy_area": _text(bill, "policyArea/name"),
        "subjects": "; ".join(_text(s, "name") for s in bill.findall("subjects/legislativeSubjects/item")),
        "short_summary": summary,
        "url": url,
        "public_law_number": "; ".join(laws),
        "source": "govinfo_billstatus",
        "sponsor_bioguide_id": _text(sponsor, "bioguideId"),
        "recent_actions": json.dumps(history[:bills.RECENT_ACTIONS_KEPT], ensure_ascii=False),
        "location_kind": location["kind"],
        "location_chamber": location["chamber"],
        "location_committee_code": location["committee_code"],
        "location_committee_name": location["committee_name"],
    }


def build_table(congress, raw_dir):
    """Every bill of a Congress as a table."""
    rows, skipped = [], 0
    for path in download(congress, raw_dir):
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if not name.endswith(".xml"):
                    continue
                try:
                    row = parse_bill(archive.read(name))
                except Exception as e:
                    skipped += 1
                    log.warning(f"Skipped {name}: {e}")
                    continue
                if row["bill_type"] and row["bill_number"] and row["congress"] == str(congress):
                    rows.append(row)
                else:
                    skipped += 1
    df = pd.DataFrame(rows).drop_duplicates(["bill_type", "bill_number"]).reset_index(drop=True)
    log.info(f"Congress {congress}: {len(df)} bills parsed, {skipped} files skipped")
    return df


def fetch_leaders(congress):
    """Speaker and majority leaders at the end of a Congress, from congress-legislators.

    Returns {"House"|"Senate"|"speaker": bioguide id}; empty when the source cannot be read.
    """
    start, end = snapshot.congress_years(congress)
    opened, closed = f"{start}-01-03", f"{end}-01-03"
    found = {}
    try:
        for name in LEGISLATORS:
            for legislator in requests.get(snapshot.ROLES_SOURCE + name, timeout=120).json():
                for role in legislator.get("leadership_roles") or []:
                    slot = snapshot.LEADER_TITLES.get(role.get("title") or "")
                    began, ended = role.get("start") or "", role.get("end") or "9999"
                    if slot and began < closed and ended > opened and began >= found.get(slot, ("", ""))[0]:
                        found[slot] = (began, legislator["id"]["bioguide"])
    except Exception as e:
        log.info(f"Leaders not available ({e}); the map will use robots for those moves")
    return {slot: who for slot, (_, who) in found.items()}


def sponsor_chambers(df):
    """{bioguide id: chamber} from the bills each member sponsored, which cannot be out of date."""
    chamber = df["bill_type"].str.startswith("S").map({True: "Senate", False: "House"})
    return dict(zip(df["sponsor_bioguide_id"], chamber))


def build_congress(congress, raw_dir, out_dir):
    """Write the table and the two map files of one Congress. Returns the paths and a summary."""
    df = build_table(congress, raw_dir)
    if df.empty:
        raise RuntimeError(f"no bills found for Congress {congress}")
    out_dir.mkdir(parents=True, exist_ok=True)
    table = out_dir / f"bills_{congress}.parquet"
    df.to_parquet(table, index=False)

    roster = snapshot.fetch_roster(congress)
    sat_in = sponsor_chambers(df)
    for member in roster:
        member["chamber"] = sat_in.get(member["id"], member["chamber"])
    roles = {"chairs": {}, "leaders": fetch_leaders(congress)}
    world, search = snapshot.build(table, roster=roster, roles=roles, congress=congress, world_days=None)
    start, end = snapshot.congress_years(congress)
    world["final"] = True
    world["years"] = [start, end]
    world["summary_source"] = "crs"

    folder = out_dir / str(congress)
    folder.mkdir(parents=True, exist_ok=True)
    files = {"world.json.gz": world, "search.json.gz": search}
    for name, content in files.items():
        with gzip.open(folder / name, "wt", encoding="utf-8") as handle:
            json.dump(content, handle, ensure_ascii=False, separators=(",", ":"))
    counts = world["counts"]
    entry = {
        "congress": int(congress),
        "years": [start, end],
        "bills": counts["total"],
        "laws": int(counts["by_kind"].get("law", 0)),
        "data_through": world["data_through"],
    }
    sizes = ", ".join(f"{name} {(folder / name).stat().st_size // 1024} KB" for name in files)
    log.info(f"Congress {congress}: {counts['total']} bills, {entry['laws']} laws, {len(world['members'])} members, "
             f"{counts['events']} events, {counts['guessed_locations']} guessed locations; {sizes}")
    return [folder / name for name in files], entry


def upload(congress, paths, entry):
    """Upload a Congress's map files and add it to the list the app's picker reads."""
    from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download

    api = HfApi(token=bills.HF_TOKEN)
    listed = {}
    try:
        current = hf_hub_download(bills.HF_REPO, "world/congresses.json", repo_type="dataset", token=bills.HF_TOKEN,
                                  force_download=True)
        listed = {item["congress"]: item for item in json.loads(Path(current).read_text())["archive"]}
    except Exception:
        pass  # first archive
    listed[entry["congress"]] = entry
    index = json.dumps({"archive": [listed[key] for key in sorted(listed, reverse=True)]}, separators=(",", ":"))
    operations = [CommitOperationAdd(path_in_repo=f"world/archive/{congress}/{path.name}", path_or_fileobj=str(path))
                  for path in paths]
    operations.append(CommitOperationAdd(path_in_repo="world/congresses.json", path_or_fileobj=io.BytesIO(index.encode())))
    api.create_commit(repo_id=bills.HF_REPO, repo_type="dataset", operations=operations,
                      commit_message=f"Add world/archive/{congress}")
    log.info(f"Uploaded Congress {congress} to {bills.HF_REPO}/world/archive/{congress}")


def parse_range(text):
    first, _, last = text.partition("-")
    return list(range(int(first), int(last or first) + 1))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the Capitol World files for finished Congresses")
    parser.add_argument("congress", help="a Congress or a range, such as 118 or 113-118")
    parser.add_argument("--raw", default=str(ARCHIVE_DIR / "raw"), help="where the bulk zips are kept")
    parser.add_argument("--out", default=str(ARCHIVE_DIR), help="directory to write into")
    parser.add_argument("--no-upload", action="store_true", help="write the files but do not upload them")
    args = parser.parse_args(argv)

    wanted = parse_range(args.congress)
    if min(wanted) < FIRST_BULK_CONGRESS or max(wanted) >= int(bills.CONGRESS):
        parser.error(f"choose finished Congresses from {FIRST_BULK_CONGRESS} to {int(bills.CONGRESS) - 1}")
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the files only")
    failed = 0
    for congress in wanted:
        try:
            paths, entry = build_congress(congress, Path(args.raw), Path(args.out))
            if not args.no_upload:
                upload(congress, paths, entry)
        except Exception as e:
            failed += 1
            log.error(f"Congress {congress} failed: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
