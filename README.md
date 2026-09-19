# uro_briefing

Full-stack briefing assistant for the UnRiskOmega "From Ping to Pitch" case:
loads the case data, joins and normalises it, ranks what matters, compares it
to a mock bank house view, pulls relevant market news, tracks client state
across calls so "what changed" is exact, and calls `gpt-4o` to produce a
structured 60-second advisor briefing — served through a FastAPI backend and
a single-page demo front end.

**Layers, in dependency order:**
`data_layer` → `analysis_layer` → `state` / `enrichment` → `synthesis` → `server.py`

## Demo front end

A single-page demo that overlays a **Generate Briefing** button on URO Advisor Pro
screenshots and shows the result in a slide-in drawer.

### How to run

```bash
pip install fastapi uvicorn openai
export OPENAI_API_KEY=sk-...
python -m uvicorn server:app --reload --port 8000
```

Then open **http://localhost:8000/**

**Add your screenshots** before the first run (the UI works without them — a
placeholder is shown — but the screenshots make the demo look real):

```
demo/static/img/client_Advisor_DB.png   # client-list view
demo/static/img/client_DB.png           # client-detail view
demo/static/img/portfolio_DB.png        # portfolio view
```

### Change the demo client

Use the **Client** dropdown in the page header — it loads all 47 clients
from `GET /api/clients` on page load, sorted alphabetically. The adjacent
**Portfolio** dropdown is populated automatically from the selected client's
portfolios.

By default the picker opens on the first alphabetical client in the loaded database.
To pre-select a specific client on first load, set `DEFAULT_CLIENT_ID`
in the `CONFIG` block at the top of `demo/static/index.html`:

```js
const DEFAULT_CLIENT_ID = '';   // set to any ClientId from clients.json, or leave empty for first client
```

The client with the most ranked priorities and SAA deviations in the core
dataset is **Company 001 AG** (`35050`).

### Demonstrating "Since Last Interaction"

The briefing's *Since last interaction* section is powered by the `state/`
layer: it diffs the current portfolio snapshot against the one saved on the
previous briefing call. On a fresh server with no prior state, every call is
a "first interaction" and the diff is empty.

To show a meaningful diff during a demo, plant a fake "30 days ago" snapshot
before you start:

```bash
python3 seed_demo_state.py        # writes .state/CASE-019.json with stale values
```

Then generate a briefing in the browser. The model receives a real diff in
its prompt:

```
- Portfolio value changed -3.6 % (from 725,000 to 698,978) since the last briefing.
- New issues since last time: IT sector overweight, Financials underweight.
- Swiss francs +7.2 pp / US-Dollar −7.8 pp / North America −6.6 pp since last briefing.
- iShares Global Water ETF newly entered the top positions.
```

| Command | Effect |
|---|---|
| `python3 seed_demo_state.py` | Plant the stale snapshot — run before each demo presentation |
| `python3 seed_demo_state.py --reset` | Delete the state file, next call is "first interaction" again |

**Why you need to re-seed between demo runs:** `refresh_client_state()` saves
a new snapshot as a side effect of every briefing call. After the first click
the baseline is today's data, so a second click correctly shows an empty diff
(nothing changed since the last call). Re-run the seed script to restore the
"30 days ago" baseline.

### Mock mode (no API key needed)

Append `?mock=1` to the URL to use the built-in mock response and test the UI
without hitting OpenAI:

```
http://localhost:8000/?mock=1
```

The drawer footer shows **demo data** (mock) or **live** (real API call).

---

## Install / run

No dependencies beyond the Python standard library, **except**:
- `server.py` (the API + demo): `pip install fastapi uvicorn openai`
  + an `OPENAI_API_KEY` environment variable
- `enrichment/market_news.py`'s live fetch: `pip install yfinance`

```bash
python3 run_example.py            # data_layer against the synthetic fixture
python3 run_analysis_example.py   # analysis_layer against the synthetic fixture
```

## Testing

```bash
python3 run_tests.py          # zero dependencies, works anywhere
# or, if you have pytest installed:
pytest tests/                 # same test files, nicer output
```

176 tests, covering `data_layer`, `analysis_layer`, `state`, `enrichment`,
and `synthesis`:
- `loader.py` — valid/invalid file shapes
- `reference_index.py` — id lookups, the plain→SAA category translation,
  the catch-all inference heuristic (including its ambiguous-refuses-to-guess
  case)
- `fund_lookthrough.py` — weight normalization, translation applied correctly
- `saa.py` — actual exposure aggregation (direct + fund positions combined),
  target comparison, breach flags
- `violations.py` — per-client override filtering
- `flatten.py` — the full `build_client_view()` output shape
- `performance.py` — trend calculation, risk-contribution ranking
- `concentration.py` — single-position and dimension-level concentration
- `material_changes.py` — change-since-last-interaction date logic
- `prioritize.py` — the combined, ranked priority list per portfolio
- `state/snapshot.py`, `diff.py`, `store.py`, `refresh.py` — snapshot
  persistence, diffing (including a manufactured-real-change check), and
  the empty-diff-on-repeat-call guarantee
- `enrichment/house_view.py` — mock house-view comparison, all four outcomes
  (`aligned`/`opposite`/`at_target`/`not_applicable`) verified to occur
  across real clients
- `enrichment/market_news.py` — security-name cleaning (95.8% real-data
  coverage, locked in by a regression test), search-term selection including
  the fund→sector-theme fallback (see below); the actual network fetch is
  NOT covered by this suite (see `enrichment` section)
- `synthesis/context_builder.py` — assembling every layer's output into
  one `BriefingContext`, including the state-diff-vs-note-proxy fallback
- `synthesis/prompt_builder.py` — every formatting function tested in
  isolation, plus the house-view actionable-vs-aligned filtering logic
- `synthesis/briefing_generator.py` — response parsing, markdown-fence
  stripping, missing-key/error handling, all against a fake client (no
  network); the real API call is NOT covered by this suite (see below)

`tests/test_real_data_regression.py` re-runs the checks we did by hand
against the real 47-client dataset (all clients build without error, no
stray untranslated SAA categories anywhere, the specific `CASE-002` numbers
that caught the fund-translation bug, the `CASE-008` orphaned-proposal edge
case, house-view outcome diversity, security-name-cleaner coverage). It's
skipped — not failed — if the real files aren't present; point
`UNRISKOMEGA_DATA_DIR` at a folder containing `clients.json` and
`reference.json` to run it (defaults to `data/core-case/portfolio-data/`,
this team's repo layout).

## Usage

```python
from data_layer import load_clients, load_reference, ReferenceIndex, build_client_view

clients = load_clients("clients.json")          # path or file-like object
reference = load_reference("reference.json")
ref = ReferenceIndex(reference)                  # build lookup indices once

for client in clients:
    view = build_client_view(client, ref)        # one resolved object per client
```

`view` contains, already joined and unit-normalized:
- client identity, risk profile, ESG profile
- portfolios, with each security position resolved to its full `Securities`
  row, plus fund look-through and SAA deviation (actual vs. target, per
  dimension: AssetClass / CurrencyGroup / CountryGroup / Industry)
- active suitability violations, with per-client overrides already filtered
  out
- proposals, transactions, tags, notes

## `data_layer` — files

| File | Responsibility |
|---|---|
| `loader.py` | Reads and parses the two JSON files. No validation beyond top-level shape. |
| `reference_index.py` | `ReferenceIndex` — id-keyed lookups for every `reference.json` collection, plus the plain→SAA category translation table (see below). |
| `fund_lookthrough.py` | Resolves a fund's underlying breakdown (`FundUnbundlingMappings`) into SAA-comparable categories and 0–1 weights. |
| `saa.py` | Compares a portfolio's actual exposure (fund-look-through-aware) against its SAA targets, per dimension. |
| `violations.py` | Filters `SuitabilityViolations` against `IndividualRuleOverrides`, attaches the full rule definition. |
| `flatten.py` | Orchestrator — `build_client_view()` / `build_portfolio_view()` tie everything above into one resolved object. |

## `analysis_layer` — deterministic "what matters" (no LLM)

Sits on top of `data_layer`'s output and produces structured, ranked facts —
still no narrative, that's the synthesis layer's job, coming next.

| File | Responsibility |
|---|---|
| `performance.py` | Portfolio value trend (from `PerformanceHistory`) and top risk contributors (ranked by `ContributionVolatility` — see scope note below). |
| `concentration.py` | Largest individual positions, and largest exposure per SAA dimension (fund-look-through-aware, reuses `data_layer.saa`). |
| `material_changes.py` | Change in portfolio value since the last client interaction, using the most recent `ClientNotes` date as a proxy timestamp (documented approximation — see below). |
| `prioritize.py` | Orchestrator — `build_client_priorities()` combines violations, SAA breaches, concentration, performance, and risk contributors into one ranked list per portfolio. |

```python
from data_layer import load_clients, load_reference, ReferenceIndex, build_client_view
from analysis_layer import build_client_priorities

clients = load_clients("clients.json")
reference = load_reference("reference.json")
ref = ReferenceIndex(reference)

for client in clients:
    view = build_client_view(client, ref)
    priorities = build_client_priorities(view, ref)  # one bundle per portfolio
```

Each bundle: `portfolio_id`, `portfolio_name`, `priorities` (violations + SAA
breaches + concentration flags, sorted highest-severity first),
`performance` (trend), `top_risk_contributors`, `change_since_last_interaction`.

**Two scope notes, not bugs:**
- The schema has per-position **risk** contribution (`ContributionVolatility`)
  but no per-position **return** contribution — only portfolio-level
  `PerformanceYTD`/`PerformanceHistory`. `top_risk_contributors` ranks by
  risk, because that's genuinely what the data supports.
- There's no explicit "last client interaction" field, so
  `material_changes.py` uses the most recent `ClientNotes` date as a proxy.
  For ~40% of portfolios in the real dataset (23/57 checked), the most
  recent note postdates the latest available `PerformanceHistory` point, so
  `change` comes back as `0.0` (nothing to compare against, not a real
  "no change" signal). Worth keeping in mind when the synthesis layer
  writes this into prose — a `0.0` here shouldn't be read as "confirmed
  unchanged."

**One real data gap found and handled:** 2 of 54 `SuitabilityRules` (e.g.
`"Volatility range undershot (portfolio risk too low)"`) have an empty
`Description` everywhere in the source data. `prioritize.py` falls back to
the `RuleCode` itself in that case, which happens to already be readable
English for both affected rules. Also worth noting: `RuleDescription` is
native-language text (mostly German) while the `RuleCode` fallback is
English — the resulting priority descriptions are a genuine language mix,
expected per `DATA.md`, and left for the synthesis (LLM) layer to normalize
rather than silently translated here.

## `state` — persistent client state, so "what changed" is exact, not guessed

`analysis_layer/material_changes.py` approximates "change since last
interaction" from a client note's date against raw performance history —
useful as a fallback, but imprecise (in the real dataset, ~40% of the time
the note postdates the available history and the comparison collapses to a
meaningless `0.0`). `state/` replaces that with something exact: it persists
a compact snapshot of each portfolio after every briefing, and on the next
call diffs the newly computed state against that saved snapshot — an actual
comparison of two known points, not an inference.

| File | Responsibility |
|---|---|
| `snapshot.py` | Builds a small, storable snapshot (`portfolio_value`, `allocation` per dimension, top positions, active violation codes) from `data_layer` + `analysis_layer` output. |
| `diff.py` | Compares two snapshots for the same portfolio: value change, allocation moves above a 0.5pt noise threshold, violations newly appeared/resolved, positions entering/exiting the top 5. |
| `store.py` | File-based persistence, one JSON file per client under `.state/snapshots/` (swappable for a real DB later without touching `snapshot.py`/`diff.py`). |
| `events.py` | Turns a diff into short human-readable strings for a rolling, capped (20-entry) per-client event log — the longer-range "history", not just the latest diff. |
| `refresh.py` | Orchestrator — `refresh_client_state()` is the one call the API layer makes: loads previous state, snapshots current state, diffs them, saves the new baseline, returns both. |

```python
from state import refresh_client_state

result = refresh_client_state(client_view, priority_bundles)
# result["portfolios"][portfolio_id]["diff"]["is_first_interaction"]  -> True on a client's first-ever briefing
# result["portfolios"][portfolio_id]["diff"]["violations_new"]        -> exact list, not inferred
# result["events_log"]                                                -> rolling history across many past calls
```

Calling this twice in a row with unchanged data correctly returns an empty
diff on the second call — not because nothing happened in the underlying
data, but because nothing happened *since the first call*, which is exactly
the distinction the case's "material changes since the previous client
interaction" requirement is asking for.

**Design choice, worth knowing:** state is saved automatically every time
`refresh_client_state()` runs, i.e. every time a briefing is generated. That
means the diff always answers "since the last time a briefing was
generated for this client," not "since the last real phone call." A
production version might instead snapshot only when an advisor explicitly
confirms the call happened — noted here rather than silently assumed.

## `enrichment` — house view comparison and market news

| File | Responsibility |
|---|---|
| `house_view.py` | Mock bank CIO tactical view (11 calls across the real dataset's actual SAA categories) + `compare_portfolio_to_house_view()`, which tells you exactly how a client's current position relates to it. |
| `market_news.py` | Decides WHAT to search news for (`relevant_search_terms()`), cleans messy Swiss/German security names into usable queries (`clean_security_name()`), and fetches/tags articles (`fetch_relevant_news()`). Split deliberately — see below. |

### House view

```python
from enrichment.house_view import compare_portfolio_to_house_view

result = compare_portfolio_to_house_view(portfolio)
# [{"category": "Shares", "house_view_stance": "overweight",
#   "relative_position": "aligned" | "opposite" | "at_target" | "not_applicable",
#   "client_actual": 0.52, "client_target": 0.50,
#   "as_of": "2026-09-01", "source": "mock", "is_mock": True, ...}, ...]
```

Four states, not two, and being exactly at the client's own SAA target is
never conflated with "aligned": `aligned` means the client is already
tilted the *same direction* as the bank's call, past their own target;
`at_target` means the client is sitting exactly at that target — a
tactical overweight/underweight call is a call to move AWAY from the
baseline, so being exactly at it means the client hasn't acted on it in
either direction, and narrating that as "aligned with an overweight call"
would misrepresent the client's actual position. `opposite` covers both
of the old `underexposed`/`overexposed` cases — the client tilted away
from what the house view recommends, whichever direction that is.

`compare_portfolio_to_house_view()` takes a `HouseViewProvider` (defaults
to `MockHouseViewProvider()`, which returns `house_view.py`'s hardcoded
mock list — the case brief explicitly allows mock CIO data). Every row it
returns carries `as_of`, `source`, and `is_mock` — swapping in a real feed
means writing a `HouseViewProvider` (or wrapping fetched rows in
`StaticHouseViewProvider(rows, source="...", as_of="...")`), not touching
comparison logic. Category names match the real dataset's `SAA_*`
vocabulary exactly, verified against `reference.json`, so no translation
step is needed to compare against `data_layer`'s `saa_deviations` output
directly.

**The precedence rule reaches the model, not just this code.** A tactical
house view never overrides client suitability, active compliance
violations, or the portfolio's own SAA targets — `HOUSE_VIEW_PRECEDENCE_NOTE`
states this once, and `prompt_builder.py`'s `_format_house_view()` prepends
it to the house-view section of every prompt unconditionally (even when
there's nothing else to say about the house view at all), so it's an
instruction the model actually receives rather than an assumption that
only ever lived in code comments.

### Market news — network-dependent, split into testable and untested parts

**Hard budgets** (`enrichment/market_news.py` constants): at most **5** search
subjects per portfolio (`BUDGET_MAX_SEARCH_SUBJECTS`), at most **2** articles
per subject (`BUDGET_MAX_ARTICLES_PER_SUBJECT`), at most **6** unique
retained articles overall (`BUDGET_MAX_RETAINED_ARTICLES`), and a **7-day
preferred / 14-day fallback** freshness window — an article with no
parseable `published_at` is never assumed fresh and is excluded rather than
guessed. When more than 5 candidate subjects exist, they're ranked by
`priority_score` (reusing `analysis_layer` v2's own ranking for
priority-derived subjects) before the cap is applied, so the budget never
silently drops the most important subject.

**Fully tested, no network needed:**
- `clean_security_name()` — this dataset's security names follow Swiss/German
  banking conventions (`"Namen-Aktie Nestle SA"`, `"Anteile -FB- Credit
  Suisse... - CSIF (CH) Bond Switzerland AAA-AA Blue"`, `"0.7 % John Deere
  Capital Corp 2021-01.11.28..."`) and are unusable as search queries as-is.
  Validated against all 504 real securities: **95.8% clean correctly**
  (locked in by a regression test — a drop below 90% fails CI). The
  remaining ~4% are structured products/derivatives and a handful of
  apparently-truncated `Name` values in the source data itself. These same
  unresolved names are excluded from search-term generation entirely
  (`_is_unresolved_security_name()`) — never guess an issuer from a raw,
  unrecognizable string.
- `relevant_search_terms()` — picks what to search for from: (1) the
  portfolio's top risk contributors, but only when `analysis_layer` v2's own
  `risk_attribution["status"]` says `ContributionVolatility` is usable
  (`invalid`/`unavailable` risk attribution never generates a news search —
  a data-quality problem must not get laundered into an apparently-confident
  news subject); (2) concentration and SAA-breach priority flags, reusing
  v2's `priority_score`; (3) material look-through industry exposure (≥10%
  absolute weight) even when nothing breached an SAA bound.
- `fetch_relevant_news_bundle()` — the full pipeline: fetch, apply the
  freshness window, merge cross-query duplicate articles (by link, or
  title+publisher) while **keeping every distinct match reason and
  connected `fact_id`** rather than dropping provenance, enforce the
  retention budget, and report one of four explicit statuses: `ok`,
  `partial` (got articles despite some subject failures), `no_news_found`
  (every subject fetched cleanly and genuinely found nothing usable), or
  `fetch_failed` (zero articles AND at least one subject raised — a real
  provider/network failure, which must never be narrated the same way as
  "no relevant news exists"). `fetch_relevant_news()` remains as a
  backward-compatible list-only wrapper around it.

Subjects are fetched **concurrently** (`concurrent.futures.ThreadPoolExecutor`,
capped at `MAX_CONCURRENT_FETCHES`) rather than one at a time — these are
small, independent, I/O-bound HTTP calls, so wall time is dominated by the
slowest single subject rather than their sum. One subject's fetch raising
never aborts the others; results are reassembled in the original `terms`
order before merging, so behavior (budgets, ranking, statuses, dedup) is
identical to a sequential fetch, just faster.

**Verified on the real API** (originally by Hamza without network access;
re-confirmed live during the house-view/market-news v2 integration — 3
search subjects for a real client, `YahooFinanceNewsProvider`, budget caps
applied: **~8.2s sequential → ~1.6-2.1s concurrent** end-to-end for the same
3 subjects and same `status="ok"` / 6-articles-retained result):
individual operating companies (e.g. `"Novartis AG"`,
`"Sandoz Group AG"`) return real news reliably. **Fund/ETF/index names
return nothing** (0/6 in testing) — they aren't "story" securities with
their own coverage. Since a large share of this dataset's holdings are
funds, `relevant_search_terms()` detects a fund position (via
`IsUnbundlingEnabled`, when a `ReferenceIndex` is passed as `ref=`) and
searches its **largest underlying sector exposure BY ABSOLUTE WEIGHT**
instead of its own name — `abs()`, not a plain `max()`, because a fund's
short/hedging positions can carry negative look-through weights, and a
plain max would let a small long position beat a much larger short one
just because of sign:

```python
from enrichment.market_news import relevant_search_terms, fetch_relevant_news_bundle, YahooFinanceNewsProvider

terms = relevant_search_terms(portfolio, priorities_bundle, ref=ref)
# a fund position generates a "sector" term (e.g. "Health Care") instead of
# a "security" term with its own unsearchable name

bundle = fetch_relevant_news_bundle(terms, YahooFinanceNewsProvider())
# {"status": "ok" | "partial" | "no_news_found" | "fetch_failed",
#  "reasons": [...], "articles": [...], "term_results": [...],
#  "freshness_window_used": "preferred_7d" | "fallback_14d" | "none"}
```

This is not just a workaround for a bad hit rate — sector-level news is
arguably *more* relevant to the case's "connection to the portfolio"
requirement than company news about an ETF issuer would be anyway, since
that's what actually explains a diversified fund position's performance.

**`YahooFinanceNewsProvider` has genuine network dependency** — confirm it
still works before a demo (APIs change): `pip install yfinance`, then fetch
a few real cleaned security names and a few fund-derived sector names, check
you're getting real articles back, not silent empty results. `FakeNewsProvider`
exists for writing tests without hitting the network.

## `synthesis` — turning facts into the actual briefing

| File | Responsibility |
|---|---|
| `context_builder.py` | Assembles every upstream layer's output into one `BriefingContext` dict, per portfolio. Plain data, no prose. |
| `prompt_builder.py` | Turns a `BriefingContext` into the actual `{system, messages}` prompt. This is where the case's "one coherent narrative, not stitched summaries" requirement is enforced. |
| `briefing_generator.py` | Standalone model call used by scripts and tests: calls OpenAI Chat Completions, returns `{recent_development, health_check, outlook_and_actions, read_time_estimate_seconds}`. Not called by `server.py` — see below. |

```python
from synthesis.context_builder import build_briefing_context
from synthesis.prompt_builder import build_prompt

context = build_briefing_context(
    client_view, priority_bundle, state_result, house_view_alignment, news_bundle=news_bundle
)
# news_bundle (enrichment.market_news.fetch_relevant_news_bundle() output) is
# preferred over the older news_articles=<list> form because it carries the
# fetch status — build_briefing_context() never fabricates a fetch_failed
# vs. no_news_found distinction that wasn't actually reported to it.
prompt = build_prompt(context)
# prompt["system"]  -> fixed instructions: 3 required sections, 4 required
#                       questions, "one narrative" constraint, JSON output format
# prompt["messages"] -> [{"role": "user", "content": "<all the client's facts, as prose>"}]
```

**Design**: `prompt_builder.py` is split into two testable pieces on purpose.
`context_to_prose()` converts every part of the context into readable,
labeled text fragments first — client/portfolio summary, performance,
priorities, risk contributors, change since last interaction, house view,
news — each with its own formatting function, each independently tested
with zero LLM calls. `build_prompt()` then wraps those fragments with the
fixed system instructions. Nothing here calls a model; that's
`briefing_generator.py`'s job, next.

**Two judgment calls baked into the system prompt, worth knowing:**
- The model is explicitly told the priority list's ranking is a simple
  rule-based sort (compliance severity), not a judgment call about what
  actually matters most for this client — and told to use its own judgment
  rather than just narrate the list in order. This was a known weak spot in
  `analysis_layer/prioritize.py` (flat 20%-threshold concentration flag, no
  weighting between issue types); rather than fix the ranking logic itself,
  the fix is pushed to the layer that's actually meant to make judgment
  calls.
- House view alignment is filtered before it reaches the prompt: only
  `opposite` categories (capped at 5) get full detail; `aligned` and
  `at_target` categories are each compressed into one summary line (kept
  separate from each other — being at_target is not the same fact as being
  aligned). Without this, a portfolio with many SAA categories produced a
  house-view section longer than the rest of the prompt combined — almost
  entirely "nothing to act on here" content that would've buried the
  genuinely interesting divergences. `HOUSE_VIEW_PRECEDENCE_NOTE` is
  prepended unconditionally regardless of this filtering.

**Validated against all 47 real clients**: no crashes, every prompt stays
well under a sanity-checked length ceiling (max observed ~4.8K characters),
client names and required section keys always present in the output.

**Guarding against fabricated causal attribution.** An LLM asked to
"identify the main drivers" of a value change will do so even when the
data provides no legitimate explanation — e.g. a heavily liquid/cash
portfolio still losing value, with no security-level risk contributors to
blame it on. Note the schema itself has **no cash-flow ledger, no fee
schedule, and no historical FX-rate table** — so those causes can never be
confirmed or quantified from this data either, only flagged as plausible
gaps worth an advisor's follow-up.

- `analysis_layer.concentration.non_base_currency_exposure()` computes a
  real, code-derived currency-EXPOSURE fact (share of the portfolio held
  in a currency other than `PortfolioCurrency`) — explicitly NOT an FX
  return-attribution number, since there's no rate history to compute one.
- `context_builder.py`'s `attribution_caveat` bundles this, the portfolio's
  liquidity ratio, and whether any risk contributors exist at all into one
  plain-data fact — computed in code, not inferred by the model.
- `prompt_builder.py` surfaces it as its own `DATA AVAILABILITY FOR
  ATTRIBUTING THIS CHANGE` prompt section, and `SYSTEM_PROMPT` has an
  explicit rule: when the value change isn't explained by the data
  provided, say the cause isn't identifiable and recommend checking cash
  flows, fees, and currency movements — never invent a plausible-sounding
  story. The risk-contributors section also states inline that volatility
  contribution is a forward-looking risk measure, not a confirmed
  explanation of a realized value change.
- `tests/test_attribution_regression.py` is a live, OPENAI_API_KEY-gated
  regression test (skipped, not failed, without a key) that builds a
  100%-liquid, declining-value portfolio with zero holdings data and calls
  the real model, checking the response for fabricated-cause phrases
  (negation-aware, since "not attributable to..." is the correct, desired
  hedge, not a violation). Confirmed live: `gpt-4o` correctly responded
  "this change in value is not attributable to investment holdings... may
  be due to... cash flows, fees, or currency movements" for exactly this
  fixture.

### `briefing_generator.py` — standalone model call (scripts / tests)

```python
from synthesis.briefing_generator import generate_briefing

briefing = generate_briefing(context)
# {"recent_development": str, "health_check": str, "outlook_and_actions": str,
#  "read_time_estimate_seconds": int, "raw_model_response": str}
```

Uses OpenAI Chat Completions (`DEFAULT_MODEL = "gpt-4o"`), strict JSON mode
(`response_format={"type": "json_object"}`), retries up to 3 times.
Raises `BriefingGenerationError` on every failure mode (API error, invalid
JSON, missing required key, `finish_reason: "length"` truncation).

**Note:** `server.py` does **not** call `generate_briefing()`. It has its own
`_generate()` function that uses the same OpenAI client and JSON mode but a
different system prompt and output schema — see `server.py` below.

## `server.py` — FastAPI entry point

Orchestrates every layer and exposes two JSON endpoints plus the demo front end.

| Endpoint | What it does |
|---|---|
| `GET /api/clients` | Returns all clients sorted by name: `[{id, name, type, portfolios: [{id, name}]}]`. Populated from `clients.json` at startup — used by the demo picker. |
| `POST /api/briefing` | Accepts `{client_id, portfolio_id?, scope?}`. Runs the full pipeline (data → analysis → state diff → house view → context → prompt → model) and returns the briefing. Results are cached in memory by `(client_id, portfolio_id)`. |
| `GET /` (and all static paths) | Serves `demo/static/` — the single-page demo front end. |

**`POST /api/briefing` response shape:**

```json
{
  "client":   {"name": "…", "id": "…", "type": "…", "profile": "…", "assets_chf": "…", "age": null},
  "headline": "One sentence — the single most important thing right now.",
  "attention": [
    {"level": "critical|warning|info", "title": "…", "detail": "…", "source": "<data field name>"}
  ],
  "since_last":     ["…"],
  "talking_points": ["…"],
  "sources": [
    {"section": "Suitability violations", "field": "active_violations", "detail": "13 active — 7 Error, 6 Warning"},
    {"section": "SAA target deviations",  "field": "saa_target_deviations", "detail": "5 dimensions out of band; largest: Swiss francs +23.7 pp"},
    "…"
  ]
}
```

`sources` is built deterministically from the pipeline data before the model
call — it lists every data section that was included in the prompt, with exact
counts and values. It is never generated by the model, so it is always
traceable back to a specific field in the source data.

**`_generate()` vs `generate_briefing()`:** `server.py` defines its own
`_generate()` that calls OpenAI Chat Completions directly (same `_default_client()`
and `response_format={"type":"json_object"}` from `briefing_generator.py`, but
a different system prompt targeting the `headline/attention/since_last/talking_points`
schema above). The `generate_briefing()` function in `briefing_generator.py`
uses a three-section prose schema and is used by standalone scripts and tests,
not by the API.

## The one non-obvious piece: category translation

`FundUnbundlingMappings` only gives a fund's breakdown in **plain, fine-grained**
category names (e.g. `"Equities EmMa"`), never in the coarser `SAA_*` names
that `StrategicAssetAllocations.Mappings` targets are set against. Comparing
them directly is wrong and silently creates phantom categories.

`ReferenceIndex` derives the plain → SAA translation from `Securities[]`
itself (any security that has both fields gives one training pair), exposed
via:

- `to_saa_category(dimension, plain_name)` — direct lookup
- `catch_all_saa_category(dimension)` — for names with no direct pairing
  (e.g. an exotic currency that only ever appears inside a fund, never as a
  security's own holding): if exactly one SAA category is never itself used
  as a plain name, it's inferred as the "everything else" bucket. Returns
  `None`, not a guess, when that's ambiguous.

Validated against the real 47-client dataset: `AssetClass`, `CountryGroup`,
and `Industry` translate fully with no fallback needed; `CurrencyGroup` needed
the catch-all (correctly inferred as `"Andere"`) for currencies with no
direct holdings anywhere in the dataset.

## Known data quirks (source data, not this code)

- `AccountPositions[].IBAN` is real, passed through as-is. Don't log or
  surface it further.
- One client (`CASE-008` in the current export) has a finalized proposal
  pointing at a `PortfolioId` that isn't one of their own portfolios. Handled
  gracefully here (nothing crashes), but not resolved — downstream code
  touching proposals should be ready for a link that doesn't resolve.
- Dates are shifted forward by a constant offset; only relative
  ordering/spacing is meaningful, except `PriceDateUtc` / `FactoryDateUtc`.
- `"Alcon AG"` (a genuine, well-known global company) returned no news via
  `YahooFinanceNewsProvider` in testing, unlike other similarly plain
  Swiss company names that worked fine. Not yet investigated — worth a look
  before assuming every plain company name resolves reliably.

## Git

Add `.state/` to your `.gitignore` — it's local, per-machine persisted
client state, not source. Each teammate's `.state/` will diverge, which is
expected and fine; it's not something to sync or commit.