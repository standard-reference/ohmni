"""Capability tiers and degraded-mode reporting.

A data layer that provides less does not fail — the harness degrades in *known,
recorded* ways. The consequence of each missing capability is DATA, not scattered
conditionals, so the obligations matrix can be tested directly against it.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Capability(str, Enum):
    KNOWABLE_AT = "knowable_at"                   # availability on every record
    TYPED_STATUS = "typed_status"                 # gaps are typed, never null
    REVISION_CHAINS = "revision_chains"           # restatements preserved as a chain
    MEASUREMENT_PROCESS = "measurement_process"   # provenance prose
    LINEAGE_COUPLING = "lineage_coupling"         # derived_from / couples_to
    NATIVE_CADENCE = "native_cadence"             # declared resolution per source
    CROSS_REFERENCE = "cross_reference"           # /relate, event spine


class Consequence(str, Enum):
    REFUSE = "refuse"              # not degradable — the harness will not run
    CONTAMINATED = "contaminated"  # run proceeds, manifest marks it contaminated
    DISABLE = "disable"            # a named downstream feature is unavailable


@dataclass(frozen=True)
class Degradation:
    capability: Capability
    consequence: Consequence
    without_it: str
    disables: tuple[str, ...] = ()


# The table from 02-build-plan §1, as data. Every row is asserted by the
# obligations matrix test: construct a layer missing the capability, run the
# harness, and check the manifest records exactly this.
DEGRADATION_TABLE: dict[Capability, Degradation] = {
    Capability.KNOWABLE_AT: Degradation(
        Capability.KNOWABLE_AT,
        Consequence.REFUSE,
        "No gating possible at all",
    ),
    Capability.TYPED_STATUS: Degradation(
        Capability.TYPED_STATUS,
        Consequence.DISABLE,
        "Gaps are untyped nulls",
        disables=("gap_reason_discrimination",),
    ),
    Capability.REVISION_CHAINS: Degradation(
        Capability.REVISION_CHAINS,
        Consequence.CONTAMINATED,
        "Restatement lookahead undetectable",
    ),
    Capability.MEASUREMENT_PROCESS: Degradation(
        Capability.MEASUREMENT_PROCESS,
        Consequence.DISABLE,
        "No provenance embedding",
        disables=("corroboration_by_independence",),
    ),
    Capability.LINEAGE_COUPLING: Degradation(
        Capability.LINEAGE_COUPLING,
        Consequence.DISABLE,
        "Shared lineage and coupling invisible; independence over-estimated",
        disables=("correlation_cap", "root_set_independence"),
    ),
    Capability.NATIVE_CADENCE: Degradation(
        Capability.NATIVE_CADENCE,
        Consequence.DISABLE,
        "Basis resolution uncheckable",
        disables=("cadence_commensurability",),
    ),
    Capability.CROSS_REFERENCE: Degradation(
        Capability.CROSS_REFERENCE,
        Consequence.DISABLE,
        "No declared relations",
        disables=("mechanism_as_graph_path_bonus",),
    ),
}

NON_NEGOTIABLE = frozenset(
    c for c, d in DEGRADATION_TABLE.items() if d.consequence is Consequence.REFUSE
)


@dataclass(frozen=True)
class CapabilitySet:
    """Declared by the layer, copied into the run manifest, so a run against a
    degraded layer is labelled rather than quietly weaker."""

    supported: frozenset[Capability]

    def __post_init__(self) -> None:
        object.__setattr__(self, "supported", frozenset(self.supported))

    def __contains__(self, cap: object) -> bool:
        return cap in self.supported

    @property
    def missing(self) -> frozenset[Capability]:
        return frozenset(DEGRADATION_TABLE) - self.supported

    @property
    def refuses(self) -> bool:
        return bool(NON_NEGOTIABLE - self.supported)

    def degradations(self) -> tuple[Degradation, ...]:
        return tuple(DEGRADATION_TABLE[c] for c in sorted(self.missing, key=lambda c: c.value))

    def disabled_features(self) -> frozenset[str]:
        out: set[str] = set()
        for d in self.degradations():
            out.update(d.disables)
        return frozenset(out)

    @classmethod
    def full(cls) -> "CapabilitySet":
        return cls(frozenset(DEGRADATION_TABLE))
