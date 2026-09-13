"""The neutral fact shape. Frozen core contract — both products depend on this,
neither depends on the other.

Deliberately absent: root_set, basis, frames, EffectClaim, spark. The data layer
emits lineage; the harness derives root sets from it on its own side of the seam.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Status(str, Enum):
    """Everyone else returns a number or null. `null` collapses at least five
    genuinely different states and a consumer cannot recover the distinction."""

    REPORTED = "reported"
    DERIVED = "derived"
    NOT_REPRESENTABLE = "not_representable"   # cannot be honestly computed (Q4 standalone)
    NOT_DISCLOSED = "not_disclosed"           # applies, entity didn't report it
    NOT_APPLICABLE = "not_applicable"         # doesn't apply to this entity type
    NOT_COVERED = "not_covered"               # outside coverage (pre-XBRL, custom taxonomy)

    @property
    def is_gap(self) -> bool:
        return self in _GAP_STATUSES

    @property
    def has_value(self) -> bool:
        return self in (Status.REPORTED, Status.DERIVED)


_GAP_STATUSES = frozenset(
    {
        Status.NOT_REPRESENTABLE,
        Status.NOT_DISCLOSED,
        Status.NOT_APPLICABLE,
        Status.NOT_COVERED,
    }
)


@dataclass(frozen=True)
class Lineage:
    """The general primitive. Three genuinely different relations, kept apart
    because collapsing them is how one claim reads as fifty:

    - `documents`   — the originating-document axis (the document join spine).
    - `derived_from`— input *records* whose values produced this one.
    - `reports_on`  — documents this record reports on without deriving its value
                      from them. The general form of "this repost's root is that
                      post", and the anchor that lets forty-three articles about
                      one 8-K collapse to one observation with wide coverage.

    Root sets are NOT here — they are the harness's interpretation of this.
    """

    documents: frozenset[str] = frozenset()
    derived_from: tuple[str, ...] = ()
    reports_on: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "documents", frozenset(self.documents))
        object.__setattr__(self, "derived_from", tuple(self.derived_from))
        object.__setattr__(self, "reports_on", frozenset(self.reports_on))


@dataclass(frozen=True)
class Revision:
    """Restatements are a chain, not a pair. `index` positions this link in it."""

    index: int
    chain_length: int
    superseded_at: datetime | None = None

    @property
    def is_superseded(self) -> bool:
        return self.superseded_at is not None


@dataclass(frozen=True)
class Record:
    id: str
    kind: str                       # neutral: "fundamental", "price", "news", "quote", ...
    subject: str                    # entity_id or instrument_id
    event_time: datetime            # when it happened
    knowable_at: datetime           # when it became knowable — REQUIRED, never null
    value: dict[str, Any]           # shape by kind; empty for a typed gap
    status: Status
    source_id: str
    lineage: Lineage = field(default_factory=Lineage)
    revision: Revision | None = None

    def __post_init__(self) -> None:
        if self.knowable_at is None:
            raise ValueError(
                f"record {self.id}: knowable_at is required and has no default. "
                "Without it there is nothing to gate on."
            )
        if not isinstance(self.status, Status):
            raise TypeError(f"record {self.id}: status must be a typed Status, not {self.status!r}")
