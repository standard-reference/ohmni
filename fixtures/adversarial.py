"""Layers that lie, each in one realistic way.

A conformance suite that has never failed is an untested assertion. Every layer
here is a real vendor behaviour described in `03-data-sources.md`, and each must
be caught by a *named* check — failing for the wrong reason is a false pass.

Note the distinction from `degraded.py`: these layers CLAIM a capability and do
not honour it. A degraded layer declares what it lacks and is honest; it must
pass conformance.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterator

from contract import Lineage, Record, Revision, Status

from . import dataset as ds
from .layer import FixtureDataLayer


class _Wrapper(FixtureDataLayer):
    """Inherits a conformant layer and breaks exactly one thing."""

    lies_about = "nothing"
    caught_by = ""          # the check id that must fire

    def __init__(self, **kw):
        super().__init__(**kw)
        self.layer_id = f"fixtures.adversarial.{type(self).__name__}"

    def _all(self):
        # NonDeterministicLayer deliberately opts out — its whole point is that
        # two identical calls differ.
        if type(self) is NonDeterministicLayer:
            return self._compute()
        if self.__dict__.get("_acache") is None:
            self.__dict__["_acache"] = self._compute()
        return self.__dict__["_acache"]

    def _compute(self):
        return FixtureDataLayer._all(self)


class FabricatedQ4Layer(_Wrapper):
    """Computes Q4 standalone as FY − Q1 − Q2 − Q3 and serves it as `reported`.

    The number is arithmetically consistent and nobody filed it. This is the most
    common quiet failure in the category, and it is indistinguishable from a filed
    value unless the status enum carries `not_representable`.
    """

    lies_about = "Q4 standalone exists"
    caught_by = "no_fabrication"

    def _compute(self) -> tuple[Record, ...]:
        recs = [r for r in super()._compute() if r.id != "fct_A_rev_q4"]
        recs.append(Record(
            id="fct_A_rev_q4", kind="fundamental", subject=ds.ENT_A,
            event_time=ds.dt(2019, 9, 28), knowable_at=ds.dt(2019, 11, 1, 20, 30),
            value={"concept": "revenue", "period_end": "2019-09-28T00:00:00+00:00",
                   "span": "standalone_quarter", "amount": "1050000000",
                   "unit": "USD", "scale": 1},
            status=Status.REPORTED,      # the lie: nobody filed this
            source_id="edgar.xbrl", lineage=Lineage(documents=frozenset()),
        ))
        return tuple(sorted(recs, key=lambda r: (r.knowable_at, r.id)))


class OverwritingLayer(_Wrapper):
    """Restatements overwrite rather than chain — the FMP / financialdatasets
    behaviour. Every timestamp is honest and the value is wrong, which is why the
    bus guard structurally cannot catch it."""

    lies_about = "restatements are preserved"
    caught_by = "restatement_as_of"

    def _compute(self) -> tuple[Record, ...]:
        # A vendor with no revision concept does not null one field — it has no
        # revisions anywhere, and every value is simply the latest one, stamped
        # with the original availability date. Every timestamp is honest and the
        # value is wrong, which is why the bus guard structurally cannot see it.
        out = []
        for r in super()._compute():
            if r.id == "fct_A_rev_q2_v0":
                continue                                   # the original is gone
            if r.id == "fct_A_rev_q2_v1":
                r = Record(**{**r.__dict__, "id": "fct_A_rev_q2",
                              "knowable_at": ds.ORIGINAL_FILED_AT})
            out.append(Record(**{**r.__dict__, "revision": None}))
        return tuple(sorted(out, key=lambda r: (r.knowable_at, r.id)))


class PeriodEndAvailabilityLayer(_Wrapper):
    """`knowable_at` silently equals the period end. Looks populated, is lookahead:
    a 10-Q's period end precedes its filing by weeks."""

    lies_about = "availability is distinct from period"
    caught_by = "availability_sanity"

    def _compute(self) -> tuple[Record, ...]:
        return tuple(
            Record(**{**r.__dict__, "knowable_at": r.event_time}) for r in super()._compute()
        )


class UntypedGapLayer(_Wrapper):
    """Gaps come back as a null value with status `reported`. Five genuinely
    different states collapse into one, and a consumer cannot recover them."""

    lies_about = "gaps are typed"
    caught_by = "status_honesty"

    def _compute(self) -> tuple[Record, ...]:
        out = []
        for r in super()._compute():
            if r.status.is_gap:
                r = Record(**{**r.__dict__, "status": Status.REPORTED,
                              "value": {**r.value, "amount": None}})
            out.append(r)
        return tuple(out)


class SnapshotAsHistoryLayer(_Wrapper):
    """Serves engagement counts for a 2019 post as though they were 2019 values.

    Pull a 2019 post today and every count is from today. There is no revision
    chain because the intermediate values were never stored anywhere. Harder than
    `backfilled`: backfilled history is suspect, snapshot history is simply wrong,
    and wrong in the direction of the future.
    """

    lies_about = "snapshot streams have an honest history"
    caught_by = "snapshot_refusal"

    def query(self, subject, kind, window, as_of):
        if kind in ("social_post", "social_engagement"):
            return [r for r in self._all()
                    if r.kind == kind and r.subject == subject]   # no as_of filter at all
        return super().query(subject, kind, window, as_of)


class UndeclaredDerivationLayer(_Wrapper):
    """Derived sentiment arrives with no `derived_from`. Shared lineage becomes
    invisible, so the accumulation layer sums an article and its own sentiment
    score as two independent legs. Classic ensemble overconfidence."""

    lies_about = "derivation lineage is declared"
    caught_by = "no_fabrication"

    def _compute(self) -> tuple[Record, ...]:
        return tuple(
            Record(**{**r.__dict__, "lineage": Lineage(documents=r.lineage.documents)})
            if r.status is Status.DERIVED else r
            for r in super()._compute()
        )


class OutOfOrderLayer(_Wrapper):
    """Streams records in event_time order rather than knowable_at order. Every
    record is honest; the sequence is not."""

    lies_about = "the stream is ordered by knowable_at"
    caught_by = "stream_ordering"

    def stream(self, start, end, subjects) -> Iterator[Record]:
        yield from sorted(super().stream(start, end, subjects),
                          key=lambda r: (r.event_time, r.id))


class IgnoresAsOfLayer(_Wrapper):
    """Accepts `as_of` and ignores it — the failure the mandatory parameter exists
    to make structurally impossible. A hosted server behaving like this inside a
    replay reads present-day values at sim-time 2019."""

    lies_about = "as_of is enforced"
    caught_by = "as_of_enforced"

    def query(self, subject, kind, window, as_of):
        return super().query(subject, kind, window, as_of=ds.dt(2026, 9, 13))


class NonDeterministicLayer(_Wrapper):
    """A model, a clock, or an unordered dict in the normalize path. Catches
    anything that makes a replay unreproducible."""

    lies_about = "normalize is a pure function of raw input"
    caught_by = "normalize_determinism"

    _n = 0

    def _compute(self) -> tuple[Record, ...]:
        type(self)._n += 1
        out = list(FixtureDataLayer._all(self))
        r = out[0]
        return tuple([Record(**{**r.__dict__,
                                "knowable_at": r.knowable_at + timedelta(microseconds=self._n)})]
                     + out[1:])


ADVERSARIAL_LAYERS = (
    FabricatedQ4Layer, OverwritingLayer, PeriodEndAvailabilityLayer, UntypedGapLayer,
    SnapshotAsHistoryLayer, UndeclaredDerivationLayer, OutOfOrderLayer,
    IgnoresAsOfLayer, NonDeterministicLayer,
)
