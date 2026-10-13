---
license: cc0-1.0
language:
- en
pretty_name: Los Angeles County Board of Supervisors
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

# Los Angeles County Board of Supervisors

What came before the Los Angeles County Board of Supervisors, what was done
with it, and how each supervisor voted.

```python
from datasets import load_dataset

items = load_dataset("{repo}", split="train")
votes = load_dataset("{repo}", "votes", split="train")
```

## Where it comes from

One source: the Board's Statements of Proceedings, the Executive Office's
record of each meeting, kept as PDFs on file.lacounty.gov and listed on the
County's page for them,
[lacounty.gov/sop](https://lacounty.gov/government/board-of-supervisors/statement-of-proceedings/).
Everything here below the list of meetings is read from the statements' text.
Nothing is added to what the Executive Office wrote there, and nothing is
corrected. The County's Legistar API holds about fifty of the Board's meetings
and hardly a vote, and nothing is taken from it.

The County lists {n_meetings} statements, from {first_listed} on, and all are
in `meetings`. Those from {first_day} on are read: {n_read} statements, of
meetings from {first_meeting} to {last_meeting}. That day is where the
statements begin to be printed in the form read here. The earlier ones are
listed and not read:

- From 21 October 2008 to 10 February 2009 a statement names who voted, but
  in an earlier form of the page. A matter's attachments stand before what
  was done with it, and in the text the names are set around their count
  ("Supervisor Molina, Supervisor Yaroslavsky," / "Ayes: 4 -" / "Supervisor
  Antonovich and Supervisor Burke"), so a list cannot be told from the line
  beside it.
- Before 21 October 2008 a statement says "Vote: Unanimously carried" and
  names nobody but the absent, so it holds no vote by name to read.

Statements that are scans with no text of their own: {n_scans}. Such a
statement is counted and left, since nothing is read off the picture of a
page.

## How a vote is read, and when it is not

In a statement each matter ends with its file number in brackets. What the
Board did follows, then the vote by name, with a count before each list:

```
... as requested at the Board meeting of October 3, 2023. (23-3603)
On motion of Supervisor Horvath, seconded by Supervisor Solis, this item was
continued to June 3, 2025.
Ayes: 4 - Supervisor Solis, Supervisor Mitchell, Supervisor
Horvath and Supervisor Barger
Absent: 1 - Supervisor Hahn
Attachments: Public Comment/Correspondence
```

A block is read whole or not at all. It is read only if each of its lists is
nothing but supervisors and as many as the count before it, every name is on
the roll at the head of that statement (those present and those absent),
nobody is named twice, and nobody on the roll is left out. A block that does
not pass puts no rows in `votes`: the motion is kept in `agenda_items` with
`votes_read` false and what stopped the reading in `problem`.

A vote is taken to belong to the matter whose file number was the last
before it, and to nothing else. Where the text does not keep that order, the
vote is not read either: a block that comes before its matter's file number
(the number is lost from the text, or misprinted) or after its attachments
(the matter it is on may be lost altogether), or after a line that has the
look of another matter and no file number of its own.

Of {n_blocks} blocks in the statements read, {n_blocks_read} were read
({share_read}%) and {n_unread} were not. Votes run from {first_vote} to
{last_vote}. To count by year:

```python
agenda = load_dataset("{repo}", "agenda_items", split="train").to_pandas()
agenda.groupby(agenda["date"].str[:4])[["vote_blocks", "blocks_read"]].sum()
```

## Tables

| Config | One row per | Rows |
|---|---|---|
| `default` (`items`) | matter (file number) in a statement read | {n_items} |
| `meetings` | statement listed | {n_meetings} |
| `agenda_items` | matter in a statement, headings too | {n_agenda_items} |
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

A matter keeps its file number from one meeting to the next (a report
continued for a year is one file), so a matter here is a file number, and its
row is drawn from the newest statement it stands in.

| Column | |
|---|---|
| `matter_id`, `matter_file` | The file number, `23-3603`. A standing matter has a letter in it (`A-1`, the local emergencies continued from meeting to meeting). Where the text has lost a line's file number, `matter_file` is empty and `matter_id` is the line's `item_id`. |
| `date`, `agenda_date` | The first and the latest meeting the matter stands in, among the statements read. |
| `times_on_agenda` | How many of those meetings. |
| `doc_type` | `ordinance` or `resolution`, from the words of the matter; else `other`. |
| `title`, `body` | As the newest statement has them. `status` and `subject` are empty. |
| `year` | Of `date`. |
| `last_action`, `last_action_date` | What the newest statement that says so says was done with it. |
| `ayes`, `noes`, `mover`, `seconder` | Of the latest vote on it. |
| `votes_read` | Whether that vote's block was read. If not, `ayes` and `noes` are 0 and mean nothing. Empty where the matter was never voted on. |
| `result` | `Fail` where the statement says the motion failed; otherwise empty. `passed_date` is empty. |
| `url` | The newest statement it stands in. |
| `item_id`, `meeting_id` | Its line in that statement. |

### meetings

`meeting_id` (the County's number for the statement), `date`, `time`, `body`,
the statement (`minutes_url`), the County's page (`url`) and how many `items`
the statement has; then the statement's `name` in the County's list, which
says what sort of meeting it was, its `file`, and what the reading found:
`kind` (the sort of meeting the statement's own title gives), `summary`
(`read`, `no text layer`, or empty where it has not been read), `pages`,
`vote_blocks`, `blocks_read`, and `roll`, the supervisors listed at the head of
the statement and whether each was present, as JSON. `date` is the day the
statement prints at its head where it was read, and `listed_date` the day the
County's list gives. `location` and `agenda_url` are empty.

### agenda_items

| Column | |
|---|---|
| `item_id`, `meeting_id`, `date`, `body` | The line, and the meeting it was at. |
| `agenda_number`, `sequence` | Its number in the statement (`12`, `S-1`, `CS-2`, `1-D`, `65-A`, `Set Matter 1`) and its place in the order. A heading has no number, nor has what opens a meeting (the video, the presentations). |
| `matter_id`, `matter_file` | The file number. Empty on a heading. |
| `title`, `text` | `text` is everything the statement says the matter is. `title` is the short title printed above it, which the statements have had since 2019; before that it is the same as `text`. |
| `action` | What the statement says the Board did: from the last "On motion of" or "By Common Consent" before the line's last vote, or with no vote its last action. |
| `mover`, `seconder` | The supervisors who moved and seconded, where the action names them. |
| `ayes`, `noes`, `not_voting` | Counted from `votes`, for that vote. 0 where its block was not read. |
| `votes_read` | True where every block on the line was read, false where one was not, empty where the line has no block. |
| `vote_blocks`, `blocks_read` | How many blocks stand on the line, and how many were read. |
| `problem` | Why a block was not read. |
| `motions`, `motion_log` | How many actions the line has, and each of them as JSON: its words, mover and seconder, and whether it has a block and the block was read. |
| `heading` | True for a heading (II. CONSENT CALENDAR), which is not a matter. |
| `section`, `group` | The heading this line sits under, and the heading in capitals above it within that (ADMINISTRATIVE MATTERS 24 - 63, or the district whose board the supervisors were sitting as). |
| `result` | `Fail` where the statement says the motion failed; otherwise empty. |
| `doc_type` | As in `items`. |

### votes

`member` and `vote`, for each motion whose block was read: `motion` numbers
the actions on a line and `motion_text` is its words. A vote is `AYE`, `NO`,
`ABSENT`, `ABSTAIN` or `RECUSED`; the statements' own words for the last
three are Absent, Abstentions and Recuse. Every motion here has one row for
each supervisor on the roll of that meeting.

### members

One row for each supervisor named in a block that was read: `name`, `district`,
and `first_vote`, `last_vote` and `votes` counted from the votes here. The
statements give no terms of office, so `start`, `end` and `role` are empty;
`serving` is true for those on the roll of the newest statement read.

## What to know

- A statement names a supervisor by surname ("Supervisor Solis"). The full
  name and the district here are from a list of everyone who has sat since
  October 2008, kept in the script; a surname not on it would be kept as
  printed, with no district.
- The Board votes on nearly everything by name, and nearly always all one
  way: a consent matter has its own block like any other. A vote "by Common
  Consent, there being no objection" is printed with a block too, and is
  here as the block has it.
- A motion with `votes_read` false was voted on by name; the names are in the
  statement (`minutes_url`) and not here. Two kinds recur. In the statements
  of the budget deliberations each change to the budget is a numbered motion
  (6-A, 6-B) under the one matter, with a vote and no file number of its own;
  those votes are not read. And where a supervisor's recusal is told in a
  sentence and not in the block ("Supervisor Kuehl declared a conflict and
  recused herself from the vote"), the block names four of five and is not
  read.
- Where the Board acted twice on a matter, the statement prints the matter
  again for the second action. Both are on the matter's one line, as motions
  1 and 2.
- A line with no `agenda_number` is what opens a meeting (the video, the
  presentations, the report of the closed session), or a matter whose number
  the text has lost; such a matter keeps its file number and its votes, and
  its `title` may be only the last of its lines. The numbers are not in one
  run: they start again for the districts' boards, and some matters are
  printed after those that follow them.
- The statement does not mark a motion that carried. Count `ayes` and `noes`;
  what number carries a motion depends on the motion (some need four votes).
- The supervisors also sit as the boards of other districts in the same
  meeting (the Development Authority, the Regional Park and Open Space
  District). Their matters are in the statement and here, numbered `1-D`,
  `1-P`; `group` says which body.
- `title`, `text` and `action` are the statement's lines joined, and may carry
  a stray line from the page around them.
- A statement is posted a week or two after its meeting. Meetings of the last
  {recent_days} days are read again on each run, since a signed copy may
  replace the first one posted.

## How it is made

[`build_la_county_board.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_la_county_board.py)
in cat-pol-datasets. The records are public records of the County of Los
Angeles; this compilation is released under CC0.
