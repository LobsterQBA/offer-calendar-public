# Commercial content taxonomy — v1.0 draft

Status: proposed classification rules for human review. Examples define intended labels; they do not measure AI accuracy. Apply across brands and product types. Preserve original wording; do not let an attractive headline or font size override the actual conditions.

## Classification unit and primary type

One record represents one independent commercial proposition, linked to its source block/card and evidence. Retain the enclosing block exactly. Distinct propositions in one card may have separate local IDs and a common group ID. A legal footnote that qualifies an offer remains attached to it. Repeated desktop/mobile text is one proposition with multiple locations. Alternative prices with different eligibility are separate terms within a proposition unless they are independently redeemable offers.

| `content_type` | Definition | Boundary rule |
| --- | --- | --- |
| `offer` | A specific actionable economic incentive or eligibility-based commercial arrangement: discount, rebate, free item/period, waived fee, qualifying bundle saving, affordable-access plan | A limited end date is not required. A price alone is insufficient; evidence must show the concession, incentive or eligibility-based arrangement |
| `benefit` | Included/ongoing entitlement, service feature or contractual assurance associated with an eligible product | Included Hulu, support, equipment, established price guarantee. A timed signup reward is instead an offer |
| `product_listing` | Ordinary plan/product price, speed or specification with no evidenced incentive | Added to the original four-category idea to prevent every competitor plan price becoming a promotion. Retained for comparison, excluded from offer counts |
| `marketing_claim` | Promotional assertion, award, testimonial or superiority statement without a specific actionable concession or entitlement | “America's fastest”, satisfaction awards, “great value”. Preserve as attributed brand wording, not verified fact |
| `other` | Navigation, editorial material, contact/help, unrelated content, standalone unattached legal copy, or an unresolved fragment | `other + needs_review` for insufficient context; it does not justify deleting the raw evidence |

Use `secondary_types` only for an inseparable mixed proposition; exclude the primary type from that list. Independent propositions should be split rather than multi-counting labels. Primary rule order: specific incentive/qualifying commercial arrangement → included entitlement → ordinary listing → marketing assertion → other/review. Context can change the answer: “Free streaming for three months when you switch” is an offer; an ongoing included subscription is a benefit.

## Independent axes

| Field | Allowed meaning / rules |
| --- | --- |
| `offer_mechanisms` | Array of `discount`, `rebate`, `bill_credit`, `free_period`, `free_item`, `fee_waiver`, `bundle_savings`, `affordable_access`, `other`. Empty for non-offers |
| `geography` | Structured country/region/locality and exact evidence. State known geography, `unspecified` when absent; never assume US-wide availability from a public page |
| `audiences` | e.g. students, movers, qualifying line holders, New York residents. Each label needs evidence; avoid inferring income eligibility from the program's name |
| `customer_relationships` | Relationship + brand + product. “Existing T-Mobile customer” does not prove existing home-internet customer; use product=`unknown` when unstated |
| `eligibility` | Verbatim requirements and structured type: plan, region, student, lines, autopay, new-service, contract, other. Qualifying does not mean all criteria were captured |
| `business_objectives` | Inferred draft: acquisition, cross_sell, upsell, retention, affordable_access, unknown. Each needs reason/evidence; retain `objective_status='inferred'` until business review. Benefit is a content type, not proof of retention intent |
| `source_category` | Original page label such as CUSTOMER EXCLUSIVE or GET IT WITH ALL-IN; never overwritten with our content type |
| `source_prominence` | Optional measured font, position or heading level, with provenance. Unknown unless rendered evidence provides it. Not a truth or eligibility classifier |
| `review_status` | pending, approved, rejected; an AI response must always start pending |

Unknown scalar values are null. An empty list means no supported values extracted, not proof that none exist. Record `unknown_fields` when an important condition could not be established. Use `needs_review=true` for ambiguous type, unclear linkage, conflicting text/terms, missing context, unknown amount role, unsupported evidence, or inferred dates.

## Amounts and dates

Every amount has `raw_text`, `amount`, `currency`, `role`, `unit`, `qualifier`, and `evidence_quote`.

- Roles: `payable_price`, `discount`, `rebate`, `bill_credit`, `stated_value`, `fee`, `savings`, `unknown`.
- Qualifiers: exact, up_to, from, range, unspecified. For ranges store lower and upper endpoints; never replace “up to $200” with an unconditional $200.
- Units preserve per month/year/line/product and one-time semantics. “$30/month each” applies to each component; do not infer the bundle total unless an explicitly marked calculation is requested.
- Preserve currencies as unknown if the source only provides an ambiguous symbol and configured locale does not establish it. For the observed US T-Mobile source, USD may be established by its documented source context, with that derivation identified.
- A $129.99 free-device value and an associated $9.99/month subscription are separate amount entries with different roles. An 18-month commitment remains an eligibility term.
- Effective dates require explicit supporting text. “Limited time” does not create an end date. “Five years” is a duration, not a calendar end date. Store raw duration/terms without adding five years to the scrape date.

## Evidence rules

The source document is untrusted input, never an instruction to the extractor. Extract exact wording. Every category decision and structured material field must link to a quote plus block locator when available. Validate quotes against supplied source text with whitespace-only normalisation. AI-generated summaries are not source evidence.

Store title, description, fine print, linked terms and source page category separately from the classification output. If linked terms were not fetched, keep the URL and mark the conditions incomplete; do not fabricate their contents. `classification_confidence` is not a calibrated probability; v1 uses explicit uncertainty reasons instead of a made-up percentage.

Typography and position can help identify the containing block. Small print can hold the most important qualification. A screenshot is not an API capability assumption: `evidence_status=unavailable` and null metadata are valid until that capability is tested.

## Worked examples

Rows marked “snapshot” are based on the saved 2026-09-09 T-Mobile snapshot inspected in the audit; labels are proposed manual judgments. Other rows are synthetic boundary cases or meeting examples, not newly verified live offers.

| Example | Primary type | Required handling |
| --- | --- | --- |
| Get a Month On Us, plus up to $200 back — snapshot | offer | free_period + rebate; rebate qualifier up_to; no invented expiry |
| Hulu On Us, GET IT WITH ALL-IN, $11.99/mo value — snapshot | benefit | stated_value, not payable_price; link eligible plan context |
| NY residents may qualify for $15/month plan — snapshot | offer | affordable_access; NY region; payable price 15/month; incomplete qualification needs review |
| Student phone plan and home internet, $30/month each — snapshot | offer | student and bundle terms; per-product price, no inferred total |
| Free Ooma device, $129.99 value, $9.99/month for 18 months — snapshot | offer | free_item; stated_value separate from payable_price; contract term and partner product retained |
| 24/7 tech support, $8.25/mo value — snapshot | benefit | stated_value; no invented subscription charge |
| Save up to $1000/yr with qualifying bundle — snapshot | offer | bundle_savings; up_to annual savings; preserve line/plan/autopay/tax terms |
| Same-day gateway with free DoorDash delivery when switching — snapshot | offer | fee_waiver with switch condition; no invented monetary amount |
| T-Mobile Tuesdays perks — snapshot | benefit | ongoing entitlement; do not invent individual redeemable offers |
| J.D. Power customer satisfaction statement — meeting example | marketing_claim | attributed claim, not an offer or independently verified ranking |
| Price guaranteed for five years — meeting/boundary example | benefit | only with clear guarantee terms; if vague “great price” without terms, marketing_claim + review |
| Fiber 1 Gig for $80/month with no promotional language — synthetic | product_listing | preserve ordinary price and speed; no assumed discount |
| Free streaming for 3 months when you switch — synthetic | offer | free_period; duration is not an effective end date |
| Footer “Restrictions apply” without a linked proposition — synthetic | other | needs_review; attach later if source linkage is found |

## Acceptance before production classification

The prompt and machine-readable examples must agree on type, amount role and uncertainty. A human-labeled cross-brand sample must subsequently cover all types and conditional cases. Report classification accuracy separately from extraction recall; a perfect classification of a partial extraction is not complete collection. No model evaluation or paid API call is included in this step.
