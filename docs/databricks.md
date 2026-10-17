# Optional Databricks integration

The local demo runs without cloud credentials. This page describes the additional setup required to use your own saved observations and collection runtime.

Set `OFFER_CALENDAR_CATALOG`, `OFFER_CALENDAR_SCHEMA`, `DATABRICKS_HOST` and `DATABRICKS_WAREHOUSE_ID` for your own environment. The adapter expects the source, run, snapshot, card-screenshot and page-evidence tables named in `data_access.py`; those live schemas and data are not supplied. Set up authentication, table permissions and a screenshot volume yourself. `app.yaml` is a generic Databricks App entry point using an attached SQL warehouse resource; it does not provision infrastructure.

Set `OFFER_CALENDAR_HSI_URL` and `OFFER_CALENDAR_FIBER_URL` for cross-view links. Defaults use reserved example domains. `.env.example` is documentation; variables must be exported or injected by your deployment.

The collector requires a Spark/Databricks runtime, your own tables and volume, Playwright with Chromium, the `scrapegraph-py` package, and `SCRAPEGRAPHAI_API_KEY`. In that environment, load `collector/collector.py`, call `configure(spark, dbutils)`, then explicitly invoke `run_collection()`. Collection calls a paid external service and appends observations. No collection or deployment was performed as part of this release. Provider HTML and API compatibility must be verified before live use.

Email functionality only prepares drafts/digest text; it does not send messages or include recipients.

## Backend contract

The adapter reads five existing tables: `offer_calendar_test_source`, `offer_calendar_test_run`, `offer_calendar_test_snapshot`, `offer_calendar_card_screenshot`, and `offer_calendar_test_evidence`. Screenshot bytes live in a governed volume. Provision these objects and their permissions in your own environment before connecting the app.

The eight-table DDL in [`sql/schema_v3_draft.sql`](../sql/schema_v3_draft.sql) is a separate design proposal. It does not create the five-table backend expected by the app. The classification prompt in `prompts/` is also an earlier design contract; the collector uses its own runtime prompt.

See [`data_access.py`](../apps/offer-calendar/data_access.py) for the actual queries and [`collector.py`](../collector/collector.py) for collection requirements.
