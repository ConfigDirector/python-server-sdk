from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from configdirector import Context
from openfeature.evaluation_context import EvaluationContext

from configdirector_openfeature._context import to_context


def test_maps_no_context_to_no_context() -> None:
    assert to_context(None) is None


def test_maps_an_empty_context_to_an_empty_context() -> None:
    assert to_context(EvaluationContext()) == Context()


def test_maps_every_known_attribute() -> None:
    context = to_context(
        EvaluationContext("user-1", {"name": "Ada", "traits": {"plan": "pro"}, "anonymous": True})
    )

    assert context == Context(id="user-1", name="Ada", traits={"plan": "pro"}, anonymous=True)


def test_prefers_the_targeting_key_over_an_id_attribute() -> None:
    assert to_context(EvaluationContext("key", {"id": "attribute"})) == Context(id="key")


def test_falls_back_to_the_id_attribute() -> None:
    assert to_context(EvaluationContext(None, {"id": "attribute"})) == Context(id="attribute")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (123, "123"),
        (1.5, "1.5"),
        (True, "true"),
        (False, "false"),
        (datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc), "2024-01-02T03:04:05+00:00"),
        ({"nested": "value"}, None),
        (["a", "b"], None),
    ],
)
def test_writes_scalar_identifiers_and_names_as_text(value: Any, expected: str | None) -> None:
    context = to_context(EvaluationContext(None, {"id": value, "name": value}))

    assert context == Context(id=expected, name=expected)


@pytest.mark.parametrize("traits", [{}, "pro", ["pro"], 7, None])
def test_ignores_traits_that_are_not_a_populated_mapping(traits: Any) -> None:
    assert to_context(EvaluationContext("user-1", {"traits": traits})) == Context(id="user-1")


def test_converts_traits_to_plain_json_values() -> None:
    seen = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    context = to_context(EvaluationContext("user-1", {"traits": {"seen": seen, "tags": ("a", ("b",))}}))

    assert context is not None
    assert context.traits == {"seen": "2024-01-02T03:04:05+00:00", "tags": ["a", ["b"]]}


@pytest.mark.parametrize("anonymous", ["true", 1, None])
def test_ignores_an_anonymous_attribute_that_is_not_a_boolean(anonymous: Any) -> None:
    assert to_context(EvaluationContext("user-1", {"anonymous": anonymous})) == Context(id="user-1")
