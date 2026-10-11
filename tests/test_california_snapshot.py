"""build_california_snapshot puts each measure where its history left it."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_california_snapshot as snap


def action(house, location="", detail="", after="", text="", date="2025-03-01", committee=""):
    code = detail if detail.startswith("C") and detail[2:].isdigit() else ""
    return {"house": house, "location": location, "location_detail": detail, "status_after": after, "action": text,
            "date": date, "committee_code": code, "committee": committee, "action_status": "Applied"}


JOURNEY = [
    action("Assembly", "Desk", after="Pending Referral", text="Read first time. To print."),
    action("Assembly", "Committee", "CX24", "In Committee Process", committee="Water, Parks and Wildlife"),
    action("Assembly", "Floor", "Second Reading", "In Floor Process"),
    action("Assembly", "E&E", "Engrossing", "In Floor Process", text="Read second time and amended."),
    action("Assembly", "Committee", "CX25", "In Committee Process", committee="Appropriations"),
    action("Assembly", "Floor", "Third Reading", "In Floor Process"),
    action("Assembly", "E&E", "Engrossing", "Passed", text="Read third time. Passed. Ordered to the Senate."),
    action("Senate", "Rules", after="Pending Referral"),
    action("Senate", "Committee", "CS55", "In Committee Process", committee="Natural Resources and Water"),
    action("Senate", "Floor", "Third Reading", "In Floor Process"),
    action("Senate", "Desk", after="Passed", text="Read third time. Passed. Ordered to the Assembly."),
    action("Assembly", "Desk", after="In Floor Process", text="Concurrence in Senate amendments pending."),
    action("Assembly", "E&E", "Enrollment", "Passed"),
    action("Governor", after="Enrolled"),
    action("Governor", after="Signed by Governor"),
    action("Secretary of State", after="Chaptered"),
]


def test_a_bill_is_followed_from_the_desk_to_the_statute_book():
    moves, final, passed, left_committee = snap.walk(JOURNEY, "AB", "Assembly")
    assert [snap.location_key(place) for _, place in moves] == [
        "referral_desk:House", "committee:House:CX24", "calendar:House", "committee:House:CX25", "floor:House",
        "other_chamber:Senate", "referral_desk:Senate", "committee:Senate:CS55", "floor:Senate", "other_chamber:House",
        "conference", "president", "law",
    ]
    assert final["kind"] == "law" and passed == {"Assembly", "Senate"} and left_committee
    assert snap.stage_of("AB", "law", "Chaptered", passed, left_committee) == 5


def test_the_assembly_fills_the_house_wing():
    assert snap.place_after(action("Assembly", "Floor", "Third Reading", "In Floor Process"), "AB")["chamber"] == "House"
    assert snap.place_after(action("Senate", "Floor", "Consent", "In Floor Process"), "SB") == \
        {"kind": "calendar", "chamber": "Senate", "committee": ""}


def test_a_resolution_ends_in_the_hall_and_a_bill_in_the_archive():
    assert snap.place_after(action("Secretary of State", after="Chaptered"), "ACR")["kind"] == "adopted"
    assert snap.place_after(action("Secretary of State", after="Chaptered"), "SB")["kind"] == "law"
    assert snap.place_after(action("Assembly", "Desk", after="Passed"), "HR")["kind"] == "adopted"  # one house is enough
    assert snap.place_after(action("Assembly", "Desk", after="Passed"), "AB") == \
        {"kind": "other_chamber", "chamber": "Senate", "committee": ""}


def test_a_veto_and_a_death_do_not_send_a_bill_back_to_a_desk():
    assert snap.place_after(action("Assembly", "Desk", after="Vetoed"), "AB")["kind"] == "vetoed"
    assert snap.place_after(action("Assembly", "Desk", after="Died"), "AB") is None
    moves, final, _, _ = snap.walk(JOURNEY[:2] + [action("Assembly", "Desk", after="Died", text="Died at Desk.")], "AB", "Assembly")
    assert final == {"kind": "committee", "chamber": "House", "committee": "CX24"}


def test_a_measure_with_no_history_waits_at_its_own_houses_desk():
    assert snap.walk([], "SB", "Senate")[1] == {"kind": "referral_desk", "chamber": "Senate", "committee": ""}


def test_how_far_a_measure_got():
    assert snap.stage_of("AB", "committee", "In Committee Process", set(), False) == 0
    assert snap.stage_of("AB", "committee", "In Committee Process", set(), True) == 1  # came back from the floor
    assert snap.stage_of("AB", "floor", "Failed", set(), True) == 2
    assert snap.stage_of("AB", "committee", "In Committee Process", {"Assembly"}, True) == 3
    assert snap.stage_of("HR", "adopted", "Passed", {"Assembly"}, True) == 3
    assert snap.stage_of("ACR", "adopted", "Chaptered", {"Assembly", "Senate"}, True) == 4
    assert snap.stage_of("AB", "vetoed", "Vetoed", {"Assembly", "Senate"}, True) == 4


def test_why_a_measure_is_dead():
    fate = lambda place, status, stage, passed, final=True, last="2026-08-31": \
        snap.fate_of("AB", place, status, stage, passed, last, final, "2025-09-30")
    assert fate("law", "Chaptered", 5, {"Assembly", "Senate"}) == "."
    assert fate("vetoed", "Vetoed", 4, {"Assembly", "Senate"}) == "v"
    assert fate("floor", "Failed", 2, set()) == "f"
    assert fate("committee", "In Committee Process", 0, set()) == "c"
    assert fate("calendar", "In Floor Process", 1, set()) == "w"
    assert fate("committee", "In Committee Process", 3, {"Assembly"}) == "o"
    assert fate("president", "Enrolled", 4, {"Assembly", "Senate"}) == "b"
    # While the session runs, only a recorded death or a year of silence counts.
    assert fate("committee", "In Committee Process", 0, set(), final=False) == "."
    assert fate("committee", "Died", 0, set(), final=False) == "c"
    assert fate("committee", "In Committee Process", 0, set(), final=False, last="2025-03-01") == "s"


def test_the_first_subject_committee_stands_for_a_policy_area():
    assert snap.area_of(JOURNEY) == "Water, Parks and Wildlife"
    assert snap.area_of([action("Senate", "Committee", "CS58", committee="Rules"),
                         action("Senate", "Committee", "CS60", committee="Health")]) == "Health"
    assert snap.area_of([action("Assembly", "Committee", "CX25", committee="Appropriations")]) == "Appropriations"
    assert snap.area_of([action("Senate", "Committee", "CS58", committee="Rules")]) == ""


def test_ids_and_the_end_of_a_session():
    assert snap.measure_id(2025, "AB", 679) == "2025-ab-679" and snap.measure_id(2025, "SB", 3, 1) == "2025-sbx1-3"
    assert not snap.finished(2025, "2026-09-30") and snap.finished(2025, "2026-10-01") and not snap.finished(2027, "2026-12-07")
