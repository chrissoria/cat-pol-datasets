"""build_chamber_snapshot puts a local body's tables into the one file Capitol World reads."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import build_chamber_snapshot as chamber


def tables():
    items = pd.DataFrame([
        {"matter_id": "10", "matter_file": "26-001", "title": "AN ORDINANCE", "doc_type": "ordinance", "status": "Passed", "body": "BOARD",
         "subject": "Public Safety", "date": "2026-09-01", "agenda_date": "2026-09-16", "last_action": "adopted", "last_action_date": "2026-09-16",
         "result": "Pass", "ayes": 2, "noes": 1, "mover": "Ann Lee", "seconder": "Bo Diaz", "times_on_agenda": 1, "text": "WORDS", "url": "u10"},
        {"matter_id": "11", "matter_file": "26-002", "title": "A REPORT", "doc_type": "other", "status": "Agenda Ready", "body": "BOARD - LAND USE",
         "subject": "Land Use", "date": "2026-09-20", "agenda_date": "2026-10-07", "last_action": "", "last_action_date": "",
         "result": "", "ayes": 0, "noes": 0, "mover": "", "seconder": "", "times_on_agenda": 1, "text": "", "url": "u11"},
    ])
    meetings = pd.DataFrame([
        {"meeting_id": "1", "date": "2026-09-16", "time": "9:00 AM", "body": "BOARD", "location": "Room 327", "url": "m1", "agenda_url": "a1", "minutes_url": "", "items": 1},
        {"meeting_id": "2", "date": "2026-10-07", "time": "9:00 AM", "body": "BOARD - LAND USE", "location": "Room 327", "url": "m2", "agenda_url": "a2", "minutes_url": "", "items": 1},
    ])
    agenda = pd.DataFrame([
        {"item_id": "100", "meeting_id": "1", "date": "2026-09-16", "sequence": 1, "agenda_number": "1", "matter_id": "10", "action": "adopted", "result": "Pass", "ayes": 2, "noes": 1},
        {"item_id": "101", "meeting_id": "2", "date": "2026-10-07", "sequence": 1, "agenda_number": "1", "matter_id": "11", "action": "", "result": "", "ayes": 0, "noes": 0},
    ])
    votes = pd.DataFrame([
        {"item_id": "100", "member": "Ann Lee", "vote": "AYE"}, {"item_id": "100", "member": "Bo Diaz", "vote": "NO"},
        {"item_id": "100", "member": "Cy Old", "vote": "AYE"}, {"item_id": "100", "member": "Someone Unlisted", "vote": "AYE"},
    ])
    supervisors = pd.DataFrame([
        {"name": "Cy Old", "district": 1, "start": "2017-01-01", "end": "2026-09-30", "role": "Member", "serving": False, "first_vote": "2017-06-20", "last_vote": "2026-09-16", "votes": 900},
        {"name": "Bo Diaz", "district": 2, "start": "2023-01-02", "end": "2027-01-04", "role": "Chair", "serving": True, "first_vote": "2023-01-10", "last_vote": "2026-09-16", "votes": 400},
        {"name": "Ann Lee", "district": 1, "start": "2026-10-01", "end": "2029-01-08", "role": "Member", "serving": True, "first_vote": "", "last_vote": "", "votes": 0},
    ])
    supervisors["district"] = supervisors["district"].astype("Int64")
    return {"items": items, "meetings": meetings, "agenda_items": agenda, "votes": votes, "members": supervisors}


def test_those_serving_come_first_in_seat_order_and_a_plain_member_has_no_role():
    members = chamber.build(tables(), today="2026-10-11")["members"]
    assert [m["id"] for m in members] == ["ann-lee", "bo-diaz", "cy-old"]
    assert [m["role"] for m in members] == ["", "Chair", ""] and members[2]["serving"] is False


def test_items_and_meetings_run_newest_first_and_names_are_kept_once():
    file = chamber.build(tables(), today="2026-10-11")
    assert file["items"]["file"] == ["26-002", "26-001"] and file["meetings"]["id"] == ["2", "1"]
    assert [file["kinds"][k] for k in file["items"]["kind"]] == ["other", "ordinance"]
    assert [file["bodies"][b] for b in file["meetings"]["body"]] == ["BOARD - LAND USE", "BOARD"]
    assert [file["bodies"][b] for b in file["items"]["body"]] == ["BOARD - LAND USE", "BOARD"]
    assert file["items"]["mover"] == [-1, 0] and file["items"]["has_text"] == [0, 1]


def test_an_agenda_entry_points_at_its_meeting_and_item_and_carries_a_letter_for_each_member():
    file = chamber.build(tables(), today="2026-10-11")
    agenda = file["agenda"]
    assert agenda["meeting"] == [0, 1] and agenda["item"] == [0, 1]
    assert agenda["votes"] == ["", "ANA"] and agenda["result"] == ["", "P"]
    assert [file["actions"][a] for a in agenda["action"]] == ["", "adopted"]


def test_the_data_runs_through_the_last_meeting_with_something_done():
    assert chamber.build(tables(), today="2026-10-11")["data_through"] == "2026-09-16"


def test_someone_who_held_two_seats_is_one_person_in_the_later_seat():
    given = tables()
    moved = pd.DataFrame([{"name": "Bo Diaz", "district": 7, "start": "2019-01-08", "end": "2022-12-12", "role": "Member", "serving": False,
                           "first_vote": "2019-01-15", "last_vote": "2022-12-06", "votes": 400}])
    moved["district"] = moved["district"].astype("Int64")
    given["members"] = pd.concat([given["members"], moved], ignore_index=True)
    members = chamber.build(given, today="2026-10-11")["members"]
    bo = [m for m in members if m["id"] == "bo-diaz"]
    assert len(bo) == 1 and bo[0]["seat"] == 2 and bo[0]["serving"] and bo[0]["start"] == "2019-01-08" and bo[0]["role"] == "Chair"


def test_a_family_name_is_the_last_word_unless_one_is_given():
    members = chamber.build(tables(), today="2026-10-11", surnames={"ann lee": "Lee-Smith"})["members"]
    assert {member["name"]: member["surname"] for member in members}["Ann Lee"] == "Lee-Smith"
    assert all(member["surname"] == member["name"].split(" ")[-1] for member in members if member["name"] != "Ann Lee")


def test_a_room_can_start_on_a_day_and_keep_its_titles_short():
    held = tables()
    held["items"].loc[1, "title"] = "A REPORT " + "on the roads of the county, " * 20
    # An item filed before the room's first day stays if a meeting since had it on its agenda.
    held["items"].loc[0, "date"] = "2026-06-01"
    old = pd.DataFrame([{"matter_id": "9", "matter_file": "25-900", "title": "AN OLD ONE", "doc_type": "other", "status": "", "body": "BOARD", "subject": "",
                         "date": "2025-01-07", "agenda_date": "2025-01-21", "last_action": "", "last_action_date": "", "result": "", "ayes": 0, "noes": 0,
                         "mover": "", "seconder": "", "times_on_agenda": 1, "text": "", "url": "u9"}])
    held["items"] = pd.concat([held["items"], old], ignore_index=True)
    held["meetings"] = pd.concat([held["meetings"], pd.DataFrame([{"meeting_id": "0", "date": "2025-01-21", "time": "", "body": "BOARD", "location": "",
                                                                    "url": "m0", "agenda_url": "", "minutes_url": "", "items": 1}])], ignore_index=True)
    held["agenda_items"] = pd.concat([held["agenda_items"], pd.DataFrame([{"item_id": "99", "meeting_id": "0", "date": "2025-01-21", "sequence": 1,
                                                                            "agenda_number": "1", "matter_id": "9", "action": "", "result": "", "ayes": 0, "noes": 0}])], ignore_index=True)
    whole = chamber.build(held, today="2026-10-11")
    assert len(whole["items"]["id"]) == 3 and len(whole["meetings"]["id"]) == 3 and len(whole["items"]["title"][0]) > 300
    room = chamber.build(held, today="2026-10-11", start="2026-01-01", titles=60)
    assert room["items"]["id"] == ["11", "10"] and room["meetings"]["id"] == ["2", "1"] and len(room["agenda"]["item"]) == 2
    assert room["items"]["title"] == ["A REPORT on the roads of the county, on the roads of the…", "AN ORDINANCE"]


def test_a_table_with_gaps_in_its_numbers_is_read_as_having_none_there():
    held = tables()
    held["items"]["ayes"] = pd.array([2, None], dtype="Int64")
    held["agenda_items"]["noes"] = pd.array([1, None], dtype="Int64")
    held["meetings"]["items"] = pd.array([None, 1], dtype="Int64")
    held["agenda_items"]["heading"] = pd.array([False, None], dtype="boolean")
    made = chamber.build(held, today="2026-10-11")
    assert made["items"]["ayes"] == [0, 2] and made["agenda"]["noes"] == [0, 1] and made["meetings"]["items"] == [1, 0]


def test_a_role_does_not_repeat_the_seat_and_a_family_name_is_not_a_rank_or_a_junior():
    assert [chamber.office(role, True) for role in ("Supervisor, District 2 Board Chair", "District 2 - Chair", "Vice Chair, District 4", "District II Supervisor",
                                                    "Council President Pro Tem")] == ["Board Chair", "Chair", "Vice Chair", "", "Council President Pro Tem"]
    assert chamber.office("District 1", False) == "District 1"  # all that says which seat, where the seat itself is not known
    assert [chamber.family(name) for name in ("Col. Paul Cook (Ret.)", "Joe Baca, Jr.", "Henry L. Foster III", "Ann Lee")] == ["Cook", "Baca", "Foster", "Lee"]


def test_someone_gone_whose_term_the_source_left_running_left_when_they_last_voted():
    held = tables()
    held["members"].loc[0, "end"] = "2200-12-05"
    gone = chamber.build(held, today="2026-10-11")["members"][2]
    assert (gone["id"], gone["serving"], gone["end"]) == ("cy-old", False, "2026-09-16")
