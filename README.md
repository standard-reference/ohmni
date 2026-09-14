# ohmni

Two products, one contract. A point-in-time financial data layer, and a harness
that discovers and tests strategies over it — coupled only through `/contract`,
so either can be replaced without the other noticing.

This repository currently contains the **test substrate**: the contract, a
hand-built fixture data layer with declared design intent, a conformance suite,
and the stage-obligation map that answers whether a given data layer can feed each
phase of the harness build.

```
/contract     shared port — both sides depend on this, neither on each other
/fixtures     a hand-built DataLayer: honest, adversarial and degraded variants
/conformance  the suite a layer must pass; ships with the plugin loader
/harness      bus (sim-clock + lookahead guard), market graph, potency,
              independence, observation, mechanism, corroboration,
              invalidation, spark assembly, stage obligations
/demo         first_spark.py    — data layer to one spark
              strategy_run.py   — spark to a generic trade type, strategy,
                                  registered prediction and calibration ledger
/data_layer   real adapters: EDGAR, Wikimedia, FINRA, GDELT, prices
/tests        158 fixture-only tests + 10 against the real adapters
/docs         test-strategy.md — what is established, and what is not
```

```bash
pip install pytest && python -m pytest tests/ -q
```

## The two claims, both falsifiable in ten minutes

```bash
python -c "
from conformance import run_conformance
from fixtures.layer import FixtureDataLayer
print(run_conformance(FixtureDataLayer()).summary())"

python -c "
from fixtures.layer import FixtureDataLayer
from harness.manifest import RunManifest
from harness.obligations import report
print(report(RunManifest.for_layer(FixtureDataLayer())))"
```

## One spark, end to end

```bash
python demo/first_spark.py
```

Data layer → bus → graph → anomaly → observation → mechanism → corroboration →
invalidation → gate. The mechanism slot is filled from a declared template
library rather than a model; the deterministic gates around it are the point.
The obvious story is rejected on shape incommensurability, with the reason kept.

## A strategy, not a trade

```bash
python demo/strategy_run.py
```

A promoted spark compiles to a **generic trade type** — conditions over basis
fields and phenomena, with no entity id or date anywhere inside it, which is
checked structurally. It fires across a universe defined by basis coverage rather
than by name, registers a prediction per firing, and the calibration ledger
scores the *form* rather than any instance.

## Over real data

```bash
python demo/historical_run.py
```

Six entities, six months, five real sources, replayed as a time-lapsed stream.
The real layer passes the same conformance suite as the fixture, and Intel's 2024
restatement of H1 2022 revenue resolves correctly on both sides.

The first run's strategy **lost 9 of 9 predictions** —
[`report 001`](docs/report-001-first-historical-run.md).

## Across epochs

```bash
python demo/multi_epoch_run.py
```

A form derived from one window is a fit to that window even with no entity id in
it, because the *parameters* carry the window. So parameters are rules resolved
against whichever window the form is applied in, and a core is promoted only when
the same invariant identity is independently derived in several disjoint epochs.

Run over four epochs, **nothing replicated** — the form that looked like a
strategy in one period appears in one epoch of three.
[`report 002`](docs/report-002-multi-epoch-replication.md).

## Reproducing a run in a fresh session

Each evaluation can run cold, in a new session with no memory, over the same
pinned corpus. Two things make that meaningful:

```bash
python scripts/rebuild_dataset.py     # rebuild from public sources, then verify
```

- **`.dataset/manifest.json.gz`** pins every file by hash. Source data never
  enters git — the repository carries the hashes and the corpus is rebuilt from
  where it came from. A rebuild that cannot be proved identical is a different
  dataset wearing the same name.
- **`.budget/ledger.json`** is the one memory a stateless protocol must keep.
  Re-running the same harness version costs nothing; a changed version costs a
  budget unit whether or not anyone remembers the earlier run, because the
  version is a content hash of the source.

Start with [`docs/test-strategy.md`](docs/test-strategy.md), which is explicit
about what the suite establishes and what it does not.
