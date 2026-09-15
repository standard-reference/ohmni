# Agentic Finance Harness — Data Sources

*Companion to `01-system-specification-v3.md`, `02-build-plan-and-parts.md`, `04-data-product-design.md` and `05-cross-reference-layer.md`. Pricing verified ~September 2026 and shifts often — re-check before buying.*

---

## 0. The two criteria that decide everything

Both represent contamination the no-lookahead bus guard **structurally cannot catch**, because the timestamp is honest and the *value* is wrong:

**1. Point-in-time integrity.** Does each record carry an availability date distinct from the period it describes, and are restatements preserved rather than overwritten? A restated value on an honest timestamp is undetectable lookahead.

**2. Survivorship bias.** Does the universe include delisted, acquired, and bankrupt entities? Most cheap equity vendors quietly serve only currently-listed tickers, which inflates every backtest invisibly.

Three secondary criteria:

**3. Backfill honesty.** Was a signal computed and published at the time, or reconstructed later by running today's methodology over archived inputs? Reconstructed history never existed as a live signal — the alt-data equivalent of restatement, and most vendors don't say which they are.

**4. Bulk vs metered.** This harness pulls history once and reuses it heavily across walk-forward windows, re-estimation, and rotating holdouts. Per-request pricing built for agent lookups is a structural mismatch.

**5. Independent measurement processes.** Corroboration requires genuinely different processes, not several transforms of one. Breadth of *process* is scarce; breadth of *fields* is cheap and mostly redundant.

---

## 1. Key findings from the vendor investigation

### EDGAR is natively point-in-time — this is the decisive finding

Every XBRL CompanyFacts fact instance carries `end` (period end), `val`, `accn` (accession number), and `filed` (filing date). Where a period is later restated, **multiple fact objects exist for the same `end` with different accession numbers**. So the full revision chain is preserved, not two fixed projections of it.

`as_of(T)` = filter to `filed <= T`, take the latest `filed` per `end`. This **dominates both vendor dimensions**: as-reported pins to the first print forever and ignores that the market later learned the restatement; most-recent is lookahead. As-of returns what was knowable at T.

Free, public domain, no key required. Rate limit 10 req/sec, `User-Agent` header mandatory.

### financialdatasets.ai: schema lacks both properties — verified

Its financial-statements response carries `ticker`, `report_period`, `fiscal_period`, `period`, `currency` and the line items. Query parameters are `ticker`, `period`, `limit`, `cik`, and `report_period` comparison operators. `report_period` is documented as the reporting period — the fiscal period end.

There is **no filing-date field and no as-reported/restated dimension**. Consequences: you cannot know when a figure became knowable (any assumed lag is either lookahead or over-conservatism, and you can't tell which), and a query for a historical period almost certainly returns today's restated value.

Their accuracy process is real and unusually transparent — values compared against the original filing on EDGAR, sampled at 1,000 companies and 20,000 data points per audit cycle. But *accurate to the filing* and *knowable at the time* are orthogonal properties. They built a serious process for the first and no schema support for the second.

**Still useful:** its filings, insider, 13F, and 8-K endpoints are fine, because for those the filing date *is* the datum. And $20 for 1,000 requests makes it an excellent **test oracle** for validating our own concept maps (stage A1).

### Sharadar: semantics verified, accuracy unverified

Its docs state the As-Reported dimensions present a point-in-time view with data time-indexed to the date of the form 10 regulatory filing to the SEC, and on restatements, when companies restate financials for prior reporting periods, the MR dimensions are updated — AR preserved, MR updated, with a worked example. Coverage is nearly 18,000 active and delisted US public companies… 99% survivorship bias free. Deep history to 1998.

What was verified is *documented semantics*, not accuracy. No published accuracy audit exists — the reverse of financialdatasets.ai's emphasis.

**Not bought for fundamentals**, given EDGAR. Its remaining value: standardization (only if concept-map coverage proves inadequate), 1998–2009 history (declined — see below), and prices with corporate actions (a live candidate for stage B4).

### Deep pre-2009 history: deliberately declined

Accounting-standard changes — SOX 2002, stock-comp expensing 2006, ASC 606, ASC 842 — mean "revenue" in 2003 and 2024 are different measured quantities. Structural market changes (decimalization 2001, Reg NMS 2007, passive-flow growth, universal algorithmic execution) mean a pre-2009 mechanism may have worked *because of* microstructure that no longer exists — structurally wrong signal, worse than no data.

The 2009–2026 window contains 2011, 2015–16, Q4 2018, COVID, and 2022 — five stress episodes in seventeen years. And spec §6's answer to sample size was cross-sectional replication, which buys power without heterogeneity. Deep history's one honest use is testing survival across a regime transition, which is a different question from present validity.

### Social platforms: two biases, one of them rarely discussed

Social data has genuine value — it measures retail discourse, which nothing else in the set captures — but historical social data carries two contaminations that are worse than the news-vendor problems below.

**Engagement metrics are current-snapshot, not historical.** Pull a 2019 post today and you get *today's* like, repost and reply counts. There is no revision chain, because the intermediate values were never stored anywhere. The post's text and creation timestamp are honest; every engagement number attached to it is from the present. Any backtest keyed on engagement is reading the future.

**Deleted-record survivorship, which is the underrated one.** A historical pull returns only posts that still exist. Deletions skew heavily toward wrong calls, retracted claims, and promotional content that was taken down — so historical social sentiment systematically over-represents what nobody regretted saying. This is exactly the delisted-ticker problem, in a place nobody checks for it.

Consequence: **social is forward-record-only.** The post stream can be recorded honestly going forward, with engagement sampled on a schedule so you build your own series. Backfill is for text and timestamps at most, never for engagement.

**X specifically:** the free tier is effectively unusable for reads, Basic sits around $200/mo with a low monthly read cap, and full-archive search is Pro-tier and up (roughly $5,000/mo) — verify current tiers before committing, since this pricing has changed repeatedly. Edit history is exposed, so an edited post has a genuine revision chain. Reposts and quotes carry lineage to an originating post, which is root-set material. Engagement can be manufactured, so bot-inflation is a quality flag rather than a signal.

**Free or cheaper alternatives worth having first:** Bluesky's AT Protocol firehose is genuinely open and fully free; Farcaster is open and crypto-native; StockTwits is explicitly finance-focused; YouTube's Data API has a usable free quota. Reddit has been paid and commercially restrictive since 2023, and Pushshift is no longer publicly available.

### GDELT has two paths and only one of them works for history

Verified 2026-09: `api.gdeltproject.org/api/v2/doc` rate-limits at the **IP
level** and returns 429 for minutes after a burst, which makes a multi-period
backfill impossible through it. `data.gdeltproject.org` serves the same corpus by
range request with **no throttling** — 26 MB/day for full GKG at ~1.5s, or
~4.7 MB/day for `gkgcounts`, which is the tractable one if only counts are needed.

Full GKG carries an `ORGANIZATIONS` field, which is entity mentions directly.
Resolution must be **exact match against a declared, versioned alias set**: the
same day's file contains `applebee`, `appleton school` and `taiwanese apple inc`,
so substring matching on `apple` builds a series measuring nothing — and the
alias set also recovers entities that appear only as `apple inc` / `tesla inc`
and never as a bare token.

`historical_access: rate_limited` for the query API, `bulk` for the archive, with
`bulk_endpoint` recorded. The distinction is not cosmetic: it is the difference
between a basis that exists in every period and one that does not.

### News-intelligence vendors: category mismatch

Perigon and NewsCatcher-class products are **monitoring** products — latency is the value proposition (Perigon: 6 min average publish-to-live, sub-200ms API response). For replay research, latency is worth nothing.

The binding constraint is history depth vs price. Perigon's free tier: 150 requests/mo, 3 months of history, personal-use license. Basic: $250/mo, 10k requests, 6 months. Plus: $550/mo, 50k requests, 3 years — and those are *startup* prices. Ten-plus years starts at $24k/yr. GDELT is free with ~11 years.

Two further problems: vendor enrichment (sentiment, entity tags) is **derived from the article text**, so it shares root lineage and provenance with the article and is never a second leg. And it is **not point-in-time stable** — an improved tagger means 2019 articles scored by a 2026 model, undetectable from the consumer side. Pinned local scoring is the only way `embedding_space_version` means anything.

---

## 2. Free sources — build the adapter

| Source | Measurement process | PIT notes | Stage |
|---|---|---|---|
| **SEC EDGAR XBRL** (CompanyFacts) | Corporate accounting disclosure | **PIT by construction** — `filed` ≠ `end`, full revision chains | A1 |
| **SEC EDGAR filings** (8-K, incl. Item 1.01) | Electronic filing submission | acceptance datetime | A1 / A3 |
| **SEC Forms 3/4/5** | Insider legal disclosure | filing date | A2 |
| **SEC 13F** | Institutional position reporting | filing date — up to 45 days after period end | A2 |
| **SEC Exhibit 21** | Subsidiary/ownership structure | filing date | A3 |
| **SEC CIK↔ticker map** | Entity resolution anchor | historical; CIK survives renames and delisting | A3 |
| **ALFRED** (archival FRED) | Statistical-agency publication, **vintaged** | vintage date — use this, never plain FRED | A2 |
| **GDELT 2.0** (bulk archive) | Global news-wire ingestion | **ingest window, not article date**; use the ARCHIVE, not the query API | A2 |
| **GDELT GKG** | Entity co-occurrence, themes | as above | A3 |
| **Wikimedia pageviews** | Public information-seeking behaviour | hourly, history to 2015, ~1 day publication lag | A2 |
| **Wikidata (SPARQL)** | Entity graph — companies, people, roles, subsidiaries | — | A3 |
| **GLEIF** | LEI codes, legal-entity hierarchies | — | A3 |
| **OpenFIGI** | Instrument identifier mapping | — | A3 |
| **Business Wire / PR Newswire / GlobeNewswire / Accesswire RSS** | Originating corporate announcements | wire timestamp | A2 / A3 |
| **Wayback CDX API** | First-capture verification for web claims | **the timestamp arbiter for mutable pages** | A3 |
| **Hacker News (Algolia)** | Technical-community attention, full history | — | A3 |
| **Federal Register** | Regulatory rulemaking | publication date | later |
| **openFDA** | Approvals, adverse events, recalls | irregular | later |
| **ClinicalTrials.gov** | Trial registration/status | irregular | later |
| **USPTO** | Patent grants and applications | weekly | later |
| **USAspending / FPDS** | Government contract awards | daily | later |
| **CourtListener / RECAP** | Litigation dockets | daily | later |
| **EIA** | Energy production, stocks | weekly | later |
| **NOAA** | Weather/climate | continuous | later |

**Wikipedia pageviews is the standout and usually overlooked:** free, hourly, deep history, keyed to entities resolvable through Wikidata, and it measures retail information-seeking — something no market stream captures, uncoupled from price in the way options are not. Real corroboration weight rather than the shared-driver trap.

### Prediction markets — a distinct measurement process

Measures aggregated explicit probabilistic belief about a named future event. Nothing else in the set does, and every contract resolves definitively, which makes it the only source here that supplies free labelled outcomes.

| Source | Stake | Notes | Retrieval |
|---|---|---|---|
| **Kalshi** | Real money | CFTC-regulated US exchange; macro, Fed, CPI, elections, weather | some history; **record quotes forward** |
| **Polymarket** | Real money | On-chain, so quote and resolution history is independently auditable; oracle resolution with a dispute window | on-chain history; still record forward |
| **Metaculus** | Reputation | Aggregated human forecasts, long horizons, calibration-focused; forecast history exposed | as_of for forecast series |
| **Manifold** | Play money | Very open API, broad question set, low signal per market | open |
| **Iowa Electronic Markets** | Real money | Academic; election history to 1988 — unusually deep for this category | as_of |

Three things to handle, detailed in `04-data-product-design.md`: quotes are transient and must be recorded; the **resolution criterion itself can be revised** after launch, so the instrument definition needs a version and its own availability date; and resolutions can be **disputed and overturned**, so the outcome needs a revision chain like a restated figure.

**Also the cheapest external calibration benchmark available** (spec §14): where a market existed on a resolved question, its price at registration time is a consensus probability to score the harness against.

### Social streams

| Source | Process | Cost | Retrieval |
|---|---|---|---|
| **Bluesky (AT Protocol firehose)** | Retail discourse | free, fully open | **record forward** |
| **Farcaster** | Retail discourse, crypto-native | free, open protocol | **record forward** |
| **StockTwits** | Retail discourse, finance-specific | check current terms | **record forward** |
| **YouTube Data API** | Comments, metadata | free quota | snapshot metrics |
| **X API** | Retail discourse, broadest reach | ~$200/mo Basic; full archive Pro-tier+ | **record forward**; engagement is snapshot; deletions unrecoverable |
| **Reddit** | Retail discourse | paid, commercially restrictive | limited |

### Order flow and market structure — free and overlooked

| Source | Process | Why it's good |
|---|---|---|
| **FINRA ATS transparency** | Off-exchange / dark pool volume by venue | Free, official, weekly. Genuinely independent of exchange matching |
| **FINRA short sale volume** | Daily short volume by symbol | Free, daily, honest lag |
| **FINRA / exchange short interest** | Bi-monthly short interest | Free |
| **SEC Rule 605/606** | Broker execution quality and routing | Free, quarterly |

FINRA ATS volume is the standout: off-exchange activity is a distinct measurement process from exchange matching, published with a known lag, and completely free.

### Commercial / app flows — the weakest category for the money

Sensor Tower, data.ai, Apptopia, Similarweb, and credit-card panels (Consumer Edge, Facteus) are all **modeled estimates**, all five figures and up, and all revise their history. Panel composition drift plus retroactive re-weighting means the historical value you would backtest against was never the value anyone saw. Declared `measurement_type: modeled` and `backfilled: true` if ever added.

Free and genuinely *measured* alternatives: **Steam player counts** (real measurements, free API), **App Store / Play Store rankings** (free but ordinal and snapshot — record forward), **Cloudflare Radar** (free domain rankings and traffic trends), **GitHub activity** (free, a real usage proxy for developer-tools companies).

### Free crypto set (slots into the same interfaces)

| Source | Process | Notes |
|---|---|---|
| **ccxt** | Exchange order matching, spot + perp | MIT licence |
| **Coinalyze** | Perp funding, open interest, liquidations | free API; **record forward** |
| **Deribit public API** | Options IV, DVOL, skew | free history shallow; **record forward** |
| **Coin Metrics community** | Blockchain settlement | free tier |
| **Blockchair / Etherscan** | On-chain raw | harsh free limits; only if Coin Metrics insufficient |

---

## 3. Paid — conditional, with the trigger that flips each

| Source | What it uniquely gives | Price | Buy when |
|---|---|---|---|
| **Price provider** — Sharadar Prices à la carte (~$9–39/mo) or Massive/Polygon Starter (~$29/mo) | Survivorship-free prices with correct corporate actions | ~$9–39/mo | **Stage B4** — scored runs need it; hand-rolled split/dividend adjustment is silently wrong |
| **financialdatasets.ai Credits** | Concept-map validation oracle | $20 one-time, 1,000 requests | **Stage A1** — cheap audit of our own mapping |
| **Sharadar Bundle** | Standardized fundamentals, PIT index membership, insider + 13F in one | $69/mo, $499/yr | Only if 1B's measured concept-map coverage is inadequate for the peer groups that matter |
| **Databento** | Historical L2 / MBO order book | $125 free credits (6mo expiry), then metered or $199/mo | Only if a short-horizon mechanism appears. Most permissive derived-data licensing of any paid vendor (CME excepted) |
| **Quiver Hobbyist** | Congressional STOCK Act disclosure | $30/mo | Optional — genuinely independent process, cheap. Free alternative: raw EDGAR |
| **Massive/Polygon Developer+** | Intraday / tick equities | $79–199/mo | Only if intraday execution realism or short horizons matter |
| **Amberdata / CoinAPI** | Deep crypto options + normalized funding history | paid | Only if free-tier depth binds — and only for history you failed to record |

### Ruled out, with reasons

| Source | Why not |
|---|---|
| **financialdatasets.ai** as fundamentals core | No filing date, no restatement dimension; per-request metering mismatched to backfill |
| **FMP** | Current-view fundamentals; assume restatements overwrite |
| **Sharadar** as fundamentals core | EDGAR gives the same PIT property free, with richer revision chains |
| **Norgate** | Overlaps a price provider; Windows-bound |
| **EODHD** | Non-US history shallow; only if non-US coverage becomes needed |
| **Perigon / NewsCatcher-class** | History depth vs price mismatch; enrichment is derived and not PIT-stable |
| **AlphaSense** | Category error — enterprise document search, not a structured API; broker-research licensing unusable |
| **Compustat PIT / CRSP / LSEG / FactSet** | Genuinely solves it; five figures and up. Check for any academic affiliation, which changes access substantially |
| **yfinance** | No delisted coverage, ToS-grey. **Prototype only — never in a scored run** |
| **Plain FRED** | Strictly dominated by ALFRED (revised vs vintaged) |
| **Vendor sentiment (any)** | Derived from article text — shares lineage, and not version-pinnable |

---

## 4. Redundancy — what not to buy alongside what

Two sources are redundant here when they share **root lineage**, and ingesting both without declaring it makes §9.3's accumulation sum them as independent legs. Redundant sources don't just cost money, they manufacture false confidence.

| Pair | Relationship | Handling |
|---|---|---|
| EDGAR fundamentals ↔ any vendor fundamentals | Same root filings | Never corroboration. Use vendor as **validation oracle** only |
| Quiver insider tier ↔ SEC Form 4 | Quiver scrapes SEC | Use Hobbyist (congressional only); take Form 4 from EDGAR |
| Vendor price ↔ vendor price | Same measurement process | Not independent evidence. One is enough |
| News ↔ derived sentiment | Sentiment computed from the news | Declared `derived_from`; the deliberate true-negative fixture |
| Options ↔ spot, same underlying | Disjoint lineage, distant provenance, **coupled through delta** | `couples_to` declaration; correlation cap |
| Blockchair/Etherscan ↔ Coin Metrics | Same blockchain root | Keep one |
| Plain FRED ↔ ALFRED | Same series, revised vs vintaged | ALFRED only |

**The rule for any redundant source kept anyway:** it declares `derived_from` or a `couples_to` strength, so the independence check discounts it rather than being fooled.

---

## 5. Independent measurement processes — the actual scorecard

What the free set spans, which is what matters more than field count:

| # | Process | Source |
|---|---|---|
| 1 | Exchange order matching | price provider / ccxt |
| 2 | Corporate accounting disclosure | EDGAR XBRL |
| 3 | Insider legal disclosure | EDGAR Forms 3/4/5 |
| 4 | Institutional position reporting | EDGAR 13F |
| 5 | Editorial publication | GDELT |
| 6 | Statistical-agency publication (vintaged) | ALFRED |
| 7 | Public information-seeking behaviour | Wikimedia pageviews |
| 8 | Congressional disclosure | Quiver / EDGAR |
| 9 | Corporate announcement (relationships) | press wires + Wayback |
| 10 | Regulatory rulemaking | Federal Register |
| 11 | Blockchain settlement | Coin Metrics (crypto) |
| 12 | Derivatives positioning | Coinalyze / Deribit (crypto) |
| 13 | **Off-exchange order routing** | FINRA ATS / short volume |
| 14 | **Aggregated probabilistic belief** | Kalshi / Polymarket / Metaculus |
| 15 | **Retail discourse** | Bluesky / Farcaster / StockTwits / X |

Fifteen processes, almost entirely free. Most paid bundles span fewer.

Two are worth singling out. **Aggregated probabilistic belief** is the only source here that produces definitively resolved outcomes, which makes it both an independent leg and a calibration benchmark. **Off-exchange order routing** is free, official, and measures something no price feed does — where volume actually executed.

---

## 6. Record-now-or-buy-later

The only time-sensitive items. Transient state not recorded is gone, and for some of these there is no archive to buy at any price:

| Stream | Why | Archive purchasable later? |
|---|---|---|
| **Bluesky firehose** | Free, open, and no historical API | No — record or lose it |
| **StockTwits / Farcaster** | Same | No |
| **X post stream** | Engagement is snapshot-only; deletions unrecoverable | Partially, at Pro-tier pricing, and still survivorship-biased |
| **Prediction market quotes** (Kalshi, Polymarket) | Transient order state | Partially, venue-dependent |
| **Deribit options IV / skew / DVOL** | Free API, shallow history | Yes, paid (Amberdata) |
| **Perp funding + open interest** (Coinalyze) | Free, shallow history | Yes, paid (CoinAPI) |
| **Crypto orderbook snapshots** (ccxt) | Transient | Rarely |
| **App store rankings** | Ordinal and snapshot | No |
| **Databento L2/MBO** | Use the free credits before they expire | Yes, metered |

The top four have **no purchasable archive**, which makes them the genuinely urgent ones. Everything else in every table above is permanently re-fetchable — filings, macro vintages, news archives, pageviews, FINRA reports.

A cron job costs almost nothing and is the only thing in this document with a clock on it.

---

## 7. Diligence checklist for any new vendor

Apply before adding anything, since new sources will keep appearing:

1. Does every record carry an **availability date** distinct from the period it describes?
2. Are **restatements/revisions preserved** as separate records, or overwritten?
3. Does the universe include **delisted/acquired/bankrupt** entities? Is there point-in-time index or universe membership?
4. Is historical data **as-published or reconstructed** (`backfilled`)? If enriched, is the enrichment recomputed when models change?
5. Does the timestamp reflect **first ingest** or claimed publication?
6. **Bulk export** available, or per-request only? What does full backfill actually cost?
7. How many **years at the tier you'd actually pay for** — not the top tier?
8. What **measurement process** does this add that the existing set lacks? If none, it's redundant regardless of price.
9. Is it **mechanically coupled** to something already ingested? If so, at what strength?
10. Does it require a **live API call at decision time**? If so, it cannot be used inside replay — bus only, no exceptions.

**The test that settles point-in-time claims empirically:** pick a company with a known restatement, query as-of a date before the restatement was filed, and check whether you get the original figures or today's. This works against any vendor, and it works against our own EDGAR adapter — which is why 1B's acceptance bar includes it.
