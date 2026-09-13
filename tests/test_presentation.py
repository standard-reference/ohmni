"""Does the data layer present the harness what it needs, correctly and labelled?

This is the question that matters, and it is narrower than "is the data right" —
there is no oracle for that and the layer never claims one. It is also wider than
conformance: conformance asks whether a source honours its own declarations;
this asks whether what arrives is *usable without being misled*.

Nothing here asserts a judgement about the data. Every assertion is about what
was delivered and how it was labelled.
"""
from datetime import timedelta

import pytest

from contract import Aggregation, Status
from fixtures import design_intent as di
from fixtures.dataset import ENT_A, REGISTRY, SCENARIOS, dt
from fixtures.layer import FixtureDataLayer
from harness.bus import Bus
from harness.observation import observe
from harness.presentation import coverage, relate

WIDE = (dt(1990, 1, 1), dt(2030, 1, 1))


def run(scenario, **kw):
    spec = SCENARIOS[scenario]
    b = Bus(FixtureDataLayer(scenarios=(scenario,)), spec["start"])
    events = tuple(b.replay(spec["start"] + timedelta(days=70)))
    return observe(events, di.fixture_basis(), spec["start"], REGISTRY, **kw)


# ── 1. availability ─────────────────────────────────────────────────────────

def test_every_value_arrives_with_when_it_became_knowable(layer):
    for r in layer.stream(*WIDE, subjects=[]):
        assert r.knowable_at is not None and r.knowable_at >= r.event_time


# ── 2. gaps are typed, never silent ─────────────────────────────────────────

def test_the_coverage_envelope_enumerates_every_hole_with_a_reason(layer):
    """A consumer cannot detect a silent gap, so absence is made first-class."""
    env = coverage(tuple(layer.stream(*WIDE, subjects=[])), WIDE)
    assert not env.complete
    assert env.reasons() == {"not_representable": 1, "not_disclosed": 1,
                             "not_applicable": 1, "not_covered": 2}
    assert all(g["reason"] for g in env.gaps), "every gap says why"


def test_a_gap_is_never_delivered_as_a_zero(layer):
    for r in layer.stream(*WIDE, subjects=[]):
        if r.status.is_gap:
            assert r.value.get("amount") is None


# ── 3. declared structure reaches the consumer ──────────────────────────────

def test_the_consumer_can_weigh_evidence_without_reading_any_text():
    """Phenomenon, role and lineage all arrive as declarations, so nothing
    downstream has to infer standing from prose."""
    from contract import Phenomenon
    from fixtures.dataset import echo_cluster
    from harness.potency import PotencyReader

    ec = echo_cluster()
    reader = PotencyReader(REGISTRY, ec)
    for r in ec:
        assert reader.phenomenon_of(r) is not None, f"{r.id} has no declared phenomenon"
    article = next(r for r in ec if r.kind == "news")
    assert reader.origin_documents(article) != frozenset(article.lineage.documents), (
        "an echo must resolve to what it echoes, or twelve copies read as twelve findings")


def test_resolution_confidence_travels_with_the_record_not_in_a_log():
    """Mis-linking a mention makes a field look like it changed when nothing did.
    Whether a consumer uses the confidence is its business; that it ARRIVES is
    the layer's obligation."""
    spec = SCENARIOS["entity_drift"]
    b = Bus(FixtureDataLayer(scenarios=("entity_drift",)), spec["start"])
    news = [e for e in b.replay(spec["start"] + timedelta(days=70)) if e.kind == "news"]
    assert news and all("resolution_confidence" in e.value for e in news)
    assert news[0].value["resolution_confidence"] == 0.55


# ── 4. declared algebra: what is valid, before anyone does it ───────────────

def test_relate_says_what_is_valid_and_never_what_is_true():
    r = relate(REGISTRY, ("edgar.xbrl", "fundamental"), ("wikimedia.pageviews", "pageviews"))
    assert r.verdict == "relatable_with_transform"
    assert "ratio" in r.valid_operations
    assert {b["op"] for b in r.blocked_operations} == {"sum", "difference", "product"}
    assert "consumer's hypothesis" in r.note


def test_resolution_is_the_coarsest_common_cadence_and_upsampling_is_refused():
    """Aggregating fine to coarse is arithmetic over observed values.
    Disaggregating coarse to fine manufactures values nobody observed."""
    r = relate(REGISTRY, ("edgar.xbrl", "fundamental"), ("wikimedia.pageviews", "pageviews"))
    assert r.resolution == "P3M"
    assert [t["to"] for t in r.required_transforms] == ["P3M"]


def test_blocked_operations_carry_their_reason():
    r = relate(REGISTRY, ("prices.eod", "price"), ("edgar.xbrl", "fundamental"))
    assert all(b["reason"] for b in r.blocked_operations)


# ── 5. the data arrives in the shape the declarations promised ──────────────

def test_frames_are_built_at_the_declared_resolution():
    obs = run("localised")
    assert len(obs.frames) == di.fixture_basis().frame_count == 8


def test_aggregation_follows_each_emissions_declared_rule():
    """Summing four quarters of headcount, or averaging four quarterly margins,
    are the errors this metadata exists to prevent. The consumer reads the rule
    from the source rather than guessing from the field name."""
    assert REGISTRY.quantity("pageviews").aggregation is Aggregation.ADDITIVE
    assert REGISTRY.quantity("short_volume").aggregation is Aggregation.WEIGHTED_AVERAGE
    assert REGISTRY.quantity("short_volume").weight_field == "total_volume"
    obs = run("localised")
    pv = obs.separations["pageviews_rate"].trajectory
    # The fixture's first frame runs at 1000 views/day. An additive field must
    # come back as the weekly SUM (~7000), not the mean of the daily totals
    # (~1000) — the latter is the silent double-aggregation bug this guards.
    assert 6500 < pv[0] < 7500, f"expected a weekly sum near 7000, got {pv[0]}"


def test_an_irregular_stream_becomes_a_rate_per_window_not_a_zero_filled_series():
    obs = run("localised")
    news = obs.separations["news_rate"].trajectory
    assert all(float(v).is_integer() and v > 0 for v in news), (
        "counts per window; a window with nothing in it would be a typed gap, not a zero")


def test_quarterly_into_a_weekly_basis_is_refused_not_forward_filled():
    obs = run("localised")
    assert obs.not_representable["revenue_yoy"] == "cadence_incoherent"
    assert "revenue_yoy" not in obs.separations


def test_not_covered_and_cadence_incoherent_stay_distinct():
    """Two different reasons a field cannot be expressed, and a consumer does
    something different about each — widen the basis, versus find a source."""
    obs = run("localised")
    assert obs.not_representable == di.EXPECTED_NOT_REPRESENTABLE
    assert len(set(obs.not_representable.values())) == 2
