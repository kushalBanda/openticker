from dataclasses import dataclass
from datetime import UTC, datetime

from engine.core.serialization import to_json_dict


@dataclass(frozen=True)
class _Inner:
    ts: datetime
    value: float


@dataclass(frozen=True)
class _Outer:
    name: str
    inner: _Inner
    items: list[_Inner]


def test_converts_single_dataclass_datetime_field() -> None:
    obj = _Inner(ts=datetime(2026, 1, 1, tzinfo=UTC), value=1.5)
    result = to_json_dict(obj)
    assert result == {"ts": "2026-01-01T00:00:00+00:00", "value": 1.5}


def test_converts_nested_dataclasses_and_lists() -> None:
    obj = _Outer(
        name="x",
        inner=_Inner(ts=datetime(2026, 1, 1, tzinfo=UTC), value=1.5),
        items=[_Inner(ts=datetime(2026, 1, 2, tzinfo=UTC), value=2.5)],
    )
    result = to_json_dict(obj)
    assert result == {
        "name": "x",
        "inner": {"ts": "2026-01-01T00:00:00+00:00", "value": 1.5},
        "items": [{"ts": "2026-01-02T00:00:00+00:00", "value": 2.5}],
    }


def test_passes_through_plain_list_of_dataclasses() -> None:
    objs = [_Inner(ts=datetime(2026, 1, 1, tzinfo=UTC), value=1.0)]
    result = to_json_dict(objs)
    assert result == [{"ts": "2026-01-01T00:00:00+00:00", "value": 1.0}]


def test_passes_through_plain_scalar_unchanged() -> None:
    assert to_json_dict(42) == 42
    assert to_json_dict("x") == "x"
    assert to_json_dict(None) is None


def test_converts_datetimes_inside_a_plain_dict() -> None:
    obj = {"ts": datetime(2026, 1, 1, tzinfo=UTC), "count": 3}
    assert to_json_dict(obj) == {"ts": "2026-01-01T00:00:00+00:00", "count": 3}
