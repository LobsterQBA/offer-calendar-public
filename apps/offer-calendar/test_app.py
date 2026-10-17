"""UI behavior tests use explicitly synthetic preview data, never live credentials."""
from datetime import date
from pathlib import Path
from streamlit.testing.v1 import AppTest


def test_filters_empty_day_and_reset(monkeypatch):
    monkeypatch.setenv("OFFER_CALENDAR_PREVIEW", "1")
    monkeypatch.setenv("DATABRICKS_APP_NAME", "offer-calendar-fiber")
    at = AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=20)
    at.session_state["selected_day"] = date(2026, 9, 16)
    at.run()
    assert not at.exception
    evidence_html = [element.proto.body for element in at.get("html")]
    assert any('<mark>$50</mark>' in value for value in evidence_html)
    assert any('<mark>$45</mark>' in value for value in evidence_html)
    assert not any('class="original-copy"' in value.value for value in at.markdown)
    calendar_html = next(m.value for m in at.markdown if 'class="calendar-scroll"' in m.value)
    assert "T-Mobile · Fiber · Amount changed" in calendar_html
    assert "3 records" not in calendar_html
    assert "Missing sources" in calendar_html
    assert "no comparison" not in calendar_html.lower()
    assert "No qualified changes" not in calendar_html
    assert "Monthly amount: $50 → $45" in calendar_html
    assert any("T-Mobile · Fiber · Amount changed" in item.label for item in at.expander)
    assert any("No screenshot captured" in message.value for message in at.info)
    assert any("What changed" in m.value for m in at.markdown)
    assert len(at.metric) == 0
    assert not any(e.label == "Comparison coverage" for e in at.expander)
    assert any("product-nav" in m.value and "offer-calendar-hsi-" in m.value for m in at.markdown)
    at.radio[0].set_value("Data inspection").run()
    assert not at.exception
    assert any(e.label == "Comparison coverage" for e in at.expander)
    for brand, count in [("AT&T", "2"), ("Verizon", "—"), ("All brands", "3")]:
        at.selectbox[0].select(brand).run()
        assert not at.exception
        assert at.metric[0].value == count
    at.date_input[0].set_value(date(2026, 9, 1)).run()
    assert at.metric[0].value == "—"
    at.date_input[0].set_value(date(2026, 9, 16)).run()
    assert at.metric[0].value == "3"
    at.text_input[0].set_value("no-matching-record").run()
    assert not at.exception
    assert any("No records match" in message.value for message in at.info)
    at.radio[0].set_value("Calendar").run()
    assert not at.exception
    assert len(at.metric) == 0
    assert len(at.selectbox(key="browse_offer").options) == 3
