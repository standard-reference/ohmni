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
/harness      bus (sim-clock + lookahead guard), potency, independence,
              a reference observation consumer, stage obligations
/tests        94 tests, fixture-only by design
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

Start with [`docs/test-strategy.md`](docs/test-strategy.md).
