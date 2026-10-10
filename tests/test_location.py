"""classify_location on action lists shaped like Congress.gov's (newest first)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build_federal_bills import classify_location, compact_actions  # noqa: E402


def act(date, kind, text, code="", committees=(), source=""):
    return {
        "actionDate": date, "type": kind, "text": text, "actionCode": code,
        "committees": [{"systemCode": c, "name": n} for c, n in committees],
        "sourceSystem": {"name": source},
    }


SMALL_BUSINESS = [("hssm00", "Small Business Committee")]
INTRO = [
    act("2025-07-22", "IntroReferral", "Referred to the House Committee on Small Business.", "H11100", SMALL_BUSINESS, "House floor actions"),
    act("2025-07-22", "IntroReferral", "Introduced in House", "1000", (), "Library of Congress"),
    act("2025-07-22", "IntroReferral", "Introduced in House", "Intro-H", (), "Library of Congress"),
]


def where(actions, bill_type="HR", origin="House"):
    return classify_location(compact_actions(actions), bill_type, origin)


def test_duplicates_from_two_source_systems_collapse():
    assert [a["text"] for a in compact_actions(INTRO)] == [
        "Referred to the House Committee on Small Business.", "Introduced in House"]


def test_introduced_only_is_in_the_hopper():
    assert where(INTRO[1:])["kind"] == "hopper"


def test_referred_bill_is_in_its_committee():
    loc = where(INTRO)
    assert (loc["kind"], loc["chamber"], loc["committee_code"]) == ("committee", "House", "hssm00")


def test_primary_committee_is_the_one_named_first():
    referral = act(
        "2026-10-05", "IntroReferral",
        "Referred to the Committee on Energy and Commerce, and in addition to the Committee on Ways and Means, "
        "for a period to be subsequently determined by the Speaker.", "H11100",
        [("hswm00", "Ways and Means Committee"), ("hsif00", "Energy and Commerce Committee")], "House floor actions")
    loc = where([referral] + INTRO[1:])
    assert (loc["committee_code"], loc["extra_referrals"]) == ("hsif00", 1)


def test_subcommittee_referral_maps_to_the_parent_committee():
    referral = act("2026-09-01", "Committee", "Referred to the Subcommittee on Health.", "", [("hsif14", "Health Subcommittee")], "House committee actions")
    assert where([referral] + INTRO)["committee_code"] == "hsif00"


def test_reported_then_calendared_is_on_the_calendar():
    actions = [
        act("2026-10-09", "Calendars", "Placed on the Union Calendar, Calendar No. 746.", "H12410", (), "House floor actions"),
        act("2026-10-09", "Committee", "Reported (Amended) by the Committee on Small Business. H. Rept. 119-84", "H12200", SMALL_BUSINESS, "House floor actions"),
    ] + INTRO
    loc = where(actions)
    assert (loc["kind"], loc["chamber"]) == ("calendar", "House")


def test_passed_origin_chamber_goes_to_the_other_chamber():
    actions = [
        act("2026-09-20", "Floor", "Motion to reconsider laid on the table Agreed to without objection.", "H38310", (), "House floor actions"),
        act("2026-09-20", "Floor", "On passage Passed by the Yeas and Nays: 300 - 120 (Roll no. 400).", "H37100", (), "House floor actions"),
    ] + INTRO
    loc = where(actions)
    assert (loc["kind"], loc["chamber"]) == ("other_chamber", "Senate")


def test_referred_in_second_chamber_is_in_that_committee():
    actions = [
        act("2026-09-22", "IntroReferral", "Received in the Senate and Read twice and referred to the Committee on Finance.", "", [("ssfi00", "Finance Committee")], "Senate"),
        act("2026-09-20", "Floor", "On passage Passed by the Yeas and Nays: 300 - 120 (Roll no. 400).", "H37100", (), "House floor actions"),
    ] + INTRO
    loc = where(actions)
    assert (loc["kind"], loc["chamber"], loc["committee_code"]) == ("committee", "Senate", "ssfi00")


def test_second_chamber_passage_without_amendment_heads_to_the_president():
    actions = [
        act("2026-10-01", "Floor", "Message on Senate action sent to the House.", "", (), "Senate"),
        act("2026-10-01", "Floor", "Passed Senate without amendment by Unanimous Consent.", "", (), "Senate"),
    ] + INTRO
    assert where(actions)["kind"] == "president"


def test_second_chamber_amendment_sends_it_back_to_resolve_differences():
    actions = [act("2026-10-01", "Floor", "Passed Senate with an amendment by Unanimous Consent.", "", (), "Senate")] + INTRO
    loc = where(actions)
    assert (loc["kind"], loc["chamber"]) == ("conference", "House")


def test_presented_signed_and_enacted():
    presented = [act("2026-10-03", "Floor", "Presented to President.", "E20000", (), "House floor actions")] + INTRO
    assert where(presented)["kind"] == "president"
    signed = [act("2026-10-06", "President", "Signed by President.", "E30000", (), "Library of Congress")] + presented
    assert where(signed)["kind"] == "law"
    law = [act("2026-10-06", "BecameLaw", "Became Public Law No: 119-119.", "E40000", (), "Library of Congress")] + signed
    assert where(law)["kind"] == "law"


def test_veto():
    actions = [act("2026-10-06", "Veto", "Vetoed by President.", "E31000", (), "Library of Congress")] + INTRO
    assert where(actions)["kind"] == "vetoed"


def test_simple_resolution_agreed_to_is_adopted():
    actions = [act("2026-10-01", "Floor", "Submitted in the Senate, considered, and agreed to without amendment and with a preamble by Unanimous Consent.", "", (), "Senate")]
    assert where(actions, "SRES", "Senate")["kind"] == "adopted"


def test_no_actions_gives_no_answer():
    assert where([])["kind"] == ""


def test_subcommittee_referral_without_a_code_stays_with_the_earlier_committee():
    referral = act("2026-09-01", "Committee", "Referred to the Subcommittee on Federal Lands.", "", (), "House committee actions")
    loc = where([referral] + INTRO)
    assert (loc["kind"], loc["committee_code"]) == ("committee", "hssm00")


def test_multiple_referral_listed_once_per_committee_keeps_the_primary_first():
    text = ("Referred to the Committee on Energy and Commerce, and in addition to the Committee on Ways and Means, "
            "for a period to be subsequently determined by the Speaker.")
    actions = [
        act("2026-10-05", "IntroReferral", text, "H11100", [("hswm00", "Ways and Means Committee")], "House floor actions"),
        act("2026-10-05", "IntroReferral", text, "H11100", [("hsif00", "Energy and Commerce Committee")], "House floor actions"),
    ] + INTRO[1:]
    loc = where(actions)
    assert (loc["committee_code"], loc["extra_referrals"]) == ("hsif00", 1)
