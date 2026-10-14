---
license: cc0-1.0
language:
- en
pretty_name: Yuba County Board of Supervisors
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

# Yuba County Board of Supervisors

What was on the agendas of the Yuba County Board of Supervisors, what the
Board did with each item, and how each supervisor voted.

```python
from datasets import load_dataset

items = load_dataset("{repo}", split="train")
votes = load_dataset("{repo}", "votes", split="train")
```

## Where it comes from

One source: the County's agenda portal,
[agendasuite.org/iip/yuba](https://agendasuite.org/iip/yuba). Its calendar
lists every meeting since {first_year}. Each meeting has a page that links the
agenda, the minutes (the Clerk's "Summary of Proceedings") and the agenda
packet as PDFs, and lists the agenda's items with their file numbers
(`473/2026`). The agenda's lines here are the page's; what was done with each,
and every vote, is read from the minutes' text. Nothing is added to what the
Clerk wrote there.

{n_read} sets of minutes are read, of meetings from {first_meeting} to
{last_meeting}. {n_scans} were scans with no text of their own; such minutes
are counted and left, since nothing is read off the picture of a page. The
portal has no minutes before July 2017, and for some later meetings it has an
agenda and no minutes: those meetings have their agenda's lines here and
nothing done (`minutes` empty in `meetings`).

## How a vote is read, and when it is not

The minutes print each motion as a block under the item it was made on, with
every supervisor's name in it:

```
MOTION: Move to approve
MOVED: Randy Fletcher SECOND: Gary Bradford
AYES: Don Blaser, Gary Bradford, Randy Fletcher
NOES: Andy Vasquez, Seth Fuhrer
ABSENT: None
ABSTAIN: None
```

The last three lines are also printed as one (`NOES: None ABSTAIN: None
ABSENT: Andy Vasquez`) or folded together (`NOES/ABSENT/ABSTAIN: None`). Some
minutes of July 2017 to March 2018 have a grid instead, a line to a supervisor
with an X under YES, NO, ABSTAIN or ABSENT. A grid with no X in it is the form
left empty under an item that had no motion of its own; it is not a vote and
is not counted as a motion. Nor is a motion that "died for lack of a second".

So nothing is worked out: a row in `votes` is the word the minutes print over
that supervisor's name, and `established` is `named` on every row. What is
checked is that the names are the Board. Each set of minutes has a line
`ROLL CALL - Supervisors Vasquez, House, Fuhrer, Bradford, Messick` (some list
those who came and then say who was absent; both are the roll), and a motion
is read only if the names in it are exactly those, each once.

A motion is read whole or not at all. It puts no rows in `votes`, and is kept
in `agenda_items` with `votes_read` false and the reason in `problem`, where:

- it names fewer than the roll (`names 4 of the 5 on the roll: no Bradford`):
  the Clerk left a name out of the list;
- it has no list of names at all (`MOTION:` and `MOVED:` with no `AYES:`), or
  only empty ones;
- it names someone twice (in `AYES` and again in `ABSENT`), or someone not on
  the roll (a supervisor sworn in after the roll call);
- it has a name under `NOES/ABSENT/ABSTAIN` folded together, which does not
  say which of the three;
- a sentence under the consent motion speaks of a vote and cannot be tied to
  an item and a supervisor (below).

Of {n_motions} motions in the minutes read, {n_motions_read} were read
({share_read}%) and {n_unread} were not. To count by year:

```python
agenda = load_dataset("{repo}", "agenda_items", split="train").to_pandas()
agenda.groupby(agenda["date"].str[:4])[["motions", "motions_read"]].sum()
```

### The consent agenda

The consent agenda is passed by one motion, printed under its heading. That
vote is on the heading's own line (`heading` true, `item_id` ending
`-consent`), and each item listed under it has that line in `section_id`; in
`items` such an item has `action_on` = `section`. An item taken off the
consent agenda is printed under it as "Moved to County Departments for
discussion" and again where it was voted on: it is one line here, with the
motion of its own.

Now and then the minutes add a sentence under the consent motion: "Supervisor
Fuhrer voted No on item 289-2022", "Supervisor House abstained on agenda items
305/2026 and 320/2026". Each item named then has a vote of its own, the
consent agenda's with that supervisor's `NO` or `ABSTAIN`, and the sentence is
its `motion_text`. The consent line keeps the vote as printed. A sentence of
that kind that cannot be tied to an item under the heading and a supervisor on
the roll leaves the consent motion unread.

### The grid

Where every line of a grid has a whole name, a line's X is that supervisor's.
In a few grids of late 2017 a long name runs on to a second line while the
X's stand one to a line from the top, so there is one line more than there are
names. Those are read by order, the first X the first supervisor's, and only
if the X's are as many as the names and fill the grid's first lines; all that
were so read have every X under YES.

## Tables

| Config | One row per | Rows |
|---|---|---|
| `default` (`items`) | item in the minutes read | {n_items} |
| `meetings` | meeting listed | {n_meetings} |
| `agenda_items` | item on a meeting's agenda, and heading voted on | {n_agenda_items} |
| `votes` | supervisor and motion read | {n_votes} |
| `members` | supervisor with votes here | {n_members} |

The five tables, and the columns listed first in each, are the same in every
council and board dataset made this way, so two can be set one on the other.
`meeting_id` joins `meetings` to the rest; `item_id` joins a vote to the line
it was taken on; `matter_id` joins `items` to both.

### items

One row for each item in minutes that were read. The portal knows an item by
a number of its own, so an item that came to two meetings is here once, with
the last of them.

| Column | |
|---|---|
| `matter_id`, `matter_file` | The portal's number for the item (`8523`), and its file number (`473/2026`). Where the page gives no number of its own, `matter_id` is the file number. |
| `date`, `agenda_date` | The day of the last meeting it came to, and of the first. |
| `doc_type` | `ordinance` or `resolution` where the words say one; else `other`. |
| `title`, `body` | The agenda's title. `status` is empty. |
| `subject` | The department the title opens with ("Sheriff-Coroner"), where it does. |
| `year` | Of `date`. |
| `last_action`, `last_action_date` | What the minutes say after the title, and the day. |
| `ayes`, `noes`, `mover`, `seconder`, `result` | Of the vote that took the item in: its own, or the consent agenda's. |
| `action_on` | `item` or `section`: which of the two that vote was. Empty where neither had one. |
| `votes_read` | Whether that vote was read. If not, `ayes` and `noes` are 0 and mean nothing. |
| `times_on_agenda` | How many agendas the item was on. `passed_date` is empty. |
| `url` | The item's page on the portal. |
| `item_id`, `meeting_id`, `section` | The line, its meeting, and the agenda's topic. |
| `number` | The resolution or ordinance number the minutes give, where they give one. |

### meetings

`meeting_id` (the portal's number), `date`, `time`, `body`, `location` (the
room), the meeting's page (`url`), the agenda and the minutes (`agenda_url`,
`minutes_url`) and how many `items` it has; then the portal's `name` for the
meeting ("BOS - 18/2026"), the Clerk's `note` on it ("Special Meeting", or how
to join), the agenda packet (`packet_url`), and what the reading found: `page`
(`read`, or `not found`), `minutes` (`read`, `no text layer`, `not a PDF`, or
empty where none are posted), `pages`, the roll call as printed (`present`),
`motions`, `motions_read`, and as JSON the `roll` with the office the page
gives each (Chair, Vice Chair). Meetings to come are listed, with nothing read.

### agenda_items

| Column | |
|---|---|
| `item_id`, `meeting_id`, `date`, `body` | The line, and the meeting it was at. |
| `agenda_number`, `sequence` | The line's number on the page's agenda, and its place in the order here. |
| `matter_id`, `matter_file`, `title` | The item, its file number and the agenda's title. Empty `matter_id` on a heading. |
| `action` | What the minutes say after the title: "Approved", "Adopted Resolution No. 2026-75", or what was said and then how the vote went. |
| `mover`, `seconder` | Who moved and seconded the last motion. |
| `ayes`, `noes`, `not_voting` | Counted from `votes`, for the last motion. 0 where it was not read. |
| `result` | `Pass` or `Fail` where the minutes say so under the motion ("Motion Carried", "Approved via unanimous Vote"); never worked out from a count. |
| `votes_read` | True where every motion on the line was read, false where one was not, empty where the line has no motion. |
| `motions`, `motions_read` | How many motions the line has, and how many were read. |
| `problem` | Why a motion was not read. |
| `heading` | True for a heading with a motion of its own: the consent agenda, or a motion made under a heading and on no item. |
| `section`, `section_id` | The agenda's topic, and for an item passed with the consent agenda, that line. |
| `in_minutes` | Whether the minutes have the item. False for an item of a meeting whose minutes are not read, and for one the minutes leave out. |
| `doc_type`, `subject`, `number` | As in `items`. |
| `document_url` | The item's staff report, where the page links one. |
| `motion_log` | Each motion on the line as JSON: its words, mover and seconder as printed, the names under each word, what follows it, and whether it was read. |

### votes

`member` and `vote`, for each motion that was read: `motion` numbers the
motions on a line, `motion_text` is the motion's words, and `established` is
`named`. A vote is `AYE`, `NO`, `ABSENT`, `ABSTAIN` or `RECUSED`. Every motion
here has one row for each supervisor on that meeting's roll.

### members

One row for each supervisor who voted on two days or more: `name` as the
minutes most often print it, and `first_vote`, `last_vote` and `votes` counted
from the votes here. `serving` is true where the last vote is within 120 days
of the run; `role` is the office the newest meeting's page gives. The minutes
give no districts and no terms of office, so `district`, `start` and `end` are
empty.

## What to know

- A supervisor absent from a meeting is still in each of its motions, as
  `ABSENT`: the minutes list them so. The roll call says who was absent when
  the meeting opened; a motion's own lists say who was there for it.
- A motion made after another on the same item, or after something said under
  it, is kept on that item's line as its next motion; `motion_text` says what
  it was. A motion made under a heading and on no item (to add an item to the
  agenda, to elect the chair) is on a line of its own with `heading` true.
- `result` is the minutes' word for the motion, not for what was moved:
  "Denied via Roll Call Vote" under a motion to deny is `Pass`.
- `section` is the agenda's topic. An item heard out of order (a hearing set
  for an hour) is printed elsewhere in the minutes and keeps its topic here.
- Lines the page has under a topic with no file number ("All matters listed
  under Consent Agenda are considered to be routine ...") are notes, not
  items, and are not kept.
- A name is matched to the roll by its surname; one a letter out ("Messsick")
  is read as the supervisor meant if no other on the roll is as near.
- Meetings of the last {recent_days} days and those to come are fetched again
  on each run: minutes are posted after the meeting.

## How it is made

[`build_yuba_board.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_yuba_board.py)
in cat-pol-datasets. The records are public records of the County of Yuba;
this compilation is released under CC0.
