# Repository Guidelines

## Project Structure & Module Organization
This repository is a script-based Python workspace for scraping, updating, and publishing civic and legislative datasets. Top-level `build_*.py`, `update_*.py`, `extract_*.py`, `summarize_*.py`, and `classify_*.py` files are the main entrypoints. Runtime artifacts live in `logs/`, and large intermediate or cached datasets live in `checkpoints/` with source-specific subdirectories such as `checkpoints/federal_bills/` and `checkpoints/executive_orders/`. Keep new helpers near the script they support unless they are reused broadly.

## Build, Test, and Development Commands
Install dependencies with:

```bash
python3 -m pip install -r requirements.txt
```

Common local runs:

```bash
python3 update_datasets.py --dry-run
python3 update_datasets.py --city fed --dry-run
python3 build_federal_bills.py --incremental --dry-run
bash install_launchd.sh --remove
```

Use `--dry-run` before any job that writes checkpoints or pushes to Hugging Face. For Berkeley-related scripts, also install Playwright and Chromium: `python3 -m pip install playwright && python3 -m playwright install chromium`.

## Coding Style & Naming Conventions
Follow existing Python style: 4-space indentation, standard-library imports first, short module docstrings, and clear constant names in `UPPER_SNAKE_CASE`. Name new entrypoint scripts with verb-first patterns such as `build_city_dataset.py` or `update_source.py`. Prefer `pathlib.Path`, keep side effects inside `main()` or clearly named functions, and write logs to `logs/` instead of printing large progress traces.

## Testing Guidelines
The dataset builders have unit tests in `tests/`; run `python -m pytest tests -q`. For the scrapers, which have none, validate changes by running the affected script with `--dry-run` and checking generated log output in `logs/`. For scraper changes, verify both a narrow run (single source) and any checkpoint path the script reads or writes.

## Commit & Pull Request Guidelines
Git history is not available in this checkout, so use simple imperative commit messages such as `Add dry-run guard for federal bill updates`. Keep commits scoped to one script or workflow. PRs should state the data source affected, list commands run for verification, mention any new environment variables, and include sample output or log excerpts when behavior changes.

## Security & Configuration Tips
Secrets are loaded from the project-level `.env`; do not hardcode API keys or tokens. Key variables referenced by scripts include `CATLLM_HUGGINGFACE_TOKEN`, `HUGGINGFACE_TOKEN`, and `GOVINFO_API_KEY`. Avoid committing generated checkpoints unless they are intentional dataset artifacts.
