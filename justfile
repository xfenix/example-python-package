# Run `just` with no args to list recipes.
default:
    @just --list

# Install dependencies and git hooks.
install:
    uv sync
    uv run pre-commit install

# Apply all autofixes (format, lint fixes, typing.Final).
fix:
    uv run ruff format
    uv run ruff check --fix
    uv run auto-typing-final src tests

# Check-only lint gate (never mutates files).
lint:
    uv run ruff format --check
    uv run ruff check
    uv run auto-typing-final --check src tests
    uv run flake8 src tests

# Static type checking with ty (floating version).
types:
    uvx ty check

# Run tests in parallel with coverage.
test:
    uv run pytest

# Full local gate: lint + types + tests.
check: lint types test

# Build the wheel and sdist.
build:
    uv build

# Stamp version from tag, build, and publish to PyPI.
publish version:
    uv version "{{ version }}"
    uv build
    uv publish
