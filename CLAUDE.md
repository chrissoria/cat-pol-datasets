# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Data pipeline for collecting, enriching, and publishing 18 political datasets to HuggingFace. Most scripts are self-contained. Scripts that call `cat_pol.classify()` or `cat_pol.summarize()` require `cat-pol` installed: `summarize_federal_bills.py`, `classify_ordinances.py`, `classify_truthsocial.py`, `enrich_truthsocial_media.py`.

## Setup

```bash
pip install -r requirements.txt
pip install playwright && python -m playwright install chromium  # Berkeley + Bakersfield only
```

**Required environment variables** in `../.env` (project root, one level above this directory):
- `CATLLM_HUGGINGFACE_TOKEN` — HuggingFace write token
- `HUGGINGFACE_API_KEY` or `HF_API_KEY` — LLM inference API key (summarization/classification)
- `GOVINFO_API_KEY` / `CONGRESS_API_KEY` / `DATA_GOV_API_KEY` — Congress.gov API (federal bills/laws)

All scripts load `.env` via `load_dotenv(PROJECT_ROOT / ".env")` where `PROJECT_ROOT` is the parent of this directory.

## Shared Library (`lib/`)

All new scripts import from `lib/` rather than duplicating helpers inline:

- **`lib/hf_utils.py`** — `get_hf_token()`, `get_hf_api_key()`, `load_hf_dataset()`, `push_hf_dataset()`
- **`lib/logging_utils.py`** — `setup_logging(log_dir, logger_name)` — file + console logger
- **`lib/validation.py`** — `validate_required_columns()`, `validate_unique_key()`, `validate_row_count_change()`
- **`lib/document_text.py`** — `extract_pdf_text(url, session)` (PDF/DOCX/DOC), `jittered_sleep(base)`

When writing new scripts, import from `lib/` instead of re-implementing these patterns.

## Script Types

**`build_*.py`** — One-time full scrapers per source. Run to reconstruct a dataset from scratch. All support `--push-only` and `--dry-run`.

**`update_*.py`** — Incremental updaters for ongoing maintenance:
- `update_datasets.py` — All sources. Use `--city <slug>` or `--exclude <slug>`. Slugs: `sd sf sal oak lb fre ber bak la clovis nb sdco fed eo speeches ts`
- `build_california_bills.py` — `chrissoria/california-bills` from the Legislature's nightly export (downloads.leginfo.legislature.ca.gov), read by byte range rather than downloaded. No flags: the session in progress; `--session 2023`: a finished one. Runs at the end of the daily cloud routine (`docs/cloud_routine.md`). `update_california_bills.py` is its old name and only calls it.
- `update_san_diego.py` — Standalone SD updater (older; `update_datasets.py` covers SD too)

**Standalone tools:**
- `publish_dataset.py` — Validate + publish any parquet to HuggingFace (CLI or importable). Runs required-column, uniqueness, and row-count-regression checks before pushing.
- `classify_ordinances.py` — Classify unclassified ordinance rows for SD/SF/Salinas. Use `--city sd|sf|sal|all` and `--dry-run`.
- `summarize_federal_bills.py` — LLM backfill for `short_summary`/`summary_bullets` on `chrissoria/federal-bills-active`. 300 bills/run, most recently updated first.

## Truth Social Pipeline

The Truth Social update is decomposed into three modules called in sequence by `update_datasets.py`:

1. **`pull_truthsocial.py`** — Fetches CNN archive, normalizes posts, updates engagement counts on existing rows, saves checkpoint.
2. **`enrich_truthsocial_media.py`** — Merges yfinance market data (18 tickers, intraday), GDELT event counts/z-scores, and image alt-text via `cat_pol.summarize()`.
3. **`classify_truthsocial.py`** — 9-category ensemble classification (attacking, threatening, enacting, de-escalating, etc.) via 3-model `cat_pol.classify()` vote.

Each can also be run or imported independently.

## Federal Bills Pipeline

Two separate scripts, always run independently:

```bash
# 1. Fetch updated bill metadata from Congress.gov API
python build_federal_bills.py --incremental          # ALWAYS use --incremental
python build_federal_bills.py --incremental --dry-run

# 2. Summarize bills missing LLM summaries (up to 300 per run)
python summarize_federal_bills.py
python summarize_federal_bills.py --dry-run
python summarize_federal_bills.py --batch-size 500
```

Cache: `.federal_bills_cache.parquet` (69 MB, 14,671 bills as of April 2026). Never run without `--incremental` — a full re-fetch takes ~15 minutes and gains nothing. The incremental merge preserves existing `short_summary`/`summary_bullets` columns.

## Caching & Checkpointing

- **Caches** (`.{slug}_cache.parquet`, dot-prefixed in this directory) — Current working copy of each dataset, updated in-place by update scripts.
- **Checkpoints** (`checkpoints/`) — Intermediate scraping state for resumable full builds. Not used by incremental updaters.
- **Logs** (`logs/`) — Per-script log files. Launchd jobs write here.

## Launchd Automation

Three scheduled jobs managed by `install_launchd.sh`:

| Job | Schedule | Command |
|---|---|---|
| `com.catpol.dataset-updater` | Sundays 9:00 AM | `update_datasets.py --exclude ts` |
| `com.catpol.truthsocial-updater` | Daily 9:00 AM | `update_datasets.py --city ts` |
| `com.catpol.california-bills-updater` | Sundays 9:30 AM | `update_california_bills.py` (now a second copy of the cloud's daily step) |

```bash
bash install_launchd.sh           # Install and load all three
bash install_launchd.sh --remove  # Unload and delete plists
```

Plists go to `~/Library/LaunchAgents/`. All paths are derived dynamically — re-run after moving the directory.

## Special Cases

- **Berkeley + Bakersfield** — Use Playwright to bypass Cloudflare on `municipal.codes`. Requires `playwright install chromium`.
- **SD County** — Legistar uses subject-area MatterTypes; `build_sdcounty_dataset.py` filters by title keyword instead of doc type.
- **Truth Social** — `checkpoints/truthsocial/trump_truths.parquet` is the local checkpoint; authoritative dataset is `chrissoria/trump-truth-social` on HuggingFace. Intraday market parquets per ticker live in `checkpoints/`.
