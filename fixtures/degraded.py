"""Layers that provide less and say so.

The distinction from `adversarial.py` is the whole point of the capability tier
system: these are honest. They must PASS conformance — the checks they cannot
satisfy are skipped because they never claimed them — and the harness must record
a named degradation for each, rather than running quietly weaker.

`yfinance`, a CSV someone writes in an afternoon, and a vendor with no filing date
are all real instances of these.
"""
from __future__ import annotations

from contract import Capability, CapabilitySet, Lineage, Record, Status

from .layer import FixtureDataLayer


class _Degraded(FixtureDataLayer):
    lacks: Capability = None        # type: ignore[assignment]
    resembles = ""

    def __init__(self, **kw):
        caps = CapabilitySet(frozenset(CapabilitySet.full().supported) - {self.lacks})
        super().__init__(capabilities=caps, **kw)
        self.layer_id = f"fixtures.degraded.no_{self.lacks.value}"


class NoRevisionChains(_Degraded):
    """A vendor whose restatements overwrite, and which says so. Run proceeds and
    the manifest marks it CONTAMINATED — restatement lookahead is undetectable, so
    the run is labelled rather than trusted."""

    lacks = Capability.REVISION_CHAINS
    resembles = "FMP, financialdatasets.ai"

    def _all(self):
        if self.__dict__.get('_dcache') is None:
            self.__dict__['_dcache'] = tuple(
                Record(**{**r.__dict__, "revision": None})
                for r in FixtureDataLayer._all(self) if r.id != "fct_A_rev_q2_v0")
        return self.__dict__['_dcache']


class NoTypedStatus(_Degraded):
    """Gaps arrive as absences. not-representable and not-disclosed collapse."""

    lacks = Capability.TYPED_STATUS
    resembles = "almost every equity API"

    def _all(self):
        if self.__dict__.get('_dcache') is None:
            self.__dict__['_dcache'] = tuple(
                r for r in FixtureDataLayer._all(self) if not r.status.is_gap)
        return self.__dict__['_dcache']


class NoMeasurementProcess(_Degraded):
    """No provenance prose, so there is nothing to embed and corroboration by
    independence is unavailable."""

    lacks = Capability.MEASUREMENT_PROCESS
    resembles = "a bare CSV adapter"

    def sources(self):
        return [type(d)(**{**d.__dict__, "measurement_process": ""}) for d in super().sources()]


class NoLineageCoupling(_Degraded):
    """No derived_from, no couples_to. Independence is over-estimated and the
    correlation cap has nothing to key off."""

    lacks = Capability.LINEAGE_COUPLING
    resembles = "any vendor that ships enrichment without saying what it derived from"

    def sources(self):
        return [type(d)(**{**d.__dict__, "couples_to": ()}) for d in super().sources()]

    def _all(self):
        if self.__dict__.get('_dcache') is None:
            self.__dict__['_dcache'] = tuple(
                Record(**{**r.__dict__, "lineage": Lineage()})
                for r in FixtureDataLayer._all(self))
        return self.__dict__['_dcache']


class NoNativeCadence(_Degraded):
    """Basis resolution is uncheckable, so the commensurability check is skipped —
    and a 5-day mechanism derived from monthly frames stops being detectable."""

    lacks = Capability.NATIVE_CADENCE
    resembles = "a source that never states its own frequency"

    def sources(self):
        # native_cadence is derived from the emissions, so it is removed where it
        # is actually declared — there is no second field to blank out.
        out = []
        for d in super().sources():
            emits = tuple(type(e)(**{**e.__dict__, "native_cadence": ""}) for e in d.emits)
            out.append(type(d)(**{**d.__dict__, "emits": emits}))
        return out


class NoCrossReference(_Degraded):
    lacks = Capability.CROSS_REFERENCE
    resembles = "a data layer with no event spine"


class NoKnowableAt(_Degraded):
    """The one capability with no degraded mode. The harness must refuse to run."""

    lacks = Capability.KNOWABLE_AT
    resembles = "financialdatasets.ai — report_period only, no filing date"


DEGRADED_LAYERS = (
    NoRevisionChains, NoTypedStatus, NoMeasurementProcess, NoLineageCoupling,
    NoNativeCadence, NoCrossReference, NoKnowableAt,
)
