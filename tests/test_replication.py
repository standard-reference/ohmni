"""Epochs, window-resolved parameters, and promotion by replication.

The correction these tests lock in: a form derived from one window and applied
elsewhere is a fit to that window, however carefully entity ids and dates were
kept out of it — because the *parameters* carried the window. The generic thing
has to be the recipe for the number, not the number.
"""
from datetime import datetime, timedelta, timezone

import pytest

from harness.epochs import Epoch, EpochSet, half_year
from harness.parameters import (Rule, UnresolvableParameter, WindowContext,
                                constant, null_quantile, subject_volatility)
from harness.replication import Derivation, group_by_core, replicated_cores
from harness.strategy import TradeTypeCore

UTC = timezone.utc


def core(template="attention", shape="spike_and_return", sign="neutral"):
    return TradeTypeCore(
        mechanism_template=template, trigger_phenomenon="information_seeking",
        required_shape=shape,
        required_invariant_phenomena=("exchange_activity", "off_exchange_routing"),
        sign=sign, horizon_frames=2,
        separation_rule=null_quantile(0.95),
        magnitude_rule=subject_volatility(1.0), regime_scope="any")


def derivation(epoch_id, entity, c=None):
    return Derivation(epoch_id=epoch_id, entity=entity, window_start=None,
                      core=c or core(), trade_type=None, support=1.0, specificity=0.6)


# ── epochs ──────────────────────────────────────────────────────────────────

def test_epochs_must_be_disjoint():
    """An epoch that shares data with another is not an independent replication —
    the same records would be counted twice as if they were two observations."""
    with pytest.raises(ValueError, match="overlap"):
        EpochSet(epochs=(
            Epoch("a", datetime(2019, 1, 1, tzinfo=UTC), datetime(2019, 12, 1, tzinfo=UTC), ""),
            Epoch("b", datetime(2019, 6, 1, tzinfo=UTC), datetime(2020, 6, 1, tzinfo=UTC), ""),
        ), min_replications=2)


def test_a_holdout_is_excluded_from_derivation():
    es = EpochSet(epochs=(half_year(2019, 1, "a"), half_year(2021, 1, "b"),
                          half_year(2023, 1, "c", holdout=True)),
                  min_replications=2)
    assert {e.id for e in es.derivation()} == {"2019H1", "2021H1"}
    assert {e.id for e in es.holdout()} == {"2023H1"}


def test_you_cannot_demand_more_replications_than_epochs():
    with pytest.raises(ValueError, match="more replications"):
        EpochSet(epochs=(half_year(2019, 1, "a"),), min_replications=2)


# ── parameters are recipes, not numbers ─────────────────────────────────────

def test_one_rule_resolves_differently_in_different_windows():
    """This is the whole point. The same claim — 'further apart than noise gets
    here' — is a different number in a quiet regime and a violent one."""
    rule = null_quantile(0.95)
    quiet = WindowContext("2019H1", lambda q: 2.10, 0.061, 800)
    loud = WindowContext("2023H1", lambda q: 2.38, 0.146, 800)
    assert rule.resolve(quiet) != rule.resolve(loud)
    assert rule.describe() == rule.describe()


def test_a_magnitude_scales_to_the_subject_not_to_a_constant():
    rule = subject_volatility(1.0)
    calm = WindowContext("e", lambda q: 2.0, 0.02, 800)
    wild = WindowContext("e", lambda q: 2.0, 0.15, 800)
    assert rule.resolve(wild) > 7 * rule.resolve(calm)


def test_an_unresolvable_rule_raises_rather_than_defaulting():
    """A default here would silently reintroduce the derivation epoch's value
    into a window that never justified it — which is the bug this whole module
    exists to remove."""
    thin = WindowContext("e", lambda q: 2.0, 0.05, null_samples=12)
    with pytest.raises(UnresolvableParameter, match="samples"):
        null_quantile(0.95, min_samples=100).resolve(thin)

    flat = WindowContext("e", lambda q: 2.0, 0.0, 800)
    with pytest.raises(UnresolvableParameter, match="volatility"):
        subject_volatility(1.0).resolve(flat)


def test_a_constant_is_possible_but_must_be_spelled_out():
    """Kept available so that using one is a visible choice, never a default."""
    assert constant(0.5).resolve(WindowContext("e", lambda q: 1.0, 0.1, 800)) == 0.5
    assert constant(0.5).describe() == "constant(value=0.5)"


# ── core identity carries no window-local number ────────────────────────────

def test_a_core_identity_contains_rules_not_values():
    c = core()
    identity = c.identity()
    assert "null_quantile" in identity
    # No resolved number may appear: two epochs resolving the same rule to
    # different values must still be the same core.
    assert not any(isinstance(x, float) for x in identity)


def test_two_epochs_resolving_differently_are_still_the_same_core():
    assert core().identity() == core().identity()


def test_a_different_story_is_a_different_core():
    assert core().identity() != core(template="something_else").identity()
    assert core().identity() != core(shape="step").identity()
    assert core().identity() != core(sign="positive").identity()


# ── promotion requires recurrence across epochs ─────────────────────────────

def test_many_firings_in_one_epoch_are_not_a_replication():
    """Ten firings inside one epoch are one observation with wide coverage: the
    windows overlap and the regime is shared. Counting firings instead of epochs
    is how a single period's quirk gets promoted as a law."""
    es = EpochSet(epochs=(half_year(2019, 1, "a"), half_year(2021, 1, "b"),
                          half_year(2023, 1, "c", holdout=True)),
                  min_replications=2)
    same_epoch = [derivation("2019H1", f"E{i}") for i in range(10)]
    assert group_by_core(same_epoch)[0].epochs == {"2019H1"}
    assert not replicated_cores(same_epoch, es)


def test_the_same_core_in_two_epochs_replicates():
    es = EpochSet(epochs=(half_year(2019, 1, "a"), half_year(2021, 1, "b"),
                          half_year(2023, 1, "c", holdout=True)),
                  min_replications=2)
    got = replicated_cores([derivation("2019H1", "A"), derivation("2021H1", "B")], es)
    assert len(got) == 1
    assert got[0].epochs == {"2019H1", "2021H1"}


def test_a_holdout_derivation_never_counts_toward_replication():
    """A core that only appears in the holdout was not proposed — it was
    discovered while scoring, which is the same mistake in a new place."""
    es = EpochSet(epochs=(half_year(2019, 1, "a"), half_year(2021, 1, "b"),
                          half_year(2023, 1, "c", holdout=True)),
                  min_replications=2)
    assert not replicated_cores(
        [derivation("2019H1", "A"), derivation("2023H1", "B")], es)


def test_distinct_cores_are_grouped_separately():
    groups = group_by_core([derivation("2019H1", "A"),
                            derivation("2021H1", "B", core("other"))])
    assert len(groups) == 2
