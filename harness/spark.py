"""The Spark — four principles, with the ordering rule expressed as data.

Principle set, fill ordering and the promotion gate are all registry data, so a
strict and a looser variant coexist as entries and which survives becomes
empirical rather than a one-time design choice.

Historical precedent is deliberately excluded as a principle: a model's claimed
recollection is unverified token recall. Genuine precedent belongs to the
robustness pass, which runs a real point-in-time replay.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .registry import Artifact, SparkKind, Sparks


class SparkStatus(str, Enum):
    OPEN = "open"
    COMPLETE = "complete"
    PROMOTED = "promoted"
    DISCARDED = "discarded"


@dataclass
class PrincipleSlot:
    filled: bool = False
    artifact_ref: str | None = None
    payload: object = None


class OrderingViolation(Exception):
    """A slot filled before its prerequisite. The ordering is a real invariant —
    corroboration of a mechanism that does not exist yet is corroboration of
    nothing — so it raises rather than warns."""


@dataclass
class Spark:
    id: str
    kind: str
    opened_at: datetime
    trigger: dict
    principles: dict[str, PrincipleSlot] = field(default_factory=dict)
    status: SparkStatus = SparkStatus.OPEN
    notes: list[str] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)

    def schema(self) -> dict:
        return Sparks.lookup(self.kind).principle_schema

    def fill(self, name: str, artifact_ref: str, payload: object = None) -> None:
        schema = self.schema()
        if name not in schema:
            raise OrderingViolation(f"{self.kind} has no principle {name!r}")
        for required in schema[name].get("requires", []):
            slot = self.principles.get(required)
            if slot is None or not slot.filled:
                raise OrderingViolation(
                    f"cannot fill {name!r} before {required!r} — the ordering rule is "
                    "data on the kind, not a convention")
        self.principles[name] = PrincipleSlot(True, artifact_ref, payload)
        if all(self.principles.get(n, PrincipleSlot()).filled for n in schema):
            self.status = SparkStatus.COMPLETE

    def gate(self, **kw) -> dict:
        return Sparks.lookup(self.kind).promotable(self, **kw)


def _promotable_v1(spark: Spark, specificity_floor: float, support_threshold: float) -> dict:
    """Gate on specificity and accumulated support, both supplied by the caller.

    Neither has a default. The specificity floor cannot be set correctly until the
    calibration ledger has data — it is an open question, and a number invented
    here would look like an answer.

    Specificity alone is gameable in the opposite direction: spurious precision
    scores brilliantly. It only works paired with the calibration ledger, where
    specificity gates promotion and calibration punishes over-narrow claims after
    the fact. Neither works alone, and only the first half exists yet.
    """
    schema = Sparks.lookup(spark.kind).principle_schema
    unfilled = [n for n in schema if not spark.principles.get(n, PrincipleSlot()).filled]
    mech = spark.principles.get("mechanism")
    corr = spark.principles.get("corroboration")

    specificity = getattr(mech.payload, "specificity", 0.0) if mech and mech.payload else 0.0
    support = getattr(corr.payload, "total", 0.0) if corr and corr.payload else 0.0

    reasons = []
    if unfilled:
        reasons.append(f"unfilled principles: {unfilled}")
    if specificity < specificity_floor:
        reasons.append(f"specificity {specificity:.3f} below floor {specificity_floor}")
    if support < support_threshold:
        reasons.append(f"accumulated support {support:.3f} below threshold {support_threshold}")

    return {"promotable": not reasons, "reasons": reasons,
            "specificity": round(specificity, 4), "support": round(support, 4)}


Sparks.register(SparkKind(
    name="spark.v1_four_principle",
    schema_version="1.0.0",
    principle_schema={
        "observation":   {"requires": []},
        "mechanism":     {"requires": ["observation"]},
        # The ordering rule, as data: corroboration of a mechanism that does not
        # exist yet is corroboration of nothing.
        "corroboration": {"requires": ["mechanism"]},
        "invalidation":  {"requires": []},
    },
    promotable=_promotable_v1,
))
