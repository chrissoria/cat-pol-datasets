"""build_calaveras_board reads the Calaveras County Board's votes out of the minutes of each meeting, which print a vote
three ways over the years: a motion whole or not at all. Nothing here asks anything of the portal."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import build_calaveras_board as cal
import build_iqm2_board as iqm2
import council_tables

BOARD_2014 = ["Debbie Ponte", "Cliff Edson", "Merita Callaway", "Chris Wright", "Darren Spellman"]
BOARD_2001 = ["Lucy Thein", "Terri Bailey", "Paul Stein", "Merita Callaway", "Thomas Tryon"]

# The portal's own minutes, as the reader keeps their text: a tab where the page sets two columns apart, a line set in
# by a space for every six points, a form feed between pages, the portal's stamp and running head on each page.
PORTAL = """                    CALAVERAS COUNTY BOARD OF SUPERVISORS
GARY TOFANELLI\tTERESA HITCHCOCK
DISTRICT 1\tCOUNTY EXECUTIVE OFFICER
AUTUMN ANDAHL\tSARAH EDWARDS
DISTRICT 2\tCOUNTY COUNSEL
MARTIN HUBERTY\tREBECCA TURNER
DISTRICT 3\tCLERK OF THE BOARD
AMANDA FOLENDORF – VICE CHAIR
DISTRICT 4\t891 MOUNTAIN RANCH ROAD
BENJAMIN STOPPER - CHAIR\tSAN ANDREAS, CA 95249
DISTRICT 5\tTEL: (209)754-6370
                                       May 26, 2026
                                REGULAR MEETING MINUTES
8:01 AM: Call to Order
 The meeting was called to order at 8:00 AM by Chair Benjamin Stopper
  Attendee Name\tTitle\tStatus Arrived
  Amanda Folendorf Vice-Chair\tPresent
  Benjamin Stopper Chair\tPresent
  Autumn Andahl\tDistrict 2 Supervisor\tPresent
  Gary Tofanelli\tDistrict 1 Supervisor\tLate\t8:15 AM
  Martin Huberty\tDistrict 3 Supervisor\tPresent
12:48 PM: Closed Session Agenda
The Clerk reported out for the May 12, 2026 Closed session. The Board
accepted a settlement by unanimous vote of Supervisors Folendorf, Stopper, Andahl, Tofanelli and Huberty.
Closed Session Agenda for May 26, 2026:
1. Pursuant to Govt. Code § 54957(b), consider the disability retirement of a safety employee.
      Board action: no reportable action taken.
Recognition and Acknowledgments
3. Proclamation - Sheriff (ID # 9167) Adopt a Proclamation recognizing Robyn Berwick for over
      twenty years of outstanding volunteer service.
      Supervisor Huberty read into record a proclamation.
      Public Comment:
      1. Lt. Poortinga recognized Ms. Berwick for her many years of dedicated service.
       RESULT: ADOPTED [UNANIMOUS]
       MOVER:\tBenjamin Stopper, Chair
       SECONDER: Gary Tofanelli, District 1 Supervisor
       AYES:\tFolendorf, Stopper, Andahl, Tofanelli, Huberty
9:55 AM: Consent Agenda
       RESULT: ADOPTED [4 TO 0]
       MOVER:\tAmanda Folendorf, Vice-Chair
       SECONDER: Autumn Andahl, District 2 Supervisor
       AYES:\tAmanda Folendorf, Benjamin Stopper, Autumn Andahl, Gary
       Tofanelli
       ABSTAIN: Martin Huberty
4. Agreement - Library (ID # 9185) Authorize the Board Chair to execute Amendment 01 to the
      2021 Master Agreement for Library software services.
Generated 7/30/2026 2:20 PM
\fRegular Meeting\tTuesday, May 26, 2026\t8:00 AM
5. Resolution - Sheriff 20260526r025 Adopt a Resolution authorizing the Sheriff to accept a grant.
6. Item 9190 was moved to Items Pulled from Consent Agenda
                                   2 | Page
Items Pulled from Consent Agenda
      Agreement - Behavioral Health (ID # 9190) Authorize the Director to execute Amendment 03.
      Chair Stopper recused himself from the board chambers at 10:54 AM.
       RESULT: APPROVED [3 TO 1]
       MOVER:\tGary Tofanelli, District 1 Supervisor
       SECONDER: Autumn Andahl, District 2 Supervisor
       AYES:\tAndahl, Tofanelli, Huberty
       NAYS:\tFolendorf
       RECUSED: Stopper
Regular Agenda
7. Action Item - Public Works (ID # 9188) Receive a presentation and provide direction.
       RESULT: TABLED [UNANIMOUS]
                     Next: 6/9/2026 8:00 AM
       MOVER:\tMartin Huberty, District 3 Supervisor
       SECONDER: Autumn Andahl, District 2 Supervisor
       AYES:\tFolendorf, Andahl, Tofanelli, Huberty, Garamendi
8. Informational Item - Planning (ID # 9163) Receive an update.
       RESULT: COMPLETED
The meeting was closed at 1:35 PM
9. Not an item
"""

# The minutes of 2000 to May 2013: a line under each motion.
MOVED = """MINUTES OF A REGULAR MEETING OF THE BOARD OF SUPERVISORS,
COUNTY OF CALAVERAS, STATE OF CALIFORNIA,
HELD ON MONDAY, JUNE 11, 2001
PRESENT: Lucy Thein, Chair; Terri Bailey, Vice-Chair; Merita
Callaway and Thomas Tryon, Supervisors; Spencer Batchelder, County
Counsel; and Mary Jane Giuffra, Supervising Board Clerk
ABSENT: Paul Stein, Supervisor/District III
Meeting recorded on Cassette 01-25, Side I only
10:00 a.m.: Chair Thein called the meeting to order.
C O N S E N T A G E N D A
Supervisor Callaway pulled Item #3. Motion was then made approving the balance of the Consent Agenda, as
submitted.
Moved: Callaway\tSecond: Tryon\tApproval: Unanimous
ABSENT: Stein
1. Minutes of May 29, 2001, as written
2. RESOLUTION\tA RESOLUTION RECOGNIZING EAGLE SCOUT BRADY P. DAVIS
NO. 01-156
(PAGE 1 of 8)
1
\f6/11/01 FINAL MINUTES
3. FISH & GAME/PURCHASING/AUDITOR (01-25, I, 131)
Supervisor Callaway questioned a request from the County Fish & Game Commission.
Motion was made approving the purchase of the Night Scope, as requested.
Moved: Callaway\tSecond: Bailey\tApproval: Unanimous
R E G U L A R A G E N D A
4. CODE COMPLIANCE/FINES (01-25, I, 1430)
Todd Barr, Code Compliance Dept., clarified the order:
1. The owners are to pay a fine.
Motion was made to uphold the findings and recommendations of the Administrative Hearing Board.
Moved: Bailey\tSecond: Callaway\tApproval: Majority NOES: Tryon
Supervisor Stein arrived at 11:05 a.m.
5. PUBLIC HEARING/PLANNING/ZONING (01-25, I, 2400)
Motion was made to adopt Zoning Amendment 01-07, with a Negative Declaration.
Moved: Tryon\tSecond: Bailey\tApproval: Unanimous
ORDINANCE\tAN ORDINANCE AMENDING TITLE 17 OF THE CALAVERAS COUNTY CODE
NO. 2657
6. ANIMAL CONTROL (01-25, I, 2500)
Motion made to waive reading and approve the introduction of an urgency Ordinance.
Moved: Callaway\tSecond: Thein\tApproval: Unanimous
ABSENT: Thein
7. ADMINISTRATION (01-25, I, 2600)
Motion made to approve the minutes of June 5.
Moved: Bailey\tSecond: Pont e\tApproved: Majority
Dissenting: Callaway
ABSTAIN: Tryon
ADJOURNMENT
There being no further business the meeting was adjourned.
1. From: State Dept. of Forestry re: Filing of Timber Harvest Plan
"""

# The minutes of May 2013 to September 2014: a sentence.
PROSE = """                               July 8, 2014
                          REGULAR MEETING MINUTES
PRESENT: Debbie Ponte, Chair; Cliff Edson, Vice-Chair; Me rita Callaway, Chris Wright and Darren Spellman,
     Supervisors; Megan Stedtfeld, Interim County Counsel; Lori Norton, County Administrative
     Officer and Diane Severud, Clerk.
  Digital Recorder 20140708 BOS
                        RECOGNITION AND ACKNOWLEDGMENTS
1. HEALTH & HUMAN SERVICES. Adopt Resolution 2014-094 recognizing Esther Tabor for over 20
     years of volunteer service. Motion by
     Supervisor Spellman, second by Supervisor Edson. Unanimously approved by Supervisors
     Edson, Wright, Callaway, Ponte and Spellman.
2. COUNTY COUNSEL. Adopt Resolution 2014-095 recognizing Janis J. Elliott. Motion by Supervisor Spellman, second by
     Supervisor Wright. Approved by Supervisors Edson, Wright, Ponte and Spellman.
     Supervisor Callaway voted no.
                               CONSENT AGENDA
  Item 4 was pulled by Bonnie Newman. Motion by Supervisor Wright, second by Supervisor
  Edson. Unanimously approved by Supervisors Edson, Wright, Callaway, Ponte and Spellman.
3. MINUTES of meeting held June 17, 2014.
4. SHERIFF. Adopt Ordinance 3031 repealing Ordinance No. 2942. A motion by Supervisor Ponte, a
     second by Supervisor Wright. 4-1 approved, Supervisor Wright voted no.
                               REGULAR AGENDA
5. ADMINISTRATION. Approve the Administrative Match Agreement. Supervisor Wright left the meeting at 1: 36 PM and returned at 1: 40 PM.
     Supervisor Spellman left the meeting at 1:55 PM. Motion by Supervisor Wright, second by Supervisor Callaway. 4-0 approved.
     Supervisor Spellman returned at 2:10 PM.
6. BUILDING. Adopt the fee ordinance. Motion by Supervisor Spellman, second by Supervisor Callaway to adopt the
     ordinance, as presented. 3-2, failed. Dissenting were Supervisors Ponte, Wright and Edson.
     Motion by Supervisor Wright, second by Supervisor Ponte to amend the ordinance. 5-0 approved.
7. BUDGET. Motion by Supervisor Callaway, second by Supervisor Edson. Supervisors Edson, Callaway and
     Ponte voted yes. Wright and Spellman voted no.
8. PLANNING. Motion by Supervisor Edson, second by Supervisor Ponte. Approved by Supervisors Edson, Callaway and Ponte.
9. ROADS. Supervisor Edson moved to rescind the resolution, seconded by Supervisors Spellman. Majority approval by
     Supervisors Edson, Spellman and Ponte. Supervisors Wright and Callaway voted no.
10. PARKS. On a motion by Supervisor Wright and a second by Supervisor Ponte, the Board directed staff to return.
ADJOURNMENT. There being no further business, the meeting was adjourned at 7:00 PM.
"""


def meeting(meeting_id="2778", date="2026-05-26"):
    return {"meeting_id": meeting_id, "date": date, "minutes_url": f"https://example.test/FileOpen.aspx?Type=12&ID={meeting_id}"}


def read(text, meeting_id="2778", date="2026-05-26", **said):
    agenda, votes, facts = cal.read_meeting(meeting(meeting_id, date), cal.scan(text, **{k: v for k, v in said.items() if k != "around"}),
                                            text.count("\f") + 1, said.get("about", ()), said.get("around", ()))
    return {row["item_id"]: row for row in agenda}, votes, facts


def cast_of(votes, item_id, motion=1):
    return {vote["member"]: (vote["vote"], vote["established"]) for vote in votes if vote["item_id"] == item_id and vote["motion"] == motion}


def motion(**said):
    return cal.a_motion(said.pop("how", "line"), **said)


# ---------------------------------------------------------------------------
# The calendar, and a document
# ---------------------------------------------------------------------------

def test_the_calendar_is_the_boards_own_meetings_with_their_minutes():
    rows = [{"meeting_id": "2778", "date": "2026-05-26", "time": "8:00 AM", "body": "Board of Supervisors", "location": "Chambers",
             "name": "Regular Meeting", "status": "Closed", "papers": {"agenda": "FileOpen.aspx?Type=14&ID=2037&Inline=True",
                                                                       "minutes": "FileOpen.aspx?Type=12&ID=2390&Inline=True"}},
            {"meeting_id": "2820", "date": "2026-06-23", "time": "8:00 AM", "body": "Board of Supervisors", "location": "Chambers",
             "name": "Regular Meeting", "status": "Scheduled", "papers": {}},
            {"meeting_id": "3001", "date": "2026-05-28", "time": "9:00 AM", "body": "Planning Commission", "location": "",
             "name": "Regular Meeting", "status": "Closed", "papers": {"minutes": "FileOpen.aspx?Type=12&ID=2391&Inline=True"}}]
    meetings = cal.board_meetings(rows)
    assert list(meetings["meeting_id"]) == ["2778", "2820"]  # another body's meeting is not the Board's
    assert list(meetings.columns) == cal.MEETING_COLUMNS
    first = meetings.iloc[0]
    assert first["minutes_url"] == "https://calaverascountyca.iqm2.com/Citizens/FileOpen.aspx?Type=12&ID=2390&Inline=True"
    assert (first["time"], first["body"], first["minutes"], first["motions"]) == ("8:00 AM", "Board of Supervisors", "", 0)
    assert meetings.iloc[1]["minutes_url"] == ""  # no minutes yet: nothing to read


class Answer:
    def __init__(self, content=b"", status=200, url="https://calaverascountyca.iqm2.com/Citizens/FileOpen.aspx?Type=12&ID=1"):
        self.content, self.status_code, self.url = content, status, url
        self.text = content.decode("latin-1")

    def raise_for_status(self):
        pass


class Session:
    def __init__(self, answer):
        self.answer, self.asked = answer, 0

    def get(self, url, timeout=0):
        self.asked += 1
        return self.answer


def test_a_document_is_a_pdf_and_anything_else_is_no_document_or_a_refusal(monkeypatch):
    url = "https://calaverascountyca.iqm2.com/Citizens/FileOpen.aspx?Type=12&ID=1&Inline=True"
    monkeypatch.setattr(iqm2, "REFUSED", {})
    monkeypatch.setattr(cal, "_session", Session(Answer(b"%PDF-1.5 the minutes")))
    assert cal.fetch_document(url).startswith(b"%PDF")
    # Minutes not yet published: the portal says so on its login page. That is no document, and no refusal.
    login = "https://calaverascountyca.iqm2.com/Citizens/Login.aspx?Message=This+file+has+not+been+published+for+viewing"
    monkeypatch.setattr(cal, "_session", Session(Answer(b"<html>MainLayout</html>", url=login)))
    with pytest.raises(cal.NoDocument):
        cal.fetch_document(url)
    assert not iqm2.REFUSED
    # The portal's viewer in place of the file: no document this time.
    viewer = Session(Answer(b"<html><div id='ContentPlaceholder1'>viewer</div></html>", url=url.replace("FileOpen", "FileView")))
    monkeypatch.setattr(cal, "_session", viewer)
    with pytest.raises(cal.NoDocument):
        cal.fetch_document(url)
    assert viewer.asked == 1 and not iqm2.REFUSED
    # A refusal is not tried again, and nothing more is asked of the host.
    refusing = Session(Answer(b"<html>Access denied</html>", status=403))
    monkeypatch.setattr(cal, "_session", refusing)
    with pytest.raises(iqm2.Refused):
        cal.fetch_document(url)
    with pytest.raises(iqm2.Refused):
        cal.fetch_document(url)
    assert refusing.asked == 1 and "calaverascountyca.iqm2.com" in iqm2.REFUSED


def test_the_pace_is_the_one_the_portals_robots_file_asks_for():
    assert cal.PAUSE == 60


def test_the_pages_own_lines_are_left_out_and_a_lines_place_is_kept():
    lines = cal.lines_of("   3. An item\n      set in\nGenerated 7/30/2026 2:20 PM\n\fRegular Meeting\tTuesday, May 26, 2026\t8:00 AM\n"
                         "                 2 | Pag e\n 3 | P a g e\n(PAGE 3 of 8)\n6/11/01 FINAL MINUTES\n20140708a 2014-\n7\nGARY TOFANELLI\tTERESA HITCHCOCK")
    assert [(line["indent"], line["text"]) for line in lines] == [(3, "3. An item"), (6, "set in"), (0, "GARY TOFANELLI TERESA HITCHCOCK")]
    assert lines[-1]["cells"] == ["GARY TOFANELLI", "TERESA HITCHCOCK"]


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

def test_a_name_in_a_vote_is_the_one_supervisor_on_the_roll_it_fits():
    roll = ["Russ Thomas", "Thomas Tryon", "Merita Callaway", "Michael C. Oliveira", "Gary Tofanelli"]
    assert cal.who("Thomas", roll) == "Russ Thomas"  # a family name, not Tryon's first name
    assert cal.who("Supervisor Tryon", roll) == "Thomas Tryon"
    assert cal.who("Michael Oliveira", roll) == "Michael C. Oliveira"
    assert cal.who("Me rita Callaway", roll) == "Merita Callaway"  # a scan's broken name
    assert cal.who("Calloway", roll) == "Merita Callaway" and cal.who("Tofaneli", roll) == "Gary Tofanelli"  # one letter out
    assert cal.who("Stein", roll) is None and cal.who("", roll) is None
    assert cal.who("Smith", ["Ann Smith", "Bob Smith"]) is None  # two it could be: neither


def test_a_supervisor_has_one_name_however_the_heads_print_it():
    names = cal.one_name({"Merita Callaway": 40, "Meri ta Callaway": 2, "Russell Thomas": 9, "Russ Thomas": 3, "Michael C. Oliveira": 20,
                          "Michael Oliveira": 6, "Thomas Tryon": 30, "Callaway": 1, "Gary Tofaneli": 1, "Gary Tofanelli": 25})
    assert names["Meri ta Callaway"] == names["Callaway"] == "Merita Callaway"
    assert names["Russ Thomas"] == "Russell Thomas" and names["Michael Oliveira"] == "Michael C. Oliveira"
    assert names["Gary Tofaneli"] == "Gary Tofanelli"
    assert names["Thomas Tryon"] == "Thomas Tryon"  # not Russell Thomas


# ---------------------------------------------------------------------------
# The head
# ---------------------------------------------------------------------------

def test_the_older_head_says_who_was_present_and_who_absent():
    head = cal.head_of(MOVED)
    assert head["format"] == cal.MOVED and head["from"] == "present line" and head["known"]
    assert [(member["name"], member["role"], member["status"]) for member in head["roll"]] == [
        ("Lucy Thein", "Chair", "Present"), ("Terri Bailey", "Vice-Chair", "Present"), ("Merita Callaway", "", "Present"),
        ("Thomas Tryon", "", "Present"), ("Paul Stein", "", "Absent")]
    assert head["roll"][-1]["district"] == 3  # "Supervisor/District III"
    assert not any("Batchelder" in member["name"] for member in head["roll"])  # the County's officers are not supervisors


def test_a_scans_broken_name_and_two_names_run_together_are_told_by_the_other_heads():
    alone = cal.head_of(PROSE)
    assert not alone["known"] and len(alone["roll"]) == 4  # "Me rita Callaway" is no name by itself
    known = {cal.key_of(name) for name in BOARD_2014 + ["Steve Wilensky", "Thomas Tryon"]}
    head = cal.head_of(PROSE, known)
    assert head["format"] == cal.PROSE and head["known"]
    assert sorted(cal.key_of(member["name"]) for member in head["roll"]) == sorted(cal.key_of(name) for name in BOARD_2014)
    names, whole = cal.said_names("Merita Callaway, Chair; Bill Claudino, Vice-Chair; Steve Wilensky Thomas Tryon and Victoria Erickson", known)
    assert whole and [member["name"] for member in names] == ["Merita Callaway", "Bill Claudino", "Steve Wilensky", "Thomas Tryon", "Victoria Erickson"]
    assert not cal.said_names("Merita Callaway, Chair; Steve Wilensky Thomas Tryon")[1]


def test_the_portals_head_has_a_table_of_who_attended_and_a_letterhead_that_is_not_the_roll():
    head = cal.head_of(PORTAL)
    assert head["format"] == cal.PORTAL and head["from"] == "attendee table" and head["known"]
    assert [(m["name"], m["role"], m["district"], m["status"], m["arrived"]) for m in head["roll"]] == [
        ("Amanda Folendorf", "Vice-Chair", 4, "Present", ""), ("Benjamin Stopper", "Chair", 5, "Present", ""),
        ("Autumn Andahl", "", 2, "Present", ""), ("Gary Tofanelli", "", 1, "Late", "8:15 AM"), ("Martin Huberty", "", 3, "Present", "")]
    assert [(m["name"], m["district"]) for m in head["letterhead"]] == [
        ("Gary Tofanelli", 1), ("Autumn Andahl", 2), ("Martin Huberty", 3), ("Amanda Folendorf", 4), ("Benjamin Stopper", 5)]
    # Minutes of 2014 and 2015 have a letterhead and no table. The letterhead is the Board of the day the document was
    # made, so it is no roll, and such minutes do not say who was present.
    bare = cal.head_of(PORTAL.replace("Attendee Name", "Those here"))
    assert bare["format"] == cal.PORTAL and bare["roll"] == [] and not bare["known"] and len(bare["letterhead"]) == 5


# ---------------------------------------------------------------------------
# A vote as each kind of minutes prints it
# ---------------------------------------------------------------------------

def test_the_portals_block_is_read_a_line_to_a_fact():
    lines = cal.lines_of("RESULT: ADOPTED AS AMENDED [3 TO 1]\nMOVER:\tGary Tofanelli, District 1 Supervisor\nSECONDER: Benjamin Stopper, Vice-Chair\n"
                         "AYES:\tBenjamin Stopper, Autumn Andahl, Gary\nTofanelli\nNAYS:\tAmanda Folendorf\nAWAY: Martin Huberty\n10. The next item")
    found, after = cal.block_of(lines, 0, ["Benjamin Stopper", "Autumn Andahl", "Gary Tofanelli", "Amanda Folendorf", "Martin Huberty"])
    assert (found["mover"], found["seconder"], found["tally"], found["unanimous"], found["result"]) == (
        "Gary Tofanelli", "Benjamin Stopper", (3, 1), False, "Pass")
    assert found["cast"] == [("Benjamin Stopper", "AYE"), ("Autumn Andahl", "AYE"), ("Gary Tofanelli", "AYE"),
                             ("Amanda Folendorf", "NO"), ("Martin Huberty", "AWAY")]
    assert lines[after]["text"] == "10. The next item"
    # What the clerk calls a result is kept; only a word that says the motion carried or failed is judged.
    assert cal.block_of(cal.lines_of("RESULT: TABLED [UNANIMOUS]\nMOVER: A B"), 0, [])[0]["result"] == ""
    assert cal.block_of(cal.lines_of("RESULT: FAILED [2 TO 3]\nMOVER: A B"), 0, [])[0]["result"] == "Fail"
    assert cal.block_of(cal.lines_of("RESULT: WITHDRAWN"), 0, [])[0]["cast"] == []


def test_the_line_under_a_motion_is_read_with_the_lines_that_follow_it():
    found = cal.line_of(cal._MOVED.match("Moved: Stein Second: Callaway Approval: Majority NOES: Tryon"), ["ABSTAIN: Thein, Bailey"])
    assert (found["mover"], found["seconder"], found["majority"], found["unanimous"], found["result"]) == ("Stein", "Callaway", True, False, "Pass")
    assert found["cast"] == [("Tryon", "NO"), ("Thein", "ABSTAIN"), ("Bailey", "ABSTAIN")]
    found = cal.line_of(cal._MOVED.match("Motion: Wright Seconded: Pont e Approved: Unanimous"), ["ABSENT: None"])
    assert (found["mover"], found["seconder"], found["unanimous"], found["cast"]) == ("Wright", "Pont e", True, [])
    assert cal.line_of(cal._MOVED.match("Moved: Callaway Second: Wilensky Approved: Majority"), ["Dissenting: Spellman"])["cast"] == [("Spellman", "NO")]
    # A line that says more than the words the reader knows is not read past.
    odd = cal.line_of(cal._MOVED.match("Moved: Tryon Second: Stein Approval: Unanimous (Callaway absent)"))
    assert cal.decide(odd, BOARD_2001) == (None, "the line says more than the reader knows: Unanimous (Callaway absent)")
    assert "at_odds" not in found


def test_a_part_of_the_meeting_is_named_by_a_short_line_or_one_in_capitals():
    assert cal.section_of("C O N S E N T A G E N D A") == cal.section_of("9:55 AM: Consent Agenda") == "Consent Agenda"
    assert cal.section_of("9:00 AM to 9:30 AM: PUBLIC COMMENT") == cal.section_of("9:41 AM: General Public Comment - 30 Minutes") == "Public Comment"
    assert cal.section_of("ITEMS PULLED FROM CONSENT") == "Items Pulled from the Consent Agenda"
    assert cal.section_of("RECOGNITION AND ACKNOWLEDGEMENTS") == "Recognition and Acknowledgments"
    assert cal.section_of("Closed session was held pursuant to Government Code section 54956.9; conference with labor") == ""
    assert cal.section_of("7. CLOSED SESSION/HUMAN RESOURCES & RISK MANAGEMENT") == "" and cal.section_of("Public comment was closed.") == ""


def test_a_motion_told_in_a_sentence_is_read_clause_by_clause():
    told = lambda words: cal.spoken(words, BOARD_2014)
    one, = told("Motion by Supervisor Spellman, second by Supervisor Wright. Approved by Supervisors Edson, Wright, Ponte and Spellman. "
                "Supervisor Callaway voted no.")
    assert (one["mover"], one["seconder"]) == ("Spellman", "Wright")
    assert one["cast"] == [("Edson", "AYE"), ("Wright", "AYE"), ("Ponte", "AYE"), ("Spellman", "AYE"), ("Callaway", "NO")]
    one, = told("A motion by Supervisor Ponte, a second by Supervisor Wright. 5- 0 approved.")
    assert (one["tally"], one["cast"], one["result"]) == ((5, 0), [], "Pass")
    one, = told("Motion by Supervisor Edson, second by Supervisor Wright. Supervisors Edson, Wright, Callaway, Ponte and Spellman approved unanimously.")
    assert len(one["cast"]) == 5 and one["unanimous"]
    one, = told("Motion to reconsider the item was made by Supervisor Callaway, second by Supervisor Spellman. Supervisors Edson, Wright, "
                "Callaway, Ponte and Spellman unanimously approved.")
    assert (one["mover"], one["seconder"], len(one["cast"])) == ("Callaway", "Spellman", 5)
    one, = told("Motion by Supervisor Callaway to appoint Robert Pachinger, second by Supervisor Edson. Approved unanimously by Supervisors "
                "Edson, Wright, Callaway, Ponte and Spellman.")
    assert (one["mover"], one["seconder"], len(one["cast"])) == ("Callaway", "Edson", 5)
    first, second = told("On a motion by Supervisor Wright and a second by Supervisor Edson, to continue. The vote was 2-2-1, Supervisors Wright "
                         "and Edson voting affirmatively, Supervisor Ponte and Callaway dissenting and Supervisor Spellman was absent. Due to a tie "
                         "vote, a motion was made by Supervisor Ponte and a second by Supervisor Callaway to table. The Board unanimously agreed, "
                         "Supervisor Spellman was absent.")
    assert first["tally"] == (2, 2) and sorted(first["cast"]) == sorted(
        [("Wright", "AYE"), ("Edson", "AYE"), ("Ponte", "NO"), ("Callaway", "NO"), ("Spellman", "ABSENT")])
    assert (second["mover"], second["unanimous"], second["cast"]) == ("Ponte", True, [("Spellman", "ABSENT")])
    one, = told("The Board accepted her resignation by unanimous vote of Supervisors Edson, Wright, Callaway, Ponte, and Spellman.")
    assert one["mover"] == "" and len(one["cast"]) == 5
    one, = told("Board action: On a motion by Supervisor Edson and a second by Supervisor Ponte, the Board voted 4-0 to authorize staff to settle.")
    assert (one["tally"], one["mover"], one["cast"]) == ((4, 0), "Edson", [])
    # A clause that names someone who is no supervisor is not a vote's clause.
    assert told("Motion by Supervisor Wright, second by Supervisor Edson. Approved by Supervisors Edson and Resolution.")[0]["cast"] == []
    assert told("Supervisor Spellman made a motion to approve the Change Order, which died for lack of a second.") == []


def test_who_comes_and_goes_is_read_where_the_minutes_say_so():
    lines = cal.lines_of("Supervisor Wright arrived at 8:35AM.\nSupervisor Wright left the meeting at 1: 36 PM and returned at 1: 40 PM.\n"
                         "Supervisors Spellman left the meeting at 1:55 PM during a\nfive minute break.\nChair Ponte returned to board chambers.\n"
                         "Supervisor Edson was absent for the closed session only.\nSupervisor Edson stepped out for the closed session item.")
    assert cal.moves_in(lines, BOARD_2014) == [[(["Chris Wright"], True)], [], [(["Darren Spellman"], False)], [], [(["Debbie Ponte"], True)], [], []]


# ---------------------------------------------------------------------------
# Deciding a motion
# ---------------------------------------------------------------------------

def test_a_motion_that_names_its_ayes_is_read_as_printed_if_the_names_and_the_count_agree():
    named = [("Edson", "AYE"), ("Wright", "AYE"), ("Ponte", "AYE"), ("Spellman", "NO"), ("Callaway", "ABSENT")]
    cast, problem = cal.decide(motion(cast=named, tally=(3, 1)), BOARD_2014)
    assert problem == "" and sorted(cast) == sorted([("Cliff Edson", "AYE", "named"), ("Chris Wright", "AYE", "named"), ("Debbie Ponte", "AYE", "named"),
                                                     ("Darren Spellman", "NO", "named"), ("Merita Callaway", "ABSENT", "named")])
    assert cal.decide(motion(cast=named, tally=(4, 1)), BOARD_2014) == (None, "the minutes count 4 to 1 and name 3 and 1")
    assert cal.decide(motion(cast=named, unanimous=True), BOARD_2014) == (None, "unanimous, with a supervisor opposed")
    assert cal.decide(motion(cast=named + [("Kearney", "AYE")]), BOARD_2014) == (None, "not on the roll: Kearney")
    assert cal.decide(motion(cast=named + [("Edson", "NO")]), BOARD_2014) == (None, "named twice: Cliff Edson")
    assert cal.decide(motion(cast=named + [("Edson", "AYE")]), BOARD_2014)[1] == ""  # the same vote entered twice is one vote
    assert cal.decide(motion(cast=named, seconder="Callaway"), BOARD_2014) == (None, "the seconder is named absent: Merita Callaway")
    # A name not in the meeting's own head may be someone on the Board about then.
    wider = BOARD_2014 + ["Steve Kearney"]
    assert cal.decide(motion(cast=named + [("Kearney", "AYE")]), BOARD_2014, wider)[0][-1] == ("Steve Kearney", "AYE", "named")


def test_a_sentence_must_account_for_everyone_since_a_clause_can_be_missed():
    some = [("Edson", "AYE"), ("Callaway", "AYE"), ("Ponte", "AYE")]
    assert cal.decide(motion(how="words", cast=some), BOARD_2014) == (None, "the vote does not say how Chris Wright, Darren Spellman voted")
    assert cal.decide(motion(how="words", cast=some, away=["Wright", "Spellman"]), BOARD_2014)[1] == ""  # the minutes have them out of the room
    assert cal.decide(motion(how="words", cast=some, tally=(3, 0)), BOARD_2014)[1] == ""  # a count the names bear out
    assert cal.decide(motion(how="words", cast=some), [], BOARD_2014, False, []) == (None, "the minutes have no roll to check the names against")
    assert cal.decide(motion(how="block", cast=some), BOARD_2014)[1] == ""  # the portal's block is the clerk's entry, and is read as it stands


def test_a_count_is_read_when_those_not_named_are_as_many_as_it_says():
    cast, problem = cal.decide(motion(how="words", tally=(4, 1), cast=[("Wright", "NO")]), BOARD_2014)
    assert problem == "" and ("Chris Wright", "NO", "named") in cast
    assert sorted(member for member, word, way in cast if (word, way) == ("AYE", "count")) == sorted(set(BOARD_2014) - {"Chris Wright"})
    assert len(cal.decide(motion(how="words", tally=(4, 0), away=["Spellman"]), BOARD_2014)[0]) == 4
    assert cal.decide(motion(how="words", tally=(4, 0)), BOARD_2014) == (None, "the count has 4 ayes and the minutes have 5 supervisors not named")
    assert cal.decide(motion(how="words", tally=(3, 2), cast=[("Ponte", "NO"), ("Wright", "NO"), ("Edson", "NO")]), BOARD_2014) == (
        None, "the count has 2 against and 3 are named")
    # Minutes with no head: five ayes on a board of five are everyone, if the Board about then is known.
    assert len(cal.decide(motion(how="words", tally=(5, 0)), [], BOARD_2014, False, BOARD_2014)[0]) == 5
    assert cal.decide(motion(how="words", tally=(5, 0)), [], [], False, [])[0] is None


def test_unanimous_and_majority_are_read_by_who_the_minutes_have_present():
    cast, problem = cal.decide(motion(unanimous=True, cast=[("Stein", "ABSENT")]), BOARD_2001)
    assert problem == "" and ("Paul Stein", "ABSENT", "named") in cast
    assert sorted(member for member, word, way in cast if (word, way) == ("AYE", "unanimous")) == sorted(set(BOARD_2001) - {"Paul Stein"})
    # Someone the minutes have away, whom the line does not name, has no row: the line does not say they had come back.
    cast, _ = cal.decide(motion(unanimous=True, away=["Paul Stein"]), BOARD_2001)
    assert len(cast) == 4 and "Paul Stein" not in [member for member, _, _ in cast]
    cast, _ = cal.decide(motion(majority=True, cast=[("Tryon", "NO")]), BOARD_2001)
    assert ("Thomas Tryon", "NO", "named") in cast and [way for _, word, way in cast if word == "AYE"] == ["majority"] * 4
    assert cal.decide(motion(majority=True), BOARD_2001) == (None, "majority, and nobody is named")
    assert cal.decide(motion(unanimous=True, cast=[("Tryon", "NO")]), BOARD_2001) == (None, "unanimous, with a supervisor opposed")
    assert cal.decide(motion(unanimous=True), BOARD_2001, known=False) == (None, "unanimous, and the head of the minutes does not say who was present")
    assert cal.decide(motion(unanimous=True, away=BOARD_2001[:3]), BOARD_2001) == (
        None, "unanimous, and the minutes have 2 supervisors present who are not named")
    assert cal.decide(motion(), BOARD_2001) == (None, "the vote is told in words the reader does not read")
    assert cal.decide(motion(cast=[("Stein", "ABSENT")]), BOARD_2001) == (None, "the minutes name no ayes and give no count")


# ---------------------------------------------------------------------------
# Whole minutes
# ---------------------------------------------------------------------------

def test_the_portals_minutes_are_read_item_by_item():
    agenda, votes, facts = read(PORTAL, about=["John Garamendi"])
    assert (facts["format"], facts["roll_from"], facts["pages"], facts["motions"], facts["motions_read"]) == ("portal", "attendee table", 2, 4, 4)
    assert list(agenda) == ["2778-1", "2778-3", "2778-c1", "2778-4", "2778-5", "2778-6", "2778-u1", "2778-7", "2778-8"]
    # A vote an earlier meeting's closed session took, reported out at this one, is not this meeting's.
    assert agenda["2778-1"]["motions"] == 0 and agenda["2778-1"]["section"] == "Closed Session Agenda"
    item = agenda["2778-3"]
    assert (item["matter_id"], item["file_type"], item["department"], item["agenda_number"]) == ("9167", "Proclamation", "Sheriff", "3")
    assert item["title"] == "Adopt a Proclamation recognizing Robyn Berwick for over twenty years of outstanding volunteer service."
    assert (item["mover"], item["seconder"], item["ayes"], item["result"], item["outcome"]) == (
        "Benjamin Stopper", "Gary Tofanelli", 5, "Pass", "ADOPTED [UNANIMOUS]")
    assert item["section"] == "Recognition and Acknowledgments"  # "Public Comment:" set in under the item opened no new part
    assert cast_of(votes, "2778-3")["Gary Tofanelli"] == ("AYE", "named")  # late by the head, and named by the block
    # The consent calendar voted on as one: the vote is on its own line, and its items point to it.
    calendar = agenda["2778-c1"]
    assert calendar["heading"] and (calendar["ayes"], calendar["not_voting"], calendar["matter_id"]) == (4, 1, "")
    assert cast_of(votes, "2778-c1")["Martin Huberty"] == ("ABSTAIN", "named") and cast_of(votes, "2778-c1")["Gary Tofanelli"] == ("AYE", "named")
    for item_id in ("2778-4", "2778-5"):
        assert (agenda[item_id]["section_id"], agenda[item_id]["voted_with"], agenda[item_id]["motions"]) == ("2778-c1", "2778-c1", 0)
        assert agenda[item_id]["votes_read"] is None
    assert (agenda["2778-5"]["number"], agenda["2778-5"]["doc_type"], agenda["2778-5"]["matter_id"]) == ("20260526r025", "resolution", "2778-5")
    # An item pulled from the calendar is taken up under no number, and has a vote of its own.
    pulled = agenda["2778-u1"]
    assert (pulled["matter_id"], pulled["section"], pulled["section_id"], pulled["voted_with"]) == (
        "9190", "Items Pulled from the Consent Agenda", "", "2778-u1")
    assert (pulled["ayes"], pulled["noes"], pulled["not_voting"], pulled["outcome"]) == (3, 1, 1, "APPROVED [3 TO 1]")
    assert cast_of(votes, "2778-u1") == {"Autumn Andahl": ("AYE", "named"), "Gary Tofanelli": ("AYE", "named"), "Martin Huberty": ("AYE", "named"),
                                         "Amanda Folendorf": ("NO", "named"), "Benjamin Stopper": ("RECUSED", "named")}
    # A word that is neither carried nor failed is kept and not judged; a name not in the head may be someone about then.
    tabled = agenda["2778-7"]
    assert (tabled["outcome"], tabled["result"], tabled["votes_read"], tabled["ayes"]) == ("TABLED [UNANIMOUS]", "", True, 5)
    assert "John Garamendi" in cast_of(votes, "2778-7")
    assert (agenda["2778-8"]["motions"], agenda["2778-8"]["outcome"], agenda["2778-8"]["action"]) == (0, "COMPLETED", "COMPLETED")
    assert not any("Not an item" in row["title"] for row in agenda.values())  # the minutes end where the meeting is closed
    assert all(vote["meeting_id"] == "2778" and vote["date"] == "2026-05-26" and vote["matter_file"] == "" for vote in votes)


def test_a_vote_an_earlier_closed_session_took_is_not_this_meetings():
    told = ("By a unanimous vote of Supervisors Folendorf, Stopper, Andahl, Tofanelli and Huberty, authority was granted to settle.\n")
    for said in ("A closed session was held on February 11, 2026 pursuant to Government Code Section 54956.9.",
                 "The Clerk reported out for the May 12, 2026 Closed session.", "May 12, 2026 CLOSED SESSION: conference with legal counsel."):
        text = PORTAL.replace("Recognition and Acknowledgments\n", "Staff Announcements\n" + said + "\n" + told + "Recognition and Acknowledgments\n")
        agenda, votes, facts = read(text, about=["John Garamendi"])
        assert facts["motions"] == 4 and not any(row["section"] == "Staff Announcements" for row in agenda.values()), said
    # Said of today's closed session, the same words are a vote of this meeting.
    text = PORTAL.replace("Recognition and Acknowledgments\n", "Staff Announcements\n" + told + "Recognition and Acknowledgments\n")
    agenda, votes, facts = read(text, about=["John Garamendi"])
    assert facts["motions"] == 5 and len(cast_of(votes, "2778-c1")) == 5 and agenda["2778-c1"]["title"] == "Staff Announcements"


def test_a_block_that_names_someone_not_on_the_board_puts_nothing_in_the_votes():
    agenda, votes, facts = read(PORTAL)  # nobody says who Garamendi is
    assert (agenda["2778-7"]["votes_read"], agenda["2778-7"]["problem"]) == (False, "not on the roll: Garamendi")
    assert cast_of(votes, "2778-7") == {} and (facts["motions"], facts["motions_read"]) == (4, 3)
    assert (agenda["2778-7"]["ayes"], agenda["2778-7"]["motions"], agenda["2778-7"]["motions_read"]) == (0, 1, 0)


def test_the_older_minutes_are_read_by_the_line_under_each_motion():
    agenda, votes, facts = read(MOVED, "1680", "2001-06-11")
    assert (facts["format"], facts["motions"], facts["motions_read"]) == ("moved", 6, 5)
    assert list(agenda) == ["1680-c1", "1680-1", "1680-2", "1680-3", "1680-4", "1680-5", "1680-6", "1680-7"]
    calendar = agenda["1680-c1"]
    assert calendar["heading"] and (calendar["mover"], calendar["seconder"], calendar["result"]) == ("Merita Callaway", "Thomas Tryon", "Pass")
    assert calendar["action"].startswith("Motion was then made approving the balance of the Consent Agenda") and "Moved: Callaway" in calendar["action"]
    assert cast_of(votes, "1680-c1") == {"Lucy Thein": ("AYE", "unanimous"), "Terri Bailey": ("AYE", "unanimous"), "Merita Callaway": ("AYE", "unanimous"),
                                         "Thomas Tryon": ("AYE", "unanimous"), "Paul Stein": ("ABSENT", "named")}
    assert (agenda["1680-1"]["voted_with"], agenda["1680-1"]["title"]) == ("1680-c1", "Minutes of May 29, 2001, as written")
    assert (agenda["1680-2"]["number"], agenda["1680-2"]["doc_type"]) == ("01-156", "resolution")
    assert agenda["1680-2"]["title"] == "RESOLUTION A RESOLUTION RECOGNIZING EAGLE SCOUT BRADY P. DAVIS"
    # Absent at the head and not named on the line: no row, since the line does not say he had not come.
    pulled = agenda["1680-3"]
    assert (pulled["title"], pulled["voted_with"], pulled["ayes"], pulled["established"]) == ("FISH & GAME/PURCHASING/AUDITOR", "1680-3", 4, "unanimous")
    assert "Paul Stein" not in cast_of(votes, "1680-3")
    # "Majority" with the one against named; a numbered list in what was said is no item.
    divided = cast_of(votes, "1680-4")
    assert divided["Thomas Tryon"] == ("NO", "named") and divided["Lucy Thein"] == ("AYE", "majority") and "Paul Stein" not in divided
    assert (agenda["1680-4"]["ayes"], agenda["1680-4"]["noes"], agenda["1680-4"]["established"]) == (3, 1, "majority")
    # He arrives, and the minutes say so: from then on he is one of the ayes.
    assert cast_of(votes, "1680-5")["Paul Stein"] == ("AYE", "unanimous") and agenda["1680-5"]["ayes"] == 5
    assert (agenda["1680-5"]["number"], agenda["1680-5"]["doc_type"]) == ("2657", "ordinance")
    # The seconder named absent on the motion's own line: one of the two is wrong, and nothing is read.
    assert (agenda["1680-6"]["votes_read"], agenda["1680-6"]["problem"]) == (False, "the seconder is named absent: Lucy Thein")
    assert cast_of(votes, "1680-6") == {}
    last = cast_of(votes, "1680-7")
    assert last["Merita Callaway"] == ("NO", "named") and last["Thomas Tryon"] == ("ABSTAIN", "named") and last["Paul Stein"] == ("AYE", "majority")
    assert agenda["1680-7"]["seconder"] == ""  # "Pont e" is nobody on this Board; the vote does not turn on it
    assert not any("Forestry" in row["title"] for row in agenda.values())  # the letters listed after the adjournment are not items


def test_the_minutes_of_2013_and_2014_are_read_by_their_sentences():
    known = {cal.key_of(name) for name in BOARD_2014}
    agenda, votes, facts = read(PROSE, "1344", "2014-07-08", known=known)
    assert (facts["format"], facts["motions"], facts["motions_read"]) == ("prose", 11, 8)
    first = agenda["1344-1"]
    assert (first["department"], first["number"], first["doc_type"], first["mover"], first["seconder"]) == (
        "HEALTH & HUMAN SERVICES", "2014-094", "resolution", "Darren Spellman", "Cliff Edson")
    assert first["title"] == "Adopt Resolution 2014-094 recognizing Esther Tabor for over 20 years of volunteer service."
    assert set(cast_of(votes, "1344-1").values()) == {("AYE", "named")} and len(cast_of(votes, "1344-1")) == 5
    assert cast_of(votes, "1344-2")["Me rita Callaway"] == ("NO", "named") and agenda["1344-2"]["noes"] == 1
    # The consent calendar's motion stands under its heading, and takes in the items no motion of their own did.
    assert agenda["1344-c1"]["heading"] and agenda["1344-c1"]["ayes"] == 5
    assert (agenda["1344-3"]["voted_with"], agenda["1344-3"]["title"]) == ("1344-c1", "MINUTES of meeting held June 17, 2014.")
    pulled = agenda["1344-4"]
    assert (pulled["voted_with"], pulled["number"], pulled["doc_type"], pulled["established"]) == ("1344-4", "3031", "ordinance", "count")
    assert cast_of(votes, "1344-4")["Chris Wright"] == ("NO", "named") and cast_of(votes, "1344-4")["Debbie Ponte"] == ("AYE", "count")
    # Out of the room by the minutes when the count was four: the four left are the ayes, and he has no row.
    assert sorted(cast_of(votes, "1344-5")) == sorted(set(BOARD_2014) - {"Darren Spellman", "Merita Callaway"} | {"Me rita Callaway"})
    # Two motions on one item: the first's count and names disagree, and it is not read; the second is.
    two = json.loads(agenda["1344-6"]["motion_log"])
    assert [(one["read"], one["problem"]) for one in two] == [(False, "the count has 2 against and 3 are named"), (True, "")]
    assert agenda["1344-6"]["votes_read"] is False and len(cast_of(votes, "1344-6", 2)) == 5 and cast_of(votes, "1344-6", 1) == {}
    assert sorted(word for word, _ in cast_of(votes, "1344-7").values()) == ["AYE", "AYE", "AYE", "NO", "NO"]  # "Wright and Spellman voted no."
    # Three named and nothing said of the other two: not read.
    assert agenda["1344-8"]["problem"].startswith("the vote does not say how ") and cast_of(votes, "1344-8") == {}
    assert sorted(word for word, _ in cast_of(votes, "1344-9").values()) == ["AYE", "AYE", "AYE", "NO", "NO"]
    assert agenda["1344-9"]["mover"] == "Cliff Edson"
    assert agenda["1344-10"]["problem"] == "the vote is told in words the reader does not read"


def test_a_motion_moved_by_someone_the_minutes_have_gone_is_not_read():
    text = MOVED.replace("Supervisor Stein arrived at 11:05 a.m.", "Supervisor Tryon left the meeting at 11:05 a.m.")
    agenda, votes, _ = read(text, "1680", "2001-06-11")
    assert agenda["1680-5"]["problem"] == "the minutes have Thomas Tryon gone from the meeting, and moving or voting here"
    assert cast_of(votes, "1680-5") == {}
    assert agenda["1680-7"]["problem"] == agenda["1680-5"]["problem"]  # named as abstaining after he had gone
    # Gone and not named on a later line: no row, and too few are left by the minutes for the line to be read by them.
    later = read(text.replace("ABSTAIN: Tryon", "ABSTAIN: Thein"), "1680", "2001-06-11")[0]["1680-7"]
    assert later["problem"] == "majority, and the minutes have 1 supervisors present who are not named"
    # Absent at the head and then moving a motion is another matter: he has come.
    text = MOVED.replace("Moved: Callaway\tSecond: Bailey\tApproval: Unanimous", "Moved: Stein\tSecond: Bailey\tApproval: Unanimous")
    assert cast_of(read(text, "1680", "2001-06-11")[1], "1680-3")["Paul Stein"] == ("AYE", "unanimous")


def test_minutes_with_no_head_are_read_by_the_board_about_that_day():
    text = PROSE[:PROSE.index("PRESENT:")] + PROSE[PROSE.index("                        RECOGNITION"):]
    assert cal.head_of(text)["roll"] == []
    agenda, votes, _ = read(text, "1329", "2013-12-10", about=BOARD_2014, around=BOARD_2014)
    assert len(cast_of(votes, "1329-1")) == 5 and len(cast_of(votes, "1329-4")) == 5  # everyone named; a count that takes in every seat
    # Four ayes, and the minutes have one supervisor out of the room: the four left are the ayes.
    assert sorted(cast_of(votes, "1329-5")) == sorted(set(BOARD_2014) - {"Darren Spellman"})
    assert agenda["1329-8"]["problem"] == "the vote does not say how Chris Wright, Darren Spellman voted"
    alone, votes, _ = read(text, "1329", "2013-12-10")
    # With no one to say whose names they are, nothing is read.
    assert alone["1329-1"]["problem"] == "unanimous, and the head of the minutes does not say who was present" and votes == []


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------

def tables_of(*readings):
    agenda, votes, found, rows = [], [], {}, []
    for (text, meeting_id, date), said in readings:
        some, cast, facts = cal.read_meeting(meeting(meeting_id, date), cal.scan(text, **said), text.count("\f") + 1,
                                             name_of=lambda name: {"Me rita Callaway": "Merita Callaway"}.get(name, name))
        agenda.extend(some)
        votes.extend(cast)
        found[meeting_id] = facts
        rows.append({"meeting_id": meeting_id, "date": date, "time": "9:00 AM", "body": "Board of Supervisors", "location": "",
                     "name": "Regular Meeting", "status": "Closed", "papers": {"minutes": f"FileOpen.aspx?Type=12&ID={meeting_id}&Inline=True"}})
    rows.append({"meeting_id": "2820", "date": "2026-06-23", "time": "", "body": "Board of Supervisors", "location": "", "name": "Regular Meeting",
                 "status": "Scheduled", "papers": {}})
    return cal.tables_of(cal.board_meetings(rows), pd.DataFrame(agenda, columns=cal.AGENDA_COLUMNS),
                         pd.DataFrame(votes, columns=cal.VOTE_COLUMNS), found, {"Me rita Callaway": "Merita Callaway"})


def test_the_tables_have_the_shape_every_boards_have():
    tables = tables_of(((PORTAL, "2778", "2026-05-26"), {}), ((PORTAL.replace("May 26, 2026", "May 12, 2026"), "2777", "2026-05-12"), {}),
                       ((PROSE, "1344", "2014-07-08"), {"known": {cal.key_of(name) for name in BOARD_2014}}))
    for name in council_tables.TABLES:
        assert list(tables[name].columns)[:len(council_tables.COLUMNS[name])] == council_tables.COLUMNS[name]
    assert list(tables["votes"].columns) == cal.VOTE_COLUMNS and list(tables["agenda_items"].columns) == cal.AGENDA_COLUMNS
    votes, agenda, items, meetings, members = (tables[name] for name in ("votes", "agenda_items", "items", "meetings", "members"))
    assert set(votes["established"]) == {"named", "count"} and set(votes["vote"]) == {"AYE", "NO", "ABSTAIN", "RECUSED"}
    assert "Me rita Callaway" not in set(votes["member"]) and "Merita Callaway" in set(votes["member"])
    assert agenda["votes_read"].dtype == "boolean" and agenda["heading"].dtype == bool
    # Every vote is on a line, and every line's counts are the votes of its last motion.
    assert set(votes["item_id"]) <= set(agenda["item_id"])
    line = agenda.set_index("item_id").loc["2778-u1"]
    assert (line["ayes"], line["noes"], line["not_voting"]) == (3, 1, 1)
    listed = meetings.set_index("meeting_id")
    assert (listed.loc["2778", "minutes"], listed.loc["2778", "items"], listed.loc["2778", "motions_read"]) == ("read", 8, 3)
    assert (listed.loc["2820", "minutes"], listed.loc["2820", "items"], listed.loc["2820", "roll"]) == ("", 0, "")
    assert json.loads(listed.loc["1344", "roll"])[2]["name"] == "Merita Callaway"
    # An item is here once: by the portal's id where the minutes print it, which two meetings may share.
    assert not items["matter_id"].duplicated().any()
    proclamation = items.set_index("matter_id").loc["9167"]
    assert (proclamation["times_on_agenda"], proclamation["date"], proclamation["agenda_date"], proclamation["action_on"]) == (
        2, "2026-05-12", "2026-05-26", "item")
    assert proclamation["url"].endswith("ID=2778&Inline=True") and proclamation["passed_date"] == ""
    by_calendar = items.set_index("matter_id").loc["9185"]
    assert (by_calendar["action_on"], by_calendar["ayes"], by_calendar["mover"], by_calendar["votes_read"]) == ("section", 4, "Amanda Folendorf", True)
    assert items.set_index("matter_id").loc["9163", "action_on"] == ""  # nothing voted on
    # A supervisor is a member with votes on two days; a district is the one the portal's head gives.
    assert set(members["name"]) == {"Amanda Folendorf", "Benjamin Stopper", "Autumn Andahl", "Gary Tofanelli", "Martin Huberty"}
    assert dict(zip(members["name"], members["district"])) == {"Amanda Folendorf": 4, "Benjamin Stopper": 5, "Autumn Andahl": 2,
                                                                "Gary Tofanelli": 1, "Martin Huberty": 3}
    assert members["serving"].all() and dict(zip(members["name"], members["role"]))["Benjamin Stopper"] == "Chair"
    assert (members["first_vote"] == "2026-05-12").all() and (members["last_vote"] == "2026-05-26").all()


def test_a_run_reads_again_what_it_has_kept_and_fetches_only_what_it_has_not(tmp_path, monkeypatch):
    rows = [{"meeting_id": meeting_id, "date": date, "time": "9:00 AM", "body": "Board of Supervisors", "location": "", "name": "Regular Meeting",
             "status": "Closed", "papers": {"minutes": f"FileOpen.aspx?Type=12&ID={meeting_id}&Inline=True"}}
            for meeting_id, date in (("1344", "2014-07-08"), ("2777", "2026-05-12"), ("2778", "2026-05-26"), ("1256", "2011-06-14"))]
    rows += [{**rows[0], "meeting_id": str(number), "date": f"2020-01-{number - 100:02d}", "papers": {}} for number in range(101, 120)]
    (tmp_path / "text").mkdir()
    (tmp_path / "text" / "2778.txt").write_text(PORTAL, encoding="utf-8")
    (tmp_path / "text" / "1344.txt").write_text(PROSE, encoding="utf-8")
    asked, slept = [], []
    pages = {"2777": ["page one of a scan", ""], "1256": None}

    def fetched(url):
        asked.append(url)
        meeting_id = url.split("ID=")[1].split("&")[0]
        if pages[meeting_id] is None:
            raise cal.NoDocument("the portal sent a page in place of the document")
        return meeting_id.encode()

    monkeypatch.setattr(cal, "listed", lambda first=None, last=None: rows)
    monkeypatch.setattr(cal, "fetch_document", fetched)
    monkeypatch.setattr(cal, "pdf_text", lambda body: pages[body.decode()])
    monkeypatch.setattr(cal.time, "sleep", slept.append)
    monkeypatch.setattr(iqm2, "REFUSED", {})
    monkeypatch.setattr(cal.council_tables, "published", lambda repo, name: None)  # nothing published is looked at
    tables, fetched_now = cal.build(True, False, tmp_path)
    assert [url.split("ID=")[1].split("&")[0] for url in asked] == ["2777", "1256"]  # the newest first; what is kept is not asked for
    assert fetched_now == 1 and slept == [cal.PAUSE]  # a minute after a document, and none after the last
    assert all((tmp_path / f"{name}.parquet").exists() for name in council_tables.TABLES)
    listed = tables["meetings"].set_index("meeting_id")
    assert (listed.loc["2778", "minutes"], listed.loc["1344", "minutes"]) == ("read", "read")
    assert listed.loc["2777", "minutes"] == "no text layer" and listed.loc["1256", "minutes"] == ""  # a scan is counted and left
    assert len(tables["votes"]) and set(tables["votes"]["meeting_id"]) == {"1344", "2778"}
    assert "Merita Callaway" not in set(tables["votes"]["member"])  # one head in a scan's spelling: the name stays as that head has it
    # Started again: the scan's text is kept too, so only the document the portal did not give is asked for.
    asked.clear()
    again, fetched_again = cal.build(True, False, tmp_path)
    assert [url.split("ID=")[1].split("&")[0] for url in asked] == ["1256"] and fetched_again == 0
    assert len(again["votes"]) == len(tables["votes"])


def test_a_role_printed_without_its_comma_is_not_part_of_the_name():
    names, whole = cal.said_names("Merita Callaway, Chair; Thomas Tryon Vice-Chair; Steve Wilensky")
    assert [(name["name"], name["role"]) for name in names] == [
        ("Merita Callaway", "Chair"), ("Thomas Tryon", "Vice-Chair"), ("Steve Wilensky", "")]
    names, whole = cal.said_names("Thomas Tryon, Chair; Lucy Thein, Vice Chair; Paul Stein")
    assert [(name["name"], name["role"]) for name in names] == [
        ("Thomas Tryon", "Chair"), ("Lucy Thein", "Vice-Chair"), ("Paul Stein", "")]


def test_a_family_name_fits_a_supervisor_whose_name_the_roll_prints_another_way():
    wider = cal.widened(["Cliff Edson", "Michael Oliveira"], ["Michael C. Oliveira", "Steve Kearney"])
    assert wider == ["Cliff Edson", "Michael Oliveira", "Steve Kearney"]
    assert cal.who("Oliveira", wider) == "Michael Oliveira"
