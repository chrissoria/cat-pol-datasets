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

What came before the {title}, what was done with it, and how each member
voted where the minutes say so by name.

```python
from datasets import load_dataset

items = load_dataset("{repo}", split="train")
votes = load_dataset("{repo}", "votes", split="train")
```

## Where it comes from

One source: the County's pages in Granicus, at
[{host}](https://{host}/ViewPublisher.php?view_id={view}). That page lists
every meeting; each meeting's minutes (`MinutesViewer.php`) are the agenda
with what was done written under each line. Nothing is added to what the
clerk wrote there, and nothing is corrected.

The County lists {n_meetings} meetings from {first_listed} to {last_listed}.
The minutes of {n_read} of them, from {first_meeting} to {last_meeting}, are
a web page and are read here. The minutes of {n_pdf} are filed as a PDF, which
is not read: those meetings are in `meetings` with nothing under them.
{vote_span}

## Who voted how: the rule

The minutes record {n_motions} motions. For {n_named} of them ({share_named})
they name who voted, and only those have rows in `votes`.

- A vote is here where the minutes list members under a word for a vote:
  `Ayes: Supervisors Corum, McDaniel and Viegas`, `Noes: Supervisor Foltz`,
  `Absent:`, `Abstain:`, `Recused:`, or a roll call with one member to a line
  (`Supervisor Corum - Nay`).
- Where the minutes say only that a motion carried, or carried unanimously
  (`Vote: Unanimous.`, `Motion passed unanimously.`, `AYES: ALL`, `it was
  unanimously ordered`), no one is put down as voting. The members present
  are **not** filled in as ayes. The line has the motion, who moved and
  seconded it, `result`, `unanimous`, and the count if the minutes give one
  (`tally`, as in `4-0-1`), and no rows in `votes`.
- A name in a list that is not plainly one surname is left out, not guessed.
- `Ayes` and `Yes` are written `AYE`; `Noes`, `Nays` and `No` are written
  `NO`; `ABSENT`, `ABSTAIN` and `RECUSED` are kept. A vote written twice for
  the same motion is kept once.

Clerks name the voters mostly when a vote is divided, when someone is absent
or steps aside, or when a roll call is required. So `votes` leans toward the
contested motions: it is not a sample of all of them.

## Tables

| Config | One row per | Rows |
|---|---|---|
| `default` (`items`) | item in a meeting's minutes | {n_items} |
| `meetings` | meeting the County lists | {n_meetings} |
| `agenda_items` | numbered line of a meeting's minutes, headings too | {n_agenda_items} |
| `votes` | member and motion, where the minutes name who voted | {n_votes} |
| `members` | member seen voting at the Board | {n_members} |

The five tables, and the columns listed first in each, are the same in every
council and board dataset made this way, so two can be set one on the other:
[san-diego-council](https://huggingface.co/datasets/chrissoria/san-diego-council)
and
[sd-county-ordinances](https://huggingface.co/datasets/chrissoria/sd-county-ordinances)
are two. `meeting_id` joins `meetings` to the rest; `item_id` joins a vote to
the line it was taken on; `matter_id` joins `items` to both.

### items

The minutes have no record of an item apart from its line, so an item is here
once for each meeting it came to, and its `matter_id` is that line's `item_id`.

| Column | |
|---|---|
| `date`, `agenda_date` | The day of the meeting. |
| `matter_id` | The line's `item_id`. `matter_file` is empty: the County gives items no file number. |
| `doc_type` | `ordinance`, `resolution` or `other`, from the title. |
| `title`, `body` | As the minutes have them. `status` and `subject` are empty. |
| `year` | Of `date`. |
| `last_action`, `last_action_date`, `result`, `ayes`, `noes`, `mover`, `seconder` | The last motion on it. Where the item had no motion of its own and a heading above it had one (a consent calendar is voted on as one), these are that motion's. |
| `action_on` | `item` or `section`: which of the two the columns above come from. Empty where neither had a motion. |
| `passed_date` | Empty. A motion that carried may have been one to deny an item or put it off, so the day of the vote is not given as the day the item passed. |
| `times_on_agenda` | Always 1. |
| `url` | The meeting's minutes. |
| `item_id`, `meeting_id`, `agenda_number`, `section` | The line, its meeting, its number, and the heading it sits under. |
| `number` | The resolution or ordinance number written on the line, where there is one. |
| `unanimous`, `tally`, `named` | Of that last motion: whether the minutes call it unanimous, the count they give, and whether they name who voted. |

### meetings

`meeting_id` (the number Granicus gives the meeting's recording), `date`,
`time` where the listing gives one, `body`, the recording's page (`url`), the
agenda and minutes (`agenda_url`, `minutes_url`) and how many `items` were
read from the minutes; then the meeting's `name` as the County lists it, and
`minutes_format`: `html` where the minutes were read, `pdf` where they are a
document that is not, empty where there are none yet or the page had no
numbered line on it. `body` is `Board of
Supervisors` for every kind of Board meeting (regular, special, continued);
{bodies} bodies in all share the listing. `location` is empty.

### agenda_items

| Column | |
|---|---|
| `item_id`, `meeting_id`, `date`, `body` | The line, and the meeting it was at. `item_id` is the meeting and the line's place in its minutes. |
| `agenda_number`, `sequence` | Its number in the minutes and its place in the order. |
| `matter_id`, `title` | The item. `matter_id` is empty on a heading. |
| `action` | The words of the last motion on this line. |
| `result` | `Pass` or `Fail` where the minutes say so; a unanimous vote is a `Pass`. Empty where they give the votes and no outcome. |
| `mover`, `seconder` | The members who moved and seconded, by surname. |
| `ayes`, `noes`, `not_voting` | For the last motion: counted from `votes` where the minutes name who voted, and otherwise the count they give (`tally`). Zero where they give neither, as for a motion that carried unanimously. |
| `heading` | True for a line with other lines set under it (a consent calendar, a public hearing with several cases). |
| `section`, `section_id` | The heading this line sits under. |
| `motions`, `motions_named` | How many motions are written on this line, and how many of them name who voted. |
| `unanimous`, `tally`, `named` | Of the last motion. |
| `motion_log` | Every motion on the line, in order, as a JSON list: its words, mover, seconder, result, tally, and whether it is unanimous and named. |
| `description` | What else the minutes say under the line: the matter, the papers, the discussion. |
| `doc_type`, `number` | As in `items`. |

### votes

`member` (a surname) and `vote`, for each motion: `motion` numbers the motions
on a line and `motion_text` is its words. A vote is `AYE`, `NO`, `ABSENT`,
`ABSTAIN` or `RECUSED`.

### members

One row for each person named as voting at the Board's own meetings on at
least {seen_days} days: `name` (the surname the minutes use), and
`first_vote`, `last_vote` and `votes` counted from the votes here. The
minutes keep no terms of office and no districts, so `district`, `role`,
`start` and `end` are empty, and `serving` is true for a member whose last
vote here is within {serving_days} days. Because a member is only named on
some motions, `first_vote` and `last_vote` fall inside their time on the
Board and do not mark its ends, and `serving` can miss a member who is
serving.

## What to know

- A consent calendar is voted on as one, so its vote is on its heading and not
  on the items under it. To see how the Board voted on a consent item, follow
  the item's `section_id` to the heading's `item_id`.
- Where several motions are written on one line, the line's own columns are
  the last motion's, and so are those of the items under it. The others are
  in `motion_log`, and their votes in `votes` under their `motion` number.
- A vote taken apart from the rest of a consent calendar and written under it
  as `Item 3.24` is kept on that item's own line.
- A member's name is as the clerk typed it; a misspelling is a second name.
  Someone named once is in `votes` and not in `members`.
- `result` is the minutes' word. Where they list ayes and noes and do not say
  whether the motion carried, it is empty: some motions need four votes of
  five, so the count alone does not say.
- The minutes are written by hand over many years and several clerks. A motion
  written in a way not met before is read as discussion, and is missing here.
- Committees and commissions that share the listing are included; `body` says
  which.

## How it is made

[`build_granicus_board.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_granicus_board.py)
in cat-pol-datasets. The records are public records of the County of {place};
this compilation is released under CC0.
