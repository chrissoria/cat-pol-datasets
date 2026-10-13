---
license: cc0-1.0
language:
- en
pretty_name: {title}
tags:
- government
- local-government
- {tag}
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

What came before the {title} and its committees, what was done
with it, and how each member voted.

```python
from datasets import load_dataset

items = load_dataset("{repo}", split="train")
votes = load_dataset("{repo}", "votes", split="train")
```

## Where it comes from

One source: the {owner}'s legislative system (Legistar), at
[{client}.legistar.com](https://{client}.legistar.com), read through its
public API at `webapi.legistar.com/v1/{client}`. Nothing is added to what the
{owner} entered there, and nothing is corrected.

Agendas here run from {first_meeting} to {last_meeting}, across {bodies}
bodies: the {board}, its committees, and the boards and commissions the {owner}
keeps in the same system. Votes are recorded from {first_vote} to {last_vote}.

## Tables

| Config | One row per | Rows |
|---|---|---|
| `default` (`items`) | thing filed | {n_items} |
| `meetings` | meeting | {n_meetings} |
| `agenda_items` | item on a meeting's agenda | {n_agenda_items} |
| `votes` | member and item voted on | {n_votes} |
| `members` | member's time on the {board} | {n_members} |

The five tables, and the columns listed first in each, are the same in every
council and board dataset made this way, so two can be set one on the other:
[san-diego-council](https://huggingface.co/datasets/chrissoria/san-diego-council)
and
[sd-county-ordinances](https://huggingface.co/datasets/chrissoria/sd-county-ordinances)
are two. `matter_id` joins `items` to `agenda_items` and `votes`; `meeting_id`
joins `meetings` to them; `item_id` joins a vote to its agenda entry.

### items

| Column | |
|---|---|
| `date` | The day it was filed. |
| `matter_id`, `matter_file` | The system's number for it, and the file number the {owner} gives it. |
| `doc_type` | `ordinance`, `resolution` or `other`: what the {owner} files it as, or failing that what its title says. |
| `title`, `body`, `status`, `subject` | As the {owner} has them. `subject` is the {owner}'s own kind of item. |
| `year` | Of `date`. |
| `agenda_date`, `passed_date` | The last agenda it was on, and the day it passed, where the {owner} records one. |
| `last_action`, `last_action_date`, `result` | The last thing done to it at a meeting, and `Pass` or `Fail` where the record says. |
| `ayes`, `noes`, `mover`, `seconder` | Of that last action. |
| `times_on_agenda` | How many agendas it was on. |
| `url` | Its page on the {owner}'s site. |
| `attachments` | The papers filed with it, as a JSON list of names and addresses. |
| `last_modified` | When the {owner} last changed the record. |

{texts}

### meetings

`meeting_id`, `date`, `time`, `body`, `location`, the meeting's page (`url`),
its agenda and minutes (`agenda_url`, `minutes_url`) and how many `items` were
on its agenda; then `agenda_status`, `minutes_status` and `last_modified` as
the system has them.

### agenda_items

| Column | |
|---|---|
| `item_id`, `meeting_id`, `date`, `body` | The entry, and the meeting it was at. |
| `agenda_number`, `sequence` | Its number on the agenda and its place in the order. |
| `matter_id`, `matter_file`, `title` | The item it belongs to. |
| `action`, `result` | What was done, in the {owner}'s word, and `Pass` or `Fail`. |
| `mover`, `seconder` | The members who moved and seconded. |
| `ayes`, `noes`, `not_voting` | Counted from `votes`. |
| `action_text` | The clerk's sentence for what was done. |

### votes

`member` and `vote`. A vote is `AYE` or `NO`, however the {owner} spells them, or
the {owner}'s own word in capitals: `ABSENT`, `EXCUSED`, `ABSTAIN`, `RECUSED`.

### members

One row for each unbroken time someone sat on the {board}: `name`, `district`, `role`,
`start`, `end`, and whether that time covers today (`serving`). The system
keeps a term for every office a member holds and every name the {board} sits
under; terms that overlap, or follow one another within a month, are one row
here, with the role of the latest. The {board} sits in this system as
{council}. `first_vote`, `last_vote` and `votes` are counted from the votes
here, in any body. Someone who votes at the {board}'s meetings on several days
and has no term on record has a row too, with no dates.

## What to know

{district_note}
- A member's `start` and `end` are as good as the terms the system has on
  record; `first_vote` and `last_vote` show when they are actually seen.
- A vote the clerk entered twice is here once.
- A vote is here only if the clerk entered it by member. An item passed
  without a recorded roll call has an `action` and no rows in `votes`.
- Committees and commissions are included; `body` says which.
- Meetings to come are listed, with nothing done yet.

## How it is made

[`build_legistar_council.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_legistar_council.py)
in cat-pol-datasets. The records are public records of the {owner} of {place};
this compilation is released under CC0.
