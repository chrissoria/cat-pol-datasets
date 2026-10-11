"""build_supreme_court reads dockets, names and votes the way the sources write them."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import build_supreme_court as sc


def entries(*lines):
    return [{"docket": "25-1", "kind": "case", "seq": i, "date": date, "text": text} for i, (date, text) in enumerate(lines)]


def docket_file(*lines, **fields):
    return {"sJsonTerm": "2025", "PetitionerTitle": "Jane Roe, et al., Applicants", "RespondentTitle": "John Doe",
            "ProceedingsandOrder": [{"Date": date, "Text": text} for date, text in lines], **fields}


def test_a_docket_number_reads_the_same_from_either_source():
    assert sc.docket_key("22O141") == sc.docket_key("No. 141, Orig.") == sc.docket_key("141-orig") == "141-orig"
    assert sc.docket_key(" 24-1287 ") == "24-1287"
    assert sc.docket_key("24") == "24"  # an old case number, not an original action


def test_only_dockets_the_court_publishes_are_asked_for():
    assert sc.docket_number("24-1287") == "24-1287"
    assert sc.docket_number("25A400") == "25A400"
    assert sc.docket_number("No. 142, Orig.") == "22O142"
    assert sc.docket_number("16-299") == ""  # before the 2017 term
    assert sc.docket_number("74-54") == "" and sc.docket_number("24") == ""


def test_the_term_is_named_for_the_october_it_opens_in():
    assert sc.current_term("2026-10-05") == 2026
    assert sc.current_term("2026-09-30") == 2025
    assert sc.current_term("2026-06-30") == 2025


def test_names_in_capitals_are_set_in_mixed_case():
    assert sc.tidy_name("LEARNING RESOURCES, INC. v. TRUMP") == "Learning Resources, Inc. v. Trump"
    assert sc.tidy_name("MCCARTHY v. O'CONNOR") == "McCarthy v. O'Connor"
    assert sc.tidy_name("CHILDREN'S HOSPITAL v. U.S.") == "Children's Hospital v. U.S."
    assert sc.tidy_name("Trump v. CASA, Inc.") == "Trump v. CASA, Inc."  # already mixed: left alone


def test_executive_orders_named_in_a_text_are_listed_once_in_order():
    text = "challenging Executive Order 14160 and E.O. 13769; see also Executive Order No. 14160"
    assert sc.orders_in(text, None) == '["13769", "14160"]'
    assert sc.orders_in("an executive order of 2025") == "[]"


def test_stage_follows_the_docket_and_ignores_motions():
    rows = entries(
        ("2025-06-17", "Petition for a writ of certiorari before judgment filed."),
        ("2025-06-20", "Motion of petitioners to expedite consideration of the petition DENIED."),
        ("2025-08-06", "DISTRIBUTED for Conference of 9/29/2025."),
    )
    assert sc.stage_of(rows)[0] == "conference"
    rows += entries(("2025-09-09", "Petition for a writ of certiorari before judgment GRANTED."),
                    ("2025-09-22", "Motion to dispense with printing the joint appendix GRANTED."),
                    ("2025-09-18", "SET FOR ARGUMENT on Wednesday, November 5, 2025."))
    assert sc.stage_of(rows)[0] == "set for argument"
    rows += entries(("2025-11-05", "Argued. For federal parties: D. John Sauer."),
                    ("2026-02-20", "Judgment in No. 24-1287 is VACATED and case REMANDED."))
    stage, reached = sc.stage_of(rows)
    assert stage == "decided"
    assert reached["granted"] == "2025-09-09" and reached["argued"] == "2025-11-05" and reached["decided"] == "2026-02-20"


def test_a_petition_turned_down_is_denied_not_stuck_at_conference():
    rows = entries(("2025-06-17", "Petition for a writ of certiorari filed."),
                   ("2025-08-06", "DISTRIBUTED for Conference of 9/29/2025."),
                   ("2025-10-06", "Petition DENIED."))
    assert sc.stage_of(rows) == ("denied", {"filed": "2025-06-17", "conference": "2025-08-06", "denied": "2025-10-06"})


def test_a_routine_application_decided_by_one_justice():
    row, its_entries = sc.application_row("25A400", docket_file(
        ("Oct 03 2025", "Application (25A400) to extend the time to file a petition for a writ of certiorari from "
                        "October 15, 2025 to November 14, 2025, submitted to Justice Kavanaugh."),
        ("Oct 07 2025", "Application (25A400) granted by Justice Kavanaugh extending the time to file until November 14, 2025."),
        Links="Linked with 25-590", LowerCourt="United States Court of Appeals for the Sixth Circuit", LowerCourtCaseNumbers="(24-5603)"))
    assert row["kind"] == "extension of time" and row["title"] == "Jane Roe, et al. v. John Doe"
    assert (row["submitted_to"], row["outcome"], row["decided_by"], row["date_resolved"]) == ("Justice Kavanaugh", "granted", "Justice Kavanaugh", "2025-10-07")
    assert row["referred_to_court"] is False and row["linked"] == "25-590" and row["lower_court_case"] == "24-5603"
    assert row["term"] == 2025 and row["date_filed"] == "2025-10-03" and len(its_entries) == 2


def test_an_application_ruled_on_by_the_whole_court():
    row, _ = sc.application_row("24A884", docket_file(
        ("Mar 13 2025", "Application (24A884) for a partial stay, submitted to The Chief Justice."),
        ("Apr 17 2025", "Application (24A884) referred to the Court."),
        ("Jun 27 2025", "Applications for partial stays (24A884, 24A885, and 24A886) granted by the Court. Barrett, J., "
                        "delivered the <a href = 'https://example.org/o.pdf'>opinion</a> of the Court.")))
    assert row["kind"] == "stay" and row["referred_to_court"] is True
    assert (row["outcome"], row["decided_by"], row["date_resolved"]) == ("granted", "the Court", "2025-06-27")


def test_what_a_filing_says_of_the_order_below_is_not_the_ruling():
    row, _ = sc.application_row("25A9", docket_file(
        ("Jul 01 2025", "Application (25A9) to vacate the stay granted by the Fifth Circuit, submitted to Justice Alito.")))
    assert row["kind"] == "stay" and row["outcome"] == "" and row["date_resolved"] == ""
    row, _ = sc.application_row("25A9", docket_file(
        ("Jul 01 2025", "Application (25A9) to vacate the stay granted by the Fifth Circuit, submitted to Justice Alito."),
        ("Jul 09 2025", "Application (25A9) to vacate the stay presented to Justice Alito and by him referred to the Court is denied.")))
    assert (row["outcome"], row["decided_by"], row["referred_to_court"]) == ("denied", "the Court", True)


def test_docket_entries_lose_their_markup():
    rows = sc.entries_of("25-1", docket_file(("Jun 27 2025", "Barrett, J., delivered the <a href = 'x.pdf'>opinion</a>  of the Court.")), "case")
    assert rows == [{"docket": "25-1", "kind": "case", "seq": 0, "date": "2025-06-27", "text": "Barrett, J., delivered the opinion of the Court."}]


def test_the_term_list_gives_the_question_and_the_dates():
    summary = sc.oyez_summary({
        "name": "Learning Resources, Inc. v. Trump", "docket_number": "24-1287 ", "term": "2025",
        "href": "https://api.oyez.org/cases/2025/24-1287", "justia_url": "https://supreme.justia.com/x",
        "question": "<p>Does the Act authorize tariffs?</p>\n<p>\xa0</p>", "description": "A case in which the Court held that it does not.",
        "timeline": [{"event": "Granted", "dates": [1757394000]}, {"event": "Argued", "dates": [1762322400]}, None,
                     {"event": "Decided", "dates": [1771567200]}],
    })
    assert summary["docket"] == "24-1287" and summary["term"] == 2025
    assert summary["question"] == "Does the Act authorize tariffs?"
    assert (summary["date_granted"], summary["date_argued"], summary["date_decided"]) == ("2025-09-09", "2025-11-05", "2026-02-20")
    assert summary["oyez_url"] == "https://www.oyez.org/cases/2025/24-1287"


def test_an_early_case_takes_its_term_from_the_day_it_was_decided():
    decided = int(pd.Timestamp("1954-05-17T05:00:00Z").timestamp())
    summary = sc.oyez_summary({"name": "Brown v. Board of Education", "docket_number": "1", "term": "1940-1955",
                               "timeline": [{"event": "Decided", "dates": [decided]}]})
    assert summary["date_decided"] == "1954-05-17" and summary["term"] == 1953


def test_oyez_fills_in_the_database_rows_it_matches():
    cases = pd.DataFrame({"term": [2025, 2025, 1975], "docket": ["24-1287", "25-9", "No. 12, Orig."], "date_argued": ["", "", ""],
                          "question": "", "description": "", "date_granted": "", "oyez_url": "", "justia_url": "", "executive_orders": "[]"})
    listed = [
        {"term": 2025, "key": "24-1287", "question": "Does Executive Order 14257 stand?", "description": "Held: no.",
         "date_granted": "2025-09-09", "oyez_url": "o1", "justia_url": "j1"},
        {"term": 1974, "key": "12-orig", "question": "Whose river?", "description": "", "date_granted": "", "oyez_url": "o2", "justia_url": ""},
    ]
    assert sc.add_oyez(cases, listed) == 2
    assert cases["question"].tolist() == ["Does Executive Order 14257 stand?", "", "Whose river?"]
    assert cases["executive_orders"].tolist() == ['["14257"]', "[]", "[]"]
    assert cases["date_granted"][0] == "2025-09-09" and cases["oyez_url"][2] == "o2"


def judges_csv(tmp_path, people):
    columns = ["Last Name", "First Name", "Middle Name", "Suffix", "Birth Year", "Death Year", "Gender", "Race or Ethnicity"]
    slots = ["Court Name", "Appointment Title", "Appointing President", "Party of Appointing President", "Nomination Date",
             "Confirmation Date", "Ayes/Nays", "Commission Date", "Recess Appointment Date", "Senior Status Date",
             "Termination", "Termination Date"]
    rows = []
    for person in people:
        row = {column: person.get(column, "") for column in columns}
        for slot in range(1, 7):
            for name in slots:
                row[f"{name} ({slot})"] = person.get(f"{name} ({slot})", "")
        rows.append(row)
    path = tmp_path / "judges.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


SCOTUS = "Supreme Court of the United States"


def test_justices_keep_the_databases_names_and_namesakes_are_told_apart(tmp_path):
    path = judges_csv(tmp_path, [
        {"Last Name": "Harlan", "First Name": "John", "Middle Name": "Marshall", "Court Name (1)": SCOTUS,
         "Commission Date (1)": "1877-11-29", "Termination Date (1)": "1911-10-14", "Termination (1)": "Death"},
        {"Last Name": "Harlan", "First Name": "John", "Middle Name": "Marshall", "Suffix": " ", "Court Name (2)": SCOTUS,
         "Court Name (1)": "U.S. Court of Appeals for the Second Circuit", "Commission Date (2)": "1955-03-17",
         "Termination Date (2)": "1971-09-23", "Termination (2)": "Retirement"},
        {"Last Name": "O'Connor", "First Name": "Sandra", "Middle Name": "Day", "Court Name (1)": SCOTUS,
         "Commission Date (1)": "1981-09-22", "Senior Status Date (1)": "2006-01-31", "Gender": "Female"},
        {"Last Name": "Rehnquist", "First Name": "William", "Middle Name": "Hubbs", "Court Name (1)": SCOTUS, "Court Name (2)": SCOTUS,
         "Appointment Title (1)": "Associate Justice", "Appointment Title (2)": "Chief Justice", "Commission Date (1)": "1971-12-15",
         "Termination Date (1)": "1986-09-26", "Commission Date (2)": "1986-09-25", "Termination Date (2)": "2005-09-03"},
        {"Last Name": "Roberts", "First Name": "John", "Middle Name": "Glover", "Suffix": "Jr.", "Court Name (1)": SCOTUS,
         "Appointment Title (1)": "Chief Justice", "Commission Date (1)": "2005-09-29", "Ayes/Nays (1)": "78/22"},
        {"Last Name": "Roberts", "First Name": "Owen", "Middle Name": "Josephus", "Court Name (1)": SCOTUS,
         "Commission Date (1)": "1930-05-20", "Termination Date (1)": "1945-07-31"},
    ])
    table = sc.justices_table(path, ["JHarlan2", "SDOConnor", "WHRehnquist", "JGRoberts"])
    ids = table.set_index("start")["justice_id"].to_dict()
    assert ids["1877-11-29"] == "JMHarlan" and ids["1955-03-17"] == "JHarlan2"
    assert ids["1930-05-20"] == "OJRoberts" and ids["2005-09-29"] == "JGRoberts"
    assert table[table["justice_id"] == "WHRehnquist"]["title"].tolist() == ["Associate Justice", "Chief Justice"]
    connor = table[table["justice_id"] == "SDOConnor"].iloc[0]
    assert connor["end"] == "2006-01-31" and connor["how_ended"] == "Retirement" and not connor["serving"]
    assert table[table["serving"]]["name"].tolist() == ["John Glover Roberts, Jr."]
    assert sc.justice_for("John G. Roberts, Jr.", table, on="2026-01-01") == "JGRoberts"
    assert sc.justice_for("John M. Harlan", table, on="1960-01-01") == "JHarlan2"


def test_new_applications_are_read_until_the_numbers_run_out(monkeypatch):
    asked = []

    def fake(number):
        asked.append(number)
        return {"n": number} if int(number.split("A")[1]) in (401, 402, 405) else None

    monkeypatch.setattr(sc, "fetch_docket", fake)
    found = sc.new_applications(25, 400)
    assert sorted(found) == ["25A401", "25A402", "25A405"]  # a gap in the numbers does not end the search
    assert max(int(number.split("A")[1]) for number in asked) >= 405 + sc.MISSES_TO_STOP


def test_petitions_are_counted_by_the_highest_number_in_use(monkeypatch):
    monkeypatch.setattr(sc, "fetch_docket", lambda number: {} if int(number.split("-")[1]) <= 1337 and number != "25-900" else None)
    assert sc.highest_number(25, 1) == 1337  # the missing 25-900 is stepped over
    monkeypatch.setattr(sc, "fetch_docket", lambda number: None)
    assert sc.highest_number(27, 5001) == 0


def test_a_docket_read_again_replaces_its_old_entries():
    held = pd.DataFrame([{"docket": "25A1", "kind": "application", "seq": 0, "date": "2025-07-01", "text": "old"},
                         {"docket": "25A2", "kind": "application", "seq": 0, "date": "2025-07-02", "text": "kept"}])
    fresh = [{"docket": "25A1", "kind": "application", "seq": 0, "date": "2025-07-01", "text": "new"},
             {"docket": "25A1", "kind": "application", "seq": 1, "date": "2025-07-03", "text": "more"}]
    merged = sc.replace_entries(held, fresh)
    assert sorted(merged["text"]) == ["kept", "more", "new"]


def test_a_host_that_refuses_is_not_a_missing_file(monkeypatch):
    class Answer:
        def __init__(self, code):
            self.status_code = code

        def json(self):
            return {"ok": True}

    monkeypatch.setattr(sc.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(sc.requests, "get", lambda *a, **k: Answer(404))
    assert sc.get_json("https://example.org/x.json") is None
    monkeypatch.setattr(sc.requests, "get", lambda *a, **k: Answer(403))
    with pytest.raises(sc.Unreachable):
        sc.get_json("https://example.org/x.json")


def test_an_application_that_ends_without_a_ruling():
    row, _ = sc.application_row("17A145", docket_file(
        ("Jul 31 2017", "Application (17A145) for a stay of execution of sentence of death, submitted to Justice Alito."),
        ("Aug 21 2017", "Application (17A145) completed.")))
    assert (row["kind"], row["outcome"], row["decided_by"], row["date_resolved"]) == ("stay of execution", "closed", "", "2017-08-21")
    row, _ = sc.application_row("17A655", docket_file(
        ("Dec 18 2017", "Application (17A655) for a stay pending appeal, submitted to The Chief Justice."),
        ("Dec 19 2017", "Letter of December 19, 2017 withdrawing the application for a stay pending appeal filed by applicant.")))
    assert (row["outcome"], row["decided_by"]) == ("withdrawn", "")


def test_a_name_in_capitals_with_et_al_is_still_reset():
    assert sc.tidy_name("CHRIS SALE, ACTING COMMISSIONER, et al. v. HAITIAN CENTERS COUNCIL, INC., et al.") == \
        "Chris Sale, Acting Commissioner, et al. v. Haitian Centers Council, Inc., et al."


def test_the_docket_gives_a_decided_case_its_disposition():
    assert sc.ruling_in(entries(("2026-02-20", "Judgment in No. 24-1287 is VACATED and case REMANDED with instructions to dismiss; "
                                                "the judgment in No. 25-250 is AFFIRMED."))) == ("vacated and remanded", "petitioner")
    assert sc.ruling_in(entries(("2026-01-10", "Adjudged to be AFFIRMED."))) == ("affirmed", "respondent")
    assert sc.ruling_in(entries(("2026-01-10", "Judgment REVERSED and case REMANDED."))) == ("reversed and remanded", "petitioner")
    assert sc.ruling_in(entries(("2026-01-10", "Judgment AFFIRMED in part, REVERSED in part, and case REMANDED."))) == \
        ("affirmed and reversed in part, and remanded", "")
    assert sc.ruling_in(entries(("2026-01-10", "Writ of certiorari DISMISSED as improvidently granted."))) == ("petition denied or appeal dismissed", "")
    assert sc.ruling_in(entries(("2025-09-22", "Motion to dispense with printing the joint appendix GRANTED."))) == ("", "")
    assert set(sc.ruling_in(entries(("2026-01-10", "Judgment REVERSED and case REMANDED.")))[:1]) <= set(sc.DISPOSITIONS.values())


def test_a_short_name_with_an_ampersand_stays_in_capitals():
    assert sc.tidy_name("FEDERAL COMMUNICATIONS COMMISSION v. AT&T") == "Federal Communications Commission v. AT&T"
    assert sc.tidy_name("JONES & LAUGHLIN STEEL CORP. v. NLRB") == "Jones & Laughlin Steel Corp. v. NLRB"


def test_the_daily_run_carries_on_when_one_source_is_out_of_reach(monkeypatch):
    held = {name: pd.DataFrame() for name in sc.TABLES}
    held["cases"] = pd.DataFrame({"id": ["2024-1"], "source": ["scdb"]})
    held["applications"] = pd.DataFrame({"docket": ["25A1"]})
    monkeypatch.setattr(sc, "read_published", lambda: {name: table.copy() for name, table in held.items()})
    monkeypatch.setattr(sc, "terms_table", lambda tables, previous=None, count_petitions=(): pd.DataFrame())

    def refuse(*args, **kwargs):
        raise sc.Unreachable("api.oyez.org: ProxyError")

    monkeypatch.setattr(sc, "refresh_live", refuse)
    monkeypatch.setattr(sc, "refresh_dockets", lambda tables, **kwargs: {"case_dockets": 0})
    tables, reached = sc.build_daily()
    assert reached == {"oyez": "unreachable", "dockets": "ok"} and len(tables["cases"]) == 1

    monkeypatch.setattr(sc, "refresh_live", lambda tables: 0)
    monkeypatch.setattr(sc, "refresh_dockets", refuse)
    assert sc.build_daily()[1] == {"oyez": "ok", "dockets": "unreachable"}
