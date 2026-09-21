# Contributing

## Layout

This repository publishes two packages, each from a directory named after its distribution:

- [configdirector-server-sdk](configdirector-server-sdk/), the server SDK, imported as
  `configdirector`.
- [configdirector-openfeature-server-provider](configdirector-openfeature-server-provider/), the
  OpenFeature provider built on it, imported as `configdirector_openfeature`.

They are members of one [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/),
so they share a lockfile and a virtual environment, and the provider always develops against the
SDK in this working tree. Each has its own version, changelog, and release, and the provider's
published metadata depends on a version range of the SDK from PyPI, not on this repository.

[samples/](samples/) and [profiling/](profiling/) are deliberately not workspace members. They
install the packages the way an application does.

## Working on the packages

```sh
make install   # uv sync, every package
make hooks     # pre-push hook that runs make check-all
make check     # lint, typecheck, test: the fast loop
make check-all # everything CI runs
```

Targets that run per package take `PACKAGES`, so `make test PACKAGES=configdirector-server-sdk`
runs one suite.

The checks live in the [Makefile](Makefile). CI and the pre-push hook only call `make` targets,
so add new checks there rather than in either of them.

## How the provider identifies itself

The SDK reports an SDK name and version in the `User-Agent` header and in telemetry. A package
built on the SDK reports its own, without the SDK accepting an identity from its caller:
`configdirector._wrappers.Wrapper` is a closed list of the packages allowed to, each mapped to the
distribution whose installed version the SDK reads for itself. Adding a wrapper package means
adding a member there, releasing the SDK, and adding the new name to `deprecated-sdk-versions.ts`
in the core API.

## Releasing

Each package is released on its own, and the steps are the same for both. The version lives in
exactly one place per package, which Hatch reads the package version from:

| Package | Version | Changelog | Workflow |
|---|---|---|---|
| configdirector-server-sdk | [`_version.py`](configdirector-server-sdk/src/configdirector/_version.py) | [CHANGELOG.md](configdirector-server-sdk/CHANGELOG.md) | [Release configdirector-server-sdk](.github/workflows/release-configdirector-server-sdk.yml) |
| configdirector-openfeature-server-provider | [`_version.py`](configdirector-openfeature-server-provider/src/configdirector_openfeature/_version.py) | [CHANGELOG.md](configdirector-openfeature-server-provider/CHANGELOG.md) | [Release configdirector-openfeature-server-provider](.github/workflows/release-configdirector-openfeature-server-provider.yml) |

1. In the package's changelog, rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD` and open a
   fresh, empty `## [Unreleased]` above it.
2. Bump `__version__` to match and merge both to `main`.
3. Run the package's release workflow against `main`. It is manual (`workflow_dispatch`) by
   design. It builds the distributions with `make release-check`, publishes this package's to
   TestPyPI, and then to PyPI, using trusted publishing rather than stored tokens.
4. Tag the released commit `<package>-vX.Y.Z` by hand, for example
   `configdirector-server-sdk-v1.2.0`. The workflow does not tag.

PyPI never accepts the same version twice, so a rerun after a successful publish fails. Bump the
version and go again instead.

Trusted publishing is configured per package and per workflow file name, on both PyPI and
TestPyPI. Renaming a release workflow means updating the publisher there first.

### Releasing the provider after an SDK change

The provider's `pyproject.toml` names the oldest SDK version it works with. When the provider
starts using something new in the SDK, raise that floor and release the SDK first:
`make release-check` installs the provider's wheel from PyPI alone, and fails while the SDK
version it needs is not published.

### Samples

The samples pin a released package from PyPI, so they pick up a new release on their own. Raise a
floor only when a sample starts using an API the older release lacks, and only once that release
resolves on PyPI.

`make samples` only checks the sample groups listed in `RELEASED_SAMPLE_GROUPS` in the Makefile.
Add a package's group there once its first release resolves on PyPI; until then
`make samples-local` is what checks its samples.
