---
license: cc0-1.0
language:
- en
pretty_name: San Diego City Council
tags:
- government
- local-government
- city-council
- votes
- california
- san-diego
configs:
- config_name: default
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
- config_name: council
  data_files:
  - split: train
    path: data/council.parquet
- config_name: rosters
  data_files:
  - split: train
    path: data/rosters.parquet
---

# San Diego City Council

What came before the San Diego City Council since 2010, what the Council did
with it, and how each member voted.

## Where it comes from

One source: the City Clerk's agenda site,
[sandiego.hylandcloud.com/211agendaonlinecouncil](https://sandiego.hylandcloud.com/211agendaonlinecouncil).
Two documents of each council meeting are read.

- **The agenda** gives the Council as it sat that day: who held each
  district, and who was Council President.
- **The results summary** is the Clerk's table of what was done with each
  item: the action, the number the ordinance or resolution was given, who
  moved and seconded, and the vote.

The summary records a vote by district ("12356789-yea; 4-nay"). Each member's
vote here is that record joined to the agenda's list of who held each
district. Where the Clerk wrote "Unanimous", every member not named as absent
or recused is counted as voting yes.

The Clerk says of the summary: it "is NOT equivalent to the Minutes which,
when approved by the City Council, constitute the official record of the
meeting." The minutes, which follow months later, are not read here.

## Tables

| Config | One row per | Rows |
|---|---|---|
| `default` (`items`) | thing before the Council | about 8,800 |
| `meetings` | meeting with a results summary | about 680 |
| `agenda_items` | item on a meeting's docket | about 9,600 |
| `votes` | member and item voted on | about 79,000 |
| `council` | member and seat | 30 |
| `rosters` | meeting and seat | about 5,900 |

### items

An ordinance or resolution is one item under its draft number (`O-2025-91`),
which it keeps from introduction to adoption. Anything with no draft number,
such as a proclamation or a report, is one item per docket entry.

| Column | |
|---|---|
| `matter_id`, `matter_file` | The draft number, or the meeting and item number for an entry without one. |
| `doc_type` | `ordinance`, `resolution` or `other`. |
| `doc_num` | The number it was given when adopted: `O-21935`, `R-316132`. The same number is `doc_num` in [san-diego-ordinances](https://huggingface.co/datasets/chrissoria/san-diego-ordinances), which has the document's text. |
| `title` | The Clerk's one-line description of what was done. |
| `date`, `agenda_date`, `passed_date` | First and last time on a docket, and the day it was given its number. |
| `last_action`, `last_action_date`, `result` | The Clerk's word for the last thing done ("Adopted", "Introduced", "Continued"), and `Pass` or `Fail` where that says so. |
| `ayes`, `noes`, `mover`, `seconder` | Of that last action. |
| `times_on_agenda` | How many dockets it was on. |
| `url` | The results summary of its last meeting. |

### agenda_items

| Column | |
|---|---|
| `item_id` | The meeting and the item number: `6457-52`. |
| `agenda_number`, `sequence` | The item's number on the docket (`52`, `S507`, `51A`) and its place in the summary. |
| `matter_id`, `matter_file` | The item it belongs to. |
| `action`, `result`, `title` | As in `items`, for this meeting. |
| `doc_type`, `doc_num` | The kind and number of document adopted here, if one was. |
| `mover`, `seconder` | The members who moved and seconded. |
| `ayes`, `noes`, `not_voting` | Counted from `votes`. |
| `vote_text` | The Clerk's own words for the vote. |

### votes

`member`, `district`, and `vote`: `AYE`, `NO`, `NOT PRESENT`, `RECUSED`,
`INELIGIBLE`, `ABSENT` or `ABSTAIN`.

### council and rosters

`rosters` is who sat in each district at each meeting, with the role the
agenda gives (`Council President`, `Council President Pro Tem`,
`Councilmember`). `council` is made from it: one row per member and seat, with
the first and last meeting they are listed at (`start`, `end`), whether the
latest agenda lists them (`serving`), and how many votes of theirs are here.
A member's dates are the meetings they are seen at, not the days they were
sworn in or left.

## What to know

- The Council had eight districts until December 2012 and has had nine since.
- The Mayor is not a member of the Council and does not vote, so is not here.
- Closed sessions, the Housing Authority and other bodies the Council sits as
  have no results summary of this kind and are not included.
- An entry whose vote the Clerk described in words, not as a count, has no
  rows in `votes`; the words are in `vote_text`.
- No subject or policy area is recorded for an item.

## How it is made

[`build_sd_council.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_sd_council.py)
in cat-pol-datasets. The records are public records of the City of San Diego;
this compilation is released under CC0.
