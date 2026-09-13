"""B1 — the market graph and deterministic anomaly detection.

Deterministic code — never a model — computes correlation shifts, centrality
changes and anomaly detection, emitting anomaly events on threshold crossings.
The model interprets and prioritises; it never does arithmetic.

`entity` nodes and entity→entity edges are what make a causal path expressible.
Without them every basis is price looking at itself.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime

from contract import Aggregation, Phenomenon, SourceRegistry

from .bus import Event
from .observation import _aggregate, _robust_scale

NODE_TYPES = ("asset", "entity", "narrative", "factor", "regime")
EDGE_TYPES = ("correlation", "sentiment_link", "mention", "lead_lag", "flow",
              "partnership", "supplier", "customer", "ownership", "observes")


@dataclass
class Node:
    id: str
    type: str
    label: str
    attributes: dict = field(default_factory=dict)
    last_updated: datetime | None = None


@dataclass
class Edge:
    id: str
    source: str
    target: str
    type: str
    weight: float = 0.0
    dispersion: float = 0.0
    weight_history: list[tuple[datetime, float]] = field(default_factory=list)
    last_updated: datetime | None = None

    def observe(self, at: datetime, weight: float) -> None:
        self.weight_history.append((at, weight))
        self.weight = weight
        self.last_updated = at
        if len(self.weight_history) > 2:
            self.dispersion = statistics.stdev(w for _, w in self.weight_history)


@dataclass(frozen=True)
class AnomalyEvent:
    """Emitted on a threshold crossing. This is what opens a spark — the trigger,
    not the thesis."""

    id: str
    at: datetime
    edge_id: str
    node_id: str
    phenomenon: str
    magnitude: float          # in units of the edge's own historical dispersion
    direction: str            # "rose" | "fell"
    window: tuple[datetime, datetime]


class MarketGraph:
    def __init__(self, registry: SourceRegistry):
        self.registry = registry
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, Edge] = {}

    def upsert_node(self, node_id: str, type_: str, label: str, at: datetime | None = None) -> Node:
        assert type_ in NODE_TYPES, f"unknown node type {type_}"
        n = self.nodes.get(node_id)
        if n is None:
            n = self.nodes[node_id] = Node(node_id, type_, label)
        n.last_updated = at or n.last_updated
        return n

    def upsert_edge(self, source: str, target: str, type_: str) -> Edge:
        assert type_ in EDGE_TYPES, f"unknown edge type {type_}"
        eid = f"{source}->{target}:{type_}"
        e = self.edges.get(eid)
        if e is None:
            e = self.edges[eid] = Edge(eid, source, target, type_)
        return e

    def ingest_window(self, events: tuple[Event, ...], window: tuple[datetime, datetime]) -> None:
        """One observation window becomes one weight sample per (entity, phenomenon)
        edge. Weights are computed from the events, never authored."""
        lo, hi = window
        buckets: dict[tuple[str, str], list[float]] = {}
        weights: dict[tuple[str, str], list[float]] = {}
        aggs: dict[tuple[str, str], Aggregation] = {}
        for ev in events:
            if not (lo <= ev.event_time < hi):
                continue
            em = self.registry.emission_for(ev.record) if ev.record else None
            if em is None:
                continue
            subject = ev.subject
            entity = _entity_of(subject)
            self.upsert_node(entity, "entity", entity, ev.knowable_at)
            ph = em.records_of.value
            self.upsert_node(f"phen:{ph}", "narrative", ph, ev.knowable_at)
            v = float(ev.value.get(em.value_field, 1.0)) if em.value_field else 1.0
            key = (entity, ph)
            buckets.setdefault(key, []).append(v)
            weights.setdefault(key, []).append(
                float(ev.value.get(em.quantity.weight_field or "", 1.0)))
            # An emission with no scalar is a count: one record, one occurrence.
            aggs[key] = em.quantity.aggregation if em.value_field else Aggregation.ADDITIVE

        for key, values in buckets.items():
            entity, ph = key
            edge = self.upsert_edge(entity, f"phen:{ph}", "observes")
            # The declared aggregation, not a blanket sum. Summing an averageable
            # field (a return) produces a number with no meaning, and the graph
            # then fires anomalies the observation layer correctly calls invariant.
            edge.observe(hi, _aggregate(values, weights[key], aggs[key]))

    def detect(self, window: tuple[datetime, datetime], z: float,
               relative_floor: float) -> list[AnomalyEvent]:
        """Threshold crossing on an edge's own historical dispersion.

        Both parameters are required and neither has a default. An anomaly
        detector with a built-in threshold hides the one number that governs its
        false-positive rate, and that rate is the only thing making the detector
        meaningful.

        `relative_floor` is the second parameter because the first alone is
        degenerate: when prior windows are nearly identical the scale collapses
        and any move reads as hundreds of sigma. The floor says "a move smaller
        than this fraction of the level is not an anomaly however quiet things
        have been", which is a statement about the field, not about the detector.
        """
        out: list[AnomalyEvent] = []
        for edge in self.edges.values():
            hist = [w for _, w in edge.weight_history]
            if len(hist) < 4 or edge.dispersion <= 0:
                continue
            *prior, latest = hist
            baseline = statistics.median(prior)
            # The SAME noise estimator the observation layer uses. When the graph
            # and the cancellation disagree about what moved, the trigger is
            # noise and the spark opens on nothing — so they share the estimator
            # rather than each having its own.
            scale = max(_robust_scale(prior), abs(baseline) * relative_floor)
            if scale <= 0:
                continue
            magnitude = (latest - baseline) / scale
            if abs(magnitude) >= z:
                out.append(AnomalyEvent(
                    id=f"anom_{edge.id}_{window[1]:%Y%m%d}",
                    at=window[1], edge_id=edge.id, node_id=edge.source,
                    phenomenon=edge.target.removeprefix("phen:"),
                    magnitude=round(magnitude, 4),
                    direction="rose" if magnitude > 0 else "fell",
                    window=window,
                ))
        return out


def _entity_of(subject: str) -> str:
    from fixtures.dataset import INSTRUMENT_OF   # spine lookup, declared as data
    return INSTRUMENT_OF.get(subject, subject)
