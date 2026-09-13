"""The core pattern: a frozen core contract plus an open, registered kind.

A small frozen core — the fields the deterministic engine depends on — and an
open `kind` declaring the shape and behaviour of everything else. The engine
never branches on kind; it calls through the registration.

**Registries are split along genuine interface differences, not naming.**
`EffectClaimKind.embed()`, `CorroborationKind.check()` and `SparkKind.promotable()`
are not interchangeable, so they live in separate typed stores. One flat map would
let a wrong-kind lookup succeed syntactically and fail deep inside a call. The
opposite choice is right where members genuinely are interchangeable — a plugin
array whose entries all share one interface belongs in one list. Neither is a
universal default.

The top-level vocabulary — Evidence, EffectClaim, Corroboration, Spark,
Invalidation, Strategy — stays fixed and small. Making *which concepts exist*
user-definable was considered and rejected: real invariants (falsifiability,
corroboration-requires-mechanism ordering, no-lookahead) would become optional
data and could be quietly defined away.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Generic, TypeVar


@dataclass(frozen=True)
class Artifact:
    """The frozen core. `attributes` is open, shaped by `kind`."""

    id: str
    kind: str
    schema_version: str
    attributes: dict[str, Any] = field(default_factory=dict)
    #: Versioned in the key and never compared across versions — thresholds
    #: calibrated on one embedder do not transfer to another.
    embeddings: dict[str, tuple[float, ...]] = field(default_factory=dict)

    def embedding(self, space_version: str) -> tuple[float, ...] | None:
        return self.embeddings.get(space_version)


class KindError(Exception):
    pass


@dataclass(frozen=True)
class KindRegistration:
    name: str
    schema_version: str
    required_attributes: tuple[str, ...] = ()

    def validate(self, attributes: dict) -> None:
        missing = [a for a in self.required_attributes if a not in attributes]
        if missing:
            raise KindError(f"{self.name}: missing required attributes {missing}")


K = TypeVar("K", bound=KindRegistration)


class Registry(Generic[K]):
    """Validate-on-registration, so a malformed kind fails at import rather than
    deep inside a run."""

    def __init__(self, label: str):
        self.label = label
        self._kinds: dict[str, K] = {}

    def register(self, kind: K) -> K:
        if kind.name in self._kinds:
            raise KindError(f"{self.label}: {kind.name} already registered")
        self._kinds[kind.name] = kind
        return kind

    def lookup(self, name: str) -> K:
        try:
            return self._kinds[name]
        except KeyError:
            raise KindError(
                f"{self.label}: no kind {name!r}; registered: {sorted(self._kinds)}"
            ) from None

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._kinds))

    def build(self, name: str, artifact_id: str, attributes: dict,
              embeddings: dict | None = None) -> Artifact:
        kind = self.lookup(name)
        kind.validate(attributes)
        return Artifact(id=artifact_id, kind=name, schema_version=kind.schema_version,
                        attributes=attributes, embeddings=embeddings or {})


# ── the typed registries, split by interface ────────────────────────────────

@dataclass(frozen=True)
class EffectClaimKind(KindRegistration):
    embed: Callable[[dict], tuple[float, ...]] | None = None
    rollup: Callable[[dict], tuple[float, ...]] | None = None


@dataclass(frozen=True)
class CorroborationKind(KindRegistration):
    check: Callable[..., dict] | None = None


@dataclass(frozen=True)
class SparkKind(KindRegistration):
    principle_schema: dict[str, dict] = field(default_factory=dict)
    promotable: Callable[..., dict] | None = None


@dataclass(frozen=True)
class InvalidationKind(KindRegistration):
    evaluate: Callable[..., str] | None = None


EffectClaims: Registry[EffectClaimKind] = Registry("EffectClaimKinds")
Corroborations: Registry[CorroborationKind] = Registry("CorroborationKinds")
Sparks: Registry[SparkKind] = Registry("SparkKinds")
Invalidations: Registry[InvalidationKind] = Registry("InvalidationKinds")

ALL_REGISTRIES = (EffectClaims, Corroborations, Sparks, Invalidations)
