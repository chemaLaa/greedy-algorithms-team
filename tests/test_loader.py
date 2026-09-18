from helpers import FIXTURES_DIR
import os
from data_layer import load_clients, load_reference, DataLoadError


def test_load_clients_returns_a_list():
    clients = load_clients(os.path.join(FIXTURES_DIR, "clients.sample.json"))
    assert isinstance(clients, list)
    assert len(clients) == 1
    assert clients[0]["ClientRef"] == "CASE-001"


def test_load_reference_returns_a_dict():
    reference = load_reference(os.path.join(FIXTURES_DIR, "reference.sample.json"))
    assert isinstance(reference, dict)
    assert "Securities" in reference


def test_load_clients_rejects_object_shaped_file(tmp_path=None):
    # reference.json is an object, not an array — loading it as clients
    # should fail loudly rather than silently returning garbage.
    try:
        load_clients(os.path.join(FIXTURES_DIR, "reference.sample.json"))
        assert False, "expected DataLoadError"
    except DataLoadError:
        pass


def test_load_reference_rejects_array_shaped_file():
    try:
        load_reference(os.path.join(FIXTURES_DIR, "clients.sample.json"))
        assert False, "expected DataLoadError"
    except DataLoadError:
        pass
