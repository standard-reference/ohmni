# Data Product — Substance-Deterministic, Agent-Native Financial Facts

*Companion to `01-system-specification-v3.md`, `02-build-plan-and-parts.md`, `03-data-sources.md` and `05-cross-reference-layer.md`. This is the ingestion product, sold separately from the harness. Build stages referenced as A1–A10 are defined in `02-build-plan-and-parts.md` §2.*

---

## 1. The two claims the product makes

**Point-in-time by construction.** Every value carries when it became knowable, distinct from the period it describes, and revisions are preserved as a chain rather than overwrites. Competitors treat time as "which period do you want"; this treats it as "when are you standing."

**Substance deterministic.** Every value, period, availability timestamp, derivation and lineage is produced by deterministic code from a source document. **No model output ever enters a numeric or temporal field.** Models are confined to *attachments* — links and edges that point at facts without altering them.

Both claims are falsifiable in ten minutes, which is the point.

### Why "substance deterministic" is the right claim

It's a **structural boundary, not a hedge.** "Deterministic on replay" is a caveat about reproducibility and invites the question "so what isn't deterministic?" Substance-deterministic answers that in advance: models never touch substance, only attachments. That's an architectural property, auditable by inspection of the pipeline, and it doesn't overclaim on the enrichment side.

| Layer | What it is | Guarantee |
|---|---|---|
| **Substance** | values, units, periods, availability, derivation, lineage | Deterministic by construction — no model in the path |
| **Attachment** | entity links, relationship edges, cross-venue question matching | Deterministic *on replay* — pinned model, content-hash cached |

An attachment can be wrong, and can be ignored. A substance field being model-generated would be unauditable, and that never happens.

---

## 2. Format neutrality — the API must not leak the harness's vocabulary

The harness's internal model (basis, frames, residue, EffectClaim, root sets, spark) **never appears in the API**. The data product emits neutral, general-purpose facts; the harness maps them into its own event model on its side of the seam.

What the product emits: facts with periods, availability, lineage, and status. What the harness derives: events, root sets, frames, bases. One is a general primitive; the other is one consumer's interpretation.

Practical test: if a field name would be meaningless to someone building a stock screener, it doesn't belong in the API.

---

## 3. The primitive is a Fact, not a statement

Statements, ratios, and time series are all *views* over facts. Make the atom explicit and every view composes from it.

```json
{
  "entity": {
    "id": "ent_0000320193",
    "cik": "0000320193",
    "name": "Apple Inc.",
    "ticker_at_period": "AAPL",
    "sic": "3571"
  },
  "concept": {
    "id": "revenue",
    "map_version": "cm_2026.3",
    "source_tag": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    "peer_group": "technology_hardware",
    "sign_convention": "positive_is_inflow"
  },
  "value": {
    "amount": "58015000000",
    "unit": "USD",
    "scale": 1,
    "display": "58.02B USD",
    "as_filed": true
  },
  "period": {
    "type": "duration",
    "start": "2018-12-30",
    "end": "2019-03-30",
    "days": 91,
    "span": "standalone_quarter",
    "fiscal": { "fy": 2019, "fp": "Q2", "fy_end_month": 9 }
  },
  "time": {
    "knowable_at": "2019-05-01T20:31:00Z",
    "as_of_used": "2019-06-15",
    "lag_days": 32
  },
  "status": "reported",
  "derivation": { "method": "filed", "inputs": [] },
  "revision": {
    "index": 0,
    "chain_length": 2,
    "superseded_at": "2019-10-31",
    "chain_url": "/v1/facts/chain/fct_8x2k9"
  },
  "source": {
    "accession": "0000320193-19-000066",
    "form": "10-Q",
    "document_url": "https://www.sec.gov/Archives/edgar/data/320193/...",
    "tag_path": "us-gaap:RevenueFromContract.../USD/2018-12-30..2019-03-30"
  },
  "provenance_class": "measured"
}
```

Design notes on specific fields:

- **`amount` is a string.** Large integers lose precision in some JSON parsers, and language models mangle long digit strings. Strings are lossless.
- **`display` is redundant on purpose.** "58.02B USD" cuts magnitude and arithmetic errors in model reasoning substantially, at trivial token cost. The cheapest agent-native affordance available.
- **`scale` is always explicit and always 1** in the API. Filings report in thousands or millions; normalize at ingest. "In thousands" headers are one of the most common sources of 1000x errors in agent-built models.
- **`lag_days`** saves a date subtraction consumers get wrong around fiscal boundaries.
- **`provenance_class`** is the substance/attachment filter (§6).

---

## 4. The status enum — the actual quality differentiator

Everyone else returns a number or `null`. `null` collapses at least five genuinely different states, and an agent cannot recover the distinction. Highest-value, lowest-cost thing in the product.

| status | Meaning | Example |
|---|---|---|
| `reported` | The entity filed this value for this period | Revenue in a 10-Q |
| `derived` | Computed deterministically from reported values; `derivation.inputs` lists them | Q2 standalone from Q2 YTD minus Q1 |
| `not_representable` | Cannot be honestly computed | Q4 standalone (§5) |
| `not_disclosed` | Concept applies to this entity but it didn't report it | R&D for a company that doesn't break it out |
| `not_applicable` | Concept doesn't apply to this entity type | Inventory for a bank |
| `not_covered` | Outside coverage | Pre-XBRL period, or a custom extension tag |

Two consequences worth putting in the docs, because they're the sales pitch:

**`not_representable`, `not_disclosed` and `not_covered` are three different reasons for a hole**, and an agent reasons differently about each — don't ask again, read the filing text, try another source. Collapsing them into `null` destroys that.

**`derived` is never silent.** If a value was computed, the method and exact input facts are in the response. Competitors compute Q4 and hand you a number indistinguishable from a filed one.

---

## 5. The quirks catalogue — where domain depth actually lives

These are the things that make financial data hard. Handling each explicitly *is* the product, and every one is deterministic.

### Period structure

- **Q4 standalone does not exist.** Companies file a 10-K, not a Q4 10-Q. FY minus Q1/Q2/Q3 produces a number nobody filed. Return `not_representable`, with `annual` and the three filed quarters available. This single behaviour signals to a knowledgeable buyer that you understand the domain.
- **YTD vs standalone durations.** A Q3 10-Q often reports both Jul-Sep and Jan-Sep. Disambiguate by duration length and label with `period.span`: `standalone_quarter` / `year_to_date` / `annual` / `trailing_twelve`. Never silently pick one.
- **Instant vs duration.** Balance-sheet facts are instants (no `start`); income and cash-flow facts are durations. Make the type explicit rather than inferable from which concept it is.
- **52/53-week fiscal years.** Retailers use week-based calendars, so roughly every fifth year has a 14-week Q4. `period.days` makes this visible; a consumer comparing Q4 year-over-year needs to know one period was 10% longer.
- **Fiscal year changes** produce a stub period of unusual length. Report as filed, never stretched to fit a calendar.
- **Fiscal is not calendar.** Apple's FY2024 ends in September. Serve fiscal periods as filed; calendar alignment is an explicit, labelled, opt-in view.
- **Pre-IPO periods** appear in a first 10-K. Legitimate, and `knowable_at` is the filing date so a backtest correctly can't see them earlier.

### Revisions and amendments

- **Restatements are a chain, not a pair.** A period can be revised more than once. Serve the full chain with an index and let `as_of` select. Two fixed dimensions (as-reported / most-recent) are a lossy projection.
- **Amended filings** (`10-K/A`, `10-Q/A`) are ordinary chain links: same period, later `knowable_at`.
- **Discontinued operations restate prior periods.** When a segment is divested, prior-period revenue is re-presented excluding it — a restatement with an unusual cause. Expose the cause in the chain entry.
- **Late filings.** An NT 10-K/NT 10-Q signals delay. The eventual filing's `knowable_at` is genuinely later, which is material to anyone modelling earnings timing.

### Values, units, and signs

- **Sign conventions vary.** XBRL sometimes tags expenses positive with negated presentation, sometimes negative. Normalize to one declared convention and publish `concept.sign_convention`. Negative revenue is rare but real (contra-revenue), so don't clamp.
- **Reporting-currency changes.** Serve the filed currency per fact. If you convert, `value.converted_from` carries the rate, rate source, rate date, and the rate's own `knowable_at`.
- **Filer scale errors.** Companies occasionally mis-tag scale. A deterministic magnitude check against the entity's own history flags outliers — `quality_flags: ["magnitude_outlier"]`. Flag, never silently correct.
- **Share classes.** "Shares outstanding" is ambiguous with multiple classes. Serve per-class plus an explicit labelled total.

### Per-share values and corporate actions — the subtle one

A filed EPS is in **pre-split terms**. Adjusting it for a later split applies information that didn't exist at the filing date — lookahead in a field that looks innocent.

**Resolution:** serve per-share values exactly as filed (`value.as_filed: true`), and publish split/dividend adjustment factors as a **separate series with their own `knowable_at`**. A consumer who wants an adjusted series composes it and inherits correct availability semantics. Never pre-adjust.

Same principle as the restatement chain, applied where no vendor applies it.

### Entities

- **Tickers are point-in-time and get recycled.** Serve a permanent `entity.id`; expose `ticker_at_period` for the requested date, never today's ticker for a historical period.
- **CIK survives renames and delisting** — the right internal anchor.
- **Mergers.** The surviving entity's history is not the combined history. Don't splice; expose the relationship and let the consumer decide.
- **Delisting mid-period** produces a truncated final period. Report as filed.
- **Segment vs consolidated facts.** Raw XBRL contains dimensional contexts (by segment, by geography). Entity-wide consolidated facts are what a top-level concept means; put segment data behind an explicit dimensional endpoint rather than mixing them.

### Coverage limits

- **XBRL starts 2009**, phased to ~2011 for full coverage. `not_covered`, with the reason.
- **Custom extension tags are invisible** to the aggregated XBRL APIs, which cover only standard taxonomies. `not_covered` with `reason: "custom_taxonomy"` — never interpolated, and the count reported so the customer sees the size of the gap.

---

## 6. Substance vs attachment, made verifiable

### The receipt

Every response carries:

```json
"determinism": {
  "response_hash": "sha256:...",
  "pipeline_version": "1.4.2",
  "concept_map_version": "cm_2026.3",
  "attachment_model_versions": {},
  "substance_only": true
}
```

Same query + same versions produces an identical `response_hash`. Publish it as a testable guarantee with a public replay endpoint that proves the hash for a historical query. A competitor with an LLM in the extraction path cannot do this at all.

### Provenance classes

**Substance classes** — deterministic by construction:

| class | Meaning |
|---|---|
| `measured` | Straight from the source document |
| `derived` | Arithmetic over measured values, inputs listed |
| `mapped` | Concept map lookup, version pinned |

**Attachment classes** — deterministic on replay:

| class | Meaning |
|---|---|
| `linked` | Entity resolution from free text |
| `extracted` | Relationship claim from prose |
| `matched` | Cross-venue question identity (prediction markets, §7) |

`GET /v1/facts?substance_only=true` returns facts with no attachment-class fields at all. One parameter answers "is there AI in my data," which is a genuinely differentiated product feature.

### The constraint on attachments

Only three surfaces need a model, and none touches a number. All three are bound by the same rules as the harness's enricher contract:

- **Pinned model version**, returned in `determinism.attachment_model_versions`
- **Content-hash cached** — `hash(model_version, input)` maps to output, so identical inputs always return identical outputs
- **Lineage declared** — an attachment always names the source it derived from, so a consumer can see it isn't independent evidence

### Retrieval mode and record survivorship

Two source-level declarations that determine whether a stream can be honestly backfilled at all. Both appear on every fact's source block.

```json
"source": {
  "retrieval": "as_of",              // "as_of" | "snapshot"
  "record_survivorship": "complete"  // "complete" | "deletions_unrecoverable"
}
```

A third declaration sits beside these two and answers a different question:

```json
"historical_access": "bulk",        // "bulk" | "metered" | "rate_limited" | "record_only"
"bulk_endpoint": "https://..."
```

`retrieval` is about the honesty of a historical *value*. `historical_access` is
about whether the history can be **obtained at all at scale**. A source can be
impeccably point-in-time and still be unusable for multi-period work because its
only access path is metered or throttled — and discovering that partway through a
backfill is too late, because by then some periods have the field and others do
not. Only `bulk` supports backfill; `metered` is a budget question; `rate_limited`
and `record_only` are hard stops.

**`retrieval: "as_of"`** means historical values are queryable as they stood — EDGAR, ALFRED, on-chain settlement. **`retrieval: "snapshot"`** means a historical query returns the *present* value: engagement counts on an old post, follower counts, app-store rankings, search-interest indices rescaled per requested window. There is no revision chain, because intermediate values were never stored anywhere. A snapshot stream **cannot be honestly backfilled**, only recorded forward.

This is a harder constraint than `backfilled`. Backfilled history is suspect; snapshot history is simply wrong, and wrong in the direction of the future.

**`record_survivorship: "deletions_unrecoverable"`** means a historical pull returns only records that still exist. This is the delisted-ticker problem applied to records rather than entities, and it is worse in social data than in equities: deletions skew heavily toward wrong calls, retracted claims and removed promotional content, so a backfill over-represents what nobody regretted saying.

A stream that is both `snapshot` and `deletions_unrecoverable` has no honest historical mode. The API should refuse a historical `as_of` query against it rather than serve contaminated values, and say why.

---

## 7. Prediction markets — a distinct measurement process

Worth adding for four reasons, and the third is the strongest:

1. **A genuinely independent measurement process.** Not exchange matching of securities, not accounting disclosure, not editorial publication. It measures *aggregated explicit probabilistic belief about a named future event*, and nothing else in the source set does.
2. **Natively forward-looking and horizon-explicit.** Every contract has a resolution date and a resolution criterion — the closest external analogue to the harness's own EffectClaim shape (subject, sign, magnitude, horizon), already priced.
3. **They resolve, definitively.** Unlike almost everything else in finance, there is a known outcome at a known time. That is clean labelled data for free, and rare.
4. **Expectation versus realization is a free delta.** ALFRED gives the vintaged macro print; a prediction market gives the prior expectation. The surprise is more informative than the raw print and is deterministically computable.

### Three artifact types, not one

Prediction market data is a contract definition, a stream of transient quotes, and a resolution. They have different availability semantics and need separating.

**Contract** — an instrument, with a versioned criterion:

```json
{
  "contract": {
    "id": "pm_kalshi_FED-MAR25-CUT",
    "venue": "kalshi",
    "type": "binary",
    "stake": "real_money",
    "question": "Will the FOMC lower the target rate at the March 2025 meeting?",
    "resolution_criterion": {
      "text": "...",
      "version": 2,
      "knowable_at": "2025-01-14T00:00:00Z"
    },
    "resolution_source": "FOMC post-meeting statement",
    "resolves_by": "2025-03-19",
    "couples_to": [ { "subject": "rates.fed_funds", "strength": 0.9 } ]
  },
  "provenance_class": "measured"
}
```

**Quote** — transient state at an observed instant:

```json
{
  "contract_id": "pm_kalshi_FED-MAR25-CUT",
  "observed_at": "2025-02-10T14:00:00Z",
  "knowable_at": "2025-02-10T14:00:00Z",
  "bid": "0.62", "ask": "0.65", "last": "0.63",
  "spread": "0.03",
  "volume_24h": "142000",
  "open_interest": "890000",
  "implied_probability": { "value": "0.635", "method": "mid" },
  "days_to_resolution": 37,
  "liquidity_flag": "adequate",
  "status": "reported",
  "provenance_class": "measured"
}
```

**Resolution** — the outcome, with its own revision chain:

```json
{
  "contract_id": "pm_kalshi_FED-MAR25-CUT",
  "outcome": "no",
  "resolved_at": "2025-03-19T18:02:00Z",
  "knowable_at": "2025-03-19T18:02:00Z",
  "resolution_source_ref": "https://...",
  "revision": { "index": 1, "chain_length": 2, "reason": "dispute_upheld" },
  "status": "reported",
  "provenance_class": "measured"
}
```

### Prediction market quirks

- **Quotes are transient.** Unless the venue publishes history, an unrecorded price is gone — this is `current_snapshot` data and belongs on the record-now list, not the backfill list.
- **The resolution criterion itself can be revised.** Venues clarify ambiguous wording after launch. This is a restatement of the *instrument definition*, not of a value — a genuinely novel quirk, and the reason `resolution_criterion` carries a version and its own `knowable_at`.
- **Resolutions can be disputed and overturned.** Polymarket resolves via an optimistic oracle with a dispute window, so the outcome needs a revision chain exactly as a restated figure does.
- **Thin liquidity means price is not probability.** A market with $200 of volume and a wide spread is noise. Always serve bid, ask, last, volume, open interest and spread; `liquidity_flag` lets a consumer filter. Serving thin-market prices as probabilities is the prediction-market equivalent of quoting IV off a stale option.
- **Never a bare "probability" field.** Fees and spread mean mid is a convention. `implied_probability` always carries its `method` (`mid`, `last`, `fee_adjusted_mid`).
- **Multi-outcome sets don't sum to 1.** Related contracts can total more or less than 100% from spread and fees. Don't normalize silently; if you do normalize, label it and keep the raw values.
- **Play money is a different process.** Manifold and Metaculus involve no financial commitment — belief without skin in the game. `stake: "real_money" | "play_money" | "reputation"` is required, and arguably they shouldn't share a concept with real-money venues at all.
- **Time to resolution is first-class.** 60% at six months out and 60% at one day out are different claims. `days_to_resolution` on every quote.
- **Contract types vary** — binary, scalar, categorical, bucketed. Explicit `type`, never inferred from the question text.
- **Question identity is unstable across venues.** The same real-world event is listed with different wording on Kalshi, Polymarket and Metaculus. Cross-venue matching is an **attachment** (`provenance_class: "matched"`), never substance — so `substance_only=true` returns per-venue contracts unmatched, which is the honest default.
- **On-chain venues have auditable history.** Polymarket settles on-chain, so its quote and resolution history is independently verifiable — a real advantage over centralized venues for point-in-time claims, and worth surfacing.

### Venues

| Venue | Stake | Notes |
|---|---|---|
| **Kalshi** | Real money | CFTC-regulated US exchange; macro, Fed, CPI, elections, weather |
| **Polymarket** | Real money | On-chain (auditable history); large volume; oracle-based resolution with disputes |
| **Metaculus** | Reputation | Aggregated human forecasts, long horizons, calibration-focused |
| **Manifold** | Play money | Very open API, broad question set, low signal per market |
| **Iowa Electronic Markets** | Real money | Academic, election history back to 1988 — unusually deep |

### Two implications for the harness spec

**External calibration benchmark (spec §14).** The calibration ledger currently scores the harness in isolation. Prediction markets supply a benchmark: on resolved questions where a market existed, was the harness's probability better than the market's? "Beat the market's Brier score on N resolved questions" is a far stronger claim than a raw calibration number, and it's the cheapest external validation available.

**Coupling must be declarable per contract, not per source (spec §9.1).** A market on "AAPL above $200" is delta-coupled to AAPL spot; a market on "Fed cuts in March" is coupled to rates and not to any equity. Source-level `couples_to` is too coarse here — this is the first case in the design that requires instrument-level coupling declaration.

---

## 7b. X / social adapter

Social measures retail discourse, which nothing else in the source set captures. But it is the stream where the §6 declarations do the most work, because almost everything about it is snapshot and lossy.

### What is honest and what is not

| Field | Honest? | Why |
|---|---|---|
| `created_at` | Yes | This is `knowable_at`. Stable. |
| Post text | Mostly | Stable, except within the edit window |
| Author identity | Yes | Stable |
| Likes / reposts / replies / quotes / bookmarks / impressions | **No** | Current-snapshot. Pull a 2019 post today and every count is from today |
| Author follower count | **No** | Current-snapshot |
| Deleted posts | **Absent** | `record_survivorship: deletions_unrecoverable` |

So the adapter declares `retrieval: "snapshot"`, `record_survivorship: "deletions_unrecoverable"`, and serves two distinct fact families:

- **Post facts** — text, author, `created_at`. Backfillable, subject to deletion survivorship, which is declared.
- **Engagement facts** — each an observation at an `observed_at` instant with `knowable_at = observed_at`. **Only ever produced by the recorder**, never by backfill. Sampling a post's engagement on a schedule builds the series the platform refuses to store.

That split is the whole design: it makes the honest half usable and makes the dishonest half structurally impossible to serve as history.

### Adapter-specific quirks

- **Edited posts have a genuine revision chain.** The API exposes edit history, so an edited post is the same artifact with a later `knowable_at` — the restatement machinery applies unchanged.
- **Reposts and quotes carry lineage.** A repost's root is the originating post. This is exactly the coverage-duplication problem from relationship extraction: fifty reposts of one claim are one claim, and without lineage they read as fifty independent signals. `source.originating_post_id` is the dedup anchor.
- **Engagement can be manufactured.** Bot inflation is a `quality_flags` entry, not a signal. Deterministic heuristics only (account age, follower-to-engagement ratio, burst timing) — never a model verdict on whether an account is a bot, which would be an attachment masquerading as substance.
- **Pricing and tiers.** Free is effectively unusable for reads; Basic sits around $200/mo with a low monthly read cap; full-archive search is Pro-tier and up. Verify before committing — this pricing has changed repeatedly.
- **Cheaper first.** Bluesky's AT Protocol firehose is fully open and free, Farcaster is open, StockTwits is finance-specific. Build the recorder against those, prove the engagement-sampling design, then decide whether X's reach justifies its price.

**The recorder is the urgent part.** There is no purchasable archive for Bluesky, Farcaster or StockTwits, and X's archive is both expensive and survivorship-biased. Recording starts paying the day it starts.

---

## 7c. The plugin system

Users — and their agents — add their own sources. The design problem is that this is precisely where the substance-deterministic guarantee is most at risk: a careless plugin can fabricate values, omit availability, call a live API mid-replay, or quietly put a model in the numeric path.

**So the guarantee is enforced by contract, not by trust.** That principle follows from everything else in the product: the plugin system's value isn't that it accepts anything, it's that anything it accepts inherits the guarantees.

### Declarative first, code as the escape hatch

Most REST sources need no code at all:

```yaml
plugin_id: acme_macro
plugin_version: "1.0.0"
measurement_process: "National statistical office publication of survey aggregates"
retrieval: as_of
record_survivorship: complete
backfilled: false
measurement_type: measured
couples_to: []
endpoints:
  - url_template: "https://api.acme.com/v1/series/{series_id}"
    auth: { type: header, name: X-API-KEY }
    availability_field: "$.published_at"      # REQUIRED — where knowable_at comes from
    period_field: "$.reference_period"
    value_path: "$.observations[*].value"
    unit: "index_points"
    scale: 1
    native_cadence: P1M
```

`availability_field` is **required and has no default**. If the source exposes no such field, the plugin must either declare a justified `publication_lag` or declare `retrieval: snapshot`. There is no path where availability is silently omitted — that single required field is the main enforcement point in the whole system.

For anything the declarative form can't express:

```python
class SourcePlugin(Protocol):
    plugin_id: str
    plugin_version: str

    def declare(self) -> SourceDeclaration: ...
    def fetch(self, request: FetchRequest) -> Iterator[RawRecord]: ...
    def normalize(self, raw: RawRecord) -> list[Fact]: ...
```

**`fetch` and `normalize` are deliberately separate.** `fetch` is the only network boundary; its output is cached as raw. `normalize` must be a **pure function** of raw input — which makes it testable, re-runnable after a bugfix with no refetch, and provably deterministic. That's the same raw/normalized split as the store design, promoted to a contract.

### The conformance suite

A plugin cannot emit facts until it passes. Every check is automated, and each one maps to a failure mode from elsewhere in this document.

| Check | What it rejects |
|---|---|
| **Declaration completeness** | Missing `measurement_process`, `availability_field` or lag, `retrieval`, `record_survivorship`, `native_cadence`, `couples_to` |
| **Normalize determinism** | `normalize(raw)` run twice must be byte-identical. Catches dict ordering, timestamps, randomness, anything model-generated |
| **No network in normalize** | Sockets blocked during `normalize`; any attempt fails the plugin. **This is the check that structurally prevents live-lookup-in-replay** |
| **Availability sanity** | `knowable_at` null, or silently equal to period end, or earlier than `event_time` |
| **Status honesty** | Any fact with a null value and no typed `status`. Gaps must be typed, never null |
| **No fabrication** | A fact with `status: derived` whose `derivation.inputs` is empty, or whose inputs don't reproduce the value |
| **Attachment declaration** | A plugin that declares no model but imports inference libraries, or emits a `measured` field its own declaration can't source |
| **Cadence coherence** | Facts arriving at a cadence its declaration says is impossible |

### Trust tiers, not a binary

```
certified    — we wrote and audit it. Full guarantee.
conformant   — passes the full suite. Guarantee is structural, not social.
declared     — registers but skips or fails checks. Facts tagged;
               excluded from substance_only=true.
```

Every fact carries `source.plugin_trust`, so a consumer — or the harness's own independence machinery — can filter rather than being forced to trust or reject the whole set.

### Agent-authored plugins

An agent writing an adapter for a new API is a real use case, and the conformance suite is what makes it safe: **the suite is the trust boundary, not the author.** An agent-written plugin that passes conformance is exactly as trustworthy as a hand-written one *with respect to the properties the suite checks*. The declarative form makes this much better still — an agent producing YAML rather than code has a far smaller surface to get wrong, and the whole declaration is machine-validatable before a single request is made.

**The honest limit, worth stating in the docs:** conformance guarantees *structure*, not *meaning*. A plugin can pass every determinism and availability check and still map the wrong upstream field to `revenue`. Semantic correctness needs either an oracle cross-check (the §5 pattern — compare against a second source and enumerate disagreements) or human review. Conformance buys you "this cannot leak lookahead and cannot fabricate," which is most of the risk but not all of it.

### Why this is a product feature, not plumbing

Every competitor's coverage is a fixed list. This one's coverage is a fixed list *plus whatever the customer needs*, and the additions inherit point-in-time correctness rather than undermining it. "Add your own source and it's still backtest-safe" is a claim that requires the conformance suite, and the suite requires the availability-first schema — so it isn't something a competitor bolts on later.

---

## 8. Agent-native affordances

Differentiation on *ingestion quality* rather than data quality. None of it needs AI.

**Token-efficient mode.** `?format=columnar` emits the schema once and rows as arrays, cutting response tokens by roughly two-thirds on time series. Agents pay per token; nobody in this market optimizes for it.

**A completeness envelope on every response.** Agents cannot detect silent gaps, so make them first-class:

```json
"coverage": {
  "requested": { "start": "2005-01-01", "end": "2024-12-31" },
  "periods_returned": 44,
  "periods_expected": 80,
  "gaps": [
    { "range": "2005-01-01..2008-12-31", "status": "not_covered", "reason": "pre_xbrl" },
    { "period": "2019-Q4", "status": "not_representable", "reason": "no_q4_filing" }
  ],
  "complete": false,
  "truncated": false
}
```

`complete: false` with enumerated reasons is worth more than more data.

**Capability discovery.** `GET /v1/entities/{id}/concepts` returns which concepts exist for this entity with coverage ranges and statuses. Agents otherwise guess concept names and burn calls on 404s.

**A comparability guard.** A cross-entity request spanning incompatible peer groups returns a warning, or refuses with the peer groups named. Comparing a bank's revenue to a manufacturer's is meaningless whether or not tags were harmonized, and no vendor currently stops you.

**Published, versioned concept maps.** `GET /v1/concept-maps/cm_2026.3` returns tag precedence, peer-group scope, and measured per-entity coverage. Standardization you can inspect, pin and diff, against opaque vendor mappings.

**Cursor pagination with an explicit `complete` flag.** Never let a truncated page look like a full answer.

**An MCP server where `as_of` is a required parameter**, pinned per session, so an agent *cannot* accidentally read present-day values mid-replay. "Backtest-safe by construction" requires this schema and cannot be retrofitted onto one without availability timestamps.

**OpenAPI spec and llms.txt.** Table stakes — but they are table stakes.

---

## 9. What the product deliberately does not do

Stating non-features is part of the positioning:

- **No summarization or interpretation.** Never "revenue grew strongly." Facts only; the consumer reasons.
- **No scores, signals, rankings or sentiment.** Derived judgments with undisclosed methodology are exactly what you can't version and can't audit — the thing this product is a reaction against.
- **No silent normalization.** Every transformation is labelled, versioned, and reversible to its inputs.
- **No fabricated values.** A hole is a typed status with a reason, never an interpolation.
- **No live-lookup convenience that breaks replay.** If it can't be served with an honest `knowable_at`, it isn't served.

---

## 10. Build order for the product

*Stage labels match `02-build-plan-and-parts.md` §2, where the two-track interleaving with the harness is set out.*

1. **Fact primitive + status enum + EDGAR fundamentals.** The whole thesis is demonstrable on one stream.
2. **Revision chains and the `as_of` selector.** The differentiator.
3. **Concept maps, published and versioned**, with measured coverage.
4. **Determinism receipt and the reproducibility endpoint.** Turns the claim into a test.
5. **Agent affordances:** columnar mode, coverage envelope, capability discovery, comparability guard.
6. **MCP server with mandatory `as_of`.**
7. **Filings, insider, 13F, macro (vintaged), news** — same fact shape, new streams.
8. **Plugin system** — declarative form plus the conformance suite. Ship the suite *with* the plugin loader, never after: a plugin system without enforcement spends the guarantee that is the whole product.
9. **Prediction markets** — contract/quote/resolution, with the versioned resolution criterion and dispute chain.
10. **Social** — post facts backfilled, engagement facts recorder-only.
11. **Attachments:** entity resolution, relationships, cross-venue matching — clearly labelled, filterable out.
12. **Published accuracy audit.** The correctness pitch is unfalsifiable without one, and the competitor's audit methodology is the right thing to copy.

**Out of band, starting immediately:** the recorders. Bluesky, Farcaster and StockTwits have no purchasable archive at all; prediction market quotes and crypto derivatives state are partially recoverable at cost. Recording is independent of build order and is the only thing here with a deadline.

The harness is the credibility artifact: "we built a research system on this — here's the leak check passing, the restatement test correct in both directions, and our Brier score against the prediction markets" is a stronger demo than any accuracy chart.
