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


def block_bootstrap(records: tuple[Record, ...], registry: SourceRegistry,
                    seed: int, block: int) -> tuple[Record, ...]:
    """Resample blocks of consecutive observations rather than single values.

    An iid shuffle destroys volatility clustering and fat-tailed runs along with
    the arrangement, which makes a null that real markets beat too easily: any
    detector keyed on a sustained move looks skilful against noise that cannot
    sustain anything. A block bootstrap keeps the local structure — a violent
    week stays a violent week — and destroys only *where* those weeks sit
    relative to each other and to the other streams.

    That is the property under test. A mechanism claims attention moved at a
    particular time relative to price and coverage; the block null preserves
    everything except that relationship.

    `block` is required and has no default: too short and the clustering is gone
    and the null is the easy one again, too long and the series is nearly its own
    permutation and the null is unbeatable. It is the parameter that decides what
    the control actually controls for, so it is declared.
    """
    if block < 1:
        raise ValueError("block length must be at least one observation")

    groups: dict[tuple, list[int]] = {}
    for i, r in enumerate(records):
        groups.setdefault((r.subject, r.source_id, r.kind), []).append(i)

    out = list(records)
    for key, idxs in sorted(groups.items()):
        if len(idxs) < block * 2:
            continue
        em = registry.emission_for(records[idxs[0]])
        if em is None or em.value_field is None:
            continue
        field = em.value_field
        # Ordered by event_time so a "block" is genuinely consecutive in the
        # series rather than in arrival order.
        ordered = sorted(idxs, key=lambda i: (records[i].event_time, records[i].id))
        values = [records[i].value.get(field) for i in ordered]

        rng = random.Random(_seed(key, seed, block, "block"))
        drawn: list = []
        while len(drawn) < len(values):
            start = rng.randrange(len(values))
            # Wrap rather than truncate, so every position is equally likely to
            # start a block and the tail is not systematically under-sampled.
            drawn.extend(values[(start + k) % len(values)] for k in range(block))
        for i, v in zip(ordered, drawn[:len(values)]):
            out[i] = replace(out[i], value={**out[i].value, field: v})
    return tuple(out)
