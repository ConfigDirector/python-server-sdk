from __future__ import annotations

from typing import Any

from configdirector import ConfigDirectorLogger


class StubbedLogger:
    def debug(self, message: str, /, *args: Any) -> None: ...

    def info(self, message: str, /, *args: Any) -> None: ...

    def warning(self, message: str, /, *args: Any) -> None: ...

    def error(self, message: str, /, *args: Any) -> None: ...


def create_stubbed_logger() -> ConfigDirectorLogger:
    return StubbedLogger()
