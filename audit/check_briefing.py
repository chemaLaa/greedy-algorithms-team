"""
check_briefing.py — audit checker for POST /api/briefing responses.
Tests C1–C11 against each audit/output_<client_id>.json.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from pathlib import Path

AUDIT_DIR = Path(__file__).parent
CLIENTS = ["49388", "181997", "17091", "78645", "125070"]
BANNED_VAGUE = [
    "significant", "significantly", "heavy", "heavily",
    "substantial", "substantially", "major", "considerable",
]
GERMAN_WORDS = set(
    "der die das und von mit ist hat für auf ein einen eine keine nicht oder auch".split()
)
FORBIDDEN_START_WORDS = ["Consider", "Discuss", "Evaluate", "Review", "Look into"]
REQUIRED_KEYS = {"client", "headline", "attention", "since_last", "talking_points", "sources"}

# ── helpers ────────────────────────────────────────────────────────────────

def load_outputs():
    outputs = {}
    for cid in CLIENTS:
        path = AUDIT_DIR / f"output_{cid}.json"
        if path.exists():
            with open(path) as f:
                outputs[cid] = json.load(f)
        else:
            outputs[cid] = None
    return outputs


def load_timing():
    path = AUDIT_DIR / "timing.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def load_payload(cid: str) -> str | None:
    path = AUDIT_DIR / f"payload_{cid}.txt"
    if path.exists():
        return path.read_text()
    return None


def all_text_fields(data: dict) -> str:
    """Flatten headline + attention titles/details + since_last + talking_points into one string."""
    parts = []
    parts.append(data.get("headline", ""))
    for item in data.get("attention", []):
        parts.append(item.get("title", ""))
        parts.append(item.get("detail", ""))
    parts.extend(data.get("since_last", []))
    parts.extend(data.get("talking_points", []))
    return " ".join(parts)


def word_count(text: str) -> int:
    return len(text.split())


def has_digit(text: str) -> bool:
    return bool(re.search(r"\d", text))


def extract_numbers(text: str) -> list[str]:
    """Extract numbers including percentages and CHF amounts."""
    return re.findall(r"CHF\s*[\d,]+(?:\.\d+)?|[\d,]+(?:\.\d+)?%?", text)


# ── individual checks ─────────────────────────────────────────────────────

def check_c1(data: dict) -> tuple[str, list[str]]:
    """C1: JSON has exactly the required top-level keys."""
    if data is None:
        return "FAIL", ["No data loaded"]
    actual = set(data.keys())
    missing = REQUIRED_KEYS - actual
    extra = actual - REQUIRED_KEYS
    issues = []
    if missing:
        issues.append(f"Missing keys: {sorted(missing)}")
    if extra:
        issues.append(f"Extra keys: {sorted(extra)}")
    return ("PASS" if not issues else "FAIL"), issues


def check_c2(data: dict) -> tuple[str, list[str]]:
    """C2: Every attention item has at least one digit in title or detail."""
    if data is None:
        return "FAIL", ["No data"]
    issues = []
    for i, item in enumerate(data.get("attention", [])):
        combined = item.get("title", "") + " " + item.get("detail", "")
        if not has_digit(combined):
            issues.append(f"attention[{i}] title={item.get('title')!r} has no digit")
    return ("PASS" if not issues else "FAIL"), issues


def check_c3(data: dict) -> tuple[str, list[str]]:
    """C3: No banned vague word without a digit within 6 words of it."""
    if data is None:
        return "FAIL", ["No data"]
    text = all_text_fields(data)
    tokens = text.split()
    issues = []
    for i, tok in enumerate(tokens):
        clean = tok.lower().strip(".,;:!?()")
        if clean in BANNED_VAGUE:
            window_start = max(0, i - 6)
            window_end = min(len(tokens), i + 7)
            window = " ".join(tokens[window_start:window_end])
            if not has_digit(window):
                issues.append(f"Vague word {tok!r} without nearby digit: '...{window}...'")
    return ("PASS" if not issues else "FAIL"), issues


def check_c4(data: dict) -> tuple[str, list[str]]:
    """C4: attention has at most 4 items; no two items share 2+ content words in titles."""
    if data is None:
        return "FAIL", ["No data"]
    items = data.get("attention", [])
    issues = []
    if len(items) > 4:
        issues.append(f"attention has {len(items)} items (max 4)")
    # Check for shared title words (ignore short words)
    stopwords = {"a", "an", "the", "in", "of", "to", "and", "is", "are", "has", "for", "with"}
    titles = []
    for item in items:
        words = set(w.lower().strip(".,;:") for w in item.get("title", "").split()
                    if w.lower().strip(".,;:") not in stopwords and len(w) > 3)
        titles.append(words)
    for i in range(len(titles)):
        for j in range(i + 1, len(titles)):
            shared = titles[i] & titles[j]
            if len(shared) >= 2:
                issues.append(f"attention[{i}] and attention[{j}] share title words: {shared}")
    return ("PASS" if not issues else "FAIL"), issues


def check_c5(data: dict) -> tuple[str, list[str]]:
    """C5: since_last is empty OR every entry has a date or CHF amount."""
    if data is None:
        return "FAIL", ["No data"]
    sl = data.get("since_last", [])
    if not sl:
        return "PASS", []
    issues = []
    date_pattern = re.compile(
        r"\d{4}-\d{2}-\d{2}|"
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\b|"
        r"CHF\s*[\d,]+",
        re.IGNORECASE,
    )
    for i, entry in enumerate(sl):
        if not date_pattern.search(entry):
            issues.append(f"since_last[{i}] has no date/CHF: {entry!r}")
        if "0.0%" in entry:
            issues.append(f"since_last[{i}] contains '0.0%': {entry!r}")
    return ("PASS" if not issues else "FAIL"), issues


def check_c6(data: dict) -> tuple[str, list[str]]:
    """C6: Every talking_point has a digit or named security; does not start with forbidden words."""
    if data is None:
        return "FAIL", ["No data"]
    tps = data.get("talking_points", [])
    issues = []
    for i, tp in enumerate(tps):
        # Check forbidden starts
        for fw in FORBIDDEN_START_WORDS:
            if tp.strip().startswith(fw):
                issues.append(f"talking_points[{i}] starts with {fw!r}: {tp!r}")
        # Check for digit or capitalized proper noun (named security = capitalized word sequence)
        has_num = has_digit(tp)
        # Check for what looks like a named position (2+ capital letter sequences)
        has_named = bool(re.search(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+", tp))
        if not has_num and not has_named:
            issues.append(f"talking_points[{i}] has no digit or named security: {tp!r}")
    return ("PASS" if not issues else "FAIL"), issues


def check_c7(data: dict) -> tuple[str, list[str]]:
    """C7: Every sources[].section does NOT contain underscore, dot, or camelCase."""
    if data is None:
        return "FAIL", ["No data"]
    issues = []
    bad_pattern = re.compile(r"[_.]|[a-z][A-Z]")
    for i, src in enumerate(data.get("sources", [])):
        section = src.get("section", "")
        if bad_pattern.search(section):
            issues.append(f"sources[{i}].section has underscore/dot/camelCase: {section!r}")
    return ("PASS" if not issues else "FAIL"), issues


def check_c8(data: dict) -> tuple[str, list[str]]:
    """C8: Total word count under 150."""
    if data is None:
        return "FAIL", ["No data"]
    text = all_text_fields(data)
    wc = word_count(text)
    if wc >= 150:
        return "FAIL", [f"Word count is {wc} (limit 150)"]
    return "PASS", [f"Word count: {wc}"]


def check_c9(data: dict, cid: str) -> tuple[str, list[str]]:
    """C9: Numbers in output appear in payload (if payload exists)."""
    if data is None:
        return "FAIL", ["No data"]
    payload = load_payload(cid)
    if payload is None:
        return "SKIP", ["No payload file (audit/payload_<id>.txt not found)"]
    text = all_text_fields(data)
    numbers = extract_numbers(text)
    issues = []
    for num in numbers:
        bare = num.replace("CHF", "").replace(",", "").strip()
        if bare and bare not in payload:
            issues.append(f"Number {num!r} not found in payload")
    if not numbers:
        return "PASS", ["No numbers to verify"]
    return ("PASS" if not issues else "FAIL"), issues


def check_c10(data: dict) -> tuple[str, list[str]]:
    """C10: client.profile is not a bare digit; no mixed English/German."""
    if data is None:
        return "FAIL", ["No data"]
    issues = []
    client = data.get("client", {})
    profile = str(client.get("profile", ""))
    if re.fullmatch(r"\d+", profile):
        issues.append(f"client.profile is a bare digit: {profile!r}")
    text = all_text_fields(data).lower()
    tokens = set(re.findall(r"[a-zäöü]+", text))
    found_german = tokens & GERMAN_WORDS
    if found_german:
        issues.append(f"German words found: {sorted(found_german)}")
    return ("PASS" if not issues else "FAIL"), issues


def check_c11(cid: str, timing: dict) -> tuple[str, list[str]]:
    """C11: Report cold_ms and cached_ms."""
    if cid not in timing:
        return "SKIP", [f"No timing data for {cid}"]
    t = timing[cid]
    cold = t.get("cold_ms", "?")
    cached = t.get("cached_ms", "?")
    notes = [f"cold={cold}ms, cached={cached}ms"]
    # Flag if cached is unreasonably slow (>500ms suggests cache miss)
    if isinstance(cached, int) and cached > 500:
        notes.append(f"WARNING: cached_ms={cached} suggests possible cache miss")
    return "PASS", notes


# ── main ──────────────────────────────────────────────────────────────────

def run():
    outputs = load_outputs()
    timing = load_timing()

    checks = ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11"]
    results = {c: {} for c in checks}
    details = []  # (check, cid, verdict, issues)

    for cid in CLIENTS:
        data = outputs[cid]

        verdicts_and_issues = {
            "C1": check_c1(data),
            "C2": check_c2(data),
            "C3": check_c3(data),
            "C4": check_c4(data),
            "C5": check_c5(data),
            "C6": check_c6(data),
            "C7": check_c7(data),
            "C8": check_c8(data),
            "C9": check_c9(data, cid),
            "C10": check_c10(data),
            "C11": check_c11(cid, timing),
        }

        for check, (verdict, issues) in verdicts_and_issues.items():
            results[check][cid] = verdict
            if issues:
                details.append((check, cid, verdict, issues))

    # Compute OVERALL per check
    for check in checks:
        verdicts = list(results[check].values())
        if all(v == "PASS" for v in verdicts):
            results[check]["OVERALL"] = "PASS"
        elif all(v == "SKIP" for v in verdicts):
            results[check]["OVERALL"] = "SKIP"
        elif any(v == "FAIL" for v in verdicts):
            results[check]["OVERALL"] = "FAIL"
        else:
            results[check]["OVERALL"] = "PARTIAL"

    # ── print table ───────────────────────────────────────────────────────
    col_w = 10
    header_clients = CLIENTS + ["OVERALL"]
    print("\n" + "=" * 80)
    print("BRIEFING AUDIT CHECK RESULTS")
    print("=" * 80)
    header = f"{'Check':<8}" + "".join(f"{c:>{col_w}}" for c in header_clients)
    print(header)
    print("-" * len(header))
    for check in checks:
        row = f"{check:<8}"
        for cid in header_clients:
            v = results[check].get(cid, "?")
            row += f"{v:>{col_w}}"
        print(row)
    print("=" * 80)

    # ── print C8 word counts ──────────────────────────────────────────────
    print("\nWORD COUNTS (C8):")
    for cid in CLIENTS:
        data = outputs[cid]
        if data:
            text = all_text_fields(data)
            wc = word_count(text)
            print(f"  {cid}: {wc} words")

    # ── print C11 timing ─────────────────────────────────────────────────
    print("\nTIMING (C11):")
    for cid in CLIENTS:
        if cid in timing:
            t = timing[cid]
            print(f"  {cid}: cold={t.get('cold_ms')}ms, cached={t.get('cached_ms')}ms")

    # ── print FAILs ───────────────────────────────────────────────────────
    fails = [(c, cid, v, iss) for c, cid, v, iss in details if v == "FAIL"]
    print(f"\n{'=' * 80}")
    print(f"FAILURES ({len(fails)} total):")
    print("=" * 80)
    if not fails:
        print("  None.")
    for check, cid, verdict, issues in fails:
        data = outputs[cid]
        client_name = (data or {}).get("client", {}).get("name", cid)
        print(f"\n[{check}] Client {cid} ({client_name}) — {verdict}")
        for iss in issues:
            print(f"  - {iss}")
        # Root cause and smallest fix
        if check == "C2":
            print(f"  Root cause: Model produced an attention item without any numbers.")
            print(f"  Smallest fix: Add to _SYSTEM: 'Every attention title and detail MUST contain at least one number.'")
        elif check == "C3":
            print(f"  Root cause: Model used vague qualifier without a number.")
            print(f"  Smallest fix: Add to _SYSTEM: 'Never use significant/heavy/substantial/major/considerable without a number.'")
        elif check == "C4":
            print(f"  Root cause: Too many attention items or overlapping content.")
            print(f"  Smallest fix: _SYSTEM already says 2-5; tighten to 'exactly 2-4 items, merge related findings.'")
        elif check == "C5":
            print(f"  Root cause: since_last entry lacks a date/CHF anchor.")
            print(f"  Smallest fix: Add to _SYSTEM: 'Each since_last entry must include a date (YYYY-MM-DD or month name) or CHF amount.'")
        elif check == "C6":
            print(f"  Root cause: Talking point starts with forbidden word or lacks a number/named security.")
            print(f"  Smallest fix: Add to _SYSTEM: 'Talking points must not start with Consider/Discuss/Evaluate/Review. Each must include a number or security name.'")
        elif check == "C7":
            print(f"  Root cause: attention[].source uses internal field name with underscore/camelCase.")
            print(f"  Smallest fix: Remove the instruction 'source: exact data field name' from _SYSTEM; replace with 'source: human-readable section label'.")
        elif check == "C8":
            print(f"  Root cause: Output exceeded 150 words.")
            print(f"  Smallest fix: Add a post-generation word-count check that trims or rejects outputs > 150 words.")
        elif check == "C10":
            print(f"  Root cause: German word(s) in English output.")
            print(f"  Smallest fix: Add to _SYSTEM: 'Respond in English only. Do not mix in German words.'")

    # ── top 3 fixes ───────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("TOP 3 HIGHEST-IMPACT FIXES:")
    print("=" * 80)
    fail_counts = {}
    for c, cid, v, iss in fails:
        fail_counts[c] = fail_counts.get(c, 0) + 1
    sorted_fails = sorted(fail_counts.items(), key=lambda x: -x[1])
    for rank, (check, count) in enumerate(sorted_fails[:3], 1):
        print(f"\n{rank}. {check} — failed for {count}/{len(CLIENTS)} clients")

    # ── score ─────────────────────────────────────────────────────────────
    all_checks = checks
    pass_count = sum(1 for c in all_checks if results[c]["OVERALL"] in ("PASS", "SKIP"))
    total = len(all_checks)
    print(f"\n{'=' * 80}")
    print(f"SCORE (C1-C11 checks): {pass_count}/{total} checks PASS/SKIP overall")
    print("=" * 80)


if __name__ == "__main__":
    run()
