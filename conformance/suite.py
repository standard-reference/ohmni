"""The conformance suite.

A plugin — or a whole data layer — cannot emit facts until it passes. This ships
*with* the loader, never after: a plugin system without enforcement spends the
guarantee that is the whole product.

The central asymmetry: a check whose capability the layer does not declare is
SKIPPED, not FAILED. Conformance tests *honesty*, not richness. A layer that
declares less and tells the truth passes; a layer that claims a capability and
does not honour it fails. That is what makes "add your own source and it's still
backtest-safe" a claim rather than a hope.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable

from contract import (
    Capability,
    DataLayer,
    HistoricalQueryRefused,
    Record,
    SourceRegistry,
    Status,
)

UTC = timezone.utc
WIDE = (datetime(1990, 1, 1, tzinfo=UTC), datetime(2030, 1, 1, tzinfo=UTC))


class Outcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class CheckResult:
    id: str
    outcome: Outcome
    detail: str = ""
    rejects: str = ""          # the failure mode this check exists to reject


@dataclass
class ConformanceReport:
    layer_id: str
    results: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures

    @property
    def failures(self) -> list[CheckResult]:
        return [r for r in self.results if r.outcome is Outcome.FAIL]

    @property
    def skipped(self) -> list[CheckResult]:
        return [r for r in self.results if r.outcome is Outcome.SKIP]

    def by_id(self, cid: str) -> CheckResult | None:
        return next((r for r in self.results if r.id == cid), None)

    def failed_ids(self) -> set[str]:
        return {r.id for r in self.failures}

    def summary(self) -> str:
        counts = {o: sum(1 for r in self.results if r.outcome is o) for o in Outcome}
        return (f"{self.layer_id}: {counts[Outcome.PASS]} pass, "
                f"{counts[Outcome.FAIL]} fail, {counts[Outcome.SKIP]} skip")


# ── check registry ──────────────────────────────────────────────────────────
CHECKS: list[tuple[str, Capability | None, str, Callable]] = []


def check(cid: str, requires: Capability | None, rejects: str):
    def deco(fn):
        CHECKS.append((cid, requires, rejects, fn))
        return fn
    return deco


def _sample(layer: DataLayer) -> list[Record]:
    return list(layer.stream(*WIDE, subjects=[]))


# ── the checks ──────────────────────────────────────────────────────────────

@check("declaration_completeness", None,
       "a source that will not say whether its history can be honestly retrieved")
def _declaration_completeness(layer: DataLayer) -> str | None:
    # These three have no degraded mode. They do not describe richness; they
    # describe whether the stream can be backfilled at all, and a source that
    # will not answer cannot be served as history under any capability tier.
    for d in layer.sources():
        missing = [f for f in ("source_id", "retrieval", "record_survivorship")
                   if getattr(d, f, None) in (None, "")]
        if missing:
            return f"{d.source_id or '<unnamed>'} omits {missing}"
        if d.backfilled is None:
            return f"{d.source_id} does not declare whether its history is backfilled"
    return None


@check("measurement_process_declared", Capability.MEASUREMENT_PROCESS,
       "no provenance prose to embed, so 'how independently was this measured' is unanswerable")
def _measurement_process_declared(layer: DataLayer) -> str | None:
    for d in layer.sources():
        if not (d.measurement_process or "").strip():
            return f"{d.source_id} has empty measurement_process"
    return None


@check("cadence_declared", Capability.NATIVE_CADENCE,
       "an undeclared cadence, so a 5-day mechanism off monthly frames stays undetectable")
def _cadence_declared(layer: DataLayer) -> str | None:
    for d in layer.sources():
        if not d.native_cadence:
            return f"{d.source_id} declares no native_cadence"
    return None


@check("availability_present", Capability.KNOWABLE_AT,
       "the one capability with no degraded mode — without it there is nothing to gate on")
def _availability_present(layer: DataLayer) -> str | None:
    for r in _sample(layer):
        if r.knowable_at is None:
            return f"{r.id} has no knowable_at"
    return None


@check("availability_sanity", Capability.KNOWABLE_AT,
       "knowable_at earlier than event_time, or silently equal to period end")
def _availability_sanity(layer: DataLayer) -> str | None:
    for r in _sample(layer):
        if r.knowable_at < r.event_time:
            return f"{r.id} knowable before it happened ({r.knowable_at} < {r.event_time})"
        # A fact describing a closed period is never knowable at the instant the
        # period closes; a 10-Q's period end precedes its filing by weeks.
        if r.value.get("period_end") and r.knowable_at == r.event_time:
            return f"{r.id} knowable_at silently equals period end"
    return None


@check("status_honesty", Capability.TYPED_STATUS,
       "a null value wearing a non-gap status; gaps that cannot be told apart")
def _status_honesty(layer: DataLayer) -> str | None:
    reg = SourceRegistry.from_layer(layer)
    for r in _sample(layer):
        em = reg.emission_for(r)
        vf = em.value_field if em else None
        if vf is None:
            continue                       # this kind declares no scalar
        if r.status.has_value and r.value.get(vf) is None:
            return f"{r.id} status={r.status.value} but carries no {vf}"
        if r.status.is_gap and r.value.get(vf) is not None:
            return f"{r.id} status={r.status.value} but carries a value"
        if r.status.is_gap and not r.value.get("reason"):
            return f"{r.id} is a gap with no reason"
    return None


def _value_field(layer: DataLayer, r: Record) -> str | None:
    """Which key carries this record's number — answered by the emitting source's
    own declaration. Nothing here keeps a list of which kinds have values."""
    return SourceRegistry.from_layer(layer).emission_for(r) and \
        SourceRegistry.from_layer(layer).emission_for(r).value_field


@check("no_fabrication", Capability.LINEAGE_COUPLING,
       "a value nobody filed, and a derived value whose inputs do not reproduce it")
def _no_fabrication(layer: DataLayer) -> str | None:
    reg = SourceRegistry.from_layer(layer)
    by_id = {r.id: r for r in _sample(layer)}
    for r in by_id.values():
        em = reg.emission_for(r)
        vf = em.value_field if em else None
        if r.status is Status.REPORTED and vf and not r.lineage.documents:
            # A filed value names its filing. A computed one that claims to be
            # filed cannot, which is the tell.
            return f"{r.id} is reported but names no source document"
        if r.status is Status.DERIVED and not r.lineage.derived_from:
            return f"{r.id} is derived but lists no inputs"
        if r.status is Status.DERIVED and vf and r.lineage.derived_from:
            inputs = [by_id.get(i) for i in r.lineage.derived_from]
            if any(i is None for i in inputs):
                return f"{r.id} names inputs that are not served"
            if all(str(i.value.get(vf, "")).lstrip("-").isdigit() for i in inputs):
                got = int(inputs[0].value[vf]) - sum(int(i.value[vf]) for i in inputs[1:])
                if str(got) != r.value[vf]:
                    return (f"{r.id} inputs do not reproduce the value "
                            f"({got} != {r.value[vf]})")
    return None


@check("restatement_as_of", Capability.REVISION_CHAINS,
       "restatements overwritten rather than chained — honest timestamp, wrong value")
def _restatement_as_of(layer: DataLayer) -> str | None:
    chained = [r for r in _sample(layer)
               if r.revision is not None and r.revision.chain_length > 1]
    if not chained:
        return ("layer declares revision chains but serves none; a restatement "
                "cannot be distinguished from a first print")
    head = next(r for r in chained if r.revision.index == 0)
    later = next(r for r in chained
                 if r.revision.index > 0 and r.value.get("period_end") == r.value.get("period_end"))
    before = layer.query(head.subject, head.kind, WIDE,
                         as_of=later.knowable_at - timedelta(seconds=1))
    after = layer.query(head.subject, head.kind, WIDE, as_of=later.knowable_at)
    b = _amount_for(before, head), _amount_for(after, head)
    if b[0] is None or b[1] is None:
        return f"period vanished across the restatement boundary: {b}"
    if b[0] == b[1]:
        return (f"as_of before and after the amendment both return {b[0]} — "
                "the original print is not recoverable")
    return None


def _amount_for(records: list[Record], like: Record) -> str | None:
    for r in records:
        if (r.value.get("concept") == like.value.get("concept")
                and r.value.get("period_end") == like.value.get("period_end")
                and r.value.get("span") == like.value.get("span")):
            return r.value.get("amount")
    return None


@check("stream_ordering", Capability.KNOWABLE_AT,
       "a stream ordered by event_time — every record honest, the sequence not")
def _stream_ordering(layer: DataLayer) -> str | None:
    prev = None
    for r in layer.stream(*WIDE, subjects=[]):
        if prev is not None and r.knowable_at < prev:
            return f"{r.id} at {r.knowable_at} follows {prev}"
        prev = r.knowable_at
    return None


@check("as_of_enforced", Capability.KNOWABLE_AT,
       "as_of accepted and ignored — the failure the mandatory parameter prevents")
def _as_of_enforced(layer: DataLayer) -> str | None:
    for r in _sample(layer)[:400]:
        if r.kind in ("social_post", "social_engagement"):
            continue
        got = layer.query(r.subject, r.kind, WIDE,
                          as_of=r.knowable_at - timedelta(seconds=1))
        if any(g.id == r.id for g in got):
            return f"{r.id} served at as_of one second before it was knowable"
    return None


@check("snapshot_refusal", None,
       "serving a snapshot stream as history — wrong in the direction of the future")
def _snapshot_refusal(layer: DataLayer) -> str | None:
    reg = SourceRegistry.from_layer(layer)
    dishonest = reg.dishonest_history_sources()
    if not dishonest:
        return None
    # Which kinds those sources produce is read from their declarations.
    kinds = {e.kind for d in dishonest for e in d.emits}
    kinds -= {e.kind for d in reg.declarations if d.has_honest_history for e in d.emits}
    sample = _sample(layer)
    for kind in sorted(kinds):
        subj = next((r.subject for r in sample if r.kind == kind), None)
        if subj is None:
            continue
        try:
            layer.query(subj, kind, WIDE, as_of=datetime(2019, 6, 15, tzinfo=UTC))
        except HistoricalQueryRefused:
            continue
        return (f"historical as_of against {kind} was served, not refused; "
                "engagement counts on an old post are present-day values")
    return None


@check("normalize_determinism", None,
       "a model, a clock, or an unordered dict anywhere in the substance path")
def _normalize_determinism(layer: DataLayer) -> str | None:
    a = repr(_sample(layer))
    b = repr(_sample(layer))
    if a != b:
        return "two identical streams differ; the run is not replayable"
    return None


@check("coupling_wellformed", Capability.LINEAGE_COUPLING,
       "a coupling declaration that names nothing the layer serves")
def _coupling_wellformed(layer: DataLayer) -> str | None:
    subjects = {r.subject for r in _sample(layer)}
    for d in layer.sources():
        for c in d.couples_to:
            if not 0.0 <= c.strength <= 1.0:
                return f"{d.source_id} declares coupling strength {c.strength}"
            if c.subject not in subjects:
                return f"{d.source_id} couples to unknown subject {c.subject}"
    return None


def run_conformance(layer: DataLayer) -> ConformanceReport:
    caps = layer.capabilities()
    report = ConformanceReport(layer_id=layer.layer_id)
    for cid, requires, rejects, fn in CHECKS:
        if requires is not None and requires not in caps:
            report.results.append(CheckResult(
                cid, Outcome.SKIP,
                f"layer does not declare {requires.value}", rejects))
            continue
        try:
            problem = fn(layer)
        except HistoricalQueryRefused as e:
            problem = None if cid == "snapshot_refusal" else f"unexpected refusal: {e}"
        except Exception as e:                       # a check must never be the crash
            problem = f"{type(e).__name__}: {e}"
        report.results.append(CheckResult(
            cid, Outcome.FAIL if problem else Outcome.PASS, problem or "", rejects))
    return report


@check("emission_matches_output", None,
       "a declaration nobody checks — the source says one thing and emits another")
def _emission_matches_output(layer: DataLayer) -> str | None:
    """This is the check that lets everything downstream trust the declaration
    instead of keeping its own table. Without it, 'the source is the ground truth'
    is an assumption; with it, it is enforced."""
    reg = SourceRegistry.from_layer(layer)
    seen: set[tuple[str, str]] = set()
    for r in _sample(layer):
        seen.add((r.source_id, r.kind))
        decl = reg.source(r.source_id)
        if decl is None:
            return f"{r.id} comes from undeclared source {r.source_id}"
        if decl.emission(r.kind) is None:
            return (f"{r.source_id} emits kind={r.kind!r} but declares "
                    f"{sorted(e.kind for e in decl.emits)}")
    for d in reg.declarations:
        for e in d.emits:
            if (d.source_id, e.kind) not in seen and e.kind in {k for _, k in seen}:
                continue
    return None


@check("lag_honours_declaration", Capability.KNOWABLE_AT,
       "a source whose records arrive sooner than its own declared publication lag")
def _lag_honours_declaration(layer: DataLayer) -> str | None:
    """Where a source declares a publication lag, its records must respect it.

    A source that exposes a real availability field declares no lag and is checked
    against the field itself; a source that declares a lag instead is checked
    against the declaration. Either way the source, not a table elsewhere, is the
    authority.
    """
    reg = SourceRegistry.from_layer(layer)
    for r in _sample(layer):
        em = reg.emission_for(r)
        if em is None or em.publication_lag is None:
            continue
        if r.knowable_at - r.event_time < em.publication_lag:
            return (f"{r.id} from {r.source_id} arrived in "
                    f"{r.knowable_at - r.event_time}, sooner than the declared "
                    f"{em.publication_lag}")
    return None
