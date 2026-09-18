"""
Smoke test / demo for the analysis layer: loads the synthetic fixtures,
runs the full priority-building pipeline, and prints the result.

Run: python3 run_analysis_example.py
"""
from data_layer import ReferenceIndex, build_client_view, load_clients, load_reference
from analysis_layer import build_client_priorities

clients = load_clients("test_fixtures/clients.sample.json")
reference = load_reference("test_fixtures/reference.sample.json")
ref = ReferenceIndex(reference)

client_view = build_client_view(clients[0], ref)
priority_bundles = build_client_priorities(client_view, ref)

print(f"=== {client_view['display_name']} ({client_view['client_ref']}) ===\n")

for bundle in priority_bundles:
    print(f"Portfolio: {bundle['portfolio_name']}")

    perf = bundle["performance"]
    print(f"  Latest value: {perf['latest_value']} (as of {perf['latest_date']})")
    if perf["change_since_previous_point"] is not None:
        print(
            f"  Change vs. previous point: {perf['change_since_previous_point']:+.2f} "
            f"({perf['change_since_previous_point_pct']:+.2%})"
        )

    print("\n  Top risk contributors:")
    for rc in bundle["top_risk_contributors"]:
        share = rc["share_of_portfolio_volatility"]
        share_str = f"{share:.1%}" if share is not None else "n/a"
        print(f"    - {rc['SecurityName']}: {share_str} of portfolio volatility")

    print(f"\n  Priorities ({len(bundle['priorities'])}), highest severity first:")
    for p in bundle["priorities"]:
        if p["type"] == "violation":
            print(f"    [{p['severity']}] {p['description']}")
        elif p["type"] == "saa_deviation":
            print(
                f"    [SAA] {p['category']} ({p['dimension']}): "
                f"actual {p['actual']:.1%} vs target {p['target']:.1%} "
                f"({'below' if p['breach'] == 'min' else 'above'} range)"
            )
        elif p["type"] == "concentration":
            print(f"    [Concentration] {p['security_name']} at {p['weight']:.1%} of portfolio")

    print()
