"""build_legistar_pages_board reads a board's Legistar site page by page: the calendar, a meeting, and each line's action details."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import build_legistar_pages_board as board
import council_tables

KEY = "san-francisco-county"
GUID, FILE_GUID, ACT_GUID = ("6C51B642-6553-48DC-BB45-F122A6C7B355", "5A0E9A1C-5F4A-4CBF-A7A7-19F514E03BDF",
                             "B6785374-3980-4945-8D64-8342CF2BE1A6")


def heads(*names):
    return "<thead><tr>" + "".join(f'<th class="rgHeader"><a href="javascript:sort()">{name}</a></th>' for name in names) + "</tr></thead>"


# Pieces of the site's pages, cut down from ones read on 2026-10-13. The markup is the site's own.
def calendar_html(year="2019", body="Board of Supervisors", pager=""):
    return f"""<div id="ctl00_ContentPlaceHolder1_pageTop">
<input id="ctl00_ContentPlaceHolder1_lstYears_Input" type="text" value="{year}"/>
<input id="ctl00_ContentPlaceHolder1_lstBodies_Input" type="text" value="{body}"/>
<table id="ctl00_ContentPlaceHolder1_gridCalendar_ctl00">
{heads("Name", "Meeting Date", "", "Meeting Time", "Meeting Location", "Meeting Details", "Agenda", "Minutes")}
<tbody>{pager}
<tr class="rgRow" id="ctl00_ContentPlaceHolder1_gridCalendar_ctl00__0"><td><a><font>Board of Supervisors</font></a></td>
 <td>12/17/2019</td><td><a href="View.ashx?M=IC&amp;ID=750597&amp;GUID={GUID}"><img src="Images/ical.gif"/></a></td>
 <td><span><font>2:00 PM</font></span></td><td><font>Legislative Chamber, Room 250 City Hall<br/><em>Regular Meeting</em></font></td>
 <td><a href="MeetingDetail.aspx?ID=750597&amp;GUID={GUID}&amp;Options=info|&amp;Search=">Meeting&nbsp;details</a></td>
 <td><a href="View.ashx?M=A&amp;ID=750597&amp;GUID={GUID}">Agenda</a></td>
 <td><a href="View.ashx?M=M&amp;ID=750597&amp;GUID={GUID}">Minutes</a></td></tr>
<tr class="rgAltRow" id="ctl00_ContentPlaceHolder1_gridCalendar_ctl00__1"><td><a><font>Board of Supervisors</font></a></td>
 <td>12/24/2019</td><td></td><td></td><td><font>Meeting cancelled</font></td>
 <td><font>Meeting&nbsp;details</font></td><td><font>Not&nbsp;available</font></td><td><font>Not&nbsp;available</font></td></tr>
</tbody></table></div>"""


def line_html(row, file_id, file, version, name, kind, status, title, action, result, action_id):
    return f"""<tr class="rgRow" id="ctl00_ContentPlaceHolder1_gridMain_ctl00__{row}">
 <td><a href="LegislationDetail.aspx?ID={file_id}&amp;GUID={FILE_GUID}&amp;Options=&amp;Search="><font>{file}</font></a></td>
 <td>{version}</td><td> </td><td>{name}</td><td>{kind}</td><td>{status}</td><td>{title}</td><td>{action}</td><td>{result}</td>
 <td><a href="#" onclick="var obj = radopen('HistoryDetail.aspx?ID={action_id}&amp;GUID={ACT_GUID}', 'HistoryDetail'); return false;">Action&nbsp;details</a></td>
 <td><a class="historyVideoIndexNotAvailableLink">Not&nbsp;available</a></td></tr>"""


MEETING = f"""<div id="ctl00_ContentPlaceHolder1_pageDetails"><table id="ctl00_ContentPlaceHolder1_gridMain_ctl00">
{heads("File&nbsp;#", "Ver.", "Agenda&nbsp;#", "Name", "Type", "Status", "Title", "Action", "Result", "Action&nbsp;Details", "Video")}
<tbody>
{line_html(0, 4163332, "191013", 1, "Transportation Code - Mobility Device Permit Requirement", "Ordinance", "Passed",
           "Ordinance amending the Transportation Code to establish a violation.", "FINALLY PASSED", "Pass", 19128601)}
{line_html(1, 4280973, "191260", 2, "Planning Code, Zoning Map - Named Neighborhood Commercial Districts", "Ordinance", "Passed",
           "Ordinance amending the Planning Code.", "", "", 19157922)}
{line_html(2, 4291111, "191300", 1, "Urging Support for a Bill", "Resolution", "Filed", "Resolution urging support.", "TABLED", "Pass", 19160001)}
</tbody></table></div>"""


def action_html(file, action, votes, mover=""):
    rows = "".join(f"""<tr class="rgRow" id="ctl00_ContentPlaceHolder1_gridVote_ctl00__{at}">
 <td><a href="PersonDetail.aspx?ID=36815&amp;GUID={GUID}&amp;Search="><font>{name}</font></a></td><td><font>{word}</font></td></tr>"""
                   for at, (name, word) in enumerate(votes))
    return f"""<div id="ctl00_ContentPlaceHolder1_pageTop"><a id="ctl00_ContentPlaceHolder1_hypFile">{file}</a>
<span id="ctl00_ContentPlaceHolder1_lblMoverPrompt">Mover:</span><a id="ctl00_ContentPlaceHolder1_hypMover">{mover}</a>
<span id="ctl00_ContentPlaceHolder1_lblResult">Pass</span><span id="ctl00_ContentPlaceHolder1_lblAction">{action}</span>
<span id="ctl00_ContentPlaceHolder1_lblActionText">{action}</span>
<table id="ctl00_ContentPlaceHolder1_gridVote_ctl00">{heads("Person Name", "Vote")}<tbody>{rows}</tbody></table></div>"""


FINAL = action_html("191013", "FINALLY PASSED", [("Sandra Lee Fewer", "Aye"), ("Matt Haney", "No"), ("Norman Yee", "Excused")], "Aaron Peskin")
TABLED = action_html("191300", "TABLED", [])


def test_the_calendar_lists_a_years_meetings_and_leaves_out_one_with_no_page():
    rows = board.calendar_rows(KEY, calendar_html())
    assert len(rows) == 1  # the cancelled meeting has no page of its own
    assert rows[0] == {
        "meeting_id": "750597", "guid": GUID, "date": "2019-12-17", "time": "2:00 PM", "body": "Board of Supervisors",
        "location": "Legislative Chamber, Room 250 City Hall", "name": "Regular Meeting",
        "agenda_url": f"https://sfgov.legistar.com/View.ashx?M=A&ID=750597&GUID={GUID}",
        "minutes_url": f"https://sfgov.legistar.com/View.ashx?M=M&ID=750597&GUID={GUID}"}
    table = board.meetings_table(KEY, rows)
    assert list(table.columns) == board.MEETING_COLUMNS
    assert table.loc[0, "url"] == f"https://sfgov.legistar.com/MeetingDetail.aspx?ID=750597&GUID={GUID}"


def test_the_calendar_is_asked_by_the_sites_own_settings_and_must_show_what_was_asked(monkeypatch):
    asked = []

    def page(url, tries=4, settings=None):
        asked.append((url, settings))
        return calendar_html(year=str(settings["Setting-60-Calendar Year"]))

    monkeypatch.setattr(board, "fetch", page)
    assert len(board.listed_year(KEY, 2019)) == 1
    assert asked == [("https://sfgov.legistar.com/Calendar.aspx",
                      {"Setting-60-Calendar Year": 2019, "Setting-60-Calendar Body": 7374, "Setting-60-Calendar Options": "info|"})]
    # If the setting did not take, the page shows the month and every body: that is not the year asked for.
    monkeypatch.setattr(board, "fetch", lambda url, tries=4, settings=None: calendar_html(year="This Month", body="BOS and Committees"))
    with pytest.raises(RuntimeError, match="shows 'BOS and Committees' in 'This Month'"):
        board.listed_year(KEY, 2019)
    more = '<tr><td><div class="rgWrap rgInfoPart">Page <strong>1</strong> of <strong>3</strong>, items 1 to 100 of 220.</div></td></tr>'
    monkeypatch.setattr(board, "fetch", lambda url, tries=4, settings=None: calendar_html(pager=more))
    with pytest.raises(RuntimeError, match="second page"):
        board.listed_year(KEY, 2019)


def test_a_meetings_lines_and_a_lines_action_details():
    lines = board.lines_of(MEETING)
    assert [(line["matter_file"], line["matter_id"], line["item_id"], line["action"], line["result"]) for line in lines] == [
        ("191013", "4163332", "19128601", "FINALLY PASSED", "Pass"), ("191260", "4280973", "19157922", "", ""),
        ("191300", "4291111", "19160001", "TABLED", "Pass")]
    assert (lines[0]["guid"], lines[0]["matter_guid"], lines[0]["file_type"], lines[0]["version"]) == (ACT_GUID, FILE_GUID, "Ordinance", "1")
    assert lines[0]["subject"].startswith("Transportation Code") and lines[0]["title"].startswith("Ordinance amending")
    done = board.read_action(FINAL)
    assert (done["file"], done["action"], done["result"], done["mover"], done["seconder"]) == ("191013", "FINALLY PASSED", "Pass", "Aaron Peskin", "")
    assert done["votes"] == [("Sandra Lee Fewer", "AYE"), ("Matt Haney", "NO"), ("Norman Yee", "EXCUSED")]
    assert board.read_action(TABLED)["votes"] == []


def test_a_meeting_is_read_line_by_line_and_only_lines_acted_on_are_asked_for(monkeypatch):
    asked = []

    def page(url, tries=4, settings=None):
        asked.append(url.split("/")[-1].split("&")[0])
        return MEETING if "MeetingDetail" in url else FINAL if "19128601" in url else TABLED

    monkeypatch.setattr(board, "fetch", page)
    meeting = {"meeting_id": "750597", "guid": GUID, "date": "2019-12-17", "body": "Board of Supervisors"}
    agenda, votes = board.read_meeting(KEY, meeting)
    assert asked == ["MeetingDetail.aspx?ID=750597", "HistoryDetail.aspx?ID=19128601", "HistoryDetail.aspx?ID=19160001"]
    assert [(line["item_id"], line["sequence"], line["action"], line["ayes"], line["noes"], line["not_voting"], line["motions"]) for line in agenda] == [
        ("19128601", 1, "FINALLY PASSED", 1, 1, 1, 1), ("19157922", 2, "", 0, 0, 0, 0), ("19160001", 3, "TABLED", 0, 0, 0, 0)]
    assert (agenda[0]["mover"], agenda[0]["doc_type"], agenda[2]["doc_type"], agenda[0]["heading"]) == ("Aaron Peskin", "ordinance", "resolution", False)
    assert [(vote["item_id"], vote["member"], vote["vote"], vote["matter_file"], vote["motion"]) for vote in votes] == [
        ("19128601", "Sandra Lee Fewer", "AYE", "191013", 1), ("19128601", "Matt Haney", "NO", "191013", 1),
        ("19128601", "Norman Yee", "EXCUSED", "191013", 1)]
    assert set(agenda[0]) == set(board.AGENDA_COLUMNS) and set(votes[0]) == set(board.VOTE_COLUMNS)
    # Action details that are another file's are not put on this line.
    monkeypatch.setattr(board, "fetch", lambda url, tries=4, settings=None: MEETING if "MeetingDetail" in url else TABLED)
    with pytest.raises(RuntimeError, match="are those of 191300"):
        board.read_meeting(KEY, meeting)


def test_the_tables_made_from_what_was_read(monkeypatch):
    monkeypatch.setattr(board, "fetch", lambda url, tries=4, settings=None: MEETING if "MeetingDetail" in url else FINAL if "19128601" in url else TABLED)
    agenda, votes = board.read_meeting(KEY, {"meeting_id": "750597", "guid": GUID, "date": "2019-12-17", "body": "Board of Supervisors"})
    agenda, votes = pd.DataFrame(agenda, columns=board.AGENDA_COLUMNS), pd.DataFrame(votes, columns=board.VOTE_COLUMNS)
    items = board.items_table(KEY, agenda).set_index("matter_file")
    assert list(items.index) == ["191300", "191260", "191013"]
    assert items.loc["191013", ["last_action", "result", "ayes", "noes", "mover", "action_on"]].tolist() == ["FINALLY PASSED", "Pass", 1, 1, "Aaron Peskin", "item"]
    assert items.loc["191260", ["last_action", "action_on", "passed_date"]].tolist() == ["", "", ""]
    assert items.loc["191013", "url"] == f"https://sfgov.legistar.com/LegislationDetail.aspx?ID=4163332&GUID={FILE_GUID}"
    # Someone seen voting on one day only may be a clerk's slip; on two days they are a member.
    again = votes.assign(date="2020-01-07", item_id="2", meeting_id="9")
    members = board.members_table(pd.concat([votes, again[again["member"] != "Norman Yee"]]))
    assert members["name"].tolist() == ["Matt Haney", "Sandra Lee Fewer"] and members["serving"].tolist() == [False, False]
    assert members["district"].isna().all() and members["votes"].tolist() == [2, 2]
    tables = council_tables.standard({"items": items.reset_index(), "meetings": board.meetings_table(KEY, board.calendar_rows(KEY, calendar_html())),
                                      "agenda_items": agenda, "votes": votes, "members": members})
    assert set(tables) == set(council_tables.TABLES)


def test_every_board_has_what_the_reader_needs_and_its_tables_go_to_the_county_boards():
    for key, facts in board.BOARDS.items():
        assert facts["host"].endswith(".legistar.com") and facts["setting"] and facts["body_id"] and facts["first"] > 1990
        assert council_tables.board_of(board.repo_of(key)) == key
