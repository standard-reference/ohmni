"""SEC EDGAR XBRL — natively point-in-time, which is the decisive property.

Every fact instance carries `end` (period end), `val`, `accn` (accession) and
`filed` (filing date). Where a period is later restated, **multiple fact objects
exist for the same `end` with different accession numbers** — so the full
revision chain is preserved rather than two fixed projections of it.

`as_of(T)` = filter to `filed <= T`, take the latest `filed` per `end`. That
dominates both vendor dimensions: as-reported pins to the first print forever and
ignores that the market later learned the restatement; most-recent is lookahead.

Free, public domain, no key. The one source here with no caveat attached.
"""
from __future__ import annotations

from datetime import datetime, time, timezone

from contract import (Aggregation, Dimension, Emission, HistoricalAccess,
                      Lineage, Phenomenon,
                      Quantity, Record, Retrieval, Revision, SourceDeclaration,
                      Status, Survivorship, TemporalType, TruthRole)

from ..cache import fetch
from ..entities import Entity

SOURCE_ID = "edgar.xbrl"
URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"

#: Tag precedence for one concept — a finite, known set, solved by a lookup table
#: with an order. This is the tractable half of the comparability problem; the
#: intractable half (a bank's revenue is not a manufacturer's) needs peer-group
#: scoping and is not a standardization problem at all.
REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
)
CONCEPT_MAP_VERSION = "cm_ohmni.1"


def declaration() -> SourceDeclaration:
    return SourceDeclaration(
        source_id=SOURCE_ID,
        measurement_process=("Corporate accounting disclosure filed under the SEC "
                             "XBRL taxonomy, with filing acceptance dates and full "
                             "restatement chains"),
        retrieval=Retrieval.AS_OF,
        record_survivorship=Survivorship.COMPLETE,
        backfilled=False,
        historical_access=HistoricalAccess.BULK,
        bulk_endpoint="https://www.sec.gov/Archives/edgar/full-index/",
        emits=(Emission(
            kind="fundamental", value_field="amount", native_cadence="P3M",
            carries_period=True,
            # No declared lag: EDGAR exposes a real availability field, so the lag
            # is observed per record rather than assumed.
            records_of=Phenomenon.CORPORATE_DISCLOSURE, role=TruthRole.CONSTITUTIVE,
            quantity=Quantity(Dimension.MONETARY_FLOW, "USD", Aggregation.ADDITIVE,
                              TemporalType.DURATION)),),
    )


def fetch_raw(entity: Entity) -> tuple[dict | None, str | None]:
    for tag in REVENUE_TAGS:
        got = fetch(URL.format(cik=entity.cik, tag=tag), absent=(403, 404))
        if got is not None:
            return got.json(), tag
    return None, None


def normalize(raw: dict, tag: str, entity: Entity) -> list[Record]:
    """Pure. The revision chain falls out of the data: group by period, order by
    filing date, and the chain index is the position in that order."""
    if raw is None:
        return []
    facts = raw.get("units", {}).get("USD", [])

    by_period: dict[tuple, list[dict]] = {}
    for f in facts:
        if not f.get("start") or not f.get("end") or f.get("val") is None:
            continue
        days = (_d(f["end"]) - _d(f["start"])).days
        # Disambiguate by duration length, never silently pick one: a Q3 10-Q
        # reports both Jul-Sep and Jan-Sep, and they are different quantities.
        span = ("standalone_quarter" if 80 <= days <= 100
                else "annual" if 350 <= days <= 380
                else "year_to_date" if 150 <= days <= 290
                else None)
        if span is None:
            continue
        by_period.setdefault((f["start"], f["end"], span), []).append(f)

    out: list[Record] = []
    for (start, end, span), group in by_period.items():
        # One accession per link; the same figure repeated in later filings as a
        # comparative is not a new link in the chain.
        seen: dict[str, dict] = {}
        for f in sorted(group, key=lambda x: (x["filed"], x["accn"])):
            seen.setdefault(f["accn"], f)
        links = sorted(seen.values(), key=lambda x: x["filed"])
        deduped = [links[0]]
        for f in links[1:]:
            if f["val"] != deduped[-1]["val"]:
                deduped.append(f)          # a chain link is a CHANGE in the value
        chain_len = len(deduped)
        for idx, f in enumerate(deduped):
            filed = datetime.combine(_d(f["filed"]), time(21, 0), tzinfo=timezone.utc)
            superseded = (datetime.combine(_d(deduped[idx + 1]["filed"]), time(21, 0),
                                           tzinfo=timezone.utc)
                          if idx + 1 < chain_len else None)
            out.append(Record(
                id=f"fct_{entity.id}_{end}_{span}_{f['accn']}", kind="fundamental",
                subject=entity.id,
                event_time=datetime.combine(_d(end), time(0, 0), tzinfo=timezone.utc),
                knowable_at=filed,
                value={"concept": "revenue", "source_tag": tag,
                       "map_version": CONCEPT_MAP_VERSION,
                       "period_end": _d(end).isoformat(), "period_start": start,
                       "span": span, "days": (_d(end) - _d(start)).days,
                       "amount": str(int(f["val"])), "unit": "USD", "scale": 1,
                       "form": f.get("form"), "fy": f.get("fy"), "fp": f.get("fp")},
                status=Status.REPORTED, source_id=SOURCE_ID,
                lineage=Lineage(documents=frozenset({f["accn"]})),
                revision=Revision(index=idx, chain_length=chain_len,
                                  superseded_at=superseded)))
    return out


def _d(s: str):
    return datetime.strptime(s, "%Y-%m-%d").date()
