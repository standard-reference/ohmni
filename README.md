# ohmni

Two products, one contract. A point-in-time financial data layer, and a harness
that discovers and tests strategies over it — coupled only through `/contract`,
so either can be replaced without the other noticing.

**[`docs/INDEX.md`](docs/INDEX.md)** is the map. **[`CLAUDE.md`](CLAUDE.md)** is
the operating brief for picking this up cold.

## Where it stands

The pipeline runs end to end on real data: 6 entities, 4 disjoint epochs, 5
sources. It has produced **no validated finding**, and the one apparent finding
was falsified by its own null control in 71 seconds — see
[report 004](docs/reports/004-null-protocol.md).

That is the system working. What exists is machinery that can tell a finding from
noise, tested once, which answered noise.

```
contract/     the shared port — both sides depend on it, neither on each other
data_layer/   EDGAR XBRL, Wikimedia, FINRA, GDELT bulk archive, Hacker News, prices
fixtures/     a hand-built DataLayer: honest, adversarial and degraded variants
conformance/  the suite any layer must pass; ships with the plugin loader
harness/      bus, graph, observation, spark, strategy, epochs, budget
demo/         runnable end-to-end paths
tests/        fixture-only by design
```

## Running

```bash
pip install pytest && python -m pytest tests/ -q

python demo/first_spark.py                # data layer to one spark
python demo/multi_epoch_run.py            # derivation, replication, holdout
python demo/run003_null_protocol.py 10    # the null control
python scripts/rebuild_dataset.py         # rebuild the corpus and prove it identical
```

## The two claims, both falsifiable in ten minutes

```bash
python -c "
from conformance import run_conformance
from data_layer import HistoricalDataLayer
from datetime import datetime, timezone
L = HistoricalDataLayer().preload(datetime(2023,1,2,tzinfo=timezone.utc),
                                  datetime(2023,6,30,tzinfo=timezone.utc))
print(run_conformance(L).summary())"
```

A real data layer passes the same conformance suite as the hand-built fixture,
with no special cases. And Intel's 2024 restatement of H1 2022 revenue resolves
correctly on both sides — \$33.674B as-of 2023, \$24.664B as-of 2025 — which is the
point-in-time property the whole design rests on.
