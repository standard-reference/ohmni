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

---

# From spark to strategy

`demo/strategy_run.py` continues the path: promoted spark → generic trade type →
strategy over a universe → execution → registered prediction → resolution →
calibration ledger, scored against a prediction market.

## Why a trade type and not a trade

A **single-trade thesis** ("buy this name on this date because this spiked")
burns a historical window for one data point, cannot be replicated, and produces
exactly one Brier score forever. It is the thing this layer exists not to build.

A **TradeType** is a parameterised form whose conditions are expressed over basis
fields and phenomena, with **no entity id and no date anywhere inside it**. That
is checked structurally — `is_generic()` serialises the form and looks for
instance literals — because it is the property that makes cross-sectional
replication possible, and §6's answer to sample size depends entirely on it.

A **StrategySpec** composes trade types over a universe that is itself a
*coverage requirement* rather than a list of names: an entity enters by having
the basis covered and leaves when it does not. The bank in the fixture has no
pageviews, so it is excluded — and excluded is recorded as `no_coverage`, never
as absence of the phenomenon.

## The compiled form

```
trade type   tt_transient_attention_no_flow      stance: abstain
entry        information_seeking residue, shape=spike_and_return, separation >= 3.70
             requires invariant: editorial_publication, exchange_activity,
                                 off_exchange_routing
direction    neutral, |move| <= 0.02 over 14d
exit         degraded -> scale to 0.25 ; invalidated -> exit
sizing       base x support 0.676, degraded x0.25
universe     coverage requirement over four phenomena
```

Every field carries `derived_from` naming the principle it came from, which is
what lets a critique check the compiled rule against its source claims
mechanically rather than trusting the translation.

`compile()` completeness is stated rather than approximated: three residue shapes
have declared predicates, two are refused with a reason. Silently compiling a
shape you cannot express produces a rule that does not implement the claim it
cites.

## Firing is not sizing

An `abstain` stance still **fires**. It makes a falsifiable claim that nothing
will happen, and that claim is registered and scored; whether capital moves is
downstream of the claim and never a condition on it. In the fixture run the
strategy fires six times across two entities and takes zero positions — and the
six predictions are what the ledger scores.

## The ledger

- **Score forward, never backward** is structural: a prediction whose horizon has
  already elapsed at registration cannot be registered at all.
- A prediction cannot be resolved before its horizon.
- Predictions are immutable once made.
- Calibration accrues to the **trade type**, across every entity it fired on.
- The probability comes from the accumulated support via the logistic — which is
  the reason support was accumulated in log-odds in the first place, so no extra
  calibration constant is invented in between.

Fixture result: six predictions at p=0.8837, all held, Brier 0.0135 against the
market's 0.1555 at registration time.

## Findings from this stage

**Invariance corroborates a no-move claim and cannot corroborate a directional
one.** The `sustained_attention` scenario produces a mechanism predicting
appreciation, and its corroboration scores **zero** — the invariant legs assert
"this held still", which the two-tier alignment's sign gate correctly refuses to
count toward "price will rise". The spark is complete but not promoted, and
compiles to no strategy. This asymmetry was flagged as unmodelled at the previous
stage; it is now enforced, and the consequence is that the fixture has no
corroborated directional trade type. Getting one requires a *directional*
independent leg, which is a fixture gap, not a code gap.

**A strategy is compiled only from a promoted spark.** Compiling an ungated spark
makes the gate decorative — the thesis reaches capital regardless of whether it
cleared specificity and support.

**Scenario windows must be disjoint including their resolution tails.** Two
scenarios overlapping on one instrument superposes two price series, and a
prediction registered in one resolves against the other. Caught by a resolved
move of +20% on a scenario built to be flat.

## What this stage does NOT establish

- **The market benchmark is a market I wrote.** Beating it proves the plumbing —
  registration at the right timestamp, the complement of the right side, Brier
  computed against a price observable at registration — and nothing about edge.
- **Six predictions on synthetic data is not a track record.** The ledger exists
  so that a real one can accumulate; it has not.
- **`hit_rate` 1.0 means the fixture was built flat.** The claim was that nothing
  would move, in a scenario constructed with nothing moving.
- **No expectation envelope, no strategy decay monitoring, no portfolio layer.**
  A live strategy is monitored by nothing here once it is deployed.

---

# Epochs, and why a single-window form is still a fit

The first historical run produced a form containing `min_separation = 1.2472`.
It had no entity id and no date in it, and `is_generic()` passed — but that number
came from one window's noise level, and in another regime it means something
else entirely. The form was a fit to its derivation window wearing a generic
costume. Keeping entity ids out is necessary and nowhere near sufficient.

## The generic thing is the recipe, not the number

A trade type now has two halves that never mix:

**`TradeTypeCore`** — the invariant identity. Mechanism, the phenomenon that must
move, the shape it must move in, the phenomena that must hold still, sign,
horizon, and a **rule** for each parameter. This is the only thing that crosses an
epoch boundary, and `identity()` is asserted to contain no floats.

**Parameter rules** (`harness/parameters.py`) — recipes resolved against whatever
window the form is applied in:

| rule | claim | 2019H1 | 2023H1 |
|---|---|---|---|
| `null_quantile(q=0.95)` | further apart than noise gets *here* 95% of the time | 2.10 | 2.38 |
| `subject_volatility(multiple=1.0)` | within the subject's own realised movement | 0.061 | 0.146 |

Same rule, same claim, different number. A rule that cannot be resolved in a
window **raises** rather than falling back to a default — a default would silently
carry the derivation epoch's value into a window that never justified it, which is
the exact bug this removes.

## Promotion is replication, not survival

`harness/epochs.py` declares disjoint epochs up front, each calibrated against
**its own** null. `harness/replication.py` then promotes a core only when the same
invariant identity is independently derived in at least `min_replications`
distinct *derivation epochs*.

Three rules that make that mean something:

- **Epochs must be disjoint.** One that shares data with another is not an
  independent replication, and the constructor refuses it.
- **Firings are not replications.** Ten firings inside one epoch are one
  observation with wide coverage — the windows overlap and the regime is shared.
  Only distinct epochs count.
- **Holdout derivations never count.** A core appearing only in the holdout was
  not proposed; it was discovered while scoring, which is the same mistake in a
  new place.

## Admission and score are different columns

The most recent epoch is a holdout the derivation never sees, and it is the only
place a score may be quoted from. Everything measured on a derivation epoch is
admission. `ScoreCard` keeps them in separate fields rather than separate rows,
because printing them in one column is how the distinction gets lost.
