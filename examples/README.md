# Three observations, three different conclusions

Run this from the repository root after installing `requirements-dev.txt`:

```bash
python examples/compare_offers.py
```

The example calls the same comparison functions as the Streamlit app. All input is synthetic. No API key, database or network access is needed.

## 1. A price changes in the original text

| September 15 | September 16 |
| --- | --- |
| Fiber internet **$50/mo**. For eligible new customers. | Fiber internet **$45/mo**. For eligible new customers. |

**Result:** `Monthly amount: $50 → $45`, one change candidate.

Both observations refer to the same offer and the same monthly amount role. The saved source wording supports the difference. The candidate still needs human review; capture dates do not prove when the price took effect.

## 2. Only the AI description changes

The saved webpage text is identical, but the extraction model rewrites its description.

**Result:** `No change`, zero change candidates. The diagnostic reason is `same_source_evidence`.

This is why the project retains original text. Comparing only model-generated summaries would create false alarms.

## 3. Collection fails

September 15 has an offer. September 16's page fetch fails and produces no new offer record.

**Result:** `Collection incomplete`, zero change candidates.

An unsuccessful observation does not establish that the offer disappeared. The dashboard preserves the failure instead of claiming a removal or a verified no-change day.

## Explore the interface

Run `python demo.py`, then:

1. Open the highlighted September 16 change in the **Fiber** view.
2. Compare the original text before and after; changed amounts are highlighted.
3. Switch to **Data inspection** to see the records and collection health behind the calendar.
4. Try **Fixed wireless** and select **Verizon** on September 16 to inspect a failed capture.

The demo is synthetic and includes no historical provider screenshots. Missing screenshots remain labelled as missing.
