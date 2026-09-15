"""Run 003 — the multi-epoch protocol over null markets.

**The question, from drift audit 001 part 4:** report 003 promoted 3 cores, all
inside 2021H1, out of 87 sparks across three epochs. Is that surprising?

The protocol is run unchanged over markets with no structure. If single-epoch
promotion clusters appear at a comparable rate in the nulls, then 2021H1 is what
chance gives, report 002's attention-without-discourse explanation is post-hoc
rationalisation of noise, and both reports should say so.

DECLARED BEFORE RUNNING — everything below is fixed in advance, and the reading
of the result is fixed with it. Choosing either after seeing the count is how a
null control becomes a formality.

    seeds                 10        (the declared minimum)
    null generator        block_bootstrap, block = 5 observations
    inner calibration     4 runs    (reduced from the real run's 8, for cost;
                                     this makes each epoch's tolerance noisier,
                                     which errs toward MORE null promotions, not
                                     fewer — the conservative direction)
    epochs, entities,
    basis, templates      identical to report 003
    cluster definition    a core with >= 2 promotions, all inside ONE epoch
                          (2021H1's was 3 promotions in 1 epoch)

    0 clusters over 10 seeds   -> 2021H1 is real; the machinery discriminates
    >= 2 clusters              -> 2021H1 is what chance gives; amend reports 002/003
    exactly 1 cluster          -> inconclusive; more seeds or more epochs needed

Run: python demo/run003_null_protocol.py [seeds]
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contract import SourceRegistry
from data_layer import HistoricalDataLayer
from data_layer.entities import ENTITIES
from harness.bus import Bus
from harness.budget import harness_version
from harness.calibration import build_null_calibration
from harness.dataset import freeze
from harness.epochs import DEFAULT_EPOCHS, Epoch
from harness.nulls import block_bootstrap
from harness.observation import observe
from harness.parameters import UnresolvableParameter, WindowContext
from harness.pipeline import (RunPolicy, compile_strategy, field_phenomena,
                              horizon_volatility, run)

from demo.multi_epoch_run import BASIS, SOURCES, _entity, windows

SEEDS = 10
BLOCK = 5
INNER_CALIBRATION_RUNS = int(__import__('os').environ.get('INNER_CAL', 4))
MIN_CLUSTER = 2          # promotions inside one epoch to count as a cluster


class NullLayer:
    """A real layer with its values block-resampled. Timestamps, availability,
    lineage and status all stay exactly as they were — only the measured values
    move, so the guard and the gating are testing the same thing they always do."""

    def __init__(self, base: HistoricalDataLayer, registry, seed: int):
        self._base = base
        self.layer_id = f"{base.layer_id}.null.block{BLOCK}.seed{seed}"
        self.layer_version = base.layer_version
        self.concept_map_version = base.concept_map_version
        self.cluster_version = base.cluster_version
        self._records = block_bootstrap(base._all(), registry, seed, block=BLOCK)

    def sources(self):
        return self._base.sources()

    def capabilities(self):
        return self._base.capabilities()

    def _all(self):
        return self._records

    def stream(self, start, end, subjects):
        wanted = set(subjects) if subjects else None
        for r in self._records:
            if start <= r.knowable_at <= end and (
                    wanted is None or r.subject in wanted
                    or _entity(r.subject) in wanted):
                yield r

    def query(self, subject, kind, window, as_of):
        return self._base.query.__func__(self, subject, kind, window, as_of)


def epoch_tolerance(layer, registry, epoch: Epoch):
    bus = Bus(layer, epoch.start)
    events = tuple(bus.replay(epoch.end))
    records = tuple(e.record for e in events if e.record)

    def one(seed):
        shuffled = {r.id: r for r in block_bootstrap(records, registry, seed, BLOCK)}
        swapped = tuple(
            e if e.record is None or e.id not in shuffled
            else type(e)(**{**e.__dict__, "value": shuffled[e.id].value,
                            "record": shuffled[e.id]})
            for e in events)
        out = []
        for start in list(windows(epoch))[:3]:
            for ent in ENTITIES:
                scoped = tuple(x for x in swapped if _entity(x.subject) == ent.id)
                out += [s.ratio for s in
                        observe(scoped, BASIS, start, registry).separations.values()]
        return out

    return build_null_calibration(one, BASIS.id, runs=INNER_CALIBRATION_RUNS)


def policy_for(cal) -> RunPolicy:
    tol = cal.quantile(0.95)
    return RunPolicy(
        anomaly_z=3.0, anomaly_relative_floor=0.05, moved_tolerance=round(tol, 4),
        moved_tolerance_source=f"null-of-null q=0.95 over {cal.n} samples",
        cluster_cap=0.70, specificity_floor=0.30, support_threshold=0.50,
        hysteresis_fraction=0.5, k_broken_legs=2, delta_reality_days=180,
        degraded_multiplier=0.25, support_scale=3.0,
        inference_delay_minutes=15, min_frames_before_deciding=8)


def one_seed(bases: dict, seed: int) -> dict:
    """Run the whole derivation protocol once over null markets."""
    per_epoch: dict[str, Counter] = {}
    for epoch in DEFAULT_EPOCHS.derivation():
        base, registry = bases[epoch.id]
        null = NullLayer(base, registry, seed)
        cal = epoch_tolerance(null, registry, epoch)
        policy = policy_for(cal)
        promoted: Counter = Counter()
        for start in windows(epoch):
            for ent in ENTITIES:
                log = run(null, BASIS, start, ent.id, ent.instrument, policy, registry)
                if log.spark is None or not (log.gate and log.gate["promotable"]):
                    continue
                evs = tuple(Bus(null, start).replay(
                    start + BASIS.frame_span * BASIS.frame_count))
                vol = horizon_volatility(evs, ent.instrument, BASIS, policy)
                ctx = WindowContext(epoch.id, cal.quantile, vol, cal.n)
                try:
                    tt, _ = compile_strategy(log, BASIS, registry,
                                             [e.id for e in ENTITIES], ctx)
                except UnresolvableParameter:
                    continue
                if tt is not None:
                    promoted[tt.core.id] += 1
        per_epoch[epoch.id] = promoted
    return per_epoch


def clusters(per_epoch: dict[str, Counter]) -> list[tuple[str, str, int]]:
    """Cores promoted >= MIN_CLUSTER times inside exactly one epoch — the shape
    of the 2021H1 result this run exists to test."""
    by_core: dict[str, dict[str, int]] = {}
    for eid, counts in per_epoch.items():
        for core, n in counts.items():
            by_core.setdefault(core, {})[eid] = n
    return [(core, next(iter(spread)), next(iter(spread.values())))
            for core, spread in by_core.items()
            if len(spread) == 1 and next(iter(spread.values())) >= MIN_CLUSTER]


def main() -> None:
    seeds = int(sys.argv[1]) if len(sys.argv) > 1 else SEEDS
    frozen = freeze(Path(".cache/raw"), Path(".cache/gkg_reduced"))
    print(f"RUN 003 — the multi-epoch protocol over null markets")
    print(f"  dataset  {frozen.short()}   harness {harness_version()}")
    print(f"  declared seeds={seeds} block={BLOCK} inner_calibration="
          f"{INNER_CALIBRATION_RUNS} min_cluster={MIN_CLUSTER}")
    print(f"  real result being tested: 3 promotions, all in 2021H1, from 87 sparks\n")

    bases = {}
    for epoch in DEFAULT_EPOCHS.derivation():
        layer = HistoricalDataLayer(sources=SOURCES).preload(epoch.start, epoch.end)
        bases[epoch.id] = (layer, SourceRegistry(tuple(layer.sources())))

    t0 = time.time()
    found, totals = [], Counter()
    for seed in range(seeds):
        per_epoch = one_seed(bases, seed)
        cl = clusters(per_epoch)
        found.append(cl)
        for eid, counts in per_epoch.items():
            totals[eid] += sum(counts.values())
        summary = ", ".join(f"{e}={sum(c.values())}" for e, c in per_epoch.items())
        print(f"  seed {seed:2d}  [{time.time() - t0:5.0f}s]  promotions {summary}"
              f"   clusters: {[(c, e, n) for c, e, n in cl] or 'none'}", flush=True)

    total_clusters = sum(len(c) for c in found)
    seeds_with = sum(1 for c in found if c)
    print(f"\n  RESULT over {seeds} null seeds")
    print(f"    total promotions per epoch: {dict(totals)}")
    print(f"    single-epoch clusters (>= {MIN_CLUSTER} promotions in one epoch): "
          f"{total_clusters}, in {seeds_with} of {seeds} seeds")
    # The criterion is on CLUSTER count, exactly as drift audit 001 part 4
    # declared it — not on how many seeds produced one. Paraphrasing a declared
    # reading after seeing the result is how a pre-registration stops being one.
    if total_clusters == 0:
        verdict = ("2021H1's cluster is REAL by the declared reading. The "
                   "machinery discriminates, and report 002's explanation is "
                   "worth taking seriously.")
    elif total_clusters >= 2:
        verdict = ("2021H1 is WHAT CHANCE GIVES by the declared reading. The "
                   "substantive explanation is post-hoc rationalisation of "
                   "noise; reports 002 and 003 need amending.")
    else:
        verdict = ("INCONCLUSIVE by the declared reading — one cluster. More "
                   "seeds or more epochs before either reading is supportable.")
    print(f"    {verdict}")
    Path("docs/reports/004-null-result.json").write_text(json.dumps(
        {"dataset": frozen.id, "harness": harness_version(), "seeds": seeds,
         "block": BLOCK, "inner_calibration": INNER_CALIBRATION_RUNS,
         "min_cluster": MIN_CLUSTER, "promotions_per_epoch": dict(totals),
         "total_clusters": total_clusters, "seeds_with_clusters": seeds_with,
         "verdict": verdict}, indent=2))


if __name__ == "__main__":
    main()
