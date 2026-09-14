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


# ── portability: a freeze id proves identity, a manifest rebuilds it ────────
#
# The id alone is only useful inside one container's lifetime. It says "this is
# the same corpus" and gives no way to CHECK that a refetched corpus matches, or
# to see which files drifted if it does not. A manifest is what makes a dataset
# outlive the machine that first assembled it — which is the whole premise of
# running each evaluation in a fresh session over the same data.

@dataclass(frozen=True)
class ManifestDiff:
    ok: bool
    missing: tuple[str, ...]     # in the manifest, absent from disk
    changed: tuple[str, ...]     # present but different bytes
    extra: tuple[str, ...]       # on disk, not in the manifest

    def describe(self) -> str:
        if self.ok:
            return "rebuilt corpus is byte-identical to the manifest"
        parts = []
        for label, items in (("missing", self.missing), ("changed", self.changed),
                             ("extra", self.extra)):
            if items:
                shown = ", ".join(items[:4]) + (" ..." if len(items) > 4 else "")
                parts.append(f"{len(items)} {label} ({shown})")
        return "; ".join(parts)


def manifest(*roots: Path) -> dict:
    """Per-file hashes, so a refetched corpus can be proved identical.

    Stored under `<root-name>/<relative path>` rather than an absolute path, so a
    manifest written in one container verifies in another.
    """
    entries: dict[str, str] = {}
    for root in sorted(roots, key=str):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                key = f"{root.name}/{path.relative_to(root).as_posix()}"
                entries[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"freeze": freeze(*roots).id, "files": entries}


def write_manifest(target: Path, *roots: Path) -> DatasetFreeze:
    import gzip

    body = json.dumps(manifest(*roots), sort_keys=True, separators=(",", ":"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(gzip.compress(body.encode()))
    return freeze(*roots)


def verify_against_manifest(target: Path, *roots: Path) -> ManifestDiff:
    """Compare a rebuilt corpus to a committed manifest, naming what differs.

    A boolean would say the rebuild failed. This says which files — which is the
    difference between "refetch everything again" and "three FINRA days are
    missing because those markets were closed".
    """
    import gzip

    stored = json.loads(gzip.decompress(target.read_bytes()))["files"]
    current = manifest(*roots)["files"]
    missing = tuple(sorted(set(stored) - set(current)))
    extra = tuple(sorted(set(current) - set(stored)))
    changed = tuple(sorted(k for k in set(stored) & set(current)
                           if stored[k] != current[k]))
    return ManifestDiff(not (missing or changed or extra), missing, changed, extra)
