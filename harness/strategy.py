"""Trade types and strategies — generic forms, never a single disposable thesis.

A trade type has two halves, and keeping them apart is the whole design:

- **`TradeTypeCore`** — the invariant identity. The mechanism, the phenomenon that
  must move, the shape it must move in, the phenomena that must hold still, the
  sign and the horizon. This is what makes a form in 2019 and a form in 2023 the
  SAME form rather than two coincidences, and it is the only thing that crosses an
  epoch boundary.
- **Parameter rules** — recipes, not numbers. "Separation above this window's own
  95th-percentile null" resolves differently in every epoch and means the same
  thing in all of them. A stored threshold would carry its derivation window with
  it into periods that never justified it.

Resolving the rules against a window is the "modified slightly to accommodate the
specific window" step, and it is done from data knowable inside that window.

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
from .parameters import Rule, WindowContext, null_quantile, subject_volatility
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
class TradeTypeCore:
    """The invariant identity of a form. Two derivations in different epochs are
    the same form exactly when these match.

    Deliberately holds no numbers that came from data: every quantity here is
    either a declared structural choice (which phenomena, which shape) or a rule
    for deriving a number inside whatever window the form is applied to.
    """

    mechanism_template: str
    trigger_phenomenon: str
    required_shape: str
    required_invariant_phenomena: tuple[str, ...]
    sign: str
    horizon_frames: int
    separation_rule: Rule
    magnitude_rule: Rule
    regime_scope: str

    @property
    def id(self) -> str:
        return f"core_{self.mechanism_template}"

    def identity(self) -> tuple:
        """What must match for two derivations to count as a replication rather
        than two unrelated findings."""
        return (self.mechanism_template, self.trigger_phenomenon, self.required_shape,
                tuple(sorted(self.required_invariant_phenomena)), self.sign,
                self.horizon_frames, self.separation_rule.kind,
                self.magnitude_rule.kind)

    def describe(self) -> str:
        return (f"{self.mechanism_template}: {self.trigger_phenomenon} moves "
                f"{self.required_shape} while "
                f"{', '.join(sorted(self.required_invariant_phenomena))} hold; "
                f"{self.sign} over {self.horizon_frames} frames; "
                f"separation={self.separation_rule.describe()}, "
                f"magnitude={self.magnitude_rule.describe()}")


@dataclass(frozen=True)
class TradeType:
    """A core, resolved against one window.

    Entity-agnostic by construction. If an entity id or a date appears in here,
    the form has collapsed into an instance — `is_generic()` checks it.
    """

    id: str
    core: TradeTypeCore
    resolved_in: str                  # the epoch whose data supplied the numbers
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
                           if k not in ("id", "spark_ref", "provenance",
                                        "resolved_in", "core")}, default=str)
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


def core_from(spark, field_phenomena) -> TradeTypeCore:
    """The invariant half, read off the mechanism template.

    No numbers from this window cross into it — only rules. That is what lets the
    same core be derived independently in another epoch and recognised as the
    same form.
    """
    mech = spark.principles["mechanism"].payload
    tpl = mech.template
    return TradeTypeCore(
        mechanism_template=tpl.id,
        trigger_phenomenon=field_phenomena[mech.trigger_field].value,
        required_shape=mech.trigger_shape,
        required_invariant_phenomena=tuple(sorted(
            p.value for p in tpl.requires_invariant)),
        sign=tpl.sign.value,
        horizon_frames=tpl.horizon_frames,
        # Recipes, not values. Both resolve against whatever window the form is
        # applied in, never against the window it was derived in.
        separation_rule=null_quantile(q=0.95),
        magnitude_rule=subject_volatility(multiple=tpl.magnitude_vol_multiple),
        regime_scope=tpl.regime_scope,
    )


def resolve_trade_type(core: TradeTypeCore, ctx: WindowContext, *, spark_ref: str,
                       basis, field_of_phenomenon: dict, support_total: float,
                       degraded_multiplier: float, support_scale: float,
                       provenance: dict) -> TradeType:
    """Apply a core to one window: resolve every rule from that window's own data.

    This is the step the previous design skipped. Before, a threshold measured in
    one epoch travelled unchanged into every other one — which is a fit to the
    derivation window however carefully the entity ids were kept out of the form.
    """
    if core.required_shape in UNCOMPILABLE_SHAPES:
        raise NotCompilable(f"{core.required_shape}: "
                            f"{UNCOMPILABLE_SHAPES[core.required_shape]}")
    if core.required_shape not in COMPILABLE_SHAPES:
        raise NotCompilable(f"{core.required_shape}: no declared predicate")

    separation = core.separation_rule.resolve(ctx)
    magnitude = core.magnitude_rule.resolve(ctx)
    stance = {"positive": "long", "negative": "short"}.get(core.sign, "abstain")
    trigger_field = field_of_phenomenon[core.trigger_phenomenon]

    entry = {
        "residue_field": trigger_field,
        "residue_phenomenon": core.trigger_phenomenon,
        "required_shape": core.required_shape,
        "predicate": COMPILABLE_SHAPES[core.required_shape],
        "separation_rule": core.separation_rule.describe(),
        "min_separation": round(separation, 6),
        "required_invariant_phenomena": list(core.required_invariant_phenomena),
        "derived_from": "spark.principles.observation",
    }
    horizon_days = basis.frame_span.days * core.horizon_frames
    direction = {
        "stance": stance, "sign": core.sign,
        "magnitude_rule": core.magnitude_rule.describe(),
        "target_magnitude": round(magnitude, 6),
        "horizon_days": horizon_days,
        "derived_from": "spark.principles.mechanism.predicted_effect",
    }
    exit_rule = {
        "on_degraded": f"scale position to {degraded_multiplier}",
        "on_invalidated": "exit",
        "on_horizon": "close and resolve the registered prediction",
        "derived_from": "spark.principles.invalidation",
    }
    sizing = {
        "base": 0.0 if stance == "abstain" else 1.0,
        "support_multiplier": round(min(1.0, (support_total or 0.0) / support_scale), 4),
        "degraded_multiplier": degraded_multiplier,
        "derived_from": "spark.principles.corroboration.accumulated_support",
    }
    universe = {
        "requires_basis_fields": [trigger_field],
        "requires_phenomena": sorted(
            {core.trigger_phenomenon} | set(core.required_invariant_phenomena)),
        "basis_id": basis.id,
        "basis_version": basis.version,
    }
    return TradeType(
        id=f"tt_{core.mechanism_template}", core=core, resolved_in=ctx.epoch_id,
        spark_ref=spark_ref, stance=stance, entry=entry, direction=direction,
        exit=exit_rule, sizing=sizing, universe=universe,
        regime_scope=core.regime_scope, provenance=provenance)


def compile_trade_type(spark, observation, moved: dict, invariant: list[str],
                       field_phenomena: dict, support, basis, ctx: WindowContext,
                       degraded_multiplier: float, support_scale: float) -> TradeType:
    """Derive a core from a spark and resolve it against the window it came from."""
    mech = spark.principles["mechanism"].payload
    core = core_from(spark, field_phenomena)
    return resolve_trade_type(
        core, ctx, spark_ref=spark.id, basis=basis,
        field_of_phenomenon={v.value: k for k, v in field_phenomena.items()},
        support_total=support.total, degraded_multiplier=degraded_multiplier,
        support_scale=support_scale,
        provenance={"mechanism_template": mech.template.id,
                    "specificity": getattr(mech, "specificity", None),
                    "support": support.total,
                    "legs": [l.source_id for l in support.legs],
                    "derived_in": ctx.epoch_id})


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
