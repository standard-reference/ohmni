"""FINRA daily short sale volume — off-exchange order routing.

Free, official, daily, with an honest lag, and it measures something no price
feed does: where volume actually executed. One of the few genuinely independent
measurement processes available at zero cost.

Note the shared document: short volume and total volume arrive in ONE file, so
they share lineage completely and can never be two independent legs. The
independence machinery sees that from the lineage without being told.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from contract import (Aggregation, Dimension, Emission, Lineage, Phenomenon,
                      Quantity, Record, Retrieval, SourceDeclaration, Status,
                      Survivorship, TemporalType, TruthRole)

from ..cache import fetch
from ..entities import Entity

SOURCE_ID = "finra.short"
URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date}.txt"
PUBLICATION_LAG = timedelta(days=1)


def declaration() -> SourceDeclaration:
    return SourceDeclaration(
        source_id=SOURCE_ID,
        measurement_process=("Off-exchange order routing; FINRA-member reported "
                             "daily short sale and total volume by symbol"),
        retrieval=Retrieval.AS_OF,
        record_survivorship=Survivorship.COMPLETE,
        backfilled=False,
        emits=(Emission(
            kind="short_volume", value_field="short_share", native_cadence="P1D",
            publication_lag=PUBLICATION_LAG, subject_type="instrument",
            records_of=Phenomenon.OFF_EXCHANGE_ROUTING, role=TruthRole.ATTESTED,
            quantity=Quantity(Dimension.RATIO, "share", Aggregation.WEIGHTED_AVERAGE,
                              TemporalType.DURATION, weight_field="total_volume")),),
    )


def fetch_raw(day: datetime):
    """Returns None on a non-trading day — an absent file is a closed market, and
    it must never become a zero."""
    # FINRA answers 403, not 404, for a day with no file. Both mean the
    # same thing here: no report exists for that date.
    return fetch(URL.format(date=day.strftime("%Y%m%d")), absent=(403, 404))


def normalize(raw_text: str, day: datetime, wanted: dict[str, Entity]) -> list[Record]:
    out = []
    doc = f"finra_cnms_{day:%Y%m%d}"
    for line in raw_text.splitlines()[1:]:
        parts = line.split("|")
        if len(parts) < 5 or parts[1] not in wanted:
            continue
        entity = wanted[parts[1]]
        try:
            short_v, total_v = float(parts[2]), float(parts[4])
        except ValueError:
            continue
        if total_v <= 0:
            continue
        at = datetime.strptime(parts[0], "%Y%m%d").replace(
            hour=16, tzinfo=timezone.utc)
        out.append(Record(
            id=f"sv_{entity.ticker}_{at:%Y%m%d}", kind="short_volume",
            subject=entity.instrument, event_time=at,
            knowable_at=at + PUBLICATION_LAG,
            value={"short_share": short_v / total_v, "total_volume": total_v},
            status=Status.REPORTED, source_id=SOURCE_ID,
            lineage=Lineage(documents=frozenset({doc}))))
    return out
