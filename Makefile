.PHONY: install hooks lint format typecheck test test-lowest coverage build verify-lock dist-check release-check samples samples-local profile check check-all clean

# Every package this repository publishes, each in a directory named after its distribution.
# Narrow a target to one of them with, for example, `make test PACKAGES=configdirector-server-sdk`.
SDK := configdirector-server-sdk
PROVIDER := configdirector-openfeature-server-provider
PACKAGES := $(SDK) $(PROVIDER)

IMPORT_$(SDK) := configdirector
IMPORT_$(PROVIDER) := configdirector_openfeature

# Sample groups whose package resolves on PyPI, which is what `make samples` installs from. Add a
# group here once the first release of its package is published; until then only
# `make samples-local` can check it.
RELEASED_SAMPLE_GROUPS := $(SDK)

install:
	uv sync --all-packages

hooks:
	git config core.hooksPath .githooks
	@echo "pre-push hook installed. Bypass a single push with 'git push --no-verify'."

# Asserts uv.lock is still consistent with every pyproject.toml in the workspace, which is what
# CI installs from.
verify-lock:
	@printf '\n\033[1m==> verify-lock\033[0m\n'
	uv sync --all-packages --locked

lint:
	@printf '\n\033[1m==> lint\033[0m\n'
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	@for package in $(PACKAGES); do \
		printf '\n\033[1m==> typecheck %s\033[0m\n' "$$package"; \
		(cd "$$package" && uv run mypy) || exit 1; \
	done

test:
	@for package in $(PACKAGES); do \
		printf '\n\033[1m==> test %s\033[0m\n' "$$package"; \
		(cd "$$package" && uv run pytest) || exit 1; \
	done

# The same tests against the oldest version of each direct dependency that pyproject.toml
# claims to support, in a throwaway environment. Without this a floor such as
# `openfeature-sdk>=0.8.2` is only ever a guess, because the lock always picks the newest.
test-lowest:
	@for package in $(PACKAGES); do \
		printf '\n\033[1m==> test-lowest %s\033[0m\n' "$$package"; \
		(cd "$$package" && uv run --isolated --resolution lowest-direct pytest) || exit 1; \
	done

coverage:
	@for package in $(PACKAGES); do \
		printf '\n\033[1m==> coverage %s\033[0m\n' "$$package"; \
		(cd "$$package" && uv run pytest --cov --cov-report=term-missing) || exit 1; \
	done

# One directory per package under dist/, so that a release uploads exactly one of them.
build:
	@rm -rf dist
	@for package in $(PACKAGES); do \
		printf '\n\033[1m==> build %s\033[0m\n' "$$package"; \
		uv build --package "$$package" --out-dir "dist/$$package" || exit 1; \
	done

# Validates each built distribution's metadata and that its wheel imports on its own, in a
# throwaway environment. Leaves dist/ in place so CI can upload it. A package in this repository
# that the wheel depends on may not be released yet, so it is taken from dist/ when PyPI does not
# have it; `release-check` is the variant that refuses to.
dist-check: override PACKAGES := $(SDK) $(PROVIDER)
dist-check: build
	@for package in $(PACKAGES); do \
		printf '\n\033[1m==> dist-check %s\033[0m\n' "$$package"; \
		uvx twine check "dist/$$package"/* || exit 1; \
		$(MAKE) --no-print-directory _import-check PACKAGE="$$package" FIND_LINKS="--find-links dist/$(SDK)" || exit 1; \
	done

# What a release workflow runs for the one package it publishes: everything `dist-check` does,
# and then the wheel installed the way a user will install it, from PyPI alone. That fails when
# the wheel depends on a version of a sibling package that has not been published yet.
release-check: dist-check
	@test -n "$(PACKAGE)" || { echo "usage: make release-check PACKAGE=<package>"; exit 1; }
	@printf '\n\033[1m==> release-check %s\033[0m\n' "$(PACKAGE)"
	@$(MAKE) --no-print-directory _import-check PACKAGE="$(PACKAGE)" FIND_LINKS=

_import-check:
	@tmp=$$(mktemp -d); \
	uv venv "$$tmp/venv" --quiet \
		&& VIRTUAL_ENV="$$tmp/venv" uv pip install --quiet $(FIND_LINKS) dist/$(PACKAGE)/*.whl \
		&& VIRTUAL_ENV="$$tmp/venv" uv run --no-project python -c \
			"import $(IMPORT_$(PACKAGE)) as package; print('wheel imports cleanly:', package.__name__, package.__version__)"; \
	status=$$?; rm -rf "$$tmp"; exit $$status

# Samples are grouped by the package they demonstrate, and resolve it from PyPI, so this checks
# the published release against the sample code -- it does NOT exercise the working tree, and
# will not catch a breaking API change here.
samples:
	@for group in $(RELEASED_SAMPLE_GROUPS); do \
		for sample in samples/$$group/*/; do \
			[ -f "$$sample/pyproject.toml" ] || continue; \
			printf '\n\033[1m==> sample %s\033[0m\n' "$$sample"; \
			(cd "$$sample" && uv sync --quiet && uv run mypy && uv run pytest) || exit 1; \
		done; \
	done

# Companion to `samples`: the same apps, resolved against the packages in this working tree
# instead of the released wheels. `samples` proves the published release still works with the
# sample code; this proves an unreleased API change has not broken it. Without this target a
# breaking change passes every check, because the samples pin a version from PyPI.
#
# The sample's dependencies are installed in one resolution together with editable installs of
# the SDK and, for any other group, of that group's package too, so a package that has never been
# released resolves as well. --no-sync stops uv from undoing that before the checks run. The
# override is not written to any file, so nothing here can be committed by accident; the next
# plain `make samples` restores the released version.
samples-local:
	@for sample in samples/*/*/; do \
		[ -f "$$sample/pyproject.toml" ] || continue; \
		group=$$(basename "$$(dirname "$$sample")"); \
		locals="-e ../../../$(SDK)"; \
		[ "$$group" = "$(SDK)" ] || locals="$$locals -e ../../../$$group"; \
		printf '\n\033[1m==> sample %s (working-tree packages)\033[0m\n' "$$sample"; \
		(cd "$$sample" && uv venv --quiet --allow-existing \
			&& uv pip install --quiet $$locals -r pyproject.toml --group dev \
			&& uv run --no-sync mypy && uv run --no-sync pytest) || exit 1; \
	done

# Exploratory load profile of the Flask sample: see profiling/README.md. Deliberately not part
# of `check-all` — it needs a real server SDK key, takes minutes, and measures the machine it
# ran on as much as the SDK. Pass options through, e.g. `make profile ARGS="--rps 100"`.
profile:
	@printf '\n\033[1m==> profile\033[0m\n'
	(cd profiling && uv sync --quiet && uv run python run.py $(ARGS))

# The fast loop while working.
check: lint typecheck test

# Everything CI runs. The pre-push hook calls this.
check-all: verify-lock lint typecheck test test-lowest dist-check samples samples-local
	@printf '\n\033[1m✓ all checks passed\033[0m\n'

clean:
	rm -rf dist build .ruff_cache
	for package in $(PACKAGES); do \
		(cd "$$package" && rm -rf .pytest_cache .mypy_cache .coverage htmlcov); \
	done
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
