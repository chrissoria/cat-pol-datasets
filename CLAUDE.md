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
- `summarize_federal_bills.py` — writes `short_summary` on `chrissoria/federal-bills-active` and keeps it current. `summary_text_version` records which text a summary was written from; a bill with no summary, or whose text has moved on, needs one. Two ways in: through catllm (`--max N`, a Qwen on Hugging Face by default, for the backlog), or `--export DIR` / `--import FILE` for a model that reads the bills and writes the summaries itself. It publishes by downloading the dataset again and putting in only the summary columns. `summary_bullets` is no longer written.

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
python summarize_federal_bills.py --max 500
python summarize_federal_bills.py --status
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
- **Berkeley (Clerk's records)** — `build_berkeley.py` reads the City Clerk's Records Online (`records.cityofberkeley.info`, an OnBase Public Access API that needs no browser): a plain run dates every new-series ordinance from the Clerk's list and adds new ones; `--texts` reads the scanned documents by OCR into `berkeley/texts.parquet` and does not publish. Document ids there are fresh on every search, so a document is found by its number each time. Prefer this over the Playwright scripts for Berkeley.
- **San Diego (City)** — `build_san_diego.py` is the backfill: `--list straight|years|search` reads the Clerk's listing three ways (it sorts by date only, so one pass repeats rows and hides others; the search's year counts are the true totals), and `--texts` reads each document, by OCR where a page has no text of its own. Needs `tesseract`, `pdfplumber` and `pypdfium2`. Every publish rewrites `.sd_cache.parquet`, which the weekly `pull_san_diego.py` starts from. Working files in `sandiego/`.
- **SD County** — `build_sd_county.py` builds all six tables of `chrissoria/sd-county-ordinances` from the Legistar API (ordinances, items, meetings, agenda items, votes, members); `pull_sd_county.py` only calls it. Legistar uses subject-area MatterTypes, so an item is an ordinance or resolution by its title. `build_sdcounty_dataset.py` is the old one-table scraper.
- **Councils and boards** — `council_tables.py` is the one shape every council's and board's dataset is written in (five tables, shared columns first, `AYE`/`NO`); `build_sd_county.py`, `build_sd_council.py` and `build_legistar_council.py` all pass their tables through `standard()`. A new city council gets its own dataset `chrissoria/<place>-council` in that shape; a county's board of supervisors goes into the one dataset of county boards (below). `build_legistar_council.py --city oakland|long-beach|fresno|salinas` reads a Legistar city with the County builder's functions, and a Legistar county the same way (`--city fresno-county`); tables are kept in `legistar/<city>/`. A county that has only just taken up Legistar leaves practice meetings in it with made-up votes under the supervisors' names: look at a county's earliest meetings before publishing, and give it a `from` day in `CITIES` if so (Placer has one; Riverside's record is nothing else and is not in the list).
- **County boards are one dataset** — `chrissoria/ca-county-boards`, made by `build_ca_county_boards.py` from the folders the readers write: `data/<table>/<county>.parquet` (the shared columns, plus `ADDED`, one schema per table), `data/counties.parquet` (one row a county: system, `read_from`, spans, counts, `note`), `raw/<county>/` (each reader's own tables, which a reader picks up from on its next run), and `world/<county>/chamber.json.gz` (the rooms). No county has a dataset of its own any more: a reader still names `chrissoria/<county>-county-board`, and `council_tables.published`/`publish` send that to the one dataset (`board_of`). To add a county: its entry in `bodies.json`, its entry in `COUNTIES` (folder, system, how votes were read, a note), then run its reader. The 31 old `<county>-county-board` datasets are left with a card that points to the new one. A county with a record in two systems (Butte: Granicus to May 2024, CivicClerk since) has the older one as `earlier` in its entry: its reader names `chrissoria/<county>-county-earlier-board`, its tables are kept in `raw/<county>/earlier/`, and `with_earlier` puts them ahead of the present ones. California's counties and cities are routines of their own (not part of the federal run): `run_ca_counties.py --minutes 60` (San Diego County, then `build_ca_county_boards.py --read`: every county with a reader in `READERS`, longest unread first, hosts the environment cannot reach passed over, PDF readers' kept texts restored from and saved to `raw/<county>/texts.tar.gz`) and `run_ca_cities.py` (San Diego, Oakland, Fresno, Salinas councils; Berkeley). Steps run through `local_steps.run`, each guarded against any exception. `publish_county` refuses a county whose votes fall below 98% of those published (unless its votes are held back).
- **City councils are one dataset too** — `chrissoria/ca-city-councils`, made by `build_ca_city_councils.py` with the county build's own code (`build_ca_county_boards.Collection`: `COUNTY` and `CITY`), kept apart from the county boards: `city`/`city_fips` columns, `data/cities.parquet`, `raw/<city>/`, `world/<city>/chamber.json.gz`. Its `CITIES` lists San Diego (`build_sd_council.py`, `read_from` `district code`, its `rosters` kept in raw/ as `extra`), Oakland, Long Beach, Fresno and Salinas (Legistar). Readers still name `chrissoria/<city>-council`; `council_tables.council_of` sends that on (`publish`, `published`). The five old city datasets hold only a pointer card. The cloud token must be able to write to `ca-city-councils` for the daily city steps to publish.
- **County boards on other systems** — one reader per system, each `--county <key> [--base] [--no-upload] [--write-card]`, each with its own card template `README_<name>.md` and tables in a folder of its own: `build_civicclerk_board.py` (`civicclerk/`; a public JSON API), `build_primegov_board.py` (`primegov/`; votes from Tulare's HTML minutes), `build_iqm2_board.py` (`iqm2/`; a page per item, so a whole read is slow: about a page a second), `build_destiny_board.py` (`destiny/`; Yolo), `build_granicus_board.py` (`granicus/`; hand-typed HTML minutes, votes only where names are listed), `build_legistar_pages_board.py` (`legistar_pages/`; San Francisco, whose Legistar API is broken: the calendar by year through the site's own cookie settings, a meeting's page, then a page per line acted on; `sfbos.org` itself disallows robots and is not read). Where a system has no mark that a motion carried, `result` is left empty and never worked out from the count; `passed_date` is left empty in all of them.
- **County boards read from PDF minutes** — `build_sacramento_board.py`, `build_orange_board.py`, `build_la_county_board.py`, `build_alameda_board.py`, `build_stanislaus_board.py`, `build_yuba_board.py`, `build_merced_board.py`, `build_sierra_board.py`, `build_calaveras_board.py`, `build_san_benito_board.py`, `build_amador_board.py`, `build_san_luis_obispo_board.py`, tables in `minutes_pdf/<county>/` (and `text/` there: each document's text, so a PDF is fetched once). Text layer only, no OCR. A vote is read whole or not at all: a block that does not pass every check stays in `agenda_items` with `votes_read` false and a `problem`, and puts nothing in `votes`. Orange and Alameda print votes as digit codes in the margin, read by the key each set of minutes prints; Alameda's needs character positions (`pypdfium2`). Stanislaus's minutes never list the ayes, so most of its votes are worked out and each says how (`established`, which becomes `read_from` `count` or `unanimous` in the one dataset); Merced, Sierra and Calaveras do the same where their minutes give a count, "unanimous" or "majority" (`majority` becomes `count`). Calaveras lists its meetings through `build_iqm2_board` and reads one minutes PDF per meeting, one a minute, because the portal's robots.txt asks for a 60-second crawl delay: a whole read takes about 17 hours and picks up where it stopped. San Benito and Amador are read from documents on their Granicus hosts (served by redirect from Granicus's storage); Amador's are the draft minutes attached to the agenda that approved them, from September 2023 (older attachments are behind a login), and two thirds of its votes are worked out from "carried unanimously". San Luis Obispo's minutes are a web page on Granicus to 2011 and a PDF grid of marks since (`format` in its `meetings`, which makes `read_from` `minutes page` or `minutes text`); its reader asks only its two hosts and follows no redirect elsewhere. Alameda's plain `12345` over `12345` margin is left unread: it is also the form's unfilled row.
- **Hosts and robots.txt** — check a new host's robots.txt before writing its reader, and say what it says. Chris's decision of 2026-10-13: a vendor's blanket robots file does not stop a slow, named read of public records (about a request a second; the crawl delay kept where a host asks for one and the read can bear it), always with the User-Agent `cat-pol-datasets (+https://github.com/chrissoria/cat-pol-datasets)`. A 401, 403, 429, bot check, CAPTCHA or login is a refusal: the reader raises `Refused`, asks nothing more of the host in that run, and nothing is done to get round it (the county sites of San Benito, Amador and Merced, and Kern, Madera, Kings and Siskiyou, stay unread for this reason).
- **Truth Social** — `checkpoints/truthsocial/trump_truths.parquet` is the local checkpoint; authoritative dataset is `chrissoria/trump-truth-social` on HuggingFace. Intraday market parquets per ticker live in `checkpoints/`.
