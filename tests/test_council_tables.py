"""council_tables is the one shape every council's and board's tables are written in."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import council_tables as shape


def tables(**extra):
    out = {name: pd.DataFrame(columns=list(reversed(shape.COLUMNS[name]))) for name in shape.TABLES}
    out.update(extra)
    return out


def test_a_vote_is_aye_or_no_however_a_body_spells_them_and_otherwise_its_own_word_in_capitals():
    assert [shape.vote_word(word) for word in ("Aye", "Ayes", "Yes", "yea")] == ["AYE"] * 4
    assert [shape.vote_word(word) for word in ("No", "Noes", "NOE", "Nay")] == ["NO"] * 4
    assert [shape.vote_word(word) for word in ("Voting Yes", "Voting No")] == ["AYE", "NO"]  # as Napa County's clerk has them
    assert shape.vote_word(" Not  Present ") == "NOT PRESENT" and shape.vote_word("Excused") == "EXCUSED" and shape.vote_word(None) == ""


def test_the_shared_columns_come_first_and_in_order_and_a_bodys_own_after_as_it_had_them():
    votes = pd.DataFrame(columns=["district", "vote", "member", "matter_file", "matter_id", "date", "meeting_id", "item_id", "note"])
    rosters = pd.DataFrame(columns=["meeting_id", "name"])
    out = shape.standard(tables(votes=votes, rosters=rosters))
    assert list(out["votes"].columns) == shape.COLUMNS["votes"] + ["district", "note"]
    assert all(list(out[name].columns) == shape.COLUMNS[name] for name in shape.TABLES if name != "votes")
    assert out["rosters"] is rosters  # a table of the body's own is left as it is


def test_a_body_that_lacks_a_shared_table_or_column_is_refused():
    with pytest.raises(ValueError, match="no members table"):
        shape.standard({name: table for name, table in tables().items() if name != "members"})
    with pytest.raises(ValueError, match="the meetings table has no location, url"):
        shape.standard(tables(meetings=pd.DataFrame(columns=[c for c in shape.COLUMNS["meetings"] if c not in ("location", "url")])))
