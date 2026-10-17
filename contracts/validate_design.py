"""Offline design checks only. Does not call an LLM, fetch pages or touch Databricks."""
import json
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
types = {"offer", "benefit", "product_listing", "marketing_claim", "other"}
mechanisms = {"discount", "rebate", "bill_credit", "free_period", "free_item", "fee_waiver", "bundle_savings", "affordable_access", "other"}
roles = {"payable_price", "discount", "rebate", "bill_credit", "stated_value", "fee", "savings", "unknown"}
fixture = json.loads((ROOT / "contracts/classification-examples.json").read_text())
examples = fixture["examples"]
assert fixture["status"] == "manual_design_fixtures_not_model_results"
assert len({e["id"] for e in examples}) == len(examples)
assert {e["expected_type"] for e in examples} == types
for e in examples:
    assert set(e["expected_mechanisms"]) <= mechanisms, e["id"]
    assert e["expected_type"] == "offer" or not e["expected_mechanisms"], e["id"]
    for amount in e["amount_expectations"]:
        assert amount["role"] in roles, e["id"]
        assert amount["quote"] in e["text"], e["id"]
        assert amount["qualifier"] in {"exact", "up_to", "from", "range", "unspecified"}

sql = (ROOT / "sql/schema_v3_draft.sql").read_text()
ddl = re.sub(r"(?m)^--.*$", "", sql)
# Match whole statements: SQL comment literals can contain semicolons.
statements = re.findall(r"CREATE TABLE IF NOT EXISTS .*?USING DELTA COMMENT '[^']*';", ddl, re.S)
expected_tables = {"source", "run", "capture", "observation", "interpretation", "version", "change_event", "evidence"}
seen_tables = set()
field_counts = {}
schema_hashes = {}
for s in statements:
    match = re.fullmatch(r"CREATE TABLE IF NOT EXISTS `example_analytics`\.offers\.offer_calendar_v3_(\w+) \(\n(.*?)\n\) USING DELTA COMMENT '[^']*';", s, re.S)
    assert match, "Unexpected DDL statement"
    name, body = match.groups()
    assert name not in seen_tables
    seen_tables.add(name)
    cols = re.findall(r"(?m)^  (\w+) ", body)
    assert len(cols) == len(set(cols)), name
    field_counts[name] = len(cols)
    compact = "".join(body.split()).lower()
    schema_hashes[name] = hashlib.sha256(compact.encode()).hexdigest()
assert seen_tables == expected_tables
assert not re.sub(r"CREATE TABLE IF NOT EXISTS .*?USING DELTA COMMENT '[^']*';", "", ddl, flags=re.S).strip()

prompt = (ROOT / "prompts/extraction-classification-v1.md").read_text()
shape = json.loads(re.search(r"```json\n(.*?)\n```", prompt, re.S).group(1))
assert shape["taxonomy_version"] == fixture["taxonomy_version"]
assert shape["items"][0]["review_status"] == "pending"
for kind in types:
    assert kind in prompt
    assert kind in (ROOT / "docs/taxonomy.md").read_text()

print(json.dumps({"examples": len(examples), "primary_types": len(types), "tables": field_counts,
                  "schema_hashes": schema_hashes,
                  "result": "PASS: design consistency only; no model or deployment validation"}, indent=2))
