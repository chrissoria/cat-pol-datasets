"""build_court_snapshot lays the tables out for the map without losing who sat and how they voted."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import build_court_snapshot as snapshot
import build_supreme_court as sc


def tables():
    def case(case_id, term, **more):
        row = {column: "" for column in sc.CASE_COLUMNS}
        row.update(id=case_id, term=term, docket=case_id.split("-", 1)[1], name=f"Case {case_id}", stage="decided",
                   majority_votes=0, minority_votes=0, precedent_altered=False, source="scdb", executive_orders="[]")
        row.update(more)
        return row

    cases = pd.DataFrame([
        case("2024-23-1", 2024, date_decided="2025-06-01", disposition="reversed", winner="petitioner", majority_votes=2, minority_votes=1,
             majority_author="JGRoberts", issue_area="Civil rights", question="May it?", description="Held: it may not."),
        case("2025-25-9", 2025, stage="argued", date_argued="2025-11-05", source="oyez", question="Does it?"),
    ])
    votes = pd.DataFrame([
        {"case_id": "2024-23-1", "term": 2024, "justice_id": "JGRoberts", "side": "majority", "vote": "majority", "wrote_opinion": True, "scdb_direction": "", "source": "scdb"},
        {"case_id": "2024-23-1", "term": 2024, "justice_id": "EKagan", "side": "majority", "vote": "regular concurrence", "wrote_opinion": True, "scdb_direction": "", "source": "scdb"},
        {"case_id": "2024-23-1", "term": 2024, "justice_id": "CThomas", "side": "dissent", "vote": "dissent", "wrote_opinion": False, "scdb_direction": "", "source": "scdb"},
    ])

    def justice(justice_id, last, start, title="Associate Justice", serving=True):
        return {"justice_id": justice_id, "name": f"First {last}", "last_name": last, "title": title, "appointed_by": "A President",
                "appointing_party": "Party", "start": start, "end": "" if serving else "2020-01-01", "serving": serving, "born": "1950", "died": "", "how_ended": "" if serving else "Retirement", "senate_vote": "60/40"}

    justices = pd.DataFrame([
        justice("CThomas", "Thomas", "1991-10-18"), justice("JGRoberts", "Roberts", "2005-09-29", "Chief Justice"),
        justice("EKagan", "Kagan", "2010-08-06"), justice("OldOne", "Gone", "1970-01-01", serving=False),
    ])
    applications = pd.DataFrame([
        {**{column: "" for column in sc.APPLICATION_COLUMNS}, "docket": "25A1", "term": 2025, "title": "A v. B", "kind": "extension of time",
         "capital_case": False, "referred_to_court": False, "n_entries": 1},
        {**{column: "" for column in sc.APPLICATION_COLUMNS}, "docket": "25A2", "term": 2025, "title": "C v. D", "kind": "stay", "outcome": "granted",
         "decided_by": "the Court", "date_filed": "2025-10-01", "date_resolved": "2025-10-09", "capital_case": False, "referred_to_court": True, "n_entries": 2,
         "submitted_to": "The Chief Justice"},
    ])
    entries = pd.DataFrame([
        {"docket": "25A2", "kind": "application", "seq": 0, "date": "2025-10-01", "text": "Application (25A2) for a stay, submitted to The Chief Justice."},
        {"docket": "25A2", "kind": "application", "seq": 1, "date": "2025-10-09", "text": "Application (25A2) granted by the Court."},
        {"docket": "25A2", "kind": "application", "seq": 2, "date": "2025-10-07", "text": "Application (25A2) referred to the Court."},
        {"docket": "25-9", "kind": "case", "seq": 0, "date": "2025-11-05", "text": "Argued. For petitioner: A. Lawyer. For respondent: B. Counsel."},
    ])
    terms = pd.DataFrame([
        {"term": 2024, "chief_justice": "Roberts", "cases": 1, "cases_decided": 1, "applications": 0, "paid_petitions": 10, "ifp_petitions": 20},
        {"term": 2025, "chief_justice": "Roberts", "cases": 1, "cases_decided": 0, "applications": 2, "paid_petitions": pd.NA, "ifp_petitions": pd.NA},
    ])
    return {"cases": cases, "votes": votes, "justices": justices, "applications": applications, "docket_entries": entries, "terms": terms}


def test_the_map_file_seats_the_justices_and_lines_up_their_votes():
    world, texts = snapshot.build(tables())
    names = [justice["last_name"] for justice in world["justices"]]
    assert names == ["Thomas", "Roberts", "Kagan"]  # by seniority; nobody without a vote who has left the Court
    first, second = world["terms"]
    assert [names[seat] for seat in first["justices"]] == ["Roberts", "Thomas", "Kagan"]  # the Chief first
    assert names[first["chief"]] == "Roberts" and first["paid_petitions"] == 10
    assert [names[seat] for seat in second["justices"]] == ["Roberts", "Thomas", "Kagan"]  # no votes yet: the Court as it sits
    assert second["paid_petitions"] is None and second["routine_applications"] == 1
    cases = world["cases"]
    assert cases["votes"] == ["WDC", ""]  # Roberts wrote for the Court, Thomas dissented, Kagan concurred in writing
    assert cases["winner"] == ["p", ""] and names[cases["author"][0]] == "Roberts" and cases["author"][1] == -1
    assert world["dispositions"][cases["disposition"][0]] == "reversed" and cases["disposition"][1] == -1


def test_routine_applications_are_counted_but_not_listed_and_the_words_go_to_term_files():
    world, texts = snapshot.build(tables())
    assert world["applications"]["docket"] == ["25A2"] and world["application_kinds"] == ["stay"]
    assert texts[2024]["cases"]["2024-23-1"] == ["May it?", "Held: it may not.", ""]
    assert texts[2025]["cases"]["2025-25-9"] == ["Does it?", "", "Argued. For petitioner: A. Lawyer. For respondent: B. Counsel."]
    assert texts[2025]["applications"]["25A2"] == ["Application (25A2) for a stay, submitted to The Chief Justice.", "Application (25A2) granted by the Court."]


def test_an_application_keeps_the_justice_it_went_to_and_the_day_it_was_referred():
    world, _ = snapshot.build(tables())
    applications = world["applications"]
    names = [justice["last_name"] for justice in world["justices"]]
    assert names[applications["submitted_to"][0]] == "Roberts"  # "The Chief Justice" is whoever held the chair that term
    assert applications["referred_on"] == ["2025-10-07"]
    assert snapshot.seat_of("Justice Kagan", [0, 1, 2], 1, world["justices"]) == 2
    assert snapshot.seat_of("Justice Nobody", [0, 1, 2], 1, world["justices"]) == -1 and snapshot.seat_of("", [0], 0, world["justices"]) == -1


def test_every_justice_is_listed_once_for_the_roster_and_the_plaques():
    world, _ = snapshot.build(tables())
    history = {person["id"]: person for person in world["history"]}
    assert list(history) == ["OldOne", "CThomas", "JGRoberts", "EKagan"]  # oldest first, and those with no vote on record too
    assert history["OldOne"]["end"] == "2020-01-01" and history["JGRoberts"]["chief_from"] == "2005-09-29"
