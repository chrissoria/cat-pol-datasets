#!/usr/bin/env python3
"""Generic Legistar scraper: fetch ordinances & resolutions for any Legistar city → HuggingFace.

Supports: Oakland, Long Beach, Fresno, Salinas (and any other Legistar city).

Usage:
    python scripts/build_legistar_dataset.py oakland
    python scripts/build_legistar_dataset.py longbeach
    python scripts/build_legistar_dataset.py fresno
    python scripts/build_legistar_dataset.py oakland --no-text
    python scripts/build_legistar_dataset.py oakland --push-only
    python scripts/build_legistar_dataset.py oakland --backfill   # complete the published table locally; never publishes

Dependencies:
    pip install -r scripts/requirements.txt
"""

from __future__ import annotations

import argparse
import io
import os
import random
import re
import signal
import subprocess
import tempfile
import time
import warnings
from pathlib import Path

import pandas as pd
import requests

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

CHECKPOINT_DIR = Path(__file__).parent / "checkpoints"
API_BASE = "https://webapi.legistar.com/v1"

HEADERS = {
    "User-Agent": "cat-pol-dataset-builder/1.0 (academic research; chrissoria@berkeley.edu)",
}

# City configurations: slug → (display_name, hf_repo, matter_types)
CITY_CONFIG = {
    "oakland": {
        "name": "Oakland",
        "repo": "chrissoria/oakland-ordinances",
        "types": ["Ordinance"],  # Oakland has no resolutions in Legistar
    },
    "longbeach": {
        "name": "Long Beach",
        "repo": "chrissoria/long-beach-ordinances",
        "types": ["Ordinance", "Resolution"],
    },
    "fresno": {
        "name": "Fresno",
        "repo": "chrissoria/fresno-ordinances",
        "types": ["Ordinance", "Resolution"],
    },
    "salinas": {
        "name": "Salinas",
        "repo": "chrissoria/salinas-ordinances",
        "types": ["Ordinance", "Resolution"],
    },
}

DATASET_COLUMNS = [
    "date", "matter_id", "matter_file", "enactment_number", "doc_type",
    "title", "text", "attachment_url", "year",
]


def _jittered_sleep(base: float) -> None:
    time.sleep(base * random.uniform(0.5, 1.5))


# ---------------------------------------------------------------------------
# Legistar API
# ---------------------------------------------------------------------------


def fetch_all_matters(city_slug: str, matter_type: str, strict: bool = False) -> list[dict]:
    """Fetch all matters of a given type from the Legistar API.

    strict: raise when a page cannot be read, rather than return the pages read so far.
    """
    all_items = []
    skip = 0
    while True:
        for attempt in range(5):
            try:
                resp = requests.get(
                    f"{API_BASE}/{city_slug}/matters",
                    params={
                        "$filter": f"MatterTypeName eq '{matter_type}'",
                        "$top": 1000,
                        "$skip": skip,
                        # MatterId breaks ties, so that $skip paging cannot repeat or drop a matter
                        "$orderby": "MatterIntroDate desc,MatterId desc",
                    },
                    headers=HEADERS,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as e:
                wait = (attempt + 1) * 10
                print(f"  [retry {attempt + 1}/5] API error: {e}, waiting {wait}s...")
                time.sleep(wait)
                data = None
        if data is None:
            if strict:
                raise RuntimeError(f"Legistar API unreachable for {city_slug} {matter_type} at $skip={skip}")
            print("  [error] Giving up after 5 retries")
            break
        if not data:
            break
        all_items.extend(data)
        skip += 1000
        if len(data) < 1000:
            break
        _jittered_sleep(2.0)
    return all_items


def fetch_attachments(city_slug: str, matter_id: int, strict: bool = False) -> list[dict]:
    """Fetch attachments for a specific matter (with retry).

    strict: raise when the API cannot be read, rather than answer "no attachments".
    """
    for attempt in range(3):
        try:
            resp = requests.get(
                f"{API_BASE}/{city_slug}/matters/{matter_id}/attachments",
                headers=HEADERS,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            if attempt < 2:
                time.sleep((attempt + 1) * 5)
    if strict:
        raise RuntimeError(f"Legistar API unreachable for {city_slug} matter {matter_id} attachments")
    return []


def find_best_attachment(attachments: list[dict]) -> str:
    """Find the best PDF attachment URL."""
    # Prefer PDFs with ordinance/resolution in name
    for att in attachments:
        url = att.get("MatterAttachmentHyperlink") or ""
        name = (att.get("MatterAttachmentName") or "").lower()
        if url.endswith(".pdf") and ("ordinance" in name or "resolution" in name):
            return url
    # Fall back to first PDF
    for att in attachments:
        url = att.get("MatterAttachmentHyperlink") or ""
        if url.endswith(".pdf"):
            return url
    # Fall back to any attachment with a URL
    for att in attachments:
        url = att.get("MatterAttachmentHyperlink") or ""
        if url:
            return url
    return ""


# ---------------------------------------------------------------------------
# Document text extraction
# ---------------------------------------------------------------------------


def extract_text(url: str, session: requests.Session) -> str:
    """Download a PDF or DOCX and extract text."""
    if not url:
        return ""

    url_lower = url.lower()

    try:
        resp = session.get(url, headers=HEADERS, timeout=60, verify=False)
        resp.raise_for_status()
    except Exception:
        return ""

    if url_lower.endswith(".pdf"):
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
                pages = [p.extract_text() for p in pdf.pages if p.extract_text()]
                return "\n\n".join(pages)
        except Exception:
            return ""

    if url_lower.endswith(".docx"):
        try:
            from docx import Document
            doc = Document(io.BytesIO(resp.content))
            return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception:
            return ""

    return ""


# Keep old name as alias for backwards compat
extract_pdf_text = extract_text


class _TooSlow(Exception):
    pass


def _raise_too_slow(signum, frame):
    raise _TooSlow()


def _document_url(url: str) -> str:
    """Where a document can actually be fetched.

    Long Beach's API gives every attachment as https://longbeach.legistar.com/Legislation.aspx<file>,
    which answers 404; the file itself is at https://legistar2.granicus.com/longbeach/attachments/<file>.
    """
    match = re.match(r"https?://(\w+)\.legistar\.com/Legislation\.aspx([^/?]+\.\w+)$", url)
    if match:
        return f"https://legistar2.granicus.com/{match.group(1)}/attachments/{match.group(2)}"
    return url


def _download(url: str, session: requests.Session, tries: int = 4) -> tuple[bytes, str]:
    """GET a document, backing off on 429, 5xx and dropped connections. Returns (bytes, "ok" or why not)."""
    url = _document_url(url)
    status = "download_failed"
    for attempt in range(tries):
        try:
            resp = session.get(url, headers=HEADERS, timeout=60, verify=False)
        except requests.RequestException as e:
            status = f"download_failed:{type(e).__name__}"
        else:
            if resp.status_code == 200:
                return resp.content, "ok"
            status = f"download_failed:{resp.status_code}"
            if resp.status_code != 429 and resp.status_code < 500:
                break  # 403, 404 and the like will not get better
        if attempt < tries - 1:
            time.sleep(15 * 2 ** attempt)
    return b"", status


def extract_text_status(url: str, session: requests.Session, time_limit: int = 300) -> tuple[str, str]:
    """As extract_text, but also says why a document gave no text. No OCR.

    Returns (text, status). status is one of: text, no_attachment, unsupported_type,
    download_failed:<why>, no_text_layer (a PDF that opens and has no text of its own:
    a scan), unreadable (the file would not open, or took too long), no_text_extracted
    (a Word file with nothing in it).
    """
    if not url:
        return "", "no_attachment"
    url_lower = url.lower()
    if not url_lower.endswith((".pdf", ".docx", ".doc")):
        return "", "unsupported_type"

    content, status = _download(url, session)
    if status != "ok":
        return "", status

    old_handler = signal.signal(signal.SIGALRM, _raise_too_slow)
    signal.alarm(time_limit)
    try:
        if url_lower.endswith(".pdf"):
            import pdfplumber
            pages = []
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        pages.append(page_text)
                    page.flush_cache()
            text = "\n\n".join(pages)
            return (text, "text") if text.strip() else ("", "no_text_layer")

        if url_lower.endswith(".docx"):
            from docx import Document
            doc = Document(io.BytesIO(content))
            text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
            return (text, "text") if text.strip() else ("", "no_text_extracted")

        # .doc, read the way lib/document_text.py reads it
        with tempfile.NamedTemporaryFile(suffix=".doc") as tmp:
            tmp.write(content)
            tmp.flush()
            result = subprocess.run(
                ["textutil", "-convert", "txt", "-stdout", tmp.name],
                capture_output=True, text=True, timeout=30,
            )
        text = result.stdout.strip() if result.returncode == 0 else ""
        return (text, "text") if text else ("", "no_text_extracted")
    except Exception:  # includes _TooSlow
        return "", "unreadable"
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def build_dataset(
    city_slug: str,
    extract_text: bool = True,
    pdf_delay: float = 1.0,
    checkpoint_every: int = 50,
) -> pd.DataFrame:
    """Fetch all ordinances/resolutions for a Legistar city with incremental checkpointing."""
    config = CITY_CONFIG[city_slug]
    session = requests.Session()
    all_rows: list[dict] = []

    # Load already-processed matter IDs from checkpoints
    processed_ids: set[str] = set()
    for cp_file in CHECKPOINT_DIR.glob(f"{city_slug}_*.parquet"):
        if "final" not in cp_file.name:
            cp_df = pd.read_parquet(cp_file)
            all_rows.extend(cp_df.to_dict("records"))
            processed_ids.update(cp_df["matter_id"].astype(str).tolist())
    if processed_ids:
        print(f"Resuming: {len(processed_ids)} matters already processed")

    for matter_type in config["types"]:
        doc_type = matter_type.lower()
        print(f"Fetching {matter_type}s for {config['name']}...")
        matters = fetch_all_matters(city_slug, matter_type)
        print(f"  Found {len(matters)} {doc_type}s")

        batch_rows: list[dict] = []
        batch_count = 0

        for i, matter in enumerate(matters):
            matter_id = str(matter["MatterId"])

            # Skip already-processed
            if matter_id in processed_ids:
                continue

            intro_date = matter.get("MatterIntroDate", "") or ""
            date = intro_date[:10] if intro_date else ""

            try:
                year = int(date[:4]) if date else 0
            except ValueError:
                year = 0

            # Fetch attachment with rate limiting
            attachments = fetch_attachments(city_slug, int(matter_id))
            attachment_url = find_best_attachment(attachments)
            _jittered_sleep(1.0)

            row = {
                "date": date,
                "matter_id": matter_id,
                "matter_file": matter.get("MatterFile", ""),
                "enactment_number": matter.get("MatterEnactmentNumber", "") or "",
                "doc_type": doc_type,
                "title": matter.get("MatterTitle", ""),
                "text": "",
                "attachment_url": attachment_url,
                "year": year,
            }

            if extract_text and attachment_url:
                row["text"] = extract_pdf_text(attachment_url, session)
                _jittered_sleep(pdf_delay)

            batch_rows.append(row)
            processed_ids.add(matter_id)
            batch_count += 1

            if batch_count % 25 == 0:
                print(f"  Processed {i + 1}/{len(matters)} ({batch_count} new)")

            # Incremental checkpoint
            if batch_count % checkpoint_every == 0 and batch_rows:
                cp_path = CHECKPOINT_DIR / f"{city_slug}_{doc_type}s_{batch_count:05d}.parquet"
                pd.DataFrame(batch_rows).to_parquet(cp_path, index=False)
                print(f"  [checkpoint] Saved {len(batch_rows)} rows to {cp_path.name}")
                all_rows.extend(batch_rows)
                batch_rows = []

        # Save remaining batch
        if batch_rows:
            cp_path = CHECKPOINT_DIR / f"{city_slug}_{doc_type}s_final.parquet"
            pd.DataFrame(batch_rows).to_parquet(cp_path, index=False)
            print(f"  [checkpoint] Saved {len(batch_rows)} {doc_type}s (final)")
            all_rows.extend(batch_rows)

    df = pd.DataFrame(all_rows, columns=DATASET_COLUMNS)
    df = df.drop_duplicates(subset=["matter_id"], keep="first").reset_index(drop=True)
    return df


def merge_checkpoints(city_slug: str) -> pd.DataFrame:
    """Merge all checkpoint files for a city."""
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    dfs = []
    for cp_file in sorted(CHECKPOINT_DIR.glob(f"{city_slug}_*.parquet")):
        if "final" not in cp_file.name:
            dfs.append(pd.read_parquet(cp_file))
    if not dfs:
        print(f"No checkpoint files found for {city_slug}.")
        return pd.DataFrame()
    df = pd.concat(dfs, ignore_index=True)
    df = df.drop_duplicates(subset=["matter_id"], keep="first").reset_index(drop=True)
    print(f"Merged {len(df)} unique rows from {len(dfs)} checkpoint files")
    return df


def load_published(repo_id: str):
    """Read the published dataset as an Arrow table. Read-only and anonymous."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    from huggingface_hub import HfApi, hf_hub_download

    files = sorted(
        f for f in HfApi(token=False).list_repo_files(repo_id, repo_type="dataset")
        if f.endswith(".parquet")
    )
    return pa.concat_tables(
        [pq.read_table(hf_hub_download(repo_id, f, repo_type="dataset", token=False)) for f in files]
    )


def _is_transient(status: str) -> bool:
    """A download that failed for a reason that may pass: worth another try on the next run."""
    if not status.startswith("download_failed"):
        return False
    why = status.partition(":")[2]
    return not why.isdigit() or why == "429" or int(why) >= 500


def backfill_dataset(
    city_slug: str,
    seed_path: str | None = None,
    extract_text: bool = True,
    pdf_delay: float = 1.0,
    limit: int | None = None,
    retry_failed: bool = False,
) -> pd.DataFrame:
    """Complete the published dataset locally, without rebuilding it and without publishing.

    Starts from the published rows (or --seed), adds every matter of the configured types
    that the API has and the published data lacks, and tries again for text on rows that
    have none. A published row is never dropped and text it has is never replaced. The
    result, in the published columns, order and types, goes to
    checkpoints/backfill_<city>.parquet; what was tried for each row without text goes to
    checkpoints/backfill_<city>_status.parquet, which is also what a second run resumes from.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    config = CITY_CONFIG[city_slug]
    seed_table = pq.read_table(seed_path) if seed_path else load_published(config["repo"])
    seed = seed_table.to_pandas()
    seed["matter_id"] = seed["matter_id"].astype(str)
    if not seed["matter_id"].is_unique:
        raise RuntimeError("Published data repeats a matter_id")
    seed_has_text = seed["text"].fillna("").str.strip().str.len() > 0
    has_text = dict(zip(seed["matter_id"], seed_has_text))
    seed_url = dict(zip(seed["matter_id"], seed["attachment_url"].fillna("")))
    print(f"Published: {len(seed)} rows, {int(seed_has_text.sum())} with text")

    matters: dict[str, tuple[dict, str]] = {}
    for matter_type in config["types"]:
        found = fetch_all_matters(city_slug, matter_type, strict=True)
        print(f"  API: {len(found)} {matter_type.lower()}s")
        for matter in found:
            matters[str(matter["MatterId"])] = (matter, matter_type.lower())
        _jittered_sleep(2.0)
    new_ids = [mid for mid in matters if mid not in has_text]
    print(f"  {len(new_ids)} matters not yet published; "
          f"{len(set(has_text) - set(matters))} published rows the API no longer lists under these types")

    status_path = CHECKPOINT_DIR / f"backfill_{city_slug}_status.parquet"
    done: dict[str, dict] = {}
    if status_path.exists():
        done = {r["matter_id"]: r for r in pd.read_parquet(status_path).to_dict("records")}
        done = {
            mid: r for mid, r in done.items()
            if not _is_transient(r["text_status"])
            and not (retry_failed and r["text_status"].startswith("download_failed"))
        }
        print(f"Resuming: {len(done)} rows already tried")

    def save_status() -> None:
        tmp = status_path.with_suffix(".parquet.tmp")
        pd.DataFrame(
            list(done.values()),
            columns=["matter_id", "attachment_url", "text", "text_status", "n_attachments"],
        ).to_parquet(tmp, index=False)
        os.replace(tmp, status_path)

    todo = [mid for mid in matters if not has_text.get(mid, False) and mid not in done]
    if not extract_text:
        todo = [mid for mid in todo if mid in new_ids]
    print(f"  {len(todo)} rows to try for an attachment and its text")
    if limit is not None:
        todo = todo[:limit]

    session = requests.Session()
    stopped = ""
    api_failures = download_failures = 0
    for n, mid in enumerate(todo, 1):
        try:
            attachments = fetch_attachments(city_slug, int(mid), strict=True)
            api_failures = 0
        except RuntimeError:
            api_failures += 1
            if api_failures >= 5:
                stopped = "the Legistar API stopped answering"
                break
            time.sleep(60 * api_failures)
            continue
        _jittered_sleep(1.0)

        # The attachment the API names now; then, if that gives no text, the published one.
        url = find_best_attachment(attachments)
        candidates = list(dict.fromkeys(u for u in (url, seed_url.get(mid, "")) if u))
        text, status, tried = "", "no_attachment", ""
        if not extract_text:
            status, tried = "text_not_tried", url
            candidates = []
        for tried in candidates:
            text, status = extract_text_status(tried, session)
            _jittered_sleep(pdf_delay)
            if text:
                break

        if _is_transient(status):
            download_failures += 1
            if download_failures >= 8:
                stopped = "documents stopped downloading"
                break
        else:
            download_failures = 0
        done[mid] = {"matter_id": mid, "attachment_url": tried, "text": text,
                     "text_status": status, "n_attachments": len(attachments)}
        if n % 25 == 0:
            save_status()
            print(f"  Tried {n}/{len(todo)}", flush=True)
    save_status()

    # Rows as the API has them today
    fresh_rows = []
    for mid, (matter, doc_type) in matters.items():
        date = (matter.get("MatterIntroDate") or "")[:10]
        try:
            year = int(date[:4]) if date else 0
        except ValueError:
            year = 0
        fresh_rows.append({
            "date": date,
            "matter_id": mid,
            "matter_file": matter.get("MatterFile", ""),
            "enactment_number": matter.get("MatterEnactmentNumber", "") or "",
            "doc_type": doc_type,
            "title": matter.get("MatterTitle", ""),
            "text": "",
            "attachment_url": "",
            "year": year,
        })
    fresh = pd.DataFrame(fresh_rows, columns=DATASET_COLUMNS).set_index("matter_id", drop=False)

    # Published rows keep their place; what the API has since filled in or changed is taken from it
    out = seed.copy()
    listed = out["matter_id"].isin(fresh.index)
    for col in ["date", "matter_file", "enactment_number", "title", "year"]:
        current = out["matter_id"].map(fresh[col])
        changed = listed & current.notna() & (current != "") & (current != out[col])
        if changed.any():
            print(f"  {col}: {int(changed.sum())} published rows brought up to date from the API")
            out.loc[changed, col] = current[changed].astype(out[col].dtype)

    if new_ids:
        new = fresh.loc[new_ids].reset_index(drop=True)
        for col in out.columns:
            if col not in new.columns:
                new[col] = None
        out = pd.concat([new[list(out.columns)], out], ignore_index=True)
        out = out.sort_values("date", ascending=False, kind="stable").reset_index(drop=True)

    for mid, r in done.items():
        row = out["matter_id"] == mid
        if r["text"]:
            out.loc[row, "text"] = r["text"]
            out.loc[row, "attachment_url"] = r["attachment_url"]
        elif r["attachment_url"] and not seed_url.get(mid, ""):
            out.loc[row, "attachment_url"] = r["attachment_url"]

    # Nothing published may be lost
    check = seed[["matter_id", "text"]].merge(out[["matter_id", "text"]], on="matter_id", how="left",
                                              suffixes=("_pub", "_out"), indicator=True)
    if (check["_merge"] != "both").any() or len(out) != out["matter_id"].nunique():
        raise RuntimeError("Backfill lost or repeated a published row")
    kept = check["text_pub"].fillna("").str.strip().str.len() > 0
    if (check.loc[kept, "text_pub"] != check.loc[kept, "text_out"]).any():
        raise RuntimeError("Backfill changed text a published row already had")

    out_path = CHECKPOINT_DIR / f"backfill_{city_slug}.parquet"
    table = pa.Table.from_pandas(out[seed_table.schema.names], schema=seed_table.schema, preserve_index=False)
    table = table.replace_schema_metadata(seed_table.schema.metadata)
    pq.write_table(table, out_path)

    out_has_text = out["text"].fillna("").str.strip().str.len() > 0
    dates = out.loc[out["date"].fillna("") != "", "date"]
    statuses = pd.Series([r["text_status"] for r in done.values()], dtype="object").value_counts().to_dict()
    left = sum(1 for mid in matters if not has_text.get(mid, False) and mid not in done)
    print(f"\n=== {config['name']} backfill ===")
    print(f"Rows: {len(seed)} published, {len(out)} now ({len(new_ids)} new)")
    print(f"Date range: {dates.min()} to {dates.max()}")
    print(f"Rows with text: {int(seed_has_text.sum())} published, {int(out_has_text.sum())} now")
    print(f"Rows without text, by what was found: {statuses}")
    print(f"Rows without text not yet tried: {left}")
    print(f"Saved to {out_path} (not published)")
    if stopped or (left and extract_text):
        print(f"NOT FINISHED{': ' + stopped if stopped else ''}. Run the same command again to resume.")
    return out


def push_to_huggingface(df: pd.DataFrame, repo_id: str) -> None:
    """Push DataFrame to HuggingFace."""
    try:
        from datasets import Dataset
        from huggingface_hub import HfApi
    except ImportError:
        raise ImportError("datasets and huggingface_hub required")

    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)
    token = os.getenv("CATLLM_HUGGINGFACE_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
    if not token:
        raise RuntimeError("No HuggingFace token found in .env")

    api = HfApi(token=token)
    api.whoami()

    ds = Dataset.from_pandas(df)
    ds.push_to_hub(repo_id, token=token, private=False)
    print(f"Pushed {len(df)} rows to https://huggingface.co/datasets/{repo_id}")


def main():
    parser = argparse.ArgumentParser(description="Build Legistar city dataset")
    parser.add_argument("city", choices=list(CITY_CONFIG.keys()), help="City to scrape")
    parser.add_argument("--no-text", action="store_true", help="Skip PDF text extraction")
    parser.add_argument("--pdf-delay", type=float, default=1.0)
    parser.add_argument("--push-only", action="store_true")
    parser.add_argument("--output", default=None)
    parser.add_argument("--backfill", action="store_true",
                        help="Complete the published table into checkpoints/backfill_<city>.parquet; never publishes")
    parser.add_argument("--seed", default=None,
                        help="With --backfill: a parquet of the published rows, instead of downloading them")
    parser.add_argument("--limit", type=int, default=None,
                        help="With --backfill: try at most this many rows this run")
    parser.add_argument("--retry-failed", action="store_true",
                        help="With --backfill: try again every document that did not download, 404s included")

    args = parser.parse_args()
    config = CITY_CONFIG[args.city]
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    if args.backfill:
        if args.push_only:
            parser.error("--backfill never publishes; it cannot be combined with --push-only")
        backfill_dataset(
            city_slug=args.city,
            seed_path=args.seed,
            extract_text=not args.no_text,
            pdf_delay=args.pdf_delay,
            limit=args.limit,
            retry_failed=args.retry_failed,
        )
        return

    if args.push_only:
        df = merge_checkpoints(args.city)
        if df.empty:
            print("Nothing to push.")
            return
    else:
        df = build_dataset(
            city_slug=args.city,
            extract_text=not args.no_text,
            pdf_delay=args.pdf_delay,
        )

    print(f"\n=== {config['name']} ===")
    print(f"Total rows: {len(df)}")
    for dt in df["doc_type"].unique():
        print(f"  {dt.title()}s: {(df['doc_type'] == dt).sum()}")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")
    print(f"Rows with text: {(df['text'].str.len() > 0).sum()}")
    print(f"Rows with attachment: {(df['attachment_url'].str.len() > 0).sum()}")

    if args.output:
        df.to_csv(args.output, index=False)
        print(f"Saved to {args.output}")

    final_path = CHECKPOINT_DIR / f"{args.city}_final_dataset.parquet"
    df.to_parquet(final_path, index=False)
    print(f"Final dataset saved to {final_path}")

    if args.push_only:
        push_to_huggingface(df, config["repo"])


if __name__ == "__main__":
    main()
