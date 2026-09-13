"""B3 — independence: three failure modes, three mechanisms."""
import pytest

from fixtures import design_intent as di
from fixtures.dataset import REGISTRY, echo_cluster, fundamentals, scenario_records
from harness.independence import collapse_to_legs, independence
from harness.potency import PotencyReader

SC = scenario_records("localised")


def of(source_id, records=SC):
    return tuple(r for r in records if r.source_id == source_id)


def test_disjoint_lineage_and_distant_provenance_scores_independent():
    r = independence(of("prices.eod"), fundamentals(), REGISTRY)
    assert r.score == pytest.approx(1.0)
    assert r.binding == "none"


def test_a_derived_signal_is_not_a_second_leg():
    """Vendor enrichment is derived from the article text, so it shares root
    lineage and provenance with the article. The deliberate true-negative."""
    r = independence(of("gdelt.news"), of("sentiment.derived"), REGISTRY)
    assert r.score == pytest.approx(0.0)
    assert r.binding == "lineage"


def test_declared_coupling_catches_what_neither_embedding_can():
    """Options and spot have disjoint lineage and distant provenance yet are
    mechanically coupled through delta. This is the case that fails silently if
    `couples_to` is not wired through the contract."""
    from contract import Lineage, Record, Status
    from fixtures.dataset import INST_OPT_A, dt

    opt = (Record(id="opt_1", kind="options_skew", subject=INST_OPT_A,
                  event_time=dt(2019, 3, 5), knowable_at=dt(2019, 3, 5, 18),
                  value={"skew": 0.12}, status=Status.REPORTED, source_id="options.iv",
                  lineage=Lineage(documents=frozenset({"opt_chain_20190305"}))),)
    r = independence(opt, of("prices.eod"), REGISTRY)
    assert r.lineage_overlap == 0.0, "lineage says independent"
    assert r.declared_coupling == pytest.approx(0.9)
    assert r.score == pytest.approx(0.1)
    assert r.binding == "coupling"


def test_echoes_of_one_filing_are_one_leg_not_twelve():
    """The case root sets alone get WRONG. Twelve articles with disjoint lineage
    documents score as twelve independent legs under overlap alone; they are one
    observation with wide coverage."""
    ec = echo_cluster()
    articles = tuple(r for r in ec if r.kind == "news")
    assert len(articles) == 12
    assert len({d for r in articles for d in r.lineage.documents}) == 12, "disjoint docs"

    r = independence(articles[:1], articles[1:], REGISTRY)
    assert r.lineage_overlap == 0.0, "root sets alone see no overlap"
    assert r.score == pytest.approx(di.ECHO_EXPECTED_INDEPENDENCE)
    assert r.binding == "origin"


def test_the_cluster_collapses_to_its_originating_records():
    legs = collapse_to_legs(echo_cluster(), REGISTRY)
    assert len(legs) == di.ECHO_EXPECTED_LEGS


def test_a_second_process_observing_the_same_event_is_a_real_leg():
    """Contrast with the echoes: the regulator's register is its own originating
    record, so it is genuine corroboration rather than coverage."""
    ec = echo_cluster()
    filing = tuple(r for r in ec if r.kind == "filing")
    notice = tuple(r for r in ec if r.kind == "regulatory_notice")
    assert independence(filing, notice, REGISTRY).score == pytest.approx(1.0)


# ── potency: relative to a phenomenon, never a claim about correctness ──────

def test_a_post_is_a_full_record_of_discourse_and_an_echo_of_earnings():
    """A post asserting something false is still a perfect record of retail
    discourse: the discourse happened and propagated, and that is the fact. It is
    only weak with respect to a different phenomenon."""
    from contract import Phenomenon
    from fixtures.dataset import social_records

    reader = PotencyReader(REGISTRY, social_records())
    post = next(r for r in social_records() if r.kind == "social_post")
    assert reader.potency(post, Phenomenon.RETAIL_DISCOURSE) == 1.0
    assert reader.potency(post, Phenomenon.CORPORATE_DISCLOSURE) == 0.0


def test_silent_is_not_the_same_as_weak():
    """A pageview count is not weak evidence about a bank's loan book; it says
    nothing on it. Three outcomes, and the third must not collapse into the
    others."""
    from contract import Phenomenon

    reader = PotencyReader(REGISTRY, SC)
    pv = next(r for r in SC if r.kind == "pageviews")
    assert reader.potency(pv, Phenomenon.INFORMATION_SEEKING) > 0.5
    assert reader.potency(pv, Phenomenon.CORPORATE_DISCLOSURE) == 0.0


def test_an_echo_carries_some_but_not_full_potency_about_what_it_echoes():
    from contract import Phenomenon

    ec = echo_cluster()
    reader = PotencyReader(REGISTRY, ec)
    article = next(r for r in ec if r.kind == "news")
    filing = next(r for r in ec if r.kind == "filing")
    assert reader.potency(filing, Phenomenon.CORPORATE_DISCLOSURE) == 1.0
    assert 0 < reader.potency(article, Phenomenon.CORPORATE_DISCLOSURE) < 0.5
    assert reader.potency(article, Phenomenon.EDITORIAL_PUBLICATION) == 1.0


def test_a_derivation_is_bounded_by_its_weakest_input():
    """Sentiment scored from an aggregator's copy does not acquire the filing's
    potency because the filing is somewhere upstream."""
    from contract import TruthRole
    from harness.potency import potency_of

    assert potency_of(TruthRole.DERIVED, (1.0, 0.2)) == 0.2
