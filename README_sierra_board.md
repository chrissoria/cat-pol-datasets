---
license: cc0-1.0
language:
- en
pretty_name: Sierra County Board of Supervisors
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

# Sierra County Board of Supervisors

What was on the agendas of the Sierra County Board of Supervisors, what the
Board did with it, and how each supervisor voted.

```python
from datasets import load_dataset

items = load_dataset("{repo}", split="train")
votes = load_dataset("{repo}", "votes", split="train")
```

## Where it comes from

One source: the County's own site, the Board of Supervisors' category of its
[AgendaCenter](https://www.sierracounty.ca.gov/AgendaCenter/Board-of-Supervisors-5).
It lists the Board's meetings from June {first_year} and keeps for each an
agenda, as a page of HTML, and the minutes, as a PDF. The lines here are the
agenda's: a number, a title, and whether the line is a section (`6.`), an item
(`6.A.`) or a part of one (`11.B.i.`). A vote is recorded nowhere but in the
minutes, so what was done and who voted are read from the minutes' text and
set on the agenda's lines by the item's number. Nothing is added to what the
Clerk wrote.

{n_agendas} agendas and {n_read} sets of minutes are read, of meetings from
{first_meeting} to {last_meeting}. {n_scans} sets of minutes are scans with no
text of their own; they are counted and left, since nothing is read off the
picture of a page. `minutes` in the `meetings` table says what became of each
meeting's minutes (below).

## How a vote is read, and when it is not

The minutes print a roll at their head, with each supervisor's district, and
under an item what was done, who moved and seconded, and a count:

```
ROLL CALL
Present:  Lee Adams, Supervisor, Chair, District #1
          ...
Absent:   Sharon Dryden, Supervisor, District #5

ADOPTED, Resolution 2019-103. Motion: Adams/Dryden/Unanimous Roll Call Vote: 5/0
APPROVED. Motion: Huebner/Roen/Majority Roll Call Vote: 4/1 (Supervisor Beard NO)
FAILED. Motion: Heuer/Adams/Failed Roll Call Vote: 2/2/1 (Supervisors LeBlanc and
Dryden NO and Supervisor Roen ABSENT)
```

The count is ayes/noes, and after them how many did not vote. The line never
lists the ayes; it names only those who did not vote aye. So the ayes are
worked out: everyone the roll of those minutes has present, less anyone the
line names. `established` on every vote says which case it is:

| `established` | The minutes say | What is written |
|---|---|---|
| `named` | The supervisor's name in the bracket, with a word: NO, ABSENT, ABSTAINED. | That supervisor's `NO`, `ABSENT` or `ABSTAIN`. |
| `count` | A count whose ayes are as many as the roll has present, less those named. | `AYE` for each of those. A supervisor the roll has absent, whom the line does not name, is `ABSENT` if the count's third number has them, and has no row if it does not. |

A motion is read whole or not at all. It puts no rows in `votes`, and is kept
in `agenda_items` with `votes_read` false and the reason in `problem`, where:

- the line has no count (`Motion: Roen/Huebner/Unanimous`, and nothing after);
- the count does not come to what the roll and the names give: `5/0` on a day
  the roll has a supervisor absent, `4/0` with five present and nobody named,
  `4/1` with nobody named as voting no;
- the line names someone who is not on the roll of those minutes, as mover,
  seconder or in the bracket;
- the line says "Unanimous" and names a supervisor as voting no;
- the minutes have no roll at their head.

Of {n_motions} motions in the minutes read, {n_motions_read} were read
({share_read}%) and {n_unread} were not. Of the {n_votes} votes, {n_count} are
`count` and {n_named} are `named`.

Two things are taken more freely than the usual form, each only where every
supervisor who did not vote aye is named with a word and the ayes still come
to the count's first number: numbers after the ayes that stand in another
order (`4/1/0 (Supervisor Roen ABSENT)`, as the minutes of 2015 often have
it), and an abstention counted where the noes go (`4/1 (Supervisor Huebner
ABSTAINED)`). The word in the bracket is what is written.

The roll is the one at the head of the minutes. A supervisor who came late or
left early is not followed through the meeting: the lines after that either
name them (`4/0/1 (Supervisor Huebner ABSENT)`) and are read, or do not, and
then the count does not fit and the motion is not read.

## The consent agenda

The Board passes the consent agenda by one motion, which the minutes print at
their head before the list of its items. That vote is on the consent agenda's
own line (`heading` true), and each item the minutes list under it has that
line in `voted_with`, and `action_on` `section` in `items`. An item taken off
the consent agenda is not in the minutes' list and has no vote from it; where
the minutes say it was moved to the regular agenda under a new number, the new
line has `moved_from` and the old one `moved_to`.

## Tables

| Config | One row per | Rows |
|---|---|---|
| `default` (`items`) | item on the agenda of a meeting whose minutes were read | {n_items} |
| `meetings` | meeting of the Board listed | {n_meetings} |
| `agenda_items` | line of an agenda | {n_agenda_items} |
| `votes` | supervisor and motion voted on | {n_votes} |
| `members` | supervisor with votes here | {n_members} |

The five tables, and the columns listed first in each, are the same in every
council and board dataset made this way, so two can be set one on the other.
`meeting_id` joins `meetings` to the rest; `item_id` joins a vote to the line
it was taken on; `matter_id` joins `items` to both.

### meetings

`meeting_id` (the number the AgendaCenter gives the meeting), `date`, `time`
and `location` (from the sentence that opens the minutes or the agenda, where
it gives one place), `body`, the listing (`url`), the agenda and the minutes
(`agenda_url`, `minutes_url`) and how many `items` the agenda has; then the
listing's `name` for the row, `kind` (`regular` or `special`), `cancelled`,
the packet and the recording (`packet_url`, `video_url`), and what the reading
found: `agenda` (`read` or empty), `pages`, `session` (the minutes' own name
for the meeting), `motions`, `motions_read`, the `roll` as JSON (each
supervisor's name, district, office and whether present), and `minutes`:

| `minutes` | |
|---|---|
| `read` | The minutes were read. |
| `no text layer` | A scan. |
| `text not legible` | The PDF gives numbers in place of its letters. |
| `not a PDF` | The site has no file behind the link. |
| `minutes of another day (...)` | The minutes posted on this row say they are of another day. |
| `the same minutes as meeting ...` | A second copy of minutes read on another row. |
| empty | No minutes are posted (the newest meetings, a cancelled one). |

A cancelled meeting is a row with nothing on it. Rows of the listing that are
not meetings of the Board (a recording, a notice of adjournment, the County
Service Areas' board) are left out.

### agenda_items

| Column | |
|---|---|
| `item_id`, `meeting_id`, `date`, `body` | The line, and the meeting it was at. |
| `agenda_number`, `sequence`, `level` | The line's number as printed (`6.A.`), its place in the agenda's order, and its rank: 1 a section, 2 an item, 3 a part of one, 0 a motion the minutes have under no number. |
| `heading` | True for a section's line. A line of the first rank with nothing under it that the Board voted on is an item. |
| `title`, `description`, `time` | The agenda's title, what it says under it, and the hour the item was set for. |
| `section`, `section_id` | The section a line stands in. |
| `subject` | The department the title ends with, `(PUBLIC WORKS)`. |
| `source` | `agenda and minutes`, `agenda` (the minutes do not take the line up, or there are none), or `minutes` (a line the agenda does not have: an item given a new number, an item added, the approval of the regular agenda). |
| `action` | What the minutes say was done, as printed: `ADOPTED, Resolution 2019-103`. For an item of the consent agenda, the note under it. |
| `result` | `Pass` where the action is APPROVED or ADOPTED on a motion the line calls unanimous, a majority's or passed; `Fail` where it is FAILED; otherwise empty (DENIED, a tie). |
| `outcome`, `how` | The line's own word for the vote (Unanimous, Majority, Passed, Failed), and the line from "Motion:" on. |
| `mover`, `seconder` | Of the line's last motion. |
| `ayes`, `noes`, `not_voting` | Counted from `votes`, for the last motion. 0 where it was not read. |
| `motions`, `motions_read`, `votes_read`, `problem` | How many motions the line has and how many were read; true, false, or empty where the line has no motion; and why one was not read. |
| `voted_with` | The line whose vote took this one in: itself, or the consent agenda. |
| `moved_from`, `moved_to` | The number an item had, or was given, where the minutes say it was moved. |
| `doc_type`, `number` | `resolution`, `ordinance` or `other`, and the numbers the action gives: `Resolution 2021-059; Agreement 2021-037`. |
| `motion_log` | Each motion on the line as JSON. |

### votes

`member` and `vote` for each motion that was read: `motion` numbers the
motions on a line, `motion_text` is the Board's motion in the minutes' words
("The Board moved to adopt the resolution ..."), or what was done where the
minutes give no such sentence, and `established` is how the vote is known. A
vote is `AYE`, `NO`, `ABSENT` or `ABSTAIN`.

### items and members

`items` has every line that is not a heading, for meetings whose minutes were
read, with the vote that took it in (`action_on`: `item`, `section` or empty
where there was none). The site has no record of an item apart from its line
on an agenda, so an item is here once for each meeting it came to.

`members` has each supervisor with votes on two days or more: the name and
district as the roll prints them, `first_vote`, `last_vote` and `votes`.
`serving` is true where the last vote is within {serving_days} days, and
`role` is the office the newest roll gives a serving supervisor. The minutes
give no terms of office.

## What to know

- The minutes take the consent agenda first and the timed items when they
  came, so a line's `sequence` is its place on the agenda, not in the meeting.
- A motion with `votes_read` false was voted on; what the minutes say of it is
  in `how` and `motion_log`.
- Where a meeting has no agenda in HTML, its lines are the minutes' own.
- Minutes are posted after the meeting and an agenda is amended; meetings of
  the last {recent_days} days are fetched again on each run.

## How it is made

[`build_sierra_board.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_sierra_board.py)
in cat-pol-datasets. The records are public records of the County of Sierra;
this compilation is released under CC0.
