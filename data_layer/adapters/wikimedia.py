"""Wikimedia pageviews — public information-seeking behaviour.

Free, deep history, keyed to entities resolvable through Wikidata, and it
measures something no market stream captures: retail information-seeking,
uncoupled from price in the way options are not.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from contract import (Aggregation, Dimension, Emission, HistoricalAccess,
                      Lineage, Phenomenon,
                      Quantity, Record, Retrieval, SourceDeclaration, Status,
                      Survivorship, TemporalType, TruthRole)

from ..cache import fetch
from ..entities import Entity

SOURCE_ID = "wikimedia.pageviews"
URL = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
       "en.wikipedia/all-access/user/{article}/daily/{start}/{end}")

#: The daily bucket for date D is not published the instant D ends. Two days is
#: deliberately conservative: over-conservatism costs signal, lookahead costs the
#: whole result, and only one of those is detectable afterwards.
PUBLICATION_LAG = timedelta(days=2)


def declaration() -> SourceDeclaration:
    return SourceDeclaration(
        source_id=SOURCE_ID,
        measurement_process=("Public information-seeking behaviour; per-article "
                             "daily request counts from Wikimedia's own logs, "
                             "automated traffic excluded"),
        retrieval=Retrieval.AS_OF,
        record_survivorship=Survivorship.COMPLETE,
        backfilled=False,
        historical_access=HistoricalAccess.BULK,
        bulk_endpoint="https://dumps.wikimedia.org/other/pageviews/",
        emits=(Emission(
            kind="pageviews", value_field="views", native_cadence="P1D",
            publication_lag=PUBLICATION_LAG,
            records_of=Phenomenon.INFORMATION_SEEKING, role=TruthRole.OBSERVED,
            quantity=Quantity(Dimension.COUNT, "views", Aggregation.ADDITIVE,
                              TemporalType.DURATION)),),
    )


def fetch_raw(entity: Entity, start: datetime, end: datetime):
    return fetch(URL.format(article=entity.wiki,
                            start=start.strftime("%Y%m%d"),
                            end=end.strftime("%Y%m%d"))).json()


def normalize(raw: dict, entity: Entity) -> list[Record]:
    out = []
    for item in raw.get("items", []):
        ts = datetime.strptime(item["timestamp"], "%Y%m%d%H").replace(tzinfo=timezone.utc)
        out.append(Record(
            id=f"pv_{entity.id}_{ts:%Y%m%d}", kind="pageviews", subject=entity.id,
            event_time=ts, knowable_at=ts + PUBLICATION_LAG,
            value={"views": float(item["views"])}, status=Status.REPORTED,
            source_id=SOURCE_ID,
            lineage=Lineage(documents=frozenset({f"wmf_pageviews_{ts:%Y%m%d}"}))))
    return out
