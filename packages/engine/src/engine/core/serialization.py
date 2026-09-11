"""Converts frozen dataclasses (ingest/quant result types) to JSON-safe
structures for MCP tool responses, one shared path instead of a
hand-written to_dict() per dataclass.
"""

import dataclasses
from datetime import datetime
from typing import Any


def to_json_dict(obj: Any) -> Any:
    """Recursively convert a dataclass instance (or list/dict of them)
    into plain dicts/lists with datetime fields rendered via isoformat().

    Args:
        obj: A dataclass instance, or a list/dict/plain value possibly
            containing dataclass instances.

    Returns:
        A JSON-serializable structure.
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            field.name: to_json_dict(getattr(obj, field.name))
            for field in dataclasses.fields(obj)
        }
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, list):
        return [to_json_dict(item) for item in obj]
    if isinstance(obj, dict):
        return {key: to_json_dict(value) for key, value in obj.items()}
    return obj
