"""Derive across epochs, promote on replication, score only on a holdout.

The correction this run exists to make: a form derived from one window and
applied elsewhere is a fit to that window, however carefully entity ids and dates
were kept out of it. The parameters carried the window.

So here:

  * Four disjoint epochs, spanning genuinely different regimes.
  * Each is calibrated against **its own** null. No threshold crosses an epoch.
  * A core is promoted only if the SAME invariant identity is independently
    derived in at least two derivation epochs. One appearance is an anecdote.
  * The most recent epoch is a **holdout** the derivation never sees, and it is
    the only place a score is quoted from. Everything else is admission.

Run: python demo/multi_epoch_run.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contract import SourceRegistry
from data_layer import HistoricalDataLayer
from data_layer.entities import ENTITIES, INSTRUMENT_OF, INSTRUMENTS_OF
from harness.bus import Bus
from harness.calibration import build_null_calibration
from harness.claims import EMBEDDING_SPACE_VERSION, Sign
from harness.epochs import DEFAULT_EPOCHS, Epoch
from harness.execution import leak_check, run_universe
from harness.nulls import shuffle_values
from harness.observation import Basis, BasisField, observe
from harness.parameters import UnresolvableParameter, WindowContext
from harness.pipeline import (RunPolicy, compile_strategy, field_phenomena,
                              horizon_volatility, run)
from harness.prediction import Ledger, PredictionRegistered, probability_from_support
from harness.budget import BudgetExhausted, BudgetLedger, harness_version
from harness.coverage import BasisRealization, check_backfillable, compare
from harness.dataset import freeze
from harness.replication import Derivation, group_by_core, replicated_cores
from harness.strategy import resolve_trade_type

STEP = timedelta(days=14)
NULL_RUNS = 8
BY_ID = {e.id: e for e in ENTITIES}

#: The basis is the SAME in every epoch, and it is built from the phenomena
#: available in every epoch. Two sparks are comparable when they share a basis, so
#: a basis that shifts between epochs cannot support a replication claim — and
#: GDELT's editorial-publication series is available in one epoch out of four.
#: Community discourse stands in its own right, not as a substitute for it.
BASIS = Basis(
    id="basis.weekly.attention_multiepoch_v1", resolution="P7D", frame_count=8,
    frame_span=timedelta(days=7),
    fields=(
        BasisField("pageviews_rate", "wikimedia.pageviews", "pageviews"),
        BasisField("price_return", "prices.daily", "price"),
        BasisField("discourse_rate", "hn.stories", "hn_stories"),
        # Real editorial publication, now available in EVERY epoch via the bulk
        # archive. This is what the rate-limited query API could not supply, and
        # its absence is what forced report 002 onto a narrower basis.
        BasisField("news_rate", "gdelt.gkg", "news"),
        BasisField("short_volume_share", "finra.short", "short_volume"),
        BasisField("revenue_yoy", "edgar.xbrl", "fundamental"),
    ),
)

#: GDELT is excluded from the multi-epoch pull, not forgotten: its public API
#: rate-limits to the point of being unusable for a bulk historical fetch, and
#: that is a property of the source worth recording rather than a bug worth
#: retrying around.
SOURCES = ("edgar", "wikimedia", "prices", "finra", "hackernews", "gdelt_bulk")


def windows(epoch: Epoch):
    at = epoch.start
    while at + BASIS.frame_span * BASIS.frame_count <= epoch.end:
        yield at
        at += STEP


def _entity(subject: str) -> str:
    return INSTRUMENT_OF.get(subject, subject)


def epoch_null(layer, registry, epoch: Epoch):
    """Each epoch's tolerance comes from ITS OWN null. A threshold measured in
    2019 is not a fact about 2023."""
    bus = Bus(layer, epoch.start)
    events = tuple(bus.replay(epoch.end))
    records = tuple(e.record for e in events if e.record)

    def one(seed):
        shuffled = {r.id: r for r in shuffle_values(records, registry, seed)}
        swapped = tuple(
            e if e.record is None or e.id not in shuffled
            else type(e)(**{**e.__dict__, "value": shuffled[e.id].value,
                            "record": shuffled[e.id]})
            for e in events)
        ratios = []
        for start in list(windows(epoch))[:3]:
            for ent in ENTITIES:
                scoped = tuple(x for x in swapped if _entity(x.subject) == ent.id)
                ratios += [s.ratio for s in
                           observe(scoped, BASIS, start, registry).separations.values()]
        return ratios

    return build_null_calibration(one, BASIS.id, runs=NULL_RUNS)


def policy_for(cal) -> RunPolicy:
    tol = cal.quantile(0.95)
    return RunPolicy(
        anomaly_z=3.0, anomaly_relative_floor=0.05, moved_tolerance=round(tol, 4),
        moved_tolerance_source=(f"this epoch's own null, q=0.95 over {cal.n} "
                                f"samples; measured FP {cal.false_positive_rate(tol):.3f}"),
        cluster_cap=0.70, specificity_floor=0.30, support_threshold=0.50,
        hysteresis_fraction=0.5, k_broken_legs=2, delta_reality_days=180,
        degraded_multiplier=0.25, support_scale=3.0,
        inference_delay_minutes=15, min_frames_before_deciding=8)


def load(epoch: Epoch):
    return HistoricalDataLayer(sources=SOURCES).preload(epoch.start, epoch.end)


def derive(epoch: Epoch, registry_out: dict) -> tuple[list[Derivation], dict]:
    layer = load(epoch)
    registry = SourceRegistry(tuple(layer.sources()))
    registry_out["registry"] = registry
    cal = epoch_null(layer, registry, epoch)
    policy = policy_for(cal)
    phen = field_phenomena(BASIS, registry)
    out: list[Derivation] = []
    stats = Counter()

    for start in windows(epoch):
        for ent in ENTITIES:
            log = run(layer, BASIS, start, ent.id, ent.instrument, policy, registry)
            if log.spark is None:
                continue
            stats["sparks"] += 1
            if not (log.gate and log.gate["promotable"]):
                continue
            stats["promoted"] += 1
            vol = horizon_volatility(
                tuple(Bus(layer, start).replay(start + BASIS.frame_span * BASIS.frame_count)),
                ent.instrument, BASIS, policy)
            ctx = WindowContext(epoch.id, cal.quantile, vol, cal.n)
            try:
                tt, _ = compile_strategy(log, BASIS, registry,
                                         [e.id for e in ENTITIES], ctx)
            except UnresolvableParameter as e:
                stats["unresolvable"] += 1
                continue
            if tt is None:
                continue
            mech = log.spark.principles["mechanism"].payload
            out.append(Derivation(
                epoch_id=epoch.id, entity=ent.ticker, window_start=start,
                core=tt.core, trade_type=tt, support=log.support.total,
                specificity=getattr(mech, "specificity", 0.0)))
    # What this epoch could ACTUALLY express, recorded so a cross-epoch claim can
    # be refused when the epochs were not observed over the same basis.
    probe_start = next(iter(windows(epoch)))
    probe_events = tuple(Bus(layer, probe_start).replay(
        probe_start + BASIS.frame_span * BASIS.frame_count))
    probe_obs = observe(tuple(e for e in probe_events
                              if _entity(e.subject) == ENTITIES[0].id),
                        BASIS, probe_start, registry)
    realization = BasisRealization.of(probe_obs, BASIS, epoch.id)
    return out, {"layer": layer, "registry": registry, "cal": cal, "policy": policy,
                 "phen": phen, "stats": stats, "realization": realization}


def main():
    es = DEFAULT_EPOCHS

    # ── the dataset is pinned before anything is computed ──────────────────
    from pathlib import Path

    from contract import SourceRegistry as _Reg
    frozen = freeze(Path(".cache/raw"), Path(".cache/gkg_reduced"))
    version = harness_version()
    ledger_budget = BudgetLedger.load()
    ledger_budget.dataset_id = frozen.id
    for e in es.epochs:
        ledger_budget.declare(e.id, sealed=e.holdout, max_opens=3 if e.holdout else None)
    print(f"DATASET  {frozen.short()}  {frozen.file_count} files  "
          f"{frozen.total_bytes / 1e6:.1f} MB")
    print(f"HARNESS  {version}")

    # A basis resting on a source whose history cannot be fetched would be
    # present in some epochs and absent in others. Checked before a single window.
    probe = HistoricalDataLayer(sources=SOURCES)
    check_backfillable(BASIS, _Reg(tuple(probe.sources())))
    print("BASIS    every source supports bulk history\n")

    print("EPOCHS (declared before anything runs)")
    for e in es.epochs:
        print(f"  {e.id}  {e.start:%Y-%m-%d}..{e.end:%Y-%m-%d}  "
              f"{'HOLDOUT' if e.holdout else 'derive '}  {e.regime_note}")
    print(f"  a core must replicate in >= {es.min_replications} derivation epochs\n")

    all_derivations: list[Derivation] = []
    contexts: dict[str, dict] = {}
    realizations: list[BasisRealization] = []

    for epoch in es.derivation():
        print("=" * 78)
        print(f"DERIVATION EPOCH {epoch.id} — {epoch.regime_note}")
        print("=" * 78)
        try:
            ledger_budget.charge(epoch.id, version, "derivation")
        except BudgetExhausted as e:
            print(f"  REFUSED: {e}")
            continue
        derivations, ctx = derive(epoch, {})
        contexts[epoch.id] = ctx
        all_derivations += derivations
        cal = ctx["cal"]
        print(f"  null      {cal.describe()}")
        print(f"  tolerance {ctx['policy'].moved_tolerance}  ({ctx['policy'].moved_tolerance_source})")
        print(f"  {dict(ctx['stats'])}")
        realizations.append(ctx["realization"])
        for core_id, n in Counter(d.core.id for d in derivations).items():
            example = next(d for d in derivations if d.core.id == core_id)
            print(f"  derived {core_id} x{n}  "
                  f"(separation resolved to {example.trade_type.entry['min_separation']}, "
                  f"magnitude {example.trade_type.direction['target_magnitude']})")
        print()

    print("=" * 78 + "\nBASIS COMMENSURABILITY\n" + "=" * 78)
    for r in realizations:
        print(f"  {r.describe()}")
    verdict = compare(realizations, min_coverage=0.75,
                      field_phenomena={k: v.value for k, v in
                                       contexts[realizations[0].epoch_id]["phen"].items()})
    print(f"  verdict: {verdict.verdict} — {verdict.reason}")

    print("\n" + "=" * 78 + "\nREPLICATION\n" + "=" * 78)
    for rep in group_by_core(all_derivations):
        print(f"  {rep.summary(es.min_replications)}")
        print(f"      {rep.core.describe()}")
    promoted = replicated_cores(all_derivations, es, realizations, min_coverage=0.75)
    for rep in group_by_core(all_derivations):
        if rep.refused_reason:
            print(f"  REFUSED {rep.core.id}: {rep.refused_reason}")
    ledger_budget.save()
    print(f"\n{ledger_budget.report()}")
    if not promoted:
        print("\n  No core replicated across epochs. That is the result: nothing "
              "here recurred, so nothing is promoted.")
        return

    # ── the holdout: never seen during derivation ──────────────────────────
    print("\n" + "=" * 78 + "\nHOLDOUT\n" + "=" * 78)
    ledger = Ledger()
    for holdout in es.holdout():
        layer = load(holdout)
        registry = SourceRegistry(tuple(layer.sources()))
        cal = epoch_null(layer, registry, holdout)
        policy = policy_for(cal)
        phen = field_phenomena(BASIS, registry)
        field_of = {v.value: k for k, v in phen.items()}
        print(f"  {holdout.id} — {holdout.regime_note}")
        print(f"  null      {cal.describe()}")
        print(f"  tolerance {policy.moved_tolerance} (resolved from THIS epoch's null, "
              "not the derivation epochs')")

        for rep in promoted:
            core = rep.core
            print(f"\n  applying {core.id}  (replicated in {sorted(rep.epochs)})")
            fired = leaks = 0
            actions = Counter()
            for start in windows(holdout):
                bus = Bus(layer, start)
                events = tuple(bus.replay(start + BASIS.frame_span * BASIS.frame_count))
                for ent in ENTITIES:
                    vol = horizon_volatility(events, ent.instrument, BASIS, policy)
                    ctx = WindowContext(holdout.id, cal.quantile, vol, cal.n)
                    try:
                        tt = resolve_trade_type(
                            core, ctx, spark_ref=f"replicated:{core.id}", basis=BASIS,
                            field_of_phenomenon=field_of, support_total=1.5,
                            degraded_multiplier=policy.degraded_multiplier,
                            support_scale=policy.support_scale,
                            provenance={"replicated_in": sorted(rep.epochs)})
                    except UnresolvableParameter:
                        continue
                    trace = run_universe(
                        events, tt, BASIS, start, [ent.id], registry,
                        entity_of=_entity,
                        inference_delay=timedelta(minutes=policy.inference_delay_minutes),
                        min_frames=policy.min_frames_before_deciding)
                    actions.update(d.action for d in trace.decisions)
                    leaks += len(leak_check(trace))
                    p = probability_from_support(1.5)
                    for d in trace.fired():
                        fired += 1
                        pid = f"pred_{core.id}_{BY_ID[d.entity].ticker}_{d.at:%Y%m%d}"
                        if pid in ledger.registered:
                            continue
                        ledger.register(PredictionRegistered(
                            id=pid, spark_ref=tt.spark_ref, trade_type_ref=core.id,
                            subject=INSTRUMENTS_OF[d.entity][0],
                            sign=Sign(tt.direction["sign"]),
                            magnitude=tt.direction["target_magnitude"],
                            horizon=timedelta(days=tt.direction["horizon_days"]),
                            probability=round(p, 4), declared_scope=core.regime_scope,
                            registered_at=d.at,
                            resolve_by=d.at + timedelta(days=tt.direction["horizon_days"]),
                            basis_id=BASIS.id,
                            embedding_space_version=EMBEDDING_SPACE_VERSION,
                            concept_map_version=layer.concept_map_version,
                            layer_id=layer.layer_id, layer_version=layer.layer_version))
            print(f"    {dict(actions)}   fired {fired}   leak check: "
                  f"{'CLEAN' if not leaks else f'{leaks} FINDINGS'}")

        # resolve
        print(f"\n  {'-' * 74}")
        pending = 0
        for pid, pr in sorted(ledger.registered.items()):
            px = layer.query(pr.subject, "price", (pr.registered_at, pr.resolve_by),
                             as_of=pr.resolve_by)
            if not px or pr.resolve_by > holdout.end + timedelta(days=40):
                pending += 1
                continue
            move = 1.0
            for r in px:
                move *= 1.0 + float(r.value["close_return"])
            res = ledger.resolve(pid, move - 1.0, pr.resolve_by)
            print(f"    {pid[:58]:58s} p={pr.probability} bound=±{pr.magnitude:.4f} "
                  f"realised={res.realized_move:+.4f} "
                  f"{'held' if res.outcome else 'FAILED'}")
        print(f"\n  HOLDOUT SCORE: {ledger.summary()}  ({pending} pending)")
        if ledger.resolved:
            print(f"  by core: {json.dumps(ledger.by_trade_type())}")
        print("\n  This is the only number in this run that is a score. Everything "
              "from the derivation epochs is admission.")


if __name__ == "__main__":
    main()
