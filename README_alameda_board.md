---
license: cc0-1.0
language:
- en
pretty_name: Alameda County Board of Supervisors
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

# Alameda County Board of Supervisors

What came before the Alameda County Board of Supervisors, what was done with
it, and how each supervisor voted.

```python
from datasets import load_dataset

items = load_dataset("{repo}", split="train")
votes = load_dataset("{repo}", "votes", split="train")
```

## Where it comes from

One source: the County's listing of its meetings in Granicus, at
[alamedacounty.granicus.com](https://alamedacounty.granicus.com/ViewPublisher.php?view_id=2).
It lists the Board's regular, planning, special and budget meetings since
March 2014 and links the minutes of each as a PDF. The system has no record of
a vote apart from the minutes, so everything here below the list of meetings
is read from the minutes' text. Nothing is added to what the Clerk wrote
there, and nothing is corrected.

{n_read} sets of minutes are read, of meetings from {first_meeting} to
{last_meeting}. {n_scans} were scans with no text of their own; such minutes
are counted and left, since nothing is read off the picture of a page.
{n_illegible} have text that is not given as letters and are left too, and
{n_other} documents posted where minutes go are something else (slides, a
page of HTML, or the minutes of the Budget Workgroup, which is not the Board).

## How a vote is printed

The minutes print a vote as two short rows in the left margin, beside what the
Board did:

```
32451   Approved as recommended                               FILE 31857
32X51                                                         C-30447
```

and a key at their foot that says what the rows are made of:

```
** KEY **
Left Margin Notes               Right Margin Notes
1 President Haubert             A Abstained     C Contract
2 Supervisor Márquez            X Excused       O Ordinance
3 Supervisor Tam                N No            R Resolution
4 Supervisor Miley              BO Board Order  LIB Library
5 Supervisor Fortunato Bas
```

The first row is the supervisors' numbers. The second has, under each number,
that number again or the letter for what that supervisor did instead of
voting aye. The vote above is four ayes with Supervisor Miley excused. In most
minutes until 2020 the second row has the numbers of those who voted aye in
rising order (`1235X` under `32154`), and since 2021 in the order of the first
row; the letters stand under their supervisors' numbers either way.

The key gives the numbers and the letters. It does not say in so many words
that a letter belongs to the number above it. That is taken from the minutes
themselves, in two ways. The numbers left in a second row are always just
those of the first row with no letter under them, or the vote is not read.
And since 2025 some minutes also say the vote in words ("The motion passed
with 4 Ayes: Supervisors Márquez, Miley, Tam and President Haubert; 1 Excused:
Supervisor Fortunato Bas"): {n_agree} motions have a whole vote in the margin
and a whole vote in words, and the two say the same of every supervisor in
all of them; {n_differ} where they differed would not have been read.

A supervisor who stands aside is left out of the margin altogether (`3251`
over `3251`), and the minutes say beside it who it was ("Supervisor Miley
recused himself from discussing or voting on this item"). Such a vote is read
with that supervisor as `RECUSED`, and only if the words name exactly those
the margin leaves out.

Which number a letter stands under is a matter of where it is on the page. The
plain text of a PDF does not keep that (a lone `X` comes out on a line of its
own), so the rows are read from the place of each character.

## When a vote is not read

A vote is read whole or not at all. It is read from the margin only if

- the minutes have a key, the key gives each number a surname and says what
  A, X and N are, and every surname in it is a supervisor named at the head
  of those minutes, in the same order;
- the first row is those supervisors' numbers, none twice;
- there is a second row, each character of which stands under one number of
  the first, and is that number, another number, or a letter of the key;
- the numbers in the second row are just those of the first with no letter
  under them;
- and nobody in the key is missing from the first row, unless the words
  beside it say that supervisor stood aside.

A vote that does not pass puts no rows in `votes`: the motion is kept in
`agenda_items` with `votes_read` false and what stopped the reading in
`problem`. Of {n_blocks} votes printed in the minutes read, {n_blocks_read}
were read ({share_read}%) and {n_unread} were not. Votes run from
{first_vote} to {last_vote}. What is not read is mostly this:

- **One row and no second** ({n_lone}). The Clerk often printed only the
  first row, most of all in 2016 and 2017, and often beside items that were
  continued or withdrawn, where the row is `12345`. It may mean all five
  voted aye. The minutes do not say so, and it is not read.
- **Before 29 July 2014** the numbers are set in the type of the text and on
  its line, one row, with any letter in the line below. These are kept as one
  row and not read: nine regular meetings.
- **Minutes with no key.** Planning, special and budget meetings' minutes
  mostly have none before 2023, and {n_no_key} sets of minutes read have none
  or one that could not be used. Their margins are not read; a vote they say
  in words is.
- **A key that does not fit its minutes.** A few sets of minutes have a key
  that names a supervisor who is not at their head (minutes written up after
  the Board had changed, it seems), and in two of 2014 the key's lines cannot
  be told apart. The numbers in such minutes are not read.
- Second rows the Clerk typed over or set askew, with more characters than
  the first row has numbers or numbers that are not those of the first row.

To count by year:

```python
agenda = load_dataset("{repo}", "agenda_items", split="train").to_pandas()
agenda.groupby(agenda["date"].str[:4])[["vote_blocks", "blocks_read"]].sum()
```

## Tables

| Config | One row per | Rows |
|---|---|---|
| `default` (`items`) | item in the minutes | {n_items} |
| `meetings` | meeting listed | {n_meetings} |
| `agenda_items` | item in the minutes | {n_agenda_items} |
| `votes` | supervisor and motion voted on | {n_votes} |
| `members` | supervisor in a vote that was read | {n_members} |

The five tables, and the columns listed first in each, are the same in every
council and board dataset made this way, so two can be set one on the other:
[san-diego-council](https://huggingface.co/datasets/chrissoria/san-diego-council)
and
[sd-county-ordinances](https://huggingface.co/datasets/chrissoria/sd-county-ordinances)
are two. `meeting_id` joins `meetings` to the rest; `item_id` joins a vote to
the item it was taken on; `matter_id` joins `items` to both.

### items

The system has no record of an item apart from its place in the minutes, so
an item is here once for each meeting it came to, and its `matter_id` is its
`item_id` there.

| Column | |
|---|---|
| `date`, `agenda_date` | The day of the meeting. |
| `matter_id` | The meeting's number and the item's, `10484-27`. `matter_file` is empty. |
| `doc_type` | `ordinance` or `resolution` where the right margin gives a number for one (`O-2024-17`, `R-2026-496`), or failing that from the title; else `other`. |
| `title`, `body` | As the minutes have them. `status` is empty. |
| `subject`, `section` | The heading in capitals the item stands under (PUBLIC ASSISTANCE, HEALTH CARE SERVICES). |
| `year` | Of `date`. |
| `last_action`, `last_action_date` | What the minutes say was done with the item at this meeting. |
| `ayes`, `noes`, `mover`, `seconder` | Of the item's last vote. |
| `votes_read` | Whether every vote printed for the item was read. If not, `ayes` and `noes` may be 0 and mean nothing. |
| `mover_from` | `words` or `margin`: see below. |
| `result` | `Pass` or `Fail` only where the minutes say in words that the motion passed or failed; otherwise empty. `passed_date` is empty. |
| `times_on_agenda` | Always 1. |
| `url` | The minutes. |
| `number`, `notes` | The ordinance or resolution number, and everything the right margin has for the item (file, contract, resolution and ordinance numbers). |

### meetings

`meeting_id` (the number the County's system gives the meeting's recording),
`date`, `time` (as the minutes' head gives it, where they were read), `body`,
the meeting's page (`url`), its agenda and minutes (`agenda_url`,
`minutes_url`) and how many `items` its minutes have; then the meeting's
`name` and the heading it is listed under (`kind`), and what the reading
found: `minutes` (`read`, `no text layer`, `text not legible`,
`other document`, `not a PDF`, or empty where there are no minutes or they
have not been read), `pages`, `vote_blocks`, `blocks_read`, `key` (`read`, or
why the key could not be used), and `roll`, the supervisors of that day with
their districts and offices, as JSON. `location` is empty.

### agenda_items

| Column | |
|---|---|
| `item_id`, `meeting_id`, `date`, `body` | The item, and the meeting it was at. |
| `agenda_number`, `sequence` | Its number in the minutes and its place in the order. A matter voted on with no number of its own (the approval of the minutes, the regular calendar taken as one) has none, and its heading for `title`. |
| `matter_id`, `title` | The item. |
| `action` | What the minutes say the Board did: beside the item's last vote, or with no vote the last thing said. |
| `mover`, `seconder`, `mover_from` | Who moved and seconded, and where that is from. `words`: the minutes say it ("A motion was made by Supervisor Tam, seconded by Supervisor Miley"). `margin`: the first two numbers of the margin's first row. The key does not say that the first two are the mover and the seconder; where the minutes name the two in words as well, they are the same two in {n_order_same} motions and not in {n_order_differs}. |
| `ayes`, `noes`, `not_voting` | Counted from `votes`, for that vote. 0 where it was not read. |
| `votes_read` | True where every vote printed for the item was read, false where one was not, empty where the item has none. |
| `vote_blocks`, `blocks_read` | How many votes the minutes print for the item (in the margin or in words), and how many were read. |
| `problem` | Why a vote was not read. |
| `motions`, `motion_log` | How many passages the item has, and each as JSON: its words, the margin's rows as read (`32451/32X51`: the first row, a stroke, the second set under it, a dot where nothing stands under a number), mover and seconder, whether it has a vote, whether the vote was read, and from where. |
| `section` | The heading in capitals the item stands under. |
| `result` | As in `items`. |
| `doc_type`, `number`, `notes` | As in `items`. |

### votes

`member` and `vote`, for each motion whose vote was read, with the
supervisor's `district` (the number the key gives, which is the district):
`motion` numbers the passages of an item and `motion_text` is its words.
`source` is `margin`, `words`, `margin and words` where both gave the whole
vote and agreed, or `margin, recusal in words` where the margin left out a
supervisor the words say stood aside. A vote is `AYE`, `NO`, `ABSTAIN`,
`EXCUSED` or `RECUSED`. Every
motion here has one row for each supervisor on the Board that day: four
while a seat stood empty.

### members

One row for each supervisor in a vote that was read: `name`, and `first_vote`,
`last_vote` and `votes` counted from the votes here. `district` and `role`
are those of the newest minutes that list the supervisor. The minutes give no
terms of office, so `start` and `end` are empty; `serving` is true for those
at the head of the newest minutes read.

## What to know

- The consent calendar is voted on as one, as item 1, and each of its items
  is printed further down with the same rows in its margin. So a consent
  item has a vote of its own here, which is the calendar's.
- Rows are printed beside some items the minutes say were continued,
  withdrawn or only presented. Whether the Board voted on those the minutes
  do not say; the vote is here as printed, with `motion_text` beside it.
- `EXCUSED` is the key's word for a supervisor who was not there for the
  vote, whether away for the day or out of the room.
- A motion with `votes_read` false was voted on; the vote is in the minutes
  (`minutes_url`) and not here.
- A supervisor's name is the forename from the head of the minutes, where it
  is in capitals, and the surname as the key writes it. Minutes with no key
  have the name in capitals only, some without its accent; a name is spelled
  here the way most of the minutes spell it.
- An item begins where a line opens with a number higher than the last
  item's. A title or an action is the minutes' lines joined. `section` is the
  line in capitals at the left edge above the item: where a heading runs over
  two lines it is the second.
- Minutes are posted some weeks after their meeting; meetings of the last
  {recent_days} days are read again on each run.

## How it is made

[`build_alameda_board.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_alameda_board.py)
in cat-pol-datasets. The records are public records of the County of
Alameda; this compilation is released under CC0.
