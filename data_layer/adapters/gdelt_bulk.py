"""GDELT GKG daily archive — editorial publication, from the bulk path.

The query API rate-limits below any backfill speed and returns 429 at the IP
level for minutes at a time. The archive it is a front end for is completely
open: range requests, no throttle, 26 MB compressed per day, ~1.5s each. This
adapter uses the archive.

**The cache here is a declared reduction, not the verbatim response.** A day's
GKG is 26 MB and a multi-epoch pull is ~19 GB of it, for what amounts to six
daily mention counts. So `fetch` filters to the declared alias set before
caching, and the alias-set version is part of the cache key — change the entity
set or an alias and the cache correctly misses rather than serving a subset
filtered under different rules.

That is a real departure from caching raw bytes verbatim, and it costs the
ability to re-derive a *different* entity set without refetching. It is recorded
rather than quietly done: the filter runs at the network boundary, is
deterministic, and `normalize` remains a pure function of what was cached.
"""
from __future__ import annotations

import gzip
import io
import zipfile
from datetime import datetime, timedelta, timezone

from contract import (Aggregation, Dimension, Emission, HistoricalAccess, Lineage,
                      Phenomenon, Quantity, Record, Retrieval, SourceDeclaration,
                      Status, Survivorship, TemporalType, TruthRole)

from ..cache import CACHE_DIR, fetch
from ..entities import GKG_ALIAS_VERSION, gkg_alias_index

SOURCE_ID = "gdelt.gkg"
URL = "https://data.gdeltproject.org/gkg/{date}.gkg.csv.zip"
BULK_INDEX = "https://data.gdeltproject.org/gdeltv2/masterfilelist.txt"

#: The daily file for date D lands the following day.
PUBLICATION_LAG = timedelta(days=1)

_ORGS_COL = 6      # 0-based: DATE NUMARTS COUNTS THEMES LOCATIONS PERSONS ORGANIZATIONS
_NUMARTS_COL = 1


def declaration() -> SourceDeclaration:
    return SourceDeclaration(
        source_id=SOURCE_ID,
        measurement_process=("Global news-wire ingestion; count of monitored "
                             "articles naming the organization, from the GDELT "
                             "Global Knowledge Graph daily archive"),
        retrieval=Retrieval.AS_OF,
        record_survivorship=Survivorship.COMPLETE,
        backfilled=False,
        historical_access=HistoricalAccess.BULK,
        bulk_endpoint=BULK_INDEX,
        emits=(Emission(
            kind="news", value_field="articles", native_cadence="P1D",
            publication_lag=PUBLICATION_LAG,
            records_of=Phenomenon.EDITORIAL_PUBLICATION, role=TruthRole.OBSERVED,
            quantity=Quantity(Dimension.COUNT, "articles", Aggregation.ADDITIVE,
                              TemporalType.DURATION)),),
    )


def _reduced_path(day: datetime):
    return CACHE_DIR.parent / "gkg_reduced" / GKG_ALIAS_VERSION / f"{day:%Y%m%d}.tsv.gz"


def fetch_raw(day: datetime) -> str | None:
    """Download one day, reduce to the declared aliases, cache the reduction.

    Returns None for a day with no file — an absent day is a real answer and
    must never become a row of zeros.
    """
    path = _reduced_path(day)
    if path.exists():
        return gzip.decompress(path.read_bytes()).decode()

    got = fetch(URL.format(date=day.strftime("%Y%m%d")), absent=(403, 404),
                store=False)
    if got is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(b""))      # remembered as genuinely absent
        return ""

    index = gkg_alias_index()
    tallies: dict[str, int] = {}
    with zipfile.ZipFile(io.BytesIO(got.body)) as z:
        with z.open(z.namelist()[0]) as fh:
            for raw in io.TextIOWrapper(fh, encoding="utf-8", errors="replace"):
                cols = raw.rstrip("\n").split("\t")
                if len(cols) <= _ORGS_COL or not cols[_ORGS_COL]:
                    continue
                try:
                    n = int(cols[_NUMARTS_COL])
                except ValueError:
                    continue
                hit: set[str] = set()
                for org in cols[_ORGS_COL].split(";"):
                    eid = index.get(org.strip().lower())
                    if eid:
                        hit.add(eid)
                # One record naming an entity twice is one article, not two.
                for eid in hit:
                    tallies[eid] = tallies.get(eid, 0) + n

    body = "\n".join(f"{eid}\t{n}" for eid, n in sorted(tallies.items()))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(body.encode()))
    return body


def normalize(reduced: str | None, day: datetime, entities) -> list[Record]:
    """Pure over the cached reduction."""
    if not reduced:
        return []
    by_id = {e.id: e for e in entities}
    out = []
    for line in reduced.splitlines():
        eid, _, count = line.partition("\t")
        if eid not in by_id or not count:
            continue
        at = day.replace(hour=12, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
        out.append(Record(
            id=f"gkg_{eid}_{at:%Y%m%d}", kind="news", subject=eid,
            event_time=at, knowable_at=at + PUBLICATION_LAG,
            value={"articles": float(count),
                   # Exact match against a curated alias set, which is a far
                   # stronger join than the DOC API's text query — but still a
                   # name match, not an identifier, so it discounts separation.
                   "resolution_confidence": 0.95,
                   "alias_version": GKG_ALIAS_VERSION},
            status=Status.REPORTED, source_id=SOURCE_ID,
            lineage=Lineage(documents=frozenset({f"gkg_daily_{at:%Y%m%d}"}))))
    return out
