"""B0 — the bus: sim-clock, lookahead guard, ordering, Record→Event, root sets.

This lives harness-side, not data-layer-side, and that is what makes "runs on any
conforming data layer" true. A well-built data layer makes `as_of` mandatory so it
cannot serve future values to *any* consumer; this guard holds regardless,
including against a data layer with no guard at all.

Hard rule enforced structurally: no model or agent calls a data API directly.
Every byte reaches reasoning through this bus. A hosted server queried inside a
replay reads present-day values at sim-time 2019, and no guard can see it because
the data never passes through here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator

from contract import DataLayer, Record, SourceRegistry

from .manifest import RunManifest


class LookaheadError(Exception):
    """A read of information not yet available at sim-time. Every route to one
    raises; none returns a degraded answer."""


class OrderingError(Exception):
    """The layer streamed a record whose knowable_at went backwards."""


@dataclass(frozen=True)
class Event:
    """The harness's own shape. `root_set` is derived here, on this side of the
    seam, from the lineage the layer emitted."""

    id: str
    kind: str
    subject: str
    event_time: datetime
    knowable_at: datetime
    value: dict
    status: str
    source_id: str
    root_set: frozenset[str]
    generation: int = 0
    record: Record | None = field(default=None, repr=False, compare=False)


#: Root sets saturate at depth — everything traces back to "the market" — so
#: independence collapses to zero for all mature evidence without a bound. The
#: bound is declared here rather than defaulted silently; it is an open question
#: which value is right, and the manifest records the one used.
ROOT_SET_GENERATION_CAP = 3


class Bus:
    def __init__(self, layer: DataLayer, start: datetime):
        self.layer = layer
        self.manifest = RunManifest.for_layer(layer)   # refuses here if ungatable
        self.registry = SourceRegistry.from_layer(layer)
        self._now = start
        self._start = start
        self._roots: dict[str, tuple[frozenset[str], int]] = {}
        self._emitted: list[Event] = []
        self.audit: list[dict] = []

    # ── sim clock ───────────────────────────────────────────────────────────
    @property
    def now(self) -> datetime:
        return self._now

    def _advance(self, to: datetime) -> None:
        if to < self._now:
            raise OrderingError(f"clock cannot go backwards: {to} < {self._now}")
        self._now = to

    # ── the only way data reaches reasoning ─────────────────────────────────
    def replay(self, end: datetime, subjects: list[str] | None = None) -> Iterator[Event]:
        prev: datetime | None = None
        for rec in self.layer.stream(self._start, end, subjects or []):
            if prev is not None and rec.knowable_at < prev:
                raise OrderingError(
                    f"{rec.id}: knowable_at {rec.knowable_at} follows {prev}; "
                    "the stream is not ordered by availability"
                )
            prev = rec.knowable_at
            self._advance(rec.knowable_at)
            yield self._to_event(rec)

    def query(self, subject: str, kind: str, window, as_of: datetime | None = None):
        """A query is always gated on the sim clock, never on the caller's word.

        Passing an `as_of` later than sim-time is not honoured-with-a-warning; it
        raises. A backtest that can ask for the future is not a backtest.
        """
        effective = as_of if as_of is not None else self._now
        if effective > self._now:
            raise LookaheadError(
                f"query as_of={effective} is past sim-time {self._now}; "
                f"{kind} for {subject} is not knowable yet"
            )
        got = self.layer.query(subject, kind, window, as_of=effective)
        for r in got:
            if r.knowable_at > self._now:
                # Defence in depth: holds even against a layer that ignores as_of.
                raise LookaheadError(
                    f"{r.id} knowable at {r.knowable_at}, past sim-time {self._now}; "
                    "the layer served a future value"
                )
        self.audit.append({"at": self._now, "subject": subject, "kind": kind,
                           "returned": [r.id for r in got]})
        return got

    # ── Record → Event, and root-set derivation ─────────────────────────────
    def _to_event(self, rec: Record) -> Event:
        roots, gen = self._root_set(rec)
        ev = Event(
            id=rec.id, kind=rec.kind, subject=rec.subject,
            event_time=rec.event_time, knowable_at=rec.knowable_at,
            value=rec.value, status=rec.status.value, source_id=rec.source_id,
            root_set=roots, generation=gen, record=rec,
        )
        self.manifest.absorb(ev.id, ev.knowable_at)
        self._emitted.append(ev)
        return ev

    def _root_set(self, rec: Record) -> tuple[frozenset[str], int]:
        """Forward-propagated: every record carries the raw source documents it
        stands on, and derived records union their parents' sets.

        Replaces backward ancestry tracing, which had an undefined depth bound.
        """
        if not rec.lineage.derived_from:
            roots = frozenset(rec.lineage.documents)
            self._roots[rec.id] = (roots, 0)
            return roots, 0
        roots: set[str] = set(rec.lineage.documents)
        gen = 0
        for parent in rec.lineage.derived_from:
            p_roots, p_gen = self._roots.get(parent, (frozenset(), 0))
            roots |= p_roots
            gen = max(gen, p_gen + 1)
        if gen > ROOT_SET_GENERATION_CAP:
            # Beyond the cap, keep only this record's own documents: past the
            # bound every set converges on "the market" and independence becomes
            # uniformly zero, which is worse than a declared truncation.
            roots = set(rec.lineage.documents)
        out = frozenset(roots)
        self._roots[rec.id] = (out, gen)
        return out, gen

    def events(self) -> tuple[Event, ...]:
        return tuple(self._emitted)
