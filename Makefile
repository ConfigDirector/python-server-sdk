.PHONY: install lint format typecheck test coverage build clean check

install:
	uv sync --all-extras

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy

test:
	uv run pytest

coverage:
	uv run pytest --cov --cov-report=term-missing

build:
	uv build

check: lint typecheck test

clean:
	rm -rf dist build .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
