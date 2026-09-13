"""What this synthetic dataset was BUILT to contain.

Read the name carefully. This is not a reference the data layer validates against
— the layer has no oracle and asserts nothing about correspondence to reality. It
records what was said, by whom, when, and how potent that saying is with respect
to a declared phenomenon. "Is this number correct?" is a question it never asks.

These constants exist because the *fixture* is synthetic: we authored the
generative process, so we know which field we moved. That makes them a legitimate
reference for testing the **harness's computation** — did cancellation find the
field we moved — and for nothing else. No data-layer code imports this module, and
a test asserting a real source's value against a hand-written expectation would be
a category error.

Kept in its own module so the expected answers are never derived from the same
functions under test; otherwise the suite only checks that the code agrees with
itself.
"""
from __future__ import annotations

from .dataset import ENT_A, ENT_B, ENT_C, REVENUE_A_Q2_ORIGINAL, REVENUE_A_Q2_RESTATED, dt

# ── A1: point-in-time correctness on both sides of a restatement ────────────
RESTATEMENT_CASES = [
    # (as_of, expected amount, why)
    (dt(2019, 6, 15), REVENUE_A_Q2_ORIGINAL, "before the amendment was filed"),
    (dt(2019, 10, 30), REVENUE_A_Q2_ORIGINAL, "the day before — still not knowable"),
    (dt(2019, 10, 31, 22, 0), REVENUE_A_Q2_RESTATED, "hours after the amendment"),
    (dt(2020, 1, 1), REVENUE_A_Q2_RESTATED, "long after"),
]

#: Q2 is knowable from 2019-05-01 20:31. One second earlier, nothing.
FIRST_KNOWABLE_A_Q2 = dt(2019, 5, 1, 20, 31)

# ── The typed-gap census. Five states that `null` collapses into one. ───────
EXPECTED_GAPS = {
    "fct_A_rev_q4": ("not_representable", "no_q4_filing"),
    "fct_B_rnd_q2": ("not_disclosed", "not_broken_out_by_filer"),
    "fct_C_inv_q2": ("not_applicable", "concept_does_not_apply_to_bank"),
    "fct_A_rev_2008": ("not_covered", "pre_xbrl"),
    "fct_B_rev_q3": ("not_covered", "custom_taxonomy"),
}

# ── B2: the basis, and what must survive cancellation in each scenario ──────
#
# Three states that must never collapse into one:
#   residue          — separated in at least one frame
#   invariant        — cancelled because indistinguishable within dispersion
#   not_representable— cannot be expressed in this basis at all
#
BASIS_FIELDS = ("pageviews_rate", "price_return", "news_rate", "short_volume_share",
                "revenue_yoy", "options_skew")

EXPECTED_NOT_REPRESENTABLE = {
    # Quarterly into a weekly basis is disaggregation, which is fabrication.
    # Refused, not forward-filled.
    "revenue_yoy": "cadence_incoherent",
    # No options data for this entity — a coverage hole, a different state from
    # "cancelled because indistinguishable".
    "options_skew": "not_covered",
}

#: Kept as ORDERING, not membership. Which fields count as "moved" needs a cut
#: point; which field moved *most* does not, and the ordering is what the fixture
#: was actually built to encode.
EXPECTED_STRONGEST_FIELD = {
    "localised": "pageviews_rate",
    "market_wide": "pageviews_rate",
}

#: Scenarios ordered by how much total separation they should show. No threshold
#: is needed to assert an ordering.
EXPECTED_SEPARATION_ORDER = ["market_wide", "localised", "entity_drift", "quiet"]

_SUPERSEDED_EXPECTED_OBSERVATION = {
    # scenario: (residue fields, invariant fields, expected shape of the residue)
    "localised": (
        {"pageviews_rate"},
        {"price_return", "news_rate", "short_volume_share"},
        "spike_and_return",
    ),
    "market_wide": (
        {"pageviews_rate", "price_return", "news_rate", "short_volume_share"},
        set(),
        "step",
    ),
    # News separates on raw numbers; entity-resolution confidence of 0.55 pulls
    # it back under threshold. Residue that is really entity drift.
    "entity_drift": (
        set(),
        {"pageviews_rate", "price_return", "news_rate", "short_volume_share"},
        None,
    ),
    "quiet": (
        set(),
        {"pageviews_rate", "price_return", "news_rate", "short_volume_share"},
        None,
    ),
}

#: Without the resolution-confidence discount, entity_drift's news_rate separates.
#: The discount is what distinguishes a finding from mis-linked mentions, so the
#: undiscounted result is asserted too — a test that only checks the discounted
#: path would pass against an implementation that ignores confidence entirely.
EXPECTED_UNDISCOUNTED_RESIDUE = {"entity_drift": {"news_rate"}}

#: Residue cardinality against invariant cardinality is the computable
#: specificity measure. One edge moving while peers held is localised; everything
#: moving is a market-wide shift with no attribution.
EXPECTED_SPECIFICITY_ORDER = ["localised", "market_wide"]   # strictly decreasing

# ── B3: the three independence cases ────────────────────────────────────────
#
# The third is the one that fails silently if `couples_to` is not wired through
# the contract — neither embedding catches it.
INDEPENDENCE_CASES = [
    ("prices.eod", "edgar.xbrl", 1.0, "disjoint lineage, distant provenance"),
    ("gdelt.news", "sentiment.derived", 0.0, "sentiment is computed from the article"),
    ("prices.eod", "options.iv", 0.1, "disjoint lineage, declared coupling 0.9"),
]

# ── Cross-entity comparability ──────────────────────────────────────────────
COMPARABLE_PAIRS = [(ENT_A, ENT_B)]
INCOMPARABLE_PAIRS = [(ENT_A, ENT_C), (ENT_B, ENT_C)]   # a bank's revenue is not a manufacturer's

# ── The echo cluster: what the three independence mechanisms must each catch ──
#: Twelve articles with disjoint lineage documents, all echoing one filing. Root
#: sets alone score them as twelve independent legs, which is the quiet failure.
ECHO_EXPECTED_LEGS = 2          # the filing (+ its echoes) and the regulatory notice
ECHO_EXPECTED_INDEPENDENCE = 0.0

#: Availability lag is NOT hand-stated here. Each source declares its own
#: publication lag on its Emission, and the conformance suite checks the records
#: against that declaration. A second table of expected lags would be a second
#: place to be wrong.


# ── The declared basis for the B2 scenarios ─────────────────────────────────
def fixture_basis():
    """Declared up front — field set, resolution, frame count and spacing — before
    anything downstream sees a result. Frame selection is otherwise a snooping
    surface: pick the spacing that makes the residue look strongest and you have
    curve-fit the observation itself."""
    from datetime import timedelta

    from harness.observation import Basis, BasisField

    return Basis(
        id="basis.weekly.attention_v1",
        resolution="P7D",
        frame_count=8,
        frame_span=timedelta(days=7),
        fields=(
            BasisField("pageviews_rate", "wikimedia.pageviews", "pageviews"),
            BasisField("price_return", "prices.eod", "price"),
            BasisField("news_rate", "gdelt.news", "news"),
            BasisField("short_volume_share", "finra.short", "short_volume"),
            # Quarterly into a weekly basis: refused, not forward-filled.
            BasisField("revenue_yoy", "edgar.xbrl", "fundamental"),
            # Declared in the basis, no data for this entity: a coverage hole,
            # which is a different state from "cancelled".
            BasisField("options_skew", "options.iv", "options_skew"),
        ),
    )
