"""Ingestion epochs — disjoint periods, each calibrated against itself.

A form derived from one window and applied elsewhere is a fit to that window
wearing a generic costume, however carefully the entity ids were kept out of it.
The parameters carry the window: a separation threshold, a volatility scale and a
base rate are all properties of the period they were measured in.

So the harness ingests **several disjoint epochs** and calibrates each against
its own null. Nothing crosses an epoch boundary except a form's invariant core.
That is what makes the same strategy the same strategy in 2019 and in 2023: not
the same numbers, but the same recipe for arriving at them.

Epochs are declared before anything runs, and some are **held out** — the
derivation never sees them, and they are the only thing a score may be quoted on.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

UTC = timezone.utc


@dataclass(frozen=True)
class Epoch:
    """One ingestion window, with its own regime and its own calibration."""

    id: str
    start: datetime
    end: datetime
    regime_note: str
    holdout: bool = False

    @property
    def days(self) -> int:
        return (self.end - self.start).days


@dataclass(frozen=True)
class EpochSet:
    epochs: tuple[Epoch, ...]
    #: How many distinct epochs must independently produce a form before it is
    #: treated as replicated rather than fitted. Required, no default — it is the
    #: single number that decides how much recurrence counts as evidence.
    min_replications: int
    #: Fraction of an epoch's frames a field must be populated in before it
    #: counts as shared with another epoch. Required, no default: a field present
    #: everywhere but populated in a fifth of one epoch's frames is not really
    #: shared, and a default would hide exactly the partial outage this exists to
    #: catch. Declared here so it is recorded with the protocol rather than
    #: living at a call site nobody reading a report can find.
    min_coverage: float

    def __post_init__(self) -> None:
        spans = sorted(((e.start, e.end, e.id) for e in self.epochs))
        for (s1, e1, i1), (s2, _, i2) in zip(spans, spans[1:]):
            if s2 < e1:
                raise ValueError(f"epochs {i1} and {i2} overlap; an epoch that shares "
                                 "data with another is not an independent replication")
        if self.min_replications > len(self.derivation()):
            raise ValueError("more replications required than there are derivation epochs")

    def derivation(self) -> tuple[Epoch, ...]:
        return tuple(e for e in self.epochs if not e.holdout)

    def holdout(self) -> tuple[Epoch, ...]:
        return tuple(e for e in self.epochs if e.holdout)

    def declared(self) -> dict:
        """The protocol, as recorded alongside a run. Everything a reader needs
        to know what bar the result was measured against."""
        return {"epochs": [e.id for e in self.epochs],
                "holdout": [e.id for e in self.holdout()],
                "min_replications": self.min_replications,
                "min_coverage": self.min_coverage}

    def by_id(self, eid: str) -> Epoch:
        return next(e for e in self.epochs if e.id == eid)


def half_year(year: int, half: int, note: str, holdout: bool = False) -> Epoch:
    start = datetime(year, 1 if half == 1 else 7, 2, tzinfo=UTC)
    end = datetime(year, 6, 30, tzinfo=UTC) if half == 1 else datetime(year, 12, 20, tzinfo=UTC)
    return Epoch(f"{year}H{half}", start, end, note, holdout)


#: Declared up front, spanning genuinely different regimes. The holdout is the
#: most recent one: a form is derived on the past and scored on a period the
#: derivation never touched, which is the only arrangement in which a score means
#: anything.
DEFAULT_EPOCHS = EpochSet(
    epochs=(
        half_year(2019, 1, "late-cycle expansion, pre-COVID"),
        half_year(2021, 1, "post-COVID liquidity, retail participation peak"),
        half_year(2023, 1, "rate-shock recovery, start of the AI attention surge"),
        half_year(2024, 1, "AI continuation", holdout=True),
    ),
    min_replications=2,
    min_coverage=0.75,
)
