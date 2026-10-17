"""Display grain and comparison eligibility shared by every dashboard view."""
from __future__ import annotations

import pandas as pd
import re
from promotion_policy import classify_deal, consolidate_deals, deal_headline


def scope_records(offers):
    """Classify both old and new records without mutating stored evidence."""
    result = offers.copy()
    result["deal_scope"] = [classify_deal(row)[0] for _, row in result.iterrows()]
    result["scope_reason"] = [classify_deal(row)[1] for _, row in result.iterrows()]
    return result


def promotion_records(offers):
    """Only collapse identical evidence within a run; never merge different terms."""
    scoped = scope_records(offers)
    scoped = scoped[scoped.deal_scope.eq("promotion")].copy()
    if scoped.empty:
        return scoped
    scoped["_deal_evidence"] = scoped.raw_text.fillna("").map(lambda t: " ".join(str(t).split()).casefold())
    scoped = scoped.drop_duplicates(["run_id", "_deal_evidence"]).drop(columns="_deal_evidence")
    indices = []
    for _, group in scoped.groupby("run_id"):
        records = [dict(row, _original_index=index) for index, row in group.iterrows()]
        indices.extend(r["_original_index"] for r in consolidate_deals(records))
    result = scoped.loc[indices].copy()
    result["display_title"] = [deal_headline(row) for _, row in result.iterrows()]
    return result


def inventory_records(offers):
    """Daily observed inventory: promotions, benefits, and AT&T pricing context."""
    scoped = scope_records(offers)
    selected = scoped.deal_scope.isin(["promotion", "included_benefit"])
    selected |= scoped.deal_scope.eq("standard_pricing") & scoped.get("brand", pd.Series(index=scoped.index, dtype=str)).eq("AT&T")
    result = scoped[selected].copy()
    # Do not collapse distinct titles/categories that happen to share page evidence.
    result["_evidence"] = result.raw_text.fillna("").map(lambda t: " ".join(str(t).split()).casefold())
    result = result.drop_duplicates(["run_id", "title", "_evidence"]).drop(columns="_evidence")
    indices = []
    # Consolidate contained headlines and exact streaming summaries within a
    # source/run/category. Different terms or neighboring campaigns stay separate.
    for _, group in result.groupby(["run_id", "deal_scope"], sort=False):
        records = [dict(row, _original_index=index) for index, row in group.iterrows()]
        indices.extend(row["_original_index"] for row in consolidate_deals(records))
    result = result.loc[indices].copy()
    result["display_title"] = [deal_headline(row) for _, row in result.iterrows()]
    return result


def calendar_status(runs, selected, expected_sources=None):
    """Never turn a failed/missing observation into a no-change claim."""
    status = comparison_status(runs, selected)
    if status.empty:
        return "Not collected"
    if expected_sources and set(expected_sources) - set(status.source_id):
        return "Missing sources"
    if status.comparison.eq("Collection incomplete").any():
        return "Collection incomplete"
    if status.comparable.all():
        return "No change"
    if status.comparable.any():
        return "No change · new baseline"
    return "First observation"

SOURCE_NAMES = {
    "tmobile_hsi_deals": "T-Mobile · HSI deals",
    "att_internet_air": "AT&T · Internet Air",
    "verizon_5g_home": "Verizon · 5G Home",
    "tmobile_fiber_deals": "T-Mobile · Fiber deals",
    "att_fiber_deals": "AT&T · Fiber deals",
    "att_fiber_plans": "AT&T · Fiber plans",
    "verizon_fios": "Verizon · Fios",
}


def amount_summary(value):
    """Do not present a scraped speed badge such as FAST as a price."""
    if value is None or pd.isna(value):
        return "No explicit amount captured"
    value = " ".join(str(value).split())
    return value if re.search(r"[$£€]\s*\d|\d+(?:\.\d+)?\s*(?:%|USD|dollars?)", value, re.I) else "No explicit amount captured"


def local_dates(frame, column):
    values = frame[column] if column in frame else pd.Series(index=frame.index, dtype=object)
    return pd.to_datetime(values, utc=True, errors="coerce").dt.tz_convert("America/Los_Angeles").dt.date


def daily_view(runs, offers):
    """Latest attempt, NOT latest success: never hide a newer collection failure."""
    runs, offers = runs.copy(), offers.copy()
    runs["report_date"] = local_dates(runs, "observed_at").fillna(local_dates(runs, "scheduled_for"))
    offers["report_date"] = local_dates(offers, "observed_at").fillna(local_dates(offers, "revised_at"))
    if runs.empty:
        return runs, offers.iloc[:0]
    runs["_time"] = pd.to_datetime(runs["observed_at"], utc=True, errors="coerce").fillna(
        pd.to_datetime(runs["scheduled_for"], utc=True, errors="coerce")
    )
    runs = runs.sort_values(["_time", "run_id"]).drop_duplicates(["source_id", "report_date"], keep="last")
    offers = offers[offers["run_id"].isin(runs["run_id"])].copy()
    # IDs are only unique inside a source/run; never deduplicate by title or across brands.
    offers = offers.drop_duplicates(["run_id", "offer_id"], keep="last")
    return runs.drop(columns="_time"), offers


def collection_method(row):
    uri = str(row.get("diagnostics_uri") or "")
    if "/promotion_collection_v1/" in uri:
        return "promotion-v1"
    return "rendered" if "/rendered_collection/" in uri else "legacy"


def comparison_runs(runs):
    """Changes across a collector migration are not evidence of a market change."""
    result = runs.copy()
    if "diagnostics_uri" in result:
        result["source_id"] = result.apply(lambda r: str(r["source_id"]) + "|" + collection_method(r), axis=1)
    return result


def comparison_status(runs, selected):
    rows = []
    for _, current in runs[runs["report_date"].eq(selected)].iterrows():
        prior = runs[(runs["source_id"] == current["source_id"]) & (runs["report_date"] < selected)
                     & runs["status"].astype(str).str.lower().eq("success")]
        if "diagnostics_uri" in runs:
            prior = prior[prior.apply(collection_method, axis=1).eq(collection_method(current))]
        if str(current["status"]).lower() != "success":
            state, baseline = "Collection incomplete", None
        elif prior.empty:
            state, baseline = "First observation", None
        else:
            state, baseline = "Compared", max(prior["report_date"])
        rows.append({"source_id": current["source_id"], "comparison": state, "baseline": baseline,
                     "comparable": baseline is not None})
    return pd.DataFrame(rows, columns=["source_id", "comparison", "baseline", "comparable"])
