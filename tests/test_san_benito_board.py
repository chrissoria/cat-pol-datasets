"""build_san_benito_board reads the San Benito County Board's votes out of minutes that print everyone's name under
every motion: a motion whole, against the Board the head of the minutes prints, or not at all."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import build_san_benito_board as sb
import council_tables

BOARD = ["Dom Zanger", "Kollin Kosmicki", "Mindy Sotelo", "Angela Curro", "Bea Gonzales"]
MEETING = {"meeting_id": "606", "date": "2023-08-08", "minutes_url": "https://cosb.granicus.com/services/minutes/reports/x/attachment"}

# Minutes as the reader keeps them: the text of each page as the PDF has it, a form feed between two pages. The head
# is the Board set out in columns, which the text runs together; pieces are from the minutes of 8 August 2023.
MINUTES = """SAN BENITO COUNTY
BOARD OF SUPERVISORS
Dom Zanger Kollin Kosmicki Mindy Sotelo A ngela Curro Bea Gonzales
District No. 1 District No. 2 District No. 3 District No. 4 D istrict No. 5
Chair Vice-Chair
Board of Supervisors Chambers 481 Fourth Street, Hollister, CA 95023
BOARD OF SUPERVISORS - REGULAR MEETING MINUTES
AUGUST 8, 2023
9:00 AM
C ALL TO ORDER
The meeting was called to order at 9:02 AM by Chair Mindy Sotelo. Those present were Supervisors
Angela Curro, Dom Zanger, and Kollin Kosmicki. Supervisor Bea Gonzales
was absent due to an illness.
a. Pledge of Allegiance
The Pledge of Allegiance was led by Supervisor Angela Curro District #4.
b. Acknowledge Certificate of Posting
Moved by Angela Curro; seconded by Kollin Kosmicki to acknowledge Certificate of
Posting. Motion : 4 - 0 - 0
Voting For: Dom Zanger, Kollin Kosmicki, Mindy Sotelo, Angela Curro
Voting Against: None
Voting Abstain: None
Absent: Bea Gonzales
c. NOTICE OF TEMPORARY PROCEDURES FOR BOARD OF SUPERVISOR MEETING
Members of the public may participate remotely:
a. If joining through web-browser, launch the address.
b. Select "JOIN A MEETING"
c. The participant will be prompted to enter the Meeting ID.
d. The participant can launch audio.
d. Presentations and Recognitions
Supervisor Sotelo presented the proclamation.
FUTURE AGENDA ITEMS
e. Public Comment
There were two public comments regarding items #1.4, 1.6, and
1.20, and Barbara Thompson regarding item #1.8.
1. CONSENT AGENDA
These matters shall be considered as a whole and without discussion.
Supervisor Kosmicki pulled item #1.2.
Moved by Kollin Kosmicki; seconded by Angela Curro to approve Consent Agenda except for
item #1.2.
Motion : 4 - 0 - 0
Voting For: Dom Zanger, Kollin Kosmicki, Mindy Sotelo, Angela Curro
\fVoting Against: None
Voting Abstain: None
Absent: Bea Gonzales
1.1 BEHAVIORAL HEALTH DEPARTMENT - R. ESPINOSA
Adopt Resolution authorizing the County Auditor to pay invoices from FY22-23.
(4/5 vote required) SBC FILE NUMBER: 810
RESOLUTION NO: 2023-97, 2023-98
1.2 RESOURCE MANAGEMENT AGENCY- A. PRADO, PLANNING AND BUILDING
DIRECTOR
Approve contract with Kimley-Horn for work on the San Benito Ag Center Environmental
Impact Report, in an amount not to exceed $257,668.00.
SBC FILE NUMBER: 790
This item was pulled by Supervisor Kosmicki for transparency.
Moved by Angela Curro; seconded by Dom Zanger to approve contract per
staff recommendation.
Motion : 3 - 1 - 0
Voting For: Dom Zanger, Mindy Sotelo, Angela Curro
Voting Against: Kollin Kosmicki
Voting Abstain: None
Absent: Bea Gonzales
1.3
CLERK OF THE BOARD - V. DELGADO
1. Approve the action minutes of the July 25, 2023 Regular Meeting; and
2. Authorize the Chair to sign.
SBC FILE NUMBER: 156
2. REGULAR AGENDA
2.1 COUNTY ADMINISTRATION OFFICE - R. ESPINOSA
Approve reallocation of funds. SBC FILE NUMBER: 119
Moved by Angela Curro; seconded by Bea Gonzales to approve reallocation per
staff recommendation.
Motion : 3 - 0 - 2
Voting For: Mindy Sotelo, Angela Curro, Bea Gonzales
Voting Against: Dom Zanger, Kollin Kosmicki
Voting Abstain: None
2.2 COUNTY COUNSEL- D. PRENTICE
Receive a report. SBC FILE NUMBER: 160
Supervisor Kosmicki made a motion and it died for lack of a second.
Moved by Dom Zanger; seconded by Angela Curro to continue the item.
The motion was withdrawn after discussion.
There was one public comment.
ADJOURNMENT
Moved by Kollin Kosmicki; seconded by Angela Curro to adjourn meeting at 1:42 PM.
Motion : 4 - 0 - 0
Voting For: Dom Zanger, Kollin Kosmicki, Mindy Sotelo, Angela
Curro
Voting Against: None
Voting Abstain: None
Absent: Bea Gonzales
"""


def motion(cast, count=None):
    return {"cast": cast, "count": count, "broken": ""}


def read(text=MINUTES, known=()):
    agenda, votes, facts = sb.read_meeting(MEETING, sb.scan(text, known), pages=text.count("\f") + 1)
    return {row["item_id"]: row for row in agenda}, votes, facts


def test_the_listing_gives_the_boards_meetings_once_each_with_their_documents():
    page = """<table><tr class="listingRow"><td class="listItem" headers="Name" scope="row">Board of Supervisors</td>
      <td class="listItem" headers="Date"> Oct&nbsp;27,&nbsp;2026 - 09:00&nbsp;AM </td>
      <td class="listItem"><a href="//cosb.granicus.com/AgendaViewer.php?view_id=1&event_id=664">Agenda</a></td></tr>
    <tr class="listingRow"><td class="listItem" headers="Name" id="Board-of-Supervisors" scope="row"> Board of Supervisors </td>
      <td class="listItem" headers="Date Board-of-Supervisors"> Sep&nbsp; 1,&nbsp;2026 - 09:00&nbsp;AM </td>
      <td class="listItem"><a href="//cosb.granicus.com/AgendaViewer.php?view_id=1&clip_id=1184" target="_blank">Agenda</a></td>
      <td class="listItem"><a href="https://cosb.granicus.com/services/minutes/reports/281ba064/attachment" target="_blank">Minutes</a></td>
      <td class="listItem"><a href="javascript:void(0);" onClick="window.open('//cosb.granicus.com/MediaPlayer.php?view_id=1&clip_id=1184')"> Video </a></td>
      <td class="listItem" headers="AgendaPacketLink"><a href="https://d3n9y02raazwpg.cloudfront.net/cosb/8f46.pdf">Agenda Packet</a></td></tr>
    <tr class="listingRow"><td class="listItem" headers="Name" scope="row"> Board of Supervisors </td>
      <td class="listItem" headers="Date"> Sep&nbsp; 1,&nbsp;2026 - 09:00&nbsp;AM </td>
      <td class="listItem"><a href="//cosb.granicus.com/AgendaViewer.php?view_id=1&clip_id=1184">Agenda</a></td></tr>
    <tr class="listingRow"><td class="listItem" headers="Name" scope="row"> Board of Supervisors - Special Meeting </td>
      <td class="listItem" headers="Date"> Sep&nbsp; 9,&nbsp;2025 - 05:30&nbsp;PM </td>
      <td class="listItem"><a href="//cosb.granicus.com/MinutesViewer.php?view_id=1&clip_id=1033&doc_id=3650238b">Minutes - Amended</a></td></tr>
    <tr class="listingRow"><td class="listItem" headers="Name" scope="row"> Planning Commission - Regular Meeting </td>
      <td class="listItem" headers="Date"> Aug&nbsp;19,&nbsp;2026 - 06:00&nbsp;PM </td>
      <td class="listItem"><a href="//cosb.granicus.com/MinutesViewer.php?view_id=1&clip_id=1175&doc_id=77">Minutes</a></td></tr></table>"""
    meetings = sb.meetings_table(sb.rows_of(page)).set_index("meeting_id")
    assert list(meetings.index) == ["1033", "1184"]  # a meeting to come, a commission's and a row printed twice are left out
    newest, amended = meetings.loc["1184"], meetings.loc["1033"]
    assert (newest["date"], newest["time"], newest["body"]) == ("2026-09-01", "9:00 AM", "Board of Supervisors")
    assert newest["minutes_url"] == "https://cosb.granicus.com/services/minutes/reports/281ba064/attachment"
    assert newest["agenda_url"] == "https://cosb.granicus.com/AgendaViewer.php?view_id=1&clip_id=1184"
    assert newest["video_url"] == "https://cosb.granicus.com/MediaPlayer.php?view_id=1&clip_id=1184"
    assert (amended["time"], amended["name"], amended["note"]) == ("5:30 PM", "Board of Supervisors - Special Meeting", "Minutes - Amended")
    assert amended["minutes_url"].startswith("https://cosb.granicus.com/MinutesViewer.php?view_id=1&clip_id=1033") and amended["video_url"] == ""
    assert list(meetings.columns)[:len(council_tables.COLUMNS["meetings"]) - 1] == council_tables.COLUMNS["meetings"][1:]


def test_the_board_is_read_from_the_head_as_known_names_end_to_end():
    districts = "District No. 1 District No. 2 District No. 3 District No. 4 D istrict No. 5"
    assert sb.board_of(["Dom Zanger Kollin Kosmicki M indy Sotelo A ngela Curro Bea Gonzales", districts], BOARD) == list(zip(range(1, 6), BOARD))
    # A name the row has only half of, with the other half on a line of its own, is that name.
    known = BOARD + ["Peter Hernandez", "Bob Tiffany", "Betsy Dirks", "Ignacio Velazquez"]
    head = ["SAN BENITO COUNTY", "Betsy Dirks Kollin Kosmicki Peter Bob Tiffany Bea Gonzales",
            "District No. 1 District No. 2 Hernandez District No. 4 D istrict No. 5", "Vice-Chair District No. 3"]
    assert [name for _, name in sb.board_of(head, known)] == ["Betsy Dirks", "Kollin Kosmicki", "Peter Hernandez", "Bob Tiffany", "Bea Gonzales"]
    head = ["Ignacio", "Dom Zanger Kollin Kosmicki Mindy Sotelo Angela Curro Velazquez", districts.replace("D istrict", "District")]
    assert sb.board_of(head, known)[-1] == (5, "Ignacio Velazquez")
    # The head of 2026 gives a district to a line, with the next column's words after the name, and a seat as vacant.
    head = ["BOARD MEMBERS: COUNTY EXECUTIVE OFFICER:", "DISTRICT 1 - Dom Zanger", "DISTRICT 2 - Kollin Kosmicki Gregory Priamos",
            "DISTRICT 3 - Mindy Sotelo Minutes", "DISTRICT 4 - Angela Curro Board of Supervisors Vanessa Delgado", "D ISTRICT 5 - Vacant"]
    assert sb.board_of(head, known) == [(1, "Dom Zanger"), (2, "Kollin Kosmicki"), (3, "Mindy Sotelo"), (4, "Angela Curro"), (5, sb.VACANT)]
    # Nothing is made of a head that has a word no vote prints as a name, a name twice, or more names than districts.
    assert sb.board_of(["Margie Barrios Anthony Botelho Robert Rivas Jerry Muenzer Jaime De La", districts], known) == []
    assert sb.board_of(["Dom Zanger Dom Zanger Mindy Sotelo Angela Curro Bea Gonzales", districts], known) == []
    assert sb.board_of(["Dom Zanger Kollin Kosmicki Mindy Sotelo Angela Curro", districts], known) == []
    # The form of a name printed most often is the one kept.
    assert sb.spelled(["Angela Curro"] * 5 + ["A ngela Curro", "Curro"]) == {"angelacurro": "Angela Curro"}


def test_a_printed_name_is_matched_to_the_board_by_its_letters_or_by_the_one_part_only_one_has():
    assert sb.who("A ngela Curro", BOARD) == "Angela Curro"
    assert sb.who("Sotelo", BOARD) == "Mindy Sotelo" and sb.who("Bea", BOARD) == "Bea Gonzales"
    assert sb.who("Supervisor Kosmicki", BOARD) == "Kollin Kosmicki"
    assert sb.who("Ksomicki", BOARD) is None and sb.who("Richard Way", BOARD) is None
    assert sb.who("Zanger", BOARD + ["Amy Zanger"]) is None  # two have it
    assert sb.names_in("Dom Zanger, Kollin Kosmicki, and Mindy Sotelo") == ["Dom Zanger", "Kollin Kosmicki", "Mindy Sotelo"]
    assert sb.names_in("None") == [] and sb.names_in("") == []


def test_a_motion_is_read_only_if_its_names_are_exactly_the_board_and_agree_with_the_count():
    ayes = ("AYE", ["Dom Zanger", "Kollin Kosmicki", "Mindy Sotelo", "Angela Curro"])
    cast, problem = sb.decide(motion([ayes, ("NO", []), ("ABSTAIN", []), ("ABSENT", ["Bea Gonzales"])], (4, 0, 0)), BOARD)
    assert problem == "" and dict(cast) == {**{name: "AYE" for name in BOARD[:4]}, "Bea Gonzales": "ABSENT"}
    # A supervisor the motion does not name is not put down as absent.
    assert sb.decide(motion([ayes, ("NO", []), ("ABSTAIN", [])], (4, 0, 0)), BOARD) == (None, "no vote printed for: Bea Gonzales")
    assert sb.decide(motion([ayes, ("NO", []), ("ABSTAIN", [])], (4, 0, 0)), BOARD[:4])[1] == ""  # the fifth seat vacant
    twice = motion([("AYE", BOARD), ("NO", []), ("ABSTAIN", []), ("ABSENT", ["Dom Zanger"])], (4, 0, 0))
    assert sb.decide(twice, BOARD) == (None, "named twice: Dom Zanger")
    joint = motion([("AYE", BOARD + ["Richard Way"]), ("NO", []), ("ABSTAIN", [])], (5, 0, 0))
    assert sb.decide(joint, BOARD) == (None, "not on the Board: Richard Way")
    split = motion([("AYE", BOARD[2:]), ("NO", BOARD[:2]), ("ABSTAIN", [])], (3, 0, 2))
    assert sb.decide(split, BOARD) == (None, "the count says 3 - 0 - 2 and 3 - 2 - 0 are named")
    assert sb.decide(motion([("AYE", BOARD[2:]), ("NO", BOARD[:2])], (3, 2, None)), BOARD)[1] == ""  # "Motion: 3-2"
    assert sb.decide(motion([("AYE", []), ("NO", []), ("ABSTAIN", [])], (5, 0, 0)), BOARD) == (None, "no names under the motion")
    assert sb.decide(motion([ayes], (4, 0, 0)), []) == (None, "the Board at the head of the minutes could not be read")
    # The minutes typed by hand give surnames, and no count.
    cast, problem = sb.decide(motion([("AYE", ["Sotelo", "Curro", "Zanger", "Gonzales"]), ("NO", ["Kosmicki"]), ("ABSTAIN", []), ("ABSENT", [])]), BOARD)
    assert problem == "" and dict(cast)["Kollin Kosmicki"] == "NO"
    assert sb.decide(motion([("AYE", ["Sotelo", "Curro", "Zanger Gonzales"]), ("NO", ["Kosmicki"])]), BOARD)[1] == "not on the Board: Zanger Gonzales"


def test_minutes_are_read_into_the_agendas_parts_its_items_and_the_motions_under_them():
    agenda, votes, facts = read()
    assert json.loads(facts["roll"]) == [{"name": name, "district": district} for district, name in enumerate(BOARD, 1)]
    assert json.loads(facts["chair"]) == {"name": "Mindy Sotelo", "role": "Chair"} and facts["seats"] == 5
    assert list(agenda) == ["606-s1", "606-a", "606-b", "606-c", "606-d", "606-e", "606-s2", "606-1.1", "606-1.2", "606-1.3", "606-s3",
                            "606-2.1", "606-2.2", "606-s4"]
    # A list set inside an item starts again at a and is not the agenda's; a line that begins "1.20," is not an item.
    assert agenda["606-c"]["title"].startswith("NOTICE OF TEMPORARY") and "d. The participant can launch audio." in agenda["606-c"]["description"]
    assert agenda["606-d"]["title"] == "Presentations and Recognitions" and "1.20, and Barbara" in agenda["606-e"]["description"]
    call, posting = agenda["606-s1"], agenda["606-b"]
    assert (call["title"], call["heading"], call["matter_id"]) == ("CALL TO ORDER", True, "")
    # A count at the end of the motion's last line is the count; the supervisor away is ABSENT because the motion says so.
    assert posting["action"] == "Moved by Angela Curro; seconded by Kollin Kosmicki to acknowledge Certificate of Posting."
    assert (posting["mover"], posting["seconder"], posting["count"], posting["votes_read"]) == ("Angela Curro", "Kollin Kosmicki", "4 - 0 - 0", True)
    assert (posting["ayes"], posting["noes"], posting["not_voting"], posting["section"], posting["section_id"]) == (4, 0, 1, "CALL TO ORDER", "606-s1")
    cast = {row["member"]: row["vote"] for row in votes if row["item_id"] == "606-b"}
    assert cast == {**{name: "AYE" for name in BOARD[:4]}, "Bea Gonzales": "ABSENT"}
    assert {row["established"] for row in votes} == {"named"} and {row["motion"] for row in votes} == {1}
    # A list of names that runs over a page or a line is one list.
    assert agenda["606-s2"]["votes_read"] is True and agenda["606-s4"]["votes_read"] is True
    assert sorted(row["member"] for row in votes if row["item_id"] == "606-s4" and row["vote"] == "AYE") == sorted(BOARD[:4])
    assert agenda["606-s4"]["heading"] is False and agenda["606-s4"]["matter_id"] == "606-s4"  # the adjournment is an item
    assert facts["motions"] == 6 and facts["motions_read"] == 4


def test_a_consent_item_is_voted_on_with_the_agenda_unless_the_motion_leaves_it_out():
    agenda, votes, _ = read()
    consent, first, pulled, third = (agenda[item] for item in ("606-s2", "606-1.1", "606-1.2", "606-1.3"))
    assert (consent["heading"], consent["matter_id"], consent["motions"], consent["ayes"]) == (True, "", 1, 4)
    assert sb.left_out(consent["action"]) == ["1.2"]
    assert sb.left_out("Moved by A; seconded by B to approve Consent Agenda except for items #1.4, 1.6, and 1.12.") == ["1.4", "1.6", "1.12"]
    assert (first["voted_with"], first["motions"], first["votes_read"]) == ("606-s2", 0, None)
    assert (first["department"], first["file_number"], first["number"]) == ("BEHAVIORAL HEALTH DEPARTMENT - R. ESPINOSA", "810", "Resolution 2023-97, 2023-98")
    assert first["title"] == "Adopt Resolution authorizing the County Auditor to pay invoices from FY22-23. (4/5 vote required)"
    assert first["doc_type"] == "resolution" and first["section"] == "CONSENT AGENDA"
    assert (pulled["voted_with"], pulled["noes"], pulled["count"]) == ("606-1.2", 1, "3 - 1 - 0")
    assert pulled["department"] == "RESOURCE MANAGEMENT AGENCY- A. PRADO, PLANNING AND BUILDING DIRECTOR"
    assert pulled["title"].startswith("Approve contract with Kimley-Horn") and pulled["title"].endswith("$257,668.00.")
    assert pulled["description"] == "This item was pulled by Supervisor Kosmicki for transparency."
    assert {row["member"] for row in votes if row["item_id"] == "606-1.2" and row["vote"] == "NO"} == {"Kollin Kosmicki"}
    # An item whose number stands on a line of its own has its department on the next.
    assert (third["department"], third["file_number"], third["voted_with"]) == ("CLERK OF THE BOARD - V. DELGADO", "156", "606-s2")
    assert third["title"].startswith("1. Approve the action minutes") and third["title"].endswith("2. Authorize the Chair to sign.")


def test_a_motion_that_does_not_add_up_or_has_nothing_under_it_is_kept_and_not_read():
    agenda, votes, _ = read()
    wrong, none = agenda["606-2.1"], agenda["606-2.2"]
    assert (wrong["votes_read"], wrong["problem"], wrong["ayes"], wrong["noes"]) == (False, "the count says 3 - 0 - 2 and 3 - 2 - 0 are named", 0, 0)
    assert not [row for row in votes if row["item_id"] in ("606-2.1", "606-2.2")]
    # A motion with no count under it ends with its sentence, and what follows is the minutes' own account.
    assert (none["motions"], none["votes_read"], none["problem"]) == (1, False, "no names under the motion")
    assert none["action"] == "Moved by Dom Zanger; seconded by Angela Curro to continue the item."
    assert none["description"].endswith("The motion was withdrawn after discussion.\nThere was one public comment.")
    assert json.loads(none["motion_log"])[0]["read"] is False
    # With no Board at the head, nothing in the minutes is read.
    agenda, votes, facts = read(MINUTES.replace("Dom Zanger Kollin Kosmicki Mindy Sotelo A ngela Curro Bea Gonzales\n", "The Board\n"))
    assert votes == [] and facts["seats"] == 0 and agenda["606-b"]["problem"] == "the Board at the head of the minutes could not be read"


def test_a_department_in_capitals_under_a_vote_is_not_taken_for_a_name():
    # Minutes kept as a page of HTML print a count of two numbers, no "Voting Abstain:", and the next item's department after.
    block = ("2. REGULAR AGENDA\nMoved by Bea Gonzales; seconded by Dom Zanger to\napprove proclamation\n.\nMotion : 4- 1\n"
             "Voting For: Dom Zanger, Kollin Kosmicki, Mindy Sotelo, Bea Gonzales\nVoting Against: Angela Curro\nBOARD OF SUPERVISORS\n"
             "Approve proclamation declaring National Health Center Week.\n")
    agenda, votes, _ = read(MINUTES.replace("2. REGULAR AGENDA\n", block))
    part = agenda["606-s3"]
    assert (part["motions_read"], part["ayes"], part["noes"], part["count"]) == (1, 4, 1, "4- 1")
    assert part["action"] == "Moved by Bea Gonzales; seconded by Dom Zanger to approve proclamation." and "BOARD OF SUPERVISORS" in part["description"]
    assert sb.html_text("<html><div>1.</div><div><b>CONSENT&nbsp;AGENDA</b></div><p>Moved by A; seconded by B to <span>adjourn</span></p><style>p {}</style></html>") \
        == "1. CONSENT AGENDA\nMoved by A; seconded by B to adjourn"


def test_the_minutes_typed_by_hand_are_read_by_their_own_words():
    text = """SAN BENITO COUNTY BOARD OF SUPERVISORS
Dom Zanger Kollin Kosmicki Mindy Sotelo Angela Curro Bea Gonzales
District No. 1 District No. 2 District No. 3 District No. 4 District No. 5
BUDGET HEARING MINUTES
CALL TO ORDER:
ACKNOWLEDGE CERTIFICATE OF POSTING:
Motion to acknowledge the Certificate of Posting made by Supervisor Gonzales and seconded by Supervisor
Kosmicki:
Ayes: Sotelo, Curro, Zanger, Kosmicki, Gonzales
Noes: None
Abstain: None
Absent: None
Motion: Approved a temporary due pass on all the items, made by Supervisor Curro
and seconded by Supervisor Gonzales:
Ayes: Sotelo, Curro, Zanger Gonzales
Noes: Kosmicki
Abstain: None
Absent: None
"""
    agenda, votes, facts = read(text, known=BOARD * 3)
    line = agenda["606-s1"]
    assert (line["motions"], line["motions_read"], line["problem"]) == (2, 1, "not on the Board: Zanger Gonzales")
    log = json.loads(line["motion_log"])
    assert (log[0]["mover"], log[0]["seconder"], log[0]["count"]) == ("Gonzales", "Kosmicki", "")
    assert sorted(row["member"] for row in votes) == sorted(BOARD) and {row["vote"] for row in votes} == {"AYE"}


def test_the_five_tables_come_out_in_the_one_shape(tmp_path):
    agenda_rows, vote_rows, facts = sb.read_meeting(MEETING, sb.scan(MINUTES), pages=2)
    agenda, votes = sb.typed(pd.DataFrame(agenda_rows, columns=sb.AGENDA_COLUMNS), pd.DataFrame(vote_rows, columns=sb.VOTE_COLUMNS))
    meetings = sb.meetings_table([{"meeting_id": "606", "name": "Board of Supervisors", "date": "2023-08-08", "time": "9:00 AM", "agenda": "",
                                   "minutes": MEETING["minutes_url"], "note": "", "video": True}])
    for name, value in facts.items():
        meetings[name] = [value]
    tables = council_tables.standard({"items": sb.items_table(agenda, meetings), "meetings": meetings, "agenda_items": agenda,
                                      "votes": votes, "members": sb.members_table(votes, meetings)})
    for name in council_tables.TABLES:
        assert list(tables[name].columns)[:len(council_tables.COLUMNS[name])] == council_tables.COLUMNS[name]
    items = tables["items"].set_index("matter_id")
    assert "606-s1" not in items.index and "606-s2" not in items.index and "606-s4" in items.index  # headings are not items
    assert (items.loc["606-1.1", "action_on"], items.loc["606-1.1", "ayes"], items.loc["606-1.1", "mover"]) == ("section", 4, "Kollin Kosmicki")
    assert (items.loc["606-1.2", "action_on"], items.loc["606-1.2", "noes"], items.loc["606-1.2", "subject"][:19]) == ("item", 1, "RESOURCE MANAGEMENT")
    assert items.loc["606-2.1", "votes_read"] == False and pd.isna(items.loc["606-a", "votes_read"])  # noqa: E712
    assert (items["passed_date"] == "").all() and (items["result"] == "").all() and items.loc["606-1.1", "url"] == MEETING["minutes_url"]
    # One day's votes do not make a member; two do, with the district the head gives.
    assert len(tables["members"]) == 0
    later = votes.assign(date="2023-08-22", meeting_id="607")
    members = sb.members_table(pd.concat([votes, later]), meetings).set_index("name")
    assert list(members.index) == sorted(BOARD) and members.loc["Bea Gonzales", "district"] == 5 and str(members["district"].dtype) == "Int64"
    assert not members["serving"].any() and (members["role"] == "").all() and (members["votes"] == 8).all()
    council_tables.write_tables(tables, tmp_path)
    assert sorted(path.name for path in tmp_path.glob("*.parquet")) == sorted(f"{name}.parquet" for name in council_tables.TABLES)
    card = sb.card(tables)
    assert not re.search(r"\{[a-z_]+\}", card) and "chrissoria/san-benito-county-board" in card


class Answer:
    def __init__(self, status=200, headers=None, content=b"%PDF-1.7"):
        self.status_code, self.headers, self.content, self.text = status, headers or {"content-type": "application/pdf"}, content, ""

    def raise_for_status(self):
        pass


def test_a_redirect_is_followed_by_hand_and_a_login_is_not_asked_for(monkeypatch):
    asked = []
    answers = {"https://cosb.granicus.com/a": Answer(302, {"location": "https://files.example.test/a.pdf"}),
               "https://files.example.test/a.pdf": Answer(),
               "https://cosb.granicus.com/b": Answer(302, {"location": "/account/login?ReturnUrl=b"})}
    monkeypatch.setattr(sb, "PAUSE", 0)
    monkeypatch.setattr(sb, "_refused", set())
    monkeypatch.setattr(sb._session, "get", lambda url, **said: asked.append((url, said["allow_redirects"])) or answers[url])
    assert sb.fetch("https://cosb.granicus.com/a").content == b"%PDF-1.7"
    assert asked == [("https://cosb.granicus.com/a", False), ("https://files.example.test/a.pdf", False)]
    with pytest.raises(sb.NotPDF):
        sb.fetch("https://cosb.granicus.com/b")
    assert len(asked) == 3  # the login page itself is never asked for


def test_a_refusal_stops_the_host_being_asked_again(monkeypatch):
    asked = []
    monkeypatch.setattr(sb, "PAUSE", 0)
    monkeypatch.setattr(sb, "_refused", set())
    monkeypatch.setattr(sb._session, "get", lambda url, **said: asked.append(url) or Answer(403, {"content-type": "text/html"}, b"<html>"))
    with pytest.raises(sb.Refused):
        sb.fetch("https://cosb.granicus.com/a")
    with pytest.raises(sb.Refused):
        sb.fetch("https://cosb.granicus.com/b")
    assert asked == ["https://cosb.granicus.com/a"]


def test_text_kept_here_is_not_fetched_again(tmp_path, monkeypatch):
    (tmp_path / "text").mkdir()
    (tmp_path / "text" / "606.txt").write_text("page one\n\fpage two", encoding="utf-8")
    monkeypatch.setattr(sb, "fetch", lambda url: pytest.fail("asked the host"))
    assert sb.text_of(MEETING, tmp_path) == "page one\n\fpage two"
    assert sb.lines_of("  a  line \n\n\fthe  next\n") == ["a line", "the next"]
