"""Runs one end-to-end profiling session against the Flask sample and reports on it.

    uv run python run.py --rps 50 --duration 120

Everything happens in one command:

1. Start ``samples/flask`` in its own process (:mod:`server`).
2. Wait for it to answer, then sit idle for a few seconds — that idle stretch is the resting
   memory and CPU baseline every later number is read against.
3. Send warm-up requests whose cost belongs to nobody: imports, connection setup, and the SDK's
   first evaluation of each config all land here rather than in the measurement.
4. Drive load at the requested rate for the requested duration (:mod:`load`), sampling the app
   process the whole time from the outside (:mod:`sampler`).
5. Keep sampling through a cooldown after the traffic stops. Memory that does not come back down
   here is the interesting kind, and the SDK's telemetry flush (every 30s by default) usually
   lands in this window.
6. Shut the app down cleanly — SIGTERM, so ``atexit`` runs and telemetry is flushed — and write
   the report (:mod:`report`).

Results land in ``results/<timestamp>-<label>/``. See ``README.md`` for what each file holds.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

import httpx
import psutil

import load
import report
from sampler import Sampler

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DEFAULT_RESULTS_DIR = HERE / "results"

# Long enough for a cold client to finish `initialize()` and start serving.
READY_TIMEOUT = 60.0
# How long to wait for the app to exit on SIGTERM before insisting.
SHUTDOWN_TIMEOUT = 20.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--rps", type=float, default=25.0, help="Requests per second (1 to ~100).")
    parser.add_argument(
        "--duration",
        type=float,
        default=60.0,
        help="How long to hold that rate, in seconds.",
    )
    parser.add_argument("--port", type=int, default=3600, help="Port to serve the sample app on.")
    parser.add_argument(
        "--sample-interval",
        type=float,
        default=0.25,
        help="Seconds between CPU/memory samples.",
    )
    parser.add_argument(
        "--baseline",
        type=float,
        default=5.0,
        help="Seconds of idle sampling before any traffic, for the resting baseline.",
    )
    parser.add_argument(
        "--warmup-requests",
        type=int,
        default=50,
        help="Requests sent, and excluded from the report, before measurement starts.",
    )
    parser.add_argument(
        "--cooldown",
        type=float,
        default=20.0,
        help=(
            "Seconds of idle sampling after the traffic stops. Raise it past 30 to catch a "
            "telemetry flush at its default interval."
        ),
    )
    parser.add_argument(
        "--distinct-users",
        type=int,
        default=500,
        help="How many distinct user ids the load cycles through.",
    )
    parser.add_argument(
        "--max-in-flight",
        type=int,
        default=0,
        help="Cap on concurrent requests. Defaults to max(50, 4 x rps).",
    )
    parser.add_argument(
        "--mode",
        default="streaming",
        choices=("streaming", "polling"),
        help="SDK connection mode to profile.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help=(
            "Point the SDK at an address nothing answers on, so every config resolves to its "
            "default. Profiles the fallback path, and gives a network-free comparison run."
        ),
    )
    parser.add_argument(
        "--cpu-profile",
        action="store_true",
        help=(
            "Also run the app under cProfile for function-level attribution. Serves requests "
            "serially and inflates every timing, so treat this as a separate investigation."
        ),
    )
    parser.add_argument(
        "--tracemalloc",
        action="store_true",
        help="Also track allocations, to attribute memory growth to source lines. Adds overhead.",
    )
    parser.add_argument("--label", default="", help="Suffix for the results directory name.")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
        help="Where run directories are created.",
    )
    return parser.parse_args()


def make_run_dir(results_dir: Path, label: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}-{label}" if label else stamp
    run_dir = results_dir / name
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def server_environment(args: argparse.Namespace) -> dict[str, str]:
    """The environment the app under test sees.

    These win over ``samples/flask/.env``: ``load_dotenv`` does not override what is already set.
    Forcing the log level matters most — the sample's ``.env`` may ask for DEBUG, which logs every
    single evaluation and would cost more than the evaluation itself.
    """
    env = dict(os.environ)
    env["CONFIGDIRECTOR_MODE"] = args.mode
    env["CONFIGDIRECTOR_LOG_LEVEL"] = "WARNING"
    env.setdefault("CONFIGDIRECTOR_TIMEOUT", "10")
    if args.offline:
        env["CONFIGDIRECTOR_BASE_URL"] = "http://127.0.0.1:1"
        env["CONFIGDIRECTOR_TIMEOUT"] = "0.5"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def start_server(args: argparse.Namespace, run_dir: Path, log_handle: IO[bytes]) -> subprocess.Popen[bytes]:
    command = [sys.executable, str(HERE / "server.py"), "--port", str(args.port), "--out", str(run_dir)]
    if args.cpu_profile:
        command.append("--cpu-profile")
    if args.tracemalloc:
        command.append("--tracemalloc")
    return subprocess.Popen(
        command,
        cwd=str(HERE),
        env=server_environment(args),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )


def wait_until_serving(process: subprocess.Popen[bytes], url: str, log_path: Path) -> None:
    """Block until the app answers, or fail loudly with what its log said."""
    deadline = time.perf_counter() + READY_TIMEOUT
    while time.perf_counter() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"the app exited before serving:\n{log_path.read_text(encoding='utf-8')}")
        try:
            response = httpx.get(url, params={"id": "warmup"}, timeout=2.0)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.25)
    raise RuntimeError(f"the app did not start within {READY_TIMEOUT:.0f}s; see {log_path}")


def stop_server(process: subprocess.Popen[bytes]) -> None:
    """SIGTERM, so the sample's ``atexit`` hook closes the client and flushes telemetry."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=SHUTDOWN_TIMEOUT)
    except subprocess.TimeoutExpired:
        print("[run] the app ignored SIGTERM; killing it")
        process.kill()
        process.wait(timeout=5)


def mark_tracemalloc_baseline(pid: int) -> None:
    if hasattr(signal, "SIGUSR1"):
        os.kill(pid, signal.SIGUSR1)


def git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--pretty=%H"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def main() -> int:
    args = parse_args()
    if args.rps <= 0:
        raise SystemExit("--rps must be greater than 0")

    run_dir = make_run_dir(args.results_dir, args.label)
    log_path = run_dir / "server.log"
    url = f"http://127.0.0.1:{args.port}/configs"
    phases: list[dict[str, object]] = []

    print(f"[run] results -> {run_dir}")
    with log_path.open("wb") as log_handle:
        process = start_server(args, run_dir, log_handle)
        try:
            wait_until_serving(process, url, log_path)
            print(f"[run] app serving on {url} (pid {process.pid})")

            sampler = Sampler(process.pid, interval=args.sample_interval)
            sampler.start()

            def mark(name: str, start: float) -> None:
                phases.append(
                    {
                        "name": name,
                        "start": round(start - sampler.started_at, 3),
                        "end": round(time.perf_counter() - sampler.started_at, 3),
                    }
                )

            phase_start = time.perf_counter()
            print(f"[run] idle baseline for {args.baseline:.0f}s")
            time.sleep(args.baseline)
            mark("baseline", phase_start)

            phase_start = time.perf_counter()
            print(f"[run] warming up with {args.warmup_requests} requests")
            asyncio.run(load.warm_up(url, args.warmup_requests, args.distinct_users))
            mark("warmup", phase_start)

            if args.tracemalloc:
                mark_tracemalloc_baseline(process.pid)

            phase_start = time.perf_counter()
            load_offset = phase_start - sampler.started_at
            print(f"[run] load: {args.rps:g} rps for {args.duration:g}s")
            results, summary = asyncio.run(
                load.generate(
                    url=url,
                    rps=args.rps,
                    duration=args.duration,
                    distinct_users=args.distinct_users,
                    max_in_flight=load.resolve_max_in_flight(args.max_in_flight, args.rps),
                    progress=True,
                )
            )
            mark("load", phase_start)

            phase_start = time.perf_counter()
            print(f"[run] cooldown for {args.cooldown:.0f}s")
            time.sleep(args.cooldown)
            mark("cooldown", phase_start)

            sampler.stop()
        finally:
            print("[run] stopping the app")
            stop_server(process)

    load.write_csv(results, run_dir / "requests.csv")
    sampler.write_csv(run_dir / "samples.csv")

    metadata: dict[str, object] = {
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "label": args.label,
        "target_rps": args.rps,
        "duration_seconds": args.duration,
        "distinct_users": args.distinct_users,
        "sample_interval": args.sample_interval,
        "mode": args.mode,
        "offline": args.offline,
        "cpu_profile": args.cpu_profile,
        "tracemalloc": args.tracemalloc,
        "load": {
            "sent": summary.sent,
            "ok": summary.ok,
            "failed": summary.failed,
            "skipped": summary.skipped,
            "actual_rps": round(summary.actual_rps, 2),
        },
        "phases": phases,
        "load_offset_seconds": round(load_offset, 3),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpu_count": psutil.cpu_count(logical=True),
            "commit": git_commit(),
        },
    }
    meta_path = run_dir / "server_meta.json"
    if meta_path.exists():
        metadata["server"] = json.loads(meta_path.read_text(encoding="utf-8"))
    (run_dir / "run.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    report.build(run_dir)
    print(f"[run] done — open {run_dir / 'chart.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
