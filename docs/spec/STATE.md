# Implementation state — gaps beside the spec, not folded into it

*Updated 2026-09-15 after report 004. Companion to `docs/spec/01`–`05`.*

Where the spec is right and the implementation is thinner, the gap is recorded
**here**, never by editing the spec to describe what exists. Rewriting a spec to
match the code quietly lowers the bar, which is the one failure mode a drift
audit exists to prevent.

Corrections in the other direction — where the implementation is right and the
spec was stale — have been folded into the spec documents (drift audit 001
part 1, applied).

---

## Blocking the headline question

| # | Gap | Consequence |
|---|---|---|
| **1** | **Promotion rate is an epoch property, not a market property** | Across 20 null runs, 2019H1 promoted **0**, 2021H1 **39**, 2023H1 **13** — on markets with no structure. Cross-epoch promotion counts are therefore not comparable, so "replicated in 2 of 3 epochs" would not mean what it appears to even if a core achieved it. This invalidates the replication bar itself and **now precedes everything else**. Undiagnosed; candidates are coverage differences feeding the invariant set, volatility differences feeding the vol-relative magnitude, and per-epoch tolerance |
| **2** | **B3: the mechanism slot is filled from a hand-written template library, not a model** | The project's central claim — that a model devises and defends its own strategies — is **untested**. Everything so far tests the gates around the slot. Rejections are informative about the data; acceptances are not informative about the world |
| **3** | **Corroboration comes from the invariant set only** | Supports no-move claims and cannot support directional ones. Every core derived to date is `neutral`. The harness structurally cannot find the thing it was built to find |
| **4** | **Window budgeting / deflated Sharpe not started** | Named the largest risk in reports 001 and 003. The ledger now separates *looks* from *tests* (1,080 per epoch recorded), so a correction has a denominator to consume — but no correction exists |

## Data layer

| Stage | State | Missing |
|---|---|---|
| A1 | partial | No persistent store (in-memory over a raw cache). Concept map is a tag-precedence tuple, not a published versioned artifact with measured coverage |
| A2 | partial | ALFRED (vintaged macro) and the press wires absent. GDELT now via the bulk archive |
| A3 | **minimal** | Six hand-written entities; no PIT ticker resolution, no 8-K relationship extraction. **Blocks entity→entity edges, so B1's graph is price and attention looking at themselves** |
| A4–A6 | not started | A `/relate`-shaped validity matrix exists in `harness/presentation.py`; join spines, relation registry and event spine do not |
| A7 | fixture only | No real venue adapter |
| A8 | partial | Conformance suite is the trust boundary and now includes both load-bearing checks (normalize determinism, no-network-in-read). Declarative YAML loader absent |
| A9 | not started | — |
| A10 | **not started** | **The only item with a clock on it.** Bluesky, Farcaster, StockTwits have no purchasable archive at any price |

## Harness, after B5

Specificity floor still a bootstrap value · no mechanism-fill critique · basis
alignment operator not started · regime scoping is a declared field, unused ·
nothing watches a live strategy · planted-effect suite not started ·
support→probability mapping uncalibrated.

## Known measurement weaknesses

- **Entity resolution is by name, not identifier**, everywhere except EDGAR. GKG
  is exact-match on a declared alias set at confidence 0.95; Hacker News is an
  exact-phrase title query at 0.9; the old GDELT text query was 0.75. Each
  discounts every separation it feeds.
- **`revenue_yoy` is not representable in any window** — quarterly filings into a
  weekly basis, correctly refused. Fundamentals have contributed nothing to any
  run.
- **Algolia truncates at 1000 results by recency**, which would manufacture a
  spike at every window boundary. Chunked monthly with a raise on truncation.
- **Prices are prototype grade** — no delisted coverage, so every run is marked
  contaminated for survivorship.

---

## Drift audit 001 part 3 — answers from the code

| Q | Answer | Action taken |
|---|---|---|
| 1. Budget granularity | Was per `(version, epoch)`. Report 003 charged 3 units for 162 `(window, entity)` evaluations — the undercount you suspected | Split into `spent` (looks, governs the holdout cap) and `evaluations` (tests, the multiple-testing surface). Both recorded, neither stands in for the other |
| 2. `harness/potency.py` | The harness's reading of the layer's declared `records_of` / `role` / `reports_on`. Load-bearing for echo-collapse independence — twelve articles about one filing have disjoint lineage and are one leg | **Should be specced.** Not yet in `01`; belongs in §9 alongside root sets and coupling as the third independence mechanism |
| 3. `is_generic()` | **The check did not change.** It still matches caller-supplied entity and date literals, and excluded `core` from the blob entirely | Added `TradeTypeCore.window_independence()` — resolves the same core against two materially different windows and reports any rule-governed field that fails to move. Behavioural, because a declared `q=0.95` and a fitted threshold are both floats |
| 4. Conformance coverage | `normalize_determinism` present; **no-network-in-normalize absent** | Added `no_network_in_read`: blocks sockets and streams the layer. Both load-bearing checks now present |
| 5. support → probability | Raw logistic, uncalibrated. Report 001's p=0.8755 against a realised 0.778 stands unexplained | Open. The ledger has rows but no calibration step consumes them |
| 6. Coverage floor | `0.75`, hardcoded at two call sites in a demo. Required-with-no-default at the function boundary, but the *value used* was recorded nowhere a report reader could find | Moved to `EpochSet.min_coverage`, required, and exposed via `EpochSet.declared()` so the protocol travels with the result |
| 7. Leak check scope | Within-trace only | The cross-epoch channel is the **core**, and it is the same hole as Q3 — answered by `window_independence`, which is the cross-epoch leak check |

---

## Run queue

Revised by report 004, which found the gates are not yet trustworthy enough to
evaluate a model's hypotheses.

1. **Diagnose the epoch asymmetry** (gap 1). Precedes everything; the replication
   bar does not mean anything until promotion rates are comparable across epochs.
2. **Run 005 — window budgeting.** Deflated Sharpe over 87 sparks and 1,080
   recorded tests per epoch. Bar: the correction either changes a promotion
   decision or shows the count is within chance. No outcome is "it ran".
3. **Run 004 — directional corroboration leg.** Bar: at least one directional
   core is *derived*. Declared failure condition — if every core remains
   `neutral` after the leg exists, stop and fix the leg rather than running more
   epochs.
4. **Mechanism discovery.** Held, now for a better-evidenced reason than before.

**Not gated on any of this: the recorders (A10).** Independent of the run loop
and the only thing with a deadline. Every day not recording is history that
cannot be bought later at any price.
