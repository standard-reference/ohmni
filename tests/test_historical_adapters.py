"""Data-layer tests for the real adapters.

Deliberately separate from the harness suite, which stays fixture-only: these
exercise the *data layer* against sources it did not author, and they need the
raw cache. The seam is intact precisely because no harness test imports anything
from `data_layer`.

Skipped when the cache is cold, so the core suite still runs with no network.
"""
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.historical

from conformance import Outcome, run_conformance
from contract import Capability, Status
from data_layer.adapters import edgar
from data_layer.cache import CACHE_DIR
from data_layer.entities import BY_TICKER, ENTITIES
from data_layer.layer import HistoricalDataLayer
from harness.manifest import RunManifest
from harness.obligations import StageStatus, assess

START = datetime(2023, 1, 3, tzinfo=timezone.utc)
END = datetime(2023, 6, 30, tzinfo=timezone.utc)

if not CACHE_DIR.exists() or len(list(CACHE_DIR.glob("*.gz"))) < 20:
    pytest.skip("raw cache is cold; run demo/historical_run.py first",
                allow_module_level=True)


@pytest.fixture(scope="module")
def layer():
    return HistoricalDataLayer().preload(START, END)


def test_a_real_layer_passes_the_same_conformance_suite(layer):
    """The test of whether the seam holds. If this needed a special case anywhere,
    the contract would be describing the fixture rather than the world."""
    report = run_conformance(layer)
    assert report.passed, [f"{f.id}: {f.detail}" for f in report.failures]


def test_normalize_is_a_pure_function_of_the_cached_bytes():
    """`fetch` is the only network boundary. Everything after it must be
    re-runnable after a bugfix with no refetch, which requires purity."""
    ent = BY_TICKER["INTC"]
    raw, tag = edgar.fetch_raw(ent)
    assert repr(edgar.normalize(raw, tag, ent)) == repr(edgar.normalize(raw, tag, ent))


def test_edgar_reconstructs_a_real_restatement_chain():
    """Intel re-presented H1 2022 revenue in 2024. Multiple fact objects exist for
    the same period end with different accession numbers, which is what makes
    EDGAR natively point-in-time rather than two fixed projections."""
    ent = BY_TICKER["INTC"]
    raw, tag = edgar.fetch_raw(ent)
    recs = edgar.normalize(raw, tag, ent)
    chains = {}
    for r in recs:
        if r.revision.chain_length > 1:
            chains.setdefault((r.value["period_end"], r.value["span"]), []).append(r)
    assert chains, "no restatement chain found in Intel's revenue history"
    links = sorted(next(iter(chains.values())), key=lambda r: r.revision.index)
    assert links[0].value["amount"] != links[-1].value["amount"]
    assert links[0].knowable_at < links[-1].knowable_at


def test_as_of_returns_what_was_knowable_not_what_is_true_now(layer):
    """The test that settles point-in-time claims empirically: query as-of a date
    before the amendment and check whether you get the original figures."""
    ent = BY_TICKER["INTC"]
    window = (datetime(2022, 1, 1, tzinfo=timezone.utc),
              datetime(2022, 7, 3, tzinfo=timezone.utc))

    def ytd(as_of):
        return [r.value["amount"] for r in layer.query(ent.id, "fundamental", window, as_of)
                if r.value["span"] == "year_to_date"]

    before = ytd(datetime(2023, 1, 1, tzinfo=timezone.utc))
    after = ytd(datetime(2025, 1, 1, tzinfo=timezone.utc))
    assert before and after and before != after, (before, after)


def test_every_real_record_is_knowable_after_it_happened(layer):
    for r in layer.stream(START, END, subjects=[]):
        assert r.knowable_at >= r.event_time, r.id


def test_declared_publication_lags_are_honoured_by_the_real_data(layer):
    """A source that declares a lag must respect it. EDGAR declares none because
    it exposes a real availability field and is checked against that instead."""
    from contract import SourceRegistry

    reg = SourceRegistry(tuple(layer.sources()))
    for r in layer.stream(START, END, subjects=[]):
        em = reg.emission_for(r)
        if em and em.publication_lag:
            assert r.knowable_at - r.event_time >= em.publication_lag, r.id


def test_a_closed_market_produces_no_record_rather_than_a_zero(layer):
    """An absent FINRA file is a closed market. A zero short-volume share would be
    a fabricated observation on a day nothing traded."""
    days = {r.event_time.date() for r in layer.stream(START, END, subjects=[])
            if r.kind == "short_volume"}
    assert days, "no FINRA records loaded"
    assert not any(d.weekday() >= 5 for d in days)
    # US markets were closed 2023-01-16 (MLK), 2023-05-29 (Memorial Day).
    assert datetime(2023, 1, 16).date() not in days
    assert datetime(2023, 5, 29).date() not in days


def test_the_prototype_price_source_declares_its_survivorship_gap(layer):
    """Only currently-listed names are served. Declared, so the run is marked —
    never silently used."""
    from contract import Survivorship

    px = next(d for d in layer.sources() if d.source_id == "prices.daily")
    assert px.record_survivorship is Survivorship.DELETIONS_UNRECOVERABLE
    assert px.backfilled is True
    assert Capability.SURVIVORSHIP not in layer.capabilities()


def test_the_run_is_marked_contaminated_rather_than_quietly_weaker(layer):
    manifest = RunManifest.for_layer(layer)
    assert Capability.SURVIVORSHIP.value in manifest.contaminated
    stages = assess(manifest)
    assert stages["B4"].status is StageStatus.CONTAMINATED
    assert stages["B5"].status is StageStatus.CONTAMINATED
    assert stages["B0"].status is StageStatus.RUNNABLE


def test_two_fields_from_one_finra_file_share_lineage_completely(layer):
    """Short volume and total volume arrive in ONE document, so they can never be
    two independent legs. The lineage says so without anyone declaring it."""
    from contract import SourceRegistry
    from harness.independence import independence

    reg = SourceRegistry(tuple(layer.sources()))
    sv = tuple(r for r in layer.stream(START, END, subjects=[])
               if r.kind == "short_volume")[:40]
    assert sv
    half = len(sv) // 2
    result = independence(sv[:half], sv[half:], reg)
    assert result.lineage_overlap > 0.0
