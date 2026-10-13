"""build_ca_county_boards puts every county board's tables in one dataset, each table with the same columns for every county."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import bodies
import build_ca_county_boards as boards
import council_tables

FACTS = {"key": "fresno-county", "county": "Fresno", "county_fips": "06019", "read_from": boards.SYSTEM}


def test_every_county_named_is_a_body_with_a_board_and_a_place():
    listed = {body["id"]: body for body in bodies.read_bodies()}
    seen = set()
    for key in boards.COUNTIES:
        facts = boards.facts_of(key, listed)
        assert facts["county_fips"].startswith("06") and len(facts["county_fips"]) == 5 and facts["body"] == "Board of Supervisors"
        assert facts["slug"] not in seen and facts["system"] and facts["builder"].endswith(".py") and facts["site"].startswith("https://")
        seen.add(facts["slug"])
    assert boards.facts_of("sd-county", listed)["slug"] == "san-diego" and boards.facts_of("sd-county", listed)["raw"] is False
    assert boards.facts_of("santa-cruz-county", listed)["room"] == ""  # its record has ended, and it has no room
    assert boards.facts_of("alpine-county", listed)["note"] == boards.CIVICCLERK_NOTE


def test_a_table_has_the_shared_columns_and_those_most_readers_add_whatever_its_reader_wrote():
    # A Legistar county's votes: the shared columns only. A PDF county's would have a motion and codes of its own.
    plain = pd.DataFrame({"item_id": ["1", "2"], "meeting_id": ["9", "9"], "date": ["2026-09-01"] * 2, "matter_id": ["5", "6"],
                          "matter_file": ["26-1", None], "member": ["A", "B"], "vote": ["AYE", "NOT PRESENT"]})
    one = boards.one_shape("votes", plain.assign(read_from=boards.SYSTEM, vote_kind=plain["vote"].map(boards.vote_kind)), FACTS)
    assert list(one.columns) == ["county", "county_fips"] + council_tables.COLUMNS["votes"] + ["vote_kind", "motion", "motion_text", "read_from"]
    assert one["county"].tolist() == ["Fresno", "Fresno"] and one["matter_file"].tolist() == ["26-1", ""]
    assert one["motion"].isna().all() and str(one["motion"].dtype) == "Int64" and one["vote_kind"].tolist() == ["AYE", "ABSENT"]
    rich = plain.assign(motion=[1, 2], motion_text=["Adopt", "Continue"], code=["12345", ""], marks=["", "N"])
    other = boards.one_shape("votes", rich.assign(read_from=boards.CODE, vote_kind="AYE"), FACTS)
    assert list(other.columns) == list(one.columns) and other["motion"].tolist() == [1, 2]  # what only it has is left to raw/
    assert boards.schema_of("votes").names == list(one.columns)


def test_an_agenda_with_no_headings_among_its_lines_has_only_items():
    lines = pd.DataFrame({column: ["x"] for column in council_tables.COLUMNS["agenda_items"]}).assign(sequence=1, ayes=5, noes=0, not_voting=0)
    assert boards.one_shape("agenda_items", lines, FACTS)["heading"].tolist() == [False]
    read = boards.one_shape("agenda_items", lines.assign(heading=True, votes_read=False, problem="two names for one seat"), FACTS)
    assert read["heading"].tolist() == [True] and read["votes_read"].tolist() == [False] and read["problem"].tolist() == ["two names for one seat"]
    assert boards.one_shape("agenda_items", lines, FACTS)["votes_read"].isna().all()  # no reading to have failed


def test_a_vote_says_how_it_was_read_and_two_counties_changed_their_way():
    votes = pd.DataFrame({"meeting_id": ["1", "2"], "code": ["12345", ""]})
    meetings = pd.DataFrame({"meeting_id": ["1", "2"], "source": ["minutes document", "minutes"]})
    assert boards.read_from({"key": "orange-county", "read_from": boards.TEXT}, votes, meetings).tolist() == [boards.CODE, boards.TEXT]
    assert boards.read_from({"key": "yolo-county", "read_from": boards.PAGE}, votes, meetings).tolist() == [boards.TEXT, boards.PAGE]
    assert boards.read_from(FACTS, votes, meetings).tolist() == [boards.SYSTEM, boards.SYSTEM]


def test_a_clerks_word_for_a_vote_is_one_of_a_few_kinds():
    assert [boards.vote_kind(word) for word in ("AYE", "NO", "ABSTAINED", "EXCUSED", "AWAY", "RECUSE", "VACANT", "")] == \
        ["AYE", "NO", "ABSTAIN", "ABSENT", "ABSENT", "RECUSED", "OTHER", "OTHER"]


def test_a_countys_line_is_counted_from_its_tables_and_the_card_lists_it(tmp_path):
    tables = {name: pd.DataFrame(columns=council_tables.COLUMNS[name] + boards.ADDED[name]) for name in boards.TABLES}
    tables["meetings"] = pd.DataFrame({"date": ["2015-01-06", "2026-10-06", "2126-01-01"], "items": [40, 38, 3]})
    tables["votes"] = pd.DataFrame({"date": ["2015-01-06", "2026-10-06"], "read_from": [boards.SYSTEM] * 2})
    tables["members"] = pd.DataFrame({"serving": [True, False, True]})
    facts = {**boards.facts_of("fresno-county"), "note": "A note."}
    row = boards.county_row(facts, tables, "2026-10-13")
    assert (row["first_meeting"], row["last_meeting"], row["first_vote"], row["last_vote"]) == ("2015-01-06", "2026-10-06", "2015-01-06", "2026-10-06")
    assert (row["votes"], row["meetings"], row["serving"], row["kept_current"], row["read_from"]) == (2, 3, 2, "daily run", "system")
    assert boards.county_row(boards.facts_of("sutter-county"), tables, "2026-10-13")["kept_current"] == "by hand"
    counties = boards.counties_table([row])
    assert list(counties.columns) == boards.COUNTY_COLUMNS
    # One county built again replaces its own line and leaves the others.
    held = pd.DataFrame([{**row, "votes": 1}, {**row, "county": "Lake", "county_fips": "06033", "votes": 9}], columns=boards.COUNTY_COLUMNS)
    again = boards.counties_table([row], held)
    assert again[["county", "votes"]].values.tolist() == [["Lake", 9], ["Fresno", 2]]
    text = boards.card(again)
    assert "{" not in text.split("---", 2)[2] and "| Fresno | Legistar | 2 | 2015-01-06 | 2026-10-06 |" in text and "- **Fresno, Lake.** A note." in text  # counties that share a note are named together


def test_a_readers_tables_for_a_county_board_go_to_the_one_dataset(monkeypatch, tmp_path):
    assert council_tables.board_of("chrissoria/fresno-county-board") == "fresno-county"
    assert council_tables.board_of("chrissoria/fresno-council") is None and council_tables.board_of(boards.REPO) is None
    asked = []
    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", lambda repo, file, **more: asked.append((repo, file)) or "nowhere.parquet")
    assert council_tables.published("chrissoria/san-mateo-county-board", "votes") is None  # nothing there to read, and no error
    council_tables.published("chrissoria/oakland-council", "votes")
    assert asked == [(boards.REPO, "raw/san-mateo/votes.parquet"), ("chrissoria/oakland-council", "data/votes.parquet")]
    sent = []
    monkeypatch.setattr(boards, "publish_county", lambda key, folder: sent.append((key, folder)) or True)
    assert council_tables.publish("chrissoria/lake-county-board", tmp_path, "a card of its own", True, "Update") is True
    assert sent == [("lake-county", tmp_path)]


def test_a_county_not_listed_is_not_published(tmp_path):
    try:
        boards.publish_county("alameda-county", tmp_path)
    except ValueError as e:
        assert "alameda-county is not among the counties" in str(e)
    else:
        raise AssertionError("published a county that is not listed")


def test_the_daily_run_reads_the_counties_longest_unread_until_its_time_is_up(monkeypatch, tmp_path):
    listed = {body["id"]: body["place"] for body in bodies.read_bodies()}
    daily = [key for key, county in boards.COUNTIES.items() if county.get("daily") and county["builder"] in boards.READERS]
    assert "fresno-county" in daily and "sd-county" not in daily and "santa-clara-county" not in daily
    # Every county was read on the 12th but two, read on the 10th and the 11th: those two come first, oldest first.
    held = pd.DataFrame({"county_fips": [listed[key] for key in daily],
                         "read_on": ["2026-10-10" if key == "lake-county" else "2026-10-11" if key == "napa-county" else "2026-10-12" for key in daily]})
    monkeypatch.setattr(boards, "held_counties", lambda out_dir: held)
    monkeypatch.setattr(boards.bills, "hf_write_problem", lambda repo=None: None)
    monkeypatch.setattr(boards.bills, "SCRIPT_DIR", tmp_path)  # no tables of San Diego's written today
    called = []

    class Reader:
        @staticmethod
        def main(argv):
            called.append(argv)
            return 1 if argv[1] == "napa-county" else 0

    monkeypatch.setattr(boards.importlib, "import_module", lambda name: Reader)
    clock = iter(range(0, 100000, 400))  # each look at the clock is 400 seconds on
    monkeypatch.setattr(boards.time, "time", lambda: next(clock))
    assert boards.read_some(15, tmp_path) == 1  # Napa's reader failed, and the run says so
    assert [argv for argv in called][:2] == [["--city", "lake-county"], ["--city", "napa-county"]]
    assert 2 <= len(called) < len(daily)  # time ran out before every county had a turn


def test_the_daily_run_reads_nothing_if_the_token_may_not_write(monkeypatch, tmp_path):
    monkeypatch.setattr(boards.bills, "hf_write_problem", lambda repo=None: "the token has no write permission")
    monkeypatch.setattr(boards.importlib, "import_module", lambda name: (_ for _ in ()).throw(AssertionError("a reader was called")))
    assert boards.read_some(30, tmp_path) == 1
