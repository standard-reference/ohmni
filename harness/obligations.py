"""What each build stage consumes from the data layer, declared as data.

This is the answer to "can a given data layer feed each phase of the harness?"
run as a computation rather than argued. Point `assess()` at any conforming layer
and it reports, per stage: runnable, degraded (with the named features lost),
contaminated (runs, but labelled), or blocked.

The obligations are stated here once. Tests assert them; they are not restated in
the tests, so there is no second copy to drift.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from contract import DEGRADATION_TABLE, Capability, Consequence

from .manifest import RunManifest


class StageStatus(str, Enum):
    RUNNABLE = "runnable"
    DEGRADED = "degraded"          # runs, a named capability is unavailable
    CONTAMINATED = "contaminated"  # runs, the result is labelled untrustworthy
    BLOCKED = "blocked"            # cannot run at all


@dataclass(frozen=True)
class Stage:
    id: str
    name: str
    bar: str                            # the acceptance bar from the build plan
    requires: tuple[Capability, ...]    # what it reads from the contract


STAGES: tuple[Stage, ...] = (
    Stage(
        "B0", "Bus: sim-clock, lookahead guard, ordering, root-set derivation",
        "Adversarial peek fails by every route; runs hash-reproducible; "
        "nulls destroy cross-stream structure",
        (Capability.KNOWABLE_AT, Capability.LINEAGE_COUPLING),
    ),
    Stage(
        "B1", "Market graph: node types, entity edges, deterministic anomaly detection",
        "Anomaly rate on nulls matches the threshold's expected false-positive rate",
        (Capability.KNOWABLE_AT, Capability.CROSS_REFERENCE),
    ),
    Stage(
        "B2", "Observation: basis, frames, cancellation, residue / invariant / "
              "not-representable",
        "Hand-moved field in residue, all others in invariant; resolution "
        "confidence discounts separation; cadence commensurability enforced",
        (Capability.KNOWABLE_AT, Capability.TYPED_STATUS, Capability.NATIVE_CADENCE),
    ),
    Stage(
        "B3", "Spark slots: mechanism + invalidation, root sets, two-tier alignment",
        "Mechanisms structurally valid and horizon-commensurable; independence "
        "fixtures score correctly",
        (Capability.KNOWABLE_AT, Capability.LINEAGE_COUPLING,
         Capability.MEASUREMENT_PROCESS),
    ),
    Stage(
        "B4", "compile() -> threshold_rule.v1, execution, leak check",
        "Compiled entry matches source residue mechanically; leak check clean",
        (Capability.KNOWABLE_AT, Capability.REVISION_CHAINS),
    ),
    Stage(
        "B5", "Real vs null comparison — the actual first question",
        "Coherent strategies on real data, measurably fewer or weaker on nulls",
        (Capability.KNOWABLE_AT, Capability.TYPED_STATUS, Capability.REVISION_CHAINS,
         Capability.LINEAGE_COUPLING, Capability.NATIVE_CADENCE),
    ),
)


@dataclass(frozen=True)
class StageAssessment:
    stage: Stage
    status: StageStatus
    missing: tuple[Capability, ...]
    lost_features: tuple[str, ...]
    note: str

    @property
    def can_run(self) -> bool:
        return self.status is not StageStatus.BLOCKED


def assess(manifest: RunManifest) -> dict[str, StageAssessment]:
    have = manifest.capabilities
    out: dict[str, StageAssessment] = {}
    for stage in STAGES:
        missing = tuple(c for c in stage.requires if c not in have)
        if not missing:
            out[stage.id] = StageAssessment(stage, StageStatus.RUNNABLE, (), (),
                                            "every declared obligation is met")
            continue
        worst = max((DEGRADATION_TABLE[c].consequence for c in missing),
                    key=lambda c: [Consequence.DISABLE, Consequence.CONTAMINATED,
                                   Consequence.REFUSE].index(c))
        lost: tuple[str, ...] = tuple(sorted(
            f for c in missing for f in DEGRADATION_TABLE[c].disables))
        status = {
            Consequence.REFUSE: StageStatus.BLOCKED,
            Consequence.CONTAMINATED: StageStatus.CONTAMINATED,
            Consequence.DISABLE: StageStatus.DEGRADED,
        }[worst]
        note = "; ".join(DEGRADATION_TABLE[c].without_it for c in missing)
        out[stage.id] = StageAssessment(stage, status, missing, lost, note)
    return out


def report(manifest: RunManifest) -> str:
    lines = [f"{manifest.layer_id} @ contract {manifest.contract_version}"]
    for sid, a in assess(manifest).items():
        detail = f" lost={list(a.lost_features)}" if a.lost_features else ""
        lines.append(f"  {sid}  {a.status.value:13s} {a.stage.name[:46]:46s}{detail}")
    return "\n".join(lines)
