"""From a promoted spark to a generic trade type, a strategy, and a scored
prediction.

The property under test throughout: what gets produced is a *form*, not an
instance. A single-trade thesis names an entity and a date, fires once, and
yields one Brier score that can never be replicated. A trade type names basis
fields and phenomena, fires across a universe, and accumulates calibration
against the form.
"""
from datetime import timedelta

import pytest

from fixtures import design_intent as di
from fixtures.dataset import (ENT_A, ENT_B, ENT_C, INSTRUMENT_OF, INSTRUMENTS_OF,
                              REGISTRY, SCENARIOS, TAIL_WEEKS)
from fixtures.layer import FixtureDataLayer
from harness.bus import Bus
from harness.calibration import build_null_calibration
from harness.claims import Sign
from harness.execution import Decision, leak_check, run_universe
from harness.observation import observe
from harness.pipeline import RunPolicy, compile_strategy, run
from harness.prediction import (Ledger, PredictionRegistered, RegistrationRefused,
                                ResolutionRefused, claim_held,
                                probability_from_support)
from harness.strategy import (COMPILABLE_SHAPES, UNCOMPILABLE_SHAPES, NotCompilable,
                              Strategies, build_strategy)

BASIS = di.fixture_basis()
UNIVERSE = [ENT_A, ENT_B, ENT_C]


def _obs(scenario, shuffled, seed=0):
    spec = SCENARIOS[scenario]
    bus = Bus(FixtureDataLayer(scenarios=(scenario,), shuffled=shuffled, shuffle_seed=seed),
              spec["start"])
    events = tuple(bus.replay(spec["start"] + BASIS.frame_span * BASIS.frame_count))
    return observe(events, BASIS, spec["start"], REGISTRY)


@pytest.fixture(scope="module")
def policy():
    cal = build_null_calibration(
        lambda seed: [s.ratio for sc in SCENARIOS
                      for s in _obs(sc, True, seed).separations.values()],
        BASIS.id, runs=8)
    tol = cal.quantile(0.95)
    return RunPolicy(
        anomaly_z=3.0, anomaly_relative_floor=0.05, moved_tolerance=tol,
        moved_tolerance_source=f"null q=0.95 FP={cal.false_positive_rate(tol):.3f}",
        cluster_cap=0.70, specificity_floor=0.30, support_threshold=0.50,
        hysteresis_fraction=0.5, k_broken_legs=2, delta_reality_days=180,
        degraded_multiplier=0.25, support_scale=3.0,
        inference_delay_minutes=15, min_frames_before_deciding=6)


@pytest.fixture(scope="module")
def compiled(policy):
    spec = SCENARIOS["localised"]
    layer = FixtureDataLayer(scenarios=("localised",), subjects=(ENT_A, ENT_B))
    log = run(layer, BASIS, spec["start"], ENT_A, INSTRUMENTS_OF[ENT_A][0],
              policy, REGISTRY)
    tt, strategy = compile_strategy(log, BASIS, REGISTRY, UNIVERSE)
    return log, tt, strategy


# ── the form contains no instance ───────────────────────────────────────────

def test_a_trade_type_names_no_entity_and_no_date(compiled):
    """The structural guarantee that this is a form, not a thesis. An entity id
    or a date inside the rule means it can only ever fire once."""
    _, tt, _ = compiled
    forbidden = (ENT_A, ENT_B, ENT_C, *INSTRUMENT_OF, "2019", "2020")
    generic, leaked = tt.is_generic(forbidden)
    assert generic, f"trade type leaked instance literals: {leaked}"


def test_the_universe_is_a_coverage_requirement_not_a_list_of_names(compiled):
    _, tt, _ = compiled
    assert tt.universe["requires_phenomena"]
    assert not any(e in str(tt.universe) for e in (ENT_A, ENT_B, ENT_C))


def test_entry_is_expressed_over_basis_fields_and_phenomena(compiled):
    _, tt, _ = compiled
    assert tt.entry["residue_field"] in {f.name for f in BASIS.fields}
    assert tt.entry["residue_phenomenon"]
    assert tt.entry["required_invariant_phenomena"]


# ── provenance back to the claims ───────────────────────────────────────────

def test_every_compiled_field_says_which_principle_it_came_from(compiled):
    """This is what lets a critique check a compiled strategy against its source
    claims mechanically, instead of trusting that the translation was faithful."""
    _, tt, _ = compiled
    assert tt.entry["derived_from"] == "spark.principles.observation"
    assert tt.direction["derived_from"] == "spark.principles.mechanism.predicted_effect"
    assert tt.exit["derived_from"] == "spark.principles.invalidation"
    assert tt.sizing["derived_from"] == "spark.principles.corroboration.accumulated_support"


def test_the_invalidation_state_machine_is_the_exit_rule(compiled):
    """Nothing new is authored for exits: `degraded` cuts size, `invalidated`
    exits, and both come straight off the tree."""
    _, tt, _ = compiled
    assert "0.25" in tt.exit["on_degraded"]
    assert tt.exit["on_invalidated"] == "exit"


def test_degraded_cuts_size_aggressively_not_cosmetically(compiled):
    """Hysteresis converts false-kills into slow-kills, so a dead thesis bleeds
    for N windows. That is only an acceptable trade if degraded sizing is severe."""
    _, tt, _ = compiled
    assert tt.sizing["degraded_multiplier"] <= 0.5


# ── compile() completeness, stated rather than approximated ─────────────────

def test_an_inexpressible_shape_is_refused_not_approximated(compiled):
    """Silently compiling a shape you cannot express produces a rule that does
    not implement the claim it cites."""
    log, _, _ = compiled
    mech = log.spark.principles["mechanism"].payload
    original = mech.trigger_shape
    object.__setattr__(mech, "trigger_shape", "oscillation")
    try:
        with pytest.raises(NotCompilable, match="oscillation"):
            compile_strategy(log, BASIS, REGISTRY, UNIVERSE)
    finally:
        object.__setattr__(mech, "trigger_shape", original)


def test_the_compilable_and_refused_shapes_are_disjoint_and_declared():
    assert not set(COMPILABLE_SHAPES) & set(UNCOMPILABLE_SHAPES)
    assert all(reason for reason in UNCOMPILABLE_SHAPES.values())


def test_model_in_loop_is_a_separate_kind_not_a_fallback_mode():
    assert "model_in_loop.v1" in Strategies.names()
    assert "threshold_rule.v1" in Strategies.names()


# ── a strategy comes only from a promoted spark ─────────────────────────────

def test_an_unpromoted_spark_compiles_to_nothing(policy):
    """Compiling an ungated spark makes the gate decorative — the thesis would
    reach capital regardless of whether it cleared specificity and support."""
    spec = SCENARIOS["sustained_attention"]
    layer = FixtureDataLayer(scenarios=("sustained_attention",), subjects=(ENT_A,))
    log = run(layer, BASIS, spec["start"], ENT_A, INSTRUMENTS_OF[ENT_A][0],
              policy, REGISTRY)
    assert log.spark is not None and not log.gate["promotable"]
    tt, strategy = compile_strategy(log, BASIS, REGISTRY, UNIVERSE)
    assert tt is None and strategy is None


def test_invariance_corroborates_a_no_move_claim_but_not_a_directional_one(policy):
    """"Three processes held still" supports "nothing will happen". It cannot
    support "price will rise", and the two-tier alignment's sign gate is what
    stops it being counted as if it did."""
    spec = SCENARIOS["sustained_attention"]
    layer = FixtureDataLayer(scenarios=("sustained_attention",), subjects=(ENT_A,))
    log = run(layer, BASIS, spec["start"], ENT_A, INSTRUMENTS_OF[ENT_A][0],
              policy, REGISTRY)
    predicted = log.spark.principles["mechanism"].payload.predicted
    assert predicted.sign is Sign.POSITIVE
    assert log.support.total == 0.0
    assert all(l.alignment == 0.0 for l in log.support.legs)


# ── execution across a universe ─────────────────────────────────────────────

@pytest.fixture(scope="module")
def trace(compiled, policy):
    _, tt, _ = compiled
    spec = SCENARIOS["localised"]
    bus = Bus(FixtureDataLayer(scenarios=("localised",), subjects=(ENT_A, ENT_B)),
              spec["start"])
    events = tuple(bus.replay(spec["start"] + BASIS.frame_span * BASIS.frame_count))
    return run_universe(events, tt, BASIS, spec["start"], UNIVERSE, REGISTRY,
                        entity_of=lambda s: INSTRUMENT_OF.get(s, s),
                        inference_delay=timedelta(minutes=policy.inference_delay_minutes),
                        min_frames=policy.min_frames_before_deciding)


def test_the_same_form_fires_on_more_than_one_entity(trace):
    """Cross-sectional replication is what buys statistical power without the
    heterogeneity of deep history. A form that can only fire on one name buys
    none of it."""
    fired = {d.entity for d in trace.fired()}
    assert {ENT_A, ENT_B} <= fired


def test_an_entity_without_basis_coverage_is_excluded_not_signalled(trace):
    """A bank has no pageviews. Absence of coverage must never read as absence of
    the phenomenon."""
    c = [d for d in trace.decisions if d.entity == ENT_C]
    assert c and all(d.action == "no_coverage" for d in c)
    assert all(d.size == 0.0 for d in c)


def test_firing_and_sizing_are_different_questions(trace):
    """An abstain stance still fires: it makes a falsifiable claim that nothing
    will happen, and that claim is registered and scored. Whether capital moves
    is downstream of the claim, never a condition on it."""
    assert trace.fired()
    assert not trace.positions()


def test_decisions_carry_a_modelled_inference_delay(trace):
    """In replay inference is instantaneous relative to sim-time; live it takes
    minutes. Without the delay the backtest is systematically optimistic."""
    assert all(d.at > d.evaluated_at for d in trace.decisions)


def test_the_leak_check_is_clean_on_an_honest_trace(trace):
    assert leak_check(trace) == []


def test_the_leak_check_catches_a_planted_leak(trace):
    """A check that has never fired is an untested assertion."""
    future = max(trace.events_by_id.values(), key=lambda e: e.knowable_at)
    earliest = min(d.evaluated_at for d in trace.decisions)
    planted = Decision(at=earliest, evaluated_at=earliest, entity=ENT_A,
                       trade_type_id="tt_x", action="fire", stance="long", size=1.0,
                       conditioned_on=frozenset({future.id}))
    trace.decisions.append(planted)
    try:
        findings = leak_check(trace)
        assert any(f.event_id == future.id for f in findings)
    finally:
        trace.decisions.remove(planted)


# ── the ledger ──────────────────────────────────────────────────────────────

def test_a_prediction_whose_horizon_has_elapsed_cannot_be_registered():
    """Score forward, never backward — made structural rather than remembered.
    Backtests are admission, not score."""
    from fixtures.dataset import dt

    ledger = Ledger()
    with pytest.raises(RegistrationRefused, match="backtest"):
        ledger.register(_prediction("p_back", dt(2019, 6, 1), dt(2019, 5, 1)))


def test_a_prediction_cannot_be_resolved_before_its_horizon():
    from fixtures.dataset import dt

    ledger = Ledger()
    ledger.register(_prediction("p1", dt(2019, 5, 13), dt(2019, 5, 27)))
    with pytest.raises(ResolutionRefused):
        ledger.resolve("p1", 0.001, dt(2019, 5, 20))


def test_predictions_are_immutable_once_made():
    from fixtures.dataset import dt

    ledger = Ledger()
    ledger.register(_prediction("p1", dt(2019, 5, 13), dt(2019, 5, 27)))
    with pytest.raises(RegistrationRefused, match="immutable"):
        ledger.register(_prediction("p1", dt(2019, 5, 13), dt(2019, 5, 27)))


def test_calibration_accrues_to_the_trade_type_not_the_instance():
    """A disposable single-trade thesis yields one Brier score forever. A form
    accumulates one per entity it fires on."""
    from fixtures.dataset import dt

    ledger = Ledger()
    for i, ent in enumerate((ENT_A, ENT_B)):
        pid = f"p_{ent}"
        ledger.register(_prediction(pid, dt(2019, 5, 13), dt(2019, 5, 27)))
        ledger.resolve(pid, 0.001, dt(2019, 5, 27))
    scored = ledger.by_trade_type()
    assert scored["tt_shared_form"]["n"] == 2


def test_probability_comes_from_the_log_odds_support_with_no_extra_constant():
    assert probability_from_support(0.0) == pytest.approx(0.5)
    assert probability_from_support(2.0281) == pytest.approx(0.8837, abs=1e-4)


def test_the_claim_shapes_resolve_as_declared():
    assert claim_held(Sign.NEUTRAL, 0.02, 0.001) == 1
    assert claim_held(Sign.NEUTRAL, 0.02, 0.05) == 0
    assert claim_held(Sign.POSITIVE, 0.04, 0.05) == 1
    assert claim_held(Sign.POSITIVE, 0.04, -0.05) == 0
    assert claim_held(Sign.NEGATIVE, 0.04, -0.05) == 1


def test_the_market_benchmark_uses_the_price_at_registration_not_later():
    """A benchmark read after the fact is not a benchmark."""
    from fixtures.dataset import PM_RESOLVE_BY, dt

    layer = FixtureDataLayer()
    at = dt(2019, 5, 13)
    quotes = layer.query("inst_NWS_common", "pm_quote", (dt(2019, 1, 1), at), as_of=at)
    assert quotes and all(q.knowable_at <= at for q in quotes)
    later = layer.query("inst_NWS_common", "pm_quote",
                        (dt(2019, 1, 1), PM_RESOLVE_BY), as_of=at)
    assert max(q.knowable_at for q in later) <= at


def _prediction(pid, registered_at, resolve_by):
    return PredictionRegistered(
        id=pid, spark_ref="spk_x", trade_type_ref="tt_shared_form",
        subject=INSTRUMENTS_OF[ENT_A][0], sign=Sign.NEUTRAL, magnitude=0.02,
        horizon=timedelta(days=14), probability=0.88, declared_scope="any",
        registered_at=registered_at, resolve_by=resolve_by, basis_id=BASIS.id,
        embedding_space_version="e", concept_map_version="cm",
        layer_id="l", layer_version="1")
