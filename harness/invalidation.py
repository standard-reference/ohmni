"""Invalidation — an error-detection bubble, mostly auto-derived.

Three of four child types need no new authoring: the mechanism's predicted
effect, each corroboration's effect claim, and the observation's residue are
already claims with a defined shape. Only a genuinely novel condition needs a
custom leaf.

The asymmetry is intentional: convergence across independent sources to build a
thesis, one *sustained* failure to break it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum


class LeafState(str, Enum):
    INTACT = "intact"
    AMBIGUOUS = "ambiguous"
    BROKEN = "broken"


class ThesisState(str, Enum):
    ACTIVE = "active"
    DEGRADED = "degraded"
    INVALIDATED = "invalidated"


@dataclass
class InvalidationNode:
    id: str
    scope: str                      # concept | mechanism | corroboration | observation
    kind: str
    source_ref: str | None = None
    children: list["InvalidationNode"] = field(default_factory=list)
    windows_below_threshold: int = 0
    hysteresis_n: int = 1
    state: LeafState = LeafState.INTACT
    note: str = ""

    def observe(self, below: bool) -> LeafState:
        """Hysteresis at the leaf, not weights at the root.

        A memoryless tree fires the instant one window dips, which under an
        unweighted OR root makes the whole thing over-twitchy. Requiring *clear*
        to mean *sustained* is how research actually abandons a position.

        The honest cost: this converts false-kills into slow-kills, so a genuinely
        dead thesis bleeds for N windows. That is what makes `degraded` cutting
        size aggressively rather than cosmetically part of the bargain.
        """
        self.windows_below_threshold = self.windows_below_threshold + 1 if below else 0
        if self.windows_below_threshold >= self.hysteresis_n:
            self.state = LeafState.BROKEN
        elif self.windows_below_threshold > 0:
            self.state = LeafState.AMBIGUOUS
        else:
            self.state = LeafState.INTACT
        return self.state


def hysteresis_for(horizon: timedelta, window: timedelta, fraction: float) -> int:
    """N scales to the claim's declared horizon, never a flat constant — a 3-day
    claim and a 6-month claim cannot share a window count.

    `fraction` is required and has no default: it directly controls the
    false-kill / slow-kill trade, and burying it would hide the one number that
    decides how much a dead thesis costs.
    """
    windows = max(1, int(horizon / window))
    return max(1, round(windows * fraction))


def build_tree(spark_id: str, predicted, support, observation_residue: dict,
               hysteresis_n: int, delta_reality_window: timedelta) -> InvalidationNode:
    root = InvalidationNode(id=f"inv_{spark_id}", scope="concept", kind="root.v1")

    root.children.append(InvalidationNode(
        id=f"inv_{spark_id}_mech", scope="mechanism",
        kind="predicted_effect.v1", source_ref=f"pred_{spark_id}",
        hysteresis_n=hysteresis_n,
        note=(f"auto-derived: fires if |realised move in {predicted.subject}| exceeds "
              f"{predicted.magnitude} over {predicted.horizon.days}d")))

    for leg in support.legs:
        root.children.append(InvalidationNode(
            id=f"inv_{spark_id}_{leg.source_id}", scope="corroboration",
            kind="effect_claim.v1", source_ref=leg.id, hysteresis_n=hysteresis_n,
            note=f"auto-derived: fires if {leg.phenomenon.value} stops holding within dispersion"))

    root.children.append(InvalidationNode(
        id=f"inv_{spark_id}_delta", scope="observation",
        kind="delta_reality.v1", hysteresis_n=1,
        note=(f"re-estimate all frames on a {delta_reality_window.days}d sample declared "
              "when the observation was filled, re-run cancellation, fire if the residue "
              "collapses. The window is declared now, not chosen later — otherwise it is "
              "re-testing until failure.")))

    root.children.append(InvalidationNode(
        id=f"inv_{spark_id}_integrity", scope="observation",
        kind="observation_integrity.v1", hysteresis_n=1,
        note="bad print, revision, delisting, feed gap"))

    # Deliberately NO persistence leaf: anomaly decay is anomalies behaving
    # normally, never thesis failure.
    return root


def thesis_state(root: InvalidationNode, k_broken_legs: int) -> ThesisState:
    """`k` is required and has no default — how many broken legs constitutes
    invalidation is a live design question, not something to bury."""
    mech = [c for c in root.children if c.scope == "mechanism"]
    broken = [c for c in root.children if c.state is LeafState.BROKEN]
    ambiguous = [c for c in root.children if c.state is LeafState.AMBIGUOUS]

    if any(c.state is LeafState.BROKEN for c in mech) or len(broken) >= k_broken_legs:
        return ThesisState.INVALIDATED
    if ambiguous or broken:
        return ThesisState.DEGRADED
    return ThesisState.ACTIVE
