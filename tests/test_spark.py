"""The spark path: trigger -> observation -> mechanism -> corroboration -> invalidation.

The honest scope: the mechanism slot here is filled from a declared template
library, not by a model. That is a real limit and it is asserted rather than
glossed — what a model adds is templates nobody wrote down, which is the thing
the harness exists to find. What is tested is that the deterministic gates around
that slot do their job whoever fills it.
"""
from datetime import timedelta

import pytest

from contract import Phenomenon
from fixtures import design_intent as di
from fixtures.dataset import ENT_A, INST_A, REGISTRY, SCENARIOS
from fixtures.layer import FixtureDataLayer
from harness.bus import Bus
from harness.calibration import build_null_calibration
from harness.claims import Sign
from harness.invalidation import LeafState, ThesisState, hysteresis_for, thesis_state
from harness.observation import observe
from harness.pipeline import RunPolicy, run
from harness.registry import Artifact, EffectClaims, KindError, Sparks
from harness.spark import OrderingViolation, Spark, SparkStatus

BASIS = di.fixture_basis()


def _obs(scenario, shuffled, seed=0):
    spec = SCENARIOS[scenario]
    bus = Bus(FixtureDataLayer(scenarios=(scenario,), shuffled=shuffled, shuffle_seed=seed),
              spec["start"])
    events = tuple(bus.replay(spec["start"] + BASIS.frame_span * BASIS.frame_count))
    return observe(events, BASIS, spec["start"], REGISTRY)


@pytest.fixture(scope="module")
def calibration():
    return build_null_calibration(
        lambda seed: [s.ratio for sc in SCENARIOS
                      for s in _obs(sc, True, seed).separations.values()],
        BASIS.id, runs=10)


@pytest.fixture(scope="module")
def policy(calibration):
    tol = calibration.quantile(0.95)
    return RunPolicy(
        anomaly_z=3.0, anomaly_relative_floor=0.05,
        moved_tolerance=tol,
        moved_tolerance_source=f"null q=0.95, measured FP {calibration.false_positive_rate(tol):.3f}",
        cluster_cap=0.70, specificity_floor=0.30, support_threshold=0.50,
        hysteresis_fraction=0.5, k_broken_legs=2, delta_reality_days=180)


def go(scenario, policy):
    spec = SCENARIOS[scenario]
    return run(FixtureDataLayer(scenarios=(scenario,)), BASIS, spec["start"],
               ENT_A, INST_A, policy, REGISTRY)


# ── the control comes first ─────────────────────────────────────────────────

def test_the_quiet_control_opens_no_spark(policy):
    """Cheap, so it runs first. If anything promotes here, false-discovery control
    is broken and every downstream result is meaningless."""
    log = go("quiet", policy)
    assert not log.anomalies
    assert log.spark is None


# ── the trigger and the observation must agree ──────────────────────────────

def test_the_trigger_only_fires_on_phenomena_the_observation_calls_moved(policy):
    """Regression: the graph summed every field regardless of its declared
    aggregation, so it fired anomalies on averageable fields (returns) that
    cancellation correctly called invariant. A spark opening on a phenomenon the
    observation says did not move is a spark opening on nothing."""
    log = go("localised", policy)
    moved_phenomena = {REGISTRY.resolve(f.kind, f.source_id)[1].records_of.value
                       for f in BASIS.fields if f.name in log.moved}
    assert {a.phenomenon for a in log.anomalies} <= moved_phenomena


# ── the two deterministic gates ─────────────────────────────────────────────

def test_shape_incommensurability_rejects_a_story_the_path_contradicts(policy):
    """A mechanism claiming attention persists and converts to flow predicts a
    sustained path. The observed residue is a spike-and-return, so the causal
    story and the observed path disagree — computably, before any model is asked."""
    log = go("localised", policy)
    rejected = {c.template.id: c.reasons for c in log.candidates if not c.accepted}
    assert "attention_precedes_flow" in rejected
    assert any("shape incommensurable" in r for r in rejected["attention_precedes_flow"])


def test_the_surviving_mechanism_is_shape_commensurable(policy):
    log = go("localised", policy)
    accepted = [c for c in log.candidates if c.accepted]
    assert len(accepted) == 1
    c = accepted[0]
    assert c.trigger_shape in c.template.compatible_shapes


def test_horizon_is_commensurable_with_the_frame_spacing(policy):
    """Frame spacing is the observation's resolution. A horizon finer than one
    frame is a claim the observation cannot see."""
    log = go("localised", policy)
    predicted = log.spark.principles["mechanism"].payload.predicted
    assert predicted.horizon >= BASIS.frame_span


def test_every_rejection_keeps_its_reason(policy):
    """A verdict is a stored, queryable artifact, never an inline boolean. The
    rejected half is the record of what the data ruled out."""
    log = go("localised", policy)
    assert log.spark.rejected
    assert all(r["reasons"] for r in log.spark.rejected)


# ── corroboration comes from the invariant half ─────────────────────────────

def test_corroborating_legs_are_the_invariant_set(policy):
    """One edge moving while three measured processes held still is the specific
    claim; each of those processes is an independent leg supporting it."""
    log = go("localised", policy)
    leg_phenomena = {l.phenomenon for l in log.support.legs}
    assert leg_phenomena == {Phenomenon.EXCHANGE_ACTIVITY,
                             Phenomenon.EDITORIAL_PUBLICATION,
                             Phenomenon.OFF_EXCHANGE_ROUTING}


def test_independence_weights_each_leg_rather_than_gating_it(policy):
    log = go("localised", policy)
    assert all(0.0 <= l.independence <= 1.0 for l in log.support.legs)
    assert all(l.support_contribution > 0 for l in log.support.legs)
    assert log.support.total == pytest.approx(
        sum(l.support_contribution for l in log.support.legs), abs=1e-3)


def test_a_leg_measured_by_a_weaker_role_contributes_less(policy):
    """FINRA aggregates what its members report, so it is attested rather than
    constitutive, and carries correspondingly less."""
    log = go("localised", policy)
    by_source = {l.source_id: l for l in log.support.legs}
    assert by_source["finra.short"].potency < by_source["prices.eod"].potency
    assert by_source["finra.short"].support_contribution < \
        by_source["prices.eod"].support_contribution


# ── invalidation ────────────────────────────────────────────────────────────

def test_the_tree_is_auto_derived_with_no_custom_leaves(policy):
    """Three of four child types need no new authoring: the mechanism's predicted
    effect, each corroboration's claim, and the observation's residue are already
    claims with a defined shape."""
    log = go("localised", policy)
    kinds = [c.kind for c in log.tree.children]
    assert "predicted_effect.v1" in kinds
    assert kinds.count("effect_claim.v1") == len(log.support.legs)
    assert "delta_reality.v1" in kinds and "observation_integrity.v1" in kinds
    assert not any("custom" in k for k in kinds)


def test_there_is_no_persistence_leaf(policy):
    """Anomaly decay is anomalies behaving normally, never thesis failure. But
    'the delta was never real' IS legitimate invalidation, and integrity checks
    cannot catch it — hence delta_reality and no persistence check."""
    log = go("localised", policy)
    assert not any("persistence" in c.kind for c in log.tree.children)
    assert any(c.kind == "delta_reality.v1" for c in log.tree.children)


def test_a_leaf_breaks_only_after_sustained_failure():
    """Hysteresis at the leaf, not weights at the root. The cost is that a dead
    thesis bleeds for N windows, which is why `degraded` must cut size
    aggressively rather than cosmetically."""
    from harness.invalidation import InvalidationNode

    leaf = InvalidationNode(id="l", scope="mechanism", kind="k", hysteresis_n=3)
    assert leaf.observe(True) is LeafState.AMBIGUOUS
    assert leaf.observe(True) is LeafState.AMBIGUOUS
    assert leaf.observe(True) is LeafState.BROKEN
    assert leaf.observe(False) is LeafState.INTACT


def test_hysteresis_scales_to_the_horizon_not_a_flat_constant():
    """A 3-day claim and a 6-month claim cannot share a window count."""
    week = timedelta(days=7)
    short = hysteresis_for(timedelta(days=14), week, fraction=0.5)
    long = hysteresis_for(timedelta(days=180), week, fraction=0.5)
    assert long > short


def test_the_root_emits_a_state_machine_not_a_boolean(policy):
    log = go("localised", policy)
    assert log.thesis is ThesisState.ACTIVE
    log.tree.children[1].state = LeafState.AMBIGUOUS
    assert thesis_state(log.tree, k_broken_legs=2) is ThesisState.DEGRADED
    log.tree.children[0].state = LeafState.BROKEN          # the mechanism leaf
    assert thesis_state(log.tree, k_broken_legs=2) is ThesisState.INVALIDATED


# ── the spark itself ────────────────────────────────────────────────────────

def test_a_spark_is_produced_end_to_end(policy):
    log = go("localised", policy)
    assert log.spark is not None
    assert log.spark.status in (SparkStatus.COMPLETE, SparkStatus.PROMOTED)
    assert set(log.spark.principles) == {"observation", "mechanism",
                                         "corroboration", "invalidation"}
    assert all(s.filled for s in log.spark.principles.values())


def test_the_ordering_rule_is_data_on_the_kind_not_a_convention():
    from datetime import datetime, timezone

    s = Spark("spk_x", "spark.v1_four_principle", datetime.now(timezone.utc), {})
    with pytest.raises(OrderingViolation, match="before 'mechanism'"):
        s.fill("corroboration", "x")
    assert Sparks.lookup("spark.v1_four_principle").principle_schema[
        "corroboration"]["requires"] == ["mechanism"]


def test_historical_precedent_is_not_a_principle():
    """A model's claimed recollection is unverified token recall. Genuine
    precedent belongs to the robustness pass, which replays point-in-time."""
    assert "precedent" not in Sparks.lookup("spark.v1_four_principle").principle_schema


def test_promotion_needs_both_specificity_and_support(policy):
    import dataclasses

    log = go("localised", policy)
    assert log.gate["promotable"]
    strict = dataclasses.replace(policy, specificity_floor=0.99)
    assert not go("localised", strict).gate["promotable"]
    starved = dataclasses.replace(policy, support_threshold=99.0)
    assert not go("localised", starved).gate["promotable"]


def test_a_scenario_with_no_surviving_mechanism_is_discarded_not_forced(policy):
    log = go("market_wide", policy)
    assert log.spark.status is SparkStatus.DISCARDED
    assert not [c for c in log.candidates if c.accepted]


# ── registries ──────────────────────────────────────────────────────────────

def test_registries_are_split_by_interface_not_by_naming():
    """A flat map would let a wrong-kind lookup succeed syntactically and fail
    deep inside a call."""
    with pytest.raises(KindError):
        Sparks.lookup("effect_claim.v4_frames")
    assert "effect_claim.v4_frames" in EffectClaims.names()


def test_a_kind_validates_on_registration_not_at_use():
    with pytest.raises(KindError, match="missing required attributes"):
        EffectClaims.build("effect_claim.v4_frames", "x", {"basis": "b"})


def test_embeddings_are_versioned_and_never_compared_across_spaces():
    from harness.claims import EMBEDDING_SPACE_VERSION

    art = Artifact(id="a", kind="k", schema_version="1",
                   embeddings={EMBEDDING_SPACE_VERSION: (0.1, 0.2)})
    assert art.embedding("some_other_space.v9") is None


def test_every_policy_parameter_is_required():
    """No number that governs a verdict gets a default. A default is a threshold
    nobody can find."""
    import inspect

    for p in inspect.signature(RunPolicy).parameters.values():
        assert p.default is inspect.Parameter.empty, f"{p.name} has a default"
