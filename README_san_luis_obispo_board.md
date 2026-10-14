---
license: cc0-1.0
language:
- en
pretty_name: San Luis Obispo County Board of Supervisors
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

# San Luis Obispo County Board of Supervisors

What the San Luis Obispo County Board of Supervisors did at its meetings, and
how each supervisor voted, from {first_vote} to {last_vote}.

```python
from datasets import load_dataset

items = load_dataset("{repo}", split="train")
votes = load_dataset("{repo}", "votes", split="train")
```

## Where it comes from

Two hosts hold the record, and everything here is read from them.

The County's archive on Granicus
([slocounty.granicus.com](https://slocounty.granicus.com/ViewPublisher.php?view_id=46),
the list on the County's own page of Board meetings) lists every meeting since
July 2006, each with its agenda and its minutes. Where the minutes are kept has
changed twice. Until the end of 2011 they are a web page on Granicus. From 2012
the archive's link leads to the County's agenda portal
([agenda.slocounty.ca.gov](https://agenda.slocounty.ca.gov/IIP), a Provox
system), which keeps the minutes as a PDF. From 2022 the link leads to a PDF
on Granicus. {n_read} sets of minutes are read: {n_pages} web pages and
{n_pdfs} PDFs, of meetings from {first_meeting} to {last_meeting}. Minutes
that are a scan with no text of their own are counted and left: {n_scans}
(those of 5 January 2009).

The portal also has a page for each meeting from 2012, which lists the
agenda's items with a file number (`87/2011`) and the portal's own number for
each. An item of the minutes that has the same number and the same words there
takes both (`matter_file`, `matter_id`). Until about 2021 the portal has a
page of votes for each item as well. Those pages are not read, one request an
item being too many to ask; the count the meeting's page shows beside an item
is kept as `portal_tally` ("5-0-0": for, against, did not vote), and can be
set against `ayes` and `noes`.

Both hosts' robots.txt disallow everything to every reader. They are read all
the same, as public records, under this project's own name and at one request
a second at most; a refusal by either host is not worked around.

## How a vote is read, and when it is not

The minutes print every vote by name, in one of two forms. Until 2011:

```
Thereafter, on motion of Supervisor Jerry Lenthall, seconded by Supervisor
Shirley Bianchi, and on the following roll call vote:
AYES:    Supervisors: Jerry Lenthall, Shirley Bianchi, James R. Patterson, Chairperson K.H. 'Katcho' Achadjian
NOES:    None
ABSENT:  Supervisor: Harry L. Ovitt
```

From 2012, a grid under the motion, a row to a supervisor with an X under
AYES, NOES, ABSTAIN or RECUSE:

```
Motion by: Bruce S. Gibson
Second by: Adam Hill
SUPERVISORS                        AYES  NOES  ABSTAIN  RECUSE
Patterson, James R. (Chairperson)   x
Mecham, Frank R. (Board Member)           x
```

So nothing is worked out: a row of `votes` says what the minutes print beside
that supervisor's name, and `established` is `named` on every row. `vote` is
`AYE`, `NO`, `ABSTAIN`, `RECUSED` or `ABSENT`.

What is checked is that the names are the Board. The head of each set of
minutes says who was PRESENT and who ABSENT, and that is the roll of the day.
A motion is read only if every name in it is on that roll, each once, and
everyone on the roll is accounted for:

- a list of names (2006 to 2011) must name everyone itself, under AYES, NOES,
  ABSENT or ABSTAIN;
- a grid (2012 on) leaves out whoever is not in the room. A supervisor it does
  not name has a row `ABSENT` if the minutes have said they are away: at the
  head, in a sentence above the motion ("Supervisor Compton is now absent",
  until "Supervisor Compton is now present"), or in the first words under the
  grid ("(SUPERVISOR ADAM HILL IS NOW PRESENT.)", as the minutes of 2012 note
  a return). If the minutes have not said so, the motion is not read.

Twenty-one web pages of 2007 to 2011 print no PRESENT and ABSENT at their
head. For those the roll is that of the nearest minutes before and the nearest
after, if both are within 60 days and name the same five; `note` in `meetings`
says so. One motion in eight of 2006 to 2011 has the mover and seconder left
empty ("on motion of Supervisor , seconded by Supervisor ,") and the names
under AYES and NOES all the same; it is read like any other and has no
`mover`.

A motion is read whole or not at all. One that is not read puts no rows in
`votes`; its line stays in `agenda_items` with `votes_read` false and the
reason in `problem`:

- the grid prints one supervisor twice and another not at all. Six sets of
  minutes of January to April 2019 do, with "Adam Hill" in two rows and no
  row for Bruce S. Gibson: 36 lines, the largest loss here;
- a name in the vote is not on the roll at the head of the minutes. This is so
  where a new supervisor is sworn in after the roll is called (8 October 2013,
  5 January 2015, 7 January 2025) and where the head leaves a supervisor out;
- the grid has not one X to a name, has no X at all, or has words beside an X
  that are not about one item ("X (Airports Fees Only)");
- the minutes print who moved and who seconded and no grid under them;
- the minutes say two things of one supervisor on one consent item (an X
  under NOES "(Item No. 14 only)" and a sentence that she recused herself).

Of {n_motions} motions in the minutes read, {n_motions_read} were read
({share_read}%) and {n_unread} were not. The share is lowest in 2019 (81%),
2025 (92%) and 2013 (94%), for the reasons above. To count by year:

```python
agenda = load_dataset("{repo}", "agenda_items", split="train").to_pandas()
agenda.groupby(agenda["date"].str[:4])[["motions", "motions_read"]].sum()
```

### The consent agenda

Most of the Board's business is passed in one motion, printed under "This is
the time set for consideration of the Consent Agenda". That vote is on a line
of its own (`heading` true, `title` "Consent Agenda") and each item it covers
points to it (`section_id`); such an item has no rows of its own in `votes`.
Which items a consent motion covers is taken from its own words ("items 1
through 9, 11 through 18 and 22 through 39"), and an item the minutes say was
pulled, withdrawn or continued is not counted as passed by it. An item pulled
from the consent agenda is printed again further down with a motion of its
own; it is one line here, with that motion.

Where the minutes add that a supervisor voted no on one item of the consent
agenda, abstained or was recused ("Supervisor Mecham: votes no on Item No.
20", "Supervisor Hill: abstains from voting on this item", an X under RECUSE
with "(Item 27 Only)"), that item has a vote of its own here: the consent
agenda's, with that supervisor's word changed. If such words cannot be tied to
an item the motion covers and a supervisor on the roll, the consent motion is
not read at all. Some consent motions name fewer items than the consent agenda
has ("Items 1 through 5, 7 through 10" of 22), and a few are printed with no
vote under them; an item no motion covers has no vote here (`action_on`
empty).

### The portal's count

Where the portal's page of a meeting shows a count for an item (2012 to about
2021), it is the same as the votes read from the minutes for all but 34 of
some 6,300 items. In those 34 the portal has, as a rule, "5-0-0" where the
minutes' grid has a supervisor under NOES or ABSTAIN. The minutes are the
record the Clerk certifies, and they are what `votes` has; `portal_tally` is
there to set beside it.

### What is not here

`result` is `Fail` where the minutes say a motion failed, and otherwise empty:
whether a motion carried is not worked out from the count (some need four
votes of five). The minutes of a meeting are posted some weeks after it, first
as a draft (`note` "draft" in `meetings`); each run fetches the last
{recent_days} days again. The adjournment ("On motion duly made and
unanimously carried") names no one and is not a line here.

## Tables

| Config | One row per | Rows |
|---|---|---|
| `default` (`items`) | item in the minutes | {n_items} |
| `meetings` | meeting the archive lists | {n_meetings} |
| `agenda_items` | item in a meeting's minutes, and consent agenda voted on | {n_agenda_items} |
| `votes` | supervisor and motion read | {n_votes} |
| `members` | supervisor with votes here | {n_members} |

The five tables, and the columns listed first in each, are the same in every
council and board dataset made this way, so two can be set one on the other.
`meeting_id` joins `meetings` to the rest; `item_id` joins a vote to the line
it was taken on; `matter_id` joins `items` to both.

### items

One row per item. An item the portal knows by a number is here once, with the
last meeting it came to; any other is here once for each set of minutes it is
in, and its `matter_id` is that line's `item_id`.

| Column | |
|---|---|
| `date`, `agenda_date` | The day of the meeting, and of the first meeting the item came to. |
| `matter_id`, `matter_file` | The portal's number for the item and its file number (`87/2011`), where the portal lists it; else the line (`4560-12`) and empty. |
| `doc_type` | `ordinance` or `resolution` where the words say one; else `other`. |
| `title`, `body` | The item as the minutes print it. `status` is empty. |
| `subject`, `section` | The heading the item stands under ("Consent Agenda - Public Works Items"). |
| `year` | Of `date`. |
| `last_action`, `last_action_date` | What the minutes say the Board did, and the day. |
| `ayes`, `noes`, `mover`, `seconder` | Of the vote that took the item in: its own, or its consent agenda's. |
| `action_on` | `item` or `section`: which of the two that vote was. Empty where neither had one. |
| `votes_read` | Whether that vote was read. If not, `ayes` and `noes` are 0 and mean nothing. |
| `result` | `Fail` where the minutes say the motion failed; otherwise empty. `passed_date` is empty. |
| `times_on_agenda` | How many sets of minutes the item is in. |
| `url` | The portal's page for the item, or the minutes. |
| `item_id`, `meeting_id` | The line, and its meeting. |
| `number` | The resolution or ordinance number the minutes give, where they give one. |

### meetings

`meeting_id` (the number Granicus gives the meeting's recording), `date`,
`time` (from the head of the minutes), `body`, the recording (`url`,
`video_url`), the agenda and the minutes as the archive links them
(`agenda_url`, `minutes_url`) and how many `items` the minutes have; then the
archive's `name` for the meeting ("Board of Supervisors - Special Meeting"),
where the minutes were found (`document_url`), the portal's number for the
meeting (`portal_id`), `format` (`html` or `pdf`), and what the reading found:
`minutes` (`read`; `no text layer`; `same as <meeting>` where the archive
lists one meeting in two parts with one set of minutes; a word for why they
could not be fetched; or empty where there are none yet), `pages`, `note`
("draft"), the head's own words for who was there (`present`), `motions`,
`motions_read`, and as JSON the `roll` of that day with the office the head
gives each. `location` is empty. An addendum to an agenda, which the archive
lists as a row of its own, is not a meeting and is not here.

### agenda_items

| Column | |
|---|---|
| `item_id`, `meeting_id`, `date`, `body` | The line, and the meeting it was at. |
| `agenda_number`, `sequence` | The item's number on the agenda (`12`; `A-12` until 2011; `1-27` for a consent agenda), and its place in the minutes. |
| `matter_id`, `matter_file` | As in `items`. Empty for a consent agenda's own line. |
| `title` | The item as the minutes print it; "Consent Agenda" for the consent agenda's line. |
| `action` | The words of the last motion on the line, or what the minutes say was done. |
| `result` | `Fail` where the minutes say the last motion failed; otherwise empty. |
| `mover`, `seconder` | Of the last motion. |
| `ayes`, `noes`, `not_voting` | Counted from the votes read on the last motion. |
| `heading` | True for a consent agenda's own line. |
| `section`, `section_id` | The heading the line stands under; and, for an item passed by a consent motion, that motion's line. |
| `motions`, `motions_read` | How many motions the minutes print on the line, and how many were read. |
| `votes_read` | True if every motion on the line was read, false if one was not, empty if there was none. |
| `problem` | Why a motion was not read. |
| `doc_type`, `number` | As in `items`. |
| `portal_tally` | The count the portal's page of the meeting shows for the item, "for-against-did not vote", where it shows one. |
| `motion_log` | Every motion on the line as JSON: its words, mover, seconder, the names and marks as printed, who the minutes had away, and whether it was read. |

### votes

`item_id`, `meeting_id`, `date`, `matter_id`, `matter_file`, `member`, `vote`,
then `motion` (1 for the first motion on a line), `motion_text` (its words) and
`established` (always `named`).

### members

One row per supervisor who voted on two days or more: `name` (as the minutes
most often print it), `district` (the minutes print it in the grid from 2019;
empty for a supervisor who left before then), `role` (the office the newest
minutes give a serving supervisor), `serving` (the last vote is no more than
120 days old), `first_vote`, `last_vote`, `votes`. `start` and `end` are
empty: the minutes give no terms of office.
