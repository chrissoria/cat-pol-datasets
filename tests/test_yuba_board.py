"""build_yuba_board reads the Yuba County Board's votes out of minutes that name every supervisor in every motion: a
motion is read only if its names are that meeting's roll, and then whole."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import build_yuba_board as yuba
import council_tables

ROLL = ["Vasquez", "House", "Fuhrer", "Bradford", "Messick"]
MEETING = {"meeting_id": "355", "date": "2026-09-22"}

# The calendar's answer for two meetings, as the portal gives it.
EVENTS = [
    {"id": 355, "title": "🔔BOS", "start": "2026-09-22T09:00:00", "end": "2026-09-22T09:00:00",
     "url": "https://agendasuite.org/iip/yuba/meeting/Details/355",
     "description": "🔔 In person meeting: The Board meeting will be open to in-person attendance.\r\n\n\n"
                    "Meeting: BOS - 18/2026\nby: Board of Supervisors\nBegin: 9:00 AM\nRoom: Board Chambers"},
    {"id": 51, "title": "BOS", "start": "2017-07-18T16:00:00", "end": "2017-07-18T16:00:00",
     "description": "Meeting: BOS - 41/2017\nby: Board of Supervisors\nBegin: 4:00 PM\nRoom: Board Chambers"},
]

# A meeting's page, cut down to what is read off it.
PAGE = """<div class="container">
    <div class="row">
        <div class="info col-lg-6"><h4>Board of Supervisors</h4><p>Tuesday, 09/22/2026</p></div>
            <div class="participants col-lg-4">
                <h5>Participants</h5>
                <table style="width:100%;">
                    <thead><tr><th>Name</th><th>Function</th></tr></thead>
                    <tbody>
                            <tr>
                                <td>Seth Fuhrer</td>
                                <td>Chair</td>
                            </tr>
                            <tr>
                                <td>Jon Messsick</td>
                                <td>Vice Chair</td>
                            </tr>
                            <tr>
                                <td>Andy Vasquez</td>
                                <td>Supervisors</td>
                            </tr>
                    </tbody>
                </table>
            </div>
    </div>
    <div class="row">
        <div class="filebox col-md-3 col-xs-12">
            Meeting files:<br />
                <a aria-label="Agenda" target="" href="/iip/yuba/file/getfile/40537">
                    <span class="fas fa-file-pdf" title="Agenda (220 kB)"></span>
                </a>
                <a aria-label="Private minutes" target="" href="/iip/yuba/file/getfile/40576">
                    <span class="fas fa-file-alt" title="Private minutes (252 kB)"></span>
                </a>
                <a aria-label="Agenda package" target="" href="/iip/yuba/file/getfile/40541">
                    <span class="fas fa-book" title="Agenda package"></span>
                </a>
                    <a href="https://play.champds.com/yubacoca/event/118" target="_blank" aria-label="Link to Media"></a>
        </div>
    </div>
    <div class="row">
        <div id="agenda" class="agenda col-lg-12" style="display:none;">
            <h3 class="agendahead">Agenda</h3>
                    <div class="topic">
                        <div class="header">
                                <strong> ROLL CALL - Supervisors Vasquez, House, Fuhrer, Bradford, Messick</strong>
                        </div>
                    </div>
                    <div class="topic">
                        <div class="header">
                                <strong> CONSENT AGENDA</strong>
                        </div>
                            <div class="meetingitem ">
                                <div style="width:40px; float:left; overflow-wrap: break-word;" class="agendanumber">
                                    1
                                </div>
                                <div style="width:70%; float:left;">
                                    All matters listed under Consent Agenda are considered to be action items that are routine and can be enacted in one motion.
                                </div>
                                <div style="width:15%; float:right;">
                                    <span id="agendaitemnumber" style="font-size:smaller">
                                    </span>
                                </div>
                            </div>
                            <div class="meetingitem ">
                                <div style="width:40px; float:left; overflow-wrap: break-word;" class="agendanumber">
                                    2
                                </div>
                                <div style="width:70%; float:left;">
                                    Administrative Services: Declare surplus items as fully depreciated and authorize Auditor-Controller to remove from Capital Asset Listing pursuant to Ordinance Title 2 Section 2.50.060.
                                </div>
                                <div style="width:15%; float:right;">
                                        <a title="Filesize 292 kB" aria-label="Agenda item document" target="" href="/iip/yuba/file/getfile/40372">
                                            <span aria-hidden="true" class="fas fa-file-pdf docicon"></span>
                                        </a>
                                        <div>
                                            <a title="Agenda item details" aria-label="Agenda item" href="/iip/yuba/agendaitem/details/8523">
                                                <span aria-hidden="true" class="fas fa-inbox docicon"></span>
                                             </a>
                                        </div>
                                    <span id="agendaitemnumber" style="font-size:smaller">
                                        473/2026
<br />
                                            <span id="noattachment" style="font-style:italic">1 Attachment</span>
                                    </span>
                                </div>
                            </div>
                            <div class="meetingitem ">
                                <div style="width:40px; float:left; overflow-wrap: break-word;" class="agendanumber">
                                    3
                                </div>
                                <div style="width:70%; float:left;">
                                    Board of Supervisors: Approve presenting proclamation to Tamara Pesci for her years of service to Yuba County, and authorize all Board members to execute.
                                </div>
                                <div style="width:15%; float:right;">
                                        <div>
                                            <a title="Agenda item details" aria-label="Agenda item" href="/iip/yuba/agendaitem/details/8537">
                                             </a>
                                        </div>
                                    <span id="agendaitemnumber" style="font-size:smaller">
                                        487/2026
                                    </span>
                                </div>
                            </div>
                            <div class="meetingitem ">
                                <div style="width:40px; float:left; overflow-wrap: break-word;" class="agendanumber">
                                    4
                                </div>
                                <div style="width:70%; float:left;">
                                    Health and Human Services: Adopt resolution authorizing Health and Human Services Director to accept funds allocated by California Department of Public Health (CDPH) for the Maternal Child and Adolescent Health (MCAH) Grant.
                                </div>
                                <div style="width:15%; float:right;">
                                        <div>
                                            <a title="Agenda item details" aria-label="Agenda item" href="/iip/yuba/agendaitem/details/8530">
                                             </a>
                                        </div>
                                    <span id="agendaitemnumber" style="font-size:smaller">
                                        480/2026
                                    </span>
                                </div>
                            </div>
                            <div class="meetingitem ">
                                <div style="width:40px; float:left; overflow-wrap: break-word;" class="agendanumber">
                                    5
                                </div>
                                <div style="width:70%; float:left;">
                                    Health and Human Services: Approve agreement with Dr. Radha Sadacharan for temporary Health Officer coverage, and authorize Chair to execute.
                                </div>
                                <div style="width:15%; float:right;">
                                    <span id="agendaitemnumber" style="font-size:smaller">
                                        471/2026
                                    </span>
                                </div>
                            </div>
                    </div>
                    <div class="topic">
                        <div class="header">
                                <strong> COUNTY DEPARTMENTS</strong>
                        </div>
                            <div class="meetingitem ">
                                <div style="width:40px; float:left; overflow-wrap: break-word;" class="agendanumber">
                                    29
                                </div>
                                <div style="width:70%; float:left;">
                                    Sheriff-Coroner: Approve agreement with Priority Dispatch System for the implementation of Emergency Medical Dispatch (EMD) program, and authorize Chair to execute. (Five minute estimate)
                                </div>
                                <div style="width:15%; float:right;">
                                        <div>
                                            <a title="Agenda item details" aria-label="Agenda item" href="/iip/yuba/agendaitem/details/8524">
                                             </a>
                                        </div>
                                    <span id="agendaitemnumber" style="font-size:smaller">
                                        474/2026
                                    </span>
                                </div>
                            </div>
                    </div>
                    <div class="topic">
                        <div class="header">
                                <strong> ADJOURN</strong>
                        </div>
                    </div>
        </div>
        <div id="minutes" class="agenda col-lg-12" style="">
            <h3 class="agendahead">Minutes</h3>
                    <div class="topic"><div class="header"><strong> CONSENT AGENDA</strong></div></div>
        </div>
    </div>
</div>"""

# Minutes as the reader keeps them: each line as far in as it stands on the page, an empty line where the page leaves
# a gap, a form feed between two pages and "Page 1 of 2" at a page's foot.
MINUTES = """
        BOARD  OF  SUPERVISORS                          Agenda materials are available at the
                                                        Yuba County Government Center,
        Summary   of Proceedings                        915 8th Street, Marysville and
                                 Tuesday, September 22, 2026
                                       9:00 A.M.
       Invocation led by Pastor Carlton Ashlock
       PLEDGE OF ALLEGIANCE – led by Supervisor House

       ROLL CALL - Supervisors Vasquez, House, Fuhrer, Bradford, Messick – Supervisor Fuhrer was
       absent

       CONSENT AGENDA

       Chair Fuhrer pulled agenda item 471/2026 to County Departments for discussion at the request of
       Supervisor House.

       MOTION: Move to approve with amendments
       MOVED: Andy Vasquez SECOND: Gary Bradford
       AYES: Andy Vasquez, Renick House, Gary Bradford, Jon Messick
       NOES: None
       ABSENT: Seth Fuhrer
       ABSTAIN: None

       Approved via unanimous Vote

       473/2026  Administrative Services: Declare surplus items as fully depreciated and authorize Auditor-
                 Controller to remove from Capital Asset Listing pursuant to Ordinance Title 2 Section
                 2.50.060. Approved

       480/2026  Health and Human Services: Adopt resolution authorizing Health and Human Services
                 Director to accept funds allocated by California Department of Public

                                        Page 1 of 2
\f

                 Health (CDPH) for the Maternal Child and Adolescent Health (MCAH) Grant. Adopted
                 Resolution No. 2026-75

       471/2026  Health and Human Services: Approve agreement with Dr. Radha Sadacharan for temporary
                 Health Officer coverage, and authorize Chair to execute. Moved to County
                 Departments for discussion.

       COUNTY DEPARTMENTS

       474/2026  Sheriff-Coroner: Approve agreement with Priority Dispatch System for the implementation of
                 Emergency Medical Dispatch (EMD) program, and authorize Chair to execute. (Five minute
                 estimate) Undersheriff Nick Morawczski provided a brief recap, and responded to Board
                 inquiries.

                 MOTION: Move to approve
                 MOVED: Andy Vasquez SECOND: Renick House
                 AYES: Andy Vasquez, Renick House, Jon Messsick
                 NOES: Gary Bradford
                 ABSENT: Seth Fuhrer
                 ABSTAIN: None

                 Approved via Roll Call Vote

       471/2026  Health and Human Services: Approve agreement with Dr. Radha Sadacharan for temporary
                 Health Officer coverage, and authorize Chair to execute. Director Jennifer Vasquez
                 provided a brief recap, and responded to Board inquiries.

                 MOTION: Move to approve
                 MOVED: Renick House SECOND: Gary Bradford
                 AYES: Andy Vasquez, Renick House, Gary Bradford
                 NOES/ABSENT/ABSTAIN: None

                 Approved via unanimous Vote

       502/2026  County Administrator: Approve letter of support for the regional water plan. County
                 Administrator Kevin Mallen provided a brief recap.

                 MOTION: Move to approve
                 MOVED: Gary Bradford SECOND: Jon Messick

       ADJOURN – at 11:03 A.M.

                                        Page 2 of 2
"""

# The grid the minutes of July to September 2017 print in place of the lists of names.
GRID = """
       ROLL CALL - Supervisors Vasquez, Leahy, Lofton, Bradford, Fletcher

       CONSENT AGENDA

                 All matters listed under Consent Agenda are considered to be routine and can be enacted in
                 one motion.


                 MOTION:
                 MOVED: Bradford, Gary SECOND: Leahy, Mike
                             YES    NO      ABSTAIN  ABSENT
                 Gary Bradford X
                 Randy Fletcher                      X
                 Mike Leahy  X
                 Doug Lofton        X
                 Andy Vasquez X
                                      Motion Carried
       165/2017  Office of Emergency Services: Adopt resolution proclaiming ongoing local emergency due to
                 tree mortality.
                 Adopted Resolution No. 2017-79.
                 MOTION:
                 MOVED: SECOND:

                                        Page 1 of 9
\f

                             YES    NO      ABSTAIN  ABSENT
                 Gary Bradford
                 Randy Fletcher
                 Mike Leahy
                 Doug Lofton
                 Andy Vasquez
       SPECIAL PRESENTATIONS

       305/2017  Present proclamation declaring July 2017 Sexual Assault Awareness Month.
                 Recognized
"""


def read(text=MINUTES, page=PAGE, meeting=MEETING, spelled=None):
    agenda, votes, facts = yuba.read_meeting(meeting, yuba.page_of(page) if page else None, yuba.scan(text) if text else None,
                                             spelled, pages=text.count("\f") + 1 if text else 0)
    return {row["item_id"]: row for row in agenda}, votes, facts


def decided(block, roll=ROLL):
    """A motion's block of lines against a roll, as ({supervisor: vote}, problem)."""
    lines = yuba.lines_of("MOTION: Move to approve\n" + block)
    cast, problem = yuba.decide(yuba.motion_at(lines, 0, 0)[0], roll)
    return (None if cast is None else {member: word for member, _, word in cast}), problem


def test_the_calendar_gives_each_meeting_its_number_day_hour_room_and_name():
    meetings = yuba.meetings_table(yuba.rows_of(EVENTS)).set_index("meeting_id")
    assert list(meetings.index) == ["51", "355"]
    last = meetings.loc["355"]
    assert (last["date"], last["time"], last["location"], last["name"]) == ("2026-09-22", "9:00 AM", "Board Chambers", "BOS - 18/2026")
    assert last["url"] == "https://agendasuite.org/iip/yuba/meeting/details/355"
    assert last["note"].startswith("In person meeting:") and meetings.loc["51", "note"] == ""
    assert meetings.loc["51", "time"] == "4:00 PM"
    assert list(meetings.columns)[:len(council_tables.COLUMNS["meetings"]) - 1] == council_tables.COLUMNS["meetings"][1:]


def test_a_page_gives_the_documents_the_board_and_the_agendas_lines():
    page = yuba.page_of(PAGE)
    assert page["files"] == {"agenda": "https://agendasuite.org/iip/yuba/file/getfile/40537",
                             "minutes": "https://agendasuite.org/iip/yuba/file/getfile/40576",
                             "packet": "https://agendasuite.org/iip/yuba/file/getfile/40541"}
    assert page["participants"][:2] == [{"name": "Seth Fuhrer", "role": "Chair"}, {"name": "Jon Messsick", "role": "Vice Chair"}]
    assert [(line["number"], line["file"], line["item"]) for line in page["lines"]] == [
        ("1", "", ""), ("2", "473/2026", "8523"), ("3", "487/2026", "8537"), ("4", "480/2026", "8530"), ("5", "471/2026", ""),
        ("29", "474/2026", "8524")]
    first = page["lines"][1]
    assert first["section"] == "CONSENT AGENDA" and first["title"].startswith("Administrative Services: Declare surplus items")
    assert first["document"] == "https://agendasuite.org/iip/yuba/file/getfile/40372"
    # A number the portal has no meeting for answers with a page that says so.
    assert yuba.page_of("<html><body>An error occurred while processing your request. Error: Id not found.</body></html>")["found"] is False


def test_a_printed_name_is_matched_to_the_roll_by_its_surname():
    assert yuba.who("Andy Vasquez", ROLL) == "Vasquez"
    assert yuba.who("Bradford, Gary", ROLL) == "Bradford"  # a mover in the minutes of 2017
    assert yuba.who("Jon Messsick", ROLL) == "Messick"  # a letter out, and no other name as near
    assert yuba.who("Mike Leahy", ROLL) is None and yuba.who("", ROLL) is None
    assert yuba.who("Maria De La Cruz", ["Vasquez", "De La Cruz"]) == "De La Cruz"
    assert yuba.names_in("Andy Vasquez, Renick House, and Seth Fuhrer") == ["Andy Vasquez", "Renick House", "Seth Fuhrer"]
    assert yuba.names_in("Don Blaser. Seth Fuhrer, Gary Bradford") == ["Don Blaser", "Seth Fuhrer", "Gary Bradford"]  # a full stop for a comma
    assert yuba.names_in("None") == [] and yuba.names_in("None.") == []


def test_the_roll_is_the_surnames_on_the_roll_call_line():
    assert yuba.roll_of("ROLL CALL - Supervisors Vasquez, House, Fuhrer, Bradford, Messick – all present")[0] == ROLL
    assert yuba.roll_of("ROLL CALL - Supervisors Vasquez, Blaser, Fuhrer, Bradford, Fletcher- All present")[0] == ["Vasquez", "Blaser", "Fuhrer", "Bradford", "Fletcher"]
    roll, printed = yuba.roll_of("ROLL CALL - Supervisors Vasquez, Blaser, Fuhrer, Bradford, Messick – Supervisor Andy Vasquez was absent")
    assert roll == ["Vasquez", "Blaser", "Fuhrer", "Bradford", "Messick"] and printed.endswith("was absent")
    assert yuba.roll_of("ROLL CALL – All present")[0] == []  # a line that names nobody gives no roll


def test_a_motion_is_read_in_each_of_the_forms_the_minutes_print_it_in():
    names = "AYES: Andy Vasquez, Renick House, Seth Fuhrer, Gary Bradford, Jon Messick\n"
    assert decided(names + "NOES/ABSENT/ABSTAIN: None") == ({member: "AYE" for member in ROLL}, "")
    assert decided(names + "NOES/ABSTAIN/ABSENT: None")[1] == ""
    cast, problem = decided("AYES: Renick House, Seth Fuhrer, Gary Bradford, Jon Messick\nNOES: None ABSTAIN: None ABSENT: Andy Vasquez")
    assert problem == "" and cast["Vasquez"] == "ABSENT" and cast["House"] == "AYE"
    cast, _ = decided("AYES: Renick House, Gary Bradford, Jon Messick\nNOES: Andy Vasquez, Seth Fuhrer\nABSENT: None\nABSTAIN: None")
    assert sorted(member for member, word in cast.items() if word == "NO") == ["Fuhrer", "Vasquez"]
    assert decided("YES: Andy Vasquez, Renick House, Seth Fuhrer, Gary Bradford\nNOES: None ABSENT: None ABSTAIN: Jon Messick")[0]["Messick"] == "ABSTAIN"
    # A list of names that runs on to a second line.
    assert decided("AYES: Andy Vasquez, Renick House, Seth Fuhrer,\nGary Bradford, Jon Messick\nNOES/ABSENT/ABSTAIN: None")[1] == ""


def test_the_roll_has_those_the_roll_call_names_as_absent_after_its_list():
    assert yuba.roll_of("ROLL CALL - Supervisors Vasquez, Blaser, Messick – Supervisors Fuhrer and Bradford were absent")[0] == [
        "Vasquez", "Blaser", "Messick", "Fuhrer", "Bradford"]
    assert yuba.roll_of("ROLL CALL - Supervisors Vasquez, Leahy, Lofton, Fletcher- Supervisor Bradford absent")[0][-1] == "Bradford"
    assert yuba.roll_of("ROLL CALL - Supervisors Vasquez, Blaser, Bradford and Fuhrer. Supervisor Fletcher was absent.")[0] == [
        "Vasquez", "Blaser", "Bradford", "Fuhrer", "Fletcher"]
    # One already in the list is not there twice, whether by surname or by full name.
    assert yuba.roll_of("ROLL CALL - Supervisors Vasquez, Leahy, Lofton, Bradford, Fletcher – Lofton and Fletcher Absent")[0] == [
        "Vasquez", "Leahy", "Lofton", "Bradford", "Fletcher"]
    assert len(yuba.roll_of("ROLL CALL - Supervisors Vasquez, House, Fuhrer, Bradford, Messick – Supervisor Jon Messick was absent")[0]) == 5
    # What is said under the roll call after a gap is not part of it.
    scanned = yuba.scan("       ROLL CALL - Supervisors Vasquez, House, Fuhrer, Bradford, Messick\n\n"
                        "       Chair Vasquez announced that agenda item 105/2023 had been moved to a\n       future meeting.\n")
    assert scanned["roll"] == ROLL and scanned["present"].endswith("Messick")


def test_the_minutes_own_slips_in_the_words_of_a_vote_are_read():
    names = "AYES: Andy Vasquez, Renick House, Seth Fuhrer, Jon Messick\n"
    assert decided(names + "NOES: None ABTAIN: None\nABSENT: Gary Bradford")[0]["Bradford"] == "ABSENT"
    assert decided(names + "NOES: None\nABSNET: None ABSTAIN: Gary Bradford")[0]["Bradford"] == "ABSTAIN"
    assert decided(names + "NOES: Gary Bradford Absent: None ABSTAIN: None")[0]["Bradford"] == "NO"
    assert decided("AYES: Andy Vasqeuz, Renick House, Seth Fuhrer, Jon Messick\nNOES/ASBENT/ABSTAIN: None\nRECUSE: Gary Bradford")[0] == {
        "Vasquez": "AYE", "House": "AYE", "Fuhrer": "AYE", "Messick": "AYE", "Bradford": "RECUSED"}
    # Who moved is printed "MOVE:", "MOVED" with no colon, on the motion's own line, or under a second "MOTION:".
    for moved in ("MOVE: Seth Fuhrer SECOND: Andy Vasquez", "MOVED Seth Fuhrer SECOND: Andy Vasquez", "MOTION: Seth Fuhrer SECOND: Andy Vasquez"):
        motion = yuba.motion_at(yuba.lines_of(f"MOTION: Move to approve\n{moved}\n{names}NOES/ABSENT/ABSTAIN: None"), 0, 0)[0]
        assert (motion["text"], motion["mover"], motion["seconder"], motion["said"][0][1][0]) == ("Move to approve", "Seth Fuhrer", "Andy Vasquez", "Andy Vasquez")
    motion = yuba.motion_at(yuba.lines_of(f"MOTION: Move to approve MOVE: Seth Fuhrer SECOND: Andy Vasquez\n{names}"), 0, 0)[0]
    assert (motion["text"], motion["mover"], motion["seconder"]) == ("Move to approve", "Seth Fuhrer", "Andy Vasquez")


def test_a_motion_whose_names_are_not_the_roll_is_not_read():
    assert decided("YES: Andy Vasquez, Renick House, Seth Fuhrer, Jon Messick\nNOES: None ABSENT: None ABSTAIN: None") == (
        None, "names 4 of the 5 on the roll: no Bradford")
    assert decided("AYES: Andy Vasquez, Renick House, Seth Fuhrer, Gary Bradford, Jon Messick\nNOES: Seth Fuhrer\nABSENT: None\nABSTAIN: None")[1] == "named twice: Fuhrer"
    assert decided("AYES: Andy Vasquez, Renick House, Seth Fuhrer, Gary Bradford, Mike Leahy\nNOES/ABSENT/ABSTAIN: None")[1] == "not on the roll: Mike Leahy"
    assert decided("AYES: Andy Vasquez, Renick House, Seth Fuhrer, Gary Bradford\nNOES/ABSENT/ABSTAIN: Jon Messick")[1] == "names under NOES/ABSENT/ABSTAIN together"
    assert decided("MOVED: Andy Vasquez SECOND: Gary Bradford")[1] == "no names: the motion has no AYES line"
    assert decided("AYES: None\nNOES/ABSENT/ABSTAIN: None")[1] == "no names: every list is empty"
    assert decided("AYES: Andy Vasquez, Renick House, Seth Fuhrer, Gary Bradford, Jon Messick\nNOES/ABSENT/ABSTAIN: None", roll=[])[1] == "no roll call that names the Board"


def test_a_grid_is_read_by_where_each_x_stands_and_an_empty_one_is_not_a_motion():
    scanned = yuba.scan(GRID)
    consent, item, presentation = [entry for entry in scanned["entries"] if entry["name" if entry["kind"] == "heading" else "file"]
                                   in ("CONSENT AGENDA", "165/2017", "305/2017")]
    assert len(consent["motions"]) == 1 and item["motions"] == []  # the form left empty under the item is no motion
    motion = consent["motions"][0]
    assert (motion["mover"], motion["seconder"], motion["after"]) == ("Bradford, Gary", "Leahy, Mike", "Motion Carried")
    assert {member: word for member, _, word in motion["cast"]} == {
        "Bradford": "AYE", "Fletcher": "ABSENT", "Leahy": "AYE", "Lofton": "NO", "Vasquez": "AYE"}
    # The heading after the empty grid is not a row of it, and the item under it is its own.
    assert presentation["section"] == "SPECIAL PRESENTATIONS" and presentation["text"].endswith("Recognized")
    # A grid with a row that has no X says nothing of that supervisor: the motion is not read.
    half = yuba.scan(GRID.replace("Doug Lofton        X", "Doug Lofton"))
    assert [entry for entry in half["entries"] if entry.get("name") == "CONSENT AGENDA"][0]["motions"][0]["problem"] == "the grid has no X for Doug Lofton"


def test_a_grid_whose_long_name_runs_on_to_a_second_line_is_read_by_the_order_of_its_xs():
    late = """
       ROLL CALL - Supervisors Vasquez, Leahy, Lofton, Bradford, Fletcher

       COUNTY DEPARTMENTS

       542/2017  Office of Emergency Services: Adopt resolution proclaiming a local emergency.

                 MOTION: Move to adopt
                 MOVED: Leahy, Mike SECOND: Vasquez, Andy
                          YES       NO      ABSTAIN  ABSENT
                 Gary Bradford X
                 Randy    X
                 Fletcher X
                 Mike Leahy X
                 Doug Lofton X
                 Andy Vasquez
                               Adopted Resolution No. 2017-151
       ADJOURN: 10:01 a.m.
"""
    motion = yuba.scan(late)["entries"][-2]["motions"][0]
    # Six lines for five names, an X on each of the first five: the X's stand one to a line from the top.
    assert [mark for (mark,), _ in motion["said"]] == ["YES", "YES", "YES", "YES", "YES", ""]
    assert {member: word for member, _, word in motion["cast"]} == {member: "AYE" for member in ("Bradford", "Fletcher", "Leahy", "Lofton", "Vasquez")}
    assert (motion["after"], motion["mover"]) == ("Adopted Resolution No. 2017-151", "Leahy, Mike")  # what stands further in is not a line of the grid
    # With an X missing from those first lines, whose X is whose cannot be told.
    motion = yuba.scan(late.replace("Mike Leahy X", "Mike Leahy").replace("Andy Vasquez\n", "Andy Vasquez X\n"))["entries"][-2]["motions"][0]
    assert (motion["cast"], motion["problem"]) == (None, "the grid's X's cannot be told one supervisor's from another's")
    # An X that stands in the middle of a name's line is still one X, under the word nearest it.
    whole = late.replace("                 Randy    X\n                 Fletcher X\n", "                 Randy X Fletcher\n").replace("Andy Vasquez\n", "Andy Vasquez                         X\n")
    cast = {member: word for member, _, word in yuba.scan(whole)["entries"][-2]["motions"][0]["cast"]}
    assert (cast["Fletcher"], cast["Vasquez"]) == ("AYE", "ABSENT")


def test_a_motion_with_no_second_is_not_a_vote_and_one_with_no_heading_is_kept_by_its_words():
    text = MINUTES.replace("""                 MOTION: Move to approve
                 MOVED: Gary Bradford SECOND: Jon Messick
""", """                 MOTION: Move to table item to a later time by Supervisor Seth
                 Fuhrer

                 Motion failed for lack of a second
""")
    agenda, _, facts = read(text)
    died = agenda["355-502-2026"]
    assert (died["motions"], died["votes_read"], died["problem"]) == (0, None, "")
    assert "MOTION: Move to table item to a later time by Supervisor Seth Fuhrer Motion failed for lack of a second" in died["title"]
    assert facts["motions"] == 3
    # A motion made before the roll call, printed from "Motion:" on with no heading over it.
    head = """       Chair Bradford read the disclaimer.
       Motion: No employee is mandated to be here, and the meeting will continue with a hybrid
       version
       MOVE: Seth Fuhrer SECOND: Andy Vasquez
       AYES: Andy Vasquez, Renick House, Seth Fuhrer
       NOES: Gary Bradford, Jon Messick
       ABSTAIN/ABSENT: None

       Approved via Roll Call Vote

"""
    agenda, votes, _ = read(MINUTES.replace("       Invocation led by Pastor Carlton Ashlock\n", head))
    first = agenda["355-motion"]
    assert (first["heading"], first["sequence"], first["ayes"], first["noes"], first["result"]) == (True, 1, 3, 2, "Pass")
    assert first["title"] == "No employee is mandated to be here, and the meeting will continue with a hybrid version"
    assert (first["mover"], first["action"]) == ("Fuhrer", "Approved via Roll Call Vote")
    # The head of the first page, "BOARD OF SUPERVISORS" with a notice beside it, is not a heading.
    assert not [row for row in agenda.values() if "BOARD OF SUPERVISORS" in row["title"]]


def test_a_file_number_printed_with_a_hyphen_or_short_of_a_digit_is_still_the_pages_item():
    text = MINUTES.replace("       473/2026  Administrative", "       473-2026  Administrative").replace("       480/2026  Health", "       480/226   Health")
    agenda, _, _ = read(text)
    assert (agenda["355-473-2026"]["action"], agenda["355-473-2026"]["in_minutes"]) == ("Approved", True)
    assert (agenda["355-480-2026"]["number"], agenda["355-480-2026"]["section_id"]) == ("2026-75", "355-consent")
    assert yuba._ITEM.match("2025/2026 Annual Report") is None and yuba._ITEM.match("2019-2020 Budget") is None  # years, not a file number
    assert yuba._ITEM.match("653-2020 and 22-2021") is None


def test_what_the_minutes_say_of_how_a_motion_went_is_the_result():
    carried = lambda after: "Fail" if yuba._FAILED.search(after) else "Pass" if yuba._CARRIED.search(after) else ""
    assert carried("Approved via unanimous Vote") == carried("Motion Carried") == carried("Adopted Resolution No. 2022-256 via Unanimous Vote") == "Pass"
    assert carried("Supervisor Fuhrer voted No on Agenda item 490/2025 Approved via majority Vote") == carried("Denied via Roll Call Vote") == "Pass"
    assert carried("Motion failed via Roll Call Vote") == carried("Motion failed Chair Blaser continued this item") == "Fail"
    assert carried("Supervisor Fuhrer voted No on item 289-2022") == carried("Director Mike Lee recapped the project.") == ""


def test_minutes_are_read_onto_the_agendas_lines_with_the_consent_vote_on_its_heading():
    agenda, votes, facts = read()
    assert list(agenda) == ["355-consent", "355-473-2026", "355-487-2026", "355-480-2026", "355-471-2026", "355-474-2026", "355-502-2026"]
    consent = agenda["355-consent"]
    assert consent["heading"] and (consent["title"], consent["matter_id"]) == ("CONSENT AGENDA", "")
    assert consent["action"] == ("Chair Fuhrer pulled agenda item 471/2026 to County Departments for discussion at the request of "
                                 "Supervisor House. Approved via unanimous Vote")
    assert (consent["mover"], consent["seconder"], consent["result"]) == ("Vasquez", "Bradford", "Pass")
    assert (consent["ayes"], consent["noes"], consent["not_voting"], consent["votes_read"]) == (4, 0, 1, True)
    # An item under the consent agenda has no motion of its own and points to the heading. Its title is the page's,
    # and what the minutes say after it is the action.
    item = agenda["355-473-2026"]
    assert (item["matter_id"], item["matter_file"], item["agenda_number"], item["action"]) == ("8523", "473/2026", "2", "Approved")
    assert (item["section"], item["section_id"], item["motions"], item["votes_read"]) == ("CONSENT AGENDA", "355-consent", 0, None)
    assert (item["subject"], item["in_minutes"]) == ("Administrative Services", True)
    # A paragraph runs over the page's end; the page's foot is not part of it.
    resolution = agenda["355-480-2026"]
    assert (resolution["action"], resolution["number"], resolution["doc_type"]) == ("Adopted Resolution No. 2026-75", "2026-75", "resolution")
    # An item on the agenda that the minutes leave out has nothing done.
    left_out = agenda["355-487-2026"]
    assert (left_out["in_minutes"], left_out["action"], left_out["section_id"]) == (False, "", "")
    assert facts["present"].endswith("Supervisor Fuhrer was absent") and facts["motions"] == 4
    assert {member["name"]: member["role"] for member in json.loads(facts["roll"])} == {
        "Vasquez": "", "House": "", "Fuhrer": "Chair", "Bradford": "", "Messick": "Vice Chair"}
    assert (facts["agenda_url"].rsplit("/", 1)[1], facts["minutes_url"].rsplit("/", 1)[1], facts["packet_url"].rsplit("/", 1)[1]) == ("40537", "40576", "40541")


def test_an_item_taken_off_the_consent_agenda_is_one_line_with_its_own_motion():
    agenda, votes, _ = read()
    pulled = agenda["355-471-2026"]
    assert (pulled["matter_id"], pulled["section_id"], pulled["motions"]) == ("471/2026", "", 1)  # the page gives it no number of its own
    assert pulled["action"] == ("Moved to County Departments for discussion. Director Jennifer Vasquez provided a brief recap, and "
                                "responded to Board inquiries. Approved via unanimous Vote")
    # Its motion names three of the five, so nobody's vote on it is written.
    assert (pulled["votes_read"], pulled["problem"], pulled["ayes"]) == (False, "names 3 of the 5 on the roll: no Fuhrer, Messick", 0)
    assert not [vote for vote in votes if vote["item_id"] == "355-471-2026"]
    assert json.loads(pulled["motion_log"])[0]["said"] == [["AYES", ["Andy Vasquez", "Renick House", "Gary Bradford"]], ["NOES/ABSENT/ABSTAIN", []]]


def test_a_divided_vote_an_absence_and_a_misspelled_name_are_read_as_printed():
    agenda, votes, facts = read(spelled={"vasquez": "Andy Vasquez", "house": "Renick House", "fuhrer": "Seth Fuhrer",
                                         "bradford": "Gary Bradford", "messick": "Jon Messick"})
    divided = agenda["355-474-2026"]
    assert (divided["ayes"], divided["noes"], divided["not_voting"], divided["votes_read"], divided["result"]) == (3, 1, 1, True, "Pass")
    assert divided["title"].endswith("(Five minute estimate)") and divided["action"].startswith("Undersheriff Nick Morawczski provided")
    assert (divided["mover"], divided["seconder"]) == ("Andy Vasquez", "Renick House")
    cast = {vote["member"]: vote["vote"] for vote in votes if vote["item_id"] == "355-474-2026"}
    assert cast == {"Andy Vasquez": "AYE", "Renick House": "AYE", "Jon Messick": "AYE", "Gary Bradford": "NO", "Seth Fuhrer": "ABSENT"}
    assert {vote["established"] for vote in votes} == {"named"} and {vote["motion_text"] for vote in votes if vote["item_id"] == "355-474-2026"} == {"Move to approve"}
    assert [vote["matter_file"] for vote in votes if vote["item_id"] == "355-474-2026"][0] == "474/2026"
    # An item the page does not have follows the line it follows in the minutes; a motion with no names is not read.
    walk_on = agenda["355-502-2026"]
    # With no title from the page and no word for something done, all the minutes say of it is its title.
    assert (walk_on["sequence"], walk_on["agenda_number"], walk_on["matter_id"]) == (7, "", "502/2026")
    assert walk_on["title"] == ("County Administrator: Approve letter of support for the regional water plan. County Administrator "
                                "Kevin Mallen provided a brief recap.")
    assert (walk_on["votes_read"], walk_on["problem"]) == (False, "no names: the motion has no AYES line")
    assert (facts["motions"], facts["motions_read"]) == (4, 2)
    per_motion = pd.DataFrame(votes).groupby(["item_id", "motion"])["member"].agg(["size", "nunique"])
    assert (per_motion["size"] == 5).all() and (per_motion["nunique"] == 5).all()


def test_a_sentence_under_the_consent_motion_gives_the_item_it_names_a_vote_of_its_own():
    text = MINUTES.replace("       Approved via unanimous Vote\n\n       473/2026", "       Supervisor House voted No on item 473-2026\n\n       473/2026", 1)
    agenda, votes, _ = read(text)
    assert (agenda["355-consent"]["ayes"], agenda["355-consent"]["noes"], agenda["355-consent"]["votes_read"]) == (4, 0, True)  # as printed
    item = agenda["355-473-2026"]
    assert (item["motions"], item["votes_read"], item["ayes"], item["noes"], item["not_voting"], item["section_id"]) == (1, True, 3, 1, 1, "")
    own = {vote["member"]: vote for vote in votes if vote["item_id"] == "355-473-2026"}
    assert (own["House"]["vote"], own["Vasquez"]["vote"], own["Fuhrer"]["vote"]) == ("NO", "AYE", "ABSENT")
    assert own["House"]["motion_text"] == "Supervisor House voted No on item 473-2026" and own["House"]["established"] == "named"
    assert agenda["355-480-2026"]["section_id"] == "355-consent"  # the other items are still the consent agenda's
    # The same in the other words the minutes use, with or without an office before the name, and for several items.
    for sentence, word in (("Chair House voted No on agenda item 473/2026 Approved via majority Vote", "NO"),
                           ("Supervisor House abstained from agenda item 473/2026 Approved via unanimous Vote", "ABSTAIN"),
                           ("Supervisor House voted Abstain on Agenda item 473/2026", "ABSTAIN"),
                           ("Supervisor House Abstained on agenda items: 473-2026 and 480/2026 pending a presentation.", "ABSTAIN")):
        agenda, votes, _ = read(text.replace("Supervisor House voted No on item 473-2026", sentence))
        assert agenda["355-consent"]["votes_read"] is True, sentence
        assert {vote["member"]: vote["vote"] for vote in votes if vote["item_id"] == "355-473-2026"}["House"] == word, sentence
        assert bool([vote for vote in votes if vote["item_id"] == "355-480-2026"]) == ("480/2026" in sentence)
    # It is printed in place of a name too: "ABSTAIN: Renick House abstained on agenda item 473/2026".
    agenda, votes, _ = read(MINUTES.replace("       ABSTAIN: None\n\n       Approved via unanimous Vote", "       ABSTAIN: Renick House abstained on agenda item 473/2026\n\n       Approved via unanimous Vote", 1))
    assert (agenda["355-consent"]["ayes"], agenda["355-consent"]["votes_read"], agenda["355-473-2026"]["not_voting"]) == (4, True, 2)
    # A sentence that names an item the consent agenda does not have, or nobody on the roll, leaves the motion unread.
    for sentence in ("Supervisor House voted No on item 999-2026", "Supervisor Leahy voted No on item 473-2026", "Supervisor House abstained"):
        agenda, votes, _ = read(text.replace("Supervisor House voted No on item 473-2026", sentence))
        assert agenda["355-consent"]["votes_read"] is False and agenda["355-consent"]["problem"].startswith("words after the vote not tied")
        assert not [vote for vote in votes if vote["item_id"] in ("355-consent", "355-473-2026")]


def test_a_meeting_with_no_minutes_has_its_agenda_and_nothing_done():
    agenda, votes, facts = read(text="")
    assert list(agenda) == ["355-473-2026", "355-487-2026", "355-480-2026", "355-471-2026", "355-474-2026"] and votes == []
    assert all(row["action"] == "" and row["votes_read"] is None and not row["in_minutes"] for row in agenda.values())
    assert (facts["minutes"], facts["page"], facts["roll"], facts["motions"]) == ("", "read", "", 0)


def test_a_title_is_parted_from_what_was_done_where_the_pages_title_ends():
    title = "Administrative Services: Declare surplus items and authorize Auditor-Controller to remove them."
    assert yuba.split_title("Administrative Services: Declare surplus items and authorize Auditor- Controller to remove them. Approved", title) == (
        "Administrative Services: Declare surplus items and authorize Auditor- Controller to remove them.", "Approved")
    assert yuba.split_title("Receive notice from the Treasurer.", "Receive notice from the Treasurer.") == ("Receive notice from the Treasurer.", "")
    # Without the page's title, or where the minutes word it differently, the first sentence that says something was done.
    assert yuba.split_title("Sheriff: Approve the agreement. Approved as amended") == ("Sheriff: Approve the agreement.", "Approved as amended")
    assert yuba.split_title("Sheriff: Approve the agreement. Adopted Resolution No. 2026-80", "Sheriff-Coroner: Approve agreement.")[1] == "Adopted Resolution No. 2026-80"
    assert yuba.split_title("Sheriff: Approve the agreement") == ("Sheriff: Approve the agreement", "")


def test_a_file_number_in_running_words_does_not_begin_an_item():
    text = MINUTES.replace("       Chair Fuhrer pulled agenda item 471/2026 to County Departments for discussion at the request of\n",
                           "       Chair Fuhrer pulled agenda items\n       471/2026, 495/2026, and 470/2026 to County Departments for discussion at the request of\n")
    agenda, _, _ = read(text)
    assert agenda["355-consent"]["action"].startswith("Chair Fuhrer pulled agenda items 471/2026, 495/2026, and 470/2026 to County")
    assert agenda["355-consent"]["votes_read"] is True


def test_the_five_tables_come_out_in_the_one_shape(tmp_path):
    spelled = {"vasquez": "Andy Vasquez", "house": "Renick House", "fuhrer": "Seth Fuhrer", "bradford": "Gary Bradford", "messick": "Jon Messick"}
    rows, cast, facts = [], [], {}
    for meeting in ({"meeting_id": "354", "date": "2026-09-08"}, MEETING):
        text = MINUTES.replace("355", meeting["meeting_id"])
        agenda_rows, vote_rows, found = yuba.read_meeting(meeting, yuba.page_of(PAGE), yuba.scan(text), spelled, pages=2)
        rows.extend(agenda_rows)
        cast.extend(vote_rows)
        facts[meeting["meeting_id"]] = found
    agenda, votes = yuba.typed(pd.DataFrame(rows, columns=yuba.AGENDA_COLUMNS), pd.DataFrame(cast, columns=yuba.VOTE_COLUMNS))
    listing = [dict(row, meeting_id="354", date="2026-09-08") if row["meeting_id"] == "51" else row for row in yuba.rows_of(EVENTS)]
    meetings = yuba.meetings_table(listing)
    for name, empty in yuba.FACTS:
        meetings[name] = [facts[meeting_id].get(name, empty) for meeting_id in meetings["meeting_id"]]
    tables = council_tables.standard({"items": yuba.items_table(agenda, meetings), "meetings": meetings, "agenda_items": agenda,
                                      "votes": votes, "members": yuba.members_table(votes, meetings, now="2026-10-13")})
    for name in council_tables.TABLES:
        assert list(tables[name].columns)[:len(council_tables.COLUMNS[name])] == council_tables.COLUMNS[name]
    # An item that came to both meetings is in `items` once, with the last of them; the heading and the item the
    # minutes leave out are not items.
    items = tables["items"].set_index("matter_id")
    assert sorted(items.index) == ["471/2026", "502/2026", "8523", "8524", "8530"]
    passed = items.loc["8523"]
    assert (passed["action_on"], passed["ayes"], passed["mover"], passed["votes_read"], passed["result"]) == ("section", 4, "Andy Vasquez", True, "Pass")
    assert (passed["date"], passed["agenda_date"], passed["times_on_agenda"], passed["meeting_id"]) == ("2026-09-22", "2026-09-08", 2, "355")
    assert passed["url"] == "https://agendasuite.org/iip/yuba/agendaitem/details/8523" and passed["last_action"] == "Approved"
    assert (items.loc["8524", "action_on"], items.loc["8524", "noes"]) == ("item", 1)
    assert items.loc["471/2026", "votes_read"] == False and items.loc["8530", "number"] == "2026-75"  # noqa: E712
    members = tables["members"].set_index("name")
    assert sorted(members.index) == sorted(spelled.values()) and members["serving"].all() and (members["votes"] == 4).all()
    assert (members.loc["Seth Fuhrer", "role"], members.loc["Jon Messick", "role"], members.loc["Renick House", "role"]) == ("Chair", "Vice Chair", "")
    assert members["district"].isna().all() and str(members["district"].dtype) == "Int64"
    assert not yuba.members_table(votes, meetings, now="2027-06-01")["serving"].any()  # no vote in the last 120 days
    assert len(yuba.members_table(votes[votes["date"] == "2026-09-22"], meetings, now="2026-10-13")) == 0  # one day's votes make no member
    council_tables.write_tables(tables, tmp_path)
    assert sorted(path.name for path in tmp_path.glob("*.parquet")) == sorted(f"{name}.parquet" for name in council_tables.TABLES)
    card = yuba.card(tables)
    assert not re.search(r"\{[a-z_]+\}", card) and "chrissoria/yuba-county-board" in card


def test_one_name_is_kept_for_each_supervisor():
    forms = {"messick": yuba.Counter({"Jon Messick": 40, "John Messick": 1}), "messsick": yuba.Counter({"Jon Messsick": 2}),
             "house": yuba.Counter({"Renick House": 30})}
    assert yuba.one_spelling(forms) == {"messick": "Jon Messick", "messsick": "Jon Messick", "house": "Renick House"}


def test_the_foot_of_a_page_is_left_out_and_a_gap_is_not_seen_across_pages():
    lines = yuba.lines_of("       CONSENT AGENDA\n\n       473/2026  Title\n\n                    Page 1 of 2\n\f\n\n                 more of it(cid:13)\n")
    assert [(line["indent"], line["text"], line["gap"], line["top"]) for line in lines] == [
        (7, "CONSENT AGENDA", False, True), (7, "473/2026 Title", True, False), (17, "more of it", False, True)]  # and no "(cid:13)" for a line's end


def test_a_meetings_page_and_minutes_are_fetched_once_and_kept(tmp_path, monkeypatch):
    class Answer:
        def __init__(self, text="", content=b""):
            self.text, self.content = text, content

    asked = []
    monkeypatch.setattr(yuba, "fetch", lambda url: asked.append(url) or (Answer(content=b"%PDF-1.7") if "getfile" in url else Answer(text=PAGE)))
    monkeypatch.setattr(yuba, "pdf_text", lambda body: MINUTES.split("\f"))
    page = yuba.fetch_meeting(MEETING, tmp_path)
    assert asked == ["https://agendasuite.org/iip/yuba/meeting/details/355", "https://agendasuite.org/iip/yuba/file/getfile/40576"]
    assert page["text_of"].endswith("/40576") and yuba.whole("355", tmp_path)
    assert (tmp_path / "text" / "355.txt").read_text(encoding="utf-8").count("\f") == 1
    yuba.fetch_meeting(MEETING, tmp_path)
    assert len(asked) == 2  # what is kept is not asked for again
    # A fresh look at the page asks for the page, and for the minutes only if it now links another file.
    yuba.fetch_meeting(MEETING, tmp_path, fresh=True)
    assert asked[2:] == ["https://agendasuite.org/iip/yuba/meeting/details/355"]


def test_a_refusal_stops_the_host_being_asked_again(monkeypatch):
    class Answer:
        status_code, headers, content, text = 403, {"content-type": "text/html"}, b"<html>", "<html>"

    asked = []
    monkeypatch.setattr(yuba, "_refused", yuba.threading.Event())
    monkeypatch.setattr(yuba, "PAUSE", 0)
    monkeypatch.setattr(yuba._session, "get", lambda url, **said: asked.append(url) or Answer())
    with pytest.raises(yuba.Refused):
        yuba.fetch("https://example.test/a")
    with pytest.raises(yuba.Refused):
        yuba.fetch("https://example.test/b")
    assert asked == ["https://example.test/a"]
