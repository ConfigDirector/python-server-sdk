from __future__ import annotations

import pytest
from configdirector import ConfigEvaluation, EvaluationReason, Variation
from openfeature.exception import ErrorCode
from openfeature.flag_evaluation import Reason

from configdirector_openfeature._resolution import to_resolution_details


def evaluation(
    reason: EvaluationReason, is_default: bool, variation: Variation | None = None
) -> ConfigEvaluation:
    return ConfigEvaluation(
        key="my-config",
        value="value",
        is_default=is_default,
        reason=reason,
        value_id="id-1",
        variation=variation,
    )


def test_a_match_is_a_targeting_match_with_the_value_id_as_its_variant() -> None:
    details = to_resolution_details(evaluation("found-match", is_default=False))

    assert (details.value, details.reason, details.variant) == ("value", Reason.TARGETING_MATCH, "id-1")
    assert details.error_code is None


def test_a_match_with_a_named_variation_has_the_name_as_its_variant() -> None:
    named = Variation(id="variation-1", name="treatment")

    details = to_resolution_details(evaluation("found-match", is_default=False, variation=named))

    assert (details.reason, details.variant) == (Reason.TARGETING_MATCH, "treatment")


def test_a_match_with_an_unnamed_variation_has_the_value_id_as_its_variant() -> None:
    unnamed = Variation(id="variation-1")

    details = to_resolution_details(evaluation("found-match", is_default=False, variation=unnamed))

    assert (details.reason, details.variant) == (Reason.TARGETING_MATCH, "id-1")


def test_a_skipped_rollout_has_the_reason_default_and_the_variation_name_as_its_variant() -> None:
    named = Variation(id="variation-1", name="control")

    details = to_resolution_details(
        evaluation("rollout-skipped-no-identifier", is_default=False, variation=named)
    )

    assert (details.value, details.reason, details.variant) == ("value", Reason.DEFAULT, "control")
    assert details.error_code is None


def test_a_skipped_rollout_without_a_variation_has_the_reason_default_and_the_value_id_variant() -> None:
    details = to_resolution_details(evaluation("rollout-skipped-no-identifier", is_default=False))

    assert (details.reason, details.variant, details.error_code) == (Reason.DEFAULT, "id-1", None)


def test_a_reason_from_a_newer_sdk_with_a_value_from_configdirector_carries_only_the_value() -> None:
    details = to_resolution_details(
        evaluation("a-reason-from-a-newer-sdk", is_default=False)  # type: ignore[arg-type]
    )

    assert (details.value, details.reason, details.variant, details.error_code) == ("value", None, None, None)


def test_a_reason_from_a_newer_sdk_with_the_in_code_default_value_is_a_type_mismatch() -> None:
    details = to_resolution_details(
        evaluation("a-reason-from-a-newer-sdk", is_default=True)  # type: ignore[arg-type]
    )

    assert (details.reason, details.error_code) == (Reason.ERROR, ErrorCode.TYPE_MISMATCH)


def test_a_config_without_a_value_resolves_to_the_in_code_default_value_without_an_error() -> None:
    details = to_resolution_details(evaluation("value-missing", is_default=True))

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
    details = to_resolution_details(evaluation(reason, is_default=True))

    assert (details.value, details.reason, details.error_code) == ("value", Reason.ERROR, error_code)
    assert details.variant is None
    assert details.error_message
