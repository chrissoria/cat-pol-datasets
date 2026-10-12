"""build_legistar_council reads a city's meetings and votes with the county's reader, and evens out what cities do differently."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import build_legistar_council as city
import build_sd_county as county
import council_tables


def vote(item, member, word, meeting="9", date="2026-05-13"):
    return {"item_id": item, "meeting_id": meeting, "date": date, "matter_id": "m" + item, "matter_file": "ID#26-" + item,
            "member": member, "vote": word}


def votes_of(*rows):
    return pd.DataFrame(list(rows), columns=county.VOTE_COLUMNS)


def entry(item, action="approved", meeting="9", date="2026-05-13", sequence=1, ayes=0, noes=0):
    row = dict.fromkeys(county.AGENDA_COLUMNS, "")
    row.update(item_id=item, meeting_id=meeting, date=date, matter_id="m" + item, action=action, sequence=sequence, result="Pass",
               mover="Jose Barajas", ayes=ayes, noes=noes, not_voting=0)
    return row


def test_a_meeting_is_read_with_each_citys_word_for_aye_and_no_given_one_spelling(monkeypatch):
    answers = {
        "events/9/eventitems": [{"EventItemId": 1, "EventItemMatterId": 70, "EventItemMatterFile": "ID#26-1", "EventItemTitle": "An ordinance",
                                 "EventItemActionName": "adopted", "EventItemPassedFlagName": "Pass", "EventItemAgendaSequence": 3},
                                {"EventItemId": 2, "EventItemMatterId": None, "EventItemTitle": "ROLL CALL"}],
        # F's vote was entered twice, as a clerk sometimes does.
        "eventitems/1/votes": [{"VotePersonName": name, "VoteValueName": word} for name, word in
                               (("A", "Ayes"), ("B", "Yes"), ("C", "Noes"), ("D", "Nay"), ("E", "Excused"), ("F", "Aye"), ("F", "Aye"))],
    }
    monkeypatch.setattr(county, "api", lambda path, **params: answers[path])
    agenda, votes, papers = county.read_meeting({"EventId": 9, "EventDate": "2026-05-13T00:00:00", "EventBodyName": "City Council"})
    assert [(v["member"], v["vote"]) for v in votes] == [("A", "AYE"), ("B", "AYE"), ("C", "NO"), ("D", "NO"), ("E", "EXCUSED"), ("F", "AYE")]
    assert [(a["item_id"], a["ayes"], a["noes"], a["not_voting"]) for a in agenda] == [("1", 3, 2, 1)]


def test_an_item_is_what_the_city_files_it_as_and_otherwise_what_its_title_says():
    assert city.doc_type_of("City Resolution", "Adopt An Ordinance Amending The Master Fee Schedule") == "resolution"
    assert city.doc_type_of("Ordinance", "Subject: Military Equipment") == "ordinance"
    assert city.doc_type_of("Report and Recommendation", "Adopt A Resolution Honoring The Day") == "resolution"
    assert city.doc_type_of(None, "Informational Report On Staffing") == "other"


def test_an_item_carries_the_last_thing_done_to_it_and_keeps_its_papers_when_not_read_again():
    city.point_at(city.CITIES["salinas"])
    matters = [{"MatterId": 1, "MatterGuid": "G1", "MatterFile": "ID#26-1", "MatterTitle": " An  ordinance ", "MatterTypeName": "Ordinance",
                "MatterIntroDate": "2026-04-01T00:00:00", "MatterStatusName": "Passed"},
               {"MatterId": 2, "MatterGuid": "G2", "MatterFile": "ID#26-2", "MatterName": "A report", "MatterTypeName": "Report",
                "MatterIntroDate": "2026-05-01T00:00:00"}]
    rows = [entry("1", "introduced", date="2026-04-07"), entry("1", "adopted", meeting="10", date="2026-05-13")]
    for row in rows:
        row["matter_id"] = "1"
    agenda = pd.DataFrame(rows, columns=county.AGENDA_COLUMNS)
    first = city.items_table(matters, agenda, {"1": [{"name": "Ordinance", "url": "https://example.org/o.pdf"}]}, None)
    item = first.set_index("matter_id").loc["1"]
    assert (item["title"], item["doc_type"], item["last_action"], item["last_action_date"], item["times_on_agenda"]) == \
        ("An ordinance", "ordinance", "adopted", "2026-05-13", 2)
    assert item["url"] == "https://salinas.legistar.com/LegislationDetail.aspx?ID=1&GUID=G1"
    assert first.set_index("matter_id").loc["2", "title"] == "A report"
    again = city.items_table(matters, agenda, {}, first).set_index("matter_id")
    assert "o.pdf" in again.loc["1", "attachments"] and again.loc["2", "attachments"] == "[]"


def test_the_council_is_those_the_source_seats_on_it_with_when_each_first_and_last_voted():
    records = [{"OfficeRecordFullName": "Dennis Donohue", "OfficeRecordBodyName": "City Council", "OfficeRecordTitle": "Mayor",
                "OfficeRecordStartDate": "2024-12-04T00:00:00", "OfficeRecordEndDate": "2099-12-31T00:00:00"},
               {"OfficeRecordFullName": "Jose Barajas", "OfficeRecordBodyName": "City Council", "OfficeRecordTitle": None,
                "OfficeRecordMemberType": "Member", "OfficeRecordStartDate": "2020-12-04T00:00:00", "OfficeRecordEndDate": "2024-12-03T00:00:00"},
               {"OfficeRecordFullName": "A Planner", "OfficeRecordBodyName": "Planning Commission", "OfficeRecordTitle": "Commissioner",
                "OfficeRecordStartDate": "2024-12-04T00:00:00", "OfficeRecordEndDate": None}]
    votes = votes_of(vote("1", "Dennis Donohue", "AYE", date="2025-01-07"), vote("2", "Dennis Donohue", "AYE", date="2026-05-13"),
                     vote("2", "Steve McShane", "NO", date="2026-05-13"), vote("3", "A Planner", "AYE", meeting="8"))
    meetings = pd.DataFrame({"meeting_id": ["9", "8"], "body": ["City Council", "Planning Commission"]})
    council = city.members_table(records, votes, meetings, "City Council").set_index("name")
    # Steve McShane votes at a council meeting and has no term on record; the planner votes only at the commission.
    assert list(council.index) == ["Steve McShane", "Jose Barajas", "Dennis Donohue"]
    assert council.loc["Steve McShane", ["role", "start", "serving", "votes"]].tolist() == ["", "", False, 1]
    assert council.loc["Dennis Donohue", ["role", "serving", "first_vote", "last_vote", "votes"]].tolist() == ["Mayor", True, "2025-01-07", "2026-05-13", 2]
    assert council.loc["Jose Barajas", ["role", "serving", "votes"]].tolist() == ["Member", False, 0]
    assert council["district"].isna().all()  # the source does not say


def test_the_tables_are_in_the_shape_every_councils_are_with_the_citys_own_columns_after():
    city.point_at(city.CITIES["salinas"])
    matters = [{"MatterId": 1, "MatterTitle": "An ordinance", "MatterTypeName": "Ordinance", "MatterIntroDate": "2026-04-01T00:00:00"}]
    agenda = pd.DataFrame([entry("1", ayes=1)], columns=county.AGENDA_COLUMNS)
    votes = votes_of(vote("1", "Dennis Donohue", "AYE"))
    meetings = county.meetings_table([{"EventId": 9, "EventDate": "2026-05-13T00:00:00", "EventBodyName": "City Council"}])
    tables = council_tables.standard({"items": city.items_table(matters, agenda, {}, None), "meetings": meetings, "agenda_items": agenda,
                                      "votes": votes, "members": city.members_table([], votes, meetings, "City Council")})
    for name in council_tables.TABLES:
        shared = council_tables.COLUMNS[name]
        assert list(tables[name].columns[:len(shared)]) == shared
    assert list(tables["items"].columns[-2:]) == ["attachments", "last_modified"]
    assert "action_text" in tables["agenda_items"].columns and "minutes_status" in tables["meetings"].columns


def test_a_citys_card_is_the_one_card_with_its_own_name_addresses_and_counts():
    meetings = pd.DataFrame({"meeting_id": ["8", "9"], "date": ["2014-03-25", "2026-05-13"], "body": ["City Council", "Planning Commission"], "items": [3, 0]})
    votes = votes_of(vote("1", "Dennis Donohue", "AYE", date="2014-03-25"))
    empty = pd.DataFrame()
    text = city.card("long-beach", {"items": empty, "meetings": meetings, "agenda_items": empty, "votes": votes, "members": empty})
    assert "# Long Beach City Council" in text and "webapi.legistar.com/v1/longbeach" in text
    assert "chrissoria/long-beach-council" in text and "long-beach-ordinances" in text
    assert "{" not in text.split("---", 2)[2]  # every fact was written in
