#!/usr/bin/env python3
"""
Keep chrissoria/berkeley-ordinances from the Berkeley City Clerk's own records.

The dataset was first read from the municipal code's table of enactments
(berkeley.municipal.codes), which gives most ordinances a year and no date and
now answers with a bot check. The City Clerk's Records Online
(records.cityofberkeley.info) is the City's archive of the ordinances
themselves: every ordinance from 1916 on with its number, the day it was
adopted and a scan of the signed document. It answers an ordinary request.

Two ways to run it:

    python build_berkeley.py
        Reads the Clerk's list of ordinances (three requests), gives each
        ordinance in the dataset the day the Clerk has for it, adds the
        ordinances passed since the dataset's newest, and publishes if
        anything changed.

    python build_berkeley.py --texts
        Reads each ordinance's document. They are scans with no text of their
        own, so this is OCR (Tesseract), and hours of it. What is read is kept
        in berkeley/ every 200 documents, so it can be stopped and started
        again. It does not publish.

    --with-texts   on a plain run, put the texts read so far into the table.
                   The first time, `text` becomes the ordinance itself and
                   what it held (the code's note on the ordinance) moves to
                   `code_history`; after that every run carries the texts.
    --workers N    documents read at once with --texts (default 2)
    --limit N      with --texts, read at most this many
    --no-upload    build the table but do not publish it

A row is matched to the Clerk's list by its number: "Ord. 7999-NS" is the
Clerk's 7999. Ordinances of the old series ("Ord. 603", "Ord. 12-A") and the
first nine hundred of the new are not in the Clerk's list and are left as they
were. So is any number the Clerk lists twice.

OCR needs `tesseract`, `pdfplumber` and `pypdfium2`, as build_san_diego.py does.
"""

import argparse
import html
import json
import logging
import multiprocessing
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests

import build_federal_bills as bills

log = logging.getLogger(__name__)

HF_REPO = "chrissoria/berkeley-ordinances"
DATA_FILE = "data/train-00000-of-00001.parquet"
OUT_DIR = bills.SCRIPT_DIR / "berkeley"
CACHE = bills.SCRIPT_DIR / ".ber_cache.parquet"  # what the weekly pull starts from; kept in step with what is published

API = "https://records.cityofberkeley.info/PublicAccess/api"
HEADERS = {"User-Agent": "cat-pol-datasets (+https://github.com/chrissoria/cat-pol-datasets; chrissoria@berkeley.edu)"}
ORDINANCES = "132"  # the Clerk's "Ordinance Query (Keywords)"
BY_NUMBER = "159"  # its "Doc Number" field
SPANS = (("1800-01-01", "1949-12-31"), ("1950-01-01", "1999-12-31"), ("2000-01-01", "2099-12-31"))

TEXT_COLUMNS = ["number", "text", "text_source", "pages", "ocr_confidence", "problem"]
NEW_COLUMNS = ["text_source", "pages", "ocr_confidence", "code_history"]
PART = 200


# ---------------------------------------------------------------------------
# The Clerk's records
# ---------------------------------------------------------------------------

def search(start="", end="", number=None, tries=4):
    """The ordinances the Clerk lists between two days, or under one number."""
    asked = {"QueryID": ORDINANCES, "Keywords": [{"ID": BY_NUMBER, "Value": str(number)}] if number else [],
             "FromDate": start, "ToDate": end, "QueryLimit": 0}
    for attempt in range(tries):
        try:
            answer = requests.post(f"{API}/CustomQuery/KeywordSearch", data=json.dumps(asked), timeout=180,
                                   headers={**HEADERS, "Content-Type": "application/json"})
            answer.raise_for_status()
            found = answer.json()
            if found.get("Truncated"):
                raise RuntimeError("the Clerk's list came back cut short")
            return found.get("Data") or []
        except (requests.RequestException, ValueError):
            if attempt == tries - 1:
                raise
            time.sleep(3 * (attempt + 1))


def day_of(shown):
    """The Clerk's "9/29/2026" as 2026-09-29, or "" if it is not a day."""
    found = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(shown or "").strip())
    return f"{found[3]}-{int(found[1]):02d}-{int(found[2]):02d}" if found else ""


def listed(rows):
    """What the Clerk lists of each document: the day, the ordinance's number and its name, where it was given one."""
    out = []
    for row in rows:
        date, _, name, number = [(cell.get("Value") or "").strip() for cell in row["DisplayColumnValues"][:4]]
        out.append({"number": number, "date": day_of(date), "title": re.sub(r"\s+", " ", html.unescape(name)), "doc_id": row["ID"]})
    return pd.DataFrame(out, columns=["number", "date", "title", "doc_id"])


def read_listing():
    table = pd.concat([listed(search(start, end)) for start, end in SPANS], ignore_index=True)
    if len(table) < 5000:
        raise RuntimeError(f"the Clerk's list came back with only {len(table)} ordinances")
    return table


# ---------------------------------------------------------------------------
# The dataset
# ---------------------------------------------------------------------------

def number_of(ordinance_number):
    """The Clerk's number for an ordinance of the new series: "Ord. 7999-NS" is 7999. "" for any other."""
    found = re.fullmatch(r"Ord\. (\d+)-NS", str(ordinance_number or "").strip())
    return found[1] if found else ""


def add_listed(dataset, listing):
    """The dataset with the Clerk's day on each ordinance it lists once, and the ordinances passed since the newest here."""
    listing = listing[(listing["number"] != "") & (listing["date"] != "")]
    once = listing.drop_duplicates("number", keep=False).set_index("number")
    out = dataset.copy()
    numbers = out["ordinance_number"].map(number_of)
    known = numbers.isin(once.index)
    dated = numbers[known].map(once["date"])
    changed = int((out.loc[known, "date"] != dated).sum())
    out.loc[known, "date"] = dated
    out.loc[known, "year"] = dated.str[:4].astype(int)

    newest = max([int(n) for n in numbers if n] or [0])
    new = once[[int(n) > newest for n in once.index]]
    rows = pd.DataFrame({
        "date": new["date"], "ordinance_number": [f"Ord. {n}-NS" for n in new.index], "doc_type": "ordinance",
        "title": new["title"], "text": "", "disposition": "", "effective_date": "", "url": "",
        "year": new["date"].str[:4].astype(int),
    }).reset_index(drop=True)
    for column in out.columns:
        if column not in rows.columns:
            rows[column] = None
    rows = rows.sort_values("ordinance_number", ascending=False)
    out = pd.concat([rows[out.columns], out], ignore_index=True) if len(rows) else out
    older = len(set(once.index) - set(numbers)) - len(new)
    return out, {"dated": int(known.sum()), "dates_changed": changed, "added": len(rows), "listed_not_here": older,
                 "here_not_listed": int((~known).sum())}


def texts_kept(folder=None):
    path = Path(folder or OUT_DIR) / "texts.parquet"
    return pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=TEXT_COLUMNS)


def add_texts(dataset, kept):
    """The dataset with the text read from each ordinance's own document, and how it was read.

    Until now `text` held what the municipal code says about an ordinance (what it amends, its disposition). That is kept,
    in `code_history`, and `text` becomes the ordinance.
    """
    out = dataset.copy()
    if "code_history" not in out.columns:
        out["code_history"] = out["text"].fillna("")
        out["text"] = ""
        out["text_source"], out["pages"], out["ocr_confidence"] = "", None, None
    read = kept[kept["text"].fillna("") != ""].drop_duplicates("number", keep="last").set_index("number")
    numbers = out["ordinance_number"].map(number_of)
    has = numbers.isin(read.index)
    for column in ("text", "text_source", "pages", "ocr_confidence"):
        out.loc[has, column] = numbers[has].map(read[column])
    out["pages"] = pd.to_numeric(out["pages"], errors="coerce").astype("Int64")
    out["ocr_confidence"] = pd.to_numeric(out["ocr_confidence"], errors="coerce")
    return out


def published():
    from huggingface_hub import hf_hub_download
    return pd.read_parquet(hf_hub_download(HF_REPO, DATA_FILE, repo_type="dataset", token=bills.HF_TOKEN, force_download=True))


def publish(table):
    """Publish the table, and keep the weekly pull's cache in step with it. False, with why logged, if it could not be."""
    problem = bills.hf_write_problem(HF_REPO)
    if problem:
        log.error(f"Berkeley ordinances not uploaded: {problem}")
        return False
    from datasets import Dataset
    Dataset.from_pandas(table, preserve_index=False).push_to_hub(HF_REPO, token=bills.HF_TOKEN, private=False)
    table.to_parquet(CACHE, index=False)
    return True


def build(dataset, listing, kept, with_texts=False):
    """The table to publish. The texts read here go into it once that has been asked for, and from then on always."""
    out, counts = add_listed(dataset, listing)
    if with_texts or "code_history" in out.columns:
        out = add_texts(out, kept)
    if len(out) < len(dataset):
        raise RuntimeError(f"only {len(out)} rows where there were {len(dataset)}; not publishing")
    counts["with_text"] = int((out["text"].fillna("") != "").sum()) if "code_history" in out.columns else 0
    return out, counts


# ---------------------------------------------------------------------------
# The documents
# ---------------------------------------------------------------------------

def read_document(number):
    """One ordinance's document, found under its number, fetched and read. One that cannot be read comes back with why."""
    import build_san_diego as scans
    empty = {"number": number, "text": "", "text_source": "", "pages": None, "ocr_confidence": None, "problem": ""}
    time.sleep(random.uniform(0.3, 0.6))
    try:
        found = search(number=number)
        if len(found) != 1:
            return {**empty, "problem": f"listed {len(found)} times"}
        answer = requests.get(f"{API}/Document/{quote(found[0]['ID'], safe='')}/", headers=HEADERS, timeout=240)
        answer.raise_for_status()
    except Exception as e:
        return {**empty, "problem": f"not fetched: {type(e).__name__}"}
    if not answer.content.lstrip()[:5].startswith(b"%PDF"):
        return {**empty, "problem": "not a PDF"}
    try:
        return {**empty, **scans.read_pdf(answer.content)}
    except Exception as e:
        return {**empty, "problem": f"not read: {type(e).__name__}"}


def keep_texts(results, folder=None):
    folder = Path(folder or OUT_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    kept = pd.concat([texts_kept(folder), pd.DataFrame(results, columns=TEXT_COLUMNS)], ignore_index=True)
    kept.drop_duplicates("number", keep="last").to_parquet(folder / "texts.parquet", index=False)


def quiet():
    logging.getLogger("pdfminer").setLevel(logging.ERROR)


def read_texts(numbers, workers):
    results, read, problems = [], 0, 0
    with multiprocessing.get_context("spawn").Pool(workers, initializer=quiet, maxtasksperchild=200) as pool:
        for result in pool.imap_unordered(read_document, numbers):
            results.append(result)
            read += 1
            problems += bool(result["problem"])
            if len(results) >= PART:
                keep_texts(results)
                results = []
                log.info(f"{read} of {len(numbers)} read; {problems} could not be")
    if results:
        keep_texts(results)
    return read, problems


def waiting(listing, kept):
    """The numbers whose document has not been read: newest first, and none the Clerk lists twice."""
    once = listing[listing["number"].str.fullmatch(r"\d+")].drop_duplicates("number", keep=False)
    done = set(kept.loc[(kept["text"].fillna("") != "") | kept["problem"].fillna("").str.startswith("listed"), "number"])
    return sorted((n for n in once["number"] if n not in done), key=int, reverse=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Keep the Berkeley ordinances from the City Clerk's records")
    parser.add_argument("--texts", action="store_true", help="read each ordinance's document by OCR; does not publish")
    parser.add_argument("--workers", type=int, default=2, help="documents read at once with --texts")
    parser.add_argument("--limit", type=int, default=0, help="with --texts, read at most this many")
    parser.add_argument("--with-texts", action="store_true",
                        help="put the texts read so far into the table: `text` becomes the ordinance, and what it held is kept in `code_history`")
    parser.add_argument("--no-upload", action="store_true", help="build the table but do not publish it")
    args = parser.parse_args(argv)
    if not args.no_upload and not args.texts and not bills.HF_TOKEN:
        log.error("Berkeley not built: no Hugging Face token; pass --no-upload to build the table only")
        return 1

    try:
        listing = read_listing()
    except Exception as e:
        log.error(f"Berkeley not built: the Clerk's list was not read: {type(e).__name__}: {e}")
        return 1
    if args.texts:
        todo = waiting(listing, texts_kept())
        todo = todo[:args.limit] if args.limit else todo
        log.info(f"{len(todo)} documents to read")
        read, problems = read_texts(todo, args.workers)
        kept = texts_kept()
        log.info(f"RESULT: berkeley-texts listed={len(listing)} read={read} could_not={problems} "
                 f"with_text={int((kept['text'].fillna('') != '').sum())} still_waiting={len(waiting(listing, kept))} pushed=False")
        return 0

    try:
        before = published()
        table, counts = build(before, listing, texts_kept(), args.with_texts)
    except Exception as e:
        log.error(f"Berkeley not built: {type(e).__name__}: {e}")
        return 1
    pushed = False
    if args.no_upload:
        pass
    elif table.equals(before):
        log.info("Nothing new at the Clerk's; not publishing")
    else:
        try:
            pushed = publish(table)
        except Exception as e:
            log.error(f"Berkeley ordinances not uploaded: {type(e).__name__}: {e}")
    log.info(f"RESULT: berkeley rows={len(table)} listed={len(listing)} dated={counts['dated']} "
             f"dates_changed={counts['dates_changed']} added={counts['added']} listed_not_here={counts['listed_not_here']} "
             f"here_not_listed={counts['here_not_listed']} with_text={counts['with_text']} newest={table['date'].max()} "
             f"pushed={pushed}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(main())
