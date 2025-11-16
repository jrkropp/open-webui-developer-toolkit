PYTHON ?= $(shell command -v python3 2>/dev/null || command -v python 2>/dev/null || command -v py 2>/dev/null)

ifeq ($(strip $(PYTHON)),)
$(error Python interpreter not found. Please set PYTHON to a Python 3.10+ executable.)
endif

PIP ?= $(PYTHON) -m pip

.PHONY: install install-dev test lint lint-fix format typecheck build clean ruff-man

install:
	$(PIP) install -e .

install-dev:
	$(PIP) install -e .[dev]

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check src tests

lint-fix:
	$(PYTHON) -m ruff check --fix src tests

format:
	$(PYTHON) -m ruff format src tests

typecheck:
	$(PYTHON) -m mypy --config-file pyproject.toml --package openai_responses_manifold

build:
	$(PYTHON) scripts/build.py

clean:
	rm -rf build dist .pytest_cache .ruff_cache *.egg-info
