"""build_amador_board reads the Amador County Board's votes out of draft minutes attached to the agenda of the meeting
that approved them: by name where the minutes list the names, and otherwise only where their own words leave no doubt."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import build_amador_board as am
import council_tables

ROLL = ["Brian Oneto", "Patrick Crew", "Frank U. Axe", "Richard M. Forster", "Jeff Brown"]
MEETING = {"meeting_id": "430", "date": "2024-06-11"}

# Minutes as the reader keeps them: an empty line is a gap the page leaves between two paragraphs, a form feed parts
# two pages, and the line at a page's foot stands above it. Pieces are from the draft minutes of 11 June 2024.
MINUTES = """Amador County Board of Supervisors
ACTION MINUTES
REGULAR MEETING

DATE: Tuesday, June 11, 2024
TIME: 9:00 a.m.
LOCATION: County Administration Center, 810 Court Street, Jackson,
California

Present on Roll Call:

Brian Oneto, District V – Chairman
Patrick Crew, District I –Vice-Chairman
Frank U. Axe, District IV
Richard M. Forster, District II
Jeff Brown, District IIIJeff Brown, District III

Staff: Charles T. Iley, County Administrative Officer
Heather Peek, Deputy Clerk of the Board

Absent: None

NOTE: These minutes remain in Draft form until approved by Minute Order at the next regular meeting of
the Board of Supervisors.

CLOSED SESSION may be called for labor negotiations. At 8:30 a.m., the Board convened into
closed session.

Confidential Minutes: Review and possible approval of the May 28, 2024 Confidential Minutes.

ACTION: Direction given pursuant to the following motion.

MOTION: It was moved by Supervisor Axe, seconded by Supervisor Forster and
carried unanimouslyto approve the May 28, 2024 Confidential Minutes.

PLEDGE OF ALLEGIANCE: Chairman Oneto led the Board and the public in the Pledge of
Allegiance.

AGENDA: Approval of agenda for this date; any and all off-agenda items must be approved by
the Board.

ACTION: Direction given pursuant to the following motion.

MOTION: It was moved by Supervisor Forster, seconded by Supervisor Crew and
carried unanimously to approve the agenda as presented.
June 11, 2024-DRAFT MINUTES 1
\fCONSENT AGENDA: Items listed on the consent agenda are considered routine and may be
enacted by one motion.

ACTION: Direction given pursuant to the following motion.

MOTION: It was moved by Supervisor Crew, seconded by Supervisor Axe and
carried unanimously to approve the consent agenda as amended.

Chairman Oneto requested to pull consent agenda item 5.b. for discussion.

Sheriff’s Office Mid-Management Association (SOMMA) Side Letter of Agreement.

ACTION: Direction given pursuant to the following motion.

MOTION: It was moved by Supervisor Forster, seconded by Supervisor Crew, and
carried 3-2 to approve the Side Letter of Agreement.
Ayes: Supervisors Crew, Forster, Brown
Noes: Supervisor Oneto, Axe
Absent: None

REGULAR AGENDA

Public Works Department: Carbondale Road Bridge Replacement.

Mr. Richard Vela, Public Works Director, addressed the Board.

ACTION: Informational only.

General Services Administration: Award of the bid for the Carbondale Road project.

**Supervisor Brown recused himself from voting on this item to avoid any perceived conflict.**

ACTION: Direction given pursuant to the following motion.

MOTION: It was moved by Supervisor Axe, seconded by Supervisor Crew and carried unanimously
to award the bid.

Administrative Agency: Request for a waiver of fees.

ACTION: Direction given pursuant to the following motion.

MOTION: It was moved by Supervisor Forster, seconded by SupervisorCrew, and
unanimously carried to waive the fees as requested.

PUBLIC HEARING 10:30 A.M.

Planning Department: Consideration of a Variance from the front setback requirement.

Chairman Oneto opened the Public Hearing at this time. There were no public comments.
June 11, 2024-DRAFT MINUTES 2
\fACTION #1: Public Hearing closed pursuant to the following motion.

MOTION #1: It was moved by Supervisor Forster, seconded by Supervisor Axe and
unanimously carried, to close the public hearing.

Discussion ensued with the following action being taken.

ACTION #2: Direction given pursuant to the following motion.

MOTION #2: It was moved by Supervisor Axe, seconded by Supervisor Brown and
carried 4-0-1 to adopt a resolution approving the requested variance, with these findings:
Ayes: Supervisors Oneto, Crew, Axe, Brown
Noes: None
Abstain: Forster

Findings:
1. This variance does not constitute the granting of a special privilege.

RESOLUTION NO. 24-077

Approving a Variance to County Code 19.24.040.

ADJOURNMENT: Until Tuesday, June 25, 2024 at 8:30 a.m.

June 11, 2024, CONSENT MINUTES

5.a. Juvenile Justice Commission: Approve the appointment of Stephen Hartmann to the subject
committee.
ACTION: Approved

5.b. Resolution Approval for the Sheriff's Office to Apply for the G24 Grant.
ACTION: Approved-Resolution No. 24-078
"""


def motion(words, *cast):
    return {"text": words, "cast": list(cast), **am.said_of(words)}


def read(text=MINUTES):
    agenda, votes, facts = am.read_meeting(MEETING, am.scan(text), pages=text.count("\f") + 1)
    return agenda, {row["title"][:24]: row for row in agenda}, votes, facts


def cast_of(votes, item_id, number=1):
    return {row["member"]: (row["vote"], row["established"]) for row in votes if row["item_id"] == item_id and row["motion"] == number}


def test_the_listing_gives_the_boards_meetings_and_not_the_other_bodies():
    page = """<table><tr class="listingRow"><td class="listItem" headers="Name" id="Board-of-Equalization" scope="row"> Board of Equalization </td>
      <td class="listItem" headers="Date Board-of-Equalization"> May&nbsp;19,&nbsp;2026 - 12:00&nbsp;PM </td>
      <td class="listItem"><a href="//amador.granicus.com/AgendaViewer.php?view_id=1&event_id=615">Agenda</a></td></tr>
    <tr class="listingRow"><td class="listItem" headers="Name" id="Board-of-Supervisors" scope="row"> Board of Supervisors </td>
      <td class="listItem" headers="Date Board-of-Supervisors"> Apr&nbsp; 9,&nbsp;2019 - 09:00&nbsp;AM </td>
      <td class="listItem"> <a href="//amador.granicus.com/AgendaViewer.php?view_id=1&event_id=125" target="_blank">Agenda</a> </td>
      <td class="listItem" headers="AgendaPacketLink"><a href="https://d3n9y02raazwpg.cloudfront.net/amador/bc27.pdf">Agenda Packet</a></td></tr>
    <tr class="listingRow"><td class="listItem" headers="Name" scope="row"> Board of Supervisors </td>
      <td class="listItem" headers="Date"> Apr&nbsp; 9,&nbsp;2019 - 09:00&nbsp;AM </td>
      <td class="listItem"><a href="//amador.granicus.com/AgendaViewer.php?view_id=1&event_id=125">Agenda</a></td></tr></table>"""
    meetings = am.meetings_table(am.rows_of(page))
    assert list(meetings["meeting_id"]) == ["125"]  # the Board of Equalization is another body, and a row printed twice is one meeting
    first = meetings.iloc[0]
    assert (first["date"], first["time"], first["body"], bool(first["listed"])) == ("2019-04-09", "9:00 AM", "Board of Supervisors", True)
    assert first["agenda_url"] == "https://amador.granicus.com/AgendaViewer.php?view_id=1&event_id=125"
    assert first["packet_url"] == "https://d3n9y02raazwpg.cloudfront.net/amador/bc27.pdf" and first["minutes_url"] == ""
    assert list(meetings.columns)[:len(council_tables.COLUMNS["meetings"])] == council_tables.COLUMNS["meetings"]


def test_the_boards_own_minutes_are_picked_out_of_what_an_agenda_has_attached():
    links = ["https://legistarweb-production.s3.amazonaws.com/uploads/attachment/pdf/2698956/June_11__2024_DRAFT_Minutes.pdf",
             "https://legistarweb-production.s3.amazonaws.com/uploads/attachment/pdf/2693080/PC_Minutes_excerpt_05-14-24.pdf",
             "https://amador.granicus.com/services/legistar/download/pdf/4338480/August_25__2026_DRAFT_Minutes.pdf",
             "https://amador.granicus.com/services/legistar/download/pdf/4032060/September_23__2025_FINAL_Minutes.pdf",
             "https://amador.granicus.com/services/legistar/download/pdf/2746191/July_16__2024_DRAFT_Special_Meeting_Minutes__Autosaved_.pdf",
             "https://amador.granicus.com/services/legistar/download/pdf/4155993/2-_LUC_Minutes_07-29-25.pdf",
             "https://amador.granicus.com/services/legistar/download/pdf/4107395/Draft_Park_and_Rec_Committee_Minutes__3-3-26_.pdf",
             "https://amador.granicus.com/services/legistar/download/pdf/4342311/Management_Salary_9.28.2025_DRAFT_amended_9.8.2026.pdf",
             "https://zoom.us/j/123", ""]
    assert am.attached(links) == [["2698956", "June_11__2024_DRAFT_Minutes.pdf"],
                                  ["2746191", "July_16__2024_DRAFT_Special_Meeting_Minutes__Autosaved_.pdf"],
                                  ["4032060", "September_23__2025_FINAL_Minutes.pdf"], ["4338480", "August_25__2026_DRAFT_Minutes.pdf"]]
    assert am.address("2698956", "June_11__2024_DRAFT_Minutes.pdf") == \
        "https://amador.granicus.com/services/legistar/download/pdf/2698956/June_11__2024_DRAFT_Minutes.pdf"


def test_the_head_gives_the_day_the_roll_and_who_was_absent():
    head = am.head_of(MINUTES)
    assert (head["date"], head["time"], head["kind"], head["said"], head["absent"]) == ("2024-06-11", "9:00 AM", "REGULAR MEETING", True, [])
    assert [seat["name"] for seat in head["roll"]] == ROLL  # the last line, printed twice over, is one supervisor
    assert head["roll"][0] == {"name": "Brian Oneto", "district": 5, "role": "Chairman"}
    assert (head["roll"][1]["role"], head["roll"][2]) == ("Vice-Chairman", {"name": "Frank U. Axe", "district": 4, "role": ""})
    away = am.head_of(MINUTES.replace("Frank U. Axe, District IV\n", "").replace("Absent: None", "Absent: Frank U. Axe, District IV"))
    assert away["absent"] == ["Frank U. Axe"] and len(away["roll"]) == 4
    assert am.head_of("Amador County Planning Commission\nMINUTES\nDATE: June 11, 2024\n") == {}  # another body's minutes
    assert am.head_of("Staff report\nto the Board\n") == {}


def test_paragraphs_end_at_a_gap_and_at_the_words_a_motion_and_its_names_open_with():
    paragraphs = am.paragraphs_of("An item's title that runs\nover two lines.\n\nACTION: Direction given.\nMOTION: It was moved\nand carried.\n"
                                  "Ayes: Supervisors Crew\nNoes: None\nJune 11, 2024-DRAFT MINUTES 3\n\fwith a sentence that runs over the page.\n\n"
                                  "A paragraph that ends\nJune 11,2024-DRAFT MINUTES 4\n\fover the page too.\n12\n\fThe next one.")
    assert paragraphs == [["An item's title that runs", "over two lines."], ["ACTION: Direction given."], ["MOTION: It was moved", "and carried."],
                          ["Ayes: Supervisors Crew"], ["Noes: None", "with a sentence that runs over the page."],
                          ["A paragraph that ends", "over the page too."], ["The next one."]]


def test_names_are_matched_to_the_roll_by_surname():
    assert am.names_in("Supervisors Crew, Forster, Brown") == ["Crew", "Forster", "Brown"]
    assert am.names_in("Supervisors Oneto, Crew, Brown and Forster") == ["Oneto", "Crew", "Brown", "Forster"]
    assert am.names_in("SupervisorOneto") == ["Oneto"] and am.names_in("None") == [] and am.names_in("Supervisor Oneto, Axe") == ["Oneto", "Axe"]
    assert am.who("Forster", ROLL) == "Richard M. Forster" and am.who("Supervisor Axe", ROLL) == "Frank U. Axe"
    assert am.who("Frank U. Axe", ROLL) == "Frank U. Axe" and am.who("Carnell", ROLL) is None
    said = am.said_of("It was moved by Supervisor Forster, seconded by SupervisorCrew, and carried4-0-1 to approve the agenda.")
    assert (said["mover"], said["seconder"], said["unanimous"], said["count"]) == ("Forster", "Crew", False, (4, 0, 1))
    assert am.said_of("It was moved by Supervisor Axe, seconded by Supervisor Crew and carriedunanimously to close the hearing.")["unanimous"]
    assert am.said_of("It was moved by Supervisor Axe, seconded by Supervisor Crew and carried 3-2, to introduce the ordinance.")["count"] == (3, 2)


def test_a_motion_with_names_is_read_only_if_they_are_the_roll_and_agree_with_the_count():
    split = motion("It was moved by Supervisor Forster, seconded by Supervisor Crew, and carried 3-2 to approve.",
                   ("AYE", ["Crew", "Forster", "Brown"]), ("NO", ["Oneto", "Axe"]), ("ABSENT", []))
    cast, problem = am.decide(split, ROLL)
    assert problem == "" and {member: word for member, word, _ in cast} == {
        "Patrick Crew": "AYE", "Richard M. Forster": "AYE", "Jeff Brown": "AYE", "Brian Oneto": "NO", "Frank U. Axe": "NO"}
    assert {way for _, _, way in cast} == {"named"}
    # The Clerk writes a count of three as ayes, noes and the rest, or as ayes, the rest and noes; the names say which.
    for count, others in (("4-1-0", ("ABSTAIN", ["Oneto"])), ("4-0-1", ("NO", ["Oneto"])), ("4-0-1", ("ABSENT", ["Oneto"])), ("4-0", ("ABSENT", ["Oneto"]))):
        asked = motion(f"It was moved by Supervisor Axe, seconded by Supervisor Crew and carried {count} to approve.",
                       ("AYE", ["Brown", "Forster", "Axe", "Crew"]), others)
        assert am.decide(asked, ROLL[1:], absent=["Brian Oneto"] if others[0] == "ABSENT" else [])[1] == "" or am.decide(asked, ROLL)[1] == ""
    wrong = motion("It was moved by Supervisor Axe, seconded by Supervisor Crew and carried 3-0-1 to approve the letter.",
                   ("AYE", ["Brown", "Crew", "Axe"]), ("NO", ["Forster"]), ("RECUSED", ["Oneto"]))
    assert am.decide(wrong, ROLL) == (None, "the count says 3-0-1 and 3 ayes, 1 noes and 1 others are named")
    five = motion("It was moved by Supervisor Crew, seconded by Supervisor Axe and carried 4-0-1 to adopt the plan.", ("AYE", [name.split()[-1] for name in ROLL]))
    assert am.decide(five, ROLL)[1] == "the count says 4-0-1 and 5 ayes, 0 noes and 0 others are named"
    short = motion("It was moved by Supervisor Forster, seconded by Supervisor Oneto and carried unanimously to approve.",
                   ("AYE", ["Brown", "Forster", "Axe", "Crew"]), ("NO", []))
    assert am.decide(short, ROLL) == (None, "no vote printed for: Brian Oneto")
    assert am.decide(motion("It was moved and carried to approve.", ("AYE", ["Brown", "Forster", "Axe", "Crew", "Carnell"])), ROLL)[1] == "not on the roll: Carnell"
    assert am.decide(motion("It was moved and carried to approve.", ("AYE", ["Brown", "Forster", "Axe", "Crew", "Brown"])), ROLL)[1] == "named twice: Jeff Brown"
    against = motion("It was moved and carried unanimously, to waive the reading.", ("AYE", ["Brown", "Crew", "Axe"]), ("NO", ["Forster", "Oneto"]))
    assert am.decide(against, ROLL) == (None, "unanimous, with a supervisor named against")
    assert am.decide(split, []) == (None, "the head of the minutes prints no roll")


def test_a_motion_that_lists_nobody_is_read_only_where_its_words_leave_no_doubt():
    unanimous = motion("It was moved by Supervisor Axe, seconded by Supervisor Forster and carried unanimously, to approve the agenda.")
    cast, problem = am.decide(unanimous, ROLL)
    assert problem == "" and cast == [(member, "AYE", "unanimous") for member in ROLL]
    assert am.decide(unanimous, ROLL[:4], absent=["Jeff Brown"]) == (None, "unanimous, and the head has Jeff Brown absent")
    assert am.decide(unanimous, ROLL, away=["Oneto"])[1] == "nobody named, and the minutes have Brian Oneto away, late or standing aside"
    assert am.decide(unanimous, ROLL, said=False)[1] == "nobody named, and the head of the minutes does not say who was absent"
    assert am.decide(unanimous, ROLL[:4])[1] == "nobody named, and the roll has 4 names for 5 seats"
    # "carried 4-0-1" at a meeting the head has one supervisor absent from is four ayes of the four present.
    counted = motion("It was moved by Supervisor Crew, seconded by Supervisor Brown and carried 4-0-1, to accept the bequest.")
    cast, problem = am.decide(counted, ROLL[:4], absent=["Jeff Brown"])
    assert problem == "" and cast == [(member, "AYE", "count") for member in ROLL[:4]] + [("Jeff Brown", "ABSENT", "count")]
    assert am.decide(counted, ROLL)[1] == "a count of 4-0-1 and no names, with 5 present and 0 absent at the head"  # someone abstained, unnamed
    assert am.decide(motion("It was moved by Supervisor Crew, seconded by Supervisor Brown and carried 3-1 to approve."), ROLL[:4], absent=["Jeff Brown"])[1] \
        == "a count of 3-1 and no names, with 4 present and 1 absent at the head"
    assert am.decide(motion("It was moved by Supervisor Crew, seconded by Supervisor Axe and carried to deny the claim."), ROLL)[1] == "neither names, a count nor unanimous"
    apart = motion("It was moved by Supervisor Crew, seconded by Supervisor Axe and carried unanimously, with Supervisor Oneto abstaining, to approve.")
    assert am.decide(apart, ROLL)[1] == "nobody named, and the motion's words set a supervisor apart"
    assert am.decide(motion("It was moved by Supervisor Crew, seconded by Supervisor Axe and carried unanimously, to send a letter of opposition."), ROLL)[1] == ""


def test_minutes_are_read_into_items_by_where_they_stand_with_the_motions_under_them():
    agenda, by_title, votes, facts = read()
    assert facts["seats"] == 5 and facts["kind"] == "REGULAR MEETING" and (facts["motions"], facts["motions_read"]) == (8, 7)
    assert [row["title"][:20] for row in agenda if row["heading"]] == ["CLOSED SESSION", "CONSENT AGENDA", "REGULAR AGENDA", "PUBLIC HEARING 10:30"]
    confidential = by_title["Confidential Minutes: Re"]
    assert (confidential["section"], confidential["mover"], confidential["seconder"]) == ("CLOSED SESSION", "Frank U. Axe", "Richard M. Forster")
    assert (confidential["how"], confidential["established"], confidential["ayes"], confidential["votes_read"]) == ("unanimous", "unanimous", 5, True)
    assert confidential["action"].endswith("carried unanimouslyto approve the May 28, 2024 Confidential Minutes.")  # as printed
    assert cast_of(votes, confidential["item_id"]) == {member: ("AYE", "unanimous") for member in ROLL}
    assert by_title["PLEDGE OF ALLEGIANCE: Ch"]["motions"] == 0 and by_title["AGENDA: Approval of agen"]["ayes"] == 5
    # The item pulled from the consent agenda is voted on by name, on a line of its own.
    pulled = by_title["Chairman Oneto requested"]
    assert (pulled["how"], pulled["established"], pulled["ayes"], pulled["noes"], pulled["section"]) == ("3-2", "named", 3, 2, "")
    assert cast_of(votes, pulled["item_id"])["Frank U. Axe"] == ("NO", "named") and "Side Letter of Agreement." in pulled["description"]
    # An item closed with "ACTION:" and no motion has what was done and no vote.
    bridge = by_title["Public Works Department:"]
    assert (bridge["outcome"], bridge["motions"], bridge["votes_read"], bridge["section"]) == ("Informational only.", 0, None, "REGULAR AGENDA")
    assert bridge["description"] == "Mr. Richard Vela, Public Works Director, addressed the Board."
    # A supervisor who stands aside from an item is not in its unanimous vote, and is in the next item's.
    award, waiver = by_title["General Services Adminis"], by_title["Administrative Agency: R"]
    assert (award["votes_read"], award["problem"]) == (False, "nobody named, and the minutes have Jeff Brown away, late or standing aside")
    assert not cast_of(votes, award["item_id"]) and (waiver["votes_read"], waiver["seconder"]) == (True, "Patrick Crew")
    # "MOTION #2:" is the same item's as "MOTION #1:", and what the motion sets out under itself is not a new item.
    hearing = by_title["Planning Department: Con"]
    assert (hearing["motions"], hearing["motions_read"], hearing["number"], hearing["section"]) == (2, 2, "Resolution 24-077", "PUBLIC HEARING 10:30 A.M.")
    assert cast_of(votes, hearing["item_id"], 1) == {member: ("AYE", "unanimous") for member in ROLL}
    assert cast_of(votes, hearing["item_id"], 2)["Richard M. Forster"] == ("ABSTAIN", "named") and hearing["not_voting"] == 1
    assert "Approving a Variance to County Code 19.24.040." in hearing["description"]
    assert [row["title"][:11] for row in agenda][-3:] == ["ADJOURNMENT", "Juvenile Ju", "Resolution "]


def test_the_consent_agendas_items_are_listed_at_the_foot_and_voted_on_with_it_unless_pulled():
    agenda, by_title, votes, _ = read()
    consent, first, second = by_title["CONSENT AGENDA"], by_title["Juvenile Justice Commiss"], by_title["Resolution Approval for "]
    assert (consent["heading"], consent["matter_id"], consent["ayes"], consent["established"]) == (True, "", 5, "unanimous")
    assert (first["item_id"], first["agenda_number"], first["section_id"], first["voted_with"]) == ("430-5.a", "5.a", consent["item_id"], consent["item_id"])
    assert (first["outcome"], first["title"]) == ("Approved", "Juvenile Justice Commission: Approve the appointment of Stephen Hartmann to the subject committee.")
    assert (second["voted_with"], second["outcome"], second["number"], second["doc_type"]) == ("", "Approved-Resolution No. 24-078", "Resolution 24-078", "resolution")


def test_a_document_is_given_to_the_meeting_its_head_names():
    rows = [{"meeting_id": "430", "date": "2024-06-11", "time": "9:00 AM"}, {"meeting_id": "487", "date": "2025-04-08", "time": "9:00 AM"},
            {"meeting_id": "575", "date": "2025-04-08", "time": "9:00 AM"}, {"meeting_id": "600", "date": "2026-07-28", "time": "9:00 AM"},
            {"meeting_id": "618", "date": "2026-07-28", "time": "4:00 PM"}]
    head = lambda date, hour="9:00 AM", kind="REGULAR MEETING": {"date": date, "time": hour, "kind": kind}
    of, unlisted = am.matched({"100": head("2024-06-11"), "250": head("2024-06-11"), "300": head("2025-04-08"), "400": head("2026-07-28", "4:00 PM", "SPECIAL MEETING"),
                               "500": head("2024-08-13"), "600": head("2024-07-16", "1:00 PM", "SPECIAL MEETING"), "700": {}}, rows)
    # The last attached of two is taken; of two meetings listed at one hour, the regular one is the first numbered.
    assert of == {"430": "250", "487": "300", "618": "400", "d20240813": "500", "d20240716s": "600"}
    assert [(row["meeting_id"], row["date"], row["time"], row["listed"]) for row in unlisted] == [
        ("d20240813", "2024-08-13", "9:00 AM", False), ("d20240716s", "2024-07-16", "1:00 PM", False)]


def test_the_five_tables_come_out_in_the_one_shape(tmp_path):
    agenda_rows, vote_rows, facts = am.read_meeting(MEETING, am.scan(MINUTES), pages=3)
    agenda, votes = am.typed(pd.DataFrame(agenda_rows, columns=am.AGENDA_COLUMNS), pd.DataFrame(vote_rows, columns=am.VOTE_COLUMNS))
    meetings = am.meetings_table([{"meeting_id": "430", "name": "Board of Supervisors", "date": "2024-06-11", "time": "9:00 AM", "agenda": "", "packet": ""}])
    for name, value in facts.items():
        meetings[name] = [value]
    meetings["minutes_url"] = am.address("2698956", "June_11__2024_DRAFT_Minutes.pdf")
    tables = council_tables.standard({"items": am.items_table(agenda, meetings), "meetings": meetings, "agenda_items": agenda,
                                      "votes": votes, "members": am.members_table(votes, meetings)})
    for name in council_tables.TABLES:
        assert list(tables[name].columns)[:len(council_tables.COLUMNS[name])] == council_tables.COLUMNS[name]
    items = tables["items"].set_index("matter_id")
    assert "430-s2" not in items.index and len(items) == len(agenda) - 4  # the four headings are not items
    assert (items.loc["430-5.a", "action_on"], items.loc["430-5.a", "ayes"], items.loc["430-5.a", "mover"], items.loc["430-5.a", "last_action"]) == (
        "section", 5, "Patrick Crew", "Approved")
    assert items.loc["430-5.b", "action_on"] == "" and pd.isna(items.loc["430-5.b", "votes_read"])
    assert (items["passed_date"] == "").all() and (items["result"] == "").all() and items.loc["430-5.a", "url"].endswith("June_11__2024_DRAFT_Minutes.pdf")
    assert set(tables["votes"]["established"]) == {"named", "unanimous"}
    assert len(tables["members"]) == 0  # one day's votes do not make a member
    later = votes.assign(date="2024-06-25", meeting_id="431")
    members = am.members_table(pd.concat([votes, later]), meetings).set_index("name")
    assert sorted(members.index) == sorted(ROLL) and members.loc["Brian Oneto", "district"] == 5 and str(members["district"].dtype) == "Int64"
    assert not members["serving"].any() and (members["role"] == "").all()  # a vote of 2024 is not a recent one
    council_tables.write_tables(tables, tmp_path)
    assert sorted(path.name for path in tmp_path.glob("*.parquet")) == sorted(f"{name}.parquet" for name in council_tables.TABLES)
    card = am.card(tables)
    assert not re.search(r"\{[a-z_]+\}", card) and "chrissoria/amador-county-board" in card


class Answer:
    def __init__(self, status=200, headers=None, content=b"%PDF-1.7"):
        self.status_code, self.headers, self.content, self.text = status, headers or {"content-type": "application/pdf"}, content, ""

    def raise_for_status(self):
        pass


def test_a_redirect_is_followed_by_hand_and_a_login_is_not_asked_for(monkeypatch):
    asked = []
    answers = {"https://amador.granicus.com/AgendaViewer.php?view_id=1&event_id=125":
               Answer(302, {"location": "https://granicus_production_attachments.s3.amazonaws.com/amador/dcba.pdf"}),
               "https://s3.amazonaws.com/granicus_production_attachments/amador/dcba.pdf": Answer(),
               "https://amador.granicus.com/services/legistar/download/pdf/1/Old_DRAFT_Minutes.pdf": Answer(302, {"location": "/account/login?ReturnUrl=x"})}
    monkeypatch.setattr(am, "PAUSE", 0)
    monkeypatch.setattr(am, "_refused", set())
    monkeypatch.setattr(am._session, "get", lambda url, **said: asked.append(url) or answers[url])
    assert am.fetch("https://amador.granicus.com/AgendaViewer.php?view_id=1&event_id=125").content == b"%PDF-1.7"
    # The store with an underscore in its name is asked for the file by its path.
    assert asked[-1] == "https://s3.amazonaws.com/granicus_production_attachments/amador/dcba.pdf"
    with pytest.raises(am.Closed):
        am.fetch(am.address("1", "Old_DRAFT_Minutes.pdf"))
    assert len(asked) == 3  # the login page itself is never asked for


def test_a_refusal_stops_the_host_being_asked_again(monkeypatch):
    asked = []
    monkeypatch.setattr(am, "PAUSE", 0)
    monkeypatch.setattr(am, "_refused", set())
    monkeypatch.setattr(am._session, "get", lambda url, **said: asked.append(url) or Answer(403, {"content-type": "text/html"}, b"<html>"))
    with pytest.raises(am.Refused):
        am.fetch("https://amador.granicus.com/a")
    with pytest.raises(am.Refused):
        am.fetch("https://amador.granicus.com/b")
    assert asked == ["https://amador.granicus.com/a"]


def test_text_kept_here_is_not_fetched_again(tmp_path, monkeypatch):
    (tmp_path / "text").mkdir()
    (tmp_path / "text" / "2698956.txt").write_text("page one\n\fpage two", encoding="utf-8")
    monkeypatch.setattr(am, "fetch", lambda url: pytest.fail("asked the host"))
    assert am.text_of("2698956", "June_11__2024_DRAFT_Minutes.pdf", tmp_path) == "page one\n\fpage two"
