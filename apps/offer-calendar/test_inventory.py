from datetime import date
import json
import pandas as pd
from dashboard_model import inventory_records, calendar_status, daily_view
from email_alerts import draft_change_email
from test_dashboard_model import run, offer
from promotion_policy import promotion_tags


def test_fiber_pricing_metadata_survives_json_transport():
    row = dict(run_id="a", brand="AT&T", title="AT&T Internet 1000",
               raw_text="AT&T Internet 1000 Up to 1 GIG speed Was $90. Now $65.",
               deal_type="standard_pricing")
    row["tags"] = json.dumps(promotion_tags(row))
    del row["deal_type"]
    found = inventory_records(pd.DataFrame([row]))
    assert found.iloc[0].deal_scope == "standard_pricing"
    assert found.iloc[0].display_title == "AT&T Fiber · 1 GIG"


def test_inventory_keeps_benefits_and_att_prices_not_generic_other_plans():
    rows = []
    for i, (brand, title) in enumerate([("T-Mobile", "Hulu On Us"), ("T-Mobile", "24/7 live assistance"),
        ("T-Mobile", "Free stuff & great deals from brands you love."), ("AT&T", "AT&T Internet Air"),
        ("Verizon", "5G Home Ultimate"), ("T-Mobile", "Your fastest move on moving day.")]):
        rows.append(dict(run_id="a", brand=brand, title=title, raw_text=title + " $55/mo. Terms apply."))
    found = inventory_records(pd.DataFrame(rows))
    assert len(found) == 4
    assert set(found.deal_scope) == {"included_benefit", "standard_pricing"}


def test_calendar_never_calls_first_or_failed_observation_no_change():
    a, b = "2026-09-20T14:00:00Z", "2026-09-21T15:00:00Z"
    runs, _ = daily_view(pd.DataFrame([run("a", a), run("b", b)]), pd.DataFrame([offer("a", a), offer("b", b)]))
    assert calendar_status(runs, date(2026,9,20)) == "First observation"
    assert calendar_status(runs, date(2026,9,21)) == "No change"
    assert calendar_status(runs, date(2026,9,21), ["att", "tmobile"]) == "Missing sources"
    runs.loc[runs.run_id.eq("b"), "status"] = "partial"
    assert calendar_status(runs, date(2026,9,21)) == "Collection incomplete"


def test_email_is_preview_only_and_filters_diagnostics_and_other_dates():
    day = date(2026,9,24)
    rows = pd.DataFrame([dict(report_date=day, event_type="review_only"), dict(report_date=date(2026,9,23), event_type="modified")])
    assert draft_change_email(rows, day, "HSI") is None
    rows = pd.DataFrame([dict(report_date=day, event_type="modified", brand="T-Mobile", before_date=date(2026,9,23),
        after_date=day, change_summary="Monthly value: $11.99 to $12.49", before={}, after={})])
    email = draft_change_email(rows, day, "HSI")
    assert "1 changes" in email["Subject"]
    assert "To" not in email and "From" not in email
    assert "No email has been sent" in email.get_content()


def test_streaming_summary_collapses_into_exact_priced_tile():
    short = dict(run_id="one", title="Save $3.99/mo YouTube Premium",
                 raw_text="Save $3.99/mo\nYouTube Premium")
    card = dict(run_id="one", title="\u200bYouTube Premium",
                raw_text="\u200bYouTube Premium\nDetails\n$12\n/mo\nSave $3.99/mo")
    frame = pd.DataFrame([short, card])
    result = inventory_records(frame)
    assert len(result) == 1
    assert result.iloc[0].raw_text == card["raw_text"]
    assert len(frame) == 2  # Storage evidence is not mutated.
    assert len(inventory_records(pd.DataFrame([short, dict(card, run_id="two")]))) == 2


def test_streaming_terms_and_different_savings_do_not_merge():
    short = dict(run_id="one", title="Save $3.99/mo YouTube Premium",
                 raw_text="Save $3.99/mo YouTube Premium")
    for raw in ["YouTube Premium Details $12 /mo Save $4.99/mo",
                "YouTube Premium Details $12 /mo Save $3.99/mo New customers only.",
                "YouTube Premium Details $12 /mo Save $3.99/mo Get a $200 Gift Card."]:
        card = dict(run_id="one", title="YouTube Premium", raw_text=raw)
        # Review-only gift-card records are excluded separately, not merged.
        from promotion_policy import consolidate_deals
        assert len(consolidate_deals([short, card])) == 2
