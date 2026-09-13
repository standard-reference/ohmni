"""The port. Both sides depend on this; neither depends on the other."""
from __future__ import annotations

from datetime import datetime
from typing import Iterator, Protocol, runtime_checkable

from .capability import CapabilitySet
from .declaration import SourceDeclaration
from .record import Record


class HistoricalQueryRefused(Exception):
    """Raised when a historical as_of query is made against a stream that has no
    honest historical mode (snapshot + deletions unrecoverable). Refusing with a
    reason beats serving contaminated values."""


@runtime_checkable
class DataLayer(Protocol):
    layer_id: str
    layer_version: str

    def sources(self) -> list[SourceDeclaration]: ...

    def capabilities(self) -> CapabilitySet: ...

    def stream(
        self, start: datetime, end: datetime, subjects: list[str]
    ) -> Iterator[Record]:
        """Ordered by knowable_at, non-decreasing."""

    def query(
        self,
        subject: str,
        kind: str,
        window: tuple[datetime, datetime],
        as_of: datetime,
    ) -> list[Record]:
        """`as_of` is mandatory: the API structurally cannot serve future values."""


CONTRACT_VERSION = "0.1.0"
