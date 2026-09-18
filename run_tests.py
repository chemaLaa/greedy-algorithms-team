"""
Runs every test_*.py file under tests/, calling every function named
test_*. No dependencies — works even without pytest installed.

If pytest IS installed, prefer it instead: `pytest tests/` (same test
files, nicer output, better failure diffs). This runner exists so the
suite is runnable in any environment, including one where installing
pytest isn't an option.

Usage: python3 run_tests.py
"""
import importlib.util
import sys
import traceback
from pathlib import Path

TESTS_DIR = Path(__file__).parent / "tests"


def discover_test_functions(module_path: Path):
    spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(TESTS_DIR))  # so `from helpers import ...` resolves
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return [
        (name, getattr(module, name))
        for name in dir(module)
        if name.startswith("test_") and callable(getattr(module, name))
    ]


def main():
    test_files = sorted(TESTS_DIR.glob("test_*.py"))
    if not test_files:
        print("No test files found under tests/")
        return 1

    total = passed = failed = 0
    failures = []

    for path in test_files:
        for name, fn in discover_test_functions(path):
            total += 1
            try:
                fn()
                passed += 1
                print(f"  ok    {path.name}::{name}")
            except Exception as e:
                failed += 1
                failures.append((path.name, name, e))
                print(f"  FAIL  {path.name}::{name}  ->  {e!r}")

    print()
    print(f"{passed}/{total} passed, {failed} failed")

    if failures:
        print("\n--- failure details ---")
        for filename, name, exc in failures:
            print(f"\n{filename}::{name}")
            traceback.print_exception(type(exc), exc, exc.__traceback__)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
