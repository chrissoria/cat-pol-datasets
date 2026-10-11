"""The roster reads cabinet posts from Senate nominations, and only those."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_executive_roster as roster


def nomination(description, action, day, received="2025-01-20", number=11, part="8"):
    return {"description": description, "latestAction": {"text": action, "actionDate": day}, "receivedDate": received,
            "congress": 119, "number": number, "partNumber": part, "citation": f"PN{number}-{part}", "organization": "Department"}


def test_posts_are_matched_and_lesser_posts_are_not():
    assert roster.post_of("Robert F. Kennedy, Jr., of California, to be Secretary of Health and Human Services.") == (
        "Secretary of Health and Human Services", "Cabinet", "health")
    assert roster.post_of("A B, of Ohio, to be Deputy Secretary of State.") is None
    assert roster.post_of("A B, of Ohio, to be an Assistant Secretary of Defense, vice C D.") is None
    assert roster.post_of("A B, of Ohio, to be Deputy Attorney General.") is None
    assert roster.post_of("A B, of Ohio, to be Secretary of War.") == ("Secretary of Defense", "Cabinet", "defense")
    assert roster.post_of("A B, of Ohio, to be Representative of the United States of America to the Sessions of the General Assembly of the United Nations.") is None


def test_a_successor_makes_the_earlier_holder_former():
    rows = roster.cabinet_rows([
        nomination("Pamela Bondi, of Florida, to be Attorney General.", "Confirmed by the Senate by Yea-Nay Vote. 54 - 46. Record Vote Number: 33.", "2025-02-04"),
        nomination("Todd Blanche, of Florida, to be Attorney General, vice Pamela Bondi.", "Confirmed by the Senate by Voice Vote.", "2026-08-08", "2026-07-01", 1078, None),
        nomination("X Y, of Texas, to be Attorney General.", "Received message of withdrawal of nomination from the President.", "2026-06-01", "2026-05-01", 900, None),
        nomination("Old Hand, of Utah, to be Secretary of Labor.", "Confirmed by the Senate by Voice Vote.", "2021-03-01", "2021-01-20", 5, None),
    ], "2025-01-20")
    assert [(row["name"], row["status"], row["end_date"], row["confirmation_vote"]) for row in rows] == [
        ("Pamela Bondi", "former", "2026-08-08", "54-46"), ("Todd Blanche", "serving", "", "voice vote")]
    assert rows[1]["nomination_url"].endswith("/119th-congress/1078") and rows[0]["nomination_url"].endswith("/119th-congress/11/8")


def test_term_start_and_congresses():
    assert roster.term_start(date(2026, 10, 10)) == "2025-01-20"
    assert roster.term_start(date(2029, 1, 19)) == "2025-01-20"
    assert roster.term_start(date(2029, 1, 20)) == "2029-01-20"
    assert roster.congresses_since("2025-01-20")[0] == 119
