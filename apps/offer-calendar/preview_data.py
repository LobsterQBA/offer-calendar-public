from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd


def preview_frames(month_start: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Clearly labeled local-only fixture used for rendered UI verification."""
    days = [month_start + timedelta(days=offset) for offset in (1, 4, 8, 11, 15)]
    sources = [
        ("tmobile_hsi", "T-Mobile", "fixed_wireless"),
        ("att_hsi", "AT&T", "fixed_wireless"),
        ("tmobile_fiber", "T-Mobile", "fiber"),
        ("att_fiber", "AT&T", "fiber"),
        ("verizon_home", "Verizon", "fixed_wireless"),
    ]
    run_rows = []
    offer_rows = []
    for day_index, day in enumerate(days):
        for source_index, (source_id, brand, product_type) in enumerate(sources):
            observed = datetime(day.year, day.month, day.day, 16, source_index, tzinfo=timezone.utc)
            run_id = f"preview_{day_index}_{source_index}"
            coverage = "partial" if source_id == "verizon_home" and day_index == 4 else "complete"
            run_rows.append(
                {
                    "run_id": run_id,
                    "source_id": source_id,
                    "scheduled_for": observed,
                    "observed_at": observed,
                    "status": "success",
                    "coverage": coverage,
                    "brand": brand,
                    "source_product_type": product_type,
                    "source_url": "https://example.com",
                    "context": "Illustrative local preview only",
                }
            )
            offer_count = (source_index % 2) + 1
            if source_id == "att_hsi":
                offer_count = 1 if day_index < 3 else 2
            if source_id == "verizon_home" and day_index == 4:
                offer_count = 0
            for offer_index in range(offer_count):
                title = f"{brand} {product_type.replace('_', ' ').title()} offer"
                offer_id = f"offer_{source_id}_{offer_index}"
                description = "Illustrative content for local layout verification."
                amount = "$50" if source_id == "tmobile_hsi" else "$--"
                if source_id == "tmobile_hsi" and day_index >= 1:
                    description = "Illustrative changed content with a five-dollar monthly discount."
                    amount = "$45"
                if source_id == "tmobile_fiber":
                    amount = "$50" if day_index < 4 else "$45"
                if source_id == "att_fiber" and day_index >= 2:
                    title = "AT&T Fiber Internet offer"
                    offer_id = f"offer_{source_id}_renamed_{offer_index}"
                # Explicit promotional fixtures, not a plan catalogue disguised as deals.
                title = f"{brand} promotional gift card {offer_index + 1}"
                offer_rows.append(
                    {
                        "snapshot_id": f"snapshot_{run_id}_{offer_index}",
                        "run_id": run_id,
                        "offer_id": offer_id,
                        "revised_at": observed,
                        "revision_kind": "candidate",
                        "review_status": "pending",
                        "product_type": product_type,
                        "title": title,
                        "description": description,
                        "terms": "Not production data.",
                        "source_category": "Preview",
                        "cta_url": "https://example.com",
                        "content_type": "offer",
                        "tags": "[]",
                        "audience": None,
                        "geography": None,
                        "eligibility": None,
                        "amounts_raw": amount,
                        "effective_start_date": None,
                        "effective_end_date": None,
                        "screenshot_uri": None,
                        "raw_text": f"Illustrative local preview only. {title}. {description} {amount} per month.",
                        "content_hash": None,
                        "source_id": source_id,
                        "observed_at": observed,
                        "run_status": "success",
                        "coverage": coverage,
                        "brand": brand,
                        "source_url": "https://example.com",
                    }
                )
    return pd.DataFrame(run_rows), pd.DataFrame(offer_rows)
