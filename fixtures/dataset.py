"""The hand-built, internally-consistent synthetic dataset.

An interface with one implementation is a guess; two is a contract. This is the
second implementation, and it is deliberately the one the harness test suite runs
against — if a harness test needs the real data layer, something has leaked.

Everything here is designed backwards from a test. Each construct exists to make
one claim in the spec falsifiable, and `groundtruth.py` states the expected answer
independently of the code that computes it.
"""
from __future__ import annotations

import random
import zlib
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from contract import (
    Aggregation,
    Coupling,
    Dimension,
    Emission,
    Lineage,
    MeasurementType,
    Quantity,
    Record,
    Retrieval,
    Revision,
    SourceDeclaration,
    Phenomenon,
    SourceRegistry,
    Status,
    Survivorship,
    TemporalType,
    TruthRole,
)

UTC = timezone.utc


def dt(y: int, m: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=UTC)


# ── Entities ────────────────────────────────────────────────────────────────
ENT_A = "ent_0000000001"   # Northwind Systems — technology_hardware
ENT_B = "ent_0000000002"   # Cascade Manufacturing — technology_hardware (peer of A)
ENT_C = "ent_0000000003"   # Meridian Savings — banking (NOT a peer; comparability guard)

INST_A = "inst_NWS_common"
INST_B = "inst_CSM_common"

PEER_GROUP = {ENT_A: "technology_hardware", ENT_B: "technology_hardware", ENT_C: "banking"}

#: The instrument spine, declared as data. One entity has many instruments and
#: they are not interchangeable, so the expansion is explicit and reported rather
#: than defaulted to the primary class silently.
INST_OPT_A = "opt_NWS_surface"      # an option surface is its own instrument
INSTRUMENT_OF = {INST_A: ENT_A, INST_B: ENT_B, INST_OPT_A: ENT_A}
INSTRUMENTS_OF = {ENT_A: (INST_A,), ENT_B: (INST_B,), ENT_C: ()}


# ── Source declarations ─────────────────────────────────────────────────────
# Fifteen independent measurement processes is the scorecard that matters; this
# fixture spans six of them, chosen to cover every independence case in B3.
def _q(dimension, unit, aggregation, temporal=TemporalType.DURATION, **kw) -> Quantity:
    return Quantity(dimension=dimension, unit=unit, aggregation=aggregation,
                    temporal_type=temporal, **kw)


SOURCES: tuple[SourceDeclaration, ...] = (
    SourceDeclaration(
        source_id="edgar.xbrl",
        measurement_process="Corporate accounting disclosure filed under SEC XBRL taxonomy",
        retrieval=Retrieval.AS_OF,
        record_survivorship=Survivorship.COMPLETE,
        backfilled=False,
        emits=(
            Emission(
                kind="fundamental", value_field="amount", native_cadence="P3M",
                records_of=Phenomenon.CORPORATE_DISCLOSURE, role=TruthRole.CONSTITUTIVE,
                # No publication_lag: EDGAR exposes a real availability field
                # (`filed`), so the lag is observed per record, not assumed. A
                # declared lag is the fallback for sources that expose none.
                carries_period=True,
                quantity=_q(Dimension.MONETARY_FLOW, "USD", Aggregation.ADDITIVE),
            ),
        ),
    ),
    SourceDeclaration(
        source_id="prices.eod",
        measurement_process="Exchange order matching, end-of-day consolidated tape",
        retrieval=Retrieval.AS_OF,
        record_survivorship=Survivorship.COMPLETE,
        backfilled=False,
        emits=(
            Emission(
                kind="price", value_field="close_return", native_cadence="P1D",
                records_of=Phenomenon.EXCHANGE_ACTIVITY, role=TruthRole.CONSTITUTIVE,
                publication_lag=timedelta(hours=2), subject_type="instrument",
                quantity=_q(Dimension.RATE, "return", Aggregation.AVERAGEABLE),
            ),
        ),
    ),
    SourceDeclaration(
        source_id="options.iv",
        measurement_process="Exchange order matching of listed options; implied volatility surface",
        retrieval=Retrieval.AS_OF,
        record_survivorship=Survivorship.COMPLETE,
        backfilled=False,
        emits=(
            Emission(
                kind="options_skew", value_field="skew", native_cadence="P1D",
                records_of=Phenomenon.EXCHANGE_ACTIVITY, role=TruthRole.CONSTITUTIVE,
                publication_lag=timedelta(hours=2), subject_type="instrument",
                quantity=_q(Dimension.RATIO, "ratio", Aggregation.AVERAGEABLE),
            ),
        ),
        # Disjoint lineage, distant provenance, mechanically coupled through delta.
        # Neither root sets nor provenance embeddings catch this; only this does.
        couples_to=(Coupling(subject=INST_A, strength=0.9, instrument=INST_OPT_A),),
    ),
    SourceDeclaration(
        source_id="gdelt.news",
        measurement_process="Global news-wire ingestion; article-level editorial publication",
        retrieval=Retrieval.AS_OF,
        record_survivorship=Survivorship.COMPLETE,
        backfilled=False,
        emits=(
            Emission(
                kind="news", value_field=None, native_cadence="irregular",
                # An article record IS a publication event — constitutive of
                # editorial publication, and only an echo with respect to whatever
                # filing or event it reports on.
                records_of=Phenomenon.EDITORIAL_PUBLICATION, role=TruthRole.CONSTITUTIVE,
                publication_lag=timedelta(minutes=15),
                # Irregular streams have no native cadence and become
                # rate-per-window fields at the panel resolution.
                quantity=_q(Dimension.COUNT, "articles", Aggregation.ADDITIVE),
            ),
        ),
    ),
    SourceDeclaration(
        source_id="sentiment.derived",
        measurement_process="Pinned local scoring of article text from gdelt.news",
        retrieval=Retrieval.AS_OF,
        record_survivorship=Survivorship.COMPLETE,
        backfilled=False,
        measurement_type=MeasurementType.MEASURED,
        emits=(
            Emission(
                kind="sentiment", value_field="score", native_cadence="irregular",
                records_of=Phenomenon.EDITORIAL_PUBLICATION, role=TruthRole.DERIVED,
                publication_lag=timedelta(minutes=20),
                quantity=_q(Dimension.INDEX, "score", Aggregation.AVERAGEABLE),
            ),
        ),
    ),
    SourceDeclaration(
        source_id="wikimedia.pageviews",
        measurement_process="Public information-seeking behaviour; per-article hourly request counts",
        retrieval=Retrieval.AS_OF,
        record_survivorship=Survivorship.COMPLETE,
        backfilled=False,
        emits=(
            Emission(
                kind="pageviews", value_field="views", native_cadence="PT1H",
                # A count aggregating many seeking acts: a measurement of the
                # phenomenon rather than the phenomenon itself.
                records_of=Phenomenon.INFORMATION_SEEKING, role=TruthRole.OBSERVED,
                publication_lag=timedelta(days=1),
                quantity=_q(Dimension.COUNT, "views", Aggregation.ADDITIVE),
            ),
        ),
    ),
    SourceDeclaration(
        source_id="finra.short",
        measurement_process="Off-exchange order routing; daily short sale volume by symbol",
        retrieval=Retrieval.AS_OF,
        record_survivorship=Survivorship.COMPLETE,
        backfilled=False,
        emits=(
            Emission(
                kind="short_volume", value_field="short_share", native_cadence="P1D",
                # FINRA aggregates what its members report, so it is attested
                # rather than constitutive.
                records_of=Phenomenon.OFF_EXCHANGE_ROUTING, role=TruthRole.ATTESTED,
                publication_lag=timedelta(days=2), subject_type="instrument",
                quantity=_q(Dimension.RATIO, "share", Aggregation.WEIGHTED_AVERAGE,
                            weight_field="total_volume"),
            ),
        ),
    ),
    SourceDeclaration(
        source_id="social.stream",
        measurement_process="Retail discourse; public post stream with engagement counters",
        retrieval=Retrieval.SNAPSHOT,                       # historical query returns TODAY's counts
        record_survivorship=Survivorship.DELETIONS_UNRECOVERABLE,
        backfilled=True,
        emits=(
            # A post asserting something false is still a perfect record of
            # retail discourse. Whether the claim inside it is true of the world
            # is not a question this layer asks.
            Emission(kind="social_post", value_field=None, native_cadence="PT1M",
                     records_of=Phenomenon.RETAIL_DISCOURSE, role=TruthRole.CONSTITUTIVE,
                     quantity=_q(Dimension.COUNT, "posts", Aggregation.ADDITIVE,
                                 temporal=TemporalType.INSTANT)),
            Emission(kind="social_engagement", value_field="likes", native_cadence="PT1M",
                     records_of=Phenomenon.RETAIL_DISCOURSE, role=TruthRole.OBSERVED,
                     quantity=_q(Dimension.COUNT, "likes", Aggregation.POINT_IN_TIME,
                                 temporal=TemporalType.INSTANT)),
        ),
    ),
)

SOURCES = SOURCES + (
    SourceDeclaration(
        source_id="edgar.filings",
        measurement_process="Electronic filing submission to SEC EDGAR; acceptance datetime",
        retrieval=Retrieval.AS_OF,
        record_survivorship=Survivorship.COMPLETE,
        backfilled=False,
        emits=(
            Emission(kind="filing", value_field=None, native_cadence="irregular",
                     records_of=Phenomenon.CORPORATE_DISCLOSURE,
                     role=TruthRole.CONSTITUTIVE,
                     quantity=_q(Dimension.COUNT, "filings", Aggregation.ADDITIVE,
                                 temporal=TemporalType.INSTANT)),
        ),
    ),
    SourceDeclaration(
        source_id="regulator.register",
        measurement_process="Regulator's own register of actions; publication date",
        retrieval=Retrieval.AS_OF,
        record_survivorship=Survivorship.COMPLETE,
        backfilled=False,
        emits=(
            Emission(kind="regulatory_notice", value_field=None, native_cadence="irregular",
                     records_of=Phenomenon.REGULATORY_ACTION,
                     role=TruthRole.CONSTITUTIVE,
                     quantity=_q(Dimension.COUNT, "notices", Aggregation.ADDITIVE,
                                 temporal=TemporalType.INSTANT)),
        ),
    ),
)

REGISTRY = SourceRegistry(SOURCES)

SOURCE_BY_ID = {s.source_id: s for s in SOURCES}


# ── Observation scenarios ───────────────────────────────────────────────────
# Each is 8 weekly frames. The shape of each field across those frames is the
# ground truth every B2 assertion is checked against.
SCENARIOS: dict[str, dict] = {
    # One field moves while correlated peers hold invariant: a specific, localised
    # event. Residue cardinality 1 against invariant cardinality 3 — high specificity.
    "localised": {
        "start": dt(2019, 3, 4),
        "pageviews": [1000, 1010, 995, 4000, 3800, 1400, 1050, 1005],
        "price_ret":  [0.0002, -0.0003, 0.0001, 0.0004, -0.0002, 0.0003, 0.0000, 0.0001],
        "news_rate":  [3, 3, 4, 3, 4, 3, 3, 4],
        "short_share": [0.21, 0.22, 0.21, 0.22, 0.21, 0.22, 0.21, 0.22],
        "news_confidence": 0.97,
    },
    # Everything moves together: a market-wide shift with no attribution.
    # Residue cardinality 4 against invariant cardinality 0 — low specificity.
    "market_wide": {
        "start": dt(2019, 6, 3),
        "pageviews": [1000, 1020, 1900, 3600, 3700, 3500, 3400, 3300],
        "price_ret":  [0.0002, 0.0010, 0.0090, 0.0180, 0.0175, 0.0160, 0.0155, 0.0150],
        "news_rate":  [3, 4, 9, 18, 19, 17, 16, 16],
        "short_share": [0.21, 0.23, 0.31, 0.44, 0.45, 0.43, 0.42, 0.41],
        "news_confidence": 0.96,
    },
    # News separates on the raw numbers, but the mentions were linked to the entity
    # by fuzzy name match. Residue that is really entity drift, indistinguishable
    # from a finding unless resolution confidence reaches the computation.
    "entity_drift": {
        "start": dt(2019, 9, 2),
        "pageviews": [1000, 1005, 998, 1002, 1010, 995, 1000, 1008],
        "price_ret":  [0.0001, -0.0002, 0.0002, 0.0000, 0.0001, -0.0001, 0.0002, 0.0000],
        "news_rate":  [3, 3, 4, 14, 16, 14, 4, 3],
        "short_share": [0.21, 0.22, 0.21, 0.22, 0.21, 0.22, 0.21, 0.22],
        "news_confidence": 0.55,          # fuzzy name match — tier 3
    },
    # Nothing moves. The control for the control.
    "quiet": {
        "start": dt(2019, 1, 7),
        "pageviews": [1000, 1005, 998, 1002, 1010, 995, 1000, 1008],
        "price_ret":  [0.0001, -0.0002, 0.0002, 0.0000, 0.0001, -0.0001, 0.0002, 0.0000],
        "news_rate":  [3, 3, 4, 3, 4, 3, 3, 4],
        "short_share": [0.21, 0.22, 0.21, 0.22, 0.21, 0.22, 0.21, 0.22],
        "news_confidence": 0.97,
    },
}

FRAME_COUNT = 8
FRAME_DAYS = 7

# Publication lag is read from each source's own declared Emission — there is no
# second table here to drift out of step with it.
def lag(kind: str) -> timedelta:
    return REGISTRY.declared_lag(kind) or timedelta(0)


def _seed(*parts: object) -> int:
    """Stable across processes. `hash()` on str is salted per interpreter run, so
    using it here would make the dataset non-reproducible between runs — the exact
    failure the normalize-determinism check exists to catch."""
    return zlib.crc32("|".join(repr(p) for p in parts).encode("utf-8"))


def _jitter(seed_parts: tuple, amplitude: float) -> float:
    """Deterministic pseudo-noise, seeded from the record's own identity so the
    dataset is byte-identical on every construction and in every process."""
    rng = random.Random(_seed(*seed_parts))
    return (rng.random() - 0.5) * 2 * amplitude


@lru_cache(maxsize=None)
def scenario_records(name: str, subject: str = ENT_A, shuffled: bool = False,
                     shuffle_seed: int = 0) -> tuple[Record, ...]:
    """Records for one observation scenario, at each source's native cadence.

    `shuffled=True` is the null: the same marginal values, permuted across time,
    so every cross-stream relationship is destroyed and the level statistics are
    preserved. If the pipeline promotes anything on this, false-discovery control
    is broken and every downstream result is meaningless.
    """
    spec = SCENARIOS[name]
    start: datetime = spec["start"]
    out: list[Record] = []

    weeks = list(range(FRAME_COUNT))
    if shuffled:
        # Permute the week index independently per field: levels survive, joint
        # structure does not.
        def perm(salt: str) -> list[int]:
            r = random.Random(_seed(name, salt, "null", shuffle_seed))
            w = list(weeks)
            r.shuffle(w)
            return w
        pv_w, pr_w, nw_w, sh_w = perm("pv"), perm("pr"), perm("nw"), perm("sh")
    else:
        pv_w = pr_w = nw_w = sh_w = weeks

    for w in weeks:
        week_start = start + timedelta(days=FRAME_DAYS * w)

        # wikimedia.pageviews — hourly
        hourly = spec["pageviews"][pv_w[w]] / 24.0
        for day in range(FRAME_DAYS):
            for hour in range(24):
                et = week_start + timedelta(days=day, hours=hour)
                v = hourly * (1 + _jitter((name, subject, "pv", w, day, hour), 0.03))
                out.append(Record(
                    id=f"pv_{subject}_{et:%Y%m%d%H}",
                    kind="pageviews", subject=subject,
                    event_time=et, knowable_at=et + lag("pageviews"),
                    value={"views": round(v, 4)}, status=Status.REPORTED,
                    source_id="wikimedia.pageviews",
                    lineage=Lineage(documents=frozenset({f"wmf_dump_{et:%Y%m%d}"})),
                ))

        # prices.eod + finra.short — daily
        for day in range(FRAME_DAYS):
            et = week_start + timedelta(days=day, hours=16)
            ret = spec["price_ret"][pr_w[w]] + _jitter((name, subject, "pr", w, day), 0.0004)
            out.append(Record(
                id=f"px_{subject}_{et:%Y%m%d}",
                kind="price", subject=INST_A if subject == ENT_A else INST_B,
                event_time=et, knowable_at=et + lag("price"),
                value={"close_return": round(ret, 8)}, status=Status.REPORTED,
                source_id="prices.eod",
                lineage=Lineage(documents=frozenset({f"tape_{et:%Y%m%d}"})),
            ))
            sh = spec["short_share"][sh_w[w]] + _jitter((name, subject, "sh", w, day), 0.004)
            out.append(Record(
                id=f"sv_{subject}_{et:%Y%m%d}",
                kind="short_volume", subject=INST_A if subject == ENT_A else INST_B,
                event_time=et, knowable_at=et + lag("short_volume"),
                value={"short_share": round(sh, 6), "total_volume": 1_000_000},
                status=Status.REPORTED,
                source_id="finra.short",
                lineage=Lineage(documents=frozenset({f"finra_daily_{et:%Y%m%d}"})),
            ))

        # gdelt.news — irregular, becomes a rate-per-window field at the basis
        # resolution. A count, never a zero-filled series.
        n = spec["news_rate"][nw_w[w]]
        for i in range(n):
            et = week_start + timedelta(days=(i * FRAME_DAYS) // max(n, 1), hours=9 + (i % 6))
            doc = f"art_{subject}_{name}_{w}_{i}"
            out.append(Record(
                id=f"nw_{doc}",
                kind="news", subject=subject,
                event_time=et, knowable_at=et + lag("news"),
                value={"headline": f"coverage {w}/{i}",
                       "resolution_confidence": spec["news_confidence"]},
                status=Status.REPORTED, source_id="gdelt.news",
                lineage=Lineage(documents=frozenset({doc})),
            ))
            # Derived sentiment: computed FROM the article text. Shared lineage,
            # shared provenance — the deliberate true-negative for independence.
            out.append(Record(
                id=f"sn_{doc}",
                kind="sentiment", subject=subject,
                event_time=et, knowable_at=et + lag("sentiment"),
                value={"score": round(0.1 + _jitter((doc,), 0.3), 4)},
                status=Status.DERIVED, source_id="sentiment.derived",
                lineage=Lineage(documents=frozenset({doc}), derived_from=(f"nw_{doc}",)),
            ))

    out.sort(key=lambda r: (r.knowable_at, r.id))
    return tuple(out)


# ── Fundamentals: the restatement chain and the typed gaps ──────────────────
# The test that settles point-in-time claims empirically: pick a company with a
# known restatement, query as-of a date before it was filed, and check whether
# you get the original figures or today's.

REVENUE_A_Q2_ORIGINAL = "1000000000"
REVENUE_A_Q2_RESTATED = "900000000"
RESTATEMENT_FILED_AT = dt(2019, 10, 31, 21, 2)
ORIGINAL_FILED_AT = dt(2019, 5, 1, 20, 31)


def _fact(rid, subject, concept, period_end, knowable_at, amount, status,
          source_doc, revision=None, derived_from=(), span="standalone_quarter",
          reason=None) -> Record:
    value: dict = {"concept": concept, "period_end": period_end.isoformat(), "span": span}
    if amount is not None:
        # amount is a string: large integers lose precision in some JSON parsers,
        # and language models mangle long digit strings.
        value |= {"amount": amount, "unit": "USD", "scale": 1}
    if reason:
        value["reason"] = reason
    return Record(
        id=rid, kind="fundamental", subject=subject,
        event_time=period_end, knowable_at=knowable_at,
        value=value, status=status, source_id="edgar.xbrl",
        lineage=Lineage(documents=frozenset({source_doc}) if source_doc else frozenset(),
                        derived_from=derived_from),
        revision=revision,
    )


@lru_cache(maxsize=None)
def fundamentals() -> tuple[Record, ...]:
    q1, q2, q3, q4 = dt(2018, 12, 29), dt(2019, 3, 30), dt(2019, 6, 29), dt(2019, 9, 28)
    out = [
        # A/Q1 — clean single-link chain.
        _fact("fct_A_rev_q1", ENT_A, "revenue", q1, dt(2019, 2, 1, 20, 30),
              "840000000", Status.REPORTED, "0000000001-19-000010",
              Revision(index=0, chain_length=1)),

        # A/Q2 — the restatement. Two links, same period, different accessions.
        # as_of before 2019-10-31 must return the original; after, the restated.
        _fact("fct_A_rev_q2_v0", ENT_A, "revenue", q2, ORIGINAL_FILED_AT,
              REVENUE_A_Q2_ORIGINAL, Status.REPORTED, "0000000001-19-000066",
              Revision(index=0, chain_length=2, superseded_at=RESTATEMENT_FILED_AT)),
        _fact("fct_A_rev_q2_v1", ENT_A, "revenue", q2, RESTATEMENT_FILED_AT,
              REVENUE_A_Q2_RESTATED, Status.REPORTED, "0000000001-19-000091",
              Revision(index=1, chain_length=2)),

        _fact("fct_A_rev_q3", ENT_A, "revenue", q3, dt(2019, 8, 1, 20, 30),
              "910000000", Status.REPORTED, "0000000001-19-000077",
              Revision(index=0, chain_length=1)),

        # Q4 standalone does not exist. Companies file a 10-K, not a Q4 10-Q.
        # FY minus Q1/Q2/Q3 produces a number nobody filed.
        _fact("fct_A_rev_q4", ENT_A, "revenue", q4, dt(2019, 11, 1, 20, 30),
              None, Status.NOT_REPRESENTABLE, None, reason="no_q4_filing"),

        # ...with the annual and the three filed quarters genuinely available.
        _fact("fct_A_rev_fy", ENT_A, "revenue", q4, dt(2019, 11, 1, 20, 30),
              "3700000000", Status.REPORTED, "0000000001-19-000100",
              Revision(index=0, chain_length=1), span="annual"),

        # B — an honest derived value. `derived` is never silent: the method and
        # the exact input facts are in the response, and the inputs reproduce it.
        _fact("fct_B_rev_h1", ENT_B, "revenue", q2, dt(2019, 5, 3, 20, 30),
              "500000000", Status.REPORTED, "0000000002-19-000021",
              Revision(index=0, chain_length=1), span="year_to_date"),
        _fact("fct_B_rev_q1", ENT_B, "revenue", q1, dt(2019, 2, 4, 20, 30),
              "220000000", Status.REPORTED, "0000000002-19-000011",
              Revision(index=0, chain_length=1)),
        _fact("fct_B_rev_q2", ENT_B, "revenue", q2, dt(2019, 5, 3, 20, 30),
              "280000000", Status.DERIVED, None, Revision(index=0, chain_length=1),
              derived_from=("fct_B_rev_h1", "fct_B_rev_q1")),

        # Three different reasons for a hole; a consumer reasons differently about
        # each — don't ask again / read the filing text / try another source.
        _fact("fct_B_rnd_q2", ENT_B, "rnd_expense", q2, dt(2019, 5, 3, 20, 30),
              None, Status.NOT_DISCLOSED, None, reason="not_broken_out_by_filer"),
        _fact("fct_C_inv_q2", ENT_C, "inventory", q2, dt(2019, 5, 6, 20, 30),
              None, Status.NOT_APPLICABLE, None, reason="concept_does_not_apply_to_bank"),
        _fact("fct_A_rev_2008", ENT_A, "revenue", dt(2008, 12, 27), dt(2009, 2, 2, 20, 30),
              None, Status.NOT_COVERED, None, reason="pre_xbrl"),
        _fact("fct_B_rev_q3", ENT_B, "revenue", q3, dt(2019, 8, 2, 20, 30),
              None, Status.NOT_COVERED, None, reason="custom_taxonomy"),
    ]
    return tuple(sorted(out, key=lambda r: (r.knowable_at, r.id)))


DERIVATION_ARITHMETIC = {
    # Inputs must reproduce the value, or it is a fabrication wearing a status.
    "fct_B_rev_q2": ("fct_B_rev_h1", "-", "fct_B_rev_q1"),
}


@lru_cache(maxsize=None)
def social_records() -> tuple[Record, ...]:
    """Post facts are backfillable (subject to declared deletion survivorship).
    Engagement facts are recorder-only: each is an observation at an instant, with
    knowable_at = observed_at, never a backfilled historical value."""
    out = []
    for i in range(6):
        et = dt(2019, 3, 5, 12 + i)
        out.append(Record(
            id=f"post_{i}", kind="social_post", subject=ENT_A,
            event_time=et, knowable_at=et,
            value={"text": f"post {i}", "author": f"user_{i%3}"},
            status=Status.REPORTED, source_id="social.stream",
            lineage=Lineage(documents=frozenset({f"post_{i}"})),
        ))
        observed = dt(2026, 9, 13, 0, 0)   # sampled by the recorder, today
        out.append(Record(
            id=f"eng_{i}", kind="social_engagement", subject=ENT_A,
            event_time=observed, knowable_at=observed,
            value={"likes": 10 + i, "observed_at": observed.isoformat()},
            status=Status.REPORTED, source_id="social.stream",
            lineage=Lineage(documents=frozenset({f"post_{i}"})),
        ))
    return tuple(sorted(out, key=lambda r: (r.knowable_at, r.id)))


# ── The echo cluster ────────────────────────────────────────────────────────
# One real-world occurrence, surfacing across processes with very different
# relationships to it. This is the case that root-set independence gets WRONG:
# the twelve articles have disjoint lineage documents, so overlap is zero and
# they score as twelve independent legs. They are one.

ECHO_ACCESSION = "0000000001-19-000055"
ECHO_EVENT_AT = dt(2019, 12, 2, 21, 2)   # deliberately clear of every
                                        # observation window: this cluster
                                        # tests independence, not cancellation
ECHO_ARTICLE_COUNT = 12


@lru_cache(maxsize=None)
def echo_cluster() -> tuple[Record, ...]:
    out = [
        # The originating record. There is nothing behind it to appeal to.
        Record(
            id="fil_A_8k_material_agreement", kind="filing", subject=ENT_A,
            event_time=ECHO_EVENT_AT, knowable_at=ECHO_EVENT_AT,
            value={"form": "8-K", "item": "1.01", "accession": ECHO_ACCESSION},
            status=Status.REPORTED, source_id="edgar.filings",
            lineage=Lineage(documents=frozenset({ECHO_ACCESSION})),
        ),
        # A genuinely independent observation of the same occurrence, by a
        # different process with its own originating authority. This is what a
        # second leg actually looks like.
        Record(
            id="reg_A_notice", kind="regulatory_notice", subject=ENT_A,
            event_time=ECHO_EVENT_AT + timedelta(hours=3),
            knowable_at=ECHO_EVENT_AT + timedelta(hours=3),
            value={"register_id": "REG-2019-8841"},
            status=Status.REPORTED, source_id="regulator.register",
            lineage=Lineage(documents=frozenset({"REG-2019-8841"})),
        ),
    ]
    for i in range(ECHO_ARTICLE_COUNT):
        doc = f"art_echo_{i}"
        et = ECHO_EVENT_AT + timedelta(minutes=8 + i * 7)
        out.append(Record(
            id=f"nw_{doc}", kind="news", subject=ENT_A,
            event_time=et, knowable_at=et + lag("news"),
            value={"headline": f"Northwind signs agreement ({i})",
                   "resolution_confidence": 0.98},
            status=Status.REPORTED, source_id="gdelt.news",
            # Disjoint documents — its own article id — but it names what it
            # reports on. Without `reports_on` these read as twelve findings.
            lineage=Lineage(documents=frozenset({doc}),
                            reports_on=frozenset({ECHO_ACCESSION})),
        ))
    return tuple(sorted(out, key=lambda r: (r.knowable_at, r.id)))
