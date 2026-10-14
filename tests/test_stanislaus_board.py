"""build_stanislaus_board reads the Stanislaus County Board's votes out of minutes that name only who moved, who
seconded and who did not vote aye: a motion whole or not at all."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import build_stanislaus_board as stan
import council_tables

ROLL = ["B. Condit", "C. Condit", "Chiesa", "Grewal", "Withrow"]
MEETING = {"meeting_id": "2026-09-15", "date": "2026-09-15", "minutes_url": "https://example.test/min09-15-26.pdf"}

# Minutes as the reader keeps them: a line set in from the margin begins with spaces, an empty line is a gap on the
# page, a form feed parts two pages and the number at a page's foot stands above it.
MINUTES = """THE BOARD OF SUPERVISORS
OF THE COUNTY OF STANISLAUS
STATE OF CALIFORNIA

Special and Regular Session Tuesday September 15, 2026
Chairman Chiesa Absent*
Pledge of Allegiance to the Flag

1.1 Conferenced with Legal Counsel – Existing Litigation. No reportable action
was taken.

Chairman Chiesa arrived at 6:30 p.m.

Daryl Terrell shared concerns regarding the theft of a catalytic converter.

Grewal/B. Condit unan. Adopted the consent calendar after removing from consent item
6.B.2 Approval of an Emergency Update – Parks
    6.A.1 Approved the minutes of 09/01/2026
    6.B.1 Authorized the Directors to close services located on Scenic Avenue for one
            day – GSA 2026-0401
1
\f    6.B.3 Approved participation in a cooperative agreement with Carahsoft
            Technology Corporation – ITC

Withrow/Grewal unan. 6.B.2 Approved an emergency update for temporary repairs to the Basso
Bridge – Parks

Grewal/B. Condit (4-1)(C. Condit opposed) 7.1 Amended the item to add Staff Recommendation
Nos. 10-12; adopted Resolution No. 2026-0412 – CEO

Chairman Chiesa left the meeting at 9:56 p.m.

B. Condit/Grewal (4-0)(Chiesa absent) 7.2 Conducted a public hearing; adopted the report
2
\fand authorized staff to submit it – Planning

Grewal/B. Condit unan. 8.1 Approved renewals to agreements – BHRS

Supervisor C. Condit reported that a community clean-up was held in Newman.

Adjourned at 10:35 p.m.
"""


def how_of(words):
    return stan.notation(words)[0]


def cast_of(words, roll=ROLL, **said):
    cast, problem = stan.decide(how_of(words), roll, **said)
    return (None if cast is None else {member: (word, way) for member, word, way in cast}), problem


def read(text=MINUTES, roll=ROLL):
    agenda, votes, facts = stan.read_meeting(MEETING, stan.scan(text), roll, pages=text.count("\f") + 1)
    return {row["item_id"]: row for row in agenda}, votes, facts


def test_a_year_page_gives_each_meeting_its_day_and_documents_and_leaves_out_what_is_not_a_meeting():
    page = """<dl><dt>March 2026</dt>
      <dd><ul class="list-inline agendalist"><li><strong>03/17</strong></li><li>6:30 p.m.</li>
        <li><a href="/bos/agenda/2026/ag03-17-26.pdf" target="_blank">Agenda</a></li>
         <li><a href="/bos/minutes/2026/min03-17-26.pdf" target="_blank">Minutes</a></li>
        <li><a href="/bos/video/03-17-2026.shtm">Video <i class="glyphicon"></i></a></li></ul></dd>
      <dd><ul class="list-inline agendalist"><li><strong>03/24</strong></li><li>No Meeting</li>
        <!-- <li><a href="/bos/minutes/2026/min03-31-26.pdf" target="_blank">Minutes</a></li> --></ul></dd>
      <!-- <dd><ul class="list-inline agendalist"><li><strong>03/27</strong></li>
        <li><a href="/bos/minutes/2026/min03-27-26.pdf">Minutes</a></li></ul></dd> -->
      <dd><ul class="list-inline agendalist"><li><strong>03/30</strong></li>
        <li><a href="/bos/Agenda/2026/Ag 03-30-26.pdf">Agenda</a></li>
        <li><a href="/bos/minutes/2026/min03-30-26special.pdf">Minutes</a></li><li>Special Meeting</li></ul></dd></dl>"""
    meetings = stan.meetings_table(stan.rows_of(page, 2026)).set_index("meeting_id")
    assert list(meetings.index) == ["2026-03-17", "2026-03-30-special"]  # a day with no meeting and a row in a comment are not meetings
    first, special = meetings.loc["2026-03-17"], meetings.loc["2026-03-30-special"]
    assert (first["date"], first["time"]) == ("2026-03-17", "6:30 PM")  # the hour as every board has it
    assert first["minutes_url"] == "https://www.stancounty.com/bos/minutes/2026/min03-17-26.pdf"
    assert first["video_url"] == "https://www.stancounty.com/bos/video/03-17-2026.shtm"
    assert special["agenda_url"] == "https://www.stancounty.com/bos/Agenda/2026/Ag%2003-30-26.pdf"
    assert special["note"] == "Special Meeting"
    assert list(meetings.columns)[:len(council_tables.COLUMNS["meetings"]) - 1] == council_tables.COLUMNS["meetings"][1:]


def test_the_words_between_the_movers_and_the_action_are_read_apart_from_the_action():
    how, said = stan.notation("(3-1)(C. Condit opposed)(Grewal absent) 7.2 Accepted the update")
    assert (how["tally"], how["unanimous"], said) == ((3, 1), False, "7.2 Accepted the update")
    assert how["notes"] == [(["C. Condit"], "NO"), (["Grewal"], "ABSENT")]
    assert how["printed"] == "(3-1)(C. Condit opposed)(Grewal absent)"
    assert how_of("unan. Adopted the consent calendar")["unanimous"]
    assert how_of("(unan) 5.B.5 Amended the Resolution")["unanimous"]
    assert how_of("unan 9:25 a.m. Conducted the public hearing")["unanimous"]
    # A bracket that says nothing of the vote opens the action.
    assert stan.notation("unan. (VI-C) Accepted the report")[1] == "(VI-C) Accepted the report"
    assert how_of("(2-3) (Chiesa, DeMartini and Chairwoman Olsen opposed) 8.1 The motion failed")["notes"] == [(["Chiesa", "DeMartini", "Olsen"], "NO")]
    assert how_of("(4-0)(District Four vacant) Adopted the consent calendar")["vacant"] == 1
    assert how_of("(3-0)(Withrow and De Martini abstained) D1 Finds")["notes"] == [(["Withrow", "De Martini"], "ABSTAIN")]
    assert how_of("(4-0)(Withrow recused) 8.1 Approved")["notes"] == [(["Withrow"], "RECUSED")]
    assert how_of("(4-1 DeMartini opposed)*B3 Approved")["notes"] == [(["DeMartini"], "NO")]
    assert how_of("(4-0)(District 4 Supervisor absent) Elected")["notes"] == [([stan.UNKNOWN], "ABSENT")]


def test_a_count_is_read_when_everyone_outside_the_ayes_is_named_and_the_numbers_make_the_seats():
    cast, problem = cast_of("(4-1)(C. Condit opposed) 7.1 Amended")
    assert problem == ""
    assert cast["C. Condit"] == ("NO", "named")
    assert {member: vote for member, vote in cast.items() if member != "C. Condit"} == {
        member: ("AYE", "count") for member in ROLL if member != "C. Condit"}
    cast, _ = cast_of("(3-0)(C. Condit recused)(B. Condit absent) 6.D.1 Set a public hearing")
    assert cast["C. Condit"] == ("RECUSED", "named") and cast["B. Condit"] == ("ABSENT", "named")
    assert sorted(member for member, (word, _) in cast.items() if word == "AYE") == ["Chiesa", "Grewal", "Withrow"]
    # The third number of a count is not relied on; the first two and the names must agree.
    assert cast_of("(3-1-0)(Chiesa opposed)(Withrow recused) 6.2 Conducted")[0]["Grewal"] == ("AYE", "count")
    # A count the names do not bear out is not read.
    assert cast_of("(4-1)(Withrow absent) 6.1 Recognized")[1] == "the count has 1 against and 0 are named"
    assert cast_of("(4-0) Olsen absent Adopted the consent calendar")[1] == "4-0 and 0 named as not voting do not make 5"
    assert cast_of("(3-2)(Chiesa and Withrow abstained) 6.1 Conducted")[1] == "the count has 2 against and 0 are named"
    assert cast_of("(4-1)(C. Condit opposed) unan. 8.2 Approved")[1] == "the line says 4-1 and unanimous both"
    assert cast_of("(4-0)(Monteith absent) B9 Approved")[1] == "not on the roll: Monteith"
    assert cast_of("(4-0)(District 4 Supervisor absent) Elected")[1] == "not on the roll: someone the minutes do not name"
    assert cast_of("(3-0)(Chiesa abstained)(Chiesa absent) B2 Approved")[1] == "named twice: Chiesa"
    assert cast_of("(Withrow recused) 5.B.3 Approved")[1] == "neither a count nor unanimous"


def test_unanimous_is_read_only_when_the_minutes_have_nobody_away():
    cast, problem = cast_of("unan. Adopted the consent calendar")
    assert problem == "" and cast == {member: ("AYE", "unanimous") for member in ROLL}
    assert cast_of("unan. 6.1 Accepted", away=["Chiesa"])[1] == "unanimous, and the minutes have Chiesa away"
    assert cast_of("unan. 6.1 Accepted", away=[stan.UNKNOWN])[1] == "unanimous, and the minutes have someone unnamed away"
    assert cast_of("unan. 6.1 Accepted", excused=["Withrow"])[1] == "unanimous, and the minutes have Withrow away"
    assert cast_of("unan. 6.1 Accepted", known=False)[1] == "unanimous, and the head of the minutes does not say who was present"
    # Unanimous with a supervisor named as taking no part: he has his word and the rest voted aye.
    cast, problem = cast_of("(Withrow recused) unan. 7.1 Conducted", away=["Withrow"])
    assert problem == "" and cast["Withrow"] == ("RECUSED", "named") and cast["Chiesa"] == ("AYE", "unanimous")
    # A count with no noes may say unanimous as well.
    assert cast_of("unan. (4-0)(Withrow abstained) 7.D.1 Finds")[0]["Withrow"] == ("ABSTAIN", "named")


def test_nothing_is_read_without_a_name_for_every_seat():
    assert cast_of("unan. Adopted the consent calendar", roll=ROLL[:4])[1] == "the minutes around this day name 4 supervisors for 5 seats"
    assert cast_of("(4-0)(Chiesa absent) 7.2 Conducted", roll=ROLL + ["Olsen"])[1] == "the minutes around this day name 6 supervisors for 5 seats"
    # A seat the minutes call vacant needs no name.
    cast, problem = cast_of("(4-0)(District Four vacant) Adopted the consent calendar", roll=ROLL[:4])
    assert problem == "" and cast == {member: ("AYE", "count") for member in ROLL[:4]}
    assert cast_of("unan. 6.1 Accepted", roll=ROLL[:4], vacant=1)[0] == {member: ("AYE", "unanimous") for member in ROLL[:4]}
    assert cast_of("(3-0)(Chiesa abstained)(District 4 vacant) 6.B.2 Approved", roll=ROLL[:4])[0]["Chiesa"] == ("ABSTAIN", "named")


def test_the_roll_of_a_day_is_whoever_the_minutes_name_on_it_or_on_both_sides_of_it():
    index = stan.roll_index({
        "a": ("2024-12-17", ["Chiesa", "Withrow", "B. Condit", "Olsen"]),
        "b": ("2025-01-07", ["Chiesa", "Withrow", "B.Condit", "Grewal"]),
        "c": ("2025-01-28", ["C. Condit", "Grewal", "De Martini"]),
        "d": ("2025-03-04", ["Chiesa", "Withrow", "B. Condit", "C. Condit", "DeMartini", "DeMartini"]),
        "e": ("2027-06-01", ["Olsen"]),
    })
    assert index["bcondit"][0] == "B. Condit" and index["demartini"][0] == "DeMartini"  # the form most often printed
    # C. Condit is first named on the 28th: he is not on the roll of the 7th, whoever sat then.
    assert stan.roll_on("2025-01-07", index) == ["B. Condit", "Chiesa", "Grewal", "Withrow"]
    assert stan.roll_on("2025-01-28", index) == ["B. Condit", "C. Condit", "Chiesa", "DeMartini", "Grewal", "Withrow"]
    # Olsen is named in 2024 and in 2027: too far apart to say anything of 2025.
    assert "Olsen" in stan.roll_on("2024-12-17", index) and "Olsen" not in stan.roll_on("2025-03-04", index)
    assert stan.roll_on("2025-03-04", index) == ["B. Condit", "C. Condit", "Chiesa", "DeMartini", "Withrow"]  # Grewal is not named again


def test_a_printed_name_is_matched_to_the_roll_by_its_letters():
    roll = ["Chiesa", "DeMartini", "Monteith", "O’Brien", "Withrow"]
    assert stan.who("De Martini", roll) == "DeMartini"
    assert stan.who("O'Brien", roll) == "O’Brien" and stan.who("OBrien", roll) == "O’Brien"
    assert stan.who("Chairman Chiesa", roll) == "Chiesa"
    assert stan.who("Montieth", roll) == "Monteith"  # a misspelling the minutes make
    assert stan.who("Condit", ROLL) is None  # two of them
    assert stan.who("B.Condit", ROLL) == "B. Condit"
    assert stan.who("M", roll) == "Monteith" and stan.who("C", ROLL) is None  # an initial, where only one name has it
    assert stan.names_in("Chairman Grover and Supervisor Simon") == ["Grover", "Simon"]
    assert stan.names_in("O’Brien, Monteith, and Mayfield") == ["O’Brien", "Monteith", "Mayfield"]
    assert stan.names_in("District 4 Supervisor") == [stan.UNKNOWN]


def test_minutes_are_read_into_a_consent_calendar_its_items_and_the_motions_after_it():
    agenda, votes, facts = read()
    assert list(agenda) == ["2026-09-15-11", "2026-09-15-c1", "2026-09-15-6A1", "2026-09-15-6B1", "2026-09-15-6B3",
                            "2026-09-15-6B2", "2026-09-15-71", "2026-09-15-72", "2026-09-15-81"]
    calendar = agenda["2026-09-15-c1"]
    assert calendar["heading"] and calendar["title"] == "Consent calendar"
    assert calendar["action"] == "Adopted the consent calendar after removing from consent item 6.B.2 Approval of an Emergency Update – Parks"
    assert (calendar["mover"], calendar["seconder"], calendar["how"]) == ("Grewal", "B. Condit", "unan.")
    assert (calendar["ayes"], calendar["noes"], calendar["votes_read"], calendar["established"]) == (5, 0, True, "unanimous")
    # The items of the calendar are set in under it; one runs over the page's end and its number is not the page's.
    item = agenda["2026-09-15-6B1"]
    assert item["title"] == "Authorized the Directors to close services located on Scenic Avenue for one day – GSA 2026-0401"
    assert (item["agenda_number"], item["section"], item["voted_with"], item["motions"]) == ("6.B.1", "Consent calendar", "2026-09-15-c1", 0)
    assert item["votes_read"] is None and item["subject"] == "GSA"
    assert agenda["2026-09-15-6B3"]["title"] == "Approved participation in a cooperative agreement with Carahsoft Technology Corporation – ITC"
    # The item taken off the calendar has a vote of its own and is not under the calendar.
    alone = agenda["2026-09-15-6B2"]
    assert (alone["section"], alone["voted_with"], alone["mover"], alone["ayes"]) == ("", "2026-09-15-6B2", "Withrow", 5)
    assert alone["title"] == "Approved an emergency update for temporary repairs to the Basso Bridge – Parks"
    divided = agenda["2026-09-15-71"]
    assert (divided["ayes"], divided["noes"], divided["not_voting"], divided["established"]) == (4, 1, 0, "count")
    assert (divided["doc_type"], divided["number"]) == ("resolution", "2026-0412")
    # A paragraph runs over a page's end; the next paragraph is not part of it.
    assert agenda["2026-09-15-72"]["title"] == "Conducted a public hearing; adopted the report and authorized staff to submit it – Planning"
    assert (agenda["2026-09-15-72"]["ayes"], agenda["2026-09-15-72"]["not_voting"]) == (4, 1)
    # Business with a number and no motion is kept, with no vote.
    assert agenda["2026-09-15-11"]["title"].startswith("Conferenced with Legal Counsel") and agenda["2026-09-15-11"]["motions"] == 0
    assert (facts["motions"], facts["motions_read"], facts["present"], facts["name"]) == (5, 4, "Chairman Chiesa Absent", "Special and Regular Session")
    assert json.loads(facts["named"]) == ROLL
    assert {member["name"]: member["role"] for member in json.loads(facts["roll"])}["Chiesa"] == "Chairman"


def test_a_supervisor_who_came_late_is_in_a_unanimous_vote_and_one_who_left_stops_it_being_read():
    agenda, votes, _ = read()
    # Absent at the head, arrived before the calendar: all five voted on it.
    assert sorted(vote["member"] for vote in votes if vote["item_id"] == "2026-09-15-c1") == ROLL
    assert {vote["established"] for vote in votes if vote["item_id"] == "2026-09-15-c1"} == {"unanimous"}
    assert {vote["member"]: (vote["vote"], vote["established"]) for vote in votes if vote["item_id"] == "2026-09-15-72"}["Chiesa"] == ("ABSENT", "named")
    # He left before 8.1, whose line says only "unan.": who voted is not said, so nobody's vote is written.
    last = agenda["2026-09-15-81"]
    assert (last["votes_read"], last["problem"], last["ayes"]) == (False, "unanimous, and the minutes have Chiesa away", 0)
    assert not [vote for vote in votes if vote["item_id"] == "2026-09-15-81"]
    assert json.loads(last["motion_log"])[0]["how"] == "unan."
    # Without the arrival, the calendar is not read either.
    agenda, votes, facts = read(MINUTES.replace("Chairman Chiesa arrived at 6:30 p.m.\n", "Recessed at 6:30 p.m.\n"))
    assert agenda["2026-09-15-c1"]["problem"] == "unanimous, and the minutes have Chiesa away"
    assert facts["motions_read"] == 2  # the two with counts, which name him or count him


def test_every_motion_in_votes_has_one_row_for_each_supervisor_and_a_short_roll_gives_none():
    _, votes, _ = read()
    per_motion = pd.DataFrame(votes).groupby(["item_id", "motion"])["member"].agg(["size", "nunique"])
    assert (per_motion["size"] == 5).all() and (per_motion["nunique"] == 5).all()
    assert set(pd.DataFrame(votes)["vote"]) == {"AYE", "NO", "ABSENT"}
    agenda, votes, facts = read(roll=ROLL[:4])
    assert votes == [] and facts["motions_read"] == 0
    assert {row["problem"] for row in agenda.values() if row["motions"]} == {"the minutes around this day name 4 supervisors for 5 seats"}


def test_two_motions_on_one_item_and_votes_taken_in_turn_stay_on_its_line():
    text = MINUTES.replace("Grewal/B. Condit unan. 8.1 Approved renewals to agreements – BHRS", """Chairman Chiesa returned at 10:01 p.m.

Withrow/C. Condit (2-3)(B. Condit, Chiesa and Grewal opposed) 8.1 The motion failed to continue the item

Grewal/B. Condit unan. 8.1 Approved renewals to agreements – BHRS

9. Amended the item to take two votes as follows:

First Vote: Grewal/Withrow unan. Elected Supervisor Chiesa as the Chairman

Second Vote: Chiesa/B. Condit (4-0)(Withrow abstained) Elected Supervisor Withrow as the Vice-Chairman""")
    agenda, votes, facts = read(text)
    item = agenda["2026-09-15-81"]
    assert (item["motions"], item["motions_read"], item["votes_read"]) == (2, 2, True)
    assert (item["action"], item["ayes"], item["result"]) == ("8.1 Approved renewals to agreements – BHRS", 5, "")
    log = json.loads(item["motion_log"])
    assert (log[0]["how"], log[0]["mover"]) == ("(2-3)(B. Condit, Chiesa and Grewal opposed)", "Withrow")
    first = [vote for vote in votes if vote["item_id"] == "2026-09-15-81" and vote["motion"] == 1]
    assert sorted(vote["member"] for vote in first if vote["vote"] == "NO") == ["B. Condit", "Chiesa", "Grewal"]
    chair = agenda["2026-09-15-9"]
    assert (chair["agenda_number"], chair["motions"], chair["motions_read"], chair["not_voting"]) == ("9.", 2, 2, 1)
    assert facts["motions"] == 8


def test_a_closed_session_vote_and_initials_for_the_movers_are_motions_too():
    text = MINUTES.replace("Grewal/B. Condit unan. 8.1 Approved renewals to agreements – BHRS",
                           "Closed Session Announcement: Chairman Chiesa/Withrow (4-0)(Chiesa absent) Appointed a director\n\nG/W (4-0)(Chiesa absent) B9 Approved the hours")
    agenda, _, facts = read(text)
    announced = [row for row in agenda.values() if row["action"] == "Appointed a director"][0]
    assert (announced["mover"], announced["seconder"], announced["votes_read"]) == ("Chiesa", "Withrow", True)
    assert (agenda["2026-09-15-B9"]["mover"], agenda["2026-09-15-B9"]["seconder"]) == ("Grewal", "Withrow")
    assert facts["motions_read"] == facts["motions"] == 6


def test_a_recusal_told_apart_from_the_vote_stops_a_bare_unanimous_on_that_item():
    text = MINUTES.replace("Chairman Chiesa left the meeting at 9:56 p.m.", "Supervisor Withrow recused himself from Item 8.1 due to a conflict.")
    text = text.replace("(4-0)(Chiesa absent) 7.2", "unan. 7.2")
    agenda, _, _ = read(text)
    assert agenda["2026-09-15-72"]["votes_read"] is True
    assert agenda["2026-09-15-81"]["problem"] == "unanimous, and the minutes have Withrow away"


def test_the_five_tables_come_out_in_the_one_shape(tmp_path):
    agenda_rows, vote_rows, facts = stan.read_meeting(MEETING, stan.scan(MINUTES), ROLL, pages=3)
    agenda, votes = stan.typed(pd.DataFrame(agenda_rows, columns=stan.AGENDA_COLUMNS), pd.DataFrame(vote_rows, columns=stan.VOTE_COLUMNS))
    meetings = stan.meetings_table([{**MEETING, "time": "6:30 p.m.", "note": "", "agenda": "", "minutes": MEETING["minutes_url"], "video": ""}])
    for name, value in facts.items():
        meetings[name] = [value]
    tables = council_tables.standard({"items": stan.items_table(agenda, meetings), "meetings": meetings, "agenda_items": agenda,
                                      "votes": votes, "members": stan.members_table(votes, meetings)})
    for name in council_tables.TABLES:
        assert list(tables[name].columns)[:len(council_tables.COLUMNS[name])] == council_tables.COLUMNS[name]
    items = tables["items"].set_index("matter_id")
    assert len(items) == 8 and "2026-09-15-c1" not in items.index  # the calendar is not an item
    assert (items.loc["2026-09-15-6B1", "action_on"], items.loc["2026-09-15-6B1", "ayes"], items.loc["2026-09-15-6B1", "mover"]) == ("section", 5, "Grewal")
    assert (items.loc["2026-09-15-71", "action_on"], items.loc["2026-09-15-71", "noes"]) == ("item", 1)
    assert items.loc["2026-09-15-81", "votes_read"] == False and pd.isna(items.loc["2026-09-15-11", "votes_read"])  # noqa: E712
    members = tables["members"].set_index("name")
    assert list(members.index) == ROLL and members["serving"].all() and (members["votes"] == 4).all()
    assert (members.loc["Chiesa", "role"], members.loc["Grewal", "role"]) == ("Chairman", "")
    assert set(tables["votes"]["established"]) == {"named", "count", "unanimous"}
    council_tables.write_tables(tables, tmp_path)
    assert sorted(path.name for path in tmp_path.glob("*.parquet")) == sorted(f"{name}.parquet" for name in council_tables.TABLES)
    card = stan.card(tables)
    assert not re.search(r"\{[a-z_]+\}", card) and "chrissoria/stanislaus-county-board" in card


def test_the_foot_of_a_page_and_the_hidden_copy_of_the_text_are_not_read():
    lines = stan.lines_of("Grewal/Withrow unan. 7.1 Accepted\n\n    6.A.1 Approved\n3\n\f2026-0412 and more\n")
    assert [(line["indent"], line["text"], line["gap"], line["top"]) for line in lines] == [
        (0, "Grewal/Withrow unan. 7.1 Accepted", False, True), (4, "6.A.1 Approved", True, False), (0, "2026-0412 and more", False, True)]


def test_a_refusal_stops_the_host_being_asked_again(monkeypatch):
    class Answer:
        status_code, headers, content, text = 403, {"content-type": "text/html"}, b"<html>", "<html>"

    asked = []
    monkeypatch.setattr(stan, "_refused", stan.threading.Event())
    monkeypatch.setattr(stan.requests, "get", lambda url, **said: asked.append(url) or Answer())
    with pytest.raises(stan.Refused):
        stan.fetch("https://example.test/a")
    with pytest.raises(stan.Refused):
        stan.fetch("https://example.test/b")
    assert asked == ["https://example.test/a"]
