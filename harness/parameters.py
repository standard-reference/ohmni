"""Parameter rules — the generic half of a generic strategy.

A form that says `separation >= 1.2472` is not generic. That number came from one
window's noise level, and in another regime it means something else entirely.

A form that says `separation >= the 95th percentile of this window's own null` IS
generic: it resolves to a different number in every epoch and to the same
*claim* in all of them. The rule travels; the value does not.

So every parameter in a trade type is one of these, and resolving them is the
"modified slightly to accommodate the specific window" step — done from data
knowable inside that window, never from the epoch the form was derived in.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class UnresolvableParameter(Exception):
    """The window cannot supply what the rule needs. Rejected rather than given a
    default: a default here would silently reintroduce the derivation epoch's
    value into a window that never justified it."""


@dataclass(frozen=True)
class WindowContext:
    """What a window can tell a rule about itself. Everything here is measured
    inside the window, from records knowable within it."""

    epoch_id: str
    null_quantile_fn: Any            # (q: float) -> float, from this window's null
    subject_volatility: float        # the subject's own realised horizon movement
    null_samples: int

    def quantile(self, q: float) -> float:
        return self.null_quantile_fn(q)


@dataclass(frozen=True)
class Rule:
    """A recipe for a number, not the number."""

    kind: str
    params: dict

    def resolve(self, ctx: WindowContext) -> float:
        fn = _RULES.get(self.kind)
        if fn is None:
            raise UnresolvableParameter(f"unknown rule {self.kind!r}")
        return fn(self, ctx)

    def describe(self) -> str:
        return f"{self.kind}({', '.join(f'{k}={v}' for k, v in self.params.items())})"


def _null_quantile(rule: Rule, ctx: WindowContext) -> float:
    """A separation threshold expressed against this window's own null.

    The claim is "further apart than noise gets here 95% of the time", which is
    the same claim in 2019 and 2023 even though the numbers differ by a lot.
    """
    if ctx.null_samples < rule.params.get("min_samples", 100):
        raise UnresolvableParameter(
            f"{ctx.epoch_id}: null has {ctx.null_samples} samples, fewer than the "
            f"{rule.params.get('min_samples', 100)} this rule needs to resolve")
    return ctx.quantile(rule.params["q"])


def _subject_volatility(rule: Rule, ctx: WindowContext) -> float:
    """A magnitude in units of the subject's own realised movement.

    The correction the first historical run forced: an absolute bound is a claim
    about a number, not about the world.
    """
    if ctx.subject_volatility <= 0:
        raise UnresolvableParameter(
            f"{ctx.epoch_id}: subject volatility unmeasurable in this window")
    return rule.params["multiple"] * ctx.subject_volatility


def _constant(rule: Rule, ctx: WindowContext) -> float:
    """For the rare parameter where a constant genuinely is window-independent.
    Kept explicit so that using one is a visible choice rather than a default."""
    return float(rule.params["value"])


_RULES = {
    "null_quantile": _null_quantile,
    "subject_volatility": _subject_volatility,
    "constant": _constant,
}


def null_quantile(q: float, min_samples: int = 100) -> Rule:
    return Rule("null_quantile", {"q": q, "min_samples": min_samples})


def subject_volatility(multiple: float) -> Rule:
    return Rule("subject_volatility", {"multiple": multiple})


def constant(value: float) -> Rule:
    return Rule("constant", {"value": value})
