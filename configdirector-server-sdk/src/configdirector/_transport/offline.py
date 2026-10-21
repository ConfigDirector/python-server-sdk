from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping

from .._bundle import ConfigBundle
from .._connection_plan import InCodeDefaults, InlineValues, OfflineFile, OfflineSource, RejectedSource
from .._evaluation import Config
from .._native_values import unconditional_config
from ..errors import (
    ConfigDirectorInitializationError,
    ConfigDirectorTypeError,
    ConfigDirectorValidationError,
)
from ..types import ConfigValue

__all__ = ["OfflineTransport"]

_OFFLINE_ENVIRONMENT_ID = "offline"
_OFFLINE_PROJECT_ID = "offline"


class OfflineTransport:
    def __init__(self, source: OfflineSource, on_bundle: Callable[[ConfigBundle], None]) -> None:
        self._source = source
        self._on_bundle = on_bundle
        self._connected = False

    def connect(self, timeout: float) -> None:
        configs = _offline_configs(self._source)
        self._connected = True
        self._on_bundle(
            ConfigBundle(
                configs=configs,
                kind="full",
                environment_id=_OFFLINE_ENVIRONMENT_ID,
                project_id=_OFFLINE_PROJECT_ID,
            )
        )

    @property
    def is_connected(self) -> bool:
        return self._connected

    def close(self) -> None:
        self._connected = False


def _offline_configs(source: OfflineSource) -> dict[str, Config]:
    match source:
        case InCodeDefaults():
            return {}
        case OfflineFile(path=path):
            return _unconditional_configs(
                _values_in_file(path), f"The offline values file '{os.fspath(path)}'"
            )
        case InlineValues(values=values):
            return _unconditional_configs(values, "The offline values")
        case RejectedSource(message=message):
            raise ConfigDirectorInitializationError(message)


def _values_in_file(path: str | os.PathLike[str]) -> Mapping[str, ConfigValue]:
    try:
        with open(path, "rb") as file:
            document_bytes = file.read()
    except OSError as error:
        raise ConfigDirectorInitializationError(
            f"The offline values file '{os.fspath(path)}' could not be read: {error}"
        ) from error
    try:
        document: object = json.loads(document_bytes)
    except ValueError as error:
        raise ConfigDirectorInitializationError(
            f"The offline values file '{os.fspath(path)}' is not valid JSON: {error}"
        ) from error
    if not isinstance(document, dict):
        raise ConfigDirectorInitializationError(
            f"The offline values file '{os.fspath(path)}' must hold a JSON object with one value per "
            f"config key."
        )
    return document


def _unconditional_configs(values: Mapping[str, ConfigValue], source_description: str) -> dict[str, Config]:
    try:
        return {
            key: unconditional_config(key, value, config_id=f"offline:{key}", value_id=None)
            for key, value in values.items()
        }
    except (ConfigDirectorTypeError, ConfigDirectorValidationError) as error:
        raise ConfigDirectorInitializationError(
            f"{source_description} could not be loaded. {error}"
        ) from error
