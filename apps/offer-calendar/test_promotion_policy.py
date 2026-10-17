import ast
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from promotion_policy import classify_deal, deal_details, deal_headline, consolidate_deals, promotion_prompt, promotion_tags
from dashboard_model import collection_method, promotion_records, inventory_records


@pytest.mark.parametrize("title,expected", [
    ("AT&T Internet Air®", "standard_pricing"),
    ("5G Home Ultimate", "standard_pricing"),
    ("24/7 live assistance with video support.", "included_benefit"),
    ("5-Year Price Guarantee", "included_benefit"),
    ("Apple AirPods 4 On Us .", "promotion"),
    ("Early termination fee payoff", "promotion"),
    ("Get a Month On Us, plus up to $200 back.", "promotion"),
    ("Hulu On Us .", "included_benefit"),
    ("Paramount+ Essential Plan for Internet On Us .", "included_benefit"),
    ("NY Affordable Broadband Act", "marketing"),
    ("Amazon Gift Card", "promotion"),
    ("Auto Pay discount", "standard_pricing"),
    ("Mobile + Home Discount", "standard_pricing"),
    ("YouTube TV $20/mo off for 6 months", "promotion"),
    ("Free stuff & great deals from brands you love.", "included_benefit"),
    ("Your fastest move on moving day.", "marketing"),
    ("Get $300 back when you activate Business Internet", "marketing"),
    ("Refer your friends and earn up to $500.", "promotion"),
    ("Save $3.99/mo YouTube Premium", "included_benefit"),
])
def test_user_examples(title, expected):
    assert classify_deal({"title": title, "raw_text": title + " Terms apply."})[0] == expected


def test_generic_plan_with_many_rewards_is_review_not_one_deal():
    row = {"title": "5G Home Ultimate", "raw_text": "5G Home Ultimate $72/mo. $200 Amazon gift card. Save $9.99/mo on streaming."}
    assert classify_deal(row)[0] == "review"


def test_offer_details_is_not_a_discount():
    row = {"title": "AT&T Internet Air®", "raw_text": "AT&T Internet Air® Starting at $55/mo. See offer details."}
    assert classify_deal(row)[0] == "standard_pricing"
    row["raw_text"] = "AT&T Internet Air® $10 off for 6 months."
    assert classify_deal(row)[0] == "review"


def test_fiber_headline_labels_speed_not_price():
    row = {"title": "AT&T Internet 1000", "raw_text": "AT&T Internet 1000 Up to 1 GIG speed Was $90. Now $65."}
    assert deal_headline(row) == "AT&T Fiber · 1 GIG"
    assert row["title"] == "AT&T Internet 1000"


def test_unsupported_ai_headline_does_not_create_promotion():
    assert classify_deal({"title": "Get $200 back", "raw_text": "Internet service for $55/mo."})[0] == "review"


def test_real_replay_campaigns_need_more_than_keywords():
    seasonal = {"title": "NFL Sunday Ticket from YouTube, on us", "raw_text": "Last Chance. Ends 9/23. NFL Sunday Ticket from YouTube, on us. For the 2026 NFL season."}
    assert classify_deal(seasonal)[0] == "promotion"
    switch = {"title": "Get up to $500 credit to help you switch", "raw_text": "Get up to $500 credit to help you switch. We'll cover early termination fees."}
    assert classify_deal(switch)[0] == "promotion"
    ai = {"title": "Special Offer", "reward_text": "Get 6 months of the Google AI Pro perk on us.", "raw_text": "Special Offer. Get 6 months of the Google AI Pro perk on us. $10/mo after."}
    assert classify_deal(ai)[0] == "promotion"
    assert deal_headline(ai) == ai["reward_text"]
    assert classify_deal(dict(ai, reward_text="Get 12 months on us"))[0] == "review"


def test_contained_excerpts_only_merge_same_headline():
    a = {"title": "Get $200 back", "raw_text": "Get $200 back. New customers."}
    b = dict(a, raw_text=a["raw_text"] + " Terms apply.")
    c = dict(a, raw_text="Get $200 back. Existing customers.")
    assert consolidate_deals([a, b, c]) == [b, c]


@pytest.mark.parametrize("title", ["Save $3.99/mo YouTube Premium", "$9.99/mo Disney+, Hulu, ESPN+ (With Ads)"])
def test_neighbor_gift_card_does_not_become_streaming_value(title):
    row = dict(title=title, raw_text=title + " Special gift on us. Get a $200 Amazon Gift Card.",
               amounts_raw="$200", reward_text="Get a $200 Amazon Gift Card")
    assert classify_deal(row)[0] == "review"
    assert inventory_records(pd.DataFrame([dict(row, run_id="fios")])).empty


def test_explicit_combined_gift_and_streaming_campaign_stays_visible():
    title = "A $250 Amazon Gift Card. Plus, Disney+ for 12 months on us."
    assert classify_deal(dict(title=title, raw_text=title))[0] == "promotion"


def test_inventory_contains_one_full_benefit_not_two_excerpts():
    a = dict(run_id="one", title="5-year price guarantee", raw_text="5-year price guarantee. Eligible customers.")
    b = dict(a, raw_text=a["raw_text"] + " Base monthly rate only.")
    c = dict(a, raw_text="5-year price guarantee. Different qualifying plan.")
    other_day = dict(a, run_id="two")
    result = inventory_records(pd.DataFrame([a, b, c, other_day]))
    assert len(result) == 3
    assert a["raw_text"] not in result[result.run_id.eq("one")].raw_text.tolist()


def test_metadata_is_quote_checked_and_roundtrips():
    row = {"title": "Get $200 back", "raw_text": "Get $200 back. For 6 months. New customers only.",
           "reward_text": "Get $200 back", "duration_text": "For 6 months.", "plan_context": "Ultimate"}
    stored = dict(row, tags=promotion_tags(row), duration_text=None, reward_text=None)
    assert deal_details(stored)["duration_text"] == "For 6 months."
    assert deal_details(stored)["plan_context"] == ""
    assert deal_details(dict(row, tags=float("nan")))["reward_text"] == "Get $200 back"


def test_no_cross_run_or_terms_deduplication():
    frame = pd.DataFrame([
        {"run_id": run, "title": "Get $200 back", "raw_text": raw}
        for run, raw in [("a", "Get $200 back. New customers."), ("a", "Get $200 back. New customers."),
                         ("b", "Get $200 back. New customers."), ("a", "Get $200 back. Existing customers.")]])
    assert len(promotion_records(frame)) == 3


def test_migration_does_not_compare_broad_and_promotion_collectors():
    assert collection_method({"diagnostics_uri": "/x/promotion_collection_v1/run/diagnostics.json"}) != collection_method({"diagnostics_uri": "/x/rendered_collection/run/diagnostics.json"})


def test_standalone_collector_shares_policy_and_validates_quotes():
    path = Path(__file__).resolve().parents[2] / "collector/collector.py"
    spec = importlib.util.spec_from_file_location("promotion_collector", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.promotion_prompt("AT&T", "fiber") == promotion_prompt("AT&T", "fiber")
    good = {"title": "Get $200 back", "raw_text": "Get $200 back with qualifying internet.", "reward_text": "Get $500 back"}
    accepted, rejected = module.validate_offers([good], good["raw_text"])
    assert not rejected
    assert accepted[0]["reward_text"] is None
    assert accepted[0]["raw_text"] == good["raw_text"]
