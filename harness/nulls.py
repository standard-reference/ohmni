"""Null controls over an arbitrary record stream.

The fixture layer could shuffle itself because it authored its own values. A real
stream cannot, so the null has to be a pure function of the records: for each
(subject, source, kind) group, keep every timestamp exactly as it was and permute
the *values* across them.

That preserves each field's marginal distribution precisely — same levels, same
dispersion, same availability lags — and destroys the temporal arrangement, which
is the thing a mechanism actually claims. Anything the pipeline finds here it
found in noise.

The honest limit, repeated because it is easy to forget: this does NOT destroy
within-field structure in the sense of magnitudes. A big move still exists, just
somewhere else. What it removes is when-relative-to-what, which is why the null
is a control on *arrangement* and not on *amplitude*.
"""
from __future__ import annotations

import random
import zlib
from dataclasses import replace

from contract import Record, SourceRegistry


def _seed(*parts: object) -> int:
    return zlib.crc32("|".join(repr(p) for p in parts).encode("utf-8"))


def shuffle_values(records: tuple[Record, ...], registry: SourceRegistry,
                   seed: int) -> tuple[Record, ...]:
    """Permute values within each (subject, source, kind) group.

    Timestamps, ids, lineage and status all stay put — only the measured value
    moves. A null that also disturbed availability would be testing the guard
    rather than the discovery.
    """
    groups: dict[tuple, list[int]] = {}
    for i, r in enumerate(records):
        groups.setdefault((r.subject, r.source_id, r.kind), []).append(i)

    out = list(records)
    for key, idxs in sorted(groups.items()):
        if len(idxs) < 3:
            continue
        em = registry.emission_for(records[idxs[0]])
        if em is None or em.value_field is None:
            continue
        field = em.value_field
        values = [records[i].value.get(field) for i in idxs]
        rng = random.Random(_seed(key, seed))
        rng.shuffle(values)
        for i, v in zip(idxs, values):
            out[i] = replace(out[i], value={**out[i].value, field: v})
    return tuple(out)
