# Test strategy

Two questions, asked in order.

1. **Does the data product work?** — `conformance/`, `tests/test_conformance.py`
2. **Can it feed each phase of the harness build?** — `harness/obligations.py`, `tests/test_obligations.py`

Everything else exists to stop those two answers being vacuous.

---

## The principle the whole suite is built around

**The data layer has no oracle.** It does not validate a value against an outside
reference, because there is nothing to validate against — it records what was
said, by whom, when, and how potent that saying is with respect to a declared
phenomenon. "Is this number correct?" is a question it never asks.

So every conformance check asks one thing: **does the source honour its own
declaration?** `run_conformance(layer)` takes the layer and nothing else — no
reference dataset, no network, no second source to cross-check against. That
signature is asserted by a test, because it is the property that keeps the suite
honest.

Two consequences worth stating plainly:

- Conformance guarantees **structure**, not **meaning**. A plugin can pass every
  check and still map the wrong upstream field to `revenue`. Semantic correctness
  needs an oracle cross-check or human review; conformance buys "this cannot leak
  lookahead and cannot fabricate", which is most of the risk and not all of it.
- **Potency is not accuracy.** A post asserting something false is a fully potent
  record of retail discourse — the discourse happened and propagated, and that is
  the fact. It is weak only with respect to a *different* phenomenon. The suite
  asserts this directly, because the natural reading of a "truth spectrum" is the
  wrong one.

---

## Tier 1 — conformance: does an honest layer pass?

15 checks in `conformance/suite.py`. Each declares the failure mode it rejects.

A check whose capability the layer does not declare is **skipped, not failed**.
That asymmetry is the design: conformance tests honesty, not richness, so a CSV
adapter someone writes in an afternoon can pass it by declaring less.

## Tier 2 — negative fixtures: does a lying layer get caught?

A suite that has never failed is an untested assertion. `fixtures/adversarial.py`
holds nine layers, each lying in one realistic way drawn from the vendor survey,
and each declaring the named check that must catch it. Failing for the *wrong*
reason is a false pass, so the test asserts the check id, not just failure.

| Fixture | Lies about | Caught by |
|---|---|---|
| `FabricatedQ4Layer` | Q4 standalone exists | `no_fabrication` |
| `OverwritingLayer` | restatements are preserved | `restatement_as_of` |
| `PeriodEndAvailabilityLayer` | availability ≠ period end | `availability_sanity` |
| `UntypedGapLayer` | gaps are typed | `status_honesty` |
| `SnapshotAsHistoryLayer` | snapshot streams have history | `snapshot_refusal` |
| `UndeclaredDerivationLayer` | derivation lineage is declared | `no_fabrication` |
| `OutOfOrderLayer` | stream ordered by knowable_at | `stream_ordering` |
| `IgnoresAsOfLayer` | as_of is enforced | `as_of_enforced` |
| `NonDeterministicLayer` | normalize is pure | `normalize_determinism` |

One check has **no** adversarial fixture, deliberately: `availability_present`.
The contract makes `knowable_at=None` unconstructible, so a layer cannot serve
one. That is the stronger form of the guarantee — not "we check for it" but "it
cannot occur" — and it is why the capability has no degraded mode.

## Tier 3 — degraded fixtures: does an honest-but-poorer layer still pass?

`fixtures/degraded.py`. Each declares one capability it lacks. All must **pass**
conformance and produce a **named** degradation in the run manifest. This is the
test that keeps "runs on any conforming data layer" true rather than aspirational.

## Tier 4 — obligations: does each build stage get what it needs?

`harness/obligations.py` declares, per stage B0–B5, what it reads from the
contract and what its acceptance bar is. `assess(manifest)` returns per stage:
runnable / degraded (naming the lost features) / contaminated / blocked.

Run against the fixture layer and every degraded variant, this answers the second
question mechanically rather than by argument. One capability is non-negotiable:
without `knowable_at` there is nothing to gate on and the harness refuses to run.
Every other gap degrades in a recorded way.

---

## Where the seam is, and why it moved twice

The line is: **the layer reads what a document says; the consumer judges what it
means.** Two things crossed it during the build and were moved back.

**Potency weights.** `Phenomenon`, `TruthRole` and `lineage.reports_on` are
structural — an 8-K *is* a filing, a repost *does* name its parent, all readable
from the document. But "an echo is worth 0.2" is interpretation, so the weight
table lives in `harness/potency.py`, not in `/contract`. Same line as lineage
versus root sets: general primitive on one side, one consumer's reading on the
other.

**Cancellation.** `harness/observation.py` is a *reference consumer*, not a
pipeline stage. Every transform it performs is lossy — aggregating hourly views
to a weekly total throws away the hours — which is exactly why it sits on this
side of the seam. The layer serves records at native cadence and declares which
aggregations are valid; performing one is a consumer's decision made knowing what
it costs. A layer that pre-aggregated would destroy information no consumer could
recover.

## Thresholds

There are none in the observation layer, and that is deliberate.

`separation_z = 2.0` was in an earlier draft. The null control showed it admitted
4 false discoveries against real data's 5 — and the obvious next move, raising it
until the nulls went quiet, is fitting the threshold to the control: the
data-snooping problem one layer up. A hard cut also manufactures a distinction the
data does not support (1.99 and 2.01 are indistinguishable) and discards the
magnitude before anything downstream can weigh it.

So `observe()` returns a `FieldSeparation` magnitude per field and no verdict.
Residue and invariant are **views**, computed at point of use with the caller's
own tolerance (`harness/calibration.py`, where `alpha` is required and has no
default). Tests assert **orderings** — which field separated most, which scenario
separated more than which — because an ordering needs no cut point.

One discretisation survives, at the decision to act. It belongs there, once, with
the full distribution in hand.

---

## What this suite does NOT establish

Stated because a green suite invites over-reading.

- **Nothing about real data.** Every test runs against `/fixtures`, by design and
  enforced: a harness test that needs the real data layer means the seam leaked.
- **Nothing about semantic correctness.** See the conformance limit above.
- **Nothing about the generative half of B5.** Whether sparks promote on real data
  and fail on nulls needs model calls. What is tested is the data-side obligation.
- **The null control is narrower than it looks.** A shuffle preserves each field's
  own marginal distribution, so a spike still appears somewhere — it destroys
  *joint* structure only. There is a test asserting this, because the intuitive
  test would encode a false guarantee, and a control believed to do more than it
  does is worse than no control.
- **`fixtures/design_intent.py` is not ground truth about the world.** It is what
  the synthetic dataset was built to contain. Legitimate for testing the harness's
  computation; a category error if pointed at a real source.

## Open, and deliberately unresolved

- Root-set saturation bound: `ROOT_SET_GENERATION_CAP = 3` is declared rather than
  defaulted silently, and is not calibrated.
- The correlation-cluster cap keys off `couples_to` only; clustering by embedding
  or by root-set overlap is unimplemented.
- Echo collapse resolves through `reports_on`. Where a source does not declare it,
  echoes are invisible and independence is over-estimated — degraded, not caught.

---

# The spark path

`demo/first_spark.py` runs the whole thing: data layer → bus → graph → anomaly →
observation → mechanism → corroboration → invalidation → gate.

On the `localised` scenario it produces one spark:

| Slot | Content |
|---|---|
| trigger | `information_seeking rose +60σ` on the entity's own edge |
| observation | residue `pageviews_rate` (spike_and_return); `price_return`, `news_rate`, `short_volume_share` invariant; `revenue_yoy` and `options_skew` not representable, for two different reasons |
| mechanism | `transient_attention_no_flow` — attention rose and decayed with no corroborating coverage, flow or positioning, so it does not reprice. Predicts `\|move\| ≤ 0.02` on the instrument over 14d |
| corroboration | three legs from the invariant half, independence 1.0 each, FINRA discounted to 0.9 for being attested rather than constitutive |
| invalidation | six auto-derived leaves, no custom conditions, thesis `active` |

The interesting part is what got **rejected**. `attention_precedes_flow` — the
obvious story — fails the shape gate: it claims attention persists and converts
to flow, which predicts a sustained path, and the observed residue is a
spike-and-return. The causal story and the observed path disagree, computably,
before any model is consulted. That rejection is stored with its reason, because
the ruled-out half is the record of what the data actually said.

`market_wide` produces **no** spark, and the reason is worth keeping: what is
special about it is *joint* — four fields moving together — and per-field
cancellation is blind to joint structure by construction. A permutation null
preserves each field's marginals, so the magnitudes alone are not evidence. The
pipeline correctly declines rather than manufacturing a thesis.

`quiet` produces no anomaly at all.

## Where the numbers live

Every parameter that has no principled default is a required field on
`RunPolicy`, recorded into the run manifest. A test asserts none of them has a
default, because a default is a threshold nobody can find.

`moved_tolerance` is the only one not chosen: it is the null distribution's 95th
percentile, so it comes with a *measured* false-positive rate (0.050) rather than
a preference. The rest are chosen, and two of them are explicitly bootstrap
values — `specificity_floor` and `support_threshold` cannot be set correctly
until the calibration ledger has resolved predictions to punish over-narrow
claims after the fact.

## What the spark path does NOT establish

- **The mechanism came from a template library I wrote.** It is not discovery.
  The deterministic gates around the slot are what is tested; what a model would
  add is templates nobody wrote down, which is the thing the harness exists to
  find.
- **"Promoted" means "passed thresholds that were invented."** Specificity gates
  promotion and calibration is supposed to punish over-narrow claims afterwards.
  Only the first half exists, and specificity alone is gameable in the opposite
  direction — spurious precision scores brilliantly.
- **Nothing is scored.** There is no prediction registration and no calibration
  ledger yet, so the spark is a pre-registration with no resolution behind it.
- **Corroboration by invariance is one reading.** "These three processes held
  still" supports a no-move claim; it would support a directional claim far more
  weakly, and that asymmetry is not yet modelled.

## Two bugs this path caught

Both were the same shape, and both are worth recording because they are the
failure mode this architecture is most prone to:

1. The graph summed every field regardless of its declared aggregation, so it
   fired anomalies on averageable fields (returns) that cancellation correctly
   called invariant — a spark opening on a phenomenon the observation says did
   not move.
2. The graph and the observation used different noise estimators, so they
   disagreed about what moved.

The fix in both cases was to read the declaration rather than keep a second
opinion. There is now a test asserting the trigger only fires on phenomena the
observation calls moved.
