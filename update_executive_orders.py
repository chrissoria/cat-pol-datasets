#!/usr/bin/env python3
"""
Keep chrissoria/executive-orders current.

The dataset is every executive order from 1791 on, with its text. The orders up
to March 2026 came from the American Presidency Project (UC Santa Barbara) in a
one-time build (build_executive_orders_ucsb.py). This script adds what has been
signed since, from the Federal Register API, which needs no key and lists every
order from 1994 on with its number, signing date and text.

Each run:
  1. reads the published table (or --base, to restore from a local copy);
  2. lists every executive order in the Federal Register (two requests);
  3. matches them to the table by order number, or by signing date and title
     for an order that had no number yet when it was first collected, and fills
     in the Federal Register details of the ones already there (entries the
     Register lists without an order number, mostly corrections, are skipped);
  4. fetches the text of the orders that are missing and adds them;
  5. publishes, unless the table would get shorter. A shorter table is never
     published: that is how the dataset was once cut from 10,780 rows to 101.

Usage:
    python update_executive_orders.py                 # the daily update
    python update_executive_orders.py --no-upload     # see what it would do
    python update_executive_orders.py --base checkpoints/executive_orders/eo_final_dataset.parquet --write-card
"""

import argparse
import html
import logging
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

import build_federal_bills as bills

log = logging.getLogger(__name__)

HF_REPO = "chrissoria/executive-orders"
CACHE_FILE = bills.SCRIPT_DIR / ".eo_cache.parquet"
CARD_FILE = bills.SCRIPT_DIR / "README_executive_orders.md"
API = "https://www.federalregister.gov/api/v1/documents.json"
HEADERS = {"User-Agent": "cat-pol-dataset-builder/1.0 (academic research)"}
FIELDS = ["title", "document_number", "publication_date", "signing_date", "executive_order_number",
          "president", "html_url", "pdf_url", "body_html_url"]
COLUMNS = [
    "date", "title", "executive_order_number", "president", "party", "text", "url", "year",
    # Added by this script:
    "source", "document_number", "publication_date", "federal_register_url", "pdf_url",
]
UCSB = "American Presidency Project"
REGISTER = "Federal Register"
# The table names presidents the way the American Presidency Project does.
PARTY = {
    "William J. Clinton": "Democratic", "George W. Bush": "Republican", "Barack Obama": "Democratic",
    "Donald J. Trump (1st Term)": "Republican", "Joseph R. Biden, Jr.": "Democratic",
    "Donald J. Trump (2nd Term)": "Republican",
    # Spellings the one-time build left without a party:
    "Harry S Truman": "Democratic", "George Bush": "Republican", "Martin van Buren": "Democratic",
}


def president_label(name, signed):
    """The Federal Register's name for a president, as the table spells it."""
    if name == "Donald Trump":
        return "Donald J. Trump (2nd Term)" if signed >= "2025-01-20" else "Donald J. Trump (1st Term)"
    return {"Joe Biden": "Joseph R. Biden, Jr.", "Joseph R. Biden Jr.": "Joseph R. Biden, Jr.",
            "Bill Clinton": "William J. Clinton", "William J. Clinton": "William J. Clinton"}.get(name, name)


def get(url, params=None, retries=3):
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, headers=HEADERS, timeout=60)
            if response.status_code == 429:
                time.sleep(20 * (attempt + 1))
                continue
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            log.info(f"Retrying {url.split('?')[0]} after {e.__class__.__name__}")
            time.sleep(3 * (attempt + 1))
    raise requests.RequestException(f"rate limited: {url}")


def fetch_listing():
    """Every executive order the Federal Register has (1994 on), without the text."""
    found, page = [], 1
    while True:
        data = get(API, {"conditions[type]": "PRESDOCU", "conditions[presidential_document_type]": "executive_order",
                         "per_page": 1000, "page": page, "order": "oldest", "fields[]": FIELDS}).json()
        found.extend(data.get("results") or [])
        if not data.get("next_page_url"):
            break
        page += 1
    if len(found) < int(data.get("count") or 0):
        log.warning(f"The Federal Register lists {data.get('count')} orders but returned {len(found)}")
    return found


def plain(markup):
    """An order's HTML body as plain text: one paragraph to a line, without the Register's page and filing marks."""
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", markup or "")
    text = re.sub(r"\s+", " ", text)  # line breaks in the markup mean nothing
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|h[1-6]|li|tr|pre)>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", "", text)).replace("\xa0", " ")
    text = re.sub(r"\(\s*printed page \d+\s*\)", "", text, flags=re.I)
    text = re.sub(r"\[FR Doc\. .*\Z", "", text, flags=re.S)
    lines = [re.sub(r"\s+([.,;:])", r"\1", re.sub(r"[ \t]+", " ", line)).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n\n".join(line for line in lines if line)).strip()


def number_of(value):
    """An order number as digits ("14394"), or "" when there is none."""
    text = "" if value is None else str(value).strip()
    return re.sub(r"\.0$", "", text) if re.fullmatch(r"\d+(\.0)?", text) else ("" if text.lower() in ("", "nan", "none") else text)


def title_key(title):
    """A title without its "Executive Order 14394—" prefix or punctuation, for matching."""
    bare = re.sub(r"^\s*Executive Order(\s+\d+[\w-]*)?\s*[—–-]+\s*", "", title or "", flags=re.I)
    return re.sub(r"[^a-z0-9]", "", bare.lower())


def read_published(path=None):
    """The table as published (or a local copy), in this script's columns."""
    if path is None:
        from huggingface_hub import HfApi, hf_hub_download
        files = sorted(f for f in HfApi(token=bills.HF_TOKEN).list_repo_files(HF_REPO, repo_type="dataset")
                       if f.startswith("data/") and f.endswith(".parquet"))
        df = pd.concat([pd.read_parquet(hf_hub_download(HF_REPO, f, repo_type="dataset", token=bills.HF_TOKEN))
                        for f in files], ignore_index=True)
    else:
        df = pd.read_parquet(path)
    for column in COLUMNS:
        if column not in df.columns:
            df[column] = ""
    for column in COLUMNS:
        if column != "year":
            df[column] = df[column].fillna("").astype(str).replace({"nan": ""})
    df["executive_order_number"] = df["executive_order_number"].map(number_of)
    df["source"] = df["source"].where(df["source"] != "", df["url"].str.contains("federalregister.gov").map({True: REGISTER, False: UCSB}))
    df["party"] = df["party"].where(df["party"] != "", df["president"].map(PARTY).fillna(""))
    return df[COLUMNS]


def merge(existing, listing, fetch_text=True):
    """Add the Federal Register's orders to the table. Returns (table, new rows, rows filled in)."""
    table = existing.to_dict("records")
    by_number = {row["executive_order_number"]: row for row in table if row["executive_order_number"] and row["date"] >= "1993"}
    by_document = {row["document_number"]: row for row in table if row["document_number"]}
    unnumbered = {}
    for row in table:
        if not row["executive_order_number"] and row["date"] >= "1994":
            unnumbered[(row["date"], title_key(row["title"]))] = row
    added = filled = 0
    for doc in listing:
        number = number_of(doc.get("executive_order_number"))
        if not number:
            # The Register files corrections, and a few orders that are not numbered executive
            # orders (blocking an acquisition, say), under the same heading. They are left out.
            continue
        signed = doc.get("signing_date") or doc.get("publication_date") or ""
        row = by_number.get(number) if number else by_document.get(doc.get("document_number") or "")
        row = row or by_document.get(doc.get("document_number") or "") or unnumbered.get((signed, title_key(doc.get("title"))))
        if row is not None:
            # Already in the table: note where the Federal Register has it, and its number if it had none.
            if not row["document_number"]:
                filled += 1
                row["document_number"] = doc.get("document_number") or ""
                row["publication_date"] = doc.get("publication_date") or ""
                row["federal_register_url"] = doc.get("html_url") or ""
                row["pdf_url"] = doc.get("pdf_url") or ""
            if number and not row["executive_order_number"]:
                row["executive_order_number"] = number
                if not re.search(r"\d", row["title"].split("—")[0]):
                    row["title"] = re.sub(r"^\s*Executive Order\s*[—–-]+\s*", f"Executive Order {number}—", row["title"])
                by_number[number] = row
            continue
        text = ""
        if fetch_text and doc.get("body_html_url"):
            try:
                text = plain(get(doc["body_html_url"]).text)
                time.sleep(0.3)
            except requests.RequestException as e:
                log.warning(f"No text for order {number or doc.get('document_number')}: {e}")
        if fetch_text and not text:
            continue  # the next run tries again, rather than keeping an order with no text
        president = president_label((doc.get("president") or {}).get("name") or "", signed)
        new = {
            "date": signed,
            "title": f"Executive Order {number}—{doc.get('title') or ''}" if number else f"Executive Order—{doc.get('title') or ''}",
            "executive_order_number": number,
            "president": president,
            "party": PARTY.get(president, ""),
            "text": text,
            "url": doc.get("html_url") or "",
            "year": int(signed[:4]) if signed[:4].isdigit() else 0,
            "source": REGISTER,
            "document_number": doc.get("document_number") or "",
            "publication_date": doc.get("publication_date") or "",
            "federal_register_url": doc.get("html_url") or "",
            "pdf_url": doc.get("pdf_url") or "",
        }
        table.append(new)
        if number:
            by_number[number] = new
        added += 1
    out = pd.DataFrame(table, columns=COLUMNS)
    out["year"] = pd.to_numeric(out["year"], errors="coerce").fillna(0).astype("int64")
    out = out.sort_values(["date", "executive_order_number"], ascending=False).reset_index(drop=True)
    return out, added, filled


def publish(df, write_card=False):
    from datasets import Dataset
    ds = Dataset.from_pandas(df, preserve_index=False)
    ds.push_to_hub(HF_REPO, token=bills.HF_TOKEN, private=False)
    bills.sync_card_features(ds, HF_REPO)
    if write_card and CARD_FILE.exists():
        from huggingface_hub import DatasetCard
        card = DatasetCard.load(HF_REPO, token=bills.HF_TOKEN)
        card.text = CARD_FILE.read_text()
        card.data["pretty_name"] = "U.S. Executive Orders, 1791 to the present"
        card.push_to_hub(HF_REPO, token=bills.HF_TOKEN, commit_message="Describe the dataset")
    log.info(f"Pushed {len(df)} rows to https://huggingface.co/datasets/{HF_REPO}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Add newly signed executive orders to the dataset")
    parser.add_argument("--base", help="start from this parquet instead of the published table")
    parser.add_argument("--no-upload", action="store_true", help="work out the update but do not publish it")
    parser.add_argument("--write-card", action="store_true", help="also publish README_executive_orders.md as the dataset card")
    args = parser.parse_args(argv)

    if not args.no_upload:
        problem = "no Hugging Face token" if not bills.HF_TOKEN else bills.hf_write_problem(HF_REPO)
        if problem:
            log.error(f"Executive orders not updated: {problem}")
            return 1
    try:
        existing = read_published(args.base)
        published = len(existing) if args.base is None else len(read_published())
    except Exception as e:
        log.error(f"Executive orders not updated: the current table could not be read ({e})")
        return 1
    try:
        listing = fetch_listing()
    except Exception as e:
        log.error(f"Executive orders not updated: the Federal Register could not be reached ({e})")
        return 1
    if not listing:
        log.error("Executive orders not updated: the Federal Register returned no orders")
        return 1

    table, added, filled = merge(existing, listing)
    newest = table["date"].max()
    pushed = False
    if len(table) < published and args.base is None:
        log.error(f"Executive orders not updated: the table would shrink from {published} to {len(table)} rows")
        return 1
    if args.no_upload:
        pass
    elif added or filled or args.base or args.write_card:
        table.to_parquet(CACHE_FILE, index=False)
        publish(table, write_card=args.write_card)
        pushed = True
    log.info(f"RESULT: executive-orders total={len(table)} new={added} matched={filled} newest={newest} pushed={pushed}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(main())
