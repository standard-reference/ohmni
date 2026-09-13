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
/tests        141 tests, fixture-only by design
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

Start with [`docs/test-strategy.md`](docs/test-strategy.md), which is explicit
about what the suite establishes and what it does not.
