# Report 004 — Run 003: the one positive signal is noise

*2026-09-15. Executes drift audit 001 part 4. Reading declared before the run;

> **Status.** Current. Supersedes the positive readings in reports 002 and 003,
> and its second finding — that promotion rate is a property of the epoch rather
> than the market — is open issue rank 1 in [`STATE.md`](../spec/STATE.md).
result read against it unchanged.*

---

## The question

Report 003 promoted 3 cores, all inside 2021H1, from 87 sparks across three
epochs. Report 002 offered a substantive explanation: attention rose without
corroborating discussion in 2021, and came with discussion in 2023.

**Was 3-promotions-in-1-of-3-epochs surprising?**

## The protocol, declared in advance

Identical epochs, entities, basis and templates to report 003. Markets replaced
by block bootstrap — blocks of 5 consecutive observations resampled, which keeps
fat tails and local volatility structure and destroys only *when* things happened
relative to each other.

```
seeds            10          (the declared minimum)
block            5 observations
cluster          a core promoted >= 2 times inside ONE epoch
                 (2021H1's was 3 promotions in 1 epoch)

0 clusters       -> 2021H1 is real; the machinery discriminates
>= 2 clusters    -> 2021H1 is what chance gives; amend 002 and 003
exactly 1        -> inconclusive
```

## The result

```
seed  0   2021H1=14   clusters: no_flow x6, no_discourse x8
seed  4   2023H1=3    clusters: no_discourse x3
seed  7   2023H1=5    clusters: no_discourse x5
seed  8   2021H1=4    clusters: no_discourse x4

5 single-epoch clusters, in 4 of 10 seeds
```

**≥ 2 clusters. By the declared reading, 2021H1 is what chance gives.**

Cluster sizes in the nulls were 3, 4, 5, 6 and 8. **The real result was 3 — the
smallest cluster the nulls produced.** In the first pass of this run (reduced
inner calibration) seed 6 reproduced report 003 *exactly*: three promotions, one
core, all inside 2021H1.

### The caveat was tested, not written around

The first pass used 4 inner calibration runs instead of the real run's 8, for
cost. That makes each epoch's tolerance noisier, which errs toward **more** null
promotions — the direction that produces this verdict. Writing that down as a
limitation would have been cheap and dishonest, so the run was repeated at the
full 8, matching report 003 exactly.

Identical verdict: 5 clusters in 4 of 10 seeds. The reduction was not driving it.

---

## What this means

**Report 003's positive signal is noise.** The attention-without-discourse story
is a post-hoc rationalisation of a pattern that null markets produce at a rate of
roughly 4 seeds in 10.

This is the most useful result the project has produced, and it cost 71 seconds.
It also could not have been reached any other way: every per-spark rigor
mechanism in the system was working correctly and each individual spark was
clean. Only running the whole protocol against structureless data could show
that the protocol's *output distribution* is indistinguishable from noise.

Reports 002 and 003 are amended accordingly — that was declared before the run,
and is done rather than deferred.

## The finding nobody asked for

Across 20 null runs, **2019H1 produced zero promotions. 2021H1 produced 39 and
2023H1 produced 13.**

On null data. The markets have no structure in any of them, so promotion
propensity is a property of the *epoch*, not of the market. Something about
2021H1 — and to a lesser extent 2023H1 — makes the gates easy to clear
regardless of whether there is anything to find.

That is a second, separate defect, and it is arguably worse than the first: it
means the promotion rate is not comparable across epochs, so "replicated in 2 of
3 epochs" would not have meant what it appeared to mean even if a core had
managed it. Candidates worth eliminating in order — coverage differences feeding
the invariant set, volatility differences feeding the vol-relative magnitude,
and tolerance differences from each epoch's own null. Not yet diagnosed.

## What this does NOT show

- **Not that the harness is broken.** Every gate behaved as specified. The null
  control is the mechanism that caught this, and it caught it on the first run —
  which is the system working.
- **Not that the approach cannot work.** It says this particular signal, from a
  hand-written template library over five fields and three epochs, is noise.
- **10 seeds is a small sample.** 5 clusters in 10 seeds has wide error bars. The
  verdict is not "certainly chance", it is "chance is not excluded, and the
  declared bar for taking the signal seriously required it to be".

## Consequences for the run queue

Drift audit 001 held mechanism discovery until the gates are trustworthy. This
run says they are not yet: a protocol whose output distribution matches noise
cannot evaluate a model's hypotheses either.

Revised order:

1. **Diagnose the epoch asymmetry.** Promotion rates that differ 39:0 across
   epochs on null data invalidate cross-epoch comparison, which is the whole
   basis of the replication bar. This now precedes run 004.
2. **Run 005 (window budgeting)** — a deflated-Sharpe correction over 87 sparks
   and 162 (window, entity) tests. The ledger now separates *looks* from *tests*
   so the correction has a denominator to consume.
3. **Run 004 (directional leg)** — unchanged in substance, moved behind the
   diagnosis.
4. **Mechanism discovery** — still held, and now for a better-evidenced reason.

## Reproducing

```bash
python demo/run003_null_protocol.py 10          # 4 inner calibration runs
INNER_CAL=8 python demo/run003_null_protocol.py 10   # matching report 003
```

Result recorded in `docs/reports/004-null-result.json`, pinned to dataset
`sha256:0d9589321` and harness `h:328e5dd176934f52`.
