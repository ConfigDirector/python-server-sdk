"""Serves the Flask sample as the process under measurement.

Run by :mod:`run` as a **separate process** so that the load generator's and the sampler's own
CPU and memory never land in the numbers. It can also be run on its own to poke at the app by
hand::

    uv run python server.py --port 3600

The app itself is imported unmodified from ``samples/flask`` — importing ``app`` is what creates
and initializes the singleton client, exactly as it would under a real WSGI server. Only three
things differ from ``flask run``, and each one exists to keep the measurement honest:

* **Werkzeug's request log is silenced.** One log line per request costs more than the config
  evaluation being measured, and at 100 requests per second it dominates the profile.
* **The SDK's own logger defaults to WARNING.** ``samples/flask/.env`` may set ``DEBUG``, which
  logs every evaluation — useful when learning the SDK, ruinous when timing it.
* **Optional instrumentation.** ``--cpu-profile`` (cProfile) and ``--tracemalloc`` attribute time
  and allocations to functions. Both distort the totals, so they are off by default and belong
  in a separate run from the one that produces the time series.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import linecache
import logging
import os
import pstats
import signal
import sys
import threading
import tracemalloc
from pathlib import Path
from types import FrameType
from typing import Any

from dotenv import load_dotenv
from werkzeug.serving import make_server

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = REPO_ROOT / "samples" / "flask"

# How many allocation sites to keep in the tracemalloc report.
TRACEMALLOC_TOP = 25
# How many functions to keep in the cProfile text summary.
CPROFILE_TOP = 40


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3600)
    parser.add_argument(
        "--out",
        type=Path,
        help="Directory to write instrumentation artifacts to. Defaults to not writing any.",
    )
    parser.add_argument(
        "--cpu-profile",
        action="store_true",
        help=(
            "Run under cProfile for function-level CPU attribution. Forces single-threaded "
            "serving (cProfile only sees the thread it was enabled on) and adds significant "
            "overhead, so use a separate run for this."
        ),
    )
    parser.add_argument(
        "--tracemalloc",
        action="store_true",
        help=(
            "Track allocations to attribute memory growth to source lines. Adds significant "
            "overhead. SIGUSR1 marks the baseline snapshot (POSIX only); the growth since that "
            "baseline is written at shutdown."
        ),
    )
    return parser.parse_args()


def load_sample_app(log_level: str) -> tuple[Any, Any]:
    """Import the Flask sample, returning its ``(app, client)``.

    The sample resolves its configuration from the environment, so everything the harness wants
    to control has to be set before this import runs — which is why the import is down here and
    not at the top of the module. Environment variables already set by the caller win over
    ``samples/flask/.env``, because ``load_dotenv`` does not override.
    """
    os.environ.setdefault("CONFIGDIRECTOR_LOG_LEVEL", log_level)
    load_dotenv(SAMPLE_DIR / ".env")

    sys.path.insert(0, str(SAMPLE_DIR))
    import app as sample_app

    return sample_app.app, sample_app.client


def write_cpu_profile(profiler: cProfile.Profile, out_dir: Path) -> None:
    """Write the raw stats plus a readable top-N, sorted by time spent in the function itself."""
    stats_path = out_dir / "cprofile.pstats"
    profiler.dump_stats(str(stats_path))

    buffer = io.StringIO()
    stats = pstats.Stats(profiler, stream=buffer)
    stats.sort_stats(pstats.SortKey.TIME).print_stats(CPROFILE_TOP)
    header = (
        "The top entry is usually select.poll or kqueue.control: that is serve_forever() waiting\n"
        "for the next connection, not work being done. Read past it.\n\n"
    )
    (out_dir / "cprofile.txt").write_text(header + buffer.getvalue(), encoding="utf-8")

    print(f"[server] wrote {stats_path.name} and cprofile.txt", flush=True)


def write_tracemalloc_diff(
    baseline: tracemalloc.Snapshot | None,
    current: tracemalloc.Snapshot,
    out_dir: Path,
) -> None:
    """Write the allocation sites that grew the most since the baseline snapshot."""
    measured: list[tuple[tracemalloc.Statistic | tracemalloc.StatisticDiff, float, int]]
    if baseline is None:
        heading = "Top allocation sites at shutdown"
        measured = [(stat, stat.size / 1024, stat.count) for stat in current.statistics("lineno")]
    else:
        heading = "Allocation growth since the baseline snapshot"
        measured = [
            (diff, diff.size_diff / 1024, diff.count_diff) for diff in current.compare_to(baseline, "lineno")
        ]

    lines = [heading, "=" * len(heading), ""]
    rows: list[dict[str, object]] = []
    for entry, size_kb, count in measured[:TRACEMALLOC_TOP]:
        frame = entry.traceback[0]
        source = linecache.getline(frame.filename, frame.lineno).strip()
        lines.append(f"{size_kb:+10.1f} KiB  {count:+8d} blocks  {frame.filename}:{frame.lineno}")
        if source:
            lines.append(f"{'':>10}       {source}")
        rows.append(
            {
                "file": frame.filename,
                "line": frame.lineno,
                "source": source,
                "size_kb": round(size_kb, 1),
                "blocks": count,
            }
        )

    (out_dir / "tracemalloc.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / "tracemalloc.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(f"[server] wrote tracemalloc.txt ({len(rows)} sites)", flush=True)


def _sdk_version() -> str:
    import configdirector

    return str(configdirector.__version__)


def main() -> None:
    args = parse_args()

    baseline_snapshot: tracemalloc.Snapshot | None = None
    if args.tracemalloc:
        # Start tracking before the app is imported, so the client's own allocations are seen.
        tracemalloc.start(25)

    app, client = load_sample_app(log_level="WARNING")

    # Werkzeug logs a line per request at INFO, which costs more than the evaluation being
    # measured. This has to come after the import: that is where the sample calls basicConfig.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    profiler = cProfile.Profile() if args.cpu_profile else None
    # cProfile only records the thread it was enabled on, so serve serially when it is active.
    httpd = make_server(args.host, args.port, app, threaded=profiler is None)

    def terminate(_signum: int, _frame: FrameType | None) -> None:
        # shutdown() blocks until serve_forever() returns, so it cannot run on this thread.
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)

    if args.tracemalloc and hasattr(signal, "SIGUSR1"):

        def mark_baseline(_signum: int, _frame: FrameType | None) -> None:
            nonlocal baseline_snapshot
            baseline_snapshot = tracemalloc.take_snapshot()
            print("[server] tracemalloc baseline captured", flush=True)

        signal.signal(signal.SIGUSR1, mark_baseline)

    ready = bool(getattr(client, "is_ready", False))
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "server_meta.json").write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "client_ready": ready,
                    "sdk_version": _sdk_version(),
                    "mode": os.environ.get("CONFIGDIRECTOR_MODE", "streaming"),
                    "base_url": os.environ.get("CONFIGDIRECTOR_BASE_URL") or None,
                    "threaded": profiler is None,
                    "cpu_profile": bool(profiler),
                    "tracemalloc": args.tracemalloc,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    print(
        f"[server] pid={os.getpid()} listening on http://{args.host}:{args.port} "
        f"(client ready={ready}, threaded={profiler is None})",
        flush=True,
    )
    if not ready:
        print(
            "[server] WARNING: the client is not ready — every config resolves to its default, "
            "so this run measures the offline path.",
            flush=True,
        )

    if profiler is not None:
        profiler.enable()
    try:
        httpd.serve_forever()
    finally:
        if profiler is not None:
            profiler.disable()

    # Snapshot before anything below runs: writing the cProfile report allocates heavily, and it
    # would otherwise be the top of the very allocation report meant to be about the app.
    final_snapshot = tracemalloc.take_snapshot() if args.tracemalloc else None

    print("[server] shutting down", flush=True)
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        if profiler is not None:
            write_cpu_profile(profiler, args.out)
        if final_snapshot is not None:
            write_tracemalloc_diff(baseline_snapshot, final_snapshot, args.out)

    # Mirrors the sample's own shutdown path: drop the connection and flush pending telemetry.
    close = getattr(client, "close", None)
    if callable(close):
        close()


if __name__ == "__main__":
    main()
