---
license: cc0-1.0
language:
- en
pretty_name: Members of the U.S. Congress
tags:
- congress
- legislators
- politics
- government
configs:
- config_name: members
  default: true
  data_files:
  - split: train
    path: data/members.parquet
- config_name: terms
  data_files:
  - split: train
    path: data/terms.parquet
---

# Members of the U.S. Congress

Everyone who has served in the U.S. Congress since 1789: when they entered,
when they left, and the main facts about them. Two tables:

- **`members`**: one row per person (about 12,800), with the seat they hold or
  last held and their service added up.
- **`terms`**: one row per term served (about 45,500).

The two join on `bioguide_id`, the id the Biographical Directory of the United
States Congress gives each member. The same id is used by
[federal-bills-active](https://huggingface.co/datasets/chrissoria/federal-bills-active)
and [federal-committees](https://huggingface.co/datasets/chrissoria/federal-committees).

```python
from datasets import load_dataset
members = load_dataset("chrissoria/congress-members", "members", split="train").to_pandas()
terms = load_dataset("chrissoria/congress-members", "terms", split="train").to_pandas()
serving = members[members["status"] == "serving"]
```

## Where it comes from

- Names, birth dates, gender, terms, parties, websites, offices, phone numbers,
  leadership posts, social media accounts and the other ids come from
  [congress-legislators](https://github.com/unitedstates/congress-legislators),
  a public-domain (CC0) project that volunteers keep current from official
  records. This dataset reshapes it; it adds no facts of its own to those
  columns.
- **`race_ethnicity`** comes only from three lists published by the Office of
  the Historian of the U.S. House of Representatives, which cover both
  chambers:
  [Black Americans in Congress](https://history.house.gov/Exhibitions-and-Publications/BAIC/Historical-Data/Black-American-Representatives-and-Senators-by-Congress/),
  [Hispanic Americans in Congress](https://history.house.gov/Exhibitions-and-Publications/HAIC/Historical-Data/Hispanic-American-Representatives,-Senators,-Delegates,-and-Resident-Commissioners-by-Congress/)
  and
  [Asian and Pacific Islander Americans in Congress](https://history.house.gov/Exhibitions-and-Publications/APA/Historical-Data/By-Congress/).
  A person on a list gets its value ("Black", "Hispanic", "Asian or Pacific
  Islander"); a person on two gets both, separated by "; ".
  `race_ethnicity_source` names the list.

### Read this before using `race_ethnicity`

- **An empty value does not mean white.** It means the person is on none of
  the three lists. No comparable official list exists of white, Native
  American, or Middle Eastern or North African members, so those members are
  empty too. The column can answer "which members does the Historian list as
  Black, Hispanic, or Asian or Pacific Islander"; it cannot give the racial
  make-up of Congress.
- Nothing is inferred. No value comes from a name, a photograph, a district or
  a caucus membership.
- The lists are the Historian's judgment, in the Historian's categories. They
  are updated some time after a member is sworn in, so the newest members may
  be missing for a while.
- A listed person is joined to this table by the Historian's own id where the
  legislators file records it, and otherwise by surname, a given name, state,
  chamber and the Congresses served. A listed person who cannot be matched to
  exactly one member is left out.

## `members` columns

| Column | Description |
|---|---|
| `bioguide_id` | The member's id in the Biographical Directory. The key. |
| `name` | The name the member goes by officially, or first and last name. |
| `first_name`, `middle_name`, `last_name`, `suffix`, `nickname` | The parts of the name. |
| `birth_date` | YYYY-MM-DD. Missing for about 540 members, nearly all of whom entered before 1900. |
| `gender` | "M" or "F", as the source records it. |
| `race_ethnicity`, `race_ethnicity_source` | See above. Empty for most members. |
| `status` | "serving" or "former". |
| `position` | "Senator", "Representative", "Delegate" or "Resident Commissioner", for the seat held now or last. |
| `chamber` | "House" or "Senate", for that seat. |
| `state` | Two-letter code of the state or territory. |
| `district` | House district; 0 for a seat at large, -1 where the source does not know it. Empty for senators. |
| `party` | As the source writes it: "Democrat", "Republican", "Independent", and about sixty historical parties. |
| `caucus` | For an independent, the party they sit with. |
| `senate_class` | 1, 2 or 3: which third of the Senate the seat belongs to. |
| `state_rank` | "senior" or "junior", for a sitting senator. |
| `first_entered` | The start of the person's first term in either chamber. |
| `last_exit` | The end of the last term. Empty for someone now serving. |
| `exit_timing` | "end of a Congress" or "during a Congress". Empty for someone now serving. See the limits below. |
| `current_service_start` | For someone now serving, the start of their unbroken time in their present chamber. A gap of more than a month between terms breaks it. |
| `n_terms`, `house_terms`, `senate_terms` | Terms served, counting the present one and partial ones. |
| `days_served` | Days in office over all terms, up to the day the table was built. |
| `leadership_position` | A party or chamber leadership post held now, such as "Senate Majority Leader". |
| `leadership_history` | Every leadership post recorded, with its dates. The source covers 2003 onward. |
| `website`, `contact_form`, `phone`, `office_address` | For someone now serving only. |
| `twitter`, `facebook`, `instagram`, `youtube`, `youtube_id`, `mastodon` | Official accounts, for someone now serving only. |
| `govtrack_id`, `icpsr_id`, `lis_id`, `wikidata_id`, `wikipedia`, `opensecrets_id`, `fec_ids`, `house_history_id` | The person's ids elsewhere (ICPSR is the id Voteview uses; `fec_ids` is separated by ";"). |
| `updated` | The day the row was last built. |

## `terms` columns

| Column | Description |
|---|---|
| `bioguide_id`, `name` | The person. |
| `term_number` | 1 for the person's first term, in order of time. |
| `chamber`, `position` | As above, for this term. |
| `start`, `end` | The first and last day of the term. For a term under way, `end` is the day it is due to end. |
| `congress_first`, `congress_last` | The Congresses the term spans (a Senate term spans three). |
| `state`, `district`, `party`, `caucus`, `senate_class`, `state_rank` | As above, for this term. |
| `how` | "appointment" or "special-election" where the source records that the term began that way. It does so for about 210 Senate appointments since 1913 and a handful of special elections, so an empty value says nothing. |
| `days` | Days served in the term so far. |
| `serving` | True for the term a sitting member is serving now. |
| `url` | The member's official website during that term, where recorded (from about 2003). |

## Limits

- **Why someone left is not recorded.** Neither source says whether a member
  lost, retired, resigned, was expelled or died. `exit_timing` says only
  whether the last term ran to the end of a Congress.
- **Departure dates before about 1990 are often the scheduled end of the
  term.** For many earlier members, mostly in the House, the source gives the
  day the term was due to end even when the member died or resigned before
  then. A check against the death dates in Wikidata found about 870 former
  members whose recorded last day is later than their death, all but four of
  them leaving before 1990. For those years `last_exit`, `days_served` and
  `exit_timing` overstate service, and "end of a Congress" is not evidence
  that the member served to the end.
- Before 1935 the source dates most terms from the day Congress first met,
  usually in December, not from March 4 when the term began in law. `days` and
  `days_served` are counted from the source's dates, so they run about nine
  months short for each of those terms.
- A delegate from a territory that later became a state has the state's code
  in the source and appears as a "Representative". Delegates from the District
  of Columbia, American Samoa, Guam, the Northern Mariana Islands, the Virgin
  Islands, and the Dakota and Orleans territories, and the resident
  commissioners of Puerto Rico and the Philippines, are named as such.
- A member who changed party in the middle of a term has the later party on
  that term.
- Contact details, websites and social media accounts are kept only for
  sitting members. No email addresses are included, because members do not
  publish them; they are written to through `contact_form` or the website.

## Updates

`build_congress_members.py` in
[cat-pol-datasets](https://github.com/chrissoria/cat-pol-datasets) rebuilds
both tables weekly. It refuses to publish if the number of sitting members is
implausible or the table has shrunk, and it keeps the `race_ethnicity` values
already published when the Historian's pages cannot be read.

`world/members.json` in this repository holds a few of these fields, for people
who have served since the 113th Congress (2013), in the shape the member card
of [Capitol World](https://christophersoria.com/capitol-world/) reads.

## Licence and credit

CC0 1.0, the licence of the congress-legislators project. The House
Historian's lists are works of the U.S. government. If you use the data, please
credit both sources.
