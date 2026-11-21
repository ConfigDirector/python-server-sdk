from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from dataclasses import replace
from typing import Any

import pytest

from configdirector import ConfigDirectorClient, ConnectionOptions, Context, create_client
from configdirector._telemetry import TelemetryCollector, TelemetryCollectorOptions
from configdirector._transport import PollingTransport, StreamingTransport, TransportOptions
from configdirector.client import _ConfigDirectorClient
from configdirector.testing import create_test_client
from tests.forked_processes import (
    HEARTBEAT_PATH,
    POLLING_PATH,
    STREAMING_PATH,
    TELEMETRY_PATH,
    ForkedProcess,
    LinkToTheParentProcess,
    PublishingServer,
    ReceivedRequest,
)
from tests.helpers import (
    NEVER,
    FakeTelemetryCollector,
    FakeTransport,
    RecordingLogger,
    TelemetryRecorder,
    ThreadWatch,
    TransportRecorder,
    wait_for,
)

pytestmark = [
    pytest.mark.skipif(not hasattr(os, "fork"), reason="This platform cannot fork a process"),
    pytest.mark.filterwarnings("ignore:This process .* is multi-threaded:DeprecationWarning"),
]

Serve = Callable[[str | None], PublishingServer]
Fork = Callable[[Callable[[LinkToTheParentProcess], None]], ForkedProcess]
CloseAtTeardown = Callable[[ConfigDirectorClient], ConfigDirectorClient]


@pytest.fixture
def serve() -> Iterator[Serve]:
    servers: list[PublishingServer] = []

    def start(greeting: str | None) -> PublishingServer:
        server = PublishingServer(greeting)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()


@pytest.fixture
def close_at_teardown() -> Iterator[CloseAtTeardown]:
    clients: list[ConfigDirectorClient] = []

    def register(client: ConfigDirectorClient) -> ConfigDirectorClient:
        clients.append(client)
        return client

    yield register
    for client in clients:
        client.close()


@pytest.fixture
def fork() -> Iterator[Fork]:
    forked_processes: list[ForkedProcess] = []

    def start(run: Callable[[LinkToTheParentProcess], None]) -> ForkedProcess:
        forked_process = ForkedProcess(run)
        forked_processes.append(forked_process)
        return forked_process

    yield start
    for forked_process in forked_processes:
        forked_process.end()


def greeting_served_by(client: ConfigDirectorClient) -> str:
    return client.get_value("greeting", "in-code default value")


def session_ids(requests: list[ReceivedRequest]) -> list[str]:
    return [request.body["sessionId"] for request in requests]


def polling_every(interval: float) -> Callable[[TransportOptions], PollingTransport]:
    return lambda options: PollingTransport(replace(options, polling_interval=interval))


def reporting_every(interval: float) -> Callable[[TelemetryCollectorOptions], TelemetryCollector]:
    return lambda options: TelemetryCollector(
        replace(options, initial_flush_delay=interval, flush_interval=interval)
    )


def evaluations_reported(server: PublishingServer, config_key: str) -> int:
    return sum(
        entry["count"]
        for report in server.requests_to(TELEMETRY_PATH)
        for entry in report.body["aggregatedEvents"]["evaluatedConfig"]
        if entry["event"]["key"] == config_key
    )


class TestAStreamingClientInitializedBeforeAFork:
    def test_an_update_published_after_the_fork_is_served_by_the_parent_and_by_the_forked_process(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        client = close_at_teardown(create_client("sdk-key", connection=ConnectionOptions(url=server.url)))
        client.initialize()

        def serve_the_update(link: LinkToTheParentProcess) -> None:
            wait_for(lambda: greeting_served_by(client) == "after the fork")
            link.report(greeting_served_by(client))

        forked_process = fork(serve_the_update)
        server.publish("after the fork")

        assert forked_process.next_report() == "after the fork"
        assert wait_for(lambda: greeting_served_by(client) == "after the fork")

    def test_the_forked_process_serves_the_values_the_parent_held_and_stays_ready(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        client = close_at_teardown(create_client("sdk-key", connection=ConnectionOptions(url=server.url)))
        client.initialize()

        forked_process = fork(lambda link: link.report([greeting_served_by(client), client.is_ready]))

        assert forked_process.next_report() == ["before the fork", True]

    def test_a_watch_registered_before_the_fork_fires_in_the_forked_process_without_a_call_to_the_client(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        client = close_at_teardown(create_client("sdk-key", connection=ConnectionOptions(url=server.url)))
        watched: list[str] = []
        client.watch("greeting", "in-code default value", watched.append)
        client.initialize()

        def wait_for_the_watch(link: LinkToTheParentProcess) -> None:
            wait_for(lambda: "after the fork" in watched)
            link.report(watched)

        forked_process = fork(wait_for_the_watch)
        server.publish("after the fork")

        watched_in_the_forked_process: list[str] = forked_process.next_report()
        assert watched_in_the_forked_process[-1] == "after the fork"

    def test_the_forked_process_calls_the_configs_updated_handlers_with_every_key_when_its_stream_opens(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        client = close_at_teardown(create_client("sdk-key", connection=ConnectionOptions(url=server.url)))
        updates: list[tuple[int, list[str]]] = []
        client.on("configs_updated", lambda event: updates.append((os.getpid(), event.keys)))
        client.initialize()

        def wait_for_an_update(link: LinkToTheParentProcess) -> None:
            wait_for(lambda: any(process_id == os.getpid() for process_id, _ in updates))
            link.report([keys for process_id, keys in updates if process_id == os.getpid()])

        forked_process = fork(wait_for_an_update)

        assert forked_process.next_report() == [["greeting"]]

    def test_client_ready_is_not_emitted_again_in_the_forked_process(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        client = close_at_teardown(create_client("sdk-key", connection=ConnectionOptions(url=server.url)))
        updated_in: list[int] = []
        ready_in: list[int] = []
        client.on("configs_updated", lambda event: updated_in.append(os.getpid()))
        client.on("client_ready", lambda event: ready_in.append(os.getpid()))
        client.initialize()
        wait_for(lambda: ready_in == [os.getpid()])

        def wait_for_an_update(link: LinkToTheParentProcess) -> None:
            wait_for(lambda: os.getpid() in updated_in)
            link.report({"updated in": updated_in, "ready in": ready_in})

        forked_process = fork(wait_for_an_update)

        assert forked_process.next_report() == {
            "updated in": [os.getpid(), forked_process.process_id],
            "ready in": [os.getpid()],
        }

    def test_a_client_that_was_not_ready_at_the_fork_becomes_ready_in_the_forked_process(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server_without_values = serve(None)
        client = close_at_teardown(
            create_client("sdk-key", connection=ConnectionOptions(url=server_without_values.url))
        )
        ready_in: list[int] = []
        client.on("client_ready", lambda event: ready_in.append(os.getpid()))
        client.initialize(timeout=0.05)
        ready_before_the_fork = client.is_ready

        def wait_until_ready(link: LinkToTheParentProcess) -> None:
            wait_for(lambda: os.getpid() in ready_in)
            link.report({"ready in": ready_in, "is ready": client.is_ready})

        forked_process = fork(wait_until_ready)
        server_without_values.publish("after the fork")

        assert ready_before_the_fork is False
        assert forked_process.next_report() == {"ready in": [forked_process.process_id], "is ready": True}

    def test_the_forked_process_opens_its_stream_under_its_own_session_id(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        client = close_at_teardown(create_client("sdk-key", connection=ConnectionOptions(url=server.url)))
        client.initialize()
        session_ids_before_the_fork = session_ids(server.requests_to(STREAMING_PATH))

        fork(LinkToTheParentProcess.wait_for_the_parent)

        assert wait_for(lambda: len(server.requests_to(STREAMING_PATH)) == 2)
        session_id_of_the_parent, session_id_of_the_forked_process = session_ids(
            server.requests_to(STREAMING_PATH)
        )
        assert session_ids_before_the_fork == [session_id_of_the_parent]
        assert session_id_of_the_forked_process != session_id_of_the_parent

    def test_the_parent_keeps_its_stream_after_the_forked_process_exits(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        client = close_at_teardown(create_client("sdk-key", connection=ConnectionOptions(url=server.url)))
        updated_in: list[int] = []
        client.on("configs_updated", lambda event: updated_in.append(os.getpid()))
        client.initialize()
        (session_id_of_the_parent,) = session_ids(server.requests_to(STREAMING_PATH))

        def exit_once_its_stream_is_open(link: LinkToTheParentProcess) -> None:
            wait_for(lambda: os.getpid() in updated_in)

        forked_process = fork(exit_once_its_stream_is_open)
        exit_code = forked_process.wait_for_exit()
        server.publish("after the fork")

        assert exit_code == 0
        assert wait_for(lambda: greeting_served_by(client) == "after the fork")
        assert session_id_of_the_parent not in server.session_ids_of_ended_streams
        assert len(server.requests_to(STREAMING_PATH)) == 2

    def test_closing_the_client_in_the_forked_process_leaves_the_stream_of_the_parent_open(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        client = close_at_teardown(create_client("sdk-key", connection=ConnectionOptions(url=server.url)))
        updated_in: list[int] = []
        client.on("configs_updated", lambda event: updated_in.append(os.getpid()))
        client.initialize()
        (session_id_of_the_parent,) = session_ids(server.requests_to(STREAMING_PATH))

        def close_the_client(link: LinkToTheParentProcess) -> None:
            wait_for(lambda: os.getpid() in updated_in)
            client.close()

        forked_process = fork(close_the_client)
        exit_code = forked_process.wait_for_exit()
        server.publish("after the fork")

        assert exit_code == 0
        assert wait_for(lambda: greeting_served_by(client) == "after the fork")
        assert session_id_of_the_parent not in server.session_ids_of_ended_streams
        assert len(server.requests_to(STREAMING_PATH)) == 2

    def test_initializing_again_in_the_forked_process_leaves_the_stream_of_the_parent_open(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        client = close_at_teardown(create_client("sdk-key", connection=ConnectionOptions(url=server.url)))
        client.initialize()
        (session_id_of_the_parent,) = session_ids(server.requests_to(STREAMING_PATH))

        def initialize_again(link: LinkToTheParentProcess) -> None:
            client.initialize()
            link.report("initialized again")
            link.wait_for_the_parent()

        forked_process = fork(initialize_again)
        forked_process.next_report()
        server.publish("after the fork")

        assert wait_for(lambda: greeting_served_by(client) == "after the fork")
        assert session_id_of_the_parent not in server.session_ids_of_ended_streams
        assert len(server.requests_to(STREAMING_PATH)) == 3

    def test_the_forked_process_sends_the_heartbeats_of_its_stream_on_a_connection_of_its_own(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        client = close_at_teardown(
            _ConfigDirectorClient(
                "sdk-key",
                connection=ConnectionOptions(url=server.url),
                transport_factory=lambda options: StreamingTransport(options, heartbeat_interval=0.02),
            )
        )
        client.initialize()
        (session_id_of_the_parent,) = session_ids(server.requests_to(STREAMING_PATH))

        def heartbeat_ports_of(session_id: str) -> set[int]:
            return {
                heartbeat.peer_port
                for heartbeat in server.requests_to(HEARTBEAT_PATH)
                if heartbeat.body["sessionId"] == session_id
            }

        assert wait_for(lambda: len(heartbeat_ports_of(session_id_of_the_parent)) == 1)
        fork(LinkToTheParentProcess.wait_for_the_parent)

        assert wait_for(lambda: len(server.requests_to(STREAMING_PATH)) == 2)
        session_id_of_the_forked_process = session_ids(server.requests_to(STREAMING_PATH))[1]
        assert wait_for(lambda: len(heartbeat_ports_of(session_id_of_the_forked_process)) == 1)
        assert heartbeat_ports_of(session_id_of_the_forked_process).isdisjoint(
            heartbeat_ports_of(session_id_of_the_parent)
        )

    def test_every_client_initialized_before_the_fork_serves_updates_in_the_forked_process(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        first_client = close_at_teardown(
            create_client("sdk-key", connection=ConnectionOptions(url=server.url))
        )
        second_client = close_at_teardown(
            create_client("sdk-key", connection=ConnectionOptions(url=server.url))
        )
        first_client.initialize()
        second_client.initialize()

        def serve_the_update(link: LinkToTheParentProcess) -> None:
            wait_for(lambda: greeting_served_by(first_client) == "after the fork")
            wait_for(lambda: greeting_served_by(second_client) == "after the fork")
            link.report([greeting_served_by(first_client), greeting_served_by(second_client)])

        forked_process = fork(serve_the_update)
        server.publish("after the fork")

        assert forked_process.next_report() == ["after the fork", "after the fork"]

    def test_a_process_forked_from_a_forked_process_serves_an_update_published_after_its_fork(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        client = close_at_teardown(create_client("sdk-key", connection=ConnectionOptions(url=server.url)))
        client.initialize()

        def serve_the_update(link: LinkToTheParentProcess) -> None:
            wait_for(lambda: greeting_served_by(client) == "after the fork")
            link.report(greeting_served_by(client))

        def fork_again(link: LinkToTheParentProcess) -> None:
            forked_from_the_forked_process = ForkedProcess(serve_the_update)
            try:
                link.report(forked_from_the_forked_process.next_report())
            finally:
                forked_from_the_forked_process.end()

        forked_process = fork(fork_again)
        server.publish("after the fork")

        assert forked_process.next_report() == "after the fork"

    def test_the_forked_process_logs_at_debug_level_that_it_restarts_the_connection(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        logger = RecordingLogger()
        client = close_at_teardown(
            create_client("sdk-key", connection=ConnectionOptions(url=server.url), logger=logger)
        )
        client.initialize()

        def report_what_was_logged(link: LinkToTheParentProcess) -> None:
            link.report([message for message in logger.messages("debug") if "forked process" in message])

        forked_process = fork(report_what_was_logged)

        assert forked_process.next_report() == [
            f"Restarting the connection in forked process {forked_process.process_id}"
        ]


class TestAPollingClientInitializedBeforeAFork:
    def test_an_update_published_after_the_fork_is_served_by_the_parent_and_by_the_forked_process(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        client = close_at_teardown(
            _ConfigDirectorClient(
                "sdk-key",
                connection=ConnectionOptions(url=server.url, mode="polling"),
                transport_factory=polling_every(0.02),
            )
        )
        client.initialize()

        def serve_the_update(link: LinkToTheParentProcess) -> None:
            link.wait_for_the_parent()
            wait_for(lambda: greeting_served_by(client) == "after the fork")
            link.report(greeting_served_by(client))

        forked_process = fork(serve_the_update)
        server.publish("after the fork")
        forked_process.release()

        assert forked_process.next_report() == "after the fork"
        assert wait_for(lambda: greeting_served_by(client) == "after the fork")

    def test_the_forked_process_serves_the_values_the_parent_held_and_stays_ready(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        client = close_at_teardown(
            create_client("sdk-key", connection=ConnectionOptions(url=server.url, mode="polling"))
        )
        client.initialize()

        forked_process = fork(lambda link: link.report([greeting_served_by(client), client.is_ready]))

        assert forked_process.next_report() == ["before the fork", True]

    def test_the_forked_process_polls_under_its_own_session_id(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        client = close_at_teardown(
            _ConfigDirectorClient(
                "sdk-key",
                connection=ConnectionOptions(url=server.url, mode="polling"),
                transport_factory=polling_every(0.02),
            )
        )
        client.initialize()
        (session_id_of_the_parent,) = set(session_ids(server.requests_to(POLLING_PATH)))

        fork(LinkToTheParentProcess.wait_for_the_parent)

        assert wait_for(lambda: len(set(session_ids(server.requests_to(POLLING_PATH)))) == 2)
        (session_id_of_the_forked_process,) = set(session_ids(server.requests_to(POLLING_PATH))) - {
            session_id_of_the_parent
        }
        assert wait_for(
            lambda: session_ids(server.requests_to(POLLING_PATH)).count(session_id_of_the_forked_process) >= 3
        )

    def test_the_forked_process_polls_at_the_fork_with_the_timestamp_the_parent_last_received(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        client = close_at_teardown(
            create_client("sdk-key", connection=ConnectionOptions(url=server.url, mode="polling"))
        )
        client.initialize()
        (poll_of_the_parent,) = server.requests_to(POLLING_PATH)

        fork(LinkToTheParentProcess.wait_for_the_parent)

        assert wait_for(lambda: len(server.requests_to(POLLING_PATH)) == 2)
        poll_at_the_fork = server.requests_to(POLLING_PATH)[1]
        assert poll_at_the_fork.body["sessionId"] != poll_of_the_parent.body["sessionId"]
        assert poll_at_the_fork.body["lastUpdateTimestamp"] == "2026-01-01T00:00:01.000Z"

    def test_a_poll_answered_without_new_values_calls_no_handler_in_the_forked_process(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        client = close_at_teardown(
            create_client("sdk-key", connection=ConnectionOptions(url=server.url, mode="polling"))
        )
        updated_in: list[int] = []
        client.on("configs_updated", lambda event: updated_in.append(os.getpid()))
        client.initialize()

        def report_the_updates(link: LinkToTheParentProcess) -> None:
            link.wait_for_the_parent()
            wait_for(lambda: os.getpid() in updated_in, timeout=0.2)
            link.report(updated_in)

        forked_process = fork(report_the_updates)
        polled_at_the_fork = wait_for(lambda: len(server.requests_to(POLLING_PATH)) == 2)
        forked_process.release()

        assert polled_at_the_fork is True
        assert forked_process.next_report() == [os.getpid()]

    def test_the_forked_process_logs_at_debug_level_that_it_restarts_the_connection(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        logger = RecordingLogger()
        client = close_at_teardown(
            create_client(
                "sdk-key", connection=ConnectionOptions(url=server.url, mode="polling"), logger=logger
            )
        )
        client.initialize()

        def report_what_was_logged(link: LinkToTheParentProcess) -> None:
            link.report([message for message in logger.messages("debug") if "forked process" in message])

        forked_process = fork(report_what_was_logged)

        assert forked_process.next_report() == [
            f"Restarting the connection in forked process {forked_process.process_id}"
        ]


class TestTelemetryOfAForkedProcess:
    def test_an_evaluation_made_in_the_forked_process_is_reported_from_that_process(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        client = close_at_teardown(
            _ConfigDirectorClient(
                "sdk-key",
                connection=ConnectionOptions(url=server.url),
                telemetry_factory=reporting_every(0.02),
            )
        )
        client.initialize()

        def read_a_config(link: LinkToTheParentProcess) -> None:
            client.get_value("read-in-the-forked-process", "in-code default value")
            link.wait_for_the_parent()

        fork(read_a_config)

        assert wait_for(lambda: evaluations_reported(server, "read-in-the-forked-process") == 1)

    def test_an_event_tracked_in_the_forked_process_is_reported_from_that_process(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        client = close_at_teardown(
            _ConfigDirectorClient(
                "sdk-key",
                connection=ConnectionOptions(url=server.url),
                telemetry_factory=reporting_every(0.02),
            )
        )
        client.initialize()

        def track_an_event(link: LinkToTheParentProcess) -> None:
            client.track("tracked-in-the-forked-process")
            link.wait_for_the_parent()

        fork(track_an_event)

        assert wait_for(
            lambda: (
                [
                    tracked_event["name"]
                    for report in server.requests_to(TELEMETRY_PATH)
                    for tracked_event in report.body["discreteEvents"]["trackedEvents"]
                ]
                == ["tracked-in-the-forked-process"]
            )
        )

    def test_what_the_parent_collected_before_the_fork_is_reported_once(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        client = close_at_teardown(
            _ConfigDirectorClient(
                "sdk-key",
                connection=ConnectionOptions(url=server.url),
                telemetry_factory=reporting_every(NEVER),
            )
        )
        client.initialize()
        client.get_value("greeting", "in-code default value", Context(id="user-1"))
        client.track("checkout-completed", Context(id="user-1"))

        def close_the_client(link: LinkToTheParentProcess) -> None:
            client.close()

        exit_code = fork(close_the_client).wait_for_exit()
        client.close()

        reports = server.requests_to(TELEMETRY_PATH)
        assert exit_code == 0
        assert evaluations_reported(server, "greeting") == 1
        assert [
            captured_context["id"]
            for report in reports
            for captured_context in report.body["discreteEvents"]["capturedContexts"]
        ] == ["user-1"]
        assert [
            tracked_event["name"]
            for report in reports
            for tracked_event in report.body["discreteEvents"]["trackedEvents"]
        ] == ["checkout-completed"]

    def test_a_client_created_before_the_fork_and_initialized_after_it_reports_from_the_forked_process(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        client = close_at_teardown(
            _ConfigDirectorClient(
                "sdk-key",
                connection=ConnectionOptions(url=server.url),
                telemetry_factory=reporting_every(0.02),
            )
        )

        def initialize_and_read_a_config(link: LinkToTheParentProcess) -> None:
            client.initialize()
            client.get_value("read-in-the-forked-process", "in-code default value")
            link.wait_for_the_parent()

        fork(initialize_and_read_a_config)

        assert wait_for(lambda: evaluations_reported(server, "read-in-the-forked-process") == 1)


class TestClientsWithNoConnectionToRestartInAForkedProcess:
    def test_a_client_that_was_never_initialized_opens_no_connection_and_logs_nothing(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        logger = RecordingLogger()
        close_at_teardown(
            create_client("sdk-key", connection=ConnectionOptions(url=server.url), logger=logger)
        )
        threads = ThreadWatch()

        def report_threads_and_log(link: LinkToTheParentProcess) -> None:
            link.report(
                {
                    "threads": sorted(threads.new_sdk_threads()),
                    "logged": [message for _, message in logger.records if "forked process" in message],
                }
            )
            link.wait_for_the_parent()

        forked_process = fork(report_threads_and_log)

        assert forked_process.next_report() == {"threads": ["configdirector-telemetry"], "logged": []}
        assert wait_for(lambda: len(server.requests_to(STREAMING_PATH)) > 0, timeout=0.2) is False

    def test_a_closed_client_starts_no_thread(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        client = close_at_teardown(create_client("sdk-key", connection=ConnectionOptions(url=server.url)))
        client.initialize()
        client.close()
        threads = ThreadWatch()

        forked_process = fork(lambda link: link.report(sorted(threads.new_sdk_threads())))

        assert forked_process.next_report() == []

    def test_an_offline_client_starts_no_thread(self, close_at_teardown: CloseAtTeardown, fork: Fork) -> None:
        client = close_at_teardown(
            create_client(connection=ConnectionOptions(mode="offline", values={"greeting": "offline"}))
        )
        client.initialize()
        threads = ThreadWatch()

        forked_process = fork(
            lambda link: link.report([sorted(threads.new_sdk_threads()), greeting_served_by(client)])
        )

        assert forked_process.next_report() == [[], "offline"]

    def test_a_test_client_starts_no_thread(self, fork: Fork) -> None:
        with create_test_client({"greeting": "from the test"}) as test_client:
            test_client.client.initialize()
            threads = ThreadWatch()

            forked_process = fork(
                lambda link: link.report(
                    [sorted(threads.new_sdk_threads()), greeting_served_by(test_client.client)]
                )
            )

            assert forked_process.next_report() == [[], "from the test"]

    def test_a_streaming_client_that_was_refused_opens_no_stream(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        server.accepts_the_sdk_key = False
        client = close_at_teardown(create_client("sdk-key", connection=ConnectionOptions(url=server.url)))
        client.initialize()
        threads = ThreadWatch()

        def report_threads(link: LinkToTheParentProcess) -> None:
            link.report(sorted(threads.new_sdk_threads()))
            link.wait_for_the_parent()

        forked_process = fork(report_threads)

        assert forked_process.next_report() == ["configdirector-telemetry"]
        assert wait_for(lambda: len(server.requests_to(STREAMING_PATH)) > 1, timeout=0.2) is False

    def test_a_polling_client_that_was_refused_does_not_poll(
        self, serve: Serve, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        server = serve("before the fork")
        server.accepts_the_sdk_key = False
        client = close_at_teardown(
            create_client("sdk-key", connection=ConnectionOptions(url=server.url, mode="polling"))
        )
        client.initialize()
        threads = ThreadWatch()

        def report_threads(link: LinkToTheParentProcess) -> None:
            link.report(sorted(threads.new_sdk_threads()))
            link.wait_for_the_parent()

        forked_process = fork(report_threads)

        assert forked_process.next_report() == ["configdirector-telemetry"]
        assert wait_for(lambda: len(server.requests_to(POLLING_PATH)) > 1, timeout=0.2) is False


class _TransportThatCannotRestart(FakeTransport):
    def restart_in_forked_process(self) -> None:
        raise RuntimeError("can't start new thread")


class _TelemetryThatCannotRestart(FakeTelemetryCollector):
    def restart_in_forked_process(self) -> None:
        raise RuntimeError("can't start new thread")


class TestARestartThatFailsInAForkedProcess:
    def test_a_connection_that_cannot_restart_is_logged_as_an_error_and_telemetry_restarts(
        self,
        transports: TransportRecorder,
        telemetry: TelemetryRecorder,
        close_at_teardown: CloseAtTeardown,
        fork: Fork,
    ) -> None:
        logger = RecordingLogger()
        close_at_teardown(
            _ConfigDirectorClient(
                "sdk-key",
                logger=logger,
                transport_factory=lambda options: _TransportThatCannotRestart(options, transports),
                telemetry_factory=telemetry,
            )
        )

        def report_errors_and_restarts(link: LinkToTheParentProcess) -> None:
            report: dict[str, Any] = {
                "errors": logger.messages("error"),
                "telemetry restarts": telemetry.last.restarts_in_forked_processes,
            }
            link.report(report)

        forked_process = fork(report_errors_and_restarts)

        assert forked_process.next_report() == {
            "errors": [
                f"Failed to restart the connection in forked process {forked_process.process_id}: "
                """RuntimeError("can't start new thread")"""
            ],
            "telemetry restarts": 1,
        }

    def test_telemetry_that_cannot_restart_is_logged_as_an_error_and_the_connection_restarts(
        self, transports: TransportRecorder, close_at_teardown: CloseAtTeardown, fork: Fork
    ) -> None:
        logger = RecordingLogger()
        close_at_teardown(
            _ConfigDirectorClient(
                "sdk-key",
                logger=logger,
                transport_factory=transports,
                telemetry_factory=_TelemetryThatCannotRestart,
            )
        )

        def report_errors_and_restarts(link: LinkToTheParentProcess) -> None:
            report: dict[str, Any] = {
                "errors": logger.messages("error"),
                "connection restarts": transports.last.restarts_in_forked_processes,
            }
            link.report(report)

        forked_process = fork(report_errors_and_restarts)

        assert forked_process.next_report() == {
            "errors": [
                f"Failed to restart telemetry in forked process {forked_process.process_id}: "
                """RuntimeError("can't start new thread")"""
            ],
            "connection restarts": 1,
        }
