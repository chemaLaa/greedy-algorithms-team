from enrichment.market_news import YahooFinanceNewsProvider

provider = YahooFinanceNewsProvider()
queries = [
    "Alcon AG",
    "Novartis AG",
    "Sandoz Group AG",
    "CSIF (CH) Equity SPI ESG Multi Premia Blue",
    "CSIF (CH) Equity Switzerland Large Cap Blue",
    "MSCI Switzerland IMI Socially Responsible",
    "MSCI World Socially Responsible UCITS ETF",
    "iShares Listed Private Equity UCITS ETF",
    "iShares MSCI World Minimum Volatility UCITS ETF",
    "SLI (R)",
    "SMI (R)",
]

hits, misses = 0, 0
for q in queries:
    articles = provider.fetch(q)
    status = f"{len(articles)} article(s)" if articles else "NOTHING"
    print(f"{q:55s} -> {status}")
    if articles:
        hits += 1
    else:
        misses += 1

print()
print(f"{hits}/{len(queries)} queries returned something, {misses} returned nothing")