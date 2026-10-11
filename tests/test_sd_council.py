"""build_sd_council reads who sat on the City Council from an agenda, and what was done from the Clerk's results summary."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import build_sd_council as council

AGENDA = """
<p>CITY OF SAN DIEGO</p><p>COUNCIL AGENDA</p>
<p>COUNCIL PRESIDENT</p><p>Joe LaCava <span>•</span> First District</p>
<p>COUNCIL PRESIDENT PRO TEM</p><p>Kent Lee • Sixth District</p>
<p>COUNCILMEMBERS</p>
<p>Jennifer Campbell</p><p>•</p><p>Second District</p>
<p>Georgette G<span>ó</span><span>mez</span> • Ninth <span>District</span></p>
<p>Charles Modica</p><p>Heather Ferbert</p><p>Independent Budget Analyst</p><p>City Attorney</p>
<p>Tuesday, March 25, 2025, AT 10:00 AM and 2:00 PM</p>
"""
ROSTER = [{"district": d, "name": name, "role": "Councilmember"} for d, name in enumerate(
    ["Joe LaCava", "Jennifer Campbell", "Stephen Whitburn", "Henry L. Foster III", "Marni von Wilpert", "Kent Lee", "Raul A. Campillo", "Vivian Moreno", "Sean Elo-Rivera"], 1)]


def row(number, action, kind="", doc="", movers="", vote=""):
    paragraphs = "".join(f"<p>{line}</p>" for line in action)
    return f"<tr><td><p>{number}</p></td><td>{paragraphs}</td><td>{kind}</td><td>{doc}</td><td>{movers}</td><td><p>{vote}</p></td></tr>"


SUMMARY = "<table><tr><td>ITEM NO.</td><td>ACTIONS</td><td>R</td><td>316125</td><td>Motion / Second</td><td>VOTE</td></tr>" + "".join([
    row("30", ["Approved", "Proclaiming March 31, 2025, to be a day"], movers="5/3", vote="Unanimous; all present"),
    row("50", ["Introduced (O-2025-98)", "Approving a six-month extension", "(NOTE: 6 votes required)"], "I", "", "2/6", "Unanimous; 4-not present"),
    row("52", ["Adopted (O-2025-91)", "Amending the SDMC regarding the Cannabis Business Tax"], "O", "2193<span>5</span>", "2/6", "12356789-yea; 4-nay"),
    row("S507", ["Adopted as Amended (R-2025-424 Rev.)", "Approving the loan agreement"], "R", "316132", "9/6", "Unanimous; all present (Motion to approve staff’s recommendation)"),
    row("330", ["Item Presented", "Presenting the 2025 Council Work Plan"]),
]) + "</table>"
MEETING = {"meeting_id": "6457", "date": "2025-03-25"}


def test_the_agenda_says_who_sat_in_each_district_and_who_presided():
    roster = council.roster_of(AGENDA)
    assert [(seat["district"], seat["name"], seat["role"]) for seat in roster] == [
        (1, "Joe LaCava", "Council President"), (2, "Jennifer Campbell", "Councilmember"),
        (6, "Kent Lee", "Council President Pro Tem"), (9, "Georgette Gómez", "Councilmember")]
    assert council.time_of(AGENDA) == "10:00 AM"


def test_a_vote_is_read_from_the_clerks_words_by_district():
    seats = {district: "x" for district in range(1, 10)}
    assert set(council.read_vote("Unanimous; all present", seats).values()) == {"AYE"}
    split = council.read_vote("12356789-yea; 4-nay", seats)
    assert split[4] == "NO" and sum(vote == "AYE" for vote in split.values()) == 8
    assert council.read_vote("2346789-yea; 15-recused", seats)[5] == "RECUSED"
    assert council.read_vote("Approved by unanimous consent; 29-not present", seats)[9] == "NOT PRESENT"
    assert council.read_vote("Motion to add the following language", seats) == {} and council.read_vote("", seats) == {}


def test_a_row_of_the_summary_is_an_action_a_draft_number_and_what_was_done():
    entries, votes = council.read_summary(SUMMARY, MEETING, ROSTER)
    by = {entry["agenda_number"]: entry for entry in entries}
    assert list(by) == ["30", "50", "52", "S507", "330"]
    assert (by["52"]["action"], by["52"]["matter_file"], by["52"]["doc_num"], by["52"]["doc_type"]) == ("Adopted", "O-2025-91", "O-21935", "ordinance")
    assert by["52"]["title"] == "Amending the SDMC regarding the Cannabis Business Tax" and (by["52"]["ayes"], by["52"]["noes"]) == (8, 1)
    assert (by["S507"]["action"], by["S507"]["matter_file"], by["S507"]["doc_num"]) == ("Adopted as Amended", "R-2025-424", "R-316132")
    assert by["50"]["title"].endswith("(NOTE: 6 votes required)") and by["50"]["not_voting"] == 1 and by["50"]["result"] == "Pass"
    assert (by["30"]["mover"], by["30"]["seconder"]) == ("Marni von Wilpert", "Stephen Whitburn") and by["30"]["matter_id"] == "6457-30"
    assert by["330"]["action"] == "Item Presented" and by["330"]["ayes"] == 0 and by["330"]["result"] == ""
    no = [vote for vote in votes if vote["vote"] == "NO"]
    assert len(votes) == 36 and [(vote["member"], vote["district"], vote["item_id"]) for vote in no] == [("Henry L. Foster III", 4, "6457-52")]


def test_an_ordinance_is_one_item_from_its_introduction_to_its_adoption():
    first, _ = council.read_summary("<table>" + row("50", ["Introduced (O-2025-91)", "Amending the tax"], "I", "", "2/6", "Unanimous; all present") + "</table>",
                                    {"meeting_id": "6440", "date": "2025-03-11"}, ROSTER)
    second, _ = council.read_summary(SUMMARY, MEETING, ROSTER)
    items = council.items_table(pd.DataFrame(first + second, columns=council.AGENDA_COLUMNS))
    tax = items[items["matter_id"] == "O-2025-91"].iloc[0]
    assert tax["times_on_agenda"] == 2 and tax["date"] == "2025-03-11" and tax["last_action"] == "Adopted" and tax["doc_num"] == "O-21935"
    assert tax["passed_date"] == "2025-03-25" and tax["noes"] == 1 and len(items) == 5


def test_a_member_is_serving_if_the_latest_agenda_lists_them():
    rosters = pd.DataFrame([
        {"meeting_id": "1", "date": "2020-01-07", "district": 4, "name": "Monica Montgomery", "role": "Councilmember"},
        {"meeting_id": "2", "date": "2025-03-25", "district": 4, "name": "Henry L. Foster III", "role": "Councilmember"},
        {"meeting_id": "2", "date": "2025-03-25", "district": 1, "name": "Joe LaCava", "role": "Council President"},
        {"meeting_id": "1", "date": "2020-01-07", "district": 1, "name": "Barbara Bry", "role": "Council President Pro Tem"},
    ])
    votes = pd.DataFrame([{"member": "Joe LaCava", "date": "2025-03-25", "vote": "AYE"}, {"member": "Barbara Bry", "date": "2020-01-07", "vote": "NO"}])
    table = council.council_table(rosters, votes).set_index("name")
    assert table.loc["Joe LaCava", "serving"] and table.loc["Joe LaCava", "role"] == "Council President" and table.loc["Joe LaCava", "end"] == ""
    assert not table.loc["Barbara Bry", "serving"] and table.loc["Barbara Bry", "end"] == "2020-01-07" and table.loc["Barbara Bry", "role"] == "Member"
    assert table.loc["Barbara Bry", "votes"] == 1 and table.loc["Monica Montgomery", "votes"] == 0


def test_two_names_set_side_by_side_take_the_two_districts_that_follow_in_order():
    head = "<p>COUNCIL DOCKET</p><p>COUNCILMEMBERS</p><p>Marti Emerald</p><p>David Alvarez</p><p>•</p><p>•</p><p>Seventh District</p><p>Eighth District</p><p>City Clerk</p>"
    assert [(seat["district"], seat["name"]) for seat in council.roster_of(head)] == [(7, "Marti Emerald"), (8, "David Alvarez")]


def test_a_memorandum_bound_in_ahead_of_the_agenda_is_not_the_council():
    memo = "<p>Office of Council President Joe LaCava</p><p>First District</p><p>City Attorney Heather Ferbert</p>"
    roster = council.roster_of(memo + AGENDA)
    assert [seat["name"] for seat in roster] == ["Joe LaCava", "Jennifer Campbell", "Kent Lee", "Georgette Gómez"]


def test_one_person_under_two_names_is_one_person():
    head = "<p>COUNCIL AGENDA</p><p>Georgette Gomez • Ninth District</p><p>Monica Montgomery • Fourth District</p>"
    assert [seat["name"] for seat in council.roster_of(head)] == ["Monica Montgomery Steppe", "Georgette Gómez"]


def test_votes_written_other_ways_are_read_too():
    seats = {district: "x" for district in range(1, 10)}
    assert council.read_vote("Yea-12345679; Nay-8", seats)[8] == "NO" and council.read_vote("Yea-25679; nay-1348", seats)[2] == "AYE"
    odd = council.read_vote("1245679; 8-nay; 3-not present", seats)
    assert odd[1] == "AYE" and odd[8] == "NO" and odd[3] == "NOT PRESENT" and 9 in odd
    assert set(council.read_vote("Unaimous; all present", seats).values()) == {"AYE"}
    assert council.read_vote("289-not present", seats) == {} and council.read_vote("Passed by Common Consent", seats) == {}


def test_the_same_action_is_always_said_the_same_way():
    assert council.tidy_action("Adopted as amended.") == "Adopted as Amended" and council.tidy_action("Adopted with direction") == "Adopted with Direction"
    assert council.tidy_action("Continued to 8/2/2022 at 2:00 p.m.") == "Continued"
    assert council.tidy_action("This item was removed from the Agenda") == "Removed from the docket"


def test_a_meeting_whose_agenda_was_not_read_takes_the_council_of_the_one_before():
    read = [{"meeting": {"meeting_id": "1", "date": "2025-03-11"}, "roster": ROSTER, "entries": [], "votes": [], "summary": ""},
            {"meeting": MEETING, "roster": ROSTER[:1], "entries": [], "votes": [], "summary": SUMMARY}]
    fixed = council.borrow_rosters(read, [])[1]
    assert len(fixed["roster"]) == 9 and len(fixed["votes"]) == 36 and fixed["entries"][2]["noes"] == 1


def test_a_note_after_a_district_does_not_put_everyone_one_seat_along():
    head = "<p>COUNCIL AGENDA</p><p>COUNCIL PRESIDENT PRO TEM</p><p>Joe LaCava</p><p>•</p><p>First District (Rev. 12/11/23)</p><p>COUNCILMEMBERS</p><p>Jennifer Campbell</p><p>•</p><p>Second District</p><p>Vacant</p><p>•</p><p>Fourth District</p><p>Kent Lee • Sixth District</p>"
    assert [(seat["district"], seat["name"]) for seat in council.roster_of(head)] == [(1, "Joe LaCava"), (2, "Jennifer Campbell"), (6, "Kent Lee")]


def test_figures_before_a_word_belong_to_that_word_only():
    seats = {district: "x" for district in range(1, 10)}
    cast = council.read_vote("123468, 5-nay; 7-not present", seats)
    assert [d for d, vote in cast.items() if vote == "NO"] == [5] and cast[7] == "NOT PRESENT" and sum(vote == "AYE" for vote in cast.values()) == 6
    plain = council.read_vote("234567 yea; 18 nay; 9 not present", seats)
    assert sum(vote == "AYE" for vote in plain.values()) == 6 and plain[1] == plain[8] == "NO" and plain[9] == "NOT PRESENT"
