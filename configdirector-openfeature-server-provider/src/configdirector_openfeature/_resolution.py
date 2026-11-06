from __future__ import annotations

from configdirector import ConfigEvaluation, ConfigValue
from openfeature.exception import ErrorCode
from openfeature.flag_evaluation import FlagResolutionDetails, Reason

__all__ = ["to_resolution_details"]


def to_resolution_details(evaluation: ConfigEvaluation) -> FlagResolutionDetails[ConfigValue]:
    value = evaluation.value
    if evaluation.reason == "found-match":
        return FlagResolutionDetails(
            value=value, variant=_variant_of(evaluation), reason=Reason.TARGETING_MATCH
        )
    if evaluation.reason == "rollout-skipped-no-identifier":
        return FlagResolutionDetails(value=value, variant=_variant_of(evaluation), reason=Reason.DEFAULT)
    if evaluation.reason == "value-missing":
        return FlagResolutionDetails(value=value, reason=Reason.DEFAULT)
    if evaluation.reason == "config-state-missing":
        return _error(
            value, ErrorCode.FLAG_NOT_FOUND, f"No config with the key '{evaluation.key}' was found."
        )
    if evaluation.reason == "client-not-ready":
        return _error(
            value,
            ErrorCode.PROVIDER_NOT_READY,
            "The ConfigDirector client has not received any configs yet.",
        )
    if evaluation.is_default:
        return _error(
            value,
            ErrorCode.TYPE_MISMATCH,
            f"The value of '{evaluation.key}' does not match the requested type ({evaluation.reason}).",
        )
    return FlagResolutionDetails(value=value)


def _variant_of(evaluation: ConfigEvaluation) -> str | None:
    if evaluation.variation is not None and evaluation.variation.name is not None:
        return evaluation.variation.name
    return evaluation.value_id


def _error(value: ConfigValue, error_code: ErrorCode, message: str) -> FlagResolutionDetails[ConfigValue]:
    return FlagResolutionDetails(
        value=value, reason=Reason.ERROR, error_code=error_code, error_message=message
    )
