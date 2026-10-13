"""build_sacramento_board reads the Sacramento County Board's votes out of the text of its action summaries, a block whole or not at all."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import build_sacramento_board as sac
import council_tables

HEAD = """Phil Serna – District 1
Patrick Kennedy – District 2
Rich Desmond – District 3
Rosario Rodriguez – District 4 (Chair)
Patrick Hume – District 5 (Vice Chair)
ACTION SUMMARY
BOARD OF SUPERVISORS
TUESDAY APRIL 28, 2026 9:30 AM
1. Speakers will have 2-minutes for each item
1 April 28, 2026
\fROLL CALL
"""
ROLL = [{"name": name, "district": district, "role": role} for name, district, role in (
    ("Phil Serna", 1, ""), ("Patrick Kennedy", 2, ""), ("Rich Desmond", 3, ""), ("Rosario Rodriguez", 4, "Chair"),
    ("Patrick Hume", 5, "Vice Chair"))]

# A consent agenda voted on as one, an item taken out of it and voted on by itself, and an item with no vote.
SUMMARY = HEAD + """Section I - Consent Matters
(Items 1 - 3)
10:10 AM Board Action: Pat Hume / Patrick Kennedy - Approved the Consent
Matters, Items 1 through 3, as recommended, with the exception of Item 2.
AYES: Phil Serna, Patrick Kennedy, Rosario Rodriguez, Pat Hume
NOES: None
ABSTAIN: None
ABSENT: Rich Desmond
RECUSAL: None
(PER POLITICAL REFORM ACT (§ 18702.5.))
PLEASE SEE ITEM 2 FOR BOARD ACTION.
COUNTY EXECUTIVE
1. Adopt An Ordinance Amending Chapter 21.15 (Budget and Debt
Management)
Supervisorial District(s): All
10:10 AM Board Action: Approved by Sacramento County Code Ordinance
No. SCC-1774.
2. Approve The Fee Schedule (Finance)
Supervisorial District(s): All
10:31 AM Board Action: Rich Desmond/ Patrick Kennedy - Adopted
Resolution No. 2026-0181.
2 April 28, 2026
\fAYES: Patrick Kennedy, Rich Desmond, Phil
Serna
NOES: Rosario Rodriguez, Pat Hume
ABSTAIN: None
ABSENT: None
RECUSAL: None
(PER POLITICAL REFORM ACT (§ 18702.5.))
SACRAMENTO COUNTY WATER AGENCY
(Directors: R. Desmond, P. Hume, P. Kennedy, R. Rodriguez, P. Serna)
3. Authorize A Grant Agreement (Water Resources)
Supervisorial District(s): Serna
10:10 AM Board Action: Approved by Resolution No. WA-3122.
Section II - Separate Matters
4. Workshop On Fees (Transportation)
10:55 AM Board Action: Held a workshop.
"""
MEETING = {"meeting_id": "10218", "date": "2026-04-28", "minutes_url": "https://example.test/summary.pdf"}


def block(*lines):
    return sac.read_block(list(lines), ROLL)


def read(monkeypatch, text, tmp_path):
    monkeypatch.setattr(sac, "text_of", lambda meeting, out_dir, fresh=False: text)
    agenda, votes, facts = sac.read_meeting(MEETING, tmp_path)
    return {row["item_id"]: row for row in agenda}, votes, facts


def test_a_listing_row_gives_the_meeting_its_day_its_time_and_where_its_documents_are():
    page = """<tr id="meeting-8792-row" class="meeting-row" data-meeting-id="8792">
      <td data-sortable-type="mtgName">BOARD OF SUPERVISORS - ADDENDUM</td><td data-sortable-type="mtgType">BOARD OF SUPERVISORS MEETING</td>
      <td data-sortable-type="mtgTime" data-sortable-label="1/7/2025" data-sortable-data="1736271000">1/7/2025 9:30:00 AM</td>
      <a href="/BoardofSupervisors/Documents/Downloadfile/B_8792_Agenda_1_7_2025.pdf?documentType=1&amp;meetingId=8792">a</a>
      <a href="/BoardofSupervisors/Documents/DownloadFile/B_8792_Minutes_1_7_2025.pdf?documentType=2&amp;meetingId=8792">s</a></tr>
      <tr id="meeting-9841-row"><td data-sortable-type="mtgName">BOARD OF SUPERVISORS - CANCELLED</td>
      <td data-sortable-type="mtgTime" data-sortable-label="6/5/2025">6/5/2025 2:00:00 PM</td></tr>"""
    meetings = sac.meetings_table(sac.rows_of(page)).set_index("meeting_id")
    held = meetings.loc["8792"]
    assert (held["date"], held["time"], held["body"], held["name"]) == ("2025-01-07", "9:30 AM", "Board of Supervisors", "BOARD OF SUPERVISORS - ADDENDUM")
    assert held["minutes_url"] == (sac.HOST + "/Documents/ViewDocument/B_8792_Minutes_1_7_2025.pdf?meetingId=8792&documentType=2"
                                   "&itemId=0&publishId=0&isSection=false")
    assert "documentType=1" in held["agenda_url"] and held["packet_url"] == ""
    assert (meetings.loc["9841", "date"], meetings.loc["9841", "time"], meetings.loc["9841", "minutes_url"]) == ("2025-06-05", "2:00 PM", "")


def test_the_roll_is_read_from_either_heading_and_a_name_is_known_by_its_surname_and_first_letter():
    roll = sac.roll_of(sac.lines_of(HEAD))
    assert roll == ROLL
    assert sac.who("Pat Hume", roll) == "Patrick Hume" and sac.who("Patrick Kennedy", roll) == "Patrick Kennedy"
    assert sac.who("Betty Williams", roll) is None and sac.who("Hume", roll) is None
    # Two to a line, as one summary has them, and with no space before the dash.
    assert [m["name"] for m in sac.roll_of(["Phil Serna – District 1 Patrick Kennedy–", "District 2 (Vice Chair)", "ACTION SUMMARY"])] == \
        ["Phil Serna", "Patrick Kennedy"]
    old = sac.roll_of(["ACTION SUMMARY", "Supervisors: Illa Collin, Roger Dickinson, Don Nottoli, Susan Peters, Jimmie R. Yee,",
                       "(All Supervisors were present)"])
    assert [(m["name"], m["district"]) for m in old] == [("Illa Collin", None), ("Roger Dickinson", None), ("Don Nottoli", None),
                                                         ("Susan Peters", None), ("Jimmie Yee", None)]


def test_a_block_gives_aye_and_no_one_spelling_and_keeps_the_other_words_in_capitals():
    cast, problem = block("AYES: Phil Serna, Patrick Kennedy,", "NOES: Pat Hume", "ABSTAIN: (None)", "ABSENT: Rich Desmond",
                          "RECUSAL: Rosario Rodriguez")
    assert problem == ""
    assert cast == [("Phil Serna", "AYE"), ("Patrick Kennedy", "AYE"), ("Patrick Hume", "NO"), ("Rich Desmond", "ABSENT"),
                    ("Rosario Rodriguez", "RECUSAL")]
    assert {council_tables.vote_word(word) for word in sac.LABELS} == {"AYE", "NO", "ABSTAIN", "ABSENT", "RECUSAL"}
    # Before 2016 a block had no RECUSAL line.
    assert block("AYES: Phil Serna, Patrick Kennedy, Rich Desmond, Rosario Rodriguez, Pat Hume", "NOES: (None)", "ABSTAIN: (None)",
                 "ABSENT: (None)")[1] == ""


@pytest.mark.parametrize("lines, why", [
    (["AYES: Phil Serna, Patrick Kennedy, Rich Desmond, Pat Hume, Betty Williams", "NOES: None", "ABSTAIN: None", "ABSENT: Rosario Rodriguez"],
     "not on the roll: Betty Williams"),
    (["AYES: Phil Serna, Patrick Kennedy, Rich Desmond, Pat Hume", "NOES: None", "ABSTAIN: None", "ABSENT: None"], "4 of 5 supervisors named"),
    (["AYES: Phil Serna, Patrick Kennedy, Rich Desmond, Pat Hume", "NOES: Phil Serna", "ABSTAIN: None", "ABSENT: Rosario Rodriguez"],
     "named twice: Phil Serna"),
    (["AYES: Phil Serna Patrick Kennedy, Rich Desmond, Pat Hume, Rosario Rodriguez", "NOES: None", "ABSTAIN: None", "ABSENT: None"],
     "not on the roll: Phil Serna Patrick Kennedy"),
    (["AYES: Serna, Kennedy, Desmond, Hume", "NOES: None", "ABSENT: Rodriguez"], "words missing or out of order: AYES NOES ABSENT"),
    (["AYES: Phil Serna, Patrick Kennedy, Rich Desmond, Pat Hume", "NOES: None", "ABSTAIN: None",
      "ABSENT: Rosario Rodriguez 7. Adopt An Ordinance"], "not on the roll: Rosario Rodriguez 7. Adopt An Ordinance"),
])
def test_a_block_that_does_not_read_cleanly_is_not_read_at_all(lines, why):
    assert sac.read_block(lines, ROLL) == (None, why)
    assert sac.read_block(["AYES: Phil Serna", "NOES: None", "ABSTAIN: None", "ABSENT: None"], [])[0] is None  # no roll to hold it to


def test_a_summary_is_read_into_headings_items_and_the_votes_on_each_motion(monkeypatch, tmp_path):
    agenda, votes, facts = read(monkeypatch, SUMMARY, tmp_path)
    assert list(agenda) == ["10218-s1", "10218-1", "10218-2", "10218-3", "10218-s2", "10218-4"]
    assert (facts["summary"], facts["pages"], facts["vote_blocks"], facts["blocks_read"]) == ("read", 3, 2, 2)
    consent, taken_out = agenda["10218-s1"], agenda["10218-2"]
    assert (consent["heading"], consent["title"], consent["mover"], consent["seconder"]) == \
        (True, "Section I - Consent Matters (Items 1 - 3)", "Patrick Hume", "Patrick Kennedy")
    assert (consent["ayes"], consent["noes"], consent["not_voting"], consent["votes_read"], consent["action_time"]) == (4, 0, 1, True, "10:10 AM")
    # The names of item 2's block run over a line and over the foot of a page.
    assert (taken_out["title"], taken_out["subject"], taken_out["districts"], taken_out["number"], taken_out["doc_type"]) == \
        ("Approve The Fee Schedule (Finance)", "Finance", "All", "2026-0181", "resolution")
    assert (taken_out["action"], taken_out["mover"], taken_out["seconder"]) == ("Adopted Resolution No. 2026-0181.", "Rich Desmond", "Patrick Kennedy")
    assert (taken_out["ayes"], taken_out["noes"], taken_out["not_voting"], taken_out["votes_read"]) == (3, 2, 0, True)
    assert [(v["member"], v["vote"]) for v in votes if v["item_id"] == "10218-2"] == [
        ("Patrick Kennedy", "AYE"), ("Rich Desmond", "AYE"), ("Phil Serna", "AYE"), ("Rosario Rodriguez", "NO"), ("Patrick Hume", "NO")]
    assert sorted((v["member"], v["vote"]) for v in votes if v["item_id"] == "10218-s1") == sorted([
        ("Phil Serna", "AYE"), ("Patrick Kennedy", "AYE"), ("Rosario Rodriguez", "AYE"), ("Patrick Hume", "AYE"), ("Rich Desmond", "ABSENT")])
    assert {v["motion"] for v in votes} == {1} and len(votes) == 10
    # An item with no block has an action and no votes; whether its votes were read is not a question.
    assert (agenda["10218-4"]["action"], agenda["10218-4"]["vote_blocks"], agenda["10218-4"]["votes_read"]) == ("Held a workshop.", 0, None)
    assert (agenda["10218-1"]["group"], agenda["10218-3"]["group"]) == ("COUNTY EXECUTIVE", "SACRAMENTO COUNTY WATER AGENCY")


def test_a_consent_item_takes_its_headings_vote_unless_the_motion_left_it_out(monkeypatch, tmp_path):
    agenda, votes, facts = read(monkeypatch, SUMMARY, tmp_path)
    assert [agenda[item]["voted_with"] for item in ("10218-1", "10218-2", "10218-3", "10218-4")] == ["10218-s1", "10218-2", "10218-s1", ""]
    table = pd.DataFrame(list(agenda.values()), columns=sac.AGENDA_COLUMNS)
    meetings = pd.DataFrame([{"meeting_id": "10218", "minutes_url": MEETING["minutes_url"]}])
    items = sac.items_table(sac.typed(table, pd.DataFrame(votes, columns=sac.VOTE_COLUMNS))[0], meetings).set_index("matter_id")
    assert set(items["url"]) == {MEETING["minutes_url"]}
    assert list(items.loc[["10218-1", "10218-2", "10218-3", "10218-4"], "action_on"]) == ["section", "item", "section", ""]
    one = items.loc["10218-1"]
    assert (one["last_action"], one["ayes"], one["noes"], one["mover"], one["doc_type"], one["number"]) == \
        ("Approved by Sacramento County Code Ordinance No. SCC-1774.", 4, 0, "Patrick Hume", "ordinance", "SCC-1774")
    assert (items.loc["10218-2", "ayes"], items.loc["10218-2", "noes"], items.loc["10218-4", "ayes"]) == (3, 2, 0)
    # However the motion says what it left out, every number after the word is left out.
    for words in ("with the exceptions of 2 and 3.", "excluding Item Nos. 2 and 3", "with the exception Item 3, and A-2"):
        text = SUMMARY.replace("with the exception of Item 2.", words)
        assert [read(monkeypatch, text, tmp_path)[0][item]["voted_with"] for item in ("10218-1", "10218-3")] == ["10218-s1", ""]


def test_a_motion_whose_block_cannot_be_read_is_kept_with_no_votes_and_says_why(monkeypatch, tmp_path):
    text = SUMMARY.replace("NOES: Rosario Rodriguez, Pat Hume", "NOES: Rosario Rodriguez")  # one supervisor lost from the block
    agenda, votes, facts = read(monkeypatch, text, tmp_path)
    unread = agenda["10218-2"]
    assert (unread["action"], unread["mover"], unread["vote_blocks"], unread["blocks_read"], unread["votes_read"]) == \
        ("Adopted Resolution No. 2026-0181.", "Rich Desmond", 1, 0, False)
    assert (unread["ayes"], unread["noes"], unread["not_voting"], unread["problem"]) == (0, 0, 0, "4 of 5 supervisors named")
    assert not [v for v in votes if v["item_id"] == "10218-2"] and len(votes) == 5
    assert (facts["vote_blocks"], facts["blocks_read"]) == (2, 1)
    assert '"read":false,"problem":"4 of 5 supervisors named"' in unread["motion_log"]


def test_a_count_stated_in_the_action_must_be_the_count_in_the_block():
    text = HEAD + """Section I - Separate Matters
1. Adopt The Budget
2:00 PM Board Action: Phil Serna/ Rich Desmond - Adopted the budget by a 4-1 vote.
AYES: Phil Serna, Rich Desmond, Patrick Kennedy
NOES: Rosario Rodriguez, Pat Hume
ABSTAIN: None
ABSENT: None
"""
    roll, lines = sac.parse(text)
    assert [(m["read"], m["cast"], m["problem"]) for m in lines[1]["motions"]] == [(False, [], "the action says 4-1 and the block has 3-2")]
    roll, lines = sac.parse(text.replace("4-1", "3-2"))
    assert lines[1]["motions"][0]["read"] and len(lines[1]["motions"][0]["cast"]) == 5


BLOCK = "AYES: Phil Serna, Patrick Kennedy, Rich Desmond, Rosario Rodriguez, Pat Hume\nNOES: None\nABSTAIN: None\nABSENT: None\n"


def test_numbered_points_inside_an_action_are_not_items_and_a_failed_motion_is_marked(monkeypatch, tmp_path):
    text = HEAD + f"""Section I - Timed Matters
1. 10:00 AM -- Proposed Rate Increases (Water Resources)
Supervisorial District(s): All
11:35 AM Board Action: Rich Desmond/ Phil Serna - Continued the item.
MOTION FAILED
{BLOCK}11:40 AM Board Action: Rich Desmond/ Patrick Kennedy - Directed staff to:
1. Approve the proposed rates.
2. Enact the increases.
3. Mail notices.
{BLOCK}2. County Executive Comments
"""
    agenda, votes, facts = read(monkeypatch, text, tmp_path)
    assert list(agenda) == ["10218-s1", "10218-1", "10218-2"]
    rates = agenda["10218-1"]
    assert (rates["motions"], rates["vote_blocks"], rates["blocks_read"], rates["votes_read"]) == (2, 2, 2, True)
    assert rates["action"] == "Directed staff to: 1. Approve the proposed rates. 2. Enact the increases. 3. Mail notices."
    assert sorted({(v["motion"], v["motion_text"]) for v in votes}) == [(1, "Continued the item. MOTION FAILED"), (2, rates["action"])]
    # The line carries its last vote, which carried; the one that failed is in the log of its motions.
    assert rates["result"] == "" and "MOTION FAILED" in rates["motion_log"]


def test_where_the_numbering_is_broken_the_blocks_it_could_have_misplaced_are_left_unread():
    lost = HEAD + f"""Section I - Separate Matters
1. First Item
9:00 AM Board Action: Phil Serna/ Rich Desmond - Approved.
{BLOCK}Second Item, Whose Number The Text Has Lost
9:05 AM Board Action: Phil Serna/ Rich Desmond - Approved.
{BLOCK}3. Third Item
9:10 AM Board Action: Phil Serna/ Rich Desmond - Approved.
{BLOCK}"""
    roll, lines = sac.parse(lost)
    assert [(line["number"], bool(line["doubt"])) for line in lines] == [("", False), ("1", True), ("3", False)]
    assert lines[1]["doubt"] == "no item numbered 2: it may have run on from the one before"
    # A title broken before a number is not an item: the numbering picks up again under it.
    broken = HEAD + f"""Section I - Separate Matters
1. Request To Appoint Trustees Of Reclamation District
813. This Item Will Return
Supervisorial District(s): All
9:00 AM Board Action: Phil Serna/ Rich Desmond - Approved.
{BLOCK}2. Second Item
9:05 AM Board Action: Phil Serna/ Rich Desmond - Approved.
{BLOCK}"""
    roll, lines = sac.parse(broken)
    assert [(line["number"], line["doubt"], [m["read"] for m in line["motions"]]) for line in lines[1:]] == [("1", "", [True]), ("2", "", [True])]
    assert lines[1]["title"].endswith("District 813. This Item Will Return")
    # A second block under one action: which of the two is the vote on it the summary does not say.
    twice = HEAD + f"Section I - Separate Matters\n1. First Item\n9:00 AM Board Action: Phil Serna/ Rich Desmond - Approved.\n{BLOCK}{BLOCK}"
    assert [m["doubt"] for m in sac.parse(twice)[1][1]["motions"]] == ["two blocks under one action", "a block with no action of its own before it"]


def test_a_matter_with_no_number_is_a_line_of_its_own(monkeypatch, tmp_path):
    text = HEAD + f"""9:30 AM -- Election Of 2026 Chair
9:34 AM Board Action: Phil Serna/ Rich Desmond - Supervisor Rodriguez was elected Chair.
{BLOCK}Section I - Separate Matters
1. First Item
9:40 AM Board Action: Phil Serna/ Rich Desmond - Approved.
{BLOCK}CLOSED SESSION
CONFERENCE WITH LEGAL COUNSEL-EXISTING LITIGATION
11:00 AM Board Action: Phil Serna/ Rich Desmond - Approved the settlement.
{BLOCK}"""
    agenda, votes, facts = read(monkeypatch, text, tmp_path)
    assert [(item, row["agenda_number"], row["title"], row["blocks_read"]) for item, row in agenda.items()] == [
        ("10218-u1", "", "9:30 AM -- Election Of 2026 Chair", 1), ("10218-s1", "", "Section I - Separate Matters", 0),
        ("10218-1", "1", "First Item", 1), ("10218-u2", "", "CLOSED SESSION CONFERENCE WITH LEGAL COUNSEL-EXISTING LITIGATION", 1)]
    assert {v["item_id"] for v in votes if v["motion_text"] == "Approved the settlement."} == {"10218-u2"}


def test_a_summary_that_is_a_scan_is_counted_and_left(monkeypatch, tmp_path):
    agenda, votes, facts = read(monkeypatch, "\f\f \f", tmp_path)
    assert (agenda, votes, facts["summary"], facts["pages"]) == ({}, [], "no text layer", 4)


def test_a_refusal_is_not_asked_again(monkeypatch):
    asked = []

    class Answer:
        status_code, headers, content, text = 403, {"content-type": "text/html"}, b"<html>", "<html>"

    monkeypatch.setattr(sac.requests, "get", lambda url, **kwargs: asked.append(url) or Answer())
    try:
        with pytest.raises(sac.Refused):
            sac.fetch(sac.HOST + "/Meetings/Search")
        with pytest.raises(sac.Refused):
            sac.fetch(sac.HOST + "/Meetings/Search")
        assert len(asked) == 1
    finally:
        sac._refused.clear()


def test_a_run_reads_the_newest_first_skips_what_it_has_read_and_writes_the_five_tables(monkeypatch, tmp_path):
    rows = [{"meeting_id": str(number), "name": "BOARD OF SUPERVISORS", "date": f"2024-01-{number:02d}" if number < 29 else f"2023-{number % 12 + 1:02d}-15",
             "time": "9:30 AM", "agenda": "a.pdf", "summary": "s.pdf" if number in (5, 6, 7) else "", "packet": ""} for number in range(1, 121)]
    read_now = []

    def text_of(meeting, out_dir, fresh=False):
        read_now.append(meeting["meeting_id"])
        if meeting["meeting_id"] == "5":
            raise ValueError("the system sent a page in place of the summary")
        return SUMMARY

    monkeypatch.setattr(sac, "listed", lambda: rows)
    monkeypatch.setattr(sac, "text_of", text_of)
    monkeypatch.setattr(council_tables, "published", lambda repo, name: None)
    monkeypatch.setattr(county_of(), "WORKERS", 1)
    tables, read = sac.build(True, False, tmp_path, limit=2)
    assert (read_now, read) == (["7", "6"], 2)
    tables, read = sac.build(True, False, tmp_path)
    assert (read_now, read) == (["7", "6", "5"], 0)  # the one that could not be fetched is asked for again, the others are not
    assert {name: list(table.columns[:len(council_tables.COLUMNS[name])]) for name, table in tables.items()} == council_tables.COLUMNS
    meetings = tables["meetings"].set_index("meeting_id")
    assert list(meetings.loc[["5", "6", "7", "8"], "summary"]) == ["", "read", "read", ""]
    assert (meetings.loc["7", "items"], meetings.loc["7", "vote_blocks"], meetings.loc["7", "blocks_read"]) == (4, 2, 2)
    assert len(tables["votes"]) == 20 and set(tables["votes"]["vote"]) == {"AYE", "NO", "ABSENT"}
    members = tables["members"].set_index("name")
    assert sorted(members.index) == sorted(member["name"] for member in ROLL)
    assert (members.loc["Patrick Hume", "district"], members.loc["Patrick Hume", "role"], members.loc["Patrick Hume", "votes"]) == (5, "Vice Chair", 4)
    assert members["serving"].all() and set(members["first_vote"]) == {"2024-01-06"}
    assert all((tmp_path / f"{name}.parquet").exists() for name in council_tables.TABLES)
    assert "{" not in sac.card(tables).split("## Tables")[1]  # every fact the card asks for was written in


def county_of():
    import build_sd_county
    return build_sd_county
