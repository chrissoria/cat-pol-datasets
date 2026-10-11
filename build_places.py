#!/usr/bin/env python3
"""
Build chrissoria/us-places: one row for each state, county and city, with what
is known of it as a whole. How many people live there, how big it is, where
its flag can be seen, and how much of its lawmaking is in the other datasets
here.

It is the table a map of the country is drawn from before any one place has
been looked at closely: which places exist, which have a flag, which already
have records.

Sources, all public:
  Census Bureau, Population Estimates   people, in 2020 and at the latest estimate;
                                        which county a city is in
  Census Bureau, Gazetteer files        land and water area, and a point inside
  Wikidata                              the flag and seal (as files on Wikimedia
                                        Commons), the official site, the seat
  the datasets in this repository       ordinances, resolutions, bills, meetings
                                        and votes on record for a place

Tables, in data/:
  places.parquet     one row per state, county and incorporated city or town
  datasets.parquet   one row per place and dataset that has records of it

    python build_places.py                  # every state and the District of Columbia
    python build_places.py --states CA TX   # only some
    --no-upload    write the tables but do not publish them
    --write-card   publish the dataset card as well as the tables

The Census files are kept in places/ once fetched. Delete them to fetch again.
"""

import argparse
import csv
import io
import json
import logging
import re
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

import build_federal_bills as bills

log = logging.getLogger(__name__)

HF_REPO = "chrissoria/us-places"
OUT_DIR = bills.SCRIPT_DIR / "places"
CARD_FILE = bills.SCRIPT_DIR / "README_places.md"
HEADERS = {"User-Agent": "cat-pol-datasets (+https://github.com/chrissoria/cat-pol-datasets; chrissoria@berkeley.edu)"}

FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09", "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15",
    "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27",
    "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46", "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53",
    "WV": "54", "WI": "55", "WY": "56",
}

# Built by default: every state and the District of Columbia. The territories are not in these Census files.
STATES = sorted(FIPS)

VINTAGE = 2024  # the year of the latest population estimate, and of the gazetteer
POPEST = f"https://www2.census.gov/programs-surveys/popest/datasets/2020-{VINTAGE}"
GAZETTEER = f"https://www2.census.gov/geo/docs/maps-data/data/gazetteer/{VINTAGE}_Gazetteer"
ACS_YEAR = 2023  # the last year of the five the survey's figures are pooled over
ACS = f"https://www2.census.gov/programs-surveys/acs/summary_file/{ACS_YEAR}/table-based-SF/data/5YRData"
CENSUS_FILES = {
    "cities.csv": f"{POPEST}/cities/totals/sub-est{VINTAGE}.csv",
    "counties.csv": f"{POPEST}/counties/totals/co-est{VINTAGE}-alldata.csv",
    "states.csv": f"{POPEST}/state/totals/NST-EST{VINTAGE}-ALLDATA.csv",
    "gaz_counties.zip": f"{GAZETTEER}/{VINTAGE}_Gaz_counties_national.zip",
    "gaz_places.zip": f"{GAZETTEER}/{VINTAGE}_Gaz_place_national.zip",
    # People by single year of age, for states. The Bureau estimates counties by age band only, and cities not at all.
    "state_ages.csv": f"{POPEST}/state/asrh/sc-est{VINTAGE}-alldata6.csv",
    # The American Community Survey's five-year tables, one file each for every place in the country.
    "acs_income.dat": f"{ACS}/acsdt5y{ACS_YEAR}-b19013.dat",
    "acs_gini.dat": f"{ACS}/acsdt5y{ACS_YEAR}-b19083.dat",
    "acs_home_value.dat": f"{ACS}/acsdt5y{ACS_YEAR}-b25077.dat",
    "acs_population.dat": f"{ACS}/acsdt5y{ACS_YEAR}-b01003.dat",
    # Which county, or counties, each place is in. The estimates say so for cities only.
    "place_counties.txt": "https://www2.census.gov/geo/docs/reference/codes2020/national_place_by_county2020.txt",
    # Bureau of Economic Analysis: gross domestic product by state and by county.
    "state_gdp.zip": "https://apps.bea.gov/regional/zip/SAGDP.zip",
    "county_gdp.zip": "https://apps.bea.gov/regional/zip/CAGDP1.zip",
    # How much of each state's and county's population the 2020 census counted as urban.
    "urban_states.xlsx": "https://www2.census.gov/geo/docs/reference/ua/State_Urban_Rural_Pop_2020_2010.xlsx",
    "urban_counties.xlsx": "https://www2.census.gov/geo/docs/reference/ua/2020_UA_COUNTY.xlsx",
    # Department of Agriculture: each county from 1 (in a metropolitan area of a million or more) to 9 (rural, not beside one).
    "rural_urban.csv": "https://www.ers.usda.gov/media/5768/2023-rural-urban-continuum-codes.csv",
}
# The FBI's estimates of crime by state and year. Its site hands out a short-lived address for the file.
CRIME_KEY = "additional-datasets/srs/estimated_crimes_1979_{year}.csv"
CRIME_LINK = "https://cde.ucr.cjis.gov/LATEST/s3/signedurl"

# The ages people are grouped by: the column, and the first and last year of age in it. 85 stands for 85 and over.
AGE_BANDS = [("age_under_1", 0, 0), ("age_1_4", 1, 4), ("age_5_12", 5, 12), ("age_13_17", 13, 17), ("age_18_24", 18, 24), ("age_25_34", 25, 34),
             ("age_35_44", 35, 44), ("age_45_54", 45, 54), ("age_55_64", 55, 64), ("age_65_74", 65, 74), ("age_75_79", 75, 79), ("age_80_plus", 80, 85)]
FEATURE_COLUMNS = ["density_per_sq_mi", "water_share", "urban_population_share", "rural_urban_code", "rural_urban_label",
                   *[band for band, _, _ in AGE_BANDS], "age_year", "median_household_income", "gini_index", "median_home_value", "income_years",
                   "gdp_per_capita", "gdp_year", "violent_crime_rate", "property_crime_rate", "homicide_rate", "crime_year"]
WIKIDATA = "https://query.wikidata.org/sparql"
WORLD = "https://christophersoria.com/capitol-world/"

# What kind of government the Census Bureau's name for a place ends with.
GOVERNMENTS = ("city and borough", "consolidated government", "metropolitan government", "unified government", "urban county", "municipality",
               "borough", "village", "town", "city")

# The datasets here that hold a place's records, by the place's state and name (a county's name ends "County"; a state's is the state's).
# `records` is the table with one row per ordinance, bill or item; `kinds` is the column that says which each is.
SOURCES = [
    {"state": "CA", "place": "California", "repo": "chrissoria/california-bills", "records": "data/bills/*.parquet", "what": "bills", "date": "date",
     "votes": "data/member_votes/*.parquet", "world": "?world=california"},
    {"state": "CA", "place": "San Diego County", "repo": "chrissoria/sd-county-ordinances", "records": "data/items.parquet", "what": "items", "date": "date",
     "meetings": "data/meetings.parquet", "votes": "data/votes.parquet", "world": "?world=chamber&place=06073"},
    {"state": "CA", "place": "San Diego", "repo": "chrissoria/san-diego-ordinances", "records": "data/*.parquet", "what": "ordinances and resolutions", "date": "date"},
    {"state": "CA", "place": "San Diego", "repo": "chrissoria/san-diego-council", "records": "data/items.parquet", "what": "items", "date": "date",
     "meetings": "data/meetings.parquet", "votes": "data/votes.parquet", "world": "?world=chamber&place=0666000"},
    *[{"state": "CA", "place": place, "repo": f"chrissoria/{slug}-ordinances", "records": "data/*.parquet", "what": "ordinances and resolutions", "date": "date"}
      for place, slug in (("San Francisco", "sf"), ("Los Angeles", "la"), ("Oakland", "oakland"), ("Long Beach", "long-beach"), ("Fresno", "fresno"),
                          ("Berkeley", "berkeley"), ("Bakersfield", "bakersfield"), ("Salinas", "salinas"), ("Newport Beach", "newport-beach"), ("Clovis", "clovis"))],
]

PLACE_COLUMNS_START = ["place_id", "kind", "name", "census_name", "government", "state", "state_name", "county_id", "county_name", "counties",
                 "population", "population_2020", "population_year", "land_sq_mi", "water_sq_mi", "latitude", "longitude", "seat"]
PLACE_COLUMNS_END = ["flag_url", "seal_url", "website", "wikidata", "n_records", "n_ordinances", "n_resolutions", "n_bills", "n_meetings", "n_votes",
                     "records_from", "records_to", "datasets", "world_url"]
PLACE_COLUMNS = PLACE_COLUMNS_START + FEATURE_COLUMNS + PLACE_COLUMNS_END
DATASET_COLUMNS = ["place_id", "name", "state", "repo", "what", "n_records", "n_ordinances", "n_resolutions", "n_meetings", "n_votes", "records_from", "records_to", "world_url"]


def fetch(url, tries=5, **kwargs):
    for attempt in range(tries):
        try:
            response = requests.get(url, headers=HEADERS, timeout=180, **kwargs)
            response.raise_for_status()
            return response
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(5 * (attempt + 1))


def census_file(name, folder):
    """One of the Census Bureau's files, fetched once and kept."""
    path = Path(folder) / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fetch(CENSUS_FILES[name]).content)
    return path


def rows_of(path):
    """A Census file's rows. The estimates are comma-separated and the gazetteer, inside its zip, is tab-separated with padded names."""
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            text = archive.read(archive.namelist()[0]).decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text), delimiter="\t")
        return [{key.strip(): (value or "").strip() for key, value in row.items() if key} for row in reader]
    with open(path, encoding="utf-8-sig" if path.name == "state_crime.csv" else "latin-1", newline="") as f:
        return list(csv.DictReader(f, delimiter="|" if path.suffix == ".txt" else ","))


def split_name(census_name):
    """'San Diego city' as the name people use and the kind of government: ('San Diego', 'city')."""
    name = re.sub(r"\s*\((balance|pt\.)\)\s*$", "", census_name).strip()
    for kind in GOVERNMENTS:
        if name.endswith(" " + kind):  # the Bureau writes the kind in small letters; "Carson City" is a name
            return name[: -len(kind) - 1].strip(), kind
    return name, ""


def number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def census_places(states, folder):
    """Every state, county and incorporated place of the states asked for, from the Census Bureau's files."""
    fips = {FIPS[state]: state for state in states}
    latest, base = f"POPESTIMATE{VINTAGE}", "ESTIMATESBASE2020"
    gaz_counties = {row["GEOID"]: row for row in rows_of(census_file("gaz_counties.zip", folder))}
    gaz_places = {row["GEOID"]: row for row in rows_of(census_file("gaz_places.zip", folder))}
    places, state_names, county_names = [], {}, {}

    def measured(gaz):
        return {"land_sq_mi": number(gaz.get("ALAND_SQMI")), "water_sq_mi": number(gaz.get("AWATER_SQMI")),
                "latitude": number(gaz.get("INTPTLAT")), "longitude": number(gaz.get("INTPTLONG"))} if gaz else {}

    for row in rows_of(census_file("states.csv", folder)):
        if row["SUMLEV"] == "040" and row["STATE"] in fips:
            state_names[row["STATE"]] = row["NAME"]
            places.append({"place_id": row["STATE"], "kind": "state", "name": row["NAME"], "census_name": row["NAME"], "government": "state",
                           "state": fips[row["STATE"]], "state_name": row["NAME"], "population": int(row[latest]), "population_2020": int(row[base]),
                           "by_year": {year: int(row[f"POPESTIMATE{year}"]) for year in range(2020, VINTAGE + 1)}})
    for row in rows_of(census_file("counties.csv", folder)):
        if row["SUMLEV"] == "050" and row["STATE"] in fips:
            geoid = row["STATE"] + row["COUNTY"]
            county_names[geoid] = row["CTYNAME"]
            places.append({"place_id": geoid, "kind": "county", "name": row["CTYNAME"], "census_name": row["CTYNAME"], "government": "county",
                           "state": fips[row["STATE"]], "state_name": state_names.get(row["STATE"], row["STNAME"]),
                           "population": int(row[latest]), "population_2020": int(row[base]),
                           "by_year": {year: int(row[f"POPESTIMATE{year}"]) for year in range(2020, VINTAGE + 1)}, **measured(gaz_counties.get(geoid))})
    # A city can lie in more than one county. Its county here is the one most of its people live in.
    parts = {}
    cities = rows_of(census_file("cities.csv", folder))
    for row in cities:
        if row["SUMLEV"] == "157" and row["STATE"] in fips:
            parts.setdefault(row["STATE"] + row["PLACE"], []).append((int(row[latest]), row["STATE"] + row["COUNTY"]))
    for row in cities:
        if row["SUMLEV"] != "162" or row["STATE"] not in fips or row["FUNCSTAT"] not in ("A", "B", "C", "G"):
            continue
        geoid = row["STATE"] + row["PLACE"]
        name, kind = split_name(row["NAME"])
        within = [county for _, county in sorted(parts.get(geoid, []), reverse=True)]
        places.append({"place_id": geoid, "kind": "city", "name": name, "census_name": row["NAME"], "government": kind or "city",
                       "state": fips[row["STATE"]], "state_name": state_names.get(row["STATE"], row["STNAME"]),
                       "county_id": within[0] if within else None, "county_name": county_names.get(within[0]) if within else None,
                       "counties": json.dumps(within) if len(within) > 1 else None,
                       "population": int(row[latest]), "population_2020": int(row[base]), **measured(gaz_places.get(geoid))})
    # Settled land that belongs to no city: the Bureau names it and draws a line round it, and counts it in its survey, though it
    # has no government but the county's. Spring Valley in San Diego County is one.
    people = survey_values(census_file("acs_population.dat", folder))
    homes = {}
    for row in rows_of(census_file("place_counties.txt", folder)):
        if row["STATEFP"] in fips and row["TYPE"] == "CENSUS DESIGNATED PLACE":
            homes.setdefault(row["STATEFP"] + row["PLACEFP"], []).append(row["STATEFP"] + row["COUNTYFP"])
    for geoid, gaz in gaz_places.items():
        if geoid[:2] not in fips or gaz.get("LSAD") != "57":
            continue
        within = homes.get(geoid, [])
        count = people.get(geoid)
        places.append({"place_id": geoid, "kind": "community", "name": re.sub(r" CDP$", "", gaz["NAME"]), "census_name": gaz["NAME"],
                       "government": "none (census designated place)", "state": fips[geoid[:2]], "state_name": state_names.get(geoid[:2]),
                       "county_id": within[0] if within else None, "county_name": county_names.get(within[0]) if within else None,
                       "counties": json.dumps(within) if len(within) > 1 else None,
                       "population": int(count) if count is not None else None, "population_2020": None, "survey": True, **measured(gaz)})
    table = pd.DataFrame(places)
    # A state's area is its counties' together; the gazetteer file for states is not fetched for two numbers.
    for column in ("land_sq_mi", "water_sq_mi"):
        sums = table[table["kind"] == "county"].groupby("state")[column].sum().round(1)
        states_rows = table["kind"] == "state"
        table.loc[states_rows, column] = table.loc[states_rows, "state"].map(sums)
    # A community's people are the survey's count over its five years, not the yearly estimate the others have.
    surveyed = table["survey"].fillna(False).astype(bool) if "survey" in table.columns else pd.Series(False, index=table.index)
    table["population_year"] = VINTAGE
    table.loc[surveyed, "population_year"] = ACS_YEAR
    return table.drop(columns=[column for column in ("survey",) if column in table.columns])


def source_file(name, folder):
    """Any of the files the table is built from, fetched once and kept. The same as census_file, under a name that fits the rest."""
    return census_file(name, folder)


def crime_file(folder):
    """The FBI's estimates by state, for the latest year it has put out."""
    path = Path(folder) / "state_crime.csv"
    if path.exists():
        return path
    for year in range(datetime.now(timezone.utc).year, 2021, -1):
        key = CRIME_KEY.format(year=year)
        try:
            link = fetch(CRIME_LINK, params={"key": key}, tries=2).json().get(key)
            body = fetch(link, tries=2).content if link else b""
        except Exception:
            continue
        if body.lstrip(b"\xef\xbb\xbf").startswith(b"year,"):  # a year it has not put out comes back as something else
            path.write_bytes(body)
            return path
    return None


def whole(text):
    """'39,431,263' as a number; None for a blank."""
    digits = re.sub(r"[^\d.]", "", str(text or ""))
    return float(digits) if digits else None


def age_tables(folder, wanted):
    """For each state: its people by single year of age, and the share of them in each of AGE_BANDS."""
    counts = {}
    for row in rows_of(source_file("state_ages.csv", folder)):
        if row["SUMLEV"] == "040" and row["SEX"] == "0" and row["ORIGIN"] == "0" and row["STATE"] in wanted:
            ages = counts.setdefault(row["STATE"], {})
            ages[int(row["AGE"])] = ages.get(int(row["AGE"]), 0) + int(row[f"POPESTIMATE{VINTAGE}"])
    shares = {}
    for state, ages in counts.items():
        total = sum(ages.values())
        shares[state] = {band: round(sum(people for age, people in ages.items() if first <= age <= last) / total, 4) for band, first, last in AGE_BANDS}
    single = pd.DataFrame([{"place_id": state, "age": age, "people": people} for state, ages in sorted(counts.items()) for age, people in sorted(ages.items())],
                          columns=["place_id", "age", "people"])
    return shares, single


def survey_values(path):
    """One of the survey's tables: the estimate for each state, county and place, by the Census code."""
    kinds = {"0400000US": 2, "0500000US": 5, "1600000US": 7}
    values = {}
    with open(path, encoding="latin-1") as f:
        next(f)
        for line in f:
            geo, estimate = line.split("|")[:2]
            if geo[:9] in kinds and len(geo) == 9 + kinds[geo[:9]]:
                found = number(estimate)
                values[geo[9:]] = found if found is not None and found >= 0 else None  # a large negative number stands for "not available"
    return values


def gdp_values(path, pattern, scale):
    """Current-dollar gross domestic product, in dollars, by place and year: {code: {year: dollars}}."""
    with zipfile.ZipFile(path) as archive:
        name = next(name for name in archive.namelist() if re.search(pattern, name))
        text = archive.read(name).decode("latin-1")
    found = {}
    for row in csv.DictReader(io.StringIO(text)):
        if (row.get("LineCode") or "").strip() != "3":
            continue
        code = (row["GeoFIPS"] or "").strip().strip('"')
        found[code] = {int(year): float(value) * scale for year, value in row.items() if year.isdigit() and number(value) is not None}
    return found


def add_features(places, folder):
    """What a place is like, beside how many live there: how dense and how urban, how old, how rich and how unequal, how safe."""
    places = places.copy()
    states = set(places.loc[places["kind"] == "state", "place_id"])
    land, water = places["land_sq_mi"], places["water_sq_mi"]
    places["density_per_sq_mi"] = (places["population"] / land.where(land > 0)).round(1)
    places["water_share"] = (water / (land + water).where((land + water) > 0)).round(4)

    urban = {}
    table = pd.read_excel(source_file("urban_states.xlsx", folder))
    table.columns = [re.sub(r"\s+", " ", str(column)).strip() for column in table.columns]
    for _, row in table.iterrows():
        if pd.notna(row["STATEFP"]):
            urban[f"{int(row['STATEFP']):02d}"] = round(float(row["2020 PCT URBAN POP"]) / (100 if float(row["2020 PCT URBAN POP"]) > 1 else 1), 4)
    table = pd.read_excel(source_file("urban_counties.xlsx", folder), usecols=["STATE", "COUNTY", "POPPCT_URB"])
    for state, county, share in zip(table["STATE"], table["COUNTY"], table["POPPCT_URB"]):
        urban[f"{int(state):02d}{int(county):03d}"] = round(float(share), 4)
    places["urban_population_share"] = places["place_id"].map(urban)

    codes, labels = {}, {}
    for row in rows_of(source_file("rural_urban.csv", folder)):
        code = f"{int(row['FIPS']):05d}"
        if row["Attribute"] == "RUCC_2023":
            codes[code] = number(row["Value"])
        elif row["Attribute"] == "Description":
            labels[code] = row["Value"].strip()
    places["rural_urban_code"] = places["place_id"].map(codes)
    places["rural_urban_label"] = places["place_id"].map(labels)
    # A state has no code of its own: it is given the average of its counties', each weighed by its people.
    counties = places[(places["kind"] == "county") & places["rural_urban_code"].notna()]
    weighted = (counties["rural_urban_code"] * counties["population"]).groupby(counties["place_id"].str[:2]).sum() / counties.groupby(counties["place_id"].str[:2])["population"].sum()
    is_state = places["kind"] == "state"
    places.loc[is_state, "rural_urban_code"] = places.loc[is_state, "place_id"].map(weighted.round(2))

    shares, single = age_tables(folder, states)
    for band, _, _ in AGE_BANDS:
        places[band] = places["place_id"].map(lambda code: shares.get(code, {}).get(band))
    places["age_year"] = places["place_id"].map(lambda code: VINTAGE if code in shares else None).astype("Int64")

    income = survey_values(source_file("acs_income.dat", folder))
    gini = survey_values(source_file("acs_gini.dat", folder))
    homes = survey_values(source_file("acs_home_value.dat", folder))
    places["median_household_income"] = places["place_id"].map(income).astype("Int64")
    places["gini_index"] = places["place_id"].map(gini).round(4)
    places["median_home_value"] = places["place_id"].map(homes).astype("Int64")
    surveyed = lambda code: any(table.get(code) is not None for table in (income, gini, homes))
    places["income_years"] = places["place_id"].map(lambda code: f"{ACS_YEAR - 4}-{ACS_YEAR}" if surveyed(code) else None)

    product = {code[:2]: by_year for code, by_year in gdp_values(source_file("state_gdp.zip", folder), r"SAGDP1__ALL_AREAS", 1e6).items() if code.endswith("000")}
    product.update({code: by_year for code, by_year in gdp_values(source_file("county_gdp.zip", folder), r"CAGDP1__ALL_AREAS", 1e3).items() if not code.endswith("000")})
    per_head, year_of = {}, {}
    for code, people in zip(places["place_id"], places["by_year"]):
        by_year = product.get(code)
        if not by_year or not isinstance(people, dict):
            continue
        year = max((year for year in by_year if year in people and people[year]), default=None)
        if year:
            per_head[code], year_of[code] = round(by_year[year] / people[year]), year
    places["gdp_per_capita"] = places["place_id"].map(per_head).astype("Int64")
    places["gdp_year"] = places["place_id"].map(year_of).astype("Int64")

    for column in ("violent_crime_rate", "property_crime_rate", "homicide_rate"):
        places[column] = None
    places["crime_year"] = pd.Series([pd.NA] * len(places), dtype="Int64")
    crimes = crime_file(folder)
    if crimes:
        rows = [row for row in rows_of(crimes) if row.get("state_abbr") and row.get("year", "").isdigit()]
    if crimes and rows:
        latest = max(int(row["year"]) for row in rows)
        by_state = {row["state_abbr"]: row for row in rows if int(row["year"]) == latest}
        for index, state in places.loc[is_state, "state"].items():
            row = by_state.get(state)
            people = whole(row["population"]) if row else None
            if not people:
                continue
            for column, key in (("violent_crime_rate", "violent_crime"), ("property_crime_rate", "property_crime"), ("homicide_rate", "homicide")):
                count = whole(row[key])
                places.loc[index, column] = round(count / people * 100000, 1) if count is not None else None
            places.loc[index, "crime_year"] = latest
    for column in ("violent_crime_rate", "property_crime_rate", "homicide_rate"):
        places[column] = places[column].astype("float64")
    return places.drop(columns="by_year"), single


def commons_url(value):
    """Wikidata gives a file on Wikimedia Commons as an address that redirects to the image; use it over https."""
    return re.sub(r"^http://", "https://", value) if value else None


def wikidata_rows(query):
    found = fetch(WIKIDATA, params={"query": query, "format": "json"}).json()["results"]["bindings"]
    return [{key: value["value"] for key, value in row.items()} for row in found]


def wikidata_facts(states):
    """Flag, seal, site and seat of each place, by its Census code. Several values for one place: the first is kept."""
    facts = {}

    def keep(code, row):
        entry = facts.setdefault(code, {})
        entry.setdefault("wikidata", row["item"].rsplit("/", 1)[-1])
        for column, key in (("flag_url", "flag"), ("seal_url", "seal"), ("website", "site"), ("seat", "seatLabel")):
            if row.get(key) and not entry.get(column):
                entry[column] = commons_url(row[key]) if key in ("flag", "seal") else row[key]

    extras = "OPTIONAL { ?item wdt:P41 ?flag } OPTIONAL { ?item wdt:P158 ?seal } OPTIONAL { ?item wdt:P856 ?site } OPTIONAL { ?item wdt:P36 ?seat }"
    labels = 'SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }'
    for state in states:
        code = FIPS[state]
        for row in wikidata_rows(f'SELECT ?item ?flag ?seal ?site ?seatLabel WHERE {{ ?item wdt:P5087 "{code}" . {extras} {labels} }}'):
            keep(code, row)
        for row in wikidata_rows(f'SELECT ?item ?fips ?flag ?seal ?site ?seatLabel WHERE {{ ?item wdt:P882 ?fips . FILTER(STRSTARTS(?fips, "{code}")) {extras} {labels} }}'):
            keep(row["fips"], row)
        # A place's code is written "06-66000" there.
        for row in wikidata_rows(f'SELECT ?item ?fips ?flag ?seal ?site WHERE {{ ?item wdt:P774 ?fips . FILTER(STRSTARTS(?fips, "{code}-")) '
                                 f'OPTIONAL {{ ?item wdt:P41 ?flag }} OPTIONAL {{ ?item wdt:P158 ?seal }} OPTIONAL {{ ?item wdt:P856 ?site }} }}'):
            keep(row["fips"].replace("-", ""), row)
        time.sleep(2)
    return facts


def count_source(source):
    """What one dataset holds of a place: how many records, of which kinds, over which years. None if it cannot be read."""
    import pyarrow.dataset as ds
    from huggingface_hub import HfFileSystem
    files = HfFileSystem(token=bills.HF_TOKEN)

    def table(pattern, columns):
        paths = files.glob(f"datasets/{source['repo']}/{pattern}")
        if not paths:
            return None
        data = ds.dataset(paths, filesystem=files, format="parquet")
        return data.to_table(columns=[column for column in columns if column in data.schema.names]).to_pandas()

    try:
        records = table(source["records"], ["doc_type", source["date"]])
        if records is None:
            return None
        dates = records[source["date"]].dropna().astype(str) if source["date"] in records.columns else pd.Series([], dtype=str)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        dates = dates[dates.str.match(r"\d{4}-\d{2}-\d{2}")].str[:10]
        dates = dates[dates <= today]  # a date yet to come is a slip of the source's, and would be the latest of all
        kinds = records["doc_type"].value_counts() if "doc_type" in records.columns else {}
        found = {"n_records": len(records), "n_ordinances": int(kinds.get("ordinance", 0)) or None, "n_resolutions": int(kinds.get("resolution", 0)) or None,
                 "records_from": dates.min() if len(dates) else None, "records_to": dates.max() if len(dates) else None, "n_meetings": None, "n_votes": None}
        for column in ("meetings", "votes"):
            if source.get(column):
                counted = table(source[column], ["date", "meeting_id", "vote", "bill_id"])
                found[f"n_{column}"] = len(counted) if counted is not None else None
        return found
    except Exception as e:
        log.warning(f"{source['repo']} not counted: {type(e).__name__}: {e}")
        return None


def datasets_table(places, sources=SOURCES, count=count_source):
    """One row per place and dataset with records of it."""
    rows = []
    for source in sources:
        match = places[(places["state"] == source["state"]) & (places["name"] == source["place"]) & places["kind"].isin(["state", "county", "city"])]
        if match.empty:
            continue
        counted = count(source)
        if counted is None:
            continue
        place = match.iloc[0]
        rows.append({"place_id": place["place_id"], "name": place["name"], "state": place["state"], "repo": source["repo"], "what": source["what"],
                     **counted, "world_url": WORLD + source["world"] if source.get("world") else None})
    table = pd.DataFrame(rows, columns=DATASET_COLUMNS)
    for column in ("n_records", "n_ordinances", "n_resolutions", "n_meetings", "n_votes"):
        table[column] = table[column].astype("Int64")
    return table


def add_records(places, datasets):
    """Put each place's datasets onto its row: the counts added up, the years they span, and the way in to its world if it has one."""
    places = places.copy()
    for column in ("n_records", "n_ordinances", "n_resolutions", "n_bills", "n_meetings", "n_votes"):
        places[column] = pd.Series([pd.NA] * len(places), dtype="Int64")
    for column in ("records_from", "records_to", "datasets", "world_url"):
        places[column] = None
    for place_id, held in datasets.groupby("place_id"):
        row = places["place_id"] == place_id
        bills_held = held[held["what"] == "bills"]
        other = held[held["what"] != "bills"]
        for column in ("n_ordinances", "n_resolutions", "n_meetings", "n_votes"):
            if held[column].notna().any():
                places.loc[row, column] = int(held[column].max())
        if len(other):
            places.loc[row, "n_records"] = int(other["n_records"].max())
        if len(bills_held):
            places.loc[row, "n_bills"] = int(bills_held["n_records"].sum())
        places.loc[row, "records_from"] = held["records_from"].dropna().min() if held["records_from"].notna().any() else None
        places.loc[row, "records_to"] = held["records_to"].dropna().max() if held["records_to"].notna().any() else None
        places.loc[row, "datasets"] = json.dumps(sorted(held["repo"]))
        worlds = held["world_url"].dropna()
        places.loc[row, "world_url"] = worlds.iloc[-1] if len(worlds) else None
    return places


def build(states, folder, facts=None, sources=SOURCES, count=count_source):
    places = census_places(states, folder)
    facts = wikidata_facts(states) if facts is None else facts
    for column in ("seat", "flag_url", "seal_url", "website", "wikidata"):
        places[column] = places["place_id"].map(lambda code: facts.get(code, {}).get(column))
    places, ages = add_features(places, folder)
    datasets = datasets_table(places, sources, count)
    places = add_records(places, datasets)
    order = {"state": 0, "county": 1, "city": 2, "community": 3}
    places = places.assign(level=places["kind"].map(order)).sort_values(["state", "level", "name"]).drop(columns="level")
    places = places.reindex(columns=PLACE_COLUMNS).reset_index(drop=True)
    for column in ("population", "population_2020", "population_year"):
        places[column] = places[column].astype("Int64")
    return places, datasets, ages


def upload(out_dir, with_card):
    from huggingface_hub import CommitOperationAdd, HfApi
    api = HfApi(token=bills.HF_TOKEN)
    api.create_repo(HF_REPO, repo_type="dataset", exist_ok=True)
    problem = bills.hf_write_problem(HF_REPO)
    if problem:
        log.error(f"Places not uploaded: {problem}")
        return False
    operations = [CommitOperationAdd(path_in_repo=f"data/{name}.parquet", path_or_fileobj=str(out_dir / f"{name}.parquet")) for name in ("places", "datasets", "ages")]
    if (with_card or "README.md" not in set(api.list_repo_files(HF_REPO, repo_type="dataset"))) and CARD_FILE.exists():
        operations.append(CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=str(CARD_FILE)))
    api.create_commit(repo_id=HF_REPO, repo_type="dataset", operations=operations,
                      commit_message=f"Update places ({datetime.now(timezone.utc).strftime('%Y-%m-%d')})")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the table of states, counties and cities")
    parser.add_argument("--states", nargs="+", default=STATES, help="postal codes of the states to build")
    parser.add_argument("--out", default=str(OUT_DIR), help="directory to write the tables into, and to keep the Census files in")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    unknown = [state for state in args.states if state not in FIPS]
    if unknown:
        parser.error(f"not a state: {', '.join(unknown)}")
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the tables only")
    out_dir = Path(args.out)
    try:
        places, datasets, ages = build(args.states, out_dir)
    except Exception as e:
        log.error(f"Places not built: {type(e).__name__}: {e}")
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    places.to_parquet(out_dir / "places.parquet", index=False)
    datasets.to_parquet(out_dir / "datasets.parquet", index=False)
    ages.to_parquet(out_dir / "ages.parquet", index=False)
    pushed = False if args.no_upload else upload(out_dir, args.write_card)
    kinds = places["kind"].value_counts()
    log.info(f"RESULT: us-places states={int(kinds.get('state', 0))} counties={int(kinds.get('county', 0))} cities={int(kinds.get('city', 0))} "
             f"communities={int(kinds.get('community', 0))} "
             f"with_flag={int(places['flag_url'].notna().sum())} with_seal={int(places['seal_url'].notna().sum())} "
             f"with_income={int(places['median_household_income'].notna().sum())} with_gdp={int(places['gdp_per_capita'].notna().sum())} "
             f"with_ages={int(places['age_year'].notna().sum())} with_crime={int(places['crime_year'].notna().sum())} "
             f"with_records={int(places['datasets'].notna().sum())} datasets={len(datasets)} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(main())
