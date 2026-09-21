from __future__ import annotations

import pytest
from configdirector import ConfigEvaluation, EvaluationReason
from openfeature.exception import ErrorCode
from openfeature.flag_evaluation import Reason

from configdirector_openfeature._resolution import to_resolution_details


def evaluation(reason: EvaluationReason, is_default: bool) -> ConfigEvaluation:
    return ConfigEvaluation(
        key="my-config", value="value", is_default=is_default, reason=reason, value_id="id-1"
    )


def test_carries_only_the_value_when_nothing_was_evaluated() -> None:
    details = to_resolution_details("value", None)

    assert (details.value, details.reason, details.variant, details.error_code) == ("value", None, None, None)


def test_a_match_is_a_targeting_match_with_the_value_id_as_its_variant() -> None:
    details = to_resolution_details("value", evaluation("found-match", is_default=False))

    assert (details.value, details.reason, details.variant) == ("value", Reason.TARGETING_MATCH, "id-1")
    assert details.error_code is None


def test_a_config_without_a_value_resolves_to_the_default_without_an_error() -> None:
    details = to_resolution_details("value", evaluation("value-missing", is_default=True))

    assert (details.reason, details.variant, details.error_code) == (Reason.DEFAULT, None, None)


@pytest.mark.parametrize(
    ("reason", "error_code"),
    [
        ("config-state-missing", ErrorCode.FLAG_NOT_FOUND),
        ("client-not-ready", ErrorCode.PROVIDER_NOT_READY),
        ("type-mismatch", ErrorCode.TYPE_MISMATCH),
        ("invalid-number", ErrorCode.TYPE_MISMATCH),
        ("invalid-json", ErrorCode.TYPE_MISMATCH),
        ("invalid-boolean", ErrorCode.TYPE_MISMATCH),
    ],
)
def test_a_failed_evaluation_is_an_error(reason: EvaluationReason, error_code: ErrorCode) -> None:
    details = to_resolution_details("value", evaluation(reason, is_default=True))

    assert (details.value, details.reason, details.error_code) == ("value", Reason.ERROR, error_code)
    assert details.variant is None
    assert details.error_message
