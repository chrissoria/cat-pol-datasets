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
# Only build_sd_county.py wants this, for PDF documents, and it goes without if it has to.
$PY -m pip install --quiet "pdfplumber>=0.10" || echo "cloud_setup: pdfplumber not installed; PDF documents will be skipped"
$PY -c 'import pandas, pyarrow, requests, dotenv, datasets, huggingface_hub; print("setup ok")'
