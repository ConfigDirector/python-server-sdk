# Changelog

All notable changes to `configdirector-openfeature-server-provider` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Releases are tagged `configdirector-openfeature-server-provider-v<version>`.

## [Unreleased]

## [1.2.0] - 2026-09-21

### Added

- `ConfigDirectorProvider`, an OpenFeature server provider backed by the ConfigDirector Python server SDK. It resolves boolean, string, integer, float, and object flags, maps the OpenFeature evaluation context onto the ConfigDirector context, reports evaluation reasons, variants, and error codes, and emits `PROVIDER_READY` and `PROVIDER_CONFIGURATION_CHANGED` events.
