# Changelog

All notable changes to `configdirector-openfeature-server-provider` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Releases are tagged `configdirector-openfeature-server-provider-v<version>`.

## [Unreleased]

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
