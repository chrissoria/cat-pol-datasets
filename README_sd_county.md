---
language:
- en
pretty_name: San Diego County Board of Supervisors
tags:
- san-diego
- county-government
- local-government
- legislation
- roll-call-votes
- politics
configs:
- config_name: ordinances
  default: true
  data_files:
  - split: train
    path: data/ordinances.parquet
- config_name: items
  data_files:
  - split: train
    path: data/items.parquet
- config_name: meetings
  data_files:
  - split: train
    path: data/meetings.parquet
- config_name: agenda_items
  data_files:
  - split: train
    path: data/agenda_items.parquet
- config_name: votes
  data_files:
  - split: train
    path: data/votes.parquet
- config_name: supervisors
  data_files:
  - split: train
    path: data/supervisors.parquet
---

# San Diego County Board of Supervisors

What has come before the San Diego County Board of Supervisors since June
2017: every item filed, the ordinance or board letter that goes with it, each
meeting's agenda and what the Board did, and how each supervisor voted.

```python
from datasets import load_dataset

ordinances = load_dataset("chrissoria/sd-county-ordinances", split="train")  # ordinances and resolutions
items = load_dataset("chrissoria/sd-county-ordinances", "items", split="train")  # everything filed
meetings = load_dataset("chrissoria/sd-county-ordinances", "meetings", split="train")
agenda_items = load_dataset("chrissoria/sd-county-ordinances", "agenda_items", split="train")
votes = load_dataset("chrissoria/sd-county-ordinances", "votes", split="train")
supervisors = load_dataset("chrissoria/sd-county-ordinances", "supervisors", split="train")
```

## Where it comes from

The County's legislative system, Legistar, through its public API
(`webapi.legistar.com/v1/sdcounty`); the same records are shown to the public
at [sdcounty.legistar.com](https://sdcounty.legistar.com/). They are public
records of the County of San Diego. The County's use of the system begins in
June 2017, and so does this dataset.

Built by
[build_sd_county.py](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_sd_county.py).

The Board also sits as other bodies with their own agendas: the Flood Control
District, the Sanitation District, the Housing Authority, the Fire Protection
District and others. Their items and meetings are here too, and `body` says
which.

## What changed in October 2026

Until October 2026 this dataset was one table of ordinances and resolutions
and had stopped in May. It is now six tables. The default one, `ordinances`,
is that table continued, with the same ten columns first and more after them.
`items` has the same columns for everything filed, whatever kind.

## `ordinances` and `items`

One row per item filed. `ordinances` is the rows of `items` whose `doc_type` is
`ordinance` or `resolution`.

| Column | Description |
|---|---|
| `date` | The day the item was filed, YYYY-MM-DD. |
| `matter_id` | The system's id for the item. The key to `agenda_items` and `votes`. |
| `matter_file` | The County's file number, as in `26-555`. |
| `doc_type` | `ordinance`, `resolution` or `other`, from the item's title: the County files items under subject areas, not kinds of document. A title that names both counts as an ordinance. |
| `title` | The item's title. |
| `text` | The text of the item's document: for an ordinance or resolution the ordinance itself where one is attached, and otherwise the board letter, in which staff set out what the Board is asked to do, why, and what it costs. Empty where nothing readable is attached or it has not been read yet. |
| `attachment_url` | The document `text` is meant to be. |
| `body` | The body the item was filed with: `BOARD OF SUPERVISORS`, `BOARD OF SUPERVISORS - LAND USE`, or one of the districts and authorities. |
| `status` | The item's status in the system: `Passed`, `Agenda Ready`, `Consent Agenda`, `Discussion Item`, `Withdrawn`, `Held` and so on. Many items the Board acted on were never moved to `Passed`; `result` is the better guide. |
| `year` | The year of `date`. |
| `subject` | The County's subject area: `Financial and General Government`, `Land Use and Environment`, `Health and Human Services`, `Public Safety`, or a narrower one such as `Appointments` or `Closed Session`. |
| `agenda_date`, `passed_date` | The dates the system holds for the item. |
| `last_action`, `last_action_date` | The last thing done to the item at a meeting, in the minutes' words. |
| `result` | `Pass` or `Fail` for that action; empty where the minutes record no vote. |
| `ayes`, `noes` | The vote on that action. |
| `mover`, `seconder` | Who moved and seconded it. |
| `times_on_agenda` | How many agendas the item has been on. |
| `text_source` | The address `text` was read from; empty until it has been read. |
| `attachments` | Everything filed with the item, as a JSON list of `{name, url}`. |
| `url` | The item's page on the County's site. |
| `last_modified` | When the County last changed the item's record (UTC). |

## `meetings`

One row per meeting.

| Column | Description |
|---|---|
| `meeting_id` | The system's id. |
| `date`, `time`, `location` | When and where. |
| `body` | The body that met. |
| `agenda_url`, `minutes_url` | The published agenda and the statement of proceedings, as PDFs. |
| `url` | The meeting's page on the County's site. |
| `agenda_status`, `minutes_status` | `Draft` or `Final`. |
| `items` | How many rows `agenda_items` has for the meeting. |
| `last_modified` | When the County last changed the meeting's record (UTC). |

## `agenda_items`

One row per item on a meeting's agenda. Headings, the roll call and the like
are left out.

| Column | Description |
|---|---|
| `item_id` | The system's id for this item at this meeting. The key to `votes`. |
| `meeting_id`, `date`, `body` | The meeting. |
| `agenda_number`, `sequence` | The item's number on the agenda and its place in the order. |
| `matter_id`, `matter_file`, `title` | The item. |
| `action` | What was done, as the minutes name it: "took action as recommended", "adopted", "continued". Empty for an item not yet acted on. |
| `action_text` | The minutes' sentence, with the mover and seconder. |
| `result` | `Pass` or `Fail`; empty where no vote was recorded. |
| `mover`, `seconder` | Names. |
| `ayes`, `noes`, `not_voting` | The tally of `votes`. |

## `votes`

One row per supervisor and item acted on.

| Column | Description |
|---|---|
| `item_id`, `meeting_id`, `date` | The item at the meeting. |
| `matter_id`, `matter_file` | The item. |
| `supervisor` | The name. |
| `vote` | `AYE`, `NOE`, `ABSENT`, `ABSTAIN`, `RECUSED` and the like, in the minutes' words. |

## `supervisors`

One row per supervisor's time on the Board, as the system records it.

| Column | Description |
|---|---|
| `name` | The name, as `votes` has it. |
| `district` | The supervisorial district. The source does not have this; it is added from the County's own pages. |
| `start`, `end` | The dates of the term the system has on record, which for a supervisor who was re-elected is the latest term and not the first. For a sitting supervisor `end` is when the term runs out. |
| `first_vote`, `last_vote`, `votes` | The first and last day the supervisor is recorded voting, and how many votes. These show the whole time on the Board since June 2017. |
| `role` | `Member`, `Chair` or `Vice Chair` at the time the table was built. |
| `serving` | Whether today falls between `start` and `end`. |

The system holds the supervisors since it came into use. Earlier ones are not
here.

## What is not here

- Anything before June 2017.
- The text of more than one document per item. `attachments` lists them all.
- Who spoke at a meeting. Speaker slips are attached to items as scanned pages.
