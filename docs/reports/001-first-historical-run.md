# Report 001 — First historical run

*2026-09-13. Six entities, six months, five real sources, replayed as a

> **Status.** Findings stand. The magnitude correction it forced — claims bounded
> by the subject's own realised movement rather than an absolute return — is now
> spec (§24) and is the reason later runs are expressible at all. The *strategy*
> it produced was superseded by report 002 and finally shown to be noise by
> report 004; read this for the correction, not for the result.
time-lapsed stream.*

---

## What this run was

The first time the harness saw data it did not author. Everything before this
ran against `/fixtures`, where the answers were known because the dataset was
built backwards from them.

| | |
|---|---|
| Window | 2023-01-03 → 2023-06-30 (prices to +45d for resolution) |
| Entities | NVDA, AMD, INTC, AAPL, MSFT, TSLA |
| Sources | SEC EDGAR XBRL, Wikimedia pageviews, FINRA daily short volume, GDELT, daily closes |
| Records | 3,929 |
| Method | 8-week observation windows, stepping 2 weeks, 9 windows × 6 entities |

---

## Result 1 — the seam holds

**The real data layer passes the same conformance suite as the fixture: 15 pass,
0 fail, 0 skip.** No special cases anywhere, and no harness test imports anything
from `data_layer`.

That was the point of building the fixture layer first. An interface with one
implementation is a guess; this is the second implementation, and the contract
survived contact with sources that do not care what the contract wants.

## Result 2 — point-in-time correctness, on a real restatement

Intel re-presented its H1 2022 revenue in an August 2024 filing.

```
as_of 2023-01-01:  2022-07-02 year_to_date = $33.674B  (filed 2022-07-29, chain 1/2)
as_of 2025-01-01:  2022-07-02 year_to_date = $24.664B  (filed 2024-08-02, chain 2/2)
```

This is the test `03-data-sources.md` specifies for settling point-in-time claims
empirically, run against live EDGAR. A nine-billion-dollar difference on an
honest timestamp is exactly the contamination the bus guard structurally cannot
catch, and the revision chain is what makes it visible.

## Result 3 — the run is marked, not quietly weaker

```
B0  runnable
B1  degraded      lost=['mechanism_as_graph_path_bonus']
B2  runnable
B3  runnable
B4  contaminated
B5  contaminated
contaminated: ['survivorship']
```

The price source serves only currently-listed names. That is declared on the
source, the capability is absent from the set, and every run against this layer
is labelled. Nobody has to remember it.

## Result 4 — the stream

```
28 sparks opened, 5 promoted, 1 trade type
mechanism rejections: required movement absent 94, shape incommensurable 14,
                      required invariance not held 2
leak check across every window: CLEAN
```

The one surviving form, applied at all 9 windows across all 6 entities:

```
tt_transient_attention_no_flow        generic: True        stance: abstain
entry      information_seeking residue, shape=spike_and_return, separation >= 1.25
           requires invariant: editorial_publication, exchange_activity,
                               off_exchange_routing
direction  neutral, |move| <= 1 x the subject's own 14d realised movement
fired      12 times — 3 in the windows it was derived from, 9 elsewhere
```

---

## Result 5 — the strategy was wrong, and that is the finding

**First run: 9 resolved predictions, 9 failures. Brier 0.7665, hit rate 0.000.**

```
NVDA +15.5%   TSLA +15.2%   TSLA +9.9%   INTC -8.8%   INTC +8.2%  ...
```

The same form scored 0.0135 on the fixture and beat a synthetic prediction
market. On real data it lost every single call.

The mechanism was not the problem. The **magnitude** was: `|move| <= 0.02 over
14 days` was a constant written for a synthetic fixture whose daily returns were
0.02%. Real semiconductors in 2023 clear 2% in a fortnight as a matter of course,
so the claim was not false-but-close, it was not a claim about the world at all.

This is precisely the failure `01-system-specification-v3.md` §10.1 predicts:

> Specificity alone is gameable in the opposite direction — spurious precision
> scores brilliantly. It only works paired with the calibration ledger:
> specificity gates promotion, calibration punishes over-narrow claims after the
> fact. Neither works alone.

The specificity gate promoted a spuriously precise claim. The ledger caught it on
the first contact with reality. **The architecture did the thing it was designed
to do, and the fixture could never have shown it** — a synthetic dataset agrees
with whatever constants you wrote into it.

### The correction

A no-move claim is now bounded by the subject's own realised movement over the
horizon, measured from data knowable at spark time, rather than by an absolute
return. `|move| <= k × σ_horizon` means the same thing for a utility and a
semiconductor; `|move| <= 0.02` does not.

**Second run: Brier 0.182, hit rate 0.778 (7 of 9).**

**That second number is admission, not score.** The definition was changed after
seeing the first result, on the same data. It says the correction is directionally
right; it does not say the form works. Only forward, registered, resolved
predictions score, and none of these are forward.

A second miscalibration is visible and unfixed: the claim is issued at p=0.8755
against a realised 0.778. That probability comes from accumulated support through
the logistic, and support is a measure of *corroboration strength*, not a
probability estimate for this claim. Mapping one to the other needs the ledger to
have data. It now has nine rows.

---

## Where the build is

### Track A — the data layer

| Stage | State | Notes |
|---|---|---|
| **A1** fact model, status enum, store, EDGAR | **partial** | Fact model, status enum, EDGAR revision chains and `as_of` all work against live data. No persistent store (in-memory over a raw cache). Concept map is a tag-precedence tuple, not a published versioned artifact with measured coverage. |
| **A2** remaining deterministic adapters | **partial** | Wikimedia, FINRA, GDELT done. ALFRED (vintaged macro) and the press wires are not. |
| **A3** entity spine, enrichers, relationships | **minimal** | Six hand-written entities. No point-in-time ticker resolution, no 8-K relationship extraction — which is why B1's graph has no entity→entity edges and the graph-path bonus is unavailable. |
| **A4–A6** cross-reference, relations, event spine | **not started** | A `/relate`-shaped validity matrix exists in `harness/presentation.py`; the join spines, relation registry and event spine do not. |
| **A7** prediction markets | **fixture only** | Contract/quote/resolution modelled and tested against a synthetic venue. No real venue adapter. |
| **A8** plugin system | **partial** | The conformance suite exists and is the trust boundary. The declarative YAML loader does not. |
| **A9** API, determinism receipt, MCP | **not started** | |
| **A10** social adapter + recorders | **not started** | **This is the one with a clock on it.** Bluesky, Farcaster and StockTwits have no purchasable archive at any price. Every day not recording is history that cannot be bought later. |

### Track B — the harness

| Stage | State | Bar met? |
|---|---|---|
| **B0** bus, guard, ordering, root sets, manifest | **done** | Adversarial peek fails by every route; runs hash-reproducible; null runs labelled and hash differently. |
| **B1** market graph, anomaly detection | **done, thin** | Five node types and deterministic detection work. No entity→entity edges pending A3, so the graph is still mostly price and attention looking at themselves. |
| **B2** observation | **done** | Residue/invariant/not-representable stay three states; cadence incoherence refused, not forward-filled; resolution confidence reaches the computation. |
| **B3** spark slots | **partial** | Slots, ordering, two-tier alignment and independence all work. The mechanism slot is filled from a **declared template library, not a model** — the deterministic gates around it are what is tested. |
| **B4** compile, execution, leak check | **done** | Compiled entry traces to source residue; leak check clean across every window and catches a planted leak. |
| **B5** real vs null | **done** | The null control runs first and the movement tolerance derives from its own distribution with a measured 5% false-positive rate. |

### After B5

1. **Prediction registration + calibration ledger** — done, and it earned its keep on day one.
2. **Hysteresis + thesis state machine** — done.
3. **Specificity floor + mechanism-fill critique** — specificity computed; the floor is still a bootstrap value and there is no critique pass.
4. **Deflated Sharpe + window budgeting** — **not started, and this run demonstrates why it matters.**
5. **Corroboration proper** — partial. Corroboration currently comes from the invariant set only.
6. **Basis alignment operator** — not started.
7. **Regime scoping** — a declared field, unused.
8. **Strategy decay + portfolio layer** — not started. Nothing watches a live strategy.
9. **Planted-effect suite** — not started.
10. **Mechanism as graph path** — optional bonus only, blocked on A3.

---

## The largest unaddressed risk

**Window budgeting.** This run tested 54 (window, entity) pairs against a single
six-month history using overlapping 8-week windows. Nothing tracks that. No
deflated-Sharpe correction, no budget per window, no rotating holdout the
proposer never sees.

Every per-spark rigor mechanism in the system is powerless against this, because
each individual spark is clean. The spec names it the largest risk in the design
and it remains completely unmitigated. One promoted form out of 28 sparks over
54 tests is not obviously more than chance would give, and there is currently no
machinery that could tell the difference.

## Other honest gaps this run exposed

- **Corroboration by invariance only supports no-move claims.** A directional
  mechanism scores zero support and can never promote, so the harness can
  presently only discover filters. That is a real ceiling.
- **No mechanism discovery.** The template library is mine. The rejections are
  informative about the data; the acceptance is not informative about the world.
- **GDELT entity resolution is a text query**, declared at confidence 0.75, which
  discounts every separation it feeds. A proper entity join would change what
  `news_rate` means.
- **`revenue_yoy` was not representable in every window** — quarterly filings
  into a weekly basis, refused rather than forward-filled. Correct, and it means
  fundamentals contributed nothing to any spark in this run.

## Next

1. **Window budgeting and deflated Sharpe.** The largest risk, and the cheapest
   thing that would make the promotion count mean something.
2. **A directional corroboration leg**, or the harness only ever finds filters.
3. **The recorders** (A10) — the only item in either track with a deadline.
4. Calibrate the support→probability mapping now that the ledger has rows.

## Reproducing

```bash
python -m pytest tests/ -q                    # 144, fixture-only
python -m pytest tests/ -m historical -q      # 10, needs the raw cache
python demo/historical_run.py                 # this report
```

The raw cache makes the run replayable without network: `fetch` is the only
network boundary and `normalize` is a pure function of what it cached.
