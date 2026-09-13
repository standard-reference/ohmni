"""Corroboration — accumulation, not binary verdicts.

Independence *weights* alignment rather than gating it: two half-independent
corroborations are worth roughly one, not two-that-pass. Verdicts are retained as
artifacts with a support contribution, because the rejected half is the record of
what the data ruled out.

The corroborating legs here come from the **invariant** set, which is the valuable
half of a cancellation. "One edge moved and these three measured processes did
not" is a specific claim, and each of those processes is an independent leg
supporting it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from contract import Phenomenon, SourceRegistry

from .claims import PredictedEffect, Sign, predicted_effect_artifact, two_tier_alignment
from .independence import independence
from .potency import ROLE_WEIGHTS, PotencyReader


@dataclass
class Leg:
    id: str
    source_id: str
    phenomenon: Phenomenon
    claim: object                 # Artifact
    potency: float
    support_cap: float = 1.0
    independence: float = 1.0
    alignment: float = 0.0
    support_contribution: float = 0.0
    capped_by: str = ""


@dataclass
class Support:
    legs: list[Leg] = field(default_factory=list)
    total: float = 0.0
    cluster_caps: dict[str, float] = field(default_factory=dict)

    def summary(self) -> str:
        return (f"support={self.total:.3f} from {len(self.legs)} legs "
                f"({', '.join(l.phenomenon.value for l in self.legs)})")


def corroborate(
    predicted: PredictedEffect,
    invariant_legs: list[tuple[str, Phenomenon, tuple]],   # (source_id, phenomenon, records)
    registry: SourceRegistry,
    reader: PotencyReader,
    spark_id: str,
    cluster_cap: float,
) -> Support:
    """`cluster_cap` is required and has no default.

    Log-odds summation assumes conditional independence given the hypothesis, and
    the independence here is estimated from proxies. Without a cap on any
    correlated cluster's total contribution this walks straight into classic
    ensemble overconfidence, so the cap is a declared input rather than a constant
    buried in the arithmetic.
    """
    support = Support()
    for source_id, phenomenon, records in invariant_legs:
        # Each invariant leg asserts the same bounded no-move claim, measured by a
        # different process.
        leg_effect = PredictedEffect(
            subject=predicted.subject, sign=Sign.NEUTRAL,
            magnitude=predicted.magnitude, horizon=predicted.horizon,
            description=f"{phenomenon.value} held within dispersion over the window",
        )
        claim = predicted_effect_artifact(leg_effect, f"{spark_id}_{source_id}")
        pot = max((reader.potency(r, phenomenon) for r in records), default=0.0)
        cap = max((reader.support_cap_for(r) for r in records), default=0.0)
        support.legs.append(Leg(id=f"leg_{source_id}", source_id=source_id,
                                phenomenon=phenomenon, claim=claim, potency=pot,
                                support_cap=cap))

    pred_artifact = predicted_effect_artifact(predicted, spark_id)
    for leg in support.legs:
        a = two_tier_alignment(leg.claim, pred_artifact)
        leg.alignment = 1.0 if a["compatible"] else 0.0

    # Pairwise independence against every other leg, taking the worst: a leg that
    # duplicates any other is discounted by that duplication.
    records_by_leg = {sid: recs for sid, _, recs in invariant_legs}
    for leg in support.legs:
        worst = 1.0
        for other in support.legs:
            if other is leg:
                continue
            r = independence(records_by_leg[leg.source_id],
                             records_by_leg[other.source_id], registry, reader)
            worst = min(worst, r.score)
        leg.independence = round(worst, 4)

    by_phenomenon: dict[str, float] = {}
    for leg in support.legs:
        # Potency carries the role's weight; the role's declared support cap
        # bounds what one leg of that kind may contribute regardless.
        raw = min(leg.alignment * leg.independence * leg.potency, leg.support_cap)
        # log-odds, so accumulating legs is additive rather than multiplicative
        contribution = math.log1p(max(raw, 0.0))
        cluster = leg.phenomenon.value
        used = by_phenomenon.get(cluster, 0.0)
        allowed = max(0.0, cluster_cap - used)
        if contribution > allowed:
            leg.capped_by = f"cluster:{cluster}"
            contribution = allowed
        by_phenomenon[cluster] = used + contribution
        leg.support_contribution = round(contribution, 4)

    support.cluster_caps = {k: round(v, 4) for k, v in by_phenomenon.items()}
    support.total = round(sum(l.support_contribution for l in support.legs), 4)
    return support
