---
license: cc-by-nc-4.0
language:
- en
pretty_name: U.S. Supreme Court Cases, 1946 to the present
tags:
- supreme-court
- law
- courts
- politics
- government
configs:
- config_name: cases
  default: true
  data_files:
  - split: train
    path: data/cases.parquet
- config_name: votes
  data_files:
  - split: train
    path: data/votes.parquet
- config_name: justices
  data_files:
  - split: train
    path: data/justices.parquet
- config_name: applications
  data_files:
  - split: train
    path: data/applications.parquet
- config_name: docket_entries
  data_files:
  - split: train
    path: data/docket_entries.parquet
- config_name: terms
  data_files:
  - split: train
    path: data/terms.parquet
---

# U.S. Supreme Court Cases, 1946 to the present

Every case the Supreme Court has decided since its 1946 term, the cases it is
hearing now, how each justice voted, and the emergency applications put to the
Court since 2017. Refreshed daily.

```python
from datasets import load_dataset

cases = load_dataset("chrissoria/supreme-court-cases", "cases", split="train")
votes = load_dataset("chrissoria/supreme-court-cases", "votes", split="train")
justices = load_dataset("chrissoria/supreme-court-cases", "justices", split="train")
applications = load_dataset("chrissoria/supreme-court-cases", "applications", split="train")
docket_entries = load_dataset("chrissoria/supreme-court-cases", "docket_entries", split="train")
terms = load_dataset("chrissoria/supreme-court-cases", "terms", split="train")
```

## Where it comes from, and the licence

This dataset joins four sources. Two of them allow non-commercial use only, so
the dataset as a whole is offered under
[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/): use it, share
it and build on it for non-commercial purposes, and credit the sources below.

- **[The Supreme Court Database](http://scdb.wustl.edu/)** (Washington
  University Law): every decided case from the 1946 term through the last
  finished one, coded by hand. Rows with `source` = `scdb` and the columns
  described as "the database's coding" come from it.
  Licence: [CC BY-NC 3.0 US](https://creativecommons.org/licenses/by-nc/3.0/us/).
  Please cite it as its authors ask: Harold J. Spaeth, Lee Epstein, Andrew D.
  Martin, Jeffrey A. Segal, Theodore J. Ruger, and Sara C. Benesh, *Supreme
  Court Database*, Version 2026 Release 01, http://supremecourtdatabase.org.
- **[Oyez](https://www.oyez.org/)** (Cornell's Legal Information Institute,
  Justia and Chicago-Kent College of Law): the question each case asks, a
  one-line account of the holding, the dates a case was granted, argued and
  decided, and, for the term in progress, the cases themselves and the votes.
  Licence: [CC BY-NC 4.0](https://www.oyez.org/license).
- **[The Supreme Court's docket](https://www.supremecourt.gov/docket/docket.aspx)**:
  the dated filings and orders of each case and application, from the 2017
  term on. A work of the U.S. government.
- **[The Federal Judicial Center's Biographical Directory of Article III
  Federal Judges](https://www.fjc.gov/history/judges)**: the justices. In the
  public domain.

## How it is kept current

The database is published about once a year, after a term ends, so it always
stops at the last finished term. The term in progress comes from Oyez (which
cases, and how they were decided) and from the Court's docket (how far each has
come). When the database publishes a new release, that term's rows are replaced
by the database's, and `source` changes from `oyez` to `scdb`.

## `cases`

One row per case. A case decided in two parts in the same term has two rows,
the second with `-b` at the end of its `id`.

| Column | Description |
|---|---|
| `id` | Term and docket number, as in `2025-24-1287`. |
| `term` | The term the case was decided in, or is being heard in. A term opens in October and is named for that year. |
| `docket` | The docket number as the source writes it. |
| `name` | The case's name. |
| `stage` | `decided`, or for a pending case `granted`, `set for argument` or `argued`. |
| `date_granted`, `date_argued`, `date_decided` | YYYY-MM-DD; empty where unknown or not yet reached. `date_granted` comes from Oyez or the docket and is missing for many older cases. |
| `citation` | The U.S. Reports citation, or the Supreme Court Reporter's until that volume is published. |
| `decision_type` | The form the decision took, such as "opinion of the Court" or "per curiam, without oral argument". |
| `disposition` | What the Court did with the judgment below: affirmed, reversed, vacated and remanded, and so on. |
| `winner` | `petitioner`, `respondent` or `unclear`. |
| `majority_votes`, `minority_votes` | The vote. |
| `majority_author` | `justice_id` of the justice who wrote the Court's opinion; empty for an unsigned one. |
| `issue_area`, `issue` | The database's coding of what the case is about, broad and narrow. |
| `law_type`, `law` | The database's coding of the kind of law at issue and the provision. |
| `declared_unconstitutional` | `federal law`, `state law` or `local law` if the Court struck one down; otherwise empty. |
| `precedent_altered` | True if the Court formally altered one of its own precedents. |
| `lower_court` | The court whose decision was under review. |
| `jurisdiction` | How the case reached the Court (certiorari, appeal, original, …). |
| `chief_justice` | The Chief Justice at the time. |
| `scdb_direction` | The database's coding of the outcome as `liberal`, `conservative` or `unspecifiable`. It is the coders' judgment under the database's written rules, not a fact about the case. |
| `question` | The question presented, from Oyez. Present for nearly every case since the 1990s and for the better-known earlier ones. |
| `description` | One sentence on what the Court held (or will decide), from Oyez. Mostly cases since about 2010. |
| `executive_orders` | A JSON list of executive order numbers named in the question or description: a link to [chrissoria/executive-orders](https://huggingface.co/datasets/chrissoria/executive-orders). Found by reading the text, so it misses orders the text does not name by number. |
| `oyez_url`, `justia_url`, `docket_url` | Links. `docket_url` is the Court's own docket page, for cases from the 2017 term on. |
| `scdb_id` | The database's own case id, for joining to its other files. |
| `source` | `scdb` or `oyez`: where the row comes from. |

For rows with `source` = `oyez` the database's columns (`disposition`,
`issue_area`, `law`, `scdb_direction` and the like) are empty until the
database covers that term.

## `votes`

One row per case and justice.

| Column | Description |
|---|---|
| `case_id` | `id` in `cases`. |
| `term` | The term. |
| `justice_id` | `justice_id` in `justices`. |
| `side` | `majority` or `dissent`. Empty where the Court divided equally or the vote could not be determined. |
| `vote` | The vote in more detail: majority, dissent, regular concurrence (joined the opinion and wrote separately), special concurrence (agreed with the result only), and so on. |
| `wrote_opinion` | True if the justice wrote or co-wrote an opinion in the case. |
| `scdb_direction` | The database's coding of the justice's vote as `liberal` or `conservative`. The same caution applies as for the case. |
| `source` | `scdb` or `oyez`. |

## `justices`

One row per appointment to the Court since 1789. A justice later made Chief
Justice has two rows with the same `justice_id`.

| Column | Description |
|---|---|
| `justice_id` | For anyone who has sat since 1946, the Supreme Court Database's name for them (`JGRoberts`, `SDOConnor`, `JHarlan2`); for earlier justices, initials and surname in the same style. |
| `name`, `last_name` | The justice's name. |
| `title` | Associate Justice or Chief Justice. |
| `appointed_by`, `appointing_party` | The president who made the appointment, and that president's party. |
| `nominated`, `confirmed` | Dates (YYYY-MM-DD). |
| `senate_vote` | The confirmation vote as ayes/nays, where there was a roll call. |
| `start`, `end` | The commission date, and the day service ended; `end` is empty for a sitting justice. A justice who retired is counted as leaving on the day they took senior status. |
| `how_ended` | Death, retirement, resignation, or appointment to another position. |
| `serving` | True for the nine sitting justices. |
| `born`, `died` | Years. |
| `gender`, `race_ethnicity` | As recorded by the Federal Judicial Center. |
| `in_database` | True if the justice has votes in `votes`. |

## `applications`

One row per application since the 2017 term: the requests, numbered like
`25A400`, that go first to a single justice. Most are routine requests for more
time to file. The others, for stays and injunctions, are what is often called
the emergency docket.

| Column | Description |
|---|---|
| `docket` | The application's number. |
| `term` | The term it was filed in. |
| `title`, `applicant`, `respondent` | Who asked, and against whom. |
| `kind` | What was asked for, read from the first docket entry: `extension of time`, `stay`, `stay of execution`, `injunction`, `vacate`, `bail`, `certificate of appealability`, `word or page limit`, or `other`. |
| `capital_case` | True if the Court marks the case as a capital one. |
| `date_filed` | The date of the first docket entry. |
| `submitted_to` | The justice it went to. |
| `referred_to_court` | True if that justice referred it to the full Court. |
| `outcome` | `granted`, `granted in part`, `denied`, `dismissed`, `withdrawn`, or `closed` (the docket ends with no ruling, usually because events overtook the request); empty while pending, or where the docket's wording was not recognised. |
| `decided_by` | The justice who ruled, or `the Court`. |
| `date_resolved` | The date of that ruling. |
| `lower_court`, `lower_court_case` | Where it came from. |
| `linked` | Other docket numbers the Court links it to, usually the petition that followed. |
| `executive_orders` | A JSON list of executive order numbers named in its docket entries. |
| `n_entries`, `last_entry_date` | The size and latest date of its docket. |
| `url` | The Court's docket page. |

`kind` and `outcome` are read from the docket's wording by fixed rules that
prefer leaving a field empty to guessing.

## `docket_entries`

One row per line of a docket, for cases from the 2017 term on and for every
application.

| Column | Description |
|---|---|
| `docket` | The docket number; for a case, the file name the Court uses (an original action such as No. 141, Orig. is `22O141`). |
| `kind` | `case` or `application`. A docket numbered with an A is an application's even in the few instances where the Court went on to hear argument on it. |
| `seq` | The line's place in the docket, from 0. |
| `date` | YYYY-MM-DD. |
| `text` | The entry. |

## `terms`

One row per term from 1946.

| Column | Description |
|---|---|
| `term` | The term. |
| `chief_justice` | The Chief Justice. |
| `cases`, `cases_decided` | Rows in `cases` for the term, and how many are decided. |
| `applications` | Applications filed that term. Empty before 2017. |
| `paid_petitions`, `ifp_petitions` | Petitions docketed with the filing fee paid, and by people excused from it (*in forma pauperis*), taken from the highest docket number in use. Empty before 2017. For the current term the count is of petitions so far. |

## Things to know

- **Cases decided without argument** are in the database only when the Court
  wrote an opinion. The thousands of petitions it turns down each term are not
  in `cases`; `terms` counts them.
- **The database's codes are judgments.** Its documentation
  ([online codebook](http://scdb.wustl.edu/documentation.php)) says how each was
  made. `scdb_direction` in particular should be read with that in hand.
- **Names of justices** differ between sources; they are matched by surname and
  first name among the justices sitting at the time.
- **Docket files exist from the 2017 term.** Earlier cases have no docket
  entries, and there are no applications before then.
- **A case's `term`** is the one it was decided in. Oyez sometimes files a case
  under the term it was argued in, so `oyez_url` may show the year before.

Built by [`build_supreme_court.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_supreme_court.py).
