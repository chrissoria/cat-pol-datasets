# Nice to do

Things worth doing some day that nothing depends on. Each entry says where it
stands and what the first step would be. Move an entry out of this file when
work on it starts.

## Fill in `race_ethnicity` in `congress-members`

**Where it stands (2026-10-10).** The column is kept. It has a value for 433 of
12,770 members, all from the House Historian's three lists (Black, Hispanic,
Asian or Pacific Islander). An empty value means "on none of those lists", not
"white". See `README_congress_members.md`.

**What a backfill would add, in order of how sure the sources are.**

1. **Listed people who were not matched.** A person on a Historian list is left
   out when they cannot be joined to exactly one member. Count them from the
   build log, then match the leftovers by hand in a small corrections file.
   No new source needed.
2. **The newest members.** The Historian's lists lag a new Congress. The
   Congressional Research Service's "Membership of the nth Congress: A Profile"
   names members by group for the current Congress; use it for members sworn in
   since the lists were last updated.
3. **Native American members.** No Historian list exists. Candidates: the
   Senate's "Ethnic Diversity in the Senate" page for senators, and the CRS
   profiles for recent Congresses of both chambers. Earlier House members would
   need another source.
4. **Everyone else.** No official source says who is white, or Middle Eastern or
   North African. Two ways to go, and they can coexist:
   - a column saying whether the lists cover the member's years at all, so that
     "not listed" can be told apart from "not looked at";
   - a second column taken from a research dataset that codes every member
     (the Center for Effective Lawmaking's files have indicators for Black and
     Latino members from the 93rd Congress on), kept apart from
     `race_ethnicity` and named for its source.

**Rules to keep.** Nothing is inferred from a name, a photograph, a district or
a caucus. Every value names its source in `race_ethnicity_source`. A derived
"white" is never written into `race_ethnicity`.

**First step.** Check each candidate source above: that it names people (not
just counts), which Congresses it covers, and whether its terms allow
republishing under CC0. The sources in items 2 to 4 are from memory and have
not been checked.

## Deliver messages to Congress from Capitol World

**Where it stands (2026-10-10).** The app opens a member's contact form or
website and sends nothing itself. Real delivery means becoming an approved
vendor of the House's Communicating with Congress system (and the Senate's
equivalent, applied for at soapbox.senate.gov). Neither charges a fee. An
email asking the House whether an individual's non-commercial site qualifies
was drafted on 2026-10-10 and had not been sent when this was written.

**What it would take.**

- Approval from the House (a six-page application emailed to
  CWCVendors@mail.house.gov) and, separately, the Senate, whose program is
  described as for high-volume senders.
- A small server to hold the vendor key and send messages; the app is a static
  page today.
- Handling visitors' names, home addresses, phone numbers and messages, with a
  privacy policy.
- Matching each address to a district (the Census Bureau's geocoder is free).
- Answering the House within 72 hours and the Senate within 24, and an
  emergency call from either within two hours.

**What changes for visitors.** They could write only to their own
Representative and two senators, not to whichever member they clicked.

**First step.** Send the email and wait for the House's answer.

## Everyone who ever sat on a local body

Asked for on 2026-10-10, as a nice thing to have for the county and city
worlds. The roster in a local world is the members serving now. A dataset of
everyone who has ever sat on a board or council, with the dates each was
elected and left, would let a roster and its statistics go back in time.

What the sources have: Legistar lists a body's members only since the body
began using it (June 2017 for the San Diego County Board of Supervisors), with
start and end dates but no district. Earlier members would have to come from
somewhere else: the body's own history pages, election results from the
Registrar of Voters, or Wikipedia's lists, none of which has been checked.

First step when this is picked up: one body, San Diego County, back to 1970
or so by hand, to find out what a row needs (seat or district, how the seat
was won, why it was left) before trying to do it for many.
