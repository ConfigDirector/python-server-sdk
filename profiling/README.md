# Profiling

Exploratory load profiling for the SDK: drive the [Flask sample](../samples/flask) at a chosen
request rate for a chosen length of time, record the app process's CPU and memory the whole way
through, and write the result out in a form you can graph and compare.

This is a measurement tool, not a check. It is not part of `make check-all` — it needs a real
server SDK key, takes minutes, and its numbers depend on the machine it ran on.

```bash
make profile                                    # 25 rps for 60s, the default
make profile ARGS="--rps 100 --duration 300"    # anything the CLI takes
```

Or directly, which is what the make target does:

```bash
cd profiling
uv run python run.py --rps 100 --duration 300 --label hundred-rps
```

Results land in `profiling/results/<timestamp>-<label>/` (gitignored). Start with `summary.md`,
graph `metrics.csv`, open `chart.html` if you would rather not.

## What one run does

| Phase | Why it exists |
| --- | --- |
| **baseline** (`--baseline`, 5s) | The app is up and idle. Resting RSS and CPU, which every later number is read against. |
| **warmup** (`--warmup-requests`, 50) | Imports, connection setup, and the SDK's first evaluation of each config all cost something once. Excluded from the report so they do not look like a startup spike. |
| **load** (`--rps`, `--duration`) | The measurement. |
| **cooldown** (`--cooldown`, 20s) | Traffic stops, sampling does not. Memory that does not come back down here is the interesting kind. Raise it past 30s to catch a telemetry flush at its default interval. |

Then the app gets SIGTERM — the sample's `atexit` hook closes the client and flushes telemetry,
the same as a real shutdown — and the report is written.

## The knobs

| Flag | Default | What it changes |
| --- | --- | --- |
| `--rps` | 25 | Requests per second. Anything from 1 to ~100 is comfortable on a laptop. |
| `--duration` | 60 | Seconds to hold that rate. |
| `--distinct-users` | 500 | How many distinct user ids the traffic cycles through. Raise it to grow the SDK's per-context telemetry; drop it to 1 to take context cardinality out of the picture. |
| `--mode` | `streaming` | SDK connection mode: `streaming` or `polling`. |
| `--offline` | off | Point the SDK at an address nothing answers on. Every config resolves to its default, so this profiles the fallback path — and gives a network-free comparison run. |
| `--sample-interval` | 0.25 | Seconds between CPU/memory samples. |
| `--max-in-flight` | `max(50, 4×rps)` | Concurrency cap. Requests over the cap are recorded as skipped rather than queued. |
| `--cpu-profile` | off | Also run under cProfile. **Serves requests serially and inflates every timing** — a separate investigation, not an addition to a normal run. |
| `--tracemalloc` | off | Also track allocations, to attribute memory growth to source lines. Significant overhead. POSIX only. |
| `--label` | — | Suffix for the results directory, so runs are tellable apart. |

## What you get

| File | What it is |
| --- | --- |
| `metrics.csv` | **One row per second**, with CPU, memory and request statistics already on the same clock. This is the file to graph — every column is numeric, `t_seconds` is the x-axis. |
| `chart.html` | Memory, CPU, throughput and latency plotted over time. Self-contained; open it in a browser. |
| `summary.md` | The headline numbers, laid out to read. |
| `summary.json` | The same numbers, for diffing two runs mechanically. |
| `samples.csv` | Raw CPU/memory samples at the sampler's interval — finer than one second. |
| `requests.csv` | One row per request: offset, latency, status. |
| `run.json` | Settings, phase boundaries, Python/SDK versions, commit. |
| `server.log` | The app's own output. |
| `cprofile.pstats`, `cprofile.txt` | Function-level CPU, with `--cpu-profile`. Browse the raw stats with `uv run python -m pstats results/<run>/cprofile.pstats`. |
| `tracemalloc.txt`, `tracemalloc.json` | Allocation growth by source line, with `--tracemalloc`. |

The two numbers worth watching:

* **`retained_after_cooldown_mb`** — memory still held once the traffic stopped. Growth *during*
  load is ordinary; growth that does not come back is what a leak looks like.
* **`cpu_ms_per_request`** — CPU seconds burned under load, divided by requests served. Derived
  from the process's monotonic user+system counters, so it is exact rather than an average of
  sampled percentages. It covers the whole request, Flask and Werkzeug included, not just the
  SDK — compare runs against each other rather than reading it as the cost of `get_value`.

## Reading the results honestly

**Check `client_ready` first.** `summary.md` says whether the SDK client ever became ready.
Without a working key in `samples/flask/.env` it never does, every config resolves to its default,
and the run measures the fallback path rather than real evaluation. The report says so in its
warnings; it does not stop you, because that path is worth profiling too.

**The dev server is not your production server.** The app is served by Werkzeug in one process
with a thread per request. That is the right shape for watching the SDK's own cost and completely
the wrong shape for a throughput benchmark — Gunicorn with several workers would look different in
every respect except the per-request SDK work.

**The harness changes two things about the sample**, both to keep the measurement honest, and both
in [`server.py`](server.py): Werkzeug's per-request log line is silenced, and the SDK's logger is
forced to WARNING. `samples/flask/.env` may ask for DEBUG, which logs every single evaluation and
would cost more than the evaluation being measured.

**Load is generated in a separate process** from the app, so the generator's own CPU and memory
never land in the numbers. The pacing is open-loop: request *i* goes out at `start + i/rps`
whether or not earlier ones have come back, so the offered rate stays at the target when the app
slows down. Back-pressure shows up as rising latency, and past `--max-in-flight` as skipped
requests, instead of the generator quietly throttling itself and hiding the problem.

## Working on it

```bash
cd profiling
uv sync
uv run mypy            # this harness only; `make lint` at the root covers its style
uv run python report.py results/<run>    # rebuild a report without re-running the load
```

`report.py` is a separate entry point on purpose: regenerating a report is free, so a change to
the aggregation or the chart does not cost another load test.

The pieces, in the order the run uses them: [`run.py`](run.py) orchestrates,
[`server.py`](server.py) is the app under measurement, [`sampler.py`](sampler.py) reads CPU and
memory from outside the app process, [`load.py`](load.py) generates traffic,
[`report.py`](report.py) aggregates, [`chart.py`](chart.py) draws.

## Things worth trying

* **`--offline` against a live run.** The difference is what evaluation and telemetry actually
  cost, with Flask's own overhead cancelled out on both sides.
* **`--distinct-users 1` against the default 500.** Isolates what context cardinality costs in
  telemetry.
* **A long run with a long `--cooldown`.** Telemetry flushes every 30s by default; a 5-minute run
  with a 60s cooldown shows several flushes and whether anything accumulates between them.
* **`--mode polling` against `--mode streaming`.** Separates the streaming connection's standing
  cost from the evaluation path.
* **`--cpu-profile` once you have a suspect**, to find which functions the time is actually in.
