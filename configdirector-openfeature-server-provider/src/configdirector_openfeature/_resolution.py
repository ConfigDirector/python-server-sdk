from __future__ import annotations

from typing import TypeVar

from configdirector import ConfigEvaluation
from openfeature.exception import ErrorCode
from openfeature.flag_evaluation import FlagResolutionDetails, Reason

__all__ = ["to_resolution_details"]

T = TypeVar("T")


def to_resolution_details(value: T, evaluation: ConfigEvaluation | None) -> FlagResolutionDetails[T]:
    if evaluation is None:
        return FlagResolutionDetails(value=value)

    if evaluation.reason == "found-match":
        return FlagResolutionDetails(value=value, variant=evaluation.value_id, reason=Reason.TARGETING_MATCH)
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


def _error(value: T, error_code: ErrorCode, message: str) -> FlagResolutionDetails[T]:
    return FlagResolutionDetails(
        value=value, reason=Reason.ERROR, error_code=error_code, error_message=message
    )
