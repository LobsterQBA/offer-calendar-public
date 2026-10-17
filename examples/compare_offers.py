"""Run three synthetic observations through the dashboard's actual comparison code.

From the repository root: python examples/compare_offers.py
No browser, credentials, network requests, or paid extraction are involved.
"""
from datetime import date
from pathlib import Path
import sys

import pandas as pd

APP_DIR = Path(__file__).resolve().parents[1] / "apps" / "offer-calendar"
sys.path.insert(0, str(APP_DIR))

from change_logic import build_change_events
from dashboard_model import calendar_status, comparison_runs, daily_view
from presentation import business_summary

SELECTED_DAY = date(2026, 9, 16)


def observations(after_price=45, after_status="success", after_description="Same description"):
    """Two dates, one source, one offer. Values are invented for this example."""
    runs, offers = [], []
    for day, price in [(15, 50), (16, after_price)]:
        run_id = f"demo-{day}"
        captured_at = f"2026-09-{day}T16:00:00Z"
        status = "success" if day == 15 else after_status
        runs.append({
            "run_id": run_id,
            "source_id": "example_fiber",
            "observed_at": captured_at,
            "scheduled_for": captured_at,
            "status": status,
            "coverage": "complete",
        })
        if status != "success":
            continue
        offers.append({
            "run_id": run_id,
            "source_id": "example_fiber",
            "offer_id": "example-plan",
            "brand": "Example Internet",
            "product_type": "fiber",
            "observed_at": captured_at,
            "title": "Fiber internet",
            "raw_text": f"Fiber internet ${price}/mo. For eligible new customers.",
            "amounts_raw": f"${price}/mo",
            "description": "Same description" if day == 15 else after_description,
        })
    return daily_view(pd.DataFrame(runs), pd.DataFrame(offers))


def explain(name, **scenario):
    runs, offers = observations(**scenario)
    assessments = build_change_events(comparison_runs(runs), offers, include_diagnostics=True)
    changes = assessments[assessments.event_type.ne("review_only")]
    result = (business_summary(changes.iloc[0]) if not changes.empty
              else calendar_status(runs, SELECTED_DAY, ["example_fiber"]))
    print(f"\n{name}\n  Result: {result}\n  Change candidates: {len(changes)}")
    for reason in assessments.evidence_reason:
        print(f"  Evidence check: {reason}")
    return result, len(changes)


def main():
    print("Offer Calendar | synthetic examples (not current market prices)")
    explain("1. Original source price changes: $50/mo -> $45/mo")
    explain("2. AI description changes; original source stays at $50/mo",
            after_price=50, after_description="Rewritten by extraction")
    explain("3. The second capture fails; the offer is not known to be removed",
            after_status="fetch_failed")


if __name__ == "__main__":
    main()
