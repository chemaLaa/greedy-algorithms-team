# uro_briefing/data_layer

Loads `clients.json` + `reference.json`, resolves every ID reference between
them, and produces one clean, fully-joined object per client. This is the
first layer of the pipeline — pure data loading and joining, no LLM calls, no
"what matters" judgment. That comes later.

## Install / run

No dependencies beyond the Python standard library.

```bash
cd uro_briefing
python3 run_example.py
```

`run_example.py` runs the pipeline against the synthetic fixtures in
`test_fixtures/` and prints the resolved output, useful as a quick sanity
check that the code still works after an edit.

## Testing

```bash
python3 run_tests.py          # zero dependencies, works anywhere
# or, if you have pytest installed:
pytest tests/                 # same test files, nicer output
```

77 tests, covering `data_layer`, `analysis_layer`, and `state`:
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

`tests/test_real_data_regression.py` re-runs the checks we did by hand
against the real 47-client dataset (all clients build without error, no
stray untranslated SAA categories anywhere, the specific `CASE-002` numbers
that caught the fund-translation bug, the `CASE-008` orphaned-proposal edge
case). It's skipped — not failed — if the real files aren't present; point
`UNRISKOMEGA_DATA_DIR` at a folder containing `clients.json` and
`reference.json` to run it (defaults to `/mnt/user-data/uploads`).

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

## Files

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
## Git

Add `.state/` to your `.gitignore` — it's local, per-machine persisted
client state, not source. Each teammate's `.state/` will diverge, which is
expected and fine; it's not something to sync or commit.
