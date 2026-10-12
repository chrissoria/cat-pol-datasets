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

build_sd_county.py, build_sd_council.py and build_legistar_council.py each
pass their tables through standard() before writing them.
"""

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
VOTE_WORDS = {"AYES": AYE, "YES": AYE, "YEA": AYE, "YEAS": AYE, "NOES": NO, "NOE": NO, "NAY": NO, "NAYS": NO}


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
