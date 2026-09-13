"""Trade types and strategies — generic forms, never a single disposable thesis.

The distinction this module exists to enforce:

- A **single-trade thesis** is "buy this name on this date because this spiked".
  It burns a historical window for one data point, cannot be replicated, and
  produces exactly one Brier score. It is not built here.
- A **TradeType** is a parameterised, *entity-agnostic* form: the conditions are
  expressed over basis fields and phenomena, never over an entity or a date. That
  is what lets the same form fire across a universe, which is what makes
  cross-sectional replication evidence rather than anecdote.
- A **StrategySpec** composes trade types over a declared universe, with sizing
  wired to the invalidation state machine and a declared regime scope.

`compile()` is mechanical because the inputs are structured: observation residue
becomes the entry predicate, the mechanism's predicted effect becomes direction
and horizon, the invalidation state machine becomes exit and sizing, and
accumulated support feeds sizing without gating it.

Every compiled field carries `derived_from`, which is what lets a critique check
a compiled strategy against its source claims mechanically instead of trusting
that the translation was faithful.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from contract import Phenomenon

from .claims import Sign
from .registry import KindRegistration, Registry


class NotCompilable(Exception):
    """A residue shape with no deterministic predicate. Named rather than
    approximated: silently compiling a shape you cannot express produces a rule
    that does not implement the claim it cites."""


#: Which residue shapes have a deterministic predicate, and what it is. The open
#: question is which shapes are expressible at all; the honest answer is a
#: declared table plus a refusal for everything else, never a silent fallback.
COMPILABLE_SHAPES = {
    "step": "latest frame separated from baseline and held for >= 1 further frame",
    "monotonic_ramp": "separation increasing across >= 3 consecutive frames",
    "spike_and_return": ("peak frame separated from baseline, latest frame back "
                         "within dispersion of baseline"),
}
UNCOMPILABLE_SHAPES = {
    "oscillation": ("no stable predicate: sign changes make entry timing "
                    "path-dependent on the frame grid"),
    "flat": "nothing to trigger on",
}


@dataclass(frozen=True)
class TradeType:
    """Entity-agnostic by construction. If an entity id or a date appears in
    here, the form has collapsed into an instance — `is_generic()` checks it."""

    id: str
    spark_ref: str
    stance: str                       # "long" | "short" | "abstain"
    entry: dict
    direction: dict
    exit: dict
    sizing: dict
    universe: dict
    regime_scope: str
    provenance: dict

    def is_generic(self, forbidden_literals: tuple[str, ...]) -> tuple[bool, list[str]]:
        """No entity id, instrument id or date may appear anywhere in the form."""
        blob = json.dumps({k: v for k, v in asdict(self).items()
                           if k not in ("id", "spark_ref", "provenance")})
        found = [lit for lit in forbidden_literals if lit and lit in blob]
        return (not found), found


@dataclass
class StrategySpec:
    id: str
    kind: str
    trade_types: list[TradeType] = field(default_factory=list)
    universe: list[str] = field(default_factory=list)
    status: str = "draft"
    attributes: dict = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyKind(KindRegistration):
    compile: object = None


Strategies: Registry[StrategyKind] = Registry("StrategyKinds")


def compile_trade_type(spark, observation, moved: dict, invariant: list[str],
                       field_phenomena: dict, support, basis,
                       degraded_multiplier: float, support_scale: float) -> TradeType:
    """Mechanical mapping from the spark's own principles.

    `degraded_multiplier` and `support_scale` are required. Hysteresis converts
    false-kills into slow-kills, so a genuinely dead thesis bleeds for N windows —
    that trade is only acceptable if `degraded` cuts size aggressively rather than
    cosmetically, and the multiplier is the number that decides which.
    """
    mech = spark.principles["mechanism"].payload
    predicted = mech.predicted
    trigger_field = mech.trigger_field
    shape = mech.trigger_shape

    if shape in UNCOMPILABLE_SHAPES:
        raise NotCompilable(f"{shape}: {UNCOMPILABLE_SHAPES[shape]}")
    if shape not in COMPILABLE_SHAPES:
        raise NotCompilable(f"{shape}: no declared predicate")

    stance = {"positive": "long", "negative": "short"}.get(predicted.sign.value, "abstain")

    entry = {
        # Named by BASIS FIELD and PHENOMENON, never by entity. The same predicate
        # evaluates against any entity whose basis is covered.
        "residue_field": trigger_field,
        "residue_phenomenon": field_phenomena[trigger_field].value,
        "required_shape": shape,
        "predicate": COMPILABLE_SHAPES[shape],
        "min_separation": round(observation.separations[trigger_field].ratio * 0.5, 4),
        "required_invariant_phenomena": sorted(
            p.value for p in mech.template.requires_invariant),
        "derived_from": "spark.principles.observation",
    }
    direction = {
        "stance": stance, "sign": predicted.sign.value,
        "target_magnitude": predicted.magnitude,
        "horizon_days": predicted.horizon.days,
        "derived_from": "spark.principles.mechanism.predicted_effect",
    }
    exit_rule = {
        # The invalidation state machine IS the exit rule; nothing new is authored.
        "on_degraded": f"scale position to {degraded_multiplier}",
        "on_invalidated": "exit",
        "on_horizon": "close and resolve the registered prediction",
        "derived_from": "spark.principles.invalidation",
    }
    sizing = {
        "base": 0.0 if stance == "abstain" else 1.0,
        # Accumulated support is a sizing input, not a gate — not a promotion
        # criterion, but not discarded either.
        "support_multiplier": round(min(1.0, (support.total or 0.0) / support_scale), 4),
        "degraded_multiplier": degraded_multiplier,
        "derived_from": "spark.principles.corroboration.accumulated_support",
    }
    universe = {
        # A coverage requirement, not a list of names. An entity enters the
        # universe by having the basis covered, and leaves when it does not.
        "requires_basis_fields": [trigger_field],
        "requires_phenomena": sorted(
            {field_phenomena[trigger_field].value}
            | {p.value for p in mech.template.requires_invariant}),
        "basis_id": basis.id,
        "basis_version": basis.version,
    }
    return TradeType(
        id=f"tt_{mech.template.id}",
        spark_ref=spark.id, stance=stance, entry=entry, direction=direction,
        exit=exit_rule, sizing=sizing, universe=universe,
        regime_scope=mech.template.regime_scope,
        provenance={"mechanism_template": mech.template.id,
                    "specificity": getattr(mech, "specificity", None),
                    "support": support.total,
                    "legs": [l.source_id for l in support.legs]},
    )


Strategies.register(StrategyKind(
    name="threshold_rule.v1",
    schema_version="1.0.0",
    required_attributes=("trade_types", "universe", "regime_scope"),
    compile=compile_trade_type,
))
Strategies.register(StrategyKind(
    name="model_in_loop.v1",
    schema_version="1.0.0",
    required_attributes=("trade_types", "universe", "regime_scope"),
    # A separate kind, never a fallback mode. Any model-in-loop strategy is
    # benchmarked against its own compiled deterministic approximation; if it does
    # not beat its distillation out of sample, the model contributes nothing but
    # cost and non-determinism and the strategy is demoted to the compiled kind.
))


def build_strategy(spec_id: str, trade_types: list[TradeType],
                   universe: list[str], regime_scope: str) -> StrategySpec:
    kinds = {t.regime_scope for t in trade_types}
    if len(kinds) > 1:
        raise ValueError(f"trade types disagree on regime scope: {kinds}")
    return StrategySpec(
        id=spec_id, kind="threshold_rule.v1", trade_types=list(trade_types),
        universe=list(universe), status="draft",
        attributes={"trade_types": [t.id for t in trade_types],
                    "universe": list(universe), "regime_scope": regime_scope},
    )
