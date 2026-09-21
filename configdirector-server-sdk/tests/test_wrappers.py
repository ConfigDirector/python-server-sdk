from __future__ import annotations

import importlib.metadata
import inspect

import pytest

import configdirector
from configdirector import ConfigDirectorTypeError, Metadata, create_client
from configdirector._version import SdkIdentity
from configdirector._wrappers import Wrapper, create_wrapped_client
from tests.helpers import TelemetryRecorder, TransportRecorder

SDK_KEY = "sdk-key"
PROVIDER_NAME = "python-openfeature-server-provider"
PROVIDER_DISTRIBUTION = "configdirector-openfeature-server-provider"


@pytest.fixture
def installed_versions(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    versions: dict[str, str] = {}

    def version(distribution: str) -> str:
        if distribution not in versions:
            raise importlib.metadata.PackageNotFoundError(distribution)
        return versions[distribution]

    monkeypatch.setattr(importlib.metadata, "version", version)
    return versions


class TestWrapperIdentity:
    def test_reports_the_wrapper_name_and_its_installed_version_to_the_transport(
        self, transports: TransportRecorder, installed_versions: dict[str, str]
    ) -> None:
        installed_versions[PROVIDER_DISTRIBUTION] = "4.5.6"

        create_wrapped_client(Wrapper.OPENFEATURE_SERVER_PROVIDER, SDK_KEY)

        options = transports.last.options
        assert options.meta_context["sdkName"] == PROVIDER_NAME
        assert options.meta_context["sdkVersion"] == "4.5.6"
        assert options.sdk_identity == SdkIdentity(sdk_name=PROVIDER_NAME, sdk_version="4.5.6")

    def test_reports_the_wrapper_identity_to_telemetry(
        self, telemetry: TelemetryRecorder, installed_versions: dict[str, str]
    ) -> None:
        installed_versions[PROVIDER_DISTRIBUTION] = "4.5.6"

        create_wrapped_client(Wrapper.OPENFEATURE_SERVER_PROVIDER, SDK_KEY)

        assert telemetry.last.options.sdk_identity == SdkIdentity(sdk_name=PROVIDER_NAME, sdk_version="4.5.6")

    def test_reports_a_development_version_when_the_wrapper_is_not_installed(
        self, transports: TransportRecorder, installed_versions: dict[str, str]
    ) -> None:
        create_wrapped_client(Wrapper.OPENFEATURE_SERVER_PROVIDER, SDK_KEY)

        assert transports.last.options.meta_context["sdkVersion"] == "0.0.0-dev"

    def test_passes_the_client_options_through(self, transports: TransportRecorder) -> None:
        create_wrapped_client(
            Wrapper.OPENFEATURE_SERVER_PROVIDER, SDK_KEY, metadata=Metadata(app_name="checkout")
        )

        assert transports.last.options.meta_context["appName"] == "checkout"


class TestClosedSet:
    @pytest.mark.parametrize(
        "wrapper",
        [
            "my-own-sdk",
            ("my-own-sdk", "1.0.0"),
            SdkIdentity(sdk_name="my-own-sdk", sdk_version="1.0.0"),
            None,
        ],
    )
    def test_rejects_anything_that_is_not_a_known_wrapper(self, wrapper: object) -> None:
        with pytest.raises(ConfigDirectorTypeError, match="known wrapper"):
            create_wrapped_client(wrapper, SDK_KEY)  # type: ignore[arg-type]

    def test_the_public_factory_accepts_no_identity(self) -> None:
        parameters = inspect.signature(create_client).parameters

        assert not [name for name in parameters if "identity" in name or "sdk_name" in name]

    def test_nothing_about_wrappers_is_part_of_the_public_api(self) -> None:
        exported = set(configdirector.__all__)

        assert exported.isdisjoint({"Wrapper", "SdkIdentity", "create_wrapped_client"})
