"""build_kern_board reads the Kern County Board's votes out of its Summaries of Proceedings, where every item has a line
of its own for its vote ("Perez-Flores: All Ayes"): a vote whole, against the Board the head names and who the roll call
and the notes have in the room, or not at all."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import build_kern_board as kern
import council_tables

BOARD = ["Peters", "Parlier", "Couch", "Flores", "Perez"]
MEETING = {"meeting_id": "5357", "date": "2026-09-01",
           "minutes_url": "https://kern.granicus.com/AgendaViewer.php?view_id=58&clip_id=5357"}

# Minutes as the reader keeps them: the text of each page as the PDF has it, a form feed between two pages. Pieces of
# the minutes of 1 September 2026 (AM).
MINUTES = """SUMMARY OF PROCEEDINGS
BOARD OF SUPERVISORS - COUNTY OF KERN
1115 Truxtun Avenue
Bakersfield, California
Regular Meeting
Tuesday, September 1, 2026
9:00 A.M.
BOARD RECONVENED
Supervisors: Peters, Parlier, Couch, Flores, Perez
ROLL CALL: All Present
SALUTE TO FLAG - Led by Miguel Pantoja, U.S. Army Veteran, Kern
County Veterans' Service Department
NOTE: The vote is displayed in bold below each item. For example, Flores-
Perez denotes Supervisor Flores made the motion and Supervisor Perez
seconded the motion.
CONSENT AGENDA/OPPORTUNITY FOR PUBLIC COMMENT: ALL
ITEMS LISTED WITH A "CA" OR "C" WERE CONSIDERED TO BE
ROUTINE AND APPROVED BY ONE MOTION.
BOARD ACTION SHOWN IN CAPS
RESOLUTIONS/PROCLAMATIONS
CA-1) Resolution honoring Sheriff's Commander Michael Deleon upon his
retirement with 27 years of dedicated service to the County of Kern -
ADOPTED RESOLUTION
Couch-Flores: All Ayes
3) Proclaim September 2026 as Hunger Action Month in Kern County -
PROCLAIMED; MADE PRESENTATION TO KELLY LOWERY,
COMMUNITY ACTION PARTNERSHIP OF KERN (CAPK)
Parlier-Flores: All Ayes
PUBLIC PRESENTATIONS
8) This portion of the meeting was reserved for persons to address the Board
on any matter not on this agenda but under the jurisdiction of the Board.
NO ONE HEARD
\fSummary of Proceedings AM Page 3
Board of Supervisors Regular Meeting – 9:00 A.M. 9/1/2026
DEPARTMENTAL REQUESTS
AGRICULTURE AND MEASUREMENT STANDARDS
CA-11) Proposed retroactive Cooperative Agreement with the California
Department of Food and Agriculture (CDFA) for Certified Farmers Market
Program inspections, from July 1, 2026 through June 30, 2027, in an
amount not to exceed $6,240 (Fiscal Impact: $6,240; State; Budgeted;
Mandated) - APPROVED; AUTHORIZED CHAIRMAN TO SIGN
AGREEMENT 432-2026
Couch-Flores: All Ayes
NOTE: SUPERVISOR COUCH LEFT THE MEETING PRIOR TO THE
VOTE ON ITEM NO. 20
20) Proposed rescission of positions (Fiscal Impact: None) -
APPROVED RESCISSION OF POSITIONS
Flores-Perez: 4 Ayes; 1 Absent - Couch
21) Proposed Agreement with Kern Fair (Fiscal Impact: None) - APPROVED
Peters-Parlier: All Ayes
CA-22) Proposed Agreement with Clinica Sierra Vista (Fiscal Impact: None) -
APPROVED; AUTHORIZED CHAIRMAN TO SIGN AGREEMENT 440-2026
Couch-Flores: All Ayes
23) Proposed Ordinance amending Chapter 2.04 (Fiscal Impact: None) -
DIRECTED COUNTY COUNSEL TO REPORT BACK
Parlier-Peters: 3 Ayes; 1 No - Flores; 1 Absent - Couch
APPROVED ADDITIONAL REFERRAL
Peters-Perez: 2 Ayes; 2 Noes - Flores,
Parlier; 1 Absent - Couch
/s/ Kathleen Krause
Clerk of the Board
/s/ Phillip Peters
Chairman, Board of Supervisors"""


def reading(text=MINUTES):
    return kern.read_meeting(MEETING, kern.checked(kern.scan(text)), text.count("\f") + 1)


def by_number(agenda):
    return {row["agenda_number"]: row for row in agenda}


def cast_of(votes, number, motion=1):
    return {row["member"]: (row["vote"], row["established"]) for row in votes
            if row["item_id"] == f"5357-{number}" and row["motion"] == motion}


LISTING = """<tr class="bg_color_23"><td headers="Month2026" class="meetingMonth">Sep</td>
<td headers="Date2026" class="meetingDate">09/01/26 @ 09:00 AM</td>
<td headers="Name2026" class="meetingName">Regular Meeting AM</td>
<td headers="Minutes2026" class="meetingMinutes"><a href="//kern.granicus.com/AgendaViewer.php?view_id=58&clip_id=5357" target="_blank">Minutes<span> (PDF)</span></a></td>
<td headers="Event2026" class="meetingEvent"><a href="//kern.granicus.com/MediaPlayer.php?view_id=58&clip_id=5357">Video</a></td></tr>
<tr class="bg_color_23"><td headers="Date2026" class="meetingDate">09/01/26 @ 09:00 AM</td>
<td headers="Name2026" class="meetingName">Regular Meeting AM</td>
<td headers="Minutes2026" class="meetingMinutes"><a href="//kern.granicus.com/AgendaViewer.php?view_id=58&clip_id=5357">Minutes</a></td></tr>
<tr><td headers="Date2009" class="meetingDate">03/23/09 @ 05:30 PM</td>
<td headers="Name2009" class="meetingName">Joint City/County Meeting</td>
<td headers="Minutes2009" class="meetingMinutes"><a href="//kern.granicus.com/AgendaViewer.php?view_id=58&clip_id=949">Minutes</a></td></tr>
<tr><td headers="Date2026" class="meetingDate">10/27/26 @ 09:00 AM</td>
<td headers="Name2026" class="meetingName">Regular Meeting AM</td><td class="meetingAgenda"></td></tr>
<tr><td headers="Date2014" class="meetingDate">08/25/14 @ 06:00 PM</td>
<td headers="Name2014" class="meetingName">Evening Budget Meeting</td>
<td headers="Minutes2014" class="meetingMinutes"><a href="//kern.granicus.com/AgendaViewer.php?view_id=58&amp;clip_id=2731">Minutes</a></td></tr>"""


def test_the_listing_gives_the_boards_own_meetings_once_each():
    rows = {row["meeting_id"]: row for row in kern.rows_of(LISTING)}
    assert set(rows) == {"5357", "2731"}  # the joint meeting is another body's, and one to come has no recording
    assert rows["5357"]["date"] == "2026-09-01" and rows["5357"]["time"] == "9:00 AM"
    assert rows["5357"]["minutes"] == "https://kern.granicus.com/AgendaViewer.php?view_id=58&clip_id=5357"
    assert rows["2731"]["name"] == "Evening Budget Meeting" and rows["2731"]["time"] == "6:00 PM"
    assert rows["2731"]["minutes"].endswith("clip_id=2731")
    table = kern.meetings_table(list(rows.values()))
    assert list(table.columns[:len(council_tables.COLUMNS["meetings"])]) == council_tables.COLUMNS["meetings"]
    assert table["video_url"].tolist() == ["", "https://kern.granicus.com/MediaPlayer.php?view_id=58&clip_id=5357"]


def test_the_roll_call_says_who_answered():
    assert kern.present_of("All Present", BOARD) == (set(BOARD), "", BOARD)
    assert kern.present_of("4 Present; 1 Absent - Perez", BOARD) == (set(BOARD) - {"Perez"}, "", BOARD)
    assert kern.present_of("3 Present; 2 Absent - Peters, Parlier", BOARD)[0] == {"Couch", "Flores", "Perez"}
    assert kern.present_of("3 Present; 2 Absent – Peters; Parlier", BOARD)[0] == {"Couch", "Flores", "Perez"}
    assert kern.present_of("1 Absent - Perez", BOARD)[0] == set(BOARD) - {"Perez"}
    assert kern.present_of("4 Present; 1 Absent - Watson", BOARD)[0] is None
    assert kern.present_of("4 Present; 2 Absent - Perez", BOARD)[0] is None
    # A head that names only those present: the one the roll call has absent makes the five.
    four = ["Peters", "Parlier", "Couch", "Perez"]
    assert kern.present_of("4 Present; 1 Absent - Flores", four) == (set(four), "", four + ["Flores"])


def test_a_vote_line_is_read_whole_against_the_board():
    everyone = set(BOARD)
    cast, _ = kern.decide("All Ayes", BOARD, everyone - {"Couch"})
    assert dict((name, word) for name, word, _ in cast) == {"Peters": "AYE", "Parlier": "AYE", "Couch": "ABSENT", "Flores": "AYE", "Perez": "AYE"}
    assert {way for _, _, way in cast} == {"all"}
    cast, _ = kern.decide("3 Ayes; 1 Absent – Perez; 1 Abstained - Couch", BOARD, everyone)
    assert {name: (word, way) for name, word, way in cast} == {
        "Peters": ("AYE", "count"), "Parlier": ("AYE", "count"), "Flores": ("AYE", "count"),
        "Perez": ("ABSENT", "named"), "Couch": ("ABSTAIN", "named")}
    cast, _ = kern.decide("2 Ayes; 3 Noes - Peters, Couch, Perez", BOARD, everyone)
    assert [name for name, word, _ in cast if word == "NO"] == ["Peters", "Couch", "Perez"]
    # What does not add up to the Board, or names someone not on it, is not read.
    assert kern.decide("4 Ayes; 2 Noes - Couch, Perez", BOARD, everyone) == (None, "the line counts 6 and the Board has 5")
    assert kern.decide("4 Ayes; 1 No - Maben", BOARD, everyone) == (None, "not on the Board: Maben")
    assert kern.decide("3 Ayes; 2 Noes - Couch", BOARD, everyone) == (None, "2 Noes and 1 named")
    assert kern.decide("All Ayes", BOARD, None)[0] is None
    assert kern.decide("Unanimous", BOARD, everyone)[1].startswith("words the reader does not know")


def test_minutes_are_read_into_items_with_the_boards_action_and_vote():
    agenda, votes, facts = reading()
    rows = by_number(agenda)
    assert facts["minutes"] == "read" and json.loads(facts["roll"]) == BOARD and facts["present"] == "All Present"
    assert facts["chair"] == "Phillip Peters"
    one = rows["CA-1"]
    assert one["title"].startswith("Resolution honoring Sheriff's Commander") and one["action"] == "ADOPTED RESOLUTION"
    assert one["consent"] and one["section"] == "RESOLUTIONS/PROCLAMATIONS" and one["mover"] == "Couch" and one["seconder"] == "Flores"
    assert rows["3"]["action"].startswith("PROCLAIMED; MADE PRESENTATION") and not rows["3"]["consent"]
    assert rows["8"]["motions"] == 0 and rows["8"]["votes_read"] is None
    eleven = rows["CA-11"]
    assert eleven["department"] == "AGRICULTURE AND MEASUREMENT STANDARDS" and eleven["section"] == "DEPARTMENTAL REQUESTS"
    assert eleven["number"] == "Agreement 432-2026" and eleven["result"] == ""
    assert cast_of(votes, "CA-1") == {name: ("AYE", "all") for name in BOARD}


def test_a_supervisor_who_left_is_absent_from_all_ayes_and_the_consent_vote_is_the_heads():
    agenda, votes, _ = reading()
    assert cast_of(votes, "20") == {"Peters": ("AYE", "count"), "Parlier": ("AYE", "count"), "Couch": ("ABSENT", "named"),
                                     "Flores": ("AYE", "count"), "Perez": ("AYE", "count")}
    assert cast_of(votes, "21")["Couch"] == ("ABSENT", "all")
    # The consent agenda was taken with Couch there (he moved it), though its item is printed after he left.
    assert cast_of(votes, "CA-22")["Couch"] == ("AYE", "all")


def test_the_consent_agendas_all_ayes_are_not_read_where_its_lines_leave_the_room_unknown():
    # Moved and seconded by two who were there all along: it may have been taken before Couch left or after.
    text = MINUTES.replace("Couch-Flores: All Ayes", "Perez-Flores: All Ayes")
    rows = by_number(reading(text)[0])
    assert rows["CA-22"]["votes_read"] is False and rows["CA-1"]["votes_read"] is False
    assert rows["CA-1"]["problem"].startswith("the consent agenda's All Ayes")
    assert rows["21"]["votes_read"] is True  # an item of its own is read where it stands


def test_two_motions_on_an_item_and_a_vote_line_that_runs_on():
    agenda, votes, _ = reading()
    item = by_number(agenda)["23"]
    assert item["motions"] == 2 and item["motions_read"] == 2 and item["votes_read"] is True
    assert cast_of(votes, "23", 1)["Flores"] == ("NO", "named")
    assert cast_of(votes, "23", 2) == {"Peters": ("AYE", "count"), "Perez": ("AYE", "count"), "Flores": ("NO", "named"),
                                        "Parlier": ("NO", "named"), "Couch": ("ABSENT", "named")}
    assert {row["motion_text"] for row in votes if row["item_id"] == "5357-23" and row["motion"] == 2} == {"APPROVED ADDITIONAL REFERRAL"}
    assert item["vote_line"].endswith("2 Noes - Flores, Parlier; 1 Absent - Couch")


def test_all_ayes_is_not_read_where_the_minutes_own_votes_disagree_with_the_notes():
    # Couch is in the room by the roll call, but a vote names him absent: he left unnoted, and when is not known, so no
    # "All Ayes" since the roll call is read. The consent agenda's, which he moved, still is.
    text = MINUTES.replace("NOTE: SUPERVISOR COUCH LEFT THE MEETING PRIOR TO THE\nVOTE ON ITEM NO. 20\n", "")
    agenda, votes, _ = reading(text)
    rows = by_number(agenda)
    assert rows["20"]["votes_read"] is True
    assert rows["21"]["votes_read"] is False and "disagree" in rows["21"]["problem"]
    assert rows["3"]["votes_read"] is False
    assert rows["CA-1"]["votes_read"] is True and rows["CA-22"]["votes_read"] is True
    assert not cast_of(votes, "21")


def test_all_ayes_is_not_read_where_a_note_says_a_supervisor_took_no_part():
    text = MINUTES.replace("21) Proposed Agreement", "NOTE: SUPERVISOR PEREZ ABSTAINED DUE TO A CONFLICT\n21) Proposed Agreement")
    rows = by_number(reading(text)[0])
    assert rows["21"]["votes_read"] is False and rows["21"]["problem"] == "All Ayes, and a note says a supervisor took no part"


def test_a_head_without_a_roll_call_reads_counts_but_not_all_ayes():
    text = MINUTES.replace("ROLL CALL: All Present\n", "")
    rows = by_number(reading(text)[0])
    assert rows["CA-1"]["votes_read"] is False and rows["CA-1"]["problem"] == "no roll call under the Board at the head"
    assert rows["20"]["votes_read"] is True


def test_a_note_of_someone_away_for_part_of_an_item():
    text = MINUTES.replace("21) Proposed Agreement",
                           "NOTE: Supervisor Parlier left the dais at the beginning of Item No. 21 and\nreturned following the vote\n21) Proposed Agreement")
    rows = by_number(reading(text)[0])
    assert rows["21"]["votes_read"] is False and "part of the item" in rows["21"]["problem"]
    assert rows["23"]["votes_read"] is True


def test_the_five_tables_come_out_in_the_one_shape(tmp_path):
    agenda, votes, facts = reading()
    meetings = kern.meetings_table([{"meeting_id": "5357", "name": "Regular Meeting AM", "date": "2026-09-01", "time": "9:00 AM",
                                     "minutes": MEETING["minutes_url"], "video": True}])
    tables = kern.tables_of(meetings, pd.DataFrame(agenda, columns=kern.AGENDA_COLUMNS), pd.DataFrame(votes, columns=kern.VOTE_COLUMNS),
                            {"5357": facts}, {"peters": 1, "parlier": 2})
    for name in council_tables.TABLES:
        assert list(tables[name].columns[:len(council_tables.COLUMNS[name])]) == council_tables.COLUMNS[name]
    council_tables.write_tables(tables, tmp_path)
    assert sorted(path.name for path in tmp_path.glob("*.parquet")) == sorted(f"{name}.parquet" for name in council_tables.TABLES)
    assert set(tables["votes"]["vote"]) <= {"AYE", "NO", "ABSENT", "ABSTAIN"}
    assert tables["meetings"]["items"].tolist() == [len(agenda)]
    members = tables["members"]
    assert members.empty  # one day of votes makes nobody a member
    assert tables["items"]["action_on"].tolist().count("item") == sum(row["motions"] > 0 for row in agenda)


def test_districts_come_from_the_minutes_own_words():
    texts = ["SALUTE TO FLAG - Led by Second District Supervisor Zack Scrivner"] * 2 + [
             "SALUTE TO FLAG -Led by Fourth District Supervisor Raymond A. Watson\nNOTE: The vote"] * 12 + [
             "Led by Third District Supervisor Raymond Watson",
             "Led by First District Supervisor Phillip Peters", "Led by Third District Supervisor Peters",
             "Led by Fifth District Supervisor Goh"]
    districts = kern.districts_of(texts)
    # Watson's one slip is outweighed; Peters's two mentions disagree; Goh's one is not enough.
    assert districts["scrivner"] == 2 and districts["watson"] == 4
    assert "peters" not in districts and "goh" not in districts


class Answer:
    def __init__(self, status, location="", body=b"%PDF-1.4", kind="application/pdf"):
        self.status_code, self.content, self.headers = status, body, {"location": location, "content-type": kind}
        self.text = body.decode("latin-1")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_a_redirect_is_followed_only_on_the_same_host(monkeypatch):
    monkeypatch.setattr(kern, "PAUSE", 0)
    monkeypatch.setattr(kern, "_refused", set())
    asked = []
    answers = iter([Answer(302, "https://kern.granicus.com/DocumentViewer.php?file=kern_x.pdf&view=1"), Answer(200)])
    monkeypatch.setattr(kern._session, "get", lambda url, **_: asked.append(url) or next(answers))
    assert kern.fetch(MEETING["minutes_url"]).content.startswith(b"%PDF")
    assert asked[1].startswith("https://kern.granicus.com/DocumentViewer.php")
    answers = iter([Answer(302, "https://itsapps.kerncounty.com/somewhere")])
    with pytest.raises(kern.NotPDF):
        kern.fetch(MEETING["minutes_url"])
    assert len(asked) == 3  # the other host was not asked


def test_a_refusal_or_a_permission_page_stops_the_host_being_asked_again(monkeypatch):
    monkeypatch.setattr(kern, "PAUSE", 0)
    monkeypatch.setattr(kern, "_refused", set())
    asked = []
    answers = iter([Answer(302, "/panes/PermissionDenied.php")])
    monkeypatch.setattr(kern._session, "get", lambda url, **_: asked.append(url) or next(answers))
    with pytest.raises(kern.Refused):
        kern.fetch(MEETING["minutes_url"])
    with pytest.raises(kern.Refused):
        kern.fetch(MEETING["minutes_url"])
    assert len(asked) == 1
    monkeypatch.setattr(kern, "_refused", set())
    answers = iter([Answer(429, body=b"slow down", kind="text/html")])
    with pytest.raises(kern.Refused):
        kern.fetch(MEETING["minutes_url"])


def test_text_kept_here_is_not_fetched_again(tmp_path, monkeypatch):
    (tmp_path / "text").mkdir()
    (tmp_path / "text" / "5357.txt").write_text(MINUTES, encoding="utf-8")
    monkeypatch.setattr(kern, "fetch", lambda url: pytest.fail("asked the host for text kept here"))
    text, asked = kern.text_of(MEETING, tmp_path)
    assert text == MINUTES and not asked


def test_motion_failed_under_a_vote_line_is_that_votes_result():
    text = MINUTES.replace("Parlier-Peters: 3 Ayes; 1 No - Flores; 1 Absent - Couch\n",
                           "Parlier-Peters: 3 Ayes; 1 No - Flores; 1 Absent - Couch\nMOTION FAILED\n")
    text = text.replace("Peters-Perez: 2 Ayes; 2 Noes - Flores,\nParlier; 1 Absent - Couch\n",
                        "Peters-Perez: 2 Ayes; 2 Noes - Flores,\nParlier; 1 Absent - Couch\nMOTION FAILED\n")
    item = by_number(reading(text)[0])["23"]
    log = json.loads(item["motion_log"])
    assert [motion["outcome"] for motion in log] == ["failed", "failed"] and item["result"] == "failed"
    assert by_number(reading()[0])["23"]["result"] == ""  # nothing printed, nothing worked out from the count
