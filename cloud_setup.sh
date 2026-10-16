#!/usr/bin/env bash
# Cloud environment setup for the federal bills routine (docs/cloud_routine.md).
# Installs into the environment's own Python: the repo is re-cloned for every
# run, so a venv inside it would not survive. Safe to re-run.
#
# The cloud image's python3 is Debian's, so pip is never self-upgraded, the
# PEP 668 "externally managed" check is bypassed (throwaway container), and a
# failed install is retried over distro-managed packages.
set -euo pipefail
PY=${PYTHON:-python3}
$PY -c 'import sys; assert sys.version_info >= (3, 10), sys.version'
export PIP_BREAK_SYSTEM_PACKAGES=1 PIP_DISABLE_PIP_VERSION_CHECK=1
PKGS=("pandas>=2.2" "pyarrow>=17" "requests>=2.31" "python-dotenv>=1.0"
      "datasets>=2.19" "huggingface_hub>=0.30")
if ! $PY -m pip install --quiet "${PKGS[@]}"; then
  echo "cloud_setup: plain install failed; retrying over distro-managed packages (--ignore-installed)"
  $PY -m pip install --quiet --ignore-installed "${PKGS[@]}"
fi
# build_sd_council.py reads the City Clerk's pages with this, and cannot go without.
$PY -m pip install --quiet "beautifulsoup4>=4.12" || echo "cloud_setup: beautifulsoup4 not installed; the San Diego council step will fail"
# PDFs: San Diego County's documents and the county boards read from PDF minutes (run_ca_counties.py). pdfplumber's
# import goes through the cryptography package, and the image's own copy (Debian's) panicked on import there on
# 2026-10-16, so pip's own copy is put over it first. Each step goes without PDFs if this fails.
$PY -m pip install --quiet --ignore-installed "cryptography>=42" || echo "cloud_setup: cryptography not reinstalled; PDF reading may fail"
$PY -m pip install --quiet "pdfplumber>=0.10" "pypdfium2>=4" || echo "cloud_setup: pdfplumber not installed; PDF documents will be skipped"
$PY -c 'import pdfplumber, pypdfium2' 2>/dev/null && echo "cloud_setup: PDF reading ok" || echo "cloud_setup: PDF reading not available"
$PY -c 'import pandas, pyarrow, requests, dotenv, datasets, huggingface_hub; print("setup ok")'
