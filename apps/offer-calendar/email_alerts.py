"""Preview-only email alerts. No network access, recipients or sending side effects."""
from email.message import EmailMessage
from presentation import business_summary


def draft_change_email(changes, selected, view):
    """Only genuine candidate events for the selected date can enter an alert."""
    rows = changes[changes.report_date.eq(selected) & changes.event_type.isin(["added", "modified", "removed"])]
    if rows.empty:
        return None
    message = EmailMessage()
    message["Subject"] = f"Offer Calendar | {view} | {selected} | {len(rows)} changes to review"
    lines = [f"Observed changes on {selected} ({view})", "", "Machine-detected candidates, pending human review."]
    for _, event in rows.iterrows():
        lines.extend(["", f"{event.brand}: {business_summary(event)}",
                      f"Compared {event.before_date} to {event.after_date}"])
    lines.extend(["", "No email has been sent. Add approved recipients before sending.",
                  "Dates are capture dates, not confirmed campaign start/end dates."])
    message.set_content("\n".join(lines))
    return message
