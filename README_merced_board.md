---
license: cc0-1.0
language:
- en
pretty_name: Merced County Board of Supervisors
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

# Merced County Board of Supervisors

What was on the agendas of the Merced County Board of Supervisors, what the
Board did with it, and how each supervisor voted.

```python
from datasets import load_dataset

items = load_dataset("{repo}", split="train")
votes = load_dataset("{repo}", "votes", split="train")
```

## Where it comes from

One source: the County's own agenda pages,
[web2.co.merced.ca.us/boardagenda](https://web2.co.merced.ca.us/boardagenda/).
A page for each year lists that year's meetings, and each meeting has its
agenda as a page whose items link the papers filed with them. The agendas go
back to {first_listed}, and every meeting of the Board listed since is here
with the lines of its agenda. The other bodies the supervisors sit as (the
In-Home Supportive Services authority, the groundwater agencies, the
redevelopment agency and the like) are left out.

The minutes ("Summary Action Minutes") are not linked from a meeting. They are
papers filed with a later meeting's item "Approve the Summary Action Minutes -
Final for the ... meeting", so they are found by looking through every agenda
from {minutes_from} on for such an item, and which meeting a set of minutes is
of is read off its own head. A vote is recorded nowhere else, so the votes
here are read from the minutes' text. Nothing is added to what the Clerk wrote
there.

The Board began approving its minutes this way in 2020, for the meetings from
September 2019. Those of September 2019 to November 2020 are scans ({n_scans}
meetings): they are counted, marked in `meetings` (`minutes` is `no text
layer`), and left, since nothing is read off the picture of a page. No agenda
has the minutes of December 2020 to December 2021. The {n_read} sets of
minutes read are of meetings from {first_meeting} to {last_meeting}, and the
votes run from {first_vote} to {last_vote}. The County keeps older minutes on
its main site, which this does not read.

## How a vote is read, and when it is not

The minutes are the agenda printed again with what was done set under each
item, in capitals, and the vote beside it by the number of each supervisor's
district:

```
CONSENT CALENDAR (Items No. 1-13)
APPROVED AS RECOMMENDED AYES: ALL
...
24. 1) Introduce an ordinance entitled ...
APPROVED AS RECOMMENDED AYES: 2, 3, 4 NOES: 1, 5
...
ADOPTED RESOLUTION NO. 2024-80 AS RECOMMENDED AYES: 2,3,4,5
NOT PRESENT: 1
```

The head of the same minutes prints the Board with its districts ("Josh
Pedrozo, District 2"), and the numbers are read against that. `established`
on every vote says how it is known:

| `established` | The minutes say | What is written |
|---|---|---|
| `numbers` | Districts under each word. Read only if every number is one of 1 to 5, none is given twice, and together they are all five. | For each supervisor the word their district stands under: `AYE`, `NO`, `NOT PRESENT`, `ABSTAIN`, `RECUSED`. |
| `all` | `AYES: ALL`, with the minutes having nobody out of the room at that point. | `AYE` for each of the five. |
| `names` | The supervisors by name under each word (one motion, in 2022). Read only if every name is on the roll and all five are named. | The word each name stands under. |

A motion is read whole or not at all. It puts no rows in `votes`, and is kept
in `agenda_items` with `votes_read` false and the reason in `problem`, where
the numbers do not make the five districts, where the line says `ALL` while
the minutes have a supervisor away (the sentence that says how the Board came
back from its closed session, "RECONVENED AT 10:00 A.M. WITH SUPERVISOR
MCDANIEL NOT PRESENT", or one that says a supervisor left, with nothing since
to say they are back), or where the minutes give only a count ("FAILED AFTER
ROLL CALL VOTE 2-3").

Of {n_motions} motions in the minutes read, {n_motions_read} were read
({share_read}%) and {n_unread} were not. Of the {n_votes} votes, {n_all} are
`all`, {n_numbers} are `numbers` and {n_names} are `names`.

`all` rests on the Clerk's own habit: when a supervisor is away, the minutes
give the vote by number with `NOT PRESENT`, and do not write `ALL`. In the
minutes read to October 2026 no `ALL` stands where the minutes have a
supervisor away. If one stepped out and neither the vote nor the minutes
around it said so, an `AYE` here is wrong for that supervisor; nothing in the
minutes would show it.

## Tables

| Config | One row per | Rows |
|---|---|---|
| `default` (`items`) | item of a meeting whose minutes were read | {n_items} |
| `meetings` | meeting of the Board listed | {n_meetings} |
| `agenda_items` | line of a meeting's agenda | {n_agenda_items} |
| `votes` | supervisor and motion voted on | {n_votes} |
| `members` | supervisor with a vote here | {n_members} |

The five tables, and the columns listed first in each, are the same in every
council and board dataset made this way, so two can be set one on the other.
`meeting_id` joins `meetings` to the rest; `item_id` joins a vote to the line
it was taken on.

### meetings

`meeting_id` (the folder the agenda is kept in: `20260317Board`, `MG154354`),
`date`, `time`, `body`, the year's listing (`url`), the agenda (`agenda_url`),
the minutes where they were found (`minutes_url`) and how many `items` the
agenda has; then the listing's label (`name`: "Board", "Board (Amended)",
"Special Meeting", "Final Budget Hearing"), whether the agenda is a page or a
PDF (`agenda`; a PDF's lines are not read), and what was found of the minutes:
`minutes` (`read`, `no text layer`, or empty), the meeting whose agenda
approved them (`minutes_from`), `pages`, the Board as their head prints it
(`roll`, as JSON with districts and offices), the sentence that says who came
back from the closed session (`present`), `motions`, `motions_read` and a
`note`. `approved` lists, as JSON, the minutes a meeting's own agenda approves
and what each turned out to be.

### agenda_items

One row for each line of an agenda: its items, and as headings (`heading`
true) the parts of the meeting (the consent calendar, the regular calendar,
scheduled items) and the departments. For a meeting whose minutes were read,
what the minutes say was done is laid on these lines, and what the minutes
have that the agenda has not is added after them (`source` says which).

| Column | |
|---|---|
| `item_id` | The meeting and the item's number: `20260210Board-14`. A hearing with no number is `-u1`, the consent calendar `-consent`, a department `-d3`. |
| `agenda_number`, `sequence`, `title` | As the agenda prints them. |
| `matter_id`, `documents_url` | The item's own number in the County's system, and the page that lists the papers filed with it. |
| `section`, `section_id`, `department` | The part of the meeting an item stands in, that part's line, and the department it is under. |
| `action` | What the minutes say was done, as printed: `APPROVED AS RECOMMENDED`, `PULLED`. The last motion's, where a line has several. |
| `how` | The vote as printed: `AYES: 2, 3, 4 NOES: 1, 5`. |
| `result` | `Pass` where what was done opens with approved, adopted, authorized or accepted, `Fail` where it says a motion failed; else empty. Never worked out from a count. |
| `number` | The resolution, ordinance or contract number printed under the item. |
| `ayes`, `noes`, `not_voting` | Counted from `votes`, for the last motion. 0 where it was not read. |
| `motions`, `motions_read`, `votes_read`, `problem` | How many motions the line has, how many were read, whether all were (empty where it has none), and why one was not. |
| `established` | `numbers`, `all` or `names`. |
| `voted_with` | The line whose vote took this item in: itself, or its consent calendar. Empty where no vote did. |
| `motion_log` | Each motion on the line as JSON. |
| `doc_type` | `ordinance` or `resolution` where the title says one; else `other`. |

`mover` and `seconder` are empty: the minutes do not print them.

### items

The items of the meetings whose minutes were read, one row for each meeting an
item came to, with the vote that took it in: `action_on` is `item` for a vote
of its own and `section` for the one vote of its consent calendar (or of the
letters "accepted and placed on file" together), and `votes_read` says whether
that vote was read. `matter_id` is the item's number in the County's system,
or its `item_id` where the agenda gives it none. `subject` is the department.

### votes

`member`, `district` and `vote` for each motion that was read; `motion`
numbers the motions on a line, `motion_text` is what was done, and
`established` is how the vote is known. Every motion here has five rows.

### members

One row for each supervisor who voted on two days or more: `name` as the head
of the minutes most often prints it, `district`, and `first_vote`, `last_vote`
and `votes` counted from the votes here. `serving` is true where the last vote
is within 120 days of the day the tables were made, and `role` is then the
office the newest minutes give (Chair, Vice Chair). `start` and `end` are
empty.

## What to know

- Votes begin in January 2022. The agendas, without votes, begin in 2008.
- The consent calendar is adopted by one vote, so that vote is on the
  calendar's line and not on its items; `voted_with` on an item gives the
  line. An item pulled from the calendar and voted on alone has its own vote.
- One supervisor's surname is printed "Espinoza" in the minutes of 2022 and
  "Espinosa" from 2023. He is one member here, under the spelling printed
  more often.
- `NOT PRESENT`, `ABSTAIN` and `RECUSED` are the minutes' words ("ABSTENTIONS:
  1", "RECUSAL: 1 AND 4").
- The minutes are in the order of the agenda, not of the clock. Who was out of
  the room "at that point" is followed down the page.
- Minutes are approved three to six weeks after their meeting, so the newest
  meetings have agendas and no votes yet. Each run fetches the agendas of the
  last {recent_days} days again.

## How it is made

[`build_merced_board.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_merced_board.py)
in cat-pol-datasets. The records are public records of the County of Merced;
this compilation is released under CC0.
