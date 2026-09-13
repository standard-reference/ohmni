"""A conformant DataLayer over the fixture dataset.

This is the second implementation that makes the contract real. The harness test
suite runs against this and nothing else; a harness test that needs the real data
layer means the seam has leaked.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterator

from contract import (
    Capability,
    CapabilitySet,
    HistoricalQueryRefused,
    Record,
    Retrieval,
    SourceDeclaration,
    Status,
    Survivorship,
)

from . import dataset as ds

#: "now" for this fixture layer. A snapshot stream can be read at the present
#: instant (that is what a recorder does); only a *historical* read is refused.
_NOW = ds.dt(2026, 9, 13)


class FixtureDataLayer:
    layer_id = "fixtures.handbuilt"
    layer_version = "0.1.0"

    #: bumped independently of layer_version; part of the replay hash
    concept_map_version = "cm_fixture.1"
    cluster_version = "es_fixture.1"

    def __init__(
        self,
        scenarios: tuple[str, ...] = ("localised", "market_wide", "entity_drift", "quiet"),
        shuffled: bool = False,
        capabilities: CapabilitySet | None = None,
        shuffle_seed: int = 0,
    ) -> None:
        self._scenarios = scenarios
        self._shuffled = shuffled
        self._shuffle_seed = shuffle_seed
        self._capabilities = capabilities or CapabilitySet.full()
        if shuffled:
            # The null must be distinguishable in the manifest, or a null run and
            # a real run hash the same and the control proves nothing.
            self.layer_id = "fixtures.handbuilt.null"

    # ── contract surface ────────────────────────────────────────────────────
    def sources(self) -> list[SourceDeclaration]:
        return list(ds.SOURCES)

    def capabilities(self) -> CapabilitySet:
        return self._capabilities

    def _all(self) -> tuple[Record, ...]:
        if self.__dict__.get("_cache") is not None:
            return self.__dict__["_cache"]
        recs: list[Record] = []
        for name in self._scenarios:
            recs.extend(ds.scenario_records(name, shuffled=self._shuffled,
                                            shuffle_seed=self._shuffle_seed))
        recs.extend(ds.fundamentals())
        recs.extend(ds.social_records())
        recs.extend(ds.echo_cluster())
        out = tuple(sorted(recs, key=lambda r: (r.knowable_at, r.id)))
        self.__dict__["_cache"] = out
        return out

    def stream(
        self, start: datetime, end: datetime, subjects: list[str]
    ) -> Iterator[Record]:
        """Ordered by knowable_at, non-decreasing. Gated on availability, never
        on event_time — gating on the wrong one produces silently optimistic
        backtests with no error anywhere."""
        wanted = set(subjects) if subjects else None
        for r in self._all():
            if not (start <= r.knowable_at <= end):
                continue
            if wanted is not None and r.subject not in wanted and not self._maps_to(r, wanted):
                continue
            yield r

    @staticmethod
    def _maps_to(r: Record, wanted: set[str]) -> bool:
        """Instrument-level records reach an entity-level request only through the
        declared instrument spine — never by a rule written into the layer."""
        return ds.INSTRUMENT_OF.get(r.subject) in wanted

    def query(
        self,
        subject: str,
        kind: str,
        window: tuple[datetime, datetime],
        as_of: datetime,
    ) -> list[Record]:
        # Which sources produce this kind is read from their own declarations.
        # No table here to keep in step with them.
        emitters = ds.REGISTRY.emitters(kind)
        honest = [d for d, _ in emitters if d.has_honest_history]
        if emitters and not honest and as_of < _NOW:
            # Snapshot + deletions-unrecoverable has no honest historical mode.
            # Refuse with a reason rather than serve contaminated values.
            decl = emitters[0][0]
            raise HistoricalQueryRefused(
                f"{decl.source_id}: retrieval={decl.retrieval.value}, "
                f"record_survivorship={decl.record_survivorship.value} — "
                "a historical as_of query would return present-day values over a "
                "survivorship-biased record set"
            )
        allowed = {d.source_id for d in honest} or {d.source_id for d, _ in emitters}

        lo, hi = window
        hits = [
            r for r in self._all()
            if r.kind == kind
            and r.subject == subject
            and lo <= r.event_time <= hi
            and r.knowable_at <= as_of          # as_of is mandatory and structural
            and r.source_id in allowed
        ]
        return self._latest_per_period(hits)

    @staticmethod
    def _latest_per_period(hits: list[Record]) -> list[Record]:
        """as_of(T) = filter to knowable_at <= T, take the latest per period.

        This dominates both vendor dimensions: as-reported pins to the first print
        forever and ignores that the market later learned the restatement;
        most-recent is lookahead. As-of returns what was knowable at T.
        """
        best: dict[tuple, Record] = {}
        for r in hits:
            key = (r.subject, r.kind, r.value.get("concept"),
                   r.value.get("period_end"), r.value.get("span"), r.id
                   if r.revision is None else None)
            prev = best.get(key)
            if prev is None or r.knowable_at > prev.knowable_at:
                best[key] = r
        return sorted(best.values(), key=lambda r: (r.event_time, r.id))
