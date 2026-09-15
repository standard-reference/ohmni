# Build Plan — Two Subprojects, One Contract

*Companion to `01-system-specification-v3.md` (harness design), `03-data-sources.md`, `04-data-product-design.md` and `05-cross-reference-layer.md` (data product design). Personal build; licences change when either ships.*

---

## 0. The split

Two products, built alongside each other, coupled only through a narrow shared contract:

- **Data layer** — ingestion, point-in-time semantics, the fact format, cross-reference, the API. Standalone product. Any consumer can use it.
- **Harness** — graph, observation, spark, strategy, testing, calibration. Consumes *a* data layer through the contract, not *the* data layer.

The goal is not two folders. It's that the harness never imports from the data layer's internals, and the data layer never knows the harness exists.

```
/contract          # shared port — both depend on this, neither on each other
  record.py        # neutral fact shape
  declaration.py   # SourceDeclaration: provenance, coupling, cadence, retrieval
  protocol.py      # DataLayer protocol
  capability.py    # capability tiers + degraded-mode reporting

/data-layer        # the product
  core/            # fact model, status enum, revision chains, concept maps
  adapters/        # edgar, alfred, gdelt, wikimedia, wires, prediction markets, social
  plugins/         # declarative loader + conformance suite
  xref/            # spines, event clustering, field algebra, /relate, /panel
  api/             # REST + MCP (as_of mandatory)
  store/           # raw + normalized parquet, duckdb catalog

/harness
  bus/             # sim-clock, lookahead guard, ordering
  graph/           # nodes, edges, deterministic anomaly detection
  observation/     # basis, frames, cancellation
  spark/           # principles, corroboration, invalidation
  strategy/        # compile, execution, portfolio
  testing/         # nulls, leak check, robustness, adversarial
  calibration/     # prediction registration + ledger

/fixtures          # a hand-built DataLayer implementation — see §3
```

`/contract` as its own package is what makes this real rather than nominal. Both sides depend on it; neither depends on the other.

---

## 1. The contract

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
    value: dict                  # shape by kind
    status: Status               # reported | derived | not_representable | ...
    source_id: str
    lineage: Lineage             # originating document, derivation inputs
    revision: Revision | None    # index, chain length, superseded_at
```

`SourceDeclaration` carries, alongside `retrieval` and `record_survivorship`:

```python
historical_access: "bulk" | "metered" | "rate_limited" | "record_only"
bulk_endpoint: str | None
```

`retrieval` says whether a historical query returns historical values. This says
whether the history can be **fetched at scale**, which is a different question and
the one that decides whether a source can serve a multi-epoch basis at all. The
check it enables: **a multi-epoch basis cannot rest on a source whose history
cannot be fetched at scale**, refused before the first request rather than three
hours into a fetch, when the epochs already have different bases.

`RunManifest` records per-source retrieval outcome and folds `unavailable_sources`
into `event_set_hash`; it also records *looks* and *tests* separately per epoch
(§ harness), since one look can be many hundred tests.

**What deliberately isn't in the contract:** `root_set`, `basis`, `frames`, `EffectClaim`, `spark`. The data layer emits lineage; the harness *derives* root sets from it. Lineage is a general primitive; root sets are one consumer's interpretation. Keeping that line is what lets the data layer serve a stock screener as happily as it serves this.

### The guard exists on both sides, with different threat models

Earlier reasoning said the sim-clock guard belongs to the data product. That's half right, and the resolution matters:

- **Data layer guard:** `as_of` is a required parameter, so the API structurally cannot serve future values *to any consumer*. This is what makes "backtest-safe by construction" a product claim.
- **Harness guard:** the bus enforces ordering and raises on any query past `now()`. This holds *even against a data layer that has no guard at all*.

Not redundancy — defence in depth against different failures. The harness must not trust the data layer to be correct, which is the same principle applied throughout the design: never trust what you can structurally enforce. It's also precisely what lets the harness accept a sloppier data layer (yfinance, a CSV) without silently losing its guarantees.

### Capability tiers and degraded-mode recording

A data layer that provides less doesn't fail — the harness degrades in *known, recorded* ways.

| Capability | Without it | Harness behaviour |
|---|---|---|
| `knowable_at` on every record | No gating possible at all | **Refuse to run.** Not degradable |
| Typed `status` | Gaps are untyped nulls | Run, flag: not-representable and not-disclosed collapse |
| `revision` chains | Restatement lookahead undetectable | Run, **mark the run contaminated** in the manifest |
| `measurement_process` prose | No provenance embedding | Corroboration by independence unavailable (§9) |
| `derived_from` / `couples_to` | Shared lineage and coupling invisible | Independence over-estimated; correlation cap disabled |
| `native_cadence` | Basis resolution uncheckable | Cadence commensurability check skipped (§8.4) |
| Cross-reference (`/relate`, event spine) | No declared relations | Mechanism-as-graph-path bonus unavailable (§10.3) |

`CapabilitySet` is declared by the layer and copied into the run manifest, so a run against a degraded layer is *labelled* rather than quietly weaker. That's the same discipline as declaring a basis: the limitation is recorded and attributable, never silent.

### Version pinning across the seam

`event_set_hash` now spans two independently-versioned products. The manifest carries `layer_id`, `layer_version`, `contract_version`, and the layer's own `concept_map_version` / `cluster_version` — or a data-layer upgrade silently changes replay results.

---

## 2. Track A — the data layer

| Stage | Content | Models | Bar |
|---|---|---|---|
| **A1** | Fact model, status enum, store, EDGAR fundamentals: revision chains, as-of, concept maps | none | As-of correct both sides of a restatement; Q4 absent not computed; coverage measured |
| **A2** | Remaining deterministic adapters: ALFRED (vintaged), GDELT, Wikimedia, wires, FINRA | none | Every source declares full provenance; lag and cadence justified per event type |
| **A3** | Entity spine, enrichers, relationship extraction | pinned, cached | PIT ticker resolution correct; 8-K recall/precision floor met; duplicates collapse |
| **A4** | Cross-reference: join spines, as-of join, field algebra, `/panel` | none | Period-joins structurally unavailable; upsampling refused; every joined value declares its join |
| **A5** | Relation registry (calc + presentation linkbases), `/relate`, phenomenon groups | none | Validity matrix derived from metadata; `no_shared_data` never collapses into `incommensurable` |
| **A6** | Event spine tiers 1–2 | none | `first_knowable_at` correct across sources; tier-2 window declared not tuned |
| **A7** | Prediction markets: contract / quote / resolution | none | Criterion versioning works; dispute chain behaves like a restatement |
| **A8** | Plugin system: declarative loader + conformance suite | none | A plugin that fetches inside `normalize` is rejected; one missing `availability_field` fails registration |
| **A9** | API surface, determinism receipt, MCP with mandatory `as_of` | none | Identical query + versions → identical `response_hash`, provable via public replay |
| **A10** | Social adapter + recorders | none | Engagement facts are recorder-only; historical `as_of` against a snapshot stream refuses with a reason |

Detailed build tickets for A1 and A3 are the former Parts 1B and 1C — unchanged in substance, see the git history of this doc or `04-data-product-design.md` §5 and §7c.

**Out of band, starting immediately:** the recorders. Bluesky, Farcaster and StockTwits have no purchasable archive at any price; prediction-market quotes and crypto derivatives state are only partially recoverable. This is the one thing in either track with a deadline.

---

## 3. The fixture layer — how modularity gets enforced

Before the harness reads a single real record, build `/fixtures` — a hand-written `DataLayer` implementation over a small, internally-consistent synthetic dataset: a few entities, a real-looking revision chain, one known restatement, deliberate typed gaps, one pair of sources with shared lineage and one genuinely independent pair.

Three reasons this is not optional:

1. **It makes the contract real.** An interface with one implementation is a guess. Two implementations is a contract. The fixture layer is the second consumer that keeps the abstraction honest.
2. **It's a better test substrate than real data.** Parts B1–B3 need ground truth — "this field moved and no other did" — which real data cannot give you.
3. **It unblocks parallelism.** The harness track never waits on the data track.

Enforce it in CI: the harness test suite runs against the fixture layer only. If a harness test needs the real data layer, something has leaked across the seam.

---

## 4. Track B — the harness

| Stage | Content | Models | Bar |
|---|---|---|---|
| **B0** | Bus: sim-clock, lookahead guard, ordering, Record→Event mapping, root-set derivation, nulls, manifest | none | Adversarial peek fails by every route; runs hash-reproducible; nulls destroy cross-stream structure |
| **B1** | Market graph: five node types, entity→entity edges, deterministic anomaly detection | none | Anomaly rate on nulls matches the threshold's expected false-positive rate |
| **B2** | Observation: basis declaration, frames, cancellation, residue / invariant / not-representable | none | Hand-moved field in residue, all others in invariant; resolution confidence discounts separation; cadence commensurability enforced |
| **B3** | Spark slots: mechanism + invalidation (corroboration deferred), root sets, two-tier alignment | generative | Mechanisms structurally valid and horizon-commensurable; independence fixtures score correctly |
| **B4** | `compile()` → `threshold_rule.v1`, execution, leak check | none | Compiled entry matches source residue mechanically; leak check clean |
| **B5** | Real vs null comparison — **the actual first question** | generative | Coherent strategies on real data, measurably fewer or weaker on nulls |

**B0 belongs to the harness, not the data layer.** It's the client-side guard from §1, plus the mapping from neutral `Record` to harness `Event` (where root sets get derived from lineage). Keeping it harness-side is what makes "accepts any data layer" true.

**Independence fixtures for B3** — the three cases the fixture layer must contain:

- price ↔ EDGAR: disjoint lineage, distant provenance → independence ≈ 1
- news ↔ derived sentiment: shared lineage → independence ≈ 0
- options ↔ spot: disjoint lineage, distant provenance, **declared coupling** → caught by `couples_to`, not by either embedding

The third is the one that fails silently if `couples_to` isn't wired through the contract.

### After B5, in order

1. Prediction registration + calibration ledger — cheap, and the flywheel needs it accumulating from day one
2. Hysteresis + thesis state machine
3. Specificity floor + mechanism-fill critique
4. Deflated Sharpe + window budgeting
5. Corroboration proper
6. Basis alignment operator (tiers 1–2 first)
7. Regime scoping
8. Strategy decay + portfolio layer
9. Planted-effect synthetic suite
10. Mechanism-as-graph-path — the big refactor, once the fixed-concept version has run

---

## 5. Interleaving the two tracks

The tracks are independent except at four points. Everything else can proceed in parallel or in whatever order holds attention.

```
A1 ──────────────────────────────┐
                                  │
Fixtures ──► B0 ──► B1 ──► B2 ──► B3 ──► B4 ──► B5
                                  ▲       ▲
A2, A3 ───────────────────────────┘       │
A4, A5, A6 ───────────────────────────────┘
```

| Dependency | Why |
|---|---|
| Fixtures → B0 | The bus needs *a* DataLayer, and it should not be the real one |
| A1 → B3 | Generative sparks over fixtures are a shape test; real fundamentals make them meaningful |
| A3 → B1 | Entity→entity edges need relationship extraction, or the graph is price looking at itself |
| A4–A6 → B4 | Aligned panels and declared relations make `compile()` and the graph-path bonus possible |

A7–A10 (prediction markets, plugins, API, social) have **no harness dependency at all** — they're product surface. Build them when the product needs them, not when the harness does.

**Recommended sequence for a solo builder:** fixtures → B0 → A1 → B1 → B2 → A3 → B3 → B4 → B5, with the recorders running in the background from day one and A4–A10 slotted in wherever the product needs them.

That ordering front-loads the two things that are provable rather than judged — the guard and as-of correctness — and reaches B5, the question the whole project exists to answer, without building the product surface first.

---

## 6. What each track can ship alone

Worth checking periodically, because it's the test of whether the split held:

**Data layer, shipped alone:** a point-in-time financial data API with typed gaps, revision chains, declared cross-reference algebra, a plugin system, and a determinism receipt. Sellable with no harness.

**Harness, shipped alone:** a strategy-discovery research system that runs on any conforming data layer — including a CSV adapter someone writes in an afternoon. Its value is the epistemology, not the data.

If at any point one cannot be described without the other, the seam has leaked.

---

## 7. Deferred deliberately

- **Standardized commercial fundamentals** — buy only if concept-map coverage proves inadequate for the peer groups that matter (A1 measures this, so the decision becomes evidential)
- **Price provider purchase** — needed at B4, not before; scored runs need survivorship-free prices with correct corporate actions
- **Microstructure / L2** — Databento free credits, only if a short-horizon mechanism appears
- **Pre-2009 fundamentals** — regime heterogeneity argues against; cross-sectional breadth substitutes for the power
- **Non-US coverage**, **earnings call transcripts**, **paid news enrichment**
- **The general-domain harness** — still a declared non-goal
