"""Independence — three failure modes, three mechanisms.

Root sets catch shared **lineage**. Declared coupling catches shared **economic
driver**. Echo collapse catches shared **origin**: twelve articles about one
filing have disjoint lineage documents and score as twelve independent legs under
root sets alone, which is the failure that manufactures false confidence quietly.

Every input is something the data layer *declared*. Nothing here is inferred from
text, and nothing here is a judgement about whether a record is correct.
"""
from __future__ import annotations

from dataclasses import dataclass

from contract import Record, SourceRegistry

from .potency import PotencyReader


@dataclass(frozen=True)
class IndependenceResult:
    score: float
    lineage_overlap: float
    origin_overlap: float
    declared_coupling: float
    binding: str          # which mechanism actually bound the score

    def __float__(self) -> float:
        return self.score


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def independence(
    left: tuple[Record, ...],
    right: tuple[Record, ...],
    registry: SourceRegistry,
    reader: PotencyReader | None = None,
) -> IndependenceResult:
    """independence = (1 − shared evidence) × (1 − declared coupling).

    Degrades gracefully: partial overlap becomes a partial discount rather than a
    veto, which is what lets two half-independent corroborations be worth roughly
    one instead of two-that-pass.
    """
    reader = reader or PotencyReader(registry, left + right)

    docs_l = frozenset().union(*(r.lineage.documents for r in left)) if left else frozenset()
    docs_r = frozenset().union(*(r.lineage.documents for r in right)) if right else frozenset()
    lineage_overlap = _jaccard(docs_l, docs_r)

    # What each side ultimately stands on. An echo stands on what it echoes, so
    # twelve articles about one filing share one origin.
    org_l = frozenset().union(*(reader.origin_documents(r) for r in left)) if left else frozenset()
    org_r = frozenset().union(*(reader.origin_documents(r) for r in right)) if right else frozenset()
    origin_overlap = _jaccard(org_l, org_r)

    # A known structural fact, not an estimate.
    subj_l = {r.subject for r in left}
    subj_r = {r.subject for r in right}
    coupling = 0.0
    for side_a, side_b in ((left, subj_r), (right, subj_l)):
        for r in side_a:
            decl = registry.source(r.source_id)
            if decl is None:
                continue
            for s in side_b:
                # The instrument being asked about is the record's OWN identity:
                # a source carrying contracts with different exposures declares
                # coupling per instrument, and looking it up without naming which
                # instrument silently finds nothing.
                coupling = max(coupling, decl.coupling_to(s, instrument=r.subject))

    shared = max(lineage_overlap, origin_overlap)
    score = (1.0 - shared) * (1.0 - coupling)
    binding = (
        "lineage" if lineage_overlap >= max(origin_overlap, coupling)
        else "origin" if origin_overlap >= coupling
        else "coupling"
    )
    if shared == 0.0 and coupling == 0.0:
        binding = "none"
    return IndependenceResult(round(score, 6), lineage_overlap, origin_overlap,
                              coupling, binding)


def collapse_to_legs(
    records: tuple[Record, ...], registry: SourceRegistry
) -> dict[frozenset[str], tuple[Record, ...]]:
    """Group records by what they ultimately stand on.

    One event observed by six processes is genuinely corroborated; one event
    observed forty-three times by one process is one observation with wide
    coverage. This is where that distinction gets made once, rather than being
    rediscovered by every consumer.
    """
    reader = PotencyReader(registry, records)
    legs: dict[frozenset[str], list[Record]] = {}
    for r in records:
        legs.setdefault(reader.origin_documents(r), []).append(r)
    return {k: tuple(v) for k, v in legs.items()}
