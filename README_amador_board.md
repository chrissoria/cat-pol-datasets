---
license: cc0-1.0
language:
- en
pretty_name: Amador County Board of Supervisors
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

# Amador County Board of Supervisors

What the Amador County Board of Supervisors did at its meetings, and how each
supervisor voted.

```python
from datasets import load_dataset

items = load_dataset("{repo}", split="train")
votes = load_dataset("{repo}", "votes", split="train")
```

## Where it comes from

One source: the County's listing of its meetings in Granicus,
[amador.granicus.com](https://amador.granicus.com/ViewPublisher.php?view_id=1).
It lists the Board's meetings from {first_listed} to {last_listed} with the
agenda of each, and no minutes. The minutes are there all the same: the Board
approves the minutes of a meeting at a later one, and the agenda of that later
meeting has them attached, as a PDF, to the item that approves them.

**So these are draft minutes**: the minutes as the Clerk wrote them and put
them to the Board, before the Board approved them, now and then "with minor
edits". Each set says so at its head. The minutes as approved are on the
County's own website, which is not read. `minutes_name` in `meetings` is the
attachment's name ("June_11__2024_DRAFT_Minutes.pdf") and `minutes_in` the
meeting whose agenda carries it.

{n_read} sets of minutes are read, of meetings from {first_meeting} to
{last_meeting}. Agendas are read from {first_year}. What older agendas have
attached is behind a login ({n_closed} sets of minutes that were asked for,
`minutes` is `behind a login`), and some meetings' minutes were never attached
to an agenda at all; those meetings are listed with nothing read.

## How a vote is read, and when it is not

The head of the minutes prints the roll: "Present on Roll Call:", a supervisor
and district to a line, and "Absent:". A motion is one paragraph, and the
names are listed under it only where the Board divided:

```
MOTION: It was moved by Supervisor Forster, seconded by Supervisor Crew,
and carried 3-2 to approve the Side Letter of Agreement.
Ayes: Supervisors Crew, Forster, Brown
Noes: Supervisor Oneto, Axe
Absent: None

MOTION: It was moved by Supervisor Axe, seconded by Supervisor Forster and
carried unanimously, to approve the agenda as presented.
```

`established` on every vote says which of three ways it is known:

| `established` | The minutes say | What is written |
|---|---|---|
| `named` | The names under the motion. They must be exactly the roll at the head (those present and those absent), none twice, with as many ayes and noes as the count. | Each supervisor's `AYE`, `NO`, `ABSENT`, `ABSTAIN` or `RECUSED`. |
| `unanimous` | "carried unanimously", and nobody named. Read only where the head has all five supervisors present, and the minutes have no supervisor out of the room, come late, or standing aside (recused, abstaining, a conflict of interest) at that motion. | `AYE` for every supervisor on the roll. |
| `count` | A count and nobody named, at a meeting the head has a supervisor absent from: "carried 4-0-1" with four present and one absent. Read under the same condition, and only where the count is all of those present for the motion. | `AYE` for each supervisor present, `ABSENT` for each the head has absent. |

A motion is read whole or not at all. It puts no rows in `votes`, and is kept
in `agenda_items` with `votes_read` false and the reason in `problem`, where:

- it lists nobody and the minutes have a supervisor out of the room or
  standing aside, or it carried "unanimously" at a meeting the head has a
  supervisor absent from: the minutes do not then say who voted;
- it has a count that is not all of those present and no names ("carried
  4-0-1" with five present, "carried 4-1"), or neither a count, names nor
  "unanimously" ("carried to deny the claim");
- the names are not the roll, a name is there twice, a supervisor is left
  out, or the count and the names disagree ("carried unanimously" over three
  ayes and two noes; "carried 4-0-1" over five ayes);
- the head prints no roll.

Of {n_motions} motions in the minutes read, {n_motions_read} were read
({share_read}%) and {n_unread} were not. Of the {n_votes} votes, {n_unanimous}
are `unanimous`, {n_named} are `named` and {n_count} are `count`.

### What `unanimous` and `count` rest on

That a supervisor on the roll call was in the room for every motion unless the
minutes say otherwise. If one stepped out and the minutes did not say so, an
`AYE` here is wrong for that supervisor; nothing in the minutes would show it.
To keep to votes the minutes list by name, take `established == "named"`.

The Clerk writes a count of three numbers two ways: ayes, noes and the rest
("3-1-1" over three ayes, a no and one absent), and ayes, the rest and noes
("4-0-1" over four ayes and a no). So with names, the first number must be
the ayes and the other two the noes and the rest in either order; the names
say which.

## Tables

| Config | One row per | Rows |
|---|---|---|
| `default` (`items`) | item in the minutes | {n_items} |
| `meetings` | meeting of the Board listed | {n_meetings} |
| `agenda_items` | item in the minutes, and consent agenda | {n_agenda_items} |
| `votes` | supervisor and motion voted on | {n_votes} |
| `members` | supervisor with votes here on {seen_days} days or more | {n_members} |

The five tables, and the columns listed first in each, are the same in every
council and board dataset made this way, so two can be set one on the other.
`meeting_id` joins `meetings` to the rest; `item_id` joins a vote to the line
it was taken on; `matter_id` joins `items` to both.

### items

The system has no record of an item apart from its place in the minutes, so an
item is here once for each meeting it came to, and its `matter_id` is that
line's `item_id`. `title` is the item as the minutes open it; `last_action` is
the words of its motion, or failing that what the minutes put after "ACTION:".
`ayes`, `noes`, `mover` and `seconder` are of the vote that took the item in:
its own (`action_on` is `item`) or the consent agenda's (`section`).
`votes_read` says whether that vote was read; if not, `ayes` and `noes` are 0
and mean nothing. `number` is a resolution's or ordinance's number where the
minutes give one. `result`, `status` and `passed_date` are empty: a motion that
carried may have been one to deny or to put off.

### meetings

`meeting_id` (the number Granicus gives the meeting), `date`, `time`, `body`,
the listing (`url`), the agenda (`agenda_url`), the minutes where an agenda
carries them (`minutes_url`) and how many `items` they have; then `listed`
(false for a meeting the listing leaves out and an agenda carries the minutes
of: its `meeting_id` is the day, `d20240813`, with an `s` after it for a
special meeting), the agenda packet (`packet_url`), `minutes` (`read`, `behind a login`, `no text layer`, or
empty where no agenda read has them), `minutes_name`, `minutes_in`, the `kind`
of meeting the minutes say it was, `pages`, `seats`, the `roll` as JSON (each
supervisor present, with district and office) and those `absent`, `motions`
and `motions_read`.

### agenda_items

One row per item of the minutes, in order. The minutes number nothing but the
consent agenda's items, so an item is known by where it stands: its first
paragraph is its `title`, what the minutes tell of it is `description`, what
they put after "ACTION:" is `outcome`, and `action`, `mover`, `seconder` and
`how` (`unanimous` or the count, `3-2`, or empty where the motion gives neither) are of its last motion. `heading` is
true for the consent agenda and for "REGULAR AGENDA" and "PUBLIC HEARING".
`motions`, `motions_read`, `votes_read`, `problem` and `motion_log` are as
above; `ayes`, `noes` and `not_voting` are counted from `votes`; `established`
is how the item's votes are known where all are known one way; `voted_with` is
the line whose vote took the item in.

### votes

`member` and `vote` for each motion that was read; `motion` numbers the
motions on a line, `motion_text` is the motion's words as printed, and
`established` is `named` or `unanimous` (above).

### members

One row for each supervisor with votes here on {seen_days} days or more:
`name` and `district` as the roll of the newest minutes gives them, and
`first_vote`, `last_vote` and `votes` counted from the votes here. The minutes
keep no terms of office, so `start` and `end` are empty; `serving` is true for
a supervisor whose last vote here is within {serving_days} days, and `role` is
the office that roll gives them (Chairman, Vice-Chairman).

## What to know

- These are draft minutes (above). Where the Board changed them before
  approving them, the change is not here.
- The consent agenda is adopted by one vote, which is on its own line; its
  items are listed at the foot of the minutes with what was done ("Approved")
  and have `voted_with` set to that line, unless the minutes say the item was
  pulled.
- The minutes do not number the items of the regular agenda, and an item is
  taken to end with its "ACTION:" and "MOTION:". An item the minutes close
  with neither runs on into the next, whose words are then in its
  `description`.
- A motion with `votes_read` false was voted on. What the minutes print of it
  is in `motion_log`, and the minutes are at `minutes_url`.
- The newest meeting's minutes are attached to the agenda of the next, so they
  come two weeks or more after the meeting. Agendas of the last {recent_days}
  days are read again on each run.

## How it is made

[`build_amador_board.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_amador_board.py)
in cat-pol-datasets. The records are public records of the County of Amador;
this compilation is released under CC0.
