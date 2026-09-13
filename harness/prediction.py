"""Predictions as first-class events — the harness as a pre-registration system.

At promotion, register. At horizon, resolve. That gives a calibration ledger
**independent of PnL**, which is the point: PnL conflates "was the thesis right"
with "was sizing and execution right", and separating them is what lets the
flywheel learn which *reasoning* works rather than which trades won.

**Score only forward, registered, resolved predictions.** Backtests are
admission, not score. That is enforced structurally here rather than remembered:
a prediction whose horizon has already elapsed at registration time cannot be
registered at all.

Predictions are keyed by **trade type**, not by instance. Calibration accrues to
the generic form across every entity it fired on, which is what makes
cross-sectional replication evidence rather than anecdote. A disposable
single-trade thesis produces one Brier score and can never be replicated.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .claims import Sign


class RegistrationRefused(Exception):
    """Raised when a prediction cannot be honestly registered — almost always
    because its horizon has already passed, which would make it a backtest
    wearing a prediction's clothes."""


class ResolutionRefused(Exception):
    """Raised when the data needed to resolve is not yet knowable."""


def probability_from_support(support: float) -> float:
    """Accumulated support is already in log-odds, which is precisely why it was
    accumulated that way: the mapping to a probability is the logistic, with no
    extra calibration constant invented in between."""
    return 1.0 / (1.0 + math.exp(-support))


@dataclass(frozen=True)
class PredictionRegistered:
    id: str
    spark_ref: str
    trade_type_ref: str          # calibration accrues HERE, not to the instance
    subject: str
    sign: Sign
    magnitude: float
    horizon: timedelta
    probability: float
    declared_scope: str
    registered_at: datetime
    resolve_by: datetime
    basis_id: str
    embedding_space_version: str
    concept_map_version: str | None
    layer_id: str
    layer_version: str


@dataclass(frozen=True)
class PredictionResolved:
    prediction_ref: str
    trade_type_ref: str
    realized_move: float
    outcome: int                 # 1 if the claim held, 0 if it did not
    brier: float
    calibration_bucket: int
    resolved_at: datetime
    benchmark: dict | None = None


@dataclass
class Ledger:
    registered: dict[str, PredictionRegistered] = field(default_factory=dict)
    resolved: list[PredictionResolved] = field(default_factory=list)

    def register(self, p: PredictionRegistered) -> PredictionRegistered:
        if p.resolve_by <= p.registered_at:
            raise RegistrationRefused(
                f"{p.id}: resolve_by {p.resolve_by} is not after registration "
                f"{p.registered_at}. A prediction whose horizon has already "
                "elapsed is a backtest; backtests are admission, not score.")
        if p.id in self.registered:
            raise RegistrationRefused(f"{p.id} is already registered; predictions "
                                      "are immutable once made")
        if not 0.0 < p.probability < 1.0:
            raise RegistrationRefused(f"{p.id}: probability {p.probability} is not "
                                      "a live claim")
        self.registered[p.id] = p
        return p

    def resolve(self, prediction_id: str, realized_move: float, at: datetime,
                benchmark: dict | None = None) -> PredictionResolved:
        p = self.registered[prediction_id]
        if at < p.resolve_by:
            raise ResolutionRefused(
                f"{prediction_id}: cannot resolve at {at}, horizon ends {p.resolve_by}")
        outcome = claim_held(p.sign, p.magnitude, realized_move)
        r = PredictionResolved(
            prediction_ref=prediction_id, trade_type_ref=p.trade_type_ref,
            realized_move=round(realized_move, 6), outcome=outcome,
            brier=round((p.probability - outcome) ** 2, 6),
            calibration_bucket=min(9, int(p.probability * 10)),
            resolved_at=at, benchmark=benchmark)
        self.resolved.append(r)
        return r

    # ── scoring ─────────────────────────────────────────────────────────────
    def brier(self, trade_type_ref: str | None = None) -> float | None:
        rows = [r for r in self.resolved
                if trade_type_ref is None or r.trade_type_ref == trade_type_ref]
        return round(statistics.fmean(r.brier for r in rows), 6) if rows else None

    def by_trade_type(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for r in self.resolved:
            g = out.setdefault(r.trade_type_ref, {"n": 0, "brier": [], "hits": 0})
            g["n"] += 1
            g["brier"].append(r.brier)
            g["hits"] += r.outcome
        return {k: {"n": v["n"], "brier": round(statistics.fmean(v["brier"]), 6),
                    "hit_rate": round(v["hits"] / v["n"], 4)}
                for k, v in out.items()}

    def versus_benchmark(self) -> dict:
        """Calibration in isolation answers "are we well calibrated"; it cannot
        answer "are we better than the consensus". Where a market existed on the
        same resolved question, its price at registration is a benchmark — and
        beating its Brier on N resolved questions is a far harder claim than any
        raw calibration figure."""
        scored = [r for r in self.resolved if r.benchmark]
        if not scored:
            return {"n": 0, "note": "no resolved question had a market to score against"}
        ours = statistics.fmean(r.brier for r in scored)
        theirs = statistics.fmean(r.benchmark["brier"] for r in scored)
        return {"n": len(scored), "harness_brier": round(ours, 6),
                "market_brier": round(theirs, 6), "harness_better": ours < theirs}

    def summary(self) -> str:
        b = self.brier()
        return (f"ledger: {len(self.registered)} registered, {len(self.resolved)} resolved"
                + (f", brier={b}" if b is not None else ", nothing scored yet"))


def claim_held(sign: Sign, magnitude: float, realized: float) -> int:
    if sign is Sign.POSITIVE:
        return int(realized >= magnitude)
    if sign is Sign.NEGATIVE:
        return int(realized <= -magnitude)
    return int(abs(realized) <= magnitude)      # a bounded no-move claim
