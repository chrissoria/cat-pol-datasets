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
configs:
- config_name: default
  data_files:
  - split: train
    path: data/places.parquet
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

One row for each state, county, city and named unincorporated community, with
what is known of it as a whole: how many people live there and how old they
are, how big, dense and urban it is, how rich and how unequal, where its flag
and seal can be seen, and how much of its lawmaking is in the other datasets
published here.

It is the table a map of the country can be drawn from before any one place
has been looked at closely. It says which places exist, which have a flag, and
which already have records.

**35,190 places:** the 50 states and the District of Columbia, their 3,144
counties, 19,467 incorporated cities, towns, villages and boroughs, and
12,528 unincorporated communities. The states are the fullest rows; what each
level has is in the table under "What each level has".

## Tables

### places (the default)

| Column | |
|---|---|
| `place_id` | The Census Bureau's code: two digits for a state (`06`), five for a county (`06073`), seven for a city (`0666000`). |
| `kind` | `state`, `county`, `city`, or `community`: settled land in no city, which the Census Bureau names and draws a line round (a "census designated place"). It has no government but the county's. |
| `name`, `census_name` | The name people use (`San Diego`) and the Bureau's (`San Diego city`). |
| `government` | For a city, what the Bureau's name calls it: `city`, `town`, `village`, `borough`. |
| `state`, `state_name` | Postal code and name. |
| `county_id`, `county_name` | For a city, the county most of its people live in. |
| `counties` | For a city in more than one county, all of them, the most populous part first. |
| `population`, `population_year` | The Bureau's latest estimate, and its year. |
| `population_2020` | The 2020 census count, as the estimates take it for their base. |
| `land_sq_mi`, `water_sq_mi`, `latitude`, `longitude` | From the Bureau's gazetteer; the point is one inside the place. A state's areas are its counties' added up. |
| `seat` | A county's seat, or a state's capital. |
| `density_per_sq_mi` | People to a square mile of land. |
| `water_share` | The share of its area that is water. |
| `urban_population_share` | The share of its people the 2020 census counted as living in urban areas. |
| `rural_urban_code`, `rural_urban_label` | For a county, the Department of Agriculture's 2023 code from 1 (in a metropolitan area of a million or more) to 9 (rural, and not beside one), with its meaning. For a state, the average of its counties' codes, each weighed by its people. |
| `age_under_1` … `age_80_plus` | The share of people of each age: under 1, 1 to 4, 5 to 12, 13 to 17, 18 to 24, 25 to 34, 35 to 44, 45 to 54, 55 to 64, 65 to 74, 75 to 79, and 80 or more. `age_year` is the year. |
| `median_household_income`, `gini_index`, `median_home_value` | From the American Community Survey, pooled over `income_years`. The Gini index runs from 0 (everyone has the same income) to 1 (one household has it all). Home value is what owners say their homes are worth, not sale prices. |
| `gdp_per_capita`, `gdp_year` | Gross domestic product in the dollars of that year, divided by the people there that year. |
| `violent_crime_rate`, `property_crime_rate`, `homicide_rate` | Offences known to the police for each 100,000 people, in `crime_year`. |
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

| | State | County | City | Community |
|---|---|---|---|---|
| People, area, density, water share | yes | yes | yes | yes |
| Income, inequality, home value | yes | yes | most | most |
| Urban share, rural-urban code | yes | yes | no | no |
| GDP for each person | yes | yes | no | no |
| Age bands | yes | no | no | no |
| Crime | yes | no | no | no |
| Flag, seal, site | yes | some | some | no |

### ages

For each state, people by single year of age (0 to 84, and 85 for 85 and
over), so that other age bands can be made than the twelve above.

### datasets

One row per place and dataset that has records of it: the dataset, what its
rows are, and the same counts and dates for that dataset alone.

## Where it comes from

- **People and counties:** the Census Bureau's Population Estimates, vintage
  2024. A community's people are the American Community Survey's count for
  2019 to 2023, since the estimates do not cover it.
- **Ages:** the same estimates, by single year of age, which the Bureau makes
  for states.
- **Area and position:** the Census Bureau's 2024 gazetteer files.
- **Income, inequality and home value:** American Community Survey, five-year
  tables B19013, B19083 and B25077 for 2019 to 2023.
- **Urban share:** the 2020 census's urban and rural counts.
- **Rural-urban code:** the Economic Research Service's 2023 Rural-Urban
  Continuum Codes.
- **GDP:** the Bureau of Economic Analysis's tables SAGDP1 and CAGDP1.
- **Crime:** the FBI's estimated crimes by state, from its Crime Data
  Explorer.
- **Flags, seals, sites and seats:** Wikidata, matched by the Census code.
  Where Wikidata has several, the first is kept.
- **Records:** counted from the datasets named in `datasets`.

## What to know

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
- Flag and seal images are other people's files. Check the file's page on
  Wikimedia Commons for its licence before using one.
- The counts say what has been collected, and collections differ. One city's
  dataset goes back to 1905 and another's covers five years.

## How it is made

[`build_places.py`](https://github.com/chrissoria/cat-pol-datasets/blob/main/build_places.py)
in cat-pol-datasets. The Census Bureau's figures are in the public domain and
Wikidata's are CC0; this compilation is released under CC0.
