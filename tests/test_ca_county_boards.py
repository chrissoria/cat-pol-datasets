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
    # Alameda's margin and its words; Stanislaus's votes the minutes print, and those worked out from a count or "unan."
    marked = pd.DataFrame({"source": ["margin", "words", "margin and words", "margin, recusal in words"]})
    assert boards.read_from({"key": "alameda-county", "read_from": boards.CODE}, marked, meetings).tolist() == [
        boards.CODE, boards.TEXT, boards.CODE, boards.CODE]
    worked = pd.DataFrame({"established": ["named", "count", "unanimous"]})
    assert boards.read_from({"key": "stanislaus-county", "read_from": boards.TEXT}, worked, meetings).tolist() == [
        boards.TEXT, boards.COUNT, boards.UNANIMOUS]
    paged = pd.DataFrame({"meeting_id": [1, 2, 1], "established": ["named", "named", "majority"]})
    forms = pd.DataFrame({"meeting_id": [1, 2], "format": ["html", "pdf"]})
    assert boards.read_from({"key": "san-luis-obispo-county", "read_from": boards.TEXT}, paged, forms).tolist() == [
        boards.PAGE, boards.TEXT, boards.COUNT]
    assert boards.read_from({"key": "ventura-county", "read_from": ""}, votes.iloc[:0], meetings).tolist() == []


def test_a_countys_earlier_record_is_put_before_its_present_one():
    def tables(meetings, votes, members):
        blank = lambda name, rows: pd.DataFrame(rows, columns=council_tables.COLUMNS[name])
        return {"items": blank("items", []), "agenda_items": blank("agenda_items", []), "meetings": blank("meetings", meetings),
                "votes": blank("votes", votes), "members": blank("members", members)}
    meeting = lambda number, date, body, items: {"meeting_id": number, "date": date, "body": body, "items": items}
    vote = lambda meeting_id, date, member: {"item_id": f"{meeting_id}-1", "meeting_id": meeting_id, "date": date, "member": member, "vote": "AYE"}
    member = lambda name, first, last, votes: {"name": name, "serving": False, "first_vote": first, "last_vote": last, "votes": votes}
    now = tables([meeting("7", "2024-05-28", "Butte County Board of Supervisors", 0),   # listed bare: the earlier record has its agenda
                  meeting("8", "2024-05-28", "Planning Commission", 0), meeting("9", "2024-08-27", "Butte County Board of Supervisors", 40)],
                 [vote("9", "2024-08-27", "Tami Ritter")], [member("Tami Ritter", "2024-08-27", "2024-09-10", 4)])
    before = tables([meeting("7", "2024-05-28", "Board of Supervisors", 30), meeting("5", "2012-01-10", "Board of Supervisors", 0)],
                    [vote("7", "2024-05-28", "Ritter"), vote("7", "2024-05-28", "Lucero")],
                    [member("Ritter", "2021-06-22", "2024-05-28", 262), member("Lucero", "2021-06-22", "2022-10-25", 108)])
    spec = {"read_from": boards.PAGE, "mark": "g", "bodies": {"Board of Supervisors": "Butte County Board of Supervisors"}}
    joined = boards.with_earlier(now, before, spec)
    assert joined["meetings"]["meeting_id"].tolist() == ["g7", "8", "9"]  # its meeting ids marked; its bare listings left out
    assert joined["meetings"]["body"].tolist()[0] == "Butte County Board of Supervisors"
    assert joined["votes"][["meeting_id", "member"]].values.tolist() == [["g7", "Tami Ritter"], ["g7", "Lucero"], ["9", "Tami Ritter"]]
    ways = boards.read_from({"key": "butte-county", "read_from": boards.SYSTEM}, joined["votes"], joined["meetings"])
    assert ways.tolist() == [boards.PAGE, boards.PAGE, boards.SYSTEM]
    people = joined["members"].set_index("name")
    assert list(people.index) == ["Lucero", "Tami Ritter"]
    assert people.loc["Tami Ritter", ["first_vote", "last_vote", "votes"]].tolist() == ["2021-06-22", "2024-09-10", 266]


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
    monkeypatch.setattr(boards, "publish_county", lambda key, folder, part="": sent.append((key, folder, part)) or True)
    assert council_tables.publish("chrissoria/lake-county-board", tmp_path, "a card of its own", True, "Update") is True
    assert sent == [("lake-county", tmp_path, "")]
    # A county's record in the system it kept before is that county's too, kept apart from its present one.
    earlier = "chrissoria/butte-county-earlier-board"
    assert (council_tables.board_of(earlier), council_tables.part_of(earlier)) == ("butte-county", "earlier")
    assert council_tables.part_of("chrissoria/butte-county-board") == "" and council_tables.part_of("chrissoria/oakland-council") == ""
    council_tables.published(earlier, "votes")
    assert asked[-1] == (boards.REPO, "raw/butte/earlier/votes.parquet")
    council_tables.publish(earlier, tmp_path, "", False, "Update")
    assert sent[-1] == ("butte-county", tmp_path, "earlier")


def test_a_county_not_listed_is_not_published(tmp_path):
    try:
        boards.publish_county("kern-county", tmp_path)
    except ValueError as e:
        assert "kern-county is not among the counties" in str(e)
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


def test_a_county_whose_tables_are_not_kept_here_is_built_from_those_published(monkeypatch, tmp_path):
    facts = boards.facts_of("alpine-county")
    asked = []

    def download(repo, file, **more):
        asked.append(file)
        name = file.rsplit("/", 1)[1][:-len(".parquet")]
        table = pd.DataFrame({column: ["x"] for column in council_tables.COLUMNS[name]})
        for column in boards.WHOLE & set(table.columns):
            table[column] = 1
        if name == "meetings":
            table["date"] = "2026-10-06"
        if name == "members":
            table["serving"] = True
        (tmp_path / "raw" / "alpine").mkdir(parents=True, exist_ok=True)
        table.to_parquet(tmp_path / file, index=False)
        return str(tmp_path / file)

    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", download)
    monkeypatch.setattr(boards, "held_counties", lambda out_dir: pd.DataFrame({"county_fips": [facts["county_fips"]], "read_on": ["2026-10-12"]}))
    row = boards.build_county("alpine-county", tmp_path, folder=tmp_path / "nowhere")
    assert sorted(asked) == sorted(f"raw/alpine/{name}.parquet" for name in boards.TABLES)
    assert (row["county"], row["votes"], row["read_on"]) == ("Alpine", 1, "2026-10-12")  # read when the published table says, not today
    assert (tmp_path / "data" / "votes" / "alpine.parquet").exists()
    # San Diego's own tables are not kept in the dataset, so without them here there is nothing to build it from.
    try:
        boards.build_county("sd-county", tmp_path, folder=tmp_path / "nowhere")
    except FileNotFoundError as e:
        assert "sd-county has no tables here" in str(e)
    else:
        raise AssertionError("built San Diego from nothing")


def test_only_the_boards_own_meetings_are_kept_where_a_system_holds_every_body():
    own = {"meetings": pd.DataFrame({"meeting_id": [1, 2], "body": ["Board of Supervisors", "Planning Commission"]}),
           "agenda_items": pd.DataFrame({"meeting_id": [1, 2], "matter_id": [10, 20]}),
           "votes": pd.DataFrame({"meeting_id": [1, 2], "member": ["A", "B"]}),
           "items": pd.DataFrame({"matter_id": [10, 20]}), "members": pd.DataFrame({"name": ["A"]})}
    kept = boards.the_board(own, r"^Board of Supervisors$")
    assert kept["meetings"]["meeting_id"].tolist() == [1] and kept["votes"]["member"].tolist() == ["A"]
    assert kept["items"]["matter_id"].tolist() == [10] and kept["members"] is own["members"]


def test_a_countys_votes_can_be_held_back_and_its_agendas_kept():
    own = {"votes": pd.DataFrame({"member": ["A"], "vote": ["AYE"]}), "members": pd.DataFrame({"name": ["A"]}),
           "agenda_items": pd.DataFrame({"title": ["An ordinance"], "ayes": [5], "votes_read": [True], "outcome": ["carried 5-0"]}),
           "items": pd.DataFrame({"title": ["An ordinance"], "ayes": [5]}), "meetings": pd.DataFrame({"meeting_id": [1]})}
    held = boards.without_votes(own)
    assert held["votes"].empty and held["members"].empty and list(held["votes"].columns) == ["member", "vote"]
    assert held["agenda_items"]["title"].tolist() == ["An ordinance"] and held["agenda_items"][["ayes", "votes_read", "outcome"]].isna().all().all()
    assert held["items"]["ayes"].isna().all() and held["meetings"] is own["meetings"]
