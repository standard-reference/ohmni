# Report 002 — Multi-epoch derivation, and nothing replicated

*2026-09-13. Four disjoint epochs, six entities, five real sources. Follows

> **Status.** The method stands and is now spec (§17, §23). Two substantive
> claims did not survive:
>
> - The basis used here was **not commensurable across epochs** — GDELT was
>   available in one epoch of four — so the null result was confounded. Report 003
>   removed the confound and reached the same conclusion on a verified basis.
> - The **attention-without-discourse explanation for 2021H1 is withdrawn.**
>   Report 004 showed null markets produce clusters of that shape in 4 of 10
>   seeds. It was noise being explained.
report 001.*

---

## What report 001 got wrong

Report 001 produced a trade type and called it generic because it contained no
entity id and no date, which `is_generic()` confirmed. It also contained
`min_separation = 1.2472`.

That number came from one window's noise level. In another regime it means
something else entirely. The form was a fit to its derivation window wearing a
generic costume — **keeping entity ids out is necessary and nowhere near
sufficient.** The parameters carried the window.

## The correction

**The generic thing is the recipe, not the number.**

| | before | after |
|---|---|---|
| separation | `1.2472` | `null_quantile(q=0.95)` — "further apart than noise gets *here* 95% of the time" |
| magnitude | `0.02` | `subject_volatility(multiple=1.0)` — the subject's own realised movement |

Resolved against each epoch's own data, the same rule gives different numbers:

```
2019H1  tolerance 2.3052   (own null: n=576, ceiling 3.97)
2021H1  tolerance 2.2893   (own null: n=576, ceiling 4.57)
2023H1  tolerance 2.4681   (own null: n=576, ceiling 5.29)
```

Nothing crosses an epoch boundary except the core's invariant identity —
asserted to contain no floats. An unresolvable rule raises rather than falling
back to a default, because a default would silently carry the derivation epoch's
value into a window that never justified it.

## The run

Epochs declared before anything ran, disjoint by construction, most recent held
out:

| epoch | regime | role |
|---|---|---|
| 2019H1 | late-cycle expansion, pre-COVID | derive |
| 2021H1 | post-COVID liquidity, retail participation peak | derive |
| 2023H1 | rate-shock recovery, start of the AI attention surge | derive |
| 2024H1 | AI continuation | **holdout** |

```
2019H1   21 sparks    0 promoted
2021H1   19 sparks    3 promoted   core_transient_attention_no_discourse (AMD, INTC, MSFT)
2023H1   27 sparks    0 promoted
```

## The result

**Nothing replicated. Nothing was promoted. The holdout was never touched.**

```
core_transient_attention_no_discourse:
  3 derivations across 1 epochs ['2021H1'], 3 entities — single-epoch, not replicated
```

67 sparks, 3 promotions, all inside one epoch. The bar was two.

This is the point. In 2021H1 alone the form looks like a promoted strategy —
three independent entities, a clean gate, a coherent story. Report 001 stopped
exactly there, in a different epoch, and called the result a strategy. Across
three epochs the form appears in one, which is what "fitted to a window" looks
like once you actually test for it.

Three firings in one epoch are **one observation with wide coverage**, not three
replications: the windows overlap and the regime is shared. Counting firings
instead of epochs is how a single period's quirk gets promoted as a law, and
`Replication.replicated()` counts epochs for exactly that reason.

### Why 2021 and not 2023

The form claims attention rose *without* corroborating community discussion,
order flow or positioning. In 2023H1 the attention spikes came **with**
discussion — the AI surge produced both — so `retail_discourse` was not invariant
and the template was correctly rejected. In 2021H1 attention moved on its own.

That is a substantive difference between the periods, not a threshold artefact:
the 2023 tolerance was *looser* relative to its own null, so a tolerance effect
would have promoted more, not fewer.

---

## An honest caveat on the comparison

Report 001's run used GDELT article counts for editorial publication. This run
uses Hacker News submissions for community discourse, because **GDELT's public
API rate-limits to the point of being unusable for a multi-epoch historical
pull** — leaving that phenomenon available in one epoch out of four, and a basis
that differs between epochs cannot support a replication claim at all.

So the two runs are not a clean before/after on identical inputs. What this run
establishes is narrower and still the point: *under a basis held constant across
epochs, the form recurs in one epoch of three.*

Hacker News is mapped to `RETAIL_DISCOURSE` and `CONSTITUTIVE`, deliberately not
to editorial publication. A community submission and a wire story are different
phenomena, and collapsing them to reuse a template would be choosing the
measurement to fit the hypothesis. A sibling template was declared over the
phenomena available in every epoch rather than rewriting the original.

## Two data traps this exposed

- **Algolia serves at most 1000 results per query and truncates by recency.** A
  busy entity's daily series would have been clipped at the start and complete at
  the end — manufacturing a spike at every window boundary. Requests are chunked
  monthly and a truncated chunk raises rather than serving a clipped series.
- **An unquoted query for `AMD` matches 4,626 stories a month** on prefix and
  typo similarity, against 19 for the quoted phrase. Entity resolution by text
  query is the weakest join in the whole source set, and that is the difference
  between a signal and a noise generator.

---

## Where this leaves the build

Unchanged from report 001 except:

- **Window budgeting** — report 001 named this the largest unaddressed risk.
  Cross-epoch replication is a partial answer: it does not budget windows, but it
  does stop a single period's artefact reaching promotion, which was the concrete
  harm. Deflated Sharpe and per-window budgets are still not built.
- **The harness can still only discover filters.** Corroboration comes from the
  invariant set, which supports a no-move claim and cannot support a directional
  one. Every core derived in this run was `neutral`.
- **GDELT is effectively unavailable** for historical work at its public rate
  limits. Recorded as a property of the source.

## What a positive result would need

Not a lower bar. Three things that do not yet exist:

1. **More epochs.** Three derivation epochs at six entities is a small sample for
   a recurrence claim in either direction. Absence of replication here is weak
   evidence of absence.
2. **Mechanism discovery.** The template library is hand-written, so the search
   space is whatever was imagined in advance. The rejections are informative
   about the data; the promotions are not informative about the world.
3. **A directional corroboration leg**, or nothing but filters can ever promote.

## Reproducing

```bash
python demo/multi_epoch_run.py      # this report
python -m pytest tests/ -q          # 158, fixture-only
```

---

## What avoids the GDELT problem

The failure decomposes into four problems and only one of them is about GDELT.

### 1. Retrieval *feasibility* was never declared

`retrieval: as_of` says a historical query returns historical values. It says
nothing about whether the history can be **fetched at scale**, and that is the
question that actually bit. Doc 03's diligence checklist asks it — "bulk export
available, or per-request only?" — but it never reached `SourceDeclaration`, so
it was neither machine-checkable nor in the manifest.

GDELT has **both** paths. Verified directly:

```
https://api.gdeltproject.org/api/v2/doc/doc?...     429, IP-level, persists for minutes
https://data.gdeltproject.org/gdeltv2/masterfilelist.txt   206, range requests, no throttle
https://data.gdeltproject.org/gkg/20190401.gkg.csv.zip     206, 39.3 MB/day
```

The archive is wide open. I built against the metered path and nothing in the
contract could tell me. `HistoricalAccess` now declares it — `bulk`, `metered`,
`rate_limited`, `record_only` — with the bulk endpoint recorded where one exists,
and `check_backfillable()` refuses a multi-epoch basis resting on a source that
cannot supply every epoch:

```
a multi-epoch basis cannot rest on sources whose history cannot be fetched at
scale; these would be present in some epochs and absent in others:
news_rate via gdelt.news (rate_limited) — a bulk archive exists at
https://data.gdeltproject.org/gdeltv2/masterfilelist.txt
```

That fires **before a single request**, rather than three hours into a fetch when
the epochs already have different bases.

### 2. The serious one: a missing source silently changed the basis

When GDELT went away, the field became `not_representable`, the observation
carried on, and the epochs ended up observed over **different bases**. I caught
that by hand and wrote it into this report. Nothing in the system caught it.

§12 is explicit that two sparks are comparable when they share a basis. That was
enforced within a run and not across epochs — which is precisely where a source
outage turns into an unnoticed comparison of two different things.

`harness/coverage.py` closes it. `BasisRealization` records what each epoch could
actually express and how well; `compare()` returns `same_basis` / `partial` /
`incommensurable`; and `replicated_cores()` now **refuses** a core whose inputs
were not expressible in every epoch rather than crediting it.

The distinction that matters: *did not replicate* and *was never testable* are
different findings, and collapsing them turns a source outage into evidence.

A coverage floor is required with no default — a field present in every epoch but
populated in a fifth of one epoch's frames is not really shared, and a default
would hide exactly the partial outage this exists to catch.

### 3. Source availability is a fact about the run

`RunManifest.record_source()` and `unavailable_sources`, folded into
`event_set_hash` so a run missing a source cannot hash the same as one that had
it.

### 4. The recorder, for anything with no archive

GDELT is recoverable from bulk, so it was never the urgent case. Bluesky,
Farcaster and StockTwits have no purchasable archive at any price — that remains
the only item in either track with a clock on it, and it is still not built.

### What this does not fix

The bulk path is open but **volumetrically expensive**: 39 MB/day of GKG is
~7 GB per six-month epoch, against a ~30 GB allowance, for what amounts to six
daily mention counts. The lighter `gkgcounts` variant is 4.7 MB/day (~850 MB per
epoch), which is tractable. Either way, an adapter against the bulk archive is
not yet written — what exists is the machinery that would have stopped the run
before it produced an uncheckable comparison.
