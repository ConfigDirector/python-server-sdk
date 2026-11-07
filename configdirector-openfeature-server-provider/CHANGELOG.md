# Changelog

All notable changes to `configdirector-openfeature-server-provider` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Releases are tagged `configdirector-openfeature-server-provider-v<version>`.

## [Unreleased]

## [1.8.1] - 2026-11-07

### Fixed

- An evaluation context with neither a targeting key nor an `id` attribute that skips a percentage
  rollout is now resolved by the targeting rules after it, as it is after a conditional rule it
  does not match. Since 1.8.0 the skipped rollout ended the evaluation and the flag resolved to the
  default targeting rule value, even when a later rule matched the context. A later rule that
  applies resolves with the reason `TARGETING_MATCH`; `DEFAULT` stays for a context resolved to the
  default targeting rule value after a skipped rollout.
- Requires `configdirector-server-sdk` 1.9.1 or later, which carries the fix.

## [1.8.0] - 2026-11-06

### Added

- The provider now implements OpenFeature's tracking. `client.track(event_name, context, details)`
  reports to ConfigDirector that something happened, such as a completed checkout, so ConfigDirector
  can show it on the live feed and count it for each variation of a running experiment. Before, a
  `track` call did nothing. The details' `value` is sent as the event's value, their other attributes
  as the event's details, and the `targeting_key` (or `id` attribute) and `kind` of the merged
  evaluation context as the context the event happened for.
- An event counts for an experiment only when its evaluation context has the `targeting_key` the
  experiment's flag was evaluated with. Without one, the event is still reported. The
  `targeting_key` of a context marked `anonymous` is not sent.
- Tracked events are sent with the next telemetry batch, at most 1,000 per batch; events beyond that
  are not reported. An event whose name does not have 1 to 150 characters is not reported. Details
  with more than 20 top-level keys or larger than 1 KB as JSON, and a `value` that is not a finite
  number, are left out and the event is still reported. Each of these logs one warning per telemetry
  batch. `track` never raises, and does nothing in `offline` mode.
- The evaluation counts the provider sends to ConfigDirector now say which variation was served,
  and which percentage rollout and share served it, so ConfigDirector can count the contexts each
  variation of an experiment reached.

### Changed

- The `variant` in evaluation details is now the variation's name when the config has variations
  and the variation served has a name, such as `treatment`. Before, it was always the value ID. It
  stays the value ID for a config without variations and for an unnamed variation. If you send
  `variant` to an analytics tool, an experiment's evaluations now show up under the variation
  names.
- An evaluation context with neither a `targeting_key` nor an `id` attribute now skips percentage
  rollouts. The flag resolves to the default targeting rule value with the reason `DEFAULT`, and
  the targeting rules after the rollout are not tried. Before, every such context was served the
  rollout's first share. Give an anonymous context a stable `targeting_key`, such as a session ID,
  to keep it in a rollout. A rule that serves a single value still applies to a context without
  one.
- Telemetry reports now write text outside ASCII as UTF-8 rather than as escape sequences, so they
  are smaller.
- Requires `configdirector-server-sdk` 1.9.0 or later, which has the `evaluate` and `track` methods
  the provider now calls.

### Fixed

- A telemetry report larger than ConfigDirector accepts is now discarded with a warning, and the
  next report is still sent. Before, the provider stopped sending telemetry until the process
  restarted.
- A telemetry report holding text that UTF-8 cannot represent, such as an unpaired surrogate in a
  targeting key, is now sent with a replacement character in its place.

## [1.7.0] - 2026-10-28

### Changed

- When no config arrives within the connection timeout, initialization now fails:
  `set_provider_and_wait` raises, and the provider reports the `ERROR` status until config
  arrives, then `READY`. Before, it reported `READY` while serving in-code default values, then
  `READY` again once config arrived. To start without waiting for ConfigDirector, call
  `set_provider` instead, or catch the exception.
- Requires `openfeature-sdk` 0.10 or newer.

### Fixed

- An object flag whose in-code default value is a dict now resolves to the config's value only
  when that value is a JSON object, and one whose in-code default value is a list only when it is
  a JSON list. Any other value gives the in-code default value with `TYPE_MISMATCH`, and the
  dashboard shows the Config type mismatch alert for the config, as it does for other mismatches.
  Before, a JSON list reached a flag read with a dict, or a JSON object one read with a list, with
  `TARGETING_MATCH`, and `get_object_value_async` returned a bare `42`, `"text"`, `true` or
  `null` as the flag's value. Requires `configdirector-server-sdk` 1.8.1 or later, which carries
  the same fix.

## [1.6.0] - 2026-10-22

### Added

- Offline mode, through the SDK's `ConnectionOptions(mode="offline")`: the provider never connects
  to ConfigDirector and serves the values of a JSON file given with `file`, or of a mapping given
  inline with `values`, to every evaluation, sending nothing. An offline provider needs no server
  SDK key, so
  `ConfigDirectorProvider(connection=ConnectionOptions(mode="offline", values={"new-checkout": True}))`
  takes the options alone. If the offline values cannot be loaded, `file` and `values` are both
  given, or either is given in `streaming` or `polling` mode, the provider's `initialize` raises
  `ConfigDirectorInitializationError`, which `set_provider_and_wait` raises in turn, and
  OpenFeature leaves the provider in the error state. Requires `configdirector-server-sdk` 1.8.0
  or later, which adds offline mode.

### Changed

- The `server_sdk_key` of `ConfigDirectorProvider` is optional and can be left out in offline
  mode. Outside offline mode a missing or blank key still raises `ConfigDirectorValidationError`,
  which `ConfigDirectorProvider()` called with no arguments now raises instead of a `TypeError`.
- An unknown connection mode, such as `"stream"`, raises `ConfigDirectorValidationError` when the
  provider is created instead of streaming.

## [1.5.0] - 2026-10-14

### Added

- The provider reads a top-level `kind` attribute of the evaluation context, beside the targeting
  key, as the ConfigDirector context kind, for example
  `EvaluationContext("kiosk-7", {"kind": "device"})`. Leaving it out means `user`, and a `kind`
  inside `traits` stays an ordinary trait. A kind has 1 to 64 characters, using only lowercase
  letters, digits, `-` and `_`. With any other kind, including one that is not a string, the whole
  context is ignored: the evaluation still resolves successfully, to the value for no context and
  without an error code, and the SDK logs an error. Requires `configdirector-server-sdk` 1.7.0 or
  later, which adds `Context.kind`.

### Changed

- A top-level `kind` attribute in the evaluation context was ignored before. An application that
  already sets one now has it evaluated as the context kind, and if it is not a valid kind the
  whole context is ignored as described above.

## [1.4.1] - 2026-10-05

### Fixed

- A segment change now emits `PROVIDER_CONFIGURATION_CHANGED` with the affected flags in
  `flags_changed`: every flag whose targeting rules use the changed segment. Before, editing a
  segment or one of its environment overrides emitted the event with an empty `flags_changed`.
  Requires `configdirector-server-sdk` 1.6.1 or later, which reports those flags in
  `ConfigsUpdatedEvent.keys`.

## [1.4.0] - 2026-10-05

### Added

- Targeting rules can now use segments: the provider evaluates segment conditions through the
  server SDK. Requires `configdirector-server-sdk` 1.6.0 or later, which reads the payload's
  segments. ConfigDirector only sends rules with segment conditions to provider versions that
  evaluate them, so upgrading is what makes rules that use segments apply to this application.

## [1.3.0] - 2026-10-01

### Changed

- `PROVIDER_CONFIGURATION_CHANGED` now lists the flags a full update removed in `flags_changed`,
  after the flags the update carried. Before, a removed flag was not reported as changed. Requires
  `configdirector-server-sdk` 1.5.0 or later, which adds `ConfigsUpdatedEvent.removed_keys`.

## [1.2.1] - 2026-09-26

### Changed

- Bump the dependency on the server SDK to 1.4.1 in order to pick up the telemetry fix.

## [1.2.0] - 2026-09-25

### Changed

- Bump the dependency on the server SDK to 1.4.0 in order to pick up the type mismatch update.

## [1.1.0] - 2026-09-23

### Fixed

- Bump the dependency on the server SDK to 1.3.0 in order to pick up the conditional evaluation fix.

## [1.0.0] - 2026-09-21

### Added

- `ConfigDirectorProvider`, an OpenFeature server provider backed by the ConfigDirector Python server SDK. It resolves boolean, string, integer, float, and object flags, maps the OpenFeature evaluation context onto the ConfigDirector context, reports evaluation reasons, variants, and error codes, and emits `PROVIDER_READY` and `PROVIDER_CONFIGURATION_CHANGED` events.
