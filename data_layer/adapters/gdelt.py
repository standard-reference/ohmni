"""GDELT — editorial publication volume.

Raw article counts, not the normalised percentage: the normalised series is
computed against the corpus as it stands at query time, which makes it a snapshot
quantity wearing a historical timestamp. The raw count for a closed day is stable.

The timestamp is GDELT's **ingest** window, not the article's claimed publication
date — which is the honest one to gate on, since ingest is when the item actually
became visible in this stream.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from contract import (Aggregation, Dimension, Emission, Lineage, Phenomenon,
                      Quantity, Record, Retrieval, SourceDeclaration, Status,
                      Survivorship, TemporalType, TruthRole)

from ..cache import fetch
from ..entities import Entity

SOURCE_ID = "gdelt.news"
URL = ("https://api.gdeltproject.org/api/v2/doc/doc?query={q}&mode=timelinevolraw"
       "&startdatetime={start}&enddatetime={end}&format=json")
PUBLICATION_LAG = timedelta(days=1)


def declaration() -> SourceDeclaration:
    return SourceDeclaration(
        source_id=SOURCE_ID,
        measurement_process=("Global news-wire ingestion; count of monitored "
                             "articles mentioning the entity, by ingest day"),
        retrieval=Retrieval.AS_OF,
        record_survivorship=Survivorship.COMPLETE,
        backfilled=False,
        emits=(Emission(
            kind="news", value_field="articles", native_cadence="P1D",
            publication_lag=PUBLICATION_LAG,
            records_of=Phenomenon.EDITORIAL_PUBLICATION, role=TruthRole.OBSERVED,
            quantity=Quantity(Dimension.COUNT, "articles", Aggregation.ADDITIVE,
                              TemporalType.DURATION)),),
    )


def fetch_raw(entity: Entity, start: datetime, end: datetime):
    import urllib.parse
    return fetch(URL.format(q=urllib.parse.quote(entity.gdelt_query),
                            start=start.strftime("%Y%m%d%H%M%S"),
                            end=end.strftime("%Y%m%d%H%M%S"))).json()


def normalize(raw: dict, entity: Entity) -> list[Record]:
    timeline = raw.get("timeline") or []
    if not timeline:
        return []
    out = []
    for point in timeline[0].get("data", []):
        at = datetime.strptime(point["date"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        out.append(Record(
            id=f"nw_{entity.id}_{at:%Y%m%d}", kind="news", subject=entity.id,
            event_time=at, knowable_at=at + PUBLICATION_LAG,
            value={"articles": float(point["value"]),
                   # Entity resolution here is a text query, not an identifier
                   # join. That confidence must reach the cancellation, not sit
                   # in a log — a fuzzy match makes a field look like it moved.
                   "resolution_confidence": 0.75},
            status=Status.REPORTED, source_id=SOURCE_ID,
            lineage=Lineage(documents=frozenset({f"gdelt_ingest_{at:%Y%m%d}"}))))
    return out
