---
license: cc0-1.0
language:
- en
pretty_name: Orange County Board of Supervisors
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

# Orange County Board of Supervisors

What came before the Orange County (California) Board of Supervisors, what was
done with it, and how each supervisor voted.

```python
from datasets import load_dataset

items = load_dataset("{repo}", split="train")
votes = load_dataset("{repo}", "votes", split="train")
```

## Where it comes from

One source: the County's agenda system, at
[ocagendaext.oc.gov](https://ocagendaext.oc.gov/ArchivedBosMeetings), which
the Board's own pages ([board.oc.gov](https://board.oc.gov/meetings-agendas))
are made from. It lists the Board's meetings and keeps the minutes of each as
a PDF. The system has no record of a vote apart from that document, so
everything here below the list of meetings is read from the minutes' text.
Nothing is added to what the Clerk wrote there, and nothing is corrected.

The minutes of {n_read} meetings are read, from {first_meeting} to
{last_meeting}. {n_scans} were scans with no text of their own, which are
counted and left: nothing is read off the picture of a page. For {n_agendas}
meetings the archive leads to the agenda where the minutes should be, and for
{n_other} to something that is not a PDF or to another day's minutes; those
are left too.

## How a vote is read, and when it is not

The minutes print a vote in one of two ways.

**By name**, from {first_named} on. Under the motion, a block names the
supervisors:

```
ON THE MOTION OF CHAIR CHAFFEE, SECONDED BY SUPERVISOR WAGNER,
APPROVED ITEM AS RECOMMENDED
Ayes: Nguyen, Wagner and Chaffee
Noes: Sarmiento and Foley
```

A block is read only if every name in it is one supervisor listed at the head
of those minutes, nobody is named twice, and nobody listed there is left out.

**By a code in the left margin**, before that, back to 2007:

```
52134  MOTION TO APPROVE ITEM AS RECOMMENDED FAILED TO CARRY
  ANN
```

with a key at the foot of the same minutes:

```
1. = Supervisor Nguyen      A. = Abstained
2. = Supervisor Sarmiento   X. = Excused
3. = Supervisor Wagner      N. = No
4. = Supervisor Chaffee     BO = Board Order
5. = Supervisor Foley
Above numbers refer to Supervisorial Districts
(1st number = Moved by; 2nd number = Seconded by)
```

So this one is: moved by Foley (5), seconded by Sarmiento (2), Nguyen (1)
abstained, Wagner (3) and Chaffee (4) voted no. In the tables it is five rows
of `votes`, with the code and the marks beside each (`code`, `marks`; the
marks are kept by column, `..ANN`).

The key says who each number is, what the first two places are, and what the
three marks are. Two things it does not say are taken as read here:

- **A mark belongs to the number it stands under.** The margin is set in a
  typewriter face, so a mark stands exactly under one number of the code. In
  every meeting whose minutes say at their head that a supervisor was excused,
  this reading has that supervisor excused in each vote, and nobody else.
- **A number with no mark under it voted aye.** The key has no mark for aye.

A code is read whole or not at all. It is read only if those minutes print the
key and it says all of the above; the key and the head of the minutes name the
same supervisor for each district; the code has each seated district once and
nothing else; every mark stands under one of its numbers, on the same page;
and neither of the first two numbers has a mark under it. (Those two moved and
seconded. A row of marks is now and then typed at the edge of the margin and
not under the numbers it is meant for, and such a row begins under them.)

Either kind of vote is left unread where it has a supervisor voting whom the
head of the same minutes has excused for the day: the minutes then say two
things, and in a few such votes the mark stands under the wrong number.

A vote that does not pass puts no rows in `votes`: the motion is kept in
`agenda_items` with `votes_read` false and what stopped the reading in
`problem`. Of {n_blocks} votes in the minutes read, {n_blocks_read} were read
({share_read}%) and {n_unread} were not. Votes run from {first_vote} to
{last_vote}. To count by year:

```python
agenda = load_dataset("{repo}", "agenda_items", split="train").to_pandas()
agenda.groupby(agenda["date"].str[:4])[["vote_blocks", "blocks_read"]].sum()
```

About half of the votes not read are in minutes whose key is not the Board of
that day: the key is typed once and carried from one meeting's minutes to the
next, and around a change of supervisors it names the old Board, or the new
one too soon. The head and the key then disagree, and nothing in those minutes
is read (`problem` on the meeting says so). Most of the rest are in a few
meetings too: four in the spring of 2021 whose head and key both still show a
seat as vacant after it was filled, so that every code has a number too many;
and three in 2014 whose codes ran over the margin onto a second line.

## Tables

| Config | One row per | Rows |
|---|---|---|
| `default` (`items`) | item in the minutes | {n_items} |
| `meetings` | meeting listed | {n_meetings} |
| `agenda_items` | line of the minutes, headings too | {n_agenda_items} |
| `votes` | supervisor and motion voted on | {n_votes} |
| `members` | supervisor in a vote that was read | {n_members} |

The five tables, and the columns listed first in each, are the same in every
council and board dataset made this way, so two can be set one on the other:
[san-diego-council](https://huggingface.co/datasets/chrissoria/san-diego-council)
and
[sd-county-ordinances](https://huggingface.co/datasets/chrissoria/sd-county-ordinances)
are two. `meeting_id` joins `meetings` to the rest; `item_id` joins a vote to
the line it was taken on; `matter_id` joins `items` to both.

### items

The system has no record of an item apart from its line in the minutes, so an
item is here once for each meeting it came to, and its `matter_id` is that
line's `item_id`.

| Column | |
|---|---|
| `date`, `agenda_date` | The day of the meeting. |
| `matter_id` | The line: the meeting's day and the item's number, `2025-12-16-S28D`. `matter_file` is empty. |
| `doc_type` | `ordinance` or `resolution` where the minutes give a number for one under the item, or failing that from the title; else `other`. |
| `title`, `body` | As the minutes have them. `status` is empty. |
| `subject`, `group` | The heading the item stands under: whose business it is (`ELECTED DEPARTMENT HEADS - Sheriff-Coroner`). |
| `year` | Of `date`. |
| `last_action`, `last_action_date` | What the minutes say was done with the item at this meeting. |
| `ayes`, `noes`, `mover`, `seconder` | Of the vote that took the item in: its own, or the consent calendar's. |
| `action_on` | `item` or `section`: which of the two that vote was. Empty where neither had one. |
| `votes_read` | Whether that vote was read. If not, `ayes` and `noes` are 0 and mean nothing. |
| `result` | `Fail` where the item's last action says the motion failed; otherwise empty. `passed_date` is empty. |
| `times_on_agenda` | Always 1. |
| `url` | The minutes. |
| `item_id`, `meeting_id`, `section` | The line, its meeting, and the part of the minutes it is in. |
| `number` | The resolution or ordinance numbers the minutes give under the item. |

### meetings

`meeting_id` (the day; a second meeting on one day, a special one beside the
regular one, ends in `-2`), `date`,
`time`, `body`, `location`, the County's listing (`url`), the minutes
(`minutes_url`), the agenda of a meeting to come (`agenda_url`) and how many
`items` the minutes have; then the meeting's `name` in the listing, its `kind`
at the head of the minutes (Regular, Special), the recording (`video_url`),
and what the reading found: `summary` (`read`, `no text layer`,
`an agenda, not minutes`, `minutes of another day`, `not a PDF`, or empty
where there are no minutes or they have not been read), `format` (`names` or `codes`),
`pages`, `vote_blocks`, `blocks_read`, `problem` (why none of the meeting's
votes were read, where that is so), and `roll`, the supervisors a vote in
those minutes is held to, with their districts and offices, as JSON.

The archive lists a meeting once for each recording of it (morning,
afternoon, read-out), each with its own address for the same minutes.
`documents` has the listing's keys for them all, and `name` their titles. A
row that leads to something other than the minutes (the agenda, a file that is
not a PDF) is listed with the day's meeting too.

### agenda_items

| Column | |
|---|---|
| `item_id`, `meeting_id`, `date`, `body` | The line, and the meeting it was at. |
| `agenda_number`, `sequence` | Its number in the minutes (`7`, `S28D`, `CS-1`, `SCS2`) and its place in the order. A heading has no number, nor has a motion to adjourn. |
| `matter_id`, `title` | The item. `matter_id` is empty on a heading. |
| `action` | What the minutes say the Board did: the line's last vote, or with no vote its last action. |
| `mover`, `seconder` | The supervisors who moved and seconded: the first two numbers of the code, or the names in the motion. |
| `ayes`, `noes`, `not_voting` | Counted from `votes`, for that vote. 0 where it was not read. |
| `votes_read` | True where every vote on the line was read, false where one was not, empty where the line has none. |
| `vote_blocks`, `blocks_read` | How many votes stand on the line, and how many were read. |
| `problem` | Why a vote was not read. |
| `voted_with` | The line whose vote took this item in: itself, or the consent calendar's heading. Empty where no vote did. |
| `motions`, `motion_log` | How many actions the line has, and each of them as JSON: its words, mover and seconder, its code and marks or its names, and whether it was read. |
| `heading` | True for a heading (II. CONSENT CALENDAR), which is not an item. |
| `section`, `section_id`, `group` | The part of the minutes this line is in, and the heading above it within that. |
| `result` | `Fail` where the line's last action says the motion failed; otherwise empty. |
| `doc_type`, `number` | As in `items`. |

### votes

`member` and `vote`, for each motion whose vote was read: `motion` numbers the
actions on a line and `motion_text` is its words. A vote is `AYE`, `NO`,
`ABSTAINED` or `EXCUSED`; the last two are the minutes' own words. `code` and
`marks` are what was printed, where the vote was printed as a code. Every
motion here has one row for each supervisor seated that day.

### members

One row for each supervisor in a vote that was read: `name`, as the head of
the minutes prints it, and `first_vote`, `last_vote` and `votes` counted from
the votes here. `district` and `role` are those printed at the head of the
newest minutes that list the supervisor. The minutes give no terms of office,
so `start` and `end` are empty; `serving` is true for those at the head of the
newest minutes read.

## What to know

- The two readings of a code that the key does not spell out (a mark belongs
  to the number above it; no mark is an aye) are this dataset's, not the
  County's words. `code` and `marks` are kept so they can be read another way.
- In the minutes with codes, the consent calendar is voted on as one, so its
  vote is on its heading. `voted_with` on an item gives that heading. An item
  the motion left out ("WITH THE EXCEPTION OF ITEM 26 ...") is not given the
  heading's vote; every number after such words is taken to be left out, days
  and times apart, which now and then leaves out one item too many.
- A motion with `votes_read` false was voted on; how is in the minutes
  (`minutes_url`) and not here.
- An action may say more than the vote does: "APPROVED ..., WITH SUPERVISOR
  SARMIENTO OPPOSING ATTACHMENT F" is five ayes in the margin, and a
  supervisor who "RECUSED HERSELF" is left out of a block of names (which is
  then not read). Read `action`.
- `EXCUSED` is the minutes' word for a supervisor who was not there for the
  vote, whether away for the day or out of the room.
- A mark is typed under its number by hand, and can be typed under the wrong
  one. Where the head of the minutes shows it (see above) the vote is not
  read; where a supervisor only stepped out, nothing shows it.
- The second number of a code is not always a seconder: a motion to adjourn in
  someone's memory is printed with a mover and then the rest of the Board. A
  code with a mark under its first or second number is not read, so a seconder
  who then voted no is not here either.
- A board order (`B.O.` in the margin: an item received, continued, deleted)
  has no vote, and is an action with no `vote_blocks`.
- The minutes do not mark a motion that carried. Count `ayes` and `noes`; what
  number carries a motion depends on the motion.
- Meetings to come are listed, with nothing read. Minutes are posted after the
  meeting; meetings of the last {recent_days} days are read again on each run.

## How it is made

[`build_orange_board.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_orange_board.py)
in cat-pol-datasets. The records are public records of the County of Orange;
this compilation is released under CC0.
