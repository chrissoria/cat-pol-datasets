"""build_places makes one row for each state, county and city, and adds up what the other datasets hold of each."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import build_places as places


def test_a_census_name_is_the_name_people_use_and_the_kind_of_government():
    assert places.split_name("San Diego city") == ("San Diego", "city")
    assert places.split_name("Paradise town") == ("Paradise", "town")
    assert places.split_name("State College borough") == ("State College", "borough")
    assert places.split_name("Nashville-Davidson metropolitan government (balance)") == ("Nashville-Davidson", "metropolitan government")
    assert places.split_name("Carson City") == ("Carson City", "")


def test_a_commons_file_is_linked_over_https():
    assert places.commons_url("http://commons.wikimedia.org/wiki/Special:FilePath/Flag%20of%20California.svg").startswith("https://commons.")
    assert places.commons_url("") is None


def table():
    return pd.DataFrame([
        {"place_id": "06", "kind": "state", "name": "California", "state": "CA"},
        {"place_id": "06073", "kind": "county", "name": "San Diego County", "state": "CA"},
        {"place_id": "0666000", "kind": "city", "name": "San Diego", "state": "CA"},
        {"place_id": "4865000", "kind": "city", "name": "San Antonio", "state": "TX"},
    ])


SOURCES = [
    {"state": "CA", "place": "California", "repo": "x/bills", "records": "", "what": "bills", "date": "date", "world": "?world=california"},
    {"state": "CA", "place": "San Diego", "repo": "x/ordinances", "records": "", "what": "ordinances and resolutions", "date": "date"},
    {"state": "CA", "place": "San Diego", "repo": "x/council", "records": "", "what": "items", "date": "date", "world": "?world=chamber&place=0666000"},
    {"state": "CA", "place": "Nowhere", "repo": "x/none", "records": "", "what": "items", "date": "date"},
    {"state": "CA", "place": "San Diego County", "repo": "x/unreadable", "records": "", "what": "items", "date": "date"},
]
COUNTS = {
    "x/bills": {"n_records": 75808, "n_ordinances": None, "n_resolutions": None, "records_from": "1999-01-01", "records_to": "2026-09-30", "n_meetings": None, "n_votes": 900},
    "x/ordinances": {"n_records": 88319, "n_ordinances": 8478, "n_resolutions": 79832, "records_from": "1905-02-06", "records_to": "2026-10-07", "n_meetings": None, "n_votes": None},
    "x/council": {"n_records": 8700, "n_ordinances": 1185, "n_resolutions": 5230, "records_from": "2010-01-05", "records_to": "2026-10-06", "n_meetings": 647, "n_votes": 78000},
}


def test_each_dataset_is_a_row_against_its_place_and_one_that_cannot_be_read_is_left_out():
    found = places.datasets_table(table(), SOURCES, lambda source: COUNTS.get(source["repo"]))
    assert found["repo"].tolist() == ["x/bills", "x/ordinances", "x/council"] and found["place_id"].tolist() == ["06", "0666000", "0666000"]
    assert found.loc[2, "world_url"].endswith("?world=chamber&place=0666000") and pd.isna(found.loc[1, "world_url"])


def test_a_places_datasets_are_put_together_on_its_row():
    given = table()
    held = places.add_records(given, places.datasets_table(given, SOURCES, lambda source: COUNTS.get(source["repo"]))).set_index("place_id")
    city = held.loc["0666000"]
    assert (city["n_records"], city["n_ordinances"], city["n_resolutions"], city["n_meetings"], city["n_votes"]) == (88319, 8478, 79832, 647, 78000)
    assert (city["records_from"], city["records_to"]) == ("1905-02-06", "2026-10-07") and city["datasets"] == '["x/council", "x/ordinances"]'
    assert city["world_url"].endswith("place=0666000")
    state = held.loc["06"]
    assert state["n_bills"] == 75808 and pd.isna(state["n_records"]) and state["world_url"].endswith("?world=california")
    assert pd.isna(held.loc["06073", "n_records"]) and held.loc["4865000", "datasets"] is None


def test_the_age_bands_take_in_every_year_of_age_once():
    covered = [age for _, first, last in places.AGE_BANDS for age in range(first, last + 1)]
    assert covered == list(range(0, 86)) and places.AGE_BANDS[2] == ("age_5_12", 5, 12)


def test_a_survey_table_gives_states_counties_and_places_and_leaves_out_what_is_not_available(tmp_path):
    path = tmp_path / "table.dat"
    path.write_text("GEO_ID|B19013_E001|B19013_M001\n0100000US|78538|176\n0400000US06|96334|300\n0500000US06073|102285|900\n"
                    "1600000US0666000|104321|1200\n1600000US0600135|-666666666|-222222222\n1400000US06073000100|50000|9\n")
    assert places.survey_values(path) == {"06": 96334.0, "06073": 102285.0, "0666000": 104321.0, "0600135": None}
