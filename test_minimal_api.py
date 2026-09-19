"""
Isolated test: does a bare, trivial Anthropic API call work at all?
Bypasses the entire briefing pipeline. If THIS hangs too, the problem is
connectivity/environment, not anything about the briefing prompt or
this codebase.
"""
import os
import time

import anthropic

api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    print("ANTHROPIC_API_KEY is not set in this terminal session.")
    raise SystemExit(1)

print("Building client with a 20s timeout...")
client = anthropic.Anthropic(api_key=api_key, timeout=20.0)

print("Sending a trivial request...")
started = time.monotonic()
try:
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=50,
        messages=[{"role": "user", "content": "Say 'hello' and nothing else."}],
    )
    elapsed = time.monotonic() - started
    print(f"SUCCESS after {elapsed:.1f}s")
    print("Response:", response.content[0].text)
except Exception as e:
    elapsed = time.monotonic() - started
    print(f"FAILED after {elapsed:.1f}s")
    print("Error type:", type(e).__name__)
    print("Error:", e)
