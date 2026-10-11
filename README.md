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
- `update_executive_orders.py` keeps
  [executive-orders](https://huggingface.co/datasets/chrissoria/executive-orders)
  current from the Federal Register. It runs at the end of the daily bills run;
  `README_executive_orders.md` is the dataset's card.
- `build_whitehouse_snapshot.py` writes `world/whitehouse.json.gz` beside the
  executive-orders dataset: for each order, who signed it, the departments it
  directs and the earlier orders it revokes or amends, read from its text. It
  is the data for Capitol World's White House map and runs whenever the
  executive orders table changes. Beside it go `world/text/<n>.json.gz`, the
  orders' text at greater length (250 orders to a file), which the app fetches
  when an order is opened.
- `build_executive_roster.py` builds
  [executive-branch-roster](https://huggingface.co/datasets/chrissoria/executive-branch-roster):
  the cabinet from Senate nominations and the senior White House staff from
  Wikidata. It has its own weekly cloud routine (`docs/cloud_routine.md`).
- `build_congress_members.py` builds congress-members (not yet published):
  everyone who has served in Congress and every term, from the public-domain
  congress-legislators project, with race or ethnicity only where the House
  Historian's lists give it. It also writes `world/members.json` for the member
  card in Capitol World. `README_congress_members.md` is the dataset's card.
- `build_congress_archive.py` builds the map files of a finished Congress
  (2003 on) from GovInfo's Bill Status bulk data, once, and uploads them to
  `world/archive/<congress>/`. It is run by hand, not by the daily job:
  `python build_congress_archive.py 113-118`. With `--committees` it adds each
  committee's roster and meetings, about an hour and a half per Congress; it
  can be stopped and repeated, publishes a committee file only from a complete
  set of meetings, and skips a Congress that is already published. `--status`
  lists what is published and what is missing.
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
