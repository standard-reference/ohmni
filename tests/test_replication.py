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
        ), min_replications=2, min_coverage=0.75)


def test_a_holdout_is_excluded_from_derivation():
    es = EpochSet(epochs=(half_year(2019, 1, "a"), half_year(2021, 1, "b"),
                          half_year(2023, 1, "c", holdout=True)),
                  min_replications=2, min_coverage=0.75)
    assert {e.id for e in es.derivation()} == {"2019H1", "2021H1"}
    assert {e.id for e in es.holdout()} == {"2023H1"}


def test_you_cannot_demand_more_replications_than_epochs():
    with pytest.raises(ValueError, match="more replications"):
        EpochSet(epochs=(half_year(2019, 1, "a"),), min_replications=2, min_coverage=0.75)


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
                  min_replications=2, min_coverage=0.75)
    same_epoch = [derivation("2019H1", f"E{i}") for i in range(10)]
    assert group_by_core(same_epoch)[0].epochs == {"2019H1"}
    assert not replicated_cores(same_epoch, es)


def test_the_same_core_in_two_epochs_replicates():
    es = EpochSet(epochs=(half_year(2019, 1, "a"), half_year(2021, 1, "b"),
                          half_year(2023, 1, "c", holdout=True)),
                  min_replications=2, min_coverage=0.75)
    got = replicated_cores([derivation("2019H1", "A"), derivation("2021H1", "B")], es)
    assert len(got) == 1
    assert got[0].epochs == {"2019H1", "2021H1"}


def test_a_holdout_derivation_never_counts_toward_replication():
    """A core that only appears in the holdout was not proposed — it was
    discovered while scoring, which is the same mistake in a new place."""
    es = EpochSet(epochs=(half_year(2019, 1, "a"), half_year(2021, 1, "b"),
                          half_year(2023, 1, "c", holdout=True)),
                  min_replications=2, min_coverage=0.75)
    assert not replicated_cores(
        [derivation("2019H1", "A"), derivation("2023H1", "B")], es)


def test_distinct_cores_are_grouped_separately():
    groups = group_by_core([derivation("2019H1", "A"),
                            derivation("2021H1", "B", core("other"))])
    assert len(groups) == 2


# ── the GDELT problem: a source outage must not become a silent basis change ──

def _realization(epoch_id, fields, missing=None, coverage=1.0, basis_id="b"):
    from harness.coverage import BasisRealization

    return BasisRealization(basis_id=basis_id, epoch_id=epoch_id,
                            representable=frozenset(fields),
                            not_representable=missing or {},
                            coverage={f: coverage for f in fields})


def test_epochs_missing_a_field_are_not_the_same_basis():
    """The failure that motivated this module. GDELT rate-limited out of three
    epochs of four, so `editorial_publication` existed in one — and the system
    happily compared them. Two sparks are comparable when they share a basis;
    that was enforced within a run and not across epochs."""
    from harness.coverage import compare

    got = compare([_realization("2019H1", ["pv", "px"]),
                   _realization("2023H1", ["pv", "px", "news"])],
                  min_coverage=0.8)
    assert got.verdict == "partial"
    assert got.shared == {"pv", "px"}
    assert got.only_in == {"2023H1": {"news"}}
    assert not got.comparable


def test_identical_bases_compare_as_the_same_basis():
    from harness.coverage import compare

    got = compare([_realization("a", ["pv", "px"]), _realization("b", ["pv", "px"])],
                  min_coverage=0.8)
    assert got.verdict == "same_basis" and got.comparable


def test_no_overlap_is_incommensurable_not_merely_different():
    """'Could not compare' and 'compared and found different' must never collapse
    into one answer — a consumer does something different in each case."""
    from harness.coverage import compare

    got = compare([_realization("a", ["pv"]), _realization("b", ["news"])],
                  min_coverage=0.8)
    assert got.verdict == "incommensurable"


def test_a_thinly_covered_field_does_not_count_as_shared():
    """Present in every epoch but populated in a fifth of one epoch's frames is
    not really shared, and a partial outage is exactly what this catches."""
    from harness.coverage import compare

    thin = _realization("b", ["pv", "px"])
    object.__setattr__(thin, "coverage", {"pv": 1.0, "px": 0.2})
    got = compare([_realization("a", ["pv", "px"]), thin], min_coverage=0.8)
    assert got.shared == {"pv"}
    assert got.verdict == "partial"


def test_min_coverage_has_no_default():
    """A default would hide the partial outage this exists to catch."""
    import inspect

    from harness.coverage import compare

    assert inspect.signature(compare).parameters["min_coverage"].default \
        is inspect.Parameter.empty


def test_a_core_untestable_in_some_epochs_is_refused_not_credited():
    """Distinct from 'did not replicate': one means the form failed to recur, the
    other means it was never testable. Crediting the second as the first is how a
    source outage turns into evidence."""
    from harness.replication import replicated_cores

    es = EpochSet(epochs=(half_year(2019, 1, "a"), half_year(2021, 1, "b"),
                          half_year(2023, 1, "c", holdout=True)),
                  min_replications=2, min_coverage=0.75)
    needs_news = core()
    object.__setattr__(needs_news, "required_invariant_phenomena",
                       ("exchange_activity", "editorial_publication"))
    derivations = [derivation("2019H1", "A", needs_news),
                   derivation("2021H1", "B", needs_news)]
    realizations = [_realization("2019H1", ["information_seeking", "exchange_activity"]),
                    _realization("2021H1", ["information_seeking", "exchange_activity",
                                            "editorial_publication"])]
    got = replicated_cores(derivations, es, realizations, min_coverage=0.8)
    assert got == []


def test_checking_commensurability_requires_a_coverage_floor():
    from harness.replication import replicated_cores

    es = EpochSet(epochs=(half_year(2019, 1, "a"), half_year(2021, 1, "b")),
                  min_replications=2, min_coverage=0.75)
    with pytest.raises(ValueError, match="min_coverage is required"):
        replicated_cores([derivation("2019H1", "A")], es,
                         [_realization("2019H1", ["x"])], min_coverage=None)


# ── retrieval feasibility, declared before a single request ─────────────────

def test_a_rate_limited_source_cannot_carry_a_multi_epoch_basis():
    """`retrieval` says whether a historical query returns historical values.
    This says whether the history can be FETCHED at all — a different question,
    and the one that was never asked."""
    from datetime import timedelta

    from contract import HistoricalAccess, SourceRegistry
    from harness.coverage import UnbackfillableSource, check_backfillable
    from harness.observation import Basis, BasisField
    from fixtures.dataset import SOURCES

    throttled = tuple(
        type(d)(**{**d.__dict__, "historical_access": HistoricalAccess.RATE_LIMITED})
        if d.source_id == "gdelt.news" else d for d in SOURCES)
    reg = SourceRegistry(throttled)
    basis = Basis(id="b", resolution="P7D", frame_count=8,
                  frame_span=timedelta(days=7),
                  fields=(BasisField("news_rate", "gdelt.news", "news"),))
    with pytest.raises(UnbackfillableSource, match="rate_limited"):
        check_backfillable(basis, reg)


def test_a_bulk_source_passes_the_same_check():
    from datetime import timedelta

    from contract import SourceRegistry
    from harness.coverage import check_backfillable
    from harness.observation import Basis, BasisField
    from fixtures.dataset import SOURCES

    basis = Basis(id="b", resolution="P7D", frame_count=8,
                  frame_span=timedelta(days=7),
                  fields=(BasisField("pv", "wikimedia.pageviews", "pageviews"),))
    check_backfillable(basis, SourceRegistry(SOURCES))     # must not raise


def test_only_bulk_access_supports_backfill():
    from contract import HistoricalAccess

    assert HistoricalAccess.BULK.supports_backfill
    for a in (HistoricalAccess.METERED, HistoricalAccess.RATE_LIMITED,
              HistoricalAccess.RECORD_ONLY):
        assert not a.supports_backfill


# ── an unavailable source is a fact about the run ──────────────────────────

def test_the_manifest_records_which_sources_were_unavailable():
    """'GDELT unavailable for 2019H1' belongs next to the capability
    degradations, not in prose somebody writes afterwards."""
    from fixtures.layer import FixtureDataLayer
    from harness.manifest import RunManifest

    m = RunManifest.for_layer(FixtureDataLayer())
    before = m.event_set_hash()
    m.record_source("gdelt.news", "rate_limited: 429 after 3 attempts")
    m.record_source("wikimedia.pageviews", "available")
    assert m.unavailable_sources == ("gdelt.news",)
    assert m.event_set_hash() != before, (
        "a run missing a source must not hash the same as one that had it")


# ── the cross-epoch channel: does the core carry its derivation window? ─────

def test_window_independence_catches_a_baked_constant():
    """The check `is_generic()` cannot perform.

    A type check cannot tell a declared `q=0.95` from a fitted threshold — both
    are floats. Behaviour can: a rule resolves differently in materially
    different windows, a constant does not. The core is the only thing crossing
    an epoch boundary, so this is also the cross-epoch leak check.
    """
    from harness.parameters import constant
    from harness.strategy import resolve_trade_type

    quiet = WindowContext("2019H1", lambda q: 2.10, 0.061, 800)
    loud = WindowContext("2023H1", lambda q: 4.90, 0.180, 800)

    def resolve(c, ctx):
        return resolve_trade_type(
            c, ctx, spark_ref="s", basis=_basis(),
            field_of_phenomenon={"information_seeking": "pageviews_rate"},
            support_total=1.0, degraded_multiplier=0.25, support_scale=3.0,
            provenance={})

    honest = core()
    ok, carried = honest.window_independence(resolve, quiet, loud)
    assert ok, carried

    fitted = core()
    object.__setattr__(fitted, "separation_rule", constant(1.2472))
    ok, carried = fitted.window_independence(resolve, quiet, loud)
    assert not ok
    assert carried == ["entry.min_separation"]


def _basis():
    from datetime import timedelta

    from harness.observation import Basis, BasisField

    return Basis(id="b", resolution="P7D", frame_count=8,
                 frame_span=timedelta(days=7),
                 fields=(BasisField("pageviews_rate", "wikimedia.pageviews",
                                    "pageviews"),))


# ── looks and tests are different quantities ───────────────────────────────

def test_the_ledger_separates_looks_from_tests(tmp_path):
    """One harness version against one epoch is one LOOK but can be a hundred
    and sixty TESTS. Charging a single unit for the lot undercounts exactly the
    multiple testing the ledger exists to make visible."""
    from harness.budget import BudgetLedger

    led = BudgetLedger(path=tmp_path / "l.json", dataset_id="d")
    led.declare("2019H1", sealed=False, max_opens=None)
    led.charge("2019H1", "h:one", "derivation", evaluations=54)
    led.charge("2019H1", "h:two", "derivation", evaluations=54)
    b = led.epochs["2019H1"]
    assert b.spent == 2, "two looks"
    assert b.evaluations == 108, "one hundred and eight tests"


def test_evaluations_do_not_consume_the_holdout_cap(tmp_path):
    """Looking once is looking once, however many pairs that look covered."""
    from harness.budget import BudgetLedger

    led = BudgetLedger(path=tmp_path / "l.json", dataset_id="d")
    led.declare("2024H1", sealed=True, max_opens=1)
    led.charge("2024H1", "h:one", evaluations=1000)
    assert led.epochs["2024H1"].remaining == 0
    assert led.epochs["2024H1"].evaluations == 1000


# ── the protocol is recorded, not left at a call site ──────────────────────

def test_the_replication_protocol_is_declared_and_recordable():
    es = EpochSet(epochs=(half_year(2019, 1, "a"), half_year(2021, 1, "b"),
                          half_year(2023, 1, "c", holdout=True)),
                  min_replications=2, min_coverage=0.75)
    d = es.declared()
    assert d["min_replications"] == 2 and d["min_coverage"] == 0.75
    assert d["holdout"] == ["2023H1"]


def test_the_coverage_floor_has_no_default():
    import inspect

    assert inspect.signature(EpochSet).parameters["min_coverage"].default \
        is inspect.Parameter.empty
