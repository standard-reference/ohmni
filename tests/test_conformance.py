"""Does the data product work?

Three questions, and the second is the one that gives the first any weight:
  1. does an honest layer pass?
  2. does a layer that LIES get caught, by the check that exists to catch it?
  3. does a layer that provides less but says so pass, and degrade in a named way?
"""
import pytest

from conformance import Outcome, run_conformance
from contract import Capability, CapabilitySet
from fixtures.adversarial import ADVERSARIAL_LAYERS
from fixtures.degraded import DEGRADED_LAYERS
from fixtures.layer import FixtureDataLayer


def test_honest_layer_passes_every_check(layer):
    report = run_conformance(layer)
    assert report.passed, [f"{f.id}: {f.detail}" for f in report.failures]
    assert not report.skipped, "a full-capability layer should skip nothing"


@pytest.mark.parametrize("bad", ADVERSARIAL_LAYERS, ids=lambda c: c.__name__)
def test_a_lying_layer_is_caught_by_its_named_check(bad):
    """Failing for the wrong reason is a false pass, so the check is named."""
    report = run_conformance(bad())
    assert bad.caught_by in report.failed_ids(), (
        f"{bad.__name__} lies about {bad.lies_about!r} and should fail "
        f"{bad.caught_by!r}; it failed {sorted(report.failed_ids())}"
    )


def test_every_check_is_exercised_by_some_adversarial_layer():
    """A check no fixture can fail has never been tested. Any check not covered
    here is an assertion nobody has verified."""
    from conformance.suite import CHECKS

    covered = {c.caught_by for c in ADVERSARIAL_LAYERS}
    uncovered = {cid for cid, *_ in CHECKS} - covered
    # Checks reachable only through a malformed *declaration* rather than a
    # malformed record; the plugin loader rejects those at registration, before a
    # layer exists to wrap. `availability_present` is the special case below.
    expected_gaps = {
        "declaration_completeness", "measurement_process_declared",
        "cadence_declared", "emission_matches_output",
        "lag_honours_declaration", "coupling_wellformed",
        "availability_present", "no_network_in_read",
    }
    assert uncovered == expected_gaps, f"unexpected coverage gap: {uncovered}"


def test_a_record_without_availability_cannot_be_constructed():
    """Why `availability_present` has no adversarial fixture: the contract makes
    the failure unrepresentable. A layer cannot serve a null `knowable_at` because
    it cannot build the record in the first place.

    This is the stronger form of the guarantee — not "we check for it" but "it
    cannot occur" — and it is the reason the capability has no degraded mode.
    """
    from datetime import datetime, timezone

    from contract import Lineage, Record, Status

    with pytest.raises(ValueError, match="knowable_at is required"):
        Record(id="x", kind="fundamental", subject="ent_1",
               event_time=datetime(2019, 1, 1, tzinfo=timezone.utc),
               knowable_at=None, value={}, status=Status.REPORTED,
               source_id="s", lineage=Lineage())


@pytest.mark.parametrize("deg", DEGRADED_LAYERS, ids=lambda c: c.__name__)
def test_a_layer_that_declares_less_still_passes(deg):
    """Conformance tests honesty, not richness. A CSV adapter written in an
    afternoon must be able to pass it."""
    report = run_conformance(deg())
    assert report.passed, [f"{f.id}: {f.detail}" for f in report.failures]


@pytest.mark.parametrize("deg", DEGRADED_LAYERS, ids=lambda c: c.__name__)
def test_degradation_skips_rather_than_fails(deg):
    report = run_conformance(deg())
    assert all(r.outcome is not Outcome.FAIL for r in report.results)


def test_conformance_needs_nothing_but_the_layer():
    """The suite has no oracle and no reference dataset. Every check asks whether
    the source honours its own declaration, never whether a value is 'correct' —
    that is a question this product does not ask and cannot answer."""
    import inspect

    from conformance.suite import run_conformance as fn

    assert list(inspect.signature(fn).parameters) == ["layer"]


# ── the two claims the product makes, falsifiable in ten minutes ────────────

def test_as_of_is_correct_on_both_sides_of_a_restatement(layer):
    from fixtures.dataset import ENT_A, dt
    from fixtures.design_intent import RESTATEMENT_CASES

    for as_of, expected, why in RESTATEMENT_CASES:
        got = layer.query(ENT_A, "fundamental", (dt(2019, 3, 1), dt(2019, 4, 1)), as_of)
        amounts = [r.value["amount"] for r in got if r.value.get("span") == "standalone_quarter"]
        assert amounts == [expected], f"as_of {as_of} ({why}) returned {amounts}"


def test_the_period_is_invisible_before_it_was_filed(layer):
    from datetime import timedelta

    from fixtures.dataset import ENT_A, dt
    from fixtures.design_intent import FIRST_KNOWABLE_A_Q2

    window = (dt(2019, 3, 1), dt(2019, 4, 1))
    before = layer.query(ENT_A, "fundamental", window,
                         FIRST_KNOWABLE_A_Q2 - timedelta(seconds=1))
    assert not [r for r in before if r.value.get("span") == "standalone_quarter"]


def test_five_reasons_for_a_hole_stay_five_reasons(layer):
    """`null` collapses at least five genuinely different states, and a consumer
    reasons differently about each — don't ask again, read the filing text, try
    another source."""
    from fixtures.design_intent import EXPECTED_GAPS

    served = {r.id: (r.status.value, r.value.get("reason"))
              for r in layer.stream(*_WIDE, subjects=[])}
    for rid, expected in EXPECTED_GAPS.items():
        assert served[rid] == expected, f"{rid}: {served.get(rid)} != {expected}"
    assert len({s for s, _ in (served[k] for k in EXPECTED_GAPS)}) == 4


def test_q4_standalone_is_not_representable_not_computed(layer):
    """FY minus Q1/Q2/Q3 produces a number nobody filed. Competitors compute it
    and hand you a value indistinguishable from a filed one."""
    from contract import Status

    q4 = next(r for r in layer.stream(*_WIDE, subjects=[]) if r.id == "fct_A_rev_q4")
    assert q4.status is Status.NOT_REPRESENTABLE
    assert q4.value.get("amount") is None
    annual = [r for r in layer.stream(*_WIDE, subjects=[])
              if r.value.get("span") == "annual"]
    assert annual, "the annual figure and the three filed quarters stay available"


def test_a_snapshot_stream_refuses_to_be_history(layer):
    from contract import HistoricalQueryRefused
    from fixtures.dataset import ENT_A, dt

    with pytest.raises(HistoricalQueryRefused) as e:
        layer.query(ENT_A, "social_engagement", (dt(2019, 1, 1), dt(2020, 1, 1)),
                    as_of=dt(2019, 6, 15))
    assert "snapshot" in str(e.value)


def test_the_same_query_twice_is_byte_identical(layer):
    a = repr(list(layer.stream(*_WIDE, subjects=[])))
    b = repr(list(FixtureDataLayer().stream(*_WIDE, subjects=[])))
    assert a == b


from conformance.suite import WIDE as _WIDE  # noqa: E402
