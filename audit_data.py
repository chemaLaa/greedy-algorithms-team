#!/usr/bin/env python3
"""Run the analysis-layer pre-flight audit on a newly received partner dataset.

Usage:
    python audit_data.py clients.json reference.json
    python audit_data.py clients.json reference.json --full > audit.json

The short report is designed for the first few minutes after tomorrow's hidden
files arrive: it tells the team which analyses are safe to enable and which
should degrade gracefully.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from analysis_layer.validation import audit_dataset


def _fmt_counts(counts: dict) -> str:
    order = ("ok", "partial", "unavailable", "invalid")
    return ", ".join(f"{k}={counts.get(k, 0)}" for k in order if counts.get(k, 0)) or "none"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("clients", type=Path)
    parser.add_argument("reference", type=Path, nargs="?")
    parser.add_argument("--full", action="store_true", help="print full machine-readable JSON")
    args = parser.parse_args()

    with args.clients.open("r", encoding="utf-8") as f:
        clients = json.load(f)
    reference = None
    if args.reference:
        with args.reference.open("r", encoding="utf-8") as f:
            reference = json.load(f)

    audit = audit_dataset(clients, reference)
    if args.full:
        print(json.dumps(audit, indent=2, default=str))
        return

    print("ANALYSIS DATA AUDIT")
    print("=" * 68)
    print(f"Clients:    {audit['client_count']}")
    print(f"Portfolios: {audit['portfolio_count']}")
    print()

    print("Analysis checks")
    for name, counts in audit["check_status_counts"].items():
        print(f"  {name:22s} {_fmt_counts(counts)}")

    print("\nSource capabilities")
    for name, available in audit["capabilities"].items():
        print(f"  {'YES' if available else 'NO ':3s}  {name}")

    print("\nPortfolio field coverage")
    for field, coverage in audit["portfolio_field_presence"].items():
        print(f"  {field:36s} {coverage['present']}/{coverage['portfolio_count']}")

    important = [i for i in audit["issues"] if i["status"] in {"invalid", "unavailable"}]
    if important:
        print("\nImportant portfolio issues (first 12; --full has all)")
        for issue in important[:12]:
            reasons = ", ".join(issue["reasons"]) or "no reason supplied"
            print(
                f"  {issue['client_ref']} / {issue['portfolio_id']}: "
                f"{issue['check']} = {issue['status']} ({reasons})"
            )
        if len(important) > 12:
            print(f"  ... {len(important) - 12} more")

    ref = audit.get("reference")
    if ref:
        lt = ref["fund_lookthrough"]
        print("\nFund look-through")
        print(f"  Scale counts: {lt['scale_counts']}")
        print(f"  Negative weight rows: {lt['negative_weight_row_count']}")
        print(f"  Suspicious fund totals: {len(lt['suspicious_funds'])}")
        print(f"  Held unbundling funds without mapping: {len(lt['held_unbundling_without_mapping'])}")

        print("\nSAA mapping capabilities")
        for dim, signatures in ref["saa"]["dimension_signatures"].items():
            print(f"  {dim:16s} {signatures}")

        print("\nHeld-security metadata coverage")
        meta = ref["held_security_metadata"]
        print(f"  Unique held securities: {meta['unique_held_security_count']}")
        print(f"  Missing references:     {len(meta['missing_from_reference'])}")
        for field, cov in meta["field_coverage"].items():
            print(f"  {field:28s} {cov['present']}/{cov['held_security_count']}")

    print("\nInterpretation reminders")
    print("  - PerformanceHistory.Value changes are portfolio-value changes unless semantics are confirmed.")
    print("  - ExpectedReturn is forward-looking, not historical performance.")
    print("  - ClientNote dates are only a fallback interaction proxy.")
    print("  - Invalid risk attribution must be omitted, not repaired by the LLM.")
    print("\nUse --full for the complete JSON audit.")


if __name__ == "__main__":
    main()
