"""A DataLayer over real historical sources.

The second implementation of the contract, and the one that tests whether the
seam actually holds: it must pass the *same* conformance suite the hand-built
fixture does, with no special cases anywhere.

What it honestly cannot claim is declared rather than omitted. Prices here are
prototype grade — no delisted coverage — so `SURVIVORSHIP` is absent from the
capability set and every run against this layer is marked contaminated. That is
the machinery working: the limitation is recorded and attributable, not a
footnote someone has to remember.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterator

from contract import (Capability, CapabilitySet, HistoricalQueryRefused, Record,
                      SourceDeclaration, SourceRegistry)

from .adapters import edgar, finra, gdelt, prices, wikimedia
from .entities import ENTITIES, INSTRUMENT_OF, Entity


class HistoricalDataLayer:
    layer_id = "ohmni.historical"
    layer_version = "0.1.0"
    concept_map_version = edgar.CONCEPT_MAP_VERSION
    cluster_version = None          # no event spine yet; declared, not implied

    def __init__(self, entities: tuple[Entity, ...] = ENTITIES,
                 start: datetime | None = None, end: datetime | None = None):
        self.entities = entities
        self.start = start
        self.end = end
        self._records: tuple[Record, ...] | None = None

    # ── contract surface ────────────────────────────────────────────────────
    def sources(self) -> list[SourceDeclaration]:
        return [m.declaration() for m in (edgar, wikimedia, prices, finra, gdelt)]

    def capabilities(self) -> CapabilitySet:
        full = set(CapabilitySet.full().supported)
        # Declared absences, each for a stated reason:
        #   SURVIVORSHIP  — the price source serves only currently-listed names
        #   CROSS_REFERENCE — no event spine or /relate is built yet
        full.discard(Capability.SURVIVORSHIP)
        full.discard(Capability.CROSS_REFERENCE)
        return CapabilitySet(frozenset(full))

    # ── ingestion: fetch is the only network boundary ───────────────────────
    #: Prices are fetched past the observation window so a prediction registered
    #: on the last frame has something to resolve against. This is not lookahead:
    #: the bus bounds every observation by its own window, and the tail is only
    #: reachable through a query whose as_of is already past the horizon.
    RESOLUTION_TAIL = timedelta(days=45)

    def preload(self, start: datetime, end: datetime, *, progress=None) -> "HistoricalDataLayer":
        recs: list[Record] = []
        wanted = {e.ticker: e for e in self.entities}

        for e in self.entities:
            if progress:
                progress(f"edgar    {e.ticker}")
            raw, tag = edgar.fetch_raw(e)
            recs += edgar.normalize(raw, tag, e)

            if progress:
                progress(f"wiki     {e.ticker}")
            recs += wikimedia.normalize(
                wikimedia.fetch_raw(e, start, end), e)

            if progress:
                progress(f"prices   {e.ticker}")
            recs += prices.normalize(
                prices.fetch_raw(e, start - timedelta(days=7),
                                 end + self.RESOLUTION_TAIL), e)

            if progress:
                progress(f"gdelt    {e.ticker}")
            recs += gdelt.normalize(gdelt.fetch_raw(e, start, end), e)

        day = start
        while day <= end:
            if day.weekday() < 5:
                got = finra.fetch_raw(day)
                if got is not None:
                    recs += finra.normalize(got.text(), day, wanted)
                elif progress:
                    # An absent file is a closed market. It is never a zero.
                    progress(f"finra    {day:%Y-%m-%d} no file (market closed)")
            day += timedelta(days=1)

        self._records = tuple(sorted(recs, key=lambda r: (r.knowable_at, r.id)))
        self.start, self.end = start, end
        return self

    def _all(self) -> tuple[Record, ...]:
        if self._records is None:
            raise RuntimeError("call preload(start, end) before reading; fetch is "
                               "the only network boundary and it happens there")
        return self._records

    def stream(self, start: datetime, end: datetime,
               subjects: list[str]) -> Iterator[Record]:
        wanted = set(subjects) if subjects else None
        for r in self._all():
            if not (start <= r.knowable_at <= end):
                continue
            if wanted is not None and r.subject not in wanted \
                    and INSTRUMENT_OF.get(r.subject) not in wanted:
                continue
            yield r

    def query(self, subject: str, kind: str, window: tuple[datetime, datetime],
              as_of: datetime) -> list[Record]:
        reg = SourceRegistry(tuple(self.sources()))
        emitters = reg.emitters(kind)
        honest = [d for d, _ in emitters if d.has_honest_history]
        if emitters and not honest:
            decl = emitters[0][0]
            raise HistoricalQueryRefused(
                f"{decl.source_id}: retrieval={decl.retrieval.value}, "
                f"record_survivorship={decl.record_survivorship.value}")
        lo, hi = window
        hits = [r for r in self._all()
                if r.kind == kind and r.subject == subject
                and lo <= r.event_time <= hi
                and r.knowable_at <= as_of]
        return self._latest_per_period(hits)

    @staticmethod
    def _latest_per_period(hits: list[Record]) -> list[Record]:
        """as_of(T) = filter to knowable_at <= T, take the latest per period.

        On EDGAR this is the whole point: before Intel's 2024 amendment the 2022
        figure it returns is the one that was filed in 2022, not the one that is
        true today.
        """
        best: dict[tuple, Record] = {}
        for r in hits:
            key = (r.subject, r.kind, r.value.get("concept"),
                   r.value.get("period_end"), r.value.get("span"),
                   r.id if r.revision is None else None)
            prev = best.get(key)
            if prev is None or r.knowable_at > prev.knowable_at:
                best[key] = r
        return sorted(best.values(), key=lambda r: (r.event_time, r.id))
