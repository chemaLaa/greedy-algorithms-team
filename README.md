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
