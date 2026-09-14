"""Stateless runs, a frozen dataset, and the one thing that must not be forgotten.

Running each evaluation in a fresh session with no memory gives reproducibility.
It does not give independence, and these tests pin the difference.

The snooping surface is the DATASET, not the session. A run lost 9 of 9
predictions during this build, the magnitude rule was changed in response, and
the next run scored better. A fresh session would not remember the first run —
but the code still contains the fix, and the fix came from that data. Forgetting
the run does not un-spend the window.
"""
from pathlib import Path

import pytest

from harness.budget import (BudgetExhausted, BudgetLedger, EpochBudget,
                            harness_version)
from harness.dataset import freeze, verify


# ── a frozen dataset makes "the same data" provable ────────────────────────

def test_the_same_bytes_freeze_to_the_same_id(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    (a / "one.txt").write_bytes(b"x")
    (a / "two.txt").write_bytes(b"y")
    assert freeze(a).id == freeze(a).id


def test_a_changed_byte_changes_the_id(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    (a / "one.txt").write_bytes(b"x")
    before = freeze(a).id
    (a / "one.txt").write_bytes(b"z")
    assert freeze(a).id != before


def test_a_renamed_file_changes_the_id(tmp_path):
    """Path is hashed with content: the same bytes under a different name are a
    different dataset, because the adapter that reads them keys on the name."""
    a = tmp_path / "a"
    a.mkdir()
    (a / "one.txt").write_bytes(b"x")
    before = freeze(a).id
    (a / "one.txt").rename(a / "renamed.txt")
    assert freeze(a).id != before


def test_verify_reports_the_mismatch_rather_than_asserting(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    (a / "one.txt").write_bytes(b"x")
    ok, got = verify(freeze(a).id, a)
    assert ok
    (a / "two.txt").write_bytes(b"y")
    ok, got = verify(got.id, a)
    assert not ok and got.file_count == 2


# ── the harness version is a content hash, not a hand-maintained string ────

def test_the_harness_version_tracks_the_code(tmp_path):
    """Deliberately not a version string. The changes that matter are exactly the
    ones made in response to a result, and those are exactly the ones nobody
    remembers to bump a version for."""
    src = tmp_path / "h"
    src.mkdir()
    (src / "m.py").write_text("x = 1")
    before = harness_version(src)
    (src / "m.py").write_text("x = 2")
    assert harness_version(src) != before


# ── the budget is on the dataset, not the session ──────────────────────────

def ledger(tmp_path) -> BudgetLedger:
    led = BudgetLedger(path=tmp_path / "l.json", dataset_id="sha256:abc")
    led.declare("2019H1", sealed=False, max_opens=None)
    led.declare("2024H1", sealed=True, max_opens=2)
    return led


def test_rerunning_the_same_version_costs_nothing(tmp_path):
    """Reproduction is not another test. A stateless re-run of an unchanged
    harness over unchanged data adds no information and must not consume budget,
    or the ledger would punish the reproducibility it exists to enable."""
    led = ledger(tmp_path)
    for _ in range(5):
        led.charge("2024H1", "h:same")
    assert led.epochs["2024H1"].spent == 1
    assert led.epochs["2024H1"].remaining == 1


def test_a_changed_harness_costs_a_unit_even_in_a_fresh_session(tmp_path):
    """The case a stateless session cannot see. Nothing here asks whether anyone
    remembered the previous run."""
    led = ledger(tmp_path)
    led.charge("2024H1", "h:before", "first evaluation")
    led.charge("2024H1", "h:after", "magnitude rule changed after seeing results")
    assert led.epochs["2024H1"].spent == 2


def test_a_sealed_holdout_refuses_once_spent(tmp_path):
    led = ledger(tmp_path)
    led.charge("2024H1", "h:one")
    led.charge("2024H1", "h:two")
    with pytest.raises(BudgetExhausted, match="nobody relabelled"):
        led.charge("2024H1", "h:three")


def test_derivation_epochs_are_uncapped_but_still_counted(tmp_path):
    """Not capped, because deriving is what they are for — but counted, because
    the count is what a deflated-Sharpe correction would need."""
    led = ledger(tmp_path)
    for i in range(20):
        led.charge("2019H1", f"h:{i}")
    assert led.epochs["2019H1"].spent == 20
    assert led.epochs["2019H1"].remaining is None


def test_an_undeclared_epoch_cannot_be_charged(tmp_path):
    with pytest.raises(KeyError, match="never declared"):
        ledger(tmp_path).charge("2099H1", "h:x")


def test_the_ledger_survives_the_session(tmp_path):
    """The whole point: sessions are stateless, the ledger is not. It is the only
    memory a fresh-session protocol is allowed to keep, and the only one it
    must."""
    path = tmp_path / "l.json"
    led = BudgetLedger(path=path, dataset_id="sha256:abc")
    led.declare("2024H1", sealed=True, max_opens=2)
    led.charge("2024H1", "h:one")
    led.save()

    reloaded = BudgetLedger.load(path)
    assert reloaded.dataset_id == "sha256:abc"
    assert reloaded.epochs["2024H1"].spent == 1
    reloaded.charge("2024H1", "h:two")
    with pytest.raises(BudgetExhausted):
        reloaded.charge("2024H1", "h:three")


# ── the dataset must outlive the container that assembled it ───────────────

def test_a_manifest_verifies_a_rebuilt_corpus(tmp_path):
    """A freeze id proves identity within one machine. A manifest is what lets a
    fresh container prove it reconstructed the same corpus — which is the whole
    premise of running each evaluation in a new session over the same data."""
    from harness.dataset import verify_against_manifest, write_manifest

    src = tmp_path / "raw"
    src.mkdir()
    (src / "a").write_bytes(b"one")
    (src / "b").write_bytes(b"two")
    m = tmp_path / "m.json.gz"
    write_manifest(m, src)
    assert verify_against_manifest(m, src).ok


def test_a_manifest_names_what_differs_rather_than_just_failing(tmp_path):
    """A boolean says the rebuild failed. This says which files — the difference
    between "refetch everything" and "three market-closed days are absent"."""
    from harness.dataset import verify_against_manifest, write_manifest

    src = tmp_path / "raw"
    src.mkdir()
    (src / "a").write_bytes(b"one")
    (src / "b").write_bytes(b"two")
    m = tmp_path / "m.json.gz"
    write_manifest(m, src)

    (src / "b").write_bytes(b"CHANGED")
    (src / "c").write_bytes(b"new")
    diff = verify_against_manifest(m, src)
    assert not diff.ok
    assert diff.changed == ("raw/b",)
    assert diff.extra == ("raw/c",)
    assert diff.missing == ()
    assert "changed" in diff.describe() and "extra" in diff.describe()


def test_a_manifest_is_portable_across_directories(tmp_path):
    """Keyed on root NAME plus relative path, not an absolute path — a manifest
    written in one container has to verify in the next one."""
    from harness.dataset import verify_against_manifest, write_manifest

    first = tmp_path / "one" / "raw"
    first.mkdir(parents=True)
    (first / "a").write_bytes(b"same")
    m = tmp_path / "m.json.gz"
    write_manifest(m, first)

    second = tmp_path / "two" / "raw"
    second.mkdir(parents=True)
    (second / "a").write_bytes(b"same")
    assert verify_against_manifest(m, second).ok


def test_source_data_stays_out_of_git():
    """The declared discipline that keeps the licensing option free at zero cost.
    The repository carries hashes; the corpus is rebuilt from public sources."""
    ignored = Path(".gitignore").read_text().splitlines()
    assert ".cache/" in ignored
