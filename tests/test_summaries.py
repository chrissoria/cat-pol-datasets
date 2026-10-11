"""summarize_federal_bills keeps a summary tied to the text it was written from."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import summarize_federal_bills as sm

GOOD = "This bill would let small contractors be paid sooner.\n\nAgencies would pay half the extra cost up front. It applies to federal construction work."


def table():
    return pd.DataFrame({
        "bill_type": ["HR", "S", "HR", "HRES", "S"],
        "bill_number": ["1", "2", "3", "4", "5"],
        "text": ["x" * 100, "x" * 100, "x" * 100, "x" * 100, "short"],
        "bill_text_version": ["Introduced in House", "Engrossed in Senate", "Reported in House", "Introduced in House", "Introduced in Senate"],
        "short_summary": ["An old summary.", "An old summary.", None, None, None],
        "date_updated": ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05"],
    })


def test_a_summary_is_checked_for_its_form():
    assert sm.check(GOOD) == []
    assert sm.check("") == ["empty"]
    assert sm.check("One paragraph only, with no opening line set apart.") == ["not one opening line, a blank line and a paragraph"]
    assert "markup" in sm.check(GOOD.replace("Agencies", "- Agencies")) and "markup" in sm.check(GOOD + " #congress")
    assert sm.check("x" * 300 + ".\n\n" + "y" * 200) == [f"over {sm.HARD_LIMIT} characters"]


def test_the_opening_may_not_say_where_the_bill_stands():
    problem = "the opening says where the bill stands"
    assert problem in sm.check("The Senate just introduced a bill on contractor pay.\n\nIt pays half up front. It covers federal work.")
    assert problem in sm.check("House lawmakers passed a measure on contractor pay.\n\nIt pays half up front. It covers federal work.")
    # What the bill itself would do can use the same words.
    assert sm.check("This bill would require that reported costs be paid within 30 days.\n\nIt pays half up front. It covers federal work.") == []
    assert sm.check(GOOD.replace("federal construction work", "work on bills already passed")) == []


def test_extra_blank_lines_and_spaces_are_tidied_before_checking():
    assert sm.tidy("  This bill would do a thing.  \n\n\n\nIt affects  many people. ") == "This bill would do a thing.\n\nIt affects many people."
    # A model that writes its line breaks as the two characters backslash and n.
    assert sm.tidy("This bill would do a thing.\\n\\nIt affects many people.") == "This bill would do a thing.\n\nIt affects many people."


def test_a_long_bill_is_cut_with_a_note_and_a_short_one_is_whole():
    assert sm.shown("abc", 10) == "abc"
    cut = sm.shown("a" * 50, 10)
    assert cut.startswith("a" * 10 + "\n\n[") and "first 10 characters" in cut


def test_an_old_summary_is_trusted_only_while_the_text_is_as_introduced():
    df = sm.stamp_legacy(table())
    assert list(df["summary_text_version"]) == ["Introduced in House", "", "", "", ""]
    # HR 1 is current. S 2's text has moved on since some summary was written; HR 3 and HRES 4 have none; S 5 has no text to speak of.
    assert list(sm.needs_summary(df)) == [False, True, True, True, False]


def test_a_stored_summary_goes_in_only_where_the_text_is_still_that_version():
    df = sm.stamp_legacy(table())
    store = pd.DataFrame([("S2", "Engrossed in Senate", GOOD, "m", "t"), ("HR3", "Introduced in House", GOOD, "m", "t"),
                          ("HRES4", "Introduced in House", GOOD, "m", "t")], columns=sm.STORE_COLUMNS)
    assert sm.apply(df, store) == 2
    assert df.loc[1, "short_summary"] == GOOD and df.loc[1, "summary_text_version"] == "Engrossed in Senate"
    assert pd.isna(df.loc[2, "short_summary"])  # written from the introduced text; the bill has since been reported
    assert list(sm.needs_summary(df)) == [False, False, True, False, False]
    assert sm.apply(df, store) == 0  # nothing left to change


def test_bills_are_handed_to_a_model_as_files_and_what_it_writes_is_checked(tmp_path):
    df = sm.stamp_legacy(table())
    index = sm.export(df, [2, 3], tmp_path)
    assert [item["id"] for item in index] == ["HR3", "HRES4"] and index[0]["text_version"] == "Reported in House"
    assert (tmp_path / "bills" / "HR3.txt").read_text().startswith("HR 3: ")
    assert "This bill would" in (tmp_path / "instructions.txt").read_text()
    written = {"HR3": GOOD + "  ", "HRES4": "The House just introduced a resolution.\n\nIt says a thing. It matters.", "S99": GOOD}
    (tmp_path / "summaries.json").write_text(json.dumps(written))
    good, refused = sm.read_import(tmp_path / "summaries.json")
    assert good == [("HR3", "Reported in House", GOOD)]
    assert refused == {"HRES4": ["the opening says where the bill stands"], "S99": ["not a bill that was asked for"]}
    (tmp_path / "summaries.json").write_text(json.dumps({"HR3": GOOD}))
    assert sm.read_import(tmp_path / "summaries.json")[1] == {"HRES4": ["missing"]}


def test_the_newest_summary_for_a_bill_and_version_is_the_one_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(sm, "STORE", tmp_path / "store.parquet")
    sm.keep([("HR3", "Introduced in House", "first")], "a")
    store = sm.keep([("HR3", "Introduced in House", "second"), ("HR3", "Reported in House", "third")], "b")
    assert sorted(zip(store["text_version"], store["summary"])) == [("Introduced in House", "second"), ("Reported in House", "third")]
    assert len(sm.load_store()) == 2
