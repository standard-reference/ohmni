# Agentic Finance Harness — System Specification v3

*Living design document. v3 as of September 12, 2026. Supersedes v2. Companion documents: `02-build-plan-and-parts.md` (build plan and the data-layer contract), `03-data-sources.md`, `04-data-product-design.md` and `05-cross-reference-layer.md` (the data layer, built as a separate product).*

---

## 1. Vision & Scope

A harness in which AI models generate, test, and refine their own trading/investment strategies — a research environment for strategy *discovery*. The model is the reasoning core; the harness's job is to let it originate and defend hypotheses under structural discipline.

Philosophically distinct from the separate financial-market-model project, where the LLM is deliberately kept at the boundary (sourcing data, not reasoning). Here the model reasons and deterministic code verifies.

### Declared non-goals

- **Open source, for now.** Personal build. The licensing constraints that shaped earlier drafts are gone. One discipline keeps the option free at zero cost: never let source data into git.
- **A general-purpose domain-agnostic hypothesis harness.** The artifact+kind engine (§7) is domain-agnostic by construction, so generalising later is cheap — but finance is the deliberate first domain because it gives fast, adversarial, externally-scored resolution. Recorded as a non-goal specifically to prevent drift into it.
- **Profitability, as the first bar.** The first bar is *coherence*: can the pipeline generate a defensible strategy over a data stream at all. Winner or not is a later question.

---

## 2. Core Pipeline

The first two stages belong to the **data layer**, a separate product consumed through a contract (§4.1). Everything below the line is the harness.

```
Data streams (historical + live)          ┐
        ↓                                  │ data layer
Entity resolution + enrichment             ┘ (pinned models)
 ─────────────────────────────────────────── contract
        ↓
Market graph (deterministic analytics)
        ↓
Observation: frames over a declared basis → delta by cancellation
        ↓
Spark: mechanism, corroboration, invalidation
        ↓
Formalizer (spark → structured strategy spec)
        ↓
Execution engine (event-driven backtest / live, shared)
        ↓
Testing (null control, leak check, robustness, adversarial)
        ↓
Prediction registration → resolution → calibration ledger
        ↓
Spark log / human session
```

---

## 3. Market Graph

```
Node { id, type: "asset" | "entity" | "narrative" | "factor" | "regime",
       label, attributes{}, last_updated }

Edge { id, source, target,
       type: "correlation" | "sentiment_link" | "mention" | "lead_lag" | "flow"
           | "partnership" | "supplier" | "customer" | "ownership",
       weight, dispersion, weight_history[], last_updated }
```

Deterministic code — never the model — computes correlation shifts, centrality changes, community reshuffling, and anomaly detection, emitting anomaly events on threshold crossings. The model interprets and prioritises; it never does arithmetic.

- `regime` is a first-class node type so mechanisms can declare scope (§10.2).
- `entity` nodes and **entity→entity relationship edges** are what make §10.3's causal paths expressible. Without them, every basis is price looking at itself.
- Node/edge vocabulary is explicitly **illustrative and growing**. It expands when the harness finds things it cannot express; that expansion is tracked (§8.1, basis coverage).

---

## 4. Execution Engine

Event-driven, not a fixed CSV backtest.

- Every source, historical or live, normalises into the same event types pushed through one bus in timestamp order.
- **A sim-clock gates the bus.** A strategy sees only events up to "now" in replay time, enforced structurally at the bus (a Liner-style guard), not trusted to model discipline.
- Strategies consume events and emit decisions; the engine tracks a virtual portfolio (fills, slippage, costs) plus a full audit trail — every decision and the exact events it was conditioned on.
- Event-sourced, so the same engine is the live/paper path later. No second implementation.

**Two timestamps, always gated on availability.** `event_time` is when a thing happened; `available_time` is when it became knowable. A 1h bar stamped 14:00 isn't knowable until 15:00; a 10-Q's period end precedes its filing by weeks; a GDP print is revised for years. Gating on the wrong one produces silently optimistic backtests with no error anywhere.

**Decision latency.** In replay, model inference is instantaneous relative to sim-time; live it takes seconds to minutes. Decisions are stamped at `event_time + modeled_inference_delay`, or backtests are systematically optimistic.

**Replay determinism.** Every model output is recorded as an event keyed by `(prompt_hash, event_set_hash, model_id, embedding_space_version, concept_map_version)`, so replays are reproducible and critique can re-run against exact conditioning.

**Hard rule: no model or agent calls a data API directly.** Every byte reaches reasoning through the bus. A hosted MCP data server queried inside a replay reads present-day values at sim-time 2019, and no guard can see it because the data never passes through the bus.

### 4.1 The data layer boundary

Ingestion is a **separate product**, consumed through a narrow contract (`02-build-plan-and-parts.md` §1). The harness depends on the contract, never on a particular data layer's internals — so it runs equally on the companion data product, on a CSV adapter, or on anything else that conforms.

The data layer supplies neutral `Record`s: value, period, `knowable_at`, typed status, lineage, revision chain. The harness maps those into `Event`s and **derives root sets from lineage on its own side**. Lineage is a general primitive; root sets are this consumer's interpretation, and keeping that line is what stops the harness's vocabulary leaking into a product that should also serve a stock screener.

**The guard exists on both sides of the seam, against different failures.** A well-built data layer makes `as_of` mandatory, so it cannot serve future values to *any* consumer. The harness's bus guard holds regardless — including against a data layer with no guard at all. The harness never trusts the data layer to be correct, which is the same principle it applies everywhere else.

**Source availability is itself point-in-time.** A source reachable yesterday may be unavailable today, and an absent source silently changes the realized basis. Per-source retrieval outcome is recorded in the run manifest and folded into `event_set_hash`, so a run missing a source cannot hash the same as one that had it.

**Capability degradation is declared, never silent.** A data layer publishes what it supports, and the run manifest records it. Missing revision chains means restatement lookahead is undetectable, so the run is **marked contaminated** rather than quietly weaker; missing `measurement_process` prose disables independence-based corroboration (§9); missing `native_cadence` disables the commensurability check (§8.4). Only one capability is non-negotiable: without `knowable_at` on every record there is nothing to gate on, and the harness refuses to run.

---

## 5. Testing — Four Passes

1. **Null control (runs first).** Bootstrapped / shuffled markets with no real structure. If the pipeline promotes anything here, false-discovery control is broken and every downstream result is meaningless. Cheap, so it runs before anything else. **The detection tolerance is *derived from* the null rather than checked against it:** a movement threshold set at the null distribution's own 95th percentile arrives with a measured false-positive rate instead of a preference, and transfers across regimes where a constant does not. Nulls must preserve what the mechanism does not claim — a block bootstrap keeps fat tails and volatility clustering and destroys only the arrangement — or the control is too easy to beat. **The null also tests the protocol's whole output distribution, not just single sparks:** every per-spark mechanism can be working correctly while the rate of promotions is indistinguishable from noise, and only running the entire protocol over structureless data will show it.
2. **Leak check (mechanical).** Walk the audit trail for any decision conditioned on information not yet available at its sim-time.
3. **Robustness (deterministic).** Walk-forward across regimes, parameter sensitivity, comparison against dumb baselines (buy-and-hold, MA crossover). Genuine historical precedent lives here — a real point-in-time replay, never a model's claimed recollection. Where a mechanism declared a regime scope, this checks *that declared scope* rather than fishing.
4. **Adversarial critique (LLM).** A second model attacks the causal story: plausible mechanism, likely coincidence, regime fragility.

Execution and testing are decoupled — testing consumes only an execution trace, so either can be swapped independently.

**Planted-effect suite (later).** Synthetic markets with a known injected mechanism, to measure recall. Deferred: realistic synthetic microstructure is its own project, whereas nulls are nearly free.

---

## 6. Data Snooping — Budgeted Windows

The largest risk in the design. Thousands of sparks against the same history means some pass walk-forward by chance, and any ranking on backtests selects precisely for those. Every per-spark rigor mechanism in §8–§11 is powerless against it, because each individual spark is clean.

- Historical windows are a **budgeted resource**: track how many hypotheses have been tested against each.
- Apply deflated-Sharpe / probability-of-backtest-overfitting corrections (Bailey & López de Prado CSCV).
- Maintain **rotating holdout windows the spark model never sees**.
- **Cross-sectional replication** partially substitutes for temporal depth: a mechanism tested across thousands of entities in one period is closer to independent evidence than overlapping walk-forward windows. This is what makes cross-entity comparability a requirement rather than a nicety (§8.5).
- **Firings are not replications.** Overlapping windows inside one regime are one observation with wide coverage, not many independent tests: the windows share data and the regime is shared. A recurrence claim counts **disjoint epochs**, and the bar is declared before the run. This does not budget windows, but it stops a single period's artefact reaching promotion — and the budget ledger must record *looks* (distinct harness versions) and *tests* ((window, entity) pairs) separately, because one look can be a hundred and sixty tests and charging one unit for the lot undercounts exactly the multiple testing this section exists to control.
- The same discipline applies to the meta-layer (§16).

---

## 7. Core Pattern: Artifact + Kind Registry

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

**Why separate:** split along genuine interface differences, not naming. `EffectClaimKind.embed()/rollup()`, `CorroborationKind.check()`, and `SparkKind.promotable()` are not interchangeable; a flat map lets a wrong-kind lookup succeed syntactically and fail deep inside a call. Validated against Better Auth's plugin architecture, which correctly uses *one* flat `plugins[]` array precisely because every plugin shares one identical interface. One registry when members are interchangeable; separate when they are not. Neither is a universal default.

**Embedding space versioning.** Thresholds calibrated on one embedder do not transfer. Spaces are versioned in the key and never compared across versions. Use local, pinned models — a hosted embedder can change under you silently, which would invalidate every stored threshold with no error surfacing.

**Deliberately not extended further.** The top-level concept vocabulary (Evidence, EffectClaim, Corroboration, Spark, Invalidation, Strategy) stays fixed and small. Making *which concepts exist* user-definable was considered and rejected: real invariants (falsifiability, corroboration-requires-mechanism ordering, no-lookahead) would become optional data and could be quietly defined away. A declarative concept manifest was noted as a possible middle ground, deferred until the fixed version has run for a while.

> This rule is why the observation delta is **not** a new concept — it is an `EffectClaim` kind (§8).

---

## 8. Observation — Basis, Frames, Delta by Cancellation

### 8.1 The basis is a declared stance

The basis is the selected field set over which an observation is expressed. It is **not** an attempt at a complete description of the world, so an omission is not a silent error: mechanism, corroboration, and invalidation are all expressed over the same selected points, making everything downstream commensurable with the observation by construction.

Consequences:

- An inadequate basis produces internally coherent theses that miss the real driver — but because the basis is a recorded artifact shared by everything downstream, this is **attributable, not silent**. Basis adequacy gets a track record (§16) and becomes empirically measurable.
- **The basis is fixed for the lifetime of an observation.** Cancellation is only meaningful over a fixed field set; a mid-observation basis change makes residue and invariant incoherent. No "improving" an observation by extending its basis mid-flight.
- Basis identity governs cross-spark comparison, as embedding-space version does (§12).
- **Basis coverage** — which fields are representable at all — is tracked and grows with the graph vocabulary. "Cancelled because indistinguishable" and "not representable" are different states and must never collapse into one.

### 8.2 Frames

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

**Pre-registration discipline:** frame count and spacing are declared when the observation slot is filled, before anything downstream. Otherwise frame selection is a snooping surface — pick the spacing that makes the residue look strongest and you have curve-fit the observation itself.

### 8.3 Delta by cancellation, not subtraction

Text embedding spaces are not reliably linear, so `embed(final) − embed(initial)` is not a usable representation of "what changed." Instead: **cancel every field that did not change, embed only what survives.**

- Cancellation is **statistical, not equality**: a field cancels when its estimates overlap within dispersion across frames, survives when it separates in *any* frame.
- Per-field separation replaces one global number — it says *which* dimensions moved credibly.
- Path-aware by construction: a spike-and-return survives because mid-frames separate even though t0 and tn cancel. The basis should include path fields (max excursion, sign changes) so round trips are representable.
- **Entity-resolution confidence discounts separation.** Mis-linking a mention makes a field appear to change when nothing did — residue that is really entity drift, indistinguishable from a finding. Resolution confidence must reach this computation, not sit in a log.

**The invariant set is the valuable half.** One edge moving while correlated peers held invariant is a specific, localised event; the same edge moving while everything moved is a market-wide shift with no attribution. Residue cardinality against invariant cardinality is therefore a **computable specificity measure**, feeding §10.1 directly.

**No fabricated values, ever.** A derived value nobody observed reads as a field changing when nothing happened, manufacturing residue — the exact failure `delta_reality` exists to catch. Where a value cannot be honestly derived (see the Q4 case in the build doc), the field is marked **not representable**, never interpolated.

### 8.4 Shape as a deterministic plausibility check

Residue carries a trajectory shape — monotonic ramp, step, spike-and-return, oscillation. A mechanism claiming "attention precedes appreciation as flow catches up over 3–5 days" predicts a ramp; if the residue is a step, the causal story and observed path disagree, **computably**. This is "never let a model self-report what a computation could verify" applied to mechanism plausibility, at a fraction of the cost of mechanism-as-graph-path (§10.3).

**Temporal commensurability.** Frame spacing is the observation's resolution, so a mechanism's horizon can be structurally checked against it. A 5-day mechanism derived from monthly-spaced frames is incoherent.

**Cadence commensurability.** A basis mixing hourly attention with quarterly filings and irregular approvals is temporally incoherent unless the basis declares a resolution and every field is aggregated to it. Irregular streams become rate-per-window fields. Anything not expressible at that resolution is *not representable* in that basis.

### 8.5 Concept maps — cross-entity comparability as a declared artifact

Cross-entity fundamentals comparison is **required**, not optional: §6's cross-sectional replication argument is itself a cross-entity claim, most real fundamental mechanisms are relative (valuation against sector, growth against peers), and "peers didn't move" corroboration is inherently cross-entity.

It is handled the same way as the basis — by declaration, not by hoping:

```
ConceptMap {
  version                 // pinned; in the manifest; changes bump event_set_hash
  concept                 // "revenue"
  tag_precedence: [...]   // ordered source tags
  peer_group_scope        // which industry groups this mapping is valid within
  coverage: {entity: bool}  // measured, not assumed
}
```

Comparison is then **valid within a declared concept map and peer group, with measured coverage** — neither silently universal nor unsupported.

Two distinct problems, only one of which standardization solves:

- **Tag variation** (several source tags for one concept) is a finite, known set — a lookup table with precedence order. Solvable.
- **Industry incomparability** (a bank's revenue is interest income plus fees; a manufacturer's is product sales) is *not* a standardization problem. No vendor fixes it. It needs peer-group scoping and declaration.

§12's basis-alignment logic extends naturally: two entities are comparable when they share a concept map and peer group, exactly as two sparks are comparable when they share a basis.

---

## 9. Evidence, Independence & Alignment

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

### 9.1 Independence by forward-propagated root sets

Every event carries a `root_set` of raw source event ids at ingest; derived events union their parents' sets.

```
independence(a, b) = 1 − overlap(a.root_set, b.root_set)
```

No depth parameter, computed instantly, degrades gracefully — partial overlap becomes a partial discount feeding §9.3. Replaces backward ancestry tracing, which had an undefined depth bound.

Two caveats written into the kind:
- Bloom false positives overstate overlap, understating independence — errs conservative, the right direction.
- Root sets **saturate at depth** (everything traces back to "the market"), so generation-distance weighting or a cap is required, or independence collapses to zero for all mature evidence. *(Open — §18.)*

**Three failure modes, three mechanisms.** Root sets catch shared **lineage**. Provenance embeddings catch shared **method**. Neither catches shared **economic driver** — options and spot on one underlying have disjoint lineage and distant provenance yet are mechanically coupled through delta. So every source declares `couples_to: [(source_id, strength)]`, a known structural fact rather than an estimate, and §9.3's correlation cap keys off it.

**Coupling is declared per instrument, not only per source.** Source-level `couples_to` is too coarse where one source carries contracts with different exposures: a prediction market on "AAPL above $200" is delta-coupled to AAPL spot, while one on "Fed cuts in March" is coupled to rates and to no equity at all. Where a source's instruments differ in what they're coupled to, the declaration lives on the instrument.

**Backfill is the alt-data equivalent of restatement.** A signal sold "with history to 2015", computed by running today's methodology over archived inputs, never existed as a live signal — the same contamination as scoring 2019 articles with a 2026 model. Every source declares `backfilled: bool`.

**Survivorship applies to records, not just entities.** Deleted records absent from a backfill bias history in the same way delisted tickers do, and often worse: deleted social posts skew disproportionately toward wrong calls and retracted claims, so a historical pull systematically over-represents what nobody regretted. Every source declares whether removed records are recoverable.

### 9.2 Two-tier alignment

Embedding similarity is weak exactly on the fields that matter most. A claim about one asset rising over a week cannot corroborate a claim about another falling over a month, regardless of semantic similarity.

1. **Hard structural compatibility first** — subject, sign, horizon commensurability.
2. **Embedding similarity second**, on residual semantic content only.

### 9.3 Evidence accumulation, not binary verdicts

Independence **weights** alignment rather than gating it — two half-independent corroborations are worth roughly one, not two-that-pass.

```
support = f(alignment) × independence_discount      // summed in log-odds
promotion requires accumulated support ≥ T
```

- Verdict artifacts are retained (they are the audit log), with `support_contribution` added as a score.
- **Correlation cap.** Log-odds summation assumes conditional independence given the hypothesis, and independence here is estimated from proxies. Total contribution from any correlated cluster is capped, or the design walks into classic ensemble overconfidence.
- **Reasoning trigger retained.** "Small support" and "genuinely ambiguous" are not the same thing; logged model reasoning at ambiguous cases is an audit artifact with independent value.

---

## 10. Spark

```
Spark {
  id, kind
  status: "open" | "complete" | "promoted" | "discarded"
  opened_at
  trigger: { graph_ref, anomaly_event }
  principles: { [name: string]: PrincipleSlot }
}

PrincipleSlot { filled, artifact_ref }

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

Four principles: **observation, mechanism, corroboration, invalidation**. Historical precedent is deliberately excluded — a model's claimed recollection is unverified token recall; genuine precedent belongs to §5's robustness pass, which runs a real point-in-time replay.

Principle set, fill ordering, and promotion gate are all data, so strict and looser variants coexist as registry entries and which survives testing becomes empirical rather than a one-time design choice.

### 10.1 Promotion gates on specificity, not "filled"

Presence-only checking let a thin generic mechanism sail through. Gate on **specificity, which is computable** where "quality" is not:

- tightness of `(subject, sign, magnitude, horizon)`
- number of non-trivial auto-derived invalidation leaves
- residue-vs-invariant cardinality (§8.3)
- distance from a maintained library of "generic mechanism" embeddings
- optional bonus if expressible as a graph path (§10.3)

**Specificity alone is gameable in the opposite direction** — spurious precision scores brilliantly. It only works paired with the calibration ledger (§14): specificity gates promotion, calibration punishes over-narrow claims after the fact. Neither works alone.

A cheap **single-slot adversarial critique runs on mechanism at fill time** — the one slot where a thin entry poisons everything downstream. Critiquing all four slots is unnecessary cost.

### 10.2 Declared regime scope

Mechanisms may declare the regime scope under which the claim holds (`regime` is a graph node type). A declared scope is more falsifiable than a claim that quietly only works sometimes, and §5's robustness pass then checks the declared scope rather than fishing.

- **Scope must be declared before the robustness pass runs**, or a model narrows scope post hoc once it sees which windows worked and declared scope becomes laundered curve-fitting.
- Unresolved tension: narrower scope is more falsifiable but has less statistical power. Cross-sectional breadth (§6) is how power is bought without heterogeneity.

### 10.3 Mechanism as graph path — optional and scored

A mechanism expressed as a causal path over graph edges (entity → narrative → asset) makes plausibility partly deterministic — do those edges exist with meaningful weight and lead-lag — and makes invalidation structural: the path's edges weakening *is* the reversal condition.

Kept **optional and bonus-scored, not required**: the graph vocabulary is still growing, and requiring path-expressibility early would amputate exactly the novel hypotheses the harness exists to find. §8.4's shape check delivers much of the same deterministic-plausibility value now, cheaply.

---

## 11. Invalidation — Error-Detection Bubble

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

Three of four child types are **auto-derived with no new model authoring**: mechanism's `predicted_effect`, each corroboration's `effect_claim`, and the observation's residue are already claims with defined shape. Only a genuinely novel condition needs a `custom_condition` leaf.

### 11.1 verification_block, not contradiction

Requiring evidence to *prove the opposite* set invalidation's bar nearly as high as corroboration's confirmation bar, undoing the intended asymmetry. Corrected: does independent evidence fail to still clear the bar needed to call the claim confirmed — evidence that has merely gone flat or ambiguous counts.

```
CorroborationKinds["verification_block.v1"] = {
  check(candidate, target) -> {
    independence: <§9.1>,
    still_confirmed: two_tier_alignment(candidate, target) > verification_threshold,
                     // near neutral, well below alignment_threshold
    verdict: independence AND NOT still_confirmed
  }
}
```

Applies **tree-wide**, not just to custom leaves.

### 11.2 Hysteresis at the leaf, state machine at the root

A memoryless tree fired the instant one window dipped below threshold; under an unweighted OR root that made the whole tree over-twitchy. The fix is hysteresis at the **leaf**, not weights at the root:

- A leaf is `broken` only after N consecutive evaluation windows below threshold, `ambiguous` in between, `intact` otherwise.
- **N scales to the claim's declared horizon** (a fraction of it), not a flat constant — a 3-day claim and a 6-month claim cannot share a window count.

The root emits a **thesis state machine** rather than a boolean:

```
active      → all leaves intact
degraded    → any leaf ambiguous, or one leaf broken with others intact   → cut sizing
invalidated → mechanism broken, or ≥k legs broken                          → exit
```

This preserves "one clear disconfirmation is enough" while requiring *clear* to mean *sustained*, which is how research actually abandons positions. Honest cost: hysteresis converts false-kills into slow-kills, so a genuinely dead thesis bleeds for N windows. `degraded` must therefore cut size **aggressively, not cosmetically** — that is what makes the trade acceptable.

### 11.3 Observation's invalidation kinds

Observation gets **two** kinds and explicitly no persistence kind:

```
InvalidationKinds["observation_integrity.v1"]   // bad print, revision, delisting, feed gap
InvalidationKinds["delta_reality.v1"]           // re-estimate all frames on the declared longer
                                                // sample, re-run cancellation, fire if residue collapses
```

Anomaly decay is anomalies behaving normally, never thesis failure — so no persistence check. But "the delta was never real" *is* legitimate invalidation and integrity checks cannot catch it: a residue collapsing to empty on more data means the observation slot was filled with noise and everything built on it is void.

`delta_reality`'s re-estimation window is **declared when the observation is filled**, not chosen later — otherwise it is re-testing until failure, the same snooping problem wearing a different hat.

### 11.4 Custom leaves, rigor-checked by the same operator

A `custom_condition` leaf must be authored as a full EffectClaim-shaped artifact (not free text) so it has an embedding to compare, and runs through `verification_block` with independence checked against **the whole spark**, not just the observation. A custom leaf restating an existing derived node fails independence and is merged rather than padding the tree.

---

## 12. Basis Alignment Operator

Bases form a partial order: adding a field can only add residue entries, never remove them (cancellation is per-field), so residue is monotonic in the basis. Two clean directions — project down to a shared sub-basis (loses residue, knowably) or join up to a union basis (gains residue).

```
BasisAlignment {
  id, kind                  // "projection.v1" | "correspondence.v1" | "join_rederive.v1"
  basis_a, basis_b
  mapping: [ { field_a, field_b, confidence } ]
  coverage                  // |∩| / |∪|
  verdict: "comparable" | "partial" | "incommensurable"
  residue_comparison?
}
```

**Tier 1 — projection onto intersection.** Compare residues on `basis_a ∩ basis_b`, report coverage. Deterministic, no model call. The critical output is the distinction between *compared and found different* and *could not compare*: if both residues lie outside the intersection, the verdict is `incommensurable`, never "nothing in common."

**Tier 2 — correspondence mapping.** For fields equivalent but not identically named. Matched by **provenance embedding similarity + type compatibility** — provenance already describes measurement process, which is exactly what field equivalence turns on. Yields a partial mapping with per-pair confidence; mapping confidence travels as a discount, since chained weak matches otherwise produce falsely precise comparisons.

**Tier 3 — join and re-derive.** Frames are computed deterministically from graph state over declared windows, so both sparks' frames can be recomputed over the union basis with no model calls. Exact rather than approximate, and the only tier that can establish that two theses genuinely *disagree*.

> **Guardrail:** re-derivation is non-destructive and analysis-only. It produces a comparison artifact, never mutates the source spark, and never feeds that spark's own promotion. Otherwise "re-derive over a wider basis" is post-hoc basis selection, reopening the snooping surface §8.1 closed.

**Polarity flips by use**, as corroboration and `verification_block` share an operator: **dedup** wants basis *similarity*; **cross-spark corroboration** wants basis *distance* (same thing seen differently is the strong case). Same computation, opposite reading.

### 12.1 Where it applies

| Scope | Applies? | Why |
|---|---|---|
| **Frames within one observation** | **No — should not exist** | Frames share a basis by construction and must: cancellation needs a fixed field set. An invariant (§8.1), not a gap. |
| **Across events / sparks in one system** | **Yes — the real home** | Same graph vocabulary, embedding version, source set, so correspondence is mostly mechanical and joins are cheap. Powers spark dedup, cross-spark corroboration via basis distance, and pre-deployment strategy-correlation estimates from spark similarity (§15) — the case realized returns cannot answer yet. |
| **Across epochs in one system** | **Yes — and required** | A source outage silently changes the basis, so a replication claim compares two different things. `BasisRealization` records what each epoch could actually express and how well; comparison returns `same_basis` / `partial` / `incommensurable`; a core whose inputs were not expressible in every epoch is **refused, not credited**. *Did not replicate* and *was never testable* are different findings, and collapsing them turns a source outage into evidence. The coverage floor is required with no default — a field present in every epoch but populated in a fifth of one epoch's frames is not really shared. Epoch boundaries behave like system boundaries the moment a source drops out. |
| **Across different systems / forks** | **No — use the prediction layer** | Different backends, vocabularies and embedding versions mean correspondence confidence is low and compounding, and joins may be uncomputable. Honest cross-system comparison is calibration on registered, resolved predictions: **reality is the one basis every system shares** (§14). |

---

## 13. Strategy Formalization

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

**`compile()` produces a form, not an instance.** A `StrategySpec` is entity-free, date-free **and constant-free**, checked structurally: its conditions are expressed over basis fields and phenomena, and its universe is a *coverage requirement* — an entity enters by having the basis covered and leaves when it does not — never a list of names. The calibration ledger (§14) therefore scores the form across every instance it fires on, which is what makes cross-sectional replication (§6) evidence rather than anecdote. A single disposable trade thesis burns a historical window for one data point and yields one Brier score forever.

Constant-freedom cannot be checked by type — a declared `q=0.95` and a fitted threshold are both floats. It is checked behaviourally: resolve the same form against two materially different windows and any rule-governed field that fails to move is carrying its derivation window. Since the form is the only thing crossing an epoch boundary, that check is also the cross-epoch leak check.

Mapping is mostly mechanical given how structured the inputs are:

- **observation residue → entry trigger** — already a computable condition over the declared basis.
- **mechanism.predicted_effect → direction + target** — sign, magnitude, horizon map onto direction and holding horizon.
- **invalidation state machine → exit + sizing** — `degraded` cuts size, `invalidated` exits (§11.2).
- **accumulated support (§9.3) → sizing input** — not a gate, but not discarded either.

Every compiled field carries provenance (`attributes.entry.derived_from = spark.principles.observation.artifact_ref`), which is what lets adversarial critique check a compiled strategy against its source claims mechanically instead of trusting a faithful translation.

**Distillation test for `model_in_loop.v1`.** Any model-in-loop strategy is benchmarked against its own compiled deterministic approximation. If it does not beat its distillation out of sample, the model contributes nothing but cost and non-determinism, and the strategy is demoted to the compiled kind. Per-strategy, empirical.

**Spark → eligible strategy kind** via a small compatibility table, with the model choosing only among eligible entries and logging why when more than one applies.

---

## 14. Predictions as First-Class Events

The harness is a **pre-registration system**.

```
PredictionRegistered { spark_ref, effect_claim, declared_scope, resolve_by,
                       embedding_space_version, concept_map_version }
PredictionResolved   { prediction_ref, realized_outcome, brier, calibration_bucket }
```

- At promotion, register. At horizon, resolve.
- Gives a **calibration ledger** (Brier per model, per spark kind, per basis) **independent of PnL**.
- PnL conflates "was the thesis right" with "was sizing and execution right." Separating them is what lets the flywheel learn which *reasoning* works rather than which trades won.
- **Score only forward, registered, resolved predictions plus forward paper-trading. Backtests are admission, not score.**

**External benchmark.** Calibration in isolation answers "are we well-calibrated"; it cannot answer "are we better than the consensus." Where a prediction market existed on the same resolved question, the market's price at registration time is a benchmark the ledger can score against — beating the market's Brier on N resolved questions is a far harder claim than a raw calibration figure, and it is the cheapest external validation available anywhere in this design. It also requires nothing new: prediction market contracts are already `(subject, sign, magnitude, horizon)` with a resolution criterion, which is the EffectClaim shape.

**Consequence:** forward-only scoring means no scoreboard for weeks. The spark log itself is the early artifact — "here is what it noticed, here is what it predicted, resolution pending" is honest and more informative than a number.

---

## 15. Live Strategy Monitoring & Portfolio Layer

The invalidation tree monitors the *thesis*; nothing else monitors the *strategy* once live.

- Derive an **expectation envelope** from walk-forward results; emit `StrategyDegraded` when the live trace drifts outside it. Alpha erosion and crowding show up here before the thesis is provably wrong.
- **Pre-deployment correlation:** because sparks carry embeddings and bases (§12), strategy correlation can be estimated from spark similarity *before* allocating capital, not only from realized returns.
- A capital allocator is just another bus consumer.

---

## 16. The Meta Layer — Kinds With Track Records

The harness is an epistemology engine: spark = hypothesis, corroboration = independent confirmation, invalidation = falsification, testing = replication. The next step is subjecting its own components to the same discipline.

Thresholds, spark kinds, corroboration kinds, invalidation kinds, bases, concept maps, and the spark model's prompt all become artifacts with track records — calibration, survival rate, false-promotion rate. Selection over kinds is then the harness evolving, and "which spark kind produces theses that survive" becomes continuously answered rather than manually asked.

**Critical constraint:** this recreates §6's data-snooping problem one layer up. Picking the best-surviving spark kind across twenty kinds is overfitting the meta-layer. The same deflated-Sharpe and window-budget discipline must apply here, or the meta-layer becomes the most sophisticated overfit in the system.

---

## 17. Substrate, Cost, Humans & Reflexivity

**Two products, one contract.** The data layer and the harness are built alongside each other but stay modular: the data layer must be sellable with no harness, and the harness must run on any conforming data layer. If either cannot be described without the other, the seam has leaked. A fixture data layer — hand-built, synthetic, with a known restatement and deliberate typed gaps — is what keeps that honest: the harness test suite runs against it alone, so any test needing the real data layer reveals a leak.

**Substrate.** Happen (Nodes + Events on NATS, Liners as governance-as-code) is the leading candidate. Every pipeline stage is naturally an event, and a Liner is the natural place to enforce the no-lookahead guard structurally. Not yet confirmed.

**Inference cost is a design constraint, not an implementation detail.** Several additions increase per-spark cost (specificity scoring, mechanism-fill critique, adversarial passes, relationship extraction). Single-payer now, so cost-per-spark needs an explicit budget line. Current cost-reducing choices: three of four invalidation leaves auto-derived, critique on mechanism only rather than all four slots, cancellation and separation fully deterministic, baseline legs computed from graph state rather than model-authored, extraction cached on content hash.

**Human-in-the-loop.** A human session is another consumer on the same bus — inject a hypothesis, force a stream re-query, fork a strategy, aim the adversarial critic. But the gates (specificity floor, accumulation threshold, hysteresis, pre-registration) are calibrated for *unattended* runs and can make a co-pilot session feel bureaucratic. Resolution: a human can **override a gate, with the override recorded as an artifact** carrying its own track record — neither bypassing rigor silently nor being blocked by it.

**Reflexivity is operational, not theoretical.** Publication is itself an invalidation channel: the more visible a thesis, the faster it decays. Acceptable *if the product is the harness rather than the alpha*, which is the current stance — but a decision made explicitly here rather than discovered later. A `crowdedness` graph node would let it be modelled rather than ignored.

---

## 18. Open Issues

Roughly in blocking order:

- **Root-set saturation bound.** Generation-distance weighting vs. a hard cap is undecided; without one, independence collapses to zero for all mature evidence.
- **`k` in the invalidation state machine** (how many broken legs = invalidated) and the `degraded` sizing multiplier are both unset.
- **Hysteresis N as a fraction of horizon** — the fraction is unset, and it directly controls the false-kill / slow-kill trade.
- **Correlation-cluster cap method** — clustering by embedding space? by `couples_to` graph? by root-set overlap? Unspecified.
- **Regime scope tension**: narrower declared scope is more falsifiable but has less statistical power. No resolution.
- **Specificity floor calibration** requires the calibration ledger to have data, so the floor cannot be set correctly until the system has run. Bootstrap value needed.
- **Concept map governance** — who decides a tag precedence, when a map version invalidates prior cross-entity comparisons, and what coverage floor makes a peer group usable.
- **Basis vocabulary growth process** — who decides a field is missing, and when a new field version invalidates prior comparisons.
- **`compile()` completeness** for `threshold_rule.v1`: which residue shapes are expressible as deterministic predicates, and what happens to those that aren't.
- **Custom extension tag coverage** — the XBRL APIs exclude non-standard taxonomies, so some entities have concept gaps. Fallback path (Financial Statement Data Sets, raw instance parsing) not built.
- Human co-pilot session UI not designed. Spark-log presentation not designed.
- Planted-effect synthetic suite deferred — needs realistic microstructure.
- Whether Happen is the confirmed substrate.

---

## 19. Recurring Design Principles

- Deterministic code computes; models interpret. Never let a model self-report what a computation could verify.
- Every structured object: frozen core contract the engine depends on, plus an open registered kind for everything else.
- Split registries along genuine interface differences, not naming.
- Keep the top-level concept vocabulary fixed and small; extend via kinds. This protects real invariants from being quietly defined away.
- Every verdict or judgment is a stored, queryable artifact, never an inline boolean.
- **Anything that could be chosen after seeing results must be declared before** — basis, frame spacing, concept map, re-estimation window, regime scope, prediction horizon. The single most repeated fix across v2 and v3.
- **A declared form carries rules, not numbers.** A threshold derived in one window *is* that window's noise level, so parameters resolve against whichever window the form is applied in (`null_quantile(q=0.95)`, `subject_volatility(multiple=1.0)`), never as stored constants. An unresolvable rule raises; a default would silently carry the derivation epoch's value into a window that never justified it. Keeping entity ids out of a form is necessary and nowhere near sufficient — `min_separation = 1.2472` contains no entity id and is a fit to one window.
- Never fabricate a value to fill a gap. Not-representable is a state; interpolation is a lie that manufactures residue.
- Evidence combines by weighted accumulation, not binary gates; independence discounts rather than vetoes.
- The asymmetry between building and breaking a thesis is intentional — convergence across independent sources to build, a single *sustained* failure to break.
- Score forward, never backward. Backtests admit; predictions score.
