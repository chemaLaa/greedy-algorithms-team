"""
Shared setup for the test suite. Deliberately plain functions, not pytest
fixtures, so these tests run under pytest if it's installed but don't
require it — a plain `assert`-based test_* function is pytest-discoverable
on its own.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data_layer import load_clients, load_reference, ReferenceIndex

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "test_fixtures")


def load_fixture_data():
    clients = load_clients(os.path.join(FIXTURES_DIR, "clients.sample.json"))
    reference = load_reference(os.path.join(FIXTURES_DIR, "reference.sample.json"))
    ref = ReferenceIndex(reference)
    return clients, reference, ref


def first_client():
    clients, _, ref = load_fixture_data()
    return clients[0], ref
