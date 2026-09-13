"""The whole pipeline over real historical data, replayed as a time-lapsed stream.

Six entities, six months, five real sources. Rolling 8-week observation windows
stepping forward two weeks at a time, each one seeing only what was knowable by
its own end.

Everything the fixture run establishes structurally is re-established here against
data nobody authored — which is the only way to find out whether the seam holds.

Run: python demo/historical_run.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conformance import run_conformance
from contract import SourceRegistry
from data_layer import HistoricalDataLayer
from data_layer.entities import BY_TICKER, ENTITIES, INSTRUMENT_OF, INSTRUMENTS_OF

BY_TICKER_BY_ID = {e.id: e.ticker for e in ENTITIES}
from harness.bus import Bus
from harness.calibration import build_null_calibration
from harness.claims import EMBEDDING_SPACE_VERSION, Sign
from harness.execution import leak_check, run_universe
from harness.manifest import RunManifest
from harness.nulls import shuffle_values
from harness.observation import Basis, BasisField, observe
from harness.obligations import report as obligations_report
from harness.pipeline import RunPolicy, compile_strategy, run
from harness.prediction import Ledger, PredictionRegistered, probability_from_support

START = datetime(2023, 1, 3, tzinfo=timezone.utc)
END = datetime(2023, 6, 30, tzinfo=timezone.utc)
STEP = timedelta(days=14)
NULL_RUNS = 12
NULL_QUANTILE = 0.95

#: The same declared stance as the fixture basis, pointed at real emissions.
#: `revenue_yoy` is quarterly and therefore not representable at this resolution —
#: the same refusal, now against a real filing cadence.
BASIS = Basis(
    id="basis.weekly.attention_real_v1",
    resolution="P7D",
    frame_count=8,
    frame_span=timedelta(days=7),
    fields=(
        BasisField("pageviews_rate", "wikimedia.pageviews", "pageviews"),
        BasisField("price_return", "prices.daily", "price"),
        BasisField("news_rate", "gdelt.news", "news"),
        BasisField("short_volume_share", "finra.short", "short_volume"),
        BasisField("revenue_yoy", "edgar.xbrl", "fundamental"),
    ),
)


def load() -> HistoricalDataLayer:
    return HistoricalDataLayer().preload(START, END)


def window_starts():
    at = START
    while at + BASIS.frame_span * BASIS.frame_count <= END:
        yield at
        at += STEP


def calibrate(layer, registry):
    """Nulls first. The tolerance comes from the control's own distribution, so it
    arrives with a measured false-positive rate rather than a preference."""
    bus = Bus(layer, START)
    events = tuple(bus.replay(END))
    records = tuple(e.record for e in events if e.record)

    def one_null(seed):
        shuffled = shuffle_values(records, registry, seed)
        by_id = {r.id: r for r in shuffled}
        swapped = tuple(
            e if e.record is None or e.id not in by_id
            else type(e)(**{**e.__dict__, "value": by_id[e.id].value,
                            "record": by_id[e.id]})
            for e in events)
        ratios = []
        for start in list(window_starts())[:3]:
            for entity in (e.id for e in ENTITIES):
                scoped = tuple(x for x in swapped
                               if _entity(x.subject) == entity)
                obs = observe(scoped, BASIS, start, registry)
                ratios += [s.ratio for s in obs.separations.values()]
        return ratios

    return build_null_calibration(one_null, BASIS.id, runs=NULL_RUNS)


def _entity(subject: str) -> str:
    return INSTRUMENT_OF.get(subject, subject)


def policy_from(cal) -> RunPolicy:
    tol = cal.quantile(NULL_QUANTILE)
    return RunPolicy(
        anomaly_z=3.0, anomaly_relative_floor=0.05,
        moved_tolerance=round(tol, 4),
        moved_tolerance_source=(f"null q={NULL_QUANTILE} over {cal.n} samples from "
                                f"{cal.runs} shuffles of the real stream; measured "
                                f"false-positive rate {cal.false_positive_rate(tol):.3f}"),
        cluster_cap=0.70, specificity_floor=0.30, support_threshold=0.50,
        hysteresis_fraction=0.5, k_broken_legs=2, delta_reality_days=180,
        degraded_multiplier=0.25, support_scale=3.0,
        inference_delay_minutes=15, min_frames_before_deciding=8)


def main():
    print("loading (fetch is cached; normalize is pure) ...", flush=True)
    layer = load()
    registry = SourceRegistry(tuple(layer.sources()))
    records = layer._all()
    print(f"{len(records)} records  "
          f"{dict(Counter(r.source_id for r in records))}\n")

    # ── 1. does a REAL layer pass the same suite the fixture does? ──────────
    print("=" * 78 + "\nCONFORMANCE (the same suite, no special cases)\n" + "=" * 78)
    report = run_conformance(layer)
    print(f"  {report.summary()}")
    for r in report.results:
        if r.outcome.value != "pass":
            print(f"  {r.outcome.value.upper():5s} {r.id}: {r.detail[:96]}")

    # ── 2. what does the harness lose against this layer? ───────────────────
    print("\n" + "=" * 78 + "\nOBLIGATIONS\n" + "=" * 78)
    manifest = RunManifest.for_layer(layer)
    print(obligations_report(manifest))
    print(f"  contaminated: {manifest.contaminated}")
    for note in manifest.degradation_notes:
        print(f"  - {note[:110]}")

    # ── 3. the point-in-time test, on a real restatement ────────────────────
    print("\n" + "=" * 78 + "\nPOINT-IN-TIME: Intel H1 2022 revenue\n" + "=" * 78)
    intc = BY_TICKER["INTC"]
    for as_of in (datetime(2023, 1, 1, tzinfo=timezone.utc),
                  datetime(2025, 1, 1, tzinfo=timezone.utc)):
        got = layer.query(intc.id, "fundamental",
                          (datetime(2022, 1, 1, tzinfo=timezone.utc),
                           datetime(2022, 7, 3, tzinfo=timezone.utc)), as_of=as_of)
        ytd = [r for r in got if r.value["span"] == "year_to_date"]
        for r in ytd:
            print(f"  as_of {as_of:%Y-%m-%d}: {r.value['period_end']} "
                  f"{r.value['span']} = ${int(r.value['amount'])/1e9:.3f}B "
                  f"(filed {r.knowable_at:%Y-%m-%d}, {r.value['form']}, "
                  f"chain {r.revision.index + 1}/{r.revision.chain_length})")

    # ── 4. the null control, then the stream ───────────────────────────────
    print("\n" + "=" * 78 + "\nNULL CONTROL\n" + "=" * 78)
    cal = calibrate(layer, registry)
    policy = policy_from(cal)
    print(f"  {cal.describe()}")
    print(f"  tolerance {policy.moved_tolerance} — {policy.moved_tolerance_source}")

    print("\n" + "=" * 78 + "\nTIME-LAPSED STREAM\n" + "=" * 78)
    ledger = Ledger()
    sparks, promoted, strategies = 0, 0, {}
    rejection_reasons = Counter()
    coverage_gaps = Counter()

    for start in window_starts():
        for ent in ENTITIES:
            log = run(layer, BASIS, start, ent.id, ent.instrument, policy, registry)
            for a in log.coverage_gaps:
                coverage_gaps[a.phenomenon] += 1
            if log.spark is None:
                continue
            sparks += 1
            for r in log.spark.rejected:
                for reason in r["reasons"]:
                    if "not fatal" not in reason:
                        rejection_reasons[reason.split(":")[0]] += 1
            if log.gate and log.gate["promotable"]:
                promoted += 1
                tt, spec = compile_strategy(log, BASIS, registry,
                                            [e.id for e in ENTITIES])
                if tt:
                    strategies.setdefault(tt.id, []).append(
                        (start, ent.ticker, log, tt))

    print(f"  windows      {len(list(window_starts()))} x {len(ENTITIES)} entities")
    print(f"  sparks       {sparks} opened")
    print(f"  promoted     {promoted}")
    print(f"  trade types  {sorted(strategies)}")
    print(f"  mechanism rejections: {dict(rejection_reasons)}")
    print(f"  out-of-basis anomalies (coverage feedback): {dict(coverage_gaps)}")

    if not strategies:
        print("\n  No strategy promoted. That is a result, not a failure — the "
              "rejections above say why.")
        return

    # ── 5. apply each promoted form across the universe, and score it ──────
    print("\n" + "=" * 78 + "\nSTRATEGIES\n" + "=" * 78)
    universe = [e.id for e in ENTITIES]
    all_windows = list(window_starts())
    for tt_id, hits in sorted(strategies.items()):
        _, _, log, tt = hits[0]
        derived_from = {(w, t) for w, t, _, _ in hits}
        generic, leaked = tt.is_generic(
            tuple([e.id for e in ENTITIES] + [e.instrument for e in ENTITIES]
                  + [e.ticker for e in ENTITIES] + ["2023", "2022"]))
        print(f"\n{tt_id}   derived from {len(hits)} promoted sparks "
              f"({', '.join(sorted({t for _, t, _, _ in hits}))})")
        print(f"  generic: {generic}" + (f"  LEAKED {leaked}" if leaked else ""))
        print(f"  stance {tt.stance}; entry {tt.entry['residue_phenomenon']} "
              f"shape={tt.entry['required_shape']} sep>={tt.entry['min_separation']}")
        print(f"  requires invariant: {tt.entry['required_invariant_phenomena']}")
        print(f"  direction {tt.direction['sign']} |move|<={tt.direction['target_magnitude']} "
              f"over {tt.direction['horizon_days']}d; sizing base={tt.sizing['base']} "
              f"x support={tt.sizing['support_multiplier']}")

        # The form is generic, so it is applied at EVERY window across the whole
        # universe — that is the only thing that distinguishes it from a thesis.
        actions, leaks_total, in_sample, out_sample = Counter(), 0, 0, 0
        p = probability_from_support(log.support.total)
        for start in all_windows:
            bus = Bus(layer, start)
            events = tuple(bus.replay(start + BASIS.frame_span * BASIS.frame_count))
            trace = run_universe(events, tt, BASIS, start, universe, registry,
                                 entity_of=_entity,
                                 inference_delay=timedelta(minutes=policy.inference_delay_minutes),
                                 min_frames=policy.min_frames_before_deciding)
            actions.update(d.action for d in trace.decisions)
            leaks_total += len(leak_check(trace))
            for d in trace.fired():
                ticker = BY_TICKER_BY_ID[d.entity]
                if (start, ticker) in derived_from:
                    in_sample += 1
                else:
                    out_sample += 1
                pid = f"pred_{tt.id}_{ticker}_{d.at:%Y%m%d}"
                if pid in ledger.registered:
                    continue
                ledger.register(PredictionRegistered(
                    id=pid, spark_ref=log.spark.id, trade_type_ref=tt.id,
                    subject=INSTRUMENTS_OF[d.entity][0], sign=Sign(tt.direction["sign"]),
                    magnitude=tt.direction["target_magnitude"],
                    horizon=timedelta(days=tt.direction["horizon_days"]),
                    probability=round(p, 4), declared_scope=tt.regime_scope,
                    registered_at=d.at,
                    resolve_by=d.at + timedelta(days=tt.direction["horizon_days"]),
                    basis_id=BASIS.id, embedding_space_version=EMBEDDING_SPACE_VERSION,
                    concept_map_version=layer.concept_map_version,
                    layer_id=layer.layer_id, layer_version=layer.layer_version))
        print(f"  applied at {len(all_windows)} windows x {len(universe)} entities: "
              f"{dict(actions)}")
        print(f"  firings: {in_sample} in-sample (the windows it was derived from), "
              f"{out_sample} elsewhere")
        print(f"  leak check across every window: "
              f"{'CLEAN' if not leaks_total else f'{leaks_total} FINDINGS'}")

    # ── 6. resolve what the data can resolve ───────────────────────────────
    print("\n" + "=" * 78 + "\nCALIBRATION LEDGER\n" + "=" * 78)
    pending = 0
    for pid, pr in sorted(ledger.registered.items()):
        if pr.resolve_by > END:
            pending += 1
            continue
        px = layer.query(pr.subject, "price", (pr.registered_at, pr.resolve_by),
                         as_of=pr.resolve_by)
        if not px:
            pending += 1
            continue
        move = 1.0
        for r in px:
            move *= 1.0 + float(r.value["close_return"])
        res = ledger.resolve(pid, move - 1.0, pr.resolve_by)
        print(f"  {pid[:62]:62s} p={pr.probability} realised={res.realized_move:+.4f} "
              f"{'held' if res.outcome else 'FAILED'} brier={res.brier}")
    print(f"\n  {ledger.summary()}   ({pending} pending — horizon beyond the data)")
    if ledger.resolved:
        print(f"  by trade type: {json.dumps(ledger.by_trade_type())}")
    print("\n  NOTE: this run is marked contaminated for survivorship — the universe "
          "is six names that still exist.\n  In-sample firings are admission, not "
          "score: the form was derived from windows it is then applied to.")


if __name__ == "__main__":
    main()
