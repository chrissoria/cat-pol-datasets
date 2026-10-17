"""build_sd_county reads the County's agendas, votes and documents the way Legistar gives them."""

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import build_sd_county as sd


def paper(name, ending="docx"):
    return {"name": name, "url": f"https://sdcounty.legistar1.com/sdcounty/attachments/{name.lower().replace(' ', '-')}.{ending}"}


PAPERS = [paper("Agenda Information Sheet", "pdf"), paper("Board Letter"), paper("Ordinance Clean Copy"),
          paper("Approval Log", "pdf"), paper("10072026 ag05 Minute Order", "pdf"), paper("10072026 ag05 Speakers", "pdf")]


def test_an_item_is_an_ordinance_or_a_resolution_by_its_title():
    assert sd.doc_type_of("ORDINANCE AMENDING THE COMPENSATION ORDINANCE") == "ordinance"
    assert sd.doc_type_of("Adopt a Resolution Authorizing Participation in the Grant") == "resolution"
    # The County's old filter looked for "ordinance" first, and so does this.
    assert sd.doc_type_of("ADOPTING A REVISED RESOLUTION AND AMENDING THE ORDINANCE") == "ordinance"
    assert sd.doc_type_of("Non-Agenda Public Communication") == "other"


def test_the_document_of_an_ordinance_is_the_ordinance_and_of_anything_else_the_board_letter():
    assert sd.pick_document("ordinance", PAPERS).endswith("ordinance-clean-copy.docx")
    assert sd.pick_document("other", PAPERS).endswith("board-letter.docx")
    assert sd.pick_document("other", [PAPERS[0], PAPERS[3]]).endswith("agenda-information-sheet.pdf")
    assert sd.pick_document("other", [paper("Att A Notice of Public Hearing", "pdf"), paper("0915 D4 NRP BL Signed", "pdf")]).endswith("bl-signed.pdf")


def test_papers_about_the_meeting_are_never_the_document():
    assert sd.pick_document("other", PAPERS[3:]) == ""
    assert sd.pick_document("resolution", [paper("Speakers on the resolution", "pdf"), paper("Attachment A")]).endswith("attachment-a.docx")
    assert sd.pick_document("other", [{"name": "Video", "url": "https://example.org/watch"}]) == ""


def test_a_choice_already_made_is_kept_while_it_is_still_on_the_item():
    held = PAPERS[0]["url"]
    assert sd.pick_document("ordinance", PAPERS, held) == held
    assert sd.pick_document("ordinance", PAPERS, "https://sdcounty.legistar1.com/gone.pdf").endswith("ordinance-clean-copy.docx")


def docx(*paragraphs):
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p>{''.join(f'<w:r><w:t>{run}</w:t></w:r>' for run in runs)}</w:p>" for runs in paragraphs)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{w}"><w:body>{body}<w:p></w:p></w:body></w:document>')
    return out.getvalue()


def test_a_word_document_is_read_a_paragraph_at_a_time_without_python_docx():
    assert sd.docx_text(docx(["OVERVIEW"], ["Today’s action ", "adopts the plan."])) == "OVERVIEW\n\nToday’s action adopts the plan."


EVENT = {"EventId": 2037, "EventDate": "2026-09-15T00:00:00", "EventBodyName": "BOARD OF SUPERVISORS"}
ITEMS = [
    {"EventItemId": 1, "EventItemMatterId": None, "EventItemTitle": "Roll Call"},
    {"EventItemId": 35947, "EventItemMatterId": 8752, "EventItemMatterFile": "26-555", "EventItemAgendaNumber": "4.",
     "EventItemAgendaSequence": 11, "EventItemTitle": "Adopt the  Regional Fuel Contingency Plan",
     "EventItemActionName": "took action as recommended, on Consent", "EventItemPassedFlagName": "Pass",
     "EventItemActionText": "ON MOTION of Supervisor Montgomery Steppe, seconded by Supervisor Aguirre.",
     "EventItemMover": "Monica Montgomery Steppe", "EventItemSeconder": "Paloma Aguirre",
     "EventItemMatterAttachments": [{"MatterAttachmentName": "Board Letter", "MatterAttachmentHyperlink": PAPERS[1]["url"]}]},
    {"EventItemId": 35950, "EventItemMatterId": 8760, "EventItemMatterFile": "26-560", "EventItemAgendaNumber": "9.",
     "EventItemAgendaSequence": 20, "EventItemTitle": "Continued item", "EventItemActionName": None,
     "EventItemMatterAttachments": []},
]
VOTES = [{"VotePersonName": name, "VoteValueName": value} for name, value in
         [("Paloma Aguirre", "AYE"), ("Joel Anderson", "Noe"), ("Terra Lawson-Remer", "AYE"),
          ("Monica Montgomery Steppe", "AYE"), ("Jim Desmond", "Absent")]]


def test_a_meeting_gives_its_items_their_votes_and_their_papers(monkeypatch):
    asked = []

    def api(path, **params):
        asked.append(path)
        return ITEMS if path.endswith("eventitems") else VOTES

    monkeypatch.setattr(sd, "api", api)
    agenda, votes, papers = sd.read_meeting(EVENT)
    assert asked == ["events/2037/eventitems", "eventitems/35947/votes"]  # an item nothing was done to has no vote to ask for
    assert [row["matter_file"] for row in agenda] == ["26-555", "26-560"]  # the roll call is not an item
    acted = agenda[0]
    assert (acted["agenda_number"], acted["result"], acted["ayes"], acted["noes"], acted["not_voting"]) == ("4", "Pass", 3, 1, 1)
    assert acted["title"] == "Adopt the Regional Fuel Contingency Plan" and acted["date"] == "2026-09-15"
    assert [(vote["member"], vote["vote"]) for vote in votes][1] == ("Joel Anderson", "NO")
    assert papers == {"8752": [{"name": "Board Letter", "url": PAPERS[1]["url"]}], "8760": []}


def matter(key, title, modified="2026-09-16T21:00:00.1"):
    return {"MatterId": key, "MatterGuid": "G", "MatterFile": f"26-{key}", "MatterTitle": title, "MatterBodyName": "BOARD OF SUPERVISORS",
            "MatterStatusName": "Passed", "MatterTypeName": "Public Safety", "MatterIntroDate": "2026-09-01T00:00:00",
            "MatterAgendaDate": "2026-09-15T00:00:00", "MatterPassedDate": None, "MatterLastModifiedUtc": modified}


def test_an_item_keeps_the_text_already_read_and_takes_its_last_action_from_the_agenda(monkeypatch):
    monkeypatch.setattr(sd, "api", lambda path, **_: ITEMS if path.endswith("eventitems") else VOTES)
    agenda, _, papers = sd.read_meeting(EVENT)
    agenda = pd.DataFrame(agenda, columns=sd.AGENDA_COLUMNS)
    # What the dataset used to be: ten columns, the document's address and its text.
    old = pd.DataFrame([{"matter_id": "8752", "attachment_url": PAPERS[1]["url"], "text": "the board letter"},
                        {"matter_id": "8000", "attachment_url": "https://sdcounty.legistar1.com/old.pdf", "text": "an old ordinance"}])
    items = sd.items_table([matter(8752, "Adopt the Plan"), matter(8760, "ORDINANCE on fees"), matter(8000, "AN OLD ORDINANCE")],
                           agenda, papers, old).set_index("matter_id")
    plan = items.loc["8752"]
    assert plan["text"] == "the board letter" and plan["text_source"] == PAPERS[1]["url"]
    assert (plan["last_action"], plan["result"], plan["ayes"], plan["mover"]) == \
        ("took action as recommended, on Consent", "Pass", 3, "Monica Montgomery Steppe")
    assert plan["subject"] == "Public Safety" and plan["doc_type"] == "other" and plan["times_on_agenda"] == 1
    assert items.loc["8760", "text"] == "" and items.loc["8760", "last_action"] == ""
    # Not on an agenda read this time, and its papers were never listed: the old address and text stand.
    assert items.loc["8000", "text"] == "an old ordinance" and items.loc["8000", "attachment_url"].endswith("old.pdf")
    assert list(items.columns[:9]) == [c for c in sd.LEGACY_COLUMNS if c != "matter_id"]


def test_a_supervisor_is_given_the_district_the_source_leaves_out():
    records = [
        {"OfficeRecordFullName": "Jim Desmond", "OfficeRecordTitle": "Supervisor", "OfficeRecordBodyName": "BOARD OF SUPERVISORS",
         "OfficeRecordStartDate": "2023-01-02T00:00:00", "OfficeRecordEndDate": "2099-01-04T00:00:00", "OfficeRecordMemberType": "Member"},
        {"OfficeRecordFullName": "Greg Cox", "OfficeRecordTitle": "Supervisor", "OfficeRecordBodyName": "BOARD OF SUPERVISORS",
         "OfficeRecordStartDate": "2017-01-01T00:00:00", "OfficeRecordEndDate": "2020-12-31T00:00:00", "OfficeRecordMemberType": "Member"},
        {"OfficeRecordFullName": "A Clerk", "OfficeRecordTitle": "Clerk", "OfficeRecordBodyName": "BOARD OF SUPERVISORS",
         "OfficeRecordStartDate": "2017-01-01T00:00:00", "OfficeRecordEndDate": None, "OfficeRecordMemberType": "Staff"},
    ]
    votes = pd.DataFrame({"member": ["Jim Desmond", "Jim Desmond", "Someone Else"], "date": ["2019-01-08", "2026-10-07", "2020-01-01"]})
    table = sd.members_table(records, votes)
    assert list(table["name"]) == ["Greg Cox", "Jim Desmond"] and list(table["district"]) == [1, 5]
    assert list(table["serving"]) == [False, True]
    # The record holds his current term; his votes show he was there four years earlier.
    assert table.set_index("name").loc["Jim Desmond", ["first_vote", "last_vote", "votes"]].tolist() == ["2019-01-08", "2026-10-07", 2]
    assert table.set_index("name").loc["Greg Cox", "first_vote"] == ""


def test_pdfs_wait_when_pdfplumber_panics_on_import(monkeypatch):
    # A broken install once made `import pdfplumber` raise pyo3's PanicException, a BaseException: the run goes on.
    import builtins
    import build_sd_county
    class PanicException(BaseException):
        pass
    real = builtins.__import__
    def imported(name, *args, **kwargs):
        if name == "pdfplumber":
            raise PanicException("Python API call failed")
        return real(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", imported)
    assert build_sd_county.pdf_reader() is None


def test_a_dropped_proxy_connection_is_asked_again_and_a_refusal_is_not(monkeypatch):
    import requests
    import build_sd_county
    monkeypatch.setattr(build_sd_county.time, "sleep", lambda seconds: None)
    calls = []

    class Answer:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"ok": 1}]

    def dropped(url, **more):
        calls.append(url)
        if len(calls) == 1:
            raise requests.exceptions.ProxyError("Unable to connect to proxy', RemoteDisconnected('Remote end closed connection')")
        return Answer()

    monkeypatch.setattr(build_sd_county.requests, "get", dropped)
    assert build_sd_county.api("matters") == [{"ok": 1}] and len(calls) == 2
    calls.clear()

    def refused(url, **more):
        calls.append(url)
        raise requests.exceptions.ProxyError("Tunnel connection failed: 403 Forbidden")

    monkeypatch.setattr(build_sd_county.requests, "get", refused)
    try:
        build_sd_county.api("matters")
    except requests.exceptions.ProxyError:
        assert len(calls) == 1
    else:
        raise AssertionError("a refusal was asked again")
