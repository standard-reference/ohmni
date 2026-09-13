"""Replication across epochs — what promotes a form instead of fitting one.

A form derived in one window and applied elsewhere is a fit to that window. A
form independently derived in several disjoint epochs, under different regimes,
is something else: the conditions recurred, and the recipe reproduced them.

So derivation and scoring are separated by construction:

- **Derivation epochs** are where cores are proposed. A core is a candidate only
  when the SAME invariant identity is derived in at least `min_replications` of
  them. One appearance is an anecdote.
- **Holdout epochs** are never seen during derivation and are the only place a
  score may be quoted from. Everything on a derivation epoch is admission.

Every parameter is re-resolved against whichever window the form is applied in,
so a threshold measured in 2019 never travels into 2023. The core travels; the
numbers are always local.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .coverage import BasisRealization, Commensurability, compare
from .epochs import Epoch, EpochSet
from .strategy import TradeType, TradeTypeCore


@dataclass
class Derivation:
    """One core, proposed from one (epoch, entity, window)."""

    epoch_id: str
    entity: str
    window_start: object
    core: TradeTypeCore
    trade_type: TradeType
    support: float
    specificity: float


@dataclass
class Replication:
    core: TradeTypeCore
    derivations: list[Derivation] = field(default_factory=list)
    #: Set when a core cleared the epoch count but its inputs were not
    #: expressible everywhere. Distinct from "did not replicate": one means the
    #: form failed to recur, the other means it was never testable.
    refused_reason: str = ""

    @property
    def epochs(self) -> set[str]:
        return {d.epoch_id for d in self.derivations}

    @property
    def entities(self) -> set[str]:
        return {d.entity for d in self.derivations}

    def replicated(self, min_replications: int) -> bool:
        """Distinct EPOCHS, not distinct firings.

        Ten firings inside one epoch are one observation with wide coverage —
        the windows overlap and the regime is shared. Two firings in two epochs
        are two observations. Counting firings instead of epochs is how a single
        period's quirk gets promoted as a law.
        """
        return len(self.epochs) >= min_replications

    def summary(self, min_replications: int) -> str:
        return (f"{self.core.id}: {len(self.derivations)} derivations across "
                f"{len(self.epochs)} epochs {sorted(self.epochs)}, "
                f"{len(self.entities)} entities — "
                f"{'REPLICATED' if self.replicated(min_replications) else 'single-epoch, not replicated'}")


def group_by_core(derivations: list[Derivation]) -> list[Replication]:
    out: dict[tuple, Replication] = {}
    for d in derivations:
        rep = out.setdefault(d.core.identity(), Replication(core=d.core))
        rep.derivations.append(d)
    return sorted(out.values(), key=lambda r: (-len(r.epochs), r.core.id))


class IncommensurableEpochs(Exception):
    """Raised when a replication claim is attempted over epochs that were not
    observed on the same basis. Not a warning: 'the form recurred' and 'the form
    recurred in the epochs where its inputs happened to exist' are different
    claims, and only one of them is evidence."""


def replicated_cores(derivations: list[Derivation], epochs: EpochSet,
                     realizations: list[BasisRealization] | None = None,
                     min_coverage: float | None = None) -> list[Replication]:
    """Only cores derived in at least `min_replications` distinct DERIVATION
    epochs, over a basis those epochs actually shared.

    Holdout derivations are excluded even if they happen — a core that only
    appears in the holdout was not proposed, it was discovered while scoring.

    When `realizations` are supplied the basis is checked first, and a core whose
    inputs were not expressible in every epoch is refused rather than credited.
    A source outage in one epoch would otherwise turn into a silent claim that the
    form "did not replicate there", when in truth it was never testable there.
    """
    derivation_ids = {e.id for e in epochs.derivation()}
    eligible = [d for d in derivations if d.epoch_id in derivation_ids]
    candidates = [r for r in group_by_core(eligible)
                  if r.replicated(epochs.min_replications)]
    if realizations is None:
        return candidates

    if min_coverage is None:
        raise ValueError("min_coverage is required when checking basis "
                         "commensurability; a default would hide a partial outage")
    verdict = compare([r for r in realizations if r.epoch_id in derivation_ids],
                      min_coverage)
    if verdict.verdict == "incommensurable":
        raise IncommensurableEpochs(
            f"{verdict.reason}; fields present in only some epochs: "
            f"{ {k: sorted(v) for k, v in verdict.only_in.items()} }")

    kept = []
    for rep in candidates:
        needed = {rep.core.trigger_phenomenon, *rep.core.required_invariant_phenomena}
        missing = needed - set(verdict.shared_phenomena or verdict.shared)
        if missing:
            rep.refused_reason = (
                f"inputs {sorted(missing)} were not expressible in every epoch, so "
                "this core was never testable in all of them")
            continue
        kept.append(rep)
    return kept


@dataclass
class ScoreCard:
    """Kept separate from the ledger on purpose: a number from a derivation epoch
    and a number from a holdout epoch are different kinds of claim, and printing
    them in one column is how the distinction gets lost."""

    admission: dict[str, dict] = field(default_factory=dict)   # derivation epochs
    score: dict[str, dict] = field(default_factory=dict)       # holdout epochs only

    def note(self) -> str:
        return ("admission figures come from epochs the form was derived in and "
                "carry no evidential weight; only the holdout column is a score")
