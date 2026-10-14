---
license: cc0-1.0
language:
- en
pretty_name: California City Councils
tags:
- government
- local-government
- city-council
- votes
- california
configs:
- config_name: default
  data_files:
  - split: train
    path: data/items/*.parquet
- config_name: meetings
  data_files:
  - split: train
    path: data/meetings/*.parquet
- config_name: agenda_items
  data_files:
  - split: train
    path: data/agenda_items/*.parquet
- config_name: votes
  data_files:
  - split: train
    path: data/votes/*.parquet
- config_name: members
  data_files:
  - split: train
    path: data/members/*.parquet
- config_name: cities
  data_files:
  - split: train
    path: data/cities.parquet
---

# California City Councils

What came before the city councils of {n_cities} California cities, what each
council did with it, and how each member voted: {n_votes} votes by member on
{n_agenda_items} agenda lines at {n_meetings} meetings, from {first_vote} to
{last_vote}. Every city is in the same tables with the same columns, to be
filtered by `city`.

```python
from datasets import load_dataset

votes = load_dataset("{repo}", "votes", split="train")
oakland = votes.filter(lambda row: row["city"] == "Oakland")

cities = load_dataset("{repo}", "cities", split="train")  # read this first
```

One city alone is one file: `data/votes/oakland.parquet`.

The boards of supervisors of California's counties are in a dataset of their
own made the same way,
[ca-county-boards](https://huggingface.co/datasets/chrissoria/ca-county-boards),
whose rows say `county` and `county_fips` where these say `city` and
`city_fips`. The tables and their other columns are the same, so a city's
council can be set beside its county's board. San Francisco, a city and
county in one, is there, as a board of supervisors.

## Read the `cities` table first

One row a city says:

| Column | |
|---|---|
| `city`, `city_fips` | The city and its Census place code (seven digits). |
| `system` | Where the city keeps its record. |
| `read_from` | How its votes came to be here. See below. |
| `site` | The city's own page for it. |
| `first_meeting`, `last_meeting` | The first and last meeting with an agenda here. |
| `first_vote`, `last_vote` | The first and last vote by member. |
| `items`, `meetings`, `agenda_items`, `votes`, `members` | Rows in each table. |
| `serving` | Members now on the council, as the tables have it. |
| `kept_current`, `read_on` | Whether the city is read again each day or by hand, and the day it was last read. |
| `room` | Its room in [Capitol World](https://christophersoria.com/capitol-world/), where there is one. |
| `builder` | The script in cat-pol-datasets that reads it. |
| `note` | What to know of this city in particular. |

### How a vote was read (`read_from`, on every vote)

| | |
|---|---|
| `system` | The clerk entered each member's vote in the city's meeting system (Legistar), and it is read from there. Nothing is worked out. |
| `district code` | The clerk's results summary of a meeting gives the vote by seat ("12356789-yea; 4-nay"), and the meeting's agenda says who held each seat that day. San Diego. |

## The cities

{city_list}

{city_notes}

## Tables

`city` and `city_fips` are on every row. An id (`meeting_id`, `item_id`,
`matter_id`) is a city's own: join on it together with `city`.

| Config | One row per | Rows |
|---|---|---|
| `default` (`items`) | item that came before a council | {n_items} |
| `meetings` | meeting | {n_meetings} |
| `agenda_items` | line of a meeting's agenda | {n_agenda_items} |
| `votes` | member and motion voted on | {n_votes} |
| `members` | time a person sat on a council | {n_members} |
| `cities` | city | {n_cities} |

The columns of each table are described in the card of
[ca-county-boards](https://huggingface.co/datasets/chrissoria/ca-county-boards),
and are the same here.

`vote` is `AYE` or `NO`, spelled one way in every city; any other word is the
city's own, in capitals. `vote_kind` puts those words in one of a few kinds:
`AYE`, `NO`, `ABSTAIN`, `ABSENT`, `RECUSED`, and `OTHER`.

## What to know

- **A count of votes is not a count of roll calls.** A consent calendar is
  voted on once, and a clerk may enter that vote on every item under it.
- **`result` is the clerk's mark**, never worked out from a count of names.
- **A name is as the clerk typed it.** One person may be under two spellings
  within a city.
- **Each city starts where its record does**, and some end: see `first_vote`
  and `last_vote` in `cities`.
- **Committees** are in `meetings` for a city whose system holds them; `body`
  says which.
- Meetings to come are listed, with nothing done yet.

## Each reader's own tables

`raw/<city>/` has the tables as the city's reader wrote them, with the columns
only that reader has. The files under `data/` are made from these.

## How it is made

[`build_sd_council.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_sd_council.py)
and
[`build_legistar_council.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_legistar_council.py)
read the cities, and
[`build_ca_city_councils.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_ca_city_councils.py)
puts what they read in one shape, in
[cat-pol-datasets](https://github.com/chrissoria/cat-pol-datasets). The
records are public records of each city; this compilation is released under
CC0.
