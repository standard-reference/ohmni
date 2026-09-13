"""EffectClaim and Evidence — the shapes everything downstream is expressed in.

An EffectClaim is `(subject, sign, magnitude, horizon)` plus a description. That
shape is deliberately the same one a prediction-market contract already has,
which is what makes external calibration cheap later.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

from .registry import Artifact, EffectClaimKind, EffectClaims

#: A pinned, local, deterministic placeholder. Versioned in the key like a real
#: space so nothing can compare across versions — but it is a hash, not a model,
#: and carries no semantics. Tier-2 alignment is correspondingly weak here; tier 1
#: is where the real work happens and is fully deterministic.
EMBEDDING_SPACE_VERSION = "placeholder_sha256.v1"


def embed_text(text: str, dims: int = 16) -> tuple[float, ...]:
    h = hashlib.sha256(text.encode()).digest()
    return tuple((h[i % len(h)] / 255.0) for i in range(dims))


class Sign(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"      # a bounded no-move claim; falsifiable, not empty


@dataclass(frozen=True)
class PredictedEffect:
    subject: str
    sign: Sign
    magnitude: float          # bound, in the subject's own units
    horizon: timedelta
    description: str

    def as_attributes(self) -> dict:
        return {"subject": self.subject, "sign": self.sign.value,
                "magnitude": self.magnitude,
                "horizon_days": self.horizon.days,
                "description": self.description}


def _embed_frames(attributes: dict) -> tuple[float, ...]:
    """Embeds residue and shape only — never the invariant set and never the raw
    frame values, so two observations that differ only in what stayed still are
    not pushed apart."""
    parts = sorted(f"{k}:{v['shape']}" for k, v in attributes["residue"].items())
    return embed_text("|".join(parts))


EffectClaims.register(EffectClaimKind(
    name="effect_claim.v4_frames",
    schema_version="4.0.0",
    required_attributes=("basis", "frames", "residue", "invariant", "not_representable"),
    embed=_embed_frames,
))

EffectClaims.register(EffectClaimKind(
    name="effect_claim.v1_predicted",
    schema_version="1.0.0",
    required_attributes=("subject", "sign", "magnitude", "horizon_days", "description"),
    embed=lambda a: embed_text(a["description"]),
))


def observation_artifact(obs, basis, anomaly_id: str) -> Artifact:
    """The observation slot's artifact. Note what is NOT collapsed: residue,
    invariant and not_representable are three separate sets, because 'cancelled
    because indistinguishable' and 'not expressible at all' are different states."""
    attributes = {
        "basis": basis.id,
        "basis_version": basis.version,
        "frames": {"count": basis.frame_count, "span_days": basis.frame_span.days},
        "residue": {name: {"separation": s.ratio, "shape": s.shape,
                           "confidence": s.confidence,
                           "trajectory": list(s.trajectory)}
                    for name, s in obs.separations.items()},
        "invariant": [],          # a view; filled by the caller's own tolerance
        "not_representable": dict(obs.not_representable),
        "anchor": {"anomaly_event": anomaly_id},
    }
    art = EffectClaims.build("effect_claim.v4_frames", f"obs_{anomaly_id}", attributes)
    return Artifact(**{**art.__dict__,
                       "embeddings": {EMBEDDING_SPACE_VERSION: _embed_frames(attributes)}})


def predicted_effect_artifact(effect: PredictedEffect, spark_id: str) -> Artifact:
    attrs = effect.as_attributes()
    art = EffectClaims.build("effect_claim.v1_predicted", f"pred_{spark_id}", attrs)
    return Artifact(**{**art.__dict__,
                       "embeddings": {EMBEDDING_SPACE_VERSION: embed_text(effect.description)}})


# ── two-tier alignment ──────────────────────────────────────────────────────

def two_tier_alignment(a: Artifact, b: Artifact) -> dict:
    """Hard structural compatibility FIRST, embedding similarity second.

    Embedding similarity is weak exactly on the fields that matter most: a claim
    about one asset rising over a week cannot corroborate a claim about another
    falling over a month, however similar the prose. So structure gates, and
    similarity only refines what survives.
    """
    aa, ab = a.attributes, b.attributes
    reasons: list[str] = []
    if aa.get("subject") != ab.get("subject"):
        reasons.append("different_subject")
    if aa.get("sign") != ab.get("sign"):
        reasons.append("different_sign")
    ha, hb = aa.get("horizon_days"), ab.get("horizon_days")
    if ha and hb and not (0.5 <= ha / hb <= 2.0):
        reasons.append("horizon_incommensurable")
    if reasons:
        return {"compatible": False, "reasons": reasons, "similarity": 0.0, "score": 0.0}

    va = a.embedding(EMBEDDING_SPACE_VERSION)
    vb = b.embedding(EMBEDDING_SPACE_VERSION)
    sim = _cosine(va, vb) if va and vb else 0.0
    return {"compatible": True, "reasons": [], "similarity": round(sim, 4),
            "score": round(sim, 4)}


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = sum(x * x for x in a) ** 0.5
    db = sum(y * y for y in b) ** 0.5
    return num / (da * db) if da and db else 0.0
