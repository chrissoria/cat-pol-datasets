#!/usr/bin/env python3
"""
Build chrissoria/us-places: one row for the country and for each state,
territory, county, city and unincorporated community, with what is known of it
as a whole. How many people live there, how big it is, where its flag can be
seen, which place it is part of, and how much of its lawmaking is in the other
datasets here.

It is the one place the rest is meant to read what a place is from: the map of
the country, the statistics of a place, and which body governs it. The bodies
are listed in bodies.json (see bodies.py).

Sources, all public:
  Census Bureau, Population Estimates   people, in 2020 and at the latest estimate;
                                        which county a city is in
  Census Bureau, Gazetteer files        land and water area, and a point inside
  Wikidata                              the flag and seal (as files on Wikimedia
                                        Commons), the official site, the seat
  MIT Election Data and Science Lab     how each state voted for president
  the datasets in this repository       ordinances, resolutions, bills, meetings
                                        and votes on record for a place

Tables, in data/:
  places.parquet     one row per place
  bodies.parquet     one row per body that governs one: Congress, a legislature, a board, a council
  datasets.parquet   one row per body and dataset that has records of it
  ages.parquet       people by single year of age, for the country and the states

and world/bodies.json, the same list of bodies as Capitol World reads it, and
index/, each place's facts as Capitol World reads them: one file for the
country and the states, and one for everything in each state.

    python build_places.py                  # every state and the District of Columbia
    python build_places.py --states CA TX   # only some
    --no-upload    write the tables but do not publish them
    --write-card   publish the dataset card as well as the tables

The Census files and what Wikidata said are kept in places/ once fetched.
Delete them to fetch again.
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

import bodies as registry
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

# The five territories that send someone to Congress. Each is one row: its municipalities, districts and villages are not here yet.
TERRITORIES = {"AS": "60", "GU": "66", "MP": "69", "PR": "72", "VI": "78"}
TERRITORY_NAMES = {"AS": "American Samoa", "GU": "Guam", "MP": "Northern Mariana Islands", "PR": "Puerto Rico", "VI": "U.S. Virgin Islands"}
NATION = "00"  # the code the Census Bureau's files give the country as a whole
STATE_KINDS = ("state", "district", "territory")  # the places a state's code stands for

# Built by default: every state, the District of Columbia and the territories.
STATES = sorted(FIPS) + sorted(TERRITORIES)

# Each state's capital, the year it joined the Union and its place in the order of joining; a territory's capital.
UNION = {
    "AL": ("Montgomery", 1819, 22), "AK": ("Juneau", 1959, 49), "AZ": ("Phoenix", 1912, 48), "AR": ("Little Rock", 1836, 25),
    "CA": ("Sacramento", 1850, 31), "CO": ("Denver", 1876, 38), "CT": ("Hartford", 1788, 5), "DE": ("Dover", 1787, 1),
    "FL": ("Tallahassee", 1845, 27), "GA": ("Atlanta", 1788, 4), "HI": ("Honolulu", 1959, 50), "ID": ("Boise", 1890, 43),
    "IL": ("Springfield", 1818, 21), "IN": ("Indianapolis", 1816, 19), "IA": ("Des Moines", 1846, 29), "KS": ("Topeka", 1861, 34),
    "KY": ("Frankfort", 1792, 15), "LA": ("Baton Rouge", 1812, 18), "ME": ("Augusta", 1820, 23), "MD": ("Annapolis", 1788, 7),
    "MA": ("Boston", 1788, 6), "MI": ("Lansing", 1837, 26), "MN": ("Saint Paul", 1858, 32), "MS": ("Jackson", 1817, 20),
    "MO": ("Jefferson City", 1821, 24), "MT": ("Helena", 1889, 41), "NE": ("Lincoln", 1867, 37), "NV": ("Carson City", 1864, 36),
    "NH": ("Concord", 1788, 9), "NJ": ("Trenton", 1787, 3), "NM": ("Santa Fe", 1912, 47), "NY": ("Albany", 1788, 11),
    "NC": ("Raleigh", 1789, 12), "ND": ("Bismarck", 1889, 39), "OH": ("Columbus", 1803, 17), "OK": ("Oklahoma City", 1907, 46),
    "OR": ("Salem", 1859, 33), "PA": ("Harrisburg", 1787, 2), "RI": ("Providence", 1790, 13), "SC": ("Columbia", 1788, 8),
    "SD": ("Pierre", 1889, 40), "TN": ("Nashville", 1796, 16), "TX": ("Austin", 1845, 28), "UT": ("Salt Lake City", 1896, 45),
    "VT": ("Montpelier", 1791, 14), "VA": ("Richmond", 1788, 10), "WA": ("Olympia", 1889, 42), "WV": ("Charleston", 1863, 35),
    "WI": ("Madison", 1848, 30), "WY": ("Cheyenne", 1890, 44),
    "AS": ("Pago Pago", None, None), "GU": ("Hagåtña", None, None), "MP": ("Saipan", None, None), "PR": ("San Juan", None, None),
    "VI": ("Charlotte Amalie", None, None), "US": ("Washington, D.C.", None, None),
}

VINTAGE = 2024  # the year of the latest population estimate, and of the gazetteer
POPEST = f"https://www2.census.gov/programs-surveys/popest/datasets/2020-{VINTAGE}"
GAZETTEER = f"https://www2.census.gov/geo/docs/maps-data/data/gazetteer/{VINTAGE}_Gazetteer"
ACS_YEAR = 2024  # the last year of the five the survey's figures are pooled over
ACS = f"https://www2.census.gov/programs-surveys/acs/summary_file/{ACS_YEAR}/table-based-SF/data/5YRData"
# The districts that members of Congress and of the state legislatures are elected from. A district's lines change, so a row is
# a district as drawn for one Congress or one session, and its place_id is the Census Bureau's full code, which says which:
# 5001900US0652 is California's 52nd as drawn for the 119th Congress. The survey counts people by the same code, so a row's
# figures are for those lines and no others. When the lines change, the prefix does, and the old rows are not the new ones.
DISTRICTS = [
    {"kind": "congressional district", "prefix": "5001900US", "file": "gaz_cd.zip", "session": "119th Congress"},
    {"kind": "state senate district", "prefix": "610U900US", "file": "gaz_sldu.zip", "session": f"{VINTAGE} legislative session"},
    {"kind": "state house district", "prefix": "620L900US", "file": "gaz_sldl.zip", "session": f"{VINTAGE} legislative session"},
]
DISTRICT_KINDS = tuple(district["kind"] for district in DISTRICTS)
# The words in a legislative district's name that say only that it is one. What is left is its number or its name.
DISTRICT_WORDS = {"state", "general", "senate", "(senate)", "house", "(house)", "assembly", "legislative", "representative", "delegate",
                  "senatorial", "district", "subdistrict", "ward"}

ISLANDS = "https://www2.census.gov/programs-surveys/decennial/2020/data/island-areas"
CENSUS_FILES = {
    # The 2020 census of the four island territories, which the yearly estimates leave out.
    "islands_AS.csv": f"{ISLANDS}/american-samoa/population-and-housing-unit-counts/american-samoa-phc-table01.csv",
    "islands_GU.csv": f"{ISLANDS}/guam/population-and-housing-unit-counts/guam-phc-table01.csv",
    "islands_MP.csv": f"{ISLANDS}/commonwealth-of-the-northern-mariana-islands/population-and-housing-unit-counts/commonwealth-northern-mariana-islands-phc-table01.csv",
    "islands_VI.csv": f"{ISLANDS}/us-virgin-islands/population-and-housing-unit-counts/us-virgin-islands-phc-table01.csv",
    "cities.csv": f"{POPEST}/cities/totals/sub-est{VINTAGE}.csv",
    "counties.csv": f"{POPEST}/counties/totals/co-est{VINTAGE}-alldata.csv",
    "states.csv": f"{POPEST}/state/totals/NST-EST{VINTAGE}-ALLDATA.csv",
    "gaz_counties.zip": f"{GAZETTEER}/{VINTAGE}_Gaz_counties_national.zip",
    "gaz_places.zip": f"{GAZETTEER}/{VINTAGE}_Gaz_place_national.zip",
    "gaz_cd.zip": f"{GAZETTEER}/{VINTAGE}_Gaz_119CDs_national.zip",
    "gaz_sldu.zip": f"{GAZETTEER}/{VINTAGE}_Gaz_sldu_national.zip",
    "gaz_sldl.zip": f"{GAZETTEER}/{VINTAGE}_Gaz_sldl_national.zip",
    # People by single year of age, for states. The Bureau estimates counties by age band only, and cities not at all.
    "state_ages.csv": f"{POPEST}/state/asrh/sc-est{VINTAGE}-alldata6.csv",
    # The American Community Survey's five-year tables, one file each for every place in the country.
    f"acs{ACS_YEAR}_income.dat": f"{ACS}/acsdt5y{ACS_YEAR}-b19013.dat",
    f"acs{ACS_YEAR}_gini.dat": f"{ACS}/acsdt5y{ACS_YEAR}-b19083.dat",
    f"acs{ACS_YEAR}_home_value.dat": f"{ACS}/acsdt5y{ACS_YEAR}-b25077.dat",
    f"acs{ACS_YEAR}_population.dat": f"{ACS}/acsdt5y{ACS_YEAR}-b01003.dat",
    f"acs{ACS_YEAR}_ages.dat": f"{ACS}/acsdt5y{ACS_YEAR}-b01001.dat",  # people by sex and age band; 200 megabytes
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
# The MIT Election Data and Science Lab's returns for president by state, on Harvard's Dataverse. The file's number there changes
# with each release, so the dataset is asked which file it is.
ELECTION_YEAR = 2024  # the last election for president; its year ends the names of the columns it fills
ELECTION_DATASET = "https://dataverse.harvard.edu/api/datasets/:persistentId/?persistentId=doi:10.7910/DVN/42MVDX"
ELECTION_FILE = "https://dataverse.harvard.edu/api/access/datafile/{id}"
# Whose votes are each party's, by the candidate's name as a state's returns write it. A nominee is on some ballots under another
# party's line as well (Harris on the Working Families line in New York), and a few states list the name the other way round.
# "Independent" is the two who ran without a party's nomination, under whatever label a state's ballot gave them.
VOTE_PARTIES = {
    "republican": r"\bTRUMP\b",
    "democrat": r"\bKAMALA\b",
    "libertarian": r"\bCHASE OLIVER\b|\bOLIVER, CHASE\b",
    "green": r"\bJILL STEIN\b|\bSTEIN, JILL\b",
    "independent": r"\bKENNEDY, ROBERT\b|\bROBERT F\.? KENNEDY\b|\bCORNEL\b|^WEST( ABDULLAH)?$",
}
NOT_A_VOTE = r"^(UNDERVOTES?|OVERVOTES?|VOID|BLANK( VOTES?)?|SPOILED)$"  # ballots that chose no one, which some states list
VOTE_COLUMNS = [f"vote_{party}_{ELECTION_YEAR}" for party in ("republican", "democrat", "independent", "libertarian", "green", "other")] + [f"votes_cast_{ELECTION_YEAR}"]

# The FBI's estimates of crime by state and year. Its site hands out a short-lived address for the file.
CRIME_KEY = "additional-datasets/srs/estimated_crimes_1979_{year}.csv"
CRIME_LINK = "https://cde.ucr.cjis.gov/LATEST/s3/signedurl"

# The ages people are grouped by: the column, and the first and last year of age in it. 85 stands for 85 and over.
AGE_BANDS = [("age_under_1", 0, 0), ("age_1_4", 1, 4), ("age_5_12", 5, 12), ("age_13_17", 13, 17), ("age_18_24", 18, 24), ("age_25_34", 25, 34),
             ("age_35_44", 35, 44), ("age_45_54", 45, 54), ("age_55_64", 55, 64), ("age_65_74", 65, 74), ("age_75_79", 75, 79), ("age_80_plus", 80, 85)]
# The survey counts people in bands of its own, which make the same bands as above from 18 up and no finer ones below: the
# band, and the numbers of the survey's columns for men (the women's are 24 further on). Table B01001.
SURVEY_BANDS = {"age_under_18": (3, 6), "age_18_24": (7, 10), "age_25_34": (11, 12), "age_35_44": (13, 14), "age_45_54": (15, 16),
                "age_55_64": (17, 19), "age_65_74": (20, 22), "age_75_79": (23, 23), "age_80_plus": (24, 25)}
MEMBERS_REPO = "chrissoria/congress-members"  # who sits in Congress now, for the districts and states they sit for
PARTY_NAMES = {"Democrat": "Democrat", "Democratic": "Democrat", "Republican": "Republican", "Independent": "Independent"}
FEATURE_COLUMNS = ["density_per_sq_mi", "water_share", "urban_population_share", "rural_urban_code", "rural_urban_label",
                   *[band for band, _, _ in AGE_BANDS], "age_under_18", "age_year", "median_household_income", "gini_index", "median_home_value", "income_years",
                   "gdp_per_capita", "gdp_year", "violent_crime_rate", "property_crime_rate", "homicide_rate", "crime_year", *VOTE_COLUMNS]
WIKIDATA = "https://query.wikidata.org/sparql"
WORLD = "https://christophersoria.com/capitol-world/"

# What kind of government the Census Bureau's name for a place ends with.
GOVERNMENTS = ("city and borough", "consolidated government", "metropolitan government", "unified government", "urban county", "municipality",
               "borough", "village", "town", "city")

# How the way in to a body's world is written after the address of Capitol World.
WORLD_ADDRESS = {"capitol": "", "chamber": "?world=chamber&place={place}"}

PLACE_COLUMNS_START = ["place_id", "kind", "name", "census_name", "government", "parent_id", "state", "state_name", "county_id", "county_name", "counties",
                       "population", "population_2020", "population_year", "land_sq_mi", "water_sq_mi", "latitude", "longitude", "seat",
                       "joined_union", "union_order", "district", "district_session", "body_id",
                       "representative", "representative_party", "representative_id", "representative_since", "senators"]
PLACE_COLUMNS_END = ["flag_url", "seal_url", "website", "wikidata", "n_records", "n_ordinances", "n_resolutions", "n_bills", "n_meetings", "n_votes",
                     "records_from", "records_to", "datasets", "world_url"]
PLACE_COLUMNS = PLACE_COLUMNS_START + FEATURE_COLUMNS + PLACE_COLUMNS_END
DATASET_COLUMNS = ["place_id", "name", "state", "body_id", "repo", "what", "n_records", "n_ordinances", "n_resolutions", "n_meetings", "n_votes",
                   "records_from", "records_to", "world_url"]
BODY_COLUMNS = ["body_id", "place_id", "place", "place_kind", "state", "name", "body", "short", "room", "member_title", "seat_title", "timezone",
                "site", "site_url", "since", "datasets", "world", "world_url", "chamber_file", "map"]
BODIES_FILE = "world/bodies.json"
# The facts of each place as Capitol World reads them: index/US.json for the country, the states and the territories, and
# index/CA.json.gz for everything in one state. A legislature's districts are left out for now.
INDEX_COLUMNS = ["name", "kind", "parent_id", "population", "population_year", "land_sq_mi", "seat", "district", "district_session",
                 "representative", "representative_party", *FEATURE_COLUMNS]
INDEX_KINDS = ("county", "city", "community", "congressional district")


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


def ordinal(n):
    """52 as "52nd"."""
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def district_names(kind, code, state_name, census_name=""):
    """
    What a district is called: (the name people use, the Census Bureau's, and its number or name alone). `code` is the part
    of its Census code after the state's two digits; `census_name` is given for a legislature's districts, which states name
    in their own ways ("Assembly District 79", "4th Middlesex District", "State House District Hillsborough 01").
    """
    if kind != "congressional district":
        own = " ".join(word for word in census_name.split() if word.lower() not in DISTRICT_WORDS)
        return f"{state_name} {census_name}", census_name, own or census_name
    if code == "00":
        return f"{state_name}'s at-large congressional district", "Congressional District (at Large)", "At Large"
    if code == "98":  # the one member a territory or the District sends, who has no vote on the floor
        seat = "Resident Commissioner" if state_name == "Puerto Rico" else "Delegate"
        return f"{state_name}'s {seat.lower()} district", f"{seat} District (at Large)", "At Large"
    return f"{state_name}'s {ordinal(int(code))} congressional district", f"Congressional District {int(code)}", str(int(code))


def island_count(path):
    """The 2020 count of an island territory, from the first table of its census."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    head = next(index for index, row in enumerate(rows) if row and row[0].strip() == "Geographic area")
    column = [cell.strip() for cell in rows[head]].index("2020")
    return int(whole(next(row for row in rows[head + 1:] if row and row[0].strip())[column]))


def census_places(states, folder):
    """The country, and every state, county, incorporated place and named community of the states asked for, from the Census Bureau's files."""
    fips = {FIPS[state]: state for state in states if state in FIPS}
    territories = {TERRITORIES[state]: state for state in states if state in TERRITORIES}
    latest, base = f"POPESTIMATE{VINTAGE}", "ESTIMATESBASE2020"
    gaz_counties = {row["GEOID"]: row for row in rows_of(census_file("gaz_counties.zip", folder))}
    gaz_places = {row["GEOID"]: row for row in rows_of(census_file("gaz_places.zip", folder))}
    places, state_names, county_names = [], {}, {}

    def measured(gaz):
        return {"land_sq_mi": number(gaz.get("ALAND_SQMI")), "water_sq_mi": number(gaz.get("AWATER_SQMI")),
                "latitude": number(gaz.get("INTPTLAT")), "longitude": number(gaz.get("INTPTLONG"))} if gaz else {}

    for row in rows_of(census_file("states.csv", folder)):
        yearly = {"population": int(row[latest]), "population_2020": int(row[base]),
                  "by_year": {year: int(row[f"POPESTIMATE{year}"]) for year in range(2020, VINTAGE + 1)}} if row["SUMLEV"] in ("010", "040") else {}
        if row["SUMLEV"] == "010":  # the fifty states and the District; the territories are not counted in it
            places.append({"place_id": NATION, "kind": "nation", "name": row["NAME"], "census_name": row["NAME"], "government": "federal",
                           "state": "US", "state_name": row["NAME"], **yearly})
        elif row["SUMLEV"] == "040" and row["STATE"] in fips:
            state_names[row["STATE"]] = row["NAME"]
            district = fips[row["STATE"]] == "DC"
            places.append({"place_id": row["STATE"], "kind": "district" if district else "state", "name": row["NAME"], "census_name": row["NAME"],
                           "government": "federal district" if district else "state", "state": fips[row["STATE"]], "state_name": row["NAME"], **yearly})
        elif row["SUMLEV"] == "040" and row["STATE"] in territories:  # Puerto Rico is estimated each year as the states are
            state_names[row["STATE"]] = row["NAME"]
            places.append({"place_id": row["STATE"], "kind": "territory", "name": row["NAME"], "census_name": row["NAME"], "government": "territory",
                           "state": territories[row["STATE"]], "state_name": row["NAME"], **yearly})
    for code, state in territories.items():
        if any(place["place_id"] == code for place in places):
            continue
        count = island_count(census_file(f"islands_{state}.csv", folder))
        places.append({"place_id": code, "kind": "territory", "name": TERRITORY_NAMES[state], "census_name": TERRITORY_NAMES[state], "government": "territory",
                       "state": state, "state_name": TERRITORY_NAMES[state], "population": count, "population_2020": count, "counted": True})
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
        # "S" marks a community the estimates count as if it were a city (Honolulu); it comes with the other communities below.
        # The rest are governments, among them the part of a merged city and county that is in no smaller city (Nashville).
        if row["SUMLEV"] != "162" or row["STATE"] not in fips or row["FUNCSTAT"] == "S":
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
    people = survey_values(census_file(f"acs{ACS_YEAR}_population.dat", folder))
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
    # The districts of Congress and of each legislature, as last drawn. The Bureau measures them, and the survey counts them.
    codes = {**fips, **territories}
    for district in DISTRICTS:
        for gaz in rows_of(census_file(district["file"], folder)):
            state = gaz["GEOID"][:2]
            if state not in codes or state not in state_names or "Z" in gaz["GEOID"]:  # "ZZ" is land the districts do not cover
                continue
            name, census_name, own = district_names(district["kind"], gaz["GEOID"][2:], state_names[state], gaz.get("NAME", ""))
            geoid = district["prefix"] + gaz["GEOID"]
            count = people.get(geoid)
            places.append({"place_id": geoid, "kind": district["kind"], "name": name, "census_name": census_name, "government": "none (electoral district)",
                           "state": codes[state], "state_name": state_names[state], "district": own, "district_session": district["session"],
                           "population": int(count) if count is not None else None, "population_2020": None, "survey": True, **measured(gaz)})
    table = pd.DataFrame(places)
    # A state's area is its counties' together (Puerto Rico's, its municipalities'); the gazetteer has no file for states. The island
    # territories have no counties in it, so no area yet. The country's is that of the states and the District, if all are here.
    for column, measure in (("land_sq_mi", "ALAND_SQMI"), ("water_sq_mi", "AWATER_SQMI")):
        sums = {}
        for geoid, gaz in gaz_counties.items():
            if number(gaz.get(measure)) is not None:
                sums[geoid[:2]] = sums.get(geoid[:2], 0) + number(gaz[measure])
        if all(code in fips for code in FIPS.values()):
            sums[NATION] = sum(sums.get(code, 0) for code in FIPS.values())
        whole_rows = table["kind"].isin((*STATE_KINDS, "nation"))
        table.loc[whole_rows, column] = table.loc[whole_rows, "place_id"].map(sums).round(1)
    # A community's people are the survey's count over its five years, and an island territory's the 2020 census's, not the
    # yearly estimate the others have.
    table["population_year"] = VINTAGE
    for column, year in (("survey", ACS_YEAR), ("counted", 2020)):
        if column in table.columns:
            table.loc[table[column].eq(True), "population_year"] = year
    # What each place is part of: a city its county (the one most of its people live in), a county its state, a state the country.
    county = table["county_id"] if "county_id" in table.columns else pd.Series(None, index=table.index)
    table["parent_id"] = county.where(county.notna(), table["place_id"].str[:2])
    drawn = table["kind"].isin(DISTRICT_KINDS)
    table.loc[drawn, "parent_id"] = table.loc[drawn, "place_id"].str[9:11]
    table.loc[table["kind"].isin(STATE_KINDS), "parent_id"] = NATION
    table.loc[table["kind"] == "nation", "parent_id"] = None
    every = {**FIPS, **TERRITORIES}
    for column, index in (("seat", 0), ("joined_union", 1), ("union_order", 2)):
        known = {(NATION if state == "US" else every[state]): facts[index] for state, facts in UNION.items()}
        table[column] = table["place_id"].map(known) if column == "seat" else table["place_id"].map(known).astype("Int64")
    return table.drop(columns=[column for column in ("survey", "counted") if column in table.columns])


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


def president_file(folder):
    """The returns for president by state, fetched once and kept. None if they cannot be had."""
    path = Path(folder) / "president.csv"
    if path.exists():
        return path
    try:
        files = fetch(ELECTION_DATASET, tries=2).json()["data"]["latestVersion"]["files"]
        found = next(file["dataFile"]["id"] for file in files if file["dataFile"]["filename"].endswith("-president.csv"))
        body = fetch(ELECTION_FILE.format(id=found), tries=2).content
    except Exception as e:
        log.warning(f"The returns for president were not fetched: {type(e).__name__}: {e}")
        return None
    if not body.lstrip(b"\xef\xbb\xbf").startswith(b"year,"):
        log.warning("The returns for president are not the file expected")
        return None
    path.write_bytes(body)
    return path


def votes_by_state(path, year=ELECTION_YEAR):
    """How each state voted for president that year: {postal code: {party: votes, ..., "cast": every vote for anyone}}."""
    found = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = re.sub(r"\s+", " ", row.get("candidate") or "").strip().upper()
            votes = whole(row.get("candidatevotes"))
            if row.get("year") != str(year) or votes is None or re.match(NOT_A_VOTE, name):
                continue
            state = found.setdefault(row["state_po"], {"cast": 0.0, "other": 0.0, **{party: 0.0 for party in VOTE_PARTIES}})
            party = next((party for party, pattern in VOTE_PARTIES.items() if re.search(pattern, name)), "other")
            state[party] += votes
            state["cast"] += votes
    return found


def vote_shares(votes):
    """One place's votes as the columns of the table: each party's share of every vote cast, and how many were cast."""
    if not votes or not votes["cast"]:
        return {}
    shares = {f"vote_{party}_{ELECTION_YEAR}": round(count / votes["cast"], 4) for party, count in votes.items() if party != "cast"}
    return {**shares, f"votes_cast_{ELECTION_YEAR}": int(votes["cast"])}


def whole(text):
    """'39,431,263' as a number; None for a blank."""
    digits = re.sub(r"[^\d.]", "", str(text or ""))
    return float(digits) if digits else None


def age_tables(folder, wanted):
    """For each state, and the country as all of them together: its people by single year of age, and the share of them in each of AGE_BANDS."""
    counts = {}
    for row in rows_of(source_file("state_ages.csv", folder)):
        if row["SUMLEV"] == "040" and row["SEX"] == "0" and row["ORIGIN"] == "0":
            for code in (row["STATE"], NATION):
                if code in wanted:
                    ages = counts.setdefault(code, {})
                    ages[int(row["AGE"])] = ages.get(int(row["AGE"]), 0) + int(row[f"POPESTIMATE{VINTAGE}"])
    shares = {}
    for state, ages in counts.items():
        total = sum(ages.values())
        shares[state] = {band: round(sum(people for age, people in ages.items() if first <= age <= last) / total, 4) for band, first, last in AGE_BANDS}
    single = pd.DataFrame([{"place_id": state, "age": age, "people": people} for state, ages in sorted(counts.items()) for age, people in sorted(ages.items())],
                          columns=["place_id", "age", "people"])
    return shares, single


def survey_values(path):
    """
    One of the survey's tables: the estimate for the country and each state, county and place, by the Census code, and for
    each district by its full code, which says whose lines it was counted on.
    """
    values = {}
    with open(path, encoding="latin-1") as f:
        next(f)
        for line in f:
            geo, estimate = line.split("|", 2)[:2]
            key = survey_key(geo)
            if key is None:
                continue
            found = number(estimate)
            values[key] = found if found is not None and found >= 0 else None  # a large negative number stands for "not available"
    return values


SURVEY_KINDS = {"0100000US": 0, "0400000US": 2, "0500000US": 5, "1600000US": 7}
SURVEY_DISTRICTS = {district["prefix"] for district in DISTRICTS}


def survey_key(geo):
    """The place_id of one of the survey's rows, or None if it is not a place kept here."""
    if geo[:9] in SURVEY_KINDS and len(geo) == 9 + SURVEY_KINDS[geo[:9]]:
        return geo[9:] or NATION
    return geo if geo[:9] in SURVEY_DISTRICTS else None


def survey_ages(path):
    """The share of each place's people in each of SURVEY_BANDS, from the survey's table of people by sex and age."""
    shares = {}
    with open(path, encoding="latin-1") as f:
        head = next(f).rstrip("\n").split("|")
        at = {name: index for index, name in enumerate(head)}
        column = lambda n: at[f"B01001_E{n:03d}"]
        bands = {band: [column(n + shift) for n in range(first, last + 1) for shift in (0, 24)] for band, (first, last) in SURVEY_BANDS.items()}
        total = column(1)
        for line in f:
            key = survey_key(line[:line.index("|")])
            if key is None:
                continue
            cells = line.rstrip("\n").split("|")
            people = number(cells[total])
            if not people or people < 0:
                continue
            shares[key] = {band: round(sum(max(number(cells[index]) or 0, 0) for index in columns) / people, 4) for band, columns in bands.items()}
    return shares


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
    states = set(places.loc[places["kind"].isin((*STATE_KINDS, "nation")), "place_id"])
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
    is_state = places["kind"].isin(STATE_KINDS)
    places.loc[is_state, "rural_urban_code"] = places.loc[is_state, "place_id"].map(weighted.round(2))

    shares, single = age_tables(folder, states)
    for band, _, _ in AGE_BANDS:
        places[band] = places["place_id"].map(lambda code: shares.get(code, {}).get(band))
    places["age_year"] = places["place_id"].map(lambda code: VINTAGE if code in shares else None).astype("Int64")
    # Below the state the Bureau's estimates have no single years of age. The survey has bands, which give the same ones from
    # 18 up and one for everyone younger; the four bands under 18 stay empty there.
    young = [band for band, _, last in AGE_BANDS if last < 18]
    places["age_under_18"] = places[young].sum(axis=1, min_count=len(young)).round(4)
    surveyed_ages = survey_ages(source_file(f"acs{ACS_YEAR}_ages.dat", folder))
    unaged = places["age_year"].isna()
    for band in SURVEY_BANDS:
        places.loc[unaged, band] = places.loc[unaged, "place_id"].map(lambda code: surveyed_ages.get(code, {}).get(band))
    places.loc[unaged & places["place_id"].isin(surveyed_ages), "age_year"] = ACS_YEAR

    income = survey_values(source_file(f"acs{ACS_YEAR}_income.dat", folder))
    gini = survey_values(source_file(f"acs{ACS_YEAR}_gini.dat", folder))
    homes = survey_values(source_file(f"acs{ACS_YEAR}_home_value.dat", folder))
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

    # How each state voted for president, and the country as all of them together. No one source has it for counties or cities.
    returns = president_file(folder)
    by_state = votes_by_state(returns) if returns else {}
    if by_state:
        by_state["US"] = {key: sum(state[key] for state in by_state.values()) for key in next(iter(by_state.values()))}
    voted = places["state"].where(places["kind"].isin((*STATE_KINDS, "nation"))).map(lambda state: vote_shares(by_state.get(state)))
    for column in VOTE_COLUMNS:
        places[column] = voted.map(lambda shares: shares.get(column) if isinstance(shares, dict) else None)
    places[VOTE_COLUMNS[-1]] = places[VOTE_COLUMNS[-1]].astype("Int64")
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
    codes = {**FIPS, **TERRITORIES}

    def keep(code, row):
        entry = facts.setdefault(code, {})
        entry.setdefault("wikidata", row["item"].rsplit("/", 1)[-1])
        for column, key in (("flag_url", "flag"), ("seal_url", "seal"), ("website", "site"), ("seat", "seatLabel")):
            if row.get(key) and not entry.get(column):
                entry[column] = commons_url(row[key]) if key in ("flag", "seal") else row[key]
        if re.fullmatch(r"Q\d+", entry.get("seat") or ""):  # a seat with no name in English comes back as its number
            del entry["seat"]

    extras = "OPTIONAL { ?item wdt:P41 ?flag } OPTIONAL { ?item wdt:P158 ?seal } OPTIONAL { ?item wdt:P856 ?site } OPTIONAL { ?item wdt:P36 ?seat }"
    labels = 'SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }'
    for row in wikidata_rows(f'SELECT ?item ?flag ?seal ?site WHERE {{ VALUES ?item {{ wd:Q30 }} {extras} }}'):
        keep(NATION, row)
    for state in states:
        code = codes[state]
        for row in wikidata_rows(f'SELECT ?item ?flag ?seal ?site ?seatLabel WHERE {{ ?item wdt:P5087 "{code}" . {extras} {labels} }}'):
            keep(code, row)
        if state in TERRITORIES:
            time.sleep(1)
            continue
        for row in wikidata_rows(f'SELECT ?item ?fips ?flag ?seal ?site ?seatLabel WHERE {{ ?item wdt:P882 ?fips . FILTER(STRSTARTS(?fips, "{code}")) {extras} {labels} }}'):
            keep(row["fips"], row)
        # A place's code is written "06-66000" there.
        for row in wikidata_rows(f'SELECT ?item ?fips ?flag ?seal ?site WHERE {{ ?item wdt:P774 ?fips . FILTER(STRSTARTS(?fips, "{code}-")) '
                                 f'OPTIONAL {{ ?item wdt:P41 ?flag }} OPTIONAL {{ ?item wdt:P158 ?seal }} OPTIONAL {{ ?item wdt:P856 ?site }} }}'):
            keep(row["fips"].replace("-", ""), row)
        time.sleep(2)
    return facts


def members_now():
    """Everyone sitting in Congress now, from the members dataset here. None if it cannot be read."""
    try:
        from huggingface_hub import hf_hub_download
        table = pd.read_parquet(hf_hub_download(MEMBERS_REPO, "data/members.parquet", repo_type="dataset", token=bills.HF_TOKEN))
        return table[table["status"] == "serving"]
    except Exception as e:
        log.warning(f"The members of Congress were not read: {type(e).__name__}: {e}")
        return None


def add_members(places, members):
    """Who sits in Congress for each place: a district's representative on its row, and a state's senators on the state's."""
    places = places.copy()
    for column in ("representative", "representative_party", "representative_id", "representative_since", "senators"):
        places[column] = None
    if members is None or not len(members):
        return places
    codes = {**FIPS, **TERRITORIES}
    prefix = next(district["prefix"] for district in DISTRICTS if district["kind"] == "congressional district")
    at = {place_id: index for index, place_id in zip(places.index, places["place_id"])}
    senators = {}
    for member in members.sort_values("current_service_start").to_dict("records"):
        state = codes.get(member["state"])
        party = PARTY_NAMES.get(member["party"], member["party"])
        if not state:
            continue
        if member["chamber"] == "Senate":
            senators.setdefault(state, []).append({"id": member["bioguide_id"], "name": member["name"], "party": party, "since": member["current_service_start"]})
            continue
        # A state's districts are numbered from 1, or 00 if it has one; the District's and a territory's one seat is 98.
        seat = "98" if member["state"] == "DC" or member["state"] in TERRITORIES else f"{int(member['district'] or 0):02d}"
        row = at.get(prefix + state + seat)
        if row is not None:
            places.loc[row, ["representative", "representative_party", "representative_id", "representative_since"]] = [
                member["name"], party, member["bioguide_id"], member["current_service_start"]]
    for state, sitting in senators.items():
        if state in at:
            places.loc[at[state], "senators"] = json.dumps(sitting, ensure_ascii=False)
    return places


def kept_facts(states, folder):
    """What Wikidata says of each place, asked once and kept beside the Census files: asking takes ten minutes."""
    path = Path(folder) / "wikidata.json"
    if path.exists():
        kept = json.loads(path.read_text(encoding="utf-8"))
        if set(states) <= set(kept["states"]):
            return kept["facts"]
    facts = wikidata_facts(states)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"states": sorted(states), "facts": facts}, ensure_ascii=False), encoding="utf-8")
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
        kinds = records["doc_type"].str.lower().value_counts() if "doc_type" in records.columns else {}
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


def sources_of(bodies):
    """Each dataset of each body, with the body it belongs to and the place that body governs."""
    return [{**dataset, "body_id": body["id"], "place_id": body["place"], "world": body.get("world")} for body in bodies for dataset in body.get("datasets", [])]


def world_url(world, place_id):
    """The address of a body's world in Capitol World, or None if it has none."""
    if not world:
        return None
    return WORLD + WORLD_ADDRESS.get(world, f"?world={world}").format(place=place_id)


def datasets_table(places, sources, count=count_source):
    """One row per body and dataset with records of the place it governs."""
    rows = []
    known = places.set_index("place_id")
    for source in sources:
        if source["place_id"] not in known.index:
            continue
        counted = count(source)
        if counted is None:
            continue
        place = known.loc[source["place_id"]]
        rows.append({"place_id": source["place_id"], "name": place["name"], "state": place["state"], "body_id": source.get("body_id"),
                     "repo": source["repo"], "what": source["what"], **counted, "world_url": world_url(source.get("world"), source["place_id"])})
    table = pd.DataFrame(rows, columns=DATASET_COLUMNS)
    for column in ("n_records", "n_ordinances", "n_resolutions", "n_meetings", "n_votes"):
        table[column] = table[column].astype("Int64")
    return table


def map_address(place):
    """Where a place is on the map of the United States, as Capitol World's address has it: "#county=06073", "#city=06073.0666000"."""
    if place["kind"] == "county":
        return f"#county={place['place_id']}"
    if place["kind"] in ("city", "community") and place.get("county_id"):
        return f"#city={place['county_id']}.{place['place_id']}"
    if place["kind"] in STATE_KINDS:
        return f"#state={place['state']}"
    return None


def bodies_table(places, bodies):
    """One row per body: whose it is, what it and its members are called, where its records are, and the way in to its room if it has one."""
    known = places.set_index("place_id")
    rows = []
    for body in bodies:
        if body["place"] not in known.index:
            continue
        place = known.loc[body["place"]]
        chamber = body.get("chamber")
        rows.append({
            "body_id": body["id"], "place_id": body["place"], "place": place["name"], "place_kind": place["kind"], "state": place["state"],
            "name": body["name"], "body": body["body"], "short": body.get("short"), "room": body.get("room"),
            "member_title": body.get("member"), "seat_title": body.get("seat"), "timezone": body.get("timezone"),
            "site": body.get("site"), "site_url": body.get("url"), "since": body.get("since"),
            "datasets": json.dumps([dataset["repo"] for dataset in body.get("datasets", [])]),
            "world": body.get("world"), "world_url": world_url(body.get("world"), body["place"]),
            "chamber_file": (f"https://huggingface.co/datasets/{chamber['repo']}/resolve/main/{chamber.get('file', 'world/chamber.json.gz')}"
                             if chamber else None),
            "map": map_address({**place.to_dict(), "place_id": body["place"]}),
        })
    return pd.DataFrame(rows, columns=BODY_COLUMNS)


def bodies_file(table, today=None):
    """The bodies as Capitol World reads them: the same rows, with nothing left in that is empty."""
    listed = [{key: value for key, value in row.items() if value is not None and not (isinstance(value, float) and pd.isna(value))}
              for row in table.to_dict("records")]
    for body in listed:
        body["datasets"] = json.loads(body["datasets"])
    return {"schema": 1, "generated_at": today or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "bodies": listed}


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
        other = held[~held["what"].isin(["bills", "votes by member"])]
        for column in ("n_ordinances", "n_resolutions", "n_meetings", "n_votes"):
            if held[column].notna().any():
                places.loc[row, column] = int(held[column].max())
        if len(other):
            places.loc[row, "n_records"] = int(other["n_records"].max())
        if len(bills_held):
            places.loc[row, "n_bills"] = int(bills_held["n_records"].sum())
        votes_held = held[held["what"] == "votes by member"]  # a dataset whose rows are the votes themselves
        if len(votes_held):
            places.loc[row, "n_votes"] = max(int(votes_held["n_records"].sum()), int(held["n_votes"].max()) if held["n_votes"].notna().any() else 0)
        places.loc[row, "records_from"] = held["records_from"].dropna().min() if held["records_from"].notna().any() else None
        places.loc[row, "records_to"] = held["records_to"].dropna().max() if held["records_to"].notna().any() else None
        places.loc[row, "datasets"] = json.dumps(sorted(held["repo"]))
        worlds = held["world_url"].dropna()
        places.loc[row, "world_url"] = worlds.iloc[-1] if len(worlds) else None
    return places


def build(states, folder, facts=None, bodies=None, count=count_source, members=members_now):
    places = census_places(states, folder)
    facts = kept_facts(states, folder) if facts is None else facts
    for column in ("flag_url", "seal_url", "website", "wikidata"):
        places[column] = places["place_id"].map(lambda code: facts.get(code, {}).get(column))
    # A state's capital is given above. A county's seat is Wikidata's.
    places["seat"] = places["seat"].where(places["seat"].notna(), places["place_id"].map(lambda code: facts.get(code, {}).get("seat")))
    places, ages = add_features(places, folder)
    places = add_members(places, members() if callable(members) else members)
    bodies = registry.read_bodies() if bodies is None else bodies
    datasets = datasets_table(places, sources_of(bodies), count)
    places = add_records(places, datasets)
    # The body a district elects to: Congress, or its state's legislature if that is among the bodies here.
    home = {body["place"]: body["id"] for body in bodies}
    places["body_id"] = None
    in_congress = places["kind"] == "congressional district"
    places.loc[in_congress, "body_id"] = home.get(NATION)
    in_legislature = places["kind"].isin(DISTRICT_KINDS) & ~in_congress
    places.loc[in_legislature, "body_id"] = places.loc[in_legislature, "parent_id"].map(home)
    order = {"nation": 0, "state": 1, "district": 1, "territory": 1, "county": 2, "city": 3, "community": 4,
             **{kind: 5 + n for n, kind in enumerate(DISTRICT_KINDS)}}
    places = places.assign(level=places["kind"].map(order), first=places["kind"] != "nation").sort_values(["first", "state", "level", "name"])
    places = places.drop(columns=["level", "first"]).reindex(columns=PLACE_COLUMNS).reset_index(drop=True)
    for column in ("population", "population_2020", "population_year", "joined_union", "union_order"):
        places[column] = places[column].astype("Int64")
    return places, datasets, ages, bodies_table(places, bodies)


def index_of(rows):
    """Places as a file the app reads: the columns once, then each place's values in that order, by its place_id."""
    def plain(value):
        if value is None or (not isinstance(value, str) and pd.isna(value)):
            return None
        return value if isinstance(value, str) else int(value) if float(value).is_integer() else round(float(value), 4)
    return {"schema": 1, "columns": INDEX_COLUMNS,
            "places": {place_id: [plain(value) for value in values] for place_id, *values in rows[["place_id", *INDEX_COLUMNS]].itertuples(index=False)}}


def write_index(places, out_dir):
    """Write index/US.json and one index/<state>.json.gz for each state. Returns how many files."""
    import gzip
    folder = Path(out_dir) / "index"
    folder.mkdir(parents=True, exist_ok=True)
    top = places[places["kind"].isin((*STATE_KINDS, "nation"))]
    (folder / "US.json").write_text(json.dumps(index_of(top), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    written = 1
    for state, rows in places[places["kind"].isin(INDEX_KINDS)].groupby("state"):
        with gzip.open(folder / f"{state}.json.gz", "wt", encoding="utf-8") as f:
            json.dump(index_of(rows), f, ensure_ascii=False, separators=(",", ":"))
        written += 1
    return written


def upload(out_dir, with_card):
    from huggingface_hub import CommitOperationAdd, HfApi
    api = HfApi(token=bills.HF_TOKEN)
    api.create_repo(HF_REPO, repo_type="dataset", exist_ok=True)
    problem = bills.hf_write_problem(HF_REPO)
    if problem:
        log.error(f"Places not uploaded: {problem}")
        return False
    operations = [CommitOperationAdd(path_in_repo=f"data/{name}.parquet", path_or_fileobj=str(out_dir / f"{name}.parquet"))
                  for name in ("places", "bodies", "datasets", "ages")]
    operations.append(CommitOperationAdd(path_in_repo=BODIES_FILE, path_or_fileobj=str(out_dir / BODIES_FILE)))
    for path in sorted((out_dir / "index").glob("*.json*")):
        operations.append(CommitOperationAdd(path_in_repo=f"index/{path.name}", path_or_fileobj=str(path)))
    if (with_card or "README.md" not in set(api.list_repo_files(HF_REPO, repo_type="dataset"))) and CARD_FILE.exists():
        operations.append(CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=str(CARD_FILE)))
    api.create_commit(repo_id=HF_REPO, repo_type="dataset", operations=operations,
                      commit_message=f"Update places ({datetime.now(timezone.utc).strftime('%Y-%m-%d')})")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the table of states, counties and cities")
    parser.add_argument("--states", nargs="+", default=STATES, help="postal codes of the states and territories to build")
    parser.add_argument("--out", default=str(OUT_DIR), help="directory to write the tables into, and to keep the Census files in")
    parser.add_argument("--no-upload", action="store_true", help="write the tables but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    unknown = [state for state in args.states if state not in FIPS and state not in TERRITORIES]
    if unknown:
        parser.error(f"not a state: {', '.join(unknown)}")
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the tables only")
    out_dir = Path(args.out)
    try:
        places, datasets, ages, bodies = build(args.states, out_dir)
    except Exception as e:
        log.error(f"Places not built: {type(e).__name__}: {e}")
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    places.to_parquet(out_dir / "places.parquet", index=False)
    datasets.to_parquet(out_dir / "datasets.parquet", index=False)
    ages.to_parquet(out_dir / "ages.parquet", index=False)
    bodies.to_parquet(out_dir / "bodies.parquet", index=False)
    (out_dir / BODIES_FILE).parent.mkdir(parents=True, exist_ok=True)
    (out_dir / BODIES_FILE).write_text(json.dumps(bodies_file(bodies), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    write_index(places, out_dir)
    pushed = False if args.no_upload else upload(out_dir, args.write_card)
    kinds = places["kind"].value_counts()
    log.info(f"RESULT: us-places states={int(kinds.get('state', 0))} territories={int(kinds.get('territory', 0))} "
             f"counties={int(kinds.get('county', 0))} cities={int(kinds.get('city', 0))} communities={int(kinds.get('community', 0))} "
             f"districts={'+'.join(str(int(kinds.get(kind, 0))) for kind in DISTRICT_KINDS)} "
             f"bodies={len(bodies)} rooms={int(bodies['world'].notna().sum())} "
             f"with_flag={int(places['flag_url'].notna().sum())} with_seal={int(places['seal_url'].notna().sum())} "
             f"with_income={int(places['median_household_income'].notna().sum())} with_gdp={int(places['gdp_per_capita'].notna().sum())} "
             f"with_ages={int(places['age_year'].notna().sum())} with_crime={int(places['crime_year'].notna().sum())} "
             f"with_votes={int(places[VOTE_COLUMNS[-1]].notna().sum())} with_adult_ages={int(places['age_80_plus'].notna().sum())} "
             f"with_representative={int(places['representative'].notna().sum())} with_senators={int(places['senators'].notna().sum())} "
             f"with_records={int(places['datasets'].notna().sum())} datasets={len(datasets)} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(main())
