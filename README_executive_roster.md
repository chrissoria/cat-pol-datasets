# U.S. Executive Branch Roster

Who holds the senior posts of the sitting administration: the cabinet, the
cabinet-level officials, and the senior White House staff. One row per person
and post, including people who held a post earlier in the term.

## Where it comes from

Two sources, told apart by the `source` column.

- **Cabinet and cabinet-level posts** come from the Senate's record of
  nominations, through the [Congress.gov API](https://api.congress.gov/). That
  is the official record of who was confirmed to which post, on what day and by
  what vote. The latest person confirmed to a post is listed as serving; anyone
  confirmed to it earlier in the term is listed as a former holder.
- **Senior White House posts** (chief of staff, counselors, advisers) are not
  confirmed by the Senate, so they come from
  [Wikidata](https://www.wikidata.org/), which is edited by volunteers. Only a
  fixed list of posts is read, only for real people who are U.S. citizens, and
  only where a start date within the current presidency is recorded. Treat
  these rows as less authoritative, and expect some posts to be missing.

## Columns

| Column | Description |
|---|---|
| `name` | The person, as the source writes the name. |
| `position` | The post. |
| `group` | "Cabinet", "Cabinet-level" or "White House". |
| `department_code` | For a cabinet secretary, a short code for the department (`state`, `treasury`, `defense`, `justice`, …). |
| `organization` | The department or office, as the Senate record names it. |
| `status` | "serving", "former" (replaced by someone confirmed later) or "nominated" (not yet confirmed). |
| `start_date` | The day the Senate confirmed the person, or the start date Wikidata records. |
| `end_date` | For a former holder, the day the successor was confirmed. The person may have left earlier. |
| `confirmation_vote` | Yeas and nays, such as "52-48", or "voice vote". |
| `nomination` | The nomination's number in the Senate, such as PN11-8. |
| `nomination_url` | Its page on Congress.gov. |
| `source` | "Congress.gov nominations" or "Wikidata". |
| `wikidata_id` | The person's Wikidata id, for rows from Wikidata. |
| `term_start` | The inauguration day that began the presidential term covered. |
| `updated` | The day the row was last built. |

## Things to know

- Neither source records an **acting** official. A post whose holder has left
  shows the last confirmed person until a successor is confirmed.
- A resignation or dismissal appears only when a successor is confirmed, so
  `end_date` is the latest the person can have left, not the day they did.
- Someone can hold two posts and so appear twice.
- The White House list is a best effort and is not complete.

## Updates

`build_executive_roster.py` in
[cat-pol-datasets](https://github.com/chrissoria/cat-pol-datasets) runs weekly.
`world/roster.json` in this repository is the same list in the shape the
[Capitol World](https://christophersoria.com/capitol-world/?world=whitehouse)
map reads.
