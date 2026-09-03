.PHONY: help install lint format test clean

VENV := .venv
PYTHON := $(VENV)/bin/python
RUFF := $(VENV)/bin/ruff
PYTEST := $(VENV)/bin/pytest

help: ## Display this help screen
	@echo "Available Makefile targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install package in editable mode with dev dependencies
	uv pip install -e ".[dev]"

lint: ## Run linter and code formatting checks
	$(RUFF) check src tests
	$(RUFF) format --check src tests

format: ## Format code and auto-fix linter issues
	$(RUFF) format src tests
	$(RUFF) check --fix src tests

test: ## Run test suite via pytest
	$(PYTEST) -v tests

clean: ## Remove build artifacts, caches, and test output
	rm -rf build/ dist/ *.egg-info .pytest_cache .ruff_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +
