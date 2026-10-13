"""build_orange_board reads the Orange County Board's votes out of its minutes, by name or by the code in the margin, a vote whole or not at all."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import build_orange_board as oc
import council_tables


def kept(*lines):
    """Lines as they are kept of a PDF: (margin, where the line begins, its words) or with "b" last for bold. A tab in
    the words is a wide gap; "\\f" alone is a page's end."""
    out = []
    for line in lines:
        if line == "\f":
            out.append(line)
        else:
            margin, x0, words = line[:3]
            out.append("\t".join([margin, str(x0), "b" if len(line) > 3 else "-", words]) + "\n")
    return "".join(out).replace("\n\f", "\f")


# The head of minutes that print codes: the chair in the middle, the others two to a row, a name run over two lines.
HEAD = [
    ("", 189, "REGULAR MEETING OF THE BOARD OF SUPERVISORS"), ("", 223, "ORANGE COUNTY, CALIFORNIA"),
    ("", 230, "Tuesday, December 16, 2025, 9:30 A.M."), ("", 254, "BOARD HEARING ROOM, FIRST FLOOR"),
    ("", 295, "400 W. Civic Center Drive"), ("", 306, "Santa Ana, California"),
    ("", 258, "DOUG CHAFFEE"), ("", 287, "CHAIR"), ("", 270, "Fourth District"),
    ("", 78, "KATRINA FOLEY\tJANET NGUYEN"), ("", 78, "VICE CHAIR\tSUPERVISOR"), ("", 78, "Fifth District\tFirst District"),
    ("", 78, "VICENTE SARMIENTO\tDONALD P."), ("", 78, "SUPERVISOR\tWAGNER"), ("", 78, "Second District\tSUPERVISOR"),
    ("", 469, "Third District"),
    ("", 72, "ATTENDANCE: All Present"), ("", 72, "EXCUSED:\tNone"),
]
KEY = [
    ("", 273, "*** KEY ***"), ("", 138, "Left Margin Notes", "b"),
    ("", 138, "1. = Supervisor Nguyen\tA. = Abstained"), ("", 138, "2.  Supervisor Sarmiento\tX.  Excused"),
    ("", 138, "3. = Supervisor Wagner\tN. = No"), ("", 138, "4. = Supervisor Chaffee\tBO = Board Order"),
    ("", 138, "5. = Supervisor Foley"), ("", 138, "ORD.= Ordinance"), ("", 138, "RESO. = Resolution"),
    ("", 81, "Above numbers refer to Supervisorial Districts (1st number = Moved by; 2nd number ="), ("", 252, "Seconded by)"),
    ("", 325, "Chair, Orange County Board of Supervisors"),
]
ROLL = [{"name": name, "district": district, "role": role} for name, district, role in (
    ("Janet Nguyen", 1, ""), ("Vicente Sarmiento", 2, ""), ("Donald P. Wagner", 3, ""), ("Doug Chaffee", 4, "Chair"),
    ("Katrina Foley", 5, "Vice Chair"))]

# A consent calendar voted on as one, an item taken out of it, a board order, a motion that failed and one that
# carried on one item, a motion with no second, and the meeting adjourned in someone's memory.
BUSINESS = [
    ("", 72, "II. CONSENT CALENDAR (Items 1-3)", "b"),
    ("25134", 123, "APPROVED AS RECOMMENDED WITH THE EXCEPTION OF ITEM 3 WHICH WAS", "b"),
    ("", 123, "CONTINUED TO 1/13/26, 9:30 A.M.; AND ITEM 1 WHICH WAS PULLED FOR", "b"),
    ("", 123, "DISCUSSION AND SEPARATE VOTE", "b"),
    ("", 72, "OC COMMUNITY RESOURCES", "b"),
    ("1.", 123, "Acting as the Orange County Housing Authority - Receive and file FY 2024-25"),
    ("", 123, "Housing Successor Agency Annual Report - All Districts"),
    ("53124", 123, "APPROVED AS RECOMMENDED", "b"),
    ("....X", 0, ""),
    ("", 72, "OC PUBLIC WORKS", "b"),
    ("2.", 123, "Adopt resolution adopting 2025 Disaster Debris Management Plan - All Districts"),
    ("", 123, "RESO: 25-133"),
    ("3.", 123, "Receive and file Annual Report on Conditions of Children - All Districts"),
    ("B.O.", 123, "CONTINUED TO 1/13/26, 9:30 A.M.", "b"),
    ("", 72, "III. DISCUSSION ITEMS (Items 4-S5A)", "b"),
    ("", 72, "ELECTED DEPARTMENT HEADS", "b"),
    ("", 121, "Sheriff-Coroner:", "b"),
    ("4.", 155, "Approve recommended positions on legislation; and consider other"),
    ("", 155, "legislative subject matters - All Districts"),
    ("51234", 155, "APPROVED RECOMMENDED ACTIONS #1 AND #2", "b"),
    ("52134", 155, "MOTION TO APPROVE RECOMMENDED ACTION #3 FAILED TO", "b"),
    ("..NNA", 155, "CARRY", "b"),
    ("", 72, "GENERAL ADMINISTRATION", "b"),
    ("S5A.", 123, "Vice Chair Foley - Adopt ordinance amending the Codified Ordinances"),
    ("3", 123, "MOTION TO APPROVE ORDINANCE FAILED FOR LACK OF A SECOND", "b"),
    ("", 72, "V. PUBLIC, CEO, BOARD COMMENTS & ADJOURNMENT", "b"),
    ("", 72, "PUBLIC COMMENTS:", "b"),
    ("", 72, "Bryan Kaye - Oral Re: Expressed a mix of gratitude, apology, and confusion"),
    ("", 72, "ADJOURNED: 2:26 P.M.", "b"),
    ("35124", 123, "Adjourned in memory of Walter Fath", "b"),
]
MINUTES = kept(*HEAD, *BUSINESS, *KEY)

# Minutes that name the voters. The page's head and foot are no part of a title.
NAMED = kept(
    ("", 147, "S U M M A R Y A C T I O N M I N U T E S", "b"),
    ("", 154, "REGULAR MEETING OF THE BOARD OF SUPERVISORS"), ("", 215, "ORANGE COUNTY, CALIFORNIA"),
    ("", 208, "Tuesday, September 29, 2026, 9:00 A.M."), ("", 253, "Santa Ana, California"),
    ("", 258, "DOUG CHAFFEE", "b"), ("", 287, "CHAIR"), ("", 271, "Fourth District"),
    ("", 45, "KATRINA FOLEY\tJANET NGUYEN", "b"), ("", 45, "VICE CHAIR\tSUPERVISOR"), ("", 45, "Fifth District\tFirst District"),
    ("", 45, "VICENTE SARMIENTO\tDONALD P. WAGNER", "b"), ("", 45, "SUPERVISOR\tSUPERVISOR"), ("", 45, "Second District\tThird District"),
    ("", 45, "ATTENDANCE:\tAll Present"), ("", 45, "EXCUSED:\tNone"),
    ("", 45, "CONSENT CALENDAR (Items 1-2)", "b"),
    ("", 45, "ON THE MOTION OF SUPERVISOR SARMIENTO, SECONDED BY SUPERVISOR WAGNER,", "b"),
    ("", 45, "APPROVED AS RECOMMENDED WITH THE EXCEPTION OF ITEM 2 WHICH WAS", "b"),
    ("", 45, "PULLED FOR DISCUSSION AND SEPARATE VOTE", "b"),
    ("", 45, "Ayes:\tNguyen, Sarmiento, Wagner, Chaffee and Foley"),
    ("", 45, "ELECTED DEPARTMENTS"),
    ("", 45, "1.\tAuditor-Controller - Receive and file Annual Report of Refunds - All Districts"),
    ("", 88, "(Click to View Files)"),
    ("", 88, "ON THE MOTION OF SUPERVISOR SARMIENTO, SECONDED BY SUPERVISOR", "b"),
    ("", 88, "WAGNER, APPROVED ITEM AS RECOMMENDED", "b"),
    ("", 88, "Ayes:\tNguyen, Sarmiento, Wagner, Chaffee and Foley"),
    ("", 85, "MINUTES - BOARD OF SUPERVISORS' MEETING, TUESDAY, SEPTEMBER 29, 2026 - PAGE 2", "b"),
    ("", 219, "Document Last Updated: 10/01/2026 10:10 AM", "b"),
    "\f",
    ("", 147, "S U M M A R Y A C T I O N M I N U T E S", "b"),
    ("", 45, "2.\tRegistrar of Voters - Receive and file Certificate of Nominees - All"),
    ("", 88, "Districts (Click to View Files)"),
    ("", 88, "RECEIVED AND FILED; SUPERVISOR NGUYEN NOTED OBJECTION", "b"),
    ("", 221, "END OF CONSENT CALENDAR"),
    ("", 45, "DISCUSSION ITEMS (Items 3-S4A )", "b"),
    ("", 45, "COUNTY DEPARTMENTS"),
    ("", 45, "3.\tCounty Executive Office - Approve proposed response to FY 2025-26 Grand Jury Report -"),
    ("", 88, "All Districts (Click to View Files)"),
    ("", 88, "ON THE MOTION OF CHAIR CHAFFEE, SECONDED BY SUPERVISOR WAGNER,", "b"),
    ("", 88, "APPROVED ITEM AS RECOMMENDED", "b"),
    ("", 88, "Ayes:\tNguyen, Wagner and"),
    ("", 88, "Chaffee"),
    ("", 88, "Noes:\tSarmiento and Foley"),
    ("", 88, "Resolution No(s). 26-074"),
    ("", 45, "S4A .\tSupervisor Sarmiento - Approve sponsorship of various nonprofit entities (Click to View Files)"),
    ("", 88, "ON THE MOTION OF SUPERVISOR SARMIENTO, SECONDED BY CHAIR", "b"),
    ("", 88, "CHAFFEE, APPROVED ITEM AS RECOMMENDED", "b"),
    ("", 88, "Ayes:\tNguyen, Sarmiento, Wagner and Chaffee"),
    ("", 88, "Abstained: Foley"),
    ("", 45, "MEMORIAL ADJOURNMENTS:"),
    ("", 45, "ON THE MOTION OF VICE CHAIR FOLEY, SECONDED BY CHAIR CHAFFEE, ADJOURNED", "b"),
    ("", 45, "IN MEMORY OF JUDITH WARE (Click to View"),  # the link after it, broken over the line's end
    ("", 45, "Files)"),
    ("", 45, "Ayes:\tNguyen, Sarmiento, Wagner and Chaffee"),
    ("", 45, "Excused: Foley"),
    ("", 45, "ADJOURNED: 6:42 P.M."),
)
DAY = "2025-12-16"


def read(text, day=DAY):
    agenda, votes, facts = oc.read_minutes(text, day, day)
    return {row["item_id"]: row for row in agenda}, votes, facts


def cast_on(votes, item_id, motion=1):
    return [(vote["member"], vote["vote"]) for vote in votes if vote["item_id"] == item_id and vote["motion"] == motion]


def test_a_listing_row_gives_the_day_the_minutes_and_the_recording():
    page = """<table><tbody><tr>
      <td data-label="Meeting Title">Board Meeting Morning</td><td data-label="Meeting Date">06/23/2020</td>
      <td data-label="Meeting Location">OC BOS Board Room</td>
      <td data-label="Accessible Minutes with Hyperlinks to Documents">
        <a href="https://ocagendaext.oc.gov/LegacyDocViewer/A5D466FE-6b61-4367-a849-b7672021c912" target="_blank">06/23/2020 Minutes</a> (PDF)</td>
      <td data-label="Board Meeting Video" class="watch-live"><a href="https://ocagendaext.oc.gov/ArchivedBosMeetingVideo/301">v</a></td></tr>
      <tr><td data-label="Meeting Title">Administration of the Oaths of Office</td><td data-label="Meeting Date">01/10/2023</td>
      <td data-label="Accessible Minutes with Hyperlinks to Documents">None</td><td data-label="Board Meeting Video"></td></tr>
      <tr><td data-label="Meeting Title">Board Of Supervisors Regular Meeting</td>
      <td data-label="Meeting Date/Time">
10/13/2026, 9:30 AM (PST)  </td><td data-label="Meeting Location">County Administration North</td>
      <td data-label="Agenda"><a href="https://ocagendaext.oc.gov/ExtDocViewer/ec31caca-7035-444d-8ae6-811e0728d406">10/13/2026 Regular Agenda</a></td></tr>
      </tbody></table>"""
    morning, oaths, coming = oc.rows_of(page, "ArchivedBosMeetings")
    assert (morning["date"], morning["title"], morning["location"], morning["time"]) == ("2020-06-23", "Board Meeting Morning", "OC BOS Board Room", "")
    assert morning["key"] == "a5d466fe-6b61-4367-a849-b7672021c912"  # in small letters, whatever the listing has
    assert morning["minutes_url"].endswith("/LegacyDocViewer/A5D466FE-6b61-4367-a849-b7672021c912")
    assert morning["video_url"].endswith("/ArchivedBosMeetingVideo/301")
    assert (oaths["date"], oaths["key"], oaths["minutes_url"]) == ("2023-01-10", "", "")
    assert (coming["date"], coming["time"], coming["minutes_url"]) == ("2026-10-13", "9:30 AM", "") and coming["agenda_url"].endswith("811e0728d406")
    line = oc.unread("2023-01-10", [oaths])
    assert (line["meeting_id"], line["summary"], line["minutes_url"], line["documents"]) == ("2023-01-10", "", "", "[]")


def test_the_head_of_the_minutes_is_read_by_its_columns_and_the_key_by_its_entries():
    lines = oc.lines_of(MINUTES)
    assert oc.seats_of(lines) == ROLL
    assert oc.key_of(lines) == ({1: "nguyen", 2: "sarmiento", 3: "wagner", 4: "chaffee", 5: "foley"}, True)
    assert oc.roll_of(lines, "codes") == (ROLL, "")
    assert oc.head_of(lines) == {"kind": "Regular", "date": "2025-12-16", "time": "9:30 AM"}
    # An older head: a name and an office over two lines each, and a seat with nobody in it.
    older = oc.lines_of(kept(
        ("", 230, "Tuesday, January 12, 2021, 9:30 A.M."), ("", 221, "ANDREW DO"), ("", 227, "CHAIRMAN"), ("", 273, "First District"),
        ("", 72, "LISA A.\tVACANT"), ("", 72, "BARTLETT\tSUPERVISOR"), ("", 72, "VICE\tSecond District"), ("", 72, "CHAIRMAN"),
        ("", 72, "Fifth District"), ("", 72, "ATTENDANCE: All Present"),
        ("", 273, "***KEY***"), ("", 138, "1.  Supervisor Do\tA.  Abstained"), ("", 138, "2.  Vacant\tX.  Excused"),
        ("", 138, "3.  Supervisor Wagner\tN.  No"), ("", 138, "4.  Supervisor Chaffee\tBO  Board Order"), ("", 138, "5.  Supervisor Bartlett"),
        ("", 81, "Above numbers refer to Supervisorial Districts (1st number = Moved by; 2nd number = Seconded by)")))
    assert oc.seats_of(older) == [{"name": "Andrew Do", "district": 1, "role": "Chairman"}, {"name": "Lisa A. Bartlett", "district": 5, "role": "Vice Chairman"}]
    assert oc.key_of(older) == ({1: "do", 2: None, 3: "wagner", 4: "chaffee", 5: "bartlett"}, True)
    # A key with full names, a letter of which is also a mark's.
    full = oc.lines_of(kept(("", 272, "*** KEY ***"), ("", 80, "1. ( Supervisor Lisa A. Bartlett"), ("", 80, "A. ( Abstained"),
                            ("", 80, "2. ( Chairman Bill Campbell"), ("", 80, "X. ( Excused"), ("", 80, "N. ( No")))
    assert oc.key_of(full) == ({1: "bartlett", 2: "campbell"}, False)  # it does not say what the first two places are
    assert oc.key_of(oc.lines_of(NAMED)) == (None, False)
    assert oc.who("VICE CHAIR FOLEY", ROLL) == "Katrina Foley" and oc.who("Wagner", ROLL) == "Donald P. Wagner"
    assert (oc.named("DONALD WAGNER"), oc.named("JOHN M.W. MOORLACH"), oc.named("ANDREW DO")) == ("Donald P. Wagner", "John M. W. Moorlach", "Andrew Do")
    # Minutes with codes that happen to have a line beginning "Ayes:" are still minutes with codes.
    assert oc.form_of(oc.lines_of(MINUTES + kept(("", 72, "Ayes: none of this is a vote")))) == "codes" and oc.form_of(oc.lines_of(NAMED)) == "names"
    assert oc.who("Bartlett", ROLL) is None and oc.who("Nguyen 7. Adopt", ROLL) is None


def test_a_code_is_read_by_the_key_and_a_mark_belongs_to_the_number_above_it():
    cast, problem = oc.read_code("52134", "..ANN", ROLL)
    assert problem == ""
    assert cast == [("Katrina Foley", "AYE"), ("Vicente Sarmiento", "AYE"), ("Janet Nguyen", "ABSTAINED"), ("Donald P. Wagner", "NO"),
                    ("Doug Chaffee", "NO")]
    assert oc.read_code("35124", "", ROLL)[0] == [(name, "AYE") for name in ("Donald P. Wagner", "Katrina Foley", "Janet Nguyen", "Vicente Sarmiento", "Doug Chaffee")]
    assert oc.read_code("35124", "....X", ROLL)[0][-1] == ("Doug Chaffee", "EXCUSED")
    assert {council_tables.vote_word(word) for word in oc.MARKS.values()} == {"NO", "ABSTAINED", "EXCUSED"}
    # With a seat empty, a code has four numbers.
    four = [member for member in ROLL if member["district"] != 2]
    assert oc.read_code("3541", "...N.", four)[0] == [("Donald P. Wagner", "AYE"), ("Katrina Foley", "AYE"), ("Doug Chaffee", "AYE"), ("Janet Nguyen", "NO")]


@pytest.mark.parametrize("code, marks, roll, why", [
    ("43252", "", ROLL, "the code 43252 does not have each seated district once"),
    ("2345", "", ROLL, "the code 2345 does not have each seated district once"),
    ("35124", "", ROLL[1:], "the code 35124 does not have each seated district once"),
    ("35124", "?????", ROLL, "a mark stands under no number"),
    ("3541", "....X", [member for member in ROLL if member["district"] != 2], "a mark stands beyond the end of the code 3541"),
    ("51234", ".X...", ROLL, "the code 51234 has a mark under its mover or seconder"),
    ("24351", "NN...", ROLL, "the code 24351 has a mark under its mover or seconder"),  # a row typed at the margin's edge, not under its numbers
    ("35124", "", [], "no roll to hold the code to"),
])
def test_a_code_that_does_not_read_cleanly_is_not_read_at_all(code, marks, roll, why):
    assert oc.read_code(code, marks, roll) == (None, why)


def test_a_block_of_names_gives_aye_and_no_one_spelling_and_keeps_the_other_words_in_capitals():
    cast, problem = oc.read_block(["Ayes: Nguyen, Wagner and", "Chaffee", "Noes: Sarmiento", "Abstained: Foley"], ROLL)
    assert problem == ""
    assert cast == [("Janet Nguyen", "AYE"), ("Donald P. Wagner", "AYE"), ("Doug Chaffee", "AYE"), ("Vicente Sarmiento", "NO"),
                    ("Katrina Foley", "ABSTAINED")]
    assert oc.read_block(["Ayes: Nguyen, Sarmiento, Wagner and Chaffee", "Excused: Foley"], ROLL)[0][-1] == ("Katrina Foley", "EXCUSED")
    assert {council_tables.vote_word(word) for word in oc.LABELS} == {"AYE", "NO", "ABSTAINED", "EXCUSED"}


@pytest.mark.parametrize("lines, why", [
    (["Ayes: Wagner, Chaffee and Foley", "Excused: Sarmiento"], "4 of 5 supervisors named"),  # one recused herself, and is in no list
    (["Ayes: Nguyen, Sarmiento, Wagner, Chaffee and Bartlett"], "not on the roll: Bartlett"),
    (["Ayes: Nguyen, Sarmiento, Wagner, Chaffee and Foley", "Noes: Foley"], "named twice: Katrina Foley"),
    (["Ayes: Nguyen, Sarmiento, Wagner, Chaffee and Foley 14. Sheriff-Coroner"], "not on the roll: Foley 14. Sheriff-Coroner"),
    (["Noes: Sarmiento and Foley", "Ayes: Nguyen, Wagner and Chaffee"], "words missing or out of order: Noes Ayes"),
    (["Noes: Nguyen, Sarmiento, Wagner, Chaffee and Foley"], "words missing or out of order: Noes"),
])
def test_a_block_that_does_not_read_cleanly_is_not_read_at_all(lines, why):
    assert oc.read_block(lines, ROLL) == (None, why)
    assert oc.read_block(["Ayes: Nguyen"], [])[0] is None  # no roll to hold it to


def test_minutes_with_codes_are_read_into_headings_items_and_the_votes_on_each_motion():
    agenda, votes, facts = read(MINUTES)
    assert list(agenda) == [f"{DAY}-{item}" for item in ("s1", "1", "2", "3", "s2", "4", "S5A", "s3", "u1")]
    assert (facts["summary"], facts["format"], facts["kind"], facts["time"], facts["problem"]) == ("read", "codes", "Regular", "9:30 AM", "")
    assert (facts["vote_blocks"], facts["blocks_read"], json.loads(facts["roll"])) == (5, 5, ROLL)
    consent, pulled = agenda[f"{DAY}-s1"], agenda[f"{DAY}-1"]
    assert (consent["heading"], consent["title"], consent["mover"], consent["seconder"]) == \
        (True, "II. CONSENT CALENDAR (Items 1-3)", "Vicente Sarmiento", "Katrina Foley")
    assert consent["action"].endswith("ITEM 1 WHICH WAS PULLED FOR DISCUSSION AND SEPARATE VOTE")
    assert (consent["ayes"], consent["noes"], consent["not_voting"], consent["votes_read"]) == (5, 0, 0, True)
    assert pulled["title"] == "Acting as the Orange County Housing Authority - Receive and file FY 2024-25 Housing Successor Agency Annual Report - All Districts"
    assert (pulled["action"], pulled["mover"], pulled["seconder"], pulled["group"]) == \
        ("APPROVED AS RECOMMENDED", "Katrina Foley", "Donald P. Wagner", "OC COMMUNITY RESOURCES")
    assert (pulled["ayes"], pulled["noes"], pulled["not_voting"]) == (4, 0, 1)
    assert cast_on(votes, f"{DAY}-1") == [("Katrina Foley", "AYE"), ("Donald P. Wagner", "AYE"), ("Janet Nguyen", "AYE"),
                                          ("Vicente Sarmiento", "AYE"), ("Doug Chaffee", "EXCUSED")]
    assert {(vote["code"], vote["marks"]) for vote in votes if vote["item_id"] == f"{DAY}-1"} == {("53124", "....X")}
    # A number under the item, a board order with no vote, and a department's own heading.
    adopted, continued = agenda[f"{DAY}-2"], agenda[f"{DAY}-3"]
    assert (adopted["number"], adopted["doc_type"], adopted["action"], adopted["vote_blocks"], adopted["votes_read"]) == ("25-133", "resolution", "", 0, None)
    assert (continued["action"], continued["motions"], continued["vote_blocks"]) == ("CONTINUED TO 1/13/26, 9:30 A.M.", 1, 0)
    # Two votes on one item: the line carries the last, which failed, and each is in the votes.
    positions = agenda[f"{DAY}-4"]
    assert (positions["group"], positions["motions"], positions["vote_blocks"], positions["blocks_read"]) == ("ELECTED DEPARTMENT HEADS - Sheriff-Coroner", 2, 2, 2)
    assert (positions["action"], positions["result"]) == ("MOTION TO APPROVE RECOMMENDED ACTION #3 FAILED TO CARRY", "Fail")
    assert (positions["ayes"], positions["noes"], positions["not_voting"]) == (2, 2, 1)
    assert cast_on(votes, f"{DAY}-4", 2) == [("Katrina Foley", "AYE"), ("Vicente Sarmiento", "AYE"), ("Janet Nguyen", "NO"),
                                             ("Donald P. Wagner", "NO"), ("Doug Chaffee", "ABSTAINED")]
    assert {word for _, word in cast_on(votes, f"{DAY}-4", 1)} == {"AYE"}
    # One number is a mover whose motion had no second: an action, and no vote.
    lone = agenda[f"{DAY}-S5A"]
    assert (lone["agenda_number"], lone["group"], lone["mover"], lone["seconder"], lone["vote_blocks"], lone["result"]) == \
        ("S5A", "GENERAL ADMINISTRATION", "Donald P. Wagner", "", 0, "Fail")
    # The meeting's end has no number, and the motion to adjourn in someone's memory is voted on.
    end = agenda[f"{DAY}-u1"]
    assert (end["agenda_number"], end["title"], end["action"], end["ayes"]) == ("", "ADJOURNED: 2:26 P.M.", "Adjourned in memory of Walter Fath", 5)
    assert len(votes) == 25 and {vote["motion_text"] for vote in votes if vote["item_id"] == f"{DAY}-u1"} == {"Adjourned in memory of Walter Fath"}


def test_a_consent_item_takes_the_calendars_vote_unless_the_motion_left_it_out():
    agenda, votes, facts = read(MINUTES)
    # Item 3 was continued and item 1 pulled; the day it was continued to (1/13/26) is not an item's number.
    assert [agenda[f"{DAY}-{item}"]["voted_with"] for item in ("1", "2", "3", "4")] == [f"{DAY}-1", f"{DAY}-s1", "", f"{DAY}-4"]
    table = pd.DataFrame(list(agenda.values()), columns=oc.AGENDA_COLUMNS)
    meetings = pd.DataFrame([{"meeting_id": DAY, "minutes_url": "https://example.test/minutes"}])
    items = oc.items_table(oc.typed(table, pd.DataFrame(votes, columns=oc.VOTE_COLUMNS))[0], meetings).set_index("matter_id")
    assert set(items["url"]) == {"https://example.test/minutes"} and len(items) == 6
    assert list(items.loc[[f"{DAY}-{item}" for item in ("1", "2", "3", "4")], "action_on"]) == ["item", "section", "", "item"]
    two = items.loc[f"{DAY}-2"]
    assert (two["last_action"], two["ayes"], two["noes"], two["mover"], two["doc_type"], two["number"], two["votes_read"]) == \
        (agenda[f"{DAY}-s1"]["action"], 5, 0, "Vicente Sarmiento", "resolution", "25-133", True)
    assert (items.loc[f"{DAY}-4", "result"], items.loc[f"{DAY}-3", "ayes"], items.loc[f"{DAY}-3", "last_action"]) == ("Fail", 0, "CONTINUED TO 1/13/26, 9:30 A.M.")


def test_minutes_that_name_the_voters_are_read_the_same_way():
    day = "2026-09-29"
    agenda, votes, facts = read(NAMED, day)
    assert list(agenda) == [f"{day}-{item}" for item in ("s1", "1", "2", "s2", "3", "S4A", "u1")]
    assert (facts["format"], facts["pages"], facts["vote_blocks"], facts["blocks_read"], facts["time"]) == ("names", 2, 5, 5, "9:00 AM")
    assert [member["name"] for member in json.loads(facts["roll"])] == [member["name"] for member in ROLL]
    consent = agenda[f"{day}-s1"]
    assert (consent["heading"], consent["mover"], consent["seconder"], consent["ayes"]) == (True, "Vicente Sarmiento", "Donald P. Wagner", 5)
    assert consent["action"] == "APPROVED AS RECOMMENDED WITH THE EXCEPTION OF ITEM 2 WHICH WAS PULLED FOR DISCUSSION AND SEPARATE VOTE"
    one, two, divided = agenda[f"{day}-1"], agenda[f"{day}-2"], agenda[f"{day}-3"]
    assert (one["title"], one["group"], one["action"], one["voted_with"]) == \
        ("Auditor-Controller - Receive and file Annual Report of Refunds - All Districts", "ELECTED DEPARTMENTS", "APPROVED ITEM AS RECOMMENDED", f"{day}-1")
    # An action with no motion has no vote; the title ran over the page's end, past its head and foot.
    assert two["title"] == "Registrar of Voters - Receive and file Certificate of Nominees - All Districts"
    assert (two["action"], two["vote_blocks"], two["votes_read"], two["voted_with"]) == ("RECEIVED AND FILED; SUPERVISOR NGUYEN NOTED OBJECTION", 0, None, "")
    assert (divided["mover"], divided["seconder"], divided["ayes"], divided["noes"], divided["number"], divided["doc_type"]) == \
        ("Doug Chaffee", "Donald P. Wagner", 3, 2, "26-074", "resolution")
    assert cast_on(votes, f"{day}-3") == [("Janet Nguyen", "AYE"), ("Donald P. Wagner", "AYE"), ("Doug Chaffee", "AYE"),
                                          ("Vicente Sarmiento", "NO"), ("Katrina Foley", "NO")]
    assert cast_on(votes, f"{day}-S4A")[-1] == ("Katrina Foley", "ABSTAINED") and agenda[f"{day}-S4A"]["not_voting"] == 1
    # A motion at the margin under no heading is no item's: its title is the words above it.
    memory = agenda[f"{day}-u1"]
    assert (memory["title"], memory["action"], memory["mover"], memory["not_voting"]) == \
        ("MEMORIAL ADJOURNMENTS:", "ADJOURNED IN MEMORY OF JUDITH WARE", "Katrina Foley", 1)
    assert len(votes) == 25 and {vote["code"] for vote in votes} == {""}


def test_a_motion_whose_vote_cannot_be_read_is_kept_with_no_votes_and_says_why():
    agenda, votes, facts = read(MINUTES.replace("53124\t", "53122\t"))
    unread = agenda[f"{DAY}-1"]
    assert (unread["action"], unread["vote_blocks"], unread["blocks_read"], unread["votes_read"]) == ("APPROVED AS RECOMMENDED", 1, 0, False)
    assert (unread["ayes"], unread["noes"], unread["not_voting"], unread["mover"]) == (0, 0, 0, "")
    assert unread["problem"] == "the code 53122 does not have each seated district once"
    assert not cast_on(votes, f"{DAY}-1") and len(votes) == 20 and (facts["vote_blocks"], facts["blocks_read"]) == (5, 4)
    assert '"read":false,"problem":"the code 53122' in unread["motion_log"]
    # A recusal leaves a supervisor out of a block of names, which is then not read.
    agenda, votes, facts = read(NAMED.replace("Ayes:\tNguyen, Sarmiento, Wagner and Chaffee\n\t88\t-\tAbstained: Foley", "Ayes:\tNguyen, Sarmiento, Wagner and Chaffee"),
                                "2026-09-29")
    assert (agenda["2026-09-29-S4A"]["problem"], agenda["2026-09-29-S4A"]["votes_read"], len(votes)) == ("4 of 5 supervisors named", False, 20)


def test_where_the_margin_does_not_say_for_certain_what_a_mark_is_under_the_vote_is_left_unread():
    def item_one(*lines):
        agenda, votes, facts = read(kept(*HEAD, ("1.", 123, "First Item"), *lines, *KEY))
        return json.loads(agenda[f"{DAY}-1"]["motion_log"]), votes
    # The marks at the top of the next page.
    log, votes = item_one(("53124", 123, "APPROVED AS RECOMMENDED", "b"), "\f", ("....X", 0, ""))
    assert (log[0]["read"], log[0]["problem"], votes) == (False, "the marks stand on the page after their code's", [])
    # A second row of marks.
    log, votes = item_one(("53124", 123, "APPROVED AS RECOMMENDED", "b"), ("....X", 0, ""), ("..N..", 0, ""))
    assert (log[0]["read"], log[0]["problem"]) == (False, "two rows of marks under one code")
    # A code that ran over the margin's end: the mark is under its last number, on a line of its own.
    log, votes = item_one(("2345", 111, "APPROVED AS RECOMMENDED", "b"), ("1", 0, ""), ("X....", 0, ""))
    assert (len(log), log[0]["read"], log[0]["problem"], votes) == (1, False, "the code ran over the margin onto a second line", [])
    # Marks under a board order.
    log, votes = item_one(("B.O.", 123, "RECEIVED AND FILED", "b"), ("..X..", 0, ""))
    assert (log[0]["block"], votes) == (False, [])
    # A row of marks under an action of two lines shares the second line, and is read.
    log, votes = item_one(("25143", 123, "APPROVED AMENDMENT TO COMPLETE CONSTRUCTION MANAGEMENT", "b"), ("...X.", 123, "FOR UP TO $205,550", "b"))
    assert (log[0]["read"], log[0]["action"], log[0]["marks"]) == (True, "APPROVED AMENDMENT TO COMPLETE CONSTRUCTION MANAGEMENT FOR UP TO $205,550", "...X.")
    assert ("Doug Chaffee", "EXCUSED") in cast_on(votes, f"{DAY}-1")


def test_where_the_key_is_not_the_board_of_that_day_nothing_in_the_minutes_is_read():
    stale = MINUTES.replace("2.  Supervisor Sarmiento", "2.  Supervisor Foley").replace("5. = Supervisor Foley", "5. = Supervisor Bartlett")
    agenda, votes, facts = read(stale)
    assert facts["problem"] == "the key and the head of the minutes name different supervisors for district 2"
    assert (facts["summary"], facts["vote_blocks"], facts["blocks_read"], facts["roll"], votes) == ("read", 5, 0, "", [])
    assert {row["problem"] for row in agenda.values() if row["vote_blocks"]} == {facts["problem"]}
    assert agenda[f"{DAY}-3"]["action"] == "CONTINUED TO 1/13/26, 9:30 A.M."  # what is not a vote is read all the same
    # No key at all, or one that does not say what the marks are.
    assert read(kept(*HEAD, *BUSINESS))[2]["problem"] == "the minutes print no key to their codes"
    assert read(MINUTES.replace("N. = No", "N. = Nay"))[2]["problem"] == "the key does not say what every number and mark means"


def test_a_vote_that_has_someone_voting_whom_the_head_has_excused_for_the_day_is_not_read():
    away = MINUTES.replace("ATTENDANCE: All Present", "ATTENDANCE: Supervisors: Foley, Nguyen, Sarmiento and Wagner").replace("EXCUSED:\tNone", "EXCUSED:\tChair Chaffee")
    agenda, votes, facts = read(away)
    assert oc.away_of(oc.lines_of(away), ROLL) == ["Doug Chaffee"]
    # Only item 1's code has the mark under his number; in the others he is an aye, which the head says he was not there to be.
    assert [(row["item_id"], row["blocks_read"]) for row in agenda.values() if row["vote_blocks"]] == [
        (f"{DAY}-s1", 0), (f"{DAY}-1", 1), (f"{DAY}-4", 0), (f"{DAY}-u1", 0)]
    assert agenda[f"{DAY}-s1"]["problem"] == "the head of the minutes has Doug Chaffee excused for the day, and this vote does not"
    assert len(votes) == 5 and ("Doug Chaffee", "EXCUSED") in cast_on(votes, f"{DAY}-1")
    # A head that says more than a name does not say the supervisor was away all day.
    late = oc.lines_of(MINUTES.replace("EXCUSED:\tNone", "EXCUSED:\tSupervisor Foley arrived during Public Comments"))
    assert oc.away_of(late, ROLL) == [] and oc.away_of(oc.lines_of(MINUTES), ROLL) == []
    assert oc.away_of(oc.lines_of(MINUTES.replace("EXCUSED:\tNone", "EXCUSED:\tSupervisors: Nguyen and Wagner")), ROLL) == ["Janet Nguyen", "Donald P. Wagner"]


def test_minutes_that_are_a_scan_an_agenda_or_another_days_are_counted_and_left():
    agenda, votes, facts = read("\f\f \f")
    assert (agenda, votes, facts["summary"], facts["pages"]) == ({}, [], "no text layer", 4)
    assert read(kept(("", 216, "A\tG\tE\tN\tD\tA", "b"), *HEAD, *BUSINESS))[2]["summary"] == "an agenda, not minutes"
    agenda, votes, facts = read(MINUTES, "2025-12-02")
    assert (agenda, votes, facts["summary"], facts["problem"]) == ({}, [], "minutes of another day", "the minutes are headed 2025-12-16")


def test_a_refusal_is_not_asked_again_and_an_answer_that_is_no_pdf_is_not_read(monkeypatch):
    asked = []

    class Answer:
        status_code, headers, content, text = 403, {"content-type": "text/html"}, b"<html>", "<html>"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(oc.requests, "get", lambda url, **kwargs: asked.append(url) or Answer())
    monkeypatch.setattr(oc.time, "sleep", lambda seconds: None)
    try:
        with pytest.raises(oc.Refused):
            oc.fetch(oc.HOST + "/ArchivedBosMeetings")
        with pytest.raises(oc.Refused):
            oc.fetch(oc.HOST + "/ArchivedBosMeetings")
        assert len(asked) == 1
    finally:
        oc._refused.clear()
    # The system answers 200 with a line of words where a document is missing.
    Answer.status_code, Answer.headers, Answer.content = 200, {"content-type": "application/pdf"}, b"Failed to connect to database"
    with pytest.raises(oc.NotPdf, match="Failed to connect to database"):
        oc.fetch_pdf(oc.HOST + "/LegacyDocViewer/x")
    assert not oc._refused.is_set()


def listing_row(key, date, title="Board Meeting", minutes=True):
    return {"key": key if minutes else "", "title": title, "date": date, "time": "", "location": "OC BOS Board Room", "listing": "ArchivedBosMeetings",
            "minutes_url": f"https://example.test/{key}" if minutes else "", "agenda_url": "", "video_url": f"https://example.test/video/{key}"}


def test_a_days_rows_with_the_same_minutes_are_one_meeting(monkeypatch, tmp_path):
    stamp = lambda text, when: b"%PDF" + text.encode() + b"/ModDate(D:2026092415" + when + b")"  # the system stamps each answer with the time
    sent = {"am": stamp(MINUTES, b"0001"), "pm": stamp(MINUTES, b"0002"), "special": stamp(MINUTES.replace("REGULAR", "SPECIAL"), b"0003"),
            "lost": None, "word": b"PK"}
    asked = []

    def fetch_pdf(url):
        asked.append(url.rsplit("/", 1)[1])
        if sent[asked[-1]] is None:
            raise ConnectionError("no answer")
        if not sent[asked[-1]].startswith(b"%PDF"):
            raise oc.NotPdf("the system sent a Word document in place of the minutes")
        return sent[asked[-1]]

    monkeypatch.setattr(oc, "fetch_pdf", fetch_pdf)
    monkeypatch.setattr(oc, "pdf_text", lambda body: body[4:].decode().split("/ModDate")[0])
    assert oc.same_bytes(sent["am"], sent["pm"]) and not oc.same_bytes(sent["am"], sent["special"])
    rows = [listing_row("am", DAY, "Board Meeting Morning"), listing_row("pm", DAY, "Board Meeting Afternoon"), listing_row("lost", DAY, "Board Meeting Read Out"),
            listing_row("special", DAY, "Special Board Meeting"), listing_row("oaths", DAY, "Oaths of Office", minutes=False)]
    meetings, agenda, votes = oc.read_day(DAY, rows, tmp_path)
    assert [(m["meeting_id"], m["kind"], json.loads(m["documents"])) for m in meetings] == [(DAY, "Regular", ["am", "pm"]), (f"{DAY}-2", "Special", ["special"])]
    assert meetings[0]["name"] == "Board Meeting Morning; Board Meeting Afternoon; Oaths of Office" and meetings[0]["minutes_url"].endswith("/am")
    assert (meetings[0]["summary"], meetings[0]["format"], meetings[0]["vote_blocks"], meetings[0]["blocks_read"], meetings[0]["items"]) == ("read", "codes", 5, 5, 6)
    assert {row["meeting_id"] for row in agenda} == {DAY, f"{DAY}-2"} and len(votes) == 50
    assert f"{DAY}-2-S5A" in {row["item_id"] for row in agenda}
    # What was read is kept, a second row of the same minutes as a pointer to the first; only the row that failed is asked for again.
    assert (tmp_path / "text" / "pm.txt").read_text() == "=am" and not (tmp_path / "text" / "lost.txt").exists()
    asked.clear()
    again = oc.read_day(DAY, rows, tmp_path)
    assert asked == ["lost"] and [m["documents"] for m in again[0]] == [m["documents"] for m in meetings]
    # A day none of whose documents can be had is left for the next run.
    assert oc.read_day("2025-12-02", [listing_row("lost", "2025-12-02")], tmp_path) is None
    # What the system sends that is not a PDF is not asked for twice: alone it is a meeting with no minutes read, and
    # beside real minutes it is listed with them.
    meetings, agenda, votes = oc.read_day("2025-12-02", [listing_row("word", "2025-12-02")], tmp_path)
    assert [(m["meeting_id"], m["summary"], m["problem"], m["documents"]) for m in meetings] == \
        [("2025-12-02", "not a PDF", "the system sent a Word document in place of the minutes", '["word"]')] and not agenda and not votes
    asked.clear()
    meetings, agenda, votes = oc.read_day(DAY, [listing_row("word", DAY, "Closed Session Report"), listing_row("am", DAY)], tmp_path)
    assert asked == [] and [(m["summary"], json.loads(m["documents"]), m["minutes_url"][-3:]) for m in meetings] == [("read", ["am", "word"], "/am")]


def test_a_days_first_meeting_is_its_regular_one_and_an_agenda_beside_minutes_is_no_meeting(monkeypatch, tmp_path):
    supplement = kept(("", 200, "ORANGE COUNTY BOARD OF SUPERVISORS"), ("", 150, "A g e n d a R e v i s i o n s a n d S u p p l e m e n t a l s"),
                      ("", 72, "Note: This supplemental agenda is updated daily showing items that have been added, continued, deleted or modified. " * 3),
                      ("", 72, "Ayes: this is no vote"))
    sent = {"agenda": supplement, "special": MINUTES.replace("REGULAR", "SPECIAL").replace("9:30 A.M.", "8:30 A.M."), "regular": MINUTES}
    monkeypatch.setattr(oc, "fetch_pdf", lambda url: b"%PDF" + sent[url.rsplit("/", 1)[1]].encode())
    monkeypatch.setattr(oc, "pdf_text", lambda body: body[4:].decode())
    rows = [listing_row("agenda", DAY, "Board Meeting Morning"), listing_row("special", DAY, "Special Board Meeting 8:30"), listing_row("regular", DAY, "Board Meeting Afternoon")]
    meetings, agenda, votes = oc.read_day(DAY, rows, tmp_path)
    assert [(m["meeting_id"], m["kind"], m["time"], m["summary"], json.loads(m["documents"])) for m in meetings] == [
        (DAY, "Regular", "9:30 AM", "read", ["regular", "agenda"]), (f"{DAY}-2", "Special", "8:30 AM", "read", ["special"])]
    assert meetings[0]["minutes_url"].endswith("/regular") and meetings[0]["name"] == "Board Meeting Afternoon; Board Meeting Morning"
    # Where the agenda is all the day has, the day is a meeting with no minutes read.
    meetings, agenda, votes = oc.read_day(DAY, rows[:1], tmp_path)
    assert [(m["meeting_id"], m["summary"], m["format"], m["items"]) for m in meetings] == [(DAY, "an agenda, not minutes", "", 0)] and not agenda and not votes


def test_a_run_reads_the_newest_first_skips_what_it_has_read_and_writes_the_five_tables(monkeypatch, tmp_path):
    days = [f"2025-{month:02d}-{day:02d}" for month in range(1, 13) for day in range(1, 10)]
    rows = [listing_row(f"k{place}", date) for place, date in enumerate(days)] + [listing_row("again", days[-1], "Board Meeting Read Out")]
    rows += [listing_row("none", "2026-01-05", minutes=False)]
    asked = []

    def fetch_pdf(url):
        asked.append(url.rsplit("/", 1)[1])
        if asked[-1] == f"k{len(days) - 3}":
            raise ConnectionError("no answer")
        day = next(row["date"] for row in rows if row["key"] == asked[-1])
        return (b"%PDF" + MINUTES.replace("December 16, 2025", f"{oc._MONTHS[int(day[5:7]) - 1].title()} {int(day[8:])}, 2025").encode())

    monkeypatch.setattr(oc, "listed", lambda: rows)
    monkeypatch.setattr(oc, "fetch_pdf", fetch_pdf)
    monkeypatch.setattr(oc, "pdf_text", lambda body: body[4:].decode())
    monkeypatch.setattr(oc, "RECENT_DAYS", 0)
    monkeypatch.setattr(council_tables, "published", lambda repo, name: None)
    monkeypatch.setattr(county_of(), "WORKERS", 1)
    tables, read = oc.build(True, False, tmp_path, limit=2)
    assert (asked, read) == ([f"k{len(days) - 1}", "again", f"k{len(days) - 2}"], 2)
    tables, read = oc.build(True, False, tmp_path, limit=2)
    assert (asked[3:], read) == ([f"k{len(days) - 3}", f"k{len(days) - 4}"], 1)  # the day that could not be had is asked for again next time
    tables, read = oc.build(True, False, tmp_path, since=2026)
    assert (asked[5:], read) == ([], 0)
    assert {name: list(table.columns[:len(council_tables.COLUMNS[name])]) for name, table in tables.items()} == council_tables.COLUMNS
    meetings = tables["meetings"].set_index("meeting_id")
    assert len(meetings) == len(days) + 1 and list(meetings.loc[[days[-1], days[-3], days[-4], days[-5], "2026-01-05"], "summary"]) == ["read", "", "read", "", ""]
    newest = meetings.loc[days[-1]]
    assert (newest["items"], newest["vote_blocks"], newest["blocks_read"], json.loads(newest["documents"])) == (6, 5, 5, [f"k{len(days) - 1}", "again"])
    assert len(tables["votes"]) == 75 and set(tables["votes"]["vote"]) == {"AYE", "NO", "ABSTAINED", "EXCUSED"}
    members = tables["members"].set_index("name")
    assert sorted(members.index) == sorted(member["name"] for member in ROLL)
    assert (members.loc["Katrina Foley", "district"], members.loc["Katrina Foley", "role"], members.loc["Katrina Foley", "votes"]) == (5, "Vice Chair", 15)
    assert members["serving"].all() and set(members["first_vote"]) == {days[-4]}
    assert all((tmp_path / f"{name}.parquet").exists() for name in council_tables.TABLES)
    assert "{" not in oc.card(tables).split("## Where it comes from")[1]  # every fact the card asks for was written in


def county_of():
    import build_sd_county
    return build_sd_county
