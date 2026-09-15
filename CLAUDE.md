# Ohmni — operating brief

A research harness in which a model generates, tests and refines trading
hypotheses, and a point-in-time financial data layer underneath it. Two products,
one narrow contract. **Read [`docs/INDEX.md`](docs/INDEX.md) for the map.**

If you are picking this up cold, the three things worth knowing before you touch
anything:

---

## 1. What is currently true

The harness runs end to end on real data. It has produced **no validated
finding**, and one apparent finding has been falsified.

| | |
|---|---|
| Runs end to end | Yes — data layer → bus → graph → spark → strategy → registered prediction → ledger |
| Real data | 6 entities, 4 disjoint epochs, 5 sources, ~4,000 records per epoch |
| Validated signal | **None.** The one positive result was shown to be noise by [report 004](docs/reports/004-null-protocol.md) |
| Biggest open problem | Promotion rate is a property of the *epoch*, not the market — on null data one epoch promoted 0 and another 39. This invalidates cross-epoch comparison, which the replication bar depends on |

Do not describe this project as working, promising, or as having found anything.
It has built machinery that can tell the difference between a finding and noise,
and the only time it has been asked, the answer was noise.

## 2. Disciplines that are not negotiable

These are load-bearing. Breaking one silently invalidates results downstream, and
each has already caught a real error.

- **Never rewrite the spec to describe what is built.** Gaps live in
  [`docs/spec/STATE.md`](docs/spec/STATE.md), beside the spec, never folded into
  it. Rewriting the spec to match the code quietly lowers the bar, which is the
  one failure mode the whole audit process exists to prevent.
- **Never let source data into git.** `.cache/` is ignored. The repo carries
  hashes (`.dataset/manifest.json.gz`); `scripts/rebuild_dataset.py` reconstructs
  from public sources and proves the rebuild identical.
- **Declare the bar before the run.** Every report's reading was fixed in advance.
  Report 004 falsified reports 002 and 003 *because* the criterion was declared
  first; had it been chosen afterwards it would have been a rationalisation.
- **No number that governs a verdict gets a default.** Thresholds are required
  parameters or rules resolved against the window in use. A test asserts
  `RunPolicy` has no defaults.
- **Parameters are rules, not numbers.** `min_separation = 1.2472` contains no
  entity id and is still a fit to one window. Forms carry
  `null_quantile(q=0.95)`; the number is resolved per window.
- **Report negative results as findings.** The most valuable output so far cost
  71 seconds and invalidated two reports.

## 3. Where things are

```
docs/INDEX.md                        the map — start here
docs/spec/ohmni-specification-v4.md  the consolidated spec (supersedes 01–05)
docs/spec/STATE.md                   living gaps + run queue. Dated. Current.
docs/reports/00N-*.md                one report per run, each self-contained
                                     with a status header saying what still holds

contract/     the shared port — both sides depend on it, neither on each other
data_layer/   real adapters: EDGAR, Wikimedia, FINRA, GDELT bulk, HN, prices
fixtures/     hand-built DataLayer: honest, adversarial and degraded variants
conformance/  the suite any layer must pass; ships with the plugin loader
harness/      bus, graph, observation, spark, strategy, epochs, budget
demo/         runnable end-to-end paths
tests/        fixture-only by design; a harness test needing real data is a leak
```

```bash
python -m pytest tests/ -q              # fixture-only
python -m pytest tests/ -m historical   # needs the raw cache
python demo/run003_null_protocol.py 10  # the null control — cheapest, most informative
```

## 4. Conventions

- Reports are numbered per run and self-contained. When a later run invalidates
  an earlier one, **amend the earlier report's status header** rather than
  leaving a reader to reconstruct it from the sequence.
- The budget ledger (`.budget/ledger.json`) is committed and must stay so. It is
  the one memory a stateless protocol keeps: the snooping surface is the dataset,
  not the session, so a fix derived from a result leaks into the code even if
  nobody remembers the run.
- Every run records the dataset freeze hash and harness version. A result that
  cannot name the bytes it saw cannot be compared with anything.
