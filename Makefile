.PHONY: install hooks lint format typecheck test coverage build verify-lock dist-check samples profile check check-all clean

install:
	uv sync --all-extras

hooks:
	git config core.hooksPath .githooks
	@echo "pre-push hook installed. Bypass a single push with 'git push --no-verify'."

# Asserts uv.lock is still consistent with pyproject.toml, which is what CI installs from.
verify-lock:
	@printf '\n\033[1m==> verify-lock\033[0m\n'
	uv sync --all-extras --locked

lint:
	@printf '\n\033[1m==> lint\033[0m\n'
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	@printf '\n\033[1m==> typecheck\033[0m\n'
	uv run mypy

test:
	@printf '\n\033[1m==> test\033[0m\n'
	uv run pytest

coverage:
	@printf '\n\033[1m==> coverage\033[0m\n'
	uv run pytest --cov --cov-report=term-missing

build:
	@printf '\n\033[1m==> build\033[0m\n'
	rm -rf dist
	uv build

# Validates the built distribution's metadata and that the wheel imports on its own, in a
# throwaway environment. Leaves dist/ in place so CI can upload it.
dist-check: build
	@printf '\n\033[1m==> dist-check\033[0m\n'
	uvx twine check dist/*
	@tmp=$$(mktemp -d); \
	uv venv "$$tmp/venv" --quiet \
		&& VIRTUAL_ENV="$$tmp/venv" uv pip install --quiet dist/*.whl \
		&& VIRTUAL_ENV="$$tmp/venv" uv run --no-project python -c \
			"import configdirector; print('wheel imports cleanly:', configdirector.__version__)"; \
	status=$$?; rm -rf "$$tmp"; exit $$status

# Samples resolve the SDK by local path, so this is what catches a breaking API change.
samples:
	@for sample in samples/*/; do \
		[ -f "$$sample/pyproject.toml" ] || continue; \
		printf '\n\033[1m==> sample %s\033[0m\n' "$$(basename $$sample)"; \
		(cd "$$sample" && uv sync --quiet && uv run mypy && uv run pytest) || exit 1; \
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
check-all: verify-lock lint typecheck test dist-check samples
	@printf '\n\033[1m✓ all checks passed\033[0m\n'

clean:
	rm -rf dist build .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
