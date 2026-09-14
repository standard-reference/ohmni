"""Rebuild the pinned dataset in a fresh container, and prove it matches.

Why this exists rather than a committed corpus: `01-system-specification-v3.md`
declares one discipline — **never let source data into git** — and that is what
keeps the licensing option free at zero cost. So the repository carries the
manifest (hashes, not data) and this script reconstructs the corpus from the
public sources it came from.

The cost is real and worth stating: a cold rebuild refetches ~120 MB across the
deterministic adapters, and the GKG reduction costs ~34 minutes and ~23 GB of
transfer because each day's 26 MB archive is filtered and discarded. That is the
price of the discipline, paid once per container.

The point is the verification at the end. A rebuild that cannot be proved
identical is a different dataset wearing the same name, and every budget entry
pinned to the old freeze would be silently meaningless.

    python scripts/rebuild_dataset.py            # rebuild, then verify
    python scripts/rebuild_dataset.py --verify   # verify only
"""
from __future__ import annotations

import sys
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_layer import HistoricalDataLayer
from data_layer.adapters import gdelt_bulk
from data_layer.entities import ENTITIES
from harness.dataset import verify_against_manifest, write_manifest
from harness.epochs import DEFAULT_EPOCHS

MANIFEST = Path(".dataset/manifest.json.gz")
ROOTS = (Path(".cache/raw"), Path(".cache/gkg_reduced"))
SOURCES = ("edgar", "wikimedia", "prices", "finra", "hackernews", "gdelt_bulk")


def rebuild() -> None:
    t0 = time.time()
    for epoch in DEFAULT_EPOCHS.epochs:
        print(f"[{time.time() - t0:5.0f}s] {epoch.id} gkg", flush=True)
        day = epoch.start
        while day <= epoch.end + timedelta(days=45):
            gdelt_bulk.fetch_raw(day)
            day += timedelta(days=1)

        print(f"[{time.time() - t0:5.0f}s] {epoch.id} adapters", flush=True)
        HistoricalDataLayer(sources=SOURCES).preload(epoch.start, epoch.end)
    print(f"[{time.time() - t0:5.0f}s] rebuild complete")


def main() -> int:
    if "--verify" not in sys.argv:
        rebuild()
    if not MANIFEST.exists():
        print(f"no manifest at {MANIFEST}; writing one from the current corpus")
        print("  freeze:", write_manifest(MANIFEST, *ROOTS).id)
        return 0
    diff = verify_against_manifest(MANIFEST, *ROOTS)
    print(("OK   " if diff.ok else "DIFF ") + diff.describe())
    if not diff.ok:
        print("\nThe rebuilt corpus is NOT the dataset the budget ledger is pinned "
              "to. Runs against it are not comparable with anything recorded "
              "against the old freeze — either recover the original or declare a "
              "new dataset and reset the ledger.")
    return 0 if diff.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
