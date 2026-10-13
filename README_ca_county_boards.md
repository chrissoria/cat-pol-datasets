---
license: cc0-1.0
language:
- en
pretty_name: California County Boards of Supervisors
tags:
- government
- local-government
- county-government
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
- config_name: counties
  data_files:
  - split: train
    path: data/counties.parquet
---

# California County Boards of Supervisors

What came before the boards of supervisors of {n_counties} California counties,
what each board did with it, and how each supervisor voted: {n_votes} votes
by member on {n_agenda_items} agenda lines at {n_meetings} meetings, from
{first_vote} to {last_vote}. Every county is in the same tables with the
same columns, to be filtered by `county`.

```python
from datasets import load_dataset

votes = load_dataset("{repo}", "votes", split="train")
fresno = votes.filter(lambda row: row["county"] == "Fresno")

counties = load_dataset("{repo}", "counties", split="train")  # read this first
```

One county alone is one file: `data/votes/fresno.parquet`.

## Read the `counties` table first

The counties are not alike, and two should not be set side by side without
knowing how each was read. One row a county says:

| Column | |
|---|---|
| `county`, `county_fips` | The county and its Census code. |
| `system` | Where the county keeps its record. |
| `read_from` | How its votes came to be here. See below. |
| `site` | The county's own page for it. |
| `first_meeting`, `last_meeting` | The first and last meeting with an agenda here. |
| `first_vote`, `last_vote` | The first and last vote by member. Agendas often go back further than votes. |
| `items`, `meetings`, `agenda_items`, `votes`, `members` | Rows in each table. |
| `serving` | Supervisors now on the board, as the tables have it. |
| `kept_current`, `read_on` | Whether the county is read again each day or by hand, and the day it was last read. |
| `room` | Its room in [Capitol World](https://christophersoria.com/capitol-world/), where there is one. |
| `builder` | The script in cat-pol-datasets that reads it. |
| `note` | What to know of this county in particular. |

### How a vote was read (`read_from`, on every vote)

| | |
|---|---|
| `system` | The clerk entered each supervisor's vote in the county's meeting system, and it is read from there. Nothing is worked out. |
| `minutes page` | Read from the words of minutes the county publishes as a web page ("AYES: ... NOES: ..."). |
| `minutes text` | Read from the text of a PDF of the minutes. A vote block is read whole or not at all: where it could not be, the agenda line has `votes_read` false, a `problem`, and no rows in `votes`. No document is read by OCR. |
| `margin code` | Read from a row of digits printed in the margin of the minutes, by the key each set of minutes prints (a digit is a district; a letter under it is a no, an abstention or an absence). |

The first is a record; the other three are readings of a document, checked
against the documents by hand in samples and not line by line.

## The counties

{county_list}

{county_notes}

## Tables

`county` and `county_fips` are on every row. An id (`meeting_id`, `item_id`,
`matter_id`) is a county's own: join on it together with `county`.

| Config | One row per | Rows |
|---|---|---|
| `default` (`items`) | item that came before a board | {n_items} |
| `meetings` | meeting | {n_meetings} |
| `agenda_items` | line of a meeting's agenda | {n_agenda_items} |
| `votes` | supervisor and motion voted on | {n_votes} |
| `members` | time a person sat on a board | {n_members} |
| `counties` | county | {n_counties} |

The tables and their first columns are those of every council and board
dataset made this way
([san-diego-council](https://huggingface.co/datasets/chrissoria/san-diego-council)
is one), so a city's can be set beside a county's.

### items

`date`, `agenda_date`, `matter_id`, `matter_file`, `doc_type` (`ordinance`,
`resolution` or `other`), `title`, `body`, `status`, `subject`, `year`; the
last thing done with it (`last_action`, `last_action_date`, `result`, `ayes`,
`noes`, `mover`, `seconder`); `passed_date`; `times_on_agenda`; `url`. Then
`item_id`, `meeting_id` and `section` for a county whose system has no record
of an item apart from its line on an agenda (the item is then here once for
each agenda it was on); `action_on` (`item` or `section`: whether the action is
the item's own or that of the consent calendar it sat under); the `number` an
ordinance or resolution was given; and `attachments`, the papers filed with
it, as a JSON list of names and addresses.

### meetings

`meeting_id`, `date`, `time`, `body`, `location`, `url`, `agenda_url`,
`minutes_url`, `items`; then the meeting's `name`, and its `packet_url` and
`video_url` where the county gives them. Committees and commissions are
included for counties whose system holds them; `body` says which.

### agenda_items

`item_id`, `meeting_id`, `date`, `body`, `agenda_number`, `sequence`,
`matter_id`, `matter_file`, `title`, `action`, `result`, `mover`, `seconder`,
`ayes`, `noes`, `not_voting`; then `heading` (true for a heading such as
"Consent Calendar", which is not an item), the `section` a line sits under and
that heading's `section_id`, how many `motions` were entered on the line,
`doc_type`, `subject`, `description`, `status`, `number`, `attachments`, and
`votes_read` and `problem` (see `minutes text` above; empty for a county whose
votes come from a system).

### votes

`item_id`, `meeting_id`, `date`, `matter_id`, `matter_file`, `member`, `vote`;
then `vote_kind`, `motion` and `motion_text` where a line had more than one
motion, and `read_from`.

`vote` is `AYE` or `NO`, spelled one way in every county; any other word is
the county's own, in capitals (`ABSTAINED`, `NOT PRESENT`, `AWAY`, ...).
`vote_kind` puts those words in one of a few kinds, the same in every county:
`AYE`, `NO`, `ABSTAIN`, `ABSENT` (absent, excused, away, not present, late),
`RECUSED`, and `OTHER` for a word that is none of these, such as a vacant
seat or a vote the clerk left blank.

### members

`name`, `district`, `role`, `start`, `end`, `serving`, `first_vote`,
`last_vote`, `votes`. A person who left and came back has a row for each time.

## What to know

- **A count of votes is not a count of roll calls.** A consent calendar is
  voted on once; some clerks enter that vote on the calendar's own line and
  some on every item under it. To count roll calls, count distinct
  `county`, `item_id` and `motion` among lines where `heading` is true or
  `action_on` is not `section`, and expect the counties to differ still.
- **`result` is the clerk's mark where the system has one, and empty where
  it has none.** It is never worked out from a count of names: what number
  carries a motion depends on the motion.
- **`passed_date` is empty** except for San Diego County. A motion that
  carried may have been one to deny an item or put it off.
- **A vote is here only where the record names who voted.** A line that says
  "unanimous" and names nobody has an `action` and no rows in `votes`.
- **A supervisor with no row for a motion** was absent, or the record does
  not say; only some counties enter an absence.
- **`district` is empty for many supervisors**, where a county's system does
  not give it.
- **A name is as the clerk typed it.** One person may be under two spellings
  within a county.
- **Each county starts where its record does**, not on a common day, and
  some end: see `first_vote` and `last_vote` in `counties`.
- Meetings to come are listed, with nothing done yet.

## Each reader's own tables

`raw/<county>/` has the five tables as the county's reader wrote them, with
the columns only that reader has: the clerk's marks and codes, the text of a
motion as the minutes have it, which pages were read and when. The files under
`data/` are made from these and lose nothing but those columns.

## How it is made

A reader for each system the counties use, and
[`build_ca_county_boards.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_ca_county_boards.py)
to put what they read in one shape, in
[cat-pol-datasets](https://github.com/chrissoria/cat-pol-datasets). The
records are public records of each county; this compilation is released under
CC0.
