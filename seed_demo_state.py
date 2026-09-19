"""
seed_demo_state.py
──────────────────
Plants a fake "previous briefing" snapshot for the default demo client
(Pikachu, id=49388, portfolio=50110) so that the next call to
POST /api/briefing produces a non-trivial "Since last interaction" diff.

Run once before the demo:

    python3 seed_demo_state.py

Then generate a briefing in the browser (without ?mock=1).
The "Since last interaction" section will show real, computed changes.

To reset and start fresh (first-interaction state again):

    python3 seed_demo_state.py --reset
"""
import json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# server.py passes state_dir=Path(".state"), so store.py writes to
# .state/<client_ref>.json  (not .state/snapshots/<client_ref>.json)
STATE_DIR   = Path(".state")
CLIENT_REF  = "CASE-019"          # client_ref for Pikachu (id=49388)
PORTFOLIO   = "50110"
STATE_FILE  = STATE_DIR / f"{CLIENT_REF}.json"

# ── "past" snapshot — values deliberately different from the current data ──
# The diff layer flags changes > 0.5 pp in allocation and any violation
# that wasn't present before.  Values below are tuned to produce several
# visible changes without being implausible.
PAST_SNAPSHOT = {
    "portfolio_id": int(PORTFOLIO),
    "captured_at": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
    "portfolio_value": 725_000.00,          # was 725k, now 699k  → -3.6 % drop
    "allocation": {
        "AssetClass": {
            "Bonds":                         0.0,
            "Liquidity":                     0.025,       # liquidity was higher
            "Real estate":                   0.0,
            "Shares":                        0.942,
            "Specialties andCommodities":    0.033,
        },
        "CurrencyGroup": {
            "Andere":       0.055,
            "Euro":         0.021,
            "Swiss francs": 0.680,           # was 68 %, now 75 %  → +7 pp overweight
            "US-Dollar":    0.244,           # was 24 %, now 17 %  → -7 pp underweight
        },
        "CountryGroup": {
            "Asia/Pacific (ex Japan)": 0.022,
            "Great Britain":           0.010,
            "Japan":                   0.007,
            "North America":           0.238,  # was 24 %, now 17 %  → drift
            "Not classified":          0.0,
            "Others":                  0.041,
            "Rest of Europe":          0.023,
            "Switzerland":             0.659,  # was 66 %, now 72 %  → +6 pp drift
        },
        "Industry": {
            "Consumer Discretionary":    0.007,
            "Consumer Staples":          0.082,   # was 8 %, now 10 %  → entered heavier
            "Energy":                    0.001,
            "Financials":                0.073,
            "Health Care":               0.368,
            "Industrials":               0.085,
            "Information Technology":    0.218,   # was 22 %, now 26 %  → +4 pp
            "Materials":                 0.023,
            "Real Estate":               0.002,
            "Telecommunication Services":0.003,
            "Utilities":                 0.053,
        },
    },
    "top_positions": [
        # Comet was already #1; Ypsomed was #2 — no change there
        {"SecurityId": 4101,  "SecurityName": "Namen-Aktie Comet Holding AG",        "weight": 0.195},
        {"SecurityId": 347,   "SecurityName": "Namen-Aktie Ypsomed Holding AG",      "weight": 0.148},
        {"SecurityId": 644,   "SecurityName": "Namen-Aktie Nestle SA",               "weight": 0.091},
        {"SecurityId": 261,   "SecurityName": "Genussschein Roche Holding AG",       "weight": 0.068},
        # 5th position was different — will appear as "entered top 5"
        {"SecurityId": 999,   "SecurityName": "Placeholder Position (exited top 5)", "weight": 0.055},
    ],
    "violations": [
        # Missing two violations that are currently active → they appear as "newly appeared"
        "Cluster risk of a single financial instrument",
        "Share is not part of the investment universe for individual shares and therefore not monitored.",
        "Significant overweight in the equity region \"Switzerland\"",
        "Significant overweight in the equity sector \"Health Care\"",
        "Significant underweight in the equity region \"North America\"",
        "Underweight in the equity sector \"Consumer Discretionary\"",
        "Underweight in the equity sector \"Consumer Staples\"",
        # "Significant overweight in the equity sector \"Information Technology\"" ← now newly active
        # "Underweight in the equity sector \"Financials\""                        ← now newly active
    ],
}

PAST_EVENTS = [
    "30 days ago: First briefing baseline captured. Portfolio at CHF 725,000.",
]


def seed():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = {"snapshots": {PORTFOLIO: PAST_SNAPSHOT}, "events": PAST_EVENTS}
    STATE_FILE.write_text(json.dumps(state, indent=2))
    print(f"Seeded {STATE_FILE}")
    print("Expected diff on next briefing call:")
    print("  • Portfolio value: CHF 725,000 → 698,978  (−3.6 %)")
    print("  • Swiss francs allocation: +7 pp drift")
    print("  • North America / USD:     −7 pp drift")
    print("  • Switzerland country:     +6 pp drift")
    print("  • IT sector:               +4 pp drift")
    print("  • 2 violations newly active (IT overweight, Financials underweight)")
    print("  • 1 position exited top 5 / 1 entered top 5")


def reset():
    if STATE_FILE.exists():
        STATE_FILE.unlink()
        print(f"Deleted {STATE_FILE} — next call will be a first-interaction baseline.")
    else:
        print("No state file found — already in first-interaction state.")


if __name__ == "__main__":
    if "--reset" in sys.argv:
        reset()
    else:
        seed()
