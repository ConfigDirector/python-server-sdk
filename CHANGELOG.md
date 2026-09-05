# Changelog

All notable changes to `configdirector-server-sdk` are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the package uses
[semantic versioning](https://semver.org/spec/v2.0.0.html). Releases are tagged `v<version>`.

## [Unreleased]

## [1.1.0] - 2026-09-05

### Added

- A streaming connection now sends a heartbeat to ConfigDirector every 90 seconds, and both
  connection modes identify themselves with a session ID, so the dashboard can tell which SDK
  sessions are live. The interval is fixed by the protocol and not configurable. A failed
  heartbeat is logged at debug level and does not disturb the stream.

### Changed

- `ConnectionOptions.polling_interval` now defaults to 5 minutes rather than 60 seconds, and
  `create_client` raises `ConfigDirectorValidationError` for anything shorter than 60 seconds.
  The attribute is `None` when omitted, with the default applied by the client.

### Removed

- The `"one-time"` connection mode. `ConnectionMode` is now `"streaming"` or `"polling"`; an
  application that wants a single fetch at startup can use `"polling"` and accept the refresh.
- The `matches regex` and `does NOT match regex` targeting operators, which the ConfigDirector API
  never allowed in a saved rule.

## [1.0.0] - 2026-08-24

### Added

- `create_client(...)`, returning a `ConfigDirectorClient` that is safe to share across threads
  and usable as a context manager. Building one makes no network calls; `initialize()` connects
  and waits for the first config state, bounded either by `ConnectionOptions.timeout` or by a
  timeout passed to it.
- `get_value`, taking its type from the default. It returns the default rather than raising,
  whether the client is not ready, the key is unknown, or the value will not parse as the
  default's type.
- `Context`, carrying `id`, `name`, `traits` and `anonymous` for targeting rules to evaluate
  against, and `Metadata` of `app_name` and `app_version`, which rules can also reference.
- Three connection modes, selected through `ConnectionOptions`: `"streaming"` over server-sent
  events, `"polling"` on an interval, and `"one-time"`. Streaming reconnects on its own and gives
  up on an unrecoverable status. A socket read timeout abandons a dead connection.
- `watch`, `unwatch` and `unwatch_all`, calling back with the newly evaluated value whenever an
  update carries the key. `watch` returns a `Subscription` that stops watching when closed or used
  as a context manager.
- `on` and `off` for the `client_ready`, `configs_updated` and `config_evaluated` events, and
  `ClientHooks` to attach handlers before the client can emit anything. `config_evaluated`
  publishes every evaluation, including those that returned the caller's default, with an
  `EvaluationReason` saying which it was.
- `get_all_configs`, evaluating every config the SDK holds, or a named subset, for handing to a
  client SDK to hydrate with. It records no telemetry, since the receiving SDK reports its own
  evaluations.
- Telemetry that aggregates evaluations and reports them from a background thread, so reading a
  config never waits on the network. `TelemetryOptions` tunes the queue limit and flush interval,
  and the payload names the SDK and its version.
- Logging through the standard library logger named `configdirector`, a `log_level` shortcut for
  applications that do not otherwise configure logging, or a `ConfigDirectorLogger` of your own.
- Typed throughout, on Python 3.10 through 3.14, with `urllib3` as the only dependency.
