from __future__ import annotations

import pytest

from configdirector._eventsource import EventSourceMessage, EventSourceParser, StreamTooLargeError


class Collector:
    def __init__(self) -> None:
        self.events: list[EventSourceMessage] = []
        self.retries: list[int] = []
        self.comments: list[str] = []
        self.parser = EventSourceParser(
            on_event=self.events.append,
            on_retry=self.retries.append,
            on_comment=self.comments.append,
        )

    def feed(self, *chunks: str) -> Collector:
        for chunk in chunks:
            self.parser.feed(chunk)
        return self

    @property
    def data(self) -> list[str]:
        return [event.data for event in self.events]


def feed_repeatedly(parser: EventSourceParser, chunk: str, times: int = 100) -> None:
    for _ in range(times):
        parser.feed(chunk)


@pytest.fixture
def parser() -> Collector:
    return Collector()


class TestEventDispatching:
    def test_dispatches_an_event_on_the_blank_line_after_data(self, parser: Collector) -> None:
        parser.feed("data: hello\n\n")

        assert parser.data == ["hello"]

    def test_does_not_dispatch_a_blank_line_with_no_data(self, parser: Collector) -> None:
        parser.feed("\n")

        assert parser.events == []

    def test_does_not_dispatch_when_only_id_and_type_are_set(self, parser: Collector) -> None:
        parser.feed("id: 1\nevent: test\n\n")

        assert parser.events == []

    def test_resets_the_event_after_dispatching(self, parser: Collector) -> None:
        parser.feed("data: first\n\ndata: second\n\n")

        assert parser.data == ["first", "second"]

    def test_resets_the_event_type_after_dispatching(self, parser: Collector) -> None:
        parser.feed("event: custom\ndata: first\n\ndata: second\n\n")

        assert parser.events[0].type == "custom"
        assert parser.events[1].type is None

    def test_carries_the_last_event_id_to_later_events(self, parser: Collector) -> None:
        parser.feed("id: 42\ndata: first\n\ndata: second\n\n")

        assert [event.id for event in parser.events] == ["42", "42"]


class TestDataField:
    def test_strips_a_single_leading_space(self, parser: Collector) -> None:
        parser.feed("data: value\n\n")

        assert parser.data == ["value"]

    def test_does_not_strip_a_second_leading_space(self, parser: Collector) -> None:
        parser.feed("data:  two spaces\n\n")

        assert parser.data == [" two spaces"]

    def test_accepts_no_space_after_the_colon(self, parser: Collector) -> None:
        parser.feed("data:value\n\n")

        assert parser.data == ["value"]

    def test_joins_multiple_data_lines_with_newlines(self, parser: Collector) -> None:
        parser.feed("data: line1\ndata: line2\ndata: line3\n\n")

        assert parser.data == ["line1\nline2\nline3"]

    def test_an_empty_data_line_contributes_a_newline(self, parser: Collector) -> None:
        parser.feed("data:\ndata: second\n\n")

        assert parser.data == ["\nsecond"]

    def test_a_field_with_no_colon_has_an_empty_value(self, parser: Collector) -> None:
        parser.feed("data\n\n")

        assert parser.events == []

    def test_keeps_colons_inside_the_value(self, parser: Collector) -> None:
        parser.feed("data: key:value\n\n")

        assert parser.data == ["key:value"]


class TestEventTypeField:
    def test_sets_the_event_type(self, parser: Collector) -> None:
        parser.feed("event: message\ndata: hello\n\n")

        assert parser.events[0].type == "message"

    def test_the_last_event_field_wins(self, parser: Collector) -> None:
        parser.feed("event: first\nevent: second\ndata: hello\n\n")

        assert parser.events[0].type == "second"


class TestIdField:
    def test_sets_the_event_id(self, parser: Collector) -> None:
        parser.feed("id: 123\ndata: hello\n\n")

        assert parser.events[0].id == "123"

    def test_ignores_an_id_containing_a_null_character(self, parser: Collector) -> None:
        parser.feed("id: abc\x00def\ndata: hello\n\n")

        assert parser.events[0].id is None

    def test_accepts_an_empty_id(self, parser: Collector) -> None:
        parser.feed("id:\ndata: hello\n\n")

        assert parser.events[0].id == ""


class TestRetryField:
    def test_reports_an_integer_retry(self, parser: Collector) -> None:
        parser.feed("retry: 3000\n\n")

        assert parser.retries == [3000]

    @pytest.mark.parametrize("value", ["3000ms", "", "1.5", "-1", " 5"])
    def test_ignores_a_retry_that_is_not_a_plain_integer(self, parser: Collector, value: str) -> None:
        parser.feed(f"retry: {value}\n\n")

        assert parser.retries == []

    @pytest.mark.parametrize("value", ["٣", "²"])
    def test_ignores_non_ascii_digits(self, parser: Collector, value: str) -> None:
        # str.isdigit() accepts these; int() accepts only some of them.
        parser.feed(f"retry: {value}\n\n")

        assert parser.retries == []

    def test_a_retry_alone_does_not_dispatch_an_event(self, parser: Collector) -> None:
        parser.feed("retry: 5000\n\n")

        assert parser.events == []
        assert parser.retries == [5000]


class TestComments:
    def test_reports_a_comment(self, parser: Collector) -> None:
        parser.feed(": this is a comment\n\n")

        assert parser.comments == ["this is a comment"]

    def test_reports_an_empty_comment(self, parser: Collector) -> None:
        parser.feed(":\n\n")

        assert parser.comments == [""]

    def test_a_comment_does_not_dispatch_an_event(self, parser: Collector) -> None:
        parser.feed(": comment\n\n")

        assert parser.events == []

    def test_mixes_comments_and_data_in_one_event(self, parser: Collector) -> None:
        parser.feed(": keep-alive\ndata: hello\n\n")

        assert parser.comments == ["keep-alive"]
        assert parser.data == ["hello"]


class TestUnknownFields:
    def test_ignores_unknown_field_names(self, parser: Collector) -> None:
        parser.feed("unknown: value\ndata: hello\n\n")

        assert parser.data == ["hello"]


class TestLineEndings:
    @pytest.mark.parametrize(
        "stream",
        ["data: hello\n\n", "data: hello\r\r", "data: hello\r\n\r\n"],
        ids=["lf", "cr", "crlf"],
    )
    def test_handles_each_terminator(self, parser: Collector, stream: str) -> None:
        parser.feed(stream)

        assert parser.data == ["hello"]

    def test_handles_mixed_terminators_in_one_chunk(self, parser: Collector) -> None:
        parser.feed("data: line1\r\ndata: line2\n\r\n")

        assert parser.data == ["line1\nline2"]

    def test_a_crlf_split_across_chunks_is_one_terminator(self, parser: Collector) -> None:
        # The CR ends the line; the LF that opens the next chunk must not read as a blank line,
        # which would dispatch the event a chunk early.
        parser.feed("data: hello\r", "\ndata: world\r\n\r\n")

        assert parser.data == ["hello\nworld"]


class TestBom:
    def test_strips_a_leading_byte_order_mark(self, parser: Collector) -> None:
        parser.feed("﻿data: hello\n\n")

        assert parser.data == ["hello"]

    def test_strips_an_undecoded_utf8_byte_order_mark(self, parser: Collector) -> None:
        parser.feed("\xef\xbb\xbfdata: hello\n\n")

        assert parser.data == ["hello"]

    def test_does_not_strip_a_mark_that_is_not_at_the_start(self, parser: Collector) -> None:
        parser.feed("data: ﻿hello\n\n")

        assert parser.data == ["﻿hello"]


class TestChunkedInput:
    def test_handles_a_field_split_across_chunks(self, parser: Collector) -> None:
        parser.feed("data: hel", "lo\n\n")

        assert parser.data == ["hello"]

    def test_handles_the_delimiter_split_across_chunks(self, parser: Collector) -> None:
        parser.feed("data: hello\n", "\n")

        assert parser.data == ["hello"]

    def test_handles_several_events_in_one_chunk(self, parser: Collector) -> None:
        parser.feed("data: one\n\ndata: two\n\ndata: three\n\n")

        assert parser.data == ["one", "two", "three"]

    def test_handles_one_character_at_a_time(self, parser: Collector) -> None:
        parser.feed(*"data: hello\n\n")

        assert parser.data == ["hello"]


class TestFinish:
    def test_discards_an_event_with_no_terminating_blank_line(self, parser: Collector) -> None:
        parser.feed("data: hello")
        parser.parser.finish()

        assert parser.events == []

    def test_discards_an_event_ending_on_a_single_newline(self, parser: Collector) -> None:
        parser.feed("data: hello\n")
        parser.parser.finish()

        assert parser.events == []

    def test_does_not_redispatch_a_completed_event(self, parser: Collector) -> None:
        parser.feed("data: complete\n\n")
        parser.parser.finish()

        assert parser.data == ["complete"]


class TestLimits:
    def test_rejects_a_line_that_never_terminates(self) -> None:
        parser = EventSourceParser(max_line_chars=1024)

        with pytest.raises(StreamTooLargeError, match="without a terminator"):
            feed_repeatedly(parser, "x" * 64)

    def test_rejects_an_event_whose_data_never_ends(self) -> None:
        parser = EventSourceParser(max_event_chars=1024)

        with pytest.raises(StreamTooLargeError, match="characters of data"):
            feed_repeatedly(parser, "data: " + "x" * 64 + "\n")

    def test_a_long_but_bounded_value_is_fine(self, parser: Collector) -> None:
        value = "x" * 100_000
        parser.feed(f"data: {value}\n\n")

        assert parser.data == [value]


class TestWithoutCallbacks:
    @pytest.mark.parametrize("stream", ["data: hello\n\n", "retry: 1000\n\n", ": comment\n\n", ""])
    def test_parsing_without_handlers_does_not_raise(self, stream: str) -> None:
        EventSourceParser().feed(stream)


class TestSpecExamples:
    def test_multi_line_data(self, parser: Collector) -> None:
        parser.feed("data: YHOO\ndata: +2\ndata: 10\n\n")

        assert parser.data == ["YHOO\n+2\n10"]

    def test_named_events(self, parser: Collector) -> None:
        parser.feed("event: add\ndata: 73857293\n\nevent: remove\ndata: 2153\n\n")

        assert [(event.type, event.data) for event in parser.events] == [
            ("add", "73857293"),
            ("remove", "2153"),
        ]

    def test_the_last_event_id_persists_until_reset(self, parser: Collector) -> None:
        parser.feed("id: 1\ndata: first\n\nid: 2\ndata: second\n\ndata: third\n\n")

        assert [event.id for event in parser.events] == ["1", "2", "2"]


class TestEdgeCases:
    def test_only_comments(self, parser: Collector) -> None:
        parser.feed(": ping\n: pong\n\n")

        assert parser.events == []
        assert parser.comments == ["ping", "pong"]

    def test_repeated_blank_lines_dispatch_once(self, parser: Collector) -> None:
        parser.feed("data: hello\n\n\n\n")

        assert parser.data == ["hello"]

    def test_json_payloads_survive_intact(self, parser: Collector) -> None:
        payload = '{"foo": "bar", "n": 42}'
        parser.feed(f"data: {payload}\n\n")

        assert parser.data == [payload]
