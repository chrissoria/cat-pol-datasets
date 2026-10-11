"""The White House snapshot reads departments and revocations from an order's own words."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_whitehouse_snapshot as wh
import pandas as pd


def test_revocation_in_a_sentence_and_the_order_it_merely_describes():
    text = ("Section 1. Executive Order 13258 of February 26, 2002, and Executive Order 13422 of January 18, 2007, "
            "concerning regulatory planning and review, which amended Executive Order 12866 of September 30, 1993, are revoked.")
    assert wh.relations_in(text, "13497") == {"revokes": ["13258", "13422"], "amends": []}


def test_revocations_in_a_list():
    text = ("Sec. 2. Revocation of Orders and Actions. The following executive actions are hereby revoked: "
            "(a) Executive Order 13985 of January 20, 2021 (Advancing Racial Equity). "
            "(b) Executive Order 13986 of January 20, 2021 (Ensuring a Lawful Enumeration). "
            "(c) The Presidential Memorandum of March 13, 2023 (Something Else). "
            "Sec. 3. Implementation. The heads of each agency shall act.")
    assert wh.relations_in(text, "14148")["revokes"] == ["13985", "13986"]


def test_negation_later_orders_and_years_are_not_revocations():
    text = ("This order shall supplement but not supersede the requirements contained in Executive Order 12866. "
            "Executive Order 14999 is revoked. Executive Order 13166 of August 11, 2000, is hereby revoked.")
    assert wh.relations_in(text, "14224") == {"revokes": ["13166"], "amends": []}


def test_amendment_from_the_title():
    assert wh.relations_in("Sec. 1. Section 2 is revised.", "13610", "Executive Order 13610—Amending Executive Order 13597") == {
        "revokes": [], "amends": ["13597"]}


def test_lead_department_needs_two_mentions_and_no_tie():
    named = wh.departments_in("The Secretary of State shall report. The Secretary of State, with the Attorney General, shall act.")
    assert named == [("state", 2), ("justice", 1)] and wh.lead_of(named) == "state"
    assert wh.lead_of(wh.departments_in("The Secretary of Energy and the Secretary of Labor shall confer.")) is None
    assert wh.lead_of(wh.departments_in("The Secretary of War shall act. The Navy Department shall assist.")) == "defense"


def test_excerpt_skips_the_formula():
    text = "By the authority vested in me as President, it is hereby ordered:\n\nSection 1 . Purpose . Farmers are essential."
    assert wh.excerpt_of(text) == "Purpose. Farmers are essential."


def test_body_keeps_paragraphs_and_text_files_follow_the_map_order():
    text = ("Executive Order 1 of May 1, 2025\n\nBy the authority vested in me, it is hereby ordered:\n\n"
            "Section 1. Purpose.   Farmers are\nessential.\n\nSec. 2. Policy. Relief follows.")
    assert wh.body_of(text) == "Purpose. Farmers are essential.\nSec. 2. Policy. Relief follows."
    df = pd.DataFrame({
        "date": ["2025-02-01", "2025-01-01", "2025-03-01"],
        "executive_order_number": ["2", "1", "3"],
        "text": ["second", "first", "x" * (wh.TEXT_CHARS + 50)],
    })
    files = wh.text_files(df)
    assert files[0][:2] == ["first", "second"]
    assert len(files[0][2]) == wh.TEXT_CHARS + 1 and files[0][2].endswith("…")
