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

What came before the {title} and the County's other
public bodies, what was done with it, and how each member voted.

```python
from datasets import load_dataset

items = load_dataset("{repo}", split="train")
votes = load_dataset("{repo}", "votes", split="train")
```

## Where it comes from

One source: the County's meeting system (CivicClerk), at
[{tenant}.portal.civicclerk.com](https://{tenant}.portal.civicclerk.com), read
through the public API that portal itself reads, at
`{tenant}.api.civicclerk.com/v1`. Nothing is added to what the County entered
there, and nothing is corrected.

Agendas here run from {first_meeting} to {last_meeting}, across {bodies}
bodies: the Board, and the commissions and committees the County keeps in the
same system. {vote_span}

## Tables

| Config | One row per | Rows |
|---|---|---|
| `default` (`items`) | item put on an agenda | {n_items} |
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

This system has no record of an item apart from its line on an agenda, so an
item is here once for each agenda it is on, and its `matter_id` is that line's
`item_id`.

| Column | |
|---|---|
| `date`, `agenda_date` | The day of the meeting. |
| `matter_id`, `matter_file` | The system's number for the line, and the item number the County gives it. |
| `doc_type` | `ordinance`, `resolution` or `other`: from the number the clerk gave it, or failing that from its title. |
| `title`, `body`, `status`, `subject` | As the County has them; often empty. |
| `year` | Of `date`. |
| `last_action`, `last_action_date`, `result`, `ayes`, `noes`, `mover`, `seconder` | The last motion on it. Where the item had no motion of its own and the heading it sits under had one (a consent agenda is voted on as one), these are that motion's. |
| `action_on` | `item` or `section`: which of the two the columns above come from. Empty where neither had a motion. |
| `passed_date` | Empty. A motion that carried may have been one to deny an item or put it off, so the day of the vote is not given as the day the item passed. |
| `times_on_agenda` | Always 1. |
| `url` | The meeting's page on the County's portal. |
| `item_id`, `meeting_id`, `section` | The line, its meeting, and the heading it sits under. |
| `number` | The ordinance or resolution number the clerk gave it, where there is one. |
| `attachments` | The papers filed with it, as a JSON list of names and addresses. |

### meetings

`meeting_id`, `date`, `time`, `body`, `location`, the meeting's page (`url`),
its agenda and minutes (`agenda_url`, `minutes_url`) and how many `items` were
on its agenda; then the meeting's `name`, the system's `agenda_id` for it and
the full packet (`packet_url`). A meeting with no `agenda_id` was listed with
no agenda entered. `agenda_read` is true once the agenda has been asked for
and answered, whether or not it held anything: a meeting brought over from an
older system often has only its packet.

### agenda_items

| Column | |
|---|---|
| `item_id`, `meeting_id`, `date`, `body` | The line, and the meeting it was at. |
| `agenda_number`, `sequence` | Its number on the agenda and its place in the order. |
| `matter_id`, `matter_file`, `title` | The item. `matter_id` is empty on a heading. |
| `action` | The words of the last motion on this line. |
| `result` | `Pass` or `Fail` where the clerk marked the motion so. See below. |
| `mover`, `seconder` | The members who moved and seconded. |
| `ayes`, `noes`, `not_voting` | Counted from `votes`, for the last motion. |
| `heading` | True for a heading (Consent Agenda, Closed Session), which is not an item. |
| `section`, `section_id` | The heading this line sits under. |
| `motions` | How many motions were entered on this line. |
| `pass_flag` | The clerk's mark on the last motion, as the system has it. |
| `description` | What else the agenda says of the line. |

### votes

`member` and `vote`, for each motion: `motion` numbers the motions on a line
and `motion_text` is its words. A vote is `AYE`, `NO` or `ABSTAIN`.

### members

One row for each person who voted at the Board's own meetings on at least
{seen_days} days: `name`, and `first_vote`, `last_vote` and `votes` counted
from the votes here. The system keeps no terms of office and no districts, so
`district`, `role`, `start` and `end` are empty, and `serving` is true for a
member whose last vote here is within {serving_days} days. The Board sits in
this system as {board_names}.

## What to know

- A consent agenda is voted on as one, so its vote is on its heading and not
  on the items under it. To see how the Board voted on a consent item, join
  the item's `section_id` to the heading's `item_id`.
- The system does not list a member who was absent: a member with no row for
  a motion did not vote on it.
- `result` is `Pass` or `Fail` only where the clerk marked the motion so.
  Clerks leave the mark unset on many motions that carried, so count `ayes`
  and `noes` rather than rely on it.
- A vote is here only if the clerk entered it by member. A motion entered
  without names has an `action` and no rows in `votes`.
- A member's name is as the clerk typed it; one person may appear under two
  spellings.
- Committees and commissions are included; `body` says which.
- Meetings to come are listed, with nothing done yet.

## How it is made

[`build_civicclerk_board.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_civicclerk_board.py)
in cat-pol-datasets. The records are public records of the County of {place};
this compilation is released under CC0.
