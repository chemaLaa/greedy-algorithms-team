"""
Isolates exactly where the connection problem is: DNS resolution,
IPv6 vs IPv4, plain Python networking (urllib, stdlib), or httpx
specifically (what the anthropic SDK actually uses under the hood).

Run this in the SAME terminal/venv where the hang happened.
"""
import socket
import time

print("=== DNS resolution (what Python sees) ===")
try:
    results = socket.getaddrinfo("api.anthropic.com", 443)
    for family, _, _, _, sockaddr in results:
        family_name = "IPv6" if family == socket.AF_INET6 else "IPv4" if family == socket.AF_INET else str(family)
        print(f"  {family_name}: {sockaddr[0]}")
except Exception as e:
    print("DNS FAILED:", e)

print()
print("=== Plain urllib HTTPS GET (stdlib only, bypasses httpx entirely) ===")
import urllib.request

started = time.monotonic()
try:
    with urllib.request.urlopen("https://api.anthropic.com", timeout=15) as resp:
        print(f"SUCCESS after {time.monotonic() - started:.1f}s, status={resp.status}")
except Exception as e:
    print(f"FAILED after {time.monotonic() - started:.1f}s: {type(e).__name__}: {e}")

print()
print("=== httpx (this is what the anthropic SDK actually uses) ===")
try:
    import httpx
except ImportError:
    print("httpx not importable — unexpected, since it's a dependency of anthropic")
else:
    started = time.monotonic()
    try:
        r = httpx.get("https://api.anthropic.com", timeout=15)
        print(f"SUCCESS after {time.monotonic() - started:.1f}s, status={r.status_code}")
    except Exception as e:
        print(f"FAILED after {time.monotonic() - started:.1f}s: {type(e).__name__}: {e}")

    print()
    print("=== httpx forced to IPv4 only ===")
    started = time.monotonic()
    try:
        transport = httpx.HTTPTransport(local_address="0.0.0.0")  # forces IPv4
        with httpx.Client(transport=transport) as client:
            r = client.get("https://api.anthropic.com", timeout=15)
            print(f"SUCCESS after {time.monotonic() - started:.1f}s, status={r.status_code}")
    except Exception as e:
        print(f"FAILED after {time.monotonic() - started:.1f}s: {type(e).__name__}: {e}")
