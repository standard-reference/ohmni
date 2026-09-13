"""End to end: data layer -> bus -> graph -> anomaly -> spark.

Every number that has no principled default lives in `RunPolicy`, is required,
and is recorded in the run manifest. Thresholds are not eliminated — at some
point the system must act, and acting is a discretisation — but they are all
visible in one declared object rather than scattered as defaults nobody can find,
and the ones derived from a control say so.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from contract import DataLayer, Phenomenon, SourceRegistry

from .bus import Bus
from .claims import observation_artifact, predicted_effect_artifact
from .corroboration import corroborate
from .graph import MarketGraph
from .invalidation import build_tree, hysteresis_for, thesis_state
from .mechanism import propose, specificity_of
from .observation import observe
from .potency import PotencyReader
from .spark import Spark, SparkStatus


@dataclass(frozen=True)
class RunPolicy:
    """Declared before the run, recorded in the manifest, never defaulted.

    `moved_tolerance` is the only one derived rather than chosen: it comes from
    the null control's own ceiling, so it is a property of the data rather than a
    number someone liked.
    """

    anomaly_z: float
    anomaly_relative_floor: float
    moved_tolerance: float
    moved_tolerance_source: str
    cluster_cap: float
    specificity_floor: float
    support_threshold: float
    hysteresis_fraction: float
    k_broken_legs: int
    delta_reality_days: int
    #: `degraded` must cut size aggressively, not cosmetically — that is what
    #: makes hysteresis's slow-kill cost acceptable.
    degraded_multiplier: float
    support_scale: float
    inference_delay_minutes: int
    min_frames_before_deciding: int


@dataclass
class SparkLog:
    spark: Spark | None
    anomalies: list
    observation: object
    moved: dict
    invariant: list
    candidates: list
    #: Anomalies on phenomena the declared basis cannot express. NOT sparks — the
    #: observation has nothing to say about them — but not discarded either:
    #: "something moved that this basis cannot see" is how basis coverage is
    #: measured and how the vocabulary learns what it is missing.
    coverage_gaps: list = field(default_factory=list)
    support: object = None
    tree: object = None
    thesis: object = None
    gate: dict | None = None
    policy: RunPolicy | None = None
    manifest: object = None


def field_phenomena(basis, registry: SourceRegistry) -> dict[str, Phenomenon]:
    """Which phenomenon each basis field observes — read from the emitting
    source's declaration, never from a table maintained here."""
    out = {}
    for bf in basis.fields:
        try:
            _, em = registry.resolve(bf.kind, bf.source_id)
        except KeyError:
            continue
        out[bf.name] = em.records_of
    return out


def run(layer: DataLayer, basis, start: datetime, entity_id: str, subject: str,
        policy: RunPolicy, registry: SourceRegistry) -> SparkLog:
    bus = Bus(layer, start)
    horizon = start + basis.frame_span * basis.frame_count
    events = tuple(bus.replay(horizon))
    bus.manifest.degradation_notes.append(f"policy: {asdict(policy)}")

    graph = MarketGraph(registry)
    anomalies = []
    for i in range(basis.frame_count):
        lo = start + basis.frame_span * i
        window = (lo, lo + basis.frame_span)
        graph.ingest_window(events, window)
        anomalies.extend(graph.detect(window, policy.anomaly_z,
                                      policy.anomaly_relative_floor))

    obs = observe(events, basis, start, registry)
    phen = field_phenomena(basis, registry)
    moved = {n: s.shape for n, s in obs.separations.items()
             if s.ratio > policy.moved_tolerance}
    invariant = sorted(n for n in obs.separations if n not in moved)

    # A basis is a declared stance, so a phenomenon outside it is not a weak
    # signal — it is unrepresentable, and a spark cannot be opened against an
    # observation that structurally cannot speak to its own trigger.
    in_basis = {p.value for p in phen.values()}
    # Scoped to the entity under analysis: a spark opened on one name from
    # another name's anomaly is attributing a move to the wrong subject.
    mine = [a for a in anomalies if a.node_id == entity_id]
    triggering = [a for a in mine if a.phenomenon in in_basis]
    gaps = [a for a in mine if a.phenomenon not in in_basis]

    log = SparkLog(spark=None, anomalies=triggering, observation=obs, moved=moved,
                   invariant=invariant, candidates=[], policy=policy,
                   manifest=bus.manifest, coverage_gaps=gaps)
    if not triggering:
        return log

    trigger = max(triggering, key=lambda a: abs(a.magnitude))
    spark = Spark(id=f"spk_{trigger.id}", kind="spark.v1_four_principle",
                  opened_at=trigger.at,
                  trigger={"graph_ref": trigger.edge_id, "anomaly_event": trigger.id,
                           "magnitude": trigger.magnitude})

    obs_art = observation_artifact(obs, basis, trigger.id)
    obs_art.attributes["invariant"] = invariant
    spark.fill("observation", obs_art.id, obs)

    candidates = propose(obs, moved, set(invariant), phen, graph, entity_id,
                         subject, basis.frame_span)
    log.candidates = candidates
    spark.rejected = [{"template": c.template.id, "reasons": c.reasons}
                      for c in candidates if not c.accepted]
    accepted = [c for c in candidates if c.accepted]
    log.spark = spark
    if not accepted:
        spark.status = SparkStatus.DISCARDED
        spark.notes.append("no mechanism template survived the deterministic gates")
        return log

    best = max(accepted, key=lambda c: specificity_of(c, len(moved), len(invariant)))
    best.specificity = specificity_of(best, len(moved), len(invariant))
    pred_art = predicted_effect_artifact(best.predicted, spark.id)
    spark.fill("mechanism", pred_art.id, best)

    reader = PotencyReader(registry, tuple(e.record for e in events if e.record))
    legs = []
    for name in invariant:
        bf = next((f for f in basis.fields if f.name == name), None)
        if bf is None or name not in phen:
            continue
        recs = tuple(e.record for e in events
                     if e.record and e.source_id == bf.source_id and e.kind == bf.kind)
        if recs:
            legs.append((bf.source_id, phen[name], recs))

    support = corroborate(best.predicted, legs, registry, reader, spark.id,
                          policy.cluster_cap)
    log.support = support
    spark.fill("corroboration", f"corr_{spark.id}", support)

    n = hysteresis_for(best.predicted.horizon, basis.frame_span,
                       policy.hysteresis_fraction)
    tree = build_tree(spark.id, best.predicted, support,
                      obs_art.attributes["residue"], n,
                      timedelta(days=policy.delta_reality_days))
    spark.fill("invalidation", tree.id, tree)
    log.tree = tree
    log.thesis = thesis_state(tree, policy.k_broken_legs)
    log.gate = spark.gate(specificity_floor=policy.specificity_floor,
                          support_threshold=policy.support_threshold)
    if log.gate["promotable"]:
        spark.status = SparkStatus.PROMOTED
    return log


# ── from spark to strategy ──────────────────────────────────────────────────

def compile_strategy(log: SparkLog, basis, registry: SourceRegistry,
                     universe: list[str]):
    """A spark becomes a generic trade type, and trade types compose a strategy.

    Nothing about a specific entity or date crosses this boundary: the trade type
    names basis fields and phenomena, and the universe is a coverage requirement
    rather than a list of names.
    """
    from .strategy import build_strategy, compile_trade_type

    # A strategy is compiled from a promoted spark, never from a complete one.
    # Compiling an ungated spark makes the gate decorative: the thesis would reach
    # capital regardless of whether it cleared specificity and support.
    if log.spark is None or log.spark.status is not SparkStatus.PROMOTED:
        return None, None
    tt = compile_trade_type(
        log.spark, log.observation, log.moved, log.invariant,
        field_phenomena(basis, registry), log.support, basis,
        degraded_multiplier=log.policy.degraded_multiplier,
        support_scale=log.policy.support_scale)
    spec = build_strategy(f"strat_{tt.id}", [tt], universe, tt.regime_scope)
    return tt, spec
