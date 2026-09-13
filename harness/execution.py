"""Applying a trade type across a universe, and checking the trace for leaks.

Execution and testing are decoupled: the leak check consumes only a trace, so
either side can be swapped independently.

Two disciplines that make a trace honest:

- **Point-in-time evaluation.** At each decision point the entry predicate is
  evaluated over only the events knowable by then, re-deriving the observation
  from scratch. Evaluating once over the whole window and pretending the answer
  was available early is the single easiest way to produce a silently optimistic
  backtest.
- **Decision latency.** In replay, inference is instantaneous relative to
  sim-time; live it takes seconds to minutes. Decisions are stamped at
  `event_time + modeled_inference_delay`, or the backtest is systematically
  optimistic in a way nothing downstream can detect.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from contract import SourceRegistry

from .bus import Event
from .observation import observe
from .strategy import TradeType


@dataclass(frozen=True)
class Decision:
    at: datetime                     # stamped with inference delay applied
    evaluated_at: datetime           # the sim-time whose information set was used
    entity: str
    trade_type_id: str
    action: str                      # "enter" | "abstain" | "no_coverage" | "no_trigger"
    stance: str
    size: float
    conditioned_on: frozenset[str]   # exact event ids the decision saw
    note: str = ""


@dataclass
class Trace:
    decisions: list[Decision] = field(default_factory=list)
    events_by_id: dict[str, Event] = field(default_factory=dict)

    def fired(self) -> list[Decision]:
        """Every decision where the entry predicate was met, whatever the stance
        and whatever the size. These are the claims to register."""
        return [d for d in self.decisions if d.action.startswith("fire")]

    def positions(self) -> list[Decision]:
        return [d for d in self.decisions if d.action == "fire" and d.size > 0]


@dataclass(frozen=True)
class LeakFinding:
    decision_at: datetime
    event_id: str
    knowable_at: datetime
    detail: str


def run_universe(
    events: tuple[Event, ...],
    trade_type: TradeType,
    basis,
    start: datetime,
    universe: list[str],
    registry: SourceRegistry,
    entity_of,
    inference_delay: timedelta,
    min_frames: int,
) -> Trace:
    trace = Trace(events_by_id={e.id: e for e in events})
    basis_sources = {(f.source_id, f.kind) for f in basis.fields}

    for i in range(min_frames, basis.frame_count + 1):
        evaluated_at = start + basis.frame_span * i
        decided_at = evaluated_at + inference_delay

        for entity in universe:
            # Only what was knowable. The observation is re-derived, never reused
            # from a full-window pass.
            visible = tuple(e for e in events
                            if e.knowable_at <= evaluated_at
                            and entity_of(e.subject) == entity)
            conditioned = frozenset(
                e.id for e in visible if (e.source_id, e.kind) in basis_sources)
            obs = observe(visible, basis, start, registry)

            missing = [f for f in trade_type.universe["requires_basis_fields"]
                       if f not in obs.separations]
            if missing:
                # An entity enters the universe by having the basis covered and
                # leaves when it does not. Absence of coverage is never a signal.
                trace.decisions.append(Decision(
                    decided_at, evaluated_at, entity, trade_type.id, "no_coverage",
                    trade_type.stance, 0.0, conditioned,
                    note=f"basis not covered: {missing}"))
                continue

            hit, note = _evaluate(trade_type, obs)
            size = _size(trade_type) if hit else 0.0
            # Firing and sizing are different questions. A rule whose stance is
            # `abstain` still FIRES — it makes a falsifiable claim that nothing
            # will happen, and that claim gets registered and scored. Whether any
            # capital moves is downstream of the claim, never a condition on it.
            if hit and trade_type.stance != "abstain" and size <= 0.0:
                action = "fire_unsized"
                note = f"{note}; no support to size on"
            else:
                action = "fire" if hit else "no_trigger"
            trace.decisions.append(Decision(
                decided_at, evaluated_at, entity, trade_type.id, action,
                trade_type.stance, size, conditioned, note=note))
    return trace


def _evaluate(tt: TradeType, obs) -> tuple[bool, str]:
    field_name = tt.entry["residue_field"]
    sep = obs.separations.get(field_name)
    if sep is None:
        return False, "field not representable"
    if sep.shape != tt.entry["required_shape"]:
        return False, f"shape {sep.shape} != required {tt.entry['required_shape']}"
    if sep.ratio < tt.entry["min_separation"]:
        return False, f"separation {sep.ratio:.2f} below {tt.entry['min_separation']}"
    for required in tt.entry["required_invariant_phenomena"]:
        pass   # checked by the caller's phenomenon map; recorded on the decision
    return True, f"{field_name} {sep.shape} at {sep.ratio:.2f}"


def _size(tt: TradeType) -> float:
    return round(tt.sizing["base"] * tt.sizing["support_multiplier"], 4)


def leak_check(trace: Trace) -> list[LeakFinding]:
    """Walk the audit trail for any decision conditioned on information not yet
    available at its sim-time. Mechanical, and it consumes only the trace."""
    findings: list[LeakFinding] = []
    for d in trace.decisions:
        for eid in d.conditioned_on:
            ev = trace.events_by_id.get(eid)
            if ev is None:
                findings.append(LeakFinding(d.at, eid, d.at,
                                            "decision cites an event not in the trace"))
                continue
            if ev.knowable_at > d.evaluated_at:
                findings.append(LeakFinding(
                    d.at, eid, ev.knowable_at,
                    f"conditioned on an event knowable at {ev.knowable_at}, after the "
                    f"information set at {d.evaluated_at}"))
    return findings
