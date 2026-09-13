"""Data layer -> bus -> graph -> anomaly -> spark. One spark, end to end.

Run: python demo/first_spark.py
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fixtures import design_intent as di
from fixtures.dataset import ENT_A, INST_A, REGISTRY, SCENARIOS
from fixtures.layer import FixtureDataLayer
from harness.bus import Bus
from harness.calibration import build_null_calibration
from harness.mechanism import specificity_of
from harness.observation import observe
from harness.pipeline import RunPolicy, run

BASIS = di.fixture_basis()
NULL_RUNS = 25
NULL_QUANTILE = 0.95


def _obs(scenario, shuffled, seed=0):
    spec = SCENARIOS[scenario]
    bus = Bus(FixtureDataLayer(scenarios=(scenario,), shuffled=shuffled, shuffle_seed=seed),
              spec["start"])
    events = tuple(bus.replay(spec["start"] + BASIS.frame_span * BASIS.frame_count))
    return observe(events, BASIS, spec["start"], REGISTRY)


def calibrate():
    """Nulls run first. They are cheap, and if the pipeline promotes anything here
    then false-discovery control is broken and every downstream result is
    meaningless."""
    return build_null_calibration(
        lambda seed: [s.ratio for sc in SCENARIOS
                      for s in _obs(sc, True, seed).separations.values()],
        BASIS.id, runs=NULL_RUNS)


def policy_from(cal) -> RunPolicy:
    tolerance = cal.quantile(NULL_QUANTILE)
    return RunPolicy(
        anomaly_z=3.0,
        anomaly_relative_floor=0.05,
        moved_tolerance=round(tolerance, 4),
        moved_tolerance_source=(
            f"null q={NULL_QUANTILE} over {cal.n} samples; "
            f"measured false-positive rate {cal.false_positive_rate(tolerance):.3f}"),
        cluster_cap=0.70,
        # BOOTSTRAP values. The specificity floor cannot be set correctly until
        # the calibration ledger has resolved predictions to punish over-narrow
        # claims after the fact. These are placeholders that say so, not answers.
        specificity_floor=0.30,
        support_threshold=0.50,
        hysteresis_fraction=0.5,
        k_broken_legs=2,
        delta_reality_days=180,
        # `degraded` cuts to a quarter, not to 90%. Hysteresis converts
        # false-kills into slow-kills, and that trade is only acceptable if
        # degraded sizing is aggressive rather than cosmetic.
        degraded_multiplier=0.25,
        support_scale=3.0,
        inference_delay_minutes=15,
        min_frames_before_deciding=6,
    )


def show(log, scenario):
    print(f"\n{'=' * 78}\nSCENARIO: {scenario}\n{'=' * 78}")
    m = log.manifest
    print(f"layer       {m.layer_id} v{m.layer_version}  contract {m.contract_version}")
    print(f"manifest    {m.event_set_hash()[:26]}...  events={m.event_count}  "
          f"contaminated={m.is_contaminated}")
    print(f"tolerance   {log.policy.moved_tolerance}  ({log.policy.moved_tolerance_source})")

    print(f"\n-- TRIGGER {'-' * 66}")
    for a in log.anomalies[:4]:
        print(f"   {a.phenomenon:22s} {a.direction} {a.magnitude:+8.2f}σ   {a.edge_id}")
    if not log.anomalies:
        print("   no threshold crossing — no spark opened")

    print(f"\n-- OBSERVATION {'-' * 62}")
    for name, s in log.observation.separations.items():
        state = "MOVED    " if name in log.moved else "invariant"
        print(f"   {state} {name:20s} separation={s.ratio:6.2f}  shape={s.shape:17s}"
              f" conf={s.confidence}")
    for name, reason in log.observation.not_representable.items():
        print(f"   {'n/a':9s} {name:20s} not representable: {reason}")

    if log.spark is None:
        print("\n   no spark\n")
        return

    print(f"\n-- MECHANISM {'-' * 64}")
    for c in log.candidates:
        mark = "ACCEPTED" if c.accepted else "rejected"
        print(f"   {mark} {c.template.id}")
        for r in c.reasons:
            print(f"            - {r}")
    mech = log.spark.principles.get("mechanism")
    if mech and mech.payload:
        p = mech.payload.predicted
        print(f"\n   predicted effect: subject={p.subject} sign={p.sign.value} "
              f"|move| <= {p.magnitude} over {p.horizon.days}d")
        print(f"   specificity={specificity_of(mech.payload, len(log.moved), len(log.invariant))}")
        print(f"   story: {mech.payload.template.story}")

    if log.support:
        print(f"\n-- CORROBORATION {'-' * 60}")
        for leg in log.support.legs:
            cap = f"  [capped by {leg.capped_by}]" if leg.capped_by else ""
            print(f"   {leg.source_id:22s} {leg.phenomenon.value:22s} "
                  f"align={leg.alignment} indep={leg.independence} "
                  f"potency={leg.potency} -> +{leg.support_contribution}{cap}")
        print(f"   {log.support.summary()}")

    if log.tree:
        print(f"\n-- INVALIDATION {'-' * 61}")
        for child in log.tree.children:
            print(f"   [{child.state.value:9s}] {child.scope:14s} {child.kind:24s} N={child.hysteresis_n}")
            print(f"                {child.note}")
        print(f"   thesis state: {log.thesis.value}")

    print(f"\n-- GATE {'-' * 69}")
    print(f"   status: {log.spark.status.value}")
    if log.gate:
        print(f"   promotable={log.gate['promotable']} "
              f"specificity={log.gate['specificity']} support={log.gate['support']}")
        for r in log.gate["reasons"]:
            print(f"   - {r}")
    for n in log.spark.notes:
        print(f"   note: {n}")


def main():
    cal = calibrate()
    print(f"NULL CONTROL (runs first): {cal.describe()}")
    policy = policy_from(cal)
    for scenario in ("localised", "market_wide", "quiet"):
        spec = SCENARIOS[scenario]
        log = run(FixtureDataLayer(scenarios=(scenario,)), BASIS, spec["start"],
                  ENT_A, INST_A, policy, REGISTRY)
        show(log, scenario)


if __name__ == "__main__":
    main()
