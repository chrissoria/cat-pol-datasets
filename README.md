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
- `build_supreme_court.py` builds
  [supreme-court-cases](https://huggingface.co/datasets/chrissoria/supreme-court-cases):
  every case decided since 1946 with each justice's vote (from the Supreme
  Court Database), the cases of the term in progress (from Oyez), and the
  dockets and emergency applications since 2017 (from the Court's own files).
  It runs at the end of the daily bills run; `--base` rebuilds it from the
  sources. `README_supreme_court.md` is the dataset's card. The dataset is
  CC BY-NC, as two of its sources are.
- `build_california_bills.py` builds
  [california-bills](https://huggingface.co/datasets/chrissoria/california-bills):
  every measure of each session of the California Legislature with its text and
  digest, its history, every roll call and each legislator's vote, from the
  Legislature's own nightly export. It runs at the end of the daily bills run;
  `--session 2023` builds a finished session. `README_california_bills.md` is
  the dataset's card.
- `build_california_snapshot.py` writes the map files for California Capitol
  World beside that dataset, in the shapes `build_world_snapshot.py` gives
  Congress's, so the app reads a state legislature with the code it reads
  Congress with. It runs whenever the California tables are published.
- `build_sd_county.py` builds
  [sd-county-ordinances](https://huggingface.co/datasets/chrissoria/sd-county-ordinances):
  everything filed with the San Diego County Board of Supervisors since 2017,
  each meeting's agenda and what was done, and how each supervisor voted, from
  the County's Legistar API. `--base` reads every meeting; without it, the
  recent ones. `README_sd_county.md` is the dataset's card. It runs at the end
  of the daily cloud run, with the other local bodies (`docs/cloud_routine.md`).
- `build_san_diego.py` fills in
  [san-diego-ordinances](https://huggingface.co/datasets/chrissoria/san-diego-ordinances),
  the City of San Diego's ordinances and resolutions since 1970. It reads the
  Clerk's listing three ways, because one pass of it repeats some documents
  and hides others, and reads the text of each document: the PDF's own where
  it has some, and OCR (Tesseract) for the scans, which is everything before
  2021. Run by hand; `pull_san_diego.py` remains the weekly pull.
- `build_sd_council.py` builds
  [san-diego-council](https://huggingface.co/datasets/chrissoria/san-diego-council):
  every San Diego City Council meeting since 2010, what was done with each
  item, and how each member voted, from the City Clerk's agenda site. The
  agenda gives who held each district; the Clerk's results summary gives the
  vote by district. `--base` reads every meeting; without it, the last 120
  days. `README_sd_council.md` is the card.
- `build_legistar_council.py` builds a dataset of the same kind for each city
  whose council keeps its record in Legistar: `oakland-council`,
  `long-beach-council`, `fresno-council` and `salinas-council`. It reads the
  city's API with the County builder's own functions; what differs from one
  city to the next is a line in its `CITIES`. `--city` says which, and `--base`
  reads every meeting. `README_legistar_council.md` is the one card, with each
  city's name and counts written in when it is published.
- `build_berkeley.py` keeps
  [berkeley-ordinances](https://huggingface.co/datasets/chrissoria/berkeley-ordinances)
  from the Berkeley City Clerk's Records Online, which lists every ordinance
  since 1916 with the day it was adopted and a scan of it, and answers an
  ordinary request. A plain run gives each ordinance the Clerk's day and adds
  those passed since; `--texts` reads the scans by OCR. It replaces
  `build_berkeley_dataset.py`, which read the municipal code's table of
  enactments through a browser to get past a bot check.
- **County boards are one dataset,
  [`ca-county-boards`](https://huggingface.co/datasets/chrissoria/ca-county-boards)**,
  to be filtered by county: 32 California boards of supervisors in the same
  tables with the same columns, a file a county within each table, and a
  `counties` table that says how each county's record was read and what to
  know of it. `build_ca_county_boards.py` makes it from the tables each
  county's reader writes; it reads nothing from a county itself. A reader run
  without `--no-upload` publishes its county there (it names
  `<county>-county-board` as it always did, and `council_tables.py` sends it
  on), so reading a county again is one command. The daily run copies San
  Diego County in and reads the Legistar counties again by turns
  (`--read --minutes 30`).
- The Legistar builder reads a county's board of supervisors where the county
  keeps its record in Legistar (`--city fresno-county`): San Bernardino, Contra Costa, Fresno, San Mateo,
  Sonoma, Santa Barbara, Placer, El Dorado, Humboldt, Napa, Nevada, Mendocino,
  Lake, Tehama and Lassen so far.
- Counties on other systems have a reader for each system, all with the same
  options (`--county`, `--base`, `--no-upload`, `--write-card`) and the same
  five tables: `build_civicclerk_board.py` (Alpine, Colusa, Del Norte,
  Mariposa, Modoc, Plumas, Tuolumne), `build_primegov_board.py` (Tulare),
  `build_iqm2_board.py` (Santa Clara, San Joaquin, Santa Cruz, Sutter),
  `build_destiny_board.py` (Yolo) and `build_granicus_board.py` (Glenn,
  Butte, Marin; not published).
- Five counties publish how each supervisor voted only in PDF documents, and
  have a reader each that takes it from the documents' own text:
  `build_sacramento_board.py`, `build_orange_board.py`,
  `build_la_county_board.py`, `build_alameda_board.py` and
  `build_stanislaus_board.py` (the last two not published). A vote there is
  read whole or not at all; what could not be read is marked, not guessed.
- A board has a room in Capitol World once its entry in `bodies.json` says so
  (`world`, `chamber` and how the room words things) and
  `build_chamber_snapshot.py --body <id>` has written its file. A long record
  is given a first day and a length for titles there (`from`, `titles`), so
  the room's file stays about a megabyte; the dataset has every year.
- `council_tables.py` is the one shape all of these builders write: five tables
  (`items`, `meetings`, `agenda_items`, `votes`, `members`), each with the same
  columns first and a body's own after them, and one spelling of aye and no.
  A new council or board is written to it, so any two can be set one on the
  other.
- `build_places.py` builds
  [us-places](https://huggingface.co/datasets/chrissoria/us-places), the one
  place everything else reads what a place is from: one row for the country
  and for each state, territory, county, city, named unincorporated
  community and district of Congress or a state legislature, with what it is
  part of, population, area, how urban it is,
  income, inequality, home value, GDP for each person, and for states the age
  bands and crime rates; links to its flag and seal; and how many records the
  other datasets here hold of it. It also writes the table of bodies and
  `world/bodies.json`, which Capitol World reads to know which places have a
  room, and `index/`, each place's facts for the app's Stats tab and
  whiteboard. `README_places.md` is the card.
- `bodies.json` lists the bodies that make law and that there are records of
  here: Congress, a legislature, a board, a council. `bodies.py` reads it. To
  add a body, add an entry; `build_places.py` and `build_chamber_snapshot.py`
  both work from the list.
- `build_boundaries.py` adds to us-places the outline of every place, from
  the Census Bureau's boundary files, and the maps Capitol World draws from
  them: each state as a grid of its counties, and each county as a grid of
  its cities and communities. Run it after `build_places.py`; the whole
  country takes about three minutes.
- `build_chamber_snapshot.py` writes `world/chamber.json.gz` beside a local
  body's dataset: the members, items, meetings and votes in the one file
  Capitol World reads for a county board's or a city council's room. It runs
  whenever the San Diego County tables are published.
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
