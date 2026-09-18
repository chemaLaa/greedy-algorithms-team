"""
Simple file-based persistence for client state — one JSON file per
client, under a local directory. Hackathon-appropriate: no database, no
server, just a durable place to keep "what did we see last time" between
advisor sessions.

Swappable later for a real database without touching snapshot.py or
diff.py — neither of those knows or cares where a snapshot came from.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_STATE_DIR = Path(__file__).parent.parent / ".state" / "snapshots"


def _path_for(client_ref: str, state_dir: Path) -> Path:
    safe_name = client_ref.replace("/", "_").replace("\\", "_")
    return state_dir / f"{safe_name}.json"


def load_client_state(client_ref: str, state_dir: Path = DEFAULT_STATE_DIR) -> dict[str, Any]:
    """
    Returns {"snapshots": {portfolio_id: snapshot, ...}, "events": [str, ...]}
    for this client, or an empty version of that shape if this client has
    never been snapshotted before (their first-ever briefing, or a
    brand-new/previously-unseen test client) — never raises for a missing
    file.
    """
    path = _path_for(client_ref, state_dir)
    if not path.exists():
        return {"snapshots": {}, "events": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_client_state(
    client_ref: str, state: dict[str, Any], state_dir: Path = DEFAULT_STATE_DIR
) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = _path_for(client_ref, state_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
