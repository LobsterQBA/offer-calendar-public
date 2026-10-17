"""Calendar HTML only: comparison decisions stay in dashboard_model/change_logic."""

import calendar
import html
from urllib.parse import urlencode

from dashboard_model import calendar_status
from presentation import business_summary, display_text


EVENT_TYPES = {"modified": "Modified", "added": "Added", "removed": "Removed"}


def event_label(event, view_name="Home internet"):
    record = event.after or event.before or {}
    product = {"fixed_wireless": "HSI", "fiber": "Fiber"}.get(
        record.get("product_type"), view_name
    )
    if event.get("evidence_reason") == "source_backed_amount_change":
        kind = "Amount changed"
    elif event.event_type == "modified":
        kind = "Offer changed"
    else:
        kind = EVENT_TYPES.get(event.event_type, "Changed")
    return f"{display_text(event.brand)} · {product} · {kind}"


def calendar_html(
    runs,
    changes,
    selected,
    brand,
    *,
    today,
    expected_sources,
    view_name,
    service_choice,
):
    """Render explicit date/status links; never relabel incomplete observations."""
    parts = ['<div class="calendar-scroll"><div class="calendar-grid">']
    weekdays = ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")
    parts.extend(f'<div class="weekday">{day}</div>' for day in weekdays)

    for week in calendar.Calendar(firstweekday=6).monthdatescalendar(
        selected.year, selected.month
    ):
        for day in week:
            if day.month != selected.month:
                parts.append('<div class="day empty" aria-hidden="true"></div>')
                continue

            daily_changes = changes[changes.report_date.eq(day)]
            labels = []
            status = "No observation yet"
            if not daily_changes.empty:
                status = f"{len(daily_changes)} change candidates"
                for _, event in daily_changes.head(3).iterrows():
                    record = event.after or event.before or {}
                    title = html.escape(display_text(record.get("title")), quote=True)
                    labels.append(
                        f"<strong>{html.escape(event_label(event, view_name))}</strong>"
                        f"<small>{html.escape(business_summary(event))}</small>"
                        f'<small class="offer-title" title="{title}">{title}</small>'
                    )
                if len(daily_changes) > 3:
                    labels.append(
                        f"<small>+{len(daily_changes) - 3} more changes</small>"
                    )
            elif day <= today:
                status = calendar_status(runs, day, expected_sources)
                labels.append(f'<span class="muted">{html.escape(status)}</span>')

            classes = "day"
            if selected == day:
                classes += " selected"
            if len(daily_changes):
                classes += " changed"
            query = html.escape(
                urlencode(
                    {
                        "day": day.isoformat(),
                        "brand": brand,
                        "service": service_choice,
                    }
                )
            )
            current = ' aria-current="date"' if selected == day else ""
            accessible_label = html.escape(f"{day:%B %d, %Y}: {status}", quote=True)
            parts.append(
                f'<a class="{classes}" href="?{query}" target="_self"'
                f' aria-label="{accessible_label}"{current}>'
                f'<span class="date">{day.day}</span>{"".join(labels)}</a>'
            )

    parts.append("</div></div>")
    return "".join(parts)
