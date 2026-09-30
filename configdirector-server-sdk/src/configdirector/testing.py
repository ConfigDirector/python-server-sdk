"""Testing tools for the ConfigDirector Python server SDK.

A **test client** is the SDK's real client connected to an in-memory server that your test
controls. Only the connection to ConfigDirector and the telemetry are replaced. Everything else is
the same code that runs in production, so the code under test behaves exactly as it does against
ConfigDirector, and no network connection is opened, no telemetry is sent, and no thread is started.

Example::

    from configdirector.testing import create_test_client

    with create_test_client({"new-checkout": True}) as test_client:
        service = CheckoutService(test_client.client)
        test_client.client.initialize()

        assert service.is_new_checkout_enabled("user-123")

        test_client.set_value("new-checkout", False)
        assert not service.is_new_checkout_enabled("user-123")
"""

from __future__ import annotations

from collections.abc import Mapping
from types import TracebackType

from ._in_memory_connection import InMemoryConnection
from .types import ConfigDirectorClient, ConfigDirectorLogger, ConfigValue

__all__ = ["TestClient", "create_test_client"]


class TestClient:
    """A real ConfigDirector client connected to an in-memory server that the test controls.

    Built by :func:`create_test_client`. The client under :attr:`client` is the SDK's production
    client: value parsing, targeting evaluation, watches, events, and readiness behave as they do
    against ConfigDirector. Only the connection and telemetry are replaced.

    Every operation that changes values delivers the change on the calling thread before it
    returns, so watches and ``configs_updated`` handlers run on the test's thread, and an assertion
    can follow the call directly.

    A test client is a context manager that closes its client on exit. Unlike the client's own
    context manager, entering it does not initialize the client: the code under test owns that call.
    """

    __test__ = False

    def __init__(self, connection: InMemoryConnection) -> None:
        self._connection = connection

    @property
    def client(self) -> ConfigDirectorClient:
        """The SDK client to hand to the code under test.

        It starts uninitialized, like a production client; ``initialize`` completes at once with
        the stored values unless initialization is held or armed to fail.
        """
        return self._connection.client

    def set_value(self, key: str, value: ConfigValue) -> None:
        """Store ``value`` under ``key`` and, when the client is connected, deliver it as an
        update carrying only that key, so reads, watches, and ``configs_updated`` handlers see it.

        The config type follows from the value's type: a ``bool``; an ``int`` (an integer
        config); a ``float`` (a float config); a ``str``; or a ``dict`` with ``str`` keys or a
        ``list`` (a JSON config). Every context receives the same value.

        Args:
            key: The config key, not blank.
            value: The value to serve.

        Raises:
            ConfigDirectorTypeError: If ``value`` is ``None`` or of an unsupported type, or JSON
                contents hold an unsupported value or a non-``str`` key.
            ConfigDirectorValidationError: If ``key`` is blank, or ``value`` is a non-finite
                number or an integer with too many digits to be written out.
        """
        self._connection.set_value(key, value)

    def remove_value(self, key: str) -> None:
        """Remove ``key`` and, when the client is connected, deliver a full update without it, so
        reads fall back to the in-code default value and watches of ``key`` receive that default.

        Args:
            key: The config key, not blank.

        Raises:
            ConfigDirectorValidationError: If ``key`` is blank.
        """
        self._connection.remove_value(key)

    def replace_values(self, values: Mapping[str, ConfigValue]) -> None:
        """Replace every stored value with ``values``, disarm any armed hold or failure, and, when
        the client is connected, deliver the new values as a full update. Use it to reset a test
        client shared across tests.

        Args:
            values: The values to serve from now on, keyed by config key.

        Raises:
            ConfigDirectorTypeError: As :meth:`set_value`, in which case nothing changes.
            ConfigDirectorValidationError: As :meth:`set_value`, in which case nothing changes.
        """
        self._connection.replace_values(values)

    def hold_initialization(self) -> None:
        """Make the next ``initialize`` wait until :meth:`complete_initialization` or
        :meth:`fail_initialization` is called, or until the client's timeout elapses. Because
        ``initialize`` blocks, a test calls it on another thread.
        """
        self._connection.hold_initialization()

    def complete_initialization(self) -> None:
        """Deliver the stored values to a held ``initialize``, on the calling thread, so the client
        is ready when this returns. When a hold is armed but no ``initialize`` has started, disarm
        the hold instead.
        """
        self._connection.complete_initialization()

    def fail_initialization(self) -> None:
        """Fail a held ``initialize`` with an unrecoverable connection error, or arm the next one
        to fail. ``initialize`` completes promptly with the client not ready, and the error is
        logged.
        """
        self._connection.fail_initialization()

    def close(self) -> None:
        """Close the client. Closing twice is harmless."""
        self._connection.client.close()

    def __enter__(self) -> TestClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def create_test_client(
    values: Mapping[str, ConfigValue] | None = None,
    *,
    timeout: float | None = None,
    logger: ConfigDirectorLogger | None = None,
) -> TestClient:
    """Create a test client serving ``values``.

    Args:
        values: The values to serve, keyed by config key; see :meth:`TestClient.set_value` for
            the types and how each becomes a config. Defaults to none.
        timeout: The connection timeout of the SDK client **in seconds**, which bounds how long a
            held ``initialize`` waits. Defaults to the SDK's production timeout.
        logger: Where the SDK client writes. Defaults to the standard library logger named
            ``"configdirector"``, as for a production client, so pytest's ``caplog`` captures it.

    Returns:
        A test client whose :attr:`TestClient.client` has not been initialized yet.

    Raises:
        ConfigDirectorTypeError: If a value in ``values`` cannot be encoded, as for
            :meth:`TestClient.set_value`.
        ConfigDirectorValidationError: If a key or value in ``values`` is invalid, as for
            :meth:`TestClient.set_value`.
    """
    return TestClient(InMemoryConnection(values, timeout, logger))
