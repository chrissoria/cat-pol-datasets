"""build_destiny_board reads a board's meetings and votes from the pages and documents of a Destiny Hosted site. No network here."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import build_destiny_board as board
import council_tables

KEY = "yolo-county"
SITE = "https://public.destinyhosted.com/agenda_publish.cfm?id=96561"

MONTH = """
<select name="get_year" id="y"><option value="2026" selected>2026</option><option value="2007">2007</option></select>
<table id="meeting-table"><thead><tr><td>Agendas</td><td>Meeting</td><td>Minutes</td><td>Other Links</td></tr></thead><tbody>
 <tr><td><a href="/agenda_publish.cfm&#x3f;id&#x3d;96561&amp;mt&#x3d;BOS&amp;get_month&#x3d;6&amp;get_year&#x3d;2026&amp;dsp&#x3d;ag&amp;seq&#x3d;3934">June 23, 2026</a></td>
     <td>Board of Supervisors</td>
     <td><a href="/agenda_publish.cfm&#x3f;id&#x3d;96561&amp;mt&#x3d;BOS&amp;dsp&#x3d;min&amp;seq&#x3d;3937">Minutes <span>for Board of Supervisors (06/23/2026)</span></a></td>
     <td><a href="https://yolocountyca.new.swagit.com/videos/391895">Video</a></td></tr>
 <tr><td><a href="agenda_publish.cfm?id=96561&mt=BOS&dsp=ag&seq=3972">June 30, 2026</a></td><td>Board of Supervisors Special <br> Meeting</td>
     <td class="tdempty">&nbsp;</td><td class="tdempty"></td></tr>
 <tr><td><a href="/yolocdocs/2007/BOS/20070626_549/546_06.26.07.pdf">June 26, 2007</a></td><td>Board of Supervisors</td>
     <td><a href="/yolocdocs/2007/BOS/20070626_549/546_06.26.07Minutes.pdf">Minutes</a></td><td></td></tr>
 <tr><td colspan="4"><hr></td></tr>
</tbody></table>
"""

SPACER = '<tr class="top"><td class="tdempty">&nbsp;</td><td class="tdempty">&nbsp;</td></tr>'


def item(line, number, title, memo=""):
    link = f'<a href="/agenda_publish.cfm&#x3f;id&#x3d;96561&amp;dsp&#x3d;agm&amp;seq&#x3d;{memo}&amp;rev&#x3d;0&amp;min&#x3d;3937&amp;ln&#x3d;{line}">{title}</a>'
    return (f'<tr class=" top"><td class=" mediumText">&nbsp;<a id="ReturnTo{line}" name="ReturnTo{line}"></a></td><td class="tdempty"></td>'
            f'<td class=" mediumText">{number}.</td><td class=" upperleft"><span>{link if memo else title}</span></td><td class="tdempty">&nbsp;</td></tr>')


def heading(title, boxed=False):
    inside = f'<table border="1"><thead><tr><th>{title}</th></tr></thead><tbody></tbody></table>' if boxed else f"<span>{title}</span>"
    return f'<tr class=" top"><td colspan="8">{inside}</td></tr>'


def entry(*boxes):
    cells = "&nbsp;".join(f'<table border="1"><tbody><tr><td><font></font><br><font></font> {"<font></font><br><font></font> ".join(box)}</td></tr></tbody></table>'
                          for box in boxes)
    return f'<tr class=" top upperleft"><td colspan="4" class="tdempty">&nbsp;</td><td colspan="4">{cells}</td></tr>'


def vote(order, words, mover, seconder, ayes, noes="None", abstain="None", absent="None", more=()):
    return [f"Minute Order No. {order}: {words}", "&#160;", f"MOVED BY:&nbsp;{mover} / SECONDED BY: {seconder}", f"AYES: {ayes}.",
            f"NOES: {noes}.", f"ABSTAIN: {abstain}.", f"ABSENT: {absent}.", *more]


MINUTES = f"""<html><body><div id="content"><form><div>
<table class="tableCollapsed"><thead>
 <tr class="top"><td><div><strong>YOLO COUNTY BOARD OF SUPERVISORS<br> MINUTES</strong><br><strong>JUNE 27, 2017</strong></div></td></tr>
 <tr class="top"><td><div><span><strong>COUNTY BOARD OF SUPERVISORS</strong><br> CHAIR, DUANE CHAMBERLAIN, DISTRICT 5<br>
   VICE-CHAIR, OSCAR <span>VILLEGAS</span>, DISTRICT 1<br> DON SAYLOR, DISTRICT 2<br> GARY SANDY, DISTRICT 3<br> JIM PROVENZA, DISTRICT 4</span></div></td></tr>
 <tr class="top"><td>Roll Call:<br> Chamberlain<br> Villegas</td></tr></thead></table>
<table class="tableCollapsed"><tbody>
 {SPACER}{heading("9:45 A.M. CALL TO ORDER", boxed=True)}
 {SPACER}{heading("Approval of Agenda")}
 {SPACER}{item(19864, 1, "Consider approval of agenda.")}
 {entry(vote("17-102", "Approved agenda as submitted.", "Sandy", "Provenza", "Villegas, Saylor, Sandy, Provenza, Chamberlain"))}
 {SPACER}{heading("CONSENT AGENDA", boxed=True)}
 {entry(vote("17-103", "Approved Consent Agenda Item Nos. 2 - 3.", "Saylor", "Villegas", "Villegas, Saylor, Sandy, Provenza, Chamberlain"))}
 {SPACER}{heading("General Government <hr>")}{SPACER}{heading("Clerk of the Board")}
 {SPACER}{item(19917, 2, "Approve the minutes of the June 6, 2017 meeting.", memo=5992)}
 {entry(["Approved the minutes on Consent."])}
 {SPACER}{item(19941, 3, "Adopt resolution opposing SB 649. (No general fund impact) (Blacklock)", memo=6391)}
 {entry(["Tim Ray addressed the Board of Supervisors on this item."],
        vote("17-104", "Approved recommended action by Resolution No. 17-85 .", "Provenza", "Saylor", "Saylor, Provenza, Chamberlain, Saylor",
             noes="Villegas", more=["RECUSE: Sandy."]))}
 {SPACER}{heading("CLOSED SESSION", boxed=True)}
 {SPACER}{item(19890, 4, "Public Report of action taken in Closed Session.")}
 {entry(["The Board approved by a 5-0 vote a settlement agreement."])}
</tbody></table>
<table><tr><td>AgendaQuick</td></tr></table></div></form></div></body></html>"""

MEETING = {"meeting_id": "1796", "date": "2017-06-27", "body": "Board of Supervisors", "agenda_kind": "page", "minutes_kind": "page",
           "agenda_url": f"{SITE}&dsp=ag&seq=1796", "minutes_url": f"{SITE}&dsp=min&seq=1799"}


def test_a_months_page_gives_each_meeting_with_what_its_agenda_and_minutes_are():
    assert board.years_of(MONTH) == [2007, 2026]
    new, coming, old = board.month_meetings(KEY, MONTH)
    assert (new["meeting_id"], new["date"], new["name"], new["agenda_kind"], new["minutes_kind"]) == \
        ("3934", "2026-06-23", "Board of Supervisors", "page", "page")
    assert new["minutes_url"] == new["url"] == f"{SITE}&dsp=min&seq=3937" and new["agenda_url"] == f"{SITE}&dsp=ag&seq=3934"
    assert new["video_url"] == "https://yolocountyca.new.swagit.com/videos/391895"
    # A meeting to come has an agenda and no minutes; its name is what the list calls it, its body the board.
    assert (coming["meeting_id"], coming["name"], coming["body"], coming["minutes_kind"], coming["url"]) == \
        ("3972", "Board of Supervisors Special Meeting", "Board of Supervisors", "", f"{SITE}&dsp=ag&seq=3972")
    # The oldest have documents for both, and the folder they are kept in for a number.
    assert (old["meeting_id"], old["agenda_kind"], old["minutes_kind"]) == ("20070626_549", "document", "document")
    assert old["minutes_url"] == "https://public.destinyhosted.com/yolocdocs/2007/BOS/20070626_549/546_06.26.07Minutes.pdf"
    assert [board.best(meeting) for meeting in (new, coming, old)] == ["minutes", "agenda", "minutes document"]


def test_a_minutes_page_is_read_into_lines_and_each_members_vote(monkeypatch):
    monkeypatch.setattr(board, "fetch", lambda url, **how: MINUTES)
    agenda, votes, source = board.read_meeting(KEY, MEETING)
    assert source == "minutes"
    lines = {line["title"][:20]: line for line in agenda}
    assert [(line["agenda_number"], line["heading"], line["title"][:20]) for line in agenda] == [
        ("", True, "9:45 A.M. CALL TO ORD"[:20]), ("", True, "Approval of Agenda"), ("1", False, "Consider approval of"),
        ("", True, "CONSENT AGENDA"), ("", True, "General Government"), ("", True, "Clerk of the Board"), ("2", False, "Approve the minutes "),
        ("3", False, "Adopt resolution opp"), ("", True, "CLOSED SESSION"), ("4", False, "Public Report of act")]

    # The members are named from the head of the page, where each has a district.
    first = [(v["member"], v["vote"], v["district"], v["name_in_minutes"]) for v in votes if v["minute_order"] == "17-102"]
    assert first == [("Oscar Villegas", "AYE", 1, "Villegas"), ("Don Saylor", "AYE", 2, "Saylor"), ("Gary Sandy", "AYE", 3, "Sandy"),
                     ("Jim Provenza", "AYE", 4, "Provenza"), ("Duane Chamberlain", "AYE", 5, "Chamberlain")]
    agreed = lines["Consider approval of"]
    assert (agreed["action"], agreed["result"], agreed["mover"], agreed["seconder"], agreed["ayes"], agreed["noes"], agreed["minute_order"]) == \
        ("Approved agenda as submitted.", "", "Gary Sandy", "Jim Provenza", 5, 0, "17-102")

    # The consent agenda's vote is on its heading; an item under it has what the clerk wrote of it and no votes of its own.
    consent, minutes = lines["CONSENT AGENDA"], lines["Approve the minutes "]
    assert (consent["motions"], consent["ayes"]) == (1, 5) and consent["item_id"] in {v["item_id"] for v in votes}
    assert (minutes["action"], minutes["motions"], minutes["section_id"], minutes["section"], minutes["subject"]) == \
        ("Approved the minutes on Consent.", 0, consent["item_id"], "CONSENT AGENDA", "Clerk of the Board")
    assert minutes["matter_id"] == "5992" and minutes["url"] == f"{SITE}&dsp=agm&seq=5992&rev=0&min=1799&ln=19917"

    # A divided vote: Saylor is entered twice and counted once, and the body's RECUSE is RECUSED.
    divided = [(v["member"], v["vote"]) for v in votes if v["minute_order"] == "17-104"]
    assert divided == [("Don Saylor", "AYE"), ("Jim Provenza", "AYE"), ("Duane Chamberlain", "AYE"), ("Oscar Villegas", "NO"), ("Gary Sandy", "RECUSED")]
    opposed = lines["Adopt resolution opp"]
    assert (opposed["ayes"], opposed["noes"], opposed["not_voting"], opposed["result"], opposed["doc_type"]) == (3, 1, 1, "", "resolution")
    assert opposed["action"] == "Approved recommended action by Resolution No. 17-85 ." and opposed["minutes"].startswith("Tim Ray addressed")

    # Where the minutes give no names, what was done is recorded and there are no votes.
    reported = lines["Public Report of act"]
    assert (reported["action"], reported["motions"], reported["result"], reported["matter_id"]) == \
        ("The Board approved by a 5-0 vote a settlement agreement.", 0, "", reported["item_id"])
    assert not [v for v in votes if v["item_id"] == reported["item_id"]]
    assert set(v["vote"] for v in votes) == {"AYE", "NO", "RECUSED"} and len(votes) == 15


def test_a_vote_is_read_by_its_labels_however_the_clerk_spelled_them():
    one = board.motions_of("Minute Order No. 18-212: Elected a Chair.\nMOTION BY: Provenza / SECONDED: Rexroad\n"
                           "YES: Saylor, Rexroad and Provenza\nNOES: None\nABTAIN: Chamberlain\nABSENTS: Villegas.\nRECUSED: None.")
    assert one == [{"minute_order": "18-212", "text": "Elected a Chair.", "mover": "Provenza", "seconder": "Rexroad",
                    "votes": [("Saylor", "AYE"), ("Rexroad", "AYE"), ("Provenza", "AYE"), ("Chamberlain", "ABSTAIN"), ("Villegas", "ABSENT")]}]
    # The oldest minutes set a vote on one line, and leave out what nobody did.
    old = board.motions_of("Minute Order No. 07-108: Approved the agenda.\nMOTION: Rexroad. SECOND: McGowan. AYES: Chamberlain, McGowan, Thomson,\nRexroad, Yamada.")
    assert (old[0]["mover"], old[0]["seconder"], [name for name, word in old[0]["votes"]]) == \
        ("Rexroad", "McGowan", ["Chamberlain", "McGowan", "Thomson", "Rexroad", "Yamada"])


def test_two_motions_in_one_entry_are_two_and_a_note_is_none():
    entry = ("Carolyn Pfanner addressed the Board. Motion made by Supervisor Provenza died for lack of a second.\n"
             "Minute Order No. 15-173: Substitute motion to approve A and C.\nMOVED BY: Saylor / SECONDED BY: Provenza\n"
             "AYES: Provenza, Chamberlain, Villegas, Saylor, Rexroad.\nNOES: None.\nABSTAIN: None.\nABSENT: None.\n"
             "Minute Order No. 15-174: Rescinded Minute Order No. 15-173 and approved B. Motion passed 4:1.\nMOVED BY: Provenza / SECONDED BY: Rexroad\n"
             "AYES: Provenza, Chamberlain, Villegas, Rexroad.\nNOES: Saylor.\nABSTAIN: None.\nABSENT: None.")
    first, second = board.motions_of(entry)
    assert (first["minute_order"], first["text"], len(first["votes"])) == ("15-173", "Substitute motion to approve A and C.", 5)
    # The order a motion speaks of is not its own number.
    assert (second["minute_order"], second["mover"], second["votes"][-1]) == ("15-174", "Provenza", ("Saylor", "NO"))
    assert second["text"] == "Rescinded Minute Order No. 15-173 and approved B. Motion passed 4:1."
    assert board.motions_of("Supervisor Villegas recused himself. Received presentation. No vote was taken.") == []
    assert board.motions_of("PRESENT: Aguiar-Curry, Kristoff\nABSENT: None") == []  # a roll call is not a vote
    assert board.motions_of("MOVED BY: Sandy / SECONDED BY: Saylor\nAYES: None\nNOES: None")[0]["votes"] == []


def test_names_are_a_list_of_names_or_nobody():
    assert board.names_of(" Vixie Sandy, Supervisor Allen and Frerichs.\nNOES") == ["Vixie Sandy", "Allen", "Frerichs"]
    assert board.names_of(" Thomson, Rexroad,\nYamada\nGeneral Government") == ["Thomson", "Rexroad", "Yamada"]
    assert board.names_of(" Sandy. Provenza") == ["Sandy", "Provenza"]  # a full stop where a comma was meant
    assert board.names_of(" None.") == [] and board.names_of("") == []
    assert board.names_of(" None. The Board then recessed until 1:30 p.m. for lunch") == []  # a sentence is nobody: no vote sooner than a wrong one


def test_a_member_is_who_sat_that_day_under_the_surname_the_clerk_typed():
    roster = board.roster_of("COUNTY BOARD OF SUPERVISORS\nCHAIR, MICHAEL H. MCGOWAN, DISTRICT 1\nVICE-CHAIRMAN, HELEN M. THOMSON, DISTRICT 2\n"
                             "MARY VIXIE SANDY , DISTRICT 3\nVICE-CHAIR DUANE CHAMBERLAIN, DISTRICT 5\nVACANT, DISTRICT 4\n625 COURT STREET, ROOM 206")
    assert roster == [("MICHAEL H. MCGOWAN", 1), ("HELEN M. THOMSON", 2), ("MARY VIXIE SANDY", 3), ("DUANE CHAMBERLAIN", 5)]
    assert board.named(roster, "McGowan") == ("Michael H. McGowan", 1)
    assert board.named(roster, "Sandy") == board.named(roster, "Vixie Sandy") == ("Mary Vixie Sandy", 3)
    assert board.named(roster, "CHAMBERLAIN") == ("Duane Chamberlain", 5)
    # A slip of the clerk's is nobody at the head of the page, and is kept as it was typed.
    assert board.named(roster, "Chambelain") == ("Chambelain", None) and board.named(roster, "") == ("", None)
    assert board.named([("GARY SANDY", 3), ("MARY VIXIE SANDY", 3)], "Sandy") == ("Sandy", None)


DOCUMENT = """COUNTY BOARD OF SUPERVISORS
CHAIR, DON SAYLOR, DISTRICT 2
VICE-CHAIR, MATT REXROAD, DISTRICT 3
JIM PROVENZA, DISTRICT 4
BOARD OF SUPERVISORS CHAMBERS
Roll Call:
Rexroad
9:00 A.M. CALL TO ORDER
Pledge of Allegiance.
Approval of Agenda
1. Consider approval of agenda.
Minute Order No. 14-93: Approved agenda as submitted.
MOVED BY: Saylor / SECONDED BY: Rexroad
AYES: Rexroad, Saylor
NOES: None
ABSTAIN: None
ABSENT: Provenza
Public Comment
2. Opportunity for members of the public to address the Board of Supervisors on
subjects relating to County business until June
30. The Board reserves the right to impose a limit.
There was no public comment.
CONSENT AGENDA
Minute Order No. 14-94: Approved Consent Agenda Item Nos. 3-4.
MOVED BY: Rexroad / SECONDED BY: Saylor
AYES: Rexroad, Saylor, Provenza
NOES: None
General Government
Clerk of the Board
3. Approve the minutes of the June 10, 2014 Board of Supervisors and June 17,
2014 Budget Hearing meetings.
Att. A. June 10, 2014 Minutes
Approved the minutes on Consent.
4.Adopt budget resolution for the District Attorney. (No general fund impact)
(Reisig/Bair)
Att. A. Resolution
Minute Order No. 14-95: Approved recommended action by Budget Resolution No. 13-
104.26.
MOVED BY: Rexroad / SECONDED BY: Provenza
AYES: Rexroad, Saylor
NOES: Provenza
ADJOURNMENT
"""


def test_minutes_kept_as_a_document_are_read_from_their_text():
    lines = board.document_lines(DOCUMENT)
    assert [(line["kind"], line["number"], line["title"][:28]) for line in lines] == [
        ("section", "", "9:00 A.M. CALL TO ORDER"), ("item", "1", "Consider approval of agenda."),
        ("item", "2", "Opportunity for members of t"), ("section", "", "CONSENT AGENDA"), ("item", "3", "Approve the minutes of the J"),
        ("item", "4", "Adopt budget resolution for "), ("section", "", "ADJOURNMENT")]
    # A figure that begins a line of running text ("30.") is not an item: an agenda's numbers run on from each other.
    assert "30. The Board reserves" in lines[2]["title"] and lines[2]["entries"] == ["There was no public comment."]
    assert lines[5]["title"] == "Adopt budget resolution for the District Attorney. (No general fund impact) (Reisig/Bair)"
    consent, budget = board.motions_of(lines[3]["entries"][0]), board.motions_of(lines[5]["entries"][0])
    assert (consent[0]["minute_order"], len(consent[0]["votes"])) == ("14-94", 3)
    assert (budget[0]["text"], budget[0]["votes"]) == ("Approved recommended action by Budget Resolution No. 13- 104.26.",
                                                      [("Rexroad", "AYE"), ("Saylor", "AYE"), ("Provenza", "NO")])


def test_a_special_meetings_document_may_begin_at_any_number_under_its_first_heading():
    text = ("COUNTY BOARD OF SUPERVISORS\nCHAIRWOMAN, HELEN M. THOMSON, DISTRICT 2\nBOARD OF SUPERVISORS CHAMBERS\nRoll Call:\nThomson\n"
            "1:30 P.M. CLOSED SESSION (ITEM 5.01)\n5.01 Conference with Legal Counsel - Anticipated Litigation\n1 case(s)\n"
            "TIME SET AGENDA (ITEM 3.01)\n3.04 2:00 P.M. County Counsel\nPublic hearing.\nMinute Order No. 10-252: Approved recommended action.\n"
            "MOVED BY: McGowan / SECONDED BY: Rexroad\nAYES: Rexroad, McGowan, Thomson\nNOES: Provenza, Chamberlain\nADJOURNMENT\n"
            "I declare that the foregoing agenda was posted at the following places:\n1. On the bulletin board at the east entrance.\n")
    lines = board.document_lines(text)
    # The title page's capitals are not headings. A number that goes back (3.04 after 5.01) is not taken for an item, nor is a list's "1.",
    # so the vote stays under the heading above it and is not lost.
    assert [(line["kind"], line["number"], line["title"][:27]) for line in lines] == [
        ("section", "", "1:30 P.M. CLOSED SESSION (I"), ("item", "5.01", "Conference with Legal Couns"), ("section", "", "TIME SET AGENDA (ITEM 3.01)"),
        ("section", "", "ADJOURNMENT")]
    assert [len(board.motions_of(entry)) for entry in lines[2]["entries"]] == [1]
    assert board.roster_of(text) == [("HELEN M. THOMSON", 2)]


def test_a_document_is_set_under_the_lines_of_the_agendas_page(monkeypatch):
    line = lambda kind, number, title, memo="": {"kind": kind, "number": number, "line": "9" + number, "memo": memo, "title": title, "entries": []}
    page = [line("section", "", "9:00 A.M. CALL TO ORDER"), line("heading", "", "Approval of Agenda"), line("item", "1", "Consider approval of agenda."),
            line("heading", "", "Public Comment"), line("item", "2", "Opportunity to address the Board."), line("section", "", "CONSENT AGENDA"),
            line("heading", "", "General Government"), line("heading", "", "Clerk of the Board"),
            line("item", "3", "Approve the minutes of the June 10, 2014 Board of Supervisors and June 17, 2014 Budget Hearing meetings.", "2100"),
            line("item", "4", "Adopt budget resolution for the District Attorney. (No general fund impact) (Reisig/Bair)", "2101")]
    merged = board.under(page, board.document_lines(DOCUMENT))
    assert [found["title"] for found in merged] == [found["title"] for found in page]
    # The document's copy of the item's words, and of the headings of the item after, are not the clerk's.
    assert merged[2]["entries"][0].startswith("Minute Order No. 14-93") and merged[2]["entries"][0].endswith("ABSENT: Provenza")
    assert merged[5]["entries"][0].endswith("NOES: None") and merged[8]["entries"] == ["Att. A. June 10, 2014 Minutes\nApproved the minutes on Consent."]
    # A vote on a line the page does not have would be lost, so the document's own lines stand.
    assert board.under(page[:-1], board.document_lines(DOCUMENT)) is None

    monkeypatch.setattr(board, "lines_of", lambda text: (page, ""))
    monkeypatch.setattr(board, "fetch", lambda url, **how: b"" if how.get("raw") else "")
    monkeypatch.setattr(board, "document_text", lambda content: DOCUMENT)
    meeting = {"meeting_id": "244", "date": "2014-06-24", "body": "Board of Supervisors", "agenda_kind": "page", "minutes_kind": "document",
               "agenda_url": f"{SITE}&dsp=ag&seq=244", "minutes_url": "https://public.destinyhosted.com/yolocdocs/2014/BOS/20140624_244/244_Minutes.pdf"}
    agenda, votes, source = board.read_meeting(KEY, meeting)
    assert source == "minutes document" and len(agenda) == 10
    # The page has no list of who sat (here), so it is taken from the head of the document.
    assert [(v["member"], v["vote"], v["district"]) for v in votes if v["minute_order"] == "14-95"] == \
        [("Matt Rexroad", "AYE", 3), ("Don Saylor", "AYE", 2), ("Jim Provenza", "NO", 4)]
    budget = agenda[-1]
    assert (budget["matter_id"], budget["result"], budget["ayes"], budget["noes"]) == ("2101", "", 2, 1)
    assert budget["url"] == f"{SITE}&dsp=agm&seq=2101&rev=0&ag=244&ln=94"


def test_the_oldest_minutes_head_each_item_with_its_number_on_a_line_of_its_own():
    text = ("M I N U T E S\nPresent were Supervisors Chamberlain and McGowan.\nAgenda Item No. 1.02\nApproval of Agenda\n"
            "Minute Order No. 07-02: Approved the agenda with these changes:\nAgenda Item No. 2.08 – (added to Regular Agenda): Approve lease.\n"
            "MOTION: Rexroad. SECOND: McGowan. AYES: Chamberlain, McGowan,\nRexroad.\nAgenda Item No. 1.03\nPublic Comment\nThere was no public comment.\n"
            "Consent Agenda\nMinute Order No. 07-04: Acted on the Consent Agenda as follows:\n2.01 Approved the minutes.\n2.02 Approved Agreement No. 07-01.\n"
            "MOTION: McGowan. SECOND: Rexroad. AYES: Chamberlain, McGowan, Rexroad.\nAgenda Item No. 3.01 A-3\nUpdate on Climate Change\nRECEIVED REPORT.\n")
    lines = board.document_lines(text)
    assert [(line["kind"], line["number"], line["title"]) for line in lines] == [
        ("item", "1.02", "Approval of Agenda"), ("item", "1.03", "Public Comment"), ("section", "", "Consent Agenda"),
        ("item", "3.01A-3", "Update on Climate Change")]
    assert [len(board.motions_of(entry)) for line in lines for entry in line["entries"]] == [1, 0, 1, 0]


def test_what_is_printed_on_every_page_of_a_document_is_left_out(monkeypatch):
    class Page:
        def __init__(self, text):
            self.text = text

        def extract_text(self):
            return self.text

    class Document:
        pages = [Page(f"{number}. Approve {thing}.\nAYES: Thomson\nNOES: None\nABSTAIN: None\nABSENT: None\n"
                      f"Board of Supervisors Minutes {number} June 26, 2007\n*Estimated times for planning purposes")
                 for number, thing in enumerate(("the agenda", "a lease", "two agreements", "the budget"), 1)] + [Page("")]
        __enter__ = lambda self: self
        __exit__ = lambda self, *error: None

    monkeypatch.setattr(board.pdfplumber, "open", lambda content: Document())
    text = board.document_text(b"").split("\n")
    assert len(text) == 20 and "Minutes" not in " ".join(text) and "*Estimated times for planning purposes" not in text
    # A vote's own lines are kept though they end every page, and so is each page's first line.
    assert text[-5:] == ["4. Approve the budget.", "AYES: Thomson", "NOES: None", "ABSTAIN: None", "ABSENT: None"]


def test_an_order_of_an_earlier_meeting_quoted_under_a_later_one_is_not_a_vote(monkeypatch):
    tally = "MOVED BY: Saylor / SECONDED BY: Rexroad\nAYES: Rexroad, Saylor, Provenza\nNOES: None"
    lines = [{"kind": "item", "number": "3", "line": "", "memo": "", "title": "Approve the minutes of July 17.", "entries": [
        f"Minute Order No. 14-245: Approved minutes with the following edits:\n{tally}\nPage 17\nMinute Order No. 14-215: Approved the district.\n{tally}",
        f"Minute Order No. 14-246: Approved the minutes of July 31.\n{tally}", f"Minute Order No. 14-246: Approved the minutes of July 31.\n{tally}"]}]
    monkeypatch.setattr(board, "lines_of", lambda text: (lines, ""))
    monkeypatch.setattr(board, "fetch", lambda url, **how: "")
    agenda, votes, source = board.read_meeting(KEY, MEETING)
    # 14-215 was a vote of the earlier meeting. On a line that quotes one, this meeting's own motions and the quoted ones
    # cannot be told apart for sure, so none of its votes is read; what the clerk entered is kept.
    assert agenda[0]["motions"] == 0 and votes == [] and "14-245" in agenda[0]["action"]


def test_a_refusal_is_not_asked_twice(monkeypatch):
    asked = []

    class Answer:
        status_code, text, headers = 403, "Access Denied", {"content-type": "text/html"}

    def get(url, **how):
        asked.append(url)
        return Answer()

    monkeypatch.setattr(board.requests, "get", get)
    monkeypatch.setattr(board, "refused", board.threading.Event())
    with pytest.raises(board.Refused):
        board.fetch("https://public.destinyhosted.com/one")
    with pytest.raises(board.Refused):
        board.fetch("https://public.destinyhosted.com/two")
    assert asked == ["https://public.destinyhosted.com/one"] and board.refused.is_set()


def listing():
    meeting = lambda number, date, minutes: {
        "meeting_id": number, "date": date, "time": "", "body": "Board of Supervisors", "location": "", "url": f"{SITE}&dsp=ag&seq={number}",
        "agenda_url": f"{SITE}&dsp=ag&seq={number}", "minutes_url": f"{SITE}&dsp=min&seq={number}9" if minutes else "", "items": 0,
        "name": "Board of Supervisors", "video_url": "", "agenda_kind": "page", "minutes_kind": "page" if minutes else "", "source": ""}
    old = [meeting(str(100 + at), f"2017-{at:02d}-06", True) for at in range(1, 11)]
    return old + [meeting("300", "2017-11-07", False), meeting("301", "2017-12-05", False)]


def test_a_run_reads_the_newest_first_skips_what_it_has_read_and_reads_again_what_now_has_minutes(monkeypatch, tmp_path):
    meetings, asked = listing(), []

    def fetch(url, **how):
        asked.append(url)
        return MINUTES if "dsp=min" in url else "<table><tbody>" + heading("9:00 A.M. CALL TO ORDER", boxed=True) + item(7, 1, "An item") + "</tbody></table>"

    monkeypatch.setattr(board, "listed", lambda key: [dict(meeting) for meeting in meetings])
    monkeypatch.setattr(board, "fetch", fetch)
    monkeypatch.setattr(council_tables, "published", lambda repo, name: None)
    monkeypatch.setattr(board.county, "WORKERS", 1)
    tables, read = board.build(KEY, True, False, tmp_path)
    assert read == 12 and asked[0].endswith("seq=301") and asked[-1].endswith("seq=1019")
    assert council_tables.standard(tables) and all(len(tables[name]) for name in council_tables.TABLES)
    sources = dict(zip(tables["meetings"]["meeting_id"], tables["meetings"]["source"]))
    assert (sources["101"], sources["300"]) == ("minutes", "agenda") and len(tables["votes"]) == 150
    assert not tables["votes"].duplicated(["item_id", "motion", "member"]).any()
    assert dict(zip(tables["meetings"]["meeting_id"], tables["meetings"]["time"]))["101"] == "9:45 AM"

    # Members: the five at the head of the minutes, with their districts and no one else.
    members = tables["members"]
    assert list(members.sort_values("district")["name"]) == ["Oscar Villegas", "Don Saylor", "Gary Sandy", "Jim Provenza", "Duane Chamberlain"]
    assert list(members.sort_values("district")["district"]) == [1, 2, 3, 4, 5] and not members["serving"].any()

    # An item with a memo is one item however many agendas it is on; its vote on consent is the heading's.
    items = tables["items"].set_index("matter_id")
    assert (items.loc["5992", "times_on_agenda"], items.loc["5992", "action_on"], items.loc["5992", "result"], items.loc["5992", "ayes"]) == (10, "section", "", 5)
    assert (items.loc["5992", "date"], items.loc["5992", "agenda_date"], items.loc["6391", "action_on"], items.loc["6391", "noes"]) == \
        ("2017-01-06", "2017-10-06", "item", 1)

    # The next run asks only for the meeting whose minutes have come in since.
    asked.clear()
    meetings[-2].update(minutes_kind="page", minutes_url=f"{SITE}&dsp=min&seq=3009")
    again, read = board.build(KEY, True, False, tmp_path)
    assert read == 1 and asked == [f"{SITE}&dsp=min&seq=3009"] and len(again["votes"]) == 165
    assert dict(zip(again["meetings"]["meeting_id"], again["meetings"]["source"]))["300"] == "minutes"
    assert len(again["agenda_items"][again["agenda_items"]["meeting_id"] == "300"]) == 10


def test_minutes_with_no_list_of_who_sat_take_their_members_from_the_nearest_that_have_one():
    row = lambda meeting, date, member, district, typed: {"item_id": f"{meeting}-1", "meeting_id": meeting, "date": date, "matter_id": "",
                                                          "matter_file": "", "member": member, "vote": "AYE", "district": district, "motion": 1,
                                                          "motion_text": "", "minute_order": "", "name_in_minutes": typed}
    votes = pd.DataFrame([row("a", "2007-04-17", "Yamada", None, "Yamada"), row("a", "2007-04-17", "Robyn", None, "Robyn"),
                          row("b", "2007-05-01", "Mariko Yamada", 4, "Yamada"), row("c", "2019-05-01", "Kenji Yamada", 2, "Yamada"),
                          row("d", "2012-05-01", "Sandy", None, "Sandy")], columns=board.VOTE_COLUMNS)
    votes["district"] = votes["district"].astype("Int64")
    agenda = pd.DataFrame([{**dict.fromkeys(board.AGENDA_COLUMNS, ""), "item_id": "a-1", "meeting_id": "a", "date": "2007-04-17", "motions": 1,
                            "mover": "Yamada", "seconder": "Robyn"}], columns=board.AGENDA_COLUMNS)
    agenda, votes = board.seated(agenda, votes)
    assert list(votes["member"]) == ["Mariko Yamada", "Robyn", "Mariko Yamada", "Kenji Yamada", "Sandy"]
    assert list(votes["district"].fillna(0)) == [4, 0, 4, 2, 0]
    assert (agenda.loc[0, "mover"], agenda.loc[0, "seconder"]) == ("Mariko Yamada", "Robyn")


def test_the_card_has_every_fact_written_in(monkeypatch, tmp_path):
    monkeypatch.setattr(board, "listed", lambda key: listing())
    monkeypatch.setattr(board, "fetch", lambda url, **how: MINUTES)
    monkeypatch.setattr(council_tables, "published", lambda repo, name: None)
    tables, read = board.build(KEY, True, False, tmp_path)
    card = board.card(KEY, tables)
    assert not re.findall(r"\{[a-z_]+\}", card)
    assert "# Yolo County Board of Supervisors" in card and "chrissoria/yolo-county-board" in card
    assert "The votes here\nare `AYE`, " in card and "`RECUSED`" in card and "run from 2017-01-06 to 2017-12-05" in card
