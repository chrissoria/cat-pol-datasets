"""Tests for the search-index additions in build_world_snapshot.py."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_federal_bills as bills  # noqa: E402
import build_world_snapshot as snapshot  # noqa: E402


def stage(status, last_action="", kind=""):
    return snapshot.STAGES[snapshot.stage_of(status, last_action, kind)]


def test_stage_follows_status():
    assert stage("In Committee", "Referred to the Committee on Energy and Commerce.") == "in_committee"
    assert stage("Introduced") == "in_committee"
    assert stage("Reported from Committee") == "out_of_committee"
    assert stage("Calendared", "Placed on the Union Calendar, Calendar No. 12.") == "out_of_committee"
    assert stage("Passed House") == "passed_one_chamber"
    assert stage("Passed Senate") == "passed_one_chamber"
    assert stage("Sent to President") == "passed_both_chambers"
    assert stage("Vetoed") == "passed_both_chambers"
    assert stage("Signed into Law") == "law"


def test_failed_vote_is_read_from_the_latest_action():
    failed = "On motion to suspend the rules and pass the bill Failed by the Yeas and Nays: (2/3 required): 250 - 180."
    assert stage("Calendared", failed) == "failed_floor_vote"
    cloture = "Cloture on the motion to proceed to the measure not invoked in Senate by Yea-Nay Vote. 51 - 47."
    assert stage("Senate Floor", cloture) == "failed_floor_vote"
    rejected = "Motion to proceed to consideration of measure rejected in Senate by Yea-Nay Vote. 48 - 51. Record Vote Number: 251."
    assert stage("Calendared", rejected) == "failed_floor_vote"
    # Passing later outranks an earlier failure.
    assert stage("Passed House", failed) == "passed_one_chamber"


def test_location_kind_can_raise_the_stage():
    assert stage("Passed Senate", kind="president") == "passed_both_chambers"
    assert stage("In Committee", kind="adopted") == "passed_one_chamber"
    assert stage("In Committee", kind="floor") == "out_of_committee"


def test_pending_round_trip(tmp_path):
    rows = pd.DataFrame([
        {"bill_type": "HR", "bill_number": 9999, "congress": 119, "title": "New", "status": "In Committee",
         "date_introduced": "2026-10-09", "sponsor_bioguide_id": "A000001", "sponsor_party": "D", "text": ""},
        {"bill_type": "S", "bill_number": 1, "congress": 119, "title": "Already in the dataset", "status": "In Committee",
         "date_introduced": "2025-01-03", "sponsor_bioguide_id": "B000002", "sponsor_party": "R", "text": ""},
    ])
    file = tmp_path / "pending.parquet"
    bills.save_pending(rows, file)
    pending = snapshot.read_pending(file, known_ids={"119-s-1"})
    assert pending["id"].tolist() == ["119-hr-9999"]
    assert "text" not in pending.columns
    assert snapshot.read_pending(tmp_path / "missing.parquet", set()).empty


def test_fate_of_names_how_a_bill_died():
    fate = snapshot.fate_of
    assert fate("Vetoed", "Vetoed by President.", "vetoed", "2026-01-01", False, "2025-10-09") == "v"
    assert fate("Signed into Law", "Became Public Law No: 119-1.", "law", "2025-02-01", False, "2025-10-09") == "."
    assert fate("Calendared", "Motion to proceed to consideration of measure rejected in Senate.", "calendar", "2026-09-01", False, "2025-10-09") == "f"
    # The current Congress: silence for a year, and nothing sooner.
    assert fate("In Committee", "Referred to the Committee on Ways and Means.", "committee", "2025-03-01", False, "2025-10-09") == "s"
    assert fate("In Committee", "Referred to the Committee on Ways and Means.", "committee", "2026-03-01", False, "2025-10-09") == "."
    # A finished Congress: everything that did not succeed died where it stood.
    assert fate("In Committee", "Referred to the Committee on Ways and Means.", "committee", "2024-03-01", True, "") == "c"
    assert fate("Calendared", "Placed on the Union Calendar.", "calendar", "2024-03-01", True, "") == "w"
    assert fate("Passed House", "Received in the Senate.", "other_chamber", "2024-03-01", True, "") == "o"
    assert fate("Passed House", "Agreed to.", "adopted", "2024-03-01", True, "") == "."
