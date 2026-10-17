"""Presentation only: never changes which observations qualify as changes."""
from __future__ import annotations

import base64
import html
import os
import re
from difflib import SequenceMatcher
from decimal import Decimal
from urllib.parse import urlencode

from change_logic import MONEY

APP_URLS = {
    "HSI": os.environ.get("OFFER_CALENDAR_HSI_URL", "https://offer-calendar-hsi-demo.example.com"),
    "Fiber": os.environ.get("OFFER_CALENDAR_FIBER_URL", "https://offer-calendar-fiber-demo.example.com"),
}
AMOUNT_CHANGE = re.compile(
    r"(?P<role>Amount|Value|Reimbursement|Reward|Discount|Fee) "
    r"\((?P<period>month|year|week|unspecified), (?P<qualifier>stated|up to|from)\): "
    r"(?P<old>[$£€][\d,.]+) → (?P<new>[$£€][\d,.]+)"
)


def markdown_literal(value):
    """Keep currency symbols and source copy literal in Streamlit Markdown labels."""
    return re.sub(r"([\\`*_\[\]$<>])", r"\\\1", str(value))


def _specific_money_label(row, amount, role):
    """A more specific label needs one unambiguous source context, not a summary."""
    raw = str((row or {}).get("raw_text") or "").lower()
    target = Decimal(amount[1:].replace(",", ""))
    matches = list(MONEY.finditer(raw))
    labels = set()
    for index, match in enumerate(matches):
        if match.group("currency") != amount[0] or Decimal(match.group("value").replace(",", "")) != target:
            continue
        start = max(match.start() - 45, matches[index - 1].end() if index else 0)
        stop = min(match.end() + 45, matches[index + 1].start() if index + 1 < len(matches) else len(raw))
        context = raw[start:stop]
        patterns = [("Gift card", r"gift card"), ("Cashback", r"cash\s?back")] if role == "Reward" else [("Price", r"\bprice\b")] if role == "Amount" else []
        found = [label for label, pattern in patterns if re.search(pattern, context)]
        labels.add(found[0] if len(found) == 1 else None)
    return next(iter(labels)) if len(labels) == 1 else None


def business_summary(event):
    """Translate accepted comparison output, without reinterpreting AI fields."""
    kind = event.get("event_type")
    if kind == "added":
        return "Newly observed offer"
    if kind == "removed":
        return "Offer no longer observed"
    summary = event.get("change_summary") or "Offer changed"
    if event.get("evidence_reason") != "source_backed_amount_change":
        return summary.replace("Core offer: ", "Offer: ", 1)

    def readable(match):
        role, period, qualifier = match.group("role", "period", "qualifier")
        # Generic amounts stay amounts: a monthly amount is not necessarily a plan price.
        label = {"Value": "Benefit value", "Reward": "Reward", "Reimbursement": "Reimbursement", "Discount": "Discount", "Fee": "Fee", "Amount": "Amount"}[role]
        old_label = _specific_money_label(event.get("before"), match.group("old"), role)
        new_label = _specific_money_label(event.get("after"), match.group("new"), role)
        if old_label and old_label == new_label:
            label = old_label
        if period != "unspecified":
            label = {"month": "Monthly", "year": "Annual", "week": "Weekly"}[period] + " " + label.lower()
        if qualifier == "up to":
            label += " (up to)"
        elif qualifier == "from":
            label += " (starting at)"
        return f"{label}: {match.group('old')} → {match.group('new')}"

    return AMOUNT_CHANGE.sub(readable, summary)


def product_links(day, brand):
    query = urlencode({"day": day.isoformat(), "brand": brand})
    return {name: f"{url}/?{query}" for name, url in APP_URLS.items()}


def highlighted_evidence(before, after):
    """Escape original copy; mark only literal word differences, not business claims."""
    left = re.findall(r"\s+|\S+", before or "")
    right = re.findall(r"\s+|\S+", after or "")
    outputs = [[], []]
    for operation, i, j, a, b in SequenceMatcher(None, left, right, autojunk=False).get_opcodes():
        for target, tokens in zip(outputs, [left[i:j], right[a:b]]):
            value = html.escape("".join(tokens))
            target.append(value if operation == "equal" or not value.strip() else f"<mark>{value}</mark>")
    return tuple("".join(output) for output in outputs)


def screenshot_html(image, scope):
    """Display original pixels in a bounded, zoomable viewport; no image rewriting."""
    src = "data:image/png;base64," + base64.b64encode(image).decode("ascii") if isinstance(image, bytes) else image
    card = scope == "offer_card"
    fit = "height:100%;object-fit:contain;" if card else "height:auto;"
    return f'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{margin:0;font:14px system-ui;color:#333}}.tools{{display:flex;align-items:center;gap:10px;height:38px}}input{{max-width:160px}}.viewport{{height:510px;overflow:auto;background:#fff;border:1px solid #d5cfc5;border-radius:6px}}img{{display:block;width:100%;{fit}}}button{{background:#fff;border:1px solid #bbb;border-radius:4px;padding:4px 8px}}input:focus,button:focus,.viewport:focus{{outline:2px solid #333}}</style></head>
<body><div class="tools"><label for="zoom">Zoom</label><input id="zoom" type="range" min="100" max="250" step="25" value="100" aria-label="Screenshot zoom"><output id="level">100%</output><button id="reset">Reset</button></div>
<div class="viewport" tabindex="0" role="region" aria-label="Original screenshot; scroll to explore"><img id="shot" src="{html.escape(src, quote=True)}" alt="Original {'offer-card' if card else 'source-page'} screenshot"></div>
<script>const zoom=document.getElementById('zoom'),shot=document.getElementById('shot');function update(){{shot.style.width=zoom.value+'%';shot.style.height={str(card).lower()}&&zoom.value==='100'?'100%':'auto';document.getElementById('level').textContent=zoom.value+'%';}}zoom.oninput=update;document.getElementById('reset').onclick=()=>{{zoom.value=100;update();document.querySelector('.viewport').scrollTo(0,0);}};</script></body></html>'''
