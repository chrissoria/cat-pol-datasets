from __future__ import annotations

import logging
from pathlib import Path


def setup_logging(log_dir: Path, logger_name: str = "dataset_updater") -> logging.Logger:
    """Create or reuse a file+console logger for script entrypoints."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger(logger_name)
    if log.handlers:
        return log

    log.setLevel(logging.DEBUG)

    fh = logging.FileHandler(log_dir / "update.log")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(ch)

    return log
