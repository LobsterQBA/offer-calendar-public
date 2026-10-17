"""Offline regression checks for omissions and unsupported extraction evidence."""
import importlib.util
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("collector", Path(__file__).with_name("collector.py"))
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class CollectionTests(unittest.TestCase):
    def test_paid_att_addons_require_named_source_block(self):
        text = "AT&T All-Fi Pro\n$25.00 /.mo plus taxes\nEquipment upgrade program\nMesh Wi-Fi extenders\nAT&T ActiveArmor Advanced Security\nWi-Fi personalization\nLimited availability/areas.\nAdd All-Fi Pro"
        for title in ["AT&T All-Fi Pro", "Equipment upgrade program"]:
            self.assertTrue(collector.att_paid_addon_excluded("att_fiber_plans", dict(title=title), text))
            self.assertFalse(collector.att_paid_addon_excluded("att_fiber_deals", dict(title=title), text))
            self.assertFalse(collector.att_paid_addon_excluded("att_fiber_plans", dict(title=title), title + " included at no extra charge"))
        self.assertFalse(collector.att_paid_addon_excluded("att_fiber_plans", dict(title="AT&T Internet 1000"), text))
        self.assertFalse(collector.att_paid_addon_excluded("att_fiber_plans", dict(title="Get All-Fi Pro on us"), text))
        self.assertTrue(collector.att_paid_addon_excluded("att_fiber_plans", dict(title="AT&T All‑Fi Pro"), text))
        self.assertTrue(collector.att_paid_addon_excluded("att_fiber_plans", dict(title="Equipment upgrade program"), "equipment upgrade program " + text))

    def test_perk_credit_keeps_original_qualifying_plan(self):
        html = '<div class="plan-highlight-header">Get $10 on us towards a perk<div>As a Mobile + Home customer, get up to $10/mo when you select and maintain a 5G Ultimate plan.</div></div><div>Get $200 back</div>'
        card = collector.verizon_perk_credit_cards(html)[0]
        self.assertEqual(card["title"], "Get $10 on us towards a perk")
        self.assertEqual(card["amounts_raw"], "up to $10/mo")
        self.assertEqual(card["plan_context"], "5G Ultimate plan")
        self.assertNotIn("$200", card["raw_text"])
        self.assertEqual(collector.verizon_perk_credit_cards(html.replace("5G Ultimate plan", "unknown plan")), [])

    def test_verizon_streaming_savings_stop_at_tile_boundary(self):
        html = '<div class="promo-tile"><h4>YouTube Premium</h4><span>$12/mo</span><span>Save $3.99/mo</span></div><div>Get a $200 Amazon Gift Card</div>'
        cards = collector.verizon_perk_cards(html)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["amounts_raw"], "Save $3.99/mo")
        self.assertNotIn("$200", cards[0]["raw_text"])
        self.assertEqual(collector.classify_deal(cards[0])[0], "included_benefit")
        self.assertEqual(collector.verizon_perk_cards('<div class="promo-tile"><h4>YouTube Premium</h4></div>'), [])

    def test_terminal_period_restores_exact_source_not_changed_money(self):
        source = "3-year price guarantee: For new customers. Base monthly rate only"
        accepted, rejected = collector.validate_offers([dict(title="3-year price guarantee",
            raw_text=source + ".", terms="Base monthly rate only.")], source)
        self.assertFalse(rejected)
        self.assertEqual(accepted[0]["raw_text"], source)
        self.assertEqual(accepted[0]["terms"], "Base monthly rate only")
        self.assertIsNone(collector.evidence_span("Get $300 back.", "Get $200 back"))

    def test_non_monetary_placeholder_is_omitted_not_offer_rejection(self):
        source = "Digital Secure Home Plus included With Fios 2 Gig and Fios 5 Gig"
        accepted, rejected = collector.validate_offers([dict(title="Digital Secure Home Plus included",
            raw_text=source, amounts_raw="No content available")], source)
        self.assertFalse(rejected)
        self.assertIsNone(accepted[0]["amounts_raw"])
        self.assertIn("amounts_raw_not_monetary", accepted[0]["field_warnings"])

    def test_duration_is_not_a_monetary_amount(self):
        raw = "Get Disney+, Hulu, & ESPN+ perk for 12 months on us."
        accepted, rejected = collector.validate_offers([dict(title=raw, raw_text=raw, amounts_raw="12 months")], raw)
        self.assertFalse(rejected)
        self.assertIsNone(accepted[0]["amounts_raw"])
        self.assertIn("amounts_raw_not_monetary", accepted[0]["field_warnings"])

    def test_duplicate_pricing_warning_does_not_fail_source(self):
        raw = "AT&T Internet 5000\n5 GIG speed\nWas $135.00 per month.. Now $110.00. per month.\nShop now"
        candidate = dict(title="Was $135.00 per month.. Now $110.00. per month.",
                         description="Was $135.00 per month.. Now $110.00. per month.",
                         raw_text="Unsupported plan terms. " + raw,
                         terms="Unsupported plan terms.", amounts_raw="$110.00. per month",
                         deal_type="promotion")
        with tempfile.TemporaryDirectory() as folder:
            location = Path(folder)
            (location / "visible.txt").write_text(raw)
            audit = dict(batches=[], rejected=[], limitations=[])
            context = dict(source=("att_fiber_plans", "AT&T", "fiber", "https://www.att.com/internet/fiber/"),
                           local=location, destination=location, capture={"status": "success"},
                           observed=None, run_id="test", audit=audit)
            with patch.object(collector, "cached_extract", return_value=[candidate]):
                offers, result = collector.extract_source(context, None, None, location)
            self.assertEqual(len(offers), 1)
            self.assertEqual(result["rejected"], [])
            self.assertEqual(result["warnings"][0]["reason"], "verified_pricing_duplicate")

    def test_pricing_duplicate_requires_verified_title_and_amount(self):
        raw = "AT&T Internet 5000\n5 GIG speed\nWas $135.00 per month.. Now $110.00. per month."
        price = dict(title="AT&T Internet 5000", raw_text=raw, deal_type="standard_pricing")
        candidate = dict(title="Was $135.00 per month.. Now $110.00. per month.",
                         raw_text=raw, amounts_raw="$110.00. per month", deal_type="promotion")
        self.assertTrue(collector.pricing_candidate_covered(candidate, [price]))
        candidate["amounts_raw"] = "$100.00. per month"
        self.assertFalse(collector.pricing_candidate_covered(candidate, [price]))
        candidate["amounts_raw"] = "$110.00. per month"
        candidate["reward_text"] = "$200 gift card"
        self.assertFalse(collector.pricing_candidate_covered(candidate, [price]))
        candidate["reward_text"] = None
        candidate["raw_text"] += " Get a $200 gift card."
        self.assertFalse(collector.pricing_candidate_covered(candidate, [price]))

    def test_invalid_optional_terms_do_not_drop_verified_offer(self):
        raw = "Get $20/mo off for 6 months. New customers only."
        item = dict(title="Get $20/mo off for 6 months", raw_text=raw,
                    amounts_raw="$20/mo", terms="Everyone qualifies")
        accepted, rejected = collector.validate_offers([item], raw)
        self.assertFalse(rejected)
        self.assertEqual(accepted[0]["raw_text"], raw)
        self.assertIsNone(accepted[0]["terms"])
        self.assertEqual(accepted[0]["field_warnings"], ["terms"])
        item["amounts_raw"] = "$50/mo"
        self.assertFalse(collector.validate_offers([item], raw)[0])

    def test_att_fiber_price_excludes_addons_and_competitor_table(self):
        block = "AT&T Internet 300\n300Mbps speed\nWas $60.00 per month.. Now $35.00. per month. plus taxes & fees\nAutoPay required\nShop now\nAll-Fi Pro $25/mo.\n"
        raw = block + "See how AT&T compares to the competition.\n" + block.replace("$35.00", "$5.00")
        prices = collector.att_pricing("att_fiber_plans", raw)
        self.assertEqual(len(prices), 1)
        self.assertNotIn("$25", prices[0]["raw_text"])
        self.assertIn("$35.00", prices[0]["amounts_raw"])
        self.assertEqual(collector.classify_deal(prices[0])[0], "standard_pricing")
        self.assertFalse(collector.validate_offers(prices, raw)[1])

    def test_att_price_is_literal_consumer_block_not_business_price(self):
        raw = "AT&T Internet Air®\n\nReliable home internet starting at $55/mo.\nAutoPay required.\nShop AT&T Internet Air\nAT&T Internet Air for Business $30/mo."
        prices = collector.att_air_pricing(raw)
        self.assertEqual(len(prices), 1)
        self.assertIn("$55/mo.", prices[0]["amounts_raw"])
        self.assertNotIn("$30", prices[0]["raw_text"])
        self.assertEqual(collector.classify_deal(prices[0])[0], "standard_pricing")
        self.assertFalse(collector.validate_offers(prices, raw)[1])
        self.assertEqual(collector.att_air_pricing("AT&T Internet Air for Business $30/mo."), [])

    def test_card_enrichment_preserves_original_and_alternative_rewards(self):
        raw = "Get a Month On Us AND your choice of AirPods or up to $200 back. New customers only."
        card = {"title": "Get a Month On Us", "raw_text": raw, "description": raw}
        class Client:
            def extract(self, *args, **kwargs):
                return SimpleNamespace(status="success", data=SimpleNamespace(json_data={
                    "reward_text": "Get a Month On Us AND your choice of AirPods or up to $200 back.",
                    "eligibility": "New customers only.", "duration_text": None, "plan_context": None}))
        with tempfile.TemporaryDirectory() as folder:
            result = collector.enrich_promotion_card(card, Client(), collector.ExtractionGate(), folder)
            self.assertEqual(result["raw_text"], raw)
            self.assertEqual(result["title"], card["title"])
            self.assertIn("or up to $200", result["reward_text"])
            self.assertEqual(result["eligibility"], "New customers only.")

    def test_card_enrichment_rejects_invented_qualification(self):
        class Client:
            def extract(self, *args, **kwargs):
                return SimpleNamespace(status="success", data=SimpleNamespace(json_data={"eligibility": "Everyone qualifies"}))
        with tempfile.TemporaryDirectory() as folder:
            result = collector.enrich_promotion_card({"raw_text": "Get a Month On Us. New customers only."}, Client(), collector.ExtractionGate(), folder)
            self.assertNotIn("eligibility", result)
            self.assertEqual(result["enrichment_warnings"], ["Unsupported quote omitted: eligibility"])

    def test_competitor_table_evidence_not_assigned_to_att(self):
        quote = "Available for $15/mo. add-on with Xfinity Pro"
        source = "AT&T plans\nSee how AT&T compares to the competition.\n" + quote + "\nCompetitor comparison based on public data\nOther benefits"
        self.assertTrue(collector.comparison_only_evidence("att_fiber_plans", quote, source))
        self.assertFalse(collector.comparison_only_evidence("att_fiber_plans", "AT&T plans", source))
        self.assertFalse(collector.comparison_only_evidence("verizon_fios", quote, source))
        self.assertFalse(collector.comparison_only_evidence("att_fiber_plans", quote, quote + "\n" + source))

    def test_missing_title_uses_verified_source_line(self):
        source = "Get unlimited 300Mbps internet for $35/mo.\nPlus, save when you bundle."
        accepted, rejected = collector.validate_offers([{"title": None, "raw_text": source}], source)
        self.assertFalse(rejected)
        self.assertEqual(accepted[0]["title"], source.splitlines()[0])

    def test_markdown_escape_recovers_source_without_changing_price(self):
        source = "Price + taxes & fees. Get internet for $65.00/mo."
        item = {"title": "Internet", "raw_text": source.replace("+", "\\+")}
        accepted, rejected = collector.validate_offers([item], source)
        self.assertFalse(rejected)
        self.assertEqual(accepted[0]["raw_text"], source)
        item["raw_text"] = item["raw_text"].replace("$65", "$55")
        self.assertFalse(collector.validate_offers([item], source)[0])

    def test_separate_verbatim_fields_recover_original_span(self):
        source = "We’ll pay your termination fee—up to $750.\nSubmit your claim\nVia prepaid card. Requires 60 days service."
        item = {"title": "termination fee", "description": "We'll pay your termination fee--up to $750.",
                "terms": "Requires 60 days service.", "amounts_raw": "$750",
                "raw_text": "We'll pay your termination fee--up to $750. Requires 60 days service."}
        accepted, rejected = collector.validate_offers([item], source)
        self.assertFalse(rejected)
        self.assertEqual(accepted[0]["raw_text"], source)
        self.assertEqual(accepted[0]["description"], source.splitlines()[0])
        item["amounts_raw"] = "$850"
        accepted, rejected = collector.validate_offers([item], source)
        self.assertFalse(accepted)
        self.assertEqual(len(rejected), 1)

    def test_rate_limit_opens_shared_circuit_after_three_calls(self):
        waits, calls = [], []
        gate = collector.ExtractionGate(sleep=waits.append, clock=lambda: 0)
        def limited():
            calls.append(1)
            raise RuntimeError("Rate limited - slow down and retry")
        for _ in range(2):
            with self.assertRaises(collector.ExtractionPaused):
                gate.call(limited)
        self.assertEqual(len(calls), 3)
        self.assertIn(30, waits)
        self.assertIn(60, waits)

    def test_rate_limit_can_recover(self):
        calls = []
        gate = collector.ExtractionGate(sleep=lambda _: None, clock=lambda: 0)
        def operation():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("HTTP 429 Too Many Requests")
            return ["ok"]
        self.assertEqual(gate.call(operation), ["ok"])
        self.assertFalse(gate.paused)

    def test_permanent_error_not_retried(self):
        calls = []
        def operation():
            calls.append(1)
            raise RuntimeError("Unauthorized")
        with self.assertRaises(RuntimeError):
            collector.ExtractionGate().call(operation)
        self.assertEqual(len(calls), 1)

    def test_insufficient_credits_stops_all_following_calls(self):
        calls = []
        gate = collector.ExtractionGate(sleep=lambda _: self.fail("Must not wait for depleted credits"))
        def operation():
            calls.append(1)
            raise RuntimeError("Insufficient credits - purchase more")
        for _ in range(3):
            with self.assertRaisesRegex(collector.ExtractionPaused, "Insufficient credits"):
                gate.call(operation)
        self.assertEqual(len(calls), 1)

    def test_success_cache_reused_even_when_gate_paused(self):
        with tempfile.TemporaryDirectory() as folder:
            gate = collector.ExtractionGate()
            result = [{"title": "Example", "raw_text": "A supported example offer"}]
            collector.cached_extract(folder, "prompt", "piece", lambda: result, gate)
            gate.paused = True
            self.assertEqual(collector.cached_extract(folder, "prompt", "piece", lambda: self.fail("cache missed"), gate), result)
            with self.assertRaises(collector.ExtractionPaused):
                collector.cached_extract(folder, "prompt", "changed piece", lambda: result, gate)

    def test_batches_preserve_every_character_including_final_terms(self):
        text = ("Plan details\n" * 1400) + "Offer ends 9/23. New customers only."
        spans = list(collector.batches(text))
        self.assertEqual(spans[0][0], 0)
        self.assertEqual(spans[-1][1], len(text))
        for previous, current in zip(spans, spans[1:]):
            self.assertLess(current[0], previous[1])
            self.assertGreater(current[1], previous[1])
        self.assertTrue(spans[-1][2].endswith("New customers only."))

    def test_paraphrased_evidence_is_rejected(self):
        source = "Get $200 back when you switch to eligible home internet."
        offers = [{"title":"Get $200 back", "raw_text":source},
                  {"title":"Gift", "raw_text":"Customers receive a $200 gift for switching."}]
        accepted, rejected = collector.validate_offers(offers, source)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(rejected[0]["reason"], "evidence_not_verbatim")

    def test_whitespace_normalization_does_not_change_amounts(self):
        source = "Get $200\nback when you switch to home internet."
        good = {"title":"Get $200 back", "raw_text":source.replace("\n", " ")}
        bad = dict(good, raw_text=good["raw_text"].replace("$200", "$300"))
        accepted, rejected = collector.validate_offers([good,bad], source)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 1)

    def test_currency_layout_recovers_actual_source_quote(self):
        source = "Get $ 200 back with qualifying internet service."
        accepted, rejected = collector.validate_offers([
            {"title":"Get $200 back", "raw_text":"Get $200 back with qualifying internet service."}
        ], source)
        self.assertFalse(rejected)
        self.assertEqual(accepted[0]["raw_text"], source)

    def test_embedded_browser_worker_compiles(self):
        compile(collector.WORKER, "capture.py", "exec")

    def test_typography_recovers_original_without_accepting_changed_numbers(self):
        source = "AutoPay req’d. Get up to $750—new customers only."
        good = "AutoPay req'd. Get up to $750--new customers only."
        accepted, rejected = collector.validate_offers([
            {"title": "Get up to $750", "raw_text": good},
            {"title": "Get up to $750", "raw_text": good.replace("$750", "$850")},
        ], source)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]["raw_text"], source)
        self.assertEqual(len(rejected), 1)

    def test_card_title_duplicates_removed_and_disclosure_retained(self):
        html = '''<article class="xpr-promoCard">
        <h2 class="xpr-promoCard__title">Hulu On Us<template>Hulu On Us</template></h2>
        <span class="xpr-promoCard__kicker">$11.99/mo value</span>
        <div class="xpr-promoCard__body">Included with eligible plans.</div>
        <template><div data-moengage-id="modalCopy">New customers only. Cancel anytime.</div></template>
        </article><article class="xpr-promoCard">
        <h2 class="xpr-promoCard__title">How to switch</h2>
        <div class="xpr-promoCard__ctas"><a href="/home-internet/the-signal/article">Read more</a></div>
        </article>'''
        offers = collector.tmobile_cards(html)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["title"], "Hulu On Us")
        self.assertIn("New customers only", offers[0]["terms"])
        self.assertEqual(offers[0]["amounts_raw"], "$11.99/mo value")


if __name__ == "__main__":
    unittest.main()
