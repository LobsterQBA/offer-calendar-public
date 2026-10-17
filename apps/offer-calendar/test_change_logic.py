from datetime import date

import pandas as pd

from change_logic import build_change_events
from data_access import attach_available_screenshots, attach_page_evidence


def _run(run_id: str, report_date: date, coverage: str = "complete") -> dict:
    return {
        "run_id": run_id,
        "source_id": "source_a",
        "observed_at": pd.Timestamp(report_date, tz="UTC"),
        "status": "success",
        "coverage": coverage,
        "report_date": report_date,
    }


def _offer(run_id: str, report_date: date, offer_id: str, title: str, amount: str) -> dict:
    return {
        "snapshot_id": f"{run_id}_{offer_id}",
        "run_id": run_id,
        "offer_id": offer_id,
        "source_id": "source_a",
        "brand": "T-Mobile",
        "product_type": "fixed_wireless",
        "content_type": "offer",
        "title": title,
        "amounts_raw": amount,
        "raw_text": f"{title}. {amount} per month.",
        "report_date": report_date,
    }


def test_exact_offer_is_modified_when_amount_changes() -> None:
    first, second = date(2026, 9, 16), date(2026, 9, 17)
    runs = pd.DataFrame([_run("r1", first), _run("r2", second)])
    offers = pd.DataFrame(
        [
            _offer("r1", first, "same", "Home Internet", "$50"),
            _offer("r2", second, "same", "Home Internet", "$45"),
        ]
    )

    events = build_change_events(runs, offers)

    assert len(events) == 1
    assert events.iloc[0]["event_type"] == "modified"
    assert events.iloc[0]["changed_fields"] == ["amounts_raw"]
    assert events.iloc[0]["match_strategy"] == "offer_id"


def test_small_title_edit_pairs_before_and_after() -> None:
    first, second = date(2026, 9, 16), date(2026, 9, 17)
    runs = pd.DataFrame([_run("r1", first), _run("r2", second)])
    offers = pd.DataFrame(
        [
            _offer("r1", first, "old", "Fiber Internet offer", "$55"),
            _offer("r2", second, "new", "Fiber Internet special offer", "$55"),
        ]
    )

    events = build_change_events(runs, offers)

    assert events.empty


def test_partial_run_suppresses_presence_changes() -> None:
    first, second = date(2026, 9, 16), date(2026, 9, 17)
    runs = pd.DataFrame([_run("r1", first), _run("r2", second, coverage="partial")])
    offers = pd.DataFrame([_offer("r1", first, "gone", "Possible removal", "$50")])

    events = build_change_events(runs, offers)

    assert events.empty


def test_same_content_hash_suppresses_ai_paraphrase() -> None:
    first, second = date(2026, 9, 16), date(2026, 9, 17)
    runs = pd.DataFrame([_run("r1", first), _run("r2", second)])
    before = _offer("r1", first, "same", "Hulu On Us", "$8.99/month value.")
    after = _offer("r2", second, "same", "Hulu On Us", "$8.99/month value")
    before.update({"description": "Included at no charge.", "content_hash": "same-hash"})
    after.update({"description": "The plan is included.", "content_hash": "same-hash"})

    events = build_change_events(runs, pd.DataFrame([before, after]))

    assert events.empty


def test_same_screenshot_suppresses_extraction_drift() -> None:
    first, second = date(2026, 9, 16), date(2026, 9, 17)
    runs = pd.DataFrame([_run("r1", first), _run("r2", second)])
    before = _offer("r1", first, "same", "Paramount+ On Us", "$8.99")
    after = _offer("r2", second, "same", "Paramount+ On Us", "$8.99")
    before.update({"terms": "Full terms apply.", "screenshot_sha256": "same-image"})
    after.update({"terms": "Additional terms are not shown.", "screenshot_sha256": "same-image"})

    events = build_change_events(runs, pd.DataFrame([before, after]))

    assert events.empty


def test_changed_screenshot_alone_is_not_a_business_change() -> None:
    first, second = date(2026, 9, 16), date(2026, 9, 17)
    runs = pd.DataFrame([_run("r1", first), _run("r2", second)])
    before = _offer("r1", first, "same", "Visual offer", "$50")
    after = _offer("r2", second, "same", "Visual offer", "$50")
    before.update(
        {"description": "Old image", "content_hash": "same-text", "screenshot_sha256": "old-image"}
    )
    after.update(
        {"description": "New image", "content_hash": "same-text", "screenshot_sha256": "new-image"}
    )

    events = build_change_events(runs, pd.DataFrame([before, after]))

    assert events.empty


def test_copy_only_source_text_change_is_not_material() -> None:
    first, second = date(2026, 9, 16), date(2026, 9, 17)
    runs = pd.DataFrame([_run("r1", first), _run("r2", second)])
    before = _offer("r1", first, "same", "Internet Air", "$55/mo")
    after = _offer("r2", second, "same", "Internet Air", "$55/mo")
    before.update({"description": "Reliable internet.", "raw_text": "Reliable internet starting at $55/mo."})
    after.update(
        {
            "description": "Fast, reliable internet.",
            "raw_text": "Reliable internet starting at $55/mo. See offer details.",
        }
    )

    events = build_change_events(runs, pd.DataFrame([before, after]))

    assert events.empty


def test_page_evidence_only_fills_missing_offer_card() -> None:
    offers = pd.DataFrame(
        [
            {"run_id": "r1", "screenshot_uri": "/Volumes/card.png"},
            {"run_id": "r1", "screenshot_uri": None},
        ]
    )
    evidence = pd.DataFrame(
        [
            {
                "run_id": "r1",
                "volume_path": "/Volumes/page.png",
                "captured_at": pd.Timestamp("2026-09-17T17:00:00Z"),
                "evidence_type": "live_source_page_screenshot",
                "evidence_scope": "page",
            }
        ]
    )

    attached = attach_page_evidence(offers, evidence)

    assert attached.iloc[0]["screenshot_uri"] == "/Volumes/card.png"
    assert attached.iloc[0]["page_screenshot_uri"] == "/Volumes/page.png"
    assert attached.iloc[0]["page_screenshot_captured_at"] == pd.Timestamp("2026-09-17T17:00:00Z")
    assert attached.iloc[1]["screenshot_uri"] == "/Volumes/page.png"
    assert attached.iloc[1]["screenshot_evidence_scope"] == "page"
    assert attached.iloc[1]["screenshot_captured_at"] == pd.Timestamp("2026-09-17T17:00:00Z")


def test_card_evidence_attaches_visual_hash() -> None:
    offers = pd.DataFrame(
        [
            {
                "source_id": "tmobile_hsi_deals",
                "observed_at": pd.Timestamp("2026-09-17T16:00:00Z"),
                "title": "Hulu On Us",
                "raw_text": "Hulu On Us",
                "screenshot_uri": None,
            }
        ]
    )
    screenshots = pd.DataFrame(
        [
            {
                "source_date": date(2026, 9, 17),
                "card_key": "hsi-hulu-title",
                "offer_title": "Hulu On Us",
                "volume_path": "/Volumes/hulu.png",
                "sha256": "stable-image-hash",
                "evidence_type": "offer_card",
            }
        ]
    )

    attached = attach_available_screenshots(offers, screenshots)

    assert attached.iloc[0]["screenshot_uri"] == "/Volumes/hulu.png"
    assert attached.iloc[0]["screenshot_card_key"] == "hsi-hulu-title"
    assert attached.iloc[0]["screenshot_sha256"] == "stable-image-hash"
