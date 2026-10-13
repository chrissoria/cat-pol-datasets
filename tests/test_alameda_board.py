"""build_alameda_board reads the Alameda County Board's votes out of the two rows the minutes print in the margin, a vote whole or not at all."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import build_alameda_board as ala
import council_tables

# The text of the minutes as layout() writes it: a tab on each side of the middle column where a margin has something,
# and two spaces where the page has a wide gap.
HEAD = """SUMMARY ACTION MINUTES
BOARD OF SUPERVISORS
9:30 AM
Regular Meeting  Tuesday, September 22, 2026
COUNTY ADMINISTRATION BUILDING  DAVID HAUBERT, PRESIDENT  DISTRICT 1
SUPERVISORS’ CHAMBERS  ELISA MÁRQUEZ  DISTRICT 2
1221 OAK STREET  LENA TAM, VICE- PRESIDENT  DISTRICT 3
FIFTH FLOOR, ROOM 512  NATE MILEY  DISTRICT 4
OAKLAND, CALIFORNIA  NIKKI FORTUNATO BAS  DISTRICT 5
SUSAN S. MURANISHI  ANDREA WEDDLE
COUNTY ADMINISTRATOR  INTERIM COUNTY COUNSEL
MISSION
TO ENRICH THE LIVES OF ALAMEDA COUNTY RESIDENTS
CALL TO ORDER AND SALUTE TO FLAG
The Board of Supervisors Regular Meeting convened at 9:42 A.M. with President Haubert presiding.
"""
FOOT = """ADJOURNED
The Board of Supervisors Meeting adjourned at 4:51 P.M.
REVIEWED BY:
CLERK, BOARD OF SUPERVISORS
** KEY **
Left Margin Notes  Right Margin Notes
1  President Haubert  A  Abstained  C  Contract
2  Supervisor Márquez  X  Excused  O  Ordinance
3  Supervisor Tam  N  No  R  Resolution
4  Supervisor Miley  BO  Board Order  LIB  Library
5  Supervisor Fortunato Bas
File/Common Folder: 31647/31821
"""
SEATS = {1: "David Haubert", 2: "Elisa Márquez", 3: "Lena Tam", 4: "Nate Miley", 5: "Nikki Fortunato Bas"}
ROLL = [{"name": name, "district": number, "role": {1: "President", 3: "Vice President"}.get(number, "")} for number, name in SEATS.items()]

# A calendar voted on in words, the consent calendar, a divided vote, two votes on one item (the second with only its
# letters printed), an item with no vote, and after a page's end an item a supervisor stood aside from.
MINUTES = HEAD + """REGULAR CALENDAR
A motion was made by Supervisor Tam, seconded by Supervisor Márquez to approve the Regular
Calendar. The motion passed with 5 Ayes: Supervisors Fortunato Bas, Márquez, Miley, Tam and President
Haubert.
32451/32X51\t1.CONSENT CALENDAR (See Item Numbers 6 - 6)\t
PUBLIC ASSISTANCE
2. Social Services Agency - Approve a Standard Services Agreement (Procurement Contract No. 30447) with
Lao Family Community Development (Principal: Kathy Chao Rothberg; Location: Oakland)
-CAO Recommends: Approve
Attachment 2
32451/32X51\tApproved as recommended\tFILE 31857
\t\tC-30447
GENERAL ADMINISTRATION
3. Registrar of Voters - Adopt a Resolution on the listing of proponents of local measures
Attachment 3
15432/154NX\tApproved as recommended\tFILE 31193
\t\tR-2024-212
4. Sheriff - Hold a public hearing and first reading and introduction of an Ordinance modifying the fee
schedule in the Sheriff's Office Crime Laboratory
Attachment 4
31245/312XX\tOpened public hearing; Closed public hearing; and\t
32451/..XX.\tContinued to Tuesday, 12/19/23 for second reading\t
5. Supervisor Miley - Informational Report on 2000 San Pablo Avenue
Attachment 5
The report was presented by the developer
MINUTES - BOARD OF SUPERVISORS' MEETING, TUESDAY, SEPTEMBER 22, 2026 - PAGE 4SUMMARY ACTION MINUTES
\f6. President Haubert - Approve the use of $100,000 to support United Seniors of Oakland
- (4/5 Vote)
Attachment 6
3251/3251\tSupervisor Miley recused himself from discussing or voting on this item because\tR-2026-361F
he presides as President of the United Seniors of Oakland and Alameda County.
A motion was made by Supervisor Tam, seconded by Supervisor Márquez, to
approve the item as recommended. The motion passed with 4 Ayes: Supervisor
Fortunato Bas, Márquez, Tam and President Haubert; 1 Recused: Supervisor
Miley
""" + FOOT
MEETING = {"meeting_id": "10484", "date": "2026-09-22", "minutes_url": "https://example.test/minutes.pdf"}


def read(monkeypatch, text, tmp_path):
    monkeypatch.setattr(ala, "text_of", lambda meeting, out_dir, fresh=False: text)
    agenda, votes, facts = ala.read_meeting(MEETING, tmp_path)
    return {row["item_id"]: row for row in agenda}, votes, facts


def cast_of(votes, item_id, motion=1):
    return {vote["member"]: vote["vote"] for vote in votes if vote["item_id"] == item_id and vote["motion"] == motion}


def set_in(text, left, base, size, wide=0.5):
    """Characters as layout() meets them: (character, left, right, baseline, size), each `wide` of its size across."""
    return [(char, left + index * wide * size, left + (index + 1) * wide * size - 0.3, base, size) for index, char in enumerate(text)]


def test_a_listing_row_gives_the_meeting_its_day_its_kind_and_where_its_documents_are():
    row = """<tr class="{}" onmouseover="x"><td class="listItem" headers="Name" id="Regular-Meeting" scope="row">
        {}</td><td class="listItem" headers="Date"><span style="display:none;">{}</span>{}</td>
        <td class="listItem"><a href="//alamedacounty.granicus.com/AgendaViewer.php?view_id=2&clip_id={}">Agenda</a></td><td>{}</td>
        <td><a onclick="window.open('//alamedacounty.granicus.com/MediaPlayer.php?view_id=2&clip_id={}')">Video</a></td></tr>"""
    minutes = '<a href="//alamedacounty.granicus.com/MinutesViewer.php?view_id=2&clip_id=10484&doc_id=b68f410c-c28b-11f1">Minutes</a>'
    page = ('<h3>Upcoming Events</h3>' + row.format("odd", "Elections Commission", 1, "Oct 14, 2026", 1, "", 1)
            + '<h3><a name=""></a>BOS Regular Meetings</h3>' + row.format("even", "Regular Meeting", 1791270000, "Oct&nbsp;&nbsp;6, 2026", 10503, "&nbsp;", 10503)
            + row.format("odd", "Regular Meeting", 1790060400, "Sep 22, 2026", 10484, minutes, 10484)
            + '<h3><a name=""></a>BOS Committee Meetings</h3>' + row.format("odd", "Health Committee", 1, "Sep 21, 2026", 10480, "", 10480))
    meetings = ala.meetings_table(ala.rows_of(page)).set_index("meeting_id")
    assert list(meetings.index) == ["10484", "10503"]  # the Board's own meetings: not its committees', nor those to come
    held = meetings.loc["10484"]
    assert (held["date"], held["body"], held["name"], held["kind"]) == ("2026-09-22", "Board of Supervisors", "Regular Meeting", "BOS Regular Meetings")
    assert held["minutes_url"] == ala.HOST + "/MinutesViewer.php?view_id=2&clip_id=10484&doc_id=b68f410c-c28b-11f1"
    assert held["agenda_url"] == ala.HOST + "/AgendaViewer.php?view_id=2&clip_id=10484" and "MediaPlayer" in held["url"]
    assert (meetings.loc["10503", "date"], meetings.loc["10503", "minutes_url"]) == ("2026-10-06", "")


def test_the_two_rows_of_a_vote_are_set_one_under_the_other_by_where_their_characters_stand():
    # Letters alone under the third and fourth numbers, in smaller type and nearer than the pitch; the action beside
    # the first row, the file number in the right margin, and small type across the page that is not the margin's.
    chars = (set_in("32451", 55, 500, 8.2) + set_in("XX", 55 + 2 * 4.1, 493, 6, 0.7) + set_in("Continued to Tuesday", 85, 497.5, 11.3)
             + set_in("FILE 31857", 475, 497.5, 11.3) + set_in("Pursuant to Board Policy signs are prohibited", 55, 700, 9))
    rows, rest = ala.margin_rows(chars)
    assert ["".join(char[0] for char in row) for _, row in rows] == ["32451", "XX"]
    lines = ala.page_lines(rest, rows, ala.pitch_of([rows]))
    assert ala.written(lines, None) == "Pursuant to Board Policy signs are prohibited\n32451/..XX.\tContinued to Tuesday\tFILE 31857"
    # What was done is set in from where the items' numbers stand, and is written with a space before it.
    assert ala.written(lines, 55) == "Pursuant to Board Policy signs are prohibited\n32451/..XX.\t Continued to Tuesday\tFILE 31857"
    # Until 2020 the second row has the ayes in rising order, and the one excused stands apart at the end of both.
    older = set_in("2143", 55, 500, 8.2) + set_in("5", 73.8, 500, 8.2) + set_in("1234", 54.7, 490.7, 8.2) + set_in("X", 70.9, 490.7, 6)
    rows, rest = ala.margin_rows(older)
    assert ala.margin_notes(rows, 9.5) == [(500, "21435/1234X")]
    # A second row with a character more than the first has numbers stands under nothing that can be told.
    rows, _ = ala.margin_rows(set_in("34512", 55, 500, 8.2) + set_in("1234X5", 55, 490.7, 8.2))
    assert ala.margin_notes(rows, 9.5) == [(500, "34512/?1234X5")]


def test_rows_the_page_does_not_pair_are_written_so_that_none_is_read():
    numbers = lambda text, base: set_in(text, 55, base, 8.2)
    rows, _ = ala.margin_rows(numbers("32451", 500) + numbers("32451", 490.7) + numbers("34251", 440) + numbers("12345", 300)
                              + numbers("12345", 290.7) + numbers("12345", 281.4))
    assert ala.pitch_of([rows]) == 9.5
    # Two at the pitch are a vote; one alone is a first row with no second; three in a run could be paired two ways.
    assert [text for _, text in ala.margin_notes(rows, 9.5)] == ["32451/32451", "34251", "?12345", "?12345", "?12345"]
    # A letter under a vote that already has its second row spoils it.
    rows, _ = ala.margin_rows(numbers("13452", 500) + numbers("1345X", 490.7) + set_in("x", 73, 484, 8.2))
    assert [text for _, text in ala.margin_notes(rows, 9.5)] == ["?13452?x"]
    # An item's number set a little above its title's line is put back on it.
    page = [ala.page_lines(set_in("20.", 55, 710.8, 11.3) + set_in("General Services Agency", 87, 703.8, 11.3)
                           + set_in("COVID-19 response", 87, 690, 11.3) + set_in("PUBLIC PROTECTION", 54, 600, 12), [], None)]
    assert ala.edge_of(page) == 55
    assert ala.written(page[0], ala.edge_of(page)) == "20. General Services Agency\n COVID-19 response\nPUBLIC PROTECTION"


def test_the_roll_is_the_key_at_the_foot_held_to_the_names_at_the_head():
    roll, seats, why = ala.roll_of(ala.lines_of(HEAD + FOOT))
    assert (roll, seats, why) == (ROLL, SEATS, "")
    # The district column of the head sometimes sits a line off; the key's numbers are what is used.
    shifted = HEAD.replace("DAVID HAUBERT, PRESIDENT  DISTRICT 1", "DAVID HAUBERT, PRESIDENT").replace(
        "ELISA MÁRQUEZ  DISTRICT 2", "ELISA MÁRQUEZ  DISTRICT 1")
    assert ala.roll_of(ala.lines_of(shifted + FOOT))[1] == SEATS
    # The head has the name without its accent in some minutes; the surname is written as the key writes it.
    assert ala.roll_of(ala.lines_of(HEAD.replace("MÁRQUEZ", "MARQUEZ") + FOOT))[1][2] == "Elisa Márquez"
    # An empty seat is in the key with no name, and the Board is four.
    vacant = ala.roll_of(ala.lines_of(HEAD.replace("ELISA MÁRQUEZ  DISTRICT 2", "DISTRICT 2") + FOOT.replace("Supervisor Márquez", "Supervisor of District 2")))
    assert (sorted(vacant[1]), vacant[2]) == ([1, 3, 4, 5], "")
    # The dots and colons of the planning meetings' key.
    dotted = FOOT.replace("1  President", "1. President").replace("2  Supervisor", "2. Supervisor").replace("A  Abstained", "A:  Abstained")
    assert ala.roll_of(ala.lines_of(HEAD + dotted))[1] == SEATS


@pytest.mark.parametrize("foot, why", [
    (FOOT.replace("Supervisor Fortunato Bas", "Supervisor Carson"), "the key gives 5 to Carson, who is not at the head of the minutes"),
    (FOOT.replace("2  Supervisor Márquez", "2  Supervisor Tam").replace("3  Supervisor Tam", "3  Supervisor Márquez"),
     "the key gives 3 to Márquez, whom the head of the minutes lists out of that order"),
    (FOOT.split("** KEY **")[0], "no key in the minutes"),
    (FOOT.replace("X  Excused", ""), "the key does not give five numbers and the letters"),
    (FOOT.replace("4  Supervisor Miley", "Supervisor Miley"), "the key does not give five numbers and the letters"),
])
def test_a_key_that_does_not_fit_its_minutes_gives_no_numbers(foot, why):
    roll, seats, problem = ala.roll_of(ala.lines_of(HEAD + foot))
    assert (seats, problem) == ({}, why)
    # Those at the head with an office or a district beside them are still the roll, for a vote said in words.
    assert [member["name"] for member in roll] == ["David Haubert", "Elisa Márquez", "Lena Tam", "Nate Miley", "Nikki Fortunato Bas"]
    assert ala.read_margin("32451/32451", seats)[:2] == (None, "no key to read the margin by")


def test_the_margin_gives_each_number_its_supervisor_and_each_letter_its_word():
    cast, problem, mover, seconder = ala.read_margin("15432/154NX", SEATS)
    assert (problem, mover, seconder) == ("", "David Haubert", "Nikki Fortunato Bas")
    assert cast == {"David Haubert": "AYE", "Nikki Fortunato Bas": "AYE", "Nate Miley": "AYE", "Lena Tam": "NO", "Elisa Márquez": "EXCUSED"}
    assert set(ala.MARKS.values()) == {"ABSTAIN", "EXCUSED", "NO"} and council_tables.vote_word("No") == "NO"
    # The ayes in rising order with the letters at the end, as until 2020; the letters alone; a small x.
    assert ala.read_margin("21435/1234X", SEATS)[0]["Nikki Fortunato Bas"] == "EXCUSED"
    assert ala.read_margin("32451/..XX.", SEATS)[0] == {"Lena Tam": "AYE", "Elisa Márquez": "AYE", "Nate Miley": "EXCUSED",
                                                        "Nikki Fortunato Bas": "EXCUSED", "David Haubert": "AYE"}
    assert ala.read_margin("14235/14n3a", SEATS)[0] == {"David Haubert": "AYE", "Nate Miley": "AYE", "Elisa Márquez": "NO", "Lena Tam": "AYE",
                                                        "Nikki Fortunato Bas": "ABSTAIN"}
    # A row that leaves a supervisor out says what it says, and says who is missing.
    cast, problem, _, _ = ala.read_margin("3251/3251", SEATS)
    assert (len(cast), problem) == (4, "4 not in the margin")


@pytest.mark.parametrize("code, why", [
    ("32451", "one row in the margin and no second"),
    ("13452/1234X", "the numbers of the second row are not those left unmarked in the first: 13452/1234X"),  # 2 marked, and 2 among the ayes
    ("34512/?1234X5", "the second row does not stand under the first: 34512/?1234X5"),
    ("32451/3245", "the second row does not stand under the first: 32451/3245"),
    ("32451/.....", "nothing in the second row: 32451/....."),
    ("32451/32.51", "the numbers of the second row are not those left unmarked in the first: 32451/32.51"),
    ("32251/32251", "not supervisors' numbers: 32251/32251"),
    ("?12345", "not supervisors' numbers: ?12345"),
    ("X", "not supervisors' numbers: X"),
])
def test_a_margin_that_does_not_read_cleanly_is_not_read_at_all(code, why):
    assert ala.read_margin(code, SEATS)[:2] == (None, why)


def test_a_vote_said_in_words_is_read_when_everyone_is_named_once():
    said = ala.read_words("The motion passed with a vote of 3 Ayes: Supervisors Miley, Tam, and President Haubert; 2 Noes: "
                          "Supervisors Fortunato Bas and Márquez 24 people spoke on this item", ROLL)
    assert len(said) == 1 and said[0]["problem"] == "" and said[0]["result"] == "Pass"
    assert said[0]["cast"] == {"Nate Miley": "AYE", "Lena Tam": "AYE", "David Haubert": "AYE", "Nikki Fortunato Bas": "NO", "Elisa Márquez": "NO"}
    # Words run together as the PDF has them, and the other words the minutes use.
    glued = ala.read_words("The motion passed with 3Ayes: Supervisors Fortunato Bas, Marquez and Tam; 1 Abstained: Supervisor Miley; 1 No: PresidentHaubert", ROLL)
    assert glued[0]["cast"] == {"Nikki Fortunato Bas": "AYE", "Elisa Márquez": "AYE", "Lena Tam": "AYE", "Nate Miley": "ABSTAIN", "David Haubert": "NO"}
    assert ala.read_words("The motion passed unanimously with 5 Ayes.", ROLL)[0]["cast"] == {name: "AYE" for name in SEATS.values()}
    assert ala.read_words("Approved as recommended", ROLL) == []
    # Not whole: a count that is not the number named, a supervisor nobody on the roll, one left out, nobody named of four.
    why = lambda text, roll=ROLL: ala.read_words(text, roll)[0]["problem"]
    assert why("The motion passed with 5 Ayes: Supervisors Fortunato Bas, Márquez, Miley and President Haubert") == "the words say 5 AYE and name 4"
    assert why("The motion passed with 4 Ayes: Supervisors Carson, Márquez, Miley and Tam; 1 Excused: President Haubert") == "the words say 4 AYE and name 0"
    assert why("The motion passed with 4 Ayes: Supervisors Fortunato Bas, Márquez, Miley and Tam") == "the words name 4 of 5 supervisors"
    assert why("The motion passed with 4 Ayes.", ROLL[:4]) == "the words say 4 AYE and name 0"
    assert ala.moved_in("A motion was made by Supervisor Tam, seconded by Supervisor Fortunato Bas to approve", ROLL) == ("Lena Tam", "Nikki Fortunato Bas")


def test_where_the_margin_and_the_words_both_speak_they_must_say_the_same():
    words = "A motion was made by President Haubert, seconded by Supervisor Tam to approve the item. The motion passed with 4 Ayes: " \
            "Supervisor Fortunato Bas, Miley, Tam and President Haubert; 1 Excused: Supervisor Márquez"
    both = ala.decide("13245/13X45", words, ROLL, SEATS, "")
    assert (both["read"], both["source"], both["cast"]["Elisa Márquez"], both["mover"], both["mover_from"], both["order"]) == \
        (True, "margin and words", "EXCUSED", "David Haubert", "words", "same")
    for margin in ("13245/1X245", "13245/13245"):  # the margin has Supervisor Tam excused, or nobody
        differs = ala.decide(margin, words, ROLL, SEATS, "")
        assert (differs["read"], differs["cast"], differs["problem"]) == (False, {}, "the margin and the words differ")
    # A margin that cannot be read says nothing, and the words stand alone.
    assert ala.decide("13245/1X345", words, ROLL, SEATS, "")["source"] == "words"
    # One row in the margin says nothing of the vote; the words beside it do.
    assert (lambda motion: (motion["read"], motion["source"]))(ala.decide("13245", words, ROLL, SEATS, "")) == (True, "words")
    # With no key the margin is not read, and the words are.
    assert ala.decide("13245/13X45", words, ROLL, {}, "no key in the minutes")["source"] == "words"
    assert ala.decide("13245/13X45", "Approved as recommended", ROLL, {}, "no key in the minutes")["problem"] == "no key in the minutes"
    # Who moved is taken from the margin where the words do not say, and marked as such.
    margin = ala.decide("32451/32X51", "Approved as recommended", ROLL, SEATS, "")
    assert (margin["read"], margin["source"], margin["mover"], margin["seconder"], margin["mover_from"]) == (True, "margin", "Lena Tam", "Elisa Márquez", "margin")
    assert ala.decide("", "Presented", ROLL, SEATS, "")["block"] is False


def test_a_supervisor_left_out_of_the_margin_is_recused_only_if_the_words_say_so():
    stood_aside = ala.decide("1325/1325", "President Miley recused himself from discussing or voting on the item and left the room; approved as recommended",
                             ROLL, SEATS, "")
    assert (stood_aside["read"], stood_aside["source"], stood_aside["cast"]["Nate Miley"]) == (True, "margin, recusal in words", "RECUSED")
    assert sum(word == "AYE" for word in stood_aside["cast"].values()) == 4
    two = ala.decide("235/235", "Supervisor Haubert and President Miley recused themselves, left the room, and did not participate", ROLL, SEATS, "")
    assert {name for name, word in two["cast"].items() if word == "RECUSED"} == {"David Haubert", "Nate Miley"}
    # The words name another supervisor than the one the margin leaves out, or nobody.
    assert ala.decide("1325/1325", "Supervisor Tam recused herself from voting on the item", ROLL, SEATS, "")["problem"] == "4 not in the margin"
    assert ala.decide("1325/1325", "Approved as recommended", ROLL, SEATS, "")["problem"] == "4 not in the margin"


def test_the_minutes_are_read_into_items_and_the_votes_on_each_motion(monkeypatch, tmp_path):
    agenda, votes, facts = read(monkeypatch, MINUTES, tmp_path)
    assert list(agenda) == ["10484-u1", "10484-1", "10484-2", "10484-3", "10484-4", "10484-5", "10484-6"]
    assert (facts["minutes"], facts["key"], facts["pages"], facts["time"], facts["vote_blocks"], facts["blocks_read"]) == ("read", "read", 2, "9:30 AM", 7, 7)
    # The regular calendar has no number: it is kept under its heading, with the vote the words give.
    calendar = agenda["10484-u1"]
    assert (calendar["agenda_number"], calendar["title"], calendar["ayes"], calendar["result"], calendar["mover"], calendar["mover_from"]) == \
        ("", "REGULAR CALENDAR", 5, "Pass", "Lena Tam", "words")
    assert agenda["10484-1"]["title"] == "CONSENT CALENDAR (See Item Numbers 6 - 6)" and cast_of(votes, "10484-1")["Nate Miley"] == "EXCUSED"
    item = agenda["10484-2"]
    assert item["title"].startswith("Social Services Agency - Approve a Standard Services Agreement") and item["title"].endswith("-CAO Recommends: Approve")
    assert (item["action"], item["section"], item["notes"], item["doc_type"]) == ("Approved as recommended", "PUBLIC ASSISTANCE", "FILE 31857; C-30447", "other")
    assert (item["ayes"], item["noes"], item["not_voting"], item["votes_read"], item["mover"], item["seconder"]) == (4, 0, 1, True, "Lena Tam", "Elisa Márquez")
    divided = agenda["10484-3"]
    assert (divided["ayes"], divided["noes"], divided["not_voting"], divided["number"], divided["doc_type"], divided["section"]) == \
        (3, 1, 1, "R-2024-212", "resolution", "GENERAL ADMINISTRATION")
    assert cast_of(votes, "10484-3") == {"David Haubert": "AYE", "Nikki Fortunato Bas": "AYE", "Nate Miley": "AYE", "Lena Tam": "NO", "Elisa Márquez": "EXCUSED"}
    # Two votes on one item: each is a motion, and the item carries the last.
    hearing = agenda["10484-4"]
    assert (hearing["motions"], hearing["vote_blocks"], hearing["blocks_read"], hearing["action"]) == (2, 2, 2, "Continued to Tuesday, 12/19/23 for second reading")
    assert cast_of(votes, "10484-4", 1) == cast_of(votes, "10484-4", 2) and cast_of(votes, "10484-4", 2)["Nikki Fortunato Bas"] == "EXCUSED"
    assert {vote["motion_text"] for vote in votes if vote["item_id"] == "10484-4"} == {"Opened public hearing; Closed public hearing; and", hearing["action"]}
    # An item with no vote has what was said of it and no votes; whether its votes were read is not a question.
    assert (agenda["10484-5"]["action"], agenda["10484-5"]["vote_blocks"], agenda["10484-5"]["votes_read"]) == ("The report was presented by the developer", 0, None)
    # Over the page's end: a supervisor who stood aside, by the margin, by the words beside it and by the vote in words.
    aside = agenda["10484-6"]
    assert (aside["ayes"], aside["not_voting"], aside["result"], aside["number"]) == (4, 1, "Pass", "R-2026-361F")
    assert cast_of(votes, "10484-6")["Nate Miley"] == "RECUSED" and {vote["source"] for vote in votes if vote["item_id"] == "10484-6"} == {"margin and words"}
    assert {vote["district"] for vote in votes if vote["member"] == "Nikki Fortunato Bas"} == {5} and len(votes) == 35


def test_a_motion_whose_vote_cannot_be_read_is_kept_with_no_votes_and_says_why(monkeypatch, tmp_path):
    text = MINUTES.replace("15432/154NX", "15432")  # the second row lost
    agenda, votes, facts = read(monkeypatch, text, tmp_path)
    unread = agenda["10484-3"]
    assert (unread["action"], unread["vote_blocks"], unread["blocks_read"], unread["votes_read"]) == ("Approved as recommended", 1, 0, False)
    assert (unread["ayes"], unread["noes"], unread["not_voting"], unread["problem"]) == (0, 0, 0, "one row in the margin and no second")
    assert not cast_of(votes, "10484-3") and len(votes) == 30 and (facts["vote_blocks"], facts["blocks_read"]) == (7, 6)
    assert '"read":false' in unread["motion_log"] and '"margin":"15432"' in unread["motion_log"]
    # Minutes with the key of another Board: nothing in the margin is read, and the votes said in words still are.
    stale, votes, facts = read(monkeypatch, MINUTES.replace("5  Supervisor Fortunato Bas", "5  Supervisor Carson"), tmp_path)
    assert facts["key"] == "the key gives 5 to Carson, who is not at the head of the minutes" and (facts["vote_blocks"], facts["blocks_read"]) == (7, 2)
    assert stale["10484-2"]["problem"] == facts["key"] and {vote["item_id"] for vote in votes} == {"10484-u1", "10484-6"}


def test_a_heading_is_capitals_at_the_left_edge_and_capitals_set_in_are_not(monkeypatch, tmp_path):
    text = HEAD + """32451/32X51\t APPROVED MINUTES\t
 REGULAR MEETING: TUESDAY, SEPTEMBER 8, 2026
SITTING AS THE BOARD OF DIRECTORS
(ANY BOARD MEMBER MAY PULL ANY ITEM)
HEALTH CARE SERVICES
1. Alameda County Health - Approve an agreement to provide lab processing services for
 COVID-19
 Attachment 1
32451/32X51\t Approved as recommended\tC-23807
2. Supervisor Miley - Informational Report
 Attachment 2
 PRESENTED
PUBLIC PROTECTION
3. Sheriff - Accept the Annual Report
 Attachment 3
32451/32X51\t\t
""" + FOOT
    agenda, votes, facts = read(monkeypatch, text, tmp_path)
    assert [(row["agenda_number"], row["title"], row["action"], row["section"], row["blocks_read"]) for row in agenda.values()] == [
        # Capitals set in, with a vote beside them and no item above: a matter of its own.
        ("", "APPROVED MINUTES", "REGULAR MEETING: TUESDAY, SEPTEMBER 8, 2026", "", 1),
        # The rest of a title in capitals is the title's; the heading above is two lines, the second in brackets.
        ("1", "Alameda County Health - Approve an agreement to provide lab processing services for COVID-19", "Approved as recommended",
         "HEALTH CARE SERVICES", 1),
        # What was done, in capitals, is not a heading; the heading after it is.
        ("2", "Supervisor Miley - Informational Report", "PRESENTED", "HEALTH CARE SERVICES", 0),
        ("3", "Sheriff - Accept the Annual Report", "", "PUBLIC PROTECTION", 1)]
    assert len(votes) == 15


def test_until_july_2014_the_numbers_are_in_the_line_of_text_and_are_not_read(monkeypatch, tmp_path):
    text = HEAD + """1. CONSENT CALENDAR (See Appendix, Item Numbers 28 - 41)
12345 Approved as recommended
2. Public Health Department - Approve and authorize the Auditor-Controller to pay a $2,000 stipend
Attachment 2
\t3125 4 Approved as recommended\tFILE 29118
X
""" + FOOT
    agenda, votes, facts = read(monkeypatch, text, tmp_path)
    assert [(row["agenda_number"], row["action"], row["vote_blocks"], row["problem"]) for row in agenda.values()] == [
        ("1", "Approved as recommended", 1, "one row in the margin and no second"),
        ("2", "Approved as recommended X", 1, "one row in the margin and no second")]
    assert votes == [] and (facts["vote_blocks"], facts["blocks_read"]) == (2, 0)


def test_minutes_that_are_a_scan_or_something_else_are_counted_and_left(monkeypatch, tmp_path):
    agenda, votes, facts = read(monkeypatch, "\f\f \f", tmp_path)
    assert (agenda, votes, facts["minutes"], facts["pages"]) == ({}, [], "no text layer", 4)
    slides = "C o u n t y  o f  A l a m e d a\nB u d g e t  U p d a t e\n" * 20
    assert read(monkeypatch, slides, tmp_path)[2]["minutes"] == "other document"
    assert read(monkeypatch, HEAD + "\x16\x15\x17\x18\x14\x03" * 200, tmp_path)[2]["minutes"] == "text not legible"

    def not_a_pdf(meeting, out_dir, fresh=False):
        raise ala.NotPDF("the system sent a page in place of the minutes")

    monkeypatch.setattr(ala, "text_of", not_a_pdf)
    assert ala.read_meeting(MEETING, tmp_path)[2]["minutes"] == "not a PDF"


def test_a_refusal_is_not_asked_again(monkeypatch):
    asked = []

    class Answer:
        status_code, headers, content, text = 403, {"content-type": "text/html"}, b"<html>", "<html>"

    monkeypatch.setattr(ala.requests, "get", lambda url, **kwargs: asked.append(url) or Answer())
    try:
        with pytest.raises(ala.Refused):
            ala.fetch(ala.HOST + "/ViewPublisher.php?view_id=2")
        with pytest.raises(ala.Refused):
            ala.fetch(ala.HOST + "/ViewPublisher.php?view_id=2")
        assert len(asked) == 1
    finally:
        ala._refused.clear()


def test_a_run_reads_the_newest_first_skips_what_it_has_read_and_writes_the_five_tables(monkeypatch, tmp_path):
    rows = [{"meeting_id": str(number), "name": "Regular Meeting", "kind": "BOS Regular Meetings",
             "date": f"2024-01-{number:02d}" if number < 29 else f"2023-{number % 12 + 1:02d}-15",
             "agenda": True, "video": True, "doc": "abc" if number in (5, 6, 7) else ""} for number in range(1, 121)]
    read_now = []

    def text_of(meeting, out_dir, fresh=False):
        read_now.append(meeting["meeting_id"])
        if meeting["meeting_id"] == "5":
            raise ValueError("the connection was lost")
        # Minutes with no key have the name only in capitals, here without its accent.
        return MINUTES if meeting["meeting_id"] == "7" else (HEAD.replace("MÁRQUEZ", "MARQUEZ") + MINUTES[len(HEAD):]).split("** KEY **")[0]

    monkeypatch.setattr(ala, "listed", lambda: rows)
    monkeypatch.setattr(ala, "text_of", text_of)
    monkeypatch.setattr(council_tables, "published", lambda repo, name: None)
    monkeypatch.setattr(ala.county, "WORKERS", 1)
    tables, read = ala.build(True, False, tmp_path, limit=2)
    assert (read_now, read) == (["7", "6"], 2)
    tables, read = ala.build(True, False, tmp_path)
    assert (read_now, read) == (["7", "6", "5"], 0)  # the one that could not be fetched is asked for again, the others are not
    assert {name: list(table.columns[:len(council_tables.COLUMNS[name])]) for name, table in tables.items()} == council_tables.COLUMNS
    meetings = tables["meetings"].set_index("meeting_id")
    assert list(meetings.loc[["5", "6", "7", "8"], "minutes"]) == ["", "read", "read", ""]
    assert list(meetings.loc[["6", "7"], "key"]) == ["no key in the minutes", "read"]
    assert (meetings.loc["7", "items"], meetings.loc["7", "vote_blocks"], meetings.loc["7", "blocks_read"], meetings.loc["7", "time"]) == (7, 7, 7, "9:30 AM")
    assert (meetings.loc["6", "vote_blocks"], meetings.loc["6", "blocks_read"]) == (7, 2)  # with no key, only the votes said in words
    votes = tables["votes"]
    assert len(votes) == 45 and set(votes["vote"]) == {"AYE", "NO", "EXCUSED", "RECUSED"}
    assert set(votes["source"]) == {"margin", "words", "margin and words"}
    # One supervisor, one spelling: the one most of the minutes have.
    members = tables["members"].set_index("name")
    assert sorted(members.index) == sorted(SEATS.values())
    assert (members.loc["Lena Tam", "district"], members.loc["Lena Tam", "role"], members.loc["Elisa Márquez", "votes"]) == (3, "Vice President", 9)
    assert members["serving"].all() and set(members["first_vote"]) == {"2024-01-06"}
    items = tables["items"].set_index("matter_id")
    assert (items.loc["7-3", "ayes"], items.loc["7-3", "noes"], items.loc["7-3", "doc_type"], items.loc["7-3", "number"]) == (3, 1, "resolution", "R-2024-212")
    assert (items.loc["7-2", "subject"], items.loc["7-2", "url"], bool(items.loc["6-2", "votes_read"])) == (
        "PUBLIC ASSISTANCE", ala.HOST + "/MinutesViewer.php?view_id=2&clip_id=7&doc_id=abc", False)
    assert all((tmp_path / f"{name}.parquet").exists() for name in council_tables.TABLES)
    assert "{" not in ala.card(tables)  # every fact the card asks for was written in
