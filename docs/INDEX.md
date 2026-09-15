# Index

Everything in this repository, and what is currently true.

## Start here

| Document | What it is |
|---|---|
| [`../CLAUDE.md`](../CLAUDE.md) | Operating brief — current state, non-negotiable disciplines, layout |
| [`spec/ohmni-specification-v4.md`](spec/ohmni-specification-v4.md) | **The specification.** Consolidated; supersedes the former `01`–`05` |
| [`spec/STATE.md`](spec/STATE.md) | **Living** implementation gaps and the run queue. Dated, updated after every run |
| [`test-strategy.md`](test-strategy.md) | What the test suite establishes, and explicitly what it does not |

The spec's §29 is a snapshot of implementation state; `STATE.md` is the dated
version. Where they disagree, `STATE.md` is current — and the gap between them is
itself the drift the audit process exists to surface.

## Reports — one per run, newest last

Each is self-contained and carries a status header saying what still holds. You
should not need to read them in sequence to know what is true.

| # | Run | Result | Status |
|---|---|---|---|
| [001](reports/001-first-historical-run.md) | First real data — 6 entities, 6 months, 5 sources | Strategy lost **9 of 9** predictions; forced the volatility-relative magnitude correction | Correction stands; result superseded |
| [002](reports/002-multi-epoch-replication.md) | Multi-epoch derivation and replication | Nothing replicated; established that a single-window form is a fit even with no entity id in it | Method stands; basis was confounded, and its 2021H1 explanation is **withdrawn** |
| [003](reports/003-commensurable-basis.md) | Bulk GDELT archive; basis verified identical across epochs | Confound removed, same conclusion: nothing replicated | Basis result stands; the cluster is **withdrawn as a signal** |
| [004](reports/004-null-protocol.md) | The whole protocol over null markets, 10 seeds | **The one positive signal is noise.** Clusters in 4 of 10 null seeds | **Current** |

Machine-readable result: [`reports/004-null-result.json`](reports/004-null-result.json),
pinned to a dataset hash and harness version.

## Code

| Path | Contents |
|---|---|
| `contract/` | The shared port. Both products depend on it; neither depends on the other |
| `data_layer/` | Real adapters — EDGAR XBRL, Wikimedia, FINRA, GDELT bulk archive, Hacker News, prices |
| `fixtures/` | Hand-built `DataLayer`: honest, nine adversarial variants, seven degraded variants |
| `conformance/` | The suite any layer must pass. Ships with the plugin loader, never after |
| `harness/` | Bus and guard · graph · observation · potency · independence · spark · strategy · epochs · budget · dataset freeze |
| `demo/` | Runnable end-to-end paths, one per stage of the argument |
| `scripts/` | `rebuild_dataset.py` — reconstruct the pinned corpus and prove it identical |

## Running

```bash
python -m pytest tests/ -q                    # fixture-only by design
python -m pytest tests/ -m historical -q      # real adapters; needs the cache

python demo/first_spark.py                    # data layer to one spark
python demo/strategy_run.py                   # spark to a generic trade type
python demo/historical_run.py                 # one epoch of real data
python demo/multi_epoch_run.py                # derivation, replication, holdout
python demo/run003_null_protocol.py 10        # the null control

python scripts/rebuild_dataset.py             # rebuild the corpus, then verify
```

## State that must persist

| Path | Why |
|---|---|
| `.budget/ledger.json` | **Committed.** The one memory a stateless run keeps — how much has been spent on each epoch. Looks and tests recorded separately |
| `.dataset/manifest.json.gz` | **Committed.** Per-file hashes, so a rebuilt corpus can be proved identical |
| `.cache/` | **Never committed.** Source data stays out of git; rebuild from public sources |
