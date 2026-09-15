"""The window budget ledger — the one thing a stateless run must NOT forget.

Running each evaluation in a fresh session with no memory gives **reproducibility**.
It does not give **independence**, and the difference is the whole problem.

The snooping surface is the *dataset*, not the session. Consider what actually
happened during this build: a run lost 9 of 9 predictions, the magnitude rule was
changed in response, and the next run scored better. A fresh session would not
remember the first run — but the *code* still contains the fix, and the fix was
derived from that data. The information leaked into the artifact, not the memory.
Forgetting the run does not un-spend the window.

So the thing that must survive across sessions is exactly one thing: **how much
has been spent on each epoch**. Every distinct harness version evaluated against
an epoch consumes budget from it, whether or not anyone remembers doing so.
Because the version is a content hash of the harness source, a change made in
response to a result is automatically counted — which is precisely the case that
is otherwise invisible.

Holdout epochs are sealed with a hard open limit. Once spent, a holdout is no
longer a holdout, and the honest move is to declare it a derivation epoch rather
than keep quoting scores from it.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

LEDGER_PATH = Path(__file__).resolve().parents[1] / ".budget" / "ledger.json"


class BudgetExhausted(Exception):
    """A sealed holdout has been opened as many times as it was declared to allow.

    Not a warning. A holdout consulted an unlimited number of times is a
    derivation set that nobody relabelled, and every score quoted from it after
    that point is admission wearing a score's clothes.
    """


def harness_version(root: Path | None = None) -> str:
    """Content hash of the harness source.

    Deliberately not a hand-maintained version string: the whole point is to
    count changes made in response to results, and those are exactly the changes
    somebody forgets to bump a version for.
    """
    root = root or Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return "h:" + digest.hexdigest()[:16]


@dataclass
class EpochBudget:
    epoch_id: str
    sealed: bool                    # a holdout
    max_opens: int | None           # None = unlimited (derivation epochs)
    opens: list[dict] = field(default_factory=list)

    @property
    def spent(self) -> int:
        """Distinct harness versions evaluated against this epoch. Re-running the
        SAME version costs nothing — that is reproduction, not another test.

        This governs the sealed-holdout cap: it answers "how many times did you
        look". It is NOT the multiple-testing surface — see `evaluations`.
        """
        return len({o["harness_version"] for o in self.opens})

    @property
    def evaluations(self) -> int:
        """How many (window, entity) pairs were actually tested here.

        A distinct quantity from `spent`, and the one a deflated-Sharpe
        correction consumes. One harness version against one epoch is one *look*
        but can be a hundred and sixty *tests*, and charging a single unit for
        the lot undercounts precisely the multiple testing this ledger exists to
        make visible. Both are recorded; neither is allowed to stand in for the
        other.
        """
        return sum(o.get("evaluations", 0) for o in self.opens)

    @property
    def remaining(self) -> int | None:
        return None if self.max_opens is None else max(0, self.max_opens - self.spent)


@dataclass
class BudgetLedger:
    path: Path = LEDGER_PATH
    dataset_id: str = ""
    epochs: dict[str, EpochBudget] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path = LEDGER_PATH) -> "BudgetLedger":
        if not path.exists():
            return cls(path=path)
        raw = json.loads(path.read_text())
        return cls(path=path, dataset_id=raw.get("dataset_id", ""),
                   epochs={k: EpochBudget(**v) for k, v in raw.get("epochs", {}).items()})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(
            {"dataset_id": self.dataset_id,
             "epochs": {k: v.__dict__ for k, v in sorted(self.epochs.items())}},
            indent=2, sort_keys=True))

    def declare(self, epoch_id: str, sealed: bool, max_opens: int | None) -> EpochBudget:
        return self.epochs.setdefault(
            epoch_id, EpochBudget(epoch_id=epoch_id, sealed=sealed, max_opens=max_opens))

    def charge(self, epoch_id: str, version: str, note: str = "",
               evaluations: int = 0) -> EpochBudget:
        """Record that this harness version was evaluated against this epoch.

        `evaluations` is the number of (window, entity) pairs the run will test.
        It does not affect the holdout cap — looking once is looking once — but
        it is what makes the multiple-testing surface countable afterwards.
        """
        b = self.epochs.get(epoch_id)
        if b is None:
            raise KeyError(f"{epoch_id} was never declared in this ledger")
        already = version in {o["harness_version"] for o in b.opens}
        if not already and b.max_opens is not None and b.spent >= b.max_opens:
            raise BudgetExhausted(
                f"{epoch_id} is sealed with {b.max_opens} opens and has spent all "
                f"of them on {sorted({o['harness_version'] for o in b.opens})}. "
                "A holdout consulted again is a derivation epoch nobody relabelled; "
                "declare it as one rather than quoting another score from it.")
        b.opens.append({"harness_version": version, "note": note,
                        "evaluations": evaluations,
                        "at": datetime.now(timezone.utc).isoformat()})
        return b

    def report(self) -> str:
        lines = [f"budget ledger over dataset {self.dataset_id[:23] or '<unpinned>'}"]
        for eid, b in sorted(self.epochs.items()):
            cap = "unlimited" if b.max_opens is None else f"{b.spent}/{b.max_opens}"
            lines.append(f"  {eid:8s} {'SEALED' if b.sealed else 'derive':7s} "
                         f"looks={cap}  tests={b.evaluations}")
        return "\n".join(lines)
