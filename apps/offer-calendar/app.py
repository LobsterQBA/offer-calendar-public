from __future__ import annotations

import calendar
import html
import os
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from change_logic import build_change_events
from email_alerts import draft_change_email
from dashboard_model import SOURCE_NAMES, amount_summary, comparison_runs, comparison_status, daily_view, scope_records, inventory_records, calendar_status
from promotion_policy import deal_details, deal_headline
from data_access import load_month, read_volume_image_sql
from preview_data import preview_frames
from presentation import business_summary, highlighted_evidence, markdown_literal, product_links, screenshot_html

APP_NAME = os.environ.get("DATABRICKS_APP_NAME", "").lower()
PRODUCT_VIEW = "fixed_wireless" if APP_NAME.endswith("-hsi") else "fiber" if APP_NAME.endswith("-fiber") else "all"
VIEW_NAME = {"fixed_wireless": "HSI", "fiber": "Fiber", "all": "Home internet"}[PRODUCT_VIEW]
FIELDS = {"title": "Title", "description": "Description", "terms": "Terms", "amounts_raw": "Amount text", "eligibility": "Eligibility", "audience": "Audience", "geography": "Geography", "content_type": "Record type", "cta_url": "Link", "presence": "Presence"}
TYPES = {"modified": "Modified", "added": "Added", "removed": "Removed"}
preview_mode = os.environ.get("OFFER_CALENDAR_PREVIEW") == "1"
st.set_page_config(page_title=f"{VIEW_NAME} offer calendar", page_icon="◫", layout="wide")


def text(value, fallback="Not captured"):
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return fallback
    return str(value).strip() or fallback


def safe_url(value):
    value = text(value, "")
    parsed = urlparse(value)
    return value if parsed.scheme == "https" and parsed.netloc else None


def source_name(value):
    return SOURCE_NAMES.get(str(value), str(value))


@st.cache_data(ttl=300, show_spinner=False)
def get_month_data(year, month, preview, user_access_token):
    start = date(year, month, 1)
    end = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    return preview_frames(start) if preview else load_month(start, end, user_access_token)


@st.cache_data(ttl=300, show_spinner=False)
def cached_volume_image(uri, user_access_token):
    return read_volume_image_sql(uri, user_access_token)


def render_image(row, token, key):
    uri = text(row.get("screenshot_uri"), "")
    if not uri:
        st.info("No screenshot captured for this record. Original text remains available below.")
        return
    scope = text(row.get("screenshot_evidence_scope"), "unknown")
    page_uri = text(row.get("page_screenshot_uri"), "")
    has_card_alternative = scope == "offer_card" and bool(page_uri) and page_uri != uri
    captured_at = row.get("screenshot_captured_at")
    if page_uri and page_uri != uri and st.checkbox("View full page", key=f"full_page_{key}"):
        uri, scope = page_uri, "page"
        captured_at = row.get("page_screenshot_captured_at")
    if scope == "page":
        st.caption("Full source page · Uncheck View full page to return to the matched card." if has_card_alternative else "Full source page · Scroll and zoom to inspect the offer. No verified card crop is available for this view.")
    elif scope == "offer_card":
        st.caption("Matched offer card · Check the saved text below; a screenshot match is not confirmation of a change.")
        if not page_uri:
            st.caption("A full-page screenshot is not linked to this capture.")
    else:
        st.caption("Saved screenshot · Image scope was not recorded.")
    captured = pd.to_datetime(captured_at, utc=True, errors="coerce")
    st.caption(f"Image captured {captured.tz_convert('America/Los_Angeles'):%b %d, %Y · %H:%M %Z}" if pd.notna(captured) else "Image capture time was not recorded; the date above belongs to the offer observation.")
    observed = pd.to_datetime(row.get("observed_at"), utc=True, errors="coerce")
    if pd.notna(captured) and pd.notna(observed) and captured.tz_convert("America/Los_Angeles").date() != observed.tz_convert("America/Los_Angeles").date():
        st.warning("This image was captured on a different day from the offer observation. Use it as supporting context, not exact-time proof.")
    try:
        if uri.startswith("/Volumes/"):
            if not token:
                st.warning("Screenshot linked, but your sign-in authorization is unavailable.")
                return
            image = cached_volume_image(uri, token)
        elif safe_url(uri):
            components.html(screenshot_html(uri, scope), height=565)
            st.link_button("Open original screenshot", uri)
            return
        elif preview_mode and Path(uri).is_file():
            image = Path(uri).read_bytes()
        else:
            st.warning("Screenshot location is not supported.")
            return
        components.html(screenshot_html(image, scope), height=565)
        st.download_button("Download original screenshot", image, file_name=f"{row.get('run_id', 'capture')}.png", mime="image/png", key=f"download_{key}")
    except Exception as error:
        st.error("Screenshot could not be loaded. A linked path does not guarantee that the file is accessible.")
        # No nested expanders: this helper also runs inside change details.
        if st.checkbox("Show image error details", key=f"image_error_{key}"):
            st.code(f"{type(error).__name__}: {error}")


def event_label(event):
    row = event.after or event.before or {}
    product = "HSI" if row.get("product_type") == "fixed_wireless" else "Fiber" if row.get("product_type") == "fiber" else VIEW_NAME
    kind = "Amount changed" if event.get("evidence_reason") == "source_backed_amount_change" else "Offer changed" if event.event_type == "modified" else TYPES.get(event.event_type, "Changed")
    return f"{text(event.brand)} · {product} · {kind}"


def render_calendar(runs, changes, selected, brand):
    parts = ['<div class="calendar-scroll"><div class="calendar-grid">']
    parts.extend(f'<div class="weekday">{d}</div>' for d in ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"])
    for week in calendar.Calendar(firstweekday=6).monthdatescalendar(selected.year, selected.month):
        for day in week:
            if day.month != selected.month:
                parts.append('<div class="day empty"></div>')
                continue
            dc = changes[changes.report_date.eq(day)]
            labels = []
            if not dc.empty:
                for _, event in dc.head(3).iterrows():
                    row = event.after or event.before or {}
                    summary = business_summary(event)
                    labels.append(f'<strong>{html.escape(event_label(event))}</strong><small>{html.escape(summary)}</small><small class="offer-title" title="{html.escape(text(row.get("title")), quote=True)}">{html.escape(text(row.get("title")))}</small>')
                if len(dc) > 3:
                    labels.append(f'<small>+{len(dc)-3} more changes</small>')
            elif day <= today:
                label = calendar_status(runs, day, expected_sources)
                if label == "Collection incomplete":
                    label = "No change"
                labels.append(f'<span class="muted">{label}</span>')
            classes = (" selected" if selected == day else "") + (" changed" if len(dc) else "")
            query = html.escape(urlencode({"day": day.isoformat(), "brand": brand}))
            parts.append(f'<a class="day{classes}" href="?{query}" target="_self"><span class="date">{day.day}</span>{"".join(labels)}</a>')
    parts.append('</div></div>')
    st.markdown("".join(parts), unsafe_allow_html=True)


st.markdown("""<style>
.stApp{background:#f5f2eb;color:#22272b}.block-container{max-width:1440px;padding-top:2rem}
h1{font-size:2.2rem!important;letter-spacing:-.035em}h2,h3{letter-spacing:-.02em}
.calendar-scroll{overflow-x:auto;margin:.4rem 0 1.5rem}.calendar-grid{display:grid;grid-template-columns:repeat(7,minmax(125px,1fr));gap:6px;min-width:940px}
.weekday{font-size:12px;color:#68706e;padding:6px 10px;letter-spacing:.08em}
a.day,.day{min-height:112px;background:#ffffff80;border:1px solid #ddd7cd;padding:10px;display:flex;flex-direction:column;gap:5px}
a.day{color:#252a2c;text-decoration:none!important}a.day:hover{background:#fff;border-color:#333}
.day.selected{outline:2px solid #252a2c;outline-offset:-2px}.day.changed{border-top:4px solid #c33d30;background:#fff8f2}
.day.empty{background:transparent;border-color:transparent}.date{font-size:15px;color:#68706e}.day.changed .date{font-weight:800;color:#aa3026}
.day strong{font-size:12px;font-weight:700}.day small{font-size:11px;line-height:1.3}.muted{font-size:11px;color:#747b78}
.offer-title{color:#68706e;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.product-nav{display:flex;gap:8px;margin:0 0 1rem}.product-nav a{padding:7px 20px;border:1px solid #bcb6ad;border-radius:6px;color:#252a2c;text-decoration:none}.product-nav a.active{background:#252a2c;color:white}.original-copy{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6;font-size:14px}.original-copy mark{background:#fff0ad;color:#252a2c;padding:1px 2px}
[data-testid="stMetricValue"]{font-size:1.6rem}[data-testid="stExpander"]{background:#ffffff70}
@media(max-width:700px){.block-container{padding:1rem}h1{font-size:1.7rem!important}.calendar-scroll::before{content:"Swipe horizontally to see all days →";display:block;font-size:12px;color:#68706e;margin-bottom:8px}}
</style>""", unsafe_allow_html=True)

today = datetime.now(ZoneInfo("America/Los_Angeles")).date()
if "selected_day" not in st.session_state:
    try:
        st.session_state.selected_day = date.fromisoformat(st.query_params.get("day", today.isoformat()))
    except ValueError:
        st.session_state.selected_day = today
selected = st.session_state.selected_day
token = None if preview_mode else st.context.headers.get("x-forwarded-access-token")
st.title(f"{VIEW_NAME} offer calendar")


def select_date():
    st.session_state.selected_day = st.session_state.date_picker
    st.query_params["day"] = st.session_state.date_picker.isoformat()


date_col, brand_col, refresh_col = st.columns([2, 2, 1])
with date_col:
    st.date_input("Observation date · Pacific time", value=selected, key="date_picker", on_change=select_date)
with brand_col:
    choices = ["All brands", "AT&T", "T-Mobile", "Verizon"]
    if "brand_filter" not in st.session_state or st.session_state.brand_filter not in choices:
        initial = st.query_params.get("brand", "All brands")
        st.session_state.brand_filter = initial if initial in choices else "All brands"
    brand = st.selectbox("Brand", choices, key="brand_filter")
    st.query_params["brand"] = brand
with refresh_col:
    st.caption("Read latest saved data")
    if st.button("Refresh data", use_container_width=True):
        get_month_data.clear()
        cached_volume_image.clear()
        st.rerun()
links = product_links(selected, brand)
st.markdown('<nav class="product-nav" aria-label="Internet service">' + ''.join(f'<a class="{"active" if name == VIEW_NAME else ""}" href="{html.escape(url, quote=True)}" target="_self">{name}</a>' for name, url in links.items()) + '</nav>', unsafe_allow_html=True)
page_view = st.radio("Workspace", ["Calendar", "Data inspection"], key="workspace_view", horizontal=True, label_visibility="collapsed")
try:
    with st.spinner("Loading Databricks data…"):
        raw_runs, raw_offers = get_month_data(selected.year, selected.month, preview_mode, token)
except Exception as error:
    st.error("Data could not be loaded. This does not mean there are no offers.")
    st.code(f"{type(error).__name__}: {error}")
    st.stop()
if preview_mode:
    st.warning("Layout preview — synthetic sample data, not live collection results.")
runs, offers = daily_view(raw_runs, raw_offers)
if PRODUCT_VIEW != "all":
    runs = runs[runs.source_product_type.eq(PRODUCT_VIEW)]
    offers = offers[offers.run_id.isin(runs.run_id)]
if brand != "All brands":
    runs = runs[runs.brand.eq(brand)]
    offers = offers[offers.run_id.isin(runs.run_id)]
offers = scope_records(offers)
inventory = inventory_records(offers)
expected_sources = [s for s, name in SOURCE_NAMES.items()
                    if (PRODUCT_VIEW == "all" or ("Fiber" in name or "Fios" in name) == (PRODUCT_VIEW == "fiber"))
                    and (brand == "All brands" or name.startswith(brand + " ·"))]
assessments = build_change_events(comparison_runs(runs), inventory, include_diagnostics=True)
changes = assessments[assessments.event_type.ne("review_only")]
diagnostics = assessments[assessments.event_type.eq("review_only")]
day_runs = runs[runs.report_date.eq(selected)]
day_offers = offers[offers.report_date.eq(selected)]
day_inventory = inventory[inventory.report_date.eq(selected)]
day_changes = changes[changes.report_date.eq(selected)]
day_diagnostics = diagnostics[diagnostics.report_date.eq(selected)]
comparison = comparison_status(runs, selected)
comparable = int(comparison.comparable.sum())
image_rows = day_offers[day_offers.get("screenshot_uri", pd.Series(index=day_offers.index, dtype=object)).fillna("").ne("")]


def render_deal_details(row):
    details = deal_details(row)
    kind = {"promotion": "Promotion", "included_benefit": "Included benefit", "standard_pricing": "Plan pricing"}.get(details["deal_type"], "Needs review")
    st.markdown(f"**{kind}**")
    st.markdown(markdown_literal(details["reward_text"] or deal_headline(row)))
    st.caption("Quoted amount / value")
    st.markdown(markdown_literal(amount_summary(row.get("amounts_raw"))))
    for label, field in [("Duration / deadline", "duration_text"), ("Eligibility", "eligibility"), ("Qualifying plan · supporting context", "plan_context")]:
        st.caption(label)
        st.markdown(markdown_literal(details[field] or "Not established in this saved record"))

def render_main():
    st.subheader(f"{selected:%B %Y}")
    st.caption("Select a day to see what changed. Open a change for before / after screenshots and the original evidence. Changes are pending review.")
    st.caption("Track promotions, included benefits and AT&T plan pricing. The inventory below shows what was observed on the selected day, even when nothing changed.")
    render_calendar(runs, changes, selected, brand)
    st.subheader(f"{selected:%B %d, %Y} · Changes")
    st.caption("Compared with the previous successful capture using the same collection method — not necessarily the previous day. Dates are observation dates, not offer effective dates.")
    if day_runs.empty:
        st.info("No collection for this date and brand. This does not mean there were no offers.")
    elif comparable < len(day_runs):
        st.info(f"{comparable} of {len(day_runs)} observed sources compared. New sources establish their first observation.")
    if day_changes.empty:
        status = calendar_status(runs, selected, expected_sources)
        st.write("No change" if status == "Collection incomplete" else status)
        if comparable:
            st.caption("No supported changes found in compared records. Missing records do not prove an offer ended; coverage is limited to the monitored pages.")
    else:
        for index, event in day_changes.reset_index(drop=True).iterrows():
            row = event.after or event.before or {}
            with st.expander(markdown_literal(f"{event_label(event)} — {business_summary(event)}")):
                st.caption(f"Pending review · Compared {event.before_date} → {event.after_date}")
                st.markdown("**What changed**")
                st.markdown(markdown_literal(business_summary(event)))
                st.caption(markdown_literal(text(row.get("title"))))
                if event.event_type != "modified":
                    st.write("Not observed in the earlier capture; observed in the later capture." if event.event_type == "added" else "Observed in the earlier capture; not observed in the later capture. Requires review.")
                left, right = st.columns(2)
                for col, label, evidence, when in [(left, "Before", event.before, event.before_date), (right, "After", event.after, event.after_date)]:
                    with col:
                        st.markdown(f"#### {label} · {when}")
                        if evidence is None:
                            st.info("This record was not observed in this capture.")
                        else:
                            render_image(evidence, token, f"event_{index}_{label}")
                            render_deal_details(evidence)
                st.markdown("**Original text evidence**")
                st.caption("Highlighted words differ in the saved text; not every wording difference is a business change. Screenshots are unaltered.")
                originals = [text((e or {}).get("raw_text"), "") for e in [event.before, event.after]]
                highlighted = highlighted_evidence(*originals) if all(originals) else [html.escape(t) for t in originals]
                for col, label, original in zip(st.columns(2), ["Before", "After"], highlighted):
                    with col:
                        st.caption(label)
                        st.html(f'<div class="original-copy">{original or "No original text available for this side."}</div>')
                if st.checkbox("Show technical details", key=f"technical_{index}"):
                    st.caption(f"Match method: {event.match_strategy} · Similarity: {event.match_score} (not a probability of change).")
                    for evidence in [event.before, event.after]:
                        if evidence:
                            st.caption(f"Screenshot match: {text(evidence.get('screenshot_match_strategy'))} · Source: {source_name(evidence.get('source_id'))}")
    with st.expander("Email alert preview · no email sent"):
        message = draft_change_email(day_changes, selected, VIEW_NAME)
        if message is None:
            st.caption("No detected changes to include in an alert for this date. No-change and first-observation days do not trigger an alert.")
        else:
            st.text(str(message["Subject"]))
            st.text(message.get_content())
            st.download_button("Download email draft", message.as_bytes(), file_name=f"offer-changes-{selected}.eml", mime="message/rfc822")
        st.caption("Automatic delivery is managed by the separate daily Databricks change alert. This preview does not send email.")
    render_inventory()


def render_inventory():
    st.subheader(f"{selected:%B %d, %Y} · Inventory")
    st.caption("Observed on monitored pages, not confirmed active dates or complete market coverage. Benefits are included; AT&T pricing is labelled separately.")
    coverage = []
    for source in expected_sources:
        observed = day_runs[day_runs.source_id.eq(source)]
        items = day_inventory[day_inventory.source_id.eq(source)]
        state = "Not collected" if observed.empty else "Not available" if not observed.status.eq("success").all() else "Collected"
        coverage.append({"Source": source_name(source), "Status": state,
                         "Inventory records": len(items) if len(observed) else None})
    st.dataframe(pd.DataFrame(coverage), hide_index=True, use_container_width=True)
    categories = {"All inventory": None, "Promotions": "promotion", "Included benefits": "included_benefit", "AT&T plan pricing": "standard_pricing"}
    category = st.selectbox("Inventory category", list(categories), key="inventory_category")
    browsable = day_inventory.copy()
    if categories[category]:
        browsable = browsable[browsable.deal_scope.eq(categories[category])]
    if browsable.empty:
        st.info("No inventory records identified for this selection. Check collection status above; this is not proof that no offers exist.")
        return
    browsable = browsable.sort_values(["brand", "deal_scope", "title"]).reset_index(drop=True)
    table = browsable[["brand", "display_title", "deal_scope", "amounts_raw", "source_id"]].copy()
    table["deal_scope"] = table.deal_scope.map({"promotion": "Promotion", "included_benefit": "Included benefit", "standard_pricing": "Plan pricing"})
    table["amounts_raw"] = table.amounts_raw.map(amount_summary)
    table["source_id"] = table.source_id.map(source_name)
    table.columns = ["Brand", "Observed offer / benefit / plan", "Category", "Quoted amount / value", "Source"]
    st.dataframe(table, hide_index=True, use_container_width=True)
    st.download_button("Download inventory CSV", table.to_csv(index=False), file_name=f"inventory-{selected}.csv", mime="text/csv")
    choice = st.selectbox("Inventory details & screenshot", list(browsable.index), format_func=lambda i: f"{browsable.loc[i, 'brand']} · {browsable.loc[i, 'display_title']}", key="browse_offer")
    offer = browsable.loc[choice]
    with st.expander(markdown_literal(deal_headline(offer)), expanded=True):
        render_deal_details(offer)
        render_image(offer, token, f"browse_{offer.get('snapshot_id', choice)}")
        st.caption("Original captured text")
        st.html(f'<div class="original-copy">{html.escape(text(offer.get("raw_text")))}</div>')


def render_inspection():
    st.caption("Supporting records and collection diagnostics. These counts are not daily changes or unique offers.")
    with st.expander("Comparison coverage"):
        status = comparison.copy()
        status["source_id"] = status.source_id.map(source_name)
        st.dataframe(status.rename(columns={"source_id": "Source", "comparison": "Status", "baseline": "Previous comparable date"}).drop(columns="comparable"), hide_index=True, use_container_width=True)

    with st.expander("Extraction diagnostics · excluded from the change calendar"):
        st.caption("Records are not deleted. Same evidence, summary-only differences and incomplete/ambiguous amounts are excluded from the main calendar, not labelled as confirmed business changes.")
        if day_diagnostics.empty:
            st.write("No excluded matched-record differences for this selection.")
        else:
            reasons = {"same_source_evidence": "Same source evidence; extraction drift", "insufficient_source_evidence": "Missing original evidence; review needed", "excerpt_or_extraction_difference": "Shorter/longer excerpt; review needed", "incomplete_or_unaligned_amount_evidence": "Amount types/periods missing or not aligned", "ambiguous_amount_evidence": "Multiple possible amounts; review needed", "unaligned_source_context": "Source context not aligned", "no_supported_core_change": "No supported core-offer change; other text differences excluded"}
            rows = [{"Offer": text((e.after or e.before or {}).get("title")), "Before date": str(e.before_date), "After date": str(e.after_date), "Reason": reasons.get(e.evidence_reason, e.evidence_reason)} for _, e in day_diagnostics.iterrows()]
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    record_tab, evidence_tab = st.tabs(["All captured records", "Screenshots & collection health"])
    with record_tab:
        st.caption("Supporting records, not daily changes. Records may overlap across source pages and are not a count of unique offers.")
        st.metric("Captured records", len(day_offers) if len(day_runs) else "—")
        search = st.text_input("Search records", placeholder="Hulu, Paramount, $35…")
        shown = day_offers.copy()
        scopes = {"All captured records": None, "Promotions": "promotion", "Included benefits": "included_benefit", "Standard pricing / plan context": "standard_pricing", "Marketing / service information": "marketing", "Needs classification review": "review"}
        selected_scope = st.selectbox("Record category", list(scopes), key="record_scope")
        if scopes[selected_scope]:
            shown = shown[shown.deal_scope.eq(scopes[selected_scope])]
        if search and not shown.empty:
            searchable = shown.reindex(columns=["title", "description", "raw_text"]).fillna("").astype(str).agg(" ".join, axis=1)
            shown = shown[searchable.str.contains(search, case=False, regex=False)]
        if shown.empty:
            st.info("No records match this date, brand and search.")
        else:
            shown = shown.sort_values(["brand", "source_id", "title"]).reset_index(drop=True)
            table = shown[["brand", "title", "deal_scope", "amounts_raw", "source_id"]].copy()
            # A missing kicker must not hide a monetary amount quoted in a title.
            table["amounts_raw"] = [a if amount_summary(a) != "No explicit amount captured" else t for a, t in zip(table.amounts_raw, table.title)]
            table["amounts_raw"] = table.amounts_raw.map(amount_summary)
            table["source_id"] = table.source_id.map(source_name)
            table.columns = ["Brand", "Record title · pending review", "Category", "Quoted amount context", "Source page"]
            st.dataframe(table.fillna("Not captured"), hide_index=True, use_container_width=True)
            choice = st.selectbox("Record details", list(shown.index), format_func=lambda i: f"{i+1}. {shown.loc[i, 'brand']} · {shown.loc[i, 'title']}")
            row = shown.loc[choice]
            st.markdown(f"#### {text(row.get('title'))}")
            st.caption("Classification: " + text(row.get("deal_scope")) + " · " + text(row.get("scope_reason")))
            for field in ["description", "amounts_raw", "eligibility", "terms", "raw_text"]:
                st.caption(FIELDS.get(field, "Original captured text"))
                st.text(text(row.get(field)))
            url = safe_url(row.get("source_url"))
            if url:
                st.link_button("Current source website ↗", url)
            st.caption("The source link opens today's website, not a historical archive.")
            if st.checkbox("Show this record's screenshot"):
                render_image(row, token, f"record_{choice}")
    with evidence_tab:
        st.caption("Only the latest attempt per source per Pacific day is shown. Refresh reloads stored data; it does not start a new scrape.")
        if day_runs.empty:
            st.info("No collection on this date.")
        else:
            health = day_runs[["source_id", "status", "coverage", "observed_at"]].copy()
            health["Records"] = health.source_id.map(day_offers.groupby("source_id").size()).fillna(0).astype(int)
            health["Screenshot"] = health.source_id.map(image_rows.groupby("source_id").size()).fillna(0).map(lambda n: "Linked · verify below" if n else "Not linked")
            health["source_id"] = health.source_id.map(source_name)
            health["observed_at"] = pd.to_datetime(health.observed_at, utc=True).dt.tz_convert("America/Los_Angeles").dt.strftime("%H:%M PT")
            st.dataframe(health.rename(columns={"source_id": "Source", "status": "Collection status", "coverage": "Coverage", "observed_at": "Captured at"}), hide_index=True, use_container_width=True)
            st.caption("Successful extraction does not prove full market coverage. Public, address-free pages only; incomplete captures are excluded from change detection.")
            if any(day_offers.get(c, pd.Series(dtype=str)).astype(str).str.startswith("unavailable").any() for c in ["screenshot_lookup_status", "page_evidence_lookup_status"]):
                st.warning("Some screenshot indexes could not be read. Image coverage may be incomplete.")
            if image_rows.empty:
                st.info("No screenshots linked for this selection. Historical images cannot be reconstructed from the current page.")
            else:
                gallery = image_rows.copy()
                gallery["_rank"] = gallery.get("screenshot_evidence_scope", pd.Series(index=gallery.index, dtype=str)).ne("page").astype(int)
                gallery = gallery.sort_values(["source_id", "_rank", "title"]).drop_duplicates("run_id").reset_index(drop=True)
                shot = st.selectbox("Source screenshot", list(gallery.index), format_func=lambda i: source_name(gallery.loc[i, "source_id"]))
                st.caption("One representative capture per source, preferring the full page. Use the image's fullscreen control or download the original to inspect small text.")
                render_image(gallery.loc[shot], token, f"gallery_{shot}")


if page_view == "Calendar":
    render_main()
else:
    st.subheader(f"{selected:%B %d, %Y} · Data inspection")
    render_inspection()
st.caption("Databricks Unity Catalog · Observed inventory and evidence-gated changes · v2026.09.29")
