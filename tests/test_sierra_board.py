"""build_sierra_board sets what the Sierra County Board's minutes say was done on the lines of its agendas, by number,
and works each supervisor's vote out of a roll, a count and the names of those who did not vote aye: a motion whole
or not at all."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import build_sierra_board as sierra
import council_tables

MEETING = {"meeting_id": "815", "date": "2024-05-07"}
ROLL = [{"name": "Lee Adams", "district": 1, "role": "Vice-Chair", "present": True},
        {"name": "Lila Heuer", "district": 2, "role": "", "present": True},
        {"name": "Terry LeBlanc", "district": 4, "role": "", "present": True},
        {"name": "Sharon Dryden", "district": 5, "role": "", "present": True},
        {"name": "Paul Roen", "district": 3, "role": "Chair", "present": False}]
FIVE = [{**member, "present": True} for member in ROLL]

# Rows of the listing as the site has them: a meeting with its minutes, the County Service Areas' board, a meeting cancelled.
LISTING = """<table><tbody>
<tr id="row815a1" class="catAgendaRow"><td><h3 class="noMargin" id="h405072024-815">
 <strong aria-label="Agenda for May 7, 2024"><abbr title="May">May</abbr> 7, 2024</strong></h3>
 <p><a id="05072024-815" name="815" href="/AgendaCenter/ViewFile/Agenda/_05072024-815?html=true" target="_blank" aria-describedby="h405072024-815">
 Meeting Agenda and Background
 </a></p></td>
 <td class="minutes"><a href="/AgendaCenter/ViewFile/Minutes/_05072024-815" aria-label="May 7, 2024. Minutes" target="_blank"><img alt="Minutes"></a></td>
 <td class="media"><a href="/CivicMedia?VID=377" aria-label="Media"><img alt="Videos"></a></td>
 <td class="downloads"><ol><li><a class="html" href="/AgendaCenter/ViewFile/Agenda/_05072024-815?html=true">HTML</a></li>
 <li><a class="pdf" href="/AgendaCenter/ViewFile/Agenda/_05072024-815">PDF</a></li>
 <li><a class="pdf" href="/AgendaCenter/ViewFile/Agenda/_05072024-815?packet=true">Packet</a></li></ol></td></tr>
<tr id="row4471b191638" class="catAgendaRow"><td><h3 class="noMargin" id="h411152018-447">
 <strong aria-label="Agenda for November 15, 2018"><abbr title="November">Nov</abbr> 15, 2018</strong></h3>
 <p><a id="11152018-447" name="447" href="/AgendaCenter/ViewFile/Agenda/_11152018-447?html=true" target="_blank" aria-describedby="h411152018-447">
 Special CSA Board of Directors Meeting Agenda &amp; Backup
 </a></p></td>
 <td class="minutes"><a href="/AgendaCenter/ViewFile/Minutes/_11152018-447" target="_blank"><img alt="Minutes"></a></td></tr>
<tr id="row840c2" class="catAgendaRow"><td><h3 class="noMargin" id="h409032024-840">
 <strong aria-label="Agenda for September 3, 2024"><abbr title="September">Sep</abbr> 3, 2024</strong></h3>
 <p><a id="09032024-840" name="840" href="/AgendaCenter/ViewFile/Agenda/_09032024-840" target="_blank" aria-describedby="h409032024-840">
 Canceled - Meeting Agenda and Background
 </a></p></td>
 <td class="minutes"></td></tr>
</tbody></table>"""

# An agenda as the site serves it, cut down to a few lines of each kind.
AGENDA = """<div id="divHeader"><strong>STATE OF CALIFORNIA, COUNTY OF SIERRA</strong><br>
The Sierra County Board of Supervisors will meet in regular session commencing at 9:00 a.m. on May 7, 2024, in the Board
of Supervisors' Chambers, Courthouse, Downieville, CA. This meeting will be recorded for posting.</div>
<div class="item level1"><div class="bullet"><span>1.</span></div><div class="content">
 <span class="time">9:00<span>A.M.</span></span>
 <h1 class="title">STANDING ORDERS</h1><div class="desc"><ul><li>Call to Order</li><li>Pledge of Allegiance</li><li>Roll Call</li></ul></div>
 <div class="documents"></div></div></div>
<div class="item level1"><div class="bullet"><span>2.</span></div><div class="content">
 <h1 class="title">PUBLIC COMMENT OPPORTUNITY</h1><div class="desc"><br></div><div class="documents"></div></div></div>
<div class="item level1"><div class="bullet"><span>6.</span></div><div class="content">
 <h1 class="title">PUBLIC HEALTH - Rhonda Grandi</h1><div class="desc"><br></div><div class="documents"></div></div></div>
<div class="item level2"><div class="bullet"><span>6.A.</span></div><div class="content">
 <h2 class="title">Resolution authorizing Public Health to hire an Extra-Help Senior Public Health Nurse to meet certain program regulations and allowing this position to have remote work flexibility at the Director&#39;s discretion.</h2>
 <div class="desc"><br></div><div class="documents"><a href="/AgendaCenter/ViewFile/Item/12590?fileID=14301">PHN.pdf</a></div></div></div>
<div class="item level1"><div class="bullet"><span>10.</span></div><div class="content">
 <h1 class="title">BOARD OF SUPERVISORS</h1><div class="desc"><br></div><div class="documents"></div></div></div>
<div class="item level2"><div class="bullet"><span>10.A.</span></div><div class="content">
 <h2 class="title">Discussion/approval of amendment to Agreement 2023-124 between the County of Sierra and the Sierra County Chamber of Commerce. (CLERK OF THE BOARD)</h2>
 <div class="desc"><br></div><div class="documents"></div></div></div>
<div class="item level2"><div class="bullet"><span>10.B.</span></div><div class="content">
 <h2 class="title">Approval of letter of support of Plumas-Sierra Telecommunication&#39;s (PST) grant application. (CHAIR ROEN)</h2>
 <div class="desc"><br></div><div class="documents"></div></div></div>
<div class="item level1"><div class="bullet"><span>13.</span></div><div class="content">
 <h1 class="title">CLOSED SESSION</h1><div class="desc"><br></div><div class="documents"></div></div></div>
<div class="item level2"><div class="bullet"><span>13.A.</span></div><div class="content">
 <h2 class="title">Conference with labor negotiators pursuant to Government Code section 54957.6.</h2>
 <div class="desc"><br></div><div class="documents"></div></div></div>
<div class="item level1"><div class="bullet"><span>14.</span></div><div class="content">
 <h1 class="title">TIMED ITEMS</h1><div class="desc"><br></div><div class="documents"></div></div></div>
<div class="item level2"><div class="bullet"><span>14.A.</span></div><div class="content">
 <span class="time">10:00<span>AM</span></span>
 <h2 class="title">RESOLUTION OF APPRECIATION</h2>
 <div class="desc"><p><span>Resolution of appreciation to Joyce White for 39 years of continuing service to the Downieville Volunteer Fire Department.</span></p></div>
 <div class="documents"></div></div></div>
<div class="item level1"><div class="bullet"><span>15.</span></div><div class="content">
 <h1 class="title">CONSENT AGENDA</h1><div class="desc"><span>Items placed on the Consent Agenda are of a routine and non-controversial nature.</span><br></div>
 <div class="documents"></div></div></div>
<div class="item level2"><div class="bullet"><span>15.A.</span></div><div class="content">
 <h2 class="title">Resolution authorizing the Auditor to make certain changes to the 2023/2024 Final Budget for Public Health in the amount of $1,102,958. (4/5th affirmative vote required) (PUBLIC HEALTH)</h2>
 <div class="desc"><br></div><div class="documents"></div></div></div>
<div class="item level2"><div class="bullet"><span>15.G.</span></div><div class="content">
 <h2 class="title">California Mental Health Services Authority (CalMHSA) Participation Agreement. (BEHAVIORAL HEALTH)</h2>
 <div class="desc"><br></div><div class="documents"></div></div></div>
<div class="item level2"><div class="bullet"><span>15.O.</span></div><div class="content">
 <h2 class="title">Resolution declaring county owned trailer as surplus and transferring the trailer to the Director of Transportation to evaluate the trailer for appropriate transfer, sale, or disposal. (SHERIFF)</h2>
 <div class="desc"><br></div><div class="documents"></div></div></div>
<div class="item level2"><div class="bullet"><span>15.S.</span></div><div class="content">
 <h2 class="title">Minutes from the regular meeting held on March 19, 2024. (CLERK OF THE BOARD)</h2>
 <div class="desc"><br></div><div class="documents"></div></div></div>
"""

# Minutes as the reader keeps them (those of 7 May 2024, cut down): a line is set in by a space for every six points
# it stands in from the margin, and a form feed parts two pages.
MINUTES = """                          STATE OF CALIFORNIA, COUNTY OF SIERRA
                                 BOARD OF SUPERVISORS
                                   MINUTES
                              REGULAR MEETING
                          Lee Adams, Vice-Chair, District 1
      The Sierra County Board of Supervisors met in regular session commencing at
9:00 a.m. on May 7, 2024, in the Board of Supervisors' Chambers, Courthouse,
Downieville, CA. This meeting was recorded for posting on the Board of Supervisors'
website at www.sierracounty.ca.gov.
PLEDGE OF ALLEGIANCE: Led by Supervisor Heuer
ROLL CALL
      Present: Lee Adams, Supervisor, Vice Chair, District #1
                  Lila Heuer, Supervisor, District #2
                  Terry LeBlanc, Supervisor, District #4
                  Sharon Dryden, Supervisor, District #5
      Absent: Paul Roen, Supervisor, Chair, District #3
      Staff: Heather Foster, County Clerk-Recorder
                  Rhetta Vander Ploeg, County Counsel
\fAPPROVAL OF THE CONSENT AGENDA
      At the request of the Clerk, Item 15.G. was pulled from the
Consent Agenda.
      15.G. California Mental Health Services Authority (CalMHSA) Participation
            Agreement in an amount not to exceed $30,000. (BEHAVIORAL HEALTH)
      At the request of Supervisor Adams, Item 15.O. was moved to the Regular Agenda
as Item 10.D.
      15.O. Resolution declaring county owned trailer as surplus and transferring the
            trailer to the Director of Transportation to evaluate the trailer for appropriate
            transfer, sale, or disposal. (SHERIFF)
      The Board moved to approve the Consent Agenda as amended.
APPROVED as amended. Motion: Heuer/LeBlanc/Unanimous Roll Call Vote: 4/0/1
(Supervisor Roen ABSENT)
15. CONSENT AGENDA
      15.A. Resolution authorizing the Auditor to make certain changes to the
            2023/2024 Final Budget for Public Health in the amount of $1,102,958.
            (4/5th affirmative vote required) (PUBLIC HEALTH)
ADOPTED, Resolution 2024-059
      15.S. Minutes from the regular meeting held on March 19, 2024. (CLERK OF THE
            BOARD)
APPROVAL OF THE REGULAR AGENDA
      The Board moved to approve the Regular Agenda as amended.
APPROVED as amended. Motion: Dryden/LeBlanc/Unanimous
Roll Call Vote: 4/0/1 (Supervisor Roen ABSENT)
REGULAR AGENDA
2. PUBLIC COMMENT OPPORTUNITY
      At 9:03 a.m. Vice-Chair Adam opened and closed the public comment opportunity
with no members of the public addressing the Board.
6. PUBLIC HEALTH - RHONDA GRANDI
      6.A. Resolution authorizing Public Health to hire an Extra-Help Senior Public
            Health Nurse to meet certain program regulations and allowing this position
            to have remote work flexibility at the Director’s discretion.
      The Assistant Director of Social Services provided background on the proposed
resolution to hire an Extra-Help Senior Public Health Nurse.
      The Board moved to adopt the resolution authorizing Public Health to hire an Extra-
Help Senior Public Health Nurse to meet certain program regulations.
\fADOPTED, Resolution 2024-070. Motion: Dryden/LeBlanc/Unanimous Roll Call Vote:
4/0/1 (Supervisor Roen ABSENT)
10. BOARD OF SUPERVISORS
      10.A. Discussion/approval of amendment to Agreement 2023-124 between the
            County of Sierra and the Sierra County Chamber of Commerce. (CLERK OF
            THE BOARD)
      The Board moved to approve the amendment to Agreement 2023-124 between
the County of Sierra and the Sierra County Chamber of Commerce.
      Brief discussion ensued with the Board.
FAILED. Motion: Heuer/Adams/Failed Roll Call Vote: 2/2/1 (Supervisors LeBlanc and
Dryden NO and Supervisor Roen ABSENT)
      10.B. Approval of letter of support of Plumas-Sierra Telecommunication's (PST)
            grant application. (CHAIR ROEN)
APPROVED. Motion: Dryden/Heuer/Unanimous Roll Call Vote: 5/0
      10.D. Resolution declaring county owned trailer as surplus and transferring the
            trailer to the Director of Transportation to evaluate the trailer for appropriate
            transfer, sale, or disposal. (SHERIFF) (Consent Item 15.O.)
      Following discussion, the Board moved to adopt the resolution declaring county
owned trailer as surplus as amended.
ADOPTED as amended, Resolution 2024-073. Motion: Dryden/Heuer/Unanimous Roll
Call Vote: 4/0/1 (Supervisor Roen ABSENT)
13. CLOSED SESSION
      13.A. Conference with labor negotiators pursuant to Government Code section
            54957.6.
CLOSED SESSION STATEMENT
      The Board met in closed session from 11:17 a.m. to 12:42 p.m.
                                    LEE ADAMS, VICE-CHAIR
                                    BOARD OF SUPERVISORS
ATTEST:
HEATHER FOSTER
CLERK OF THE BOARD
"""


def motion_of(line):
    """The one motion on a line of the minutes, as the reader has it."""
    return sierra.motions_in([(0, row) for row in line.split("\n")])[0]


def cast_of(line, roll=ROLL, why=""):
    cast, problem = sierra.decide(motion_of(line), roll, why)
    return (None if cast is None else {member: (word, way) for member, word, way in cast}), problem


def read(text=MINUTES, agenda=AGENDA):
    lines = sierra.agenda_of(agenda) if agenda else None
    rows, votes, facts = sierra.read_meeting(MEETING, lines, sierra.scan(text) if text else None, {}, pages=2)
    return {row["item_id"]: row for row in rows}, votes, facts


def test_the_listing_gives_each_meeting_its_number_and_documents_and_leaves_out_what_is_not_the_boards():
    meetings = sierra.meetings_table(sierra.rows_of(LISTING)).set_index("meeting_id")
    assert list(meetings.index) == ["815", "840"]  # the County Service Areas' board is not the Board of Supervisors
    held, off = meetings.loc["815"], meetings.loc["840"]
    assert (held["date"], held["kind"], held["cancelled"], held["name"]) == ("2024-05-07", "regular", False, "Meeting Agenda and Background")
    assert held["agenda_url"] == "https://www.sierracounty.ca.gov/AgendaCenter/ViewFile/Agenda/_05072024-815?html=true"
    assert held["minutes_url"] == "https://www.sierracounty.ca.gov/AgendaCenter/ViewFile/Minutes/_05072024-815"
    assert held["packet_url"].endswith("_05072024-815?packet=true") and held["video_url"].endswith("/CivicMedia?VID=377")
    # A cancelled meeting is a row with nothing on it; its agenda is the PDF, which is not read.
    assert (off["date"], off["cancelled"], off["minutes_url"]) == ("2024-09-03", True, "")
    assert off["agenda_url"].endswith("_09032024-840")
    assert "CIDs=5," in sierra.year_url(2019) and "startDate=01/01/2019&endDate=12/31/2019" in sierra.year_url(2019)
    assert list(meetings.reset_index().columns)[:len(council_tables.COLUMNS["meetings"])] == council_tables.COLUMNS["meetings"]


def test_an_agenda_is_its_lines_with_their_numbers_ranks_titles_and_hours():
    agenda = sierra.agenda_of(AGENDA)
    assert (agenda["time"], agenda["location"]) == ("9:00 AM", "Board of Supervisors' Chambers, Courthouse, Downieville, CA")
    lines = {line["number"]: line for line in agenda["lines"]}
    assert [line["number"] for line in agenda["lines"]][:4] == ["1.", "2.", "6.", "6.A."]
    assert (lines["1."]["level"], lines["1."]["title"], lines["1."]["time"]) == (1, "STANDING ORDERS", "9:00 AM")
    assert lines["1."]["description"] == "Call to Order; Pledge of Allegiance; Roll Call"
    assert lines["6.A."]["level"] == 2 and lines["6.A."]["title"].endswith("at the Director's discretion.")
    assert (lines["14.A."]["time"], lines["14.A."]["title"]) == ("10:00 AM", "RESOLUTION OF APPRECIATION")
    assert lines["14.A."]["description"].startswith("Resolution of appreciation to Joyce White")


def test_the_hour_the_place_and_the_day_are_read_from_the_sentence_at_the_head():
    assert sierra.held_at("The Sierra County Board of Supervisors met in regular session commencing at 9:00 a.m. on June 17, 2025, "
                          "at 105 Beckwith Street, Social Hall, Loyalton, CA. This meeting was recorded") == (
        "9:00 AM", "105 Beckwith Street, Social Hall, Loyalton, CA", "2025-06-17")
    # A teleconference names no one place.
    assert sierra.held_at("met in a special teleconference meeting held at 9:00 a.m. on Tuesday, September 24, 2013. Locations "
                          "available to the public were in the Chambers") == ("9:00 AM", "", "2013-09-24")
    assert sierra.held_at("met in regular session commencing at 9:00 a.m. on April 20, 2021.This meeting was recorded") == ("9:00 AM", "", "2021-04-20")
    assert sierra.clock("10:00AM") == "10:00 AM" and sierra.clock("1:30 p.m.") == "1:30 PM"


def test_the_roll_is_the_lines_with_a_district_under_present_and_under_absent():
    roll, end, why = sierra.roll_of(sierra.lines_of(MINUTES))
    assert why == "" and roll == ROLL
    assert sierra.lines_of(MINUTES)[end][1] == "APPROVAL OF THE CONSENT AGENDA"
    # An office before a name is not part of the name; the roll called twice is the later one.
    again = sierra.lines_of("ROLL CALL – Site Visit\n  Present: Lee Adams, Supervisor, District #1\nROLL CALL\n"
                            "  Present: Chair Adams, Supervisor, Chair, District #1\n     Supervisor Roen, District #3\n"
                            "     Terry LeBlanc, Supervisor, District #4\n  Absent: Lila Heuer, Supervisor, Vice-Chair, District #2\n"
                            "  Staff: Heather Foster, County Clerk\nAPPROVAL OF THE REGULAR AGENDA")
    roll, _, why = sierra.roll_of(again)
    assert why == "" and [(member["name"], member["district"], member["role"], member["present"]) for member in roll] == [
        ("Adams", 1, "Chair", True), ("Roen", 3, "", True), ("Terry LeBlanc", 4, "", True), ("Lila Heuer", 2, "Vice-Chair", False)]
    assert sierra.roll_of(sierra.lines_of("APPROVAL OF CONSENT AGENDA\n13. CONSENT AGENDA"))[2] == "no roll at the head of the minutes"
    assert sierra.roll_of(sierra.lines_of("ROLL CALL\n Present: Lee Adams, Supervisor, District #1\n Paul Roen, Supervisor, District #1\n"
                                          " Jim Beard, Supervisor, District #4"))[2] == "the roll has a district or a surname twice"


def test_a_label_of_the_roll_set_apart_from_its_name_is_put_back_on_that_names_line():
    # The roll of 17 June 2025 as the PDF places it: "Absent:" a little above its name, "Staff:" a little below its first.
    page = [{"text": "Present: Lee Adams, Supervisor, Chair, District #1", "x0": 144.0, "x1": 480.0, "top": 538.0},
            {"text": "Terry LeBlanc, Supervisor, District #4", "x0": 216.0, "x1": 420.0, "top": 579.4},
            {"text": "Absent:", "x0": 147.5, "x1": 188.0, "top": 613.0},
            {"text": "Sharon Dryden, Supervisor, District #5", "x0": 216.0, "x1": 425.0, "top": 616.3},
            {"text": "Heather Foster, County Clerk-Recorder", "x0": 216.0, "x1": 420.0, "top": 639.3},
            {"text": "Staff:", "x0": 145.3, "x1": 176.0, "top": 644.8},
            {"text": "Rhetta Vander Ploeg, County Counsel", "x0": 216.0, "x1": 420.0, "top": 653.1}]
    assert [line["text"] for line in sierra.labelled(page)] == [
        "Present: Lee Adams, Supervisor, Chair, District #1", "Terry LeBlanc, Supervisor, District #4",
        "Absent: Sharon Dryden, Supervisor, District #5", "Staff: Heather Foster, County Clerk-Recorder",
        "Rhetta Vander Ploeg, County Counsel"]
    # A label with no name beside it (nobody absent) stays where it is.
    alone = [{"text": "Absent:", "x0": 147.5, "x1": 188.0, "top": 600.0}, {"text": "Staff: Heather Foster", "x0": 145.0, "x1": 300.0, "top": 613.8}]
    assert [line["text"] for line in sierra.labelled(alone)] == ["Absent:", "Staff: Heather Foster"]


def test_a_motions_line_is_read_into_what_was_done_the_movers_the_count_and_those_named():
    motion = motion_of("FAILED. Motion: Heuer/Adams/Failed Roll Call Vote: 2/2/1 (Supervisors LeBlanc and\nDryden NO and Supervisor Roen ABSENT)")
    assert (motion["action"], motion["mover"], motion["seconder"], motion["outcome"], motion["count"]) == ("FAILED", "Heuer", "Adams", "Failed", (2, 2, 1))
    assert motion["notes"] == [(["LeBlanc", "Dryden"], "NO"), (["Roen"], "ABSENT")]
    assert motion["how"] == "Motion: Heuer/Adams/Failed Roll Call Vote: 2/2/1 (Supervisors LeBlanc and Dryden NO and Supervisor Roen ABSENT)"
    # What was done may run over two lines, and the count may stand on the line after.
    motion = motion_of("ADOPTED, Resolution 2021-059 and APPROVED, Agreement 2021-037. Motion:\nRoen/Huebner/Unanimous Roll Call Vote: 5/0")
    assert (motion["action"], motion["count"]) == ("ADOPTED, Resolution 2021-059 and APPROVED, Agreement 2021-037", (5, 0))
    assert sierra.numbers_in(motion["action"]) == "Resolution 2021-059; Agreement 2021-037"
    assert sierra.numbers_in("ADOPTED, CSA Resolution 2020-008") == "CSA Resolution 2020-008"
    assert sierra.numbers_in("ADOPTED as amended, Ordinance No. 1061") == "Ordinance 1061"
    # The forms the minutes vary it with.
    assert motion_of("APPROVED, Agreement 2015-086. Adams/Roen/Unanimous Roll Call Vote: 5/0")["count"] == (5, 0)  # no "Motion:"
    assert motion_of("ADOPTED as amended, Resolution 2019-102. Motion. Adams/Huebner/Unanimous\nRoll Call Vote: 5/0")["count"] == (5, 0)
    assert motion_of("APPROVED. Motion: Roll Call Vote: Roen/Adams/Unanimous Roll Call Vote: 4/0/1\n(Supervisor Beard ABSENT)")["mover"] == "Roen"
    assert motion_of("APPROVED. Motion: Roen//LeBlanc/Unanimous Roll Call Vote: 5/0")["seconder"] == "LeBlanc"
    assert motion_of("ADOPTED, Resolution 2014-093. Motion: Adams/Huebner/U‐nanimous Roll Call Vote:\n5/0")["outcome"] == "Unanimous"
    tie = motion_of("NO ACTION. Motion: Roen/Adams/TIE Roll Call Vote: 2/2/1 (Supervisors Huebner\nand Beard NO, Supervisor Schlefstein ABSENT)")
    assert (tie["action"], tie["outcome"], tie["notes"]) == ("NO ACTION", "TIE", [(["Huebner", "Beard"], "NO"), (["Schlefstein"], "ABSENT")])
    assert motion_of("APPROVED. Motion: Adams/Roen/Majority Roll Call Vote: 4/1 (Chairman Schlefstein)")["notes"] is None
    # The movers printed twice are one motion, and a sentence that ends "the motion." is none.
    assert len(sierra.motions_in([(0, "APPROVED. Motion: Adams/Roen/Unanimous Motion: Adams/Roen/Unanimous"), (0, "Roll Call Vote: 4/0/1 (Supervisor Huebner ABSENT)")])) == 1
    assert sierra.motions_in([(6, "Supervisor Adams withdrew the motion."), (0, "The Board took no action.")]) == []
    # The Board's motion in words is the nearest paragraph above that says the Board moved.
    said = sierra.motions_in([(6, "The Board moved to approve the amendment to Agreement 2023-124 between"), (0, "the County and the Chamber."),
                              (6, "Brief discussion ensued with the Board."), (0, "FAILED. Motion: Heuer/Adams/Failed Roll Call Vote: 2/2/1")])[0]["said"]
    assert said == "The Board moved to approve the amendment to Agreement 2023-124 between the County and the Chamber."


def test_the_ayes_are_the_roll_less_those_named_and_must_come_to_the_count():
    cast, problem = cast_of("APPROVED. Motion: Dryden/Heuer/Unanimous Roll Call Vote: 5/0", FIVE)
    assert problem == "" and cast == {member["name"]: ("AYE", "count") for member in FIVE}
    cast, problem = cast_of("APPROVED. Motion: Heuer/Roen/Majority Roll Call Vote: 4/1 (Supervisor LeBlanc NO)", FIVE)
    assert problem == "" and cast["Terry LeBlanc"] == ("NO", "named")
    assert sorted(member for member, (word, way) in cast.items() if (word, way) == ("AYE", "count")) == ["Lee Adams", "Lila Heuer", "Paul Roen", "Sharon Dryden"]
    # Absent at the head and named on the line.
    cast, problem = cast_of("FAILED. Motion: Heuer/Adams/Failed Roll Call Vote: 2/2/1 (Supervisors LeBlanc and Dryden NO and Supervisor Roen ABSENT)")
    assert problem == "" and cast == {"Terry LeBlanc": ("NO", "named"), "Sharon Dryden": ("NO", "named"), "Paul Roen": ("ABSENT", "named"),
                                      "Lee Adams": ("AYE", "count"), "Lila Heuer": ("AYE", "count")}
    # Absent at the head and not named: ABSENT by the count's third number if it has them, no row if the count leaves them out.
    assert cast_of("APPROVED. Motion: Dryden/Heuer/Unanimous Roll Call Vote: 4/0/1")[0]["Paul Roen"] == ("ABSENT", "count")
    cast, problem = cast_of("APPROVED. Motion: Dryden/Heuer/Unanimous Roll Call Vote: 4/0")
    assert problem == "" and "Paul Roen" not in cast and len(cast) == 4
    # Present at the head, gone by this vote, and named.
    assert cast_of("APPROVED. Motion: Dryden/Adams/Unanimous Roll Call Vote: 3/0/2 (Supervisors Heuer and Roen ABSENT)")[0]["Lila Heuer"] == ("ABSENT", "named")
    assert cast_of("APPROVED. Motion: Dryden/Adams/Majority Roll Call Vote: 4/0/1 (Supervisor Heuer ABSTAINED)", FIVE)[0]["Lila Heuer"] == ("ABSTAIN", "named")


def test_a_motion_whose_count_names_or_roll_do_not_add_up_is_not_read():
    # The count says five voted aye on a day the roll has four present.
    assert cast_of("APPROVED. Motion: Dryden/Heuer/Unanimous Roll Call Vote: 5/0")[1] == "the count has 5 ayes and the roll and the names give 4"
    assert cast_of("APPROVED. Motion: Beard/Huebner/Unanimous Roll Call Vote: 4/0", [
        {"name": name, "district": at, "role": "", "present": True} for at, name in enumerate(["Lee Adams", "Peter W. Huebner", "Paul Roen", "Jim Beard", "Scott A. Schlefstein"], 1)])[1] == (
        "the count has 4 ayes and the roll and the names give 5")
    assert cast_of("APPROVED. Motion: Adams/Dryden/Majority Roll Call Vote: 3/1/1")[1] == "the count has 3 ayes and the roll and the names give 4"
    assert cast_of("APPROVED. Motion: Adams/Dryden/Majority Roll Call Vote: 3/2/0 (Supervisor Heuer NO)")[1] == "the count has 2 noes and 1 are named"
    assert cast_of("APPROVED. Motion: Adams/Dryden/Unanimous Roll Call Vote: 4/0/2")[1] == "the count has 2 not voting and the roll and the names give 1"
    assert cast_of("APPROVED. Motion: Roen/Huebner/Unanimous")[1] == "no count on the motion's line"
    assert cast_of("APPROVED. Motion: Dryden/Huebner/Unanimous Roll Call Vote: 4/0/1 (Supervisor Roen ABSENT)")[1] == "not on the roll: Huebner"
    assert cast_of("APPROVED. Motion: Dryden/Heuer/Unanimous Roll Call Vote: 3/0/2 (Supervisors Beard and Roen ABSENT)")[1] == "not on the roll: Beard"
    assert cast_of("APPROVED. Motion: Adams/Heuer/Unanimous Roll Call Vote: 4/0/1 (Chairman Roen)")[1] == "the bracket is not read: (Chairman Roen)"
    assert cast_of("APPROVED. Motion: Adams/Heuer/Unanimous Roll Call Vote: 3/1/1 (Supervisor Dryden NO and Supervisor Roen ABSENT)")[1] == (
        "unanimous, with a supervisor named as voting no")
    assert cast_of("APPROVED. Motion: 4/01 (Supervisor Roen ABSENT)")[1] == "the line after Motion: is not movers and a vote"
    assert cast_of("APPROVED. Motion: Dryden/Heuer/Unanimous Roll Call Vote: 4/0/1", why="no roll at the head of the minutes")[1] == "no roll at the head of the minutes"


def test_numbers_after_the_ayes_in_another_order_are_read_only_where_everyone_they_count_is_named(monkeypatch):
    # The minutes of 2015 put the absent second: four ayes, Roen named absent, nobody voting no.
    cast, problem = cast_of("APPROVED. Motion: Adams/Heuer/Unanimous Roll Call Vote: 4/1/0 (Supervisor Roen ABSENT)")
    assert problem == "" and cast["Paul Roen"] == ("ABSENT", "named") and sum(word == "AYE" for word, _ in cast.values()) == 4
    # An abstention counted where the noes go.
    cast, problem = cast_of("APPROVED. Motion: Adams/Dryden/Majority Roll Call Vote: 4/1 (Supervisor Heuer ABSTAINED)", FIVE)
    assert problem == "" and cast["Lila Heuer"] == ("ABSTAIN", "named")
    # Nobody named for the number: it is not read, in any order.
    assert cast_of("APPROVED. Motion: Adams/Dryden/Majority Roll Call Vote: 4/1", FIVE)[1] == "the count has 4 ayes and the roll and the names give 5"
    monkeypatch.setattr(sierra, "ANY_ORDER", False)
    assert cast_of("APPROVED. Motion: Adams/Heuer/Unanimous Roll Call Vote: 4/1/0 (Supervisor Roen ABSENT)")[1] == "the count has 1 noes and 0 are named"


def test_a_name_on_a_motions_line_is_the_one_supervisor_on_the_roll_it_can_be():
    assert sierra.who("LeBlanc", ROLL) == "Terry LeBlanc" and sierra.who("Supervisor Roen", ROLL) == "Paul Roen"
    assert sierra.who("Le Blanc", ROLL) == "Terry LeBlanc"
    assert sierra.who("Lee", ROLL) == "Lee Adams"  # a first name, where one supervisor has it
    assert sierra.who("Adam", ROLL) == "Lee Adams" and sierra.who("LeBlance", ROLL) == "Terry LeBlanc"  # misprints the minutes make
    assert sierra.who("Beard", ROLL) is None and sierra.who("Passed", ROLL) is None
    assert sierra.names_in("Supervisors LeBlanc and Dryden") == ["LeBlanc", "Dryden"]
    assert sierra.names_in("Chair Beard and Supervisor Schlefstein") == ["Beard", "Schlefstein"]
    assert sierra.names_in("Supervisor, Huebner") == ["Huebner"]
    assert sierra.names_in("Item 12.E. Roll Call Vote: 4/1 Supervisor Adams") is None
    # One spelling throughout: the commonest full name, and for a surname alone or a name run together the one it can be.
    spelling = sierra.spelling_of([[{"name": "Peter W. Huebner"}, {"name": "Lee Adams"}], [{"name": "Peter W. Huebner"}, {"name": "LeeAdams"}],
                                   [{"name": "Peter Huebner"}, {"name": "Adams"}]])
    assert spelling == {"Peter W. Huebner": "Peter W. Huebner", "Peter Huebner": "Peter W. Huebner", "Lee Adams": "Lee Adams",
                        "LeeAdams": "Lee Adams", "Adams": "Lee Adams"}


def test_a_line_opens_an_item_only_where_its_number_is_followed_by_a_title():
    opens = lambda words: bool(sierra._ITEM.match(words) and sierra.begins(sierra._ITEM.match(words)))
    assert all(opens(words) for words in ("6.A. Resolution authorizing", "12.A.i. Minutes from", "6. PUBLIC HEALTH - RHONDA GRANDI",
                                          "13.A Appointment of", "6 .A. Resolution adopting", "7.C.. Letter from", "14.TIMED ITEMS",
                                          "6. 1:00 P.M. PUBLIC HEARING - 2021 REDISTRICTING", "14.A. 10:00 AM - RESOLUTION OF APPRECIATION"))
    # A sentence that runs on from the line above can open with a number too.
    assert not any(opens(words) for words in ("6.C. and 6.D.", "7. The Board directed staff", "2019. The Director reported", "5.5 miles of road"))
    assert [sierra.number_of(number) for number in ("13.A.", "13. A", "7.C..", "6 .A.", "11.B.iv.")] == ["13.A", "13.A", "7.C", "6.A", "11.B.iv"]
    assert sierra.order_of("13.A.ii") == (13, 1, 2) and sierra.order_of("9.AA") == (9, 27) and sierra.order_of("8.E.2") == (8, 5, 2)


def test_minutes_are_read_onto_the_agendas_lines_by_number():
    agenda, votes, facts = read()
    assert list(agenda) == ["815-1", "815-u1", "815-2", "815-6", "815-6A", "815-10", "815-10A", "815-10B", "815-10D", "815-13", "815-13A",
                            "815-14", "815-14A", "815-15", "815-15A", "815-15G", "815-15O", "815-15S"]
    assert [row["sequence"] for row in agenda.values()] == list(range(1, 19))
    item = agenda["815-6A"]
    assert (item["agenda_number"], item["level"], item["heading"], item["source"]) == ("6.A.", 2, False, "agenda and minutes")
    assert item["title"].endswith("at the Director's discretion.")  # the agenda's own title
    assert (item["action"], item["result"], item["outcome"], item["number"], item["doc_type"]) == (
        "ADOPTED, Resolution 2024-070", "Pass", "Unanimous", "Resolution 2024-070", "resolution")
    assert (item["mover"], item["seconder"], item["ayes"], item["noes"], item["not_voting"], item["votes_read"]) == (
        "Sharon Dryden", "Terry LeBlanc", 4, 0, 1, True)
    assert (item["section"], item["section_id"], item["voted_with"]) == ("PUBLIC HEALTH - Rhonda Grandi", "815-6", "815-6A")
    assert item["how"] == "Motion: Dryden/LeBlanc/Unanimous Roll Call Vote: 4/0/1 (Supervisor Roen ABSENT)"
    failed = agenda["815-10A"]
    assert (failed["action"], failed["result"], failed["outcome"], failed["ayes"], failed["noes"], failed["not_voting"]) == ("FAILED", "Fail", "Failed", 2, 2, 1)
    assert failed["subject"] == "CLERK OF THE BOARD"
    cast = {vote["member"]: (vote["vote"], vote["established"]) for vote in votes if vote["item_id"] == "815-10A"}
    assert cast == {"Terry LeBlanc": ("NO", "named"), "Sharon Dryden": ("NO", "named"), "Paul Roen": ("ABSENT", "named"),
                    "Lee Adams": ("AYE", "count"), "Lila Heuer": ("AYE", "count")}
    assert {vote["motion_text"] for vote in votes if vote["item_id"] == "815-10A"} == {
        "The Board moved to approve the amendment to Agreement 2023-124 between the County of Sierra and the Sierra County Chamber of Commerce."}
    # A count that says five on a day the roll has four present is not read, and writes no votes.
    slip = agenda["815-10B"]
    assert (slip["action"], slip["votes_read"], slip["problem"], slip["ayes"]) == ("APPROVED", False, "the count has 5 ayes and the roll and the names give 4", 0)
    assert not [vote for vote in votes if vote["item_id"] == "815-10B"]
    assert json.loads(slip["motion_log"])[0]["how"] == "Motion: Dryden/Heuer/Unanimous Roll Call Vote: 5/0"
    # Lines the Board did not vote on.
    assert agenda["815-13A"]["motions"] == 0 and agenda["815-13A"]["votes_read"] is None and agenda["815-13A"]["source"] == "agenda and minutes"
    assert (agenda["815-14A"]["source"], agenda["815-14A"]["time"]) == ("agenda", "10:00 AM")  # on the agenda, not in the minutes
    assert agenda["815-6"]["heading"] and agenda["815-6"]["matter_id"] == "" and agenda["815-6A"]["matter_id"] == "815-6A"
    assert (facts["minutes"], facts["agenda"], facts["motions"], facts["motions_read"], facts["session"], facts["time"]) == (
        "read", "read", 6, 5, "REGULAR MEETING", "9:00 AM")
    assert facts["location"] == "Board of Supervisors' Chambers, Courthouse, Downieville, CA"
    assert json.loads(facts["roll"]) == ROLL


def test_the_consent_agendas_one_vote_is_on_its_own_line_and_its_items_point_to_it():
    agenda, votes, _ = read()
    calendar = agenda["815-15"]
    assert (calendar["heading"], calendar["title"], calendar["action"], calendar["result"], calendar["motions"]) == (True, "CONSENT AGENDA", "APPROVED as amended", "Pass", 1)
    assert (calendar["mover"], calendar["seconder"], calendar["ayes"], calendar["not_voting"]) == ("Lila Heuer", "Terry LeBlanc", 4, 1)
    assert {vote["motion_text"] for vote in votes if vote["item_id"] == "815-15"} == {"The Board moved to approve the Consent Agenda as amended."}
    listed = agenda["815-15A"]
    assert (listed["voted_with"], listed["motions"], listed["action"], listed["number"]) == ("815-15", 0, "ADOPTED, Resolution 2024-059", "Resolution 2024-059")
    assert listed["votes_read"] is None and listed["subject"] == "PUBLIC HEALTH"
    assert agenda["815-15S"]["voted_with"] == "815-15" and agenda["815-15S"]["action"] == ""
    # An item taken off the consent agenda is printed in the approval, not in the list: the consent vote is not its vote.
    assert (agenda["815-15G"]["voted_with"], agenda["815-15G"]["source"], agenda["815-15G"]["moved_to"]) == ("", "agenda", "")
    # One moved to the regular agenda has a new number there, a line the agenda does not have, after the lines before it.
    moved = agenda["815-10D"]
    assert (agenda["815-15O"]["voted_with"], agenda["815-15O"]["moved_to"]) == ("", "10.D")
    assert (moved["source"], moved["moved_from"], moved["section_id"], moved["level"]) == ("minutes", "15.O", "815-10", 2)
    assert moved["title"].endswith("transfer, sale, or disposal. (SHERIFF)") and moved["subject"] == "SHERIFF"
    assert (moved["action"], moved["ayes"], moved["votes_read"]) == ("ADOPTED as amended, Resolution 2024-073", 4, True)
    # The approval of the regular agenda has no number: it is a line of the minutes' own, under the standing orders.
    regular = agenda["815-u1"]
    assert (regular["title"], regular["level"], regular["heading"], regular["agenda_number"], regular["section_id"]) == (
        "APPROVAL OF THE REGULAR AGENDA", 0, False, "", "815-1")
    assert (regular["action"], regular["mover"], regular["ayes"], regular["source"]) == ("APPROVED as amended", "Sharon Dryden", 4, "minutes")


def test_minutes_with_no_agenda_give_their_own_lines_and_an_agenda_with_no_minutes_gives_lines_with_nothing_done():
    agenda, votes, facts = read(agenda=None)
    assert list(agenda) == ["815-u1", "815-2", "815-6", "815-6A", "815-10", "815-10A", "815-10B", "815-10D", "815-13", "815-13A",
                            "815-15", "815-15A", "815-15S"]  # in the order of their numbers
    assert {row["source"] for row in agenda.values()} == {"minutes"} and facts["agenda"] == ""
    assert agenda["815-6A"]["title"].startswith("Resolution authorizing Public Health to hire an Extra-Help Senior Public Health Nurse to meet")
    assert agenda["815-15A"]["voted_with"] == "815-15" and agenda["815-10A"]["result"] == "Fail"
    agenda, votes, facts = read(text="")
    assert len(agenda) == 16 and votes == [] and (facts["minutes"], facts["agenda"], facts["motions"]) == ("", "read", 0)
    assert {row["source"] for row in agenda.values()} == {"agenda"} and agenda["815-15A"]["voted_with"] == ""


def test_the_approval_under_a_bare_heading_an_item_resumed_and_a_heading_of_the_minutes_own():
    text = MINUTES.replace("REGULAR AGENDA\n2. PUBLIC", "2. PUBLIC").replace("APPROVAL OF THE REGULAR AGENDA\n", "REGULAR AGENDA\n").replace(
        "13. CLOSED SESSION", "Item 10.B. continued from earlier in the meeting.\n      The Board moved to reconsider.\n"
        "APPROVED. Motion: Dryden/Heuer/Unanimous Roll Call Vote: 4/0/1 (Supervisor Roen ABSENT)\n13. CLOSED SESSION").replace(
        "      The Board met in closed session from 11:17 a.m. to 12:42 p.m.",
        "      The Board moved to approve the agreement.\nAPPROVED, Agreement 2024-050. Motion: Adams/Heuer/Unanimous Roll Call Vote: 4/0")
    agenda, votes, _ = read(text)
    # With no "APPROVAL OF THE REGULAR AGENDA", the heading "REGULAR AGENDA" is where the minutes approve it.
    assert (agenda["815-u1"]["title"], agenda["815-u1"]["action"], agenda["815-u1"]["section_id"]) == ("REGULAR AGENDA", "APPROVED as amended", "815-1")
    # An item taken up again later has both its motions on its one line.
    again = agenda["815-10B"]
    assert (again["motions"], again["motions_read"], again["votes_read"], again["ayes"]) == (2, 1, False, 4)
    assert sorted({vote["motion"] for vote in votes if vote["item_id"] == "815-10B"}) == [2]
    # A motion under a heading of the minutes' own is a line after the numbered line it follows; Roen has no row,
    # being absent at the head and left out of the count.
    stated = agenda["815-u2"]
    assert (stated["title"], stated["number"], stated["sequence"] - agenda["815-13A"]["sequence"]) == ("CLOSED SESSION STATEMENT", "Agreement 2024-050", 1)
    assert sorted(vote["member"] for vote in votes if vote["item_id"] == "815-u2") == ["Lee Adams", "Lila Heuer", "Sharon Dryden", "Terry LeBlanc"]


def test_minutes_that_cannot_be_read_at_all_are_told_apart():
    assert sierra.legible(MINUTES) == ""
    assert sierra.legible("\n\f\n\f\n") == "no text layer"
    assert sierra.legible("(cid:36)(cid:51)(cid:51)(cid:53)(cid:50)(cid:57)(cid:40)(cid:39). Motion: Adams/Roen " * 20) == "text not legible"
    assert sierra.scan(MINUTES)["day"] == "2024-05-07"  # held against the listing's day: minutes of another day are not read


def test_the_five_tables_come_out_in_the_one_shape(tmp_path, monkeypatch):
    rows, vote_rows, facts = sierra.read_meeting(MEETING, sierra.agenda_of(AGENDA), sierra.scan(MINUTES), {}, pages=2)
    agenda, votes = sierra.typed(pd.DataFrame(rows, columns=sierra.AGENDA_COLUMNS), pd.DataFrame(vote_rows, columns=sierra.VOTE_COLUMNS))
    meetings = sierra.meetings_table(sierra.rows_of(LISTING))
    for name, empty in sierra.FACTS:
        meetings[name] = [facts[name] if meeting_id == "815" else empty for meeting_id in meetings["meeting_id"]]
    members = sierra.members_table(votes, meetings, on="2024-06-01")
    assert len(members) == 0  # votes on one day only make nobody a member
    later = votes.assign(date="2024-05-21", meeting_id="816", item_id=votes["item_id"].str.replace("815-", "816-"))
    both = pd.concat([votes, later], ignore_index=True)
    tables = council_tables.standard({"items": sierra.items_table(agenda, meetings), "meetings": meetings, "agenda_items": agenda,
                                      "votes": both, "members": sierra.members_table(both, meetings, on="2024-06-01")})
    for name in council_tables.TABLES:
        assert list(tables[name].columns)[:len(council_tables.COLUMNS[name])] == council_tables.COLUMNS[name]
    items = tables["items"].set_index("matter_id")
    assert len(items) == 11 and "815-15" not in items.index and "815-6" not in items.index  # a section is not an item
    assert (items.loc["815-15A", "action_on"], items.loc["815-15A", "ayes"], items.loc["815-15A", "mover"], items.loc["815-15A", "result"]) == (
        "section", 4, "Lila Heuer", "Pass")
    assert items.loc["815-15A", "last_action"] == "ADOPTED, Resolution 2024-059" and items.loc["815-15S", "last_action"] == "APPROVED as amended"
    assert (items.loc["815-10A", "action_on"], items.loc["815-10A", "noes"], items.loc["815-10A", "result"]) == ("item", 2, "Fail")
    assert (items.loc["815-15G", "action_on"], items.loc["815-13A", "action_on"]) == ("", "")
    assert items.loc["815-10B", "votes_read"] == False and pd.isna(items.loc["815-13A", "votes_read"])  # noqa: E712
    assert (items["passed_date"] == "").all() and (items["times_on_agenda"] == 1).all()
    members = tables["members"].set_index("name")
    assert list(members.index) == ["Lee Adams", "Lila Heuer", "Paul Roen", "Sharon Dryden", "Terry LeBlanc"]
    assert members["district"].to_dict() == {"Lee Adams": 1, "Lila Heuer": 2, "Paul Roen": 3, "Sharon Dryden": 5, "Terry LeBlanc": 4}
    assert members["serving"].all() and (members.loc["Paul Roen", "role"], members.loc["Lila Heuer", "role"]) == ("Chair", "")
    assert not sierra.members_table(both, meetings, on="2025-06-01")["serving"].any()  # a last vote long ago
    assert set(tables["votes"]["established"]) == {"named", "count"} and set(tables["votes"]["vote"]) == {"AYE", "NO", "ABSENT"}
    assert int(meetings.set_index("meeting_id").loc["840", "motions"]) == 0
    council_tables.write_tables(tables, tmp_path)
    assert sorted(path.name for path in tmp_path.glob("*.parquet")) == sorted(f"{name}.parquet" for name in council_tables.TABLES)
    monkeypatch.setattr(sierra, "CARD_FILE", Path(__file__).resolve().parent.parent / "README_sierra_board.md")
    card = sierra.card(tables)
    assert not re.search(r"\{[a-z_]+\}", card) and "chrissoria/sierra-county-board" in card


def test_a_refusal_stops_the_host_being_asked_again(monkeypatch):
    class Answer:
        status_code, headers, content, text = 403, {"content-type": "text/html"}, b"<html>", "<html>"

    class Session:
        asked = []

        def get(self, url, **said):
            self.asked.append(url)
            return Answer()

    monkeypatch.setattr(sierra, "_refused", sierra.threading.Event())
    monkeypatch.setattr(sierra, "_session", Session())
    monkeypatch.setattr(sierra, "PAUSE", 0)
    with pytest.raises(sierra.Refused):
        sierra.fetch("https://example.test/a")
    with pytest.raises(sierra.Refused):
        sierra.fetch("https://example.test/b")
    assert Session.asked == ["https://example.test/a"]


def test_a_page_sent_in_place_of_the_minutes_is_not_kept_as_minutes(monkeypatch, tmp_path):
    class Answer:
        status_code, headers, content, text = 200, {"content-type": "text/html"}, b"<!DOCTYPE html><html>", "<html>"

    monkeypatch.setattr(sierra, "fetch", lambda url: Answer())
    with pytest.raises(sierra.NotPDF):
        sierra.text_of({"meeting_id": "880", "minutes_url": "https://example.test/Minutes/_02042025-880"}, tmp_path)
    assert not (tmp_path / "text" / "880.txt").exists()
