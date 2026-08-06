from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from typing import Any, TypeVar

import pytest

from configdirector import ConfigDirectorTypeError
from configdirector._eventsource import (
    EventSourceClient,
    EventSourceMessage,
    ReadyState,
    ReconnectionState,
    StreamClosedError,
    ValueOutOfRangeError,
)

from .helpers import FailingTransport, FakeResponse, FakeTransport, sse, wait_for

URL = "http://localhost/sse"
_R = TypeVar("_R")


def record(sink: list[Any], attribute: str | None, *, returning: _R) -> Callable[[ReconnectionState], _R]:
    def handler(state: ReconnectionState) -> _R:
        sink.append(state if attribute is None else getattr(state, attribute))
        return returning

    return handler


def _append(sink: list[Any], value: Any, result: bool) -> bool:
    sink.append(value)
    return result


def _set(event: threading.Event, result: float) -> float:
    event.set()
    return result


@pytest.fixture
def clients() -> Iterator[list[EventSourceClient]]:
    created: list[EventSourceClient] = []
    yield created
    for client in created:
        client.close()


def build(clients: list[EventSourceClient], **kwargs: object) -> EventSourceClient:
    client = EventSourceClient(URL, **kwargs)  # type: ignore[arg-type]
    clients.append(client)
    return client


class TestRequestConfiguration:
    def test_sends_the_event_stream_accept_header(self, clients: list[EventSourceClient]) -> None:
        transport = FakeTransport(FakeResponse(chunks=sse("data: hi\n\n")))
        client = build(clients, transport=transport, should_reconnect=lambda state: False)

        client.connect()
        assert transport.opened.acquire(timeout=5)

        assert transport.requests[0].headers["Accept"] == "text/event-stream"

    def test_merges_caller_headers(self, clients: list[EventSourceClient]) -> None:
        transport = FakeTransport(FakeResponse(chunks=sse("data: hi\n\n")))
        client = build(
            clients,
            transport=transport,
            headers={"Authorization": "Bearer token"},
            should_reconnect=lambda state: False,
        )

        client.connect()
        assert transport.opened.acquire(timeout=5)

        assert transport.requests[0].headers["Authorization"] == "Bearer token"
        assert transport.requests[0].headers["Accept"] == "text/event-stream"

    def test_sends_a_configured_last_event_id(self, clients: list[EventSourceClient]) -> None:
        transport = FakeTransport(FakeResponse(chunks=sse("data: hi\n\n")))
        client = build(
            clients, transport=transport, last_event_id="abc", should_reconnect=lambda state: False
        )

        client.connect()
        assert transport.opened.acquire(timeout=5)

        assert transport.requests[0].headers["Last-Event-ID"] == "abc"

    def test_omits_the_header_when_there_is_no_last_event_id(self, clients: list[EventSourceClient]) -> None:
        transport = FakeTransport(FakeResponse(chunks=sse("data: hi\n\n")))
        client = build(clients, transport=transport, should_reconnect=lambda state: False)

        client.connect()
        assert transport.opened.acquire(timeout=5)

        assert "Last-Event-ID" not in transport.requests[0].headers

    def test_sends_a_server_supplied_event_id_on_reconnect(self, clients: list[EventSourceClient]) -> None:
        transport = FakeTransport(FakeResponse(chunks=sse("id: 7\ndata: hi\n\n")))
        client = build(
            clients,
            transport=transport,
            calculate_reconnect_delay=lambda state: 0.001,
            should_reconnect=lambda state: transport.attempts < 2,
        )

        client.connect()
        assert wait_for(lambda: transport.attempts >= 2)

        assert transport.requests[1].headers["Last-Event-ID"] == "7"

    def test_passes_the_method_and_body_through(self, clients: list[EventSourceClient]) -> None:
        transport = FakeTransport(FakeResponse(chunks=sse("data: hi\n\n")))
        client = build(
            clients,
            transport=transport,
            method="POST",
            body=b'{"key":"value"}',
            should_reconnect=lambda state: False,
        )

        client.connect()
        assert transport.opened.acquire(timeout=5)

        assert transport.requests[0].method == "POST"
        assert transport.requests[0].body == b'{"key":"value"}'


class TestHandlers:
    def test_calls_on_connect_when_the_stream_opens(self, clients: list[EventSourceClient]) -> None:
        opened = threading.Event()
        transport = FakeTransport(FakeResponse(chunks=sse("data: hi\n\n")))
        client = build(
            clients,
            transport=transport,
            on_connect=opened.set,
            should_reconnect=lambda state: False,
        )

        client.connect()

        assert opened.wait(timeout=5)

    def test_does_not_call_on_connect_for_an_error_response(self, clients: list[EventSourceClient]) -> None:
        connects = []
        transport = FakeTransport(FakeResponse(status=500))
        client = build(
            clients,
            transport=transport,
            on_connect=lambda: connects.append(1),
            should_reconnect=lambda state: False,
        )

        client.connect()
        assert wait_for(lambda: client.ready_state is ReadyState.CLOSED)

        assert connects == []

    def test_delivers_messages_in_order(self, clients: list[EventSourceClient]) -> None:
        received: list[EventSourceMessage] = []
        transport = FakeTransport(FakeResponse(chunks=sse("data: one\n\ndata: two\n\ndata: three\n\n")))
        client = build(
            clients,
            transport=transport,
            on_message=received.append,
            should_reconnect=lambda state: False,
        )

        client.connect()
        assert wait_for(lambda: len(received) == 3)

        assert [message.data for message in received] == ["one", "two", "three"]

    def test_reports_comments(self, clients: list[EventSourceClient]) -> None:
        comments: list[str] = []
        transport = FakeTransport(FakeResponse(chunks=sse(": keep-alive\ndata: hi\n\n")))
        client = build(
            clients,
            transport=transport,
            on_comment=comments.append,
            should_reconnect=lambda state: False,
        )

        client.connect()
        assert wait_for(lambda: comments == ["keep-alive"])

    def test_calls_on_disconnect_for_204(self, clients: list[EventSourceClient]) -> None:
        disconnected = threading.Event()
        transport = FakeTransport(FakeResponse(status=204))
        client = build(clients, transport=transport, on_disconnect=disconnected.set)

        client.connect()

        assert disconnected.wait(timeout=5)
        assert transport.attempts == 1

    def test_calls_on_disconnect_when_reconnecting_is_declined(
        self, clients: list[EventSourceClient]
    ) -> None:
        disconnected = threading.Event()
        transport = FakeTransport(FakeResponse(status=500))
        client = build(
            clients,
            transport=transport,
            on_disconnect=disconnected.set,
            should_reconnect=lambda state: False,
        )

        client.connect()

        assert disconnected.wait(timeout=5)

    def test_does_not_call_on_disconnect_for_an_explicit_close(
        self, clients: list[EventSourceClient]
    ) -> None:
        disconnects = []
        connected = threading.Event()
        transport = FakeTransport(FakeResponse(chunks=sse("data: hi\n\n"), hang=True))
        client = build(
            clients,
            transport=transport,
            on_connect=connected.set,
            on_disconnect=lambda: disconnects.append(1),
        )

        client.connect()
        assert connected.wait(timeout=5)
        client.close()

        assert disconnects == []


class TestReadyState:
    def test_starts_closed(self, clients: list[EventSourceClient]) -> None:
        client = build(clients, transport=FakeTransport(FakeResponse(hang=True)))

        assert client.ready_state is ReadyState.CLOSED

    def test_is_connecting_as_soon_as_connect_returns(self, clients: list[EventSourceClient]) -> None:
        client = build(clients, transport=FakeTransport(FakeResponse(hang=True)))

        client.connect()

        assert client.ready_state in (ReadyState.CONNECTING, ReadyState.OPEN)

    def test_is_open_while_the_stream_is_live(self, clients: list[EventSourceClient]) -> None:
        connected = threading.Event()
        client = build(
            clients,
            transport=FakeTransport(FakeResponse(chunks=sse("data: hi\n\n"), hang=True)),
            on_connect=connected.set,
        )

        client.connect()
        assert connected.wait(timeout=5)

        assert client.ready_state is ReadyState.OPEN

    def test_returns_to_closed_after_close(self, clients: list[EventSourceClient]) -> None:
        client = build(clients, transport=FakeTransport(FakeResponse(hang=True)))

        client.connect()
        client.close()

        assert client.ready_state is ReadyState.CLOSED

    def test_returns_to_closed_when_the_server_says_no_content(
        self, clients: list[EventSourceClient]
    ) -> None:
        disconnected = threading.Event()
        client = build(
            clients,
            transport=FakeTransport(FakeResponse(status=204)),
            on_disconnect=disconnected.set,
        )

        client.connect()
        assert disconnected.wait(timeout=5)

        assert client.ready_state is ReadyState.CLOSED


class TestErrors:
    def test_reports_a_transport_failure(self, clients: list[EventSourceClient]) -> None:
        errors: list[BaseException] = []
        transport = FailingTransport(OSError("connection refused"))
        client = build(
            clients,
            transport=transport,
            on_error=errors.append,
            should_reconnect=lambda state: False,
        )

        client.connect()
        assert wait_for(lambda: len(errors) == 1)

        assert isinstance(errors[0], OSError)

    def test_does_not_report_http_error_statuses_as_errors(self, clients: list[EventSourceClient]) -> None:
        errors: list[BaseException] = []
        client = build(
            clients,
            transport=FakeTransport(FakeResponse(status=500)),
            on_error=errors.append,
            should_reconnect=lambda state: False,
        )

        client.connect()
        assert wait_for(lambda: client.ready_state is ReadyState.CLOSED)

        assert errors == []

    @pytest.mark.parametrize("delay", [0, -1, 3_600.001, float("inf"), float("nan"), "soon", None])
    def test_reports_an_out_of_range_reconnect_delay(
        self, clients: list[EventSourceClient], delay: object
    ) -> None:
        errors: list[BaseException] = []
        seen = threading.Event()

        def calculate(state: ReconnectionState) -> object:
            seen.set()
            return delay

        client = build(
            clients,
            transport=FakeTransport(FakeResponse(chunks=sse("retry: 5\ndata: hi\n\n"))),
            on_error=errors.append,
            calculate_reconnect_delay=calculate,
        )

        client.connect()
        assert seen.wait(timeout=5)
        assert wait_for(lambda: len(errors) >= 1)
        client.close()

        assert isinstance(errors[0], ValueOutOfRangeError)

    @pytest.mark.parametrize("delay", [0.001, 3_600.0])
    def test_accepts_the_boundary_delays(self, clients: list[EventSourceClient], delay: float) -> None:
        errors: list[BaseException] = []
        seen = threading.Event()

        def calculate(state: ReconnectionState) -> float:
            seen.set()
            return delay

        client = build(
            clients,
            transport=FakeTransport(FakeResponse(chunks=sse("data: hi\n\n"))),
            on_error=errors.append,
            calculate_reconnect_delay=calculate,
        )

        client.connect()
        assert seen.wait(timeout=5)
        client.close()

        assert errors == []

    def test_a_raising_handler_does_not_stop_the_loop(self, clients: list[EventSourceClient]) -> None:
        received: list[str] = []

        def explode(message: EventSourceMessage) -> None:
            received.append(message.data)
            raise RuntimeError("boom")

        client = build(
            clients,
            transport=FakeTransport(FakeResponse(chunks=sse("data: one\n\ndata: two\n\n"))),
            on_message=explode,
            should_reconnect=lambda state: False,
        )

        client.connect()
        assert wait_for(lambda: received == ["one", "two"])

    def test_a_raising_should_reconnect_falls_back_to_reconnecting(
        self, clients: list[EventSourceClient]
    ) -> None:
        transport = FakeTransport(FakeResponse(status=500))

        def explode(state: ReconnectionState) -> bool:
            raise RuntimeError("boom")

        client = build(
            clients,
            transport=transport,
            should_reconnect=explode,
            calculate_reconnect_delay=lambda state: 0.001,
        )

        client.connect()

        assert wait_for(lambda: transport.attempts >= 3)


class TestStatusHandling:
    def test_passes_the_status_to_should_reconnect(self, clients: list[EventSourceClient]) -> None:
        statuses: list[int | None] = []
        client = build(
            clients,
            transport=FakeTransport(FakeResponse(status=404)),
            should_reconnect=record(statuses, "status", returning=False),
        )

        client.connect()
        assert wait_for(lambda: statuses == [404])

    def test_reconnects_after_a_server_error_by_default(self, clients: list[EventSourceClient]) -> None:
        transport = FakeTransport(FakeResponse(status=503))
        client = build(clients, transport=transport, calculate_reconnect_delay=lambda state: 0.001)

        client.connect()

        assert wait_for(lambda: transport.attempts >= 3)


class TestReconnection:
    def test_reconnects_when_the_stream_ends(self, clients: list[EventSourceClient]) -> None:
        connects: list[int] = []
        transport = FakeTransport(FakeResponse(chunks=sse("data: hi\n\n")))
        client = build(
            clients,
            transport=transport,
            on_connect=lambda: connects.append(1),
            calculate_reconnect_delay=lambda state: 0.001,
            should_reconnect=lambda state: len(connects) < 3,
        )

        client.connect()
        assert wait_for(lambda: len(connects) == 3)

    def test_reports_the_stream_closing_as_the_reason(self, clients: list[EventSourceClient]) -> None:
        reasons: list[BaseException | None] = []
        client = build(
            clients,
            transport=FakeTransport(FakeResponse(chunks=sse("data: hi\n\n"))),
            should_reconnect=record(reasons, "error", returning=False),
        )

        client.connect()
        assert wait_for(lambda: len(reasons) == 1)

        assert isinstance(reasons[0], StreamClosedError)

    def test_counts_consecutive_failures(self, clients: list[EventSourceClient]) -> None:
        attempts: list[int] = []

        def should_reconnect(state: ReconnectionState) -> bool:
            attempts.append(state.attempt)
            return state.attempt < 3

        client = build(
            clients,
            transport=FakeTransport(FakeResponse(status=503)),
            should_reconnect=should_reconnect,
            calculate_reconnect_delay=lambda state: 0.001,
        )

        client.connect()
        assert wait_for(lambda: attempts == [1, 2, 3])

    def test_a_successful_connection_resets_the_counter(self, clients: list[EventSourceClient]) -> None:
        attempts: list[int] = []
        client = build(
            clients,
            transport=FakeTransport(FakeResponse(chunks=sse("data: hi\n\n"))),
            should_reconnect=lambda state: _append(attempts, state.attempt, len(attempts) < 2),
            calculate_reconnect_delay=lambda state: 0.001,
        )

        client.connect()
        assert wait_for(lambda: len(attempts) == 3)

        assert attempts == [1, 1, 1]

    def test_a_fresh_connect_resets_the_counter(self, clients: list[EventSourceClient]) -> None:
        attempts: list[int] = []
        disconnected = threading.Event()
        client = build(
            clients,
            transport=FakeTransport(FakeResponse(status=503)),
            should_reconnect=record(attempts, "attempt", returning=False),
            on_disconnect=disconnected.set,
        )

        for _ in range(2):
            disconnected.clear()
            client.connect()
            assert disconnected.wait(timeout=5)

        assert attempts == [1, 1]

    def test_the_retry_field_sets_the_server_delay_in_seconds(self, clients: list[EventSourceClient]) -> None:
        seen: list[float] = []
        client = build(
            clients,
            transport=FakeTransport(FakeResponse(chunks=sse("retry: 5000\ndata: hi\n\n"))),
            should_reconnect=record(seen, "server_reconnect_delay", returning=False),
        )

        client.connect()
        assert wait_for(lambda: len(seen) == 1)

        # The SSE field is milliseconds; the Python API is seconds throughout.
        assert seen == [5.0]

    def test_the_default_server_delay_is_two_seconds(self, clients: list[EventSourceClient]) -> None:
        seen: list[ReconnectionState] = []
        client = build(
            clients,
            transport=FakeTransport(FakeResponse(chunks=sse("data: hi\n\n"))),
            should_reconnect=record(seen, None, returning=False),
        )

        client.connect()
        assert wait_for(lambda: len(seen) == 1)

        assert seen[0].attempt == 1
        assert seen[0].server_reconnect_delay == 2.0

    def test_connect_is_ignored_while_already_connected(self, clients: list[EventSourceClient]) -> None:
        connected = threading.Event()
        transport = FakeTransport(FakeResponse(chunks=sse("data: hi\n\n"), hang=True))
        client = build(clients, transport=transport, on_connect=connected.set)

        client.connect()
        client.connect()
        client.connect()
        assert connected.wait(timeout=5)

        assert transport.attempts == 1


class TestClose:
    def test_close_cancels_a_pending_reconnect(self, clients: list[EventSourceClient]) -> None:
        scheduled = threading.Event()
        transport = FakeTransport(FakeResponse(status=503))
        client = build(
            clients,
            transport=transport,
            calculate_reconnect_delay=lambda state: _set(scheduled, 3.0),
        )

        client.connect()
        assert scheduled.wait(timeout=5)
        client.close()
        attempts_at_close = transport.attempts

        assert not wait_for(lambda: transport.attempts > attempts_at_close, timeout=0.3)

    def test_close_allows_a_later_connect(self, clients: list[EventSourceClient]) -> None:
        transport = FakeTransport(FakeResponse(chunks=sse("data: hi\n\n"), hang=True))
        connected = threading.Event()
        client = build(clients, transport=transport, on_connect=connected.set)

        client.connect()
        assert connected.wait(timeout=5)
        client.close()

        connected.clear()
        client.connect()
        assert connected.wait(timeout=5)
        assert transport.attempts == 2

    def test_close_is_idempotent(self, clients: list[EventSourceClient]) -> None:
        client = build(clients, transport=FakeTransport(FakeResponse(hang=True)))

        client.connect()
        client.close()
        client.close()

        assert client.ready_state is ReadyState.CLOSED

    def test_close_from_inside_a_handler_does_not_deadlock(self, clients: list[EventSourceClient]) -> None:
        done = threading.Event()
        client = build(clients, transport=FakeTransport(FakeResponse(chunks=sse("data: hi\n\n"))))

        def on_message(message: EventSourceMessage) -> None:
            client.close()
            done.set()

        client.on_message = on_message
        client.connect()

        assert done.wait(timeout=5)
        assert client.ready_state is ReadyState.CLOSED


class TestInvalidOptions:
    @pytest.mark.parametrize(
        "option",
        [
            "on_connect",
            "on_disconnect",
            "on_message",
            "on_comment",
            "on_error",
            "should_reconnect",
            "calculate_reconnect_delay",
        ],
    )
    def test_a_non_callable_handler_is_rejected(self, option: str) -> None:
        with pytest.raises(ConfigDirectorTypeError, match=option):
            EventSourceClient(URL, **{option: "not callable"})  # type: ignore[arg-type]


class TestConcurrentLifecycle:
    def test_simultaneous_connects_open_one_connection(self, clients: list[EventSourceClient]) -> None:
        # Catches a missing "already running" guard, which would fail this every time. It cannot
        # catch the interleaving the lock exists for: that needs a preempt between the state
        # check and the assignment, which only shows up under a forced tiny switch interval.
        transport = FakeTransport(FakeResponse(chunks=sse("data: hi\n\n"), hang=True))
        client = build(clients, transport=transport)
        ready = threading.Barrier(8)

        def race() -> None:
            ready.wait()
            client.connect()

        threads = [threading.Thread(target=race) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        assert wait_for(lambda: transport.attempts >= 1)
        assert transport.attempts == 1

    def test_a_late_connection_does_not_reopen_a_closed_client(
        self, clients: list[EventSourceClient]
    ) -> None:
        release = threading.Event()
        opened = threading.Event()

        class SlowTransport:
            attempts = 0

            def __call__(self, request: object) -> FakeResponse:
                opened.set()
                # Long enough that close() lands first, short enough that the worker is not
                # still parked here when close() waits for it.
                release.wait(0.05)
                return FakeResponse(chunks=sse("data: late\n\n"), hang=True)

        received: list[EventSourceMessage] = []
        client = build(clients, transport=SlowTransport(), on_message=received.append)

        client.connect()
        assert opened.wait(timeout=5)
        client.close()
        release.set()

        # The connection completes after close(). _open() already refuses a stopped client, so
        # this pins the observable guarantee rather than any single guard.
        assert not wait_for(lambda: client.ready_state is not ReadyState.CLOSED, timeout=0.3)
        assert received == []
