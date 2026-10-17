from __future__ import annotations

import os
import re
from contextlib import contextmanager
from datetime import date, timedelta
from difflib import SequenceMatcher
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd


CATALOG = os.environ.get("OFFER_CALENDAR_CATALOG", "example_analytics")
SCHEMA = os.environ.get("OFFER_CALENDAR_SCHEMA", "offers")
if not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", name) for name in (CATALOG, SCHEMA)):
    raise ValueError("Catalog and schema must be simple SQL identifiers.")
SOURCE_TABLE = f"`{CATALOG}`.`{SCHEMA}`.`offer_calendar_test_source`"
RUN_TABLE = f"`{CATALOG}`.`{SCHEMA}`.`offer_calendar_test_run`"
SNAPSHOT_TABLE = f"`{CATALOG}`.`{SCHEMA}`.`offer_calendar_test_snapshot`"
SCREENSHOT_TABLE = f"`{CATALOG}`.`{SCHEMA}`.`offer_calendar_card_screenshot`"
EVIDENCE_TABLE = f"`{CATALOG}`.`{SCHEMA}`.`offer_calendar_test_evidence`"


@contextmanager
def sql_connection(user_access_token: str | None = None):
    """Open a read-only Databricks SQL connection for the current app user."""
    from databricks import sql
    from databricks.sdk.core import Config

    warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID")
    if not warehouse_id:
        raise RuntimeError("The app has no SQL warehouse resource.")

    config = None
    host = os.environ.get("DATABRICKS_HOST")
    if not host or not user_access_token:
        config = Config()
        host = config.host
    hostname = host.removeprefix("https://").removeprefix("http://")
    auth = (
        {"access_token": user_access_token}
        if user_access_token
        else {"credentials_provider": lambda: config.authenticate}
    )
    connection = sql.connect(
        server_hostname=hostname,
        http_path=f"/sql/1.0/warehouses/{warehouse_id}",
        _use_arrow_native_complex_types=False,
        **auth,
    )
    try:
        yield connection
    finally:
        connection.close()


def query_frame(query: str, user_access_token: str | None = None) -> pd.DataFrame:
    with sql_connection(user_access_token) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query)
            return cursor.fetchall_arrow().to_pandas()


def _evidence_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def attach_available_screenshots(offers: pd.DataFrame, screenshots: pd.DataFrame) -> pd.DataFrame:
    """Attach existing verified T-Mobile card evidence without overstating fuzzy matches."""
    offers = offers.copy()
    offers["screenshot_match_strategy"] = None
    offers["screenshot_offer_title"] = None
    offers["screenshot_evidence_type"] = None
    offers["screenshot_evidence_scope"] = None
    offers["screenshot_card_key"] = None
    offers["screenshot_sha256"] = None
    offers["screenshot_captured_at"] = None
    if offers.empty or screenshots.empty:
        return offers

    screenshots = screenshots.copy()
    screenshots["source_date"] = pd.to_datetime(screenshots["source_date"], errors="coerce").dt.date
    screenshots["title_key"] = screenshots["offer_title"].map(_evidence_text)

    observed_dates = pd.to_datetime(offers["observed_at"], utc=True, errors="coerce")
    offers["_source_date"] = observed_dates.dt.tz_convert("America/Los_Angeles").dt.date
    for index, offer in offers.iterrows():
        if _evidence_text(offer.get("screenshot_uri")):
            offers.at[index, "screenshot_match_strategy"] = "snapshot_uri"
            offers.at[index, "screenshot_evidence_scope"] = "offer_card"
            continue
        if str(offer.get("source_id")) != "tmobile_hsi_deals":
            continue
        candidates = screenshots[
            screenshots["source_date"].eq(offer["_source_date"])
            & screenshots["volume_path"].notna()
            & screenshots["title_key"].str.len().ge(10)
        ]
        snapshot_title = _evidence_text(offer.get("title"))
        raw_text = _evidence_text(offer.get("raw_text"))
        matches: list[tuple[float, int, str]] = []
        for shot_index, shot in candidates.iterrows():
            shot_title = shot["title_key"]
            if shot_title == snapshot_title:
                matches.append((1.0, shot_index, "exact_title"))
            elif shot_title in raw_text:
                matches.append((0.96, shot_index, "captured_text"))
            elif snapshot_title and SequenceMatcher(None, shot_title, snapshot_title).ratio() >= 0.88:
                matches.append((0.88, shot_index, "title_similarity"))
        if not matches:
            continue
        score, shot_index, strategy = max(matches, key=lambda item: (item[0], len(candidates.loc[item[1], "title_key"])))
        shot = candidates.loc[shot_index]
        offers.at[index, "screenshot_uri"] = shot["volume_path"]
        offers.at[index, "screenshot_match_strategy"] = strategy
        offers.at[index, "screenshot_offer_title"] = shot["offer_title"]
        offers.at[index, "screenshot_evidence_type"] = shot.get("evidence_type")
        offers.at[index, "screenshot_evidence_scope"] = "offer_card"
        offers.at[index, "screenshot_card_key"] = shot.get("card_key")
        offers.at[index, "screenshot_sha256"] = shot.get("sha256")
        offers.at[index, "screenshot_captured_at"] = shot.get("rendered_at")
    return offers.drop(columns=["_source_date"])


def attach_page_evidence(offers: pd.DataFrame, evidence: pd.DataFrame) -> pd.DataFrame:
    """Keep the same-run full page alongside any card, without replacing card evidence."""
    offers = offers.copy()
    offers["page_screenshot_uri"] = None
    offers["page_screenshot_captured_at"] = None
    if offers.empty or evidence.empty:
        return offers
    latest = (
        evidence.sort_values("captured_at")
        .drop_duplicates("run_id", keep="last")
        .set_index("run_id")
    )
    for index, offer in offers.iterrows():
        run_id = offer.get("run_id")
        if run_id not in latest.index:
            continue
        page = latest.loc[run_id]
        offers.at[index, "page_screenshot_uri"] = page["volume_path"]
        offers.at[index, "page_screenshot_captured_at"] = page["captured_at"]
        if _evidence_text(offer.get("screenshot_uri")):
            continue
        offers.at[index, "screenshot_uri"] = page["volume_path"]
        offers.at[index, "screenshot_match_strategy"] = "run_page_fallback"
        offers.at[index, "screenshot_offer_title"] = "Full source page"
        offers.at[index, "screenshot_evidence_type"] = page["evidence_type"]
        offers.at[index, "screenshot_evidence_scope"] = page["evidence_scope"]
        offers.at[index, "screenshot_captured_at"] = page["captured_at"]
    return offers


def load_month(
    month_start: date,
    next_month_start: date,
    user_access_token: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return the month plus enough prior history for day-over-day comparisons."""
    start = (month_start - timedelta(days=45)).isoformat()
    end = next_month_start.isoformat()

    runs = query_frame(
        f"""
        SELECT
          r.run_id,
          r.source_id,
          r.scheduled_for,
          r.observed_at,
          r.status,
          r.coverage,
          r.diagnostics_uri,
          s.brand,
          s.product_type AS source_product_type,
          s.source_url,
          s.context
        FROM {RUN_TABLE} r
        LEFT JOIN {SOURCE_TABLE} s ON r.source_id = s.source_id
        WHERE DATE(FROM_UTC_TIMESTAMP(COALESCE(r.observed_at, r.scheduled_for),
              'America/Los_Angeles')) >= DATE('{start}')
          AND DATE(FROM_UTC_TIMESTAMP(COALESCE(r.observed_at, r.scheduled_for),
              'America/Los_Angeles')) < DATE('{end}')
        """,
        user_access_token,
    )

    offers = query_frame(
        f"""
        WITH ranked AS (
          SELECT
            sn.*,
            ROW_NUMBER() OVER (
              PARTITION BY sn.run_id, sn.offer_id
              ORDER BY
                CASE sn.revision_kind WHEN 'human' THEN 3 WHEN 'ai' THEN 2 ELSE 1 END DESC,
                sn.revised_at DESC,
                sn.snapshot_id DESC
            ) AS revision_rank
          FROM {SNAPSHOT_TABLE} sn
        )
        SELECT
          sn.snapshot_id,
          sn.run_id,
          sn.offer_id,
          sn.revised_at,
          sn.revision_kind,
          sn.review_status,
          sn.product_type,
          sn.title,
          sn.description,
          sn.terms,
          sn.source_category,
          sn.cta_url,
          sn.content_type,
          to_json(sn.tags) AS tags,
          sn.audience,
          sn.geography,
          sn.eligibility,
          sn.amounts_raw,
          sn.effective_start_date,
          sn.effective_end_date,
          sn.screenshot_uri,
          sn.raw_text,
          sn.content_hash,
          r.source_id,
          r.observed_at,
          r.status AS run_status,
          r.coverage,
          src.brand,
          src.source_url
        FROM ranked sn
        JOIN {RUN_TABLE} r ON sn.run_id = r.run_id
        LEFT JOIN {SOURCE_TABLE} src ON r.source_id = src.source_id
        WHERE sn.revision_rank = 1
          AND DATE(FROM_UTC_TIMESTAMP(COALESCE(r.observed_at, sn.revised_at),
              'America/Los_Angeles')) >= DATE('{start}')
          AND DATE(FROM_UTC_TIMESTAMP(COALESCE(r.observed_at, sn.revised_at),
              'America/Los_Angeles')) < DATE('{end}')
        """,
        user_access_token,
    )
    try:
        screenshots = query_frame(
            f"""
            WITH ranked AS (
              SELECT
                DATE(FROM_UTC_TIMESTAMP(source_observed_at, 'America/Los_Angeles')) AS source_date,
                card_key,
                offer_title,
                volume_path,
                sha256,
                evidence_type,
                rendered_at,
                ROW_NUMBER() OVER (
                  PARTITION BY DATE(FROM_UTC_TIMESTAMP(source_observed_at, 'America/Los_Angeles')), card_key
                  ORDER BY rendered_at DESC
                ) AS screenshot_rank
              FROM {SCREENSHOT_TABLE}
              WHERE status = 'success'
                AND volume_path IS NOT NULL
                AND DATE(source_observed_at) >= DATE('{start}')
                AND DATE(source_observed_at) < DATE('{end}')
            )
            SELECT source_date, card_key, offer_title, volume_path, sha256, evidence_type, rendered_at
            FROM ranked
            WHERE screenshot_rank = 1
            """,
            user_access_token,
        )
        offers = attach_available_screenshots(offers, screenshots)
        offers["screenshot_lookup_status"] = "available"
    except Exception as error:
        offers = attach_available_screenshots(offers, pd.DataFrame())
        offers["screenshot_lookup_status"] = f"unavailable: {type(error).__name__}"
    try:
        page_evidence = query_frame(
            f"""
            SELECT
              run_id,
              source_id,
              evidence_scope,
              evidence_type,
              volume_path,
              captured_at
            FROM {EVIDENCE_TABLE}
            WHERE status = 'success'
              AND evidence_scope = 'page'
              AND volume_path IS NOT NULL
              AND DATE(FROM_UTC_TIMESTAMP(source_observed_at, 'America/Los_Angeles')) >= DATE('{start}')
              AND DATE(FROM_UTC_TIMESTAMP(source_observed_at, 'America/Los_Angeles')) < DATE('{end}')
            """,
            user_access_token,
        )
        offers = attach_page_evidence(offers, page_evidence)
        offers["page_evidence_lookup_status"] = "available"
    except Exception as error:
        offers["page_evidence_lookup_status"] = f"unavailable: {type(error).__name__}"
    return runs, offers


def read_volume_file(
    volume_path: str,
    user_access_token: str,
    *,
    max_bytes: int = 12 * 1024 * 1024,
) -> bytes:
    """Download one governed Unity Catalog Volume file as the current app user."""
    if not volume_path.startswith("/Volumes/"):
        raise ValueError("Only /Volumes paths can be downloaded through the Files API.")
    if not user_access_token:
        raise RuntimeError("A forwarded Databricks user token is required for screenshots.")
    host = os.environ.get("DATABRICKS_HOST")
    if not host:
        raise RuntimeError("DATABRICKS_HOST is unavailable.")
    host = host.strip().rstrip("/")
    if "://" not in host:
        host = "https://" + host
    encoded_path = quote(volume_path, safe="/")
    request = Request(
        f"{host.rstrip('/')}/api/2.0/fs/files{encoded_path}",
        headers={"Authorization": f"Bearer {user_access_token}"},
    )
    with urlopen(request, timeout=20) as response:
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ValueError("Screenshot is larger than the 12 MB dashboard limit.")
    return body


def read_volume_image_sql(volume_path: str, user_access_token: str) -> bytes:
    """Read screenshot bytes through the viewer's governed SQL connection."""
    prefix = f"/Volumes/{CATALOG}/{SCHEMA}/offer_calendar_screenshots/"
    if not volume_path.startswith(prefix) or any(c in volume_path for c in ("*", "?", "[", "]")):
        raise ValueError("Expected a single file in the screenshot volume.")
    if ".." in volume_path.split("/"):
        raise ValueError("Invalid screenshot path.")
    if not user_access_token:
        raise RuntimeError("A forwarded Databricks user token is required for screenshots.")
    with sql_connection(user_access_token) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT content FROM read_files(:path, format => 'binaryFile') "
                "WHERE length <= 12582912 LIMIT 1",
                {"path": volume_path},
            )
            row = cursor.fetchone()
    if row is None:
        raise ValueError("Screenshot is missing or exceeds the 12 MB image limit.")
    return bytes(row[0])
