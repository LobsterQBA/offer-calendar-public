from datetime import date
import pandas as pd
from dashboard_model import daily_view, comparison_status, comparison_runs, amount_summary
from change_logic import build_change_events


def run(rid, timestamp, status="success", method="rendered"):
    return dict(run_id=rid, source_id="att", observed_at=timestamp, scheduled_for=timestamp,
                status=status, coverage="partial", diagnostics_uri=f"/rendered_collection/{rid}" if method == "rendered" else "/old")


def offer(rid, timestamp, oid="same", amount="$35"):
    return dict(run_id=rid, observed_at=timestamp, revised_at=timestamp, offer_id=oid,
                source_id="att", title="Internet", amounts_raw=amount, raw_text=f"Internet {amount}/mo", product_type="fiber", content_type="offer")


def test_latest_attempt_only_not_sum_of_reruns():
    a,b="2026-09-21T14:00:00Z","2026-09-21T15:00:00Z"
    runs,offers=daily_view(pd.DataFrame([run("a",a),run("b",b)]),pd.DataFrame([offer("a",a),offer("b",b)]))
    assert runs.run_id.tolist()==["b"]
    assert offers.run_id.tolist()==["b"]


def test_failure_not_hidden_by_older_success():
    a,b="2026-09-21T14:00:00Z","2026-09-21T15:00:00Z"
    runs,offers=daily_view(pd.DataFrame([run("a",a),run("b",b,"fetch_failed")]),pd.DataFrame([offer("a",a)]))
    assert runs.status.tolist()==["fetch_failed"]
    assert offers.empty


def test_los_angeles_day_not_utc_day():
    t="2026-09-21T01:00:00Z"
    runs,offers=daily_view(pd.DataFrame([run("a",t)]),pd.DataFrame([offer("a",t)]))
    assert runs.iloc[0].report_date==date(2026,9,20)
    assert offers.iloc[0].report_date==date(2026,9,20)


def test_new_collector_is_baseline_not_market_change():
    a,b="2026-09-20T14:00:00Z","2026-09-21T15:00:00Z"
    runs,offers=daily_view(pd.DataFrame([run("a",a,method="legacy"),run("b",b)]),pd.DataFrame([offer("a",a),offer("b",b,amount="$50")]))
    assert not comparison_status(runs,date(2026,9,21)).comparable.any()
    assert build_change_events(comparison_runs(runs),offers).empty


def test_same_method_remains_comparable_and_detects_change():
    a,b="2026-09-20T14:00:00Z","2026-09-21T15:00:00Z"
    runs,offers=daily_view(pd.DataFrame([run("a",a),run("b",b)]),pd.DataFrame([offer("a",a),offer("b",b,amount="$50")]))
    assert comparison_status(runs,date(2026,9,21)).comparable.all()
    assert len(build_change_events(comparison_runs(runs),offers))==1


def test_partial_current_is_not_claimed_comparable():
    a,b="2026-09-20T14:00:00Z","2026-09-21T15:00:00Z"
    runs,offers=daily_view(pd.DataFrame([run("a",a),run("b",b,"partial")]),pd.DataFrame([offer("a",a),offer("b",b)]))
    assert not comparison_status(runs,date(2026,9,21)).comparable.any()
    assert build_change_events(comparison_runs(runs),offers).empty


def test_same_id_across_sources_is_not_collapsed():
    t="2026-09-21T15:00:00Z"
    other=run("b",t); other["source_id"]="tmobile"
    runs,offers=daily_view(pd.DataFrame([run("a",t),other]),pd.DataFrame([offer("a",t),offer("b",t)]))
    assert len(offers)==2


def test_marketing_speed_badges_are_not_prices():
    assert amount_summary("FASTER")=="No explicit amount captured"
    assert amount_summary(None)=="No explicit amount captured"
    assert amount_summary("$55/mo plus $200 back")=="$55/mo plus $200 back"
    assert amount_summary("20% discount")=="20% discount"
