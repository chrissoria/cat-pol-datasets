---
license: cc0-1.0
language:
- en
pretty_name: Kern County Board of Supervisors
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

# Kern County Board of Supervisors

What the Kern County Board of Supervisors did at its meetings, and how each
supervisor voted.

```python
from datasets import load_dataset

items = load_dataset("{repo}", split="train")
votes = load_dataset("{repo}", "votes", split="train")
```

## Where it comes from

One source: the County's listing of the Board's meetings in Granicus,
[kern.granicus.com](https://kern.granicus.com/ViewPublisher.php?view_id=58).
It lists the Board's meetings from {first_listed} to {last_listed} and links
the minutes of {n_with_minutes} of them, the Board's Summary of Proceedings,
as a PDF. A vote is recorded nowhere else, so everything here below the list
of meetings is read from the minutes' text. Nothing is added to what the
Clerk wrote there.

{n_read} sets of minutes are read, of meetings from {first_meeting} to
{last_meeting}. {n_scans} more are scans with no text of their own (19 sets
of 2026, 9 of 2025, and a few earlier); they are counted (`minutes` is
`no text layer`) and left, since nothing is read off the picture of a page.
The meetings the listing has with another body (with the Bakersfield City
Council, the Civil Service Commission or the Planning Commission, and one
multi-jurisdictional forum) are not the Board's own and are left out.

## How a vote is read, and when it is not

The minutes have been set out one way since 2006. The head names the Board by
family name and says who answered the roll:

```
Supervisors: Peters, Parlier, Couch, Flores, Perez
ROLL CALL: All Present
```

Each item is its words, the Board's action in capitals, and a line with who
moved, who seconded and how the vote went:

```
CA-11) Proposed retroactive Cooperative Agreement with the California
Department of Food and Agriculture ... - APPROVED; AUTHORIZED CHAIRMAN
TO SIGN AGREEMENT 432-2026
Perez-Flores: All Ayes
Rubio-Watson: 3 Ayes; 2 Noes - Maben, Maggard
Maggard-Couch: 3 Ayes; 1 Absent – Perez; 1 Abstained - Scrivner
```

`established` on each vote says how it is known:

- `named` ({n_named} rows): the line names the supervisor with a word.
- `count` ({n_count}): the line gives a count of ayes and names everyone who
  was not one; the ayes are the rest of the Board at the head, and must be as
  many as the count says.
- `all` ({n_all}): the line says "All Ayes", which means every supervisor
  present at that point voted aye. Who was present is the roll call, changed
  by what the minutes note on the way ("NOTE: SUPERVISOR WATSON LEFT THE
  MEETING PRIOR TO THE VOTE ON ITEM NO. 4", "RECONVENED WITH ALL MEMBERS
  PRESENT"); a supervisor away at that point is `ABSENT`.

The consent agenda (items marked "CA" or "C", in 2006 and 2007 "*" or "#") is
approved by one motion, whose vote is printed again under each of its items,
wherever they stand; when it was taken is not printed. Its "All Ayes" are
read against the Board in the room then: the one a note gives ("Supervisor
Perez arrived prior to consideration of the consent agenda"), or else the only
one, of those the roll call and notes have in the room during the meeting,
that its own lines agree with (its mover and seconder there, anyone a line
names absent away). An item pulled from it and voted on apart has another
mover and seconder, and is read where it stands.

A vote is read whole or not at all. A line puts no rows in `votes`, and its
item is kept in `agenda_items` with `votes_read` false and the reason in
`problem`, where:

- its counts do not add up to the Board at the head, or it names someone not
  on it, or is told in words the reader does not know;
- it says "All Ayes" where who was in the room cannot be told: the minutes'
  own votes (a mover, a named absence) have a supervisor there whom the roll
  call and notes have away, or the other way round, so someone came or went
  unnoted (every "All Ayes" from the last note of that supervisor on is then
  left); a note says a supervisor abstained or was away for part of the item;
  or the head has no roll call;
- it is the consent agenda's "All Ayes" and a supervisor came or went during
  the meeting in a way its lines do not settle (it might have been taken with
  either Board in the room). This is most of what is not read.

Minutes are left whole where they have no roll of the Board (the State of the
County addresses, two meetings that were not held) and where the listing sends
the minutes to another host (the Committee of the Whole of 25 September 2006,
whose link goes to itsapps.kerncounty.com, which is not asked).

Of {n_motions} motions in the minutes read, {n_motions_read} were read
({share_read}%) and {n_unread} were not.

## Tables

| Config | One row per | Rows |
|---|---|---|
| `default` (`items`) | item in the minutes | {n_items} |
| `meetings` | meeting of the Board listed | {n_meetings} |
| `agenda_items` | item of the minutes, and step of procedure voted on | {n_agenda_items} |
| `votes` | supervisor and motion voted on | {n_votes} |
| `members` | supervisor with votes here on {seen_days} days or more | {n_members} |

The five tables, and the columns listed first in each, are the same in every
council and board dataset made this way. `meeting_id` (the number Granicus
gives the meeting's recording) joins `meetings` to the rest; `item_id` joins
a vote to its item; `matter_id` joins `items` to both.

### items

The system has no record of an item apart from its line in the minutes, so an
item is here once for each meeting it came to, and its `matter_id` is that
line's `item_id` (`5357-CA-11`). `title` is the item's words, `last_action`
the Board's action in capitals, `number` an agreement's, resolution's or
ordinance's number the action gives, `subject` and `department` the
department the minutes print it under, `consent` whether it is marked as the
consent agenda's. `result` is `carried` or `failed` only where the minutes
say so; `status` and `passed_date` are empty.

### meetings

`date`, `time`, the listing's `name` for the meeting ("Regular Meeting AM",
"Regular Meeting PM", "Budget Hearings", "Board of Supervisors @ KMC",
"Special Meeting - Closed Session" ...), `minutes_url`, `video_url`, and what
the reading found: `minutes` (`read`, `no text layer`), `pages`, the `roll`
the head names (JSON), who answered it (`present`, as printed), the `chair`
who signed the minutes, `motions` and `motions_read`. `agenda_url` is empty:
the listing links no agenda for a past meeting.

### agenda_items

One row per item of the minutes, and per step of procedure with a vote of its
own ("ADJOURNED AS BOARD OF SUPERVISORS; RECONVENED AS BOARD OF DIRECTORS,
KERN COUNTY WATER AGENCY"), which has no `agenda_number`. At the budget
hearings an item is a budget unit (`9144`). `action` is the Board's action in
capitals, `mover` and `seconder` those of the last vote line, `vote_line` the
vote lines as printed, `ayes`, `noes` and `not_voting` counted from `votes`.
`motions` and `motions_read` count the vote lines under the item, `votes_read`
is true where all were read, false where one was not, and empty where the item
has none; `problem` says why. `motion_log` has every vote line as JSON.

### votes

`member` (the family name, as the minutes print it) and `vote` (`AYE`, `NO`,
`ABSENT`, `ABSTAIN` ...) for each line that was read; `motion` numbers the
vote lines under an item, `motion_text` is the action that line is the vote
on, and `established` says how the row is known. Every line read has one row
for each supervisor at the head.

### members

One row for each supervisor with votes here on {seen_days} days or more:
`name` as the minutes print it, `district` where the minutes' own words give
one ("Led by Second District Supervisor Zack Scrivner") and never another,
and `first_vote`, `last_vote` and `votes` counted from the votes here. The
minutes keep no terms of office, so `start` and `end` are empty and `serving`
is true for a supervisor whose last vote here is within {serving_days} days.
`role` is `Chairman` for the serving supervisor who signed the newest minutes
read as Chairman.

## What to know

- The consent agenda's vote is printed under every one of its items, so one
  motion is here once per item.
- An "All Ayes" row rests on the roll call and the notes, not on the line
  alone; filter on `established` to keep only what a line names.
- Votes are dated by the listing's date for the meeting. A set of budget
  hearings that ran over two days is one document, dated by its first day.
- Minutes of the last {recent_days} days are fetched again on each run.

## How it is made

[`build_kern_board.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_kern_board.py)
in cat-pol-datasets. The records are public records of the County of Kern;
this compilation is released under CC0.
