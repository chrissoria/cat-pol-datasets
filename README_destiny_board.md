---
license: cc0-1.0
language:
- en
pretty_name: {title}
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

# {title}

What came before the {title}, what the Board did
with it, and how each member voted.

```python
from datasets import load_dataset

items = load_dataset("{repo}", split="train")
votes = load_dataset("{repo}", "votes", split="train")
```

## Where it comes from

One source: the County's meeting system (Destiny Hosted, also called
AgendaQuick), at
[public.destinyhosted.com/agenda_publish.cfm?id={id}](https://public.destinyhosted.com/agenda_publish.cfm?id={id}).
The system has no API. A month's meetings are a page, and so are a meeting's
agenda and its minutes; in the older years the minutes are a document put up
in the page's place. Each meeting is read from the best of these it has:

| `source` in `meetings` | What was read | Meetings |
|---|---|---|
| `minutes` | The minutes' page. The clerk's entry sits under the line it is about. | {n_minutes} |
| `minutes document` | The minutes as a document, read from its text (no OCR), and set under the lines of the agenda's page where there is one. | {n_minutes_document} |
| `agenda` | The agenda's page only: the minutes are not up yet, or there were none. | {n_agenda} |

Meetings are listed from {first_listed} to {last_listed}; the minutes are
pages from {first_page}. Votes by member run from {first_vote} to {last_vote}.

A vote is the clerk's own words in the minutes, read by their labels:

```
Minute Order No. 17-104: Approved recommended action.
MOVED BY: Provenza / SECONDED BY: Saylor
AYES: Saylor, Provenza, Chamberlain.
NOES: Villegas.
ABSTAIN: None.
ABSENT: None.
RECUSE: Rexroad.
```

The minutes name a member by surname. The head of the same minutes lists who
sat that day and for which district ("JIM PROVENZA, DISTRICT 4"), and the two
together give `member` and `district`. Nothing else is added to what the
County entered, and nothing is corrected.

## Tables

| Config | One row per | Rows |
|---|---|---|
| `default` (`items`) | item put on an agenda | {n_items} |
| `meetings` | meeting of the Board | {n_meetings} |
| `agenda_items` | line of a meeting's agenda or minutes, headings too | {n_agenda_items} |
| `votes` | member and motion voted on | {n_votes} |
| `members` | member named in the Board's votes | {n_members} |

The five tables, and the columns listed first in each, are the same in every
council and board dataset made this way, so two can be set one on the other:
[san-diego-council](https://huggingface.co/datasets/chrissoria/san-diego-council)
and
[sd-county-ordinances](https://huggingface.co/datasets/chrissoria/sd-county-ordinances)
are two. `meeting_id` joins `meetings` to the rest; `item_id` joins a vote to
the line it was taken on; `matter_id` joins `items` to both.

### items

An item the County wrote a memo for has that memo's number as its
`matter_id`, and is here once however many agendas it was on. An item with no
memo (a call to order, a closed session, anything read from a document alone)
is here once for its line, and its `matter_id` is that line's `item_id`.

| Column | |
|---|---|
| `date`, `agenda_date` | The day of the first meeting it was at, and of the last. |
| `matter_id` | The memo's number in the system, or the line's `item_id`. `matter_file` is empty: the County gives an item no number of its own. |
| `doc_type` | `ordinance`, `resolution` or `other`, from its title. |
| `title`, `body` | The item's words on the agenda, and the Board. `status` is empty. |
| `subject` | The heading it sat under: usually the department. |
| `year` | Of `agenda_date`. |
| `last_action`, `last_action_date` | What the minutes say was done at its last meeting. |
| `result`, `ayes`, `noes`, `mover`, `seconder` | The last motion on it. Where the item had no motion of its own and the main heading it sits under had one (a consent agenda is voted on as one), these are that motion's. |
| `action_on` | `item` or `section`: which of the two the columns above come from. Empty where neither had a motion. |
| `passed_date` | Empty. A motion that carried may have been one to deny an item or put it off, so the day of the vote is not given as the day the item passed. |
| `times_on_agenda` | How many agendas it was on. |
| `url` | The item's own page, with its memo and attachments; failing that the meeting's. |
| `item_id`, `meeting_id`, `section` | The line, its meeting, and the main heading it sits under. |
| `minute_order` | The number the clerk gave the order made on it. |

### meetings

`meeting_id`, `date`, `time` (the hour in the agenda's first heading, where it
has one), `body`, the meeting's page (`url`), its agenda and minutes
(`agenda_url`, `minutes_url`) and how many `items` it had; then the meeting's
`name` as the County lists it ("Board of Supervisors Special Meeting",
"Budget Hearings"), the recording (`video_url`), whether the agenda and the
minutes are each a `page` of the system or a `document` (`agenda_kind`,
`minutes_kind`), and what the meeting was read from (`source`). `location` is
empty. The system files everything it lists under "{type}" as the Board's; all
of it is `body` "{body}" here. A meeting's number is its agenda's in the
system, or for the oldest the folder its documents are kept in.

### agenda_items

| Column | |
|---|---|
| `item_id`, `meeting_id`, `date`, `body` | The line, and the meeting it was at. `item_id` is the meeting and the line's place in it. |
| `agenda_number`, `sequence` | Its number on the agenda and its place in the order. |
| `matter_id`, `title` | The item. `matter_id` is empty on a heading. |
| `action` | The words of the last motion on this line. Where no vote was entered, everything the clerk entered under it. |
| `result` | Empty: the minutes do not mark a motion as carried or lost. Count `ayes` and `noes`. |
| `mover`, `seconder` | The members who moved and seconded. |
| `ayes`, `noes`, `not_voting` | Counted from `votes`, for the last motion. |
| `heading` | True for a heading, which is not an item. |
| `section`, `section_id` | The main heading this line sits under (CONSENT AGENDA, REGULAR AGENDA). |
| `subject` | The smaller heading above it: usually the department. |
| `motions` | How many motions were entered on this line. |
| `minute_order` | The number of the last. |
| `minutes` | Everything the clerk entered under the line: who spoke, and every motion. |
| `doc_type`, `url` | As in `items`. |

### votes

`member`, `vote` and `district`, for each motion: `motion` numbers the motions
on a line, `motion_text` is its words, `minute_order` its number, and
`name_in_minutes` the member's name as the clerk typed it. The votes here
are {vote_words}: `AYE` and `NO` are spelled one way in every dataset, and
the rest are the Board's own words (its minutes say `RECUSE`; here it is
`RECUSED`).

### members

One row for each person named in votes on at least {seen_days} days: `name`
and `district` from the head of the minutes, and `first_vote`, `last_vote`
and `votes` counted from the votes here. The system keeps no terms of office,
so `role`, `start` and `end` are empty, and `serving` is true for a member
whose last vote here is within {serving_days} days.

## What to know

- A consent agenda is voted on as one, so its vote is on its heading and not
  on the items under it. To see how the Board voted on a consent item, join
  the item's `section_id` to the heading's `item_id`. Where a member stood
  aside from one consent item, the clerk says so in words under that item
  ("with Supervisor Villegas recusing himself on this item"): it is in
  `action`, and not in `votes`.
- `result` and `passed_date` are empty: the minutes do not mark a motion as
  carried or lost, and what number carries one depends on the motion (some
  need four votes of five). Count `ayes` and `noes`.
- Where the minutes of an earlier meeting are corrected, the clerk sets that
  meeting's orders out again under the item. No vote is read off such a line,
  since its own motion and the ones quoted cannot be told apart for sure.
- A vote is here only if the minutes name the members. What the Board did by
  consensus, or reported out of closed session ("approved by a 5-0 vote"),
  has an `action` and no rows in `votes`.
- A name the clerk mistyped ("Chambelain") matches nobody at the head of the
  minutes and is kept as typed, with no district. Such a name is in `votes`
  and not in `members`.
- Where the minutes are a document, the text runs on: `title` is cut at the
  first line that ends a sentence, and `action` and `minutes` may carry the
  names of the item's attachments before the clerk's words and the next
  heading after them. Votes do not depend on this. The minutes of the first
  months of 2007 are laid out differently again, with no list of who sat at
  their head: their members are named from the nearest meeting that has one.
- An earlier meeting's order set out again where its minutes were corrected
  is not counted as a vote of the later meeting.
- The clerk now and then gives two orders the same number.
- The County keeps other bodies in the same system (the Planning Commission,
  LAFCO and others). They are not read here.
- Meetings to come are listed, with their agenda and nothing done yet.

## How it is made

[`build_destiny_board.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_destiny_board.py)
in cat-pol-datasets. The records are public records of the County of {place};
this compilation is released under CC0.
