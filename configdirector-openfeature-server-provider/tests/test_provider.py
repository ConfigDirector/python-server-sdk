from __future__ import annotations

import pytest
from configdirector import ConfigDirectorValidationError, Metadata
from openfeature import api
from openfeature.evaluation_context import EvaluationContext
from openfeature.event import EventDetails, ProviderEvent
from openfeature.exception import ErrorCode
from openfeature.flag_evaluation import Reason
from openfeature.provider import ProviderStatus

from configdirector_openfeature import ConfigDirectorProvider, __version__
from tests.conftest import ProviderFactory, ServerFactory
from tests.helpers import (
    POLLING_PATH,
    TELEMETRY_PATH,
    config,
    rule,
    set_provider_and_wait,
    wait_for,
)

SDK_NAME = "python-openfeature-server-provider"


class ReadyEvents:
    def __init__(self) -> None:
        self.events: list[EventDetails] = []
        api.get_client().add_handler(ProviderEvent.PROVIDER_READY, self)

    def __call__(self, details: EventDetails) -> None:
        if details.provider_name == "ConfigDirectorProvider":
            self.events.append(details)

    def __len__(self) -> int:
        return len(self.events)


class TestIdentity:
    def test_fetches_configs_under_its_own_name_and_version(
        self, serve: ServerFactory, provide: ProviderFactory
    ) -> None:
        server = serve(config("greeting", "string", "hello"))

        provide(server).initialize(EvaluationContext())

        request = server.requests_to(POLLING_PATH)[0]
        assert request.body["metaContext"]["sdkName"] == SDK_NAME
        assert request.body["metaContext"]["sdkVersion"] == __version__
        assert request.headers["User-Agent"] == f"{SDK_NAME}/{__version__}"

    def test_reports_telemetry_under_its_own_name_and_version(
        self, serve: ServerFactory, provide: ProviderFactory
    ) -> None:
        server = serve(config("greeting", "string", "hello"))
        provider = provide(server)
        provider.initialize(EvaluationContext())
        provider.resolve_string_details("greeting", "default")

        provider.shutdown()

        request = server.requests_to(TELEMETRY_PATH)[0]
        assert request.body["metaContext"] == {"sdkName": SDK_NAME, "sdkVersion": __version__}
        assert request.headers["User-Agent"] == f"{SDK_NAME}/{__version__}"

    def test_names_itself_to_openfeature(self, serve: ServerFactory, provide: ProviderFactory) -> None:
        assert provide(serve()).get_metadata().name == "ConfigDirectorProvider"


class TestConstruction:
    def test_passes_the_client_options_through(self, serve: ServerFactory, provide: ProviderFactory) -> None:
        server = serve(config("greeting", "string", "hello"))

        provide(server, metadata=Metadata(app_name="checkout", app_version="2.1.0")).initialize(
            EvaluationContext()
        )

        meta_context = server.requests_to(POLLING_PATH)[0].body["metaContext"]
        assert meta_context["appName"] == "checkout"
        assert meta_context["appVersion"] == "2.1.0"

    def test_rejects_a_blank_sdk_key(self) -> None:
        with pytest.raises(ConfigDirectorValidationError):
            ConfigDirectorProvider(" ")


class TestResolution:
    @pytest.fixture
    def provider(self, serve: ServerFactory, provide: ProviderFactory) -> ConfigDirectorProvider:
        server = serve(
            config("enabled", "boolean", "true"),
            config("greeting", "string", "hello"),
            config("limit", "integer", "42"),
            config("ratio", "float", "1.5"),
            config("whole-ratio", "float", "2"),
            config("theme", "json", '{"color": "blue", "sizes": [1, 2]}'),
            config("regions", "json", '["eu", "us"]'),
        )
        provider = provide(server)
        provider.initialize(EvaluationContext())
        return provider

    def test_resolves_a_boolean(self, provider: ConfigDirectorProvider) -> None:
        details = provider.resolve_boolean_details("enabled", False)

        assert details.value is True
        assert details.reason == Reason.TARGETING_MATCH
        assert details.variant == "default-of-enabled"
        assert details.error_code is None

    def test_resolves_a_string(self, provider: ConfigDirectorProvider) -> None:
        assert provider.resolve_string_details("greeting", "default").value == "hello"

    def test_resolves_an_integer(self, provider: ConfigDirectorProvider) -> None:
        assert provider.resolve_integer_details("limit", 0).value == 42

    def test_resolves_a_float(self, provider: ConfigDirectorProvider) -> None:
        assert provider.resolve_float_details("ratio", 0.0).value == 1.5

    def test_resolves_a_float_when_the_default_is_a_whole_number(
        self, provider: ConfigDirectorProvider
    ) -> None:
        value = provider.resolve_float_details("whole-ratio", 1).value

        assert value == 2.0
        assert isinstance(value, float)

    def test_resolves_an_object(self, provider: ConfigDirectorProvider) -> None:
        details = provider.resolve_object_details("theme", {})

        assert details.value == {"color": "blue", "sizes": [1, 2]}

    def test_resolves_a_list(self, provider: ConfigDirectorProvider) -> None:
        assert provider.resolve_object_details("regions", ()).value == ["eu", "us"]

    def test_returns_the_default_for_an_unknown_flag(self, provider: ConfigDirectorProvider) -> None:
        details = provider.resolve_string_details("missing", "default")

        assert details.value == "default"
        assert details.reason == Reason.ERROR
        assert details.error_code == ErrorCode.FLAG_NOT_FOUND
        assert details.variant is None

    def test_returns_a_plain_default_for_an_unknown_object_flag(
        self, provider: ConfigDirectorProvider
    ) -> None:
        details = provider.resolve_object_details("missing", ("a", {"b": ("c",)}))

        assert details.value == ["a", {"b": ["c"]}]

    def test_reports_a_type_mismatch(self, provider: ConfigDirectorProvider) -> None:
        details = provider.resolve_integer_details("greeting", 7)

        assert details.value == 7
        assert details.reason == Reason.ERROR
        assert details.error_code == ErrorCode.TYPE_MISMATCH
        assert "greeting" in (details.error_message or "")

    def test_one_resolution_does_not_leak_into_the_next(
        self, provider: ConfigDirectorProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider.resolve_string_details("greeting", "default")
        monkeypatch.setattr(provider._client, "get_value", lambda key, default, context: default)

        details = provider.resolve_string_details("greeting", "default")

        assert (details.value, details.reason, details.variant) == ("default", None, None)


class TestContext:
    def test_targets_by_the_mapped_context(self, serve: ServerFactory, provide: ProviderFactory) -> None:
        server = serve(
            config("by-key", "string", "nobody", [rule("identifier", "user-1", "matched")]),
            config("by-name", "string", "nobody", [rule("name", "Ada", "matched")]),
            config("by-trait", "string", "nobody", [rule("traits", "pro", "matched", trait="/plan")]),
        )
        provider = provide(server)
        provider.initialize(EvaluationContext())
        context = EvaluationContext("user-1", {"name": "Ada", "traits": {"plan": "pro"}})

        for key in ("by-key", "by-name", "by-trait"):
            details = provider.resolve_string_details(key, "default", context)
            assert (key, details.value, details.variant) == (key, "matched", "rule-value-matched")
            assert provider.resolve_string_details(key, "default").value == "nobody"


class TestLifecycle:
    def test_evaluates_through_the_openfeature_api(
        self, serve: ServerFactory, provide: ProviderFactory
    ) -> None:
        server = serve(config("enabled", "boolean", "true"))

        set_provider_and_wait(provide(server))
        details = api.get_client().get_boolean_details("enabled", False)

        assert details.value is True
        assert details.reason == Reason.TARGETING_MATCH
        assert details.variant == "default-of-enabled"

    def test_announces_the_flags_that_changed(self, serve: ServerFactory, provide: ProviderFactory) -> None:
        server = serve(config("b", "string", "1"), config("a", "string", "2"))
        changes: list[EventDetails] = []
        api.get_client().add_handler(ProviderEvent.PROVIDER_CONFIGURATION_CHANGED, changes.append)

        set_provider_and_wait(provide(server))

        wait_for(lambda: bool(changes))
        assert changes[0].flags_changed == ["a", "b"]

    def test_reports_not_ready_until_config_state_arrives(
        self, serve: ServerFactory, provide: ProviderFactory
    ) -> None:
        server = serve(config("greeting", "string", "hello"))
        server.stream_released.clear()
        provider = provide(server, mode="streaming", timeout=0.2)
        ready = ReadyEvents()
        client = api.get_client()

        set_provider_and_wait(provider)
        before = client.get_string_details("greeting", "default")
        announced = len(ready)
        server.stream_released.set()
        wait_for(lambda: len(ready) > announced)
        after = client.get_string_details("greeting", "default")

        assert (before.value, before.error_code) == ("default", ErrorCode.PROVIDER_NOT_READY)
        assert (after.value, after.error_code) == ("hello", None)
        assert client.get_provider_status() == ProviderStatus.READY

    def test_does_not_announce_ready_twice_when_config_state_arrives_in_time(
        self, serve: ServerFactory, provide: ProviderFactory
    ) -> None:
        server = serve(config("greeting", "string", "hello"))
        ready = ReadyEvents()

        set_provider_and_wait(provide(server))

        assert len(ready) == 1

    def test_shutting_down_closes_the_client(self, serve: ServerFactory, provide: ProviderFactory) -> None:
        provider = provide(serve())
        provider.initialize(EvaluationContext())

        provider.shutdown()

        assert provider._client.closed is True
