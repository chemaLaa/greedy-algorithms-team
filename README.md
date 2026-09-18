# uro_briefing

Backend pipeline for the UnRiskOmega "From Ping to Pitch" briefing assistant:
loads the case data, joins and normalizes it, ranks what matters, compares it
to a mock bank house view, pulls relevant market news, and tracks client
state across calls so "what changed" is exact, not guessed. No LLM yet — this
is everything the synthesis (prompt + model call) layer will consume once
it's built.

**Layers, in dependency order:**
`data_layer` → `analysis_layer` → `state` / `enrichment` → *(not yet built)* `synthesis`

## Install / run

No dependencies beyond the Python standard library, **except**
`enrichment/market_news.py`'s live fetch, which needs `pip install yfinance`
(see the `enrichment` section below).

```bash
cd uro_briefing
python3 run_example.py            # data_layer against the synthetic fixture
python3 run_analysis_example.py   # analysis_layer against the synthetic fixture
```

## Testing

```bash
python3 run_tests.py          # zero dependencies, works anywhere
# or, if you have pytest installed:
pytest tests/                 # same test files, nicer output
```

147 tests, covering `data_layer`, `analysis_layer`, `state`, `enrichment`,
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
  (`aligned`/`underexposed`/`overexposed`/`not_applicable`) verified to occur
  across real clients
- `enrichment/market_news.py` — security-name cleaning (95.8% real-data
  coverage, locked in by a regression test), search-term selection including
  the fund→sector-theme fallback (see below); the actual network fetch is
  NOT covered by this suite (see `enrichment` section)
- `synthesis/context_builder.py` — assembling every layer's output into
  one `BriefingContext`, including the state-diff-vs-note-proxy fallback
- `synthesis/prompt_builder.py` — every formatting function tested in
  isolation, plus the house-view actionable-vs-aligned filtering logic

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
#   "relative_position": "aligned" | "underexposed" | "overexposed" | "not_applicable",
#   "client_actual": 0.52, "client_target": 0.50, ...}, ...]
```

`HOUSE_VIEW` in `house_view.py` is mock data (the case brief explicitly
allows this), not a real market forecast — category names match the real
dataset's `SAA_*` vocabulary exactly, verified against `reference.json`, so
no translation step is needed to compare against `data_layer`'s
`saa_deviations` output directly.

### Market news — network-dependent, split into testable and untested parts

**Fully tested, no network needed:**
- `clean_security_name()` — this dataset's security names follow Swiss/German
  banking conventions (`"Namen-Aktie Nestle SA"`, `"Anteile -FB- Credit
  Suisse... - CSIF (CH) Bond Switzerland AAA-AA Blue"`, `"0.7 % John Deere
  Capital Corp 2021-01.11.28..."`) and are unusable as search queries as-is.
  Validated against all 504 real securities: **95.8% clean correctly**
  (locked in by a regression test — a drop below 90% fails CI). The
  remaining ~4% are structured products/derivatives and a handful of
  apparently-truncated `Name` values in the source data itself — a small,
  bounded, documented limitation, not a silent failure.
- `relevant_search_terms()` — picks what to search for from the portfolio's
  own top risk contributors and priority flags, not anything generic.

**Verified on the real API (by Hamza, not in this sandbox — no network
access here):** individual operating companies (e.g. `"Novartis AG"`,
`"Sandoz Group AG"`) return real news reliably. **Fund/ETF/index names
return nothing** (0/6 in testing) — they aren't "story" securities with
their own coverage. Since a large share of this dataset's holdings are
funds, `relevant_search_terms()` detects a fund position (via
`IsUnbundlingEnabled`, when a `ReferenceIndex` is passed as `ref=`) and
searches its **largest underlying sector exposure** instead of its own name:

```python
from enrichment.market_news import relevant_search_terms, fetch_relevant_news, YahooFinanceNewsProvider

terms = relevant_search_terms(portfolio, priorities_bundle, ref=ref)
# a fund position generates a "sector" term (e.g. "Health Care") instead of
# a "security" term with its own unsearchable name

articles = fetch_relevant_news(terms, YahooFinanceNewsProvider())
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
| `briefing_generator.py` | *(not yet built)* — the actual model call. |

```python
from synthesis.context_builder import build_briefing_context
from synthesis.prompt_builder import build_prompt

context = build_briefing_context(client_view, priority_bundle, state_result, house_view_alignment, news_articles)
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
  `underexposed`/`overexposed` categories (capped at 5) get full detail,
  `aligned` categories are compressed into one summary line. Without this,
  a portfolio with many SAA categories produced a house-view section longer
  than the rest of the prompt combined — almost entirely "nothing to act on
  here" content that would've buried the genuinely interesting divergences.

**Validated against all 47 real clients**: no crashes, every prompt stays
well under a sanity-checked length ceiling (max observed ~4.8K characters),
client names and required section keys always present in the output.

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