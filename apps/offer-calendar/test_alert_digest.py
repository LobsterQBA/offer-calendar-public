"""Synthetic email parity checks; never send email during tests."""
from datetime import date
import pandas as pd
from alert_digest import daily_digest


def frames(price=45, status="success", product="fiber"):
    runs = pd.DataFrame([dict(run_id=f"r{i}", source_id="s", observed_at=f"2026-09-{i:02}T16:00:00Z", scheduled_for=f"2026-09-{i:02}T16:00:00Z", status="success" if i == 29 else status, coverage="partial") for i in (29, 30)])
    offers = pd.DataFrame([dict(run_id=f"r{i}", source_id="s", offer_id="o", snapshot_id=f"sn{i}", observed_at=f"2026-09-{i:02}T16:00:00Z", title="Internet", raw_text=f"Internet ${50 if i == 29 else price}/mo.", brand="AT&T", product_type=product, amounts_raw=f"${50 if i == 29 else price}/mo.") for i in (29, 30)])
    offers["deal_type"] = "standard_pricing"
    return runs, offers


def test_real_amount_change_includes_fiber_link():
    result = daily_digest(*frames(), date(2026, 9, 30))
    assert result["change_count"] == 1
    assert "$50 → $45" in result["summary"]
    assert "offer-calendar-fiber" in result["summary"]


def test_no_change_or_failed_capture_never_alerts():
    assert daily_digest(*frames(price=50), date(2026, 9, 30))["change_count"] == 0
    assert daily_digest(*frames(status="fetch_failed"), date(2026, 9, 30))["change_count"] == 0


def test_hsi_and_old_dates():
    assert "offer-calendar-hsi" in daily_digest(*frames(product="fixed_wireless"), date(2026, 9, 30))["summary"]
    assert daily_digest(*frames(), date(2026, 10, 1))["change_count"] == 0
