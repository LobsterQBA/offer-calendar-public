from datetime import date

import pandas as pd
import pytest

from data_access import attach_page_evidence
from presentation import business_summary, highlighted_evidence, markdown_literal, product_links, screenshot_html


@pytest.mark.parametrize("raw,expected", [
    ("Amount (month, stated): $50 → $45", "Monthly amount: $50 → $45"),
    ("Value (month, stated): $8.99 → $9.99", "Monthly benefit value: $8.99 → $9.99"),
    ("Reward (unspecified, up to): $200 → $300", "Reward (up to): $200 → $300"),
    ("Reimbursement (unspecified, up to): $650 → $750", "Reimbursement (up to): $650 → $750"),
    ("Discount (month, stated): $5 → $10", "Monthly discount: $5 → $10"),
    ("Fee (unspecified, stated): $35 → $0", "Fee: $35 → $0"),
    ("Amount (year, from): £100 → £90", "Annual amount (starting at): £100 → £90"),
])
def test_money_labels_preserve_type_qualifier_and_period(raw, expected):
    assert business_summary({"event_type": "modified", "evidence_reason": "source_backed_amount_change", "change_summary": raw}) == expected


def test_presence_is_observation_not_launch_or_withdrawal_claim():
    assert business_summary({"event_type": "added"}) == "Newly observed offer"
    assert business_summary({"event_type": "removed"}) == "Offer no longer observed"


def test_currency_does_not_become_latex_in_streamlit_labels():
    assert markdown_literal("Monthly amount: $50 → $45") == r"Monthly amount: \$50 → \$45"


@pytest.mark.parametrize("word,label", [("gift card", "Gift card"), ("cashback", "Cashback")])
def test_specific_reward_needs_both_original_contexts(word, label):
    event = {"event_type": "modified", "evidence_reason": "source_backed_amount_change", "change_summary": "Reward (unspecified, stated): $100 → $200", "before": {"raw_text": f"Get a $100 {word}."}, "after": {"raw_text": f"Get a $200 {word}."}}
    assert business_summary(event) == f"{label}: $100 → $200"
    event["after"]["raw_text"] = "Get a $200 reward."
    assert business_summary(event) == "Reward: $100 → $200"


def test_switch_product_preserves_filters():
    links = product_links(date(2026, 9, 16), "AT&T")
    assert set(links) == {"HSI", "Fiber"}
    assert links["HSI"].endswith("/?day=2026-09-16&brand=AT%26T")


def test_highlight_literal_differences_and_escape_source_html():
    left, right = highlighted_evidence('Plan <script> $50 per month.', 'Plan <script> $45 per month.')
    assert "<script>" not in left
    assert "&lt;script&gt;" in left
    assert '<mark>$50</mark>' in left
    assert '<mark>$45</mark>' in right
    assert highlighted_evidence("Same offer", "Same offer") == ("Same offer", "Same offer")


def test_screenshot_pixels_are_not_modified_and_frame_is_same_size():
    for scope in ["page", "offer_card", "unknown"]:
        rendered = screenshot_html(b"original-bytes", scope)
        assert "b3JpZ2luYWwtYnl0ZXM=" in rendered
        assert "height:510px;overflow:auto" in rendered
        assert 'aria-label="Screenshot zoom"' in rendered
    assert "object-fit:contain" in screenshot_html(b"image", "offer_card")


def test_full_page_never_backfills_another_run_or_day():
    offers = pd.DataFrame([{"run_id": "old", "screenshot_uri": None}])
    evidence = pd.DataFrame([{"run_id": "new", "captured_at": "2026-09-21T10:00:00Z", "volume_path": "/Volumes/new.png"}])
    attached = attach_page_evidence(offers, evidence)
    assert attached.iloc[0].screenshot_uri is None
    assert attached.iloc[0].page_screenshot_uri is None
