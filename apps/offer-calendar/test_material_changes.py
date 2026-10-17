"""Conservative business-change rules; examples labelled synthetic unless noted."""
from datetime import date
import pandas as pd
import pytest
from change_logic import assess_pair, build_change_events, _text


def pair(left, right, **changes):
    before = pd.Series(dict(title="Internet offer", raw_text=left, amounts_raw="$50/mo"))
    after = before.copy()
    after["raw_text"] = right
    for key, value in changes.items():
        after[key] = value
    return assess_pair(before, after)


@pytest.mark.parametrize("value", [None, "No content available", "Not captured", "N/A", "—", "null", "No specific geography stated"])
def test_missing_values(value):
    assert _text(value) == ""


@pytest.mark.parametrize("left,right", [
    ("Internet $50/mo.", "Internet $50.00/month."),
    ("Up to $750 back.", "Up to $750 back. Up to $750 back."),
    ("Internet $50/mo plus $200 gift card.", "Internet $50/mo."),
    ("Internet $50/mo.", "Internet $50/year."),
    ("Internet $50/mo.", "Internet starts here."),
    ("", "Internet $45/mo."),
    ("Internet $50/mo; additional plan $60/mo.", "Internet $45/mo; additional plan $55/mo."),
    ("Up to $50 cashback.", "Up to $50 cashback!"),
])
def test_ambiguous_missing_duplicate_format_or_period_is_not_change(left, right):
    assert pair(left, right, terms="Rewritten", amounts_raw="$45")[0] == []


def test_original_amount_change_survives_unchanged_ai_field():
    fields, summary, reason = pair("Internet $50/mo.", "Internet $45/mo.")
    assert fields == ["amounts_raw"]
    assert "$50 → $45" in summary
    assert reason == "source_backed_amount_change"


def test_reordered_amounts_are_not_a_change():
    assert pair("Internet $50/mo with $200 gift card.", "$200 gift card. Internet $50/mo.")[0] == []


def test_two_explicit_role_matched_changes_are_retained():
    assert pair("Internet $50/mo with $200 gift card.", "Internet $200/mo with $50 gift card.")[0] == ["amounts_raw"]


def test_real_contract_freedom_replay():
    # Read-only live audit: 2026-09-18 and 2026-09-19 source quotes, unmodified.
    before = "Break free from Big Cable contracts. Switch to T-Mobile 5G Home Internet and we'll pay off your early termination fee--up to $750."
    after = before + " We'll reimburse your previous internet service provider's early termination fees when you join T-Mobile Home Internet or Small Business Internet--up to $750 via virtual prepaid card to you."
    fields, _, reason = pair(before, after, audience="Customers switching from another internet provider", geography="Not captured", terms="Requires 60 days of service before validation")
    assert not fields
    assert reason == "excerpt_or_extraction_difference"


def test_real_verizon_conditional_charge_quote_replay():
    # Actual saved quotes, 2026-09-16/17; this tests assessment, NOT run eligibility.
    before = "Disney+, Hulu, ESPN+ (With Ads) included with your plan through an existing VHI plan and switch to an in-market VHI plan... your Verizon account will be charged $19.99/mo or the then-current price... Offer may end without notice."
    after = "If you have Disney+, Hulu, ESPN+ (With Ads) included with your plan through an existing VHI plan and switch to an in-market VHI plan, and do not enroll in the Disney+, Hulu, ESPN+ (With Ads) plan perk, your previously included Disney bundle will no longer be included with your plan and your Verizon account will be charged $21.99/mo or the then-current price of Disney+, Hulu, ESPN+ (With Ads) through Verizon"
    fields, summary, _ = pair(before, after)
    assert fields == ["amounts_raw"]
    assert "$19.99 → $21.99" in summary


def test_synthetic_core_benefit_replacement():
    before = pd.Series(dict(title="Hulu On Us", raw_text="Hulu On Us. Included with this internet plan."))
    after = pd.Series(dict(title="Paramount+ On Us", raw_text="Paramount+ On Us. Included with this internet plan."))
    fields, summary, reason = assess_pair(before, after)
    assert fields == ["title"]
    assert "Hulu On Us → Paramount+ On Us" in summary
    assert reason == "source_backed_core_change"


def test_ai_title_change_without_source_support_is_not_replacement():
    before = pd.Series(dict(title="Hulu On Us", raw_text="Stream all your favorites."))
    after = pd.Series(dict(title="Paramount+ On Us", raw_text="Stream your favorite movies."))
    assert not assess_pair(before, after)[0]


def test_terms_only_stays_in_diagnostics():
    runs = pd.DataFrame([dict(run_id=f"r{i}", source_id="s", report_date=date(2026,9,i), observed_at=f"2026-09-0{i}T16:00:00Z", status="success", coverage="complete") for i in (1,2)])
    offers = pd.DataFrame([dict(run_id=f"r{i}", source_id="s", offer_id="o", report_date=date(2026,9,i), title="Internet", raw_text="Internet $50/mo", terms=str(i)) for i in (1,2)])
    assert build_change_events(runs, offers).empty
    audit = build_change_events(runs, offers, include_diagnostics=True)
    assert audit.event_type.tolist() == ["review_only"]
    assert audit.evidence_reason.tolist() == ["same_source_evidence"]


@pytest.mark.parametrize("coverage,expected", [("complete", {"added", "removed"}), ("partial", set())])
def test_evidenced_offer_replacement_requires_complete_runs(coverage, expected):
    runs = pd.DataFrame([dict(run_id=f"r{i}", source_id="s", report_date=date(2026,9,i), observed_at=f"2026-09-0{i}T16:00:00Z", status="success", coverage=coverage) for i in (1,2)])
    offers = pd.DataFrame([
        dict(run_id="r1", source_id="s", offer_id="old", report_date=date(2026,9,1), title="Free router", raw_text="Free router included with Internet.", product_type="fiber"),
        dict(run_id="r2", source_id="s", offer_id="new", report_date=date(2026,9,2), title="Reward card", raw_text="Reward card: get $200 back.", product_type="fiber"),
    ])
    assert set(build_change_events(runs, offers).event_type) == expected
