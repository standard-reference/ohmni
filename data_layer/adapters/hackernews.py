"""Hacker News submissions — technical-community discourse.

Free, full history, no key, and genuinely a different measurement process from
both editorial publication and information-seeking: a submission is a person
deciding something is worth putting in front of a community.

Mapped to RETAIL_DISCOURSE and CONSTITUTIVE, which is the honest reading — the
post IS the discourse. It is deliberately NOT mapped to editorial publication:
a community submission and a wire story are different phenomena, and collapsing
them to reuse a mechanism template would be choosing the measurement to fit the
hypothesis.

Why it is here at all: GDELT's public API rate-limits to the point of being
unusable for a multi-epoch historical pull, so `editorial_publication` is
available in one epoch out of four. A basis that differs between epochs cannot
support a replication claim — two sparks are comparable when they share a basis —
so the multi-epoch basis uses phenomena available in *every* epoch, and this is
one of them.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from contract import (Aggregation, Dimension, Emission, Lineage, Phenomenon,
                      Quantity, Record, Retrieval, SourceDeclaration, Status,
                      Survivorship, TemporalType, TruthRole)

from ..cache import fetch
from ..entities import Entity

SOURCE_ID = "hn.stories"
#: Quoted phrase, title only. Unquoted, "AMD" matches four thousand stories a
#: month on prefix and typo similarity — a series measuring nothing about the
#: entity. Quoted it matches nineteen. Entity resolution by text query is the
#: weakest join in the whole source set and this is the difference between a
#: signal and a noise generator.
URL = ("https://hn.algolia.com/api/v1/search_by_date?query=%22{q}%22&tags=story"
       "&restrictSearchableAttributes=title&advancedSyntax=true"
       "&numericFilters=created_at_i%3E{start}%2Ccreated_at_i%3C{end}"
       "&hitsPerPage=1000")
PUBLICATION_LAG = timedelta(hours=1)

#: Algolia serves at most 1000 results per query whatever `nbPages` claims, and
#: it truncates by RECENCY — which would manufacture a spike at the end of every
#: window. Monthly chunks keep each request well under the cap, so the series is
#: complete rather than quietly clipped.
CHUNK_DAYS = 31


def declaration() -> SourceDeclaration:
    return SourceDeclaration(
        source_id=SOURCE_ID,
        measurement_process=("Technical-community discourse; story submissions to "
                             "Hacker News mentioning the entity, by submission time"),
        retrieval=Retrieval.AS_OF,
        # Submissions can be deleted by moderators, and a historical search will
        # not return them. Declared rather than assumed complete.
        record_survivorship=Survivorship.DELETIONS_UNRECOVERABLE,
        backfilled=False,
        emits=(Emission(
            kind="hn_stories", value_field="stories", native_cadence="P1D",
            publication_lag=PUBLICATION_LAG,
            records_of=Phenomenon.RETAIL_DISCOURSE, role=TruthRole.CONSTITUTIVE,
            quantity=Quantity(Dimension.COUNT, "stories", Aggregation.ADDITIVE,
                              TemporalType.DURATION)),),
    )


def fetch_raw(entity: Entity, start: datetime, end: datetime) -> list[dict]:
    import urllib.parse

    chunks, at = [], start
    while at < end:
        stop = min(at + timedelta(days=CHUNK_DAYS), end)
        body = fetch(URL.format(q=urllib.parse.quote(entity.hn_query),
                                start=int(at.timestamp()),
                                end=int(stop.timestamp()))).json()
        # Truncation is recorded, never silent: a consumer cannot detect a gap it
        # is not told about, and a clipped count is a smaller number, not a
        # smaller world.
        body["_truncated"] = body.get("nbHits", 0) > len(body.get("hits", []))
        chunks.append(body)
        at = stop
    return chunks


def normalize(pages: list[dict], entity: Entity) -> list[Record]:
    """Daily submission counts. A day with no submission produces NO record —
    the basis turns it into a rate-per-window of zero at aggregation time, which
    is arithmetic over observed absence rather than a fabricated observation."""
    if any(c.get("_truncated") for c in pages):
        # Rather than serve a clipped series as if it were whole.
        raise ValueError(f"{entity.hn_query}: a chunk exceeded the result cap; "
                         "narrow CHUNK_DAYS before trusting these counts")
    by_day: dict[str, int] = {}
    seen: set[str] = set()
    for body in pages:
        for hit in body.get("hits", []):
            oid = hit.get("objectID")
            if oid in seen:
                continue
            seen.add(oid)
            at = datetime.fromtimestamp(hit["created_at_i"], tz=timezone.utc)
            by_day[at.strftime("%Y-%m-%d")] = by_day.get(at.strftime("%Y-%m-%d"), 0) + 1

    out = []
    for day, count in sorted(by_day.items()):
        at = datetime.strptime(day, "%Y-%m-%d").replace(hour=12, tzinfo=timezone.utc)
        out.append(Record(
            id=f"hn_{entity.id}_{at:%Y%m%d}", kind="hn_stories", subject=entity.id,
            event_time=at, knowable_at=at + PUBLICATION_LAG,
            value={"stories": float(count),
                   # A text query, not an identifier join.
                   "resolution_confidence": 0.9},
            status=Status.REPORTED, source_id=SOURCE_ID,
            lineage=Lineage(documents=frozenset({f"hn_day_{at:%Y%m%d}"}))))
    return out
