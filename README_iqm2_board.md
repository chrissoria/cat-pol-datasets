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

One source: the County's meeting portal (IQM2, also called MinuteTraq), at
[{host}](https://{host}/Citizens/Default.aspx). The portal has no API, so the
pages a visitor sees are read: the calendar, each meeting's page, and the page
of each item and motion on it. Nothing is added to what the County entered
there. {ends}

The calendar lists meetings from {listed_from}, of {bodies} bodies: the Board,
and the commissions and committees the County keeps in the same portal. All of
them are in `meetings`. Agendas and votes are read for the Board's own meetings
only, and here run from {first_meeting} to {last_meeting}. {vote_span}

## Tables

| Config | One row per | Rows |
|---|---|---|
| `default` (`items`) | item with a page of its own | {n_items} |
| `meetings` | meeting | {n_meetings} |
| `agenda_items` | line of a meeting's agenda, headings too | {n_agenda_items} |
| `votes` | member and motion voted on | {n_votes} |
| `members` | member seen voting at the Board | {n_members} |

The five tables, and the columns listed first in each, are the same in every
council and board dataset made this way, so two can be set one on the other:
[san-diego-council](https://huggingface.co/datasets/chrissoria/san-diego-council)
and
[sd-county-ordinances](https://huggingface.co/datasets/chrissoria/sd-county-ordinances)
are two. `meeting_id` joins `meetings` to the rest; `item_id` joins a vote to
the agenda line it was taken on; `matter_id` joins `items` to both.

### items

An item has a page of its own in the portal, and may come before the Board at
more than one meeting: an ordinance is introduced at one and adopted at the
next. It is here once.

| Column | |
|---|---|
| `date`, `agenda_date` | The first day and the last day it was on an agenda read here. |
| `matter_id`, `matter_file` | The portal's number for the item, and the file number the County gives it, where it gives one. |
| `doc_type` | `ordinance`, `resolution` or `other`: from the kind and category the County files it under, or failing that from its title. |
| `title`, `body`, `status` | As the County has them. `status` is the stamp on the item's page. |
| `subject`, `department`, `file_type` | The item's category, the department it came from, and the kind of file the County calls it. |
| `year` | Of `date`. |
| `last_action`, `last_action_date`, `result`, `ayes`, `noes`, `mover`, `seconder` | The last thing done with it at a meeting read here. Where it was passed with the consent calendar and has no vote on its own page, the count, the mover and the seconder are those of the calendar's vote. |
| `action_on` | `item` or `section`: which of the two the count comes from. Empty where nothing was done. |
| `passed_date` | Empty. A motion that carried may have been one to deny an item or put it off, so the day of the vote is not given as the day the item passed. |
| `times_on_agenda` | How many agenda lines read here it is on. |
| `url` | The item's page. |
| `attachments` | The papers filed with it, as a JSON list of names and addresses. |

### meetings

`meeting_id`, `date`, `time`, `body`, `location`, the meeting's page (`url`),
its agenda and minutes (`agenda_url`, `minutes_url`) and how many `items` were
on its agenda; then the kind of meeting (`name`), its `status` in the portal
(`Closed`, `Scheduled`, `Cancelled`), the full packet (`packet_url`), the short
minutes (`summary_url`), and the day its agenda was last read (`read_on`,
empty for a meeting not read: a cancelled one, another body's, or one not yet
reached).

### agenda_items

| Column | |
|---|---|
| `item_id`, `meeting_id`, `date`, `body` | The line, and the meeting it was at. |
| `agenda_number`, `sequence` | Its number on the agenda and its place in the order. |
| `matter_id`, `matter_file`, `title` | The item. `matter_id` is empty on a line that is not an item. |
| `action` | The clerk's word for what was done: `ADOPTED`, `APPROVED`, `CONTINUED`. |
| `result` | `Pass` or `Fail`, worked out from the clerk's word and the clerk's count. See below. |
| `mover`, `seconder` | The members who moved and seconded. |
| `ayes`, `noes`, `not_voting` | Counted from `votes`, for the last motion on the line. |
| `heading` | True for a line the agenda sets in bold: a section, not an item. |
| `level` | How far the line is set in on the agenda; 0 is a section. |
| `kind` | `item` (it has an item's page), `motion` (a consent calendar, the minutes, a motion that is no item), `communication` or `text`. |
| `section`, `section_id` | The section this line sits under. |
| `motions` | How many votes were entered on this line. |
| `tally` | The count as the clerk gives it: `UNANIMOUS`, `4 TO 1`. |
| `mover_title`, `seconder_title` | The titles the page gives the mover and the seconder. |
| `comments` | What the minutes say of the line. |
| `description` | What else the agenda says of the line. |
| `doc_type`, `status`, `subject`, `department`, `file_type`, `attachments` | As in `items`. |

### votes

`member` and `vote`, for each motion: `motion` numbers the motions on a line
and `motion_text` is the clerk's result for it. A vote is `AYE` or `NO`, or
the clerk's own word in capitals: `ABSENT`, `ABSTAIN`, `RECUSED`.

### members

One row for each person who voted at the Board's own meetings on at least
{seen_days} days: `name`, and `first_vote`, `last_vote` and `votes` counted
from the votes here. `role` is the title the pages last gave them as the mover
or seconder of a motion. The portal keeps no terms of office, so `start` and
`end` are empty, and `serving` is true for a member whose last vote here is
within {serving_days} days. The Board sits in this portal as {board_names}.

## What to know

- A consent calendar is voted on as one, and that vote is on the calendar's
  own line (`kind` is `motion`). Some clerks enter it again on each item under
  it and some do not: where an item's `action` says "By Consent Vote" and it
  has no rows in `votes`, join its `section_id` to the calendar line's
  `item_id` to see how the Board voted. Where they do, a count of rows in
  `votes` counts the one vote many times.
- `result` is not the clerk's. It is `Fail` where the clerk's word is FAILED
  or DEFEATED, and `Pass` where the clerk's count is unanimous or has more
  for than against. A motion to deny that carried is `Pass` with the `action`
  DENIED. Where the clerk gave no count it is empty, whatever the names add
  up to.
- A vote is here only if the clerk entered it by member. An older meeting, or
  a motion entered without names, has an `action` and no rows in `votes`; some
  have the names only in `comments`.
- {district_note}
- A member's name is as the pages give it, with one change: where a motion's
  page drops a middle initial an item's page has ("Steven Ding", "Steven J.
  Ding"), the fuller name is used for both.
- An item that came before the Board several times has one row in `items` and
  a line in `agenda_items` for each meeting, each with that meeting's votes.
- The County's other bodies are in `meetings` only.
- Meetings to come are listed, with nothing done yet.

## How it is made

[`build_iqm2_board.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_iqm2_board.py)
in cat-pol-datasets. The records are public records of the County of {place};
this compilation is released under CC0.
