---
license: cc0-1.0
language:
- en
pretty_name: Sacramento County Board of Supervisors
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

# Sacramento County Board of Supervisors

What came before the Sacramento County Board of Supervisors, what was done
with it, and how each supervisor voted.

```python
from datasets import load_dataset

items = load_dataset("{repo}", split="train")
votes = load_dataset("{repo}", "votes", split="train")
```

## Where it comes from

One source: the County's meeting system (AgendaNet), at
[agendanet.saccounty.gov/BoardofSupervisors](https://agendanet.saccounty.gov/BoardofSupervisors/).
It lists the Board's meetings and keeps an action summary of each as a PDF.
The system has no record of a vote apart from that document, so everything
here below the list of meetings is read from the summaries' text. Nothing is
added to what the Clerk wrote there, and nothing is corrected.

{n_read} summaries are read, of meetings from {first_meeting} to
{last_meeting}. None was a scan with no text of its own ({n_scans}); such a
summary would be counted and left, since nothing is read off the picture of a
page.

## How a vote is read, and when it is not

In a summary, each motion voted on is followed by a block that names every
supervisor:

```
10:31 AM Board Action: Rich Desmond/ Patrick Kennedy - Adopted Resolution No. 2026-0181.
AYES: Patrick Kennedy, Rich Desmond, Phil Serna
NOES: Rosario Rodriguez, Pat Hume
ABSTAIN: None
ABSENT: None
RECUSAL: None
```

A block is read whole or not at all. It is read only if its words stand once
each and in their order, every name in it is one supervisor listed at the head
of that summary, nobody is named twice, and nobody listed there is left out.
A block that does not pass (one that names a director of another board, one
the Clerk left a supervisor out of, one cut short) puts no rows in `votes`:
the motion is kept in `agenda_items` with `votes_read` false and what stopped
the reading in `problem`. The same is done where the summary's text does not
say for certain which item a block belongs to (an item's number lost from the
text, two blocks under one action).

Of {n_blocks} blocks in the summaries read, {n_blocks_read} were read
({share_read}%) and {n_unread} were not. Votes run from {first_vote} to
{last_vote}. The share read is lower in 2006 and 2007, when the Board sat in
the same meetings as the sanitation districts' boards, whose blocks name
directors who are not supervisors and are not read. To count by year:

```python
agenda = load_dataset("{repo}", "agenda_items", split="train").to_pandas()
agenda.groupby(agenda["date"].str[:4])[["vote_blocks", "blocks_read"]].sum()
```

## Tables

| Config | One row per | Rows |
|---|---|---|
| `default` (`items`) | item on a summary | {n_items} |
| `meetings` | meeting listed | {n_meetings} |
| `agenda_items` | line of a summary, headings too | {n_agenda_items} |
| `votes` | supervisor and motion voted on | {n_votes} |
| `members` | supervisor named in a block that was read | {n_members} |

The five tables, and the columns listed first in each, are the same in every
council and board dataset made this way, so two can be set one on the other:
[san-diego-council](https://huggingface.co/datasets/chrissoria/san-diego-council)
and
[sd-county-ordinances](https://huggingface.co/datasets/chrissoria/sd-county-ordinances)
are two. `meeting_id` joins `meetings` to the rest; `item_id` joins a vote to
the line it was taken on; `matter_id` joins `items` to both.

### items

The system has no record of an item apart from its line in a summary, so an
item is here once for each meeting it came to, and its `matter_id` is that
line's `item_id`.

| Column | |
|---|---|
| `date`, `agenda_date` | The day of the meeting. |
| `matter_id` | The line: the meeting's number and the item's, `10218-7`. `matter_file` is empty. |
| `doc_type` | `ordinance` or `resolution` where the action gives a number for one, or failing that from the title; else `other`. |
| `title`, `body` | As the summary has them. `status` is empty. |
| `subject` | The department in brackets at the end of the title, where there is one. |
| `year` | Of `date`. |
| `last_action`, `last_action_date` | What the summary says was done with the item at this meeting. |
| `ayes`, `noes`, `mover`, `seconder` | Of the vote that took the item in: its own, or its heading's (a consent agenda is voted on as one). |
| `action_on` | `item` or `section`: which of the two that vote was. Empty where neither had one. |
| `votes_read` | Whether that vote's block was read. If not, `ayes` and `noes` are 0 and mean nothing. |
| `result`, `passed_date` | Empty: see below. |
| `times_on_agenda` | Always 1. |
| `url` | The summary. |
| `item_id`, `meeting_id`, `section`, `group` | The line, its meeting, and the headings it sits under. |
| `number` | The resolution or ordinance number the action gives, where it gives one. |

### meetings

`meeting_id`, `date`, `time`, `body`, the meeting's page (`url`), its agenda
and action summary (`agenda_url`, `minutes_url`) and how many `items` its
summary has; then the meeting's `name` in the listing (which says if it was
cancelled, special or an addendum), the full packet (`packet_url`), and what
the reading found: `summary` (`read`, `no text layer`, or empty where there is
no summary or it has not been read), `pages`, `vote_blocks`, `blocks_read`,
and `roll`, the supervisors listed at the head of the summary with their
districts, as JSON. `location` is empty.

### agenda_items

| Column | |
|---|---|
| `item_id`, `meeting_id`, `date`, `body` | The line, and the meeting it was at. |
| `agenda_number`, `sequence` | Its number in the summary and its place in the order. A heading has no number, nor has a matter taken up without one (the election of the chair, a closed session). |
| `matter_id`, `title` | The item. `matter_id` is empty on a heading. |
| `action`, `action_time` | What the summary says the Board did, and the time it gives: of the line's last vote, or with no vote its last action. |
| `mover`, `seconder` | The supervisors who moved and seconded, where the action names them. |
| `ayes`, `noes`, `not_voting` | Counted from `votes`, for that vote. 0 where its block was not read. |
| `votes_read` | True where every block on the line was read, false where one was not, empty where the line has no block. |
| `vote_blocks`, `blocks_read` | How many blocks stand on the line, and how many were read. |
| `problem` | Why a block was not read. |
| `voted_with` | The line whose vote took this item in: itself, or its consent heading. Empty where no vote did. |
| `motions`, `motion_log` | How many actions the line has, and each of them as JSON: its time, words, mover and seconder, and whether it has a block and the block was read. |
| `heading` | True for a heading (Section III - Consent Matters), which is not an item. |
| `section`, `section_id`, `group` | The heading this line sits under, and the heading in capitals above it within that (COUNTY EXECUTIVE, SACRAMENTO COUNTY WATER AGENCY). |
| `result` | `Fail` where the summary prints MOTION FAILED on the line's last vote; otherwise empty. |
| `districts`, `doc_type`, `subject`, `number` | The supervisorial districts the summary gives for the item, and the three columns `items` has. |

### votes

`member` and `vote`, for each motion whose block was read: `motion` numbers
the actions on a line and `motion_text` is its words. A vote is `AYE`, `NO`,
`ABSTAIN`, `ABSENT` or `RECUSAL`. Every motion here has one row for each
supervisor on the Board that day.

### members

One row for each supervisor named in a block that was read: `name`, and
`first_vote`, `last_vote` and `votes` counted from the votes here. `district`
is the one printed at the head of the summaries, which print it from 2014 on;
it is empty for a supervisor who left before then. The summaries give no
terms of office, so `start` and `end` are empty; `serving` is true for those
listed at the head of the newest summary read, and `role` is the office
printed beside the name there (Chair, Vice Chair).

## What to know

- A consent agenda is voted on as one, so its vote is on its heading and not
  on the items under it. `voted_with` on an item gives the heading whose vote
  took it in. An item the motion left out ("with the exception of Items 10
  and 13") is not given the heading's vote; every number after such words is
  taken to be left out, which now and then leaves out one item too many.
- A motion with `votes_read` false was voted on by name; the names are in the
  summary (`minutes_url`) and not here.
- Most actions have no block of their own: a consent item's "Approved by
  Resolution No. 2026-0181", a presentation, a report received.
- The summary does not mark a motion that carried. Count `ayes` and `noes`;
  what number carries a motion depends on the motion.
- A supervisor's name is as the head of the summary has it. The block may
  print another form ("Pat Hume" for Patrick Hume); the two are matched by
  surname and first letter.
- The head of a summary lists the Board as it stood when the document was
  made, which for a few older meetings is later than the meeting. Blocks in
  those summaries name a supervisor who is not listed, and are not read.
- The Board sits as other bodies in the same meeting (the Water Agency, the
  In-Home Supportive Services Public Authority). Their items are numbered in
  with the Board's; `group` often says which body.
- A title or an action is the summary's lines joined; a line in capitals
  between them may have ended one early.
- Meetings to come are listed, with nothing read. A summary is posted some
  weeks after its meeting; meetings of the last {recent_days} days are read
  again on each run.

## How it is made

[`build_sacramento_board.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_sacramento_board.py)
in cat-pol-datasets. The records are public records of the County of
Sacramento; this compilation is released under CC0.
