"""The run manifest — what a run was, recorded so a replay can be checked.

`event_set_hash` spans two independently-versioned products, so the manifest
carries both sides' versions. Without that a data-layer upgrade silently changes
replay results.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime

from contract import (
    CONTRACT_VERSION,
    Capability,
    CapabilitySet,
    Consequence,
    DataLayer,
)

from .potency import POTENCY_VERSION


class HarnessRefusal(Exception):
    """Raised when a layer is missing a capability with no degraded mode. There is
    exactly one: without `knowable_at` on every record there is nothing to gate
    on, so the harness refuses to run rather than running blind."""


@dataclass
class RunManifest:
    layer_id: str
    layer_version: str
    contract_version: str = CONTRACT_VERSION
    potency_version: str = POTENCY_VERSION
    concept_map_version: str | None = None
    cluster_version: str | None = None
    capabilities: frozenset[Capability] = frozenset()
    contaminated: list[str] = field(default_factory=list)
    disabled_features: frozenset[str] = frozenset()
    degradation_notes: list[str] = field(default_factory=list)
    is_null_run: bool = False
    event_count: int = 0
    _digest: str = ""

    @classmethod
    def for_layer(cls, layer: DataLayer) -> "RunManifest":
        caps: CapabilitySet = layer.capabilities()
        if caps.refuses:
            missing = sorted(c.value for c in caps.missing if c in {Capability.KNOWABLE_AT})
            raise HarnessRefusal(
                f"{layer.layer_id} does not provide {missing}; there is nothing to "
                "gate on and no degraded mode exists. Refusing to run."
            )
        m = cls(
            layer_id=layer.layer_id,
            layer_version=layer.layer_version,
            concept_map_version=getattr(layer, "concept_map_version", None),
            cluster_version=getattr(layer, "cluster_version", None),
            capabilities=caps.supported,
            disabled_features=caps.disabled_features(),
            is_null_run="null" in layer.layer_id,
        )
        for d in caps.degradations():
            m.degradation_notes.append(f"{d.capability.value}: {d.without_it}")
            if d.consequence is Consequence.CONTAMINATED:
                # Marked contaminated rather than quietly weaker. The limitation is
                # recorded and attributable, never silent.
                m.contaminated.append(d.capability.value)
        return m

    @property
    def is_contaminated(self) -> bool:
        return bool(self.contaminated)

    def feature_enabled(self, name: str) -> bool:
        return name not in self.disabled_features

    def event_set_hash(self) -> str:
        payload = json.dumps({
            "layer_id": self.layer_id, "layer_version": self.layer_version,
            "contract_version": self.contract_version,
            "potency_version": self.potency_version,
            "concept_map_version": self.concept_map_version,
            "cluster_version": self.cluster_version,
            "capabilities": sorted(c.value for c in self.capabilities),
            "digest": self._digest, "event_count": self.event_count,
        }, sort_keys=True)
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()

    def absorb(self, event_id: str, knowable_at: datetime) -> None:
        self.event_count += 1
        self._digest = hashlib.sha256(
            f"{self._digest}|{event_id}|{knowable_at.isoformat()}".encode()
        ).hexdigest()
