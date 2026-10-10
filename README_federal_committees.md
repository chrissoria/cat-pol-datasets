---
license: cc0-1.0
language:
- en
pretty_name: Federal Committees (119th Congress)
tags:
- congress
- legislation
- politics
- government
configs:
- config_name: meetings
  default: true
  data_files:
  - split: train
    path: data/committee_meetings.parquet
- config_name: committees
  data_files:
  - split: train
    path: data/committees.parquet
- config_name: members
  data_files:
  - split: train
    path: data/committee_members.parquet
---

# Federal Committees

Committee-level data for the 119th U.S. Congress (2025–2026): every committee and
subcommittee, who sits on each, and every hearing, markup and business meeting
they have held or scheduled. Refreshed daily alongside
[chrissoria/federal-bills-active](https://huggingface.co/datasets/chrissoria/federal-bills-active).

```python
from datasets import load_dataset

meetings = load_dataset("chrissoria/federal-committees", "meetings", split="train")
committees = load_dataset("chrissoria/federal-committees", "committees", split="train")
members = load_dataset("chrissoria/federal-committees", "members", split="train")
```

The three tables join on `committee_code` (for example `hsif00`, House Energy
and Commerce; subcommittees end in a number other than `00`). Bills in
`meetings.bills` use the same ids as the bills dataset, built as
`{congress}-{type}-{number}` (for example `119-hr-5889`).

## meetings

One row per committee meeting, newest first.

| Column | Meaning |
|---|---|
| `event_id` | Congress.gov event number |
| `chamber` | House or Senate |
| `date` | Start time in UTC (ISO 8601). There is no end time in the source. |
| `meeting_type` | Hearing, Markup, Meeting, Open Business Meeting, Closed Hearing and so on, as published |
| `status` | Scheduled, Rescheduled, Postponed or Canceled. A past meeting stays "Scheduled"; the source does not mark meetings as held. |
| `title` | The meeting's subject |
| `committee_codes`, `committee_names` | JSON lists of the committees and subcommittees holding it |
| `building`, `room`, `city`, `state` | Where it was held. City and state are filled for field hearings. |
| `bills` | JSON list of bill ids on the agenda |
| `n_nominations`, `n_treaties` | How many nominations and treaties were on the agenda |
| `witnesses` | JSON list of `{name, position, organization}` |
| `documents` | JSON list of `{name, type, url}`: notices, bill texts, amendments. For markups the name often records the outcome and the vote. |
| `n_witness_documents` | Number of witness statements and biographies filed |
| `videos` | JSON list of video links |
| `has_transcript` | Whether a printed hearing transcript is linked |
| `update_date` | When Congress.gov last changed the record |
| `url` | The meeting's page on Congress.gov |

## committees

One row per committee and subcommittee.

| Column | Meaning |
|---|---|
| `committee_code` | System code used across Congress.gov |
| `name`, `chamber`, `committee_type` | As published (Standing, Select, Joint, Subcommittee and so on) |
| `parent_code`, `parent_name` | The full committee, for a subcommittee |
| `n_subcommittees`, `n_members` | Counts |
| `chair_bioguide_id`, `ranking_member_bioguide_id` | Bioguide ids of the chair and the ranking member |
| `update_date`, `url` | |

## members

One row per seat.

| Column | Meaning |
|---|---|
| `committee_code` | The committee or subcommittee |
| `bioguide_id`, `name` | The member |
| `side` | `majority` or `minority` |
| `rank` | Seniority on that side of the committee, 1 first |
| `title` | Chair, Ranking Member, Vice Chair, Ex Officio, or blank |

## Sources and limits

Meetings and the committee list come from the
[Congress.gov API](https://api.congress.gov/). Membership comes from the
public-domain [congress-legislators](https://github.com/unitedstates/congress-legislators)
project, because the API does not publish rosters; it reflects current
membership only, not who sat on a committee earlier in the Congress.

Detail varies by chamber and committee. House meetings usually list witnesses
and documents; many Senate meetings carry only a title, time and room. Closed
meetings have little beyond their title. Meeting records are as the committees
filed them and are not corrected here.

The collection code is in
[cat-pol-datasets](https://github.com/chrissoria/cat-pol-datasets)
(`build_committees.py`). Not affiliated with Congress.
