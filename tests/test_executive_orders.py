"""update_executive_orders.merge adds the Federal Register's orders without duplicating or losing any."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import update_executive_orders as eo


def table(rows):
    df = pd.DataFrame(rows)
    for column in eo.COLUMNS:
        if column not in df.columns:
            df[column] = ""
    df["year"] = 2026
    return df[eo.COLUMNS]


def doc(number, signed, title, document="2026-1"):
    return {"executive_order_number": number, "signing_date": signed, "publication_date": signed, "title": title,
            "document_number": document, "html_url": "https://fr/x", "pdf_url": "https://fr/x.pdf",
            "president": {"name": "Donald Trump"}, "body_html_url": ""}


def test_merge_matches_adds_and_skips():
    existing = table([
        {"date": "2026-03-13", "title": "Executive Order 14394—Removing Barriers", "executive_order_number": "14394", "text": "a"},
        {"date": "2026-03-20", "title": "Executive Order—Preserving America's Game", "executive_order_number": "", "text": "b"},
    ])
    listing = [
        doc(14394, "2026-03-13", "Removing Barriers", "2026-10"),
        doc(14396, "2026-03-20", "Preserving America’s Game".replace("’", "'"), "2026-11"),  # had no number when first collected
        doc(14397, "2026-03-24", "A New Order", "2026-12"),
        doc(None, "2026-03-25", "Correction", "2026-13"),
    ]
    out, added, filled = eo.merge(existing, listing, fetch_text=False)
    assert (len(out), added, filled) == (3, 1, 2)
    numbered = out.set_index("executive_order_number")
    assert numbered.loc["14396", "title"] == "Executive Order 14396—Preserving America's Game"
    assert numbered.loc["14396", "document_number"] == "2026-11" and numbered.loc["14396", "text"] == "b"
    assert numbered.loc["14397", "president"] == "Donald J. Trump (2nd Term)" and numbered.loc["14397", "party"] == "Republican"
    assert numbered.loc["14397", "title"] == "Executive Order 14397—A New Order"
    # Running it again changes nothing.
    again, added, filled = eo.merge(out, listing, fetch_text=False)
    assert (len(again), added, filled) == (3, 0, 0)


def test_plain_drops_markup_and_filing_marks():
    body = "<p>Section 1\n<span>.</span> Purpose.</p><p>( printed page 12)</p><p>THE WHITE HOUSE,</p><p>[FR Doc. 2026-1 Filed 1-1-26]</p>"
    assert eo.plain(body) == "Section 1. Purpose.\n\nTHE WHITE HOUSE,"


def test_president_label_tells_terms_apart():
    assert eo.president_label("Donald Trump", "2019-05-01") == "Donald J. Trump (1st Term)"
    assert eo.president_label("Donald Trump", "2026-05-01") == "Donald J. Trump (2nd Term)"
    assert eo.president_label("Joe Biden", "2022-05-01") == "Joseph R. Biden, Jr."
