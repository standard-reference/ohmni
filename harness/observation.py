"""A REFERENCE CONSUMER of the data layer, not part of the data product.

Every transform here is lossy — aggregating hourly views to a weekly total throws
away the hours — and that is precisely why it lives on this side of the seam. The
data layer serves records at their native cadence and *declares* which
aggregations are valid; performing one is a consumer's decision, made knowing
what it costs. A layer that pre-aggregated would have destroyed information no
consumer could recover, in a form nobody asked for.

Kept here because running it end-to-end proves the data arrives usable, and
because it is a worked example of what the declarations make computable. Nothing
downstream is obliged to use it.

B2 — the basis, frames, and delta by cancellation.

Text embedding spaces are not reliably linear, so `embed(final) − embed(initial)`
is not a usable representation of "what changed". Instead: cancel every field that
did not change, keep only what survives.

Three states that must never collapse into one — "cancelled because
indistinguishable", "separated", and "not representable in this basis at all".
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from contract import Aggregation, SourceRegistry, cadence_rank

from .bus import Event


@dataclass(frozen=True)
class BasisField:
    """A basis names *which emission it selects*. Cadence, aggregation, units and
    value location all come from that emission's own declaration — there is no
    per-field table here to keep in step with the sources."""

    name: str
    source_id: str
    kind: str


@dataclass(frozen=True)
class Basis:
    """A declared stance, fixed for the lifetime of an observation.

    Not an attempt at a complete description of the world, so an omission is not a
    silent error: mechanism, corroboration and invalidation are expressed over the
    same selected points, which makes everything downstream commensurable with the
    observation by construction.
    """

    id: str
    fields: tuple[BasisField, ...]
    resolution: str                  # ISO-8601; the observation's own cadence
    frame_count: int                 # declared before anything downstream
    frame_span: timedelta
    version: str = "basis.v1"

    def field_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields)


@dataclass
class FrameState:
    estimate: float | None
    dispersion: float
    n: int
    confidence: float = 1.0


@dataclass(frozen=True)
class FieldSeparation:
    """How far a field's frames pulled apart, kept as a magnitude.

    Deliberately NOT a verdict. There is no cut point here: storing
    residue-vs-invariant at this layer would discard the magnitude before anything
    downstream could weigh it, and would freeze a threshold into the artifact that
    every later consumer is then stuck with.
    """

    field: str
    ratio: float             # discounted separation, in units of the field's own noise
    undiscounted: float      # before entity-resolution confidence was applied
    confidence: float
    frames: tuple[int, int]
    shape: str
    trajectory: tuple[float, ...]


@dataclass
class Observation:
    basis_id: str
    frames: list[dict[str, FrameState]] = field(default_factory=list)
    separations: dict[str, FieldSeparation] = field(default_factory=dict)
    not_representable: dict[str, str] = field(default_factory=dict)

    def ratios(self) -> dict[str, float]:
        return {k: v.ratio for k, v in self.separations.items()}


_AGG = {
    Aggregation.ADDITIVE: lambda xs, w: sum(xs),
    Aggregation.AVERAGEABLE: lambda xs, w: statistics.fmean(xs),
    Aggregation.POINT_IN_TIME: lambda xs, w: xs[-1],
}


def _aggregate(values: list[float], weights: list[float], agg: Aggregation) -> float:
    if agg is Aggregation.WEIGHTED_AVERAGE:
        total = sum(weights)
        if total <= 0:
            raise ValueError("weighted_average with no weight")
        return sum(v * w for v, w in zip(values, weights)) / total
    return _AGG[agg](values, weights)


def observe(
    events: tuple[Event, ...],
    basis: Basis,
    start: datetime,
    registry: SourceRegistry,
    apply_resolution_confidence: bool = True,
) -> Observation:
    obs = Observation(basis_id=basis.id)
    windows = [(start + basis.frame_span * i, start + basis.frame_span * (i + 1))
               for i in range(basis.frame_count)]

    usable: list[BasisField] = []
    for bf in basis.fields:
        try:
            _, em = registry.resolve(bf.kind, bf.source_id)
        except KeyError:
            obs.not_representable[bf.name] = "not_declared"
            continue
        if em.value_field is None and em.quantity.aggregation is not Aggregation.ADDITIVE:
            obs.not_representable[bf.name] = "no_scalar"
            continue
        if em.quantity.aggregation is Aggregation.NON_AGGREGABLE:
            obs.not_representable[bf.name] = "non_aggregable"
            continue
        if not em.is_irregular:
            src_rank, basis_rank = cadence_rank(em.native_cadence), cadence_rank(basis.resolution)
            if src_rank is None or basis_rank is None:
                obs.not_representable[bf.name] = "cadence_undeclared"
                continue
            if src_rank > basis_rank:
                # Aggregating fine → coarse is arithmetic over observed values.
                # Disaggregating coarse → fine is interpolation, which manufactures
                # values nobody observed. Refused, never forward-filled.
                obs.not_representable[bf.name] = "cadence_incoherent"
                continue
        usable.append(bf)

    for lo, hi in windows:
        state: dict[str, FrameState] = {}
        for bf in usable:
            _, em = registry.resolve(bf.kind, bf.source_id)
            rows = [e for e in events
                    if e.source_id == bf.source_id and e.kind == bf.kind
                    and lo <= e.event_time < hi]
            if not rows:
                state[bf.name] = FrameState(None, 0.0, 0)
                continue
            conf = statistics.fmean(
                [float(e.value.get("resolution_confidence", 1.0)) for e in rows])
            if em.value_field is None:
                # An irregular stream has no native cadence and becomes a
                # rate-per-window field: "articles in this window: 3".
                est = float(len(rows))
                disp = max(math.sqrt(est), 1.0)          # counting noise
                state[bf.name] = FrameState(est, disp, len(rows), conf)
                continue
            vals = [float(e.value[em.value_field]) for e in rows]
            wts = [float(e.value.get(em.quantity.weight_field or "", 1.0)) for e in rows]
            # Sub-window aggregates give the dispersion an honest denominator.
            daily: dict[str, list[float]] = {}
            dailyw: dict[str, list[float]] = {}
            for e, v, w in zip(rows, vals, wts):
                k = e.event_time.strftime("%Y-%m-%d")
                daily.setdefault(k, []).append(v)
                dailyw.setdefault(k, []).append(w)
            # ONE application of the declared rule, over the raw values. The
            # earlier version aggregated to days and then averaged those, which
            # silently turned an additive field into a mean — a lossy transform
            # nobody declared. Sub-aggregates are used only to estimate a scale.
            est = _aggregate(vals, wts, em.quantity.aggregation)
            sub = [_aggregate(daily[k], dailyw[k], em.quantity.aggregation)
                   for k in sorted(daily)]
            disp = statistics.stdev(sub) if len(sub) > 1 else 0.0
            state[bf.name] = FrameState(est, disp, len(rows), conf)
        obs.frames.append(state)

    for bf in usable:
        _measure(obs, bf.name, apply_resolution_confidence)
    for bf in basis.fields:
        if bf.name not in obs.separations and bf.name not in obs.not_representable:
            obs.not_representable[bf.name] = "not_covered"
    return obs


def _robust_scale(values: list[float]) -> float:
    """A robust estimate of a field's frame-to-frame noise.

    Cancellation asks "did this field move beyond its own normal wobble?", so the
    null it is judged against must be the field's own variability, not the
    sampling noise inside one window. Within-window noise shrinks with sample
    size, which would make a densely-sampled flat field separate on nothing.

    Median absolute consecutive difference, scaled to a standard deviation. Robust
    because a genuine step inflates it only slightly — and inflating it errs
    toward cancelling, which is the conservative direction.
    """
    if len(values) < 2:
        return 0.0
    diffs = [abs(b - a) for a, b in zip(values, values[1:])]
    step = 1.4826 * statistics.median(diffs) if diffs else 0.0
    # A series that repeats values (an alternating low-cardinality field, or a
    # shuffle that happens to produce runs) drives the median consecutive
    # difference to zero and the ratio to infinity. Spread is the second view of
    # the same noise and does not collapse that way; take the larger.
    med = statistics.median(values)
    spread = 1.4826 * statistics.median([abs(v - med) for v in values])
    return max(step, spread)


def _measure(obs: Observation, name: str, apply_conf: bool) -> None:
    states = [f.get(name) for f in obs.frames]
    live = [(i, s) for i, s in enumerate(states) if s and s.estimate is not None]
    if len(live) < 2:
        obs.not_representable[name] = "not_covered"
        return

    traj = [s.estimate for _, s in live]
    scale = _robust_scale(traj)
    if scale <= 0:
        scale = max([s.dispersion for _, s in live] + [1e-9])

    best = (0.0, 0, 0)
    for a in range(len(live)):
        for b in range(a + 1, len(live)):
            (ia, sa), (ib, sb) = live[a], live[b]
            da, db = max(sa.dispersion, scale), max(sb.dispersion, scale)
            denom = math.sqrt(da ** 2 + db ** 2) or 1e-9
            ratio = abs(sa.estimate - sb.estimate) / denom
            if ratio > best[0]:
                best = (ratio, ia, ib)

    conf = statistics.fmean([s.confidence for _, s in live])
    # Mis-linking a mention makes a field appear to change when nothing did —
    # residue that is really entity drift, indistinguishable from a finding. The
    # confidence must reach this computation, not sit in a log.
    obs.separations[name] = FieldSeparation(
        field=name,
        ratio=round(best[0] * conf if apply_conf else best[0], 6),
        undiscounted=round(best[0], 6),
        confidence=round(conf, 6),
        frames=(best[1], best[2]),
        shape=_shape(traj),
        trajectory=tuple(traj),
    )


def _shape(traj: list[float]) -> str:
    """Residue carries a trajectory shape, and a mechanism's causal story can be
    checked against it computably. A mechanism claiming "attention precedes
    appreciation as flow catches up over 3–5 days" predicts a ramp; if the residue
    is a step, the story and the observed path disagree."""
    base = statistics.fmean(traj[:2])
    devs = [v - base for v in traj]
    peak = max(devs, key=abs)
    if abs(peak) < 1e-12:
        return "flat"
    # Path-aware by construction: a spike-and-return survives because mid-frames
    # separate even though the endpoints cancel.
    if abs(devs[-1]) < 0.3 * abs(peak):
        return "spike_and_return"
    steps = [traj[i + 1] - traj[i] for i in range(len(traj) - 1)]
    biggest = max(steps, key=abs)
    if abs(biggest) > 0.5 * abs(devs[-1]):
        return "step"
    signs = [1 if s > 0 else -1 for s in steps if abs(s) > 0.1 * abs(peak)]
    if sum(1 for a, b in zip(signs, signs[1:]) if a != b) >= 2:
        return "oscillation"
    return "monotonic_ramp"


def peak_frame(trajectory: list[float]) -> int:
    base = statistics.fmean(trajectory[:2])
    devs = [abs(v - base) for v in trajectory]
    return devs.index(max(devs))


def cross_field_alignment(fields: "list[FieldSeparation]") -> float | None:
    """Do the fields that moved, move *together*?

    This is the quantity a shuffled null destroys. Per-field cancellation is not
    protected by a shuffle — each field keeps its own marginal distribution, so a
    spike still appears, just in a different week. What the null removes is the
    joint structure, and that is therefore what a null control can actually test.
    """
    peaks = [peak_frame(list(s.trajectory)) for s in fields]
    if len(peaks) < 2:
        return None      # alignment is undefined below two fields, never 1.0
    modal = max(set(peaks), key=peaks.count)
    return peaks.count(modal) / len(peaks)
