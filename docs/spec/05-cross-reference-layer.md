# Cross-Reference Layer — Joins, Field Algebra & Presentation

*Companion to `01-system-specification-v3.md`, `02-build-plan-and-parts.md`, `03-data-sources.md`, `04-data-product-design.md`. Part of the data product; built at stages A4–A6 in `02-build-plan-and-parts.md` §2.*

---

## 1. The organizing frame

Cross-referencing looks like one problem and is actually four, each answerable deterministically and each needing a different mechanism:

| Question | Mechanism | §  |
|---|---|---|
| Do these share an axis? | Join spines | 2 |
| Are these the same thing? | Identity tiers | 3–4 |
| What operations are valid on this pair? | Field algebra | 6 |
| What is declared to connect them? | Relation registry, phenomenon groups | 7–8 |

Then two surfaces (§9–10) and two presentations (§11–12). The separation matters because conflating them is how APIs end up either refusing valid joins or silently serving invalid ones.

**The boundary, stated once and defended throughout:** this layer serves the *algebra* — what is structurally valid and what is declared. It never serves inference. `/relate` answers what you *can* do, never what is *true*.

---

## 2. Join spines

Five axes everything joins on. A field is cross-referenceable with another exactly when they share at least one.

| Spine | Key | Notes |
|---|---|---|
| **Entity** | `entity_id` | The universal one. CIK-anchored, point-in-time tickers. This is why the entity layer is load-bearing rather than a utility |
| **Instrument** | `instrument_id` | One entity has many, and they are **not** interchangeable — share classes, options, ADRs, convertibles. An entity-level join across instruments is usually wrong |
| **Person** | `person_id` | Form 4 filers, executives, congresspeople, journalists, social authors. The hardest spine to resolve across sources |
| **Document** | `accession` / `doc_id` | The lineage axis. Everything derived from one filing shares it, which is what makes independence computable |
| **Event** | `event_id` | The differentiated one — §3 |

**Instrument-vs-entity is the spine people get wrong.** Fundamentals are entity-level; prices, options and short interest are instrument-level. Joining an entity's revenue to "its" price requires choosing an instrument, and that choice must be explicit rather than defaulted to the primary class silently.

---

## 3. The event spine

One real-world occurrence surfaces across many measurement processes. A drug approval appears as an openFDA record, a press release, a Federal Register notice, forty news articles, an 8-K, and a resolved prediction market — six independent processes, one event.

```json
{
  "event": {
    "id": "evt_9k2m4x",
    "type": "regulatory_approval",
    "subject_entities": ["ent_0000078003"],
    "first_knowable_at": "2019-04-12T13:04:00Z",
    "cluster_rule": "identifier_exact",
    "cluster_version": "es_2026.2",
    "observations": [
      { "source": "openfda", "knowable_at": "2019-04-12T13:04:00Z",
        "join_tier": 1, "join_key": "NDA-021436", "provenance_class": "measured" },
      { "source": "wire.businesswire", "knowable_at": "2019-04-12T13:31:00Z",
        "join_tier": 1, "join_key": "NDA-021436", "provenance_class": "measured" },
      { "source": "edgar.8k", "knowable_at": "2019-04-12T21:02:00Z",
        "join_tier": 2, "join_key": "entity+type+48h", "provenance_class": "derived" },
      { "source": "gdelt.news", "knowable_at": "2019-04-12T14:10:00Z",
        "join_tier": 3, "confidence": 0.88, "count": 43, "provenance_class": "matched",
        "url": "/v1/events/evt_9k2m4x/observations?source=gdelt.news" }
    ]
  }
}
```

**`first_knowable_at` is the field nobody else serves.** "When did this actually become public?" requires clustering across heterogeneous sources and comparing availability timestamps, and it is exactly what a backtest needs. It is also cheap once the cluster exists.

### Identity tiers — the same tiered logic as basis alignment

| Tier | Basis | Class | Confidence |
|---|---|---|---|
| **1 — shared identifier** | An identifier present in both records: FDA application number, Federal Register document number, accession, contract id, patent number | `measured` | 1.0 |
| **2 — structural coincidence** | Same entity + same declared event type + `knowable_at` within a **declared** window | `derived` | < 1.0, rule reported |
| **3 — semantic match** | Text similarity or model linkage | `matched` (attachment) | model-scored |

Three rules that make this safe:

- **The cluster is a stored artifact with its own lineage**, not computed per request. You can audit why two observations were grouped, and re-cluster under a different rule version without losing the old one. Same principle as verdicts-as-artifacts in the harness.
- **The tier-2 window is declared, never tuned per case.** Otherwise "same event" becomes a parameter someone fits after seeing results.
- **`substance_only=true` drops tier 3 entirely**, returning the identifier- and rule-joined observations only. A consumer who cannot accept model-assisted clustering gets a smaller, fully auditable event.

**Tier-3 observations are collapsed to a count with a drill-down URL**, never enumerated inline. Forty-three articles inline is a context-window disaster, and coverage count is the useful number anyway.

### Derived independence

Because every observation carries its source, an event's observation set yields the measurement-process breadth directly — which is what the harness's §9 independence machinery consumes. One event observed by six processes is genuinely corroborated; one event observed forty-three times by one process is one observation with high coverage. The event spine is where that distinction gets made once rather than rediscovered per consumer.

---

## 4. Entity, instrument and person identity

Same tiered structure, so one mental model covers all identity in the product:

| Tier | Method | Class |
|---|---|---|
| 1 | `cik_exact`, `figi_exact`, `lei_exact`, `accession_exact` | `measured` |
| 2 | `ticker_pit` (point-in-time ticker map), `name_exact` | `derived` |
| 3 | `name_fuzzy`, `model_linked` | `linked` (attachment) |

Every joined value carries the tier and method that produced it (§5). A 13F holding joined on CIK and a news mention joined on fuzzy name are not the same quality of fact, and an agent must be able to tell without asking.

---

## 5. Temporal joins — the rule that prevents lookahead in the join

A join can leak even when every value is honest. Joining fundamentals to prices on **period end** introduces lookahead in the join itself: every number correct, the result contaminated, no error anywhere.

**One primitive only: as-of join on `knowable_at`.**

```sql
-- internal; DuckDB ASOF JOIN fits the store design directly
SELECT p.date, p.close, f.amount AS revenue
FROM prices p ASOF JOIN facts f
  ON f.entity_id = p.entity_id AND f.knowable_at <= p.date
WHERE f.concept = 'revenue'
```

The API exposes no join-on-period option at all. **Make the wrong join unavailable rather than discouraged** — the same reasoning as making `as_of` a required parameter.

### The coarsest-cadence rule

Relating fields of different cadence requires one resolution, and the choice is forced:

- **Aggregating fine → coarse is deterministic.** Hourly pageviews summed to a quarter is arithmetic over observed values.
- **Disaggregating coarse → fine is fabrication.** Quarterly revenue spread across hours is interpolation, which manufactures values nobody observed.

So **resolution is always the coarsest common cadence**, and upsampling is refused, not offered. This is the "never fabricate a value" principle applied to alignment, and it means a panel mixing quarterly filings with hourly attention is quarterly — stated explicitly rather than silently chosen.

Irregular streams (filings, approvals, litigation) have no native cadence and become **rate-per-window** fields at the panel resolution: "approvals in this quarter: 2". Anything not expressible at that resolution is a typed gap, not a zero.

### Every joined value declares its join

```json
"join": {
  "spine": "entity",
  "method": "cik_exact",
  "tier": 1,
  "confidence": 1.0,
  "temporal": "as_of_knowable_at",
  "as_of_used": "2019-06-15",
  "staleness_days": 45,
  "provenance_class": "measured"
}
```

`staleness_days` — how old the joined fact was at the as-of moment — is the field that stops an agent treating a 45-day-old filing as current information.

---

## 6. Field algebra

Cross-referencing unlike fields needs the agent to know which operations are *valid*, which is derivable from structural metadata alone.

```json
"quantity": {
  "dimension": "monetary_flow",
  "unit": "USD",
  "temporal_type": "duration",
  "aggregation": "additive",
  "weight_field": null,
  "denominator_rule": null,
  "polarity": "higher_is_inflow",
  "native_cadence": "P3M"
}
```

**Dimensions:** `monetary_flow` · `monetary_stock` · `count` · `rate` · `ratio` · `probability` · `index` · `share_count` · `price_per_share` · `duration`

**Aggregation** — the cheapest error-preventer in the whole layer:

| value | Meaning | Failure it prevents |
|---|---|---|
| `additive` | Sum over periods is valid | — |
| `averageable` | Mean is valid, sum is not | Summing four quarters of headcount |
| `weighted_average` | Mean requires `weight_field` | Averaging four quarterly margins — the annual margin is revenue-weighted, not the mean |
| `point_in_time` | Neither sum nor mean; take the endpoint | Summing four quarters of total assets |
| `non_aggregable` | No temporal aggregation is meaningful | Averaging credit ratings |

Models get all of these wrong routinely, and no API currently tells them which applies.

**`denominator_rule`** handles the stock/flow subtlety: a flow over a stock (asset turnover, ROE) needs the *period-average* stock, not the endpoint. Declaring `denominator_rule: "period_average"` on stock fields means an agent computing a turnover ratio stops getting it quietly wrong.

### The validity matrix, derived not stored

```
sum:        same dimension AND same unit AND both additive
difference: same dimension AND same unit
ratio:      any dimension pair with compatible units after the denominator rule
product:    only where one side is dimensionless (probability, ratio, index)
```

| a | b | sum | difference | ratio | product |
|---|---|---|---|---|---|
| monetary_flow | monetary_flow (same unit) | ✓ | ✓ | ✓ margin | ✗ |
| monetary_flow | monetary_stock | ✗ | ✗ | ✓ turnover (period-avg) | ✗ |
| count | monetary_flow | ✗ | ✗ | ✓ per-unit | ✗ |
| ratio | ratio | ✗ | ✓ spread | ✓ | ✓ |
| probability | monetary_flow | ✗ | ✗ | ✗ | ✓ expected value |
| index | anything | ✗ | ✗ | ✗ | ✗ |

Fully deterministic from the metadata. `/relate` computes it rather than storing it.

---

## 7. The relation registry

Structural relations between fields and facts. **Only declared structural facts, never empirical ones.** "Revenue − COGS = gross profit" is structural. "Pageviews lead price by three days" is a signal, and the product does not sell signals.

That constraint is less limiting than it sounds, because filings ship the structural relations already.

```json
{
  "relation": {
    "id": "rel_4p8x",
    "type": "arithmetic_component",
    "from": ["revenue@ent_0000320193", "cost_of_revenue@ent_0000320193"],
    "to": "gross_profit@ent_0000320193",
    "operator": "a_minus_b",
    "asserted_by": "xbrl_calculation_linkbase",
    "scope": { "accession": "0000320193-19-000066" },
    "provenance_class": "measured"
  }
}
```

| type | Source | Class |
|---|---|---|
| `arithmetic_component` | XBRL **calculation linkbase** — the filer's own asserted arithmetic | `measured` |
| `taxonomic_parent` | XBRL **presentation linkbase** — R&D is a component of operating expense | `measured` |
| `segment_of` | XBRL dimensional context | `measured` |
| `expectation_of` / `realization_of` | A prediction market contract and the macro print it resolves against | `measured` |
| `superseded_by` | Revision chain | `measured` |
| `same_phenomenon` | Phenomenon group membership (§8) | `mapped` |
| `counterparty_of` | Relationship extraction from prose | `extracted` (attachment) |

**Relations are scoped, not universal.** A calculation-linkbase relation is asserted *by a specific filing*, so it is valid for that filing's facts and may differ across filings and eras. Serving it as a global truth would be exactly the kind of silent normalization the product refuses. The `scope` block is mandatory.

Serving the calculation and presentation linkbases is also the moat item from earlier: nobody publishes them, they are pure substance, and they are precisely what an agent needs to know two unlike fields are arithmetically related rather than merely adjacent.

---

## 8. Phenomenon groups

Multiple fields measuring one underlying quantity through genuinely different processes.

```json
{
  "phenomenon": {
    "id": "attention",
    "version": "ph_2026.1",
    "members": [
      { "field": "wikipedia_pageviews",  "process": "information_seeking",    "cadence": "PT1H" },
      { "field": "news_mention_count",   "process": "editorial_publication",  "cadence": "PT15M" },
      { "field": "social_post_volume",   "process": "retail_discourse",       "cadence": "PT1M" }
    ],
    "asserts": "these fields measure the same underlying quantity",
    "does_not_assert": "that they agree, correlate, or are interchangeable"
  }
}
```

| Phenomenon | Members |
|---|---|
| Attention | pageviews, news mention count, social post volume |
| Insider conviction | Form 4 net buys, congressional trades |
| Positioning / leverage | short interest, options open interest, perp funding |
| Distress | going-concern language, 8-K Item 4.02, credit downgrades |
| Expectation | prediction market implied probability, analyst consensus vintage |

Published and versioned like concept maps — a declaration, never a model judgment. It lets an agent ask "everything measuring attention for this entity" without knowing field names, and `does_not_assert` is in the payload because the distinction is the whole point.

**Direct contribution to the harness's independence machinery:** members of one phenomenon with *distinct* `process` values are candidate independent corroborating legs; members sharing a process are one leg counted twice. The data product makes that determination available as data instead of leaving every consumer to rediscover it.

---

## 9. `/relate` — ask what is valid

```
GET /v1/relate?a=revenue@AAPL&b=wikipedia_pageviews@AAPL
```

```json
{
  "verdict": "relatable_with_transform",
  "shared_spines": ["entity", "time"],
  "a": { "quantity": { "dimension": "monetary_flow", "native_cadence": "P3M", "aggregation": "additive" } },
  "b": { "quantity": { "dimension": "count", "native_cadence": "PT1H", "aggregation": "additive" } },
  "resolution": { "value": "P3M", "reason": "coarsest_common_cadence" },
  "required_transforms": [
    { "field": "wikipedia_pageviews", "op": "aggregate_sum", "from": "PT1H", "to": "P3M" }
  ],
  "valid_operations": [
    { "op": "ratio", "result_dimension": "monetary_flow_per_count", "note": "revenue per pageview" }
  ],
  "blocked_operations": [
    { "op": "sum", "reason": "different_dimensions" },
    { "op": "difference", "reason": "different_dimensions" },
    { "op": "product", "reason": "neither_side_dimensionless" }
  ],
  "declared_relations": [],
  "shared_phenomena": [],
  "note": "No structural relation is declared between these fields. Any relationship is the consumer's hypothesis."
}
```

**Verdicts, and the distinction that matters:**

| verdict | Meaning |
|---|---|
| `directly_relatable` | Shared spine, compatible dimensions, same cadence |
| `relatable_with_transform` | Shared spine; deterministic transforms listed |
| `relatable_via_relation` | A declared relation connects them (§7) |
| `no_shared_data` | Relatable in principle, but no overlapping observations for this entity/window |
| `incommensurable` | No shared spine, or dimensions admit no valid operation |

`no_shared_data` and `incommensurable` must never collapse into one answer — the same insistence as §12 of the spec, where *could not compare* is distinct from *compared and found different*. An agent does something different in each case: retry with a wider window, versus stop.

**`blocked_operations` with reasons** is the status-enum principle applied to algebra. Telling an agent what it cannot do, and why, prevents more errors than telling it what it can.

---

## 10. `/panel` — do not make the agent do the join

Alignment is where the errors are, so the product does it.

```
GET /v1/panel?entities=AAPL,MSFT&fields=revenue,wikipedia_pageviews,insider_net
             &as_of=2019-06-15&resolution=P3M&format=columnar
```

```json
{
  "request": { "entities": ["ent_0000320193","ent_0000789019"],
               "fields": ["revenue","wikipedia_pageviews","insider_net"],
               "as_of": "2019-06-15", "resolution": "P3M" },

  "schema": [
    { "name": "period_end", "type": "date" },
    { "name": "entity_id",  "type": "string" },
    { "name": "revenue", "quantity": {...}, "transform": null,
      "join": { "spine": "entity", "method": "cik_exact", "tier": 1 } },
    { "name": "wikipedia_pageviews", "quantity": {...},
      "transform": { "op": "aggregate_sum", "from": "PT1H", "to": "P3M" },
      "join": { "spine": "entity", "method": "wikidata_qid", "tier": 1 } },
    { "name": "insider_net", "quantity": {...},
      "transform": { "op": "aggregate_sum", "from": "irregular", "to": "P3M" },
      "join": { "spine": "entity", "method": "cik_exact", "tier": 1 } }
  ],

  "rows": [
    ["2019-03-30","ent_0000320193","58015000000","reported","412300000","reported","-1840000","reported"],
    ["2018-12-29","ent_0000320193","84310000000","reported","501100000","reported",null,"not_disclosed"]
  ],

  "alignment": {
    "temporal_join": "as_of_knowable_at",
    "resolution": "P3M",
    "resolution_reason": "coarsest_common_cadence",
    "upsampling": "refused",
    "max_staleness_days": 78
  },

  "coverage": {
    "cells_expected": 48, "cells_reported": 41,
    "gaps": [ { "field": "insider_net", "periods": 5, "status": "not_disclosed" },
              { "field": "revenue", "periods": 2, "status": "not_covered", "reason": "pre_xbrl" } ],
    "complete": false, "truncated": false
  },

  "determinism": { "response_hash": "sha256:...", "concept_map_version": "cm_2026.3",
                   "phenomenon_version": "ph_2026.1", "event_cluster_version": "es_2026.2",
                   "substance_only": true }
}
```

Design notes:

- **Columnar with status columns interleaved.** Schema once, rows as arrays — two-thirds fewer tokens on time series, and every value keeps its typed status so gaps stay legible.
- **Transforms declared per field**, so a consumer can see exactly what the product did rather than trusting it.
- **`upsampling: "refused"`** is stated, not implied. It tells the agent the resolution was forced rather than chosen.
- **`max_staleness_days`** caps how old any joined value is — one number that tells an agent whether the panel is roughly current or stitched from stale filings.

---

## 11. Presentation to an agent

Agents do not want a graph. They want a question answered, with lineage, and with **bounded fan-out**.

```
GET /v1/entities/{id}/view?as_of=2019-06-15&streams=fundamentals,insider,events,prediction
```

```json
{
  "entity": { "id": "...", "name": "...", "ticker_at_period": "AAPL" },
  "as_of": "2019-06-15",
  "fundamentals": { "revenue": {...}, "net_income": {...} },
  "related": {
    "insider_transactions": { "count": 47, "window": "P1Y", "latest": {...},
                              "url": "/v1/facts?..." },
    "events":               { "count": 12, "types": ["material_agreement","guidance"],
                              "url": "/v1/events?..." },
    "news_mentions":        { "count": 1203, "join_tier_min": 3,
                              "join_confidence_min": 0.71, "url": "..." },
    "prediction_contracts": { "count": 0 }
  },
  "coverage": { "streams_requested": 4, "streams_with_data": 3,
                "gaps": [ { "stream": "prediction", "reason": "no_contracts_for_entity" } ] }
}
```

**Counts and drill-down URLs, never 1,203 inline articles.** Uncontrolled fan-out is the single most common way a multi-source API becomes unusable for agents. The coverage block is what stops an agent inferring absence from silence — `"no_contracts_for_entity"` is information; an empty array is not.

`join_tier_min` and `join_confidence_min` on a collapsed set tell the agent the *weakest* link in what it is being shown, which is the number that should govern how much weight it puts on the set.

---

## 12. Presentation to a human

Two views do the work, and one of them is the demo.

**The dual timeline.** Streams as rows, time on x, every event plotted **twice** — once at `event_time`, once at `knowable_at` — with the gap drawn between them. A 10-Q's period ends in March and becomes knowable in May; the seven-week gap is visible. No vendor UI shows this, and for anyone validating a backtest it is exactly the thing to look at.

**The as-of scrubber.** A time slider that re-renders everything as it was knowable at that instant. Drag back before a restatement and the restated figures vanish, replaced by originals; drag forward and they change. That is the entire product thesis demonstrated in thirty seconds with no explanation — and it is just the `as_of` parameter wired to a UI control.

**The lineage view** for any single value: this number, from this accession, superseded on this date, full chain here, the footnote the filer attached, and the calculation-linkbase check passing.

**The event card**: one occurrence, its observations across processes, each with its own availability timestamp, `first_knowable_at` highlighted, and the join tier for each.

**What not to build: the graph visualization.** Node-link diagrams of financial data are attractive and unreadable. The harness keeps a graph internally because it *computes* over it; the data product serves joins and should not try to draw them.

---

## 13. The boundary

This layer serves algebra and declared structure. It never serves inference.

**Never:**
- correlations, co-movement statistics, lead-lag estimates, or any fitted relationship
- rankings, scores, or composite indices
- auto-normalization without a declared, reversible transform
- storing a consumer's proposed relation as though it were a declared one
- an LLM anywhere in a value, period, availability, join key, or relation — attachments only, and labelled

The moment `/relate` returns "these correlate at 0.7," the product becomes a signal vendor with undisclosed methodology — the thing it exists as a reaction against. **`/relate` returns what is valid; the agent forms the hypothesis; the harness tests it.**

---

## 14. Build order

1. **Entity spine + join declarations.** Nothing else works without it.
2. **As-of join primitive and the coarsest-cadence rule.** The lookahead-in-the-join fix, before any multi-source endpoint exists.
3. **Quantity metadata on every field**, including `aggregation` and `denominator_rule`. Cheapest error-prevention available.
4. **`/panel`** with columnar output, declared transforms, typed gaps, coverage envelope.
5. **Relation registry from the XBRL calculation and presentation linkbases.** Pure substance, unserved by anyone, and the foundation for relating unlike-but-connected fields.
6. **`/relate`** with the validity matrix and the five verdicts.
7. **Phenomenon groups**, published and versioned.
8. **Event spine, tiers 1–2 only** (identifier and declared-window). Deterministic, auditable, immediately useful for `first_knowable_at`.
9. **Event spine tier 3** (semantic matching) as an attachment, filterable out.
10. **Human UI:** as-of scrubber first — it is the demo — then dual timeline, then lineage and event cards.

Tiers 1–2 of the event spine are worth shipping well before tier 3. Identifier joins plus a declared window cover a large fraction of real events, are fully auditable, and carry the `first_knowable_at` value on their own.
