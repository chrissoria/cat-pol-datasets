#!/usr/bin/env python3
"""
Fill in chrissoria/san-diego-ordinances: every ordinance and resolution the
City of San Diego's Clerk has put online, with the text of each.

Two things were missing from the dataset, and this fills both.

The list. The Clerk's listing at sandiego.gov sorts by date alone and shows 50
rows a page, so documents adopted on the same day change places between pages:
one pass shows some twice and others not at all. It is read here three ways,
each of which hides different rows, and the three are put together:

    straight   the listing as it comes, page after page
    years      the listing one year at a time
    search     the Clerk's document search one year at a time, ten rows a page;
               only for the years still short of the count the search gives

The text. Documents from before 2021 are scanned pages with no text in them.
A page that has text of its own is read as it is; a page that has none is read
by OCR (Tesseract). Three columns say which: text_source ("pdf", "ocr" or
"pdf+ocr"), pages, and ocr_confidence (the mean confidence Tesseract gives its
words, 0 to 100). OCR stops at MAX_PAGES pages of a document.

    python build_san_diego.py --list straight|years|search
        Read the listing one way and keep what it showed in sandiego/passes/.

    python build_san_diego.py --texts
        Read the documents that have no text yet, ordinances first and then
        resolutions from the newest back. Saves every 500 documents in
        sandiego/texts/ and can be stopped and started again.

    python build_san_diego.py --status
        What is listed, what the search says there is, and what has text.

    --max-docs N       documents to read in one run (default: all of them)
    --workers N        documents read at once (default 6)
    --publish-every N  publish each time this many more are read (default 10000)
    --retry            try again the documents that could not be read
    --no-upload        keep what is read here but do not publish it
    --publish-only     publish what is kept here and read nothing

Needs tesseract on the PATH, and pdfplumber and pypdfium2.
"""

import argparse
import csv
import io
import logging
import multiprocessing
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd
import requests

import build_federal_bills as bills

log = logging.getLogger(__name__)

HF_REPO = "chrissoria/san-diego-ordinances"
DATA_FILE = "data/train-00000-of-00001.parquet"
OUT_DIR = bills.SCRIPT_DIR / "sandiego"
CACHE = bills.SCRIPT_DIR / ".sd_cache.parquet"  # what the weekly pull starts from; kept in step with what is published

LISTING = "https://www.sandiego.gov/city-clerk/officialdocs/council-resolutions-ordinances"
SEARCH = "https://www.sandiego.gov/search/ocd"
YEAR_FILTER = "field_doc_date_year_value"
KIND = "facet_searchp_ocd_doc_type:council-resolutions-and-ordinances"
YEAR_FACET = "facet_searchp_ocd_doc_date_year"
HEADERS = {"User-Agent": "cat-pol-datasets (+https://github.com/chrissoria/cat-pol-datasets; chrissoria@berkeley.edu)"}

INDEX_COLUMNS = ["date", "doc_num", "doc_num_alt", "doc_type", "title", "pdf_url", "year"]
TEXT_COLUMNS = ["pdf_url", "text", "text_source", "pages", "ocr_confidence", "problem"]
NEW_COLUMNS = ["text_source", "pages", "ocr_confidence"]
WAYS = ("straight", "years", "search")

MAX_PAGES = 100  # OCR stops here; a few documents carry plans of several hundred pages
LAYER_CHARS = 40  # a page with this much text of its own is not put through OCR
DPI = 200
LONGEST = 4400  # pixels on a page's longer side, at most
PART = 500

_session = None


def fetch(url, params=None, tries=6):
    """One page or document, asked for again after a failure; this Mac sometimes runs out of sockets under load."""
    global _session
    if _session is None:
        _session = requests.Session()
    for attempt in range(tries):
        try:
            response = _session.get(url, params=params, headers=HEADERS, timeout=60)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(4 * (attempt + 1))


def secure(url):
    """The Clerk lists documents at http; the same server answers at https."""
    return re.sub(r"^http://", "https://", (url or "").strip())


def number_of(url):
    """The number a document's file is named for: .../rao2019/R-312806.pdf.pdf is R-312806."""
    name = (url or "").rsplit("/", 1)[-1]
    name = re.sub(r"(\.pdf)+$", "", name, flags=re.I)
    return name.strip()


def kind_of(number):
    if number.startswith("O-"):
        return "ordinance"
    if number.startswith("R-"):
        return "resolution"
    return "unknown"


def last_page(html):
    pages = [int(n) for n in re.findall(r"[?&;]page=(\d+)", html)]
    return max(pages) if pages else 0


def listing_rows(html):
    """The rows of one page of the listing, as the dataset has always kept them."""
    from build_san_diego_dataset import _parse_table_html
    return [{column: row[column] for column in INDEX_COLUMNS} for row in _parse_table_html(html)]


def search_rows(html):
    """The rows of one page of the document search: a date, a title and the document."""
    from bs4 import BeautifulSoup
    rows = []
    content = BeautifulSoup(html, "html.parser").find("div", class_="view-content")
    for link in content.find_all("a") if content else []:
        url = (link.get("href") or "").strip()
        stamp = link.find("time")
        if "council_reso_ordinance" not in url or stamp is None:
            continue
        date = (stamp.get("datetime") or "")[:10]
        title = link.get_text(" ", strip=True)
        title = title[len(stamp.get_text(" ", strip=True)):].lstrip(" -–\xa0").strip()
        number = number_of(url)
        rows.append({"date": date, "doc_num": number, "doc_num_alt": None, "doc_type": kind_of(number), "title": title,
                     "pdf_url": url, "year": int(date[:4]) if date[:4].isdigit() else 0})
    return rows


def search_counts():
    """How many ordinances and resolutions the search holds for each year."""
    return year_counts(fetch(SEARCH, {"search_text": "", "f[0]": KIND}).text)


def year_counts(html):
    """The counts beside the years the search offers to narrow by: "1975 (2978)"."""
    from bs4 import BeautifulSoup
    counts = {}
    for link in BeautifulSoup(html, "html.parser").find_all("a"):
        found = re.fullmatch(r"(\d{4})\s*\(([\d,]+)\)", link.get_text(" ", strip=True))
        if found and YEAR_FACET in (link.get("href") or ""):
            counts[int(found.group(1))] = int(found.group(2).replace(",", ""))
    return counts


def pause():
    time.sleep(random.uniform(0.5, 1.0))


def read_pages(url, params, rows_of, label):
    """Every page of one listing, first to last."""
    first = fetch(url, params).text
    rows = rows_of(first)
    for page in range(1, last_page(first) + 1):
        pause()
        try:
            found = rows_of(fetch(url, {**params, "page": str(page)}).text)
        except Exception as e:
            log.warning(f"{label}: page {page} not read: {type(e).__name__}")
            continue
        rows.extend(found)
        if page % 100 == 0:
            log.info(f"{label}: page {page}, {len(rows)} rows")
    return rows


def pass_file(way, part=""):
    return OUT_DIR / "passes" / f"{way}{'-' + str(part) if part != '' else ''}.parquet"


def keep_pass(rows, way, part=""):
    path = pass_file(way, part)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=INDEX_COLUMNS).to_parquet(path, index=False)
    return path


def read_listing(way, years=None):
    """Read the listing one way. Years already kept from an earlier run of the same way are not read again."""
    if way == "straight":
        rows = read_pages(LISTING, {}, listing_rows, "straight")
        keep_pass(rows, way)
        return len(rows)
    counts = search_counts()
    if not counts:
        raise RuntimeError("the search gave no counts by year")
    total = 0
    for year in sorted(counts if years is None else years, reverse=True):
        if pass_file(way, year).exists():
            continue
        if way == "years":
            rows = read_pages(LISTING, {YEAR_FILTER: str(year)}, listing_rows, f"years {year}")
        else:
            rows = read_pages(SEARCH, {"search_text": "", "f[0]": f"{YEAR_FACET}:{year}", "f[1]": KIND}, search_rows, f"search {year}")
        keep_pass(rows, way, year)
        total += len(rows)
        log.info(f"{way} {year}: {len(rows)} rows, {len({r['pdf_url'] for r in rows})} documents; the search counts {counts.get(year)}")
        pause()
    return total


def merge_index(frames):
    """One row a document from several readings. A document is its address; the first reading that has it is kept,
    so the listing (which gives the second number) goes before the search (which does not)."""
    frames = [f[INDEX_COLUMNS] for f in frames if f is not None and len(f)]
    if not frames:
        return pd.DataFrame(columns=INDEX_COLUMNS)
    merged = pd.concat(frames, ignore_index=True)
    merged = merged[merged["pdf_url"].fillna("").str.strip() != ""]
    merged["address"] = merged["pdf_url"].map(secure).str.lower()
    return merged.drop_duplicates("address").drop(columns="address").reset_index(drop=True)


def passes():
    """What every reading of the listing kept here showed, listing readings first."""
    folder = OUT_DIR / "passes"
    files = sorted(folder.glob("*.parquet"), key=lambda p: (p.name.startswith("search"), p.name)) if folder.exists() else []
    return [pd.read_parquet(path) for path in files]


def short_years(index, counts):
    """The years in which fewer documents are listed than the search says there are."""
    have = index.groupby("year").size().to_dict()
    return {year: count - have.get(year, 0) for year, count in counts.items() if have.get(year, 0) < count}


# ---------------------------------------------------------------------------
# The text of a document
# ---------------------------------------------------------------------------


def ocr_image(image):
    """The text Tesseract reads on one page and the confidence of each word."""
    with tempfile.TemporaryDirectory() as folder:
        picture, out = os.path.join(folder, "page.png"), os.path.join(folder, "out")
        image.save(picture)
        subprocess.run(["tesseract", picture, out, "-l", "eng", "txt", "tsv"], capture_output=True, timeout=180,
                       env={**os.environ, "OMP_THREAD_LIMIT": "1"})
        with open(out + ".txt", encoding="utf-8", errors="replace") as f:
            text = f.read().replace("\f", "").strip()
        confidence = []
        with open(out + ".tsv", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
                try:
                    value = float(row["conf"])
                except (KeyError, TypeError, ValueError):
                    continue
                if value >= 0 and (row.get("text") or "").strip():
                    confidence.append(value)
    return text, confidence


def source_of(from_layer, from_ocr):
    if from_ocr and from_layer:
        return "pdf+ocr"
    return "ocr" if from_ocr else "pdf" if from_layer else ""


def read_pdf(body, ocr=ocr_image):
    """The text of a PDF: each page's own text where it has some, and OCR where it has none."""
    import pdfplumber
    import pypdfium2
    texts, confidence, from_layer, from_ocr = [], [], 0, 0
    with pdfplumber.open(io.BytesIO(body)) as layered:
        count = len(layered.pages)
        rendered = None
        for index in range(min(count, MAX_PAGES)):
            try:
                own = (layered.pages[index].extract_text() or "").strip()
            except Exception:
                own = ""
            if len(re.sub(r"\s", "", own)) >= LAYER_CHARS:
                texts.append(own)
                from_layer += 1
                continue
            if rendered is None:
                rendered = pypdfium2.PdfDocument(body)
            try:
                page = rendered[index]
                scale = min(DPI / 72, LONGEST / max(page.get_size()))  # a plan sheet is not drawn a hundred megapixels large
                text, words = ocr(page.render(scale=scale, grayscale=True).to_pil())
            except Exception:
                text, words = "", []
            from_ocr += 1
            confidence.extend(words)
            if text:
                texts.append(text)
    return {"text": "\n\n".join(texts), "text_source": source_of(from_layer, from_ocr), "pages": count,
            "ocr_confidence": round(sum(confidence) / len(confidence), 1) if confidence else None, "problem": ""}


def read_document(url):
    """One document, fetched and read. A document that cannot be read comes back with why."""
    empty = {"pdf_url": url, "text": "", "text_source": "", "pages": None, "ocr_confidence": None, "problem": ""}
    time.sleep(random.uniform(0.2, 0.4))
    try:
        response = fetch(secure(url))
    except Exception as e:
        return {**empty, "problem": f"not fetched: {type(e).__name__}"}
    if response is None:
        return {**empty, "problem": "not found"}
    if not response.content.lstrip()[:5].startswith(b"%PDF"):
        return {**empty, "problem": "not a PDF"}
    try:
        return {**empty, **read_pdf(response.content)}
    except Exception as e:
        return {**empty, "problem": f"not read: {type(e).__name__}"}


def texts_kept(folder=None):
    """Every document read so far, the latest reading of each."""
    folder = Path(folder or OUT_DIR / "texts")
    files = sorted(folder.glob("part-*.parquet")) if folder.exists() else []
    if not files:
        return pd.DataFrame(columns=TEXT_COLUMNS)
    kept = pd.concat([pd.read_parquet(path) for path in files], ignore_index=True)
    return kept.drop_duplicates("pdf_url", keep="last").reset_index(drop=True)


def keep_texts(results):
    folder = OUT_DIR / "texts"
    folder.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(results, columns=TEXT_COLUMNS)
    frame["pages"] = frame["pages"].astype("Int64")
    frame["ocr_confidence"] = frame["ocr_confidence"].astype("float64")
    frame.to_parquet(folder / f"part-{int(time.time() * 1000)}.parquet", index=False)


def waiting(dataset, kept, retry=False):
    """The documents to read, in order: ordinances, then resolutions and the rest, each from the newest back."""
    done = kept if retry is False else kept[kept["problem"].fillna("") == ""]
    todo = dataset[(dataset["text"].fillna("") == "") & (dataset["pdf_url"].fillna("") != "")
                   & ~dataset["pdf_url"].isin(set(done["pdf_url"]))]
    todo = todo.assign(later=(todo["doc_type"] != "ordinance").astype(int))
    return todo.sort_values(["later", "date"], ascending=[True, False], kind="stable")["pdf_url"].tolist()


# ---------------------------------------------------------------------------
# The dataset
# ---------------------------------------------------------------------------


def published():
    """The table as published. It is one file unless a publishing split it in parts, which are then read as one."""
    from huggingface_hub import HfApi, hf_hub_download
    listed = HfApi(token=bills.HF_TOKEN).list_repo_files(HF_REPO, repo_type="dataset")
    parts = sorted(name for name in listed if re.fullmatch(r"data/train-\d+-of-\d+\.parquet", name)) or [DATA_FILE]
    return pd.concat([pd.read_parquet(hf_hub_download(HF_REPO, part, repo_type="dataset", token=bills.HF_TOKEN)) for part in parts],
                     ignore_index=True)


def add_listed(dataset, index):
    """Add the documents listed that the dataset does not have. Returns the dataset and how many were left out
    because their number is another document's."""
    have = set(dataset["pdf_url"].map(secure).str.lower())
    new = index[~index["pdf_url"].map(secure).str.lower().isin(have)].copy()
    taken, rows, left_out = set(dataset["doc_num"]), [], 0
    for row in new.to_dict("records"):
        number = row["doc_num"]
        if number in taken:  # the listing gives two documents one number; the file's own name tells them apart
            number = number_of(row["pdf_url"])
            if number in taken or not re.fullmatch(r"[A-Z]{1,2}-[\w.-]+", number):
                left_out += 1
                continue
            row.update(doc_num=number, doc_type=kind_of(number))
        taken.add(number)
        rows.append({**row, "text": ""})
    if not rows:
        return dataset, left_out
    added = pd.DataFrame(rows).reindex(columns=dataset.columns)
    added["text"] = ""
    for column in dataset.columns:  # an added row is empty where the dataset has columns the listing does not give
        if column not in added.columns or added[column].isna().all():
            added[column] = pd.Series([None] * len(added), dtype=dataset[column].dtype)
    return pd.concat([dataset, added.astype(dataset.dtypes.to_dict(), errors="ignore")], ignore_index=True), left_out


def add_texts(dataset, kept):
    """Give each document without text the text read for it, and say where every text came from."""
    dataset = dataset.copy()
    for column, kind in (("text_source", "object"), ("pages", "Int64"), ("ocr_confidence", "float64")):
        if column not in dataset.columns:
            dataset[column] = pd.Series([None] * len(dataset), dtype=kind)
    dataset["pages"] = dataset["pages"].astype("Int64")  # whole numbers with gaps come back from a parquet file as floats
    had = dataset["text"].fillna("") != ""
    dataset.loc[had & dataset["text_source"].isna(), "text_source"] = "pdf"  # all text before this was the PDF's own
    read = kept[kept["problem"].fillna("") == ""].set_index("pdf_url")
    rows = ~had & dataset["pdf_url"].isin(read.index)
    urls = dataset.loc[rows, "pdf_url"]
    source = urls.map(read["text_source"])
    dataset.loc[rows, "text"] = urls.map(read["text"]).fillna("")
    dataset.loc[rows, "text_source"] = source.where(source.fillna("") != "", None)
    dataset.loc[rows, "pages"] = urls.map(read["pages"]).astype("Int64")
    dataset.loc[rows, "ocr_confidence"] = urls.map(read["ocr_confidence"]).astype("float64")
    return dataset


def assemble(dataset, index, kept):
    dataset, left_out = add_listed(dataset, index)
    dataset = add_texts(dataset, kept)
    dataset = dataset.sort_values("date", ascending=False, kind="stable").reset_index(drop=True)
    return dataset, left_out


def publish():
    """Put what is listed and read here onto what is published now, and publish that."""
    problem = bills.hf_write_problem(HF_REPO)
    if problem:
        log.error(f"San Diego not published: {problem}")
        return None
    before = published()
    dataset, left_out = assemble(before, merge_index(passes()), texts_kept())
    had, has = int((before["text"].fillna("") != "").sum()), int((dataset["text"].fillna("") != "").sum())
    if len(dataset) < len(before) or has < had or dataset["doc_num"].duplicated().any():
        raise RuntimeError(f"{len(dataset)} rows and {has} texts where there were {len(before)} and {had}; not publishing")
    from datasets import Dataset
    # One file whatever its size: the table is read by that file's name, here and by whoever uses the dataset.
    Dataset.from_pandas(dataset, preserve_index=False).push_to_hub(HF_REPO, token=bills.HF_TOKEN, private=False,
                                                                   max_shard_size="8GB")
    dataset.to_parquet(CACHE, index=False)
    log.info(f"Published {len(dataset)} rows, {has} with text ({len(dataset) - len(before)} new rows, {has - had} new texts, "
             f"{left_out} left out for a number already taken)")
    return {"rows": len(dataset), "with_text": has, "new_rows": len(dataset) - len(before), "new_texts": has - had}


def quiet():
    """pdfminer warns about every oddity in a scanned file."""
    logging.getLogger("pdfminer").setLevel(logging.ERROR)


def read_texts(urls, workers, publish_every, upload):
    """Read the documents, keeping every PART of them and publishing every so often."""
    results, read, problems, since = [], 0, 0, 0
    with multiprocessing.get_context("spawn").Pool(workers, initializer=quiet, maxtasksperchild=300) as pool:
        for result in pool.imap_unordered(read_document, urls):
            results.append(result)
            read += 1
            problems += bool(result["problem"])
            if len(results) >= PART:
                keep_texts(results)
                since += len(results)
                results = []
                log.info(f"{read} of {len(urls)} read; {problems} could not be")
                if upload and since >= publish_every:
                    since = 0
                    try:
                        publish()
                    except Exception as e:
                        log.error(f"San Diego not published this time: {type(e).__name__}: {e}")
    if results:
        keep_texts(results)
    return read, problems


def status():
    dataset = published()
    index = merge_index([dataset] + passes())
    kept = texts_kept()
    counts = search_counts()
    short = short_years(index, counts)
    log.info(f"RESULT: san-diego-status published={len(dataset)} with_text={int((dataset['text'].fillna('') != '').sum())} "
             f"listed={len(index)} search_count={sum(counts.values())} years_short={len(short)} documents_short={sum(short.values())} "
             f"read_here={len(kept)} unreadable={int((kept['problem'].fillna('') != '').sum())}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fill in the City of San Diego ordinances and resolutions dataset")
    parser.add_argument("--list", choices=WAYS, help="read the listing one way")
    parser.add_argument("--texts", action="store_true", help="read the documents that have no text")
    parser.add_argument("--status", action="store_true", help="say what is listed and read, and stop")
    parser.add_argument("--max-docs", type=int, default=0, help="documents to read in one run (0 for all)")
    parser.add_argument("--workers", type=int, default=6, help="documents read at once")
    parser.add_argument("--publish-every", type=int, default=10000, help="publish each time this many more are read")
    parser.add_argument("--retry", action="store_true", help="try again the documents that could not be read")
    parser.add_argument("--no-upload", action="store_true", help="keep what is read here but do not publish it")
    parser.add_argument("--publish-only", action="store_true", help="publish what is kept here and read nothing")
    args = parser.parse_args(argv)
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to keep what is read here only")
    if args.status:
        return status()

    listed = read = problems = 0
    if args.list:
        years = None
        if args.list == "search":  # ten rows a page, so only the years the other two ways leave short
            index = merge_index([published()] + passes())
            years = sorted(short_years(index, search_counts()))
            log.info(f"The search is read for {len(years)} years still short")
        listed = read_listing(args.list, years)
    if args.texts:
        dataset, _ = add_listed(published(), merge_index(passes()))
        urls = waiting(dataset, texts_kept(), args.retry)
        if args.max_docs:
            urls = urls[:args.max_docs]
        log.info(f"{len(urls)} documents to read, {args.workers} at once")
        read, problems = read_texts(urls, args.workers, args.publish_every, not args.no_upload)
    done = None
    if not args.no_upload and (args.texts or args.list or args.publish_only):
        try:
            done = publish()
        except Exception as e:
            log.error(f"San Diego not published: {type(e).__name__}: {e}")
    log.info(f"RESULT: san-diego listed={listed} read={read} unreadable={problems} "
             f"rows={done['rows'] if done else 'not published'} with_text={done['with_text'] if done else 'not published'} "
             f"pushed={done is not None}")
    return 0 if args.no_upload or done else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    sys.exit(main())
