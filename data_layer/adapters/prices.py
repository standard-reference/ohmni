"""Daily closes — PROTOTYPE GRADE, and declared as such.

This source fails two of the criteria that decide everything, and says so rather
than being quietly used:

- **Survivorship.** Only currently-listed tickers are served. A universe built
  from it silently excludes everything that delisted, went bankrupt or was
  acquired, which inflates every backtest invisibly.
- **Retroactive adjustment.** Closes are split-adjusted with information that did
  not exist at the time. Daily *returns* are unaffected by a uniform split factor
  applied to both endpoints, which is why returns are what this emits and levels
  are not — but the adjustment is still a fact about the data and is declared.

`adjclose` is deliberately never read: dividend adjustment does change returns,
and applying a later dividend to an earlier bar is lookahead in a field that
looks innocent.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from contract import (Aggregation, Dimension, Emission, Lineage, Phenomenon,
                      Quantity, Record, Retrieval, SourceDeclaration, Status,
                      Survivorship, TemporalType, TruthRole)

from ..cache import fetch
from ..entities import Entity

SOURCE_ID = "prices.daily"
URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
       "?period1={p1}&period2={p2}&interval=1d")

#: A close is knowable shortly after the bell, not at the bar's stamped time.
PUBLICATION_LAG = timedelta(hours=2)


def declaration() -> SourceDeclaration:
    return SourceDeclaration(
        source_id=SOURCE_ID,
        measurement_process=("Exchange order matching; consolidated daily closing "
                             "price, retroactively split-adjusted by the vendor"),
        retrieval=Retrieval.AS_OF,
        # The declaration that marks the run. Delisted names are absent and
        # unrecoverable, which is the record-level form of survivorship bias.
        record_survivorship=Survivorship.DELETIONS_UNRECOVERABLE,
        backfilled=True,
        emits=(Emission(
            kind="price", value_field="close_return", native_cadence="P1D",
            publication_lag=PUBLICATION_LAG, subject_type="instrument",
            records_of=Phenomenon.EXCHANGE_ACTIVITY, role=TruthRole.CONSTITUTIVE,
            quantity=Quantity(Dimension.RATE, "return", Aggregation.AVERAGEABLE,
                              TemporalType.DURATION)),),
    )


def fetch_raw(entity: Entity, start: datetime, end: datetime):
    return fetch(URL.format(sym=entity.ticker,
                            p1=int(start.timestamp()),
                            p2=int(end.timestamp()))).json()


def normalize(raw: dict, entity: Entity) -> list[Record]:
    result = raw["chart"]["result"][0]
    stamps = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]
    out, prev = [], None
    for ts, close in zip(stamps, closes):
        if close is None:
            continue                      # a gap in the feed is not a zero return
        at = datetime.fromtimestamp(ts, tz=timezone.utc)
        if prev is not None and prev[1]:
            out.append(Record(
                id=f"px_{entity.ticker}_{at:%Y%m%d}", kind="price",
                subject=entity.instrument, event_time=at,
                knowable_at=at + PUBLICATION_LAG,
                value={"close_return": (close / prev[1]) - 1.0,
                       "close": close},
                status=Status.REPORTED, source_id=SOURCE_ID,
                lineage=Lineage(documents=frozenset({f"tape_{entity.ticker}_{at:%Y%m%d}"}))))
        prev = (at, close)
    return out
