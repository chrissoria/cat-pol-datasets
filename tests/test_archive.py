"""parse_bill reads a GovInfo Bill Status file into the columns the map uses."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
