"""build_merced_board reads the Merced County Board's agendas off the County's pages, finds the minutes among the
papers of a later agenda, and reads each vote by the districts' numbers printed beside it: a motion whole or not at
all."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import build_merced_board as merced
import council_tables

MEETING = {"meeting_id": "20260210Board", "date": "2026-02-10", "time": "10:00 AM", "name": "Board",
           "agenda_url": "https://web2.co.merced.ca.us/boardagenda/2026/20260210Board/Agenda.html"}
MINUTES_URL = "https://web2.co.merced.ca.us/boardagenda/2026/20260317Board/350338/350344/350394/350201/MINUTES350201.pdf"

# A year's listing as the site has it: the Board's meetings and those of the other bodies the supervisors sit as.
LISTING = """<table id="Meetings" width="100%">
<tr><td><img src="Images/meeting.png" alt="March 17, 2026 Board" /></td>
 <td><a target="fraAgenda" href="2026/20260317Board/Agenda.html" onClick="DocReset();">03/17/2026 8:30am Board</a></td></tr>
<tr><td><a target="fraAgenda" href="2026/20260303PublicFacilitiesCorp/Agenda.html" onClick="DocReset();">03/03/2026 10:00am Public Facilities Corp.</a></td></tr>
<tr><td><a target="fraAgenda" href="2026/20260210Board/Agenda.html" onClick="DocReset();">02/10/2026 10:00am Board</a></td></tr>
<tr><td><a target="fraAgenda" href="2026/20260203BoardAmended/Agenda.html" onClick="DocReset();">02/03/2026 10:00am Board (Amended)</a></td></tr>
<tr><td><a target="fraAgenda" href="2026/20260106ChowchillaGSA/Agenda.html" onClick="DocReset();">01/06/2026 10:00am Chowchilla GSA</a></td></tr>
<tr><td><a target="fraAgenda" href="2026/20260707IHSS/Agenda.html">07/07/2026 8:30am IHSS</a></td></tr>
<tr><td><a target="fraAgenda" href="2026/20260616BoardProposedBudgetAmended/Agenda.html">06/16/2026 8:30am Board &amp; Proposed Budget (Amended)</a></td></tr>
<tr><td><a target="fraAgenda" href="2010/MG156139/Agenda.htm">6/22/2010 7:30am Board</a></td></tr>
<tr><td><a target="fraAgenda" href="2010/MG156139/Agenda.htm#130">6/22/2010 1:30pm Proposed
                    Budget</a></td></tr>
<tr><td><a target="fraAgenda" href="2010/MG156341/Agenda.htm">6/22/2010 10:00am RDA</a></td></tr>
<tr><td><a target="fraAgenda" href="2021/2021-11-29_Special_Meeting_Agenda.pdf">11/29/2021 9:00am Special Meeting</a></td></tr>
<tr><td><a target="fraAgenda" href="2023/20230531SpecialMeeting/2023-05-31_SpecialMeetingAgenda.pdf">05/31/2023 6:00pm Special Meeting - Town Hall</a></td></tr>
<tr><td><a href="/pdfs/bos/agenda/05182009.pdf">Special Meeting for May 18, 2009 3:30 pm</a></td></tr>
</table>"""

# An agenda as the County saves it from Word: a paragraph to an item, its words a link to the page of its papers.
AGENDA = """<html><head><style>p.Items {margin:0}</style></head><body>
<p class="MsoNormal"><span>Session Items (Placeholder Section)</span></p>
<p class="MsoNormal">&#8226; CONSENT CALENDAR: These matters include routine financial and administrative action</p>
<p class="MsoNormal"><a name="AS_NAME"></a><a name="AS_RBKM"><u><span>CONSENT CALENDAR (Items No. 1-3)</span></u></a></p>
<p class="CCSection"><a name="a1"></a><a name="a2">Public Works</a></p>
<p class="Items"><a name="AI350383_NAME">1.<span>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; </span></a><a href="350338/350339/350383/Documents.htm"
 target="fraDocuments"><span>Approve a budget transfer in the amount of $8,500 to increase appropriations to Capital Asset
 No. 85717 - Ag Center HVAC Controls to cover increased project costs. (Simple Majority)</span></a><a name="AI350383_RBKM"></a></p>
<p class="Items"><a name="AI350384_NAME">2.<span>&nbsp;&nbsp;&nbsp; </span></a>PULLED</p>
<p class="CCSection">Board of Supervisors</p>
<p class="Items"><a name="AI350394_NAME">3.<span>&nbsp; </span></a><a href="350338/350344/350394/Documents.htm" target="fraDocuments"><span>Approve
 the Summary Action Minutes - Final for the January 13, 2026 Board of Supervisors meeting.</span></a></p>
<p class="MsoNormal"><b>REGULAR CALENDAR</b></p>
<p class="MsoNormal">BOARD ACTION</p>
<p class="CCSection">PUBLIC WORKS</p>
<p class="Items">4.<span>&nbsp; </span><a href="350357/350358/350453/Documents.htm">Adopt a Resolution adjusting the mileage of maintained roads
 in Merced County in 2025 to be 1,751.119 miles.</a></p>
<p class="Items">5.<span>&nbsp; </span><a href="350357/350358/350398/Documents.htm">1) Introduce an ordinance entitled &#8220;An Ordinance Amending
 Chapter 5.90 of the Merced County Code Amending Refuse Collection Fees and Charges&#8221;, and waive further reading.</a></p>
<p class="CCSection">HEALTH</p>
<p class="Items">6.<span>&nbsp; </span><a href="350357/350359/350399/Documents.htm">Adopt a Resolution naming the Dos Palos Library the
 &#8220;Jerry O&#8217;Banion Library&#8221;.</a></p>
<p class="Items">7.<span>&nbsp; </span><a href="350357/350359/350400/Documents.htm">Approve and authorize the Board Chair to sign a contract with
 Central California Alliance for Health, in an amount not to exceed $25,000.</a></p>
<p class="CCSection">BOARD APPOINTMENTS</p>
<p class="Items">8.<span>&nbsp; </span><a href="350357/350361/350402/Documents.htm">1) Reappoint Patricia Ramos Anderson to continue to serve as a
 member of the Santa Nella Municipal Advisory Council, until March 31, 2028.</a></p>
<p class="MsoNormal">BOARD INFORMATION &amp; POSSIBLE ACTION</p>
<p class="Items">9.<span>&nbsp; </span><a href="350530/350663/Documents.htm">Santa Cruz-Monterey-Merced-San Benito-Mariposa Managed Medical Care
 Commission re: 2025 Annual Report</a></p>
<p class="MsoNormal">3:00 PM - SCHEDULED ITEMS:</p>
<p class="MsoNormal"><a href="351959/352003/Documents.htm" target="fraDocuments">COMMUNITY AND ECONOMIC DEVELOPMENT - PUBLIC HEARING</a></p>
<p class="MsoNormal">To Consider Adoption of a Resolution Approving General Plan Amendment No. GPA25-003</p>
<p class="MsoNormal">RECOMMENDATION:</p>
<p class="MsoNormal">1) Open public hearing and accept public comment.</p>
<p class="MsoNormal">REPORTS/BOARD DIRECTION</p>
<p class="MsoNormal">Board of Supervisors Members, County Counsel, County Executive Officer</p>
</body></html>"""

# Minutes as the reader keeps them: a form feed parts two pages, the line along the top of a page is its first and
# the page's number its last. The lines are the Clerk's, from the minutes of 2022 to 2026.
MINUTES = """Board of Supervisors Summary Action Minutes - Final February 10, 2026
BOARD OF SUPERVISORS
Jim Pacheco, District 1
Josh Pedrozo, District 2
Chair Daron McDaniel, District 3
Vice Chair Lloyd Pareira, Jr., District 4
Scott M. Silveira, District 5
Phone: (209) 385-7366 Fax: (209) 726-7977
SUMMARY ACTION MINUTES - FINAL
TUESDAY, FEBRUARY 10, 2026
Closed Session – 8:30 a.m.
Regular Meeting – 10:00 a.m.
The REGULAR MEETING is divided into three sections:
• CONSENT CALENDAR: These matters include routine financial and administrative action and usually are
approved by a single vote.
• SCHEDULED ITEMS: These items are noticed hearings, work sessions and public hearings
1
\fBoard of Supervisors Summary Action Minutes - Final February 10, 2026
8:30 A.M. – CLOSED SESSION
THE BOARD RECESSED AT 8:32 A.M. WITH SUPERVISOR PAREIRA NOT PRESENT AND
RECONVENED AT 10:00 A.M. WITH ALL MEMBERS PRESENT AND THE BOARD CHAIR
ADVISED STAFF WAS GIVEN DIRECTION
10:00 A.M. – REGULAR MEETING
CONSENT CALENDAR (Items No. 1-3)
APPROVED AS RECOMMENDED AYES: ALL
Public Works
1. Approve a budget transfer in the amount of $8,500 to increase appropriations to Capital Asset
No. 85717 - Ag Center HVAC Controls to cover increased project costs. (Simple Majority)
2. PULLED
Board of Supervisors
3. Approve the Summary Action Minutes - Final for the January 13, 2026 Board of Supervisors
meeting.
REGULAR CALENDAR
BOARD ACTION
PUBLIC WORKS
4. Adopt a Resolution adjusting the mileage of maintained roads in Merced County in 2025 to
be 1,751.119 miles.
APPROVED AS RECOMMENDED AYES: ALL
ADOPTED RESOLUTION NO. 2026-08
5. 1) Introduce an ordinance entitled “An Ordinance Amending Chapter 5.90 of the Merced
County Code Amending Refuse Collection Fees and Charges”, and waive further reading.
SUPERVISOR MCDANIEL AND CHAIRMAN SILVEIRA PROVIDED COMMENTS
APPROVED AS RECOMMENDED AYES: 2, 3, 4 NOES: 1, 5
2
\fBoard of Supervisors Summary Action Minutes - Final February 10, 2026
HEALTH
6. Adopt a Resolution naming the Dos Palos Library the “Jerry O’Banion Library”.
SUPERVISOR MCDANIEL AND SUPERVISOR SILVEIRA PROVIDED COMMENTS
ADOPTED RESOLUTION NO. 2024-80 AS RECOMMENDED AYES: 2,3,4,5___
NOT PRESENT: 1
7. Approve and authorize the Board Chair to sign a contract with Central California Alliance for
Health, in an amount not to exceed $25,000.
AUTHORIZED CONTRACT NO. 2022103 AS RECOMMENDED AYES: 1, 2, 3, 4 NOT
PRESENT; 5
BOARD APPOINTMENTS
APPROVED AS RECOMMENDED AYES: 1,2,3,4 NOES: 5
8. 1) Reappoint Patricia Ramos Anderson to continue to serve as a member of the Santa Nella
Municipal Advisory Council, until March 31, 2028.
BOARD INFORMATION & POSSIBLE ACTION
ACCEPTED AND PLACED ON FILE AYES: ALL
9. Santa Cruz-Monterey-Merced-San Benito-Mariposa Managed Medical Care Commission re:
2025 Annual Report
SCHEDULED ITEMS:
COMMUNITY AND ECONOMIC DEVELOPMENT - PUBLIC HEARING
To Consider Adoption of a Resolution Approving General Plan Amendment No. GPA25-003
RECOMMENDATION:
1) Open public hearing and accept public comment.
2) Close the public hearing.
BOARD CHAIR MCDANIEL CLOSED THE PUBLIC HEARING
MOTION #1 FOR ITEM 3 APPROVED AS RECOMMENDED AYES: ALL
MOTION #2 FOR ITEMS 4-7 APPROVED AS RECOMMENDED AYES: 2,3,4,5 ABSTENTIONS: 1
ADOPTED RESOLUTION NO. 2026-10
ADOPTED ORDINANCE NO. 2056
SUPERVISOR PAREIRA LEFT THE MEETING AT 12:20 P.M.
REPORTS/BOARD DIRECTION
Board of Supervisors Members, County Counsel, County Executive Officer
MOTION TO RECONSIDER ITEM NO. 53 FROM THE MAY 27, 2025 BOARD MEETING.
APPROVED AS RECOMMENDED AYES: ALL
THE BOARD ADJOURNED THE MEETING AT 12:31 P.M. UNTIL TUESDAY, MARCH 3,
2026 AT 10:00 A.M.
10:00 A.M. REGULAR MEETING
PUBLIC OPPORTUNITY TO SPEAK ON NON-AGENDA ITEMS
Present: McDaniel, Pacheco, Pedrozo, Pareira, Jr., Silveira
3
"""

ROLL = [{"name": "Jim Pacheco", "district": 1, "role": ""}, {"name": "Josh Pedrozo", "district": 2, "role": ""},
        {"name": "Daron McDaniel", "district": 3, "role": "Chair"}, {"name": "Lloyd Pareira, Jr.", "district": 4, "role": "Vice Chair"},
        {"name": "Scott M. Silveira", "district": 5, "role": ""}]


def agenda():
    return merced.agenda_lines(merced.paragraphs(AGENDA))


def scanned(text=MINUTES):
    items = [line for line in agenda() if line["kind"] == "item"]
    return merced.scan(text, {line["number"]: line["title"] for line in items if line["number"]},
                       [line["head"] for line in items if not line["number"]],
                       {line["number"]: line["department"] for line in items if line["number"]})


def read(text=MINUTES, roll=ROLL):
    rows, votes, facts = merced.read_meeting(MEETING, agenda(), scanned(text), roll, MINUTES_URL)
    return {row["item_id"]: row for row in rows}, votes, facts


def votes_of(text, roll=ROLL, away=(), noted=()):
    """A vote line as (each district's word, why it was not read)."""
    parts, _, problem = merced.vote_at(text, merced._AYES.search(text).end())
    cast, why = (None, problem) if problem else merced.decide(parts, roll, away, noted)
    districts = {member["name"]: member["district"] for member in roll}
    return (None if cast is None else {districts[member]: word for member, word, _ in cast}), why


def test_a_listing_gives_the_boards_own_meetings_by_the_folder_of_their_agenda():
    rows = merced.rows_of(LISTING, 2026)
    meetings = merced.meetings_table(rows).set_index("meeting_id")
    # The corporation, the groundwater agency, the IHSS authority and the redevelopment agency are other bodies.
    assert sorted(meetings.index) == ["05182009", "2021-11-29_Special_Meeting_Agenda", "20230531SpecialMeeting", "20260203BoardAmended",
                                      "20260210Board", "20260317Board", "20260616BoardProposedBudgetAmended", "MG156139"]
    board = meetings.loc["20260317Board"]
    assert (board["date"], board["time"], board["name"], board["agenda"]) == ("2026-03-17", "8:30 AM", "Board", "html")
    assert board["agenda_url"] == "https://web2.co.merced.ca.us/boardagenda/2026/20260317Board/Agenda.html"
    assert board["url"] == "https://web2.co.merced.ca.us/boardagenda/Meetings2026.asp"
    assert meetings.loc["20260616BoardProposedBudgetAmended", "name"] == "Board & Proposed Budget (Amended)"
    # Two entries for one agenda are one meeting, and the first stands.
    assert (meetings.loc["MG156139", "date"], meetings.loc["MG156139", "time"], meetings.loc["MG156139", "name"]) == ("2010-06-22", "7:30 AM", "Board")
    # A meeting whose agenda is a PDF is known by its folder, or by the file's name where it has none.
    assert meetings.loc["20230531SpecialMeeting", "agenda"] == "pdf"
    assert meetings.loc["2021-11-29_Special_Meeting_Agenda", "agenda_url"].endswith("/boardagenda/2021/2021-11-29_Special_Meeting_Agenda.pdf")
    assert (meetings.loc["05182009", "date"], meetings.loc["05182009", "time"], meetings.loc["05182009", "name"]) == ("2009-05-18", "3:30 PM", "Special Meeting")
    assert merced.year_url(2024).endswith("Meetings2024.htm") and merced.year_url(2025).endswith("Meetings2025.asp")
    assert list(meetings.columns)[:len(council_tables.COLUMNS["meetings"]) - 1] == council_tables.COLUMNS["meetings"][1:]


def test_an_agenda_is_read_into_its_parts_its_departments_and_its_items():
    lines = agenda()
    assert [(line["kind"], line["part"], line["number"]) for line in lines] == [
        ("part", "consent", ""), ("department", "consent", ""), ("item", "consent", "1"), ("item", "consent", "2"),
        ("department", "consent", ""), ("item", "consent", "3"), ("part", "regular", ""), ("part", "action", ""),
        ("department", "action", ""), ("item", "action", "4"), ("item", "action", "5"), ("department", "action", ""),
        ("item", "action", "6"), ("item", "action", "7"), ("department", "action", ""), ("item", "action", "8"),
        ("part", "information", ""), ("item", "information", "9"), ("part", "scheduled", ""), ("item", "scheduled", ""),
        ("part", "reports", "")]
    first = lines[2]
    assert first["title"].startswith("Approve a budget transfer in the amount of $8,500") and first["title"].endswith("(Simple Majority)")
    assert (first["matter_id"], first["papers"], first["department"]) == ("350383", "350338/350339/350383/Documents.htm", "Public Works")
    # An item taken off the agenda keeps its number and has no papers.
    assert (lines[3]["title"], lines[3]["matter_id"], lines[3]["papers"]) == ("PULLED", "", "")
    # A letter for information links two folders, not three; the item's own number is still the last.
    assert lines[17]["matter_id"] == "350663"
    # A hearing has no number; what it is about is the paragraphs under it.
    hearing = lines[19]
    assert hearing["head"] == "COMMUNITY AND ECONOMIC DEVELOPMENT - PUBLIC HEARING" and hearing["matter_id"] == "352003"
    assert hearing["title"].endswith("RECOMMENDATION: 1) Open public hearing and accept public comment.")
    # A heading may open with its hour; the same words opening a sentence are not a heading, and the form's own line is left out.
    assert merced.part_of("3:00 PM - SCHEDULED ITEMS:") == "scheduled" and merced.part_of("CONSENT CALENDAR (Items # 1 - 41)") == "consent"
    assert merced.part_of("SCHEDULED ITEMS – These items are noticed hearings, work sessions and public hearings") == ""
    assert not [line for line in lines if "Placeholder" in line["title"]]


def test_an_older_agenda_has_no_classes_and_a_department_is_the_short_line_above_a_numbered_item():
    page = """<p class=MsoNormal><u><span>CONSENT CALENDAR</span></u><span> <u>(Items #1 - 38)<o:p></o:p></u></span></p>
    <p class=MsoNormal><u><span>Public Works<o:p></o:p></span></u></p>
    <p class=MsoNormal><![if !supportLists]><span><span>1.<span>&nbsp;&nbsp;&nbsp; </span></span></span><![endif]><span><a TARGET="fraDocuments"
     HREF="AS154370/AS154371/AI154555/Documents.htm">Approve and authorize the Chairman to sign Amendment</a> to Contract No. 2000125 with SCS Engineers.</span></p>
    <p class=MsoNormal>2. PULLED</p>
    <p class=MsoNormal><u><span>Mental Health</span></u></p>
    <p class=MsoNormal><span>3.&nbsp; <a HREF="AS154370/AS154372/AI154557/Documents.htm">Approve and authorize the Chairman to sign Renewal</a> Contract No. 2008190.</span></p>"""
    lines = merced.agenda_lines(merced.paragraphs(page))
    assert [(line["kind"], line["number"], line["department"]) for line in lines] == [
        ("part", "", ""), ("department", "", "Public Works"), ("item", "1", "Public Works"), ("item", "2", "Public Works"),
        ("department", "", "Mental Health"), ("item", "3", "Mental Health")]
    assert lines[2]["matter_id"] == "AI154555" and lines[2]["title"] == "Approve and authorize the Chairman to sign Amendment to Contract No. 2000125 with SCS Engineers."


def test_the_papers_of_an_item_are_listed_with_addresses_that_can_be_asked_for():
    page = """<table id="TblDocs"><tr><td><a target="_blank" href="312559/ITEM 28312559.pdf">ITEM 28</a></td></tr>
    <tr><td><a target="_blank" href="312572/BOS MINUTES312572.pdf">BOS MINUTES</a></td></tr>
    <tr><td><a target="_blank" href="244520/SEPTEMBER 10, 2019244520.pdf">SEPTEMBER 10, 2019</a></td></tr>
    <tr><td><a target="_blank" href="312573/GSA SAM312573.pdf">GSA SAM</a></td></tr></table>
    <p><a target="_blank" href="http://get.adobe.com/reader/">Adobe Acrobat Reader</a></p>"""
    base = "https://web2.co.merced.ca.us/boardagenda/2022/20220426Board/302269/302282/302360/Documents.htm"
    papers = merced.papers_of(page, base)
    assert [name for name, _ in papers] == ["ITEM 28", "BOS MINUTES", "SEPTEMBER 10, 2019", "GSA SAM"]
    assert papers[1][1] == "https://web2.co.merced.ca.us/boardagenda/2022/20220426Board/302269/302282/302360/312572/BOS%20MINUTES312572.pdf"
    assert papers[2][1].endswith("/244520/SEPTEMBER%2010%2C%202019244520.pdf") and merced.paper_id(papers[2][1]) == "244520"
    # The letter that asks for the approval is not minutes, and a groundwater agency's minutes are not the Board's.
    assert merced._ITEM_PAPER.match("ITEM 28") and merced._OTHER_BODY.search("GSA SAM") and not merced._OTHER_BODY.search("BOS MINUTES")
    assert merced._APPROVES.search("Approve the Summary Action Minutes - Final for the February 10, 2026 Board of Supervisors meeting.")
    assert merced._APPROVES.search("Approve minutes for September 10, 2019, September 17, 2019 and December 17, 2019 - IHSS.")
    assert not merced._APPROVES.search("Approve a budget transfer. Public comment is limited to three minutes.")
    assert (merced.day_in("SEPTEMBER 10, 2019"), merced.day_in("APR 14, 2020"), merced.day_in("MINUTES")) == ("2019-09-10", "2020-04-14", "")


def test_the_head_of_minutes_gives_the_board_the_day_and_whose_minutes_they_are():
    head = merced.head_of(MINUTES)
    assert head["roster"] == ROLL
    assert (head["date"], head["kind"], head["other"], head["draft"]) == ("2026-02-10", "regular", False, False)
    budget = MINUTES.replace("SUMMARY ACTION MINUTES - FINAL\n", "SUMMARY ACTION MINUTES – FINAL\nFINAL BUDGET HEARING AGENDA\n")
    assert merced.head_of(budget)["kind"] == "budget"
    assert merced.head_of(MINUTES.replace("Regular Meeting – 10:00 a.m.", "Regular Meeting & Proposed Budget – 10:00 a.m."))["kind"] == "regular"
    assert merced.head_of(MINUTES.replace("SUMMARY ACTION MINUTES - FINAL\n", "SUMMARY ACTION MINUTES - FINAL\nADDENDUM TO REGULAR AGENDA\n"))["kind"] == "addendum"
    assert merced.head_of(MINUTES.replace("MINUTES - FINAL\nTUESDAY", "MINUTES - DRAFT\nTUESDAY"))["draft"]
    # The supervisors sitting as another body: the name stands between "BOARD OF SUPERVISORS" and the Board.
    other = MINUTES.replace("BOARD OF SUPERVISORS\nJim", "BOARD OF SUPERVISORS\nAS COUNTY OF MERCED\nGROUNDWATER SUSTAINABILITY\nAGENCY - CHOWCHILLA\nJim")
    assert merced.head_of(other)["other"] and not merced.head_of(other)["roster"] == []
    assert merced.head_of(MINUTES.replace("District 5", "District5"))["roster"][4]["district"] == 5
    # The sorts of meeting the listing's labels say, against which a set of minutes is placed.
    assert [merced.kind_of(name) for name in ("Board", "", "Board (Amended)", "Board & Proposed Budget", "Final Budget Hearing", "Addendum",
                                              "Special Meeting", "Study Session")] == [
        "regular", "regular", "regular", "regular", "budget", "addendum", "special", "special"]
    day = [{"meeting_id": "20250923Board", "name": "Board"}, {"meeting_id": "20250923FinalBudgetHearing", "name": "Final Budget Hearing"}]
    assert merced.placed("regular", day) == "20250923Board" and merced.placed("budget", day) == "20250923FinalBudgetHearing"
    assert merced.placed("addendum", day) == "" and merced.placed("regular", []) == ""
    assert merced.placed("regular", [{"meeting_id": "20260320SpecialMeeting", "name": "Special Meeting"}]) == "20260320SpecialMeeting"


def test_one_pdf_may_hold_several_sets_of_minutes_and_a_scan_holds_none():
    contents = "Board of Supervisors\nSummary Action Minutes - Final\nTable of Contents\nJuly 12, 2022 - Board of Supervisors\n"
    second = MINUTES.replace("FEBRUARY 10, 2026", "MARCH 3, 2026").replace("February 10, 2026", "March 3, 2026")
    sets = merced.sets_in(contents + "\f" + MINUTES + "\f" + second)
    assert [merced.head_of(one)["date"] for one in sets] == ["2026-02-10", "2026-03-03"]  # the table of contents is of neither
    assert sets[0].count("\f") == MINUTES.count("\f")
    assert merced.sets_in("\f\f \n\f") == [] and merced.sets_in("7\n\f8") == []


def test_a_vote_is_read_by_the_districts_numbers_only_when_they_are_all_five():
    assert votes_of("APPROVED AS RECOMMENDED AYES: 2, 3, 4 NOES: 1, 5") == ({1: "NO", 2: "AYE", 3: "AYE", 4: "AYE", 5: "NO"}, "")
    assert votes_of("AYES: 1, 2, 4, 5 NOT PRESENT: 3")[0][3] == "NOT PRESENT"
    # The words and the numbers run over the line's end, a rule is drawn after them, a colon is mistyped.
    assert votes_of("AUTHORIZED CONTRACT NO. 2019276 AS RECOMMENDED AYES: 1, 2, 4, 5 NOT\nPRESENT: 3")[0] == {1: "AYE", 2: "AYE", 3: "NOT PRESENT", 4: "AYE", 5: "AYE"}
    assert votes_of("AYES: 2,3,4,5___\nNOT PRESENT: 1")[0][1] == "NOT PRESENT"
    assert votes_of("AYES: 1, 2, 3, 4 NOT\nPRESENT; 5")[0][5] == "NOT PRESENT"
    assert votes_of("AYES: 1, 3, 4, 5,\nNOT PRESENT: 2")[0][2] == "NOT PRESENT"
    assert votes_of("AYES:2,3,5 NOES:4 NOT PRESENT:1")[0] == {1: "NOT PRESENT", 2: "AYE", 3: "AYE", 4: "NO", 5: "AYE"}
    # The minutes' own words for not voting, as the tables have them.
    assert votes_of("AYES: 2,3,4,5 ABSTENTIONS: 1")[0][1] == "ABSTAIN" and votes_of("AYES: 2,3,4,5 ABSTAIN: 1")[0][1] == "ABSTAIN"
    assert votes_of("AYES: 2, 3, 5 RECUSAL: 1 AND 4")[0] == {1: "RECUSED", 2: "AYE", 3: "AYE", 4: "RECUSED", 5: "AYE"}
    # The next item's number is not one of the districts.
    assert votes_of("AYES: 2, 3, 4 NOES: 1, 5\n24. 1) Introduce an ordinance")[0][5] == "NO"
    # Numbers that are not the five districts are not read.
    assert votes_of("AYES: 1, 2, 3, 4") == (None, "nothing is said of district 5")
    assert votes_of("AYES: 1, 2, 3, 4 NOES: 4") == (None, "given twice: district 4")
    assert votes_of("AYES: 1, 2, 3, 4 NOT PRESENT: 6") == (None, "not a district: 6")
    assert votes_of("AYES: 1, 2, 3, 4 NOT PRESENT:") == (None, "nothing that can be read after NOT PRESENT:")
    assert votes_of("AYES: 2,3,4,5 NOES: 1", roll=ROLL[:4]) == (None, "the head of the minutes gives districts [1, 2, 3, 4], not the five")


def test_all_is_every_supervisor_unless_the_minutes_have_one_away():
    cast, problem = votes_of("APPROVED AS RECOMMENDED AYES: ALL")
    assert problem == "" and cast == {district: "AYE" for district in range(1, 6)}
    assert votes_of("ADOPTED RESOLUTION NOS. 2022-69 AND 2022-70 AS RECOMMENDED AYES:\nALL")[0] == cast  # over the line's end
    assert votes_of("A YES: ALL")[0] == cast and votes_of("AYES: A LL")[0] == cast and votes_of("AYES:ALL.")[0] == cast  # as two PDFs print it
    assert votes_of("AYES: ALL NOES: NONE")[0] == cast
    assert votes_of("AYES: ALL", away=["pareira"]) == (None, "ALL, and the minutes have Lloyd Pareira, Jr. not present")
    assert votes_of("AYES: ALL", noted=["McDaniel"]) == (None, "ALL, and the minutes have Daron McDaniel not present")
    assert votes_of("AYES: ALL NOT PRESENT: 3") == (None, "ALL, and something more")
    parts, _, _ = merced.vote_at("AYES: ALL", 5)
    assert {established for _, _, established in merced.decide(parts, ROLL)[0]} == {"all"}


def test_a_vote_given_by_name_is_read_against_the_roll():
    words = "APPROVED AS RECOMMENDED\nAYES: SUPERVISOR PAREIRA, SUPERVISOR PEDROZO, SUPERVISOR MCDANIEL,\nSUPERVISOR SILVEIRA\nABSTAIN: SUPERVISOR ESPINOZA"
    roll = [{"name": "Rodrigo Espinosa", "district": 1, "role": ""}] + ROLL[1:]  # the roll's spelling is the other one
    assert votes_of(words, roll=roll) == ({1: "ABSTAIN", 2: "AYE", 3: "AYE", 4: "AYE", 5: "AYE"}, "")
    assert votes_of(words) == (None, "not on the roll: ESPINOZA")
    # A supervisor is one however the head of the minutes prints them from one year to the next.
    assert merced.key_of("Scott M. Silveira") == merced.key_of("Scott Silveira") and merced.key_of("Lloyd Pareira, Jr.") == merced.key_of("Lloyd Pareira")
    assert merced.key_of("Rodrigo Espinoza") == merced.key_of("Rodrigo Espinosa") != merced.key_of("Josh Pedrozo")
    assert merced.who("BOARD CHAIR MCDANIEL", ROLL)["district"] == 3 and merced.who("Pareira, Jr.", ROLL)["district"] == 4
    assert merced.who("Lor", ROLL) is None
    assert merced.names_in("SUPERVISOR PAREIRA AND SUPERVISOR ESPINOSA") == ["PAREIRA", "ESPINOSA"]
    assert merced.names_in("McDaniel, Pacheco, Pedrozo, Pareira, Jr., Silveira") == ["McDaniel", "Pacheco", "Pedrozo", "Pareira", "Silveira"]


def test_who_is_out_of_the_room_is_followed_down_the_minutes():
    text = ("THE BOARD RECESSED AT 8:34 A.M. WITH SUPERVISOR MCDANIEL AND\nSUPERVISOR SILVEIRA NOT PRESENT AND RECONVENED AT 10:00 A.M. WITH\n"
            "SUPERVISOR MCDANIEL NOT PRESENT, AND THE CHAIRMAN ADVISED STAFF WAS GIVEN DIRECTION\nCONSENT CALENDAR\n"
            "AT 10:54 A.M. SUPERVISOR MCDANIEL RETURNED TO THE MEETING\nBOARD ACTION\nSUPERVISOR PAREIRA LEFT THE MEETING AT 12:20 P.M.\n"
            "THE BOARD RECESSED INTO CLOSED SESSION AT 12:04 P.M. WITH ALL\nMEMBERS PRESENT AND RETURNED TO THE CHAMBERS AT 12:30 P.M.")
    events = merced.comings(text)
    assert [(what, names) for _, what, names in events] == [("set", ["MCDANIEL", "SILVEIRA"]), ("set", ["MCDANIEL"]), ("came", ["MCDANIEL"]),
                                                            ("went", ["PAREIRA"]), ("set", [])]
    at = lambda words: merced.away_at(text.index(words), events)
    assert at("RECONVENED") == ["mcdaniel", "silveira"] and at("CONSENT") == ["mcdaniel"] and at("BOARD ACTION") == []
    assert at("THE BOARD RECESSED INTO") == ["pareira"] and merced.away_at(len(text), events) == []
    # The Board returning to its chambers is not a supervisor returning.
    assert not merced._CAME.search("WITH SUPERVISOR MCDANIEL NOT PRESENT AND RETURNED TO THE CHAMBERS AT 11:41 A.M.")


def test_minutes_are_laid_on_the_agenda_with_the_consent_calendars_vote_on_its_own_line():
    rows, votes, facts = read()
    assert list(rows) == [
        "20260210Board-consent", "20260210Board-d1", "20260210Board-1", "20260210Board-2", "20260210Board-d2", "20260210Board-3",
        "20260210Board-regular", "20260210Board-action", "20260210Board-d3", "20260210Board-4", "20260210Board-5", "20260210Board-d4",
        "20260210Board-6", "20260210Board-7", "20260210Board-d5", "20260210Board-8", "20260210Board-information", "20260210Board-9",
        "20260210Board-scheduled", "20260210Board-u1", "20260210Board-reports", "20260210Board-u2"]
    calendar = rows["20260210Board-consent"]
    assert (calendar["heading"], calendar["title"], calendar["action"], calendar["how"]) == (True, "CONSENT CALENDAR (Items No. 1-3)", "APPROVED AS RECOMMENDED", "AYES: ALL")
    # Pareira was out when the Board recessed and the minutes have everyone back at ten: ALL is all five.
    assert (calendar["ayes"], calendar["noes"], calendar["votes_read"], calendar["established"], calendar["result"]) == (5, 0, True, "all", "Pass")
    assert (calendar["matter_id"], calendar["section"]) == ("", "")
    item = rows["20260210Board-1"]
    assert (item["agenda_number"], item["matter_id"], item["section"], item["section_id"], item["department"]) == (
        "1", "350383", "Consent Calendar", "20260210Board-consent", "Public Works")
    assert (item["motions"], item["votes_read"], item["voted_with"], item["action"], item["source"]) == (0, None, "20260210Board-consent", "", "agenda, minutes")
    assert item["documents_url"] == "https://web2.co.merced.ca.us/boardagenda/2026/20260210Board/350338/350339/350383/Documents.htm"
    # An item pulled from the calendar was not adopted with it.
    pulled = rows["20260210Board-2"]
    assert (pulled["title"], pulled["action"], pulled["voted_with"], pulled["motions"]) == ("PULLED", "PULLED", "", 0)
    assert rows["20260210Board-d1"]["heading"] and rows["20260210Board-d1"]["title"] == "Public Works" and rows["20260210Board-d1"]["motions"] == 0
    assert (facts["minutes"], facts["motions"], facts["motions_read"], facts["pages"], facts["minutes_url"]) == ("read", 10, 9, 3, MINUTES_URL)
    assert facts["present"].startswith("THE BOARD RECESSED AT 8:32 A.M. WITH SUPERVISOR PAREIRA NOT PRESENT AND RECONVENED AT 10:00 A.M. WITH ALL MEMBERS PRESENT")
    assert json.loads(facts["roll"])[3] == {"name": "Lloyd Pareira, Jr.", "district": 4, "role": "Vice Chair"}


def test_each_items_vote_is_the_one_printed_under_it():
    rows, votes, _ = read()
    of = lambda item_id, motion=1: {vote["district"]: vote["vote"] for vote in votes if vote["item_id"] == item_id and vote["motion"] == motion}
    unanimous = rows["20260210Board-4"]
    assert (unanimous["action"], unanimous["how"], unanimous["number"], unanimous["doc_type"], unanimous["ayes"]) == (
        "APPROVED AS RECOMMENDED", "AYES: ALL", "Resolution 2026-08", "resolution", 5)
    divided = rows["20260210Board-5"]
    assert (divided["ayes"], divided["noes"], divided["not_voting"], divided["established"], divided["how"]) == (3, 2, 0, "numbers", "AYES: 2, 3, 4 NOES: 1, 5")
    assert of("20260210Board-5") == {1: "NO", 2: "AYE", 3: "AYE", 4: "AYE", 5: "NO"}
    # The vote of an item that opens a page, and one whose words run over a line.
    away = rows["20260210Board-6"]
    assert (away["action"], away["how"], away["ayes"], away["not_voting"]) == ("ADOPTED RESOLUTION NO. 2024-80 AS RECOMMENDED", "AYES: 2,3,4,5 NOT PRESENT: 1", 4, 1)
    assert of("20260210Board-6")[1] == "NOT PRESENT" and rows["20260210Board-6"]["number"] == "Resolution 2024-80"
    assert of("20260210Board-7") == {1: "AYE", 2: "AYE", 3: "AYE", 4: "AYE", 5: "NOT PRESENT"} and rows["20260210Board-7"]["number"] == "Contract 2022103"
    assert {vote["member"] for vote in votes if vote["district"] == 4} == {"Lloyd Pareira, Jr."}
    # Every motion read has one row for each of the five.
    per_motion = pd.DataFrame(votes).groupby(["item_id", "motion"])["district"].agg(["size", "nunique"])
    assert len(per_motion) == 9 and (per_motion["size"] == 5).all() and (per_motion["nunique"] == 5).all()
    assert {vote["matter_id"] for vote in votes if vote["item_id"] == "20260210Board-5"} == {"350398"}
    assert {vote["motion_text"] for vote in votes if vote["item_id"] == "20260210Board-7"} == {"AUTHORIZED CONTRACT NO. 2022103 AS RECOMMENDED"}


def test_a_department_voted_on_as_one_has_the_vote_on_its_own_line():
    rows, votes, _ = read()
    department = rows["20260210Board-d5"]
    assert (department["title"], department["heading"], department["motions"], department["how"], department["noes"]) == (
        "BOARD APPOINTMENTS", True, 1, "AYES: 1,2,3,4 NOES: 5", 1)
    # The vote under the department's name is not a second vote on the item above it.
    assert rows["20260210Board-7"]["motions"] == 1
    assert (rows["20260210Board-8"]["motions"], rows["20260210Board-8"]["voted_with"]) == (0, "20260210Board-d5")
    # The letters accepted and placed on file together are voted on as one too.
    assert (rows["20260210Board-information"]["action"], rows["20260210Board-information"]["ayes"]) == ("ACCEPTED AND PLACED ON FILE", 5)
    assert rows["20260210Board-9"]["voted_with"] == "20260210Board-information"


def test_a_hearing_takes_its_motions_in_turn_and_a_vote_under_no_item_is_a_line_of_its_own():
    rows, votes, _ = read()
    hearing = rows["20260210Board-u1"]
    assert (hearing["agenda_number"], hearing["matter_id"], hearing["section"], hearing["motions"], hearing["motions_read"]) == ("", "352003", "Scheduled Items", 2, 2)
    assert hearing["action"] == "MOTION #2 FOR ITEMS 4-7 APPROVED AS RECOMMENDED" and hearing["number"] == "Resolution 2026-10; Ordinance 2056"
    log = json.loads(hearing["motion_log"])
    assert [(one["action"], one["how"]) for one in log] == [("MOTION #1 FOR ITEM 3 APPROVED AS RECOMMENDED", "AYES: ALL"),
                                                           ("MOTION #2 FOR ITEMS 4-7 APPROVED AS RECOMMENDED", "AYES: 2,3,4,5 ABSTENTIONS: 1")]
    second = {vote["district"]: (vote["vote"], vote["established"]) for vote in votes if vote["item_id"] == "20260210Board-u1" and vote["motion"] == 2}
    assert second[1] == ("ABSTAIN", "numbers") and second[2] == ("AYE", "numbers")
    assert (hearing["ayes"], hearing["not_voting"], hearing["established"]) == (4, 1, "")  # of the last motion; the two were known two ways
    # Pareira left before the vote taken during the Board's reports: ALL does not say who voted, so nobody's vote is written.
    loose = rows["20260210Board-u2"]
    assert (loose["title"], loose["section"], loose["source"], loose["votes_read"]) == ("APPROVED AS RECOMMENDED", "Reports/Board Direction", "minutes", False)
    assert loose["problem"] == "ALL, and the minutes have Lloyd Pareira, Jr. not present" and loose["ayes"] == 0
    assert not [vote for vote in votes if vote["item_id"] == "20260210Board-u2"]
    assert rows["20260210Board-reports"]["motions"] == 0  # the heading itself is not voted on


def test_a_count_with_no_districts_and_a_vote_the_board_order_has_otherwise_are_not_read():
    text = MINUTES.replace("SUPERVISOR MCDANIEL AND CHAIRMAN SILVEIRA PROVIDED COMMENTS\n",
                           "MOTION TO CONTINUE ITEM FOR ONE MONTH MADE BY BOARD CHAIR ESPINOSA\nSECONDED BY SUPERVISOR MCDANIEL, FAILED AFTER ROLL CALL VOTE 2-3\n")
    rows, votes, facts = read(text)
    item = rows["20260210Board-5"]
    assert (item["motions"], item["motions_read"], item["votes_read"], item["problem"]) == (2, 1, False, "a count, and no word of who voted how")
    assert [one["read"] for one in json.loads(item["motion_log"])] == [False, True] and item["noes"] == 2
    assert {vote["motion"] for vote in votes if vote["item_id"] == "20260210Board-5"} == {2}
    # A Board Order appended to the minutes names the ayes and noes of an item; where it has them otherwise, nothing is read.
    order = "ACTION ITEM NO. 5\n2026-02-10 PUBLIC WORKS\nUpon motion of Supervisor Silveira, seconded by Supervisor Pedrozo, the Board introduces the ordinance.\n{}\n4\n"
    same = MINUTES[:-2] + order.format("Ayes: Pedrozo, McDaniel, Pareira\nNoes: Pacheco, Silveira")
    assert read(same)[0]["20260210Board-5"]["votes_read"] is True
    other = MINUTES[:-2] + order.format("Ayes: Pacheco, Pedrozo, McDaniel, Pareira\nNoes: Silveira")
    rows, votes, _ = read(other)
    assert rows["20260210Board-5"]["problem"] == "the Board Order appended to the minutes has the vote otherwise"
    assert not [vote for vote in votes if vote["item_id"] == "20260210Board-5"]


def test_an_agenda_with_no_minutes_read_has_its_lines_and_nothing_done():
    rows, votes, facts = merced.read_meeting(MEETING, agenda())
    assert votes == [] and facts == {"motions": 0, "motions_read": 0}
    rows = {row["item_id"]: row for row in rows}
    assert len(rows) == 21 and "20260210Board-u2" not in rows
    item = rows["20260210Board-5"]
    assert (item["action"], item["motions"], item["votes_read"], item["voted_with"], item["source"], item["result"]) == ("", 0, None, "", "agenda", "")
    assert rows["20260210Board-1"]["voted_with"] == ""  # a consent calendar is not taken as adopted without minutes that say so


def test_the_five_tables_come_out_in_the_one_shape(tmp_path):
    agenda_rows, vote_rows, facts = merced.read_meeting(MEETING, agenda(), scanned(), ROLL, MINUTES_URL)
    later = {**MEETING, "meeting_id": "20260303Board", "date": "2026-03-03"}
    more_rows, more_votes, more_facts = merced.read_meeting(later, agenda(), scanned(), ROLL, MINUTES_URL)
    table, votes = merced.typed(pd.DataFrame(agenda_rows + more_rows, columns=merced.AGENDA_COLUMNS),
                                pd.DataFrame(vote_rows + more_votes, columns=merced.VOTE_COLUMNS))
    meetings = merced.meetings_table([{**MEETING, "agenda": MEETING["agenda_url"], "kind": "html"},
                                      {**later, "agenda": MEETING["agenda_url"], "kind": "html"}])
    for name in facts:
        meetings[name] = [facts[name], more_facts[name]]
    tables = council_tables.standard({"items": merced.items_table(table, meetings), "meetings": meetings, "agenda_items": table, "votes": votes,
                                      "members": merced.members_table(votes, meetings, asof="2026-04-01")})
    for name in council_tables.TABLES:
        assert list(tables[name].columns)[:len(council_tables.COLUMNS[name])] == council_tables.COLUMNS[name]
    items = tables["items"][tables["items"]["meeting_id"] == "20260210Board"].set_index("item_id")
    assert len(items) == 11 and "20260210Board-consent" not in items.index  # a heading is not an item
    assert (items.loc["20260210Board-1", "action_on"], items.loc["20260210Board-1", "ayes"], items.loc["20260210Board-1", "matter_id"]) == ("section", 5, "350383")
    assert (items.loc["20260210Board-5", "action_on"], items.loc["20260210Board-5", "noes"], items.loc["20260210Board-5", "subject"]) == ("item", 2, "PUBLIC WORKS")
    assert (items.loc["20260210Board-8", "action_on"], items.loc["20260210Board-8", "noes"], items.loc["20260210Board-8", "last_action"]) == ("section", 1, "APPROVED AS RECOMMENDED")
    assert items.loc["20260210Board-2", "action_on"] == "" and pd.isna(items.loc["20260210Board-2", "votes_read"])
    assert items.loc["20260210Board-u2", "votes_read"] == False and items.loc["20260210Board-u2", "matter_id"] == "20260210Board-u2"  # noqa: E712
    assert items.loc["20260210Board-4", "url"] == MINUTES_URL and (items["passed_date"] == "").all()
    members = tables["members"].set_index("name")
    assert list(members.index) == [member["name"] for member in ROLL] and list(members["district"]) == [1, 2, 3, 4, 5]
    assert members["serving"].all() and (members["votes"] == 18).all() and members.loc["Daron McDaniel", "role"] == "Chair"
    assert (members["first_vote"] == "2026-02-10").all() and (members["last_vote"] == "2026-03-03").all()
    # Voting on one day only does not make a member, and a last vote long ago is not serving.
    assert len(merced.members_table(votes[votes["date"] == "2026-02-10"], meetings)) == 0
    assert not merced.members_table(votes, meetings, asof="2026-09-01")["serving"].any()
    assert set(tables["votes"]["established"]) == {"all", "numbers"} and set(tables["votes"]["vote"]) == {"AYE", "NO", "NOT PRESENT", "ABSTAIN"}
    council_tables.write_tables(tables, tmp_path)
    assert sorted(path.name for path in tmp_path.glob("*.parquet")) == sorted(f"{name}.parquet" for name in council_tables.TABLES)
    card = merced.card(tables)
    assert not re.search(r"\{[a-z_]+\}", card) and "chrissoria/merced-county-board" in card


def test_what_is_kept_is_not_asked_for_again(tmp_path, monkeypatch):
    class Answer:
        status_code, headers = 200, {"content-type": "text/html"}

        def __init__(self, content):
            self.content, self.text = content, content.decode("cp1252")

        def raise_for_status(self):
            pass

    asked = []
    monkeypatch.setattr(merced, "PAUSE", 0)
    monkeypatch.setattr(merced, "_refused", merced.threading.Event())
    monkeypatch.setattr(merced._session, "get", lambda url, **said: asked.append(url) or Answer(AGENDA.encode("cp1252")))
    first = merced.agenda_of(MEETING, tmp_path)
    again = merced.agenda_of(MEETING, tmp_path)
    assert asked == [MEETING["agenda_url"]] and [tuple(one) for one in first] == again
    assert merced.agenda_lines(again) == agenda()
    assert (tmp_path / "text" / "agendas" / "20260210Board.txt").exists()
    # The newer pages are UTF-8 with a mark at their head; the agendas are in Windows' letters.
    assert merced.decoded(b"\xef\xbb\xbf<p>caf\xc3\xa9</p>") == "<p>café</p>" and merced.decoded("“M” Street".encode("cp1252")) == "“M” Street"


def test_a_refusal_stops_the_host_being_asked_again(monkeypatch):
    class Answer:
        status_code, headers, content, text = 403, {"content-type": "text/html"}, b"<html>", "<html>"

    asked = []
    monkeypatch.setattr(merced, "PAUSE", 0)
    monkeypatch.setattr(merced, "_refused", merced.threading.Event())
    monkeypatch.setattr(merced._session, "get", lambda url, **said: asked.append(url) or Answer())
    with pytest.raises(merced.Refused):
        merced.fetch("https://example.test/a")
    with pytest.raises(merced.Refused):
        merced.fetch("https://example.test/b")
    assert asked == ["https://example.test/a"]

    class Blocked:
        status_code, headers, content = 200, {"content-type": "text/html; charset=UTF-8"}, b"<title>Attention Required!</title> Sorry, you have been blocked"
        text = content.decode()

    monkeypatch.setattr(merced, "_refused", merced.threading.Event())
    monkeypatch.setattr(merced._session, "get", lambda url, **said: Blocked())
    with pytest.raises(merced.Refused):
        merced.fetch("https://example.test/c")
