"""OPTIONAL consumer-side heuristic. Not a pipeline stage, and not the data product.

Deciding whether a field "moved" is a judgement, and judgements belong to the
consumer — to strategy derivation, where a model can choose this heuristic, a
different one, or none. It is kept here because it is a useful worked example of
what the data layer's declarations make computable, and because running it
end-to-end proves the data actually arrives in usable shape.

Nothing downstream is required to use it, **no threshold has a default**, and
neither this module nor anything it computes is part of the contract.

Calibration against the null — what replaces a hand-set threshold.

A separation ratio on its own is uninterpretable: it is in units of one
dispersion estimator, over one basis, at one cadence. Comparing it to a constant
someone picked is the worst of both worlds — the constant does not transfer, and
tuning it until the nulls go quiet is fitting the threshold to the control, which
is the data-snooping problem one layer up.

So there is no constant. The null runs give an empirical distribution of
separation *under no structure*, and a field's score is its position against that
distribution. The units become "how often does noise do this", which does
transfer.

Two disciplines the finite null forces, both of them honest:

- **A finite null has finite resolution.** With n samples the smallest reportable
  exceedance is 1/(n+1). The calibration reports that rather than implying a
  precision it does not have.
- **Exceedance is never zero.** The +1 is the standard conservative correction:
  you cannot claim from 400 samples that something never happens.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class NullCalibration:
    samples: tuple[float, ...]
    runs: int
    basis_id: str

    @property
    def n(self) -> int:
        return len(self.samples)

    @property
    def resolution(self) -> float:
        """The smallest exceedance this null can report. Anything below it is
        'beyond what we sampled', not 'impossible'."""
        return 1.0 / (self.n + 1)

    @property
    def ceiling(self) -> float:
        return max(self.samples) if self.samples else 0.0

    def exceedance(self, ratio: float) -> float:
        """Fraction of null separations at least this large, conservatively
        corrected. This is the number that replaces 'is it over 2.0'."""
        at_least = sum(1 for s in self.samples if s >= ratio)
        return (at_least + 1) / (self.n + 1)

    def beyond_null(self, ratio: float) -> bool:
        """Larger than anything the null produced. The strongest statement a
        finite control can support, and it carries `resolution` as its p."""
        return ratio > self.ceiling

    def describe(self) -> str:
        return (f"null[{self.basis_id}] n={self.n} runs={self.runs} "
                f"ceiling={self.ceiling:.2f} resolution={self.resolution:.4f} "
                f"median={statistics.median(self.samples):.2f}")


def build_null_calibration(observe_null, basis_id: str, runs: int = 25) -> NullCalibration:
    """`observe_null(seed)` returns the separation ratios from one null run."""
    samples: list[float] = []
    for seed in range(runs):
        samples.extend(observe_null(seed))
    return NullCalibration(tuple(sorted(samples)), runs, basis_id)


# ── views over an observation, computed at point of use ─────────────────────

def residue(obs, calibration: NullCalibration, alpha: float) -> dict:
    """Residue is a VIEW, computed at point of use, never stored state.

    `alpha` is required and has no default. A default here would be exactly the
    hidden threshold this module exists to avoid — the caller decides its own
    tolerance, or uses `beyond_null` and accepts the control's own resolution.
    """
    return {name: sep for name, sep in obs.separations.items()
            if calibration.exceedance(sep.ratio) <= alpha}


def invariant(obs, calibration: NullCalibration, alpha: float) -> list[str]:
    keep = residue(obs, calibration, alpha)
    return sorted(n for n in obs.separations if n not in keep)


def specificity(obs, calibration: NullCalibration | None = None) -> float:
    """How concentrated the movement is, as a magnitude rather than a count.

    One edge moving while correlated peers held still is a specific, localised
    event; the same edge moving while everything moved is a market-wide shift with
    no attribution. The old form — residue cardinality against invariant
    cardinality — needed a cut to produce those two counts. This one does not: it
    is the concentration of separation mass across the basis, so a field that
    barely moved contributes barely anything instead of flipping a category.

    1.0 = all movement in one field. 0.0 = movement spread evenly.
    """
    ratios = [max(s.ratio, 0.0) for s in obs.separations.values()]
    total = sum(ratios)
    if total <= 0 or len(ratios) < 2:
        return 0.0
    weights = [r / total for r in ratios]
    entropy = -sum(w * math.log(w) for w in weights if w > 0)
    return round(1.0 - entropy / math.log(len(ratios)), 6)
