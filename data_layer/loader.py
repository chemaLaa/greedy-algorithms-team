"""
Loads clients.json / reference.json into plain Python objects.

No schema coercion happens here on purpose: the source data is already
well-formed JSON, and the "absent, not null" convention (a missing field
means the key isn't there at all, not that it's present with value None)
means downstream code has to use defensive .get()-style access anyway.
A rigid model layer covering ~15 collections and their optional fields
would mostly get in the way without buying real safety. This module's
only job is: read bytes, parse JSON, sanity-check the top-level shape.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Union

PathLike = Union[str, Path]


class DataLoadError(Exception):
    """Raised when a clients/reference file doesn't match the expected shape."""


def load_clients(source: Union[PathLike, Any]) -> list[dict]:
    """
    Load a clients.json-shaped file: a JSON array of Client objects.

    `source` can be a path (str/Path) or an already-open file-like object
    (e.g. a FastAPI UploadFile.file), so the same function works whether
    you're loading from disk or handling an advisor's upload of a new
    client-data file at runtime.
    """
    data = _read_json(source)
    if not isinstance(data, list):
        raise DataLoadError(
            "clients.json must be a JSON array of Client objects, "
            f"got {type(data).__name__}"
        )
    return data


def load_reference(source: Union[PathLike, Any]) -> dict:
    """
    Load a reference.json-shaped file: a single JSON object of named
    lookup collections. Any individual collection may be entirely absent
    if nothing in the paired clients.json references it.
    """
    data = _read_json(source)
    if not isinstance(data, dict):
        raise DataLoadError(
            f"reference.json must be a JSON object, got {type(data).__name__}"
        )
    return data


def _read_json(source: Union[PathLike, Any]) -> Any:
    if isinstance(source, (str, Path)):
        with open(source, "r", encoding="utf-8") as f:
            return json.load(f)
    if hasattr(source, "read"):
        content = source.read()
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        return json.loads(content)
    raise DataLoadError(f"Unsupported input type: {type(source).__name__}")
