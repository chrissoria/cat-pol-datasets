"""build_granicus_board reads a county's minutes on granicus.com, and puts no one down as voting whom the minutes do not name."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import build_granicus_board as board
import council_tables

GLENN = {"meeting_id": "2620", "date": "2026-08-18", "body": "Board of Supervisors"}
BUTTE = {"meeting_id": "1374", "date": "2024-05-14", "body": "Board of Supervisors"}
MARIN = {"meeting_id": "4881", "date": "2011-08-09", "body": "Board of Supervisors"}


def page(*lines):
    """Minutes as Granicus prints them, near enough: a cell or a block to a line."""
    return "<html><style>td { x: y }</style><body>" + "".join(f"<div>{line}</div>" for line in lines) + "</body></html>"


def read(key, meeting, *lines):
    agenda, votes = board.read_minutes(key, meeting, page(*lines))
    return {row["agenda_number"]: row for row in agenda}, votes


def cast(votes, item_id=None, motion=None):
    return [(vote["member"], vote["vote"]) for vote in votes
            if (item_id is None or vote["item_id"] == item_id) and (motion is None or vote["motion"] == motion)]


# ---------------------------------------------------------------------------
# The listing
# ---------------------------------------------------------------------------

def test_the_listing_is_read_however_the_county_writes_its_rows_and_dates():
    glenn = '''<table><tr><th id="Name">Name</th></tr>
      <tr class="odd"><td class="listItem" headers="Name" id="Board-of-Supervisors" scope="row">Board of Supervisors - Special Meeting</td>
        <td class="listItem" headers="Date Board-of-Supervisors"><span style="display:none;">1787036400</span>Aug 18, 2026</td>
        <td class="listItem"><a href="//glenncounty.granicus.com/AgendaViewer.php?view_id=9&clip_id=2620" target="_blank">Agenda</a></td>
        <td class="listItem"><a href="//glenncounty.granicus.com/MinutesViewer.php?view_id=9&clip_id=2620" target="_blank">Minutes</a></td></tr>
      <tr class="even"><td class="listItem" headers="Name" id="Technical-Testing" scope="row">Technical Testing</td>
        <td class="listItem" headers="Date Technical-Testing"><span style="display:none;">1136361600</span>Jan  4, 2006</td>
        <td class="listItem"><a href="//glenncounty.granicus.com/MediaPlayer.php?view_id=9&clip_id=30">Audio</a></td></tr>
      <tr class="odd"><td class="listItem" headers="Name" scope="row">Board of Supervisors</td>
        <td class="listItem" headers="Date Board-of-Supervisors">Aug 18, 2026</td>
        <td class="listItem"><a href="//glenncounty.granicus.com/AgendaViewer.php?view_id=9&clip_id=2620">Agenda</a></td></tr>
      <tr><td class="listItem" headers="Name" scope="row">Water Commission</td><td headers="Date Water">Dec 2, 2026</td></tr></table>'''
    meetings = board.meetings_table("glenn-county", glenn)
    # The newest row is printed twice and kept once; a meeting to come with nothing filed has no number and is left out,
    # and so is the clerk's test of the recorder.
    assert meetings[["meeting_id", "date", "body", "name"]].values.tolist() == [
        ["2620", "2026-08-18", "Board of Supervisors", "Board of Supervisors - Special Meeting"]]
    assert meetings.loc[0, "minutes_url"] == "https://glenncounty.granicus.com/MinutesViewer.php?view_id=9&clip_id=2620"
    assert meetings.loc[0, "agenda_url"].endswith("AgendaViewer.php?view_id=9&clip_id=2620") and list(meetings.columns) == board.MEETING_COLUMNS

    butte = '''<tr class="listingRow"><td class="listItem" headers="Name" id="Board-of-Supervisors-Meeting" scope="row">
          Board of Supervisors Meeting </td>
        <td class="listItem" headers="Date Board-of-Supervisors-Meeting"> May&nbsp;14,&nbsp;2024 - 09:00&nbsp;AM </td>
        <td class="listItem"><a href="//buttecounty.granicus.com/MinutesViewer.php?view_id=2&amp;clip_id=1374&amp;doc_id=d619e9e3">Minutes</a></td></tr>'''
    row = board.meetings_table("butte-county", butte).iloc[0]
    assert (row["date"], row["time"], row["body"]) == ("2024-05-14", "9:00 AM", "Board of Supervisors")
    assert row["minutes_url"] == "https://buttecounty.granicus.com/MinutesViewer.php?view_id=2&clip_id=1374&doc_id=d619e9e3"

    marin = '''<tr class="listingRow"><td class="listItem" headers="Month" id="BOS-MEETING-260623" scope="row"><strong>June</strong></td>
        <td class="listItem" headers="Name" id="BOS-MEETING-260623"
            scope="row"> Board of Supervisors 2026 </td>
        <td class="listItem" headers="Date BOS-MEETING-260623"><span style="display:none;">1782198000</span>06/23/26 </td>
        <td class="listItem"><a href="//marin.granicus.com/MinutesViewer.php?view_id=33&clip_id=13163&doc_id=aad7">Minutes</a></td></tr>'''
    marin += '''<tr class="odd"><td class="listItem" headers="Name" id="BOS-250708---En-Español" scope="row"><strong>July</strong></td>
        <td class="listItem" headers="Name" id="BOS-250708---En-Español" scope="row"> Spanish Audio Files </td>
        <td class="listItem" headers="Date BOS-250708"><span style="display:none;">1751958000</span>07/08/25 </td>
        <td><a onClick="window.open('//marin.granicus.com/MediaPlayer.php?view_id=33&clip_id=12679')">Video</a></td></tr>
      <tr class="even"><td class="listItem" headers="Name" scope="row"> </td><td class="listItem" headers="Name" scope="row">Budget 2025</td>
        <td class="listItem" headers="Date Budget">06/16/25</td>
        <td><a href="//marin.granicus.com/MinutesViewer.php?view_id=33&clip_id=12650&doc_id=9f">Minutes</a></td></tr>'''
    meetings = board.meetings_table("marin-county", marin)
    # A budget hearing is the Board's, listed apart; the Spanish recording of a meeting is not another meeting.
    assert meetings[["meeting_id", "date", "body", "name"]].values.tolist() == [
        ["12650", "2025-06-16", "Board of Supervisors", "Budget 2025"], ["13163", "2026-06-23", "Board of Supervisors", "Board of Supervisors 2026"]]


# ---------------------------------------------------------------------------
# Minutes
# ---------------------------------------------------------------------------

def test_a_page_is_read_as_lines_with_a_label_joined_to_what_it_labels():
    glenn = '''<table><tbody><tr><td vAlign=top width=50><div>3. </div></td><td><div><a class="Agenda"><strong>CONSENT&nbsp;CALENDAR</strong></a></div>
      <table><tr><td width=100>Motion/Second: </td><td>Supervisor Rossman/Supervisor Withrow</td></tr>
      <tr><td width=100>Order: </td><td></td></tr></table><table><tr><td>Vote:</td><td>Ayes: Supervisor Rossman, and Supervisor Withrow. </td></tr></table>
      <div>Absent:</div><div>4.</div><script>var x = "<div>not a line</div>";</script><!-- <td>nor this</td> --></td></tr></tbody></table>'''
    assert board.lines_of(glenn) == ["3.", "CONSENT CALENDAR", "Motion/Second: Supervisor Rossman/Supervisor Withrow", "Order:",
                                     "Vote: Ayes: Supervisor Rossman, and Supervisor Withrow.", "Absent:", "4."]


def test_a_unanimous_vote_names_no_one_and_no_one_is_put_down_for_it():
    lines, votes = read(
        "glenn-county", GLENN,
        "1.", "ROLL CALL", "Supervisors Present: Supervisors Arendt, Carmon, Rossman, Yoder, and Withrow", "Supervisors Absent: None",
        "3.", "CONSENT CALENDAR", "Matter:", "The Consent Calendar groups together those items which are considered noncontroversial.",
        "a.", "ASSESSOR - ASSESSMENT ROLL CORRECTIONS", "Authorize the Assessor to make adjustments.", "Documents:", "Board Report",
        "b.", "PUBLIC WORKS - RESOLUTION / ROADS", "Adopt Resolution 2026-063.",
        "Motion/Second:", "Supervisor Rossman/Supervisor Withrow", "Order:", "Approve the Consent Calendar.", "Vote:", "Unanimous.",
        "5.", "PUBLIC WORKS - LEASE AGREEMENT", "Proceedings:", "a. The Director reviewed the aforesaid matter;",
        "c. On motion of Supervisor Arendt, seconded by Supervisor Withrow, it was unanimously ordered to approve the aforesaid matter as amended.",
        "6.", "CLOSED SESSION")
    assert votes == []  # five were present and the vote was unanimous: the minutes still do not say who voted
    consent = lines["3"]
    assert (consent["heading"], consent["action"], consent["mover"], consent["seconder"]) == (True, "Approve the Consent Calendar.", "Rossman", "Withrow")
    assert (consent["result"], consent["unanimous"], consent["named"], consent["motions"], consent["motions_named"]) == ("Pass", True, False, 1, 0)
    assert (consent["ayes"], consent["noes"], consent["not_voting"], consent["tally"]) == (0, 0, 0, "")
    # The motion written at the foot of the consent calendar is the calendar's, not its last item's.
    assert lines["b"]["motions"] == 0 and lines["b"]["section_id"] == consent["item_id"] and lines["b"]["number"] == "Resolution 2026-063"
    assert (lines["5"]["mover"], lines["5"]["seconder"], lines["5"]["result"], lines["5"]["unanimous"]) == ("Arendt", "Withrow", "Pass", True)
    assert lines["5"]["action"] == "it was unanimously ordered to approve the aforesaid matter as amended."
    assert lines["1"]["motions"] == 0 and "Supervisors Present" in lines["1"]["description"]
    assert json.loads(consent["motion_log"])[0]["unanimous"] is True and lines["6"]["motion_log"] == ""


def test_a_divided_vote_is_read_by_name_with_each_word_given_one_spelling():
    lines, votes = read(
        "glenn-county", GLENN,
        "7.", "Resolution - Fees", "Motion/Second:", "Supervisor Quarne/Supervisor Viegas", "Order:", "Adopt Resolution 2009-15.",
        "Vote:", "Ayes: Supervisor Quarne, Supervisor Murray, Supervisor Soeth, and Supervisor Viegas.", "Noes: Supervisor McDaniel.",
        "8.", "Ordinance - Franchise", "Proceedings:",
        "h. On motion of Supervisor McDaniel, seconded by Supervisor Foltz, it was ordered to introduce Ordinance by reading title by the following vote: "
        "Ayes: Supervisors McDaniel, Foltz, Soeth, and Viegas", "Recused: Supervisor Murray",
        "9.", "Budget", "d. On motion of Supervisor Quarne, seconded by Supervisor Murray, the motion to approve the aforesaid matter failed by the following roll call vote:",
        "Ayes: Supervisor Quarne", "Noes: Supervisors McDaniel, Soeth, and Murray.", "Absent: None", "Abstain: Spervisors Viegas",
        "10.", "Minutes", "On motion of Supervisor Corum, seconded by Supervisor Carmon, it was ordered by members present to approve the Minutes by the following Roll Call Vote:",
        "AYES: Supervisors Carmon, Arnold, Corum and Barr", "NOES: None", "ABSENT: Supervisor Hahn",
        "b. The Chairman thanked staff.", "Absent: David Shoemaker, County Administrative Officer")
    assert cast(votes, lines["7"]["item_id"]) == [("Quarne", "AYE"), ("Murray", "AYE"), ("Soeth", "AYE"), ("Viegas", "AYE"), ("McDaniel", "NO")]
    assert (lines["7"]["ayes"], lines["7"]["noes"], lines["7"]["result"], lines["7"]["named"]) == (4, 1, "", True)  # they do not say it carried
    assert cast(votes, lines["8"]["item_id"])[-1] == ("Murray", "RECUSED") and lines["8"]["not_voting"] == 1 and lines["8"]["result"] == "Pass"
    assert cast(votes, lines["9"]["item_id"]) == [("Quarne", "AYE"), ("McDaniel", "NO"), ("Soeth", "NO"), ("Murray", "NO"), ("Viegas", "ABSTAIN")]
    assert lines["9"]["result"] == "Fail" and lines["9"]["action"] == "the motion to approve the aforesaid matter failed"
    # What is written after the vote is over is not part of it.
    assert cast(votes, lines["10"]["item_id"]) == [("Carmon", "AYE"), ("Arnold", "AYE"), ("Corum", "AYE"), ("Barr", "AYE"), ("Hahn", "ABSENT")]
    assert {vote["vote"] for vote in votes} == {"AYE", "NO", "ABSTAIN", "ABSENT", "RECUSED"}
    assert all(vote["matter_id"] == vote["item_id"] and vote["date"] == "2026-08-18" and vote["meeting_id"] == "2620" for vote in votes)


def test_a_roll_call_written_one_member_to_a_line_is_one_vote_and_a_later_motion_is_another():
    lines, votes = read(
        "glenn-county", GLENN,
        "16.", "DEPUTY COUNTY COUNSEL", "Proceedings:", "a. Supervisor Corum made a motion to approve;", "n. Motion in (j) above failed by the following roll call vote:",
        "Supervisor Corum - Nay", "Superisor Foltz - Noe", "Supervisor McDaniel - Aye", "Superviso Minto: Yes", "Supervsor Viegas: No",
        "o. On motion of Supervisor Foltz, seconded by Supervisor Corum, it was ordered to continue the matter by the following vote:",
        "Ayes: Supervisors Corum, Foltz and Viegas Noes: Supervisor Minto", "Supervisor McDaniel abstained and left the room.")
    item = lines["16"]["item_id"]
    assert cast(votes, item, 1) == [("Corum", "NO"), ("Foltz", "NO"), ("McDaniel", "AYE"), ("Minto", "AYE"), ("Viegas", "NO")]
    assert cast(votes, item, 2) == [("Corum", "AYE"), ("Foltz", "AYE"), ("Viegas", "AYE"), ("Minto", "NO")]  # the abstention is prose, and not read
    log = json.loads(lines["16"]["motion_log"])
    assert [(motion["result"], motion["mover"], motion["named"]) for motion in log] == [("Fail", "", True), ("Pass", "Foltz", True)]
    assert (lines["16"]["motions"], lines["16"]["motions_named"], lines["16"]["ayes"], lines["16"]["noes"]) == (2, 2, 3, 1)


def test_a_list_of_votes_is_the_motions_it_is_announced_for_or_a_vote_of_its_own():
    lines, votes = read(
        "glenn-county", GLENN,
        "17.", "PUBLIC WORKS - LAND LEASE", "Proceedings:",
        "g. On motion of Supervisor Minto, seconded by Supervisor Barr, it was ordered to approve the aforesaid matter;",
        "h. Supervisor McDaniel asked if there was any further discussion, whereby hearing none, the motion passed with the following Roll Call vote:",
        "i. AYES: Supervisor Barr, Viegas, Corum, Minto, and McDaniel", "ii. NOES: None", "iii. ABSENT or ABSTAIN: None",
        "19.", "PUBLIC WORKS - STUDY SESSION", "Proceedings:", "j. A resident spoke in favor of the matter;",
        "k. It was the consensus of the Board to continue discussions regarding the lease criteria by the following vote:",
        "AYES: Supervisors Arendt, Withrow, and Yoder", "NOES: Supervisors Carmon and Rossman",
        "20.", "MINUTES", "a. On motion of Supervisor Yoder, seconded by Supervisor Carmon, it was unanimously ordered to approve the Minutes;",
        "b. The Clerk read a resolution into the record, which had passed by this vote:", "AYES: SUPERVISOR RODONI, SUPERVISOR MOULTON-PETERS. Supervisor Rice")
    # One motion, moved by Minto and voted on by name two lines later: not a motion with no names and a vote with no mover.
    assert (lines["17"]["motions"], lines["17"]["mover"], lines["17"]["seconder"], lines["17"]["result"], lines["17"]["named"]) == (1, "Minto", "Barr", "Pass", True)
    assert cast(votes, lines["17"]["item_id"]) == [(name, "AYE") for name in ("Barr", "Viegas", "Corum", "Minto", "McDaniel")]
    assert (lines["19"]["motions"], lines["19"]["mover"], lines["19"]["result"], lines["19"]["ayes"], lines["19"]["noes"]) == (1, "", "", 3, 2)
    assert lines["19"]["action"] == "It was the consensus of the Board to continue discussions regarding the lease criteria"
    # A motion that carried unanimously is not given the names of a list that comes after it.
    log = json.loads(lines["20"]["motion_log"])
    assert [(motion["mover"], motion["unanimous"], motion["named"]) for motion in log] == [("Yoder", True, False), ("", False, True)]
    assert cast(votes, lines["20"]["item_id"], 2) == [("Rodoni", "AYE"), ("Moulton-Peters", "AYE"), ("Rice", "AYE")]


def test_minutes_with_no_numbered_lines_keep_their_motions_under_the_pages_heading():
    agenda, votes = board.read_minutes("marin-county", MARIN, page(
        "BUDGET MEETING OF THE MARIN COUNTY BOARD OF SUPERVISORS HELD MONDAY, JUNE 18, 2018", "Roll Call", "Present:", "Supervisor Rodoni; Supervisor Rice",
        "Public Comment", "M/s Supervisor Sears - Supervisor Rice to adopt the FY 2018-19 Proposed Budget.", "AYES:", "Supervisor Sears, Supervisor Rice", "ABSENT:", "Supervisor Arnold"))
    assert [(row["item_id"], row["agenda_number"], row["title"][:14], row["motions"], row["mover"], row["heading"]) for row in agenda] == [
        ("4881-1", "", "BUDGET MEETING", 1, "Sears", False)]
    assert cast(votes) == [("Sears", "AYE"), ("Rice", "AYE"), ("Arnold", "ABSENT")]
    # The head of a page is not a line of the agenda where nothing was moved there, and a page of nothing is nothing.
    agenda, votes = board.read_minutes("marin-county", MARIN, page("REGULAR MEETING", "Roll Call", "1.", "Open time"))
    assert [(row["item_id"], row["agenda_number"]) for row in agenda] == [("4881-1", "1")]
    assert board.read_minutes("marin-county", MARIN, page("REGULAR MEETING", "Minutes to follow.")) == ([], [])
    assert board.read_minutes("marin-county", MARIN, "") == ([], [])


def test_buttes_consent_agenda_its_separate_votes_and_the_notes_at_the_foot_of_the_page():
    lines, votes = read(
        "butte-county", BUTTE,
        "1.", "CALL TO ORDER", "3B.", "ADOPT CONSENT AGENDA",
        "Action: Adoption of the Consent Agenda with an exception to item 3.02 which Supervisor Durfee recused himself.",
        "Motion: Supervisor Teeter", "Seconded: Supervisor Durfee", "Motion passed unanimously.",
        "Item 3.02", "Motion passed 4-0-1", "Ayes: Supervisor Connelly, Ritter, Teeter & Chair Kimmelshue", "Nays: None", "Recused: Supervisor Durfee",
        "3.01", "Approval of Minutes", "Action Requested - APPROVE THE MINUTES",
        "3.02", "Budget Adjustment for County Service Area 87", "Action Requested - APPROVE BUDGET ADJUSTMENT (4/5 VOTE REQUIRED)",
        "4.", "REGULAR AGENDA", "4.01", "Boards, Commissions, and Committees", "A.", "Appointment to Listed Vacancies", "1)", "Cemetery District",
        "Action: APPOINT LARENCE HAMMAN.", "Motion: Supervisor Ritter", "Seconded: Supervisor Teeter", "Motion passed unanimously.", "Staff Report",
        "4.02", "Water Wells Ordinance", "Motion: Waive the first reading of the ordinance.",
        "Motion moved for approval by Supervisor Kimmelshue; Seconded by Supervisor Lucero.", "Motion passed 3-2.",
        "Ayes: Supervisors Lucero, Ritter, Lucero and Kimmelshue", "Nayes: Supervisor Teeter and Chair Connelly",
        "4.03", "Contract", "Action: APPROVE CONTRACT", "Motion: Supervisor Teeter", "Seconded: Supervisor Durfee",
        "Ayes: Supervisor Teeter, Durfee, and Chair Kimmelshue", "Nays: Supervisor Connelly and Supervisor Ritter", "Motion Failed - Directed Staff to develop a policy.",
        "4.04", "Lien", "Motion: Supervisor Durfee", "Seconded: Supervisor Teeter", "Absent: Chair Kimmelshue",
        "Motion passed by a 4-0-1 Vote (Ayes: Supervisors Connelly, Durfee, Ritter and Vice-Chair Teeter; Nays: None; Absent: Chair Kimmelshue)",
        "Housing Authority Approved appointment of Rich Ober to the District 3 Seat. (Vote 4-0-1 Ayes: Supervisors Connelly, Durfee, Ritter and Chair Kimmelshue; Absent: None; Nays: Supervisor Teeter)",
        "4.05", "Update", "Action requested - ACCEPT FOR INFORMATION",
        "1.", "Consent Agenda: These items are considered routine and are handled by one motion and vote of the Board.", "2.", "Public Comment: This is the area")
    assert list(lines) == ["1", "3B", "3.01", "3.02", "4", "4.01", "A", "1)", "4.02", "4.03", "4.04", "4.05"]  # the notes are not the agenda
    consent = lines["3B"]
    assert (consent["heading"], consent["motions"], consent["result"], consent["unanimous"], consent["mover"]) == (True, 1, "Pass", True, "Teeter")
    # The vote on the item taken apart is on that item's own line, with the count the minutes give and the names.
    apart = lines["3.02"]
    assert (apart["action"], apart["tally"], apart["ayes"], apart["noes"], apart["not_voting"], apart["mover"]) == ("Item 3.02", "4-0-1", 4, 0, 1, "")
    assert cast(votes, apart["item_id"]) == [("Connelly", "AYE"), ("Ritter", "AYE"), ("Teeter", "AYE"), ("Kimmelshue", "AYE"), ("Durfee", "RECUSED")]
    assert lines["3.01"]["motions"] == 0 and lines["3.01"]["section_id"] == consent["item_id"]
    assert (lines["1)"]["action"], lines["1)"]["mover"], lines["1)"]["seconder"], lines["1)"]["named"]) == ("APPOINT LARENCE HAMMAN.", "Ritter", "Teeter", False)
    assert lines["1)"]["section"] == "Appointment to Listed Vacancies" and lines["4.01"]["heading"] and not lines["4.02"]["heading"]
    # Lucero's aye is written twice under 4.02 and kept once.
    assert cast(votes, lines["4.02"]["item_id"]) == [("Lucero", "AYE"), ("Ritter", "AYE"), ("Kimmelshue", "AYE"), ("Teeter", "NO"), ("Connelly", "NO")]
    assert (lines["4.02"]["action"], lines["4.02"]["mover"], lines["4.02"]["seconder"], lines["4.02"]["tally"]) == (
        "Waive the first reading of the ordinance.", "Kimmelshue", "Lucero", "3-2")
    assert (lines["4.03"]["result"], lines["4.03"]["ayes"], lines["4.03"]["noes"], lines["4.03"]["motions"]) == ("Fail", 3, 2, 1)
    # "Absent:" written above the vote and again inside it is one absence, on one motion; the appointment after it is another.
    assert cast(votes, lines["4.04"]["item_id"], 1) == [("Kimmelshue", "ABSENT"), ("Connelly", "AYE"), ("Durfee", "AYE"), ("Ritter", "AYE"), ("Teeter", "AYE")]
    assert cast(votes, lines["4.04"]["item_id"], 2) == [("Connelly", "AYE"), ("Durfee", "AYE"), ("Ritter", "AYE"), ("Kimmelshue", "AYE"), ("Teeter", "NO")]
    assert (lines["4.04"]["motions"], lines["4.04"]["result"], lines["4.04"]["tally"], lines["4.04"]["mover"]) == (2, "Pass", "4-0-1", "")
    assert json.loads(lines["4.04"]["motion_log"])[0]["mover"] == "Durfee" and lines["4.04"]["action"].startswith("Housing Authority Approved appointment")
    assert lines["4.05"]["motions"] == 0
    assert not pd.DataFrame(votes).duplicated(["item_id", "motion", "member"]).any()


def test_a_vote_on_the_older_consent_agenda_is_the_headings():
    lines, votes = read(
        "butte-county", BUTTE,
        "3.", "CONSENT AGENDA", "A.", "Supervisor Comments on Consent Agenda Items", "None", "B.", "Adopt Consent Agenda",
        "Motion to approve the Consent Agenda: Motioned by Supervisor Lucero, Seconded by Supervisor Ritter. Consent agenda was unanimously approved.",
        "3.01", "Approval of Minutes", "5.01.", "A tentative map", "Motion to approve. Moved by Supervisor Teeter, seconded Ritter. Motion passed 4-1.")
    assert (lines["3"]["motions"], lines["3"]["mover"], lines["3"]["seconder"], lines["3"]["result"], lines["3"]["unanimous"]) == (1, "Lucero", "Ritter", "Pass", True)
    assert lines["B"]["motions"] == 0 and lines["3.01"]["section_id"] == lines["3"]["item_id"]
    assert (lines["5.01"]["mover"], lines["5.01"]["seconder"], lines["5.01"]["tally"], lines["5.01"]["ayes"], lines["5.01"]["noes"]) == ("Teeter", "Ritter", "4-1", 4, 1)
    assert votes == []  # a count with no names is a count


def test_marins_motions_and_the_votes_under_them():
    lines, votes = read(
        "marin-county", MARIN,
        "5.", "Consent Calendar A (Items CA-1 through CA-2)", "M/s Supervisor Sears - Supervisor Rice to approve Consent Calendar A as presented.",
        "CA-1.", "Board of Supervisors:", "a.", "Approval of minutes.", "CA1a - MINUTES", "CA-2.", "Registrar of Voters: Request to adopt Resolution No. 2017-63.",
        "AYES:", "ALL",
        "9.", "Health Council of Marin annual report", "9 - STAFF REPORT",
        "M/s Supervisor Kinsey - Supervisor Sears to accept report and adopt Resolution No. 2011-72.", "A member of the public expressed support.",
        "Thereafter, the vote on the pending motion was", "Vote:", "Motion carried 3-1", "AYES:", "Supervisor Sears, Supervisor Kinsey, Supervisor Adams",
        "NOES:", "Supervisor Arnold", "ABSENT:", "Supervisor Brown", "(Supervisor Brown present at 11:08 a.m.)",
        "10.", "Appointments", "a.", "Parks Commission", "M/s - ", "AYES:", "ALL", "b.", "Library Commission",
        "M/s Supervisor Moulton-Peters - Supervisor Arnold to reappoint Ann Smith.", "AYES:", "Supervisor Moulton-Peters, Supervisor Arnold", "ABSENT:", "12.", "Adjournment")
    consent = lines["5"]
    # The motion is moved under the heading and voted on at the foot of it, after its items: it is the heading's.
    assert (consent["motions"], consent["mover"], consent["seconder"], consent["result"], consent["unanimous"], consent["named"]) == (1, "Sears", "Rice", "Pass", True, False)
    assert lines["CA-2"]["motions"] == 0 and lines["CA-2"]["number"] == "Resolution 2017-63" and lines["CA-1"]["heading"]
    assert cast(votes, consent["item_id"]) == []  # "AYES: ALL" does not say who
    assert cast(votes, lines["9"]["item_id"]) == [("Sears", "AYE"), ("Kinsey", "AYE"), ("Adams", "AYE"), ("Arnold", "NO"), ("Brown", "ABSENT")]
    assert (lines["9"]["tally"], lines["9"]["ayes"], lines["9"]["noes"], lines["9"]["not_voting"], lines["9"]["result"]) == ("3-1", 3, 1, 1, "Pass")
    assert lines["9"]["action"] == "to accept report and adopt Resolution No. 2011-72."
    letters = [row for row in board.read_minutes("marin-county", MARIN, page(
        "10.", "Appointments", "a.", "Parks Commission", "M/s - ", "AYES:", "ALL", "b.", "Library Commission",
        "M/s Supervisor Moulton-Peters - Supervisor Arnold to reappoint Ann Smith.", "AYES:", "Supervisor Moulton-Peters, Supervisor Arnold", "ABSENT:", "12.", "Adjournment"))[0]]
    assert [(row["agenda_number"], row["motions"], row["motions_named"], row["mover"]) for row in letters] == [
        ("10", 0, 0, ""), ("a", 1, 0, ""), ("b", 1, 1, "Moulton-Peters"), ("12", 0, 0, "")]  # "ABSENT:" with nobody under it, above "12."


def test_a_motion_that_names_a_heading_is_the_headings_wherever_the_page_prints_it():
    lines, votes = read(
        "marin-county", MARIN,
        "3.", "Consent Calendar A (Items CA-1 through CA-2)", "CA - 1. Board of Supervisors", "a.", "Request to adopt resolution.", "b.", "Request to execute agreement.",
        "M/s Supervisor Rodoni - Supervisor Moulton-Peters 3. Consent Calendar A (Items CA-1 through CA-2)",
        "Vote:", "Motion carried 4-0", "AYES:", "Supervisor Rodoni, Supervisor Arnold, Supervisor Moulton-Peters, Supervisor Rice", "ABSENT:", "Supervisor Connolly",
        "4.", "Open time")
    assert lines["b"]["motions"] == 0 and lines["3"]["motions"] == 1 and lines["CA-1"]["title"] == "Board of Supervisors"
    assert cast(votes, lines["3"]["item_id"])[-1] == ("Connolly", "ABSENT") and len(votes) == 5 and lines["3"]["ayes"] == 4


def test_a_list_of_names_keeps_only_what_is_plainly_a_name():
    assert board.names_of("Supervisor Connelly, Ritter, Teeter & Chair Kimmelshue") == (["Connelly", "Ritter", "Teeter", "Kimmelshue"], True)
    assert board.names_of("Supervisors Rodoni, Moulton-Peters and Vice-Chair Teeter.") == (["Rodoni", "Moulton-Peters", "Teeter"], True)
    assert board.names_of("None") == ([], True) and board.names_of("") == ([], True)
    assert board.names_of("ALL") == ([], False) and board.names_of("Unanimous") == ([], False)
    # A title, a sentence, a number, or two names run together with no comma: none is put down as a member.
    assert board.names_of("David Shoemaker, County Administrative Officer") == ([], True)
    assert board.names_of("Supervisors Corum Minto and Viegas (by phone); 4") == (["Viegas"], True)
    assert board.person("Supervisor De Moss said he would") == "" and board.person("Board Member Hahn") == "Hahn"
    assert [word for word, _, _ in board.votes_in("Yeas: Supervisor A. Noe: None. Abstained: Supervisor Bee, Recusals: Supervisor Cee")] == ["AYE", "NO", "ABSTAIN", "RECUSED"]
    assert board.said_in("Supervisors Present: Supervisors Arendt and Carmon. Absent: Supervisor Yoder") == {}
    assert board.said_in("Action Requested - APPROVE CONTRACT AND AUTHORIZE CHAIR TO SIGN") == {}


# ---------------------------------------------------------------------------
# Asking the county's pages, and the tables
# ---------------------------------------------------------------------------

class Answer:
    def __init__(self, status=200, kind="text/html; charset=utf-8", text="<p>minutes</p>"):
        self.status_code, self.headers, self.text, self.encoding, self.read = status, {"content-type": kind}, text, "utf-8", False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass


def test_minutes_filed_as_a_pdf_are_not_downloaded_and_a_host_that_refuses_is_asked_no_more(monkeypatch):
    asked = []
    answers = {"https://a.granicus.com/m": Answer(), "https://a.granicus.com/pdf": Answer(kind="application/pdf"),
               "https://b.granicus.com/m": Answer(status=403), "https://c.granicus.com/m": Answer(text="<title>Just a moment...</title>")}

    def get(url, headers, timeout, stream):
        assert stream and headers == board.county.HEADERS  # the repository's own name for itself, and nothing dressed up
        asked.append(url)
        return answers[url]

    monkeypatch.setattr(board.requests, "get", get)
    monkeypatch.setattr(board, "REFUSED", set())
    assert board.fetch("https://a.granicus.com/m") == "<p>minutes</p>"
    assert board.fetch("https://a.granicus.com/pdf") == ""
    for host in ("b", "c"):
        with pytest.raises(board.Refused):
            board.fetch(f"https://{host}.granicus.com/m")
        with pytest.raises(board.Refused):
            board.fetch(f"https://{host}.granicus.com/m")
    assert asked.count("https://b.granicus.com/m") == 1 and asked.count("https://c.granicus.com/m") == 1
    assert board.REFUSED == {"b.granicus.com", "c.granicus.com"}


def listing(*meetings):
    return "<table>" + "".join(
        f'<tr><td headers="Name">{name}</td><td headers="Date x">{day}</td>'
        + (f'<td><a href="//glenncounty.granicus.com/MinutesViewer.php?view_id=9&clip_id={clip}">Minutes</a></td>' if minutes else "")
        + f'<td><a href="//glenncounty.granicus.com/AgendaViewer.php?view_id=9&clip_id={clip}">Agenda</a></td></tr>'
        for clip, name, day, minutes in meetings) + "</table>"


def test_a_run_reads_the_newest_first_and_does_not_read_again_what_it_has_read(monkeypatch, tmp_path):
    minutes = {
        "101": page("1.", "Fees", "Motion/Second:", "Supervisor Amaro/Supervisor Hansen", "Order:", "Approve.", "Vote:", "Ayes: Supervisor Amaro, Supervisor Hansen.", "Noes: Supervisor Murray."),
        "102": "",  # a PDF
        "103": page("1.", "CONSENT CALENDAR", "a.", "Contract", "b.", "Resolution 2010-44", "Motion/Second:", "Supervisor Murray/Supervisor Amaro", "Order:", "Approve.", "Vote:", "Unanimous.",
                    "2.", "Appeal", "On motion of Supervisor Hansen, seconded by Supervisor Murray, it was ordered to deny the appeal by the following vote:",
                    "Ayes: Supervisors Hansen and Murray", "Noes: Supervisor Amaro", "Abstain: Supervisor Typo"),
    }
    rows = [(str(clip), "Board of Supervisors", day, has) for clip, day, has in
            ((101, "Jan 5, 2010", True), (102, "Feb 2, 2010", True), (103, "Mar 2, 2010", True), (104, "Apr 6, 2010", False))]
    rows += [(str(200 + n), "Board of Supervisors", f"May {n + 1}, 2011", False) for n in range(8)]
    asked = []

    def fetch(url):
        if "ViewPublisher" in url:
            return listing(*rows)
        asked.append(url.split("clip_id=")[1])
        return minutes[asked[-1]]

    monkeypatch.setattr(board, "fetch", fetch)
    monkeypatch.setattr(board.county, "together", lambda function, things, what: [function(thing) for thing in things])
    monkeypatch.setattr(council_tables, "published", lambda repo, name: None)
    tables, read = board.build("glenn-county", True, False, tmp_path)
    assert asked == ["103", "102", "101"] and read == 3
    for name in council_tables.TABLES:
        assert list(tables[name].columns)[:len(council_tables.COLUMNS[name])] == council_tables.COLUMNS[name]
        assert (tmp_path / f"{name}.parquet").exists()
    meetings = tables["meetings"].set_index("meeting_id")
    assert meetings.loc[["101", "102", "103", "104"], "minutes_format"].tolist() == ["html", "pdf", "html", ""]
    assert meetings.loc[["101", "102", "103"], "items"].tolist() == [1, 0, 3]
    assert board.motions_of(tables["agenda_items"]) == (3, 2)
    # Amaro, Hansen and Murray each voted on two days; the name seen once is in the votes and is not a member.
    assert tables["members"]["name"].tolist() == ["Amaro", "Hansen", "Murray"] and "Typo" in set(tables["votes"]["member"])
    assert tables["members"].set_index("name").loc["Amaro", ["first_vote", "last_vote", "votes"]].tolist() == ["2010-01-05", "2010-03-02", 2]
    items = tables["items"].set_index("item_id")
    # An item under the consent calendar carries the calendar's motion, and says that it is the calendar's.
    assert items.loc["103-3", ["last_action", "result", "mover", "action_on", "unanimous", "named", "ayes"]].tolist() == ["Approve.", "Pass", "Murray", "section", True, False, 0]
    assert items.loc["103-4", ["action_on", "ayes", "noes", "result", "passed_date"]].tolist() == ["item", 2, 1, "Pass", ""]
    assert "103-1" not in items.index and items.loc["103-3", "doc_type"] == "resolution"
    assert items.loc["101-1", "url"].endswith("MinutesViewer.php?view_id=9&clip_id=101")

    # A second run asks for nothing it has read, the PDF among them; the minutes of 104, now posted, are new to it.
    asked.clear()
    rows[3] = ("104", "Board of Supervisors", "Apr 6, 2010", True)
    minutes["104"] = page("1.", "Budget", "Motion/Second:", "Supervisor Hansen/Supervisor Amaro", "Order:", "Approve.", "Vote:", "Unanimous by members present.")
    tables, read = board.build("glenn-county", True, False, tmp_path)
    assert asked == ["104"] and read == 1 and len(tables["votes"]) == 7 and board.motions_of(tables["agenda_items"]) == (4, 2)
    asked.clear()
    assert board.build("glenn-county", True, True, tmp_path)[1] == 4 and asked == ["104", "103", "102", "101"]  # --all

    text = board.card("glenn-county", tables)
    assert "{" not in text.split("---", 2)[2].replace("{id}", "") and "chrissoria/glenn-county-board" in text
    assert "4 motions. For 2 of them (50%)" in " ".join(text.split()) and "The minutes of 1 are filed as a PDF" in " ".join(text.split())


def test_a_run_stops_where_the_host_answers_with_a_bot_check(monkeypatch, tmp_path):
    def fetch(url):
        if "ViewPublisher" in url:
            return listing(*[(str(n), "Board of Supervisors", f"May {n}, 2011", True) for n in range(1, 13)])
        board.REFUSED.add("glenncounty.granicus.com")
        raise board.Refused("glenncounty.granicus.com answered 403")

    monkeypatch.setattr(board, "fetch", fetch)
    monkeypatch.setattr(board, "REFUSED", set())
    monkeypatch.setattr(council_tables, "published", lambda repo, name: None)
    with pytest.raises(board.Refused):
        board.build("glenn-county", True, False, tmp_path)
    assert board.main(["--county", "glenn-county", "--base", "--no-upload", "--out", str(tmp_path)]) == 1


def test_every_county_has_what_the_reader_needs_and_a_dataset_of_its_own():
    assert set(board.BOARDS) == {"glenn-county", "butte-county", "marin-county", "imperial-county"}
    # Butte's record here is the one it kept before CivicClerk: the earlier part of its tables among the county boards.
    assert board.repo_of("butte-county") == "chrissoria/butte-county-earlier-board" and board.repo_of("marin-county") == "chrissoria/marin-county-board"
    for key, county in board.BOARDS.items():
        assert county["host"].endswith(".granicus.com") and county["view"] and county["numbers"]
        assert board.re.search(county["board"], "Board of Supervisors")
