"""Daily email input using the dashboard's unchanged comparison rules."""
from urllib.parse import urlencode

from presentation import APP_URLS
from change_logic import build_change_events
from dashboard_model import comparison_runs, daily_view, inventory_records


def daily_digest(raw_runs, raw_offers, selected):
    runs, offers = daily_view(raw_runs, raw_offers)
    events = build_change_events(comparison_runs(runs), inventory_records(offers))
    events = events[events.report_date.eq(selected) & events.event_type.ne("review_only")]
    lines = []
    for _, event in events.drop_duplicates("event_id").iterrows():
        record = event["after"] or event["before"]
        service = "fiber" if record.get("product_type") == "fiber" else "hsi"
        url = APP_URLS["Fiber" if service == "fiber" else "HSI"].rstrip("/") + "/?" + urlencode({"day": selected.isoformat(), "brand": event.brand})
        lines.append(f"{event.brand} | {service.upper()} | {record.get('display_title') or record.get('title')} | {event.change_summary or event.event_type} | {url}")
    return {"observation_date": selected, "change_count": len(lines),
            "summary": "\n".join(lines),
            "coverage_note": "Evidence-supported candidates, pending review. Failed or missing captures do not prove no change. Observation dates are not offer effective dates."}
