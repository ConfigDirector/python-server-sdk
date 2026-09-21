from __future__ import annotations

from collections.abc import Callable

from .errors import StreamTooLargeError
from .types import EventSourceMessage

__all__ = ["DEFAULT_MAX_EVENT_CHARS", "DEFAULT_MAX_LINE_CHARS", "EventSourceParser"]

# A server that never terminates a line, or never ends an event, would otherwise grow these
# buffers without bound. Both are generous next to any real config payload; exceeding one is
# treated as a broken stream rather than something to keep absorbing.
DEFAULT_MAX_LINE_CHARS = 1 << 20  # 1 MiB
DEFAULT_MAX_EVENT_CHARS = 1 << 24  # 16 MiB

_BOM = "\ufeff"
# Some servers emit the UTF-8 BOM bytes without them being decoded as one character.
_DECODED_BOM = "\xef\xbb\xbf"


class EventSourceParser:
    def __init__(
        self,
        *,
        on_event: Callable[[EventSourceMessage], None] | None = None,
        on_retry: Callable[[int], None] | None = None,
        on_comment: Callable[[str], None] | None = None,
        max_line_chars: int = DEFAULT_MAX_LINE_CHARS,
        max_event_chars: int = DEFAULT_MAX_EVENT_CHARS,
    ) -> None:
        self._on_event = on_event
        self._on_retry = on_retry
        self._on_comment = on_comment
        self._max_line_chars = max_line_chars
        self._max_event_chars = max_event_chars

        self._first_chunk = True
        # An unterminated line is kept as fragments and joined once, so feeding a long line one
        # chunk at a time stays linear rather than re-copying the whole buffer per chunk.
        self._line_parts: list[str] = []
        self._line_len = 0
        # A CR at the very end of a chunk may be half of a CRLF; the LF is skipped if it opens
        # the next chunk.
        self._pending_lf = False

        self._event_type: str | None = None
        self._data_parts: list[str] = []
        self._data_len = 0
        self._last_event_id: str | None = None

    def feed(self, chunk: str) -> None:
        if self._first_chunk:
            self._first_chunk = False
            chunk = self._strip_bom(chunk)
        if not chunk:
            return

        start = 0
        if self._pending_lf:
            self._pending_lf = False
            if chunk[0] == "\n":
                start = 1

        index = start
        length = len(chunk)
        while index < length:
            character = chunk[index]
            if character not in "\r\n":
                index += 1
                continue

            self._finish_line(chunk[start:index])
            if character == "\r":
                if index + 1 < length:
                    if chunk[index + 1] == "\n":
                        index += 1
                else:
                    self._pending_lf = True
            index += 1
            start = index

        if start < length:
            self._buffer_line(chunk[start:])

    def finish(self) -> None:
        # An event needs a terminating blank line to be dispatched, so whatever is buffered when
        # the stream ends is discarded.
        self._line_parts.clear()
        self._line_len = 0
        self._pending_lf = False
        self._reset_event()

    @staticmethod
    def _strip_bom(chunk: str) -> str:
        if chunk.startswith(_BOM):
            return chunk[1:]
        if chunk.startswith(_DECODED_BOM):
            return chunk[3:]
        return chunk

    def _buffer_line(self, fragment: str) -> None:
        self._line_len += len(fragment)
        if self._line_len > self._max_line_chars:
            raise StreamTooLargeError(
                f"A single line exceeded {self._max_line_chars} characters without a terminator"
            )
        self._line_parts.append(fragment)

    def _finish_line(self, fragment: str) -> None:
        if self._line_parts:
            self._line_parts.append(fragment)
            line = "".join(self._line_parts)
            self._line_parts.clear()
            self._line_len = 0
        else:
            line = fragment
        self._dispatch_line(line)

    def _dispatch_line(self, line: str) -> None:
        if line.startswith(":"):
            if self._on_comment is not None:
                self._on_comment(_field_value(line, 1))
            return

        if not line:
            self._emit_event()
            return

        colon = line.find(":")
        if colon == -1:
            self._apply_field(line, "")
        else:
            self._apply_field(line[:colon], _field_value(line, colon + 1))

    def _apply_field(self, field: str, value: str) -> None:
        match field:
            case "event":
                self._event_type = value
            case "data":
                self._data_len += len(value) + 1
                if self._data_len > self._max_event_chars:
                    raise StreamTooLargeError(
                        f"A single event exceeded {self._max_event_chars} characters of data"
                    )
                self._data_parts.append(value)
            case "id":
                # The spec requires ids containing a NULL to be ignored.
                if "\0" not in value:
                    self._last_event_id = value
            case "retry":
                # isdigit() alone accepts Unicode digits, some of which int() then rejects.
                if value.isascii() and value.isdigit() and self._on_retry is not None:
                    self._on_retry(int(value))
            case _:
                pass

    def _emit_event(self) -> None:
        # Joining is equivalent to the spec's "append value then LF, drop the trailing LF", and
        # avoids rebuilding the string on every data line.
        data = "\n".join(self._data_parts)
        if data and self._on_event is not None:
            self._on_event(EventSourceMessage(data=data, type=self._event_type, id=self._last_event_id))
        self._reset_event()

    def _reset_event(self) -> None:
        self._event_type = None
        self._data_parts.clear()
        self._data_len = 0


def _field_value(line: str, start: int) -> str:
    # A single leading space after the colon is part of the delimiter, not the value.
    if start < len(line) and line[start] == " ":
        return line[start + 1 :]
    return line[start:]
