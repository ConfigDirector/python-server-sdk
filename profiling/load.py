"""Drives traffic at the sample app's ``/configs`` endpoint at a fixed request rate.

Usable on its own against an already-running app::

    uv run python load.py --rps 50 --duration 60 --out results/requests.csv

or through :mod:`run`, which starts the app, samples it, and reports on the result.

**Pacing is open-loop.** Request *i* is sent at ``start + i / rps`` regardless of whether earlier
requests have come back, so the offered rate stays at the target even when the app slows down —
a closed-loop generator would quietly throttle itself and hide exactly the regression this is
looking for. Back-pressure instead shows up as rising latency and, past ``--max-in-flight``,
as skipped requests recorded in the CSV.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import itertools
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

# Context shapes the app sees, cycled in order. They vary along the axes that cost the SDK
# something: the number of traits to evaluate rules against, whether an id is supplied at all
# (the SDK generates one when it is not), and anonymous vs identified.
CONTEXT_VARIANTS: tuple[dict[str, str], ...] = (
    {"id": "user-{n}", "plan": "pro", "region": "us-east", "role": "writer"},
    {"id": "user-{n}", "name": "Ada Lovelace", "plan": "free", "region": "eu-west"},
    {"id": "user-{n}", "plan": "enterprise", "region": "ap-south", "beta": "true", "seats": "250"},
    {"id": "user-{n}", "name": "Grace Hopper", "role": "admin"},
    {"id": "user-{n}", "plan": "free", "anonymous": "true"},
    {"anonymous": "true"},
    {"id": "service-{n}", "plan": "pro", "region": "us-east", "internal": "true"},
    {"id": "user-{n}"},
)

CSV_COLUMNS = ("seq", "t_seconds", "latency_ms", "status", "variant", "error")


@dataclass(frozen=True)
class Result:
    """One attempted request."""

    seq: int
    t_seconds: float
    latency_ms: float
    status: int
    variant: int
    error: str


@dataclass(frozen=True)
class Summary:
    """What the caller needs to know without re-reading the CSV."""

    sent: int
    ok: int
    failed: int
    skipped: int
    elapsed: float

    @property
    def actual_rps(self) -> float:
        return self.sent / self.elapsed if self.elapsed > 0 else 0.0


def build_params(seq: int, distinct_users: int) -> tuple[dict[str, str], int]:
    """Return the query parameters for request ``seq``, and which variant they came from.

    Deterministic on purpose: two runs at the same settings send the identical sequence, so a
    difference between their profiles is a difference in the SDK, not in the traffic.
    """
    variant = seq % len(CONTEXT_VARIANTS)
    user = (seq // len(CONTEXT_VARIANTS)) % distinct_users
    params = {key: value.replace("{n}", str(user)) for key, value in CONTEXT_VARIANTS[variant].items()}
    return params, variant


async def send(
    client: httpx.AsyncClient,
    url: str,
    seq: int,
    started_at: float,
    distinct_users: int,
    results: list[Result],
) -> None:
    params, variant = build_params(seq, distinct_users)
    sent_at = time.perf_counter()
    status, error = 0, ""
    try:
        response = await client.get(url, params=params)
        status = response.status_code
        # Read the body: an app that builds a response it never has to serialize is not the app
        # under test.
        await response.aread()
    except Exception as exc:  # Any failure is data to record, not a reason to stop the run.
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = (time.perf_counter() - sent_at) * 1000
    results.append(
        Result(
            seq=seq,
            t_seconds=sent_at - started_at,
            latency_ms=latency_ms,
            status=status,
            variant=variant,
            error=error,
        )
    )


async def generate(
    url: str,
    rps: float,
    duration: float,
    distinct_users: int,
    max_in_flight: int,
    progress: bool,
) -> tuple[list[Result], Summary]:
    """Send ``rps`` requests per second for ``duration`` seconds."""
    results: list[Result] = []
    in_flight: set[asyncio.Task[None]] = set()
    skipped = 0
    interval = 1.0 / rps

    limits = httpx.Limits(max_connections=max_in_flight, max_keepalive_connections=max_in_flight)
    timeout = httpx.Timeout(10.0)
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        started_at = time.perf_counter()
        next_report = 1.0
        for seq in itertools.count():
            target = seq * interval
            if target >= duration:
                break
            delay = target - (time.perf_counter() - started_at)
            if delay > 0:
                await asyncio.sleep(delay)

            if len(in_flight) >= max_in_flight:
                # The app is not keeping up. Recording the skip beats letting the generator's own
                # queue grow without bound and become the thing that runs out of memory.
                skipped += 1
                results.append(
                    Result(
                        seq=seq,
                        t_seconds=time.perf_counter() - started_at,
                        latency_ms=0.0,
                        status=0,
                        variant=seq % len(CONTEXT_VARIANTS),
                        error="skipped: max-in-flight reached",
                    )
                )
                continue

            task = asyncio.create_task(send(client, url, seq, started_at, distinct_users, results))
            in_flight.add(task)
            task.add_done_callback(in_flight.discard)

            elapsed = time.perf_counter() - started_at
            if progress and elapsed >= next_report:
                print(
                    f"[load] {elapsed:6.1f}s  sent={len(results):6d}  in-flight={len(in_flight):4d}"
                    f"  skipped={skipped}",
                    flush=True,
                )
                next_report = elapsed + 1.0

        if in_flight:
            await asyncio.wait(in_flight, timeout=15)
        elapsed = time.perf_counter() - started_at

    results.sort(key=lambda result: result.seq)
    ok = sum(1 for result in results if result.status == 200)
    failed = sum(1 for result in results if result.status != 200 and not result.error.startswith("skipped"))
    summary = Summary(
        sent=len(results) - skipped,
        ok=ok,
        failed=failed,
        skipped=skipped,
        elapsed=elapsed,
    )
    return results, summary


def write_csv(results: list[Result], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for result in results:
            writer.writerow(
                [
                    result.seq,
                    f"{result.t_seconds:.4f}",
                    f"{result.latency_ms:.3f}",
                    result.status,
                    result.variant,
                    result.error,
                ]
            )


async def warm_up(url: str, requests: int, distinct_users: int) -> None:
    """Send a handful of requests whose cost belongs to nobody.

    The first requests through a fresh process pay for import-time laziness, connection setup and
    the SDK's first evaluation of each config. Counting that as steady-state load would make every
    run look like it had a latency spike at the start.
    """
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        for seq in range(requests):
            params, _ = build_params(seq, distinct_users)
            with contextlib.suppress(httpx.HTTPError):
                await client.get(url, params=params)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:3600/configs", help="Endpoint to hit.")
    parser.add_argument("--rps", type=float, default=25.0, help="Requests per second, 1 to ~100.")
    parser.add_argument("--duration", type=float, default=60.0, help="How long to send traffic, in seconds.")
    parser.add_argument(
        "--distinct-users",
        type=int,
        default=500,
        help="How many distinct user ids to cycle through. Higher values grow the SDK's telemetry.",
    )
    parser.add_argument(
        "--max-in-flight",
        type=int,
        default=0,
        help="Cap on concurrent requests. Defaults to max(50, 4 x rps).",
    )
    parser.add_argument("--out", type=Path, help="Write the per-request CSV here.")
    parser.add_argument("--quiet", action="store_true", help="Suppress the per-second progress line.")
    return parser.parse_args()


def resolve_max_in_flight(requested: int, rps: float) -> int:
    return requested if requested > 0 else max(50, int(rps * 4))


def main() -> None:
    args = parse_args()
    results, summary = asyncio.run(
        generate(
            url=args.url,
            rps=args.rps,
            duration=args.duration,
            distinct_users=args.distinct_users,
            max_in_flight=resolve_max_in_flight(args.max_in_flight, args.rps),
            progress=not args.quiet,
        )
    )
    if args.out is not None:
        write_csv(results, args.out)
        print(f"[load] wrote {args.out}")
    print(
        f"[load] sent={summary.sent} ok={summary.ok} failed={summary.failed} "
        f"skipped={summary.skipped} actual_rps={summary.actual_rps:.1f}"
    )


if __name__ == "__main__":
    main()
