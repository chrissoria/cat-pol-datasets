---
license: cc0-1.0
language:
- en
pretty_name: Stanislaus County Board of Supervisors
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

# Stanislaus County Board of Supervisors

What the Stanislaus County Board of Supervisors did at its meetings, and how
each supervisor voted.

```python
from datasets import load_dataset

items = load_dataset("{repo}", split="train")
votes = load_dataset("{repo}", "votes", split="train")
```

## Where it comes from

One source: the County's own site,
[stancounty.com/bos](https://www.stancounty.com/bos/). It lists the Board's
meetings a year to a page and keeps the minutes of each as a PDF. A vote is
recorded nowhere else, so everything here below the list of meetings is read
from the minutes' text. Nothing is added to what the Clerk wrote there.

{n_read} sets of minutes are read, of meetings from {first_meeting} to
{last_meeting}. None was a scan with no text of its own ({n_scans}); such
minutes would be counted and left, since nothing is read off the picture of a
page.

The minutes go back to 1993 on the site. They are read from {first_year}: the
first minutes that give the movers by name are those of 3 February 2004.
Before that the movers are initials (`C/P unan.`), and in 1993 "unan." was
written with a supervisor absent, so the rule below would not hold there.

## How a vote is read, and when it is not

The minutes are short. Each motion is one paragraph, which opens with who
moved, who seconded, and how the vote went:

```
Withrow/B. Condit unan. Adopted the consent calendar
Chiesa/Withrow (4-1)(C. Condit opposed) 5.B.1 Approved the Agreement with ...
B. Condit/Grewal (4-0)(Chiesa absent) 7.2 Conducted a public hearing ...
```

They never list the ayes, and they print no roll of the Board. A supervisor
who voted aye is named only if they moved or seconded. So a vote row for a
supervisor the line does not name is written only where the minutes' own words
leave no other possibility. `established` on every vote says which case it is:

| `established` | The minutes say | What is written |
|---|---|---|
| `named` | The supervisor's name with a word: opposed, absent, abstained, recused. | That supervisor's `NO`, `ABSENT`, `ABSTAIN` or `RECUSED`. |
| `count` | A count, `(4-1)`, and by name everyone who is not an aye. The noes named must be as many as the count's; ayes, noes and those named as not voting must make the seats. | `AYE` for each supervisor on that day's roll who is not named. |
| `unanimous` | `unan.` and no count, with the minutes having nobody away at that point: the head says "All Supervisors Present" (or whoever it names absent has since arrived), and nobody has left the room without returning. | `AYE` for every supervisor on that day's roll. |

A motion is read whole or not at all. It puts no rows in `votes`, and is kept
in `agenda_items` with `votes_read` false and the reason in `problem`, where:

- the line has `unan.` while the minutes have a supervisor away. The line does
  not then say who voted;
- a count and the names do not agree: `(4-1)(Olsen absent)`, `(4-0)` with
  nobody named, `(4-1)(O'Brien opposed) unan.`;
- the line names someone who is not on the roll, or someone without a name
  ("District 4 Supervisor absent");
- the line has names but neither a count nor `unan.`;
- the roll of that day has no name for one of the seats (below).

Of {n_motions} motions in the minutes read, {n_motions_read} were read
({share_read}%) and {n_unread} were not. Of the {n_votes} votes, {n_unanimous}
are `unanimous`, {n_count} are `count` and {n_named} are `named`. To count by
year:

```python
agenda = load_dataset("{repo}", "agenda_items", split="train").to_pandas()
agenda.groupby(agenda["date"].str[:4])[["motions", "motions_read"]].sum()
```

The share read is lowest in 2004, whose January minutes still give initials,
and dips where the Board's membership changes.

### What `unanimous` rests on

That when a supervisor is out of the room the Clerk says so. In the minutes
read to September 2026, every one of the 474 vote lines that name a supervisor
absent comes after the minutes had said that supervisor was away (absent at
the head, or "left at 10:08 a.m."), and of 506 motions voted on with a
supervisor away, 487 carry a count that names them. Twelve say only "unan."
and are not read. If a supervisor stepped out and neither the vote line nor
the minutes around it said so, an `AYE` here is wrong for that supervisor;
nothing in the minutes would show it.

### Who is on the Board

The minutes print no roll, so the roll of a meeting is drawn from the minutes
themselves, never from a list kept elsewhere. A supervisor is on it if the
minutes name them where only a supervisor can stand (moving, seconding, in a
vote's brackets, absent at the head, arriving or leaving), or open a paragraph
by calling them the chair, at that meeting, or at both an earlier and a later
meeting no more than a year apart. The roll must then have a name for every
seat: five, less any seat the minutes call vacant ("District Four Vacant").
Where it has not, nothing in that meeting is read.

This costs the first meetings of a new supervisor until the minutes first name
them, the last meetings of one who leaves without being named again, and the
newest meeting or two until every supervisor has been named in a later one.
Each run reads again every set of minutes whose text it has, and fetches those
of the last {recent_days} days again, so those fill in.

## Tables

| Config | One row per | Rows |
|---|---|---|
| `default` (`items`) | item in the minutes | {n_items} |
| `meetings` | meeting listed | {n_meetings} |
| `agenda_items` | item in the minutes, and consent calendar | {n_agenda_items} |
| `votes` | supervisor and motion voted on | {n_votes} |
| `members` | supervisor with a vote here | {n_members} |

The five tables, and the columns listed first in each, are the same in every
council and board dataset made this way, so two can be set one on the other:
[sacramento-county-board](https://huggingface.co/datasets/chrissoria/sacramento-county-board)
and
[sd-county-ordinances](https://huggingface.co/datasets/chrissoria/sd-county-ordinances)
are two. `meeting_id` joins `meetings` to the rest; `item_id` joins a vote to
the line it was taken on; `matter_id` joins `items` to both.

### items

The site has no record of an item apart from its line in the minutes, so an
item is here once for each meeting it came to, and its `matter_id` is that
line's `item_id`.

| Column | |
|---|---|
| `date`, `agenda_date` | The day of the meeting. |
| `matter_id` | The line: the meeting's day and the item's number, `2026-09-15-71`. `matter_file` is empty. |
| `doc_type` | `ordinance` or `resolution` where the words say one; else `other`. |
| `title`, `body` | What the minutes say was done with the item; the minutes give no other title. `status` is empty. |
| `subject` | The department the minutes end the item with ("– Planning"), where they do. |
| `year` | Of `date`. |
| `last_action`, `last_action_date` | The same words, and the day. |
| `ayes`, `noes`, `mover`, `seconder` | Of the vote that took the item in: its own, or its consent calendar's. |
| `action_on` | `item` or `section`: which of the two that vote was. Empty where neither had one. |
| `votes_read` | Whether that vote was read. If not, `ayes` and `noes` are 0 and mean nothing. |
| `result` | `Fail` where the words open by saying the motion failed; otherwise empty. `passed_date` is empty. |
| `times_on_agenda` | Always 1. |
| `url` | The minutes. |
| `item_id`, `meeting_id`, `section` | The line, its meeting, and "Consent calendar" for an item of one. |
| `number` | The resolution or ordinance number the words give, where they give one. |

### meetings

`meeting_id` (the day, with `-special` where the site keeps a second set of
minutes for it), `date`, `time` (where the listing gives one), `body`, the
year's page (`url`), the agenda and the minutes (`agenda_url`, `minutes_url`)
and how many `items` the minutes have; then the listing's `note` ("Special
Meeting"), the video page (`video_url`), and what the reading found: `minutes`
(`read`, `no text layer`, or empty where there are no minutes or they have not
been read), `pages`, the session's `name` and the line at the head that says
who was there (`present`), `seats`, `motions`, `motions_read`, and as JSON the
`roll` of that day with the office the minutes give each, those the minutes
name where only a supervisor can stand (`named`) and as the chair (`spoken`).
`location` is empty. A day the listing marks "No Meeting" is not listed.

### agenda_items

| Column | |
|---|---|
| `item_id`, `meeting_id`, `date`, `body` | The line, and the meeting it was at. |
| `agenda_number`, `sequence` | The item's number as the minutes print it (`7.1`, `*B5a`, a public hearing's hour) and the line's place in the order. Many motions have none. |
| `matter_id`, `title` | The item, and what was done with it. `matter_id` is empty on a consent calendar. |
| `action` | The words of the line's last motion, with the item's number as printed; with no motion, the same as `title`. |
| `mover`, `seconder` | The supervisors who moved and seconded the last motion. |
| `how` | What the line says of the vote, as printed: `unan.`, `(4-1)(C. Condit opposed)`. |
| `ayes`, `noes`, `not_voting` | Counted from `votes`, for the last motion. 0 where it was not read. |
| `votes_read` | True where every motion on the line was read, false where one was not, empty where the line has no motion. |
| `motions`, `motions_read` | How many motions the line has, and how many were read. |
| `problem` | Why a motion was not read. |
| `established` | `count` or `unanimous`: how the votes of those not named were known. |
| `voted_with` | The line whose vote took this item in: itself, or its consent calendar. Empty where no vote did. |
| `motion_log` | Each motion on the line as JSON: its words, mover and seconder as printed, `how`, and whether it was read. |
| `heading` | True for a consent calendar, which is not an item. |
| `section`, `section_id` | The consent calendar an item was adopted in. |
| `result` | `Fail` where the words open by saying the motion failed; otherwise empty. |
| `doc_type`, `subject`, `number` | As in `items`. |

### votes

`member` and `vote`, for each motion that was read: `motion` numbers the
motions on a line, `motion_text` is its words, and `established` is how the
vote is known (above). A vote is `AYE`, `NO`, `ABSENT`, `ABSTAIN` or
`RECUSED`. Every motion here has one row for each supervisor on the Board that
day: five, or four while a seat was vacant.

### members

One row for each supervisor with a vote here: `name`, and `first_vote`,
`last_vote` and `votes` counted from the votes here. The name is the surname,
as the minutes print it, with an initial where two supervisors share one
("B. Condit", "C. Condit"). The minutes give no districts and no terms of
office, so `district`, `start` and `end` are empty; `serving` is true for those
on the roll of the newest meeting whose roll is whole, and `role` is the
office the minutes of that year give them (Chairman, Vice-Chairman).

## What to know

- A consent calendar is adopted by one vote, so that vote is on the calendar's
  line and not on the items under it; `voted_with` on an item gives the
  calendar. An item taken off the calendar is voted on by itself further down
  and is not under the calendar.
- A motion with `votes_read` false was voted on; what the minutes say of it is
  in `how` and `motion_log`, and the minutes are at `minutes_url`.
- The minutes do not mark a motion that carried. Count `ayes` and `noes`; what
  number carries a motion depends on the motion.
- A count of three numbers, `(3-1-0)`, is read by its first two, which must
  agree with the names like any other; the third is used two ways in the
  minutes and is not relied on.
- `RECUSED` and `ABSTAIN` are the minutes' words. "Recused" first appears in
  2018; before then the minutes have only "abstained".
- A name is matched by its letters, so "De Martini" is DeMartini and
  "B.Condit" is B. Condit. Five misspellings the minutes make (Montieth,
  Montheith, Cheisa, Whithrow, Wthrow) are read as the supervisor meant.
- Business with a number and no motion (a closed session, a letter referred)
  has a line with no vote. Speakers, presentations and reports with no number
  are not kept.
- A paragraph that ends at the foot of a page can run on into the paragraph
  that opens the next, where a title then has more words than it should.
- Minutes are posted after the meeting. Meetings listed with no minutes yet
  have nothing read.

## How it is made

[`build_stanislaus_board.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_stanislaus_board.py)
in cat-pol-datasets. The records are public records of the County of
Stanislaus; this compilation is released under CC0.
