"""SourceDeclaration — what a source says about itself.

Every field here exists because some specific contamination is undetectable
without it. The declaration is the enforcement point: a source that cannot
declare availability cannot be honestly backfilled.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum


class Retrieval(str, Enum):
    AS_OF = "as_of"          # historical values queryable as they stood
    SNAPSHOT = "snapshot"    # a historical query returns the PRESENT value


class Survivorship(str, Enum):
    COMPLETE = "complete"
    DELETIONS_UNRECOVERABLE = "deletions_unrecoverable"


class MeasurementType(str, Enum):
    MEASURED = "measured"
    MODELED = "modeled"


class PluginTrust(str, Enum):
    CERTIFIED = "certified"     # we wrote and audit it
    CONFORMANT = "conformant"   # passes the full suite; structural, not social
    DECLARED = "declared"       # registers but skips/fails checks; excluded from substance_only


@dataclass(frozen=True)
class Coupling:
    """A declared structural fact, not an estimate.

    Options and spot on one underlying have disjoint lineage and distant
    provenance yet are mechanically coupled through delta. Neither root sets nor
    provenance embeddings catch that; only this declaration does.

    `instrument` is set where one source carries contracts with different
    exposures — a prediction market on "AAPL above $200" is delta-coupled to AAPL
    spot; one on "Fed cuts in March" is coupled to rates and to no equity at all.
    """

    subject: str
    strength: float
    instrument: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError(f"coupling strength must be in [0,1], got {self.strength}")


class Dimension(str, Enum):
    """What kind of quantity this is. Half the field algebra falls out of it."""

    MONETARY_FLOW = "monetary_flow"
    MONETARY_STOCK = "monetary_stock"
    COUNT = "count"
    RATE = "rate"
    RATIO = "ratio"
    PROBABILITY = "probability"
    INDEX = "index"
    SHARE_COUNT = "share_count"
    PRICE_PER_SHARE = "price_per_share"
    DURATION = "duration"


class Aggregation(str, Enum):
    """The cheapest error-preventer available. Models get these wrong routinely
    and no API currently tells them which applies."""

    ADDITIVE = "additive"                  # sum over periods is valid
    AVERAGEABLE = "averageable"            # mean valid, sum is not
    WEIGHTED_AVERAGE = "weighted_average"  # mean requires weight_field
    POINT_IN_TIME = "point_in_time"        # neither; take the endpoint
    NON_AGGREGABLE = "non_aggregable"      # no temporal aggregation is meaningful


class TemporalType(str, Enum):
    INSTANT = "instant"      # balance-sheet facts, quotes
    DURATION = "duration"    # income and cash-flow facts, windowed rates


class Phenomenon(str, Enum):
    """What a record is a record OF.

    Declared, versioned, never inferred. A phenomenon asserts that its members
    measure one underlying quantity; it does NOT assert that they agree, correlate
    or are interchangeable.
    """

    CORPORATE_DISCLOSURE = "corporate_disclosure"
    EXCHANGE_ACTIVITY = "exchange_activity"
    OFF_EXCHANGE_ROUTING = "off_exchange_routing"
    INFORMATION_SEEKING = "information_seeking"
    EDITORIAL_PUBLICATION = "editorial_publication"
    RETAIL_DISCOURSE = "retail_discourse"
    REGULATORY_ACTION = "regulatory_action"
    AGGREGATED_BELIEF = "aggregated_belief"


class TruthRole(str, Enum):
    """A record's relationship to the phenomenon it is a record of.

    **Not an accuracy score, and never a judgement about whether a claim is
    correct.** A post asserting something false is still a *constitutive* record
    of retail discourse: the discourse happened, it propagated, and that is the
    fact being recorded. Whether the claim inside it corresponds to the world is a
    question the data layer does not ask and cannot answer — the harness reasons,
    the layer records.

    Potency is therefore always relative to a phenomenon. The same post is
    CONSTITUTIVE of retail discourse and ECHOED with respect to corporate
    disclosure, and it is only the second reading that makes it weak evidence.
    """

    CONSTITUTIVE = "constitutive"   # the record IS the phenomenon: a post, a trade, a filing
    ATTESTED = "attested"           # a party to the phenomenon states it: a press release
    OBSERVED = "observed"           # a third party measured it: pageview counts
    REPORTED = "reported"           # someone not party to it reports on it: journalism
    ECHOED = "echoed"               # re-publication of someone else's record: repost, aggregator
    DERIVED = "derived"             # computed from other records; inherits, never gains


#: Structural, not numeric: an ECHOED or DERIVED record must name what it came
#: from. This is a property of the declaration itself — readable from the
#: document, checkable by conformance — and carries no weighting with it.
ROLE_PRESUPPOSES_PRIOR = frozenset({TruthRole.ECHOED, TruthRole.DERIVED})


@dataclass(frozen=True)
class Quantity:
    dimension: Dimension
    unit: str
    aggregation: Aggregation
    temporal_type: TemporalType
    weight_field: str | None = None
    denominator_rule: str | None = None      # e.g. "period_average" for stock denominators
    polarity: str | None = None


@dataclass(frozen=True)
class Emission:
    """What a source emits, declared by the source itself.

    This exists so that nothing downstream maintains a parallel table of what each
    source produces. Cadence, availability lag, value location and field algebra
    are all read from here. A consumer that hardcodes any of them has a second
    place to be wrong, and the two will drift.

    `emission_matches_output` in the conformance suite is what makes this
    trustworthy: a declaration nobody checks is documentation, not ground truth.
    """

    kind: str                              # the neutral Record.kind this produces
    quantity: Quantity
    native_cadence: str                    # ISO-8601 duration, or "irregular"
    records_of: Phenomenon = Phenomenon.EDITORIAL_PUBLICATION   # what it is a record OF
    role: TruthRole = TruthRole.CONSTITUTIVE                    # its relation to that
    value_field: str | None = None         # key in Record.value holding the number;
                                           # None means this kind carries no scalar
    publication_lag: timedelta | None = None   # floor on knowable_at - event_time
    subject_type: str = "entity"           # "entity" | "instrument"
    carries_period: bool = False           # describes a closed period, not an instant

    @property
    def is_irregular(self) -> bool:
        return self.native_cadence == "irregular"


#: Ordering used to resolve the coarsest common cadence. Disaggregating coarse to
#: fine is fabrication, so resolution is always the coarsest, never the finest.
_CADENCE_RANK = {
    "PT1M": 1, "PT15M": 2, "PT1H": 3, "P1D": 4, "P7D": 5, "P1M": 6, "P3M": 7,
    "P1Y": 8, "irregular": 0,
}


def coarsest(cadences) -> str | None:
    known = [c for c in cadences if c in _CADENCE_RANK and c != "irregular"]
    if not known:
        return None
    return max(known, key=lambda c: _CADENCE_RANK[c])


def cadence_rank(cadence: str | None) -> int | None:
    return _CADENCE_RANK.get(cadence) if cadence else None


@dataclass(frozen=True)
class SourceDeclaration:
    source_id: str
    measurement_process: str          # prose; the provenance-embedding input
    retrieval: Retrieval
    record_survivorship: Survivorship
    backfilled: bool
    measurement_type: MeasurementType = MeasurementType.MEASURED
    emits: tuple[Emission, ...] = ()
    couples_to: tuple[Coupling, ...] = ()
    plugin_trust: PluginTrust = PluginTrust.CERTIFIED

    def __post_init__(self) -> None:
        object.__setattr__(self, "couples_to", tuple(self.couples_to))
        object.__setattr__(self, "emits", tuple(self.emits))

    @property
    def native_cadence(self) -> str | None:
        """Derived from the emissions, never stored twice. A source emitting at
        several cadences (EDGAR: quarterly fundamentals, irregular 8-Ks) resolves
        to the coarsest, because that is the only honest common resolution."""
        if not self.emits:
            return None
        if any(not e.native_cadence for e in self.emits):
            return None
        return coarsest(e.native_cadence for e in self.emits) or "irregular"

    def emission(self, kind: str) -> Emission | None:
        return next((e for e in self.emits if e.kind == kind), None)

    @property
    def has_honest_history(self) -> bool:
        """A stream that is both snapshot and deletions-unrecoverable has no
        honest historical mode at all. The API must refuse a historical as_of
        query against it rather than serve contaminated values."""
        return not (
            self.retrieval is Retrieval.SNAPSHOT
            and self.record_survivorship is Survivorship.DELETIONS_UNRECOVERABLE
        )

    def coupling_to(self, subject: str, instrument: str | None = None) -> float:
        """Strongest declared coupling to `subject`. Instrument-level declarations
        win over source-level ones for the instrument they name."""
        best = 0.0
        for c in self.couples_to:
            if c.subject != subject:
                continue
            if c.instrument is not None and c.instrument != instrument:
                continue
            best = max(best, c.strength)
        return best


class AmbiguousKind(Exception):
    """Two sources emit the same kind and the caller did not say which it meant.
    Silently picking one is how a vendor price quietly substitutes for an exchange
    print, so this raises instead."""


@dataclass
class SourceRegistry:
    """Everything about a source, read from the source's own declaration.

    Built once from `layer.sources()`. Nothing downstream keeps its own table of
    what each source emits, what it costs in publication lag, or how its values
    aggregate — those questions are answered here, from the declaration.
    """

    declarations: tuple[SourceDeclaration, ...]

    def __post_init__(self) -> None:
        self.declarations = tuple(self.declarations)
        self._by_id = {d.source_id: d for d in self.declarations}

    @classmethod
    def from_layer(cls, layer) -> "SourceRegistry":
        return cls(tuple(layer.sources()))

    def source(self, source_id: str) -> SourceDeclaration | None:
        return self._by_id.get(source_id)

    def emitters(self, kind: str) -> tuple[tuple[SourceDeclaration, Emission], ...]:
        """Every (source, emission) pair producing this kind. Plural on purpose:
        two price vendors emitting `price` is legitimate, and collapsing them is not."""
        return tuple((d, e) for d in self.declarations for e in d.emits if e.kind == kind)

    def resolve(self, kind: str, source_id: str | None = None) -> tuple[SourceDeclaration, Emission]:
        hits = self.emitters(kind)
        if source_id is not None:
            hits = tuple(h for h in hits if h[0].source_id == source_id)
        if not hits:
            raise KeyError(f"no declared emission for kind={kind!r} source={source_id!r}")
        if len(hits) > 1:
            raise AmbiguousKind(
                f"kind={kind!r} is emitted by "
                f"{[d.source_id for d, _ in hits]}; name the source")
        return hits[0]

    def emission_for(self, record) -> Emission | None:
        d = self._by_id.get(record.source_id)
        return d.emission(record.kind) if d else None

    def declared_lag(self, kind: str, source_id: str | None = None) -> timedelta | None:
        return self.resolve(kind, source_id)[1].publication_lag

    def quantity(self, kind: str, source_id: str | None = None) -> Quantity:
        return self.resolve(kind, source_id)[1].quantity

    def kinds(self) -> frozenset[str]:
        return frozenset(e.kind for d in self.declarations for e in d.emits)

    def dishonest_history_sources(self) -> tuple[SourceDeclaration, ...]:
        return tuple(d for d in self.declarations if not d.has_honest_history)
