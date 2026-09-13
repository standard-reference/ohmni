"""B0 — the guard, ordering, root sets, reproducibility.

Bar: adversarial peek fails by every route; runs hash-reproducible; nulls destroy
cross-stream structure.
"""
from datetime import timedelta

import pytest

from contract import Capability
from fixtures.adversarial import IgnoresAsOfLayer, OutOfOrderLayer
from fixtures.dataset import ENT_A, dt
from fixtures.degraded import NoKnowableAt
from fixtures.layer import FixtureDataLayer
from harness.bus import Bus, LookaheadError, OrderingError
from harness.manifest import HarnessRefusal, RunManifest

START, END = dt(2019, 1, 1), dt(2019, 5, 1)


def bus(layer=None):
    return Bus(layer or FixtureDataLayer(), START)


def test_the_guard_refuses_an_explicit_future_as_of():
    b = bus()
    list(b.replay(dt(2019, 3, 1)))
    with pytest.raises(LookaheadError):
        b.query(ENT_A, "fundamental", (START, END), as_of=dt(2019, 12, 1))


def test_the_guard_holds_against_a_layer_that_ignores_as_of():
    """Defence in depth: the harness must not trust the data layer to be correct.

    This is what lets it accept a sloppier layer — a CSV, yfinance — without
    silently losing the guarantee.
    """
    b = bus(IgnoresAsOfLayer())
    list(b.replay(dt(2019, 3, 1)))
    with pytest.raises(LookaheadError, match="the layer served a future value"):
        b.query(ENT_A, "fundamental", (START, END))


def test_a_default_query_is_gated_on_sim_time_not_the_callers_word():
    b = bus()
    list(b.replay(dt(2019, 6, 1)))          # past the original Q2 filing
    got = b.query(ENT_A, "fundamental", (dt(2019, 3, 1), dt(2019, 4, 1)))
    amounts = [r.value["amount"] for r in got if r.value.get("span") == "standalone_quarter"]
    assert amounts == ["1000000000"], "sim-time 2019-06 must not see the October restatement"


def test_out_of_order_availability_raises_rather_than_being_sorted_away():
    b = bus(OutOfOrderLayer())
    with pytest.raises(OrderingError):
        list(b.replay(END))


def test_the_clock_never_runs_backwards():
    b = bus()
    seen = None
    for ev in b.replay(END):
        if seen is not None:
            assert ev.knowable_at >= seen
        seen = ev.knowable_at


def test_gating_is_on_availability_not_event_time():
    """A pageview bucket stamped 14:00 is not knowable until the dump lands. Every
    source's lag comes from its own declaration, never from a table here."""
    from fixtures.dataset import REGISTRY

    b = bus()
    for ev in b.replay(dt(2019, 2, 1)):
        em = REGISTRY.emission_for(ev.record)
        if em and em.publication_lag:
            assert ev.knowable_at - ev.event_time >= em.publication_lag
        assert ev.knowable_at <= b.now


def test_root_sets_are_derived_harness_side_from_lineage():
    """The layer emits lineage; the harness derives root sets. Lineage is a
    general primitive, root sets are one consumer's interpretation."""
    b = bus()
    evs = list(b.replay(dt(2019, 2, 1)))
    sentiment = next(e for e in evs if e.kind == "sentiment")
    article = next(e for e in evs if e.id == "nw_" + next(iter(sentiment.record.lineage.documents)))
    assert sentiment.root_set == article.root_set
    assert sentiment.generation == 1 and article.generation == 0


def test_root_set_derivation_is_absent_from_the_contract():
    """If `root_set` appeared in the contract, the harness's vocabulary would have
    leaked into a product that should also serve a stock screener."""
    import contract

    assert not hasattr(contract.Record, "root_set")
    assert "root_set" not in {f for f in contract.Record.__dataclass_fields__}


def test_a_run_is_hash_reproducible():
    a, b = bus(), bus()
    list(a.replay(END))
    list(b.replay(END))
    assert a.manifest.event_set_hash() == b.manifest.event_set_hash()


def test_the_hash_spans_both_products_versions():
    b = bus()
    list(b.replay(dt(2019, 2, 1)))
    first = b.manifest.event_set_hash()
    b.manifest.concept_map_version = "cm_fixture.2"
    assert b.manifest.event_set_hash() != first, (
        "a data-layer upgrade must change replay results visibly")


def test_a_null_run_is_distinguishable_from_a_real_one():
    real, null = bus(), bus(FixtureDataLayer(shuffled=True))
    list(real.replay(END))
    list(null.replay(END))
    assert real.manifest.event_set_hash() != null.manifest.event_set_hash()
    assert null.manifest.is_null_run


def test_an_ungatable_layer_is_refused_not_degraded():
    """The one capability with no degraded mode."""
    with pytest.raises(HarnessRefusal, match="nothing to.*gate on"):
        RunManifest.for_layer(NoKnowableAt())


def test_a_layer_without_revision_chains_runs_but_is_marked_contaminated():
    from fixtures.degraded import NoRevisionChains

    m = RunManifest.for_layer(NoRevisionChains())
    assert m.is_contaminated
    assert Capability.REVISION_CHAINS.value in m.contaminated
