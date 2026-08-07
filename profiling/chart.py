"""Renders a run's per-second metrics as a single self-contained HTML page.

No CDN, no build step: the metrics are embedded as JSON and drawn as inline SVG, so the file can
be opened straight from ``results/`` or attached to an issue and still work.

Four panels share one x-axis — memory, CPU, throughput and latency — because they are four
measures on four scales. Overlaying any two of them on a second y-axis would let the reader
"see" a correlation that the arbitrary choice of scales invented.
"""

from __future__ import annotations

import json
from pathlib import Path

DATA_TOKEN = "/*__PROFILE_DATA__*/"

# Columns the page needs; anything else in metrics.csv stays in the CSV.
SERIES_COLUMNS = (
    "t_seconds",
    "phase",
    "rss_mb",
    "rss_delta_mb",
    "cpu_percent",
    "cpu_percent_of_machine",
    "rps_actual",
    "requests",
    "errors",
    "skipped",
    "threads",
    "latency_p50_ms",
    "latency_p95_ms",
    "latency_p99_ms",
)

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ConfigDirector profile</title>
<style>
  :root {
    color-scheme: light dark;
    --surface-0: #f4f3f0;
    --surface-1: #fcfcfb;
    --surface-2: #f0efec;
    --grid: #e2e1dc;
    --text-primary: #0b0b0b;
    --text-secondary: #52514e;
    --text-muted: #6f6e6a;
    --series-1: #2a78d6;
    --series-2: #eb6834;
    --series-3: #1baf7a;
    --warn: #eda100;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) {
      --surface-0: #121211;
      --surface-1: #1a1a19;
      --surface-2: #232322;
      --grid: #33332f;
      --text-primary: #ffffff;
      --text-secondary: #c3c2b7;
      --text-muted: #9b9a92;
      --series-1: #3987e5;
      --series-2: #d95926;
      --series-3: #199e70;
      --warn: #c98500;
    }
  }
  :root[data-theme="dark"] {
    --surface-0: #121211;
    --surface-1: #1a1a19;
    --surface-2: #232322;
    --grid: #33332f;
    --text-primary: #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted: #9b9a92;
    --series-1: #3987e5;
    --series-2: #d95926;
    --series-3: #199e70;
    --warn: #c98500;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    padding: 32px 24px 64px;
    background: var(--surface-0);
    color: var(--text-primary);
    font: 14px/1.5 ui-sans-serif, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  main { max-width: 1080px; margin: 0 auto; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  .subtitle { color: var(--text-secondary); margin: 0 0 24px; }
  .tiles { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 28px; }
  .tile {
    flex: 1 1 150px; background: var(--surface-1); border: 1px solid var(--grid);
    border-radius: 10px; padding: 12px 14px;
  }
  .tile .label { color: var(--text-secondary); font-size: 12px; }
  .tile .value { font-size: 24px; font-weight: 600; letter-spacing: -0.01em; margin-top: 2px; }
  .tile .value span { font-size: 13px; font-weight: 400; color: var(--text-muted); }
  .panel {
    background: var(--surface-1); border: 1px solid var(--grid); border-radius: 10px;
    padding: 14px 16px 8px; margin-bottom: 14px;
  }
  .panel header { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
  .panel h2 { font-size: 14px; margin: 0; font-weight: 600; }
  .panel .unit { color: var(--text-muted); font-size: 12px; }
  .legend { display: flex; gap: 14px; margin-left: auto; flex-wrap: wrap; }
  .legend span { display: inline-flex; align-items: center; gap: 6px; font-size: 12px;
                 color: var(--text-secondary); }
  .legend i { width: 14px; height: 2px; border-radius: 1px; display: inline-block; }
  svg { display: block; width: 100%; height: auto; overflow: visible; }
  .warnings {
    background: var(--surface-1); border: 1px solid var(--warn); border-left-width: 4px;
    border-radius: 8px; padding: 12px 16px; margin-bottom: 24px;
  }
  .warnings ul { margin: 6px 0 0; padding-left: 18px; color: var(--text-secondary); }
  details { margin-top: 24px; }
  summary { cursor: pointer; color: var(--text-secondary); }
  .table-wrap { overflow-x: auto; max-height: 420px; overflow-y: auto; margin-top: 12px; }
  table { border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
  th, td { padding: 4px 10px; text-align: right; white-space: nowrap; }
  th { position: sticky; top: 0; background: var(--surface-1); color: var(--text-secondary);
       border-bottom: 1px solid var(--grid); text-align: right; }
  td:nth-child(2), th:nth-child(2) { text-align: left; }
  tbody tr:nth-child(even) { background: var(--surface-2); }
  #tooltip {
    position: fixed; pointer-events: none; opacity: 0; transition: opacity .1s;
    background: var(--surface-1); border: 1px solid var(--grid); border-radius: 8px;
    padding: 8px 10px; font-size: 12px; box-shadow: 0 6px 20px rgba(0,0,0,.16); z-index: 10;
    min-width: 168px;
  }
  #tooltip .tt-time { color: var(--text-secondary); margin-bottom: 6px; }
  #tooltip .tt-row { display: flex; align-items: center; gap: 8px; }
  #tooltip .tt-row i { width: 12px; height: 2px; border-radius: 1px; flex: none; }
  #tooltip .tt-row b { font-weight: 600; margin-left: auto; font-variant-numeric: tabular-nums; }
  #tooltip .tt-row span { color: var(--text-secondary); }
  footer { color: var(--text-muted); font-size: 12px; margin-top: 28px; }
</style>
</head>
<body>
<main>
  <h1 id="title"></h1>
  <p class="subtitle" id="subtitle"></p>
  <div class="warnings" id="warnings" hidden><strong>Read this before trusting the numbers</strong>
    <ul></ul></div>
  <div class="tiles" id="tiles"></div>
  <div id="panels"></div>
  <details>
    <summary>Data table — every value plotted above</summary>
    <div class="table-wrap"><table id="table"></table></div>
  </details>
  <footer id="footer"></footer>
</main>
<div id="tooltip" role="status" aria-live="polite"></div>
<script>
const DATA = /*__PROFILE_DATA__*/;

const W = 1000, H = 170, M = { top: 14, right: 46, bottom: 24, left: 58 };
const PLOT_W = W - M.left - M.right, PLOT_H = H - M.top - M.bottom;
const SVG_NS = "http://www.w3.org/2000/svg";

const PANELS = [
  { title: "Memory", unit: "MB resident (RSS)", zeroBased: false,
    series: [{ key: "rss_mb", name: "RSS", color: "--series-1" }] },
  { title: "CPU", unit: "% of one core", zeroBased: true,
    series: [{ key: "cpu_percent", name: "CPU", color: "--series-1" }] },
  { title: "Throughput", unit: "requests completed per second", zeroBased: true,
    series: [{ key: "rps_actual", name: "Completed", color: "--series-1" }] },
  { title: "Latency", unit: "milliseconds", zeroBased: true,
    series: [
      { key: "latency_p50_ms", name: "p50", color: "--series-1" },
      { key: "latency_p95_ms", name: "p95", color: "--series-2" },
      { key: "latency_p99_ms", name: "p99", color: "--series-3" },
    ] },
];

const rows = DATA.metrics;
const tMin = rows.length ? rows[0].t_seconds : 0;
const tMax = rows.length ? rows[rows.length - 1].t_seconds : 1;
const xOf = (t) => M.left + (tMax === tMin ? 0 : (t - tMin) / (tMax - tMin)) * PLOT_W;

const el = (name, attrs = {}, parent = null) => {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  if (parent) parent.appendChild(node);
  return node;
};
const fmt = (value, digits = 1) =>
  value === null || value === undefined ? "—" : Number(value).toFixed(digits).replace(/\\.0+$/, "");

/** Round an axis maximum up to something a reader can do arithmetic with. */
function niceTicks(min, max, count = 4) {
  if (!isFinite(min) || !isFinite(max) || max === min) return [min, min + 1];
  const raw = (max - min) / count;
  const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].find((m) => m * magnitude >= raw) * magnitude;
  const start = Math.floor(min / step) * step, end = Math.ceil(max / step) * step;
  const ticks = [];
  for (let value = start; value <= end + step / 2; value += step) ticks.push(Number(value.toFixed(6)));
  return ticks;
}

function drawPanel(panel, isFirst, isLast) {
  const wrap = document.createElement("section");
  wrap.className = "panel";
  const header = document.createElement("header");
  const heading = document.createElement("h2");
  heading.textContent = panel.title;
  const unit = document.createElement("span");
  unit.className = "unit";
  unit.textContent = panel.unit;
  header.append(heading, unit);

  // A legend is the dependable identity channel whenever more than one line shares a panel.
  if (panel.series.length > 1) {
    const legend = document.createElement("div");
    legend.className = "legend";
    for (const series of panel.series) {
      const item = document.createElement("span");
      const key = document.createElement("i");
      key.style.background = `var(${series.color})`;
      const name = document.createElement("span");
      name.textContent = series.name;
      item.append(key, name);
      legend.appendChild(item);
    }
    header.appendChild(legend);
  }
  wrap.appendChild(header);

  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });
  svg.setAttribute("aria-label", `${panel.title} over time`);

  const values = rows.flatMap((row) => panel.series.map((s) => row[s.key])).filter(Number.isFinite);
  const dataMax = values.length ? Math.max(...values) : 1;
  const dataMin = values.length ? Math.min(...values) : 0;
  // Rates start at zero because zero is meaningful. An absolute level like RSS does not: pinning
  // it to zero would flatten the growth that is the whole reason to plot it.
  const ticks = panel.zeroBased
    ? niceTicks(0, dataMax || 1)
    : niceTicks(dataMin - (dataMax - dataMin || 1) * 0.25, dataMax + (dataMax - dataMin || 1) * 0.15);
  const yMin = ticks[0], yMax = ticks[ticks.length - 1];
  const yOf = (value) => M.top + PLOT_H - ((value - yMin) / (yMax - yMin || 1)) * PLOT_H;

  // Phase bands: the stretches that are not "load" are shaded, so the traffic window is obvious.
  for (const phase of DATA.phases) {
    const x0 = xOf(Math.max(phase.start, tMin)), x1 = xOf(Math.min(phase.end, tMax));
    if (x1 <= x0) continue;
    if (phase.name !== "load") {
      el("rect", { x: x0, y: M.top, width: x1 - x0, height: PLOT_H, fill: "var(--surface-2)" }, svg);
    }
    // Name the phases once, on the top panel; the shading carries them down the rest.
    if (isFirst && x1 - x0 > 40) {
      const label = el("text", { x: (x0 + x1) / 2, y: M.top + 11, "text-anchor": "middle",
                                 fill: "var(--text-muted)", "font-size": 10 }, svg);
      label.textContent = phase.name;
    }
  }

  for (const tick of ticks) {
    el("line", { x1: M.left, x2: W - M.right, y1: yOf(tick), y2: yOf(tick),
                 stroke: "var(--grid)", "stroke-width": 1, "vector-effect": "non-scaling-stroke" }, svg);
    const label = el("text", { x: M.left - 8, y: yOf(tick) + 4, "text-anchor": "end",
                               fill: "var(--text-muted)", "font-size": 11 }, svg);
    label.textContent = fmt(tick, tick % 1 === 0 ? 0 : 1);
  }

  for (const series of panel.series) {
    const points = rows
      .filter((row) => Number.isFinite(row[series.key]))
      .map((row) => `${xOf(row.t_seconds).toFixed(2)},${yOf(row[series.key]).toFixed(2)}`);
    if (!points.length) continue;
    el("polyline", {
      points: points.join(" "), fill: "none", stroke: `var(${series.color})`,
      "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round",
      "vector-effect": "non-scaling-stroke",
    }, svg);
  }

  // Label the peak, not the endpoint: in a load test the extreme is the story, and after the
  // cooldown every rate series ends at a zero that says nothing. Labels that would collide are
  // dropped rather than nudged — a nudged label stops pointing at anything, and the tooltip and
  // table view keep every value reachable anyway.
  const peaks = panel.series
    .map((series) => {
      let best = null;
      for (const row of rows) {
        if (Number.isFinite(row[series.key]) && (!best || row[series.key] > best[series.key])) best = row;
      }
      return best ? { series, row: best, x: xOf(best.t_seconds), y: yOf(best[series.key]) } : null;
    })
    .filter(Boolean)
    .sort((a, b) => a.y - b.y);
  const placed = [];
  for (const peak of peaks) {
    if (placed.some((other) => Math.abs(other.y - peak.y) < 14 && Math.abs(other.x - peak.x) < 90)) continue;
    placed.push(peak);
    el("circle", { cx: peak.x, cy: peak.y, r: 4, fill: `var(${peak.series.color})`,
                   stroke: "var(--surface-1)", "stroke-width": 2 }, svg);
    const atRightEdge = peak.x > W - M.right - 46;
    const label = el("text", {
      x: peak.x + (atRightEdge ? -8 : 8),
      y: Math.max(peak.y - 8, M.top + 10),
      "text-anchor": atRightEdge ? "end" : "start",
      fill: "var(--text-secondary)", "font-size": 11,
    }, svg);
    label.textContent = fmt(peak.row[peak.series.key], 1);
  }

  if (isLast) {
    for (const tick of niceTicks(tMin, tMax, 6)) {
      if (tick < tMin || tick > tMax) continue;
      const label = el("text", { x: xOf(tick), y: H - 4, "text-anchor": "middle",
                                 fill: "var(--text-muted)", "font-size": 11 }, svg);
      label.textContent = `${fmt(tick, 0)}s`;
    }
  }

  const crosshair = el("line", { y1: M.top, y2: M.top + PLOT_H, stroke: "var(--text-muted)",
                                 "stroke-width": 1, "vector-effect": "non-scaling-stroke",
                                 opacity: 0 }, svg);
  const dots = panel.series.map((series) =>
    el("circle", { r: 4, fill: `var(${series.color})`, stroke: "var(--surface-1)",
                   "stroke-width": 2, opacity: 0 }, svg));

  wrap.appendChild(svg);
  return { wrap, svg, crosshair, dots, panel, yOf };
}

const panelViews = PANELS.map((panel, index) =>
  drawPanel(panel, index === 0, index === PANELS.length - 1));
const panelsHost = document.getElementById("panels");
for (const view of panelViews) panelsHost.appendChild(view.wrap);

// -- hover: one crosshair across every panel, one tooltip listing every series ------------
const tooltip = document.getElementById("tooltip");

function nearestRow(clientX, svg) {
  const box = svg.getBoundingClientRect();
  const scale = W / box.width;
  const x = (clientX - box.left) * scale;
  const t = tMin + ((x - M.left) / PLOT_W) * (tMax - tMin);
  let best = null, bestDistance = Infinity;
  for (const row of rows) {
    const distance = Math.abs(row.t_seconds - t);
    if (distance < bestDistance) { bestDistance = distance; best = row; }
  }
  return best;
}

function showAt(row, event) {
  for (const view of panelViews) {
    view.crosshair.setAttribute("x1", xOf(row.t_seconds));
    view.crosshair.setAttribute("x2", xOf(row.t_seconds));
    view.crosshair.setAttribute("opacity", 0.4);
    view.panel.series.forEach((series, index) => {
      const dot = view.dots[index];
      if (!Number.isFinite(row[series.key])) { dot.setAttribute("opacity", 0); return; }
      dot.setAttribute("cx", xOf(row.t_seconds));
      dot.setAttribute("cy", view.yOf(row[series.key]));
      dot.setAttribute("opacity", 1);
    });
  }

  tooltip.textContent = "";
  const time = document.createElement("div");
  time.className = "tt-time";
  time.textContent = `t = ${row.t_seconds}s · ${row.phase}`;
  tooltip.appendChild(time);
  // Only the latency series get a colored key: they are the one panel where color carries
  // identity. Keying the single-series panels would imply a shared meaning for blue.
  const readouts = [
    [null, "RSS", `${fmt(row.rss_mb, 2)} MB`],
    [null, "CPU", `${fmt(row.cpu_percent, 1)}%`],
    [null, "Requests", `${row.rps_actual}/s`],
    ["--series-1", "p50", `${fmt(row.latency_p50_ms, 2)} ms`],
    ["--series-2", "p95", `${fmt(row.latency_p95_ms, 2)} ms`],
    ["--series-3", "p99", `${fmt(row.latency_p99_ms, 2)} ms`],
  ];
  for (const [color, name, value] of readouts) {
    const line = document.createElement("div");
    line.className = "tt-row";
    const key = document.createElement("i");
    if (color) key.style.background = `var(${color})`;
    const label = document.createElement("span");
    label.textContent = name;
    const strong = document.createElement("b");
    strong.textContent = value;
    line.append(key, label, strong);
    tooltip.appendChild(line);
  }
  tooltip.style.opacity = "1";
  const x = Math.min(event.clientX + 16, window.innerWidth - tooltip.offsetWidth - 12);
  const y = Math.min(event.clientY + 16, window.innerHeight - tooltip.offsetHeight - 12);
  tooltip.style.left = `${x}px`;
  tooltip.style.top = `${y}px`;
}

function hide() {
  tooltip.style.opacity = "0";
  for (const view of panelViews) {
    view.crosshair.setAttribute("opacity", 0);
    for (const dot of view.dots) dot.setAttribute("opacity", 0);
  }
}

for (const view of panelViews) {
  view.svg.addEventListener("pointermove", (event) => {
    const row = nearestRow(event.clientX, view.svg);
    if (row) showAt(row, event);
  });
  view.svg.addEventListener("pointerleave", hide);
}

// -- headline numbers, warnings and the table ---------------------------------------------
const run = DATA.summary.run || {};
const memory = DATA.summary.memory || {};
const cpu = DATA.summary.cpu || {};
const latency = DATA.summary.latency_ms || {};
const throughput = DATA.summary.throughput || {};

document.getElementById("title").textContent =
  `Flask sample under ${run.target_rps} rps for ${run.duration_seconds}s`;
document.getElementById("subtitle").textContent =
  `${run.started_at || ""} · ${run.mode}${run.offline ? " (offline)" : ""} · ` +
  `${throughput.requests_ok} of ${throughput.requests_attempted} requests returned 200`;

const tiles = [
  ["Peak memory", `${fmt(memory.peak_rss_mb, 1)}`, "MB"],
  ["Retained after cooldown", `${fmt(memory.retained_after_cooldown_mb, 2)}`, "MB over baseline"],
  ["CPU per request", `${fmt(cpu.cpu_ms_per_request, 3)}`, "ms"],
  ["CPU under load", `${fmt(cpu.percent_mean, 1)}`, "% of a core"],
  ["Latency p95", `${fmt(latency.p95, 2)}`, "ms"],
];
const tilesHost = document.getElementById("tiles");
for (const [label, value, unit] of tiles) {
  const tile = document.createElement("div");
  tile.className = "tile";
  const labelNode = document.createElement("div");
  labelNode.className = "label";
  labelNode.textContent = label;
  const valueNode = document.createElement("div");
  valueNode.className = "value";
  valueNode.textContent = value + " ";
  const unitNode = document.createElement("span");
  unitNode.textContent = unit;
  valueNode.appendChild(unitNode);
  tile.append(labelNode, valueNode);
  tilesHost.appendChild(tile);
}

const warnings = DATA.summary.warnings || [];
if (warnings.length) {
  const box = document.getElementById("warnings");
  box.hidden = false;
  const list = box.querySelector("ul");
  for (const warning of warnings) {
    const item = document.createElement("li");
    item.textContent = warning;
    list.appendChild(item);
  }
}

const table = document.getElementById("table");
const columns = DATA.columns;
const head = table.createTHead().insertRow();
for (const column of columns) {
  const cell = document.createElement("th");
  cell.textContent = column;
  head.appendChild(cell);
}
const body = table.createTBody();
for (const row of rows) {
  const line = body.insertRow();
  for (const column of columns) line.insertCell().textContent = String(row[column]);
}

const environment = run.environment || {};
document.getElementById("footer").textContent =
  `SDK ${(run.server || {}).sdk_version || "?"} · Python ${environment.python} · ` +
  `${environment.cpu_count} cores · ${environment.platform} · commit ` +
  `${String(environment.commit || "").slice(0, 12)}`;
</script>
</body>
</html>
"""


def write(metrics: list[dict[str, object]], summary: dict[str, object], path: Path) -> None:
    """Write the chart page for one run."""
    payload = {
        "metrics": [{column: row.get(column) for column in SERIES_COLUMNS} for row in metrics],
        "columns": list(SERIES_COLUMNS),
        "phases": summary.get("phases", []),
        "summary": summary,
    }
    # `</script>` inside the JSON would end the script block early; escaping the slash is the
    # standard fix and stays valid JSON.
    encoded = json.dumps(payload, default=str).replace("</", "<\\/")
    path.write_text(TEMPLATE.replace(DATA_TOKEN, encoded), encoding="utf-8")
