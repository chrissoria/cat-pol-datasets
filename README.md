# cat-pol-datasets

Scripts that collect, enrich and publish the public political and legislative
datasets behind [cat-pol](https://github.com/chrissoria/cat-pol): federal bills
and votes, executive orders, presidential speeches, California bills, municipal
ordinances for several California cities, and Truth Social posts. The datasets
are published at [huggingface.co/chrissoria](https://huggingface.co/chrissoria).

- `build_*.py` build a dataset from scratch; `update_*.py` and `pull_*.py`
  update one incrementally.
- `CLAUDE.md` describes every script, the caches and the environment variables.
- `README_federal_bills.md` is the codebook for
  [federal-bills-active](https://huggingface.co/datasets/chrissoria/federal-bills-active)
  and [federal-votes](https://huggingface.co/datasets/chrissoria/federal-votes).
- `docs/cloud_routine.md` describes the daily cloud run that keeps
  federal-bills-active current.
- `build_congress_archive.py` builds the map files of a finished Congress
  (2003 on) from GovInfo's Bill Status bulk data, once, and uploads them to
  `world/archive/<congress>/`. It is run by hand, not by the daily job:
  `python build_congress_archive.py 113-118`.
- `build_committees.py` builds
  [federal-committees](https://huggingface.co/datasets/chrissoria/federal-committees):
  every committee and subcommittee, its members, and every hearing, markup and
  business meeting held or scheduled. It runs at the end of the daily bills run.

```bash
pip install -r requirements.txt
python build_federal_bills.py --incremental --dry-run
```

Keys go in a `.env` file one directory above this one; nothing secret is stored
in the repository.

License: GPL-3.0-or-later.
