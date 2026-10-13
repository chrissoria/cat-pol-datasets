"""build_iqm2_board reads a county's meeting portal page by page: the calendar, a meeting, and each item and motion on it."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import build_iqm2_board as board
import council_tables

KEY = "sutter-county"

# Pieces of the portal's pages, cut down from ones read on 2026-10-12. The markup is the portal's own, slips and all.
CALENDAR = """
<div id="ContentPlaceholder1_pnlMeetings" class="Section">
<div class="Row MonthHeader">April, 2026</div>
<div class="Row MeetingRow" id="divRow"><div class="RowTop">
  <div class="RowLink"><a href="/Citizens/Detail_Meeting.aspx?ID=3019" title="TUESDAY, APRIL 14, 2026  3:00 PM&#13;&#13;Board:&#09;Board of Supervisors&#13;Type:&#09;Regular Session&#13;Status:&#09;Closed&#13;&#13;&#09;City Council Chambers&#13;&#09;1201 CIVIC CENTER BLVD., YUBA CITY, CA  95993" >Apr 14, 2026 3:00 PM </a></div>
  <div class="RowRight MeetingLinks">
    <div>&nbsp;<a href='FileOpen.aspx?Type=14&ID=2529&Inline=True' class='' target='_blank'>Agenda</a>&nbsp;</div>
    <div>&nbsp;<a href='FileOpen.aspx?Type=1&ID=2529&Inline=True' class='' target='_blank'>Agenda Packet</a>&nbsp;</div>
    <div>&nbsp;<a href='FileOpen.aspx?Type=15&ID=1981&Inline=True' class='' target='_blank'>Summary of Proceedings</a>&nbsp;</div>
    <div>&nbsp;<a href='FileOpen.aspx?Type=12&ID=1981&Inline=True' class='' target='_blank'>Minutes</a>&nbsp;</div>
    <div class="WithoutSeparator">&nbsp;<a href="#" class="HiddenDocumentLink">Video</a>&nbsp;</div>
  </div></div>
  <div class="RowBottom"><div class="MainScreenText RowDetails">Board of Supervisors - Regular Session</div></div></div>
<div class="Row MeetingRow Alt"><div class="RowTop">
  <div class="RowLink"><a href="/Citizens/Detail_Meeting.aspx?ID=3118" title="MONDAY, APRIL 20, 2026  10:00 AM&#13;&#13;Board:&#09;Real Estate Committee&#13;Type:&#09;Standing Committee Meeting&#13;Status:&#09;Cancelled&#13;&#13;&#09;1160 Civic Center Blvd., Suite A" >Apr 20, 2026 10:00 AM </a></div>
  <div class="RowRight MeetingLinks">
    <div>&nbsp;<a href='' class='HiddenDocumentLink' target=''>Agenda</a>&nbsp;</div>
    <div>&nbsp;<a href='' class='HiddenDocumentLink' target=''>Minutes</a>&nbsp;</div>
  </div></div></div>
<div class="Row MeetingRow"><div class="RowTop">
  <div class="RowLink"><a href="/Citizens/Detail_Meeting.aspx?ID=3120" title="TUESDAY, APRIL 21, 2026  12:00 AM&#13;&#13;Board:&#09;Board of Supervisors&#13;Type:&#09;Budget Hearing&#13;Status:&#09;Scheduled&#13;&#13;" >Apr 21, 2026 </a></div>
  <div class="RowRight MeetingLinks"></div></div></div>
</div>"""

MEETING = """
<span id="ContentPlaceholder1_lblOutline"><table id='MeetingDetail' class='MeetingDetail' cellpadding='0' cellspacing='0'>
<tr><td class='Num'><strong></strong></td><td class='Title' colspan='10'><strong>3:00 PM REGULAR MEETING/CALL TO ORDER</strong></td></tr>
<tr><td></td><td class='Num'></td><td class='Title' colspan='9'><a target='_top' class='Link'  href='Detail_Motion.aspx?Frame=&MeetingID=3019&MinutesID=1981&MediaPosition=270.238&ID=34789&Type=50&CssClass= style='cursor: hand'>Invocation</a></td></tr>
<tr><td class='Num'><strong></strong></td><td class='Title' colspan='10'><a target='_top' class='Link'  href='Detail_Motion.aspx?Frame=&MeetingID=3019&MinutesID=1981&MediaPosition=441.238&ID=34792&Type=100&CssClass= style='cursor: hand'><strong>CONSENT CALENDAR</strong></a></td></tr>
<tr><td></td><td class='Num'></td><td class='Title' colspan='9'>Clerk of the Board</td></tr>
<tr><td></td><td class='Num'>1. </td><td class='Title' colspan='9'><a target='_top' class='Link'  href='Detail_LegiFile.aspx?Frame=&MeetingID=3019&MediaPosition=441.238&ID=7639&CssClass='>Approval of two appointments (MT7639)</a><span class = 'ItemVoteResult'> Adopted By Consent Vote [Unanimous] </span><a class='DiscussionLink' href='#' onclick='javascript: return ShowItemDiscussion(10,7639);' title='Discuss this item'><img src='/Citizens/Images/Discussion_Empty.png' alt='Comment'></a></td></tr>
<tr><td></td><td></td><td class='Num'><img src='/Citizens/images/DocumentIcon.gif' alt='document'></td><td class='Title' colspan='8'><a href='FileOpen.aspx?Type=30&ID=32138&MeetingID=3019'>Agenda Item Printout</a></td></tr>
<tr><td></td><td></td><td class='Num'>a. </td><td class='Title' colspan='8'><a target='_blank' class='Link'  href='FileOpen.aspx?Type=4&ID=27031&MeetingID=3019'>Application Redacted</a></td></tr>
<tr><td class='Num'><strong></strong></td><td class='Title' colspan='10'><a target='_top' class='Link'  href='Detail_Motion.aspx?Frame=&MeetingID=3019&MinutesID=1981&MediaPosition=&ID=34840&Type=70&CssClass= style='cursor: hand'><strong>PUBLIC HEARING</strong></a></td></tr>
<tr><td></td><td class='Num'>12. </td><td class='Title' colspan='9'><a target='_top' class='Link'  href='Detail_LegiFile.aspx?Frame=&MeetingID=3019&MediaPosition=900&ID=7544&CssClass='>BOS-2026-5 : Public Hearing to consider an ordinance on speed limits</a></td></tr>
<tr><td></td><td></td><td></td><td class='Comments' colspan='8'>Possible action: a. Open the hearing.</td></tr>
<tr><td class='Num'><strong></strong></td><td class='Title' colspan='10'><strong>ADJOURNMENT</strong></td></tr>
</table></span>"""


def item_html(number, title, history):
    return f"""<div id="ContentPlaceholder1_pnlMain" class="LegiFileDetails DetailPage">
<div id="ContentPlaceholder1_lblLegiFileType">Agenda Item</div><div id="ContentPlaceholder1_lblResNum">{number}</div>
<span id="ContentPlaceholder1_lblStatus">Adopted</span>
<h1 id="ContentPlaceholder1_lblLegiFileTitle" class="LegiFileHeading"> {title}</h1>
<table id="tblLegiFileInfo"><tr><th><strong>Department</strong>:</th><td>Development Services</td><th><strong>Sponsors</strong>:</th><td></td></tr><tr><th><strong>Category</strong>:</th><td>Ordinance</td></tr></table>
<ol class="UndecoratedList"><li class="snapShotListItem"><a id='lnkDownload' href='/Citizens/FileOpen.aspx?Type=30&ID=32144' target='_blank'>Printout</a></li>
<li class="snapShotListItem"><span>Proposed Ordinance</span></li></ol>
<div id="ContentPlaceholder1_divHistory" class="LegiFileSection MeetingHistory"><table class="LayoutTable MeetingHistory">{history}</table></div></div>"""


def history_html(meeting_id, comments, *records):
    return f"""<tr class="HeaderRow HistorySection"><td class="Date"><a href="/Citizens/Detail_Meeting.aspx?ID={meeting_id}">Apr 14, 2026 3:00 PM</a></td></tr>
<tr class="VoteResultRow"><td colspan="4"><div class="Comments"><p>{comments}</p></div>{"".join(records)}</td></tr>"""


def record_html(result, *rows):
    return ("<table cellspacing='0' cellpadding='0' class='VoteRecord'>"
            f"<tr><td class='Role'>RESULT:</td><td class='Result'>{result}</td><td class='Next'></td></tr>"
            + "".join(f"<tr><td class='Role'>{role}:</td><td colspan='2'>{names}</td></tr>" for role, names in rows) + "</table>")


CONSENT_ITEM = item_html("7639", "Approval of two appointments (MT7639)", history_html("3019", "", record_html(
    "ADOPTED [UNANIMOUS]", ("MOVER", "Karm Bains, Vice Chair, District 4"), ("SECONDER", "Jeffrey K. Boone, District 1"),
    ("AYES", "Jeffrey K. Boone, Mike Ziegenmeyer, Karm Bains, Jeff Stephens"), ("ABSENT", "Dan Flores"))))
# An ordinance heard at an earlier meeting too, with the vote of this one entered twice and one member named twice.
HEARING_ITEM = item_html("7544", "Public Hearing to consider an ordinance on speed limits (MT7544)", (
    history_html("2990", "Introduced.", record_html("CONTINUED [UNANIMOUS]", ("MOVER", "Dan Flores, District 2"),
                                                    ("AYES", "Jeffrey K. Boone, Dan Flores, Mike Ziegenmeyer, Karm Bains, Jeff Stephens")))
    + history_html("3019", "The hearing was held.", *[record_html(
        "ADOPTED [3 TO 1]", ("MOVER", "Mike Ziegenmeyer, Chair, District 3"), ("SECONDER", "Jeff Stephens, District 5"),
        ("AYES", "Jeffrey K. Boone, Mike Ziegenmeyer, Jeff Stephens, Jeff Stephens"), ("NAYS", "Karm Bains"), ("RECUSED", "Dan Flores"))] * 2)))

MOTION = """<span id="ContentPlaceholder1_lblTitle"><b>CONSENT CALENDAR</b></span>
<span id="ContentPlaceholder1_lblVote"><table border=0 width='100%'><tr><td colspan='3' align='center'><strong>Vote Results</strong></td></tr>
<tr><td colspan='3' height='1' bgcolor='#EFEFF6'><img src='images/spacer.gif' height='1' alt='spacer'/></td></tr>
<tr><td align='left'>Jeffrey Boone</td><td align='left'>Seconder</td><td align='left'>Yes/Aye</td></tr>
<tr><td align='left'>Dan Flores</td><td align='left'>Voter</td><td align='left'>Absent</td></tr>
<tr><td align='left'>Mike Ziegenmeyer</td><td align='left'>Voter</td><td align='left'>No/Nay</td></tr>
<tr><td align='left'>Karm Bains</td><td align='left'>Mover</td><td align='left'>Yes/Aye</td></tr>
<tr><td align='left'>Karm Bains</td><td align='left'>Mover</td><td align='left'>Yes/Aye</td></tr>
<tr><td align='left'>Jeff Stephens</td><td align='left'>Voter</td><td align='left'>Yes/Aye</td></tr></table></span>
<table border="0" id="Table4"><span id="ContentPlaceholder1_lblHistory"><tr><td colspan='3' height='1' bgcolor='#EFEFF6'><img src='images/spacer.gif' height='1' alt='spacer'/></td></tr>
<tr><td align='left'><strong>April 14, 2026 3:00 PM</strong> <img src='images/spacer.gif' alt='spacer' />Adopted</td></tr>
<tr><td><div><p>The Board approved the consent calendar items 1-11.</p></div></td></tr></span></table>"""

PAGES = {("Detail_Meeting.aspx", "3019"): MEETING, ("Detail_LegiFile.aspx", "7639"): CONSENT_ITEM,
         ("Detail_LegiFile.aspx", "7544"): HEARING_ITEM, ("Detail_Motion.aspx", "34792"): MOTION}


def portal(asked):
    """A portal that answers from the pages above, and keeps what it was asked for."""
    def fetch(url, tries=4, **params):
        page = url.rsplit("/", 1)[1]
        name, _, query = page.partition("?")
        number = str(params.get("ID") or query.partition("ID=")[2])
        asked.append((name, number))
        return PAGES[(name, number)]
    return fetch


def read(monkeypatch):
    asked = []
    monkeypatch.setattr(board, "fetch", portal(asked))
    agenda, votes = board.read_meeting(KEY, {"meeting_id": "3019", "date": "2026-04-14", "body": "Board of Supervisors"})
    return agenda, votes, asked


def test_the_calendar_gives_each_meeting_its_day_body_status_and_papers():
    rows = board.calendar_rows(CALENDAR)
    assert [(row["meeting_id"], row["date"], row["time"], row["body"], row["name"], row["status"]) for row in rows] == [
        ("3019", "2026-04-14", "3:00 PM", "Board of Supervisors", "Regular Session", "Closed"),
        ("3118", "2026-04-20", "10:00 AM", "Real Estate Committee", "Standing Committee Meeting", "Cancelled"),
        ("3120", "2026-04-21", "", "Board of Supervisors", "Budget Hearing", "Scheduled")]  # no time was entered for the last
    assert rows[0]["location"] == "City Council Chambers, 1201 CIVIC CENTER BLVD., YUBA CITY, CA 95993"
    meetings = board.meetings_table(KEY, rows)
    assert list(meetings.columns) == board.MEETING_COLUMNS
    first = meetings.iloc[0]
    assert first["url"] == "https://suttercountyca.iqm2.com/Citizens/Detail_Meeting.aspx?ID=3019"
    assert first["agenda_url"].endswith("/Citizens/FileOpen.aspx?Type=14&ID=2529&Inline=True")
    assert first["minutes_url"].endswith("FileOpen.aspx?Type=12&ID=1981&Inline=True")
    assert first["summary_url"].endswith("FileOpen.aspx?Type=15&ID=1981&Inline=True")
    # A paper not yet filed has a link that leads nowhere.
    assert meetings.iloc[1][["agenda_url", "minutes_url", "packet_url", "summary_url"]].tolist() == ["", "", "", ""]


def test_a_year_the_portal_cannot_answer_at_once_is_asked_for_by_month(monkeypatch):
    asked = []

    def fetch(url, tries=4, **params):
        asked.append((params["From"], params["To"]))
        if params["From"] == "1/1/2024" and params["To"] == "12/31/2024":
            raise board.NoPage(url)
        return CALENDAR if params["From"] == "4/1/2024" else ""

    monkeypatch.setattr(board, "fetch", fetch)
    assert [row["meeting_id"] for row in board.listed_year(KEY, 2024)] == ["3019", "3118", "3120"]
    assert asked[1] == ("1/1/2024", "1/31/2024") and asked[2] == ("2/1/2024", "2/29/2024") and len(asked) == 13


def test_a_meetings_page_is_read_as_lines_and_the_papers_under_an_item_are_not_lines():
    lines = board.lines_of(MEETING)
    assert [(line["kind"], line["page_id"], line["page_kind"], line["agenda_number"], line["level"], line["heading"]) for line in lines] == [
        ("text", "", "", "", 0, True), ("motion", "34789", "50", "", 1, False), ("motion", "34792", "100", "", 0, True),
        ("text", "", "", "", 1, False), ("item", "7639", "", "1", 1, False), ("motion", "34840", "70", "", 0, True),
        ("item", "7544", "", "12", 1, False), ("text", "", "", "", 0, True)]
    assert lines[4]["title"] == "Approval of two appointments (MT7639)"
    assert lines[4]["outcome"] == "Adopted By Consent Vote [Unanimous]"
    assert lines[6]["description"] == "Possible action: a. Open the hearing."


def test_an_older_agenda_that_links_an_item_as_hashes_takes_its_words_from_the_line_below():
    page = """<table id='MeetingDetail'>
<tr><td></td><td class='Num'></td><td class='Title' colspan='9'><a href='Detail_LegiFile.aspx?Frame=&MeetingID=1002&ID=60682&CssClass='>4. ###</a></td></tr>
<tr><td></td><td class='Num'></td><td class='Title' colspan='9'>Public Comment.</td></tr>
<tr><td class='Num'></td><td class='Title' colspan='10'>12) Approve the minutes</td></tr></table>"""
    assert [(line["kind"], line["agenda_number"], line["title"]) for line in board.lines_of(page)] == [
        ("item", "4", "Public Comment."), ("text", "12", "Approve the minutes")]


def test_an_item_gives_only_this_meetings_votes_with_each_word_as_the_tables_have_it():
    found = board.read_item(HEARING_ITEM, "3019")
    assert (found["number"], found["status"], found["department"], found["subject"], found["file_type"]) == (
        "7544", "Adopted", "Development Services", "Ordinance", "Agenda Item")
    assert found["comments"] == "The hearing was held."
    assert found["attachments"] == [{"name": "Printout", "url": "/Citizens/FileOpen.aspx?Type=30&ID=32144"}]
    # The record entered twice is one motion, and the member named twice in it has one vote.
    assert len(found["motions"]) == 1
    motion = found["motions"][0]
    assert motion["votes"] == [("Jeffrey K. Boone", "AYE"), ("Mike Ziegenmeyer", "AYE"), ("Jeff Stephens", "AYE"),
                               ("Karm Bains", "NO"), ("Dan Flores", "RECUSED")]
    assert (motion["mover"], motion["mover_title"]) == ("Mike Ziegenmeyer", "Chair, District 3")
    assert (motion["seconder"], motion["seconder_title"]) == ("Jeff Stephens", "District 5")
    assert board.read_item(HEARING_ITEM, "2990")["motions"][0]["words"] == "CONTINUED [UNANIMOUS]"
    assert board.read_item(HEARING_ITEM, "1")["motions"] == []
    with pytest.raises(ValueError):
        board.read_item("<html><body>Something else</body></html>", "3019")


def test_a_motions_page_gives_one_vote_named_by_member():
    found = board.read_motion(MOTION)
    motion = found["motions"][0]
    assert motion["votes"] == [("Jeffrey Boone", "AYE"), ("Dan Flores", "ABSENT"), ("Mike Ziegenmeyer", "NO"), ("Karm Bains", "AYE"),
                               ("Jeff Stephens", "AYE")]
    assert (motion["words"], motion["mover"], motion["seconder"]) == ("Adopted", "Karm Bains", "Jeffrey Boone")
    assert found["comments"] == "The Board approved the consent calendar items 1-11."
    assert board.read_motion("<span id='ContentPlaceholder1_lblVote'></span>")["motions"] == []


def test_names_are_split_at_commas_but_a_junior_stays_with_his_name():
    assert board.names_of("Ann Lee, John Smith, Jr., Bo Ruiz") == ["Ann Lee", "John Smith, Jr.", "Bo Ruiz"]
    assert board.names_of("") == []
    assert board.person_of("Justin Cummings, Vice Chair,Third District Supervisor", ["Justin Cummings"]) == (
        "Justin Cummings", "Vice Chair,Third District Supervisor")
    assert board.person_of("John Smith, Jr., District 2", ["Ann Lee", "John Smith, Jr."]) == ("John Smith, Jr.", "District 2")
    assert board.person_of("Paul Canepa", []) == ("Paul Canepa", "")


def test_a_result_is_the_clerks_word_and_count_and_whether_the_motion_carried():
    assert board.decided("ADOPTED (FINAL) [4 TO 0]") == ("ADOPTED (FINAL)", "4 TO 0")
    assert board.decided("Adopted By Consent Vote [Unanimous]") == ("Adopted By Consent Vote", "Unanimous")
    assert board.decided("SEE MINUTES EXCERPT") == ("SEE MINUTES EXCERPT", "")
    assert board.result_of("ADOPTED", "UNANIMOUS", 0, 0) == "Pass"
    assert board.result_of("DENIED", "3 TO 2", 3, 2) == "Pass"
    assert board.result_of("FAILED", "2 TO 3", 2, 3) == "Fail"
    assert board.result_of("DEFEATED", "", 0, 0) == "Fail"
    assert board.result_of("APPROVED", "2 TO 2", 2, 2) == ""
    assert board.result_of("Adopted", "", 4, 0) == ""  # no count from the clerk
    assert board.result_of("SEE MINUTES EXCERPT", "", 0, 0) == ""


def test_a_meeting_is_read_with_a_page_for_each_item_and_each_motion_that_may_have_a_vote(monkeypatch):
    agenda, votes, asked = read(monkeypatch)
    # The invocation and the heading are kinds of line never seen with a vote, and are not asked for.
    assert asked == [("Detail_Meeting.aspx", "3019"), ("Detail_Motion.aspx", "34792"), ("Detail_LegiFile.aspx", "7639"),
                     ("Detail_LegiFile.aspx", "7544")]
    assert [line["item_id"] for line in agenda] == ["3019-t1", "3019-m34789", "3019-m34792", "3019-t4", "3019-7639", "3019-m34840",
                                                    "3019-7544", "3019-t8"]
    assert set(agenda[0]) == set(board.AGENDA_COLUMNS) and set(votes[0]) == set(board.VOTE_COLUMNS)
    consent, item, hearing = agenda[2], agenda[4], agenda[6]
    assert (consent["kind"], consent["action"], consent["result"], consent["ayes"], consent["noes"], consent["not_voting"]) == (
        "motion", "Adopted", "", 3, 1, 1)
    assert (item["matter_id"], item["matter_file"], item["section"], item["section_id"]) == ("7639", "", "CONSENT CALENDAR", "3019-m34792")
    assert (item["action"], item["tally"], item["result"], item["mover"], item["mover_title"]) == (
        "ADOPTED", "UNANIMOUS", "Pass", "Karm Bains", "Vice Chair, District 4")
    assert (item["doc_type"], item["subject"], item["department"]) == ("ordinance", "Ordinance", "Development Services")
    assert item["attachments"] == '[{"name":"Printout","url":"https://suttercountyca.iqm2.com/Citizens/FileOpen.aspx?Type=30&ID=32144"}]'
    # The county's file number comes off the front of the words, and the item's own page has the better title.
    assert (hearing["matter_file"], hearing["title"]) == ("BOS-2026-5", "Public Hearing to consider an ordinance on speed limits (MT7544)")
    assert (hearing["action"], hearing["tally"], hearing["ayes"], hearing["noes"], hearing["not_voting"], hearing["motions"]) == (
        "ADOPTED", "3 TO 1", 3, 1, 1, 1)
    assert [(vote["member"], vote["vote"]) for vote in votes if vote["item_id"] == "3019-7544"] == [
        ("Jeffrey K. Boone", "AYE"), ("Mike Ziegenmeyer", "AYE"), ("Jeff Stephens", "AYE"), ("Karm Bains", "NO"), ("Dan Flores", "RECUSED")]
    assert {vote["vote"] for vote in votes} == {"AYE", "NO", "ABSENT", "RECUSED"}
    assert all(vote["vote"] == council_tables.vote_word(vote["vote"]) for vote in votes)
    assert len(votes) == len({(vote["item_id"], vote["motion"], vote["member"]) for vote in votes}) == 15


def test_an_item_whose_page_the_portal_cannot_make_keeps_its_line(monkeypatch):
    answer = portal([])

    def fetch(url, tries=4, **params):
        if params.get("ID") == "7639":
            raise board.NoPage(url)
        return answer(url, **params)

    monkeypatch.setattr(board, "fetch", fetch)
    agenda, votes = board.read_meeting(KEY, {"meeting_id": "3019", "date": "2026-04-14", "body": "Board of Supervisors"})
    item = agenda[4]
    # What the meeting's own page says was done stands in for the vote.
    assert (item["matter_id"], item["title"], item["action"], item["tally"], item["result"], item["motions"]) == (
        "7639", "Approval of two appointments (MT7639)", "Adopted By Consent Vote", "Unanimous", "Pass", 0)
    assert not [vote for vote in votes if vote["item_id"] == "3019-7639"]


def tables_of(monkeypatch):
    agenda, votes, _ = read(monkeypatch)
    earlier = [{**row, "meeting_id": "2990", "date": "2026-03-24", "item_id": row["item_id"].replace("3019-", "2990-")}
               for row in agenda if row["matter_id"] == "7544"]
    earlier[0].update(action="CONTINUED", result="Pass", mover="Dan Flores", mover_title="District 2", seconder="", seconder_title="")
    earlier_votes = [{**vote, "meeting_id": "2990", "date": "2026-03-24", "item_id": vote["item_id"].replace("3019-", "2990-")}
                     for vote in votes if vote["item_id"] == "3019-7544"]
    agenda = pd.DataFrame(agenda + earlier, columns=board.AGENDA_COLUMNS)
    votes = pd.DataFrame(votes + earlier_votes, columns=board.VOTE_COLUMNS)
    return board.one_name(agenda, votes)


def test_a_member_named_with_a_middle_initial_and_without_is_one_member(monkeypatch):
    assert board.fuller_names({"Steven Ding", "Steven J. Ding", "Paul Canepa", "Ann B. Lee", "Ann C. Lee", "Ann Lee"}) == {
        "Steven Ding": "Steven J. Ding"}
    agenda, votes = tables_of(monkeypatch)
    assert "Jeffrey Boone" not in set(votes["member"]) and "Jeffrey Boone" not in set(agenda["seconder"])
    assert set(votes["member"]) == {"Jeffrey K. Boone", "Dan Flores", "Mike Ziegenmeyer", "Karm Bains", "Jeff Stephens"}


def test_an_item_is_here_once_with_the_last_thing_done_to_it(monkeypatch):
    agenda, votes = tables_of(monkeypatch)
    items = board.items_table(KEY, agenda)
    assert list(items.columns) == board.ITEM_COLUMNS and sorted(items["matter_id"]) == ["7544", "7639"]
    item = items.set_index("matter_id").loc["7544"]
    assert (item["date"], item["agenda_date"], item["times_on_agenda"], item["year"]) == ("2026-03-24", "2026-04-14", 2, 2026)
    assert (item["last_action"], item["last_action_date"], item["passed_date"], item["ayes"], item["noes"], item["mover"]) == (
        "ADOPTED", "2026-04-14", "", 3, 1, "Mike Ziegenmeyer")
    assert item["url"] == "https://suttercountyca.iqm2.com/Citizens/Detail_LegiFile.aspx?ID=7544"
    assert (item["doc_type"], item["action_on"]) == ("ordinance", "item")
    # A consent item with no vote on its own page has the count and the mover of the calendar it was passed with.
    own = agenda["item_id"] == "3019-7639"
    agenda.loc[own, ["action", "tally", "motions", "ayes", "mover", "seconder"]] = ["Adopted By Consent Vote", "Unanimous", 0, 0, "", ""]
    item = board.items_table(KEY, agenda).set_index("matter_id").loc["7639"]
    assert (item["last_action"], item["action_on"], item["ayes"], item["noes"], item["mover"], item["seconder"]) == (
        "Adopted By Consent Vote", "section", 3, 1, "Karm Bains", "Jeffrey K. Boone")


def test_members_are_those_who_vote_on_several_days_with_the_district_their_title_gives(monkeypatch):
    agenda, votes = tables_of(monkeypatch)
    meetings = pd.DataFrame({"meeting_id": ["3019", "2990"], "body": ["Board of Supervisors"] * 2})
    stray = {**votes.iloc[0].to_dict(), "member": "Clerk Of The Board"}  # named once, on one day: a slip
    votes = pd.concat([votes, pd.DataFrame([stray])], ignore_index=True)
    members = board.members_table(agenda, votes, meetings, {"Board of Supervisors"})
    assert list(members.columns) == council_tables.COLUMNS["members"]
    assert sorted(members["name"]) == ["Dan Flores", "Jeff Stephens", "Jeffrey K. Boone", "Karm Bains", "Mike Ziegenmeyer"]
    by_name = members.set_index("name")
    assert by_name["district"].to_dict() == {"Dan Flores": 2, "Jeff Stephens": 5, "Jeffrey K. Boone": 1, "Karm Bains": 4,
                                             "Mike Ziegenmeyer": 3}
    assert by_name.loc["Karm Bains", "role"] == "Vice Chair, District 4"
    assert (by_name.loc["Karm Bains", "first_vote"], by_name.loc["Karm Bains", "last_vote"]) == ("2026-03-24", "2026-04-14")
    # A district typed in for a county whose pages give none is the one used.
    typed = board.members_table(agenda, votes, meetings, {"Board of Supervisors"}, {"Karm Bains": 9}).set_index("name")
    assert typed.loc["Karm Bains", "district"] == 9
    assert board.district_of("Vice Chair,Third District Supervisor") == 3 and board.district_of("District 2 - Chair") == 2
    assert board.district_of("Supervisor") is None


class Answer:
    def __init__(self, status_code, text, url="https://suttercountyca.iqm2.com/Citizens/Calendar.aspx"):
        self.status_code, self.text, self.url = status_code, text, url

    def raise_for_status(self):
        pass


def test_a_host_that_turns_us_away_is_not_asked_again(monkeypatch):
    asked = []

    class Session:
        headers = {}

        def get(self, url, **kwargs):
            asked.append(url)
            return Answer(200, '<body id="MainLayout">Log in</body>', "https://suttercountyca.iqm2.com/Login.aspx?ReturnURL=x")

    monkeypatch.setattr(board, "REFUSED", {})
    monkeypatch.setattr(board, "PAUSE", 0)
    monkeypatch.setattr(board._local, "session", Session(), raising=False)
    for _ in range(2):
        with pytest.raises(board.Refused):
            board.fetch("https://suttercountyca.iqm2.com/Citizens/Calendar.aspx")
    assert len(asked) == 1 and "Login.aspx" in board.REFUSED["suttercountyca.iqm2.com"]
    # A bot check is a refusal too.
    Session.get = lambda self, url, **kwargs: Answer(403, "<html><title>Attention Required! | Cloudflare</title></html>")
    monkeypatch.setattr(board, "REFUSED", {})
    with pytest.raises(board.Refused):
        board.fetch("https://suttercountyca.iqm2.com/Citizens/Calendar.aspx")


def test_the_portals_own_error_page_is_no_page_and_a_page_that_mentions_a_captcha_is_still_a_page(monkeypatch):
    # Asked for minutes not yet published, the portal shows its login page and says why. That is no page, not a refusal.
    unpublished = ("https://suttercountyca.iqm2.com/Login.aspx?ReturnURL=https%3A%2F%2Fsuttercountyca%2Eiqm2%2Ecom%2FCitizens%2F"
                   "Detail%5FMotion%2Easpx%3FID%3D1&Message=The%20Minutes%20have%20not%20been%20published%20for%20viewing%20yet%2E")
    pages = iter([Answer(200, '<body id="MainLayout">Oops.. an error occured</body>'),
                  Answer(200, '<body id="MainLayout">Log in</body>', unpublished),
                  Answer(200, '<body id="MainLayout"><div id="ContentPlaceholder1_pnlMain">A contract for reCAPTCHA</div></body>')])

    class Session:
        headers = {}

        def get(self, url, **kwargs):
            return next(pages)

    monkeypatch.setattr(board, "REFUSED", {})
    monkeypatch.setattr(board, "PAUSE", 0)
    monkeypatch.setattr(board._local, "session", Session(), raising=False)
    for _ in range(2):
        with pytest.raises(board.NoPage):
            board.fetch("https://suttercountyca.iqm2.com/Citizens/Detail_LegiFile.aspx", ID=1)
    assert "reCAPTCHA" in board.fetch("https://suttercountyca.iqm2.com/Citizens/Detail_LegiFile.aspx", ID=1)
    assert board.REFUSED == {}


def test_a_whole_run_reads_the_newest_meetings_first_and_does_not_ask_twice(monkeypatch, tmp_path):
    asked = []
    answer = portal(asked)
    rows = [{"meeting_id": "3019", "date": "2026-04-14", "time": "3:00 PM", "body": "Board of Supervisors", "location": "", "name": "Regular Session",
             "status": "Closed", "papers": {}},
            {"meeting_id": "3118", "date": "2026-04-20", "time": "10:00 AM", "body": "Real Estate Committee", "location": "",
             "name": "Standing Committee Meeting", "status": "Closed", "papers": {}},
            {"meeting_id": "3200", "date": "2026-05-12", "time": "3:00 PM", "body": "Board of Supervisors", "location": "", "name": "Regular Session",
             "status": "Cancelled", "papers": {}}]
    monkeypatch.setattr(board, "fetch", answer)
    old = [{**rows[1], "meeting_id": str(number), "date": f"2012-{number:02d}-03"} for number in range(1, 11)]
    monkeypatch.setattr(board, "listed_year", lambda key, year: rows if year == 2026 else old if year == 2012 else [])
    monkeypatch.setattr(board, "today", lambda: "2026-10-12")
    monkeypatch.setattr(board, "RECENT_DAYS", 0)
    monkeypatch.setattr(council_tables, "published", lambda repo, name: None)
    tables, read, unread = board.build(KEY, True, False, tmp_path)
    assert (read, unread) == (1, 0)
    for name in council_tables.TABLES:
        assert list(tables[name].columns)[:len(council_tables.COLUMNS[name])] == council_tables.COLUMNS[name]
        assert (tmp_path / f"{name}.parquet").exists()
    meetings = tables["meetings"].set_index("meeting_id")
    # Another body's meeting and a cancelled one are listed and not read.
    assert len(meetings) == 13 and meetings["read_on"][["3019", "3118", "3200"]].to_dict() == {"3019": "2026-10-12", "3118": "", "3200": ""}
    assert meetings.loc["3019", "items"] == 4
    assert len(tables["votes"]) == 15 and not tables["votes"].duplicated(["item_id", "motion", "member"]).any()
    assert set(tables["votes"]["member"]) == {"Jeffrey K. Boone", "Dan Flores", "Mike Ziegenmeyer", "Karm Bains", "Jeff Stephens"}
    assert sorted(tables["items"]["matter_id"]) == ["7544", "7639"]
    # Started again from what was written, there is nothing left to ask a meeting's pages for.
    asked.clear()
    tables, read, unread = board.build(KEY, True, False, tmp_path)
    assert (read, unread, asked) == (0, 0, []) and len(tables["votes"]) == 15 and len(tables["meetings"]) == 13
    # The routine run lists only this year's calendar again, and keeps the meetings of the years before it.
    listed = []
    monkeypatch.setattr(board, "listed_year", lambda key, year: listed.append(year) or (rows if year == 2026 else []))
    monkeypatch.setattr(council_tables, "published", lambda repo, name: pd.read_parquet(tmp_path / f"{name}.parquet"))
    tables, read, unread = board.build(KEY, False, False, tmp_path)
    assert listed == [2026, 2027] and len(tables["meetings"]) == 13 and (read, unread, asked) == (0, 0, [])
    text = board.card(KEY, tables)
    assert "{" not in text.split("---", 2)[2].replace("{id}", "")
    assert "Sutter County Board of Supervisors" in text and "suttercountyca.iqm2.com" in text
