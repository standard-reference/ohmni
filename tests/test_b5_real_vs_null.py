"""B5 — real versus null, asserted as ORDERING so no threshold is needed.

Which fields count as "moved" requires a cut point, and a cut point tuned until
the nulls go quiet is the snooping problem one layer up. Which scenario shows
*more* separation than another does not require one, and it is what the fixture
was actually built to encode.
"""
from datetime import timedelta

import pytest

from fixtures import design_intent as di
from fixtures.dataset import REGISTRY, SCENARIOS
from fixtures.layer import FixtureDataLayer
from harness.bus import Bus
from harness.observation import observe


def obs_for(scenario, shuffled=False, seed=0):
    spec = SCENARIOS[scenario]
    b = Bus(FixtureDataLayer(scenarios=(scenario,), shuffled=shuffled, shuffle_seed=seed),
            spec["start"])
    events = tuple(b.replay(spec["start"] + timedelta(days=70)))
    return observe(events, di.fixture_basis(), spec["start"], REGISTRY)


def total_separation(obs):
    return sum(s.ratio for s in obs.separations.values())


def test_scenarios_order_by_separation_as_designed():
    order = [total_separation(obs_for(s)) for s in di.EXPECTED_SEPARATION_ORDER]
    assert order == sorted(order, reverse=True), dict(
        zip(di.EXPECTED_SEPARATION_ORDER, order))


@pytest.mark.parametrize("scenario", sorted(di.EXPECTED_STRONGEST_FIELD))
def test_the_field_that_was_moved_separates_most(scenario):
    obs = obs_for(scenario)
    strongest = max(obs.separations.values(), key=lambda s: s.ratio)
    assert strongest.field == di.EXPECTED_STRONGEST_FIELD[scenario]


def test_real_data_separates_more_than_its_own_null():
    """Averaged over independent null realisations, so a single lucky shuffle
    cannot carry the result."""
    real = total_separation(obs_for("market_wide"))
    nulls = [total_separation(obs_for("market_wide", shuffled=True, seed=s))
             for s in range(12)]
    assert real > max(nulls), f"real={real:.1f} null_max={max(nulls):.1f}"


def test_the_quiet_control_separates_least_on_real_data():
    quiet = total_separation(obs_for("quiet"))
    assert quiet < total_separation(obs_for("localised"))


def test_a_null_run_is_labelled_and_hashes_differently():
    spec = SCENARIOS["market_wide"]
    real = Bus(FixtureDataLayer(scenarios=("market_wide",)), spec["start"])
    null = Bus(FixtureDataLayer(scenarios=("market_wide",), shuffled=True), spec["start"])
    list(real.replay(spec["start"] + timedelta(days=70)))
    list(null.replay(spec["start"] + timedelta(days=70)))
    assert null.manifest.is_null_run and not real.manifest.is_null_run
    assert null.manifest.event_set_hash() != real.manifest.event_set_hash()


def test_the_confidence_discount_lowers_separation_rather_than_flipping_a_verdict():
    """Entity-resolution confidence is applied as a discount on a magnitude, not
    as a gate. A consumer that wants a verdict applies its own tolerance."""
    spec = SCENARIOS["entity_drift"]
    b = Bus(FixtureDataLayer(scenarios=("entity_drift",)), spec["start"])
    events = tuple(b.replay(spec["start"] + timedelta(days=70)))
    basis = di.fixture_basis()
    disc = observe(events, basis, spec["start"], REGISTRY)
    raw = observe(events, basis, spec["start"], REGISTRY, apply_resolution_confidence=False)
    assert disc.separations["news_rate"].ratio < raw.separations["news_rate"].ratio
    assert disc.separations["news_rate"].confidence == pytest.approx(0.55)
