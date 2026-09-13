"""Basis realization — what a basis actually turned out to be, per epoch.

A declared basis is a stance. What a window can actually express is a different
thing, and the gap between them is where a cross-epoch comparison quietly breaks:
if one epoch could express `editorial_publication` and another could not, the two
epochs were not observed over the same basis, and any claim that a form
"replicated" across them is comparing two different things.

Two sparks are comparable when they share a basis. That rule was enforced within
a run and not across epochs, which is how a source outage turned into a
replication claim nobody could have checked. This module closes it.

`no_shared_basis` and `compared_and_differed` must never collapse into one
answer — a consumer does something different in each case.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BasisRealization:
    """Which declared fields a window could actually express, and how well."""

    basis_id: str
    epoch_id: str
    representable: frozenset[str]
    not_representable: dict[str, str]       # field -> reason
    coverage: dict[str, float] = field(default_factory=dict)   # field -> frames covered

    @classmethod
    def of(cls, observation, basis, epoch_id: str) -> "BasisRealization":
        covered = {}
        for name in observation.separations:
            live = sum(1 for f in observation.frames
                       if f.get(name) and f[name].estimate is not None)
            covered[name] = round(live / max(1, len(observation.frames)), 4)
        return cls(basis_id=basis.id, epoch_id=epoch_id,
                   representable=frozenset(observation.separations),
                   not_representable=dict(observation.not_representable),
                   coverage=covered)

    def describe(self) -> str:
        return (f"{self.epoch_id}: {sorted(self.representable)}"
                + (f" | unavailable {self.not_representable}"
                   if self.not_representable else ""))


@dataclass(frozen=True)
class Commensurability:
    verdict: str                 # "same_basis" | "partial" | "incommensurable"
    shared: frozenset[str]
    only_in: dict[str, frozenset[str]]
    reason: str
    #: The same answer expressed in phenomena rather than field names, because a
    #: mechanism core names phenomena and a basis names fields.
    shared_phenomena: frozenset[str] = frozenset()

    @property
    def comparable(self) -> bool:
        return self.verdict == "same_basis"


def compare(realizations: list[BasisRealization], min_coverage: float,
            field_phenomena: dict[str, str] | None = None) -> Commensurability:
    """Are these epochs observed over the same basis?

    `min_coverage` is required. A field present in every epoch but only populated
    in a fifth of one epoch's frames is not really shared, and a default here
    would hide exactly the partial outage this exists to catch.
    """
    if len({r.basis_id for r in realizations}) > 1:
        return Commensurability("incommensurable", frozenset(), {},
                                "epochs declare different bases")
    to_phen = field_phenomena or {}
    usable = [frozenset(f for f in r.representable
                        if r.coverage.get(f, 0.0) >= min_coverage)
              for r in realizations]
    shared = frozenset.intersection(*usable) if usable else frozenset()
    union = frozenset.union(*usable) if usable else frozenset()
    only_in = {r.epoch_id: u - shared for r, u in zip(realizations, usable) if u - shared}

    phen = frozenset(to_phen.get(f, f) for f in shared)
    if not shared:
        return Commensurability("incommensurable", shared, only_in,
                                "no field is expressible in every epoch", phen)
    if only_in:
        return Commensurability(
            "partial", shared, only_in,
            "some fields are expressible in only some epochs; a form using them "
            "cannot be said to have replicated across all of them", phen)
    return Commensurability("same_basis", shared, {}, "every declared field is "
                            "expressible in every epoch", phen)


class UnbackfillableSource(Exception):
    """A basis that draws on a source whose history cannot be fetched at scale.

    Raised at declaration time, before a single request is made. The alternative
    is discovering it partway through a multi-epoch pull, by which point the
    epochs already have different bases and the only honest options are to
    redesign the basis or throw the run away.
    """


def check_backfillable(basis, registry) -> None:
    """Every source a multi-epoch basis depends on must support bulk history.

    `metered` is a budget question and is allowed through with the cost visible;
    `rate_limited` and `record_only` are hard stops for backfill, and a basis
    resting on one of them cannot produce the same fields in every epoch.
    """
    from contract import HistoricalAccess

    blocked = []
    for bf in basis.fields:
        decl = registry.source(bf.source_id)
        if decl is None:
            continue
        access = getattr(decl, "historical_access", HistoricalAccess.BULK)
        if access in (HistoricalAccess.RATE_LIMITED, HistoricalAccess.RECORD_ONLY):
            hint = (f" — a bulk archive exists at {decl.bulk_endpoint}"
                    if decl.bulk_endpoint else " — no archive path exists")
            blocked.append(f"{bf.name} via {bf.source_id} ({access.value}){hint}")
    if blocked:
        raise UnbackfillableSource(
            "a multi-epoch basis cannot rest on sources whose history cannot be "
            "fetched at scale; these would be present in some epochs and absent "
            "in others: " + "; ".join(blocked))
