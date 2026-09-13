"""Mechanism proposal — deterministic, as a path over graph edges.

The spec keeps a model in this slot. There is no model here, and that is a
deliberate scoping choice rather than a substitute: a mechanism expressed as a
causal path over graph edges is the one form whose plausibility is *partly
deterministic* — do those edges exist, with meaningful weight, in the right
order — and whose invalidation is structural, because the path's edges weakening
IS the reversal condition.

So this proposes from a declared template library, and every rejection is a
stored reason rather than an inline boolean. A model-authored mechanism slots
into the same interface and is checked by the same two deterministic gates below;
what it would add is templates nobody wrote down, which is exactly the thing the
harness exists to find.

Two gates, both computable, both applied before anything downstream:

- **Shape commensurability.** A mechanism claiming "attention persists and
  converts to flow" predicts a sustained path. If the observed residue is a
  spike-and-return, the causal story and the observed path disagree — computably,
  and at a fraction of the cost of a full graph-path requirement.
- **Temporal commensurability.** Frame spacing is the observation's resolution, so
  a horizon finer than one frame is incoherent: the observation cannot see it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from contract import Phenomenon

from .claims import PredictedEffect, Sign

SUSTAINED = ("step", "monotonic_ramp")
TRANSIENT = ("spike_and_return",)


@dataclass(frozen=True)
class MechanismTemplate:
    id: str
    story: str
    requires_moved: tuple[Phenomenon, ...]
    requires_invariant: tuple[Phenomenon, ...]
    #: The path the story asserts, as graph node ids relative to the entity.
    path: tuple[str, ...]
    #: Shapes the story is compatible with, on the field that triggered it.
    compatible_shapes: tuple[str, ...]
    sign: Sign
    magnitude: float
    horizon_frames: int
    regime_scope: str


#: Declared before any result is seen. A template added after seeing which one
#: would have worked is laundered curve-fitting.
TEMPLATES: tuple[MechanismTemplate, ...] = (
    MechanismTemplate(
        id="attention_precedes_flow",
        story=("Sustained information-seeking precedes positioning: retail attention "
               "persists, converts to order flow, and the asset appreciates as flow "
               "catches up."),
        requires_moved=(Phenomenon.INFORMATION_SEEKING,),
        requires_invariant=(Phenomenon.EXCHANGE_ACTIVITY,),
        path=("entity", "phen:information_seeking", "phen:exchange_activity"),
        compatible_shapes=SUSTAINED,
        sign=Sign.POSITIVE, magnitude=0.04, horizon_frames=2,
        regime_scope="any",
    ),
    MechanismTemplate(
        id="transient_attention_no_flow",
        story=("Attention rose and decayed without corroborating coverage, order flow "
               "or positioning. Information-seeking that no other process confirms "
               "reflects a transient interest event rather than a change in the "
               "asset's prospects, so it does not reprice."),
        requires_moved=(Phenomenon.INFORMATION_SEEKING,),
        requires_invariant=(Phenomenon.EXCHANGE_ACTIVITY,
                            Phenomenon.EDITORIAL_PUBLICATION,
                            Phenomenon.OFF_EXCHANGE_ROUTING),
        path=("entity", "phen:information_seeking"),
        compatible_shapes=TRANSIENT,
        sign=Sign.NEUTRAL, magnitude=0.02, horizon_frames=2,
        regime_scope="any",
    ),
    MechanismTemplate(
        id="disclosure_repricing",
        story=("A corporate disclosure changed the information set and the asset "
               "repriced to it in a single step."),
        requires_moved=(Phenomenon.CORPORATE_DISCLOSURE, Phenomenon.EXCHANGE_ACTIVITY),
        requires_invariant=(),
        path=("entity", "phen:corporate_disclosure", "phen:exchange_activity"),
        compatible_shapes=("step",),
        sign=Sign.POSITIVE, magnitude=0.05, horizon_frames=1,
        regime_scope="any",
    ),
    MechanismTemplate(
        id="broad_repricing",
        story=("Every measured process moved together, which is a market-wide shift "
               "with no attribution to this entity."),
        requires_moved=(Phenomenon.INFORMATION_SEEKING, Phenomenon.EXCHANGE_ACTIVITY,
                        Phenomenon.EDITORIAL_PUBLICATION, Phenomenon.OFF_EXCHANGE_ROUTING),
        requires_invariant=(),
        path=("entity", "phen:exchange_activity"),
        compatible_shapes=SUSTAINED,
        sign=Sign.POSITIVE, magnitude=0.03, horizon_frames=2,
        regime_scope="any",
    ),
)


@dataclass
class Candidate:
    template: MechanismTemplate
    accepted: bool
    reasons: list[str] = field(default_factory=list)
    predicted: PredictedEffect | None = None
    path_weights: dict[str, float] = field(default_factory=dict)
    trigger_field: str | None = None
    trigger_shape: str | None = None


def propose(
    observation,
    moved_fields: dict[str, str],       # basis field -> observed shape
    invariant_fields: set[str],
    field_phenomena: dict[str, Phenomenon],
    graph,
    entity_id: str,
    subject: str,
    frame_span: timedelta,
) -> list[Candidate]:
    """Every template is evaluated and every rejection keeps its reason.

    A verdict is a stored, queryable artifact, never an inline boolean — the
    rejected candidates are the record of what the data ruled out, which is the
    half a promotion-only log throws away.
    """
    moved_ph = {field_phenomena[f] for f in moved_fields if f in field_phenomena}
    inv_ph = {field_phenomena[f] for f in invariant_fields if f in field_phenomena}
    out: list[Candidate] = []

    for tpl in TEMPLATES:
        c = Candidate(template=tpl, accepted=True)

        absent = [p.value for p in tpl.requires_moved if p not in moved_ph]
        if absent:
            c.accepted = False
            c.reasons.append(f"required movement absent: {absent}")

        noisy = [p.value for p in tpl.requires_invariant if p not in inv_ph]
        if noisy:
            c.accepted = False
            c.reasons.append(f"required invariance not held: {noisy}")

        trigger = next((f for f, ph in field_phenomena.items()
                        if tpl.requires_moved and ph == tpl.requires_moved[0]
                        and f in moved_fields), None)
        if trigger:
            c.trigger_field = trigger
            c.trigger_shape = moved_fields[trigger]
            if c.trigger_shape not in tpl.compatible_shapes:
                c.accepted = False
                c.reasons.append(
                    f"shape incommensurable: story implies {list(tpl.compatible_shapes)}, "
                    f"observed {c.trigger_shape}")

        # Frame spacing is the observation's resolution; a horizon it cannot see
        # is incoherent regardless of how good the story is.
        horizon = frame_span * tpl.horizon_frames
        if tpl.horizon_frames < 1:
            c.accepted = False
            c.reasons.append("horizon finer than the observation's own resolution")

        for a, b in zip(tpl.path, tpl.path[1:]):
            src = entity_id if a == "entity" else a
            tgt = entity_id if b == "entity" else b
            edge = graph.edges.get(f"{src}->{tgt}:observes")
            if edge is None:
                # Not fatal: the path bonus is optional and the vocabulary is
                # still growing. Requiring path-expressibility early would
                # amputate exactly the novel hypotheses worth finding.
                c.reasons.append(f"path edge absent (not fatal): {src}->{tgt}")
            else:
                c.path_weights[edge.id] = round(edge.weight, 4)

        if c.accepted:
            c.predicted = PredictedEffect(
                subject=subject, sign=tpl.sign, magnitude=tpl.magnitude,
                horizon=horizon,
                description=f"{tpl.story} (regime scope: {tpl.regime_scope})",
            )
        out.append(c)

    return sorted(out, key=lambda c: (not c.accepted, c.template.id))


def specificity_of(candidate: Candidate, moved: int, invariant: int) -> float:
    """Gate on specificity, which is computable, where 'quality' is not.

    One edge moving while correlated peers held invariant is specific; the same
    edge moving while everything moved has no attribution.
    """
    if moved + invariant == 0:
        return 0.0
    localisation = invariant / (moved + invariant)
    tightness = 1.0 if candidate.template.sign is not Sign.NEUTRAL else 0.8
    declared_invariants = len(candidate.template.requires_invariant)
    return round(localisation * tightness * min(1.0, 0.4 + 0.2 * declared_invariants), 4)
