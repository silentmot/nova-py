# Nova — developer tasks.
# Use: `make help`, `make install`, `make run`, `make test`, ...

PY ?= python
VENV ?= .venv

# Windows venvs put executables in .venv/Scripts/; POSIX uses .venv/bin/.
# Detect via the MAKE-builtin $(OS) variable (set to "Windows_NT" by cmd/git-bash).
ifeq ($(OS),Windows_NT)
    VENV_BIN := $(VENV)/Scripts
else
    VENV_BIN := $(VENV)/bin
endif

PYV := $(VENV_BIN)/python
PIP := $(PYV) -m pip

.PHONY: help venv install install-dev hooks run test lint format typecheck check clean docker-build docker-run

help:
	@echo "Nova developer commands"
	@echo "------------------------"
	@echo "  venv         Create a local virtualenv in $(VENV)"
	@echo "  install      Install runtime dependencies"
	@echo "  install-dev  Install runtime + dev dependencies"
	@echo "  hooks        Install pre-commit hooks (requires git repo)"
	@echo "  run          Start the bot (uses .env)"
	@echo "  test         Run pytest"
	@echo "  lint         Run ruff"
	@echo "  format       Run black + ruff --fix"
	@echo "  typecheck    Run mypy"
	@echo "  check        lint + typecheck + test"
	@echo "  clean        Remove caches and build artifacts"
	@echo "  docker-build Build the Docker image"
	@echo "  docker-run   Run the bot in Docker using .env"

venv:
	$(PY) -m venv $(VENV)

install: venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PIP) install -e .

install-dev: venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt
	$(PIP) install -e ".[dev]"
	@echo "Run 'make hooks' after 'git init' to install pre-commit hooks."

# Optional — only useful once this directory is a git repo.
hooks:
	$(PYV) -m pre_commit install

run:
	$(PYV) -m nova

test:
	$(PYV) -m pytest

lint:
	$(PYV) -m ruff check src tests

format:
	$(PYV) -m ruff check --fix src tests
	$(PYV) -m black src tests

typecheck:
	$(PYV) -m mypy

check: lint typecheck test

clean:
	rm -rf build dist *.egg-info
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

docker-build:
	docker build -t nova-bot:latest .

docker-run:
	docker run --rm -it --env-file .env nova-bot:latest
