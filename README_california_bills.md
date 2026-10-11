---
license: cc0-1.0
language:
- en
pretty_name: California Legislature, bills and votes
tags:
- california
- legislation
- state-legislature
- politics
- government
- roll-call-votes
configs:
- config_name: bills
  default: true
  data_files:
  - split: train
    path: data/bills/*.parquet
- config_name: actions
  data_files:
  - split: train
    path: data/actions/*.parquet
- config_name: votes
  data_files:
  - split: train
    path: data/votes/*.parquet
- config_name: member_votes
  data_files:
  - split: train
    path: data/member_votes/*.parquet
- config_name: legislators
  data_files:
  - split: train
    path: data/legislators/*.parquet
- config_name: committees
  data_files:
  - split: train
    path: data/committees/*.parquet
- config_name: hearings
  data_files:
  - split: train
    path: data/hearings/*.parquet
---

# California Legislature: bills and votes

Every measure before the California Legislature, session by session: its text,
the Legislative Counsel's digest of it, who wrote it, each step of its history,
every roll call on it in committee and on the floor, and how each legislator
voted. The session in progress is refreshed daily.

```python
from datasets import load_dataset

bills = load_dataset("chrissoria/california-bills", split="train")  # the same as "bills"
actions = load_dataset("chrissoria/california-bills", "actions", split="train")
votes = load_dataset("chrissoria/california-bills", "votes", split="train")
member_votes = load_dataset("chrissoria/california-bills", "member_votes", split="train")
legislators = load_dataset("chrissoria/california-bills", "legislators", split="train")
committees = load_dataset("chrissoria/california-bills", "committees", split="train")
hearings = load_dataset("chrissoria/california-bills", "hearings", split="train")
```

Each table is one file per session (`data/bills/2025-2026.parquet`), so a
single session can be read on its own:

```python
import pandas as pd
bills = pd.read_parquet("hf://datasets/chrissoria/california-bills/data/bills/2025-2026.parquet")
```

## Where it comes from, and the licence

One source: the Legislature's own export of its bill database, published by the
Legislative Counsel at
[downloads.leginfo.legislature.ca.gov](https://downloads.leginfo.legislature.ca.gov/)
and shown to the public at
[leginfo.legislature.ca.gov](https://leginfo.legislature.ca.gov/). Under
California Government Code section 10248.5 this information is in the public
domain. The tables here are offered under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).

Built by
[build_california_bills.py](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_california_bills.py).

## What changed in October 2026

Until October 2026 this dataset was one table of 742 bills, most without text.
It is now every measure of each session, in seven tables. The sixteen columns
the old table had are still the first sixteen of `bills`, with the same names,
but three of them held the wrong thing and now hold what their names say:

- `date` was the thirty-first day a bill was in print. It is the day the bill
  was introduced.
- `urgency` and `fiscal_committee` were read from the neighbouring columns of
  the export (appropriation and local program). They are now the urgency and
  fiscal committee flags.
- `title`, `text` and `sponsor_name` were taken from each bill's first version.
  They are taken from its newest.

`sponsor_name` now gives full names, separated by `; ` where a bill has more
than one lead author, and `current_committee` gives the committee's name
(its code is in `current_committee_code`).

## `bills`

One row per measure.

| Column | Description |
|---|---|
| `date` | The day the measure was introduced, YYYY-MM-DD. |
| `session` | The two-year session, as in `2025-2026`. |
| `bill_number` | `AB-679`, `SB-4`, `ACR-12`. A bill of an extraordinary session carries its number: `ABX1-3`. |
| `bill_id` | The Legislature's own id, as in `202520260AB679`. The key to every other table. |
| `doc_type` | `assembly_bill`, `senate_bill`, `assembly_constitutional_amendment`, `senate_concurrent_resolution`, `house_resolution` and so on. |
| `title` | The subject line the measure is known by. A house resolution has none, so what it is "relative to" stands in. |
| `text` | The text of the newest version, one paragraph to a line. |
| `url` | The measure's page on the Legislature's site. |
| `origin_chamber` | `Assembly` or `Senate`. |
| `sponsor_name` | The lead authors of the newest version, separated by `; `. A committee is named as "Committee on …". |
| `status` | Where the measure stands: `Chaptered`, `Vetoed`, `Died`, `In Committee Process`, `In Floor Process`, `Pending Referral`, `Passed`, `Failed Passage in Committee` and the like, in the Legislature's words. |
| `current_house` | `Assembly`, `Senate`, or `Secretary of State` for a measure that has been chaptered. |
| `current_committee` | The committee the measure is before, if it is before one. |
| `vote_requirement` | `Majority` or `Two Thirds`. |
| `urgency`, `fiscal_committee`, `appropriation`, `local_program`, `tax_levy` | The flags the Legislative Counsel sets on the newest version, `Yes` or `No`. |
| `special_session` | 0 for the regular session; 1, 2, … for an extraordinary one. |
| `measure_type`, `measure_number` | `AB` and 679. |
| `long_title` | The formal title: "An act to amend Section … relating to …". |
| `digest` | The Legislative Counsel's Digest: what existing law says and what the measure would change. Written by the Legislature's lawyers for each version; resolutions have none. |
| `sponsor_ids` | `legislator_id` of each lead author, separated by `; `. Empty for a committee. |
| `sponsor_party` | The lead authors' party, or parties. |
| `principal_coauthors`, `coauthors` | Names, separated by `; `. |
| `coauthor_count` | How many coauthors of either kind. |
| `measure_state` | What the newest version is: `Introduced`, `Amended Assembly`, `Amended Senate`, `Enrolled`, `Chaptered`. |
| `current_location` | `Desk`, `Committee`, `Floor` or `Rules`; empty once the measure has left the houses. |
| `current_location_detail` | The committee's code, or the part of the floor's file the measure is on (`Third Reading`, `Inactive`). |
| `current_committee_code` | `committee_code` in `committees`. |
| `last_action_date`, `last_action` | The newest entry of the measure's history. |
| `chapter`, `chapter_year` | For a measure that became law or a resolution that was adopted: "Chapter 275, Statutes of 2025". |
| `versions` | How many versions were printed. |
| `text_version_id`, `text_version`, `text_date` | Which version `text` and `digest` are. |
| `veto_date`, `veto_message` | For a vetoed bill, the Governor's message, where the Legislature has published it. |
| `roll_calls` | How many rows `votes` has for the measure. |

In a finished session, `status` is where the measure stood when the session
ended. A bill that was still `In Committee Process` or `In Floor Process` then
died with the session, whether or not the Legislature's record went on to say
`Died`.

The export records a measure's status and place only from the 2007-2008
session on. For earlier sessions `status` is worked out from what the record
does hold: `Chaptered` for a measure with a chapter, `Vetoed` for a bill whose
history says the Governor vetoed it, `Passed` for a house resolution its house
adopted, and `Died` for everything else. `current_house`, the location
columns, and the place columns of `actions` are empty for those sessions.

## `actions`

One row per entry in a measure's history.

| Column | Description |
|---|---|
| `bill_id`, `session` | The measure. |
| `seq`, `date` | The order of the entry and its day. |
| `action` | The entry, as the Legislature's history has it. |
| `action_code` | The Legislature's number for the kind of entry. |
| `action_status` | `Applied`, or `Rescinded` or `Reconsidered` for an action later undone. |
| `house`, `location`, `location_detail` | Where the action left the measure: the house (or `Governor`, `Secretary of State`), then `Desk`, `Committee`, `Floor`, `Rules` or `E&E` (engrossing and enrolling), then the committee's code or the part of the file. |
| `committee_code`, `committee` | The committee, when the measure was left with one. |
| `status_after` | The measure's status after the action. |

## `votes`

One row per roll call.

| Column | Description |
|---|---|
| `vote_id` | The name of the roll call; the key to `member_votes`. |
| `bill_id`, `session`, `date`, `date_time` | The measure and when. Committee votes carry no time of day. |
| `chamber` | `Assembly`, `Senate`, or `Conference`. |
| `location_code`, `location` | Where: a committee or a floor. |
| `motion` | What was voted on, as the clerk recorded it. |
| `ayes`, `noes`, `not_voting` | The tally. |
| `result` | `PASS` or `FAIL`. |
| `file_item` | The measure's item number in that day's file. |

## `member_votes`

One row per legislator and roll call.

| Column | Description |
|---|---|
| `vote_id` | `vote_id` in `votes`. |
| `bill_id`, `session`, `date` | The measure and the day. |
| `legislator` | The name as the roll call has it, usually a surname. |
| `legislator_id` | `legislator_id` in `legislators`; empty for the rare name that matches nobody. |
| `vote` | `AYE`, `NOE`, or `ABS`: no vote recorded, whether absent, abstaining or not voting. |

## `legislators`

One row per person who held a seat in the session.

| Column | Description |
|---|---|
| `legislator_id` | District and name, as in `AD28-pellerin`. It names a person in one session; the same person in another district or session has another id. |
| `session`, `chamber`, `district` | The seat. |
| `name`, `last_name`, `first_name` | The name. |
| `author_name` | The name as bills and roll calls print it. |
| `party` | `Democratic`, `Republican`. |
| `title` | `Assembly Member` or `Senator`. |
| `serving` | False for someone who left the seat during the session. |

## `committees`

One row per committee, and one for each floor.

| Column | Description |
|---|---|
| `session`, `committee_code` | `CX25` is the Assembly's Appropriations committee, `CS61` the Senate's. |
| `chamber`, `name` | The house and the name. |
| `kind` | `committee`, `floor` or `conference`. |
| `active` | False for a committee dissolved or renamed during the session. |

## `hearings`

One row per measure and committee hearing it was set for.

| Column | Description |
|---|---|
| `bill_id`, `session`, `date` | The measure and the day of the hearing. |
| `committee_code`, `committee`, `chamber` | The committee. |

## What is not here

- Sessions before 1999-2000. The Legislature's files for them hold only the
  measures that were chaptered, with no history and no votes.
- Committee and floor analyses. The export has them, about a gigabyte a
  session; they can be read on each measure's page.
- Earlier versions of a bill's text. `versions` says how many there were.
- The codes themselves (the statutes as amended).
- A link between one session's legislators and the next's. `legislator_id` is
  for one session.
