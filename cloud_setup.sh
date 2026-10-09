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
$PY -c 'import pandas, pyarrow, requests, dotenv, datasets, huggingface_hub; print("setup ok")'
