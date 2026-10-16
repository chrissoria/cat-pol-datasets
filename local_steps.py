"""Running a routine's steps one after another, each in its own guard (run_ca_counties.py, run_ca_cities.py)."""

import importlib
import logging

log = logging.getLogger(__name__)


def run(name, steps):
    """Run each (module, arguments, what) by its main(arguments), the next whatever became of the last. A step fails if
    it returns other than 0 or None, or raises anything: a library that panics on import (pyo3's PanicException, a
    BaseException) stops that step only. Returns 1 if any failed."""
    failed = []
    for module, arguments, what in steps:
        try:
            code = importlib.import_module(module).main(list(arguments))
        except KeyboardInterrupt:
            raise
        except BaseException as e:
            code = f"{type(e).__name__}: {e}"
        if code:
            log.error(f"{what} not updated: {code}")
            failed.append(what)
    log.info(f"RESULT: {name} steps={len(steps)} failed={','.join(failed) or 'none'} pushed={len(failed) < len(steps)}")
    return 1 if failed else 0
