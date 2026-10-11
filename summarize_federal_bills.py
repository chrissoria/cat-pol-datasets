#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-present Christopher Soria <chrissoria@berkeley.edu>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Write the `short_summary` of bills in chrissoria/federal-bills-active, and keep it current.

A summary is written from one version of a bill's text, and `summary_text_version`
records which. A bill needs a summary when it has none, or when its text has
moved on to another version since. The summary says what the bill would do and
never where it stands in Congress, which changes without the text changing.

This script does not fetch bills (build_federal_bills.py does). It starts from
the published dataset, and when it publishes it downloads the dataset again and
puts in only the two summary columns, so a daily pull in between is not undone.
Every summary written is also kept here, in summaries/federal.parquet, and put
back at the next publish if something overwrote it.

Two ways of writing them:

    python summarize_federal_bills.py --max 1000
        Through catllm, by a model on Hugging Face (a mid-sized Qwen by
        default). For the backlog. Works through the bills most recently
        updated first, saves after every chunk, and publishes at the end.

        catllm takes one bill at a time. For several at once, start N runs
        with --part 0/N ... --part N-1/N and --dry-run, then publish once.

    python summarize_federal_bills.py --export DIR --max 60
    python summarize_federal_bills.py --import DIR/summaries.json
        For a model that reads the bills and writes the summaries itself (the
        daily routine). --export writes the bills that need one as text files
        with an index; --import checks what the model wrote against the format
        rules, keeps what passes, and publishes.

    --dry-run        write and keep summaries but do not publish
    --publish-only   publish what is kept here and missing from the dataset
    --status         say how many bills need a summary, and stop
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

import build_federal_bills as bills

log = logging.getLogger(__name__)

STORE = bills.SCRIPT_DIR / "summaries" / "federal.parquet"
STORE_COLUMNS = ["key", "text_version", "summary", "model", "written"]
DEFAULT_MODEL = "Qwen/Qwen3.8-27B"
DEFAULT_SOURCE = "huggingface"
ROUTINE_MODEL = "claude-haiku-5-5"  # what writes the summaries that come in through --import
KEY_NAMES = ("HUGGINGFACE_API_KEY_STRONG", "HUGGINGFACE_API_KEY", "HF_API_KEY")  # the first that is set is used
CHUNK = 50  # bills to a call of catllm, and so how much a stopped run loses at most
MAX_CHARS = 300_000  # of a bill's text given to the model; about 75,000 tokens
EXPORT_CHARS = 40_000  # the same, for a model reading the bills as files
LIMIT = 400  # characters in a summary, as the instructions ask
HARD_LIMIT = 480  # a summary longer than this is refused rather than kept

INSTRUCTIONS = (
    "Write a short summary of this bill for the public. "
    f"STRICT LIMIT: the entire output must be under {LIMIT} characters including spaces.\n"
    "Structure:\n"
    "- First line: one standalone sentence saying what the measure would do, beginning "
    "'This bill would...' (or 'This resolution would...', 'This resolution expresses...' for a resolution). "
    "It must make sense completely on its own.\n"
    "- Then leave a blank line (two newlines).\n"
    "- Then 2-3 short sentences with the key details: what it does, who it affects, why it matters.\n\n"
    "Do not say who introduced it, when, or where it stands in Congress (introduced, reported, passed, "
    "signed): that changes, and readers are shown it separately. Describe only what the text provides. "
    "No hashtags, no emojis, no bullet points, no headings or other markup. Exactly one blank line."
)
TRUNCATED = "\n\n[The bill continues beyond this point; only its first {shown:,} characters are shown.]"

_STAGE = re.compile(r"\b(?:introduced|passed|approved|advanced|signed|enacted|reported)\b", re.I)
_OPENING = re.compile(r"^This (?:bill|resolution|measure|joint resolution|concurrent resolution|act)\b", re.I)
_MARKUP = re.compile(r"#|\*\*|^\s*[-•*] |[\U0001F300-\U0001FAFF☀-➿]", re.M)


def key_of(bill_type, bill_number):
    """'HR9846': how a bill is named in the store and in the files for the routine."""
    return f"{bill_type}{bill_number}"


def text_of(value):
    return "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)


def tidy(summary):
    """A summary as it is kept: no stray spaces, and one blank line where the model left more."""
    summary = text_of(summary).strip()
    if "\n" not in summary and "\\n" in summary:
        summary = summary.replace("\\n", "\n")  # some models spell their line breaks out, as a backslash and an n
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text_of(summary).strip().split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def check(summary):
    """What is wrong with a summary's form, as a list. Empty when it can be kept."""
    summary = text_of(summary)
    if not summary.strip():
        return ["empty"]
    problems = []
    if len(summary) > HARD_LIMIT:
        problems.append(f"over {HARD_LIMIT} characters")
    if summary.count("\n\n") != 1 or summary.count("\n") != 2:
        problems.append("not one opening line, a blank line and a paragraph")
    if _MARKUP.search(summary):
        problems.append("markup")
    opening = summary.split("\n")[0]
    if _STAGE.search(opening) and not _OPENING.match(opening):
        problems.append("the opening says where the bill stands")
    return problems


def shown(text, limit):
    """A bill's text as given to the model: whole, or its first `limit` characters with a note that it goes on."""
    text = text_of(text)
    return text if len(text) <= limit else text[:limit] + TRUNCATED.format(shown=limit)


def stamp_legacy(df):
    """Give `summary_text_version` to summaries written before it was recorded.

    A bill whose text is still as introduced can only have been summarized from that
    text. One whose text has moved on may have been summarized from either, so it is
    left without a stamp and counts as needing a new summary.
    """
    if "summary_text_version" not in df.columns:
        df["summary_text_version"] = ""
    df["summary_text_version"] = df["summary_text_version"].map(text_of)
    version = df["bill_text_version"].map(text_of)
    summarized = df["short_summary"].map(text_of).str.strip() != ""
    unstamped = summarized & (df["summary_text_version"] == "") & version.str.startswith("Introduced")
    df.loc[unstamped, "summary_text_version"] = version[unstamped]
    return df


def needs_summary(df):
    """Which bills have no summary, or one written from an earlier version of their text."""
    has_text = df["text"].map(text_of).str.len() > 50
    summarized = df["short_summary"].map(text_of).str.strip() != ""
    current = df["summary_text_version"].map(text_of) == df["bill_text_version"].map(text_of)
    return has_text & ~(summarized & current)


def keys_of(df):
    return [key_of(kind, number) for kind, number in zip(df["bill_type"], df["bill_number"])]


def download():
    """The dataset as published now."""
    from huggingface_hub import HfApi, hf_hub_download
    files = sorted(f for f in HfApi(token=bills.HF_TOKEN).list_repo_files(bills.HF_REPO, repo_type="dataset")
                   if f.startswith("data/train-") and f.endswith(".parquet"))
    if not files:
        raise FileNotFoundError(f"no data/train-*.parquet files in {bills.HF_REPO}")
    df = pd.concat([pd.read_parquet(hf_hub_download(bills.HF_REPO, f, repo_type="dataset", token=bills.HF_TOKEN,
                                                    force_download=True)) for f in files], ignore_index=True)
    return stamp_legacy(df)


def load_store():
    """Every summary kept here: the main file and the one each parallel run writes of its own."""
    files = sorted(STORE.parent.glob(f"{STORE.stem}*.parquet"))
    if not files:
        return pd.DataFrame(columns=STORE_COLUMNS)
    store = pd.concat([pd.read_parquet(path) for path in files], ignore_index=True)
    return store.sort_values("written").drop_duplicates(["key", "text_version"], keep="last").reset_index(drop=True)


def keep(rows, model, part=""):
    """Add summaries to the store: `rows` is a list of (key, text_version, summary). The newest for a key and version wins.

    A run that is one of several at once names its `part` and writes a file of its own, so none overwrites another's.
    """
    if not rows:
        return load_store()
    path = STORE.with_name(f"{STORE.stem}{'-' + part if part else ''}.parquet")
    written = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fresh = pd.DataFrame([(key, version, summary, model, written) for key, version, summary in rows], columns=STORE_COLUMNS)
    mine = pd.concat([pd.read_parquet(path), fresh], ignore_index=True) if path.exists() else fresh
    path.parent.mkdir(parents=True, exist_ok=True)
    mine.drop_duplicates(["key", "text_version"], keep="last").to_parquet(path, index=False)
    return load_store()


def apply(df, store):
    """Put the stored summaries into the table wherever the bill's text is still the version summarized. Returns how many changed."""
    if store.empty:
        return 0
    held = {(key, version): summary for key, version, summary in zip(store["key"], store["text_version"], store["summary"])}
    changed = 0
    versions = df["bill_text_version"].map(text_of)
    for index, key, version in zip(df.index, keys_of(df), versions):
        summary = held.get((key, version))
        if summary is None:
            continue
        if text_of(df.at[index, "short_summary"]) != summary or text_of(df.at[index, "summary_text_version"]) != version:
            df.at[index, "short_summary"] = summary
            df.at[index, "summary_text_version"] = version
            changed += 1
    return changed


def revision():
    """The dataset's latest commit: it changes whenever anything is pushed."""
    from huggingface_hub import HfApi
    return HfApi(token=bills.HF_TOKEN).dataset_info(bills.HF_REPO).sha


def publish(tries=3):
    """Download the dataset, put in the stored summaries, and push it. Returns (changed, still needing one).

    The daily pull pushes the same table. If it did so while this was working, what was
    downloaded is no longer the newest, and pushing it would undo the pull: so start again.
    """
    for attempt in range(tries):
        seen = revision()
        df = download()
        before = int((df["short_summary"].map(text_of).str.strip() != "").sum())
        changed = apply(df, load_store())
        after = int((df["short_summary"].map(text_of).str.strip() != "").sum())
        waiting = int(needs_summary(df).sum())
        if not changed:
            log.info("Nothing to publish: the dataset already has every stored summary that still fits its text")
            return 0, waiting
        if after < before:
            raise RuntimeError(f"the table would have {after} summaries where it has {before}; not publishing")
        table = bills.order_dataset_columns(df)
        if revision() != seen:
            log.warning("The dataset was pushed to while the summaries were being put in; starting again from the new one")
            continue
        if not bills.push_to_hf(table):
            raise RuntimeError("the push to Hugging Face did not go through")
        return changed, waiting
    raise RuntimeError("the dataset kept changing underneath; the summaries are kept here for the next run")


def write_with_catllm(df, todo, model, source, api_key, workers, thinking_budget):
    """Summaries for the rows `todo` of `df`: (key, text_version, summary) for those well formed, and a count of each refusal."""
    import cat_pol
    rows = df.loc[todo]
    result = cat_pol.summarize(
        input_data=[shown(text, MAX_CHARS) for text in rows["text"]],
        format="raw", tone="eli5", instructions=INSTRUCTIONS, description="U.S. federal bills",
        api_key=api_key, user_model=model, model_source=source, batch_mode=False,
        max_workers=workers, **({"thinking_budget": thinking_budget} if thinking_budget else {}),
    )
    good, refused = [], {}
    for key, version, (_, answer) in zip(keys_of(rows), rows["bill_text_version"].map(text_of), result.iterrows()):
        summary = tidy(answer.get("summary")) if answer.get("processing_status") == "success" else ""
        problems = check(summary) if summary else [text_of(answer.get("error_message"))[:80] or "no answer"]
        if problems:
            refused[problems[0]] = refused.get(problems[0], 0) + 1
        else:
            good.append((key, version, summary))
    return good, refused


def export(df, todo, folder):
    """The bills that need a summary, as files for a model to read: bills/<key>.txt and an index saying what is wanted."""
    folder = Path(folder)
    (folder / "bills").mkdir(parents=True, exist_ok=True)
    for old in (folder / "bills").glob("*.txt"):
        old.unlink()
    rows = df.loc[todo]
    index = []
    for key, row in zip(keys_of(rows), rows.to_dict("records")):
        (folder / "bills" / f"{key}.txt").write_text(f"{row['bill_type']} {row['bill_number']}: {text_of(row.get('title'))}\n\n"
                                                    f"{shown(row['text'], EXPORT_CHARS)}")
        index.append({"id": key, "title": text_of(row.get("title")), "text_version": text_of(row.get("bill_text_version"))})
    (folder / "index.json").write_text(json.dumps(index, indent=1))
    (folder / "instructions.txt").write_text(INSTRUCTIONS)
    return index


def read_import(path):
    """What a model wrote: {key: summary}, checked against the index beside it. Returns (good rows, refusals by key)."""
    path = Path(path)
    wanted = {item["id"]: item["text_version"] for item in json.loads((path.parent / "index.json").read_text())}
    written = json.loads(path.read_text())
    if not isinstance(written, dict):
        raise ValueError("the file is not a JSON object of bill id to summary")
    good, refused = [], {}
    for key, summary in written.items():
        if key not in wanted:
            refused[key] = ["not a bill that was asked for"]
            continue
        summary = tidy(summary) if isinstance(summary, str) else ""
        problems = check(summary)
        if problems:
            refused[key] = problems
        else:
            good.append((key, wanted[key], summary))
    for key in wanted:
        if key not in written:
            refused[key] = ["missing"]
    return good, refused


def provider_problem(source, model, api_key):
    """Why the model cannot be called, or None. Asked once before a run, because catllm waits and retries on every
    bill when the account has simply run out of credit."""
    if source != "huggingface":
        return None
    import requests
    try:
        answer = requests.post("https://router.huggingface.co/v1/chat/completions", headers={"Authorization": f"Bearer {api_key}"},
                               json={"model": model, "messages": [{"role": "user", "content": "Reply with the word ready."}],
                                     "max_tokens": 20}, timeout=120)
    except requests.RequestException as e:
        return f"Hugging Face could not be reached: {type(e).__name__}"
    if answer.status_code == 200:
        return None
    try:
        said = str(answer.json().get("error"))[:200]
    except ValueError:
        said = answer.text[:200]
    return f"Hugging Face answered {answer.status_code}: {said}"


def api_key_from(env_file):
    if env_file:
        load_dotenv(env_file, override=True)
    for name in KEY_NAMES:
        if os.getenv(name):
            return os.getenv(name)
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Write and refresh the short summaries of federal bills")
    parser.add_argument("--max", "--batch-size", dest="max", type=int, default=300, help="how many bills to take this run")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--model-source", default=DEFAULT_SOURCE, help="a catllm provider: huggingface, claude-agent, openai, ...")
    parser.add_argument("--thinking-budget", type=int, default=0, help="tokens of reasoning, for a model that takes it; 0 for none")
    parser.add_argument("--workers", type=int, default=6, help="bills summarized at once")
    parser.add_argument("--env-file", help="another .env to read the model's key from")
    parser.add_argument("--part", metavar="K/N", help="take every Nth bill, starting at the Kth: for N runs at once (use with --dry-run, "
                                                      "then one --publish-only)")
    parser.add_argument("--export", metavar="DIR", help="write the bills that need a summary as files, and stop")
    parser.add_argument("--import", dest="import_file", metavar="FILE", help="check and keep the summaries a model wrote")
    parser.add_argument("--dry-run", action="store_true", help="do not publish")
    parser.add_argument("--publish-only", action="store_true", help="publish what is kept here")
    parser.add_argument("--status", action="store_true", help="say how many bills need a summary, and stop")
    args = parser.parse_args(argv)

    refused = {}
    written = 0
    if args.import_file:
        good, refused = read_import(args.import_file)
        keep(good, args.model if args.model != DEFAULT_MODEL else ROUTINE_MODEL)
        written = len(good)
        for key, problems in sorted(refused.items()):
            log.warning(f"Refused {key}: {', '.join(problems)}")
        refused = {"refused": len(refused)} if refused else {}
    elif not args.publish_only:
        df = download()
        apply(df, load_store())  # what is kept here but not yet published does not need writing again
        need = needs_summary(df)
        order = pd.to_datetime(df["date_updated"], errors="coerce", utc=True)
        todo = list(order[need].sort_values(ascending=False).index)
        if args.part:
            which, of = (int(n) for n in args.part.split("/"))
            todo = todo[which % of::of]
        todo = todo[:args.max]
        stale = int((need & (df["short_summary"].map(text_of).str.strip() != "")).sum())
        log.info(f"{int(need.sum())} bills need a summary ({stale} of them have one from an earlier text); taking {len(todo)}")
        if args.status:
            log.info(f"RESULT: federal-summaries waiting={int(need.sum())} stale={stale} kept_here={len(load_store())}")
            return 0
        if args.export:
            index = export(df, todo, args.export)
            log.info(f"RESULT: federal-summaries exported={len(index)} to={args.export} waiting={int(need.sum())}")
            return 0
        api_key = api_key_from(args.env_file)
        if not api_key and args.model_source not in ("claude-agent", "claude-code", "codex-agent"):
            log.error(f"No key for {args.model_source} (looked for {', '.join(KEY_NAMES)})")
            return 1
        problem = provider_problem(args.model_source, args.model, api_key)
        if problem:
            log.error(f"The model cannot be called. {problem}")
            log.info("RESULT: federal-summaries written=0 refused=0 published=0 pushed=False")
            return 1
        for start in range(0, len(todo), CHUNK):
            good, some_refused = write_with_catllm(df, todo[start:start + CHUNK], args.model, args.model_source, api_key,
                                                   args.workers, args.thinking_budget)
            keep(good, args.model, (args.part or "").replace("/", "of"))
            written += len(good)
            for problem, count in some_refused.items():
                refused[problem] = refused.get(problem, 0) + count
            log.info(f"{min(start + CHUNK, len(todo))} of {len(todo)} done; {written} kept, {sum(refused.values())} refused")
        for problem, count in sorted(refused.items(), key=lambda item: -item[1])[:8]:
            log.warning(f"Refused {count}: {problem}")

    published, waiting = 0, "not checked"
    if not args.dry_run:
        try:
            published, waiting = publish()
        except Exception as e:
            log.error(f"Summaries not published: {e}")
            log.info(f"RESULT: federal-summaries written={written} refused={sum(refused.values())} published=0 pushed=False")
            return 1
    log.info(f"RESULT: federal-summaries written={written} refused={sum(refused.values())} published={published} "
             f"waiting={waiting} pushed={published > 0}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(main())
