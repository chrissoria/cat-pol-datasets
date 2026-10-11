"""build_california_bills reads the Legislature's export the way the Legislature writes it."""

import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import build_california_bills as ca


MEASURE = """<?xml version="1.0" encoding="UTF-8"?>
<caml:MeasureDoc xmlns:caml="http://lc.ca.gov/legalservices/schemas/caml.1#">
<caml:Description xmlns="http://www.w3.org/1999/xhtml"><caml:Id>20250AB__067993CHP</caml:Id>
<caml:Title> An act to amend Section 5006.1 of the Public Resources Code,
   relating to state parks.</caml:Title>
<caml:DigestText><p>Existing law makes the department responsible.</p><p>This bill would
		 exempt three parks.</p></caml:DigestText></caml:Description>
<caml:Bill id="bill" xmlns="http://www.w3.org/1999/xhtml"><caml:Preamble>The people of the State of California do enact as follows:</caml:Preamble>
<caml:BillSection><caml:Num>SECTION 1.</caml:Num><caml:Content><p>(a)<span class="EnSpace"/>In 2020, a fire burned the park.</p>
<p>(b)<span class="EnSpace"/>The <i>department</i> shall report.</p></caml:Content></caml:BillSection></caml:Bill></caml:MeasureDoc>"""


def row(*fields):
    return "\t".join("NULL" if field is None else str(field) if isinstance(field, int) else f"`{field}`" for field in fields)


def export_of(tmp_path, **members):
    """A small export on disk, in the shape of the Legislature's."""
    path = tmp_path / "pubinfo.zip"
    with zipfile.ZipFile(path, "w") as z:
        for name, body in members.items():
            z.writestr(name.replace("__", "."), body)
    return ca.Export(path)


def test_a_row_is_split_on_tabs_and_null_is_nothing():
    text = "`202520260AB1`\t`20252026`\t13\tNULL\n`202520260AB2`\t`20252026`\t7\t`Died`\n"
    assert list(ca.records(text, 4)) == [["202520260AB1", "20252026", "13", None], ["202520260AB2", "20252026", "7", "Died"]]


def test_a_line_break_inside_a_field_does_not_end_the_row():
    text = "`202520260AB1`\t`Read first time.\nTo print.`\t`Applied`\n"
    assert list(ca.records(text, 3)) == [["202520260AB1", "Read first time.\nTo print.", "Applied"]]


def test_a_measure_is_read_into_title_digest_and_text_one_paragraph_to_a_line():
    found = ca.read_measure(MEASURE.encode())
    assert found["long_title"] == "An act to amend Section 5006.1 of the Public Resources Code, relating to state parks."
    assert found["digest"] == "Existing law makes the department responsible.\nThis bill would exempt three parks."
    assert found["text"].split("\n") == [
        "The people of the State of California do enact as follows:",
        "SECTION 1.",
        "(a) In 2020, a fire burned the park.",
        "(b) The department shall report.",
    ]


def test_markup_that_is_not_well_formed_still_gives_its_words():
    found = ca.read_measure(b"<html><p>An act to add a section.<br>SECTION 1. It is added.</html>")
    assert found["text"] == "An act to add a section.\nSECTION 1. It is added."
    assert found["digest"] == ""


def test_a_bill_of_an_extraordinary_session_is_numbered_apart():
    assert ca.bill_number("AB", 679, "0") == "AB-679"
    assert ca.bill_number("AB", 1, "1") == "ABX1-1"
    assert ca.bill_number("SB", 3, "2") == "SBX2-3"


def test_a_house_resolution_is_the_assemblys():
    assert ca.origin_chamber("HR") == "Assembly" and ca.origin_chamber("ACA") == "Assembly"
    assert ca.origin_chamber("SR") == "Senate" and ca.origin_chamber("SB") == "Senate"
    assert ca.origin_chamber("GRP") == ""


def test_a_place_code_tells_the_house():
    assert ca.chamber_of_location("AFLOOR") == "Assembly" and ca.chamber_of_location("CX25") == "Assembly"
    assert ca.chamber_of_location("SFLOOR") == "Senate" and ca.chamber_of_location("CS61") == "Senate"
    assert ca.chamber_of_location("CONFCM") == "Conference"


def test_a_name_is_turned_the_way_it_is_said():
    assert ca.full_name("Ward, Christopher M.") == "Christopher M. Ward"
    assert ca.full_name("Avila Farias, Anamarie") == "Anamarie Avila Farias"
    assert ca.full_name("Jones, Reginald", "Jr.") == "Reginald Jones Jr."


def test_a_session_and_a_chapter_are_written_as_people_write_them():
    assert ca.session_label("20252026") == "2025-2026"
    assert ca.chapter_of("CHP", "275", "2025") == "Chapter 275, Statutes of 2025"
    assert ca.chapter_of("CHR", "12", "2025") == "Resolution Chapter 12, Statutes of 2025"
    assert ca.chapter_of(None, None, None) == ""


@pytest.fixture
def export(tmp_path):
    bills = "\n".join([
        row("202520260AB679", "20252026", "0", "AB", 679, "Chaptered", "2025", "CHP", "0", "275", "20250AB67993CHP", "Y",
            "X", None, None, None, "Secretary of State", "Chaptered", None),
        row("202520260SB4", "20252026", "0", "SB", 4, "Amended Senate", None, None, None, None, "20250SB499INT", "Y", "X",
            None, "CX25", "Committee", "Assembly", "In Committee Process", None),
        row("202520260HR1", "20252026", "0", "HR", 1, "Introduced", None, None, None, None, "20250HR199INT", "Y", "X", None,
            None, "Desk", "Assembly", "Pending Referral", None),
    ])
    versions = "\n".join([
        # The newest version has the lowest number: 99 is the bill as introduced.
        row("20250AB67999INT", "202520260AB679", 99, "2025-02-14 00:00:00", "Introduced", None, "State parks.", "Majority",
            "No", "Yes", "No", None, "No", "No") + "\tBILL_VERSION_TBL_1.lob\t`Y`\t`X`\tNULL",
        row("20250AB67993CHP", "202520260AB679", 93, "2025-10-03 00:00:00", "Chaptered", None, "State parks: three parks.",
            "Majority", "No", "Yes", "No", None, "No", "No") + "\tBILL_VERSION_TBL_2.lob\t`Y`\t`X`\tNULL",
        row("20250SB499INT", "202520260SB4", 99, "2025-01-06 00:00:00", "Introduced", None, "Insurance.", "Majority", "No",
            "No", "No", None, "Yes", "No") + "\tBILL_VERSION_TBL_3.lob\t`Y`\t`X`\tNULL",
        row("20250HR199INT", "202520260HR1", 99, "2024-12-02 00:00:00", "Introduced", None, None, None, None, None, None, None,
            None, None) + "\tBILL_VERSION_TBL_4.lob\t`Y`\t`X`\tNULL",
    ])
    authors = "\n".join([
        row("20250AB67993CHP", "Legislator", "ASSEMBLY", "Pellerin", "LEAD_AUTHOR", None, "Y", "X", None, "Y"),
        row("20250AB67993CHP", "Legislator", "SENATE", "Laird", "COAUTHOR", None, "Y", "X", None, "N"),
        row("20250AB67999INT", "Legislator", "ASSEMBLY", "Rivas", "LEAD_AUTHOR", None, "Y", "X", None, "Y"),
        row("20250SB499INT", "Committee", "SENATE", "Budget and Fiscal Review", "LEAD_AUTHOR", None, "Y", "X", None, "Y"),
    ])
    history = "\n".join([
        row("202520260AB679", 1, "2025-02-14 00:00:00", "Read first time.  To print.", "X", None, 1, "1", "Applied",
            "Assembly", "Desk", None, "Pending Referral"),
        row("202520260AB679", 2, "2025-10-03 00:00:00", "Chaptered by Secretary of State - Chapter 275, Statutes of 2025.",
            "X", None, 30, "9", "Applied", "Secretary of State", None, None, "Chaptered"),
        row("202520260SB4", 3, "2025-08-29 00:00:00", "Referred to Com. on APPR.", "X", None, 5, "2", "Applied", "Assembly",
            "Committee", "CX25", "In Committee Process"),
    ])
    summary = row("202520260AB679", "AFLOOR", "2025-05-05 14:00:00", 1012, 77, 57, 12, 10, "(PASS)", "X", None, "7", "AF",
                  "<BR/>", "2025-05-05 00:00:00")
    detail = "\n".join([
        row("202520260AB679", "AFLOOR", "Pellerin", "2025-05-05 14:00:00", 1012, "AYE", 77, "X", None, 1, None, None),
        row("202520260AB679", "AFLOOR", "Nobody", "2025-05-05 14:00:00", 1012, "NOE", 77, "X", None, 2, None, None),
    ])
    motions = row(77, "AB 679 Pellerin Assembly Third Reading", "X", None) + "\n" + row(5, "An old motion", "X", None)
    seats = "\n".join([
        row("AD28", "20252026", "Pellerin, Gail", "A", "Pellerin", "Gail", "Pellerin", None, None, "Assembly Member",
            "Assembly Member", "DEM", "Y", "X", None, "Y"),
        row("SD17", "20252026", "Laird, John", "S", "Laird", "John", "Laird", None, None, "Senator", "Senator", "DEM", "Y",
            "X", None, "Y"),
        row("AD03", "20252026", None, "A", None, None, None, None, None, None, None, None, "Y", "X", None, "Y"),
    ])
    places = "\n".join([
        row("20252026", "CX25", "B", None, "Asm Appropriations", "Appropriations", "Y", "X", None, None),
        row("20252026", "AFLOOR", "V", None, "Assembly Floor", "Assembly Floor", "Y", "X", None, None),
        row("20252026", "SF0510", "M", "29", "Sen Special Consent Calendar No. 29", "Special Consent", "Y", "X", None, None),
    ])
    hearings = row("202520260SB4", "CX", 25, "2025-09-01 00:00:00", "CX25", "X", None)
    vetoes = ""
    resolution = MEASURE.replace("<caml:DigestText>", "<caml:Old>").replace("</caml:DigestText>", "</caml:Old>") \
        .replace("An act to amend Section 5006.1 of the Public Resources Code,\n   relating to state parks.",
                 "Relative to the Standing Rules of the Assembly.")
    return export_of(tmp_path, BILL_TBL__dat=bills, BILL_VERSION_TBL__dat=versions, BILL_VERSION_AUTHORS_TBL__dat=authors,
                     BILL_HISTORY_TBL__dat=history, BILL_SUMMARY_VOTE_TBL__dat=summary, BILL_DETAIL_VOTE_TBL__dat=detail,
                     BILL_MOTION_TBL__dat=motions, LEGISLATOR_TBL__dat=seats, LOCATION_CODE_TBL__dat=places,
                     COMMITTEE_HEARING_TBL__dat=hearings, VETO_MESSAGE_TBL__dat=vetoes,
                     BILL_VERSION_TBL_1__lob="<p>the bill as introduced</p>", BILL_VERSION_TBL_2__lob=MEASURE,
                     BILL_VERSION_TBL_3__lob=MEASURE, BILL_VERSION_TBL_4__lob=resolution)


def test_a_session_is_built_from_the_newest_version_of_each_bill(export, tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "published", lambda *_: None)
    session, tables, counts = ca.build(export, tmp_path)
    assert session == "2025-2026" and counts == {"fetched": 3, "with_text": 3}
    bills = tables["bills"].set_index("bill_number")
    parks = bills.loc["AB-679"]
    assert parks["title"] == "State parks: three parks."  # the chaptered version's, not the introduced one's
    assert parks["text_version"] == "Chaptered" and parks["text"].startswith("The people of the State of California")
    assert parks["date"] == "2025-02-14" and parks["last_action_date"] == "2025-10-03"
    assert parks["sponsor_name"] == "Gail Pellerin" and parks["sponsor_ids"] == "AD28-pellerin"
    assert parks["coauthors"] == "John Laird" and parks["sponsor_party"] == "Democratic"
    assert parks["chapter"] == "Chapter 275, Statutes of 2025" and parks["roll_calls"] == 1
    assert parks["fiscal_committee"] == "Yes" and parks["urgency"] == "No"
    budget = bills.loc["SB-4"]
    assert budget["sponsor_name"] == "Committee on Budget and Fiscal Review" and budget["sponsor_ids"] == ""
    assert budget["current_committee"] == "Appropriations" and budget["current_committee_code"] == "CX25"
    assert budget["urgency"] == "Yes"
    assert bills.loc["HR-1"]["title"] == "The Standing Rules of the Assembly"  # a resolution has no subject line

    assert list(tables["legislators"]["legislator_id"]) == ["AD28-pellerin", "SD17-laird"]  # an empty seat is nobody
    assert list(tables["committees"]["committee_code"]) == ["CX25", "AFLOOR"]  # a page of the Daily File is no committee
    assert tables["actions"]["action"].iloc[0] == "Read first time. To print."
    assert tables["actions"].set_index("bill_id").loc["202520260SB4", "committee"] == "Appropriations"
    vote = tables["votes"].iloc[0]
    assert (vote["chamber"], vote["location"], vote["result"], vote["ayes"], vote["motion"]) == \
        ("Assembly", "Assembly Floor", "PASS", 57, "AB 679 Pellerin Assembly Third Reading")
    cast = tables["member_votes"].set_index("legislator")
    assert cast.loc["Pellerin", "legislator_id"] == "AD28-pellerin" and cast.loc["Nobody", "legislator_id"] == ""
    assert set(cast["vote_id"]) == {vote["vote_id"]}
    assert tables["hearings"].iloc[0]["committee"] == "Appropriations"


def test_a_text_already_held_is_not_asked_for_again(export, tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "published", lambda *_: None)
    _, tables, _ = ca.build(export, tmp_path)
    held = tables["bills"].copy()
    held.loc[held["bill_number"] == "SB-4", "text_version_id"] = "an older version"
    monkeypatch.setattr(ca, "published", lambda *_: held)
    asked = []
    read = export.read
    monkeypatch.setattr(export, "read", lambda name: (asked.append(name), read(name))[1])
    _, again, counts = ca.build(export, tmp_path)
    assert counts["fetched"] == 1 and [name for name in asked if name.endswith(".lob")] == ["BILL_VERSION_TBL_3.lob"]
    assert (again["bills"]["text"] == tables["bills"]["text"]).all()


def test_a_table_that_shrank_is_not_published(export, tmp_path, monkeypatch):
    longer = pd.DataFrame({"bill_id": [f"b{i}" for i in range(200)], "text": "words", "text_version_id": "v",
                           "text_version": "", "text_date": "", "long_title": "", "digest": "", "veto_message": ""})
    monkeypatch.setattr(ca, "published", lambda *_: longer)
    with pytest.raises(RuntimeError, match="smaller than the published one"):
        ca.build(export, tmp_path)


def test_an_older_session_says_where_a_measure_ended_only_in_its_chapter_and_history():
    bills = pd.DataFrame({"bill_id": ["a", "b", "c", "d", "e"], "measure_type": ["AB", "SB", "HR", "AB", "SR"],
                          "chapter": ["Chapter 1, Statutes of 2001", "", "", "", ""], "status": ""})
    actions = pd.DataFrame({"bill_id": ["a", "b", "c", "d", "d"],
                            "action": ["Chaptered by Secretary of State.", "Vetoed by Governor.",
                                       "Read and adopted. (Ayes 70. Noes 0.)", "Read third time, amended.",
                                       "From committee without further action."]})
    assert list(ca.settle_statuses(bills, actions)["status"]) == ["Chaptered", "Vetoed", "Passed", "Died", "Died"]
