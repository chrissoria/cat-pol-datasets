"""parse_bill reads a GovInfo Bill Status file into the columns the map uses."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import build_congress_archive as archive

SAMPLE = b"""<?xml version="1.0" encoding="utf-8"?>
<billStatus><bill>
  <number>59</number><type>HJRES</type><congress>113</congress>
  <originChamber>House</originChamber><introducedDate>2013-09-10</introducedDate>
  <title>Continuing Appropriations Resolution, 2014</title>
  <actions>
    <item><actionDate>2013-12-26</actionDate><text>Became Public Law No: 113-67.</text><type>President</type>
      <actionCode>E40000</actionCode><sourceSystem><name>House floor actions</name></sourceSystem></item>
    <item><actionDate>2013-09-10</actionDate><text>Referred to the House Committee on Appropriations.</text>
      <type>IntroReferral</type><actionCode>H11100</actionCode><sourceSystem><name>House floor actions</name></sourceSystem>
      <committees><item><systemCode>hsap00</systemCode><name>Appropriations Committee</name></item></committees></item>
  </actions>
  <sponsors><item><bioguideId>R000395</bioguideId><fullName>Rep. Rogers, Harold [R-KY-5]</fullName>
    <party>R</party><state>KY</state></item></sponsors>
  <cosponsors><item><bioguideId>A000001</bioguideId></item><item><bioguideId>B000002</bioguideId></item></cosponsors>
  <laws><item><type>Public Law</type><number>113-67</number></item></laws>
  <policyArea><name>Economics and Public Finance</name></policyArea>
  <summaries>
    <summary><actionDate>2013-09-10</actionDate><text>&lt;p&gt;Old text.&lt;/p&gt;</text></summary>
    <summary><actionDate>2013-12-26</actionDate><cdata><text>&lt;p&gt;Makes &lt;b&gt;continuing&lt;/b&gt; appropriations &amp;amp; more.&lt;/p&gt;</text></cdata></summary>
  </summaries>
  <latestAction><actionDate>2013-12-26</actionDate><text>Became Public Law No: 113-67.</text></latestAction>
</bill></billStatus>"""


def test_parse_bill_reads_the_map_columns():
    row = archive.parse_bill(SAMPLE)
    assert (row["congress"], row["bill_type"], row["bill_number"]) == ("113", "HJRES", "59")
    assert row["status"] == "Signed into Law" and row["location_kind"] == "law"
    assert row["sponsor_bioguide_id"] == "R000395" and row["sponsor_party"] == "R"
    assert row["num_cosponsors"] == 2
    assert row["public_law_number"] == "Public Law 113-67"
    assert row["short_summary"] == "Makes continuing appropriations & more."  # the latest summary, as plain text
    assert row["url"] == "https://www.congress.gov/bill/113th-congress/house-joint-resolution/59"
    assert json.loads(row["recent_actions"])[-1]["committees"] == ["hsap00"]


def test_parse_bill_refuses_a_document_type_declaration():
    with pytest.raises(ValueError):
        archive.parse_bill(b'<!DOCTYPE x [<!ENTITY a "b">]>' + SAMPLE)


def test_ordinal_and_years():
    assert [archive.ordinal(n) for n in (101, 102, 103, 111, 113, 118)] == ["101st", "102nd", "103rd", "111th", "113th", "118th"]
    assert archive.snapshot.congress_years(118) == (2023, 2025)


def test_chamber_in_uses_the_term_of_that_congress():
    terms = [{"chamber": "House of Representatives", "startYear": 2001, "endYear": 2025}, {"chamber": "Senate", "startYear": 2025}]
    assert archive.snapshot.chamber_in(terms, 118) == "House of Representatives"
    assert archive.snapshot.chamber_in(terms, 119) == "Senate"


def _meetings(count):
    return pd.DataFrame({"event_id": [str(n) for n in range(count)], "update_date": "2024-01-01", "date": "2024-01-01"})


def _committee_run(monkeypatch, tmp_path, answers):
    """Run build_committee_file against a scripted fetch_meetings. Returns the waits taken."""
    waits = []
    replies = iter(answers)
    monkeypatch.setattr(archive.committees, "fetch_committee_list", lambda congress: pd.DataFrame({"committee_code": ["hsag00"]}))
    monkeypatch.setattr(archive.committees, "fetch_meetings", lambda *a, **k: next(replies))
    monkeypatch.setattr(archive.committees, "app_snapshot", lambda listing, seats, meetings: {"meetings": len(meetings)})
    monkeypatch.setattr(archive.time, "sleep", waits.append)
    path = archive.build_committee_file(118, pd.DataFrame(), tmp_path)
    return path, waits


def test_committee_file_waits_out_an_outage_and_carries_on(monkeypatch, tmp_path):
    answers = [(_meetings(400), 400, 600), (_meetings(400), 0, 600), (_meetings(400), 0, None), (_meetings(1000), 600, 0)]
    path, waits = _committee_run(monkeypatch, tmp_path, answers)
    assert waits == [archive.STALL_WAIT, archive.STALL_WAIT]
    assert path.exists() and len(pd.read_parquet(tmp_path / "meetings_118.parquet")) == 1000


def test_committee_file_is_not_written_from_a_partial_set(monkeypatch, tmp_path):
    answers = [(_meetings(400), 400, 600)] + [(_meetings(400), 0, 600)] * (archive.STALL_TRIES + 1)
    with pytest.raises(RuntimeError, match="600 meetings still to fetch"):
        _committee_run(monkeypatch, tmp_path, answers)
    assert not (tmp_path / "118" / "committees.json.gz").exists()
    assert len(pd.read_parquet(tmp_path / "meetings_118.parquet")) == 400  # kept for the next run


def test_committee_file_goes_on_without_a_few_unavailable_meetings(monkeypatch, tmp_path):
    answers = [(_meetings(997), 997, 3), (_meetings(997), 0, 3), (_meetings(997), 0, 3)]
    path, waits = _committee_run(monkeypatch, tmp_path, answers)
    assert waits == [archive.STALL_WAIT] and path.exists()


def test_a_failed_page_of_the_meeting_list_is_not_the_end_of_the_list(monkeypatch):
    pages = iter([{"committeeMeetings": [{"eventId": n, "updateDate": "x"} for n in range(250)]}, None])
    monkeypatch.setattr(archive.committees.bills, "api_get", lambda *a, **k: next(pages))
    with pytest.raises(archive.committees.ListingFailed):
        archive.committees.list_meetings("house", 118)


def test_fetch_meetings_keeps_what_it_has_when_the_list_fails(monkeypatch):
    monkeypatch.setattr(archive.committees.bills, "api_get", lambda *a, **k: None)
    held = _meetings(12)
    table, fetched, left = archive.committees.fetch_meetings(held, congress=118)
    assert len(table) == 12 and fetched == 0 and left is None
