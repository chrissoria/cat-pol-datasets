---
license: cc0-1.0
language:
- en
pretty_name: Calaveras County Board of Supervisors
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

# Calaveras County Board of Supervisors

What the Calaveras County Board of Supervisors did at its meetings, and how
each supervisor voted, read from the minutes of each meeting.

```python
from datasets import load_dataset

items = load_dataset("{repo}", split="train")
votes = load_dataset("{repo}", "votes", split="train")
```

## Where it comes from

One source: the County's meeting portal (IQM2),
[calaverascountyca.iqm2.com](https://calaverascountyca.iqm2.com/Citizens/).
Its calendar lists the Board's meetings from 2000, and {n_with_minutes} of
them have a minutes document, a PDF with its own text. The portal also has a
page for every agenda item, but most of those pages have no vote; the minutes
have the votes all the way back. So everything here below the list of meetings
is read from the minutes. Nothing is added to what the Clerk wrote there.

{n_read} sets of minutes are read, of meetings from {first_meeting} to
{last_meeting}. {n_scans} more are scans with no text of their own; they are
counted (`minutes` is `no text layer`) and left, since nothing is read off the
picture of a page. The minutes of 2011 to 2014 are scans the County ran
through a character reader: their text has slips ("Meri ta Callaway"), which
are read through where a name's letters still say who is meant.

The portal's robots file asks for a minute between requests. The minutes are
fetched one every {pause} seconds, once, and their text is kept.

## How a vote is printed, and how it is read

The minutes print a vote three ways, by when they were written (`format` in
`meetings`):

| `format` | Meetings | A vote in the minutes |
|---|---|---|
| `moved` | 2000 to 28 May 2013 | A line under the motion: `Moved: Callaway Second: Tryon Approval: Unanimous`, then `ABSENT: Stein` where someone was. A divided vote is `Approval: Majority NOES: Tryon` (or `Dissenting:`, `ABSTAIN:`). |
| `prose` | 11 June 2013 to 9 September 2014 | A sentence: "Motion by Supervisor Spellman, second by Supervisor Edson. Unanimously approved by Supervisors Edson, Wright, Callaway, Ponte and Spellman." A divided vote names both sides. Until January 2014 it is a count instead, "5-0 approved" or "4-1 approved, Supervisor Wright voted no." |
| `portal` | 23 September 2014 on | The portal's own minutes, a block under each item: `RESULT: ADOPTED [4 TO 1]`, `MOVER:`, `SECONDER:`, `AYES:`, `NAYS:`, and `ABSENT:`, `ABSTAIN:`, `RECUSED:`, `AWAY:` where there are any. |

Who was there is at the head: "PRESENT: ...; ..., Supervisors" and "ABSENT:"
in the older minutes, a table (Attendee Name / Title / Status / Arrived) in
the portal's. The portal's minutes of 2014 and 2015 have no table (`roll_from`
is empty), and a vote in them is read only where it names its ayes.

`established` on every vote says how it is known:

| `established` | The minutes say | What is written |
|---|---|---|
| `named` | The supervisor's name on that motion, with a word. | That supervisor's `AYE`, `NO`, `ABSENT`, `ABSTAIN`, `RECUSED` or `AWAY`. |
| `count` | A count and, by name, only those who were not ayes. | `AYE` for the supervisors left. They must be as many as the count says. |
| `unanimous` | Only "Unanimous". | `AYE` for each supervisor the head has present, less anyone the minutes have out of the room at that point. |
| `majority` | "Majority", and by name who did not vote aye. | `AYE` for the others, worked out as for `unanimous`. |

A motion is read whole or not at all. It puts no rows in `votes`, and is kept
in `agenda_items` with `votes_read` false and the reason in `problem`, where a
name on it is nobody on the Board, the count and the names disagree, a
sentence leaves a supervisor unaccounted for, the line says "Unanimous" and
the head does not say who was present, the minutes have the mover gone from
the meeting, or the vote is told in words the reader does not know.

Of {n_motions} motions in the minutes read, {n_motions_read} were read
({share_read}%) and {n_unread} were not. Of the {n_votes} votes, {n_named} are
`named`, {n_unanimous} `unanimous`, {n_count} `count` and {n_majority}
`majority`.

### What `unanimous` and `majority` rest on

That the Clerk says so when a supervisor is out of the room: "ABSENT: Stein"
on the motion's line, or "Supervisor Spellman left the meeting at 1:55 PM" in
the minutes. A supervisor the head has absent, whom a line does not name, has
no row for that motion: the line does not say they had not come. If a
supervisor stepped out and nothing said so, an `AYE` here is wrong for them,
and nothing in the minutes would show it. Votes that are `named` do not rest
on this.

## Tables

| Config | One row per | Rows |
|---|---|---|
| `default` (`items`) | item in the minutes | {n_items} |
| `meetings` | meeting of the Board the calendar lists | {n_meetings} |
| `agenda_items` | item in the minutes, and consent calendar voted on as one | {n_agenda_items} |
| `votes` | supervisor and motion voted on | {n_votes} |
| `members` | supervisor with votes on {seen_days} days or more | {n_members} |

The five tables, and the columns listed first in each, are the same in every
council and board dataset made this way. `meeting_id` joins `meetings` to the
rest; `item_id` joins a vote to the line it was taken on; `matter_id` joins
`items` to both.

### items

One row per item. `matter_id` is the portal's id for the item where the
minutes print it ("(ID # 9167)", from 2019), which is also its page on the
portal (`Detail_LegiFile.aspx?ID=`); such an item is here once however many
meetings it came to (`times_on_agenda`). Where the minutes print no id, the
item is its line in the minutes, `matter_id` is that line's `item_id`, and it
is here once for each meeting it came to. `ayes`, `noes`, `mover`, `seconder`
and `result` are those of the vote that took the item in: its own
(`action_on` is `item`) or its consent calendar's (`section`). `votes_read`
says whether that vote was read; if not, the counts are 0 and mean nothing.
`subject` is the department, `number` a resolution, ordinance or agreement
number the words give, `url` the minutes. `passed_date` and `status` are empty.

### meetings

`meeting_id` (the portal's), `date`, `time`, `body`, `location`, the meeting's
page (`url`), the agenda and the minutes (`agenda_url`, `minutes_url`), and
how many `items` the minutes have; the calendar's `name` ("Regular Meeting"),
`status`, `packet_url` and `summary_url`; and what the reading found:
`minutes` (`read`, `no text layer`, or empty where there are none or they have
not been fetched), `format`, `pages`, `motions`, `motions_read`, and as JSON
the `roll` the head gives (name, office, district, status, hour of arrival),
where it came from (`roll_from`), and the supervisors on the portal's
`letterhead`. The letterhead is the Board of the day the document was made,
not of the meeting, so it is kept apart from the roll.

### agenda_items

| Column | |
|---|---|
| `item_id`, `meeting_id`, `date`, `body` | The line, and the meeting it was at. |
| `agenda_number`, `sequence` | The item's number in the minutes and the line's place in the order. |
| `matter_id`, `title` | The item and its words. `matter_id` is empty on a consent calendar. |
| `action` | The words of the line's last motion as printed; with no motion, the result the minutes give, or the title. |
| `result` | `Pass` or `Fail` where the minutes' own word says so ("ADOPTED", "Approval:", "failed"). Never worked out from the names. |
| `outcome` | What the minutes print of the result: `ADOPTED [4 TO 1]`, `TABLED [UNANIMOUS]`, `Approval: Majority NOES: Tryon`. |
| `mover`, `seconder` | Of the last motion. |
| `ayes`, `noes`, `not_voting` | Counted from `votes`, for the last motion. 0 where it was not read. |
| `votes_read` | True where every motion on the line was read, false where one was not, empty where the line has no motion. |
| `motions`, `motions_read`, `problem` | How many motions the line has, how many were read, and why one was not. |
| `established` | How the votes of the line are known: `named`, or the way those not named were worked out. |
| `heading` | True for a consent calendar voted on as one, which is not an item. |
| `section`, `section_id` | The part of the meeting, and the consent calendar's line where its vote took the item in. |
| `voted_with` | The line whose vote took this item in: itself, its consent calendar, or the line it was taken up on after being pulled. |
| `doc_type`, `file_type`, `department`, `number` | `ordinance`, `resolution` or `other`; the portal's kind of file; the department; a number the words give. |
| `motion_log` | Each motion on the line as JSON: its words, mover and seconder as printed, how it was told, whether it was read. |

### votes

`member` and `vote` for each motion that was read: `motion` numbers the
motions on a line, `motion_text` is the motion's words as printed (in the
portal's minutes, the result line), and `established` is how the vote is known.

### members

One row for each supervisor with votes on {seen_days} days or more: `name`
(one name per person, the form the heads print most often), `district` where
the portal's minutes give it (the older minutes give none, so a supervisor who
left before 2014 has none), `first_vote`, `last_vote`, `votes`. `serving` is
true where the last vote is within {serving_days} days of the newest minutes
read, and `role` is the office those minutes give. The minutes give no terms
of office: `start` and `end` are empty.

## What to know

- Minutes are published months after their meeting. Meetings listed with no
  minutes yet have nothing read.
- In the portal's minutes each item of the consent calendar usually has its
  own block, so its vote is on the item. Where the calendar was voted on as
  one (all the older minutes, some of the portal's), the vote is on the
  calendar's line and the items point to it with `voted_with`.
- A vote in the portal's block is the Clerk's entry and is read as it stands,
  whoever it leaves out. A vote told in a sentence must account for every
  supervisor, since a clause can be missed.
- A vote an earlier meeting's closed session took, reported out at a later
  meeting, is not read as that later meeting's.
- A name is matched by its letters, so a scan's "Meri ta Callaway" is Merita
  Callaway, and by one letter's difference for a name of five letters or more.
- Speakers, presentations and reports are not kept apart from the item they
  stand under. A title in the portal's minutes that ends without a full stop
  may run on into what was said.

## How it is made

[`build_calaveras_board.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_calaveras_board.py)
in cat-pol-datasets. The records are public records of the County of
Calaveras; this compilation is released under CC0.
