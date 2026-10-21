from __future__ import annotations

from typing import TypeGuard

from .errors import ConfigDirectorValidationError

__all__ = ["validate_config_key", "validated_server_sdk_key"]


def validate_config_key(config_key: str) -> None:
    if not _has_content(config_key):
        raise ConfigDirectorValidationError("Invalid config key. The config key must be a non-empty string.")


def validated_server_sdk_key(server_sdk_key: str | None) -> str:
    if _has_content(server_sdk_key):
        return server_sdk_key
    raise ConfigDirectorValidationError(
        "No server SDK key was provided, the client cannot be instantiated without a valid server SDK key"
    )


def _has_content(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value.strip())
