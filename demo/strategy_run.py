"""Spark -> generic trade type -> strategy -> execution -> registered prediction
-> resolution -> calibration ledger, scored against a prediction market.

Run: python demo/strategy_run.py

The output is a STRATEGY, not a trade: a parameterised form with no entity or
date inside it, applied across a universe, with sizing wired to the invalidation
state machine.
"""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fixtures import design_intent as di
from fixtures.dataset import (ENT_A, ENT_B, ENT_C, INSTRUMENT_OF, INSTRUMENTS_OF,
                              PM_CONTRACT_ID, REGISTRY, SCENARIOS)
from fixtures.layer import FixtureDataLayer
from harness.bus import Bus
from harness.claims import EMBEDDING_SPACE_VERSION, Sign
from harness.execution import leak_check, run_universe
from harness.pipeline import compile_strategy, run
from harness.prediction import (Ledger, PredictionRegistered,
                                probability_from_support)
from demo.first_spark import BASIS, calibrate, policy_from

UNIVERSE = [ENT_A, ENT_B, ENT_C]      # ENT_C is a bank: no basis coverage at all


def realised_move(layer, instrument, frm, to) -> float:
    """Compounded from daily returns, gated on availability: only prices knowable
    by the resolution instant are used."""
    recs = layer.query(instrument, "price", (frm, to), as_of=to)
    total = 1.0
    for r in recs:
        total *= 1.0 + float(r.value["close_return"])
    return total - 1.0


def market_benchmark(layer, at, outcome_for_us: int) -> dict | None:
    """The market's price at REGISTRATION time — not later. Where a market existed
    on the same resolved question, beating its Brier on N questions is a far
    harder claim than any raw calibration figure."""
    quotes = layer.query("inst_NWS_common", "pm_quote", (at - timedelta(days=7), at),
                         as_of=at)
    if not quotes:
        return None
    latest = quotes[-1]
    p_move = float(latest.value["implied_probability"]["value"])
    p_no_move = 1.0 - p_move            # our claim is the complement
    return {"contract": PM_CONTRACT_ID, "observed_at": latest.event_time.isoformat(),
            "implied_probability_method": latest.value["implied_probability"]["method"],
            "market_probability": round(p_no_move, 4),
            "brier": round((p_no_move - outcome_for_us) ** 2, 6)}


def main():
    cal = calibrate()
    policy = policy_from(cal)
    ledger = Ledger()
    resolution_layers: dict[str, tuple] = {}
    print(f"NULL CONTROL: {cal.describe()}")
    print(f"tolerance {policy.moved_tolerance}  ({policy.moved_tolerance_source})\n")

    for scenario in ("localised", "sustained_attention"):
        spec_meta = SCENARIOS[scenario]
        start = spec_meta["start"]
        layer = FixtureDataLayer(scenarios=(scenario,), subjects=(ENT_A, ENT_B))
        log = run(layer, BASIS, start, ENT_A, INSTRUMENTS_OF[ENT_A][0], policy, REGISTRY)
        if log.spark is None or "mechanism" not in log.spark.principles:
            print(f"{scenario}: no spark\n")
            continue

        tt, strategy = compile_strategy(log, BASIS, REGISTRY, UNIVERSE)
        print("=" * 78)
        if tt is None:
            print(f"SCENARIO {scenario}  ->  NO STRATEGY")
            print("=" * 78)
            print(f"spark {log.spark.id} status={log.spark.status.value}")
            for r in (log.gate or {}).get("reasons", []):
                print(f"   gate: {r}")
            print("   a strategy is compiled only from a promoted spark\n")
            continue
        print(f"SCENARIO {scenario}  ->  TRADE TYPE {tt.id}")
        print("=" * 78)

        forbidden = tuple([ENT_A, ENT_B, ENT_C, *INSTRUMENT_OF, "2019", "2020"])
        generic, found = tt.is_generic(forbidden)
        print(f"generic: {generic}" + (f"  LEAKED LITERALS {found}" if found else
                                       "  (no entity or date anywhere in the form)"))
        print(f"stance      {tt.stance}   regime scope: {tt.regime_scope}")
        print(f"entry       {tt.entry['residue_phenomenon']} residue, shape="
              f"{tt.entry['required_shape']}, separation >= {tt.entry['min_separation']}")
        print(f"            predicate: {tt.entry['predicate']}")
        print(f"            requires invariant: {tt.entry['required_invariant_phenomena']}")
        print(f"direction   {tt.direction['sign']}, |move| <= "
              f"{tt.direction['target_magnitude']} over {tt.direction['horizon_days']}d")
        print(f"exit        degraded -> {tt.exit['on_degraded']}; "
              f"invalidated -> {tt.exit['on_invalidated']}")
        print(f"sizing      base={tt.sizing['base']} x support="
              f"{tt.sizing['support_multiplier']}  (degraded x{tt.sizing['degraded_multiplier']})")
        print(f"universe    coverage requirement: {tt.universe['requires_phenomena']}")
        print(f"provenance  {json.dumps(tt.provenance)}")

        # ── apply across the universe ───────────────────────────────────────
        bus = Bus(FixtureDataLayer(scenarios=(scenario,), subjects=(ENT_A, ENT_B)), start)
        events = tuple(bus.replay(start + BASIS.frame_span * BASIS.frame_count))
        trace = run_universe(
            events, tt, BASIS, start, UNIVERSE, REGISTRY,
            entity_of=lambda s: INSTRUMENT_OF.get(s, s),
            inference_delay=timedelta(minutes=policy.inference_delay_minutes),
            min_frames=policy.min_frames_before_deciding)

        print(f"\nSTRATEGY {strategy.id}  ({strategy.kind})  universe={len(UNIVERSE)}")
        outcomes: dict[str, list[str]] = {}
        for d in trace.decisions:
            outcomes.setdefault(d.entity, []).append(d.action)
        for entity, actions in outcomes.items():
            uniq = {a: actions.count(a) for a in dict.fromkeys(actions)}
            print(f"   {entity}  {uniq}")

        leaks = leak_check(trace)
        print(f"   leak check: {'CLEAN' if not leaks else f'{len(leaks)} FINDINGS'} "
              f"over {len(trace.decisions)} decisions, "
              f"{sum(len(d.conditioned_on) for d in trace.decisions)} conditioning events")

        # ── register a prediction per entity the type fired on ──────────────
        fired = trace.fired()
        probability = probability_from_support(log.support.total)
        for d in fired:
            instrument = INSTRUMENTS_OF[d.entity][0]
            pid = f"pred_{tt.id}_{d.entity}_{d.at:%Y%m%d}"
            if pid in ledger.registered:
                continue
            resolution_layers[pid] = (layer, scenario)
            ledger.register(PredictionRegistered(
                id=pid, spark_ref=log.spark.id, trade_type_ref=tt.id,
                subject=instrument, sign=Sign(tt.direction["sign"]),
                magnitude=tt.direction["target_magnitude"],
                horizon=timedelta(days=tt.direction["horizon_days"]),
                probability=round(probability, 4),
                declared_scope=tt.regime_scope, registered_at=d.at,
                resolve_by=d.at + timedelta(days=tt.direction["horizon_days"]),
                basis_id=BASIS.id, embedding_space_version=EMBEDDING_SPACE_VERSION,
                concept_map_version=layer.concept_map_version,
                layer_id=layer.layer_id, layer_version=layer.layer_version))
        print(f"   positions taken: {len(trace.positions())} "
              f"(stance={tt.stance}, so firing need not mean a position)")
        print(f"   registered {len(fired)} predictions at p={probability:.4f} "
              f"(from accumulated support {log.support.total} in log-odds)")
        print()

    # ── resolve everything whose horizon has elapsed ────────────────────────
    print("=" * 78)
    print("CALIBRATION LEDGER")
    print("=" * 78)
    pending = []
    for pid, p in sorted(ledger.registered.items()):
        layer, scenario = resolution_layers[pid]
        from fixtures.dataset import TAIL_WEEKS
        data_ends = (SCENARIOS[scenario]["start"]
                     + BASIS.frame_span * (BASIS.frame_count + TAIL_WEEKS))
        if p.resolve_by > data_ends:
            # Forward-only scoring means no scoreboard for weeks. Pending is the
            # honest state, not an inconvenience to design around.
            pending.append((pid, p))
            continue
        move = realised_move(layer, p.subject, p.registered_at, p.resolve_by)
        outcome = 1 if abs(move) <= p.magnitude else 0
        bench = market_benchmark(layer, p.registered_at, outcome)
        r = ledger.resolve(pid, move, p.resolve_by, benchmark=bench)
        mark = "held" if r.outcome else "FAILED"
        print(f"   {pid}")
        print(f"      p={p.probability}  realised={r.realized_move:+.5f}  "
              f"claim {mark}  brier={r.brier}"
              + (f"  | market p={bench['market_probability']} brier={bench['brier']}"
                 if bench else "  | no market on this question"))
    for pid, p in pending:
        print(f"   {pid}\n      PENDING — horizon ends {p.resolve_by:%Y-%m-%d}, "
              f"beyond available data")
    print(f"\n   {ledger.summary()}")
    print(f"   by trade type: {json.dumps(ledger.by_trade_type(), indent=6)}")
    print(f"   vs market:     {json.dumps(ledger.versus_benchmark())}")


if __name__ == "__main__":
    main()
