"""Potency — the harness's interpretation of what the data layer declared.

The seam, stated once: the data layer declares three *structural* facts about
every record — which phenomenon it is a record of (`records_of`), its relation to
that phenomenon (`role`), and what earlier records it echoes (`lineage.reports_on`).
All three are readable from the document itself. None of them is a number, and
none requires a model.

Turning those into weights is interpretation, and interpretation lives here. A
stock screener consuming the same layer would weight them differently, or ignore
them entirely, and nothing in the layer would have to change. That is the same
line as lineage-versus-root-sets: general primitive on one side, one consumer's
reading on the other.

**None of this is an accuracy score.** A post asserting something false is a
fully potent record of retail discourse; the discourse happened and propagated,
and that is the fact. It is only weak with respect to a *different* phenomenon —
the earnings it misdescribes — and the arithmetic below never confuses the two.
"""
from __future__ import annotations

from dataclasses import dataclass

from contract import Emission, Phenomenon, Record, SourceRegistry, TruthRole


@dataclass(frozen=True)
class RoleWeight:
    potency: float | None    # how much of the phenomenon a record carries; None = inherit
    support_cap: float       # most one record of this role may contribute as a leg


#: The harness's weighting. Tunable, versioned into the run manifest, and subject
#: to the meta-layer's own track record (§16) like every other threshold here.
ROLE_WEIGHTS: dict[TruthRole, RoleWeight] = {
    TruthRole.CONSTITUTIVE: RoleWeight(1.00, 1.00),
    TruthRole.ATTESTED:     RoleWeight(0.90, 0.90),
    TruthRole.OBSERVED:     RoleWeight(0.85, 0.85),
    TruthRole.REPORTED:     RoleWeight(0.45, 0.35),
    TruthRole.ECHOED:       RoleWeight(0.20, 0.10),
    TruthRole.DERIVED:      RoleWeight(None, 0.50),
}

#: A record's relation to a phenomenon it merely reports on. A wire story about a
#: filing is constitutive of editorial publication and an echo of the disclosure.
CROSS_PHENOMENON_ROLE = TruthRole.ECHOED

POTENCY_VERSION = "potency_v1"


def potency_of(role: TruthRole, input_potencies: tuple[float, ...] = ()) -> float:
    """Derived records take the MINIMUM over their inputs: a derivation is bounded
    by its weakest source and is never averaged up by a strong one."""
    w = ROLE_WEIGHTS[role]
    if w.potency is not None:
        return w.potency
    if not input_potencies:
        return ROLE_WEIGHTS[TruthRole.ECHOED].potency  # type: ignore[return-value]
    return min(input_potencies)


def potency_for(
    emission: Emission,
    phenomenon: Phenomenon,
    reports_on_phenomena: frozenset[Phenomenon] = frozenset(),
    input_potencies: tuple[float, ...] = (),
) -> float:
    """How much a record carries *about the phenomenon being asked about*.

    Three outcomes, and the third must never collapse into the others: strong
    evidence, echoed evidence, or **silent** — no evidence at all. A pageview
    count is not weak evidence about a bank's loan book; it says nothing on it.
    """
    if emission.records_of == phenomenon:
        return potency_of(emission.role, input_potencies)
    if phenomenon in reports_on_phenomena:
        return potency_of(CROSS_PHENOMENON_ROLE, input_potencies)
    return 0.0


class PotencyReader:
    """Resolves potency for records, using only what the layer declared."""

    def __init__(self, registry: SourceRegistry, records: tuple[Record, ...] = ()):
        self.registry = registry
        self._by_doc: dict[str, Record] = {}
        for r in records:
            for d in r.lineage.documents:
                self._by_doc.setdefault(d, r)

    def phenomenon_of(self, record: Record) -> Phenomenon | None:
        em = self.registry.emission_for(record)
        return em.records_of if em else None

    def reports_on_phenomena(self, record: Record) -> frozenset[Phenomenon]:
        """Which phenomena this record speaks about second-hand, resolved through
        the documents it names — never guessed from its text."""
        out = set()
        for doc in record.lineage.reports_on:
            origin = self._by_doc.get(doc)
            if origin is None:
                continue
            ph = self.phenomenon_of(origin)
            if ph is not None:
                out.add(ph)
        return frozenset(out)

    def potency(self, record: Record, phenomenon: Phenomenon) -> float:
        em = self.registry.emission_for(record)
        if em is None:
            return 0.0
        return potency_for(em, phenomenon, self.reports_on_phenomena(record))

    def origin_documents(self, record: Record) -> frozenset[str]:
        """What this record ultimately stands on: its own documents if it is
        originating, the documents it echoes if it is not. Two records with
        different ids and the same origin are one leg."""
        if record.lineage.reports_on:
            return frozenset(record.lineage.reports_on)
        return frozenset(record.lineage.documents)
