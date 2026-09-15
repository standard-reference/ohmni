# Ohmni — Consolidated Specification v4

*2026-09-15. Supersedes `01-system-specification-v3.md`, `03-data-sources.md`, `04-data-product-design.md` and `05-cross-reference-layer.md`, which it merges. Incorporates every correction from `06-drift-audit-001.md` Part 1. Implementation state is §29; it is tracked separately from the spec on purpose.*

---

# PART I — FOUNDATIONS

## 1. Vision, scope, non-goals

Two products, built alongside each other, coupled only through a narrow contract.

**The data layer** — ingestion, point-in-time semantics, a neutral fact format, cross-reference algebra, an API. Standalone. Any consumer can use it.

**The harness** — graph, observation, spark, strategy, testing, calibration. A research environment for strategy *discovery*, in which a model reasons and deterministic code verifies. It consumes *a* data layer through the contract, never *the* data layer.

The harness is philosophically distinct from a model that trades. Here the model is the reasoning core; the harness's job is to let it originate and defend hypotheses under structural discipline, and to catch it when it is wrong.

### Declared non-goals

- **Open source, for now.** Personal build. One discipline keeps the option free at zero cost: never let source data into git.
- **A general-purpose domain-agnostic hypothesis harness.** The artifact+kind engine (§18) is domain-agnostic by construction, so generalising later is cheap — but finance is the deliberate first domain because it gives fast, adversarial, externally-scored resolution. Recorded as a non-goal specifically to prevent drift into it.
- **Profitability, as the first bar.** The first bar is *coherence*: can the pipeline generate a defensible strategy over a data stream at all, and can it refuse one that does not hold up. Winner or not is a later question.

## 2. Two products, one contract

```
/contract          shared port — both depend on this, neither on each other
/data-layer        core, adapters, plugins, xref, api, store
/harness           bus, graph, observation, spark, strategy, testing, calibration
/fixtures          a hand-built DataLayer: honest, adversarial and degraded variants
/conformance       the suite a layer must pass; ships with the plugin loader
```

`/contract` as its own package is what makes the split real rather than nominal.

```python
class DataLayer(Protocol):
    layer_id: str
    layer_version: str

    def sources(self) -> list[SourceDeclaration]: ...
    def capabilities(self) -> CapabilitySet: ...
    def stream(self, start: datetime, end: datetime,
               subjects: list[str]) -> Iterator[Record]:
        """Ordered by knowable_at, non-decreasing."""
    def query(self, subject: str, kind: str,
              window: tuple[datetime, datetime], as_of: datetime) -> list[Record]: ...
```

```python
@dataclass(frozen=True)
class Record:
    id: str
    kind: str                    # neutral: "fundamental", "price", "news", "quote", ...
    subject: str                 # entity_id or instrument_id
    event_time: datetime         # when it happened
    knowable_at: datetime        # when it became knowable — REQUIRED, never null
    value: dict
    status: Status               # §6
    source_id: str
    lineage: Lineage             # originating document, derivation inputs
    revision: Revision | None
```

**What deliberately is not in the contract:** `root_set`, `basis`, `frames`, `EffectClaim`, `spark`. The data layer emits lineage; the harness derives root sets from it on its own side. Lineage is a general primitive; root sets are one consumer's interpretation, and keeping that line is what stops the harness's vocabulary leaking into a product that should also serve a stock screener.

### 2.1 The guard exists on both sides

- **Data layer:** `as_of` is a required parameter, so the API structurally cannot serve future values *to any consumer*. This is what makes "backtest-safe by construction" a product claim rather than a promise.
- **Harness:** the bus enforces ordering and raises on any query past `now()`. This holds *even against a data layer with no guard at all*.

Not redundancy — defence against different failures. The harness never trusts the data layer to be correct, which is the same principle it applies everywhere else, and it is precisely what lets it accept a sloppier layer without silently losing its guarantees.

### 2.2 Capability degradation is declared, never silent

| Capability | Without it | Harness behaviour |
|---|---|---|
| `knowable_at` on every record | No gating possible | **Refuse to run.** Not degradable |
| Typed `status` | Gaps are untyped nulls | Run, flag: not-representable and not-disclosed collapse |
| `revision` chains | Restatement lookahead undetectable | Run, **mark the run contaminated** |
| Survivorship-complete universe | Backtests inflated invisibly | Run, **mark contaminated** |
| `measurement_process` prose | No provenance embedding | Independence-based corroboration unavailable (§20) |
| `derived_from` / `couples_to` | Shared lineage and coupling invisible | Independence over-estimated; correlation cap disabled |
| `native_cadence` | Basis resolution uncheckable | Cadence commensurability skipped (§19.4) |
| `historical_access` ≥ bulk | Multi-epoch basis unfetchable | **Refuse a multi-epoch run** (§7.2) |
| Cross-reference (`/relate`, event spine) | No declared relations | Mechanism-as-graph-path bonus unavailable (§21.3) |

The declared `CapabilitySet` is copied into the run manifest, so a degraded run is *labelled* rather than quietly weaker.

### 2.3 Versioning across the seam

`event_set_hash` spans two independently-versioned products. The manifest carries `layer_id`, `layer_version`, `contract_version`, the layer's `concept_map_version` / `cluster_version`, and **`unavailable_sources`** — a run missing a source must not hash the same as one that had it.

## 3. Recurring design principles

These govern everything below and are the compressed form of the whole document.

- **Deterministic code computes; models interpret.** Never let a model self-report what a computation could verify.
- **Every structured object:** a frozen core contract the engine depends on, plus an open registered kind for everything else.
- **Split registries along genuine interface differences**, not naming. One registry when members are interchangeable; separate when they are not.
- **Keep the top-level concept vocabulary fixed and small**; extend via kinds. This protects real invariants from being quietly defined away.
- **Every verdict or judgment is a stored, queryable artifact**, never an inline boolean.
- **Anything that could be chosen after seeing results must be declared before** — basis, frame spacing, concept map, re-estimation window, regime scope, prediction horizon, epoch set, replication bar. **And a declared form carries rules, not numbers:** a threshold derived in one window is that window's noise level, so parameters resolve against whichever window the form is applied in (`null_quantile(q=0.95)`, `subject_volatility(multiple=1.0)`), never as constants. An unresolvable rule raises; a default would silently carry the derivation epoch's value into a window that never justified it.
- **Never fabricate a value to fill a gap.** Not-representable is a state; interpolation is a lie that manufactures residue.
- **Evidence combines by weighted accumulation**, not binary gates; independence discounts rather than vetoes.
- **The asymmetry between building and breaking a thesis is intentional** — convergence across independent sources to build, a single *sustained* failure to break.
- **Score forward, never backward.** Backtests admit; predictions score.
- **Could-not-compare is never collapsed into compared-and-differed.** This applies to basis alignment, to `/relate` verdicts, to typed gaps, and to replication.

---

# PART II — THE DATA LAYER

## 4. The two claims

**Point-in-time by construction.** Every value carries when it became knowable, distinct from the period it describes, and revisions are preserved as a chain rather than overwrites. Competitors treat time as "which period do you want"; this treats it as "when are you standing."

**Substance deterministic.** Every value, period, availability timestamp, derivation and lineage is produced by deterministic code from a source document. **No model output ever enters a numeric or temporal field.** Models are confined to *attachments* — links and edges that point at facts without altering them.

Both claims are falsifiable in ten minutes, which is the point.

"Substance deterministic" is a structural boundary, not a hedge. "Deterministic on replay" is a caveat about reproducibility and invites the question *so what isn't deterministic?* Substance-deterministic answers it in advance.

| Layer | What it is | Guarantee |
|---|---|---|
| **Substance** | values, units, periods, availability, derivation, lineage | Deterministic by construction — no model in the path |
| **Attachment** | entity links, relationship edges, cross-venue question matching | Deterministic *on replay* — pinned model, content-hash cached |

An attachment can be wrong, and can be ignored. A substance field being model-generated would be unauditable, and that never happens.

### 4.1 Format neutrality

The harness's internal model (basis, frames, residue, EffectClaim, root sets, spark) **never appears in the API**. Practical test: if a field name would be meaningless to someone building a stock screener, it does not belong in the API.

## 5. The primitive is a Fact

Statements, ratios and time series are all *views* over facts.

```json
{
  "entity": {
    "id": "ent_0000320193", "cik": "0000320193", "name": "Apple Inc.",
    "ticker_at_period": "AAPL", "sic": "3571"
  },
  "concept": {
    "id": "revenue", "map_version": "cm_2026.3",
    "source_tag": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    "peer_group": "technology_hardware", "sign_convention": "positive_is_inflow"
  },
  "value": {
    "amount": "58015000000", "unit": "USD", "scale": 1,
    "display": "58.02B USD", "as_filed": true
  },
  "period": {
    "type": "duration", "start": "2018-12-30", "end": "2019-03-30",
    "days": 91, "span": "standalone_quarter",
    "fiscal": { "fy": 2019, "fp": "Q2", "fy_end_month": 9 }
  },
  "time": {
    "knowable_at": "2019-05-01T20:31:00Z", "as_of_used": "2019-06-15", "lag_days": 32
  },
  "status": "reported",
  "derivation": { "method": "filed", "inputs": [] },
  "revision": {
    "index": 0, "chain_length": 2, "superseded_at": "2019-10-31",
    "chain_url": "/v1/facts/chain/fct_8x2k9"
  },
  "source": {
    "accession": "0000320193-19-000066", "form": "10-Q",
    "document_url": "https://www.sec.gov/Archives/edgar/data/320193/...",
    "tag_path": "us-gaap:RevenueFromContract.../USD/2018-12-30..2019-03-30",
    "retrieval": "as_of", "record_survivorship": "complete",
    "plugin_trust": "certified"
  },
  "provenance_class": "measured"
}
```

- **`amount` is a string.** Large integers lose precision in some JSON parsers, and language models mangle long digit strings.
- **`display` is redundant on purpose.** Cuts magnitude and arithmetic errors in model reasoning substantially, at trivial token cost.
- **`scale` is always explicit and always 1.** Filings report in thousands or millions; normalise at ingest. "In thousands" headers are among the most common sources of 1000× errors in agent-built models.
- **`lag_days`** saves a date subtraction consumers get wrong around fiscal boundaries.

## 6. The status enum

Everyone else returns a number or `null`. `null` collapses at least five genuinely different states, and an agent cannot recover the distinction. Highest-value, lowest-cost thing in the product.

| status | Meaning | Example |
|---|---|---|
| `reported` | The entity filed this value for this period | Revenue in a 10-Q |
| `derived` | Computed deterministically; `derivation.inputs` lists the inputs | Q2 standalone from Q2 YTD minus Q1 |
| `not_representable` | Cannot be honestly computed | Q4 standalone (§8) |
| `not_disclosed` | Concept applies but the entity did not report it | R&D for a company that does not break it out |
| `not_applicable` | Concept does not apply to this entity type | Inventory for a bank |
| `not_covered` | Outside coverage | Pre-XBRL period, or a custom extension tag |

`not_representable`, `not_disclosed` and `not_covered` are three different reasons for a hole, and a consumer reasons differently about each — do not ask again, read the filing text, try another source.

**`derived` is never silent.** If a value was computed, the method and exact input facts are in the response.

## 7. Provenance and source declaration

```python
@dataclass(frozen=True)
class SourceDeclaration:
    source_id: str
    measurement_process: str              # prose — embedded for independence (§20)
    derived_from: list[str]               # source_ids this computes from; empty if raw
    couples_to: list[tuple[str, float]]   # known mechanical coupling + strength
    backfilled: bool                      # computed live, or reconstructed later?
    retrieval: Literal["as_of", "snapshot"]
    record_survivorship: Literal["complete", "deletions_unrecoverable"]
    historical_access: Literal["bulk", "metered", "rate_limited", "record_only"]
    bulk_endpoint: str | None
    publication_lag: dict                 # kind → timedelta, justified
    native_cadence: dict                  # kind → timedelta | None (None = irregular)
    measurement_type: Literal["measured", "estimated", "modeled"]
    known_biases: list[str]
```

- **`measurement_process`** is the text embedded to compute provenance distance. Write the *process*: "SEC electronic filing submission of XBRL-tagged statements", not "fundamentals". One-word labels sit close to everything in embedding space.
- **`couples_to`** closes the gap root sets and provenance both miss. Root sets catch shared *lineage*; provenance embeddings catch shared *method*; neither catches shared *economic driver* — options and spot on one underlying have disjoint lineage and distant provenance yet are coupled through delta. Declared, not estimated. **Declared per instrument where a source's contracts differ in exposure:** a market on "AAPL above $200" is delta-coupled to AAPL spot; one on "Fed cuts in March" is coupled to rates and to no equity.
- **`backfilled`** is the alt-data equivalent of restatement: a signal sold "with history to 2015" computed by running today's methodology over archived inputs never existed as a live signal.
- **`retrieval: snapshot`** means a historical query returns the *present* value — engagement counts, follower counts, app-store rankings, search indices rescaled per window. No revision chain exists because intermediate values were never stored. A snapshot stream **cannot be honestly backfilled**, only recorded forward. Harder than `backfilled`: backfilled history is suspect, snapshot history is simply wrong, in the direction of the future.
- **`record_survivorship: deletions_unrecoverable`** means a historical pull returns only records that still exist. The delisted-ticker problem applied to records, and worse in social data than equities: deletions skew toward wrong calls and retracted claims, so a backfill over-represents what nobody regretted saying.

A stream that is both `snapshot` and `deletions_unrecoverable` has no honest historical mode. The API refuses a historical `as_of` query against it and says why.

### 7.1 `historical_access` — retrieval feasibility

`retrieval: as_of` says a historical query returns historical values. It says nothing about whether the history can be **fetched at scale**, and that is a separate, decisive question.

| value | Meaning |
|---|---|
| `bulk` | A bulk archive exists; record `bulk_endpoint` |
| `metered` | Per-request, priced; backfill cost is a budget question |
| `rate_limited` | Throttled to the point of impracticality for backfill |
| `record_only` | No history at any price; forward recording is the only path |

### 7.2 `check_backfillable()`

**A multi-epoch basis cannot rest on a source whose history cannot be fetched at scale**, because the field will be present in some epochs and absent in others — which silently changes the basis (§23.1). The check fires **before the first request**, not hours into a fetch when the epochs already differ:

```
a multi-epoch basis cannot rest on sources whose history cannot be fetched at
scale; these would be present in some epochs and absent in others:
  news_rate via gdelt.news (rate_limited)
  — a bulk archive exists at https://data.gdeltproject.org/gdeltv2/masterfilelist.txt
```

## 8. The quirks catalogue

These are what make financial data hard. Handling each explicitly *is* the product, and every one is deterministic.

### Period structure

- **Q4 standalone does not exist.** Companies file a 10-K, not a Q4 10-Q. FY − Q1 − Q2 − Q3 produces a number nobody filed; in a frames-and-cancellation model it reads as a field changing when nothing happened, manufacturing residue. Return `not_representable`, with `annual` and the three filed quarters available.
- **YTD vs standalone durations.** A Q3 10-Q often reports both Jul–Sep and Jan–Sep. Disambiguate by duration length and label with `period.span`. Never silently pick one.
- **Instant vs duration.** Balance-sheet facts are instants (no `start`); income and cash-flow are durations. Explicit, not inferable from which concept it is.
- **52/53-week fiscal years.** Roughly every fifth year has a 14-week Q4. `period.days` makes it visible; a consumer comparing Q4 year-over-year needs to know one period was 10% longer.
- **Fiscal year changes** produce a stub period of unusual length. Report as filed, never stretched.
- **Fiscal is not calendar.** Serve fiscal periods as filed; calendar alignment is an explicit, labelled, opt-in view.
- **Pre-IPO periods** appear in a first 10-K. Legitimate, and `knowable_at` is the filing date.

### Revisions

- **Restatements are a chain, not a pair.** Serve the full chain with an index and let `as_of` select. Two fixed dimensions (as-reported / most-recent) are a lossy projection.
- **Amended filings** (`10-K/A`, `10-Q/A`) are ordinary chain links: same period, later `knowable_at`.
- **Discontinued operations restate prior periods.** Expose the cause in the chain entry.
- **Late filings.** NT 10-K/NT 10-Q signals delay; the eventual `knowable_at` is genuinely later, which is material to earnings timing.

### Values, units, signs

- **Sign conventions vary.** Normalise to one declared convention and publish `concept.sign_convention`. Negative revenue is rare but real; do not clamp.
- **Reporting-currency changes.** Serve the filed currency. If converting, `value.converted_from` carries the rate, its source, its date, and the rate's own `knowable_at`.
- **Filer scale errors.** A deterministic magnitude check against the entity's own history flags outliers — `quality_flags: ["magnitude_outlier"]`. Flag, never silently correct.
- **Share classes.** Serve per-class plus an explicit labelled total.

### Per-share values and corporate actions

A filed EPS is in **pre-split terms**. Adjusting it for a later split applies information that did not exist at the filing date — lookahead in a field that looks innocent.

**Resolution:** serve per-share values exactly as filed (`value.as_filed: true`), and publish split/dividend adjustment factors as a **separate series with their own `knowable_at`**. A consumer composes the adjusted series and inherits correct availability semantics. Never pre-adjust.

### Entities

- **Tickers are point-in-time and get recycled.** Serve a permanent `entity.id`; expose `ticker_at_period` for the requested date.
- **CIK survives renames and delisting** — the right internal anchor.
- **Mergers.** The surviving entity's history is not the combined history. Do not splice; expose the relationship.
- **Delisting mid-period** produces a truncated final period. Report as filed.
- **Segment vs consolidated.** Entity-wide consolidated facts are what a top-level concept means; segment data goes behind an explicit dimensional endpoint.

### Coverage limits

- **XBRL starts 2009**, phased to ~2011 for full coverage. `not_covered`, with the reason.
- **Custom extension tags are invisible** to the aggregated XBRL APIs, which cover only standard taxonomies. `not_covered` with `reason: "custom_taxonomy"` — never interpolated, and the count reported so the gap's size is visible.

### 8.1 Concept maps — cross-entity comparability as a declared artifact

Cross-entity comparison is **required**, not optional: §17's cross-sectional replication argument is itself a cross-entity claim, most real fundamental mechanisms are relative, and "peers did not move" corroboration is inherently cross-entity.

```python
@dataclass(frozen=True)
class ConceptMap:
    version: str                      # pinned; in the manifest; changes bump event_set_hash
    concept: str
    tag_precedence: list[tuple[str, str]]   # ordered (taxonomy, tag)
    peer_group_scope: list[str]
    coverage: dict[str, bool]         # measured per entity, not assumed
```

Two distinct problems, only one of which standardisation solves:

- **Tag variation** — several standard tags for one concept. A finite, known set; a lookup table with precedence order. Solvable.
- **Industry incomparability** — a bank's revenue is interest income plus fees, a manufacturer's is product sales. **Not** a standardisation problem; no vendor fixes it. Needs `peer_group_scope`, declared.

Comparison is valid **within a declared map and peer group, with measured coverage**. A concept queried outside its declared scope raises rather than returning a value.

**Validation via a cheap oracle.** Where a vendor's standardised values disagree with EDGAR-derived concept values, that flags one of the two. A few hundred companies across a few years validates a mapping table for the price of a one-off credit pack.

## 9. Sources

### 9.1 The criteria that decide everything

The first two represent contamination the no-lookahead guard **structurally cannot catch**, because the timestamp is honest and the *value* is wrong.

1. **Point-in-time integrity.** Does each record carry an availability date distinct from the period it describes, and are restatements preserved rather than overwritten?
2. **Survivorship bias.** Does the universe include delisted, acquired and bankrupt entities? Most cheap equity vendors quietly serve only currently-listed tickers.
3. **Backfill honesty.** Computed live, or reconstructed later by running today's methodology over archived inputs?
4. **Retrieval feasibility.** Bulk or metered? A rate-limited archive is unavailable for multi-epoch work regardless of what its schema promises (§7.1).
5. **Independent measurement processes.** Breadth of *process* is scarce; breadth of *fields* is cheap and mostly redundant.

### 9.2 EDGAR is natively point-in-time — the decisive finding

Every XBRL CompanyFacts fact instance carries `end`, `val`, `accn` and `filed`. Where a period is restated, **multiple fact objects exist for the same `end` with different accession numbers**, so the full revision chain is preserved.

```python
def as_of(facts: list[XbrlFact], as_of: date) -> dict[tuple[date, str], XbrlFact]:
    """What was knowable at `as_of`: latest revision filed on or before it."""
    visible = [f for f in facts if f.filed <= as_of]
    out = {}
    for f in sorted(visible, key=lambda f: (f.filed, f.accn)):
        out[(f.end, f.unit)] = f
    return out
```

| Semantics | Gives | Problem |
|---|---|---|
| As-reported (first print, pinned) | The original figure forever | Ignores that the market later learned the restatement |
| Most-recent (restated) | Today's figure | Lookahead |
| **As-of, from the revision chain** | **What was knowable at T** | none |

Both vendor dimensions are lossy projections of this. Free, public domain, 10 req/sec, `User-Agent` mandatory.

**Event emission: one filing, one event.** `available_time` is a property of the filing, not of individual facts. One event per `accn`, `available_time = filed`, payload carries every fact with its own `start`/`end`. Consequence: a restated 2019 figure appearing in a 2021 filing carries the 2021 filing date, so the bus gates it correctly with no special handling.

### 9.3 Free sources — build the adapter

| Source | Measurement process | PIT notes | Access |
|---|---|---|---|
| **SEC EDGAR XBRL** | Corporate accounting disclosure | PIT by construction | bulk |
| **SEC EDGAR filings** (8-K incl. Item 1.01) | Electronic filing submission | acceptance datetime | bulk |
| **SEC Forms 3/4/5** | Insider legal disclosure | filing date | bulk |
| **SEC 13F** | Institutional position reporting | filing date, up to 45d after period end | bulk |
| **SEC Exhibit 21** | Subsidiary/ownership structure | filing date | bulk |
| **SEC CIK↔ticker map** | Entity resolution anchor | historical; CIK survives renames | bulk |
| **ALFRED** (archival FRED) | Statistical-agency publication, **vintaged** | vintage date — never plain FRED | bulk |
| **GDELT 2.0** | Global news-wire ingestion | ingest window, not article date | **bulk archive; the v2 doc API is rate_limited** |
| **Wikimedia pageviews** | Public information-seeking behaviour | hourly, from 2015, ~1d lag | bulk |
| **Hacker News (Algolia)** | Community discourse | full history | metered |
| **FINRA ATS / short volume** | Off-exchange order routing | weekly / daily, honest lag | bulk |
| **Wikidata, GLEIF, OpenFIGI** | Entity graph, LEI, instrument mapping | — | bulk |
| **Press wires RSS** | Originating corporate announcements | wire timestamp | record_only |
| **Wayback CDX** | First-capture verification | the timestamp arbiter for mutable pages | metered |
| **Federal Register, openFDA, ClinicalTrials, USPTO, USAspending, CourtListener, EIA, NOAA** | Regulatory, approvals, patents, contracts, litigation, energy, weather | varies | bulk |

**Wikipedia pageviews is the standout and usually overlooked:** free, hourly, deep history, entity-keyed through Wikidata, and it measures retail information-seeking — uncoupled from price in the way options are not.

**GDELT volumetrics:** GKG is ~39 MB/day (~7 GB per six-month epoch); the `gkgcounts` variant is ~4.7 MB/day (~850 MB), which is the tractable one.

### 9.4 Prediction markets — a distinct measurement process

Measures aggregated explicit probabilistic belief about a named future event, and every contract resolves definitively — the only source here that supplies free labelled outcomes.

| Venue | Stake | Notes |
|---|---|---|
| **Kalshi** | Real money | CFTC-regulated; macro, Fed, CPI, elections, weather |
| **Polymarket** | Real money | On-chain, so quote and resolution history is independently auditable; oracle resolution with a dispute window |
| **Metaculus** | Reputation | Aggregated forecasts, long horizons, calibration-focused |
| **Manifold** | Play money | Very open API, low signal per market |
| **Iowa Electronic Markets** | Real money | Academic; election history to 1988 |

**Three artifact types, not one:** a contract (with a **versioned resolution criterion carrying its own `knowable_at`** — venues clarify wording after launch, which is a restatement of the *instrument definition*), a stream of transient quotes (`record_only`), and a resolution (**with its own revision chain**, since disputes overturn outcomes).

Quirks: thin liquidity means price is not probability, so always serve bid/ask/last/volume/OI/spread with a `liquidity_flag`; never a bare probability field without a declared `method`; multi-outcome sets do not sum to 1 and must not be silently normalised; `stake` is required because play money is a different process; `days_to_resolution` is first-class, since 60% at six months and 60% at one day are different claims; cross-venue question matching is an **attachment**, never substance.

### 9.5 Social — forward-record-only

Two contaminations, and the second is rarely discussed. **Engagement metrics are current-snapshot**: pull a 2019 post today and every count is from today, with no revision chain because intermediate values were never stored. **Deleted-record survivorship**: a historical pull returns only surviving posts, and deletions skew heavily toward wrong calls and retracted claims.

So the adapter declares `retrieval: snapshot`, `record_survivorship: deletions_unrecoverable`, and serves two families: **post facts** (text, author, `created_at` — backfillable) and **engagement facts** (each an observation at an `observed_at` instant, **recorder-only, never backfilled**). That split makes the honest half usable and the dishonest half structurally impossible to serve as history.

Edited posts have a genuine revision chain. Reposts carry lineage to an originating post — fifty reposts are one claim. Bot inflation is a `quality_flags` entry from deterministic heuristics, never a model verdict.

Bluesky (AT Protocol firehose) and Farcaster are fully open and free; StockTwits is finance-specific; X is ~$200/mo Basic with full-archive at Pro tier and up. Reddit is paid and commercially restrictive; Pushshift is gone.

### 9.6 Redundancy — what not to ingest alongside what

Two sources are redundant when they share **root lineage**, and ingesting both without declaring it makes §20.3's accumulation sum them as independent legs. Redundant sources do not just cost money, they manufacture false confidence.

| Pair | Relationship | Handling |
|---|---|---|
| EDGAR fundamentals ↔ vendor fundamentals | Same root filings | Never corroboration. Validation oracle only |
| Vendor insider tier ↔ SEC Form 4 | Vendor scrapes SEC | Take Form 4 from EDGAR |
| Vendor price ↔ vendor price | Same measurement process | One is enough |
| News ↔ derived sentiment | Sentiment computed from the news | Declared `derived_from`; the deliberate true-negative fixture |
| Options ↔ spot, same underlying | Disjoint lineage, distant provenance, **coupled through delta** | `couples_to`; correlation cap |
| Plain FRED ↔ ALFRED | Same series, revised vs vintaged | ALFRED only |

### 9.7 Independent measurement processes — the scorecard

Exchange order matching · corporate accounting disclosure · insider legal disclosure · institutional position reporting · editorial publication · statistical-agency publication (vintaged) · public information-seeking behaviour · congressional disclosure · corporate announcement · regulatory rulemaking · blockchain settlement · derivatives positioning · off-exchange order routing · aggregated probabilistic belief · retail discourse · community discourse.

Sixteen processes, almost entirely free. Most paid bundles span fewer. **Hacker News is `RETAIL_DISCOURSE` / community discourse and deliberately not editorial publication** — a community submission and a wire story are different phenomena, and collapsing them to reuse a template would be choosing the measurement to fit the hypothesis.

### 9.8 Record-now-or-buy-later

| Stream | Archive purchasable later? |
|---|---|
| **Bluesky firehose** | **No — record or lose it** |
| **StockTwits / Farcaster** | **No** |
| **X post stream** | Partially, at Pro-tier pricing, still survivorship-biased |
| **Prediction market quotes** | Partially, venue-dependent |
| Deribit options IV / skew | Yes, paid |
| Perp funding + open interest | Yes, paid |
| App store rankings | No |

The top four have no purchasable archive at any price. Everything else in §9.3 is permanently re-fetchable. A cron job costs almost nothing and is the only thing in this document with a clock on it.

### 9.9 Diligence checklist for any new source

1. Availability date distinct from the period described?
2. Revisions preserved as separate records, or overwritten?
3. Delisted/acquired/bankrupt included? Point-in-time universe membership?
4. As-published or reconstructed (`backfilled`)? If enriched, recomputed when models change?
5. Timestamp reflects first ingest or claimed publication?
6. **Bulk export or per-request?** What does a full backfill actually cost, in money and in time?
7. How many years at the tier you would actually pay for?
8. What measurement process does this add that the set lacks? If none, redundant regardless of price.
9. Mechanically coupled to something already ingested? At what strength?
10. Does it require a live API call at decision time? If so it cannot be used inside replay.

**The test that settles point-in-time claims empirically:** pick a known restatement, query as-of a date before it was filed, and check whether you get the original figures or today's. It works against any vendor and against our own adapter.

## 10. Cross-reference

Cross-referencing looks like one problem and is four, each answerable deterministically.

| Question | Mechanism |
|---|---|
| Do these share an axis? | Join spines (§10.1) |
| Are these the same thing? | Identity tiers (§10.2–10.3) |
| What operations are valid? | Field algebra (§10.5) |
| What is declared to connect them? | Relation registry, phenomenon groups (§10.6–10.7) |

**The boundary, defended throughout:** this layer serves the *algebra* — what is structurally valid and what is declared. It never serves inference.

### 10.1 Join spines

| Spine | Key | Notes |
|---|---|---|
| **Entity** | `entity_id` | The universal one. CIK-anchored, point-in-time tickers |
| **Instrument** | `instrument_id` | One entity has many and they are **not** interchangeable — share classes, options, ADRs |
| **Person** | `person_id` | Form 4 filers, executives, congresspeople, authors. The hardest to resolve |
| **Document** | `accession` / `doc_id` | The lineage axis; what makes independence computable |
| **Event** | `event_id` | §10.3 |

**Instrument-vs-entity is the spine people get wrong.** Fundamentals are entity-level; prices, options and short interest are instrument-level. Joining revenue to "its" price requires choosing an instrument, explicitly.

### 10.2 Identity tiers

One tiered structure covers all identity in the product.

| Tier | Method | Class |
|---|---|---|
| 1 | `cik_exact`, `figi_exact`, `lei_exact`, `accession_exact` | `measured` |
| 2 | `ticker_pit`, `name_exact`, declared-window structural coincidence | `derived` |
| 3 | `name_fuzzy`, `model_linked`, semantic match | `linked` / `matched` (attachment) |

**Entity resolution by text query is the weakest join in the whole source set.** An unquoted `AMD` matches thousands of stories a month on prefix and typo similarity, against a handful for the quoted phrase — the difference between a signal and a noise generator. Resolution confidence must reach the observation layer and discount separation (§19.3), not sit in a log.

### 10.3 The event spine

One occurrence surfaces across many processes: a drug approval appears as an openFDA record, a press release, a Federal Register notice, forty news articles, an 8-K, and a resolved prediction market.

```json
{
  "event": {
    "id": "evt_9k2m4x", "type": "regulatory_approval",
    "subject_entities": ["ent_0000078003"],
    "first_knowable_at": "2019-04-12T13:04:00Z",
    "cluster_rule": "identifier_exact", "cluster_version": "es_2026.2",
    "observations": [
      { "source": "openfda", "knowable_at": "2019-04-12T13:04:00Z",
        "join_tier": 1, "join_key": "NDA-021436", "provenance_class": "measured" },
      { "source": "wire.businesswire", "knowable_at": "2019-04-12T13:31:00Z",
        "join_tier": 1, "join_key": "NDA-021436", "provenance_class": "measured" },
      { "source": "edgar.8k", "knowable_at": "2019-04-12T21:02:00Z",
        "join_tier": 2, "join_key": "entity+type+48h", "provenance_class": "derived" },
      { "source": "gdelt.news", "knowable_at": "2019-04-12T14:10:00Z",
        "join_tier": 3, "confidence": 0.88, "count": 43, "provenance_class": "matched" }
    ]
  }
}
```

**`first_knowable_at` is the field nobody else serves.** Three rules make it safe: the cluster is a **stored artifact with its own lineage**, not computed per request; the tier-2 window is **declared, never tuned per case**; and `substance_only=true` drops tier 3 entirely.

**Tier-3 observations collapse to a count with a drill-down**, never enumerated inline.

**Derived independence:** an event's observation set yields measurement-process breadth directly. One event observed by six processes is genuinely corroborated; one observed forty-three times by one process is one observation with high coverage. The event spine makes that distinction once rather than per consumer.

### 10.4 Temporal joins

A join can leak even when every value is honest. Joining fundamentals to prices on **period end** introduces lookahead in the join itself.

**One primitive only: as-of join on `knowable_at`.** The API exposes no join-on-period option at all — make the wrong join unavailable rather than discouraged.

**The coarsest-cadence rule.** Aggregating fine → coarse is deterministic arithmetic over observed values. Disaggregating coarse → fine is fabrication. So resolution is always the **coarsest common cadence**, and upsampling is **refused**, not offered. Irregular streams become **rate-per-window** fields; anything not expressible at that resolution is a typed gap, not a zero.

Every joined value declares its join — spine, method, tier, confidence, `temporal: as_of_knowable_at`, `as_of_used`, and **`staleness_days`**, the field that stops a consumer treating a 45-day-old filing as current.

### 10.5 Field algebra

```json
"quantity": {
  "dimension": "monetary_flow", "unit": "USD", "temporal_type": "duration",
  "aggregation": "additive", "weight_field": null, "denominator_rule": null,
  "polarity": "higher_is_inflow", "native_cadence": "P3M"
}
```

**Dimensions:** `monetary_flow` · `monetary_stock` · `count` · `rate` · `ratio` · `probability` · `index` · `share_count` · `price_per_share` · `duration`

**Aggregation — the cheapest error-preventer in the layer:**

| value | Failure it prevents |
|---|---|
| `additive` | — |
| `averageable` | Summing four quarters of headcount |
| `weighted_average` (needs `weight_field`) | Averaging four quarterly margins — the annual margin is revenue-weighted |
| `point_in_time` | Summing four quarters of total assets |
| `non_aggregable` | Averaging credit ratings |

**`denominator_rule`** handles the stock/flow subtlety: a flow over a stock (turnover, ROE) needs the *period-average* stock, not the endpoint.

**The validity matrix is derived, not stored:** sum requires same dimension, same unit, both additive; difference requires same dimension and unit; ratio allows any pair with compatible units after the denominator rule; product only where one side is dimensionless.

### 10.6 The relation registry

**Only declared structural facts, never empirical ones.** "Revenue − COGS = gross profit" is structural. "Pageviews lead price by three days" is a signal, and the product does not sell signals.

| type | Source | Class |
|---|---|---|
| `arithmetic_component` | XBRL **calculation linkbase** — the filer's own asserted arithmetic | `measured` |
| `taxonomic_parent` | XBRL **presentation linkbase** | `measured` |
| `segment_of` | XBRL dimensional context | `measured` |
| `expectation_of` / `realization_of` | A prediction market contract and the macro print it resolves against | `measured` |
| `superseded_by` | Revision chain | `measured` |
| `same_phenomenon` | Phenomenon group membership | `mapped` |
| `counterparty_of` | Relationship extraction from prose | `extracted` (attachment) |

**Relations are scoped, not universal.** A calculation-linkbase relation is asserted *by a specific filing*, valid for that filing's facts, and may differ across filings and eras. The `scope` block is mandatory. Serving the linkbases is also a moat item: nobody publishes them, they are pure substance, and they are what an agent needs to know two unlike fields are arithmetically related rather than merely adjacent.

### 10.7 Phenomenon groups

Multiple fields measuring one underlying quantity through genuinely different processes.

| Phenomenon | Members |
|---|---|
| Attention | pageviews, news mention count, social post volume |
| Insider conviction | Form 4 net buys, congressional trades |
| Positioning / leverage | short interest, options open interest, perp funding |
| Distress | going-concern language, 8-K Item 4.02, credit downgrades |
| Expectation | prediction market implied probability, analyst consensus vintage |

Each member declares its `process`. The group **asserts that these measure the same underlying quantity** and explicitly **does not assert that they agree, correlate, or are interchangeable** — the `does_not_assert` field is in the payload because the distinction is the point.

**Direct contribution to independence:** members with *distinct* `process` values are candidate independent corroborating legs; members sharing a process are one leg counted twice.

### 10.8 `/relate` and `/panel`

`/relate` returns a verdict, the shared spines, both quantities, the forced resolution with its reason, required transforms, valid operations, **blocked operations with reasons**, declared relations and shared phenomena.

| verdict | Meaning |
|---|---|
| `directly_relatable` | Shared spine, compatible dimensions, same cadence |
| `relatable_with_transform` | Shared spine; deterministic transforms listed |
| `relatable_via_relation` | A declared relation connects them |
| `no_shared_data` | Relatable in principle, no overlapping observations |
| `incommensurable` | No shared spine, or no valid operation |

`no_shared_data` and `incommensurable` must never collapse — a consumer retries with a wider window in one case and stops in the other.

`/panel` does the join, because alignment is where the errors are: columnar rows with status columns interleaved, transforms declared per field, `upsampling: "refused"` stated rather than implied, `max_staleness_days`, a coverage envelope with typed gaps, and a determinism receipt.

## 11. The plugin system

Users and their agents add their own sources. This is where the substance-deterministic guarantee is most at risk, so **the guarantee is enforced by contract, not by trust.**

**Declarative first, code as the escape hatch.** Most REST sources need no code — a YAML declaration with `availability_field` **required and with no default**. If the source exposes no such field, the plugin must declare a justified `publication_lag` or declare `retrieval: snapshot`. There is no path where availability is silently omitted; that single required field is the main enforcement point in the whole system.

For anything the declarative form cannot express, `fetch` and `normalize` are **deliberately separate**: `fetch` is the only network boundary and its output is cached raw; `normalize` must be a **pure function** of raw input, which makes it testable, re-runnable after a bugfix with no refetch, and provably deterministic.

### 11.1 The conformance suite

| Check | What it rejects |
|---|---|
| Declaration completeness | Missing `measurement_process`, `availability_field` or lag, `retrieval`, `record_survivorship`, `historical_access`, `native_cadence`, `couples_to` |
| Normalize determinism | `normalize(raw)` twice must be byte-identical. Catches dict ordering, timestamps, randomness, anything model-generated |
| **No network in normalize** | Sockets blocked during `normalize`. **The check that structurally prevents live-lookup-in-replay** |
| Availability sanity | `knowable_at` null, silently equal to period end, or earlier than `event_time` |
| Status honesty | Any fact with a null value and no typed status |
| No fabrication | `status: derived` with empty `derivation.inputs`, or inputs that do not reproduce the value |
| Attachment declaration | A plugin declaring no model but importing inference libraries |
| Cadence coherence | Facts arriving at a cadence its declaration says is impossible |

### 11.2 Trust tiers

```
certified    — we wrote and audit it. Full guarantee.
conformant   — passes the full suite. Guarantee is structural, not social.
declared     — registers but skips or fails checks. Facts tagged; excluded from substance_only.
```

Every fact carries `source.plugin_trust`, so a consumer — or the harness's independence machinery — can filter rather than trust or reject the whole set.

**Agent-authored plugins:** the suite is the trust boundary, not the author. An agent-written plugin that passes conformance is exactly as trustworthy as a hand-written one *with respect to the properties the suite checks*. **The honest limit:** conformance guarantees *structure*, not *meaning*. A plugin can pass every check and still map the wrong upstream field to `revenue`. Semantic correctness needs an oracle cross-check or human review.

## 12. API surface and agent affordances

**The determinism receipt.** Every response carries `response_hash`, `pipeline_version`, `concept_map_version`, `attachment_model_versions` and `substance_only`. Same query plus same versions produces an identical hash, provable via a public replay endpoint. A competitor with an LLM in the extraction path cannot do this at all.

**Provenance classes.** Substance: `measured`, `derived`, `mapped`. Attachment: `linked`, `extracted`, `matched`. `?substance_only=true` returns facts with no attachment-class fields — one parameter answering "is there AI in my data."

**Other affordances, none of which need AI:** columnar mode (schema once, rows as arrays — roughly two-thirds fewer tokens on time series) · a completeness envelope with enumerated typed gaps, because agents cannot detect silent ones · capability discovery (`/entities/{id}/concepts`) so agents stop guessing concept names · a comparability guard that warns or refuses on incompatible peer groups · published versioned concept maps · cursor pagination with an explicit `complete` flag · **an MCP server where `as_of` is a required parameter, pinned per session**, so an agent cannot accidentally read present-day values mid-replay · OpenAPI and llms.txt.

**What the product deliberately does not do:** no summarisation or interpretation · no scores, signals, rankings or sentiment · no silent normalisation · no fabricated values · no live-lookup convenience that breaks replay.

---

# PART III — THE HARNESS

## 13. Pipeline

```
Data layer (Records, via the contract)
        ↓ ─────────────────────────────── contract boundary
Bus: sim-clock, lookahead guard, Record→Event, root-set derivation
        ↓
Market graph (deterministic analytics)
        ↓
Observation: frames over a declared basis → delta by cancellation
        ↓
Spark: mechanism, corroboration, invalidation
        ↓
Formalizer (spark → generic trade type)
        ↓
Execution engine (event-driven backtest / live, shared)
        ↓
Testing (null control, leak check, robustness, adversarial)
        ↓
Prediction registration → resolution → calibration ledger
        ↓
Replication across epochs → core promotion
        ↓
Spark log / human session
```

## 14. Market graph

```
Node { id, type: "asset" | "entity" | "narrative" | "factor" | "regime",
       label, attributes{}, last_updated }

Edge { id, source, target,
       type: "correlation" | "sentiment_link" | "mention" | "lead_lag" | "flow"
           | "partnership" | "supplier" | "customer" | "ownership",
       weight, dispersion, weight_history[], last_updated }
```

Deterministic code — never the model — computes correlation shifts, centrality changes, community reshuffling and anomaly detection, emitting anomaly events on threshold crossings. The model interprets and prioritises; it never does arithmetic.

`regime` is a first-class node type so mechanisms can declare scope (§21.2). `entity` nodes and **entity→entity relationship edges** are what make §21.3's causal paths expressible; without them every basis is price looking at itself. The vocabulary is explicitly **illustrative and growing**, and that growth is tracked as basis coverage (§19.1).

## 15. Bus and execution

Event-driven, not a fixed CSV backtest. Every source normalises into the same event types pushed through one bus in timestamp order.

**A sim-clock gates the bus.** A strategy sees only events up to "now" in replay time, enforced structurally at the bus, not trusted to model discipline. The clock advances to each event's `available_time` *before* the event reaches handlers, per-event, never batched.

**The guard raises, never truncates** — a truncating guard returns a wrong window and the caller proceeds on it. It checks `available_time`, not `event_time`.

**Ordering** is non-decreasing `available_time`, ties broken by `(available_time, source_id, id)` — never by registration or dict order.

**Two timestamps, always gated on availability.** A 1h bar stamped 14:00 is not knowable until 15:00; a 10-Q's period end precedes its filing by weeks; a GDP print is revised for years. Gating on the wrong one produces silently optimistic backtests with no error anywhere.

**Decision latency.** Decisions are stamped at `event_time + modeled_inference_delay`, or backtests are systematically optimistic.

**Replay determinism.** Every model output is recorded as an event keyed by `(prompt_hash, event_set_hash, model_id, embedding_space_version, concept_map_version)`.

**Hard rule: no model or agent calls a data API directly.** Every byte reaches reasoning through the bus. A hosted MCP data server queried inside a replay reads present-day values at sim-time 2019, and no guard can see it because the data never passes through the bus. This is a lookahead rule, not a licensing one.

**The audit trail** records every decision and the exact events it was conditioned on. Event-sourced, so the same engine is the live path later — no second implementation.

## 16. Testing — four passes

1. **Null control (runs first).** Bootstrapped / shuffled markets with no real structure. If the pipeline promotes anything here, false-discovery control is broken and every downstream result is meaningless. Cheap, so it runs before anything else. **`block_bootstrap` is the honest null** — it preserves fat tails and volatility clustering, which `iid_shuffle` destroys, so a pipeline surviving only the latter may be detecting nothing but those. **Nulls must cover every stream and destroy cross-stream structure**; real news with shuffled prices is not a null.
2. **Leak check (mechanical).** Walk the audit trail for any decision conditioned on information not yet available at its sim-time. Must also run **across epoch boundaries**, not only within a window.
3. **Robustness (deterministic).** Walk-forward across regimes, parameter sensitivity, comparison against dumb baselines. Genuine historical precedent lives here — a real point-in-time replay, never a model's claimed recollection. Where a mechanism declared a regime scope, this checks *that declared scope* rather than fishing.
4. **Adversarial critique (LLM).** A second model attacks the causal story: plausible mechanism, likely coincidence, regime fragility.

Execution and testing are decoupled — testing consumes only an execution trace.

**Detection thresholds derive from the null, not from a constant.** The movement tolerance is taken from the null distribution's own quantiles with a measured false-positive rate, rather than configured and then checked. Same principle as rules-not-numbers (§3), one layer down.

**Planted-effect suite (later).** Synthetic markets with a known injected mechanism, to measure recall. Deferred: realistic synthetic microstructure is its own project, whereas nulls are nearly free.

### What the null control is actually for

Not only false discovery per spark. **The null tests the protocol's entire output
distribution.** Every per-spark mechanism can be behaving exactly as specified,
each individual spark clean, and the *rate and shape* of promotions still be
indistinguishable from noise. Nothing inside a single spark can reveal that.

So the whole protocol is run unchanged over structureless markets, enough times
to make a count mean something, with the reading of the result declared before it
runs. A null generator must preserve what the mechanism does not claim — a block
bootstrap keeps fat tails and volatility clustering and destroys only the
arrangement — or the control is too easy to beat and passing it means nothing.

The conformance suite carries the matching structural check on the data side:
reading an already-loaded layer must not touch the network, enforced by blocking
sockets during a read. `fetch` is the only network boundary, and a layer that
reaches out during a read can serve a present-day value at sim-time 2019 with no
downstream discipline able to notice.

## 17. Data snooping, budgets, replication

The largest risk in the design. Thousands of sparks against the same history means some pass walk-forward by chance, and any ranking on backtests selects precisely for those. Every per-spark rigor mechanism in §18–§24 is powerless against it, because each individual spark is clean.

- Historical windows are a **budgeted resource**: track how many hypotheses have been tested against each. The budget ledger must be keyed per `(harness_version, window)`, not per version alone, or two forms tested against one window at one version cost a single unit and the multiple testing goes uncounted.
- Apply deflated-Sharpe / probability-of-backtest-overfitting corrections (Bailey & López de Prado CSCV).
- Maintain **rotating holdout windows the spark model never sees**, declared before the run and untouched until the bar is met.
- **Cross-sectional replication** partially substitutes for temporal depth: a mechanism tested across thousands of entities in one period is closer to independent evidence than overlapping walk-forward windows. This is what makes cross-entity comparability a requirement rather than a nicety (§8.1).
- **Firings are not replications.** Overlapping windows inside one regime are one observation with coverage, not several. A recurrence claim counts **disjoint epochs**, and the bar is declared before the run. Counting firings instead of epochs is how a single period's quirk gets promoted as a law.
- The same discipline applies to the meta-layer (§27).

### 17.1 Epochs

Epochs are declared before anything runs, disjoint by construction, with the most recent held out. A **core** — the invariant identity of a form, asserted to contain no floats — is promoted only when independently derived in several disjoint epochs, and the bar is declared in advance.

**Nothing crosses an epoch boundary except the core's invariant identity.** Every parameter resolves against the epoch it is applied in (§3).

### Looks are not tests

A budget ledger must record two quantities and never let one stand for the other:

- **Looks** — distinct harness versions evaluated against an epoch. Governs a
  sealed holdout's cap, because looking once is looking once. Re-running an
  unchanged harness over unchanged data costs nothing: reproduction is not
  another test, and a ledger that charged for it would punish the reproducibility
  it exists to enable.
- **Tests** — `(window, entity)` pairs actually evaluated. This is the
  multiple-testing surface a deflated-Sharpe correction consumes. One look can be
  a thousand tests, and charging one unit for the lot undercounts precisely what
  this section exists to control.

The harness version is a **content hash of the source**, not a maintained string.
The changes that matter are the ones made in response to a result, and those are
exactly the ones nobody remembers to bump a version for. Running each evaluation
in a fresh session gives reproducibility, not independence: the snooping surface
is the dataset, not the session, and a fix derived from a result leaks into the
artifact rather than the memory. The ledger is the one memory a stateless
protocol must keep.

## 18. Core pattern: artifact + kind registry

- A small **frozen core contract** — the fields the deterministic engine depends on.
- An open, **registered kind** — the shape and behaviour of everything else, declared per kind, not hardcoded.

```
Artifact {
  id
  kind
  schema_version
  embeddings: { [space_version: string]: vector }   // versioned; never compare across spaces
  attributes: {}                                     // open, shape defined by `kind`
}

Registry<K extends KindRegistration> {
  register(kind: K)      // validate-on-registration
  lookup(name) -> K
}
```

Applied to `EffectClaim`, `Evidence`, `Corroboration`, `Spark`, `InvalidationNode`, `StrategySpec`, `BasisAlignment` — each with its own **typed registry**, sharing a common base registration mechanism, kept as separate typed stores rather than one flat namespaced map.

**Why separate:** split along genuine interface differences, not naming. `EffectClaimKind.embed()/rollup()`, `CorroborationKind.check()` and `SparkKind.promotable()` are not interchangeable; a flat map lets a wrong-kind lookup succeed syntactically and fail deep inside a call. One registry when members are interchangeable; separate when they are not.

**Embedding space versioning.** Thresholds calibrated on one embedder do not transfer. Spaces are versioned in the key and never compared across versions. Use local, pinned models — a hosted embedder can change under you silently, invalidating every stored threshold with no error surfacing.

**Deliberately not extended further.** The top-level concept vocabulary stays fixed and small. Making *which concepts exist* user-definable was considered and rejected: real invariants (falsifiability, corroboration-requires-mechanism ordering, no-lookahead) would become optional data and could be quietly defined away.

## 19. Observation

### 19.1 The basis is a declared stance

The basis is the selected field set over which an observation is expressed. It is **not** an attempt at a complete description of the world, so an omission is not a silent error: mechanism, corroboration and invalidation are all expressed over the same selected points, making everything downstream commensurable with the observation by construction.

- An inadequate basis produces internally coherent theses that miss the real driver — but because the basis is a recorded artifact shared by everything downstream, this is **attributable, not silent**. Basis adequacy gets a track record (§27).
- **The basis is fixed for the lifetime of an observation.** Cancellation is only meaningful over a fixed field set.
- Basis identity governs cross-spark and **cross-epoch** comparison (§23).
- **Basis coverage** — which fields are representable at all — is tracked and grows with the graph vocabulary. "Cancelled because indistinguishable" and "not representable" are different states and must never collapse.

### 19.2 Frames

Frames are the primitive. `before / during / after` is an *interpretation* overlaid on frames once an anchor event is identified — many anomalies have no identifiable anchor, and those still get frames.

```
EffectClaimKinds["effect_claim.v4_frames"] = {
  attributes_schema: {
    basis,                                            // declared stance
    frames: [ { t, window, state_over_basis } ],      // t0..tn, declared count and spacing
    anchor?: { event_ref, t_range },
    residue:   [ { field, path, shape, separation_profile } ],
    invariant: [ field ],
    not_representable: [ field ],
    description, embedding                            // embeds residue + shape only
  },
  embed(attributes) -> vector,
  rollup(attributes) -> vector
}
```

**Pre-registration discipline:** frame count and spacing are declared when the observation slot is filled. Otherwise frame selection is a snooping surface — pick the spacing that makes the residue look strongest and you have curve-fit the observation itself.

### 19.3 Delta by cancellation, not subtraction

Text embedding spaces are not reliably linear, so `embed(final) − embed(initial)` is not a usable representation of "what changed." Instead: **cancel every field that did not change, embed only what survives.**

- Cancellation is **statistical, not equality**: a field cancels when its estimates overlap within dispersion across frames, survives when it separates in *any* frame.
- Per-field separation replaces one global number — it says *which* dimensions moved credibly.
- Path-aware by construction: a spike-and-return survives because mid-frames separate even though t0 and tn cancel. The basis should include path fields so round trips are representable.
- **Entity-resolution confidence discounts separation.** Mis-linking a mention makes a field appear to change when nothing did — residue that is really entity drift, indistinguishable from a finding.

**The invariant set is the valuable half.** One edge moving while correlated peers held invariant is a specific, localised event; the same edge moving while everything moved is a market-wide shift with no attribution. Residue cardinality against invariant cardinality is therefore a **computable specificity measure**.

**No fabricated values, ever.** Where a value cannot be honestly derived, the field is marked **not representable**, never interpolated.

### 19.4 Shape and commensurability

Residue carries a trajectory shape — monotonic ramp, step, spike-and-return, oscillation. A mechanism claiming "attention precedes appreciation as flow catches up over 3–5 days" predicts a ramp; if the residue is a step, the causal story and observed path disagree, **computably**. This is the deterministic plausibility check, at a fraction of the cost of mechanism-as-graph-path.

**Temporal commensurability.** Frame spacing is the observation's resolution, so a mechanism's horizon is structurally checkable against it. A 5-day mechanism derived from monthly-spaced frames is incoherent.

**Cadence commensurability.** A basis mixing hourly attention with quarterly filings is temporally incoherent unless the basis declares a resolution and every field is aggregated to it. Irregular streams become rate-per-window fields. Anything not expressible at that resolution is *not representable* in that basis — refused, not forward-filled.

## 20. Evidence, independence, alignment

```
Evidence {
  anomaly_event_id
  root_set                          // forward-propagated
  provenance: { description, embedding }
  effect_claim: { subject, sign, magnitude, horizon, confidence, description, embedding }
}
```

- **Provenance space** — distance answers "how independently was this measured?"
- **Effect space** — similarity answers "what outcome does this imply, and how well does it align with a prediction?"

### 20.1 Independence by forward-propagated root sets

Every event carries a `root_set` of raw source event ids at ingest; derived events union their parents' sets.

```
independence(a, b) = 1 − overlap(a.root_set, b.root_set)
```

No depth parameter, computed instantly, degrades gracefully. Two caveats in the kind: bloom false positives overstate overlap and so understate independence, which errs conservative; and root sets **saturate at depth**, so generation-distance weighting or a cap is required, or independence collapses to zero for all mature evidence.

**Three failure modes, three mechanisms.** Root sets catch shared **lineage**; provenance embeddings catch shared **method**; `couples_to` catches shared **economic driver** (§7).

### 20.2 Two-tier alignment

Embedding similarity is weak exactly on the fields that matter most. A claim about one asset rising over a week cannot corroborate a claim about another falling over a month, regardless of semantic similarity.

1. **Hard structural compatibility first** — subject, sign, horizon commensurability.
2. **Embedding similarity second**, on residual semantic content only.

### 20.3 Accumulation, not binary verdicts

Independence **weights** alignment rather than gating it — two half-independent corroborations are worth roughly one, not two-that-pass.

```
support = f(alignment) × independence_discount      // summed in log-odds
promotion requires accumulated support ≥ T
```

- Verdict artifacts are retained as the audit log, with `support_contribution` added as a score.
- **Correlation cap.** Log-odds summation assumes conditional independence given the hypothesis, and independence here is estimated from proxies. Total contribution from any correlated cluster is capped, or the design walks into ensemble overconfidence.
- **Reasoning trigger retained.** "Small support" and "genuinely ambiguous" are not the same thing; logged model reasoning at ambiguous cases is an audit artifact with independent value.
- **Support is not a probability.** It measures corroboration strength. Mapping support to a claim probability requires the calibration ledger to have data, and until it does the mapping is declared unresolved rather than assumed.

### 20.4 Directional corroboration

Corroboration drawn from the **invariant set alone supports only no-move claims**. A directional mechanism scores zero support and can never promote, so a harness with only an invariance leg can discover filters and nothing else. A directional corroboration leg is required for the design to find what it was built to find.

## 21. Spark

```
Spark {
  id, kind
  status: "open" | "complete" | "promoted" | "discarded"
  opened_at
  trigger: { graph_ref, anomaly_event }
  principles: { [name: string]: PrincipleSlot }
}

SparkKinds["spark.v1_four_principle"] = {
  principle_schema: {
    observation:    { requires: [] },                 // effect_claim.v4_frames
    mechanism:      { requires: ["observation"] },
    corroboration:  { requires: ["mechanism"] },       // ordering rule, as data
    invalidation:   { requires: [] },
  },
  promotable(principles) -> bool
}
```

Four principles: **observation, mechanism, corroboration, invalidation**. Historical precedent is deliberately excluded — a model's claimed recollection is unverified token recall; genuine precedent belongs to §16's robustness pass.

Principle set, fill ordering and promotion gate are all data, so strict and looser variants coexist as registry entries and which survives testing becomes empirical.

### 21.1 Promotion gates on specificity

Presence-only checking lets a thin generic mechanism sail through. Gate on **specificity, which is computable** where "quality" is not: tightness of `(subject, sign, magnitude, horizon)`; number of non-trivial auto-derived invalidation leaves; residue-vs-invariant cardinality; distance from a maintained library of generic-mechanism embeddings; optional bonus if expressible as a graph path.

**Specificity alone is gameable in the opposite direction** — spurious precision scores brilliantly. It only works paired with the calibration ledger (§25): specificity gates promotion, calibration punishes over-narrow claims after the fact. Neither works alone. *(This is not hypothetical: a magnitude constant written for a synthetic fixture passed the specificity gate and lost nine of nine predictions on first contact with real data.)*

A cheap **single-slot adversarial critique runs on mechanism at fill time** — the one slot where a thin entry poisons everything downstream.

### 21.2 Declared regime scope

Mechanisms may declare the regime scope under which the claim holds. A declared scope is more falsifiable than a claim that quietly only works sometimes.

**Scope must be declared before the robustness pass runs**, or a model narrows scope post hoc once it sees which windows worked, and declared scope becomes laundered curve-fitting. Unresolved tension: narrower scope is more falsifiable but has less statistical power; cross-sectional breadth is how power is bought without heterogeneity.

### 21.3 Mechanism as graph path — optional and scored

A mechanism expressed as a causal path over graph edges makes plausibility partly deterministic and makes invalidation structural: the path's edges weakening *is* the reversal condition. Kept **optional and bonus-scored**: the graph vocabulary is still growing, and requiring path-expressibility early would amputate exactly the novel hypotheses the harness exists to find.

## 22. Invalidation

```
InvalidationNode {
  id, kind
  scope: "concept" | "mechanism" | "corroboration" | "observation"
  source_ref?
  children: InvalidationNode[]
  state: "intact" | "ambiguous" | "broken"
  windows_below_threshold
}
```

Three of four child types are **auto-derived with no new model authoring**: mechanism's `predicted_effect`, each corroboration's `effect_claim`, and the observation's residue are already claims with defined shape.

### 22.1 verification_block, not contradiction

Requiring evidence to *prove the opposite* set invalidation's bar nearly as high as corroboration's confirmation bar, undoing the intended asymmetry. Corrected: does independent evidence fail to still clear the bar needed to call the claim confirmed — evidence that has merely gone flat or ambiguous counts. Applies **tree-wide**.

### 22.2 Hysteresis at the leaf, state machine at the root

- A leaf is `broken` only after N consecutive evaluation windows below threshold, `ambiguous` in between, `intact` otherwise.
- **N scales to the claim's declared horizon**, not a flat constant.

```
active      → all leaves intact
degraded    → any leaf ambiguous, or one leaf broken with others intact   → cut sizing
invalidated → mechanism broken, or ≥k legs broken                          → exit
```

This preserves "one clear disconfirmation is enough" while requiring *clear* to mean *sustained*. Honest cost: hysteresis converts false-kills into slow-kills, so a dead thesis bleeds for N windows. `degraded` must therefore cut size **aggressively, not cosmetically**.

### 22.3 Observation's invalidation kinds

Two kinds, and explicitly no persistence kind — anomaly decay is anomalies behaving normally, never thesis failure.

```
InvalidationKinds["observation_integrity.v1"]   // bad print, revision, delisting, feed gap
InvalidationKinds["delta_reality.v1"]           // re-estimate all frames on the declared longer
                                                // sample, re-run cancellation, fire if residue collapses
```

`delta_reality`'s re-estimation window is **declared when the observation is filled**, not chosen later — otherwise it is re-testing until failure.

### 22.4 Custom leaves

A `custom_condition` leaf must be authored as a full EffectClaim-shaped artifact so it has an embedding to compare, and runs through `verification_block` with independence checked against **the whole spark**. A leaf restating an existing derived node fails independence and is merged rather than padding the tree.

## 23. Basis alignment

Bases form a partial order: adding a field can only add residue entries, never remove them, so residue is monotonic in the basis. Two clean directions — project down to a shared sub-basis, or join up to a union basis.

**Tier 1 — projection onto intersection.** Compare residues on `basis_a ∩ basis_b`, report coverage. Deterministic, no model call. If both residues lie outside the intersection the verdict is `incommensurable`, never "nothing in common."

**Tier 2 — correspondence mapping.** For fields equivalent but not identically named, matched by **provenance embedding similarity + type compatibility**. Mapping confidence travels as a discount.

**Tier 3 — join and re-derive.** Both sparks' frames recomputed over the union basis with no model calls. Exact rather than approximate, and the only tier that can establish that two theses genuinely *disagree*.

> **Guardrail:** re-derivation is non-destructive and analysis-only. It produces a comparison artifact, never mutates the source spark, and never feeds that spark's own promotion. Otherwise "re-derive over a wider basis" is post-hoc basis selection.

**Polarity flips by use:** dedup wants basis *similarity*; cross-spark corroboration wants basis *distance*.

### 23.1 Where it applies

| Scope | Applies? | Why |
|---|---|---|
| **Frames within one observation** | **No — should not exist** | Frames share a basis by construction and must: cancellation needs a fixed field set. An invariant, not a gap |
| **Across sparks in one system** | **Yes** | Same vocabulary, embedding version, source set, so correspondence is mostly mechanical. Powers dedup, cross-spark corroboration via basis distance, and pre-deployment strategy-correlation estimates |
| **Across epochs in one system** | **Yes, and required** | A source outage silently changes the basis, so a replication claim compares two different things. `BasisRealization` records what each epoch could express and how well; comparison returns `same_basis` / `partial` / `incommensurable`; a core whose inputs were not expressible in every epoch is **refused, not credited**. *Did not replicate* and *was never testable* are different findings, and collapsing them turns a source outage into evidence |
| **Across systems / forks** | **No — use the prediction layer** | Different backends, vocabularies and embedding versions mean correspondence confidence is low and compounding. Honest cross-system comparison is calibration on registered, resolved predictions: **reality is the one basis every system shares** |

**The coverage floor is required with no default.** A field present in every epoch but populated in a fifth of one epoch's frames is not really shared, and a default would hide exactly the partial outage this exists to catch. Same discipline as `availability_field` in the plugin system.

## 24. Strategy formalization

```
StrategySpec {
  id, kind
  spark_ref
  status
  attributes: {}            // open, shaped by kind — entry, exit, sizing, universe
}

StrategyKinds["threshold_rule.v1"]  = { attributes_schema, compile(spark) -> attributes }
StrategyKinds["model_in_loop.v1"]   = { /* separate kind, not a fallback mode */ }
```

### 24.1 The compiled artifact is a form, not an instance

A promoted spark compiles to a **generic trade type**: conditions over basis fields and phenomena, with **no entity id, no date, and no constants** anywhere inside it, checked structurally. It fires across a universe defined by **basis coverage** rather than by name, registers a prediction per firing, and the calibration ledger scores the *form* rather than any instance.

**Keeping entity ids out is necessary and nowhere near sufficient.** A threshold derived in one window is that window's noise level; a form carrying it is a fit to its derivation window wearing a generic costume. Every parameter is a rule resolved against the window the form is applied in (§3), and an unresolvable rule raises.

### 24.2 Mapping

- **observation residue → entry trigger** — already a computable condition over the declared basis.
- **mechanism.predicted_effect → direction + target** — sign, magnitude, horizon map onto direction and holding horizon.
- **invalidation state machine → exit + sizing** — `degraded` cuts size, `invalidated` exits.
- **accumulated support → sizing input** — not a gate, but not discarded either.

Every compiled field carries provenance (`attributes.entry.derived_from = spark.principles.observation.artifact_ref`), which is what lets adversarial critique check a compiled strategy against its source claims mechanically instead of trusting a faithful translation.

**Distillation test for `model_in_loop.v1`.** Any model-in-loop strategy is benchmarked against its own compiled deterministic approximation. If it does not beat its distillation out of sample, the model contributes nothing but cost and non-determinism, and the strategy is demoted to the compiled kind.

**Spark → eligible strategy kind** via a small compatibility table, with the model choosing only among eligible entries and logging why when more than one applies.

### Checking constant-freedom

It cannot be done by type: a declared `q=0.95` and a threshold fitted to one
window are both floats. It is checked **behaviourally** — resolve the same form
against two materially different windows, and any rule-governed field that fails
to move is carrying its derivation window whatever it is named.

Since the form's core is the only thing that crosses an epoch boundary, that
check is also the **cross-epoch leak check**. The within-window leak check walks
an execution trace for decisions conditioned on unavailable information; nothing
travels between epochs except the core, so asking whether the core moved is
asking whether information from the derivation epoch travelled inside it.

## 25. Predictions and calibration

The harness is a **pre-registration system**.

```
PredictionRegistered { spark_ref, effect_claim, declared_scope, resolve_by,
                       embedding_space_version, concept_map_version }
PredictionResolved   { prediction_ref, realized_outcome, brier, calibration_bucket }
```

- At promotion, register. At horizon, resolve.
- Gives a **calibration ledger** (Brier per model, per spark kind, per basis) **independent of PnL**. PnL conflates "was the thesis right" with "was sizing and execution right"; separating them is what lets the flywheel learn which *reasoning* works.
- **Score only forward, registered, resolved predictions plus forward paper-trading. Backtests are admission, not score.** A definition changed after seeing a result, re-run on the same data, is admission — it says a correction is directionally right, never that a form works.

**The two-score diagnostic:**

| | Thesis correct | Thesis wrong |
|---|---|---|
| **Profitable** | working as designed | luck — flag, do not learn from it |
| **Unprofitable** | **expression failure** — fix the strategy layer | correctly rejected |

Bottom-left is the valuable cell and is invisible to anyone scoring on PnL alone.

**External benchmark.** Where a prediction market existed on the same resolved question, its price at registration is a benchmark the ledger scores against. Beating the market's Brier on N resolved questions is a far harder claim than a raw calibration figure, and it is the cheapest external validation available anywhere in this design.

**Consequence:** forward-only scoring means no scoreboard for weeks. The spark log itself is the early artifact.

## 26. Live monitoring and portfolio

The invalidation tree monitors the *thesis*; nothing else monitors the *strategy* once live.

- Derive an **expectation envelope** from walk-forward results; emit `StrategyDegraded` when the live trace drifts outside it. Alpha erosion and crowding show up here before the thesis is provably wrong.
- **Pre-deployment correlation:** because sparks carry embeddings and bases, strategy correlation can be estimated from spark similarity *before* allocating capital.
- A capital allocator is just another bus consumer.

## 27. The meta layer

The harness is an epistemology engine: spark = hypothesis, corroboration = independent confirmation, invalidation = falsification, testing = replication. The next step is subjecting its own components to the same discipline.

Thresholds, spark kinds, corroboration kinds, invalidation kinds, bases, concept maps and the spark model's prompt all become artifacts with track records — calibration, survival rate, false-promotion rate.

**Critical constraint:** this recreates §17's data-snooping problem one layer up. Picking the best-surviving spark kind across twenty kinds is overfitting the meta-layer. The same deflated-Sharpe and window-budget discipline must apply, or the meta-layer becomes the most sophisticated overfit in the system.

---

# PART IV — OPERATIONS

## 28. Substrate, cost, humans, reflexivity

**Substrate.** Happen (Nodes + Events on NATS, Liners as governance-as-code) is the leading candidate. Every pipeline stage is naturally an event, and a Liner is the natural place to enforce the no-lookahead guard structurally. Not yet confirmed.

**Reproducibility across sessions.** Each evaluation must run cold, in a new session with no memory, over the same pinned corpus. Two things make that meaningful: a dataset manifest pinning every file by hash, with source data never entering git and the corpus rebuilt from where it came from — a rebuild that cannot be proved identical is a different dataset wearing the same name; and a budget ledger, which is the one memory a stateless protocol must keep, keyed on a content hash of the harness source so a changed version costs budget whether or not anyone remembers the earlier run.

**Inference cost is a design constraint.** Several mechanisms increase per-spark cost (specificity scoring, mechanism-fill critique, adversarial passes, relationship extraction). Cost-reducing choices already made: three of four invalidation leaves auto-derived; critique on mechanism only; cancellation and separation fully deterministic; baseline legs computed from graph state; extraction cached on content hash.

**Human-in-the-loop.** A human session is another consumer on the same bus. The gates are calibrated for *unattended* runs and can make a co-pilot session feel bureaucratic, so a human can **override a gate, with the override recorded as an artifact** carrying its own track record — neither bypassing rigor silently nor being blocked by it. The human's own overrides accumulate a calibration record on the same terms as any kind.

**Reflexivity is operational, not theoretical.** Publication is itself an invalidation channel: the more visible a thesis, the faster it decays. Acceptable *if the product is the harness rather than the alpha*, which is the current stance — but a decision made explicitly rather than discovered later. A `crowdedness` graph node would let it be modelled rather than ignored.

## 29. Implementation state

**Tracked separately from the spec on purpose.** Rewriting the spec to describe what is built would quietly lower the bar. These are gaps, not corrections.

> The table below is a **snapshot at v4**. The living version is
> [`STATE.md`](STATE.md), which is dated and updated after every run. Where the
> two disagree, `STATE.md` is current — and the discrepancy is itself the drift
> this section exists to surface.

### Blocking the headline question

| Gap | Consequence | Rank |
|---|---|---|
| **Promotion rate is a property of the epoch, not the market** | Found by run 003 (report 004): over 20 null runs, one epoch promoted 0 while another promoted 39 — on markets with no structure. Cross-epoch promotion counts are therefore not comparable, so a replication bar does not mean what it appears to even when a core clears it. **This invalidates the replication machinery itself** and precedes everything else | 1 |
| Mechanism slot filled from a hand-written template library, not a model | The central claim — that a model devises its own strategies — is **untested**. Rejections are informative about the data; acceptances are not informative about the world | 2 |
| Corroboration from the invariant set only (§20.4) | Every core is `neutral` by construction. The harness can discover filters and nothing else | 3 |
| Window budgeting / deflated Sharpe not started | Named the largest risk; overlapping windows against one history. The ledger now records the denominator (§17) but no correction consumes it | 4 |

### Data layer

Fact model, status enum, EDGAR revision chains and `as_of` work against live data; no persistent store, and the concept map is a tag-precedence tuple rather than a published versioned artifact with measured coverage · Wikimedia, FINRA, GDELT done; ALFRED and the press wires absent · entity spine **minimal** (hand-written entities, no PIT ticker resolution, no relationship extraction — which blocks entity→entity edges and the graph-path bonus) · cross-reference, relation registry and event spine not started · prediction markets fixture-only · conformance suite exists, declarative loader does not · API, determinism receipt and MCP not started · **recorders not started, and they are the only item with a clock on them**.

### Harness

Bus, guard, ordering, root sets and manifest done · graph and anomaly detection done but thin · observation done · spark slots partial (see rank 1) · compile, execution and leak check done · real-vs-null done, with the tolerance derived from the null's own distribution · prediction registration and calibration ledger done · hysteresis and state machine done · specificity computed but the floor is a bootstrap value and there is no critique pass · basis alignment, regime scoping, strategy decay and the planted-effect suite not started.

### Known measurement weaknesses

Entity resolution by text query at low declared confidence, discounting every separation it feeds · fundamentals contributing nothing where quarterly filings meet a weekly basis, correctly refused rather than forward-filled · third-party search APIs that truncate by recency and would manufacture a spike at every window boundary unless chunked with a raise on truncation.

## 30. Open issues

Roughly in blocking order:

- **A directional corroboration leg** — without it, only filters can ever promote.
- **Mechanism discovery** — the template library is hand-written, so the search space is whatever was imagined in advance.
- **Window budgeting.** The ledger now separates looks from tests (§17), so a correction has a denominator; the correction itself is not built.
- **Epoch comparability.** Promotion rates differ by an order of magnitude across epochs *on null data* (§29). Until diagnosed, cross-epoch counts cannot be compared and the replication bar is not meaningful. Candidates: coverage differences feeding the invariant set, volatility differences feeding the vol-relative magnitude, per-epoch tolerance.
- **Root-set saturation bound** — generation-distance weighting vs a hard cap.
- **`k` in the invalidation state machine** and the `degraded` sizing multiplier, both unset.
- **Hysteresis N as a fraction of horizon** — the fraction is unset and controls the false-kill / slow-kill trade.
- **Correlation-cluster cap method** — by embedding space, by `couples_to` graph, or by root-set overlap.
- **Support → probability mapping** — unresolved until the ledger has enough rows.
- **Specificity floor calibration** — cannot be set correctly until the system has run; bootstrap value in use.
- **Regime scope tension** — narrower is more falsifiable and less testable. No resolution.
- **Concept map governance** — who decides tag precedence, when a version invalidates prior comparisons, what coverage floor makes a peer group usable.
- **Basis vocabulary growth process** — who decides a field is missing, and when a new field version invalidates prior comparisons.
- ~~**Coverage floor value**~~ — now declared on the epoch set and recorded with the protocol, so it travels with any result quoting it.
- **`compile()` completeness** — which residue shapes are expressible as deterministic predicates, and what happens to those that are not.
- **Custom extension tag coverage** — the XBRL APIs exclude non-standard taxonomies; the fallback path is not built.
- **More epochs.** Three derivation epochs at six entities is a small sample for a recurrence claim in either direction. Absence of replication is weak evidence of absence.
- Human co-pilot session and spark-log presentation not designed.
- Whether Happen is the confirmed substrate.
