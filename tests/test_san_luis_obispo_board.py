"""build_san_luis_obispo_board reads the San Luis Obispo County Board's votes out of minutes that print them by name:
a list of names under AYES, NOES and ABSENT on a web page until 2011, a grid of Xs in a PDF since. A motion whole or
not at all. Nothing here asks anything of the network."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import build_san_luis_obispo_board as slo
import council_tables

T = "\t"
MEETING = {"meeting_id": "2700", "date": "2017-06-20", "minutes_url": "https://example.test/MinutesViewer.php?clip_id=2700"}

# Minutes as the reader keeps them from a PDF: a line set in from the margin begins with spaces, an empty line is a
# gap on the page, a form feed parts two pages, and a grid's cells are parted by tabs. From the minutes of 10 July
# 2012, 8 July 2014 and 20 June 2017, cut short.
GRID = f" SUPERVISORS{T}AYES{T}NOES{T}ABSTAIN{T}RECUSE\n"
ROWS = lambda *marks: "".join(f" {name}{T}{T.join('x' if at == mark else '' for at in range(4))}\n" for name, mark in zip(
    ("Peschong, John (Chairperson)", "Hill, Adam (Vice Chairperson)", "Gibson, Bruce S (Board Member)", "Compton, Lynn (Board Member)",
     "Arnold, Debbie (Board Member)"), marks))
MINUTES = f"""Board of Supervisors Page 1 of 3

                                                                Tuesday, June 20, 2017

The Board of Supervisors of the County of San Luis Obispo, and ex-officio the governing body of all other special
assessment and taxing districts for which said Board so acts, met in regular session at 9:00 AM.

PRESENT: Supervisors: Bruce S. Gibson, Adam Hill, Lynn Compton, Debbie Arnold, and Chairperson John
                    Peschong
ABSENT: None

THE PLEDGE OF ALLEGIANCE IS LED BY CHAIRPERSON JOHN PESCHONG.

Consent Agenda – Review and Approval:

1-5. This is the time set for consideration of the Consent Agenda.

      Chairperson Peschong: opens the floor to public comment.

      Supervisor Arnold: requests Consent Agenda Item No. 3 be pulled for a separate vote.

      Supervisor Hill: states he will be abstaining from voting on Item No. 4.

      The action taken for Consent Agenda items 1 through 2 and 4 through 5 on the following vote is indicated
      for each item. (Item No. 3 is pulled for separate action.)

      Motion by: Debbie Arnold
      Second by: Bruce S. Gibson

{GRID}{ROWS(0, 0, 0, 0, 0)}
Supervisor Compton: votes no on Item No. 2.

Items Set for Hearing:

1. Setting a public hearing to consider a resolution declaring intention to levy annual assessments for Tract
      1747 Streetlight Assessment District, Nipomo. Hearing date set for July 11, 2017. District 4.

      The Board approves as recommended by the County Administrative Officer. RESOLUTION NO. 2017-157,
      adopted.

Consent Agenda - Board of Supervisors Items:

2. Request to appoint Robyn DeRohan as a District 4 representative to the Commission on the Status of
      Women. All Districts.

      The Board approves as recommended by the County Administrative Officer.

3. Submittal of a resolution calling and giving notice of the holding of special all mail ballot election. Districts
      1 and 5.

      The Board pulls this item for separate action.
Board of Supervisors Page 2 of 3

4. Request to approve a renewal service contract (Clerk’s File) for Direct Family Services. All Districts.

      Supervisor Hill: abstains from voting on this item.

      The Board approves as recommended by the County Administrative Officer.

5. Submittal of right of way documents accepting conveyance for the Willow Road Project. District 4.

      This item is withdrawn, per the addendum to the agenda.

Items Pulled for Separate Action:

      Supervisors Hill and Gibson: question why these items are being pulled from the Consent Agenda
      without discussion.
3.
Board of Supervisors Page 3 of 3

      Submittal of a resolution calling and giving notice of the holding of special all mail ballot election. Districts
      1 and 5.

      The Board adopts RESOLUTION NO. 2017-170, a resolution of the Board of Supervisors calling and giving
      notice of the holding of special all mailed ballot elections.

      Motion by: Bruce S. Gibson
      Second by: Lynn Compton

{GRID}{ROWS(0, 0, 0, 0, 1)}
Hearings:

6. Hearing to consider an ordinance amending Title 22 of the County Code. All Districts.

      Supervisor Compton: states she is recusing herself from participating on this item and is now absent.

      Chairperson Peschong: opens the floor to public comment.

      The Board directs staff to agendize an item to hear staff’s analysis, motion fails.

      Motion by: Bruce S. Gibson
      Second by: Adam Hill

{GRID}{ROWS(1, 0, 0, None, 1)[:0]} Peschong, John (Chairperson){T}{T}x{T}{T}
 Hill, Adam (Vice Chairperson){T}x{T}{T}{T}
 Gibson, Bruce S (Board Member){T}x{T}{T}{T}
 Arnold, Debbie (Board Member){T}{T}x{T}{T}

      Supervisor Compton is now present.

      ORDINANCE NO. 3350, an ordinance amending Title 22 of the County Code, adopted.

      Motion by: Lynn Compton
      Second by: John Peschong

{GRID}{ROWS(0, 0, 3, 0, 0)}
7. Hearing to consider an appeal. District 2.

      The Board continues this hearing to Tuesday, July 18, 2017.

      Motion by: Adam Hill
      Second by: Bruce S. Gibson

{GRID} Peschong, John (Chairperson){T}x{T}{T}{T}
 Hill, Adam (Vice Chairperson){T}x{T}{T}{T}
 Gibson, Bruce S (Board Member){T}x{T}{T}{T}
 Arnold, Debbie (Board Member){T}x{T}{T}{T}

On motion duly made and unanimously carried, the Board of Supervisors of the County of San Luis Obispo, and
ex-officio the governing body of all other special assessment and taxing districts for which said Board so acts, does
now adjourn.
"""

# The same, as the minutes of 2020 on print a grid: the district with each name, a name too long for its cell run on
# to a second line (and the Xs then no longer on the lines of their names), and a supervisor absent left out.
LATER = f"""BOARD OF SUPERVISORS 1 of 1

The Board of Supervisors of the County of San Luis Obispo met in regular session at 9:00 A.M.

 PRESENT: Supervisors: John Peschong, Bruce S. Gibson, Debbie Arnold and Chairperson Lynn
                        Compton

 ABSENT: Supervisor: Adam Hill

 BOARD BUSINESS:

 01 Request to approve a Funding Agreement with the Central Coast Water Authority. All Districts.

        The Board authorizes the Director of Public Works to sign a Funding Agreement.

        Motion By: Compton, Lynn
        Second By: Gibson, Bruce S.

        Board Members:{T}AYES:{T}NOES:{T}ABSTAIN:{T}RECUSE:
        Lynn Compton (Chairperson, District 4){T}X{T}{T}{T}
        Bruce S. Gibson (Vice-Chairperson, District{T}X{T}{T}{T}
        2){T}{T}X{T}{T}
        John Peschong (Board Member, District 1){T}{T}X{T}{T}
        Debbie Arnold (Board Member, District 5)

        The motion on the floor fails. No action taken.
"""

# Minutes as the reader keeps them from a web page: a line of the agenda opens with §, then its place, its number and
# its words; a label and what it labels are parted by a tab. From the minutes of 16 December 2008, cut short.
PAGE = f"""Tuesday, December 16, 2008
The Board of Supervisors of the County of San Luis Obispo, and ex-officio the governing body of all other special assessment and taxing districts for which said Board so acts, met in regular session at 9:00 a.m.
PRESENT:{T}Supervisors: Harry L. Ovitt, Bruce S. Gibson, Jerry Lenthall, K.H. 'Katcho' Achadjian, and Chairperson James R. Patterson
ABSENT:{T}None
§{T}{T}{T}THE PLEDGE OF ALLEGIANCE TO THE FLAG IS LED BY CHAIRPERSON JAMES R. PATTERSON.
§{T}2{T}CA-1{T}This is the time set for consideration of the Consent Agenda.
Thereafter, on motion of Supervisor K.H. 'Katcho' Achadjian, seconded by Supervisor Jerry Lenthall, and on the following roll call vote:
AYES:{T}Supervisors: K.H. 'Katcho' Achadjian, Jerry Lenthall, Harry L. Ovitt, Bruce S. Gibson, Chairperson James R. Patterson
NOES:{T}None
ABSENT:{T}None
Item A-2-B is approved (with Supervisor Gibson abstaining). Item A-3 is withdrawn. Consent Agenda Items A-1 through A-3 are approved as recommended by the County Administrative Officer and as amended by this Board. (SUPERVISOR GIBSON VOTED NO ON ITEM A-2-A)
§{T}{T}{T}Administrative Office Items:
§{T}{T}A-1{T}Revised San Luis Obispo County Emergency Operations Plan (Clerk’s File), Approved.
Staff Report
§{T}{T}A-2{T}Submittal of 2 resolutions approving new land conservation contracts, Approved.
§{T}{T}A.{T}RESOLUTION NO. 2008-435, AGP2007-00016 - Proposal by Johansing, Adopted.
§{T}{T}B.{T}RESOLUTION NO. 2008-436, AGP2007-00018 - Proposal by Michael, Adopted.
§{T}{T}A-3{T}Submittal of a resolution approving a new contract, Withdrawn.
§{T}4{T}C-8{T}The Board takes into consideration the continued hearing regarding Santa Margarita Ranch.
Mr. Eric Greening: speaks.
Thereafter, on motion of Supervisor Bruce S. Gibson, seconded by Supervisor James R. Patterson, and on the following roll call vote:
AYES:{T}Supervisors: Bruce S. Gibson, Chairperson James R. Patterson
NOES:{T}Supervisors: Harry L. Ovitt, Jerry Lenthall, K.H. 'Katcho' Achadjian
ABSENT:{T}None
to continue the hearing to February 10, 2009, motion fails.
Thereafter, on motion of Supervisor Harry L. Ovitt, seconded by Supervisor Jerry Lenthall, and on the following roll call vote:
AYES:{T}Supervisors: Harry L. Ovitt, Jerry Lenthall, K.H. 'Katcho' Achadjian
NOES:{T}Supervisors: Bruce S. Gibson, Chairperson James R. Patterson
ABSENT:{T}None
the Board continues the hearing to Friday, December 19, 2008 at 10 a.m.
§{T}5{T}B-1{T}This is the time set for a presentation commending David L. Johnson upon his retirement.
Thereafter, on motion of Supervisor , seconded by Supervisor , and on the following roll call vote:
AYES:{T}Supervisors: , , Harry L. Ovitt, Bruce S. Gibson, Jerry Lenthall, K.H. 'Katcho' Achadjian, Chairperson James R. Patterson
NOES:{T}None
ABSENT:{T}None
§{T}6{T}C-9{T}This is the time set for hearing to consider an appeal.
Thereafter, on motion of Supervisor Harry L. Ovitt, seconded by Supervisor Jerry Lenthall, and on the following roll call vote:
AYES:{T}Supervisors: Harry L. Ovitt, Jerry Lenthall, K.H. 'Katcho' Achadjian
NOES:{T}Supervisor: Bruce S. Gibson
ABSENT:{T}None
RESOLUTION NO. 2008-452, resolution denying the appeal, adopted.
On motion duly made and unanimously carried, the Board of Supervisors of the County of San Luis Obispo does now adjourn.
"""


def read(text=MINUTES, page=None, meeting=MEETING, scan=None):
    scanned = (scan or slo.scan_pdf)(text)
    agenda, votes, facts = slo.read_meeting(meeting, scanned, page)
    return {row["item_id"]: row for row in agenda}, votes, facts, scanned


def cast(votes, item_id, motion=1):
    return {vote["member"]: vote["vote"] for vote in votes if vote["item_id"] == item_id and vote["motion"] == motion}


# -- the head, and names --------------------------------------------------------------------------------------

def test_the_head_gives_the_roll_the_hour_and_the_chair():
    scanned = slo.scan_pdf(MINUTES)
    assert scanned["roll"] == ["Bruce S. Gibson", "Adam Hill", "Lynn Compton", "Debbie Arnold", "John Peschong"]
    assert scanned["absent"] == [] and scanned["hour"] == "9:00 AM" and scanned["session"] == "regular"
    assert scanned["roles"] == {"peschong": "Chairperson"}
    later = slo.scan_pdf(LATER)
    assert later["roll"] == ["John Peschong", "Bruce S. Gibson", "Debbie Arnold", "Lynn Compton", "Adam Hill"]
    assert later["absent"] == ["Adam Hill"]


def test_a_name_is_one_name_however_it_is_printed():
    for printed in ("Gibson, Bruce S (Board Member)", "BRUCE S. GIBSON", "Chairperson Bruce S. Gibson", "Gibson, Bruce S.",
                    "Bruce S. Gibson (Vice-Chairperson, District 2)"):
        assert slo.shown(printed) == "Bruce S. Gibson"
    assert slo.shown("K.H. 'Katcho' Achadjian") == "K.H. 'Katcho' Achadjian"
    assert slo.key_of("Dawn Ortiz-Legg (Board Member, District 3)") == "ortizlegg"
    assert slo.district_of("Dawn Ortiz-Legg (Board Member, District 3)") == 3 and slo.district_of("Hill, Adam (Board Member)") is None
    assert slo.role_of("Hill, Adam (Vice Chairperson)") == "Vice-Chairperson" and slo.role_of("Chairperson John Peschong") == "Chairperson"
    assert slo.names_in("Supervisors: , , Shirley Bianchi, and Chairperson K.H. 'Katcho' Achadjian") == ["Shirley Bianchi", "Chairperson K.H. 'Katcho' Achadjian"]
    assert slo.names_in("None") == []
    assert slo.who("ADAM HILL", ["Adam Hill", "Bruce S. Gibson"]) == "Adam Hill" and slo.who("Caren Ray", ["Adam Hill"]) is None


# -- the grid -------------------------------------------------------------------------------------------------

def test_a_grid_is_read_by_the_column_each_x_stands_under():
    agenda, votes, facts, _ = read()
    assert cast(votes, "2700-3") == {"John Peschong": "AYE", "Adam Hill": "AYE", "Bruce S. Gibson": "AYE", "Lynn Compton": "AYE", "Debbie Arnold": "NO"}
    line = agenda["2700-3"]
    assert (line["ayes"], line["noes"], line["not_voting"], line["votes_read"], line["problem"]) == (4, 1, 0, True, "")
    assert (line["mover"], line["seconder"], line["number"], line["doc_type"]) == ("Bruce S. Gibson", "Lynn Compton", "2017-170", "resolution")
    assert line["action"].startswith("The Board adopts RESOLUTION NO. 2017-170")
    assert all(vote["established"] == "named" for vote in votes)


def test_an_item_printed_twice_is_one_line_and_the_number_may_stand_alone_at_the_foot_of_a_page():
    agenda, votes, _, _ = read()
    assert [item_id for item_id in agenda if item_id.endswith("-3")] == ["2700-3"]
    assert agenda["2700-3"]["title"].startswith("Submittal of a resolution calling") and agenda["2700-3"]["section_id"] == ""
    assert "2700-motion" not in agenda


def test_a_supervisor_the_minutes_have_out_of_the_room_is_absent_and_one_merely_missing_stops_the_reading():
    agenda, votes, _, _ = read()
    first, second = cast(votes, "2700-6", 1), cast(votes, "2700-6", 2)
    assert first == {"John Peschong": "NO", "Adam Hill": "AYE", "Bruce S. Gibson": "AYE", "Debbie Arnold": "NO", "Lynn Compton": "ABSENT"}
    assert second == {"John Peschong": "AYE", "Adam Hill": "AYE", "Bruce S. Gibson": "RECUSED", "Lynn Compton": "AYE", "Debbie Arnold": "AYE"}
    assert agenda["2700-6"]["motions"] == 2 and agenda["2700-6"]["number"] == "3350" and agenda["2700-6"]["doc_type"] == "ordinance"
    # Item 7's grid has four names and the minutes have not said the fifth is away: nothing is read.
    assert cast(votes, "2700-7") == {}
    assert agenda["2700-7"]["votes_read"] is False and agenda["2700-7"]["problem"] == "names 4 of the 5 on the roll: no Lynn Compton"


def test_a_motion_the_minutes_say_failed_is_marked_and_no_other_result_is_worked_out():
    agenda, votes, _, _ = read()
    log = json.loads(agenda["2700-6"]["motion_log"])
    assert log[0]["text"].endswith("motion fails.") and agenda["2700-6"]["result"] == ""  # the line has its last motion's
    assert agenda["2700-3"]["result"] == ""
    later, later_votes, _, _ = read(LATER, meeting={"meeting_id": "3575", "date": "2020-06-16"})
    assert later["3575-1"]["result"] == "Fail"


def test_a_name_run_on_to_a_second_line_takes_the_xs_in_order_and_the_head_s_absentee_is_absent():
    agenda, votes, _, scanned = read(LATER, meeting={"meeting_id": "3575", "date": "2020-06-16"})
    assert cast(votes, "3575-1") == {"Lynn Compton": "AYE", "Bruce S. Gibson": "AYE", "John Peschong": "NO", "Debbie Arnold": "NO", "Adam Hill": "ABSENT"}
    assert (agenda["3575-1"]["ayes"], agenda["3575-1"]["noes"], agenda["3575-1"]["not_voting"]) == (2, 2, 1)
    assert ("gibson", "Bruce S. Gibson", 2) in slo.printed_names(scanned)


def test_a_grid_that_does_not_come_out_whole_is_not_read():
    short = LATER.replace(f"        2){T}{T}X{T}{T}\n", "        2)\n")
    agenda, votes, _, _ = read(short, meeting={"meeting_id": "3575", "date": "2020-06-16"})
    assert votes == [] and agenda["3575-1"]["problem"] == "the grid has 3 marks for 4 names" and agenda["3575-1"]["votes_read"] is False
    stranger = LATER.replace("John Peschong (Board Member, District 1)", "Caren Ray (Board Member, District 4)")
    agenda, votes, _, _ = read(stranger, meeting={"meeting_id": "3575", "date": "2020-06-16"})
    assert votes == [] and agenda["3575-1"]["problem"] == "not on the roll: Caren Ray"
    noted = LATER.replace(f"Lynn Compton (Chairperson, District 4){T}X{T}{T}{T}", f"Lynn Compton (Chairperson, District 4){T}X{T}{T}{T}X (Airports Fees Only)")
    agenda, votes, _, _ = read(noted, meeting={"meeting_id": "3575", "date": "2020-06-16"})
    assert votes == [] and agenda["3575-1"]["problem"] == "a note beside a mark in the grid: Airports Fees Only"
    no_head = LATER.replace(" PRESENT: Supervisors:", " Supervisors:")
    agenda, votes, _, _ = read(no_head, meeting={"meeting_id": "3575", "date": "2020-06-16"})
    assert votes == [] and agenda["3575-1"]["problem"] == "no roll at the head of the minutes"


# -- the consent agenda ---------------------------------------------------------------------------------------

def test_the_consent_agenda_s_vote_is_on_its_own_line_and_its_items_point_to_it():
    agenda, votes, facts, _ = read()
    consent = agenda["2700-consent"]
    assert consent["heading"] and consent["title"] == "Consent Agenda" and consent["agenda_number"] == "1-5"
    assert (consent["ayes"], consent["noes"], consent["votes_read"]) == (5, 0, True)
    assert len(cast(votes, "2700-consent")) == 5
    assert agenda["2700-1"]["section_id"] == "2700-consent" and pd.isna(agenda["2700-1"]["votes_read"]) and agenda["2700-1"]["motions"] == 0
    assert agenda["2700-1"]["number"] == "2017-157" and agenda["2700-1"]["section"] == "Items Set for Hearing"
    # Item 3 was pulled and item 5 withdrawn: the consent motion did not pass them.
    assert agenda["2700-3"]["section_id"] == "" and agenda["2700-5"]["section_id"] == ""
    assert facts["motions"] == 7 and facts["motions_read"] == 6


def test_a_supervisor_s_no_or_abstention_on_one_consent_item_is_that_item_s_own_vote():
    agenda, votes, _, _ = read()
    assert cast(votes, "2700-2") == {"John Peschong": "AYE", "Adam Hill": "AYE", "Bruce S. Gibson": "AYE", "Lynn Compton": "NO", "Debbie Arnold": "AYE"}
    assert cast(votes, "2700-4")["Adam Hill"] == "ABSTAIN" and list(cast(votes, "2700-4").values()).count("AYE") == 4
    assert agenda["2700-2"]["section_id"] == "" and agenda["2700-2"]["votes_read"] is True and (agenda["2700-2"]["ayes"], agenda["2700-2"]["noes"]) == (4, 1)
    assert cast(votes, "2700-consent")["Lynn Compton"] == "AYE"  # the consent agenda's own vote is as the grid has it


def test_words_of_a_vote_that_cannot_be_tied_leave_the_consent_motion_unread():
    loose = MINUTES.replace("Supervisor Compton: votes no on Item No. 2.", "Supervisor Compton: votes no on the airport items.")
    agenda, votes, _, _ = read(loose)
    assert cast(votes, "2700-consent") == {} and agenda["2700-consent"]["votes_read"] is False
    assert agenda["2700-consent"]["problem"] == "words of a vote under the consent agenda not tied to an item and a supervisor"
    assert cast(votes, "2700-4") == {}  # and nothing is made of the abstention on item 4 either
    outside = MINUTES.replace("Supervisor Compton: votes no on Item No. 2.", "Supervisor Compton: votes no on Item No. 9.")
    agenda, votes, _, _ = read(outside)
    assert cast(votes, "2700-consent") == {}


def test_a_note_in_the_consent_grid_is_that_item_s_vote():
    noted = MINUTES.replace(f" Gibson, Bruce S (Board Member){T}x{T}{T}{T}\n Compton, Lynn (Board Member){T}x{T}{T}{T}\n Arnold, Debbie (Board Member){T}x{T}{T}{T}\n\nSupervisor Compton",
                            f" Gibson, Bruce S (Board Member){T}x{T}{T}{T}X (Item 1 Only)\n Compton, Lynn (Board Member){T}x{T}{T}{T}\n Arnold, Debbie (Board Member){T}x{T}{T}{T}\n\nSupervisor Compton")
    assert noted != MINUTES
    agenda, votes, _, _ = read(noted)
    assert cast(votes, "2700-consent")["Bruce S. Gibson"] == "AYE"
    assert cast(votes, "2700-1")["Bruce S. Gibson"] == "RECUSED" and len(cast(votes, "2700-1")) == 5


def test_a_consent_agenda_passed_by_two_motions_is_two_lines():
    two = MINUTES.replace("The action taken for Consent Agenda items 1 through 2 and 4 through 5 on the following vote is indicated\n      for each item. (Item No. 3 is pulled for separate action.)",
                          "The action taken for Consent Agenda Item 1 on the following vote is indicated in the item.")
    two = two.replace("\nSupervisor Compton: votes no on Item No. 2.\n",
                      f"\n      The actions taken for Consent Agenda Items 2 through 5 on the following vote are indicated in each item.\n\n"
                      f"      Motion by: Adam Hill\n      Second by: Bruce S. Gibson\n\n{GRID}{ROWS(0, 0, 0, 1, 0)}\n")
    agenda, votes, _, _ = read(two)
    assert agenda["2700-1"]["section_id"] == "2700-consent" and agenda["2700-2"]["section_id"] == "2700-consent-2"
    assert cast(votes, "2700-consent-2")["Lynn Compton"] == "NO" and cast(votes, "2700-consent")["Lynn Compton"] == "AYE"
    assert slo.covered("1 through 9, 11 through 18 and 22 through 24") == set(range(1, 10)) | set(range(11, 19)) | {22, 23, 24}
    assert slo.covered("1–36, 46") == set(range(1, 37)) | {46}


# -- the web page of 2006 to 2011 -----------------------------------------------------------------------------

def test_a_roll_call_on_a_web_page_is_read_by_the_names_under_each_word():
    agenda, votes, facts, scanned = read(PAGE, meeting={"meeting_id": "601", "date": "2008-12-16"}, scan=slo.scan_page)
    assert scanned["roll"] == ["Harry L. Ovitt", "Bruce S. Gibson", "Jerry Lenthall", "K.H. 'Katcho' Achadjian", "James R. Patterson"]
    assert cast(votes, "601-C-8", 1) == {"Bruce S. Gibson": "AYE", "James R. Patterson": "AYE", "Harry L. Ovitt": "NO", "Jerry Lenthall": "NO",
                                          "K.H. 'Katcho' Achadjian": "NO"}
    assert list(cast(votes, "601-C-8", 2).values()).count("AYE") == 3
    line = agenda["601-C-8"]
    assert (line["motions"], line["ayes"], line["noes"], line["mover"], line["seconder"]) == (2, 3, 2, "Harry L. Ovitt", "Jerry Lenthall")
    assert json.loads(line["motion_log"])[0]["text"].endswith("motion fails.") and line["action"].startswith("the Board continues the hearing")
    assert line["section"] == ""  # a line with its place in the meeting is under no heading


def test_a_web_page_s_consent_agenda_covers_its_lettered_items_and_asides_are_tied():
    agenda, votes, _, _ = read(PAGE, meeting={"meeting_id": "601", "date": "2008-12-16"}, scan=slo.scan_page)
    listed_ = PAGE.replace("NOES:\tNone\nABSENT:\tNone\nItem A-2-B is approved (with Supervisor Gibson abstaining). Item A-3 is withdrawn. ",
                           "NOES:\tSupervisor: Bruce S. Gibson on Item A-2-B\nABSENT:\tNone\nItem A-3 is withdrawn. ")
    assert listed_ != PAGE  # the same said in the list of noes: "Bruce S. Gibson on Item A-2-B"
    assert cast(read(listed_, meeting={"meeting_id": "601", "date": "2008-12-16"}, scan=slo.scan_page)[1], "601-A-2-B")["Bruce S. Gibson"] == "NO"
    assert agenda["601-consent"]["heading"] and agenda["601-consent"]["agenda_number"] == "CA-1" and len(cast(votes, "601-consent")) == 5
    assert agenda["601-A-1"]["section_id"] == "601-consent" and agenda["601-A-1"]["section"] == "Administrative Office Items"
    assert cast(votes, "601-A-2-A")["Bruce S. Gibson"] == "NO" and cast(votes, "601-A-2-B")["Bruce S. Gibson"] == "ABSTAIN"
    assert agenda["601-A-2"]["section_id"] == "601-consent" and agenda["601-A-2-A"]["number"] == "2008-435"


def test_a_roll_call_that_is_not_whole_is_not_read():
    agenda, votes, facts, _ = read(PAGE, meeting={"meeting_id": "601", "date": "2008-12-16"}, scan=slo.scan_page)
    # A form with the mover and seconder left empty still names who voted: it is read, and has no mover.
    assert list(cast(votes, "601-B-1").values()) == ["AYE"] * 5 and agenda["601-B-1"]["mover"] == "" and agenda["601-B-1"]["votes_read"] is True
    assert cast(votes, "601-C-9") == {} and agenda["601-C-9"]["problem"] == "names 4 of the 5 on the roll: no James R. Patterson"
    assert facts["motions"] == 7 and facts["motions_read"] == 6  # the two asides on the consent agenda are motions too
    noted = PAGE.replace("NOES:\tSupervisor: Bruce S. Gibson\nABSENT:\tNone\nRESOLUTION NO. 2008-452",
                         "NOES:\tSupervisor: Bruce S. Gibson, James R. Patterson (on Exhibit A only)\nABSENT:\tNone\nRESOLUTION NO. 2008-452")
    assert noted != PAGE
    agenda, votes, _, _ = read(noted, meeting={"meeting_id": "601", "date": "2008-12-16"}, scan=slo.scan_page)
    assert cast(votes, "601-C-9") == {} and agenda["601-C-9"]["problem"] == "a note beside a name in the vote: on Exhibit A only"
    # A name printed twice under one word says one thing; under two words, two.
    twice = PAGE.replace("AYES:\tSupervisors: Harry L. Ovitt, Jerry Lenthall, K.H. 'Katcho' Achadjian\nNOES:\tSupervisor: Bruce S. Gibson\n",
                         "AYES:\tSupervisors: Harry L. Ovitt, Jerry Lenthall, K.H. 'Katcho' Achadjian, Chairperson James R. Patterson, Harry L. Ovitt\nNOES:\tSupervisor: Bruce S. Gibson\n")
    agenda, votes, _, _ = read(twice, meeting={"meeting_id": "601", "date": "2008-12-16"}, scan=slo.scan_page)
    assert len(cast(votes, "601-C-9")) == 5 and cast(votes, "601-C-9")["Harry L. Ovitt"] == "AYE"
    agenda, votes, _, _ = read(twice.replace("NOES:\tSupervisor: Bruce S. Gibson\nABSENT:\tNone\nRESOLUTION NO. 2008-452", "NOES:\tSupervisors: Bruce S. Gibson, Harry L. Ovitt\nABSENT:\tNone\nRESOLUTION NO. 2008-452"),
                               meeting={"meeting_id": "601", "date": "2008-12-16"}, scan=slo.scan_page)
    assert cast(votes, "601-C-9") == {} and agenda["601-C-9"]["problem"] == "named twice: Harry L. Ovitt"
    assert "adjourn" not in " ".join(row["action"] for row in agenda.values())


def test_a_web_page_is_kept_as_lines_with_the_agenda_s_rows_marked():
    markup = """<script>gtag('js')</script><div align=right><strong>Tuesday, December 16, 2008</strong></div>
<table><tbody><tr><td vAlign=top width=40><div><strong>PRESENT:</strong> </div></td><td vAlign=top><div>Supervisors: Harry L. Ovitt, and Chairperson James R. Patterson</div></td></tr>
<tr><td vAlign=top><div><strong>ABSENT:</strong> </div></td><td vAlign=top><div>None</div></td></tr></tbody></table>
<table cellSpacing=0><tbody><tr vAlign=top align=left>
<td width=40>2</td>
<td width=40>CA-1</td>
<td><div>This is the time set for consideration of the&nbsp;Consent Agenda.<span class=printtime> <span style="COLOR: red">(09:05 AM)</span></span> </div></td></tr></tbody></table>
<blockquote><table><tbody><tr><td width=80></td><td><div><strong>Thereafter, on motion of Supervisor&nbsp;Harry L. Ovitt, seconded by Supervisor Jerry Lenthall, and on the following roll call vote:</strong></div>
<div><table><tbody><tr><td vAlign=top><div><strong>AYES:</strong> </div></td><td vAlign=top><div><strong>Supervisors: Harry L. Ovitt, Chairperson James R. Patterson</strong> </div></td></tr>
<tr><td vAlign=top><div><strong>NOES:</strong> </div></td><td vAlign=top><div><strong> None</strong> </div></td></tr></tbody></table></div>
<div><br><strong>Consent Agenda Items A-1 through A-30 are approved.</strong></div></td></tr></tbody></table></blockquote>"""
    assert slo.page_text(markup).split("\n") == [
        "Tuesday, December 16, 2008",
        "PRESENT:\tSupervisors: Harry L. Ovitt, and Chairperson James R. Patterson",
        "ABSENT:\tNone",
        "§\t2\tCA-1\tThis is the time set for consideration of the Consent Agenda.",
        "Thereafter, on motion of Supervisor Harry L. Ovitt, seconded by Supervisor Jerry Lenthall, and on the following roll call vote:",
        "AYES:\tSupervisors: Harry L. Ovitt, Chairperson James R. Patterson",
        "NOES:\tNone",
        "Consent Agenda Items A-1 through A-30 are approved.",
    ]


# -- the listing, and where the minutes are -------------------------------------------------------------------

LISTING = """<table><thead><tr><th id="Name">Name</th></tr></thead><tbody>
<tr class="listingRow">
<td class="listItem" headers="Name" id="Board-of-Supervisors" scope="row"> Board of Supervisors </td>
<td class="listItem" headers="Date Board-of-Supervisors">Sep&nbsp;29,&nbsp;2026</td>
<td class="listItem"><a href="//slocounty.granicus.com/AgendaViewer.php?view_id=46&clip_id=5130" target="_blank">Agenda</a></td>
<td class="listItem"><form><select><option selected disabled="disabled">Documents...</option>
<option value="//slocounty.granicus.com/MinutesViewer.php?view_id=46&clip_id=5130&doc_id=977eb6e1">Item Documents</option>
<option value="//slocounty.granicus.com/MinutesViewer.php?view_id=46&clip_id=5130&doc_id=e18763f0">Minutes</option></select></form></td>
<td class="listItem"><a href="javascript:void(0);" onClick="window.open('//slocounty.granicus.com/MediaPlayer.php?view_id=46&clip_id=5130','player')">Video</a></td></tr>
<tr class="listingRow">
<td class="listItem" headers="Name" id="Addendum" scope="row"> Addendum to Board of Supervisors Agenda </td>
<td class="listItem" headers="Date Addendum">Sep 29, 2026</td>
<td class="listItem"><a href="//slocounty.granicus.com/AgendaViewer.php?view_id=46&clip_id=5131">Agenda</a></td>
<td class="listItem"><a href="//slocounty.granicus.com/MinutesViewer.php?view_id=46&clip_id=5131&doc_id=67e2e893">Item Documents</a></td></tr>
<tr class="listingRow">
<td class="listItem" headers="Name" id="Board-of-Supervisors" scope="row"> Board of Supervisors </td>
<td class="listItem" headers="Date Board-of-Supervisors">Oct 6, 2026</td>
<td class="listItem"><a href="//slocounty.granicus.com/AgendaViewer.php?view_id=46&clip_id=5137">Agenda</a></td>
<td class="listItem"><a href="//slocounty.granicus.com/MinutesViewer.php?view_id=46&clip_id=5137&doc_id=f11f0b5b">Item Documents</a></td></tr>
<tr class="listingRow">
<td class="listItem" headers="Name" id="Board-of-Supervisors" scope="row"> Board of Supervisors </td>
<td class="listItem" headers="Date Board-of-Supervisors">Dec 16, 2008</td>
<td class="listItem"><a href="//slocounty.granicus.com/AgendaViewer.php?view_id=46&clip_id=601">Agenda</a></td>
<td class="listItem"><a href="//slocounty.granicus.com/MinutesViewer.php?view_id=46&clip_id=601&doc_id=0a1b" target="_blank">12-16-08</a></td></tr>
</tbody></table>"""


def test_the_listing_gives_each_meeting_its_minutes_and_leaves_out_addenda():
    rows = slo.rows_of(LISTING)
    assert [(row["meeting_id"], row["date"]) for row in rows] == [("5130", "2026-09-29"), ("5137", "2026-10-06"), ("601", "2008-12-16")]
    assert rows[0]["minutes"] == "https://slocounty.granicus.com/MinutesViewer.php?view_id=46&clip_id=5130&doc_id=e18763f0"
    assert rows[0]["agenda"].endswith("AgendaViewer.php?view_id=46&clip_id=5130") and rows[0]["video"].endswith("MediaPlayer.php?view_id=46&clip_id=5130")
    assert rows[1]["minutes"] == ""  # "Item Documents" alone is the agenda: the minutes are not up yet
    assert rows[2]["minutes"].endswith("clip_id=601&doc_id=0a1b")  # the clerks of 2008 labelled the minutes with the day
    table = slo.meetings_table(rows)
    assert list(table["meeting_id"]) == ["601", "5130", "5137"] and list(table.columns) == slo.MEETING_COLUMNS


def test_where_the_archive_sends_a_reader_for_the_minutes():
    viewer = ("https://docs.google.com/gview?url=https%3A%2F%2Fslocounty.granicus.com%2FDocumentViewer.php%3Ffile%3Dslocounty_609b.pdf%26view%3D1"
              "&embedded=true")
    assert slo.where(viewer) == ("granicus", "https://slocounty.granicus.com/DocumentViewer.php?file=slocounty_609b.pdf&view=1", "")
    assert slo.where("http://agenda.slocounty.ca.gov/agenda/sanluisobispo/158/TWludXRlcw==/9/n/13471.doc") == ("portal meeting", "", "158")
    assert slo.where("http://agenda.slocounty.ca.gov/iip/sanluisobispo/file/getfile/110087") == (
        "portal file", "https://agenda.slocounty.ca.gov/IIP/sanluisobispo/file/getfile/110087", "")
    assert slo.where("https://example.test/minutes.pdf")[0] == "elsewhere"
    assert slo.where("https://docs.google.com/gview?url=https%3A%2F%2Fexample.test%2Fa.pdf")[0] == "elsewhere"


def test_no_other_host_is_asked_anything():
    with pytest.raises(ValueError):
        slo.fetch("https://docs.google.com/gview?url=x")


# -- the portal's page ----------------------------------------------------------------------------------------

PORTAL_PAGE = """<div class="row"><div class="filebox col-md-3 col-xs-12">Meeting files:<br />
<a aria-label="Private invitation" target="" href="/IIP/sanluisobispo/file/getfile/1986"><span title="Private invitation (158 kB)"></span></a>
<a aria-label="Minutes" target="" href="/IIP/sanluisobispo/file/getfile/4087"><span title="Minutes (392 kB)"></span></a>
</div></div>
<div id="agenda" class="agenda col-lg-12"><h3 class="agendahead">Agenda</h3>
<div class="topic"><div class="header"><strong> Consent Agenda - Board of Supervisors Items:</strong></div>
<div class="meetingitem "><div style="width:40px; float:left; overflow-wrap: break-word;" class="agendanumber">2</div>
<div style="width:70%; float:left;">Request to appoint Robyn DeRohan as a District 4 representative to the Commission on the Status of Women. All Districts.</div>
<div style="width:15%; float:right;"><a title="Agenda item details" aria-label="Agenda item" href="/IIP/sanluisobispo/agendaitem/details/654"></a>
<span id="agendaitemnumber" style="font-size:smaller">Agenda 87/2017<br /></span></div></div>
<div class="meetingitem "><div style="width:40px; float:left;" class="agendanumber">3</div>
<div style="width:70%; float:left;">An altogether different thing.</div>
<div style="width:15%; float:right;"><a aria-label="Agenda item" href="/IIP/sanluisobispo/agendaitem/details/655"></a>
<span id="agendaitemnumber" style="font-size:smaller">88/2017</span></div></div></div></div>
<div id="minutes" class="agenda col-lg-12"><h3 class="agendahead">Minutes</h3>
<div class="topic"><div class="header"><strong> Consent Agenda - Board of Supervisors Items:</strong></div>
<div class="meetingitem"><div style="width:40px; float:left;" class="agendanumber">2</div>
<div style="width:70%; float:left;">Request to appoint Robyn DeRohan as a District 4 representative.</div>
<div style="width:15%; float:right;"><a aria-label="Agenda item" href="/IIP/sanluisobispo/agendaitem/details/654"></a>
<a title="Voting details:&#xA;Voted for: 4&#xA;Voted against: 1&#xA;Did not vote: 0" aria-label="Voting details" class="agendavoting" href="/IIP/sanluisobispo/voting/details/360"></a>
<span id="agendaitemnumber" style="font-size:smaller">87/2017</span></div></div></div></div>"""


def test_the_portal_s_page_gives_an_item_its_file_number_and_the_count_it_shows():
    page = slo.page_of(PORTAL_PAGE)
    assert page["files"] == {"private agenda": "https://agenda.slocounty.ca.gov/IIP/sanluisobispo/file/getfile/1986",
                             "minutes": "https://agenda.slocounty.ca.gov/IIP/sanluisobispo/file/getfile/4087"}
    assert [(line["number"], line["file"], line["item"], line["tally"]) for line in page["lines"]] == [("2", "87/2017", "654", "4-1-0"), ("3", "88/2017", "655", "")]
    assert page["lines"][0]["section"] == "Consent Agenda - Board of Supervisors Items"
    agenda, votes, _, _ = read(page=page)
    assert (agenda["2700-2"]["matter_id"], agenda["2700-2"]["matter_file"], agenda["2700-2"]["portal_tally"]) == ("654", "87/2017", "4-1-0")
    assert {vote["matter_file"] for vote in votes if vote["item_id"] == "2700-2"} == {"87/2017"}
    # Item 3 has the same number on the page and other words: it is not taken to be the same thing.
    assert (agenda["2700-3"]["matter_id"], agenda["2700-3"]["matter_file"]) == ("2700-3", "")
    assert slo.page_of("<html>Error: Id not found.</html>") == {"found": False, "files": {}, "lines": []}
    assert slo.events_of([{"id": 15, "start": "2012-01-10T09:00:00", "description": "Meeting: BOS - 1/2012\nby: Board of Supervisors\nBegin: 9:00 AM"},
                          {"id": 16, "start": "2012-01-10T09:00:00", "description": "Meeting: ADD - 1/2012\nby: Additions, subtractions and corrections to the Board of Supervisors Agenda\nBegin: 9:00 AM"}]) == {"2012-01-10": ["15"]}


# -- the tables -----------------------------------------------------------------------------------------------

def test_the_tables_are_in_the_shared_shape():
    agenda, votes, facts, scanned = read()
    agenda_table = pd.DataFrame(list(agenda.values()), columns=slo.AGENDA_COLUMNS)
    votes_table = pd.DataFrame(votes, columns=slo.VOTE_COLUMNS)
    agenda_table, votes_table = slo.typed(agenda_table, votes_table)
    meetings = slo.meetings_table([{"meeting_id": "2700", "date": "2017-06-20", "name": "Board of Supervisors", "agenda": "", "minutes": MEETING["minutes_url"], "video": ""}])
    meetings["roll"] = [facts["roll"]]
    tables = council_tables.standard({"items": slo.items_table(agenda_table, meetings), "meetings": meetings, "agenda_items": agenda_table,
                                      "votes": votes_table, "members": slo.members_table(votes_table, meetings, {"gibson": 2}, now="2017-07-01")})
    for name in council_tables.TABLES:
        assert list(tables[name].columns[:len(council_tables.COLUMNS[name])]) == council_tables.COLUMNS[name]
    items = tables["items"].set_index("item_id")
    assert "2700-consent" not in items.index and len(items) == 7
    assert (items.loc["2700-1", "action_on"], items.loc["2700-1", "ayes"], bool(items.loc["2700-1", "votes_read"])) == ("section", 5, True)
    assert (items.loc["2700-3", "action_on"], items.loc["2700-3", "noes"]) == ("item", 1)
    assert items.loc["2700-5", "action_on"] == "" and pd.isna(items.loc["2700-5", "votes_read"])
    assert items.loc["2700-7", "votes_read"] == False and set(items["passed_date"]) == {""}  # noqa: E712
    # One day of votes does not make a member; with a second day it does.
    assert len(tables["members"]) == 0
    more = pd.concat([votes_table, votes_table.assign(date="2017-06-27")], ignore_index=True)
    members = slo.members_table(more, meetings, {"gibson": 2}, now="2017-07-01").set_index("name")
    assert list(members.index) == ["Adam Hill", "Bruce S. Gibson", "Debbie Arnold", "John Peschong", "Lynn Compton"]
    assert members.loc["Bruce S. Gibson", "district"] == 2 and pd.isna(members.loc["Adam Hill", "district"])
    assert members["serving"].all() and members.loc["John Peschong", "role"] == "Chairperson" and members.loc["Adam Hill", "role"] == ""
    assert not slo.members_table(more, meetings, now="2018-07-01")["serving"].any()


def test_one_spelling_for_each_supervisor():
    from collections import Counter
    assert slo.one_spelling({"gibson": Counter({"Bruce S. Gibson": 40, "Bruce Gibson": 2}), "mecham": Counter({"Frank Mecham": 3, "Frank R. Mecham": 3})}) == {
        "gibson": "Bruce S. Gibson", "mecham": "Frank R. Mecham"}
    agenda, votes, _, _ = slo.read_meeting(MEETING, slo.scan_pdf(MINUTES), spelled={"gibson": "Bruce Gibson"})[0:2] + (None, None)
    assert any(vote["member"] == "Bruce Gibson" for vote in votes) and not any(vote["member"] == "Bruce S. Gibson" for vote in votes)


# -- what the clerks get wrong, and what is made of it ----------------------------------------------------------

def test_two_names_run_together_at_the_head_are_parted_only_where_both_are_known():
    head = MINUTES.replace("Lynn Compton, Debbie Arnold, and", "Lynn Compton Debbie Arnold and")
    assert slo.scan_pdf(head)["roll"] == ["Bruce S. Gibson", "Adam Hill", "Lynn Compton Debbie Arnold", "John Peschong"]
    known = {"Lynn Compton", "Debbie Arnold", "Adam Hill"}
    assert slo.scan_pdf(head, known)["roll"] == ["Bruce S. Gibson", "Adam Hill", "Lynn Compton", "Debbie Arnold", "John Peschong"]
    assert slo.parted_names(["Bruce S. Gibson", "K.H. 'Katcho' Achadjian"], known | {"Bruce S. Gibson"}) == ["Bruce S. Gibson", "K.H. 'Katcho' Achadjian"]
    assert slo.names_in("None:") == [] and slo.names_in("Supervisors: Adam Hill and Chairperson Debbie Arnold and") == ["Adam Hill", "Chairperson Debbie Arnold"]


def test_a_misspelt_surname_is_that_supervisor_if_no_other_is_as_near():
    roll = ["Debbie Anrold", "Adam Hill", "Dawn Ortiz- Legg"]
    assert slo.who("Debbie Arnold (Vice-Chairperson, District 5)", roll) == "Debbie Anrold"
    assert slo.shown("Dawn Ortiz- Legg") == "Dawn Ortiz-Legg" and slo.who("Dawn Ortiz-Legg", roll) == "Dawn Ortiz- Legg"
    assert slo.who("Adam Hall", roll) is None  # too short a name to be sure of
    assert slo.near("arnold", "anrold") and slo.near("peschong", "peshong") and not slo.near("arnold", "gibson") and not slo.near("hill", "hall")
    from collections import Counter
    assert slo.one_spelling({"arnold": Counter({"Debbie Arnold": 50}), "anrold": Counter({"Debbie Anrold": 1})})["anrold"] == "Debbie Arnold"


def test_who_is_away_is_followed_through_the_clerks_own_spellings():
    roll = ["Debbie Arnold", "John Peschong", "Jimmy Paulding"]
    away = set()
    slo.now_away("(SUPERVISIOR ARNOLD IS NOW ABSENT.)", away, roll)
    assert away == {"Debbie Arnold"}
    slo.now_away("(SUPERVISOR ANROLD IS NOW PRESENT.) CHAIRPERSON PAULDING STEPS DOWN AND IS NOW ABSENT.", away, roll)
    assert away == {"Jimmy Paulding"}
    slo.now_away("Chairperson Peschong: recuses on this item due to a donation by the Bunnell Family; and is now absent.", away, roll)
    assert away == {"Jimmy Paulding", "John Peschong"}
    slo.now_away("The Appellant is now absent. Patrick McGibney is now absent. 6 PULLED FOR SEPARATE ACTION IS NOW PRESENTED:", away, roll)
    assert away == {"Jimmy Paulding", "John Peschong"}  # not supervisors
    slo.now_away("Supervisor Smith is now present.", away, roll)
    assert slo.UNSURE in away  # a supervisor came back, and which cannot be read
    # From then on a grid that leaves someone out is not read, though the minutes had said that supervisor was away.
    unsure = MINUTES.replace("Supervisor Compton: states she is recusing herself from participating on this item and is now absent.",
                             "Supervisor Compton: is now absent.\n\n      Supervisor Smith is now present.")
    agenda, votes, _, _ = read(unsure)
    assert cast(votes, "2700-6", 1) == {} and agenda["2700-6"]["problem"] == "names 4 of the 5 on the roll, and who the minutes have away cannot be read"


def test_a_line_of_the_grid_with_two_xs_or_none_is_not_made_up_from_its_neighbours():
    grid = MINUTES.replace(f" Peschong, John (Chairperson){T}{T}x{T}{T}\n Hill, Adam (Vice Chairperson){T}x{T}{T}{T}\n",
                           f" Peschong, John (Chairperson){T}x{T}x{T}{T}\n Hill, Adam (Vice Chairperson){T}{T}{T}{T}\n")
    assert grid != MINUTES
    agenda, votes, _, _ = read(grid)
    assert cast(votes, "2700-6", 1) == {} and "two marks beside John Peschong" in json.loads(agenda["2700-6"]["motion_log"])[0]["problem"]
    # A name left without its closing bracket is still one name, and the next line is the next name.
    open_ = LATER.replace(f"        Bruce S. Gibson (Vice-Chairperson, District{T}X{T}{T}{T}\n        2){T}{T}X{T}{T}\n        John Peschong (Board Member, District 1){T}{T}X{T}{T}\n"
                          "        Debbie Arnold (Board Member, District 5)\n",
                          f"        Bruce S. Gibson (Vice-Chairperson, District 2{T}X{T}{T}{T}\n        John Peschong (Board Member, District 1){T}{T}X{T}{T}\n"
                          f"        Debbie Arnold (Board Member, District 5){T}{T}X{T}{T}\n")
    assert open_ != LATER
    agenda, votes, _, _ = read(open_, meeting={"meeting_id": "3575", "date": "2020-06-16"})
    assert cast(votes, "3575-1") == {"Lynn Compton": "AYE", "Bruce S. Gibson": "AYE", "John Peschong": "NO", "Debbie Arnold": "NO", "Adam Hill": "ABSENT"}


def test_words_about_an_item_taken_off_the_consent_agenda_do_not_stop_its_reading():
    pulled = MINUTES.replace("Supervisor Compton: votes no on Item No. 2.", "Supervisor Compton: states she will need to recuse from Item No. 3.")
    agenda, votes, _, _ = read(pulled)
    assert len(cast(votes, "2700-consent")) == 5 and cast(votes, "2700-3")["Lynn Compton"] == "AYE"  # item 3's own grid says how
    chair = MINUTES.replace("Supervisor Compton: votes no on Item No. 2.", "Chairperson Peschong: recuses himself from item no. 2 and opens the floor to public comment.")
    agenda, votes, _, _ = read(chair)
    assert cast(votes, "2700-2")["John Peschong"] == "RECUSED"


def test_the_numbers_of_the_last_months_of_2011_and_the_consent_agenda_s_own_count():
    page = PAGE.replace(f"§{T}2{T}CA-1{T}", f"§{T}{T}1-2.{T}").replace("A-1 through A-3 are approved", "1 through 38 are approved")
    page = page.replace(f"§{T}{T}A-1{T}", f"§{T}{T}1.{T}").replace(f"§{T}{T}A-3{T}", f"§{T}{T}3.{T}")
    page = page.replace("Item A-2-B is approved (with Supervisor Gibson abstaining). Item A-3 is withdrawn. ", "").replace(" (SUPERVISOR GIBSON VOTED NO ON ITEM A-2-A)", "")
    agenda, votes, _, _ = read(page, meeting={"meeting_id": "1201", "date": "2011-12-13"}, scan=slo.scan_page)
    assert agenda["1201-consent"]["agenda_number"] == "1-2" and agenda["1201-1"]["section_id"] == "1201-consent"
    assert agenda["1201-3"]["section_id"] == ""  # the motion says 1 through 38; the agenda's consent items are 1 and 2
    assert slo.covers_of("A-1 through A-30 are approved", "CA-1") == {f"A-{number}" for number in range(1, 31)}
    assert slo.covers_of(" 1 through 11, 13 through 36, and added Item 46 ", "1–36, 46") == {str(number) for number in list(range(1, 12)) + list(range(13, 37)) + [46]}
    assert slo.covers_of("", "02-36 & 46") == {str(number) for number in list(range(2, 37)) + [46]}


def test_two_words_for_one_supervisor_on_one_consent_item_leave_that_item_unread():
    both = MINUTES.replace(f" Hill, Adam (Vice Chairperson){T}x{T}{T}{T}\n Gibson, Bruce S (Board Member){T}x{T}{T}{T}\n Compton, Lynn (Board Member){T}x{T}{T}{T}\n Arnold, Debbie (Board Member){T}x{T}{T}{T}\n\nSupervisor Compton",
                           f" Hill, Adam (Vice Chairperson){T}x{T}x (Item No. 4 only){T}{T}\n Gibson, Bruce S (Board Member){T}x{T}{T}{T}\n Compton, Lynn (Board Member){T}x{T}{T}{T}\n Arnold, Debbie (Board Member){T}x{T}{T}{T}\n\nSupervisor Compton")
    assert both != MINUTES
    agenda, votes, _, _ = read(both)
    # The grid has Hill's X under NOES for item 4 only; the sentences have him abstaining on it.
    assert cast(votes, "2700-4") == {} and agenda["2700-4"]["votes_read"] is False
    assert agenda["2700-4"]["problem"] == "the minutes say two things of Adam Hill on this item: ABSTAIN and NO"
    assert len(cast(votes, "2700-consent")) == 5 and cast(votes, "2700-2")["Lynn Compton"] == "NO"  # the rest stands
