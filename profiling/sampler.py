"""Samples the app process's CPU and memory on a fixed interval.

Runs as a thread inside :mod:`run` — the *orchestrator's* process, not the app's — and reads the
app process from the outside through psutil. Measuring from outside is the point: an in-process
sampler would show up in its own numbers, and it would stop being scheduled at exactly the moment
the app is busy enough to be interesting.

Children are rolled into the totals so the numbers stay meaningful if the app is ever served by a
process-based server (Gunicorn workers, or ``flask run --debug``'s reloader) instead of the
single-process harness.
"""

from __future__ import annotations

import csv
import threading
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import psutil


@dataclass(frozen=True)
class Sample:
    """One observation of the app process tree."""

    t_seconds: float
    wall_time: float
    cpu_percent: float
    """Percent of a *single* core. 100 means one core saturated; it can exceed 100."""
    rss_bytes: int
    """Resident set size — the memory actually held in RAM. This is the memory number to graph."""
    vms_bytes: int
    cpu_user_seconds: float
    cpu_system_seconds: float
    threads: int
    open_files: int
    connections: int
    processes: int


CSV_COLUMNS = tuple(field.name for field in fields(Sample))


class Sampler:
    """Collects :class:`Sample` rows for a process tree until stopped."""

    def __init__(self, pid: int, interval: float = 0.25) -> None:
        self.interval = interval
        self.samples: list[Sample] = []
        self._root = psutil.Process(pid)
        self._tracked: dict[int, psutil.Process] = {pid: self._root}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="sampler", daemon=True)
        self._started_at = 0.0
        # cpu_percent() reports the average since the previous call on the same object, so the
        # first call only establishes the baseline and is discarded.
        self._root.cpu_percent()

    @property
    def started_at(self) -> float:
        """``time.perf_counter()`` at ``start()`` — the zero of every ``t_seconds`` in the run."""
        return self._started_at

    def start(self) -> None:
        self._started_at = time.perf_counter()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=self.interval * 4)

    def _refresh_tracked(self) -> None:
        """Pick up processes the app has forked since the last sample."""
        try:
            for child in self._root.children(recursive=True):
                if child.pid not in self._tracked:
                    child.cpu_percent()
                    self._tracked[child.pid] = child
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    def _collect(self) -> Sample | None:
        self._refresh_tracked()

        cpu = rss = vms = user = system = threads = files = conns = 0.0
        alive = 0
        for pid, process in list(self._tracked.items()):
            try:
                with process.oneshot():
                    cpu += process.cpu_percent()
                    memory = process.memory_info()
                    rss += memory.rss
                    vms += memory.vms
                    times = process.cpu_times()
                    user += times.user
                    system += times.system
                    threads += process.num_threads()
                    files += _count(process.open_files)
                    conns += _count(process.net_connections)
                alive += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                self._tracked.pop(pid, None)

        if alive == 0:
            return None
        return Sample(
            t_seconds=time.perf_counter() - self._started_at,
            wall_time=time.time(),
            cpu_percent=round(cpu, 2),
            rss_bytes=int(rss),
            vms_bytes=int(vms),
            cpu_user_seconds=round(user, 3),
            cpu_system_seconds=round(system, 3),
            threads=int(threads),
            open_files=int(files),
            connections=int(conns),
            processes=alive,
        )

    def _run(self) -> None:
        while not self._stop.is_set():
            sample = self._collect()
            if sample is None:
                # The app exited. Nothing left to sample.
                break
            self.samples.append(sample)
            self._stop.wait(self.interval)

    def write_csv(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for sample in self.samples:
                row = asdict(sample)
                row["t_seconds"] = f"{sample.t_seconds:.3f}"
                row["wall_time"] = f"{sample.wall_time:.3f}"
                writer.writerow(row)


def _count(collect: object) -> int:
    """Length of a psutil listing, or 0 where the platform will not report it."""
    if not callable(collect):
        return 0
    try:
        return len(collect())
    except (psutil.AccessDenied, NotImplementedError, OSError):
        return 0
