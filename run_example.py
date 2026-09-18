"""
Smoke test for the data layer: loads the synthetic fixtures, builds a
resolved client view, and prints the parts that are easiest to get wrong
(SAA deviations with fund look-through, violation filtering) so a human
can eyeball whether the numbers make sense.

Run: python3 run_example.py
"""
import json

from data_layer import ReferenceIndex, build_client_view, load_clients, load_reference

clients = load_clients("test_fixtures/clients.sample.json")
reference = load_reference("test_fixtures/reference.sample.json")
ref = ReferenceIndex(reference)

client_view = build_client_view(clients[0], ref)

print("=== Client ===")
print(client_view["display_name"], client_view["client_ref"])
print("AUM:", client_view["aum"], client_view["reporting_currency"])
print("Risk profile:", client_view["risk_profile"]["Name"])
print("Tags:", [t["TagName"] for t in client_view["tags"]])

print("\n=== Active violations (should exclude the overridden currency rule) ===")
for v in client_view["active_violations"]:
    print(f"- {v['RuleCode']} [{v['Severity']}]: {v['rule']['Description'] if v['rule'] else '(rule not found)'}")

portfolio = client_view["portfolios"][0]

print("\n=== Positions ===")
for pos in portfolio["resolved_security_positions"]:
    sec = pos["security"]
    print(
        f"- {pos['SecurityName']}: {pos['PortfolioValuePercentage']:.0%} of portfolio, "
        f"recommended={pos['is_recommended']}, unbundling={sec.get('IsUnbundlingEnabled') if sec else None}"
    )

print("\n=== SAA deviations (AssetClass dimension) ===")
print("Expect: Shares actual ~0.35 + (0.25*0.6)=0.15 -> 0.50 vs target 0.50 (on target)")
print("Expect: Bonds actual ~0.25*0.4=0.10 vs target 0.40 (underweight, breaches min 0.30)")
for row in portfolio["saa_deviations"]["AssetClass"]:
    print(
        f"- {row['category']}: actual={row['actual']:.3f} target={row['target']} "
        f"deviation={row['deviation_from_target']} breach_min={row['breaches_min']} breach_max={row['breaches_max']}"
    )

print("\n=== Full client view keys (sanity check on shape) ===")
print(list(client_view.keys()))
