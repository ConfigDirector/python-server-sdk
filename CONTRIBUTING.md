# Contributing

## Working on the SDK

```sh
make install   # uv sync, all extras
make hooks     # pre-push hook that runs make check-all
make check     # lint, typecheck, test: the fast loop
make check-all # everything CI runs
```

The checks live in the [Makefile](Makefile). CI and the pre-push hook only call `make` targets,
so add new checks there rather than in either of them.

## Releasing

The version lives in exactly one place: `__version__` in
[src/configdirector/_version.py](src/configdirector/_version.py). Hatch reads the package version
from it, and the SDK reports it in the `User-Agent` and telemetry.

1. In [CHANGELOG.md](CHANGELOG.md), rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD` and
   open a fresh, empty `## [Unreleased]` above it.
2. Bump `__version__` to match and merge both to `main`.
3. Run the [Release](.github/workflows/release.yml) workflow against `main`. It is manual
   (`workflow_dispatch`) by design. It builds the distribution with `make dist-check`, publishes
   it to TestPyPI, and then to PyPI, using trusted publishing rather than stored tokens.
4. Tag the released commit `vX.Y.Z` by hand. The workflow does not tag.

PyPI never accepts the same version twice, so a rerun after a successful publish fails. Bump the
version and go again instead.

The samples pin `configdirector-server-sdk>=1.0` from PyPI, so they pick up a new release on their
own. Raise that floor only when a sample starts using an API the older release lacks, and only once
that release resolves on PyPI.
