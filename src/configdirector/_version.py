from __future__ import annotations

from dataclasses import dataclass

__version__ = "1.1.0"

_SDK_NAME = "python-server-sdk"


@dataclass(frozen=True, slots=True)
class SdkIdentity:
    sdk_name: str
    sdk_version: str
