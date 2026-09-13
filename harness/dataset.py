"""Dataset freeze — making "the same data" provable rather than assumed.

A run that cannot name exactly which bytes it saw cannot be compared with
another run. This content-addresses the whole ingested corpus, so two runs in two
sessions either agree on the dataset or the mismatch is visible immediately.

This is what makes stateless re-runs meaningful: the harness changes between
runs, the data does not, and the hash proves it.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DatasetFreeze:
    id: str                       # content hash over every cached artifact
    file_count: int
    total_bytes: int
    roots: tuple[str, ...]

    def short(self) -> str:
        return self.id[:16]

    def to_json(self) -> str:
        return json.dumps({"id": self.id, "file_count": self.file_count,
                           "total_bytes": self.total_bytes,
                           "roots": list(self.roots)}, sort_keys=True)


def freeze(*roots: Path) -> DatasetFreeze:
    """Hash every cached artifact by path and content.

    Ordered by path so the result is independent of filesystem enumeration
    order — otherwise two runs over identical data would produce different ids
    and the comparison this exists to enable would be impossible.
    """
    digest = hashlib.sha256()
    count = total = 0
    for root in sorted(roots, key=str):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            body = path.read_bytes()
            digest.update(rel.encode())
            digest.update(hashlib.sha256(body).digest())
            count += 1
            total += len(body)
    return DatasetFreeze(id="sha256:" + digest.hexdigest(), file_count=count,
                         total_bytes=total,
                         roots=tuple(str(r) for r in sorted(roots, key=str)))


def verify(expected: str, *roots: Path) -> tuple[bool, DatasetFreeze]:
    got = freeze(*roots)
    return got.id == expected, got
