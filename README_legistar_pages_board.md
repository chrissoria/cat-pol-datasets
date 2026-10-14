---
license: cc0-1.0
language:
- en
pretty_name: {title}
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
- config_name: members
  data_files:
  - split: train
    path: data/members.parquet
---

# {title}

What came before the {title}, what was done with it, and
how each member voted.

```python
from datasets import load_dataset

items = load_dataset("{repo}", split="train")
votes = load_dataset("{repo}", "votes", split="train")
```

## Where it comes from

One source: the pages of the Board's own Legistar site,
[{host}](https://{host}/Calendar.aspx). Legistar has an API, and most
councils and boards here are read through it; this one's has been broken on
its owner's side for years, so the pages a visitor sees are read instead: the
calendar of each year, each meeting's page, and the "Action details" of each
line the Board acted on. They hold the same record, entered by the clerk.
Nothing is added to it.

The calendar lists the Board's meetings from {listed_from}. Agendas here run
from {first_meeting} to {last_meeting}, and votes by member from {first_vote}
to {last_vote}. The Board's committees are not read.

## Tables

| Config | One row per | Rows |
|---|---|---|
| `default` (`items`) | item on an agenda read here | {n_items} |
| `meetings` | meeting of the Board | {n_meetings} |
| `agenda_items` | line of a meeting's agenda | {n_agenda_items} |
| `votes` | member and line voted on | {n_votes} |
| `members` | member seen voting at the Board | {n_members} |

The five tables, and the columns listed first in each, are the same in every
council and board dataset made this way, so two can be set one on the other.
`meeting_id` joins `meetings` to the rest; `item_id` joins a vote to the
agenda line it was taken on; `matter_id` joins `items` to both.

### items

An item (a "file") may come before the Board at more than one meeting: an
ordinance is passed on first reading at one and finally passed at the next.
It is here once.

| Column | |
|---|---|
| `date`, `agenda_date` | The first day and the last day it was on an agenda read here. |
| `matter_id`, `matter_file` | The site's number for the item's page, and the file number the Board gives it. |
| `doc_type` | `ordinance`, `resolution` or `other`, from the kind of file the Board calls it. |
| `title`, `subject` | The item's full title and its short name. A very long title is cut where the meeting's page cuts it. |
| `body`, `status`, `file_type`, `version` | As the site has them. `status` is where the item stands now. |
| `year` | Of `date`. |
| `last_action`, `last_action_date`, `result`, `ayes`, `noes`, `mover`, `seconder` | The last thing done with it at a meeting read here. |
| `action_on` | `item` where something was done. |
| `passed_date` | Empty. A motion that carried may have been one to table an item or put it off. |
| `times_on_agenda` | How many agenda lines read here it is on. |
| `url` | The item's page. |

### meetings

`meeting_id`, `date`, `time`, `body`, `location`, the meeting's page (`url`),
its agenda and minutes (`agenda_url`, `minutes_url`) and how many `items` were
on its agenda; then the kind of meeting (`name`: "Regular Meeting"), the
second half of the page's address (`guid`), and the day its agenda was last
read (`read_on`, empty for a meeting not yet reached).

### agenda_items

| Column | |
|---|---|
| `item_id`, `meeting_id`, `date`, `body` | The line, and the meeting it was at. `item_id` is the site's number for the line's action details. |
| `agenda_number`, `sequence` | Its number on the agenda, where the site gives one, and its place in the order. |
| `matter_id`, `matter_file`, `title` | The item. |
| `action`, `result` | The clerk's words for what was done (`FINALLY PASSED`, `ADOPTED`, `CONTINUED`) and for how it came out (`Pass`, `Fail`). Both are empty on a line where nothing was done. |
| `action_text` | What the action details say was done, where they say more. |
| `mover`, `seconder` | The members who moved and seconded, where the clerk entered them. |
| `ayes`, `noes`, `not_voting` | Counted from `votes`. |
| `heading` | Always false: the page lists items only. |
| `motions` | 1 where a vote by member was entered on the line, else 0. |
| `doc_type`, `subject`, `status`, `file_type`, `version` | As in `items`. |
| `guid`, `matter_guid` | The second half of the addresses of the line's action details and of the item's page. |

### votes

`member` and `vote` for each line voted on. A vote is `AYE` or `NO`, or the
clerk's own word in capitals: `ABSENT`, `EXCUSED`. `motion` is always 1, and
`motion_text` is the line's `action_text`.

### members

One row for each person who voted at the Board's meetings on at least
{seen_days} days: `name`, and `first_vote`, `last_vote` and `votes` counted
from the votes here. The pages keep no terms of office and give no district,
so `start`, `end` and `district` are empty, and `serving` is true for a member
whose last vote here is within {serving_days} days.

## What to know

- Every line acted on has its own vote in the record, the items of a consent
  agenda too: an item passed with thirty others "by the following vote" has
  that vote on its own line. A count of rows in `votes` counts such a roll
  call once for each item.
- A vote is here only if the clerk entered it by member.
- `result` is the clerk's.
- An item that came before the Board several times has one row in `items` and
  a line in `agenda_items` for each meeting, each with that meeting's votes.
- A member's name is as the pages give it.
- Meetings to come are listed, with nothing done yet.

## How it is made

[`build_legistar_pages_board.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_legistar_pages_board.py)
in cat-pol-datasets. The records are public records of {place}; this
compilation is released under CC0.
