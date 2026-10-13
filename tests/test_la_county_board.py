"""build_la_county_board reads the Los Angeles County Board's votes out of the text of its Statements of Proceedings, a block whole or not at all."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import build_la_county_board as la
import council_tables

HEAD = """STATEMENT OF PROCEEDINGS FOR THE
REGULAR MEETING OF THE BOARD OF SUPERVISORS
OF THE COUNTY OF LOS ANGELES HELD IN ROOM 381B
OF THE KENNETH HAHN HALL OF ADMINISTRATION
500 WEST TEMPLE STREET, LOS ANGELES, CALIFORNIA 90012
Tuesday, May 6, 2025
9:30 AM
Present: Supervisor Solis, Supervisor Mitchell, Supervisor Horvath,
Supervisor Hahn and Supervisor Barger
Video Link for the Entire Meeting (03-1075)
Attachments: Video Transcript
Invocation led by Reverend Joyce Stickney, Malibu (3).
"""
ROLL = [(name, "Present") for name in ("Solis", "Mitchell", "Horvath", "Hahn", "Barger")]
ALL_AYES = "Ayes: 5 - Supervisor Solis, Supervisor Mitchell, Supervisor\nHorvath, Supervisor Hahn and Supervisor Barger\n"

# A matter set for a time, whose number the text takes apart; a divided vote whose names run over the foot of a page,
# on a matter whose file number the line's end cuts in two; and a matter with no vote.
STATEMENT = HEAD + """I. SET MATTERS
Set Report on the Homelessness Missions
Matter
1. Report by the Executive Director of the Homeless Initiative, as requested at
the Board meeting of October 3, 2023. (Continued from the meeting of 4-1-25) (23-3603)
Interested person(s) submitted written testimony.
On motion of Supervisor Horvath, seconded by Supervisor Solis, this item was
continued to June 3, 2025.
Ayes: 4 - Supervisor Solis, Supervisor Mitchell, Supervisor
Horvath and Supervisor Barger
Absent: 1 - Supervisor Hahn
Attachments: Public Comment/Correspondence
County of Los Angeles Page 2
\fBoard of Supervisors Statement Of Proceedings May 6, 2025
II. CONSENT CALENDAR
BOARD OF SUPERVISORS 2 - 3
2. Rent Stabilization
Recommendation as submitted by Supervisors Solis and Mitchell: Instruct the
Director of Consumer and Business Affairs to report back in 60 days. (25-
2491)
Ana Lee addressed the Board.
After discussion, on motion of Supervisor Solis, seconded by Supervisor
Mitchell, this item was duly carried by the following vote:
Ayes: 3 - Supervisor Solis, Supervisor Mitchell and Supervisor
County of Los Angeles Page 3
\fBoard of Supervisors Statement Of Proceedings May 6, 2025
Horvath
Noes: 1 - Supervisor Barger
Abstentions: 1 - Supervisor Hahn
Attachments: Motion by Supervisors Solis and Mitchell
Public Comment/Correspondence
ADMINISTRATIVE MATTERS 3
3. Report on the Jails
Report by the Sheriff on conditions in the jails. (25-0100)
By Common Consent, there being no objection, this item was continued one week
to May 13, 2025.
Attachments: Report
"""
MEETING = {"meeting_id": "1184402", "date": "2025-05-07", "minutes_url": la.FILES + "1184402_050625.pdf"}


def block(*entries):
    return la.read_block(list(entries), ROLL)


def read(monkeypatch, text, tmp_path, meeting=MEETING):
    monkeypatch.setattr(la, "text_of", lambda meeting, out_dir, fresh=False: text)
    agenda, votes, facts = la.read_meeting(meeting, tmp_path)
    return {row["item_id"]: row for row in agenda}, votes, facts


def test_the_list_is_asked_of_the_index_the_countys_page_names_and_a_row_is_one_statement():
    page = """<script type="module">
        const client = algoliasearch('APPID12345', '0123456789abcdef0123456789abcdef')
        const indexNames = ['SopMainPrdv2'];</script>"""
    address, sent = la.index_of(page)
    assert address == "https://APPID12345-dsn.algolia.net/1/indexes/SopMainPrdv2/query"
    assert sent == {"X-Algolia-Application-Id": "APPID12345", "X-Algolia-API-Key": "0123456789abcdef0123456789abcdef"}
    assert la.index_of("<html>Request unsuccessful.</html>") is None
    hit = {"sds_doc_id": "1184402", "sds_title": "Statement of Proceedings for 5/6/2025 ", "sds_document_dt": "5/6/2025, 12:00:00 AM",
           "date": 1746489600000, "sds_published_url": la.FILES + "1184402_050625.pdf", "object_name": "1184402_050625.pdf"}
    row = la.row_of(hit)
    assert row == {"meeting_id": "1184402", "name": "Statement of Proceedings for 5/6/2025", "date": "2025-05-06",
                   "minutes_url": la.FILES + "1184402_050625.pdf", "file": "1184402_050625.pdf"}
    # With no day in words the index's own count of the day is used; a file kept anywhere else is not a statement.
    assert la.row_of({**hit, "sds_document_dt": ""})["date"] == "2025-05-06"
    assert la.row_of({**hit, "sds_published_url": "https://example.test/1184402_050625.pdf"}) is None
    assert la.row_of({**hit, "sds_document_dt": "", "date": None}) is None
    held = la.meetings_table([row]).iloc[0]
    assert (held["meeting_id"], held["date"], held["listed_date"], held["body"], held["minutes_url"], held["summary"]) == \
        ("1184402", "2025-05-06", "2025-05-06", "Board of Supervisors", la.FILES + "1184402_050625.pdf", "")
    assert la.since_day("2024") == "2024-01-01" and la.since_day("2024-10-01") == "2024-10-01" and la.since_day("") == la.FIRST_DAY


def test_the_head_gives_the_day_the_time_the_kind_of_meeting_and_the_roll():
    head = la.head_of(la.lines_of(HEAD))
    assert (head["date"], head["time"], head["kind"], head["roll"]) == ("2025-05-06", "9:30 AM", "Regular Meeting", ROLL)
    assert head["lines"] == set(range(9))  # down to the roll: the video's line is the meeting's first matter
    # A supervisor away all day is on the roll too, and the roll may stand below the video's line.
    lines = ["STATEMENT OF PROCEEDINGS FOR THE", "SPECIAL MEETING OF THE BOARD OF SUPERVISORS", "Tuesday, June 26, 2012", "1:00 PM",
             "Video Link for the Entire Meeting (03-1075)", "Attachments: Video Transcript",
             "Present: Supervisor Molina, Supervisor Ridley-Thomas, Supervisor", "Antonovich and Supervisor Yaroslavsky",
             "Absent: Supervisor Knabe", "Invocation led by The Reverend Ken Walden."]
    head = la.head_of(lines)
    assert head["roll"] == [("Molina", "Present"), ("Ridley-Thomas", "Present"), ("Antonovich", "Present"), ("Yaroslavsky", "Present"),
                            ("Knabe", "Absent")]
    assert (head["time"], head["kind"], head["lines"]) == ("1:00 PM", "Special Meeting", {0, 1, 2, 3, 6, 7, 8})
    # A list that is not all supervisors is no roll, nor is a head with nobody present.
    assert la.head_of(["Tuesday, May 6, 2025", "Present: Supervisor Solis, the Executive Officer and Supervisor Hahn"])["roll"] == []
    assert la.head_of(["Tuesday, May 6, 2025", "Absent: Supervisor Solis"])["roll"] == []
    assert la.head_of(["Tuesday, May 6, 2025", "Present: Supervisor Solis and Supervisor Solis"])["roll"] == []
    # The statements of the budget deliberations name the supervisors in full, and some give the chair's office.
    full = la.head_of(["Monday, June 25, 2012", "9:30 AM", "Present: Supervisor Gloria Molina, Supervisor Mark Ridley-Thomas,",
                       "Supervisor Michael D. Antonovich and Supervisor Zev", "Yaroslavsky", "Absent: Supervisor Don Knabe"])
    assert full["roll"] == [("Molina", "Present"), ("Ridley-Thomas", "Present"), ("Antonovich", "Present"), ("Yaroslavsky", "Present"),
                            ("Knabe", "Absent")]
    chaired = la.head_of(["Wednesday, May 13, 2009", "Present: Supervisor Yaroslavsky, Supervisor Antonovich, and Supervisor",
                          "Knabe, Chairman", "Absent: Supervisor Molina and Supervisor Ridley-Thomas"])
    assert [name for name, word in chaired["roll"]] == ["Yaroslavsky", "Antonovich", "Knabe", "Molina", "Ridley-Thomas"]


def test_a_list_of_names_is_supervisors_and_nothing_else():
    assert la.names_of("Supervisor Solis, Supervisor Ridley-Thomas and Supervisor Hahn") == ["Solis", "Ridley-Thomas", "Hahn"]
    assert la.names_of("Supervisor Barger") == ["Barger"]
    assert la.names_of("Supervisor Solis, Supervisor Hahn and Supervisor Barger Attachments: Board Letter") is None
    assert la.names_of("Supervisor Solis and the Chair") is None and la.names_of("") is None
    assert la.joined_list("Supervisor Solis and Supervisor Ridley-", "Thomas") == "Supervisor Solis and Supervisor Ridley-Thomas"
    assert la.member_of("Solis") == "Hilda L. Solis" and la.member_of("Newcomer") == "Newcomer"
    assert sorted(seat for _, seat in la.KNOWN.values()) == [1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 5, 5]


def test_a_block_gives_aye_and_no_one_spelling_and_the_other_words_as_the_other_boards_have_them():
    cast, problem = block(("Ayes", "2", "Supervisor Solis and Supervisor Mitchell"), ("Noes", "1", "Supervisor Barger"),
                          ("Abstentions", "1", "Supervisor Hahn"), ("Recuse", "1", "Supervisor Horvath"))
    assert problem == ""
    assert cast == [("Hilda L. Solis", "AYE"), ("Holly J. Mitchell", "AYE"), ("Kathryn Barger", "NO"), ("Janice Hahn", "ABSTAIN"),
                    ("Lindsey P. Horvath", "RECUSED")]
    assert block(("Ayes", "4", "Supervisor Solis, Supervisor Mitchell, Supervisor Horvath and Supervisor Barger"),
                 ("Absent", "1", "Supervisor Hahn"))[0][-1] == ("Janice Hahn", "ABSENT")
    assert {council_tables.vote_word(word) for word in la.LABELS.values()} == {"AYE", "NO", "ABSTAIN", "ABSENT", "RECUSED"}
    # The budget deliberations' statements say Aye, No and Abstain; five abstentions are a vote like any other.
    assert block(("Aye", "3", "Supervisor Solis, Supervisor Mitchell and Supervisor Horvath"), ("No", "1", "Supervisor Barger"),
                 ("Abstain", "1", "Supervisor Hahn"))[0][-2:] == [("Kathryn Barger", "NO"), ("Janice Hahn", "ABSTAIN")]
    assert {word for _, word in block(("Abstentions", "5", "Supervisor Solis, Supervisor Mitchell, Supervisor Horvath, Supervisor Hahn "
                                                              "and Supervisor Barger"))[0]} == {"ABSTAIN"}


def test_a_line_of_a_block_is_a_word_a_count_and_supervisors():
    assert la.label_of("Ayes: 4 - Supervisor Solis, Supervisor Mitchell, Supervisor") == ("Ayes", "4", "Supervisor Solis, Supervisor Mitchell, Supervisor")
    assert la.label_of("Ayes: 4 -") == ("Ayes", "4", "")  # a known word, its list on the lines below
    assert la.label_of("Excused: 1 - Supervisor Hahn") == ("Excused", "1", "Supervisor Hahn")  # not known: it will stop the block being read
    # A list of documents that begins with a number, and prose that happens to look alike, are no part of a block.
    assert la.label_of("Attachments: 30 - Day Report") is None and la.label_of("Sections: 1 - 5 of the ordinance") is None
    assert la.numbered_of("12. Rent Stabilization") == ("12", "Rent Stabilization") and la.numbered_of("101-A.Waiving Fees") == ("101-A", "Waiving Fees")
    assert [la.numbered_of(line)[0] for line in ("S-1. 11:00 a.m.", "CS-2. CONFERENCE", "1-PA. Recommendation", "2a. Issues", "Set Matter-1 Report",
                                                 "Set Matter - 3. Report")] == ["S-1", "CS-2", "1-PA", "2a", "Set Matter 1", "Set Matter 3"]
    assert la.numbered_of("3.100.030A of the County Code") is None and la.numbered_of("2025 Annual Report") is None


@pytest.mark.parametrize("entries, why", [
    ([("Ayes", "5", "Supervisor Solis, Supervisor Mitchell, Supervisor Horvath, Supervisor Hahn and Supervisor Knabe")], "not on the roll: Knabe"),
    ([("Ayes", "5", "Supervisor Solis, Supervisor Mitchell, Supervisor Horvath and Supervisor Hahn")], "Ayes says 5 and names 4"),
    ([("Ayes", "4", "Supervisor Solis, Supervisor Mitchell, Supervisor Horvath and Supervisor Hahn"), ("Noes", "1", "Supervisor Solis")],
     "named twice: Solis"),
    ([("Ayes", "4", "Supervisor Solis, Supervisor Mitchell, Supervisor Horvath and Supervisor Hahn"),
      ("Absent", "1", "Supervisor Barger 7. Rent Stabilization")], "not a list of supervisors: Supervisor Barger 7. Rent Stabilization"),
    ([("Ayes", "4", "Supervisor Solis, Supervisor Mitchell, Supervisor Horvath and Supervisor Hahn"), ("Present", "1", "Supervisor Barger")],
     "a word not known: Present"),
    ([("Ayes", "3", "Supervisor Solis, Supervisor Mitchell and Supervisor Horvath"), ("Ayes", "2", "Supervisor Hahn and Supervisor Barger")],
     "Ayes twice"),
    ([("Absent", "1", "Supervisor Barger")], "1 of 5 supervisors named"),
    ([("Ayes", "4", "Supervisor Solis, Supervisor Mitchell, Supervisor Horvath and Supervisor Hahn")], "4 of 5 supervisors named"),
])
def test_a_block_that_does_not_read_cleanly_is_not_read_at_all(entries, why):
    assert la.read_block(entries, ROLL) == (None, why)
    assert la.read_block([("Ayes", "1", "Supervisor Solis")], []) == (None, "no roll at the head of the statement")


def test_a_statement_is_read_into_headings_matters_and_the_votes_on_each_motion(monkeypatch, tmp_path):
    agenda, votes, facts = read(monkeypatch, STATEMENT, tmp_path)
    assert list(agenda) == ["1184402-u1", "1184402-s1", "1184402-Set-Matter-1", "1184402-s2", "1184402-2", "1184402-3"]
    assert (facts["summary"], facts["pages"], facts["vote_blocks"], facts["blocks_read"]) == ("read", 3, 2, 2)
    assert (facts["date"], facts["time"], facts["kind"]) == ("2025-05-06", "9:30 AM", "Regular Meeting")
    assert '{"name":"Janice Hahn","district":4,"present":true}' in facts["roll"]
    # The day is the one the statement prints, not the listing's.
    assert {row["date"] for row in agenda.values()} == {"2025-05-06"} and {vote["date"] for vote in votes} == {"2025-05-06"}
    video, heading, report, divided, quiet = (agenda[item] for item in ("1184402-u1", "1184402-s1", "1184402-Set-Matter-1", "1184402-2", "1184402-3"))
    assert (video["title"], video["matter_file"], video["agenda_number"], video["vote_blocks"]) == ("Video Link for the Entire Meeting", "03-1075", "", 0)
    assert (heading["heading"], heading["title"], heading["matter_id"]) == (True, "I. SET MATTERS", "")
    assert (report["agenda_number"], report["matter_file"], report["matter_id"], report["section"]) == ("Set Matter 1", "23-3603", "23-3603", "I. SET MATTERS")
    assert report["title"].startswith("Report on the Homelessness Missions Report by the Executive Director")
    assert report["title"].endswith("(Continued from the meeting of 4-1-25)")
    assert (report["action"], report["mover"], report["seconder"]) == (
        "On motion of Supervisor Horvath, seconded by Supervisor Solis, this item was continued to June 3, 2025.",
        "Lindsey P. Horvath", "Hilda L. Solis")
    assert (report["ayes"], report["noes"], report["not_voting"], report["votes_read"]) == (4, 0, 1, True)
    # The file number broken over a line, a short title above what is recommended, and names that run over a page's foot.
    assert (divided["matter_file"], divided["title"], divided["section"], divided["group"]) == \
        ("25-2491", "Rent Stabilization", "II. CONSENT CALENDAR", "BOARD OF SUPERVISORS 2 - 3")
    assert divided["text"].startswith("Rent Stabilization Recommendation as submitted") and divided["text"].endswith("report back in 60 days.")
    assert divided["action"].startswith("After discussion, on motion of Supervisor Solis, seconded by Supervisor Mitchell")
    assert (divided["ayes"], divided["noes"], divided["not_voting"], divided["mover"], divided["seconder"]) == \
        (3, 1, 1, "Hilda L. Solis", "Holly J. Mitchell")
    assert [(v["member"], v["vote"]) for v in votes if v["item_id"] == "1184402-2"] == [
        ("Hilda L. Solis", "AYE"), ("Holly J. Mitchell", "AYE"), ("Lindsey P. Horvath", "AYE"), ("Kathryn Barger", "NO"), ("Janice Hahn", "ABSTAIN")]
    assert {(v["matter_id"], v["matter_file"], v["motion"]) for v in votes if v["item_id"] == "1184402-2"} == {("25-2491", "25-2491", 1)}
    assert len(votes) == 10
    # A matter with no block has an action and no votes; whether its votes were read is not a question.
    assert (quiet["action"], quiet["vote_blocks"], quiet["votes_read"], quiet["group"]) == (
        "By Common Consent, there being no objection, this item was continued one week to May 13, 2025.", 0, None, "ADMINISTRATIVE MATTERS 3")


def test_a_motion_whose_block_cannot_be_read_is_kept_with_no_votes_and_says_why(monkeypatch, tmp_path):
    text = STATEMENT.replace("Noes: 1 - Supervisor Barger", "Noes: 2 - Supervisor Barger")  # the count and the names do not agree
    agenda, votes, facts = read(monkeypatch, text, tmp_path)
    unread = agenda["1184402-2"]
    assert (unread["mover"], unread["vote_blocks"], unread["blocks_read"], unread["votes_read"]) == ("Hilda L. Solis", 1, 0, False)
    assert (unread["ayes"], unread["noes"], unread["not_voting"], unread["problem"]) == (0, 0, 0, "Noes says 2 and names 1")
    assert not [v for v in votes if v["item_id"] == "1184402-2"] and len(votes) == 5
    assert (facts["vote_blocks"], facts["blocks_read"]) == (2, 1)
    assert '"read":false,"problem":"Noes says 2 and names 1"' in unread["motion_log"]
    # A statement with no roll at its head has no votes read at all.
    agenda, votes, facts = read(monkeypatch, STATEMENT.replace("Present: Supervisor Solis", "Present were Supervisor Solis"), tmp_path)
    assert (votes, facts["roll"], facts["vote_blocks"], facts["blocks_read"]) == ([], "", 2, 0)
    assert agenda["1184402-2"]["problem"] == "no roll at the head of the statement"


def test_numbered_points_and_a_sentence_broken_before_a_number_are_not_matters(monkeypatch, tmp_path):
    text = HEAD + f"""I. PUBLIC HEARINGS 1 - 2
1. Hearing on Fees
Hearing on ordinance for adoption amending County Code, Title 8, to make changes
to Rules 2, 6, 7, 8, 10, and 11. (Department of Public Health) (25-1610)
On motion of Supervisor Hahn, seconded by Supervisor Barger, the Board
closed the public hearing and took the following actions:
1. Made a finding that the fees are exempt; and
2. Adopted Ordinance No. 2025-0024, which amends Rules 2, 6, 7, 8, 10, and
11." This ordinance shall take effect on June 5, 2025.
Said motion was duly carried by the following vote:
{ALL_AYES}Attachments: Board Letter
2. Hearing on Annexations
Hearing on the annexation of 28 parcels. (Department of Public Works) (25-1721)
On motion of Supervisor Solis, seconded by Supervisor Hahn, this item was
referred back to the Department.
{ALL_AYES}"""
    agenda, votes, facts = read(monkeypatch, text, tmp_path)
    assert [(row["agenda_number"], row["matter_file"], row["blocks_read"]) for row in agenda.values() if not row["heading"]] == [
        ("", "03-1075", 0), ("1", "25-1610", 1), ("2", "25-1721", 1)]
    fees = agenda["1184402-1"]
    assert fees["action"].startswith("On motion of Supervisor Hahn") and "1. Made a finding" in fees["action"]
    assert fees["action"].endswith("Said motion was duly carried by the following vote:")
    assert (fees["doc_type"], fees["title"]) == ("ordinance", fees["text"])  # no short title: the title is all of it
    assert len(votes) == 10 and {v["vote"] for v in votes} == {"AYE"}


def test_a_matter_printed_again_for_a_second_action_is_one_line_with_two_motions(monkeypatch, tmp_path):
    text = HEAD + f"""I. PUBLIC HEARING 1
1. Franchise Ordinance
Hearing on ordinance for adoption granting a franchise. (Department of Public
Works) (24-4386)
After discussion, on motion of Supervisor Barger, seconded by Supervisor
Mitchell, the Board closed the public hearing and denied the protest.
Said motion was duly carried by the following vote:
{ALL_AYES}Attachments: Board Letter
Audio
County of Los Angeles Page 2
\fBoard of Supervisors Statement Of Proceedings May 6, 2025
Franchise Ordinance
Hearing on ordinance for adoption granting a franchise. (Department of Public
Works) (24-4386)
Further, on motion of Supervisor Barger, seconded by Supervisor Horvath, the
Board adopted Ordinance No. 2024-0061F. The motion failed to carry by the following vote:
Ayes: 2 - Supervisor Horvath and Supervisor Barger
Noes: 3 - Supervisor Solis, Supervisor Mitchell and Supervisor Hahn
Attachments: Board Letter
"""
    agenda, votes, facts = read(monkeypatch, text, tmp_path)
    assert list(agenda) == ["1184402-u1", "1184402-s1", "1184402-1"]
    line = agenda["1184402-1"]
    assert (line["motions"], line["vote_blocks"], line["blocks_read"], line["votes_read"]) == (2, 2, 2, True)
    assert (line["ayes"], line["noes"], line["seconder"], line["result"]) == (2, 3, "Lindsey P. Horvath", "Fail")  # the line carries its last vote
    assert sorted({(v["motion"], v["vote"]) for v in votes}) == [(1, "AYE"), (2, "AYE"), (2, "NO")]
    assert {v["matter_file"] for v in votes} == {"24-4386"} and len(votes) == 10


def test_a_vote_that_does_not_stand_where_a_vote_stands_is_left_unread(monkeypatch, tmp_path):
    approved = "On motion of Supervisor Hahn, seconded by Supervisor Solis, this item was approved.\n" + ALL_AYES
    # The matter's file number is lost: the vote comes before any.
    lost = HEAD + f"I. CONSENT CALENDAR\n1. First Matter\nRecommendation: Approve the plan.\n{approved}"
    head, lines = la.parse(lost)
    assert [(line["number"], line["file"], [m["doubt"] for m in line["motions"]]) for line in lines[2:]] == [
        ("1", "", ["a vote before the matter's file number"])]
    agenda, votes, facts = read(monkeypatch, lost, tmp_path)
    assert (votes, facts["vote_blocks"], facts["blocks_read"], agenda["1184402-1"]["votes_read"]) == ([], 1, 0, False)
    # A vote after a matter's attachments may be on a matter whose number and file number are both lost.
    after = HEAD + f"""I. CONSENT CALENDAR
1. First Matter (25-0001)
{approved}Attachments: Board Letter
Second Matter, whose number and file number the text has lost
{approved}"""
    agenda, votes, facts = read(monkeypatch, after, tmp_path)
    first = agenda["1184402-1"]
    assert (first["vote_blocks"], first["blocks_read"], first["problem"], len(votes)) == (2, 1, "a vote after the matter's attachments", 5)
    # The next number with no file number after it, before a second vote: it may have opened a matter.
    run_on = HEAD + f"""I. CONSENT CALENDAR
1. First Matter (25-0001)
{approved}2. Second Matter, whose file number the text has lost
{approved}3. Third Matter (25-0003)
{approved}"""
    agenda, votes, facts = read(monkeypatch, run_on, tmp_path)
    assert [(row["agenda_number"], row["matter_file"], row["vote_blocks"], row["blocks_read"], row["problem"]) for row in list(agenda.values())[2:]] == [
        ("1", "25-0001", 2, 1, "a line that may open a matter, with no file number after it"), ("3", "25-0003", 1, 1, "")]
    assert {v["item_id"] for v in votes} == {"1184402-1", "1184402-3"} and len(votes) == 10
    # Where matter 2 does open further down, the line was not matter 2, and the vote after it is read.
    named = run_on.replace("2. Second Matter, whose file number the text has lost", "Later in the meeting it was taken up again with Item No.\n2. ")
    named = named.replace("3. Third Matter (25-0003)", "Attachments: Board Letter\n2. Second Matter (25-0002)")
    agenda, votes, facts = read(monkeypatch, named, tmp_path)
    assert [(row["agenda_number"], row["vote_blocks"], row["blocks_read"]) for row in list(agenda.values())[2:]] == [("1", 2, 2), ("2", 1, 1)]
    # A vote before anything at all.
    head, lines = la.parse(HEAD.split("Video")[0] + ALL_AYES)
    assert [m["doubt"] for m in lines[0]["motions"]] == ["a vote with no matter before it"]


def test_matters_out_of_their_order_and_numbered_again_are_matters_by_their_file_numbers(monkeypatch, tmp_path):
    approved = "On motion of Supervisor Hahn, seconded by Supervisor Solis, this item was approved.\n" + ALL_AYES + "Attachments: Board Letter\n"
    text = HEAD + f"""I. PUBLIC HEARINGS 1 - 2
1. First Hearing (25-0001)
{approved}2. Second Hearing (25-0002)
{approved}II. CONSENT CALENDAR
1. First Motion, numbered from 1 again (25-0011)
{approved}26. A Later Matter (25-0026)
{approved}27. The Matter After It (25-0027)
{approved}SEPARATE MATTERS 24
24. A Matter printed after the ones that follow it (25-0024)
On motion of Supervisor Hahn, seconded by Supervisor Solis, the Board took the following actions:
1. Approved the plan; and
29. This line is a sentence broken before a number, and no matter.
{ALL_AYES}"""
    agenda, votes, facts = read(monkeypatch, text, tmp_path)
    assert [(item, row["matter_file"], row["blocks_read"]) for item, row in agenda.items() if row["agenda_number"]] == [
        ("1184402-1", "25-0001", 1), ("1184402-2", "25-0002", 1), ("1184402-1~2", "25-0011", 1), ("1184402-26", "25-0026", 1),
        ("1184402-27", "25-0027", 1), ("1184402-24", "25-0024", 1)]
    assert agenda["1184402-24"]["group"] == "SEPARATE MATTERS 24" and len(votes) == 30
    assert agenda["1184402-24"]["action"].endswith("29. This line is a sentence broken before a number, and no matter.")


def test_a_file_number_with_no_number_before_it_and_one_with_only_its_brackets(monkeypatch, tmp_path):
    text = HEAD + f"""I. PRESENTATIONS
Presentation of scroll to the Conservation Corps, as arranged by Supervisor Hahn.
Presentation of pets, as arranged by Supervisor Barger. (25-2288)
II. CONSENT CALENDAR
22. Adoption Awareness Month
Recommendation: Print a message on all County warrants. (24-)
On motion of Supervisor Hahn, seconded by Supervisor Mitchell, this item was
duly carried by the following vote:
{ALL_AYES}A-1. Continue local emergencies as a result of the following: (a) Discovery of an
infestation of fruit flies, as proclaimed on May 10, 1990. (A-1)
This item was reviewed and continued.
{ALL_AYES}"""
    agenda, votes, facts = read(monkeypatch, text, tmp_path)
    scrolls, month, standing = agenda["1184402-u2"], agenda["1184402-22"], agenda["1184402-A-1"]
    assert scrolls["title"].startswith("Presentation of scroll to the Conservation Corps") and scrolls["matter_file"] == "25-2288"
    assert (month["matter_file"], month["matter_id"], month["blocks_read"]) == ("", "1184402-22", 1)
    assert (standing["matter_file"], standing["agenda_number"], standing["blocks_read"], standing["action"]) == ("A-1", "A-1", 1, "This item was reviewed and continued.")
    assert {(v["item_id"], v["matter_id"]) for v in votes} == {("1184402-22", "1184402-22"), ("1184402-A-1", "A-1")}


def test_a_statement_that_is_a_scan_is_counted_and_left(monkeypatch, tmp_path):
    agenda, votes, facts = read(monkeypatch, "\f\f \f", tmp_path)
    assert (agenda, votes, facts["summary"], facts["pages"]) == ({}, [], "no text layer", 4)


def test_a_refusal_is_not_asked_again_and_a_check_stops_the_host(monkeypatch):
    asked = []

    class Answer:
        status_code, headers, content, text = 403, {"content-type": "text/html"}, b"<html>", "<html>"

    monkeypatch.setattr(la.requests, "get", lambda url, **kwargs: asked.append(url) or Answer())
    try:
        with pytest.raises(la.Refused):
            la.fetch(la.FILES + "1184402_050625.pdf")
        with pytest.raises(la.Refused):
            la.fetch(la.FILES + "1184403_051325.pdf")
        assert len(asked) == 1
        assert asked[0].startswith("https://file.lacounty.gov/")
        la._refused.clear()
        Answer.text = "<html>Request unsuccessful. Incapsula incident ID: 0-1</html>"
        with pytest.raises(la.Refused):
            la.challenged(Answer, la.PAGE)
        assert la._refused == {"lacounty.gov"}
    finally:
        la._refused.clear()


def test_a_run_reads_the_newest_first_skips_what_it_has_read_and_writes_the_five_tables(monkeypatch, tmp_path):
    def row(number):
        day = f"2024-01-{number:02d}" if number < 29 else f"2007-{number % 12 + 1:02d}-15"  # most are from before the form read here
        return {"meeting_id": str(number), "name": f"Statement of Proceedings for {day}", "date": day,
                "minutes_url": la.FILES + f"{number}_sop.pdf", "file": f"{number}_sop.pdf"}

    rows = [row(number) for number in range(1, 1201)]
    read_now = []

    def text_of(meeting, out_dir, fresh=False):
        read_now.append(meeting["meeting_id"])
        if meeting["meeting_id"] == "26":
            raise ValueError("the County sent a page in place of the statement")
        return STATEMENT.replace("May 6, 2025", f"January {int(meeting['meeting_id'])}, 2024").replace("Tuesday,", "Monday,")

    monkeypatch.setattr(la, "listed", lambda: rows)
    monkeypatch.setattr(la, "text_of", text_of)
    monkeypatch.setattr(council_tables, "published", lambda repo, name: None)
    monkeypatch.setattr(county_of(), "WORKERS", 1)
    tables, read = la.build(True, False, tmp_path, limit=2)
    assert (read_now, read) == (["28", "27"], 2)
    tables, read = la.build(True, False, tmp_path, since="2024-01-25")
    assert (read_now, read) == (["28", "27", "26", "25"], 1)  # the one that could not be fetched is asked for again next time
    assert {name: list(table.columns[:len(council_tables.COLUMNS[name])]) for name, table in tables.items()} == council_tables.COLUMNS
    meetings = tables["meetings"].set_index("meeting_id")
    assert list(meetings.loc[["24", "25", "26", "27"], "summary"]) == ["", "read", "", "read"]
    assert (meetings.loc["27", "items"], meetings.loc["27", "vote_blocks"], meetings.loc["27", "blocks_read"], meetings.loc["27", "time"]) == (4, 2, 2, "9:30 AM")
    assert len(tables["votes"]) == 30 and set(tables["votes"]["vote"]) == {"AYE", "NO", "ABSENT", "ABSTAIN"}
    # A matter is a file number: the report continued from meeting to meeting is one row, drawn from the newest statement.
    items = tables["items"].set_index("matter_id")
    assert len(items) == 4 and items.index.is_unique
    report = items.loc["23-3603"]
    assert (report["date"], report["agenda_date"], report["times_on_agenda"], report["meeting_id"], report["ayes"], report["noes"]) == \
        ("2024-01-25", "2024-01-28", 3, "28", 4, 0)
    assert (report["url"], bool(report["votes_read"]), report["last_action_date"]) == (la.FILES + "28_sop.pdf", True, "2024-01-28")
    assert pd.isna(items.loc["25-0100", "votes_read"]) and items.loc["25-0100", "last_action"].startswith("By Common Consent")
    members = tables["members"].set_index("name")
    assert sorted(members.index) == ["Hilda L. Solis", "Holly J. Mitchell", "Janice Hahn", "Kathryn Barger", "Lindsey P. Horvath"]
    assert (members.loc["Janice Hahn", "district"], members.loc["Janice Hahn", "votes"], members.loc["Janice Hahn", "first_vote"]) == (4, 6, "2024-01-25")
    assert members["serving"].all()
    assert all((tmp_path / f"{name}.parquet").exists() for name in council_tables.TABLES)
    assert "{" not in la.card(tables).split("## Tables")[1]  # every fact the card asks for was written in
    # A statement that is no longer listed is left out, with what was read from it.
    monkeypatch.setattr(la, "listed", lambda: [kept for kept in rows if kept["meeting_id"] != "28"])
    tables, read = la.build(True, False, tmp_path, since="2024-01-25")
    assert "28" not in set(tables["votes"]["meeting_id"]) | set(tables["agenda_items"]["meeting_id"]) | set(tables["meetings"]["meeting_id"])
    assert len(tables["votes"]) == 20 and tables["items"].set_index("matter_id").loc["23-3603", "times_on_agenda"] == 2


def county_of():
    import build_sd_county
    return build_sd_county
