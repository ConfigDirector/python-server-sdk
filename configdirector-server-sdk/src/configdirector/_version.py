from __future__ import annotations

from dataclasses import dataclass

__version__ = "1.4.0"


@dataclass(frozen=True, slots=True)
class SdkIdentity:
    sdk_name: str
    sdk_version: str

    @property
    def user_agent(self) -> str:
        return f"{self.sdk_name}/{self.sdk_version}"


SERVER_SDK_IDENTITY = SdkIdentity(sdk_name="python-server-sdk", sdk_version=__version__)
