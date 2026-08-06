from __future__ import annotations

import threading
from datetime import datetime, timezone

from configdirector._telemetry.events import EvaluatedConfigEvent
from configdirector._telemetry.queue import ContextRegistry, EventQueue, aggregate
from configdirector.types import Context

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)


def event(key: str = "my-config", value: str = "hello") -> EvaluatedConfigEvent:
    return EvaluatedConfigEvent.of(
        key=key, default="default", value=value, used_default=False, reason="found-match"
    )


class TestEventQueue:
    def test_takes_a_snapshot_of_what_was_pushed(self) -> None:
        queue = EventQueue(10)
        queue.push(event("a"))
        queue.push(event("b"))

        snapshot = queue.take_snapshot()

        assert [e.key for e in snapshot.events] == ["a", "b"]
        assert snapshot.dropped_count == 0

    def test_a_snapshot_empties_the_queue(self) -> None:
        queue = EventQueue(10)
        queue.push(event())

        queue.take_snapshot()

        assert queue.take_snapshot().is_empty

    def test_drops_the_oldest_events_once_full(self) -> None:
        queue = EventQueue(2)
        for key in ("a", "b", "c", "d"):
            queue.push(event(key))

        snapshot = queue.take_snapshot()

        assert [e.key for e in snapshot.events] == ["c", "d"]
        assert snapshot.dropped_count == 2

    def test_the_dropped_count_starts_over_after_a_snapshot(self) -> None:
        queue = EventQueue(1)
        queue.push(event("a"))
        queue.push(event("b"))
        queue.take_snapshot()

        queue.push(event("c"))

        assert queue.take_snapshot().dropped_count == 0

    def test_the_window_starts_at_the_first_event_and_ends_at_the_snapshot(self) -> None:
        queue = EventQueue(10)
        before = datetime.now(timezone.utc)
        queue.push(event())

        snapshot = queue.take_snapshot()

        assert before <= snapshot.start_time <= snapshot.end_time
        assert snapshot.end_time <= datetime.now(timezone.utc)

    def test_an_empty_snapshot_is_not_a_zero_length_window(self) -> None:
        snapshot = EventQueue(10).take_snapshot()

        assert snapshot.is_empty
        assert snapshot.start_time == snapshot.end_time

    def test_a_snapshot_holding_only_drops_is_not_empty(self) -> None:
        queue = EventQueue(1)
        queue.push(event("a"))
        queue.push(event("b"))

        assert queue.take_snapshot().is_empty is False

    def test_clearing_discards_the_events_and_the_dropped_count(self) -> None:
        queue = EventQueue(1)
        queue.push(event("a"))
        queue.push(event("b"))

        queue.clear()

        assert queue.take_snapshot().is_empty

    def test_concurrent_pushes_all_land(self) -> None:
        queue = EventQueue(1_000)
        barrier = threading.Barrier(4)

        def push_many() -> None:
            barrier.wait()
            for index in range(50):
                queue.push(event(f"config-{index}"))

        threads = [threading.Thread(target=push_many) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        snapshot = queue.take_snapshot()
        assert len(snapshot.events) == 200
        assert snapshot.dropped_count == 0


class TestContextRegistry:
    def test_collects_the_contexts_it_is_given(self) -> None:
        registry = ContextRegistry(10)
        registry.add("user-a", Context(id="user-a"))
        registry.add("user-b", Context(id="user-b"))

        contexts, dropped = registry.take_snapshot()

        assert sorted(c.id or "" for c in contexts) == ["user-a", "user-b"]
        assert dropped == 0

    def test_keeps_only_the_most_recent_context_for_an_id(self) -> None:
        registry = ContextRegistry(10)
        registry.add("user-a", Context(id="user-a"))
        registry.add("user-a", Context(id="user-a", name="Admin"))

        contexts, _ = registry.take_snapshot()

        assert contexts == [Context(id="user-a", name="Admin")]

    def test_a_snapshot_starts_the_next_batch_over(self) -> None:
        registry = ContextRegistry(10)
        registry.add("user-a", Context(id="user-a"))
        registry.take_snapshot()

        assert registry.take_snapshot() == ([], 0)

    def test_evicts_the_oldest_context_once_full(self) -> None:
        registry = ContextRegistry(2)
        for identifier in ("user-a", "user-b", "user-c", "user-d"):
            registry.add(identifier, Context(id=identifier))

        contexts, dropped = registry.take_snapshot()

        assert [c.id for c in contexts] == ["user-c", "user-d"]
        assert dropped == 2

    def test_seeing_a_context_again_does_not_save_it_from_eviction(self) -> None:
        # Re-assigning a key leaves it where it was, which is how the other SDKs behave too.
        registry = ContextRegistry(2)
        registry.add("user-a", Context(id="user-a"))
        registry.add("user-b", Context(id="user-b"))
        registry.add("user-a", Context(id="user-a", name="Admin"))
        registry.add("user-c", Context(id="user-c"))

        contexts, _ = registry.take_snapshot()

        assert [c.id for c in contexts] == ["user-b", "user-c"]

    def test_clearing_discards_the_contexts_and_the_dropped_count(self) -> None:
        registry = ContextRegistry(1)
        registry.add("user-a", Context(id="user-a"))
        registry.add("user-b", Context(id="user-b"))

        registry.clear()

        assert registry.take_snapshot() == ([], 0)


class TestAggregate:
    def test_collapses_identical_events_into_one_entry_with_a_count(self) -> None:
        aggregated = aggregate([event(), event(), event()], START, END)

        assert len(aggregated) == 1
        assert aggregated[0].count == 3
        assert aggregated[0].event == event()

    def test_keeps_events_that_differ_apart(self) -> None:
        aggregated = aggregate([event("config-a"), event("config-b"), event("config-a")], START, END)

        assert sorted((a.event.key, a.count) for a in aggregated) == [("config-a", 2), ("config-b", 1)]

    def test_every_entry_carries_the_window_the_snapshot_covers(self) -> None:
        aggregated = aggregate([event("a"), event("b")], START, END)

        assert all(a.start_time == START and a.end_time == END for a in aggregated)

    def test_aggregating_nothing_produces_nothing(self) -> None:
        assert aggregate([], START, END) == []
