from __future__ import annotations

import json
import re
import unicodedata
from decimal import Decimal
from datetime import date
from difflib import SequenceMatcher
from typing import Iterable

import pandas as pd


COMPARE_FIELDS = (
    "title",
    "description",
    "terms",
    "amounts_raw",
    "eligibility",
    "audience",
    "geography",
    "content_type",
    "cta_url",
)


def _text(value: object) -> str:
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    result = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value))).strip()
    if result.lower().rstrip(".") in {"", "none", "null", "nan", "n/a", "na", "—", "-", "unknown", "not captured", "not provided", "not specified", "no content available", "no specific geography stated"}:
        return ""
    return result


def _normalized_title(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _text(value).lower()).strip()


def _normalized_source_text(value: object) -> str:
    return re.sub(r"[^a-z0-9$%]+", " ", _text(value).lower()).strip()


def _numeric_tokens(value: object) -> tuple[str, ...]:
    return tuple(re.findall(r"\$?\d+(?:[.,]\d+)?%?", _text(value).lower()))


def _token_overlap(left: object, right: object) -> float:
    left_tokens = set(_normalized_title(left).split())
    right_tokens = set(_normalized_title(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _same_source_evidence(before: pd.Series, after: pd.Series) -> bool:
    """Return true when deterministic source evidence proves the card did not change."""
    left_shot = _text(before.get("screenshot_sha256"))
    right_shot = _text(after.get("screenshot_sha256"))
    if left_shot and left_shot == right_shot:
        return True
    left_hash = _text(before.get("content_hash"))
    right_hash = _text(after.get("content_hash"))
    if left_hash and left_hash == right_hash:
        return True
    left_raw = _normalized_source_text(before.get("raw_text"))
    right_raw = _normalized_source_text(after.get("raw_text"))
    return bool(left_raw and left_raw == right_raw)


MONEY = re.compile(r"(?P<currency>[$£€])\s*(?P<value>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)")


def _money_facts(value):
    """Read money from source text, not AI fields. Ambiguous roles stay ambiguous."""
    raw = _text(value).lower()
    matches = list(MONEY.finditer(raw))
    facts = {}
    for i, match in enumerate(matches):
        start = max(0, match.start() - 45, matches[i-1].end() if i else 0)
        stop = min(len(raw), match.end() + 45, matches[i+1].start() if i+1 < len(matches) else len(raw))
        prefix, suffix = raw[start:match.start()], raw[match.end():stop]
        period_match = re.match(r"\s*(?:/|per\s+)\s*(mo(?:nth)?s?|yr|years?|weeks?|wk)\b", suffix)
        period = period_match.group(1) if period_match else "unspecified"
        period = "month" if period.startswith("mo") else "year" if period in {"yr", "year", "years"} else "week" if period in {"week", "weeks", "wk"} else period
        context = prefix + " MONEY " + suffix
        role = "amount"
        for kind, pattern in [("value", r"\bvalue\b"), ("reimbursement", r"reimburs|termination fee|pay off"), ("reward", r"gift card|cash ?back|\bback\b|prepaid|reward"), ("discount", r"discount|\bsave\b|savings|bill credit"), ("fee", r"activation|equipment fee|installation fee")]:
            if re.search(pattern, context):
                role = kind
                break
        qualifier = "up to" if re.search(r"up to\s*(?:a\s*)?$", prefix) else "from" if re.search(r"(?:from|starting at|as low as)\s*$", prefix) else "stated"
        key = (match.group("currency"), period, role, qualifier)
        facts.setdefault(key, set()).add(str(Decimal(match.group("value").replace(",", "")).normalize()))
    return facts


def assess_pair(before, after):
    """Fail closed: only source-backed money or explicit core-offer replacement."""
    if _same_source_evidence(before, after):
        return [], "", "same_source_evidence"
    left, right = _text(before.get("raw_text")), _text(after.get("raw_text"))
    if not left or not right:
        return [], "", "insufficient_source_evidence"
    lnorm, rnorm = _normalized_source_text(left), _normalized_source_text(right)
    if lnorm in rnorm or rnorm in lnorm:
        return [], "", "excerpt_or_extraction_difference"
    lf, rf = _money_facts(left), _money_facts(right)
    if lf != rf:
        if not lf or not rf or lf.keys() != rf.keys():
            return [], "", "incomplete_or_unaligned_amount_evidence"
        deltas = []
        aligned_contexts = []
        for key in lf:
            if lf[key] == rf[key]:
                continue
            if len(lf[key]) != 1 or len(rf[key]) != 1:
                return [], "", "ambiguous_amount_evidence"
            currency, period, role, qualifier = key
            old, new = next(iter(lf[key])), next(iter(rf[key]))
            def contexts(raw, value):
                return [_normalized_source_text(MONEY.sub("AMOUNT", raw[max(0, m.start()-40):m.end()+40])) for m in MONEY.finditer(raw) if str(Decimal(m.group("value").replace(",", "")).normalize()) == value]
            aligned_contexts.append(any(SequenceMatcher(None, a, b).ratio() >= 0.8 for a in contexts(left, old) for b in contexts(right, new)))
            display = lambda v: format(Decimal(v), "f")
            deltas.append(f"{role.capitalize()} ({period}, {qualifier}): {currency}{display(old)} → {currency}{display(new)}")
        # Require comparable surrounding source copy, not unrelated price snippets.
        masked_left = _normalized_source_text(MONEY.sub("AMOUNT", left))
        masked_right = _normalized_source_text(MONEY.sub("AMOUNT", right))
        if deltas and (SequenceMatcher(None, masked_left, masked_right).ratio() >= 0.65 or all(aligned_contexts)):
            return ["amounts_raw"], "; ".join(deltas), "source_backed_amount_change"
        return [], "", "unaligned_source_context"

    # Core changes must be visible in both source-backed headlines. Summary-only
    # title/description/terms changes do not satisfy this gate.
    lt, rt = _normalized_title(before.get("title")), _normalized_title(after.get("title"))
    if not lt or not rt or lt not in _normalized_title(left) or rt not in _normalized_title(right):
        return [], "", "no_supported_core_change"
    if lt == rt:
        return [], "", "no_supported_core_change"
    # An explicit benefit replacement (e.g. Hulu On Us -> Paramount+ On Us),
    # or a changed core speed/duration, is not a terms/eligibility paraphrase.
    benefit_pattern = r"(.+?)\s+(?:on us|for free)$"
    lb, rb = re.search(benefit_pattern, lt), re.search(benefit_pattern, rt)
    features = [r"\b\d+(?:\.\d+)?\s*(?:mbps|gbps|gig)\b", r"\b\d+\s*year price guarantee\b", r"\b\d+\s*months?\s*(?:free|on us)\b"]
    feature_change = any(re.findall(p, lt) and re.findall(p, rt) and re.findall(p, lt) != re.findall(p, rt) for p in features)
    benefit_change = bool(lb and rb and _token_overlap(lb.group(1), rb.group(1)) < 0.25)
    if feature_change or benefit_change:
        return ["title"], f"Core offer: {_text(before.get('title'))} → {_text(after.get('title'))}", "source_backed_core_change"
    return [], "", "no_supported_core_change"


def _changed_fields(before: pd.Series, after: pd.Series) -> list[str]:
    return [field for field in COMPARE_FIELDS if _text(before.get(field)) != _text(after.get(field))]


def _pair_similar_titles(
    before: pd.DataFrame,
    after: pd.DataFrame,
    threshold: float = 0.76,
) -> list[tuple[int, int, float, str]]:
    """Greedily pair unmatched offers using title or deterministic source evidence."""
    candidates: list[tuple[float, int, int, str]] = []
    for before_index, before_row in before.iterrows():
        for after_index, after_row in after.iterrows():
            if _text(before_row.get("product_type")) != _text(after_row.get("product_type")):
                continue
            # content_type is AI-extracted and may drift between offer/benefit/plan.
            left = _normalized_title(before_row.get("title"))
            right = _normalized_title(after_row.get("title"))
            if not left or not right:
                continue
            title_score = SequenceMatcher(None, left, right).ratio()
            left_raw = _normalized_source_text(before_row.get("raw_text"))
            right_raw = _normalized_source_text(after_row.get("raw_text"))
            raw_score = SequenceMatcher(
                None,
                left_raw,
                right_raw,
            ).ratio()
            if title_score >= threshold:
                candidates.append((title_score, before_index, after_index, "title_similarity"))
            elif left_raw and right_raw and raw_score >= 0.75 and _token_overlap(left, right) >= 0.25:
                candidates.append((raw_score, before_index, after_index, "raw_similarity"))

    matches: list[tuple[int, int, float, str]] = []
    used_before: set[int] = set()
    used_after: set[int] = set()
    for score, before_index, after_index, strategy in sorted(candidates, reverse=True):
        if before_index in used_before or after_index in used_after:
            continue
        used_before.add(before_index)
        used_after.add(after_index)
        matches.append((before_index, after_index, score, strategy))
    return matches


def _event_row(
    before: pd.Series | None,
    after: pd.Series | None,
    *,
    before_date: date,
    after_date: date,
    event_type: str,
    changed_fields: Iterable[str],
    match_strategy: str,
    match_score: float | None = None,
    change_summary: str = "",
    evidence_reason: str = "",
) -> dict[str, object]:
    anchor = after if after is not None else before
    assert anchor is not None
    before_id = _text(before.get("snapshot_id")) if before is not None else ""
    after_id = _text(after.get("snapshot_id")) if after is not None else ""
    return {
        "event_id": "|".join(
            [
                _text(anchor.get("source_id")),
                after_date.isoformat(),
                before_id,
                after_id,
                event_type,
            ]
        ),
        "report_date": after_date,
        "before_date": before_date,
        "after_date": after_date,
        "event_type": event_type,
        "changed_fields": list(changed_fields),
        "match_strategy": match_strategy,
        "match_score": match_score,
        "comparison_status": "pending_review",
        "change_summary": change_summary,
        "evidence_reason": evidence_reason,
        "source_id": anchor.get("source_id"),
        "brand": anchor.get("brand"),
        "product_type": anchor.get("product_type"),
        "before": before.to_dict() if before is not None else None,
        "after": after.to_dict() if after is not None else None,
    }


def build_change_events(runs: pd.DataFrame, offers: pd.DataFrame, *, include_diagnostics=False) -> pd.DataFrame:
    """Compare the latest successful daily run to the prior successful day per source.

    Every result is deliberately pending review. Presence changes are emitted only when
    both adjacent runs claim complete coverage.
    """
    columns = [
        "event_id",
        "report_date",
        "before_date",
        "after_date",
        "event_type",
        "changed_fields",
        "match_strategy",
        "match_score",
        "comparison_status",
        "change_summary",
        "evidence_reason",
        "source_id",
        "brand",
        "product_type",
        "before",
        "after",
    ]
    if runs.empty or offers.empty or "report_date" not in runs or "report_date" not in offers:
        return pd.DataFrame(columns=columns)

    successful = runs[runs["status"].astype(str).str.lower().eq("success")].copy()
    if successful.empty:
        return pd.DataFrame(columns=columns)
    successful["_observed_sort"] = pd.to_datetime(successful["observed_at"], utc=True, errors="coerce")
    daily_runs = (
        successful.sort_values(["source_id", "report_date", "_observed_sort"])
        .drop_duplicates(["source_id", "report_date"], keep="last")
        .sort_values(["source_id", "report_date"])
    )

    events: list[dict[str, object]] = []
    for _, source_runs in daily_runs.groupby("source_id", sort=False):
        records = list(source_runs.to_dict("records"))
        for previous_run, current_run in zip(records, records[1:]):
            before_date = previous_run["report_date"]
            after_date = current_run["report_date"]
            before = offers[offers["run_id"].eq(previous_run["run_id"])].copy()
            after = offers[offers["run_id"].eq(current_run["run_id"])].copy()

            before_by_id = {str(row["offer_id"]): index for index, row in before.iterrows()}
            after_by_id = {str(row["offer_id"]): index for index, row in after.iterrows()}
            exact_ids = sorted(set(before_by_id).intersection(after_by_id))
            matched_before: set[int] = set()
            matched_after: set[int] = set()

            for offer_id in exact_ids:
                before_index = before_by_id[offer_id]
                after_index = after_by_id[offer_id]
                matched_before.add(before_index)
                matched_after.add(after_index)
                changed, summary, reason = assess_pair(before.loc[before_index], after.loc[after_index])
                has_difference = _changed_fields(before.loc[before_index], after.loc[after_index]) or _text(before.loc[before_index].get("raw_text")) != _text(after.loc[after_index].get("raw_text"))
                if changed or (include_diagnostics and has_difference):
                    events.append(
                        _event_row(
                            before.loc[before_index],
                            after.loc[after_index],
                            before_date=before_date,
                            after_date=after_date,
                            event_type="modified" if changed else "review_only",
                            changed_fields=changed,
                            match_strategy="offer_id",
                            match_score=1.0,
                            change_summary=summary,
                            evidence_reason=reason,
                        )
                    )

            unmatched_before = before.loc[~before.index.isin(matched_before)]
            unmatched_after = after.loc[~after.index.isin(matched_after)]
            for before_index, after_index, score, strategy in _pair_similar_titles(
                unmatched_before, unmatched_after
            ):
                matched_before.add(before_index)
                matched_after.add(after_index)
                changed, summary, reason = assess_pair(before.loc[before_index], after.loc[after_index])
                if changed or include_diagnostics:
                    events.append(
                        _event_row(
                            before.loc[before_index],
                            after.loc[after_index],
                            before_date=before_date,
                            after_date=after_date,
                            event_type="modified" if changed else "review_only",
                            changed_fields=changed,
                            match_strategy=strategy,
                            match_score=round(score, 3),
                            change_summary=summary,
                            evidence_reason=reason,
                        )
                    )

            complete_pair = (
                str(previous_run.get("coverage")).lower() == "complete"
                and str(current_run.get("coverage")).lower() == "complete"
            )
            if not complete_pair:
                continue

            # Missing source text or the same raw offer elsewhere in the opposite
            # capture cannot establish offer arrival/removal from an ID mismatch.
            before_corpus = " ".join(_normalized_source_text(row.get("raw_text")) for _, row in before.iterrows())
            after_corpus = " ".join(_normalized_source_text(row.get("raw_text")) for _, row in after.iterrows())
            if any(not _text(row.get("raw_text")) for _, row in pd.concat([before, after]).iterrows()):
                continue

            for before_index, before_row in before.loc[~before.index.isin(matched_before)].iterrows():
                if not _text(before_row.get("raw_text")) or after.empty:
                    continue
                if not _normalized_title(before_row.get("title")) or _normalized_title(before_row.get("title")) not in _normalized_title(before_row.get("raw_text")):
                    continue
                if _normalized_source_text(before_row.get("raw_text")) in after_corpus:
                    continue
                events.append(
                    _event_row(
                        before_row,
                        None,
                        before_date=before_date,
                        after_date=after_date,
                        event_type="removed",
                        changed_fields=["presence"],
                        match_strategy="unmatched",
                        change_summary="Offer no longer observed across complete comparable captures; pending review.",
                        evidence_reason="complete_capture_presence_change",
                    )
                )

            for after_index, after_row in after.loc[~after.index.isin(matched_after)].iterrows():
                if not _text(after_row.get("raw_text")) or before.empty:
                    continue
                if not _normalized_title(after_row.get("title")) or _normalized_title(after_row.get("title")) not in _normalized_title(after_row.get("raw_text")):
                    continue
                if _normalized_source_text(after_row.get("raw_text")) in before_corpus:
                    continue
                events.append(
                    _event_row(
                        None,
                        after_row,
                        before_date=before_date,
                        after_date=after_date,
                        event_type="added",
                        changed_fields=["presence"],
                        match_strategy="unmatched",
                        change_summary="New offer observed across complete comparable captures; pending review.",
                        evidence_reason="complete_capture_presence_change",
                    )
                )

    return pd.DataFrame(events, columns=columns)
