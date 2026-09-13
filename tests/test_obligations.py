"""Can the data product feed each phase of the harness build?

Answered per stage, per capability, from the declared obligations in
`harness/obligations.py` — never restated here, so there is no second copy to
drift out of step with the capability table.
"""
import pytest

from contract import DEGRADATION_TABLE, Capability, CapabilitySet, Consequence
from fixtures.degraded import DEGRADED_LAYERS
from fixtures.layer import FixtureDataLayer
from harness.manifest import HarnessRefusal, RunManifest
from harness.obligations import STAGES, StageStatus, assess


def test_a_full_layer_satisfies_every_stage():
    a = assess(RunManifest.for_layer(FixtureDataLayer()))
    assert {s: v.status for s, v in a.items()} == {
        s.id: StageStatus.RUNNABLE for s in STAGES}


@pytest.mark.parametrize("deg", [d for d in DEGRADED_LAYERS
                                 if d.lacks is not Capability.KNOWABLE_AT],
                         ids=lambda c: c.__name__)
def test_each_missing_capability_produces_its_declared_consequence(deg):
    """The capability table is the contract's promise about degradation. This is
    the test that makes it a promise rather than a comment."""
    manifest = RunManifest.for_layer(deg())
    expected = DEGRADATION_TABLE[deg.lacks]
    affected = [a for a in assess(manifest).values() if deg.lacks in a.stage.requires]
    assert affected, f"no stage declares it needs {deg.lacks.value}"

    for a in affected:
        if expected.consequence is Consequence.CONTAMINATED:
            assert a.status is StageStatus.CONTAMINATED
            assert deg.lacks.value in manifest.contaminated
        elif expected.consequence is Consequence.DISABLE:
            assert a.status is StageStatus.DEGRADED
            assert set(expected.disables) <= set(a.lost_features)


@pytest.mark.parametrize("deg", DEGRADED_LAYERS, ids=lambda c: c.__name__)
def test_degradation_is_recorded_never_silent(deg):
    """A run against a degraded layer is labelled, not quietly weaker. Same
    discipline as declaring a basis: the limitation is attributable."""
    try:
        manifest = RunManifest.for_layer(deg())
    except HarnessRefusal:
        assert deg.lacks in {Capability.KNOWABLE_AT}
        return
    assert any(deg.lacks.value in note for note in manifest.degradation_notes)


def test_only_one_capability_is_non_negotiable():
    """Without `knowable_at` on every record there is nothing to gate on. Every
    other gap has a declared degraded mode."""
    refuse = [c for c, d in DEGRADATION_TABLE.items()
              if d.consequence is Consequence.REFUSE]
    assert refuse == [Capability.KNOWABLE_AT]


def test_every_stage_declares_what_it_reads_from_the_contract():
    for stage in STAGES:
        assert stage.requires, f"{stage.id} declares no obligations"
        assert Capability.KNOWABLE_AT in stage.requires, (
            f"{stage.id} must be gated like everything else")
        assert stage.bar, f"{stage.id} has no acceptance bar"


def test_every_capability_is_consumed_by_some_stage():
    """A capability no stage reads is one the contract does not need to demand."""
    demanded = {c for s in STAGES for c in s.requires}
    assert demanded == set(DEGRADATION_TABLE)


def test_a_csv_grade_layer_still_reaches_the_first_real_question():
    """The claim is that the harness runs on any conforming data layer, including
    one someone writes in an afternoon. That is only true if the weakest honest
    layer still reaches B5 — labelled, but running."""
    weakest = FixtureDataLayer(capabilities=CapabilitySet(frozenset({Capability.KNOWABLE_AT})))
    a = assess(RunManifest.for_layer(weakest))
    assert all(v.can_run for v in a.values())
    assert a["B5"].status in (StageStatus.DEGRADED, StageStatus.CONTAMINATED)
    assert a["B5"].lost_features, "and it must say what it lost"
