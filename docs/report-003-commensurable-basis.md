# Report 003 — Bulk archive, a commensurable basis, and still no replication

*2026-09-13. Follows report 002. Same four epochs, now over a basis that is
genuinely identical across all of them.*

---

## What changed

Report 002's conclusion carried a caveat that swallowed most of it: GDELT
rate-limited out of three epochs, so `editorial_publication` existed in one, and
the epochs were compared over **different bases**. That is not a comparison.

The fix was not a workaround. GDELT's query API and its bulk archive are two
paths to the same data, and only one of them is throttled:

```
api.gdeltproject.org/api/v2/doc/...          429, IP-level, persists for minutes
data.gdeltproject.org/gkg/YYYYMMDD.gkg.zip   206, ~26 MB, ~1.5 s, no throttle
```

901 days pulled from the archive in 34 minutes. Reduced to the declared entity
alias set at the network boundary: **3.6 MB cached, from ~23 GB of raw.**

### Entity resolution by exact alias, not by pattern

The GKG `ORGANIZATIONS` field is a list of lowercase org names. The same day's
file contains `applebee`, `appleton school`, `apple app store or google play` and
`taiwanese apple inc`. Substring matching on `apple` builds a series measuring
nothing about the entity.

Each entity now declares an exact, versioned alias set. That also recovered Apple
and Tesla, which the old text query missed entirely — they appear as `apple inc`
and `tesla inc`, never as the bare token.

---

## The run

```
DATASET  sha256:0d9589321  1669 files  123.4 MB
HARNESS  h:0daf13110ebec352
BASIS    every source supports bulk history
```

### Basis commensurability — checked, not assumed

```
2019H1: [discourse_rate, news_rate, pageviews_rate, price_return, short_volume_share]
2021H1: [discourse_rate, news_rate, pageviews_rate, price_return, short_volume_share]
2023H1: [discourse_rate, news_rate, pageviews_rate, price_return, short_volume_share]
verdict: same_basis — every declared field is expressible in every epoch
```

`revenue_yoy` is `cadence_incoherent` in all three, identically — quarterly
filings into a weekly basis, refused rather than forward-filled. An identical
absence is still a shared basis; it is a *differing* absence that breaks a
comparison, which is exactly what report 002 was suffering from.

### Results

| epoch | tolerance (own null) | sparks | promoted |
|---|---|---|---|
| 2019H1 | 2.4440 | 27 | 0 |
| 2021H1 | 2.4925 | 26 | 3 |
| 2023H1 | 2.3813 | 34 | 0 |

```
core_transient_attention_no_discourse:
  3 derivations across 1 epochs ['2021H1'], 3 entities — single-epoch, not replicated

No core replicated across epochs.
```

**87 sparks, 3 promotions, all inside one epoch. The bar was two.** The holdout
was never opened: `2024H1 SEALED spent=0/3`.

---

## What this settles that report 002 could not

Report 002's null result was confounded — a form could have failed to replicate
simply because its inputs did not exist in two of the three epochs. That
confound is gone:

- The basis is **identical** in all three epochs, verified rather than assumed.
- `transient_attention_no_flow` — the template from report 001, which requires
  editorial publication to hold invariant — was **evaluable in every epoch for
  the first time**, and promoted in none of them.
- Its sibling over community discourse promoted in one epoch of three.

So the report 001 finding does not survive. A form that looked like a strategy in
one six-month window appears in one epoch of three when tested over a basis that
is actually the same in each. That is what a single-window fit looks like once
the confound is removed.

## The budget ledger, first real entry

```
budget ledger over dataset sha256:0d9589321042540b
  2019H1   derive  spent=unlimited  versions=1
  2021H1   derive  spent=unlimited  versions=1
  2023H1   derive  spent=unlimited  versions=1
  2024H1   SEALED  spent=0/3        versions=0
```

This persists across sessions and is the answer to "can each run be a fresh
session with no memory". It can — **but the ledger is the one memory that must
survive**, because the snooping surface is the dataset, not the session.

The harness version is a content hash of the source. During this build a run lost
9 of 9 predictions, the magnitude rule was changed in response, and the next run
scored better; a fresh session would not remember the first run, but the code
still carried the fix and the fix came from that data. Hashing the source counts
that automatically, which is precisely the case a stateless protocol cannot
otherwise see.

## Still true, and still limiting

- **Only filters can promote.** Corroboration comes from the invariant set, which
  supports a no-move claim and cannot support a directional one. Every core
  derived across all three epochs was `neutral`.
- **The template library is hand-written**, so the search space is whatever was
  imagined in advance. Three epochs of rejections are informative about the data;
  the one promotion is not informative about the world.
- **Three derivation epochs is a small sample** for a recurrence claim in either
  direction. Absence of replication here remains weak evidence of absence.
- **The run is still contaminated for survivorship** — six names that still exist.

## Reproducing

```bash
python demo/multi_epoch_run.py      # this report
python -m pytest tests/ -q
```

The dataset hash pins exactly which bytes produced this. A rerun of the same
harness version over the same freeze costs no budget — reproduction is not
another test.

---

> ## AMENDED — see report 004
>
> Run 003 put this protocol over block-bootstrap null markets, 10 seeds, with the
> reading declared in advance. Single-epoch promotion clusters appeared in **4 of
> 10 null seeds**, with sizes 3, 4, 5, 6 and 8. The result reported above — three
> promotions, one core, all inside 2021H1 — is the *smallest* cluster the nulls
> produced, and one null seed reproduced it exactly.
>
> **The 2021H1 cluster is what chance gives.** The attention-without-discourse
> explanation offered above is a post-hoc rationalisation of noise and should not
> be relied on. The conclusion that nothing *replicated* still stands; what does
> not stand is treating the single-epoch cluster as a signal worth explaining.
