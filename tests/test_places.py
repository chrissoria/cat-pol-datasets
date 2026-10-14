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
        {"place_id": "0666000", "kind": "city", "name": "San Diego", "state": "CA", "county_id": "06073"},
        {"place_id": "4865000", "kind": "city", "name": "San Antonio", "state": "TX", "county_id": "48029"},
    ])


BODIES = [
    {"id": "ca-legislature", "place": "06", "name": "California State Legislature", "body": "Legislature", "world": "california",
     "datasets": [{"repo": "x/bills", "records": "", "what": "bills", "date": "date"}]},
    {"id": "sd-council", "place": "0666000", "name": "San Diego City Council", "body": "City Council", "short": "the Council", "member": "Councilmember",
     "world": "chamber", "chamber": {"repo": "x/council", "folder": "sdcouncil", "members": "members"},
     "datasets": [{"repo": "x/ordinances", "records": "", "what": "ordinances and resolutions", "date": "date"},
                  {"repo": "x/council", "records": "", "what": "items", "date": "date"}]},
    {"id": "nowhere-council", "place": "0699999", "name": "Nowhere City Council", "body": "City Council",
     "datasets": [{"repo": "x/none", "records": "", "what": "items", "date": "date"}]},
    {"id": "sd-county", "place": "06073", "name": "San Diego County Board of Supervisors", "body": "Board of Supervisors",
     "datasets": [{"repo": "x/unreadable", "records": "", "what": "items", "date": "date"}]},
]
SOURCES = places.sources_of(BODIES)
COUNTS = {
    "x/bills": {"n_records": 75808, "n_ordinances": None, "n_resolutions": None, "records_from": "1999-01-01", "records_to": "2026-09-30", "n_meetings": None, "n_votes": 900},
    "x/ordinances": {"n_records": 88319, "n_ordinances": 8478, "n_resolutions": 79832, "records_from": "1905-02-06", "records_to": "2026-10-07", "n_meetings": None, "n_votes": None},
    "x/council": {"n_records": 8700, "n_ordinances": 1185, "n_resolutions": 5230, "records_from": "2010-01-05", "records_to": "2026-10-06", "n_meetings": 647, "n_votes": 78000},
}


def test_each_dataset_is_a_row_against_its_place_and_one_that_cannot_be_read_is_left_out():
    found = places.datasets_table(table(), SOURCES, lambda source: COUNTS.get(source["repo"]))
    assert found["repo"].tolist() == ["x/bills", "x/ordinances", "x/council"] and found["place_id"].tolist() == ["06", "0666000", "0666000"]
    assert found["body_id"].tolist() == ["ca-legislature", "sd-council", "sd-council"]
    assert found.loc[2, "world_url"].endswith("?world=chamber&place=0666000") and found.loc[0, "world_url"].endswith("?world=california")


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


def test_a_survey_table_gives_the_country_states_counties_and_places_and_leaves_out_what_is_not_available(tmp_path):
    path = tmp_path / "table.dat"
    path.write_text("GEO_ID|B19013_E001|B19013_M001\n0100000US|78538|176\n0400000US06|96334|300\n0500000US06073|102285|900\n"
                    "1600000US0666000|104321|1200\n1600000US0600135|-666666666|-222222222\n1400000US06073000100|50000|9\n"
                    "5001900US0652|98000|2000\n5001800US0652|91000|2000\n610U900US06039|88000|3000\n04000A0US06|1|1\n")
    assert places.survey_values(path) == {"00": 78538.0, "06": 96334.0, "06073": 102285.0, "0666000": 104321.0, "0600135": None,
                                          "5001900US0652": 98000.0, "610U900US06039": 88000.0}  # a district drawn for another Congress is not this one


def test_a_body_is_a_row_with_its_place_its_room_and_the_way_in():
    found = places.bodies_table(table(), BODIES).set_index("body_id")
    assert list(found.index) == ["ca-legislature", "sd-council", "sd-county"]  # a body of a place that is not in the table is left out
    council = found.loc["sd-council"]
    assert (council["place"], council["place_kind"], council["member_title"]) == ("San Diego", "city", "Councilmember")
    assert council["world_url"].endswith("?world=chamber&place=0666000") and council["map"] == "#city=06073.0666000"
    assert council["chamber_file"] == "https://huggingface.co/datasets/x/council/resolve/main/world/chamber.json.gz"
    assert council["datasets"] == '["x/ordinances", "x/council"]'
    county = found.loc["sd-county"]
    assert county["map"] == "#county=06073" and county["world"] is None and county["chamber_file"] is None
    assert found.loc["ca-legislature", "map"] == "#state=CA"
    # A county board's room is a file of its own in the one dataset of county boards.
    board = {**BODIES[1], "chamber": {"repo": "x/boards", "tables": "raw/fresno", "file": "world/fresno/chamber.json.gz", "members": "members"}}
    assert places.bodies_table(table(), [board])["chamber_file"].tolist() == ["https://huggingface.co/datasets/x/boards/resolve/main/world/fresno/chamber.json.gz"]


def test_the_file_the_app_reads_lists_the_bodies_and_leaves_out_what_is_empty():
    file = places.bodies_file(places.bodies_table(table(), BODIES), today="2026-10-11T00:00:00Z")
    assert file["schema"] == 1 and [body["body_id"] for body in file["bodies"]] == ["ca-legislature", "sd-council", "sd-county"]
    county = file["bodies"][2]
    assert "world" not in county and "room" not in county and county["datasets"] == ["x/unreadable"]


def test_an_island_territorys_count_is_read_from_its_census_table(tmp_path):
    path = tmp_path / "guam.csv"
    path.write_text('\ufeffPopulation of Guam:  2010 and 2020,,,,\n,,,,\n,Population,,"Change \n(2020 less 2010)",\nGeographic area,2010,2020,Number,Percent\n'
                    ', ,,,\nGuam,"159,358","153,836","-5,522",-3.5\n,,,,\nDededo,"44,943","44,908",-35,-0.1\n', encoding="utf-8")
    assert places.island_count(path) == 153836


def test_the_bodies_listed_here_can_be_read_and_each_names_a_place_and_its_datasets():
    listed = places.registry.read_bodies()
    assert len({body["id"] for body in listed}) == len(listed)
    for body in listed:
        assert body["place"].isdigit() and len(body["place"]) in (2, 5, 7) and body["name"] and body["body"]
        assert all(dataset["repo"] and dataset["records"] and dataset["what"] and dataset["date"] for dataset in body["datasets"])
        if body.get("world") == "chamber":
            assert body["chamber"]["repo"] and all(body.get(key) for key in ("short", "room", "member", "seat", "timezone", "site", "url", "since"))


RETURNS = """year,state,state_po,office,candidate,party_detailed,writein,candidatevotes,totalvotes
2020,NEW YORK,NY,US PRESIDENT,"TRUMP, DONALD J.",REPUBLICAN,False,999999,999999
2024,NEW YORK,NY,US PRESIDENT,"HARRIS, KAMALA D.",DEMOCRAT,False,400,1000
2024,NEW YORK,NY,US PRESIDENT,"HARRIS, KAMALA D.",WORKING FAMILIES / DEMOCRAT,False,100,1000
2024,NEW YORK,NY,US PRESIDENT,"TRUMP, DONALD J.",REPUBLICAN,False,300,1000
2024,NEW YORK,NY,US PRESIDENT,"KENNEDY, ROBERT F. JR",WE THE PEOPLE,False,50,1000
2024,NEW YORK,NY,US PRESIDENT,CORNEL WEST AND MELINA ABDULLAH,,True,10,1000
2024,NEW YORK,NY,US PRESIDENT,"OLIVER, CHASE",LIBERTARIAN,False,40,1000
2024,NEW YORK,NY,US PRESIDENT,JILL STEIN,WRITE-IN,True,30,1000
2024,NEW YORK,NY,US PRESIDENT,"DE LA CRUZ, CLAUDIA",INDEPENDENT,False,60,1000
2024,NEW YORK,NY,US PRESIDENT,SHARON E HARRIS,DEMOCRATIC,True,5,1000
2024,NEW YORK,NY,US PRESIDENT,WRITE-IN,,True,5,1000
2024,NEW YORK,NY,US PRESIDENT,UNDERVOTES,,False,70,1000
2024,NEW YORK,NY,US PRESIDENT,OVERVOTES,,False,7,1000
"""


def test_a_states_votes_are_counted_by_whose_they_are_whatever_line_they_were_cast_on(tmp_path):
    path = tmp_path / "president.csv"
    path.write_text(RETURNS, encoding="utf-8")
    state = places.votes_by_state(path, 2024)["NY"]
    assert state == {"cast": 1000.0, "republican": 300.0, "democrat": 500.0, "libertarian": 40.0, "green": 30.0, "independent": 60.0, "other": 70.0}
    assert places.votes_by_state(path, 2020)["NY"]["republican"] == 999999.0


def test_votes_become_shares_of_every_vote_cast_that_add_up_to_one(tmp_path):
    path = tmp_path / "president.csv"
    path.write_text(RETURNS, encoding="utf-8")
    shares = places.vote_shares(places.votes_by_state(path, 2024)["NY"])
    year = places.ELECTION_YEAR
    assert shares[f"vote_democrat_{year}"] == 0.5 and shares[f"vote_republican_{year}"] == 0.3 and shares[f"vote_independent_{year}"] == 0.06
    assert shares[f"votes_cast_{year}"] == 1000 and set(shares) == set(places.VOTE_COLUMNS)
    assert abs(sum(value for column, value in shares.items() if column.startswith("vote_")) - 1) < 1e-9
    assert places.vote_shares(None) == {} and places.vote_shares({"cast": 0.0}) == {}


def test_a_district_is_named_the_way_people_name_it_and_keeps_its_own_number_or_name():
    names = places.district_names
    assert names("congressional district", "52", "California") == ("California's 52nd congressional district", "Congressional District 52", "52")
    assert names("congressional district", "03", "Texas")[0] == "Texas's 3rd congressional district" and names("congressional district", "11", "Ohio")[0].startswith("Ohio's 11th")
    assert names("congressional district", "00", "Alaska") == ("Alaska's at-large congressional district", "Congressional District (at Large)", "At Large")
    assert names("congressional district", "98", "Puerto Rico")[:2] == ("Puerto Rico's resident commissioner district", "Resident Commissioner District (at Large)")
    assert names("congressional district", "98", "District of Columbia")[0] == "District of Columbia's delegate district"
    assert names("state house district", "079", "California", "Assembly District 79") == ("California Assembly District 79", "Assembly District 79", "79")
    assert names("state house district", "x", "Massachusetts", "4th Middlesex District")[2] == "4th Middlesex"
    assert names("state house district", "x", "New Hampshire", "State House District Hillsborough 01")[2] == "Hillsborough 01"
    assert names("state house district", "x", "Vermont", "Chittenden-1 State House District")[2] == "Chittenden-1"
    assert names("state senate district", "x", "Washington", "Legislative (Senate) District 1")[2] == "1"
    assert names("state senate district", "x", "Alaska", "State Senate District A")[2] == "A"
    assert names("state senate district", "x", "District of Columbia", "Ward 1") == ("District of Columbia Ward 1", "Ward 1", "1")


def test_the_surveys_age_bands_make_the_adult_bands_and_one_for_everyone_younger(tmp_path):
    names = ["GEO_ID"] + [f"B01001_{kind}{n:03d}" for n in range(1, 50) for kind in ("E", "M")]
    def row(geo, men, women):
        cells = {"B01001_E001": sum(men) + sum(women), "B01001_E002": sum(men), "B01001_E026": sum(women)}
        cells.update({f"B01001_E{3 + n:03d}": count for n, count in enumerate(men)})
        cells.update({f"B01001_E{27 + n:03d}": count for n, count in enumerate(women)})
        return "|".join([geo] + [str(cells.get(name, 5)) for name in names[1:]])
    men = [10] * 23  # ten in each of the survey's 23 bands
    path = tmp_path / "ages.dat"
    path.write_text("\n".join(["|".join(names), row("5001900US0652", men, men), row("0500000US06073", men, [0] * 23), row("1400000US06073000100", men, men)]) + "\n")
    shares = places.survey_ages(path)
    assert set(shares) == {"5001900US0652", "06073"}
    district = shares["5001900US0652"]
    assert district["age_under_18"] == round(80 / 460, 4) and district["age_18_24"] == round(80 / 460, 4) and district["age_75_79"] == round(20 / 460, 4)
    assert abs(sum(district.values()) - 1) < 0.001 and set(district) == set(places.SURVEY_BANDS)
    assert shares["06073"]["age_80_plus"] == round(20 / 230, 4)


def test_a_districts_representative_and_a_states_senators_are_put_on_their_rows():
    given = pd.DataFrame({"place_id": ["06", "5001900US0652", "5001900US0200", "5001900US1198", "5001900US0601"],
                          "kind": ["state"] + ["congressional district"] * 4})
    sitting = pd.DataFrame([
        {"bioguide_id": "P000145", "name": "Alex Padilla", "chamber": "Senate", "state": "CA", "district": None, "party": "Democrat", "current_service_start": "2021-01-20"},
        {"bioguide_id": "S001150", "name": "Adam Schiff", "chamber": "Senate", "state": "CA", "district": None, "party": "Democrat", "current_service_start": "2024-12-09"},
        {"bioguide_id": "V000130", "name": "Juan Vargas", "chamber": "House", "state": "CA", "district": 52, "party": "Democrat", "current_service_start": "2013-01-03"},
        {"bioguide_id": "B001323", "name": "Nicholas J. Begich", "chamber": "House", "state": "AK", "district": 0, "party": "Republican", "current_service_start": "2025-01-03"},
        {"bioguide_id": "N000147", "name": "Eleanor Holmes Norton", "chamber": "House", "state": "DC", "district": 0, "party": "Democrat", "current_service_start": "1991-01-03"},
        {"bioguide_id": "X000001", "name": "Someone Else", "chamber": "House", "state": "TX", "district": 1, "party": "Republican", "current_service_start": "2025-01-03"},
    ])
    found = places.add_members(given, sitting).set_index("place_id")
    assert found.loc["5001900US0652", ["representative", "representative_party", "representative_id"]].tolist() == ["Juan Vargas", "Democrat", "V000130"]
    assert found.loc["5001900US0200", "representative"] == "Nicholas J. Begich" and found.loc["5001900US1198", "representative"] == "Eleanor Holmes Norton"
    assert found.loc["5001900US0601", "representative"] is None  # a seat with no one in it
    senators = __import__("json").loads(found.loc["06", "senators"])
    assert [senator["name"] for senator in senators] == ["Alex Padilla", "Adam Schiff"] and senators[0]["since"] == "2021-01-20"
    assert places.add_members(given, None)["representative"].isna().all()


def test_the_file_of_facts_the_app_reads_has_the_columns_once_and_each_places_values_in_that_order(tmp_path):
    import gzip, json
    rows = pd.DataFrame([
        {"place_id": "00", "kind": "nation", "name": "United States", "state": "US", "population": 340110988},
        {"place_id": "06", "kind": "state", "name": "California", "state": "CA", "parent_id": "00", "population": 39431263, "gini_index": 0.48691, "age_under_1": 0.0102},
        {"place_id": "06073", "kind": "county", "name": "San Diego County", "state": "CA", "parent_id": "06", "population": 3298799.0},
        {"place_id": "610U900US06039", "kind": "state senate district", "name": "California State Senate District 39", "state": "CA", "parent_id": "06"},
    ]).reindex(columns=["place_id", "state", *places.INDEX_COLUMNS])
    assert places.write_index(rows, tmp_path) == 2
    top = json.loads((tmp_path / "index" / "US.json").read_text())
    at = top["columns"].index
    assert set(top["places"]) == {"00", "06"} and top["places"]["06"][at("name")] == "California" and top["places"]["06"][at("gini_index")] == 0.4869
    assert top["places"]["00"][at("parent_id")] is None and top["places"]["06"][at("population")] == 39431263
    state = json.load(gzip.open(tmp_path / "index" / "CA.json.gz", "rt"))
    assert set(state["places"]) == {"06073"} and state["places"]["06073"][at("population")] == 3298799  # a legislature's districts are left out


def test_the_surveys_table_of_origin_and_race_makes_five_shares_that_add_to_the_whole(tmp_path):
    names = ["GEO_ID"] + [f"B03002_{kind}{n:03d}" for n in range(1, 22) for kind in ("E", "M")]
    def row(geo, **counts):
        cells = {f"B03002_E{n:03d}": count for n, count in ((int(name[1:]), count) for name, count in counts.items())}
        return "|".join([geo] + [str(cells.get(name, 0)) for name in names[1:]])
    # 1,000 people: 400 White, 100 Black, 10 American Indian, 150 Asian, 5 Pacific Islander, 5 of some other race,
    # 30 of two or more, none of them Hispanic or Latino; and 300 Hispanic or Latino of any race.
    county = row("0500000US06073", e1=1000, e2=700, e3=400, e4=100, e5=10, e6=150, e7=5, e8=5, e9=30, e12=300)
    path = tmp_path / "race.dat"
    path.write_text("\n".join(["|".join(names), county, row("0400000US72", e1=0), row("1400000US06073000100", e1=50, e3=50)]) + "\n")
    shares = places.survey_race(path)
    assert set(shares) == {"06073"}  # a place with nobody counted has no shares, and a tract is not a place kept here
    assert shares["06073"] == {"white_share": 0.4, "black_share": 0.1, "asian_share": 0.15, "hispanic_share": 0.3, "other_race_share": 0.05}
    assert abs(sum(shares["06073"].values()) - 1) < 0.001 and set(shares["06073"]) == set(places.RACE_SHARES)
    assert set(places.RACE_SHARES) <= set(places.PLACE_COLUMNS) and "race_years" in places.INDEX_COLUMNS
