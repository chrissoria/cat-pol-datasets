"""build_primegov_board reads a county board's meetings and votes from PrimeGov's pages and puts them in the one shape."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import build_primegov_board as prime
import council_tables

KEY = "tulare-county"
SITE = "https://tularecounty.primegov.com"


def cast(**names):
    """The lines the system writes under a motion: one for each way of voting, then the count."""
    result = names.pop("result", "5 &ndash;&nbsp;0&nbsp;Passed")
    rows = "".join(f"<div><span><strong>{word.upper()}:</strong>&nbsp;{who}</span></div>\n" for word, who in names.items())
    return (f'<div style="padding-bottom: 10pt;">\n{rows}<div><span></span></div>\n'
            f"<div><span><strong>Final Result:&nbsp;</strong>{result}</span></div>\n</div>")


def moved(by, second, what):
    return f'<span><strong><span style="background-color:#ffff00;">Moved by {by}, seconded by&nbsp;{second} to {what}</span></strong></span><br>\n&nbsp;'


def item(number, mark, words, under="", after="", papers=""):
    return (f"<div class='meeting-item' data-itemid='{number}'><table class='item-table'><tr>"
            f"<td class='attachment-cell'><span title='Has Attachments'></span></td><td class='number-cell'><span>{mark}</span></td>"
            f"<td class='item-cell'><div class='agenda-item' id='AgendaItem_{number}'><div><span>{words}</span><br>\n<br>\n"
            f"<span>{under}</span></div>\n</div>{after}"
            f'<div style="display:none;" class="item_contents" id="agenda_item_area_{number}">{papers}</div></td></tr></table></div>')


def section(number, words, inside="", foot=""):
    footer = f"<table id='sectionfooter_9{number}'><tr><td>{foot}</td></tr></table>" if foot else ""
    return (f"<table><tr><td><div class='section-with-items' data-sectionid='{number}'><table><tr class='section-row'><td colspan='2'>"
            f"{words}</td></tr><tr><td colspan='2'>{inside}</td></tr></table>{footer}</div></td></tr></table>")


FIVE = "Larry Micari, Pete Vander Poel, Amy Shuklian, Eddie Valero, Dennis Townsend"
PAPER = ('<div class="attachment-holder"><a href="/viewer/preview?id=0&type=8&uid=u1"><span class="glyphicon"></span></a>'
         '<a href="/api/compilemeetingattachmenthistory/historyattachment/?historyId=u1"><span></span>&nbsp;&nbsp;Resolution No. 2025-0002</a></div>')
# Minutes as the system writes them: the consent calendar's one vote is at the foot of its own heading, and the items it
# took in sit under the headings of the departments that follow.
MINUTES = "<html><body><img src=\"data:image/png;base64,AAAA\"><div id='meetingSection'>" + "".join([
    section(1, "<div><strong>INVOCATION AND<br>\nPLEDGE OF ALLEGIANCE</strong></div>",
            item(101, "1.", "Election of the Chair for the year 2025.", "<strong>Resolution No.</strong>&nbsp;2025-0001<br>",
                 # The system wrote the ayes out three times over.
                 moved("Eddie Valero", "Dennis Townsend", "Approved to Elect Supervisor Vander Poel as Chair.")
                 + cast(ayes=f"{FIVE}, </span><strong>AYES:</strong> <span>{FIVE}, </span><strong>AYES:</strong> <span>{FIVE}"))
            + item(102, "2.", "Public Comments.")),
    section(2, "<div><strong>CONSENT CALENDAR (Numbers <s>2</s> 3&nbsp;through 5)</strong></div>\n<table><tr><td>&nbsp;</td></tr></table>"
               "<table><tr><td><strong>NOTICE TO THE PUBLIC</strong> These items are routine.</td></tr></table>",
            # What was moved is set as a paragraph of its own, breaking the sentence in two.
            foot='<span>Moved by Amy Shuklian, seconded by Larry Micari to <p>Approved Consent Calendar (Numbers 3 through 5) with the '
                 "exception of item #4 which was pulled for separate consideration.</p>.</span><br>"
                 + cast(ayes="Larry Micari, Pete Vander Poel, Amy Shuklian, Dennis Townsend", absent="Eddie Valero", result="4 &ndash; 0 Passed")),
    section(3, "<p><u><strong>Health &amp; Human Services Agency</strong></u></p>",
            item(103, "3.", "Approve an agreement for peer support.", "<strong>Resolution No.</strong>&nbsp;2025-0002<br>", papers=PAPER)
            + item(104, "4.", "Adopt an ordinance on camping.", "",
                   "<span>Karen Elliott, Director &ndash; staff presentation<br>\n<br>\n</span>"
                   + moved("Eddie Valero", "Amy Shuklian", "Approved to continue the matter.")
                   + cast(ayes="Amy Shuklian, Eddie Valero", noes="Larry Micari, Pete Vander Poel, Dennis Townsend", result="2 &ndash; 3 Failed")
                   + moved("Dennis Townsend", "Pete Vander Poel", "Approved.")
                   + cast(ayes="Larry Micari, Pete Vander Poel, Dennis Townsend", noes="Amy Shuklian", abstain="Eddie Valero", result="3 &ndash; 1"))
            + item(105, "5.", "Approve the minutes.")),
    section(4, "<div><strong>ITEMS NOT TIMED</strong><br>Items not specifically timed may be taken in any order</div>",
            # A count and no names.
            item(106, "6.", "Receive a report.", "", moved("Larry Micari", "Eddie Valero", "Approved.")
                 + "<div><div><span><strong>Final Result:&nbsp;</strong>5 &ndash; 0 Passed</span></div></div>")
            + item(107, "ITEM A", "CONFERENCE WITH LEGAL COUNSEL<br>Number of Potential Cases: 1", "",
                   "<span>Supervisor Valero recusal due to conflict of interest</span>")),
]) + "</div></body></html>"

MEETING = {"meeting_id": "9", "date": "2025-01-07", "body": "Board of Supervisors", "document_id": "12554"}


def read(monkeypatch, page=MINUTES):
    monkeypatch.setattr(prime, "fetch", lambda url: page)
    agenda, votes = prime.read_meeting(KEY, MEETING)
    return pd.DataFrame(agenda, columns=prime.AGENDA_COLUMNS), pd.DataFrame(votes, columns=prime.VOTE_COLUMNS)


def test_a_page_is_read_in_order_with_each_line_under_its_heading(monkeypatch):
    agenda, _ = read(monkeypatch)
    assert list(agenda["item_id"]) == ["s1", "101", "102", "s2", "s3", "103", "104", "105", "s4", "106", "107"]
    assert list(agenda["sequence"]) == list(range(1, 12))
    assert list(agenda["heading"]) == [True, False, False, True, True, False, False, False, True, False, False]
    assert list(agenda["agenda_number"]) == ["", "1", "2", "", "", "3", "4", "5", "", "6", "ITEM A"]
    lines = agenda.set_index("item_id")
    # A heading broken off mid-phrase runs on; one with a note under it does not; struck-out words are left out.
    assert lines.loc["s1", "title"] == "INVOCATION AND PLEDGE OF ALLEGIANCE"
    assert (lines.loc["s4", "title"], lines.loc["s4", "description"]) == ("ITEMS NOT TIMED", "Items not specifically timed may be taken in any order")
    assert lines.loc["s2", "title"] == "CONSENT CALENDAR (Numbers 3 through 5)" and lines.loc["s2", "description"].startswith("NOTICE TO THE PUBLIC")
    assert (lines.loc["103", "section"], lines.loc["103", "section_id"]) == ("Health & Human Services Agency", "s3")
    assert (lines.loc["103", "title"], lines.loc["103", "number"]) == ("Approve an agreement for peer support.", "2025-0002")
    assert lines.loc["103", "attachments"] == ('[{"name":"Resolution No. 2025-0002","url":"' + SITE
                                               + '/api/compilemeetingattachmenthistory/historyattachment/?historyId=u1"}]')
    assert (lines.loc["107", "title"], lines.loc["107", "description"]) == ("CONFERENCE WITH LEGAL COUNSEL", "Number of Potential Cases: 1")
    assert (lines.loc["104", "doc_type"], lines.loc["103", "doc_type"], lines.loc["s3", "doc_type"]) == ("ordinance", "other", "")
    assert list(lines.loc[["s1", "101"], "matter_id"]) == ["", "101"]  # a heading is not an item
    assert set(agenda["body"]) == {"Board of Supervisors"} and set(agenda["date"]) == {"2025-01-07"}


def test_each_motion_has_its_votes_in_the_one_spelling_and_a_vote_written_twice_is_kept_once(monkeypatch):
    agenda, votes = read(monkeypatch)
    chair = votes[votes["item_id"] == "101"]
    assert list(chair["member"]) == FIVE.split(", ") and set(chair["vote"]) == {"AYE"}
    assert set(chair["motion_text"]) == {"Approved to Elect Supervisor Vander Poel as Chair."} and set(chair["matter_id"]) == {"101"}
    camping = votes[votes["item_id"] == "104"]
    assert [(v.motion, v.member, v.vote) for v in camping.itertuples()] == [
        (1, "Amy Shuklian", "AYE"), (1, "Eddie Valero", "AYE"), (1, "Larry Micari", "NO"), (1, "Pete Vander Poel", "NO"),
        (1, "Dennis Townsend", "NO"),
        (2, "Larry Micari", "AYE"), (2, "Pete Vander Poel", "AYE"), (2, "Dennis Townsend", "AYE"), (2, "Amy Shuklian", "NO"),
        (2, "Eddie Valero", "ABSTAIN")]
    row = agenda.set_index("item_id").loc["104"]
    # The line shows its last motion, and claims a result only where the minutes give one.
    assert (row["action"], row["result"], row["tally"], row["ayes"], row["noes"], row["not_voting"], row["motions"]) == (
        "Approved.", "", "3-1", 3, 1, 1, 2)
    assert (row["mover"], row["seconder"]) == ("Dennis Townsend", "Pete Vander Poel")
    assert row["minutes_text"].startswith("Karen Elliott, Director – staff presentation\n\nMoved by Eddie Valero")
    assert votes[votes["item_id"] == "107"].empty  # a recusal told in a sentence is not a vote


def test_a_motion_with_a_count_and_no_names_has_its_action_and_no_votes(monkeypatch):
    agenda, votes = read(monkeypatch)
    row = agenda.set_index("item_id").loc["106"]
    assert (row["action"], row["mover"], row["tally"], row["result"], row["motions"]) == ("Approved.", "Larry Micari", "5-0", "Pass", 1)
    assert (row["ayes"], row["noes"], row["not_voting"]) == (0, 0, 0) and votes[votes["item_id"] == "106"].empty


def test_a_consent_calendars_vote_is_on_its_heading_and_names_the_items_it_took_in(monkeypatch):
    agenda, votes = read(monkeypatch)
    lines = agenda.set_index("item_id")
    consent = votes[votes["item_id"] == "s2"]
    assert [(v.member, v.vote) for v in consent.itertuples()] == [("Larry Micari", "AYE"), ("Pete Vander Poel", "AYE"), ("Amy Shuklian", "AYE"),
                                                                 ("Dennis Townsend", "AYE"), ("Eddie Valero", "ABSENT")]
    assert set(consent["matter_id"]) == {""}
    heading = lines.loc["s2"]
    assert (heading["mover"], heading["seconder"], heading["result"], heading["ayes"], heading["not_voting"]) == (
        "Amy Shuklian", "Larry Micari", "Pass", 4, 1)
    assert heading["action"].startswith("Approved Consent Calendar (Numbers 3 through 5) with the exception of item #4")
    # 3 and 5 were taken in; 4 was pulled and voted on by itself; 6 comes after the run.
    assert list(lines.loc[["103", "104", "105", "106", "101"], "consent_id"]) == ["s2", "", "s2", "", ""]

    items = prime.items_table(KEY, agenda, pd.DataFrame({"meeting_id": ["9"], "url": [SITE + "/Portal/Meeting?meetingTemplateId=12554"]}))
    assert list(items.columns[:20]) == council_tables.COLUMNS["items"]
    items = items.set_index("matter_id")
    assert set(items.index) == {"101", "102", "103", "104", "105", "106", "107"}
    assert (items.loc["103", "action_on"], items.loc["103", "ayes"], items.loc["103", "mover"], items.loc["103", "passed_date"]) == (
        "consent", 4, "Amy Shuklian", "")
    assert (items.loc["104", "action_on"], items.loc["104", "last_action"], items.loc["104", "noes"]) == ("item", "Approved.", 1)
    assert (items.loc["102", "action_on"], items.loc["102", "last_action"], items.loc["102", "ayes"]) == ("", "", 0)
    assert items.loc["105", "url"] == SITE + "/Portal/Meeting?meetingTemplateId=12554"


def test_the_run_of_a_consent_calendar_is_what_its_motion_names_less_what_was_pulled():
    title = "CONSENT CALENDAR (Numbers 5 through 9)"
    assert prime.covered(title, "Approved Consent Calendar (Numbers 5 through 9).") == {5, 6, 7, 8, 9}
    assert prime.covered(title, "Approved.") == {5, 6, 7, 8, 9}  # the motion says only that it carried
    assert prime.covered(title, "Approved Consent Calendar (Numbers 5 though 9) except items #6, 7, and #9 which were pulled.") == {5, 8}
    assert prime.covered(title, "Approved with the exception of items 6-8 which were pulled off calendar.") == {5, 9}
    assert prime.covered(title, "Approved Consent Calendar (Numbers 5 through 9). Item # 7 verbal correction.") == {5, 6, 7, 8, 9}
    assert prime.covered("CONSENT CALENDAR (Number 1)", "Approved.") == {1}
    # The heading and the motion differ: the one that starts at the first item is right, and failing that what both name.
    assert prime.covered("CONSENT CALENDAR (Numbers 4 through 6)", "Approved Consent Calendar (Numbers 7 through 9).", 7) == {7, 8, 9}
    assert prime.covered("CONSENT CALENDAR (Numbers 4 through 6)", "Approved Consent Calendar (Numbers 4 through 9).", 4) == {4, 5, 6}
    assert prime.covered("ITEMS NOT TIMED", "Approved items #1 through #7.") == set()


def test_minutes_typed_by_hand_are_read_the_same_way():
    motions = prime.motions_in([
        "Resolution No. 10089", "Motion by Whitlatch, seconded by Millies to Approve PPM 23-005.",
        "AYES: Carlos Aleman, Bill Whitlatch and Natalie R. La Fleur", "NOES:", "Final Result: 6-0",
        "ABSENT: Gil Aguilar, Terren Brown", "Emily Gage, Project Planner", "Public Comments – No public comment received.",
        # A second motion with no sentence before it, its words run together on one line.
        "AYE: A One, B Two NOES: None ABSTAINED: C Three RECUSED: D Four Final Result: 2 – 0 Failed"])
    first, second = motions
    assert (first["mover"], first["seconder"], first["action"], first["tally"], first["result"]) == ("Whitlatch", "Millies", "Approve PPM 23-005.", "6-0", "")
    assert first["votes"] == [("Carlos Aleman", "AYE"), ("Bill Whitlatch", "AYE"), ("Natalie R. La Fleur", "AYE"),
                              ("Gil Aguilar", "ABSENT"), ("Terren Brown", "ABSENT")]
    assert second["votes"] == [("A One", "AYE"), ("B Two", "AYE"), ("C Three", "ABSTAIN"), ("D Four", "RECUSED")]
    assert (second["mover"], second["action"], second["tally"], second["result"]) == ("", "", "2-0", "Fail")
    # Who was at the meeting is not a vote, and neither is a sentence that only uses the words.
    assert prime.motions_in(["PRESENT: A One, B Two", "ABSENT: C Three", "The item was moved by staff to a later date."]) == []
    assert prime.people("A One, B Two; C Three & D Four and None, 5 through 9, a long run of words that is no name.") == [
        "A One", "B Two", "C Three", "D Four"]


# An agenda made from the clerk's Word document: a table for each heading and each item, one after the other.
def row(mark, number, cells, papers=""):
    icon = f'<td class="agenda-item" id="attachment-icon-{number}"><div></div></td>' if mark == "itemid" else '<td class="attachmentCell"><div></div></td>'
    buttons = f'<td class="optionalButtonsCell"><a href="/meetings/minipacket?id={number}"><svg><title>Combine item\'s attachments into one PDF and view</title></svg></a></td>'
    return f'<table class="item-table-fromdocx" data-id="{number}" data-{mark}="{number}"><tr>{icon}{cells}{buttons}</tr></table>'


WORD = "<html><body><div id='MeetingContents'>" + "".join([
    row("sectionid", 70, '<td><p><span>CONSENT CALENDAR</span></p><p><span>The following items are expected to be routine.</span></p></td>'),
    row("sectionid", 71, '<td><p><span>Public Works</span></p></td>'),
    row("itemid", 4274, '<td><p><span>C2</span></p></td><td class="agenda-item" data-itemid="4274" id="AgendaItem_4274"><p><span>Adopt a resolution '
        'which repeals Resolution No. 2021-022.</span></p><table><tr><td><p><span>&#xa0;</span></p></td></tr><tr><td><p><span>No General Fund '
        'Impact</span></p></td></tr><tr><td><p><span>&#xa0;</span></p></td></tr><tr><td><p><span>Simple Majority Vote</span></p></td></tr></table>'
        '<div class="item_contents" id="agenda_item_area_4274"><div class="attachment-holder"><a href="/api/x?historyId=u2"> Staff Report </a>'
        '</div></div></td>'),
    # An item with no papers has no mark on the cell of its words.
    row("itemid", 3880, '<td><p><span>R1</span></p></td><td><p><span>Receive an update from the County Executive Officer.</span></p></td>'),
    row("sectionid", 72, '<td><p><span>&#xa0;</span></p></td>'),  # a gap in the page
]) + "</div></body></html>"


def test_a_page_made_from_a_word_document_is_read_too():
    lines = prime.lines_of("shasta-county", WORD)
    assert [(line["id"], line["heading"], line["number"], line["title"], line["section"]) for line in lines] == [
        ("s70", True, "", "CONSENT CALENDAR", None), ("s71", True, "", "Public Works", None),
        ("4274", False, "C2", "Adopt a resolution which repeals Resolution No. 2021-022.", "s71"),
        ("3880", False, "R1", "Receive an update from the County Executive Officer.", "s71")]
    assert lines[0]["description"] == "The following items are expected to be routine."
    assert lines[2]["description"] == "No General Fund Impact\nSimple Majority Vote"
    assert json.loads(lines[2]["attachments"]) == [{"name": "Staff Report", "url": "https://shastacounty.primegov.com/api/x?historyId=u2"}]
    assert not any(line for one in lines for line in one["minutes"])  # the buttons beside a line are not its words


def test_an_agenda_from_an_older_system_has_its_numbers_in_its_words():
    page = "<div>" + "".join(f"<div class='meeting-item' data-itemid='{n}'><table><tr><td class='item-cell'><div class='agenda-item' "
                             f"id='AgendaItem_{n}'><div>{words}</div></div></td></tr></table></div>"
                             for n, words in ((1, "12. Presentation regarding the film festival."), (2, "(A) PPM 12-013 A Tentative Parcel Map"),
                                              (3, "<p>ITEM J</p><p>CONSIDER PUBLIC EMPLOYEE APPOINTMENT</p>"), (4, "U.S. Forest Service update"),
                                              (5, "&nbsp;"))) + "</div>"
    assert [(line["number"], line["title"]) for line in prime.lines_of(KEY, page)] == [
        ("12", "Presentation regarding the film festival."), ("(A)", "PPM 12-013 A Tentative Parcel Map"),
        ("ITEM J", "CONSIDER PUBLIC EMPLOYEE APPOINTMENT"), ("", "U.S. Forest Service update")]
    assert prime.lines_of(KEY, "<html><body>Sorry! It seems you've run into an error</body></html>") == []


def paper(name, template, kind=1, link=None, published="2025-01-02T17:36:49.57"):
    return {"templateName": name, "templateId": template, "compileOutputType": kind, "link": link, "publishDate": published}


def event(number, when="2025-01-07T09:00:00", papers=(), **more):
    return {"id": number, "committeeId": 25, "dateTime": when, "time": "09:00 AM", "title": "Board of Supervisors Regular Meeting ",
            "location": "Board Chambers,  Visalia", "videoUrl": None, "meetingState": 3, "documentList": list(papers), **more}


def test_a_meeting_has_its_time_place_and_documents_and_the_page_to_read():
    events = [
        event(9, papers=[paper("PDF Agenda", 12553), paper("HTML Minutes", 12554, 3, published="2025-09-09T00:00:07.87"), paper("Minutes", 12554),
                         paper("HTML Agenda", 12553, 3), paper("Packet", 12555)], videoUrl="https://youtube.com/watch?v=x"),
        event(10, "2025-02-04T13:30:00", [paper("HTML Agenda", 77, 3, link="http://bosagendas.co.tulare.ca.us/1/Agenda.html"), paper("BOS Minutes 3/09/10", 78)],
              time="01:30 PM"),
        event(11, "2025-03-04T09:00:00", [paper("Notice of Cancellation", 80), paper("HTML Mini-Packet", 81, 3)], committeeId=142,
              title="Testing New Event", meetingState=1),
    ]
    meetings = prime.meetings_table(KEY, events, {25: "Board of Supervisors"}).set_index("meeting_id")
    held = meetings.loc["9"]
    assert (held["date"], held["time"], held["body"], held["location"], held["name"]) == (
        "2025-01-07", "9:00 AM", "Board of Supervisors", "Board Chambers, Visalia", "Board of Supervisors Regular Meeting")
    # The minutes are read where they are a page; the agenda and the minutes are given as pages where there are pages.
    assert (held["document"], held["document_id"], held["document_date"]) == ("HTML Minutes", "12554", "2025-09-09T00:00:07.87")
    assert held["url"] == held["minutes_url"] == SITE + "/Portal/Meeting?meetingTemplateId=12554"
    assert held["agenda_url"] == SITE + "/Portal/Meeting?meetingTemplateId=12553"
    assert held["packet_url"] == SITE + "/Public/CompiledDocument?meetingTemplateId=12555&compileOutputType=1"
    assert (held["video_url"], held["committee_id"], held["state"]) == ("https://youtube.com/watch?v=x", "25", 3)
    # An agenda the system only links to, on another site, is not a page to read.
    linked = meetings.loc["10"]
    assert (linked["time"], linked["document_id"], linked["agenda_url"]) == ("1:30 PM", "", "http://bosagendas.co.tulare.ca.us/1/Agenda.html")
    assert linked["minutes_url"] == SITE + "/Public/CompiledDocument?meetingTemplateId=78&compileOutputType=1"
    other = meetings.loc["11"]  # a body the portal does not name; a packet is read where there is no agenda
    assert (other["body"], other["document"], other["agenda_url"], other["state"]) == ("Testing New Event", "HTML Mini-Packet", "", 1)


def test_a_member_is_someone_seen_voting_at_the_board_on_more_than_one_day():
    def vote(member, meeting, date):
        return {"item_id": "1", "meeting_id": meeting, "date": date, "matter_id": "", "matter_file": "", "member": member,
                "vote": "AYE", "motion": 1, "motion_text": ""}
    today = pd.Timestamp.now(tz="UTC")
    near, far = (today - pd.Timedelta(days=10)).strftime("%Y-%m-%d"), (today - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    votes = pd.DataFrame([vote("A", "1", "2023-01-10"), vote("A", "2", near), vote("B", "1", "2023-01-10"), vote("B", "3", "2023-02-14"),
                          vote("Clerk", "1", "2023-01-10"),  # once, a slip
                          vote("Commissioner", "8", far), vote("Commissioner", "9", near)])  # another body's member
    meetings = pd.DataFrame({"meeting_id": ["1", "2", "3", "8", "9"], "committee_id": ["25"] * 3 + ["16"] * 2})
    members = prime.members_table(votes, meetings, {"25"})
    assert list(members.columns) == council_tables.COLUMNS["members"]
    assert [(m.name, m.serving, m.first_vote, m.votes) for m in members.itertuples()] == [("A", True, "2023-01-10", 2), ("B", False, "2023-01-10", 2)]
    assert members["district"].isna().all() and set(members["start"]) == {""}


def portal(events, pages, asked):
    """A stand-in for the host: the list of meetings, and a page for each document."""
    def fetch(url):
        if url.endswith("ListUpcomingMeetings"):
            return "[]"
        if url.endswith("GetArchivedMeetingYears"):
            return "[2024, 2023]"
        if "ListArchivedMeetings?year=" in url:
            return json.dumps([e for e in events if e["dateTime"].startswith(url[-4:])])
        if "GetCommitteeesListByShowInPublicPortal" in url:
            return json.dumps([{"id": 25, "name": "Board of Supervisors"}])
        template = url.rsplit("=", 1)[1]
        asked.append(template)
        if pages.get(template) is None:
            raise prime.requests.ConnectionError("no answer")
        return pages[template]
    return fetch


def test_a_run_reads_the_newest_first_and_only_what_it_has_not_read_or_what_has_changed(monkeypatch, tmp_path):
    events = [event(n, f"2023-{n:02d}-07T09:00:00", [paper("HTML Agenda", 100 + n, 3), paper("Minutes", 200 + n)]) for n in range(1, 12)]
    events.append(event(12, "2024-01-09T09:00:00", [paper("HTML Minutes", 112, 3)]))
    events.append(event(13, "2024-02-06T09:00:00", [paper("Agenda", 113)]))  # only a PDF: nothing to read
    empty = "<html><body>Meeting</body></html>"
    pages = {str(100 + n): empty for n in range(1, 12)}
    pages.update({"112": MINUTES, "105": None})  # one page does not answer
    asked = []
    monkeypatch.setattr(prime, "fetch", portal(events, pages, asked))
    monkeypatch.setattr(council_tables, "published", lambda repo, name: None)
    monkeypatch.setattr(prime.county, "WORKERS", 1)
    tables, read = prime.build(KEY, True, False, tmp_path)
    assert asked == ["112"] + [str(100 + n) for n in range(11, 0, -1)] and read == 11
    meetings = tables["meetings"].set_index("meeting_id")
    assert meetings.loc["12", "document_read"] == "112 2025-01-02T17:36:49.57" and meetings.loc["12", "items"] == 7
    assert meetings.loc["5", "document_read"] == "" and meetings.loc["13", "document_id"] == ""
    assert len(tables["votes"]) == 20 and len(tables["items"]) == 7 and list(tables["members"]["name"]) == []  # one day of votes
    for name in council_tables.TABLES:
        assert list(tables[name].columns[:len(council_tables.COLUMNS[name])]) == council_tables.COLUMNS[name]

    # Again: a page that held nothing is remembered, and the one that did not answer is asked for.
    asked.clear()
    pages["105"] = empty
    again, read = prime.build(KEY, True, False, tmp_path)
    assert asked == ["105"] and read == 1 and len(again["votes"]) == 20

    # Minutes take the place of an agenda, and a page is published again: both are read again, and nothing else.
    events[2]["documentList"].append(paper("HTML Minutes", 303, 3))
    events[11]["documentList"][0]["publishDate"] = "2025-10-01T00:00:00"
    pages["303"] = MINUTES.replace("data-itemid='10", "data-itemid='30").replace("AgendaItem_10", "AgendaItem_30").replace("data-sectionid='", "data-sectionid='3")
    asked.clear()
    once_more, read = prime.build(KEY, True, False, tmp_path)
    assert asked == ["112", "303"] and read == 2 and len(once_more["votes"]) == 40
    assert list(once_more["members"]["name"]) == ["Amy Shuklian", "Dennis Townsend", "Eddie Valero", "Larry Micari", "Pete Vander Poel"]
    assert once_more["agenda_items"]["item_id"].is_unique


def answer(status, text="{}"):
    return type("Answer", (), {"status_code": status, "text": text, "raise_for_status": lambda self: None})()


def test_a_host_that_refuses_is_not_asked_again(monkeypatch):
    calls = []
    monkeypatch.setattr(prime, "_refused", set())
    monkeypatch.setattr(prime.requests, "get", lambda url, **more: calls.append(url) or answer(403))
    with pytest.raises(prime.Refused):
        prime.fetch("https://a.primegov.com/api/x")
    with pytest.raises(prime.Refused):
        prime.fetch("https://a.primegov.com/api/y")
    assert calls == ["https://a.primegov.com/api/x"]  # the second was not sent
    # A page that asks who is calling is a refusal too, whatever number it comes with.
    monkeypatch.setattr(prime.requests, "get", lambda url, **more: answer(200, "<html><head><title>Just a moment...</title></head></html>"))
    with pytest.raises(prime.Refused):
        prime.fetch("https://b.primegov.com/Portal/Meeting?meetingTemplateId=1")
    monkeypatch.setattr(prime.requests, "get", lambda url, **more: answer(200, "<html><head><title>Meeting</title></head></html>"))
    assert "Meeting" in prime.fetch("https://c.primegov.com/Portal/Meeting?meetingTemplateId=1")


def test_a_run_stops_when_the_host_refuses_and_keeps_what_it_read(monkeypatch, tmp_path):
    events = [event(n, f"2023-{n:02d}-07T09:00:00", [paper("HTML Minutes", 100 + n, 3)]) for n in range(1, 12)]
    asked = []
    listing = portal(events, {str(100 + n): MINUTES for n in range(1, 12)}, asked)

    def fetch(url):
        if url.endswith("=110"):
            prime._refused.add("tularecounty.primegov.com")
            raise prime.Refused("403")
        if prime._refused and "meetingTemplateId" in url:
            raise prime.Refused("refused before")
        return listing(url)

    monkeypatch.setattr(prime, "_refused", set())
    monkeypatch.setattr(prime, "fetch", fetch)
    monkeypatch.setattr(council_tables, "published", lambda repo, name: None)
    monkeypatch.setattr(prime.county, "WORKERS", 1)
    with pytest.raises(prime.Refused):
        prime.build(KEY, True, False, tmp_path)
    assert asked == ["111"]
    kept = pd.read_parquet(tmp_path / "meetings.parquet").set_index("meeting_id")
    assert kept.loc["11", "document_read"] != "" and (kept.drop("11")["document_read"] == "").all()
    assert pd.read_parquet(tmp_path / "votes.parquet")["meeting_id"].unique().tolist() == ["11"]


def test_the_card_has_the_countys_facts_written_in(monkeypatch, tmp_path):
    events = [event(n, f"2023-{n:02d}-07T09:00:00", [paper("HTML Minutes", 100 + n, 3)]) for n in range(1, 12)]
    monkeypatch.setattr(prime, "fetch", portal(events, {str(100 + n): MINUTES for n in range(1, 12)}, []))
    monkeypatch.setattr(council_tables, "published", lambda repo, name: None)
    tables, _ = prime.build(KEY, True, False, tmp_path)
    text = prime.card(KEY, tables)
    assert "{" not in text.split("---", 2)[2]
    assert "# Tulare County Board of Supervisors" in text and "chrissoria/tulare-county-board" in text
    assert "tularecounty.primegov.com" in text and "Votes are recorded from 2023-01-07 to 2023-11-07" in text
    tables["votes"] = tables["votes"].iloc[0:0]
    assert "publishes its minutes only as PDFs" in prime.card(KEY, tables)
    assert sorted(prime.BOARDS) == ["shasta-county", "tulare-county", "ventura-county"]
    assert prime.repo_of("ventura-county") == "chrissoria/ventura-county-board"
