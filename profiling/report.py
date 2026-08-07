"""Turns a run's raw CSVs into something you can read, graph, and compare against.

    uv run python report.py results/20260806-150000-baseline

:func:`build` is what :mod:`run` calls at the end of a session, but it is deliberately a separate
entry point: re-running it is cheap, so the report can be regenerated after a change here without
paying for another load test.

It writes four things:

``metrics.csv``
    One row per second of the run, with CPU, memory and the request statistics for that second
    already lined up on the same clock. This is the file to graph — every column is numeric and
    the ``t_seconds`` column is the x-axis.
``summary.json``
    The headline numbers, for diffing two runs mechanically.
``summary.md``
    The same numbers laid out to be read.
``chart.html``
    Memory and CPU over time, plotted, in a single self-contained file.

Raw ``samples.csv`` (sub-second resolution) and ``requests.csv`` (per request) stay next to them
for anything this aggregation smooths away.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import chart

BYTES_PER_MB = 1024 * 1024

METRICS_COLUMNS = (
    "t_seconds",
    "phase",
    "cpu_percent",
    "cpu_percent_of_machine",
    "rss_mb",
    "rss_delta_mb",
    "threads",
    "open_files",
    "connections",
    "requests",
    "ok",
    "errors",
    "skipped",
    "rps_actual",
    "latency_p50_ms",
    "latency_p95_ms",
    "latency_p99_ms",
    "latency_max_ms",
)


@dataclass(frozen=True)
class Window:
    """A stretch of the run's timeline, in sampler seconds."""

    name: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    def contains(self, t: float) -> bool:
        return self.start <= t < self.end


def percentile(sorted_values: list[float], fraction: float) -> float:
    """Nearest-rank percentile: the smallest value at or above ``fraction`` of the sample.

    Empty input is 0.0 rather than an error, so a second with no requests reports as a gap
    instead of breaking the row.
    """
    if not sorted_values:
        return 0.0
    index = math.ceil(fraction * len(sorted_values)) - 1
    return sorted_values[max(0, min(len(sorted_values) - 1, index))]


def section(mapping: dict[str, object], key: str) -> dict[str, object]:
    """A nested dict out of a JSON blob, or an empty one. Keeps the writers total on partial runs."""
    value = mapping.get(key)
    return value if isinstance(value, dict) else {}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_windows(run: dict[str, object]) -> list[Window]:
    phases = run.get("phases")
    if not isinstance(phases, list):
        return []
    return [
        Window(str(phase["name"]), float(phase["start"]), float(phase["end"]))
        for phase in phases
        if isinstance(phase, dict)
    ]


def window_named(windows: list[Window], name: str) -> Window | None:
    return next((window for window in windows if window.name == name), None)


def phase_at(windows: list[Window], t: float) -> str:
    return next((window.name for window in windows if window.contains(t)), "idle")


def build_metrics(
    samples: list[dict[str, str]],
    requests: list[dict[str, str]],
    windows: list[Window],
    load_offset: float,
    baseline_rss_mb: float,
    cpu_count: int,
) -> list[dict[str, object]]:
    """Bucket both raw series into one row per second of the run."""
    sample_buckets: dict[int, list[dict[str, str]]] = defaultdict(list)
    for sample in samples:
        sample_buckets[int(float(sample["t_seconds"]))].append(sample)

    request_buckets: dict[int, list[dict[str, str]]] = defaultdict(list)
    for request in requests:
        # Request timestamps start at the load phase; shift them onto the sampler's clock.
        request_buckets[int(float(request["t_seconds"]) + load_offset)].append(request)

    rows: list[dict[str, object]] = []
    for second in sorted(set(sample_buckets) | set(request_buckets)):
        bucket = sample_buckets.get(second, [])
        calls = request_buckets.get(second, [])
        skipped = [call for call in calls if call["error"].startswith("skipped")]
        attempted = [call for call in calls if not call["error"].startswith("skipped")]
        ok = [call for call in attempted if call["status"] == "200"]
        latencies = sorted(float(call["latency_ms"]) for call in ok)

        cpu = statistics.fmean(float(row["cpu_percent"]) for row in bucket) if bucket else 0.0
        rss_mb = statistics.fmean(float(row["rss_bytes"]) for row in bucket) / BYTES_PER_MB if bucket else 0.0

        rows.append(
            {
                "t_seconds": second,
                "phase": phase_at(windows, second + 0.5),
                "cpu_percent": round(cpu, 2),
                "cpu_percent_of_machine": round(cpu / cpu_count, 2) if cpu_count else 0.0,
                "rss_mb": round(rss_mb, 3),
                "rss_delta_mb": round(rss_mb - baseline_rss_mb, 3),
                "threads": max((int(row["threads"]) for row in bucket), default=0),
                "open_files": max((int(row["open_files"]) for row in bucket), default=0),
                "connections": max((int(row["connections"]) for row in bucket), default=0),
                "requests": len(attempted),
                "ok": len(ok),
                "errors": len(attempted) - len(ok),
                "skipped": len(skipped),
                "rps_actual": len(attempted),
                "latency_p50_ms": round(percentile(latencies, 0.50), 3),
                "latency_p95_ms": round(percentile(latencies, 0.95), 3),
                "latency_p99_ms": round(percentile(latencies, 0.99), 3),
                "latency_max_ms": round(latencies[-1], 3) if latencies else 0.0,
            }
        )
    return rows


def mean_rss_mb(samples: list[dict[str, str]], window: Window | None) -> float:
    values = [
        float(sample["rss_bytes"]) / BYTES_PER_MB
        for sample in samples
        if window is None or window.contains(float(sample["t_seconds"]))
    ]
    return statistics.fmean(values) if values else 0.0


def cpu_seconds_in(samples: list[dict[str, str]], window: Window) -> float:
    """CPU time consumed inside a window, from the process's monotonic user+system counters.

    Differencing the counters is exact, unlike averaging the sampled percentages, so this is what
    the per-request CPU cost is derived from.
    """
    inside = [sample for sample in samples if window.contains(float(sample["t_seconds"]))]
    if len(inside) < 2:
        return 0.0
    total = [float(sample["cpu_user_seconds"]) + float(sample["cpu_system_seconds"]) for sample in inside]
    return total[-1] - total[0]


def summarize(
    run: dict[str, object],
    samples: list[dict[str, str]],
    requests: list[dict[str, str]],
    metrics: list[dict[str, object]],
    windows: list[Window],
    load_offset: float,
) -> dict[str, object]:
    cpu_count = int(str(section(run, "environment").get("cpu_count", 1) or 1))

    baseline = window_named(windows, "baseline")
    load_window = window_named(windows, "load")
    cooldown = window_named(windows, "cooldown")

    baseline_rss = mean_rss_mb(samples, baseline)
    peak_rss = max((float(row["rss_bytes"]) for row in samples), default=0.0) / BYTES_PER_MB
    final_rss = float(samples[-1]["rss_bytes"]) / BYTES_PER_MB if samples else 0.0
    cooldown_rss = mean_rss_mb(samples, cooldown)

    load_rows = [row for row in metrics if row["phase"] == "load"]
    load_cpu = sorted(float(str(row["cpu_percent"])) for row in load_rows)

    attempted = [call for call in requests if not call["error"].startswith("skipped")]
    ok = [call for call in attempted if call["status"] == "200"]
    latencies = sorted(float(call["latency_ms"]) for call in ok)
    cpu_seconds = cpu_seconds_in(samples, load_window) if load_window else 0.0

    warnings: list[str] = []
    server = section(run, "server")
    if server and not server.get("client_ready"):
        warnings.append(
            "The SDK client was never ready, so every config resolved to its default. "
            "This run measures the offline fallback path, not real evaluation."
        )
    if len(attempted) != len(ok):
        warnings.append(f"{len(attempted) - len(ok)} of {len(attempted)} requests did not return 200.")
    skipped = len(requests) - len(attempted)
    if skipped:
        warnings.append(f"{skipped} requests were skipped: the app could not keep up with the target rate.")
    if run.get("cpu_profile"):
        warnings.append("cProfile was active and requests were served serially; timings are inflated.")
    if run.get("tracemalloc"):
        warnings.append("tracemalloc was active; allocation-heavy paths are slower than they really are.")

    return {
        "run": run,
        "throughput": {
            "target_rps": run.get("target_rps"),
            "actual_rps": round(len(attempted) / load_window.duration, 2)
            if load_window and load_window.duration
            else 0.0,
            "requests_attempted": len(attempted),
            "requests_ok": len(ok),
            "requests_skipped": skipped,
        },
        "cpu": {
            "percent_mean": round(statistics.fmean(load_cpu), 2) if load_cpu else 0.0,
            "percent_p95": round(percentile(load_cpu, 0.95), 2),
            "percent_max": round(max(load_cpu), 2) if load_cpu else 0.0,
            "percent_of_machine_mean": round(statistics.fmean(load_cpu) / cpu_count, 2) if load_cpu else 0.0,
            "cpu_seconds_under_load": round(cpu_seconds, 3),
            "cpu_ms_per_request": round(cpu_seconds * 1000 / len(attempted), 4) if attempted else 0.0,
        },
        "memory": {
            "baseline_rss_mb": round(baseline_rss, 2),
            "peak_rss_mb": round(peak_rss, 2),
            "cooldown_rss_mb": round(cooldown_rss, 2),
            "final_rss_mb": round(final_rss, 2),
            "growth_vs_baseline_mb": round(final_rss - baseline_rss, 2),
            "retained_after_cooldown_mb": round(cooldown_rss - baseline_rss, 2),
            "bytes_per_request": round((final_rss - baseline_rss) * BYTES_PER_MB / len(attempted), 1)
            if attempted
            else 0.0,
            "peak_threads": max((int(sample["threads"]) for sample in samples), default=0),
            "peak_open_files": max((int(sample["open_files"]) for sample in samples), default=0),
        },
        "latency_ms": {
            "p50": round(percentile(latencies, 0.50), 3),
            "p95": round(percentile(latencies, 0.95), 3),
            "p99": round(percentile(latencies, 0.99), 3),
            "max": round(latencies[-1], 3) if latencies else 0.0,
            "mean": round(statistics.fmean(latencies), 3) if latencies else 0.0,
        },
        "phases": [{"name": w.name, "start": w.start, "end": w.end} for w in windows],
        "load_offset_seconds": load_offset,
        "warnings": warnings,
    }


def write_metrics_csv(rows: list[dict[str, object]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=METRICS_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def write_summary_markdown(summary: dict[str, object], path: Path) -> None:
    run = section(summary, "run")
    cpu = section(summary, "cpu")
    memory = section(summary, "memory")
    latency = section(summary, "latency_ms")
    throughput = section(summary, "throughput")
    environment = section(run, "environment")
    server = section(run, "server")

    lines = [
        f"# Profile: {run.get('label') or 'unlabelled'} — {run.get('started_at', '')}",
        "",
        "| Setting | Value |",
        "| --- | --- |",
        f"| Target rate | {run.get('target_rps')} rps for {run.get('duration_seconds')}s |",
        f"| Distinct users | {run.get('distinct_users')} |",
        f"| Connection mode | {run.get('mode')}{' (offline)' if run.get('offline') else ''} |",
        f"| SDK client ready | {server.get('client_ready', 'unknown')} |",
        f"| SDK version | {server.get('sdk_version', 'unknown')} |",
        f"| Python | {environment.get('python', '')} on {environment.get('platform', '')} |",
        f"| Cores | {environment.get('cpu_count', '')} |",
        f"| Commit | `{str(environment.get('commit', ''))[:12]}` |",
        "",
        "## Throughput",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Requests attempted | {throughput['requests_attempted']} |",
        f"| Returned 200 | {throughput['requests_ok']} |",
        f"| Skipped (app fell behind) | {throughput['requests_skipped']} |",
        f"| Achieved rate | {throughput['actual_rps']} rps |",
        "",
        "## CPU (100% = one core)",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Mean under load | {cpu['percent_mean']}% |",
        f"| p95 under load | {cpu['percent_p95']}% |",
        f"| Peak | {cpu['percent_max']}% |",
        f"| Share of the machine | {cpu['percent_of_machine_mean']}% |",
        f"| CPU seconds under load | {cpu['cpu_seconds_under_load']} |",
        f"| **CPU per request** | **{cpu['cpu_ms_per_request']} ms** |",
        "",
        "## Memory (RSS)",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Idle baseline | {memory['baseline_rss_mb']} MB |",
        f"| Peak | {memory['peak_rss_mb']} MB |",
        f"| After cooldown | {memory['cooldown_rss_mb']} MB |",
        f"| Growth vs baseline | {memory['growth_vs_baseline_mb']} MB |",
        f"| **Retained after cooldown** | **{memory['retained_after_cooldown_mb']} MB** |",
        f"| Per request | {memory['bytes_per_request']} bytes |",
        f"| Peak threads | {memory['peak_threads']} |",
        f"| Peak open files | {memory['peak_open_files']} |",
        "",
        "## Latency",
        "",
        "| Percentile | ms |",
        "| --- | --- |",
        f"| p50 | {latency['p50']} |",
        f"| p95 | {latency['p95']} |",
        f"| p99 | {latency['p99']} |",
        f"| max | {latency['max']} |",
        "",
    ]

    warnings = summary["warnings"]
    if isinstance(warnings, list) and warnings:
        lines += ["## Read this before trusting the numbers", ""]
        lines += [f"- {warning}" for warning in warnings]
        lines += [""]

    lines += [
        "## Files",
        "",
        "- `metrics.csv` — one row per second: the file to graph.",
        "- `samples.csv` — raw CPU/memory samples at the sampler's interval.",
        "- `requests.csv` — one row per request, with latency and status.",
        "- `chart.html` — memory and CPU over time, plotted.",
        "- `server.log` — the app's own output.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def build(run_dir: Path) -> dict[str, object]:
    """Read a run directory's raw output and write the report files into it."""
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    samples = read_csv(run_dir / "samples.csv")
    requests = read_csv(run_dir / "requests.csv")
    windows = load_windows(run)
    load_offset = float(run.get("load_offset_seconds", 0.0))

    cpu_count = int(str(section(run, "environment").get("cpu_count", 1) or 1))
    baseline_rss_mb = mean_rss_mb(samples, window_named(windows, "baseline"))

    metrics = build_metrics(samples, requests, windows, load_offset, baseline_rss_mb, cpu_count)
    summary = summarize(run, samples, requests, metrics, windows, load_offset)

    write_metrics_csv(metrics, run_dir / "metrics.csv")
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_summary_markdown(summary, run_dir / "summary.md")
    chart.write(metrics, summary, run_dir / "chart.html")

    print(f"[report] wrote metrics.csv, summary.json, summary.md and chart.html to {run_dir}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("run_dir", type=Path, help="A results/<run> directory to (re)build the report for.")
    args = parser.parse_args()
    if not (args.run_dir / "run.json").exists():
        print(f"{args.run_dir} does not look like a run directory (no run.json)", file=sys.stderr)
        return 1
    build(args.run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
