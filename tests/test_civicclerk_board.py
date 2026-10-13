"""build_civicclerk_board reads a county board's meetings and votes from CivicClerk and puts them in the one shape."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import build_civicclerk_board as civic
import council_tables

KEY = "del-norte-county"


def motion(yes=(), no=(), abstain=(), words="Move to approve", by="A", second="B", flag=-1):
    return {"motionName": words, "initiatedBy": by, "secondedBy": second, "passFail": flag,
            "yesVotes": list(yes), "noVotes": list(no), "abstainVotes": list(abstain)}


def line(number, name, order, section=0, motions=(), children=(), **more):
    return {"id": number, "agendaObjectItemName": name, "sortOrder": order, "isSection": section,
            "minutesItemVotes": list(motions), "childItems": list(children), **more}


EVENT = {"id": 9, "agendaId": 40, "startDateTime": "2026-09-08T10:00:00Z", "categoryName": "Board of Supervisors "}
AGENDA = {"items": [
    # Out of order as the system may give them, and a tree: the consent agenda's vote is on its heading.
    line(3, "REGULAR ITEMS", 20, section=1, children=[
        line(31, "Adopt an &quot;Ordinance&quot; on <b>camping</b>", 21, agendaObjectItemNumber="2026-31", agendaObjectItemOutlineNumber="3.",
             ordinanceFormattedNumber="2026-004",
             # C's aye was entered twice, and the motion to continue failed before the one to adopt carried.
             motions=[motion(yes=["C"], no=["A", "B", "D"], words="Continue", flag=0),
                      motion(yes=["A", "B", "C", "C"], no=["D "], abstain=["E"], words="Adopt", flag=1)],
             attachmentsList=[{"id": 77, "fileName": "Ordinance", "isPublished": True, "isLink": False},
                              {"id": 78, "fileName": "Draft", "isPublished": False}]),
        line(32, "Receive a report", 22, agendaObjectItemNumber="2026-32"),
    ]),
    line(1, "CONSENT AGENDA", 10, section=1, motions=[motion(yes=["A", "B", "C", "D"])], children=[
        line(11, "Approve the minutes", 11, agendaObjectItemNumber="2026-11", agendaObjectItemOutlineNumber="1."),
        line(12, "Adopt a Resolution on roads", 12, agendaObjectItemNumber="2026-12", agendaObjectItemOutlineNumber="2."),
    ]),
]}


def read(monkeypatch):
    monkeypatch.setattr(civic, "fetch", lambda url, **params: AGENDA)
    agenda, votes = civic.read_meeting(KEY, EVENT)
    return pd.DataFrame(agenda, columns=civic.AGENDA_COLUMNS), pd.DataFrame(votes, columns=civic.VOTE_COLUMNS)


def test_an_agenda_is_read_in_order_with_each_line_under_its_heading(monkeypatch):
    agenda, _ = read(monkeypatch)
    assert list(agenda["item_id"]) == ["1", "11", "12", "3", "31", "32"]
    assert list(agenda["sequence"]) == [1, 2, 3, 4, 5, 6]
    assert list(agenda["heading"]) == [True, False, False, True, False, False]
    assert list(agenda["section"]) == ["", "CONSENT AGENDA", "CONSENT AGENDA", "", "REGULAR ITEMS", "REGULAR ITEMS"]
    assert list(agenda["matter_id"]) == ["", "11", "12", "", "31", "32"]  # a heading is not an item
    ordinance = agenda.set_index("item_id").loc["31"]
    assert ordinance["title"] == 'Adopt an "Ordinance" on camping' and ordinance["agenda_number"] == "3"
    assert (ordinance["doc_type"], ordinance["number"]) == ("ordinance", "2026-004")
    assert ordinance["attachments"] == ('[{"name":"Ordinance","url":"https://delnortecoca.api.civicclerk.com/v1/Meetings/'
                                        'GetAttachmentFile(fileId=77)"}]')
    assert agenda.set_index("item_id").loc["12", "doc_type"] == "resolution"
    assert set(agenda["body"]) == {"Board of Supervisors"} and set(agenda["date"]) == {"2026-09-08"}


def test_each_motion_has_its_votes_and_a_line_shows_its_last_motion(monkeypatch):
    agenda, votes = read(monkeypatch)
    cast = votes[votes["item_id"] == "31"]
    assert [(v.motion, v.member, v.vote) for v in cast.itertuples()] == [
        (1, "C", "AYE"), (1, "A", "NO"), (1, "B", "NO"), (1, "D", "NO"),
        (2, "A", "AYE"), (2, "B", "AYE"), (2, "C", "AYE"), (2, "D", "NO"), (2, "E", "ABSTAIN")]
    assert set(cast["motion_text"]) == {"Continue", "Adopt"} and set(cast["matter_file"]) == {"2026-31"}
    row = agenda.set_index("item_id").loc["31"]
    assert (row["action"], row["result"], row["ayes"], row["noes"], row["not_voting"], row["motions"]) == ("Adopt", "Pass", 3, 1, 1, 2)
    # The consent agenda's vote is on its heading and nowhere else. Its mark was left unset, so no result is claimed.
    consent = votes[votes["item_id"] == "1"]
    assert list(consent["member"]) == ["A", "B", "C", "D"] and set(consent["matter_id"]) == {""}
    heading = agenda.set_index("item_id").loc["1"]
    assert (heading["result"], heading["pass_flag"], heading["ayes"]) == ("", -1, 4)
    assert votes[votes["item_id"].isin(["11", "12", "32"])].empty


def test_a_result_is_the_clerks_mark_and_nothing_where_there_is_none(monkeypatch):
    lines = [line(1, "A", 1, motions=[motion(yes=["A"], no=["B", "C"], flag=0)]), line(2, "B", 2, motions=[motion(yes=["A", "B"], flag=-1)]),
             line(3, "C", 3, motions=[motion(yes=["A", "B"], flag=1)]), line(4, "D", 4)]
    monkeypatch.setattr(civic, "fetch", lambda url, **params: {"items": lines})
    agenda, _ = civic.read_meeting(KEY, EVENT)
    assert [row["result"] for row in agenda] == ["Fail", "", "Pass", ""]
    assert [row["pass_flag"] for row in agenda] == [0, -1, 1, None]


def test_an_item_carries_its_own_motion_or_failing_that_its_sections(monkeypatch):
    agenda, _ = read(monkeypatch)
    items = civic.items_table(KEY, agenda)
    assert list(items.columns[:20]) == council_tables.COLUMNS["items"]
    items = items.set_index("matter_id")
    assert set(items.index) == {"11", "12", "31", "32"}
    assert (items.loc["31", "action_on"], items.loc["31", "last_action"], items.loc["31", "passed_date"]) == ("item", "Adopt", "")
    assert (items.loc["11", "action_on"], items.loc["11", "ayes"], items.loc["11", "mover"]) == ("section", 4, "A")
    assert (items.loc["32", "action_on"], items.loc["32", "last_action"], items.loc["32", "ayes"]) == ("", "", 0)
    assert items.loc["12", "url"] == "https://delnortecoca.portal.civicclerk.com/event/9/files"


def test_a_meeting_has_its_time_place_and_files():
    events = [dict(EVENT, eventName="Board Chambers", eventLocation={"address1": "Flynn Center", "address2": "", "city": "Crescent City"},
                   publishedFiles=[{"type": "Agenda", "fileId": 760}, {"type": "Agenda Packet", "fileId": 762}, {"type": "Minutes", "fileId": 763}]),
              {"id": 10, "agendaId": 0, "startDateTime": "2026-12-08T13:30:00Z", "categoryName": "Planning Commission"}]
    meetings = civic.meetings_table(KEY, events).set_index("meeting_id")
    held = meetings.loc["9"]
    assert (held["date"], held["time"], held["body"], held["location"]) == ("2026-09-08", "10:00 AM", "Board of Supervisors", "Flynn Center, Crescent City")
    stream = "https://delnortecoca.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId={},plainText=false)"
    assert (held["agenda_url"], held["packet_url"], held["minutes_url"]) == (stream.format(760), stream.format(762), stream.format(763))
    assert (meetings.loc["10", "time"], meetings.loc["10", "agenda_id"], meetings.loc["10", "agenda_url"]) == ("1:30 PM", "", "")


def test_a_member_is_someone_seen_voting_at_the_board_on_more_than_one_day():
    def vote(member, meeting, date):
        return {"item_id": "1", "meeting_id": meeting, "date": date, "matter_id": "", "matter_file": "", "member": member,
                "vote": "AYE", "motion": 1, "motion_text": ""}
    today = pd.Timestamp.now(tz="UTC")
    near, far = (today - pd.Timedelta(days=10)).strftime("%Y-%m-%d"), (today - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    votes = pd.DataFrame([vote("A", "1", "2023-01-10"), vote("A", "2", near), vote("B", "1", "2023-01-10"), vote("B", "3", "2023-02-14"),
                          vote("Clerk", "1", "2023-01-10"),  # once, a slip
                          vote("Commissioner", "8", far), vote("Commissioner", "9", near)])  # another body's member
    meetings = pd.DataFrame({"meeting_id": ["1", "2", "3", "8", "9"],
                             "body": ["Board of Supervisors"] * 3 + ["Planning Commission"] * 2})
    members = civic.members_table(votes, meetings, {"Board of Supervisors"})
    assert list(members.columns) == council_tables.COLUMNS["members"]
    assert [(m.name, m.serving, m.first_vote, m.votes) for m in members.itertuples()] == [("A", True, "2023-01-10", 2), ("B", False, "2023-01-10", 2)]
    assert members["district"].isna().all() and set(members["start"]) == {""}


def test_a_run_reads_what_it_has_not_read_and_remembers_an_agenda_that_held_nothing(monkeypatch, tmp_path):
    old = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=400)).strftime("%Y-%m-%dT09:00:00Z")
    events = [dict(EVENT, id=number, agendaId=number + 100, startDateTime=old) for number in range(1, 12)]
    asked = []

    def fetch(url, **params):
        if url.endswith("/Events"):
            return {"value": events}
        asked.append(url.rsplit("/", 1)[1])
        return AGENDA if url.endswith("/101") else {"items": []}  # only the first has anything on its agenda

    monkeypatch.setattr(civic, "fetch", fetch)
    monkeypatch.setattr(council_tables, "published", lambda repo, name: None)
    tables, read = civic.build(KEY, True, False, tmp_path)
    assert read == 11 and len(asked) == 11
    assert tables["meetings"]["agenda_read"].all() and tables["meetings"].set_index("meeting_id").loc["1", "items"] == 4
    assert len(tables["votes"]) == 13 and len(tables["items"]) == 4
    for name in council_tables.TABLES:
        assert list(tables[name].columns[:len(council_tables.COLUMNS[name])]) == council_tables.COLUMNS[name]
    asked.clear()
    again, read = civic.build(KEY, True, False, tmp_path)
    assert read == 0 and asked == [] and len(again["votes"]) == 13


def test_the_card_has_the_countys_facts_written_in(monkeypatch, tmp_path):
    monkeypatch.setattr(civic, "fetch", lambda url, **params: {"value": [dict(EVENT, id=n, agendaId=n + 100) for n in range(1, 12)]}
                        if url.endswith("/Events") else AGENDA)
    monkeypatch.setattr(council_tables, "published", lambda repo, name: None)
    tables, _ = civic.build(KEY, True, False, tmp_path)
    text = civic.card(KEY, tables)
    assert "{" not in text.split("---", 2)[2].replace("{id}", "")
    assert "# Del Norte County Board of Supervisors" in text and "chrissoria/del-norte-county-board" in text
    assert "delnortecoca.api.civicclerk.com/v1" in text and "Votes by member are here from 2026-09-08 to 2026-09-08" in text
    tables["votes"] = tables["votes"].iloc[0:0]
    assert "does not enter votes in this system" in civic.card(KEY, tables)
