---
license: cc0-1.0
language:
- en
pretty_name: San Benito County Board of Supervisors
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

# San Benito County Board of Supervisors

What the San Benito County Board of Supervisors did at its meetings, and how
each supervisor voted.

```python
from datasets import load_dataset

items = load_dataset("{repo}", split="train")
votes = load_dataset("{repo}", "votes", split="train")
```

## Where it comes from

One source: the County's listing of its meetings in Granicus,
[cosb.granicus.com](https://cosb.granicus.com/ViewPublisher.php?view_id=1).
It lists the Board's meetings from {first_listed} to {last_listed} and links
the minutes of {n_with_minutes} of them as a PDF. A vote is recorded nowhere
else, so everything here below the list of meetings is read from the minutes'
text. Nothing is added to what the Clerk wrote there.

{n_read} sets of minutes are read, of meetings from {first_meeting} to
{last_meeting} (five of 2022 are kept as a page of HTML and not a PDF, and
are read the same way). {n_scans} more are scans with no text of their own:
all the minutes of 2015 to 2019 that the listing has but four, and the signed
copies filed for many meetings of 2026. They are counted (`minutes` is
`no text layer`) and left, since nothing is read off the picture of a page.
The listing has no minutes for 2020 and 2021 and few before 2022; the County
keeps the rest on its own website, which is not read.

## How a vote is read, and when it is not

From 2022 the minutes are the agenda with what was done written under each
line. Every vote is printed the same way, with everyone on the Board named:

```
Moved by Angela Curro; seconded by Dom Zanger to approve contract per
staff recommendation.
Motion : 4 - 0 - 0
Voting For: Dom Zanger, Kollin Kosmicki, Mindy Sotelo, Angela Curro
Voting Against: None
Voting Abstain: None
Absent: Bea Gonzales
```

The head of the minutes prints the Board, a supervisor to a district (or
"Vacant"). A motion is read only if the names under it are exactly that Board,
none of them twice, and as many under each word as the count above them says.
Each name becomes a row: `AYE`, `NO`, `ABSTAIN` or `ABSENT`. `established` is
`named` on every vote: no vote here is worked out from a count or from who was
in the room.

A motion is read whole or not at all. It puts no rows in `votes`, and is kept
in `agenda_items` with `votes_read` false and the reason in `problem`, where:

- the names are not the Board: a supervisor is left out (one who was away and
  has no "Absent:" line), someone else is in (a joint meeting with the
  Planning Commission lists the commissioners too), or a name is misspelled
  past telling;
- a supervisor is named twice ("Voting For: Dom Zanger, ..." and "Absent: Dom
  Zanger");
- the count and the names disagree (`3 - 0 - 2` over three for and two
  against), or the count stands over "Voting For: None";
- the motion has no count and no names under it (one withdrawn, or one whose
  outcome is told in a sentence);
- the Board at the head of the minutes could not be read. That is so for the
  four sets of minutes of 2015 to 2017 that have text (they are set out
  another way, and name voters by surname), and for the meeting of 13
  December 2022, whose head has six names for five districts.

Of {n_motions} motions in the minutes read, {n_motions_read} were read
({share_read}%) and {n_unread} were not. To count by year:

```python
agenda = load_dataset("{repo}", "agenda_items", split="train").to_pandas()
agenda.groupby(agenda["date"].str[:4])[["motions", "motions_read"]].sum()
```

## Tables

| Config | One row per | Rows |
|---|---|---|
| `default` (`items`) | item in the minutes | {n_items} |
| `meetings` | meeting of the Board listed | {n_meetings} |
| `agenda_items` | line of the minutes, headings too | {n_agenda_items} |
| `votes` | supervisor and motion voted on | {n_votes} |
| `members` | supervisor with votes here on {seen_days} days or more | {n_members} |

The five tables, and the columns listed first in each, are the same in every
council and board dataset made this way, so two can be set one on the other.
`meeting_id` joins `meetings` to the rest; `item_id` joins a vote to the line
it was taken on; `matter_id` joins `items` to both.

### items

The system has no record of an item apart from its line in the minutes, so an
item is here once for each meeting it came to, and its `matter_id` is that
line's `item_id` (the meeting's number and the item's: `1184-1.7`).

`title` is what the agenda asks the Board to do, `subject` and `department`
the department and officer the agenda prints over it, `file_number` the
County's "SBC FILE NUMBER" (the file for that kind of business, not for the
item), and `number` a resolution's or ordinance's number where the minutes
print one under the item. `last_action`, `ayes`, `noes`, `mover` and
`seconder` are of the vote that took the item in: its own (`action_on` is
`item`) or its consent agenda's (`section`). `votes_read` says whether that
vote was read; if not, `ayes` and `noes` are 0 and mean nothing. `result`,
`status` and `passed_date` are empty: the minutes print a count, not what
became of a motion, and a motion that carried may have been one to deny or to
put off.

### meetings

`meeting_id` (the number Granicus gives the meeting's recording), `date`,
`time`, `body`, the listing (`url`), the agenda and the minutes (`agenda_url`,
`minutes_url`) and how many `items` the minutes have; then the listing's `name`
for the meeting ("Board of Supervisors - Special Meeting"), a `note` where the
minutes are marked ("Minutes - Amended"), the recording (`video_url`), and what
the reading found: `minutes` (`read`, `no text layer`, or empty where there are
none), `pages`, `seats` (the supervisors the head names), the `roll` as JSON
(each district's supervisor, or `vacant`), the `chair` the minutes say called
the meeting to order, `motions` and `motions_read`.

### agenda_items

One row per line of the minutes: the parts of the agenda (`heading` true for
one with items under it, and for the consent agenda), the numbered items under
them, and the lettered ones under the call to order. `action`, `mover`,
`seconder` and `count` (the count as printed, `4 - 0 - 0`) are of the line's
last motion; `ayes`, `noes` and `not_voting` are counted from `votes`.
`motions` and `motions_read` count the motions on the line, `votes_read` is
true where all were read, false where one was not, and empty where the line
has no motion; `problem` says why one was not. `voted_with` is the line whose
vote took the item in: itself, or its consent agenda. `description` is what
the minutes say under the line, and `motion_log` every motion on it as JSON.

### votes

`member` and `vote` for each motion that was read; `motion` numbers the
motions on a line, `motion_text` is the motion's words as printed, and
`established` is `named`. Every motion here has one row for each supervisor
the head of its minutes names.

### members

One row for each supervisor with votes here on {seen_days} days or more:
`name` as the minutes print it, `district` as the head of the newest minutes
gives it, and `first_vote`, `last_vote` and `votes` counted from the votes
here. The minutes keep no terms of office, so `start` and `end` are empty and
`serving` is true for a supervisor whose last vote here is within
{serving_days} days. `role` is `Chair` for the serving supervisor the newest
minutes say called the meeting to order.

## What to know

- The consent agenda is adopted by one vote, which is on its own line; an item
  under it has `voted_with` set to that line unless the motion leaves it out
  ("except for item #1.7"). An item left out has a motion of its own under it,
  or none.
- Votes run from {first_vote} to {last_vote}, but not evenly: the listing has
  minutes for part of 2022 only, and many of 2026 are scans.
- A motion with `votes_read` false was voted on. What the minutes print of it
  is in `motion_log`, and the minutes are at `minutes_url`.
- The minutes posted for a meeting are those the Board approved at a later
  one, so the newest meetings have none yet. Minutes of the last {recent_days}
  days are fetched again on each run, since a set is now and then replaced by
  an amended one.
- A name is matched by its letters, and a surname or first name alone
  ("Ignacio") is taken for the one supervisor on that day's Board who has it.

## How it is made

[`build_san_benito_board.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_san_benito_board.py)
in cat-pol-datasets. The records are public records of the County of San
Benito; this compilation is released under CC0.
