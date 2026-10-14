"""
The one shape the tables of a council or a board are published in, whichever
city or county it is and whatever its record is kept in.

Every such dataset has these five tables, each with these columns first and in
this order. A body may have more columns of its own after them (the County's
items have the text of the document; San Diego's votes have the district), and
more tables of its own beside them. What is the same from one body to the next
is what is listed here, so the tables of two bodies can be set one on the other.

  items          every thing that came before the body
  meetings       one row per meeting
  agenda_items   one row per item on a meeting's agenda, with what was done
  votes          one row per member and item acted on
  members        one row per member's time on the body

build_sd_county.py, build_sd_council.py, build_legistar_council.py and the
county readers written for other systems (build_civicclerk_board.py,
build_primegov_board.py, build_iqm2_board.py, build_destiny_board.py,
build_granicus_board.py) or for one county's own documents
(build_sacramento_board.py, build_orange_board.py, build_la_county_board.py,
build_alameda_board.py, build_stanislaus_board.py) each pass their tables
through standard() before writing them. All but the first two also keep and
publish their tables through the functions at the foot of this file.
"""

import re
from pathlib import Path

TABLES = ("items", "meetings", "agenda_items", "votes", "members")

COLUMNS = {
    "items": ["date", "matter_id", "matter_file", "doc_type", "title", "body", "status", "year", "subject", "agenda_date",
              "passed_date", "last_action", "last_action_date", "result", "ayes", "noes", "mover", "seconder",
              "times_on_agenda", "url"],
    "meetings": ["meeting_id", "date", "time", "body", "location", "url", "agenda_url", "minutes_url", "items"],
    "agenda_items": ["item_id", "meeting_id", "date", "body", "agenda_number", "sequence", "matter_id", "matter_file", "title",
                     "action", "result", "mover", "seconder", "ayes", "noes", "not_voting"],
    "votes": ["item_id", "meeting_id", "date", "matter_id", "matter_file", "member", "vote"],
    "members": ["name", "district", "role", "start", "end", "serving", "first_vote", "last_vote", "votes"],
}

# A vote is one of these words. Aye and no are spelled one way; any other word is the body's own, in capitals.
AYE, NO = "AYE", "NO"
VOTE_WORDS = {"AYES": AYE, "YES": AYE, "YEA": AYE, "YEAS": AYE, "VOTING YES": AYE, "NOES": NO, "NOE": NO, "NAY": NO, "NAYS": NO, "VOTING NO": NO}


def vote_word(word):
    """A body's word for a vote, as the tables have it."""
    word = " ".join(str(word or "").upper().split())
    return VOTE_WORDS.get(word, word)


def standard(tables):
    """The tables in the one shape: the shared columns first and in order, then the body's own as it had them.

    Raises if a shared table or column is missing: a body that cannot fill a column still has it, empty.
    """
    out = dict(tables)
    for name in TABLES:
        if name not in tables:
            raise ValueError(f"no {name} table")
        table = tables[name]
        missing = [column for column in COLUMNS[name] if column not in table.columns]
        if missing:
            raise ValueError(f"the {name} table has no {', '.join(missing)}")
        out[name] = table[COLUMNS[name] + [column for column in table.columns if column not in COLUMNS[name]]]
    return out


# ---------------------------------------------------------------------------
# Keeping and publishing the tables
# ---------------------------------------------------------------------------

# A county's board has no dataset of its own. Its tables are that county's files in the one dataset of county boards
# (build_ca_county_boards.py): as its reader wrote them under raw/<county>/, and in the shape every county has under data/.
# A reader still names where its tables go as it always did, "chrissoria/<county>-county-board", and is sent on from here.
COUNTY_BOARDS = "chrissoria/ca-county-boards"
BOARD = re.compile(r"chrissoria/([a-z-]+-county)(-earlier)?-board")
EARLIER = "earlier"  # the record a county kept in another system before the one it has now, where both are read


def board_of(repo):
    """The county whose board a reader's tables are for ("fresno-county"), or None if `repo` is a dataset of its own."""
    found = BOARD.fullmatch(repo)
    return found[1] if found else None


def part_of(repo):
    """EARLIER if a reader's tables are those of a county's earlier record ("chrissoria/butte-county-earlier-board"), else ""."""
    found = BOARD.fullmatch(repo)
    return EARLIER if found and found[2] else ""


def published(repo, name):
    """A table of a dataset as last published, or None. A county board's is the one its reader last wrote."""
    import pandas as pd
    import build_federal_bills as bills
    county = board_of(repo)
    part = f"{part_of(repo)}/" if part_of(repo) else ""
    place, file = (COUNTY_BOARDS, f"raw/{county[:-len('-county')]}/{part}{name}.parquet") if county else (repo, f"data/{name}.parquet")
    try:
        from huggingface_hub import hf_hub_download
        return pd.read_parquet(hf_hub_download(place, file, repo_type="dataset", token=bills.HF_TOKEN))
    except Exception:
        return None


def held(repo, out_dir, name, base):
    """The table a run starts from: what is published, or failing that what was last written here.

    A whole run looks here first: it is run by hand and stopped and started, so what it has written is further on than
    what is published. The routine run looks at what is published first: it may be run where nothing was written before.
    """
    import pandas as pd
    path = Path(out_dir) / f"{name}.parquet"
    local = lambda: pd.read_parquet(path) if path.exists() else None
    first, second = (local, lambda: published(repo, name)) if base else (lambda: published(repo, name), local)
    found = first()
    return found if found is not None else second()


def write_tables(tables, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        table.to_parquet(out_dir / f"{name}.parquet", index=False)


def publish(repo, out_dir, card, with_card, message):
    """Publish the five tables written in `out_dir`, and the card if asked for or if the dataset has none.

    A county board's tables go into the one dataset of county boards, as that county's files; the card there is the one
    card for all of them, so `card` is not used. Raises PermissionError if the token may not write.
    """
    import build_federal_bills as bills
    if board_of(repo):
        import build_ca_county_boards
        return build_ca_county_boards.publish_county(board_of(repo), out_dir, part=part_of(repo))
    from huggingface_hub import CommitOperationAdd, HfApi
    hub = HfApi(token=bills.HF_TOKEN)
    hub.create_repo(repo, repo_type="dataset", exist_ok=True)
    problem = bills.hf_write_problem(repo)
    if problem:
        raise PermissionError(problem)
    operations = [CommitOperationAdd(path_in_repo=f"data/{name}.parquet", path_or_fileobj=str(Path(out_dir) / f"{name}.parquet"))
                  for name in TABLES]
    if card and (with_card or "README.md" not in set(hub.list_repo_files(repo, repo_type="dataset"))):
        operations.append(CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=card.encode("utf-8")))
    hub.create_commit(repo_id=repo, repo_type="dataset", operations=operations, commit_message=message)
