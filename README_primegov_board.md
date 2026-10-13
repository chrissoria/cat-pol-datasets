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

What came before the {title} and the County's other
public bodies, what was done with it, and how each member voted.

```python
from datasets import load_dataset

items = load_dataset("{repo}", split="train")
votes = load_dataset("{repo}", "votes", split="train")
```

## Where it comes from

One source: the County's meeting system (PrimeGov, also sold as Granicus
OneMeeting), at
[{host}.primegov.com](https://{host}.primegov.com/public/portal). The list of
meetings is read through the public API that portal itself reads
(`/api/v2/PublicPortal`). What was on an agenda and what was done with it are
read from the meeting's page (`/Portal/Meeting`): the minutes where the County
publishes them as a page, the agenda otherwise. Nothing is read from a PDF,
nothing is added to what the County published, and nothing is corrected.

Agendas here run from {first_meeting} to {last_meeting}, across {bodies}
bodies: the Board, and the commissions and committees the County keeps in the
same system. {vote_span}

## Tables

| Config | One row per | Rows |
|---|---|---|
| `default` (`items`) | item put on an agenda | {n_items} |
| `meetings` | meeting | {n_meetings} |
| `agenda_items` | line of a meeting's agenda, headings too | {n_agenda_items} |
| `votes` | member and motion voted on | {n_votes} |
| `members` | member seen voting at the Board | {n_members} |

The five tables, and the columns listed first in each, are the same in every
council and board dataset made this way, so two can be set one on the other:
[san-diego-council](https://huggingface.co/datasets/chrissoria/san-diego-council)
and
[sd-county-ordinances](https://huggingface.co/datasets/chrissoria/sd-county-ordinances)
are two. `meeting_id` joins `meetings` to the rest; `item_id` joins a vote to
the agenda line it was taken on; `matter_id` joins `items` to both.

### items

The system gives an item a new number on each agenda it is on, so an item is
here once for each, and its `matter_id` is that line's `item_id`.

| Column | |
|---|---|
| `date`, `agenda_date` | The day of the meeting. |
| `matter_id` | The system's number for the line. `matter_file` is empty: the County gives items no file number. |
| `doc_type` | `ordinance`, `resolution` or `other`, from the item's title. |
| `title`, `body` | The item's first line of words, and the body it came before. `status` and `subject` are empty. |
| `year` | Of `date`. |
| `last_action`, `last_action_date`, `result`, `ayes`, `noes`, `mover`, `seconder` | The last motion on it. Where the item had no motion of its own and was taken in by a consent calendar's one motion, these are that motion's. |
| `action_on` | `item` or `consent`: which of the two the columns above come from. Empty where neither had a motion. |
| `passed_date` | Empty. A motion that carried may have been one to deny an item or put it off, so the day of the vote is not given as the day the item passed. |
| `times_on_agenda` | Always 1. |
| `url` | The page the meeting was read from. |
| `item_id`, `meeting_id`, `section` | The line, its meeting, and the heading it sits under. |
| `number` | The resolution or ordinance number the clerk wrote under it, where there is one. |
| `attachments` | The papers filed with it, as a JSON list of names and addresses. |

### meetings

`meeting_id`, `date`, `time`, `body`, `location`, the page the meeting was
read from (`url`), its agenda and minutes (`agenda_url`, `minutes_url`: the
page where there is one, else the PDF) and how many `items` were on its
agenda; then the meeting's `name`, the system's number for the body
(`committee_id`), the packet and the video (`packet_url`, `video_url`), and
the system's own mark of the meeting's `state`. `document`, `document_id` and
`document_date` say which page the lines were read from and when the County
last published it; `document_read` is the same once it has been read. A
meeting with no `document` has no page, only files, and has no lines here.

### agenda_items

| Column | |
|---|---|
| `item_id`, `meeting_id`, `date`, `body` | The line, and the meeting it was at. A heading's `item_id` begins with `s`. |
| `agenda_number`, `sequence` | Its number on the agenda and its place in the order. |
| `matter_id`, `title` | The item, and its first line of words. `matter_id` is empty on a heading. |
| `action` | The words of the last motion on this line. |
| `result` | `Pass` or `Fail` where the minutes say so. See below. |
| `mover`, `seconder` | The members who moved and seconded. |
| `ayes`, `noes`, `not_voting` | Counted from `votes`, for the last motion. |
| `heading` | True for a heading (Consent Calendar, Closed Session), which is not an item. |
| `section`, `section_id` | The heading this line sits under. |
| `consent_id` | The heading whose one motion took this item in, where it was on a consent calendar and had no motion of its own. |
| `motions` | How many motions the minutes record on this line. |
| `tally` | The count the minutes give for the last motion, as `ayes-noes`. |
| `description` | What else the agenda says of the line. |
| `minutes_text` | Everything the minutes add under the line: the motions, and who presented or spoke. |

### votes

`member` and `vote`, for each motion: `motion` numbers the motions on a line
and `motion_text` is its words. A vote is `AYE`, `NO`, or the minutes' own
word in capitals: `ABSENT`, `ABSTAIN`, `RECUSED`.

### members

One row for each person who voted at the Board's own meetings on at least
{seen_days} days: `name`, and `first_vote`, `last_vote` and `votes` counted
from the votes here. The system publishes no terms of office and no districts,
so `district`, `role`, `start` and `end` are empty, and `serving` is true for
a member whose last vote here is within {serving_days} days. The Board is the
body numbered {board_ids} in this system.

## What to know

- A consent calendar is voted on as one, so its vote is on its heading and
  not on the items under it. To see how the Board voted on a consent item,
  join the item's `consent_id` to the heading's `item_id`. Which items the
  motion took in is read from its words (`Numbers 5 through 32`, less any it
  says were pulled); where the heading and the motion name different runs,
  only the items both name, or the run that starts at the first item, are
  taken.
- `result` is `Pass` or `Fail` only where the minutes say so. Many motions
  that carried have a count and no such word, so count `ayes` and `noes`
  rather than rely on it. A motion can fail with more ayes than noes where
  four votes of five are needed.
- A vote is here only if the minutes name who voted. A motion with a count
  and no names has an `action` and a `tally` and no rows in `votes`.
- A list of names the minutes write out more than once is kept once.
- A member's name is as the minutes have it; one person may appear under two
  spellings.
- Words a clerk struck out in correcting the minutes are left out.
- An agenda brought over from an older system may have lines that are only a
  time of day or a placeholder; they are kept as the system has them. Some
  older agendas are only linked to, on another site, and have no lines here.
- Committees and commissions are included; `body` says which.
- Meetings to come are listed, with nothing done yet.

## How it is made

[`build_primegov_board.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_primegov_board.py)
in cat-pol-datasets. The records are public records of the County of {place};
this compilation is released under CC0.
