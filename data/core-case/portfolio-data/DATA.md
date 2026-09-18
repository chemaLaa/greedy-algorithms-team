# Case Study Data Reference

This describes the two JSON files that make up this case study: `data/clients.json` and
`data/reference.json`. Together they cover 47 client/portfolio bundles from a wealth-advisory system,
restructured for external use — no application code is required to read or use them; they're plain,
self-contained JSON.

## The two files, at a glance

| File | Shape | Contains |
|---|---|---|
| `clients.json` | Array of **Client** objects (47) | Everything specific to one client: identity, portfolios, holdings, proposals, transactions, rule violations, tags, notes |
| `reference.json` | One **object** with ~10 named collections | Shared/lookup data referenced by the clients above: security master data, fund breakdowns, rule definitions, risk/ESG profiles, advisory configuration, target allocations |
| *(3 more files, not included yet)* | Same shape as `clients.json` | Three additional client-data files will be provided later, for the live use-case presentation — make sure your solution can accept new files in this shape (e.g. via an upload feature) rather than only working with the file handed over |

The split mirrors a normal relational design: `clients.json` is "fact" data, `reference.json` is
"dimension"/lookup data. Many fields in `clients.json` are already resolved to a human-readable name
(so you don't strictly need to cross-reference anything for basic display), but the underlying IDs are
also present so you can look up full detail — e.g. a client's `RiskProfileId` resolves to a row in
`reference.json`'s `RiskProfiles` with volatility/PRC ceilings that aren't repeated on every client.

**Important**: `reference.json` is trimmed to only the rows actually referenced by the 47 clients in
`clients.json` — it is *not* a full dump of the source system's lookup tables (e.g. no currency nobody
holds, no security nobody owns).

**Also important — optional/absent keys**: neither file uses "include nulls" JSON serialization. A
field that is `null` for a given record is simply **absent** from that object, not present with a
`null` value — and a whole collection in `reference.json` can be **entirely absent** if none of the
current clients reference it (e.g. `EsgProfiles` is absent in a run where no client has an ESG profile
set). Always code defensively (`obj.Field ?? fallback`, `(collection || [])`), never assume a key
exists.

**Also important — dates are shifted forward.** Dates across the export are shifted forward by a
constant offset so they read as current rather than as a stale historical snapshot — the *relative*
ordering and spacing of dates is preserved, but no date should be read as "as of [exact real calendar
date]" unless it's a price/factory-calculation date (those are independently live-refreshed and not
shifted).

---

## `clients.json` — Client object

One array element per client. Top-level fields:

| Field | Type | Notes |
|---|---|---|
| `ClientId` | number | Internal numeric ID (source system) |
| `ClientRef` | string | Sequential `CASE-001`, `CASE-002`, ... — use this as the human-facing identifier |
| `FirstName` / `LastName` | string | Absent (not null) for company clients |
| `Company` | string | Only present when `IsClientACompany` is true |
| `IsClientACompany` | boolean | |
| `IsEmployee` | boolean | Whether this client is a bank employee |
| `RegulatoryClientTypeId` / `RegulatoryClientTypeName` | number / string | e.g. "Private client". No matching lookup collection in `reference.json` — treat `RegulatoryClientTypeName` as the canonical value |
| `ReportingCurrency` | string | ISO currency code, e.g. `"CHF"` |
| `RiskProfileId` / `RiskProfileName` | number / string | Joins to `reference.json` → `RiskProfiles[].Id` for volatility/PRC ceiling detail |
| `EsgProfileId` / `EsgProfileName` | number / string | Absent if the client has no ESG profile assigned. Joins to `reference.json` → `EsgProfiles[].Id` |
| `Birthday` | date string (`yyyy-MM-dd`) | Absent for company clients |
| `ProfilingDateUtc` | date-time string | When the client's risk profile was last assessed |
| `AssetsUnderManagementInDefaultCurrency` | number | In `ReportingCurrency` |
| `LiquidityInDefaultCurrency` | number | In `ReportingCurrency` |
| `Portfolios` | array | See below |
| `Proposals` | array | See below |
| `Transactions` | array | See below |
| `SuitabilityViolations` | array | See below |
| `IndividualRuleOverrides` | array | See below |
| `Tags` | array | See below |
| `ClientNotes` | array | See below |

### `Portfolios[]`

| Field | Type | Notes |
|---|---|---|
| `PortfolioId` | number | |
| `PublicGuid` | string (GUID) | |
| `PortfolioNr` | string | `CASE-001-01`, etc. |
| `Name` | string | Portfolio name (e.g. "Vorsorge Indiv") |
| `PortfolioCurrency` | string | This portfolio's own reporting currency |
| `IsProfessionalTreasury` | boolean | Exists in the source schema but is `null` for every portfolio at this bank, so it's always **absent** here |
| `StrategicAssetAllocationId` | number | Joins to `reference.json` → `StrategicAssetAllocations[].Id` — this portfolio's target allocation policy |
| `InvestmentServiceId` / `InvestmentServiceName` | number / string | The advisory service this portfolio is under (e.g. "Investment Advisory"). Resolved via the SAA above, not a direct portfolio column in the source system |
| `StrategyId` / `StrategyName` | number / string | Resolved the same way. Joins to `reference.json` → `Strategies[].Id` |
| `ReferenceCurrency` | string | The SAA's own reference currency (may differ from `PortfolioCurrency`) |
| `AssetsUnderManagementInDefaultCurrency` / `LiquidityInDefaultCurrency` | number | In the *client's* `ReportingCurrency`, not `PortfolioCurrency` |
| `Volatility` / `ExpectedReturn` / `ValueAtRisk` / `PerformanceYTD` | number | Fractions (0–1), e.g. `0.0825` = 8.25%. Live risk-engine output |
| `FactoryDateUtc` | date-time string | When the risk figures above were last calculated |
| `SecurityPositions` | array | See below |
| `AccountPositions` | array | See below |
| `PerformanceHistory` | array | `[{ "Date": "yyyy-MM-01", "Value": <NAV number> }, ...]`, ~5 years monthly |

#### `Portfolios[].SecurityPositions[]`

| Field | Type | Notes |
|---|---|---|
| `SecurityId` | number | **Primary join key** → `reference.json` → `Securities[].Id`. Prefer this over `Isin` — the same ISIN can appear as multiple `Security` rows (one per currency share class), so an ISIN-only match can be ambiguous |
| `Isin` / `Valor` | string | Present for convenience/fallback matching |
| `SecurityName` | string | |
| `Quantity` / `PricePerUnit` | number | |
| `Currency` | string | The position's own currency (may differ from `PortfolioCurrency`) |
| `TotalAmountInPortfolioCurrency` | number | Converted to `PortfolioCurrency` |
| `PortfolioValuePercentage` | number | **Fraction, 0–1** (not 0–100) — e.g. `0.235` = 23.5% of the portfolio |
| `MarginalContributionToRisk` | number | Raw, unweighted marginal risk contribution — **not** the figure that sums to `Portfolio.Volatility` |
| `ContributionVolatility` | number | `MarginalContributionToRisk × PortfolioValuePercentage` — this is what sums to `Portfolio.Volatility` across all positions in the portfolio |

#### `Portfolios[].AccountPositions[]`

Cash/account positions. Same shared columns as security positions (`Currency`,
`TotalAmountInPortfolioCurrency`, `PortfolioValuePercentage`, `MarginalContributionToRisk`,
`ContributionVolatility` — same conventions as above), plus:

| Field | Type | Notes |
|---|---|---|
| `AccountName` | string | e.g. "Privatkonto USD" |
| `IBAN` | string | **Real, passed through as-is** from the source system — a known gap, not an oversight. Treat any IBAN value here as potentially real and don't publish it further |

**Caution — `Currency` is not always an ISO currency code.** A small number of accounts hold
cryptocurrency, represented with the crypto ticker (`"BTC"`, `"ETH"`, `"DOT"`, `"SOL"`, `"SHIB"`, ...)
standing in for `Currency` instead of a real ISO-4217 code — the source system has no native concept of
a crypto holding, so this reuses the cash-account shape rather than inventing a new one.
`TotalAmountInPortfolioCurrency` is still a real CHF number, so it's safe to sum/aggregate — just don't
assume every `AccountPositions[].Currency` value is a tradable fiat currency if you're cross-referencing
it against an FX table.

### `Proposals[]`

An investment proposal (Anlagevorschlag) — a specific set of trades proposed to/by the client.

| Field | Type | Notes |
|---|---|---|
| `ProposalId` | number | |
| `PublicGuid` | string (GUID) | |
| `PortfolioId` | number | Joins to `Portfolios[].PortfolioId` on the *same client* |
| `ProposalStatusId` / `ProposalStatusName` | number / string | e.g. "Finalized". Joins to `reference.json` → `ProposalStatuses[].Id` |
| `AdvisoryTypeId` / `AdvisoryTypeName` | number / string | Joins to `reference.json` → `AdvisoryTypes[].Id` |
| `Currency` | string | |
| `StrategicAssetAllocationId` | number | Joins to `reference.json` → `StrategicAssetAllocations[].Id` |
| `ProposedDateUTC` / `FinalizedDateUTC` / `TransactionsSubmittedDateUTC` | date-time string | The latter two are absent if the proposal never reached that stage |
| `Reason` | string | Reason for the consultation |
| `Notes` | string | Free-text notes on the proposal (real, if present) |
| `ExpectedReturn` / `Volatility` / `ValueAtRisk` | number | |
| `SecurityPositions` | array | Proposed security trades — `Isin`, `SecurityName`, `Quantity`, `PricePerUnit`, `Currency`, `TotalAmountInProposalCurrency`, `ProposalValuePercentage` (fraction, 0–1) |
| `AccountPositions` | array | Proposed cash movements — `AccountName`, `Currency`, `Amount`, `TotalAmountInProposalCurrency` |
| `Contracts` | array | `ContractType`, `IsCoded`, `SignDate` — often empty |
| `StandingOrders` | array | `Amount`, `Frequency`, `PaymentDay`, `PaymentMonth`, `PaymentYear` — often empty |

### `Transactions[]`

Order records submitted from a proposal. Only transactions tied to a still-**active** proposal are
included (the source system can have transactions pointing at a since-deactivated/superseded proposal;
those are dropped rather than shown as "unlinked").

| Field | Type | Notes |
|---|---|---|
| `TransactionId` | number | |
| `PublicGuid` | string (GUID) | |
| `ProposalId` | number | Joins to `Proposals[].ProposalId` on the *same client* |
| `SecurityId` | number | Joins to `reference.json` → `Securities[].Id` (absent for a pure cash transaction) |
| `Isin` / `SecurityName` | string | |
| `QuantityForTransaction` / `TotalAmount` | number | |
| `Currency` | string | |
| `IsExpiry` | boolean | `true` = an expiry/"Verfall" record, never order-submittable |
| `ForwardState` | number | Order-forwarding status code: `0` = OK, `2` = warning, other values exist but aren't decoded here |

### `SuitabilityViolations[]`

A currently-active suitability-rule violation on one of the client's portfolios.

| Field | Type | Notes |
|---|---|---|
| `Id` | number | |
| `RuleCode` | string | The rule's name (already English) — **join key** → `reference.json` → `SuitabilityRules[].RuleCode` (there's no separate numeric rule ID on this object) |
| `RuleDescription` | string | Longer description, native language (mostly German — no English text exists for this at the source) |
| `ErrorLevel` | number | `1` = warning, other values = error |
| `Severity` | string | Pre-resolved: `"Warning"` or `"Error"` |
| `PortfolioId` | number | Joins to `Portfolios[].PortfolioId` on the *same client* |
| `LastViolatedDateUTC` | date-time string | |
| `SecurityIsin` | string | Absent if the violation isn't tied to one specific security |
| `ViolationPath` | array or absent | The rule engine's resolved evaluation trace for *this* violation — real nested JSON, not a string. Each entry: `{ "FieldName": string, "LeftValue": number, "RightValue": number, "Operator": number }` — `LeftValue` is the actual value checked, `RightValue` is the threshold/comparison value, `Operator` is the engine's internal comparison-operator code (not decoded here). Absent (not `null`) for the small number of violations whose source data was corrupted upstream |

### `IndividualRuleOverrides[]`

Suitability rules explicitly overridden/disabled for this specific client. Just `RuleCode` and
`RuleDescription`, same meaning as above.

### `Tags[]`

See `reference.json` → `Tags[]` below for the full vocabulary.

| Field | Type | Notes |
|---|---|---|
| `TagName` | string | A region (e.g. `"Switzerland"`, `"North America"`) or industry sector (e.g. `"Health Care"`) |
| `TagTypeName` | string | `"Region"` or `"Industry"` |
| `Scope` | string | Always `"Client"` — these are client-level interest tags, not scoped to a specific portfolio/position |

### `ClientNotes[]`

A small pool of advisory notes, English only.

| Field | Type | Notes |
|---|---|---|
| `Note` | string | Free text, German or French |
| `CreatedByDateUTC` | date-time string | |

---

## `reference.json` — shared/lookup collections

A single object. Every collection below may be **entirely absent** if nothing in `clients.json`
references it for the current export run (see note at the top). Each is trimmed to only the rows
actually used by the current 47 clients.

### `Securities[]`

Instrument master data. **One row per instrument *per currency*** — the same ISIN can legitimately
appear as multiple rows (one per currency share class), so always match on `Id`, not `Isin` alone.

| Field | Type | Notes |
|---|---|---|
| `Id` | number | **Join key**, referenced from `SecurityPositions[].SecurityId`, `Transactions[].SecurityId`, `FundUnbundlingMappings[].FundSecurityId` |
| `Isin` / `Valor` / `Name` | string | |
| `SecurityTypeId` / `SecurityTypeName` | number / string | e.g. "Shares", "Investment fund", "Bond" |
| `Currency` | string | This security's own trading currency |
| `Assetclass` / `AssetClassName` | number / string | Granular classification (~200 distinct values), e.g. "Equities North America" |
| `Industry` / `IndustryName` | number / string | |
| `CountryId` / `CountryName` | number / string | Specific country, e.g. "Switzerland" |
| `CurrencyGroupName` | string | A currency grouping, distinct from `Currency` |
| `CountryGroupName` | string | A **regional** grouping (e.g. "Equities North America"), coarser than `CountryName` and using a *different* taxonomy — don't treat these as the same dimension |
| `SAA_AssetClassName` / `SAA_CurrencyGroupName` / `SAA_CountryGroupName` / `SAA_IndustryName` | string | This security's classification rolled up into the *same, coarser* buckets that `StrategicAssetAllocations[].Mappings` targets are set against (e.g. `AssetClassName` "Equities North America" → `SAA_AssetClassName` "Shares"). **Use these fields, not the plain ones above, when comparing actual holdings against SAA targets** — the plain fields use a finer taxonomy that won't match target category names |
| `IsMoneyMarket` / `IsTreasury` | boolean | |
| `EndOfDayPrice` | number | Last known price, in `Currency` |
| `PriceDateUtc` | date-time string | |
| `Volatility` / `ExpectedReturn` | number | The instrument's own standalone volatility/return |
| `SustainabilityRatingId` / `SustainabilityScore` | number | |
| `IsUnbundlingEnabled` | boolean | Whether a fund-breakdown exists — see `FundUnbundlingMappings` below |
| `MaturityDateUtc` | date-time string | Bonds etc. A far-future date (e.g. year 2299) means "no maturity / perpetual", not a data error |
| `PRC` | number | Product Risk Class |
| `YieldToMaturity` | number | |
| `SecurityInvestRatingId` / `SecurityInvestRatingName` | number / string | May be absent |
| `InRecommendationList` | boolean | |
| `ProductClassId` / `ProductClassName` | number / string | |

### `FundUnbundlingMappings[]`

The look-through breakdown of a fund's underlying holdings ("Fondsplitting") — one row per
fund × dimension-category combination.

| Field | Type | Notes |
|---|---|---|
| `FundSecurityId` | number | Joins to `Securities[].Id` (the fund itself) |
| `FundSecurityIsin` | string | |
| `AssetClassName` / `CurrencyGroupName` / `CountryGroupName` / `IndustryName` | string | Exactly one of these four is meaningful per intended *dimension* of breakdown — group and sum `Weight` by whichever one you're analyzing (asset class, currency, country, or industry) |
| `Weight` | number | **Percentage points, 0–100** (not a 0–1 fraction) — rows for one fund and one dimension sum to ~100 |

### `SuitabilityRules[]`

| Field | Type | Notes |
|---|---|---|
| `Id` | number | Internal ID — not referenced from the client side (see `SuitabilityViolations[].RuleCode`) |
| `RuleCode` | string | **Join key** from `SuitabilityViolations[].RuleCode` / `IndividualRuleOverrides[].RuleCode` |
| `Description` | string | Native language |
| `Level` | number | |
| `IsIndividual` | boolean | Whether this rule can be individually overridden per client |

### `RiskProfiles[]`

| Field | Type | Notes |
|---|---|---|
| `Id` | number | **Join key** from `Client.RiskProfileId` |
| `Name` / `Description` | string | |
| `RiskLevel` | number | |
| `MaxVola` / `MaxPRC` | number | Ceilings this profile allows |
| `EquityQuoteInPercent` | number | |

### `EsgProfiles[]`

Two profile definitions: a binary ESG-preference flag ("Yes"/"No").

| Field | Type | Notes |
|---|---|---|
| `Id` | number | **Join key** from `Client.EsgProfileId` |
| `Name` | string | `"Yes"` or `"No"` |
| `Level` / `ProfileType` | number | |
| `MinimumLevel` / `MaximumLevel` / `MinimumPositionLevel` | number | |

### `InvestmentServices[]`

| Field | Type | Notes |
|---|---|---|
| `Id` | number | **Join key** from `Portfolios[].InvestmentServiceId` |
| `Name` | string | e.g. "Investment Advisory", "Depository Advisory" |
| `IsVorsorge` | boolean | Whether this is a pension/retirement-focused service |

### `Strategies[]`

| Field | Type | Notes |
|---|---|---|
| `Id` | number | **Join key** from `Portfolios[].StrategyId` |
| `Name` | string | e.g. "Investor profile 5" |
| `RiskLevel` | number | |
| `VolatilityMinimum` / `VolatilityMaximum` | number | |

### `StrategicAssetAllocations[]`

A target allocation policy ("SAA") — what a portfolio *should* look like.

| Field | Type | Notes |
|---|---|---|
| `Id` | number | **Join key** from `Portfolios[].StrategicAssetAllocationId` / `Proposals[].StrategicAssetAllocationId` |
| `Name` / `Description` | string | |
| `InvestmentServiceId` / `StrategyId` | number | Cross-reference `InvestmentServices[]` / `Strategies[]` |
| `ReferenceCurrency` | string | |
| `Mappings` | array | The actual targets — see below |

#### `StrategicAssetAllocations[].Mappings[]`

Real target data. Despite the source system's underlying table also having country/currency/industry
columns alongside the asset-class one, in practice **each row sets a target for exactly one dimension**
— there is no true multi-dimensional combination to worry about.

| Field | Type | Notes |
|---|---|---|
| `Dimension` | string | Which dimension this target row is for: `"AssetClass"`, `"CurrencyGroup"`, `"CountryGroup"`, or `"Industry"` |
| `Category` | string | The target bucket's name, e.g. `"Shares"`, `"US-Dollar"`, `"North America"`, `"Industrials"` — matches `Securities[].SAA_AssetClassName` etc., **not** the plain `AssetClassName`/etc. fields |
| `MinPercentage` / `TargetPercentage` / `MaxPercentage` | number | **Fractions, 0–1** (not 0–100) — e.g. `0.97` = 97% |

### `Tags[]`

The full tag vocabulary (17 entries: 6 regions + 11 industries). Not trimmed to what's actually
assigned to a client; always all 17 — see `Client.Tags[]` above for which ones a given client has.

| Field | Type | Notes |
|---|---|---|
| `Id` | number | Not referenced from the client side — `Client.Tags[].TagName`/`TagTypeName` are already resolved |
| `Name` | string | e.g. `"Switzerland"`, `"Health Care"` |
| `TagTypeName` | string | `"Region"` or `"Industry"` |

### `RecommendationLists[]`

One entry: the bank's "Recommendation list free assets" (its other 2 real lists — a pension-specific
one and a general equity universe — aren't exported, not requested).

| Field | Type | Notes |
|---|---|---|
| `Id` | number | |
| `Name` | string | `"Recommendation list free assets"` |
| `Securities` | array | `{ "SecurityId": number, "Isin": string }` — `SecurityId` joins to `Securities[].Id` (guaranteed present, even for a security no client actually holds) |

### `ProposalStatuses[]`

| Field | Type | Notes |
|---|---|---|
| `Id` | number | **Join key** from `Proposals[].ProposalStatusId` |
| `Name` | string | e.g. "Finalized" |
| `IsArchived` / `AllowTransactionSubmit` | boolean | |

### `AdvisoryTypes[]`

| Field | Type | Notes |
|---|---|---|
| `Id` | number | **Join key** from `Proposals[].AdvisoryTypeId` |
| `Name` | string | |
| `IsProposal` / `IsPortfolioReview` | boolean | |

---

## How the two files link together — join-key cheat sheet

Every link below goes **from a field in `clients.json` to an `Id` (or `RuleCode`) in one of
`reference.json`'s collections**, except where noted as within-client.

| From (`clients.json`) | To (`reference.json`) | Notes |
|---|---|---|
| `Client.RiskProfileId` | `RiskProfiles[].Id` | |
| `Client.EsgProfileId` | `EsgProfiles[].Id` | Absent for some clients — see `Client.EsgProfileId` above |
| `Portfolios[].StrategicAssetAllocationId` | `StrategicAssetAllocations[].Id` | |
| `Portfolios[].InvestmentServiceId` | `InvestmentServices[].Id` | Already denormalized as `InvestmentServiceName` too |
| `Portfolios[].StrategyId` | `Strategies[].Id` | Already denormalized as `StrategyName` too |
| `Portfolios[].SecurityPositions[].SecurityId` | `Securities[].Id` | **Prefer over `Isin`** — see `Securities[]` notes |
| `Transactions[].SecurityId` | `Securities[].Id` | |
| `Proposals[].StrategicAssetAllocationId` | `StrategicAssetAllocations[].Id` | |
| `Proposals[].ProposalStatusId` | `ProposalStatuses[].Id` | Already denormalized as `ProposalStatusName` too |
| `Proposals[].AdvisoryTypeId` | `AdvisoryTypes[].Id` | Already denormalized as `AdvisoryTypeName` too |
| `SuitabilityViolations[].RuleCode` | `SuitabilityRules[].RuleCode` | Text-based join, not numeric — no rule ID is exposed on the violation itself |
| `IndividualRuleOverrides[].RuleCode` | `SuitabilityRules[].RuleCode` | Same as above |
| `Securities[].SAA_AssetClassName` (and the 3 sibling `SAA_*Name` fields) | `StrategicAssetAllocations[].Mappings[].Category` (where `Dimension` matches) | For comparing actual holdings against SAA targets — see `Securities[]` notes |
| `Client.Tags[].TagName` | `Tags[].Name` | Already denormalized (`TagTypeName` too) — this join only matters if you want the full vocabulary, e.g. to show unassigned tags |

Within `reference.json` itself (no `clients.json` involved): `RecommendationLists[].Securities[].SecurityId` joins to `Securities[].Id`.

**Within-client links** (both sides are arrays on the *same* Client object, no `reference.json`
involved):

| From | To |
|---|---|
| `Proposals[].PortfolioId` | `Portfolios[].PortfolioId` |
| `Transactions[].ProposalId` | `Proposals[].ProposalId` |
| `SuitabilityViolations[].PortfolioId` | `Portfolios[].PortfolioId` |

### Worked example: "what does this position's price/target look like?"

```
client.Portfolios[0].SecurityPositions[0].SecurityId  →  1234
                                                            │
reference.Securities.find(s => s.Id === 1234)              │  gives EndOfDayPrice, AssetClassName,
                                                            │  SAA_AssetClassName, ...
                                                            ▼
reference.StrategicAssetAllocations
  .find(saa => saa.Id === client.Portfolios[0].StrategicAssetAllocationId)
  .Mappings.filter(m => m.Dimension === "AssetClass")
  .find(m => m.Category === thatSecurity.SAA_AssetClassName)
                                                            →  TargetPercentage / MinPercentage / MaxPercentage
                                                               for this position's asset class
```
