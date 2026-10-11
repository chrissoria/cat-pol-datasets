"""The members tables add up a person's terms, and race comes only from a published list."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_congress_members as members

TODAY = "2026-10-10"


def person(bioguide, first, last, terms, **more):
    return {"id": {"bioguide": bioguide, "govtrack": 1, **more.pop("ids", {})}, "name": {"first": first, "last": last, **more.pop("name", {})},
            "bio": {"birthday": "1958-10-13", "gender": "F"}, "terms": terms, **more}


def term(kind, start, end, state="WA", **more):
    return {"type": kind, "start": start, "end": end, "state": state, "party": "Democrat", **more}


CANTWELL = person("C000127", "Maria", "Cantwell", [
    term("rep", "1993-01-05", "1995-01-03", district=1),
    term("sen", "2001-01-03", "2007-01-03", **{"class": 1}),
    term("sen", "2007-01-04", "2031-01-03", **{"class": 1}, url="https://www.cantwell.senate.gov", phone="202-224-3441",
         contact_form="https://www.cantwell.senate.gov/contact", address="511 Hart Senate Office Building Washington DC 20510",
         office="511 Hart Senate Office Building"),
], leadership_roles=[{"title": "Senate Democratic Conference Secretary", "start": "2017-01-03", "end": "2019-01-03"},
                     {"title": "Senate Minority Whip", "start": "2025-01-03"}])
GRAHAM = person("G000359", "Lindsey", "Graham", [
    term("rep", "1995-01-04", "2003-01-03", "SC", district=3, url="http://old.house.gov"),
    term("sen", "2003-01-07", "2026-07-11", "SC", url="https://www.lgraham.senate.gov", phone="202-224-5972"),
])


def test_congresses_and_their_first_days():
    assert members.congress_start(119) == "2025-01-03" and members.congress_start(73) == "1933-03-04"
    assert members.congress_of("2026-10-10") == 119
    assert members.congress_of("2025-01-02") == 118 and members.congress_of("2025-01-03") == 119
    assert members.congress_of("1933-03-03") == 72 and members.congress_of("1934-12-31") == 73 and members.congress_of("1935-01-03") == 74
    assert members.congress_of("1789-03-04") == 1


def test_a_member_row_adds_up_the_terms():
    row = members.member_row(CANTWELL, True, {"twitter": "SenatorCantwell", "twitter_id": 1}, TODAY)
    assert (row["status"], row["position"], row["chamber"], row["state"], row["district"]) == ("serving", "Senator", "Senate", "WA", None)
    assert (row["first_entered"], row["last_exit"], row["exit_timing"]) == ("1993-01-05", "", "")
    # Her time in the Senate is unbroken since 2001; the House term six years earlier is not part of it.
    assert row["current_service_start"] == "2001-01-03"
    assert (row["n_terms"], row["house_terms"], row["senate_terms"]) == (3, 1, 2)
    assert row["days_served"] == 728 + 2191 + members.days_between("2007-01-04", TODAY)
    assert row["leadership_position"] == "Senate Minority Whip" and "Conference Secretary (2017-01-03 to 2019-01-03)" in row["leadership_history"]
    assert row["website"] == "https://www.cantwell.senate.gov" and row["twitter"] == "SenatorCantwell" and row["facebook"] == ""


def test_someone_who_has_left_keeps_no_contact_details():
    row = members.member_row(GRAHAM, False, {"twitter": "LindseyGrahamSC"}, TODAY)
    assert (row["status"], row["last_exit"], row["exit_timing"], row["current_service_start"]) == ("former", "2026-07-11", "during a Congress", "")
    assert row["website"] == row["phone"] == row["twitter"] == ""
    # The terms table keeps the address each term had.
    assert [t["url"] for t in members.term_rows(GRAHAM, False, TODAY)] == ["http://old.house.gov", "https://www.lgraham.senate.gov"]


def test_exit_timing_knows_when_congresses_ended():
    assert members.exit_timing("2025-01-03") == "end of a Congress"
    assert members.exit_timing("2024-01-03") == "during a Congress"  # an even year: the middle of a Congress
    assert members.exit_timing("1869-03-03") == "end of a Congress" and members.exit_timing("1933-03-04") == "end of a Congress"
    assert members.exit_timing("2018-08-25") == "during a Congress"


def test_a_break_in_service_starts_the_count_again():
    back = [term("rep", "2017-01-03", "2023-01-03"), term("rep", "2024-02-13", "2025-01-03"), term("rep", "2025-01-03", "2027-01-03")]
    assert members.last_stretch_start(back) == "2024-02-13"
    late = [term("rep", "1977-01-04", "1979-01-03"), term("rep", "1979-01-15", "1981-01-03")]  # sworn in twelve days late
    assert members.last_stretch_start(late) == "1977-01-04"


def test_term_rows_number_the_terms_and_name_the_congresses():
    rows = members.term_rows(CANTWELL, True, TODAY)
    assert [(r["term_number"], r["chamber"], r["congress_first"], r["congress_last"], r["serving"]) for r in rows] == [
        (1, "House", 103, 103, False), (2, "Senate", 107, 109, False), (3, "Senate", 110, 121, True)]
    assert rows[0]["district"] == 1 and rows[1]["district"] is None and rows[0]["days"] == 728
    delegate = members.term_rows(person("N000147", "Eleanor", "Norton", [term("rep", "1991-01-03", "1993-01-03", "DC", district=0)]), False, TODAY)
    assert delegate[0]["position"] == "Delegate"
    assert members.position_of(term("rep", "2025-01-03", "2029-01-03", "PR", district=0)) == "Resident Commissioner"


def test_tables_have_their_columns_and_whole_number_districts():
    table, terms = members.build_tables([CANTWELL], [GRAHAM], [{"id": {"bioguide": "C000127"}, "social": {"twitter": "SenatorCantwell"}}], TODAY)
    assert list(table.columns) == members.MEMBER_COLUMNS and list(terms.columns) == members.TERM_COLUMNS
    assert list(table["bioguide_id"]) == ["C000127", "G000359"] and len(terms) == 5
    assert str(terms["district"].dtype) == "Int64" and terms["district"].tolist()[0] == 1
    assert table.loc[0, "twitter"] == "SenatorCantwell" and table.loc[0, "updated"] == TODAY


def test_the_app_file_has_the_shape_the_map_reads_and_only_recent_members():
    old = person("O000001", "Old", "Timer", [term("rep", "2009-01-06", "2013-01-03", district=2)])
    data = members.app_file([CANTWELL], [GRAHAM, old], TODAY)
    assert data["schema"] == 1 and sorted(data["members"]) == ["C000127", "G000359"]  # the 112th Congress is before the map's first
    card = data["members"]["C000127"]
    assert list(card) == ["url", "contact_form", "email", "phone", "office", "since", "first_entered", "terms", "born", "gender"]
    assert (card["since"], card["first_entered"], card["email"], card["office"]) == ("2001-01-03", "1993-01-05", "", "511 Hart Senate Office Building")
    assert card["terms"][0] == {"chamber": "House", "start": "1993-01-05", "end": "1995-01-03", "state": "WA", "district": 1, "party": "Democrat"}
    assert card["terms"][1]["district"] is None
    gone = data["members"]["G000359"]
    assert gone["url"] == gone["phone"] == "" and gone["since"] == "2003-01-07"


HISTORIAN_PAGE = """
<table class="dynamic"><tbody>
<tr class="group"><td colspan="5">112th (2011-2013)</td></tr>
<tr class="odd"><td> 112th (2011-2013) </td><td> <a href="/People/Detail/19999"> PAYNE, Donald Milford </a></td><td>NJ</td><td>Democrat</td><td>House</td></tr>
<tr class="even"><td> 112th (2011-2013) </td><td> <a href="/People/Detail/15032387602"> PAYNE, Donald, Jr. <sup> 4 </sup></a></td><td>NJ</td><td>Democrat</td><td>House</td></tr>
<tr class="odd"><td> 113th (2013-2015) </td><td> <a href="/People/Detail/15032387602"> PAYNE, Donald, Jr. </a></td><td>NJ</td><td>Democrat</td><td>House</td></tr>
<tr class="even"><td> 116th (2019-2021) </td><td> <a href="/People/Detail/15032440001"> NEGUSE, Joseph </a></td><td>CO</td><td>Democrat</td><td>House</td></tr>
<tr class="odd"><td> 118th (2023-2025) </td><td> <a href="/People/Detail/15032440002"> PEREZ, Marie Gluesenkamp </a></td><td>WA</td><td>Democrat</td><td>House</td></tr>
<tr class="even"><td> 113th (2013-2015) </td><td> <a href="/People/Detail/15032440003"> SCOTT, Timothy </a></td><td>SC</td><td>Republican</td><td>Both</td></tr>
<tr class="odd"><td> 118th (2023-2025) </td><td> <a href="/People/Detail/15032440004"> SMITH, Jane </a></td><td>TX</td><td>Democrat</td><td>House</td></tr>
</tbody></table>
"""
PAYNE_SR = person("P000149", "Donald", "Payne", [term("rep", "1989-01-03", "2012-03-06", "NJ", district=10)], ids={"house_history": 19999})
PAYNE_JR = person("P000604", "Donald", "Payne", [term("rep", "2012-11-15", "2013-01-03", "NJ", district=10), term("rep", "2013-01-03", "2024-04-24", "NJ", district=10)],
                  name={"suffix": "Jr."})
NEGUSE = person("N000191", "Joe", "Neguse", [term("rep", "2019-01-03", "2027-01-03", "CO", district=2)])
PEREZ = person("G000600", "Marie", "Gluesenkamp Perez", [term("rep", "2023-01-03", "2027-01-03", district=3)])
SCOTT = person("S001184", "Tim", "Scott", [term("rep", "2011-01-05", "2013-01-02", "SC", district=1), term("sen", "2013-01-02", "2029-01-03", "SC")])
OTHER_NEGUSE = person("N000999", "Sam", "Neguse", [term("rep", "2019-01-03", "2021-01-03", "CO", district=5)])
SMITHS = [person("S000001", "Jane", "Smith", [term("rep", "2023-01-03", "2025-01-03", "TX", district=1)]),
          person("S000002", "Janet", "Smith", [term("rep", "2023-01-03", "2025-01-03", "TX", district=2)])]


def test_the_historians_list_is_read_by_person():
    listed = members.parse_historian(HISTORIAN_PAGE)
    assert len(listed) == 6
    assert listed[15032387602] == {"last": "PAYNE", "given": "Donald, Jr.", "seats": {(112, "House", "NJ"), (113, "House", "NJ")}}
    assert listed[15032440003]["seats"] == {(113, "House Senate", "SC")}


def test_listed_people_are_matched_to_one_member_or_not_at_all():
    people = [PAYNE_SR, PAYNE_JR, NEGUSE, OTHER_NEGUSE, PEREZ, SCOTT, CANTWELL] + SMITHS
    found = members.match_historian(members.parse_historian(HISTORIAN_PAGE), people)
    assert found[19999] == "P000149"  # by the Historian's own id
    assert found[15032387602] == "P000604"  # father and son sat for the same seat in one Congress; only the son sat in both listed
    assert found[15032440001] == "N000191"  # Joseph is Joe, and is not the other Neguse from Colorado
    assert found[15032440002] == "G000600"  # the surname is written two ways
    assert found[15032440003] == "S001184"  # in both chambers in one Congress
    assert 15032440004 not in found  # two Texans it could be: left out rather than guessed


def test_race_is_written_only_for_listed_members_with_its_source():
    table, _ = members.build_tables([CANTWELL, NEGUSE], [PAYNE_JR], [], TODAY)
    table = members.add_race(table, {"N000191": ["Black"], "P000604": ["Hispanic", "Black"]})
    by_id = table.set_index("bioguide_id")
    assert by_id.loc["C000127", "race_ethnicity"] == "" and by_id.loc["C000127", "race_ethnicity_source"] == ""
    assert by_id.loc["N000191", "race_ethnicity"] == "Black"
    assert by_id.loc["N000191", "race_ethnicity_source"] == "U.S. House, Office of the Historian: Black Americans in Congress"
    assert by_id.loc["P000604", "race_ethnicity"] == "Black; Hispanic"  # always in the same order
    assert by_id.loc["P000604", "race_ethnicity_source"].count("Office of the Historian") == 2


def test_a_broken_table_is_not_published():
    import pandas as pd
    def table(serving, former=12000):
        return pd.DataFrame({"bioguide_id": [f"X{i:06d}" for i in range(serving + former)], "status": ["serving"] * serving + ["former"] * former})
    terms = pd.DataFrame({"bioguide_id": ["X"] * 45000})
    nothing = pd.DataFrame(columns=members.MEMBER_COLUMNS)
    assert members.problem_with(table(539), terms, nothing) is None
    assert "serving" in members.problem_with(table(12), terms, nothing)
    assert "fewer" in members.problem_with(table(539), terms, table(539, 12500))
    assert "terms" in members.problem_with(table(539), terms.head(900), nothing)
    twice = table(539)
    twice.loc[1, "bioguide_id"] = twice.loc[0, "bioguide_id"]
    assert "twice" in members.problem_with(twice, terms, nothing)
