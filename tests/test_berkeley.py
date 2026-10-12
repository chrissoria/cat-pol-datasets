"""build_berkeley gives each Berkeley ordinance the day the City Clerk has for it, and adds the ones passed since."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import build_berkeley as berkeley

COLUMNS = ["date", "ordinance_number", "doc_type", "title", "text", "disposition", "effective_date", "url", "year"]


def row(number, date, year, title="A title"):
    return {"date": date, "ordinance_number": number, "doc_type": "ordinance", "title": title, "text": "Legislative History",
            "disposition": "Codified", "effective_date": "", "url": "https://berkeley.municipal.codes/enactments/x", "year": year}


def dataset():
    return pd.DataFrame([row("Ord. 8001-NS", "2026-02-10", 2026), row("Ord. 2099-NS", "1936", 1936), row("Ord. 3495-NS", "1968-01-01", 1968),
                         row("Ord. 45-NS", "1911", 1911), row("Ord. 603", "1905", 1905), row("Ord. 12-A", "1899", 1899),
                         row("Ord. 5000-NS", "1977", 1977)], columns=COLUMNS)


def clerk(*rows):
    return pd.DataFrame([{"number": n, "date": d, "title": t, "doc_id": "x"} for n, d, t in rows], columns=["number", "date", "title", "doc_id"])


LISTING = clerk(("8001", "2026-02-10", "POLICE EQUIPMENT"), ("2099", "1937-06-15", ""), ("3495", "1956-03-20", ""),
                ("5000", "1977-05-03", ""), ("5000", "1977-05-10", ""),  # listed twice: which is it?
                ("8002", "2026-03-10", "A NEW ORDINANCE"), ("8032", "2026-09-29", "REPEAL OF CHAPTER 3.72"),
                ("950", "1924-01-08", ""), ("", "1930-01-01", "NO NUMBER"))


def test_the_clerks_listing_is_read_from_what_the_records_site_answers():
    answer = [{"ID": "token=", "Name": "9/29/2026; CLK - Ordinance; City Council; 8032; ; REPEAL OF  CHAPTER 3.72 &amp; 3.73",
               "DisplayColumnValues": [{"Value": "9/29/2026", "RawValue": "1790640000000"}, {"Value": "CLK - Ordinance", "RawValue": None},
                                       {"Value": "REPEAL OF  CHAPTER 3.72 &amp; 3.73", "RawValue": None}, {"Value": "8032", "RawValue": "8032"}]},
              {"ID": "other=", "Name": "4/23/1968; CLK - Ordinance; City Council; 4342; ;",
               "DisplayColumnValues": [{"Value": "4/23/1968", "RawValue": "-53481600000"}, {"Value": "CLK - Ordinance", "RawValue": None},
                                       {"Value": None, "RawValue": None}, {"Value": "4342", "RawValue": "4342"}]}]
    assert berkeley.listed(answer).to_dict("records") == [
        {"number": "8032", "date": "2026-09-29", "title": "REPEAL OF CHAPTER 3.72 & 3.73", "doc_id": "token="},
        {"number": "4342", "date": "1968-04-23", "title": "", "doc_id": "other="}]
    assert berkeley.day_of("1/5/1926") == "1926-01-05" and berkeley.day_of("") == "" and berkeley.day_of("1926") == ""


def test_only_an_ordinance_of_the_new_series_has_a_number_the_clerk_knows():
    assert berkeley.number_of("Ord. 7999-NS") == "7999"
    assert [berkeley.number_of(n) for n in ("Ord. 603", "Ord. 12-A", "Ord. 7999A-NS", "Ord. 12-1/2-NS", None)] == [""] * 5


def test_an_ordinance_takes_the_clerks_day_and_its_year_follows():
    out, counts = berkeley.add_listed(dataset(), LISTING)
    by = out.set_index("ordinance_number")
    assert (by.loc["Ord. 2099-NS", "date"], by.loc["Ord. 2099-NS", "year"]) == ("1937-06-15", 1937)
    assert (by.loc["Ord. 3495-NS", "date"], by.loc["Ord. 3495-NS", "year"]) == ("1956-03-20", 1956)  # not the code's 1968
    assert counts["dated"] == 3 and counts["dates_changed"] == 2
    assert by.loc["Ord. 2099-NS", "title"] == "A title" and by.loc["Ord. 2099-NS", "text"] == "Legislative History"  # nothing else is touched


def test_what_the_clerk_does_not_list_or_lists_twice_is_left_as_it_was():
    out, counts = berkeley.add_listed(dataset(), LISTING)
    by = out.set_index("ordinance_number")
    assert [by.loc[n, "date"] for n in ("Ord. 45-NS", "Ord. 603", "Ord. 12-A", "Ord. 5000-NS")] == ["1911", "1905", "1899", "1977"]
    assert counts["here_not_listed"] == 4


def test_the_ordinances_passed_since_the_newest_here_are_added_and_older_strays_are_not():
    out, counts = berkeley.add_listed(dataset(), LISTING)
    assert list(out["ordinance_number"][:2]) == ["Ord. 8032-NS", "Ord. 8002-NS"] and len(out) == 9 and list(out.columns) == COLUMNS
    new = out.iloc[0]
    assert (new["date"], new["year"], new["title"], new["doc_type"], new["text"], new["url"]) == \
        ("2026-09-29", 2026, "REPEAL OF CHAPTER 3.72", "ordinance", "", "")
    assert counts["added"] == 2 and counts["listed_not_here"] == 1  # 950 is listed and not here, and is not added
    assert "Ord. 950-NS" not in set(out["ordinance_number"])
    assert out["year"].dtype == dataset()["year"].dtype


def test_running_it_twice_changes_nothing_more():
    once, _ = berkeley.add_listed(dataset(), LISTING)
    twice, counts = berkeley.add_listed(once, LISTING)
    assert twice.equals(once) and counts["added"] == 0 and counts["dates_changed"] == 0


def test_a_text_read_from_the_document_becomes_the_text_and_the_codes_note_is_kept_beside_it():
    kept = pd.DataFrame([{"number": "2099", "text": "ORDINANCE NO. 2099-N.S.", "text_source": "ocr", "pages": 2, "ocr_confidence": 88.5, "problem": ""},
                         {"number": "3495", "text": "", "text_source": "", "pages": None, "ocr_confidence": None, "problem": "not fetched: Timeout"}],
                        columns=berkeley.TEXT_COLUMNS)
    out = berkeley.add_texts(dataset(), kept).set_index("ordinance_number")
    assert out.loc["Ord. 2099-NS", ["text", "text_source", "pages", "ocr_confidence", "code_history"]].tolist() == \
        ["ORDINANCE NO. 2099-N.S.", "ocr", 2, 88.5, "Legislative History"]
    assert out.loc["Ord. 3495-NS", "text"] == "" and out.loc["Ord. 3495-NS", "code_history"] == "Legislative History"
    again = berkeley.add_texts(out.reset_index(), kept).set_index("ordinance_number")
    assert again.loc["Ord. 2099-NS", "code_history"] == "Legislative History" and again.loc["Ord. 2099-NS", "text"].startswith("ORDINANCE")


def test_the_documents_still_to_read_are_the_newest_first_and_none_listed_twice():
    kept = pd.DataFrame([{"number": "8032", "text": "read", "text_source": "ocr", "pages": 1, "ocr_confidence": 90.0, "problem": ""},
                         {"number": "950", "text": "", "text_source": "", "pages": None, "ocr_confidence": None, "problem": "not fetched: Timeout"}],
                        columns=berkeley.TEXT_COLUMNS)
    assert berkeley.waiting(LISTING, kept) == ["8002", "8001", "3495", "2099", "950"]  # a failure is tried again
