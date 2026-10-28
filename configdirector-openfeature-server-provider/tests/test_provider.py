from __future__ import annotations

import contextlib
import threading
from pathlib import Path
from typing import Any

import pytest
from configdirector import ConfigDirectorInitializationError, ConfigDirectorValidationError, Metadata
from openfeature import api
from openfeature.evaluation_context import EvaluationContext
from openfeature.event import EventDetails, ProviderEvent, ProviderEventDetails
from openfeature.exception import ErrorCode, OpenFeatureError, ProviderNotReadyError
from openfeature.flag_evaluation import FlagEvaluationDetails, FlagValueType, Reason
from openfeature.hook import Hook, HookContext, HookHints
from openfeature.provider import FeatureProvider, ProviderStatus
from openfeature.provider._registry import provider_registry

from configdirector_openfeature import ConfigDirectorProvider, __version__
from tests.conftest import OfflineProviderFactory, ProviderFactory, ServerFactory
from tests.helpers import (
    POLLING_PATH,
    TELEMETRY_PATH,
    config,
    rule,
    wait_for,
)

SDK_NAME = "python-openfeature-server-provider"

READINESS_CHECK_THREAD = "configdirector-openfeature-readiness-check"


def readiness_check_is_running() -> bool:
    return READINESS_CHECK_THREAD in [thread.name for thread in threading.enumerate()]


class RecordedEvents:
    def __init__(self, event: ProviderEvent) -> None:
        self.events: list[EventDetails] = []
        api.get_client().add_handler(event, self)

    def __call__(self, details: EventDetails) -> None:
        if details.provider_name == "ConfigDirectorProvider":
            self.events.append(details)

    def __len__(self) -> int:
        return len(self.events)


class RecordingHook(Hook):
    def __init__(self) -> None:
        self.after_details: list[FlagEvaluationDetails[FlagValueType]] = []
        self.errors: list[Exception] = []

    def after(
        self, hook_context: HookContext, details: FlagEvaluationDetails[FlagValueType], hints: HookHints
    ) -> None:
        self.after_details.append(details)

    def error(self, hook_context: HookContext, exception: Exception, hints: HookHints) -> None:
        self.errors.append(exception)


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

    def test_reports_telemetry_with_the_app_name_and_version(
        self, serve: ServerFactory, provide: ProviderFactory
    ) -> None:
        server = serve(config("greeting", "string", "hello"))
        provider = provide(server, metadata=Metadata(app_name="checkout", app_version="2.1.0"))
        provider.initialize(EvaluationContext())
        provider.resolve_string_details("greeting", "default")

        provider.shutdown()

        meta_context = server.requests_to(TELEMETRY_PATH)[0].body["metaContext"]
        assert meta_context["appName"] == "checkout"
        assert meta_context["appVersion"] == "2.1.0"

    def test_rejects_a_blank_sdk_key(self) -> None:
        with pytest.raises(ConfigDirectorValidationError):
            ConfigDirectorProvider(" ")

    def test_requires_a_server_sdk_key_outside_offline_mode(self) -> None:
        with pytest.raises(ConfigDirectorValidationError):
            ConfigDirectorProvider()


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
            config("bare-limit", "json", "42"),
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
        assert details.reason == Reason.TARGETING_MATCH

    def test_resolves_a_list(self, provider: ConfigDirectorProvider) -> None:
        details = provider.resolve_object_details("regions", ())

        assert details.value == ["eu", "us"]
        assert details.reason == Reason.TARGETING_MATCH

    def test_reports_a_type_mismatch_for_an_object_flag_holding_a_number(
        self, provider: ConfigDirectorProvider
    ) -> None:
        details = provider.resolve_object_details("bare-limit", {"max": 1})

        assert details.value == {"max": 1}
        assert details.reason == Reason.ERROR
        assert details.error_code == ErrorCode.TYPE_MISMATCH
        assert "bare-limit" in (details.error_message or "")

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


class TestContextKind:
    @pytest.fixture
    def provider(self, serve: ServerFactory, provide: ProviderFactory) -> ConfigDirectorProvider:
        server = serve(
            config("by-key", "string", "nobody", [rule("identifier", "user-1", "matched")]),
            config("by-kind", "string", "nobody", [rule("kind", "device", "matched")]),
        )
        provider = provide(server)
        provider.initialize(EvaluationContext())
        return provider

    def test_targets_by_the_mapped_kind(self, provider: ConfigDirectorProvider) -> None:
        device = provider.resolve_string_details(
            "by-kind", "default", EvaluationContext("42", {"kind": "device"})
        )
        user = provider.resolve_string_details("by-kind", "default", EvaluationContext("42"))

        assert (device.value, device.variant) == ("matched", "rule-value-matched")
        assert (user.value, user.variant) == ("nobody", "default-of-by-kind")

    def test_a_kind_inside_traits_does_not_set_the_kind(self, provider: ConfigDirectorProvider) -> None:
        details = provider.resolve_string_details(
            "by-kind", "default", EvaluationContext("42", {"traits": {"kind": "device"}})
        )

        assert details.value == "nobody"

    @pytest.mark.parametrize("kind", ["Device", "", 42])
    def test_an_invalid_kind_resolves_successfully_to_the_value_for_no_context(
        self, provider: ConfigDirectorProvider, kind: Any
    ) -> None:
        without_a_context = provider.resolve_string_details("by-key", "default")

        details = provider.resolve_string_details(
            "by-key", "default", EvaluationContext("user-1", {"kind": kind})
        )

        assert (details.value, details.reason, details.variant, details.error_code) == (
            "nobody",
            Reason.TARGETING_MATCH,
            "default-of-by-key",
            None,
        )
        assert details == without_a_context


class TestLifecycle:
    def test_evaluates_through_the_openfeature_api(
        self, serve: ServerFactory, provide: ProviderFactory
    ) -> None:
        server = serve(config("enabled", "boolean", "true"))

        api.set_provider_and_wait(provide(server))
        details = api.get_client().get_boolean_details("enabled", False)

        assert details.value is True
        assert details.reason == Reason.TARGETING_MATCH
        assert details.variant == "default-of-enabled"

    def test_announces_the_flags_that_changed(self, serve: ServerFactory, provide: ProviderFactory) -> None:
        server = serve(config("b", "string", "1"), config("a", "string", "2"))
        changes: list[EventDetails] = []
        api.get_client().add_handler(ProviderEvent.PROVIDER_CONFIGURATION_CHANGED, changes.append)

        api.set_provider_and_wait(provide(server))

        wait_for(lambda: bool(changes))
        assert changes[0].flags_changed == ["a", "b"]

    def test_announces_removed_flags_after_the_flags_an_update_carried(
        self, serve: ServerFactory, provide: ProviderFactory
    ) -> None:
        server = serve(config("a", "string", "1"), config("b", "string", "2"))
        changes: list[EventDetails] = []
        api.get_client().add_handler(ProviderEvent.PROVIDER_CONFIGURATION_CHANGED, changes.append)
        api.set_provider_and_wait(provide(server, mode="streaming"))
        wait_for(lambda: bool(changes))

        server.push(config("a", "string", "3"))

        wait_for(lambda: len(changes) == 2)
        assert changes[1].flags_changed == ["a", "b"]
        assert api.get_client().get_string_value("b", "fallback") == "fallback"

    def test_fails_to_initialize_when_no_config_state_arrives_within_the_timeout(
        self, serve: ServerFactory, provide: ProviderFactory
    ) -> None:
        server = serve(config("greeting", "string", "hello"))
        server.stream_released.clear()
        errors = RecordedEvents(ProviderEvent.PROVIDER_ERROR)
        changes_after_the_failure = RecordedEvents(ProviderEvent.PROVIDER_CONFIGURATION_CHANGED)
        client = api.get_client()

        with pytest.raises(ProviderNotReadyError) as failure:
            api.set_provider_and_wait(provide(server, mode="streaming", timeout=0.2))
        wait_for(lambda: not readiness_check_is_running())
        status = client.get_provider_status()
        details = client.get_string_details("greeting", "default")
        server.stream_released.set()
        wait_for(lambda: len(changes_after_the_failure) > 0)

        assert failure.value.error_code == ErrorCode.PROVIDER_NOT_READY
        assert status == ProviderStatus.ERROR
        assert [event.error_code for event in errors.events] == [ErrorCode.PROVIDER_NOT_READY]
        assert (details.value, details.error_code) == ("default", ErrorCode.PROVIDER_NOT_READY)

    def test_fails_to_initialize_when_the_sdk_key_is_rejected(
        self, serve: ServerFactory, provide: ProviderFactory
    ) -> None:
        server = serve(config("greeting", "string", "hello"))
        server.accepts_the_sdk_key = False
        client = api.get_client()

        with pytest.raises(ProviderNotReadyError) as failure:
            api.set_provider_and_wait(provide(server))
        details = client.get_string_details("greeting", "default")

        assert failure.value.error_code == ErrorCode.PROVIDER_NOT_READY
        assert client.get_provider_status() == ProviderStatus.ERROR
        assert (details.value, details.error_code) == ("default", ErrorCode.PROVIDER_NOT_READY)

    def test_reports_ready_once_when_config_state_arrives_after_a_failed_initialization(
        self, serve: ServerFactory, provide: ProviderFactory
    ) -> None:
        server = serve(config("greeting", "string", "hello"))
        server.stream_released.clear()
        ready = RecordedEvents(ProviderEvent.PROVIDER_READY)
        errors = RecordedEvents(ProviderEvent.PROVIDER_ERROR)
        changes = RecordedEvents(ProviderEvent.PROVIDER_CONFIGURATION_CHANGED)
        client = api.get_client()
        with contextlib.suppress(ProviderNotReadyError):
            api.set_provider_and_wait(provide(server, mode="streaming", timeout=0.2))
        wait_for(lambda: len(ready) + len(errors) > 0)
        announced_before_config = len(ready)

        server.stream_released.set()
        wait_for(lambda: len(ready) > announced_before_config)
        server.push(config("greeting", "string", "hello again"))
        wait_for(lambda: len(changes) == 2)
        details = client.get_string_details("greeting", "default")

        assert len(ready) == 1
        assert client.get_provider_status() == ProviderStatus.READY
        assert (details.value, details.error_code) == ("hello again", None)

    def test_reports_ready_when_config_state_arrives_while_openfeature_records_the_failure(
        self, serve: ServerFactory, provide: ProviderFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        server = serve(config("greeting", "string", "hello"))
        server.stream_released.clear()
        provider = provide(server, mode="streaming", timeout=0.2)
        config_state_handled = threading.Event()
        provider._client.on("client_ready", lambda _event: config_state_handled.set())
        config_state_handled_before_the_error_was_recorded: list[bool] = []
        dispatch_event = provider_registry.dispatch_event

        def deliver_config_state_before_recording_the_failure(
            source: FeatureProvider, event: ProviderEvent, details: ProviderEventDetails
        ) -> None:
            if event == ProviderEvent.PROVIDER_ERROR:
                server.stream_released.set()
                config_state_handled_before_the_error_was_recorded.append(config_state_handled.wait(5))
            dispatch_event(source, event, details)

        monkeypatch.setattr(
            provider_registry, "dispatch_event", deliver_config_state_before_recording_the_failure
        )

        with contextlib.suppress(ProviderNotReadyError):
            api.set_provider_and_wait(provider)
        wait_for(lambda: api.get_client().get_provider_status() == ProviderStatus.READY)

        assert config_state_handled_before_the_error_was_recorded == [True]

    def test_does_not_announce_ready_twice_when_config_state_arrives_in_time(
        self, serve: ServerFactory, provide: ProviderFactory
    ) -> None:
        server = serve(config("greeting", "string", "hello"))
        ready = RecordedEvents(ProviderEvent.PROVIDER_READY)

        api.set_provider_and_wait(provide(server))

        assert len(ready) == 1

    def test_shutting_down_closes_the_client(self, serve: ServerFactory, provide: ProviderFactory) -> None:
        provider = provide(serve())
        provider.initialize(EvaluationContext())

        provider.shutdown()

        assert provider._client.closed is True

    def test_shutting_down_stops_waiting_for_openfeature_to_record_a_failure(
        self, serve: ServerFactory, provide: ProviderFactory
    ) -> None:
        server = serve(config("greeting", "string", "hello"))
        server.available = False
        provider = provide(server, timeout=0.2)
        with contextlib.suppress(ProviderNotReadyError):
            provider.initialize(EvaluationContext())

        provider.shutdown()

        assert readiness_check_is_running() is False


class TestHooks:
    def test_runs_an_after_hook_that_sees_targeting_match_and_the_value_id_for_a_served_value(
        self, serve: ServerFactory, provide: ProviderFactory
    ) -> None:
        api.set_provider_and_wait(provide(serve(config("enabled", "boolean", "true"))))
        hook = RecordingHook()
        client = api.get_client()
        client.add_hooks([hook])

        client.get_boolean_value("enabled", False)

        assert [(details.reason, details.variant) for details in hook.after_details] == [
            (Reason.TARGETING_MATCH, "default-of-enabled")
        ]

    def test_runs_an_error_hook_that_sees_flag_not_found_for_a_config_that_does_not_exist(
        self, serve: ServerFactory, provide: ProviderFactory
    ) -> None:
        api.set_provider_and_wait(provide(serve()))
        hook = RecordingHook()
        client = api.get_client()
        client.add_hooks([hook])

        client.get_boolean_value("missing", False)

        [error] = hook.errors
        assert isinstance(error, OpenFeatureError)
        assert error.error_code == ErrorCode.FLAG_NOT_FOUND


class TestOfflineMode:
    def test_resolves_the_offline_values_without_a_server_sdk_key(
        self, provide_offline: OfflineProviderFactory
    ) -> None:
        api.set_provider_and_wait(provide_offline(values={"enabled": True}))

        details = api.get_client().get_boolean_details("enabled", False)

        assert (details.value, details.error_code) == (True, None)

    def test_fails_to_initialize_when_the_offline_values_cannot_be_loaded(
        self, provide_offline: OfflineProviderFactory, tmp_path: Path
    ) -> None:
        provider = provide_offline(file=str(tmp_path / "missing.json"))

        with pytest.raises(ConfigDirectorInitializationError):
            provider.initialize(EvaluationContext())

    def test_is_left_in_the_error_state_when_the_offline_values_cannot_be_loaded(
        self, provide_offline: OfflineProviderFactory, tmp_path: Path
    ) -> None:
        provider = provide_offline(file=str(tmp_path / "missing.json"))

        with contextlib.suppress(ConfigDirectorInitializationError):
            api.set_provider_and_wait(provider)

        assert api.get_client().get_provider_status() == ProviderStatus.ERROR
