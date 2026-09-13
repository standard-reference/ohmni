"""What the harness actually needs from the data layer, checked as presentation.

Not "is this number right" — there is no oracle for that and the layer never
claims one. The question here is narrower and answerable: **did everything the
harness needs in order not to be misled actually arrive, and arrive labelled?**

Four things, each of which a consumer cannot reconstruct if the layer omits it:

  1. availability, so nothing is read before it was knowable
  2. typed gaps with reasons, so absence is distinguishable from zero
  3. declared structure — phenomenon, role, lineage, coupling — so evidence can be
     weighed without inferring anything from text
  4. declared algebra — dimension, unit, cadence, aggregation — so the consumer
     knows which operations are valid before performing one

A silent gap is the failure mode all four exist to prevent, because a consumer
cannot detect one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from contract import (
    Aggregation,
    Dimension,
    Record,
    SourceRegistry,
    Status,
    cadence_rank,
)


@dataclass
class CoverageEnvelope:
    """`complete: false` with enumerated reasons is worth more than more data.

    A consumer cannot detect a silent gap, so gaps are made first-class rather
    than left as an absence to be noticed.
    """

    requested: tuple[datetime, datetime]
    records_returned: int = 0
    gaps: list[dict] = field(default_factory=list)
    truncated: bool = False

    @property
    def complete(self) -> bool:
        return not self.gaps and not self.truncated

    def reasons(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for g in self.gaps:
            out[g["status"]] = out.get(g["status"], 0) + 1
        return out


def coverage(records: tuple[Record, ...], window: tuple[datetime, datetime]) -> CoverageEnvelope:
    env = CoverageEnvelope(requested=window)
    for r in records:
        if r.status.is_gap:
            env.gaps.append({"id": r.id, "subject": r.subject,
                             "status": r.status.value,
                             "reason": r.value.get("reason")})
        else:
            env.records_returned += 1
    return env


# ── field algebra: what operations the declarations permit ──────────────────
#
# Telling a consumer what it cannot do, and why, prevents more errors than
# telling it what it can. Fully derived from declared metadata; nothing stored.

DIMENSIONLESS = {Dimension.PROBABILITY, Dimension.RATIO, Dimension.INDEX}


@dataclass(frozen=True)
class Relatability:
    verdict: str
    resolution: str | None
    required_transforms: tuple[dict, ...]
    valid_operations: tuple[str, ...]
    blocked_operations: tuple[dict, ...]
    note: str = ""


def relate(registry: SourceRegistry, a: tuple[str, str], b: tuple[str, str]) -> Relatability:
    """`a` and `b` are (source_id, kind). Answers what is VALID, never what is true.

    The moment this returns "these correlate at 0.7" the product becomes a signal
    vendor with undisclosed methodology — the thing it exists as a reaction
    against. The consumer forms the hypothesis; the harness tests it.
    """
    _, ea = registry.resolve(a[1], a[0])
    _, eb = registry.resolve(b[1], b[0])
    qa, qb = ea.quantity, eb.quantity

    blocked: list[dict] = []
    valid: list[str] = []
    same_dim = qa.dimension == qb.dimension
    same_unit = qa.unit == qb.unit

    if same_dim and same_unit and qa.aggregation is qb.aggregation is Aggregation.ADDITIVE:
        valid.append("sum")
    else:
        blocked.append({"op": "sum", "reason": "different_dimensions" if not same_dim
                        else "different_units" if not same_unit else "not_both_additive"})
    if same_dim and same_unit:
        valid.append("difference")
    else:
        blocked.append({"op": "difference",
                        "reason": "different_dimensions" if not same_dim else "different_units"})
    valid.append("ratio")
    if qa.dimension in DIMENSIONLESS or qb.dimension in DIMENSIONLESS:
        valid.append("product")
    else:
        blocked.append({"op": "product", "reason": "neither_side_dimensionless"})

    # Aggregating fine to coarse is arithmetic over observed values.
    # Disaggregating coarse to fine is interpolation. Resolution is therefore
    # always the coarsest common cadence, and upsampling is refused, not offered.
    transforms: list[dict] = []
    ranks = [cadence_rank(e.native_cadence) for e in (ea, eb)]
    if None in ranks:
        resolution = None
    else:
        resolution = ea.native_cadence if ranks[0] >= ranks[1] else eb.native_cadence
        for e, r in ((ea, ranks[0]), (eb, ranks[1])):
            if e.native_cadence != resolution:
                transforms.append({"field": e.kind, "op": f"aggregate_{e.quantity.aggregation.value}",
                                   "from": e.native_cadence, "to": resolution})

    verdict = ("incommensurable" if not valid
               else "directly_relatable" if not transforms
               else "relatable_with_transform")
    return Relatability(verdict, resolution, tuple(transforms), tuple(valid), tuple(blocked),
                        note="No structural relation is declared between these fields. "
                             "Any relationship is the consumer's hypothesis.")
