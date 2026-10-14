---
license: cc0-1.0
language:
- en
pretty_name: US Places
tags:
- government
- local-government
- geography
- census
- flags
- boundaries
- geoparquet
configs:
- config_name: default
  data_files:
  - split: train
    path: data/places.parquet
- config_name: bodies
  data_files:
  - split: train
    path: data/bodies.parquet
- config_name: boundaries
  data_files:
  - split: train
    path: data/boundaries.parquet
- config_name: datasets
  data_files:
  - split: train
    path: data/datasets.parquet
- config_name: ages
  data_files:
  - split: train
    path: data/ages.parquet
---

# US Places

One row for the country and for each state, territory, county, city, named
unincorporated community and legislative district, with what is known of it
as a whole: what it is part
of, how many people live there and how old they are, how big, dense and urban
it is, how rich and how unequal, where its flag and seal can be seen, which
body governs it, and how much of its lawmaking is in the other datasets
published here.

It is meant as the one place to read what a place is from. Every table has the
same key, `place_id`, the Census Bureau's code.

**42,475 places:** the United States, the 50 states, the District of Columbia
and five territories, 3,144 counties, 19,478 incorporated cities, towns,
villages and boroughs, 12,528 unincorporated communities, and 7,268
districts: 437 of Congress, 1,958 of the states' upper houses and 4,873 of
their lower houses. The states are
the fullest rows; what each level has is in the table under "What each level
has".

The `boundaries` table has the outline of every one of them, and `maps/` has
each state and each county drawn from those outlines as a grid of squares.

## Tables

### places (the default)

| Column | |
|---|---|
| `place_id` | The Census Bureau's code: two digits for a state (`06`), five for a county (`06073`), seven for a city (`0666000`). The country is `00`. A district has the Bureau's full code, which says whose lines it is drawn on: `5001900US0652` is California's 52nd as drawn for the 119th Congress. |
| `kind` | `nation`, `state`, `district` (the District of Columbia), `territory`, `county`, `city`, or `community`: settled land in no city, which the Census Bureau names and draws a line round (a "census designated place"). It has no government but the county's. A district is a `congressional district`, a `state senate district` or a `state house district` (the lower house, whatever the state calls it). |
| `parent_id` | The place it is part of: a city's or community's county, a county's state, a state's country. A city in several counties is given the one most of its people live in. A district's is its state. |
| `district`, `district_session` | For a district, its number or name alone (`52`, `At Large`, `4th Middlesex`), and what its lines were drawn for: `119th Congress`, or `2024 legislative session`. |
| `body_id` | For a district, the body it elects a member to, if that body is in `bodies`. |
| `representative`, `representative_party`, `representative_id`, `representative_since` | For a congressional district, who sits for it now: their name, party, Biographical Directory id, and the day their unbroken service began. Empty for a vacant seat. |
| `senators` | For a state, its senators now, as a list: each one's `id`, `name`, `party` and `since`. |
| `name`, `census_name` | The name people use (`San Diego`) and the Bureau's (`San Diego city`). |
| `government` | For a city, what the Bureau's name calls it: `city`, `town`, `village`, `borough`. |
| `state`, `state_name` | Postal code and name. |
| `county_id`, `county_name` | For a city, the county most of its people live in. |
| `counties` | For a city in more than one county, all of them, the most populous part first. |
| `population`, `population_year` | The Bureau's latest estimate, and its year. The country's is that of the states and the District, without the territories. A community's and a district's are the American Community Survey's count over the five years ending in `population_year`. |
| `population_2020` | The 2020 census count, as the estimates take it for their base. |
| `land_sq_mi`, `water_sq_mi`, `latitude`, `longitude` | From the Bureau's gazetteer; the point is one inside the place. A state's areas are its counties' added up. |
| `seat` | A county's seat, or a state's or territory's capital. |
| `joined_union`, `union_order` | For a state, the year it joined the Union and its place in the order of joining. |
| `density_per_sq_mi` | People to a square mile of land. |
| `water_share` | The share of its area that is water. |
| `urban_population_share` | The share of its people the 2020 census counted as living in urban areas. |
| `rural_urban_code`, `rural_urban_label` | For a county, the Department of Agriculture's 2023 code from 1 (in a metropolitan area of a million or more) to 9 (rural, and not beside one), with its meaning. For a state, the average of its counties' codes, each weighed by its people. |
| `age_under_1` … `age_80_plus` | The share of people of each age: under 1, 1 to 4, 5 to 12, 13 to 17, 18 to 24, 25 to 34, 35 to 44, 45 to 54, 55 to 64, 65 to 74, 75 to 79, and 80 or more. `age_year` is the year. Below the state, the four bands under 18 are empty: the survey does not count them apart. |
| `age_under_18` | The share under 18, which every level has. |
| `white_share`, `black_share`, `asian_share`, `hispanic_share`, `other_race_share` | The share of people in each of five groups that add to the whole: Hispanic or Latino people of any race, and everyone else by race (White, Black, Asian, and other: American Indian or Alaska Native, Native Hawaiian or Pacific Islander, some other race, and two or more races). From the American Community Survey's table B03002, pooled over `race_years`. |
| `median_household_income`, `gini_index`, `median_home_value` | From the American Community Survey, pooled over `income_years`. The Gini index runs from 0 (everyone has the same income) to 1 (one household has it all). Home value is what owners say their homes are worth, not sale prices. |
| `gdp_per_capita`, `gdp_year` | Gross domestic product in the dollars of that year, divided by the people there that year. |
| `violent_crime_rate`, `property_crime_rate`, `homicide_rate` | Offences known to the police for each 100,000 people, in `crime_year`. |
| `vote_republican_2024`, `vote_democrat_2024`, `vote_independent_2024`, `vote_libertarian_2024`, `vote_green_2024`, `vote_other_2024` | The share of the votes for president in 2024 that went to each party's nominee: Trump, Harris, Oliver and Stein, on whatever line of the ballot. "Independent" is Robert F. Kennedy Jr. and Cornel West together, who ran without a party's nomination. The six add up to 1. The year is in the name, and a later election will add columns of its own. |
| `votes_cast_2024` | Every vote cast for anyone for president. Ballots that chose no one are left out. |
| `flag_url`, `seal_url` | The flag and seal as files on Wikimedia Commons. The address leads to the image. |
| `website` | The official site. |
| `wikidata` | The place's item on Wikidata, where the four columns above come from. |
| `n_records` | Ordinances, resolutions and other items on record for it in the datasets here. |
| `n_ordinances`, `n_resolutions` | Of those, how many are each. |
| `n_bills` | For a state, measures of its legislature on record. |
| `n_meetings`, `n_votes` | Meetings of its governing body on record, and members' votes. |
| `records_from`, `records_to` | The earliest and latest dates among them. |
| `datasets` | The datasets that hold them. |
| `world_url` | Its page in [Capitol World](https://christophersoria.com/capitol-world/), if it has one. |

A place with no records here has nothing in the last nine columns. That says
nothing has been collected, not that the place has passed nothing.

### What each level has

| | State | County | City | Community | District |
|---|---|---|---|---|---|
| People, area, density, water share | yes | yes | yes | yes | yes |
| Income, inequality, home value | yes | yes | most | most | yes |
| Urban share, rural-urban code | yes | yes | no | no | no |
| GDP for each person | yes | yes | no | no | no |
| Age bands from 18 up, and under 18 as one | yes | yes | most | most | yes |
| Age bands under 18 | yes | no | no | no | no |
| Who sits for it in Congress | senators | no | no | no | representative |
| Crime | yes | no | no | no | no |
| Vote for president | yes | no | no | no | no |
| Flag, seal, site | yes | some | some | no | no |

### bodies

One row per body that makes law for a place and has records here: Congress, a
state's legislature, a county's board, a city's council.

| Column | |
|---|---|
| `body_id` | A short name of its own: `sd-council`. |
| `place_id`, `place`, `place_kind`, `state` | The place it governs. |
| `name`, `body`, `short` | "San Diego City Council", "City Council", "the Council". |
| `room`, `member_title`, `seat_title` | Where it meets, what a member is called, and what a seat is called: "Council Chambers", "Councilmember", "District". |
| `timezone` | The time zone its meeting times are in. |
| `site`, `site_url` | Its own site, and what to call it. |
| `since` | How far back the record of its meetings goes, in words. |
| `datasets` | The datasets with its records. |
| `world`, `world_url` | Its room in [Capitol World](https://christophersoria.com/capitol-world/), if it has one. |
| `chamber_file` | For a board or council with a room, the file the room is drawn from. |
| `map` | Where its place is on Capitol World's map of the country. |

`world/bodies.json` in this repository is the same list as a file, which
Capitol World reads to know which places have a room.

### boundaries

One row per place, with its outline. Every state, territory, county, city,
community and district in `places` has one; the country does not.

| Column | |
|---|---|
| `place_id`, `kind` | As in `places`. |
| `geometry` | The outline as well-known binary: a polygon, or a multipolygon for a place of several pieces. Longitude and latitude, in the North American Datum of 1983. The file is GeoParquet, so GeoPandas, DuckDB and QGIS read the column as shapes. |
| `west`, `south`, `east`, `north` | The box round it. |
| `middle_longitude`, `middle_latitude` | The middle of its area. For a place of an odd shape this can lie outside it. |
| `pieces`, `points` | How many separate pieces it has, and how many points its outline. |

The outlines are the Census Bureau's cartographic boundary files at
1:500,000: simplified for drawing, and cut back to the shoreline. They are
not survey lines, and should not be used to say which side of a street is in
a city.

### maps

Not a table: files made from `boundaries` and `places`, which
[Capitol World](https://christophersoria.com/capitol-world/) draws its maps
from. Each is a grid of squares 150 along its longer side, written as runs
along its rows (which shape, then how many squares).

- `maps/states/CA.json`: a state, each square one of its counties. `ids` and
  `names` list the counties in the order the grid numbers them from 1; 0 is
  outside the state. `capital` is where the capitol stands, in squares.
- `maps/congress/CA.json`: the state again on the same grid as its county
  map, each square one of its congressional districts. `short` is each
  district's number, and `people`, `income` and `home` its population,
  median household income and median home value.
- `maps/counties/CA.json.gz`: every county of a state, by its code. In each,
  a square is a city, a named community, or the land in neither, which comes
  last as `<county>-u`. `kinds` says which each is, and `seat` where the
  county's government sits.

### index

Not a table either: the same rows as `places`, cut up small for Capitol World
to read. `index/US.json` has the country, the states and the territories;
`index/CA.json.gz` has every county, city, community and congressional
district of one state. Each lists its `columns` once and then each place's
values in that order, by `place_id`.

### ages

For the country and each state, people by single year of age (0 to 84, and 85 for 85 and
over), so that other age bands can be made than the twelve above.

### datasets

One row per body and dataset that has records of it: the dataset, what its
rows are, and the same counts and dates for that dataset alone.

## Where it comes from

- **People and counties:** the Census Bureau's Population Estimates, vintage
  2024. The island territories' are from their 2020 census. A community's people are the American Community Survey's count for
  2020 to 2024, since the estimates do not cover it.
- **Ages:** the same estimates, by single year of age, which the Bureau makes
  for states. Below the state, the American Community Survey's table B01001
  for 2020 to 2024.
- **Members of Congress:** the
  [congress-members](https://huggingface.co/datasets/chrissoria/congress-members)
  dataset, as it stood when this was built.
- **Area and position:** the Census Bureau's 2024 gazetteer files.
- **Income, inequality and home value:** American Community Survey, five-year
  tables B19013, B19083 and B25077 for 2020 to 2024.
- **Urban share:** the 2020 census's urban and rural counts.
- **Rural-urban code:** the Economic Research Service's 2023 Rural-Urban
  Continuum Codes.
- **GDP:** the Bureau of Economic Analysis's tables SAGDP1 and CAGDP1.
- **Crime:** the FBI's estimated crimes by state, from its Crime Data
  Explorer.
- **Districts:** the Census Bureau's 2024 gazetteer files for the districts
  of the 119th Congress and of each legislature's 2024 session, and the
  American Community Survey for 2020 to 2024, which counts people on those
  same lines.
- **Outlines:** the Census Bureau's 2024 cartographic boundary files for
  states, counties, places and districts.
- **Vote for president:** the MIT Election Data and Science Lab's
  [U.S. President 1976–2024](https://doi.org/10.7910/DVN/42MVDX), which is
  each state's certified returns. The country's is the states' and the
  District's added up.
- **Flags, seals, sites and county seats:** Wikidata, matched by the Census
  code. Where Wikidata has several, the first is kept.
- **Bodies:** listed by hand in
  [`bodies.json`](https://github.com/chrissoria/cat-pol-datasets/blob/main/bodies.json).
- **Records:** counted from the datasets named in `datasets`.

## What to know

- A district is a set of lines, and lines are redrawn. A row is the district
  as drawn for the Congress or session in `district_session`, and every
  figure on it is for those lines. When a state redraws, the new district is
  a new row under a new code, even if it keeps the number.
- The delegate districts of the four island territories are not here; each
  is the whole territory. The District of Columbia's eight wards are listed
  as its "state senate districts", as the Bureau lists them. Nebraska has one
  house, so no lower-house districts.
- A legislature's districts have their outlines and figures but are not
  drawn in `maps/`, and their rows do not say who sits for them.
- The vote for president is not known by district. The House's own returns
  by district are published by the MIT lab but not read here yet.
- A territory is one row. Its municipalities, districts and villages are not
  here yet. Puerto Rico has a yearly estimate and the survey's figures; the
  four island territories have their 2020 census count and little else.
- Where a city and its county have merged (Nashville, Indianapolis,
  Louisville), the city here is the part in no smaller city, which the Bureau
  calls the "balance".
- Cities are the Census Bureau's incorporated places. The towns of New York
  and New England and the townships of Pennsylvania and the Midwest are
  governments too, but the Bureau counts them as divisions of a county, and
  they are not here yet.
- Most places have no flag on record: about 1,000 have one and about 950 a
  seal. That is what Wikidata holds, not a count of the flags that exist. New
  York City is among those with none recorded against its code.
- There is no measure of green space yet. Water share is here because the
  Census Bureau measures it; tree cover and parkland need a land-cover map
  laid over each place's outline.
- The survey's figures for a small place rest on few households and can be far
  off. The Bureau publishes a margin of error with each, which is not kept
  here.
- GDP is missing for the cities of Virginia that the Bureau of Economic
  Analysis combines with a neighbouring county, and the urban share for
  Connecticut's planning regions, which replaced its counties after 2020.
- Crime is the FBI's estimate for the state. A state's figure can be compared
  with its own in other years more safely than with another state's.
- The vote for president is by state only. The same lab publishes it by
  county; that file is not read here yet. No one publishes it by city: it
  would have to be added up from precincts.
- A party's share is its nominee's. A state where the nominee was not on the
  ballot shows the write-in votes for them, if the state reported those, and
  otherwise nothing: the Green share is 0 in a few states for that reason.
- Flag and seal images are other people's files. Check the file's page on
  Wikimedia Commons for its licence before using one.
- The counts say what has been collected, and collections differ. One city's
  dataset goes back to 1905 and another's covers five years.

## How it is made

[`build_places.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_places.py)
and, for the outlines and maps,
[`build_boundaries.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_boundaries.py)
in cat-pol-datasets. The Census Bureau's figures are in the public domain and
Wikidata's are CC0; this compilation is released under CC0.
