.PHONY: help install lint format test clean build package testpypi pypi install-testpypi uninstall bump-version bump-major

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

build: ## Build source distribution and wheel
	uv build --no-build-isolation

package: bump-version build ## Create package archive for distribution
	@echo "Package created successfully. See dist/ directory."

testpypi: clean package ## Publish package to TestPyPI
	python3 -m twine upload --repository testpypi dist/*

pypi: clean package ## Publish package to PyPI
	python3 -m twine upload dist/*

install-testpypi: ## Install the latest version of the tool from TestPyPI
	python3 -m pip install --upgrade \
	--no-cache-dir \
	--index-url https://test.pypi.org/simple/ \
	--extra-index-url https://pypi.org/simple/ \
	metaproject

uninstall: ## Uninstall the tool from the current Python environment
	python3 -m pip uninstall -y metaproject

bump-version: ## Increment project version based on git heuristics
	scripts/bump_version.sh

bump-major: ## Force major milestone version increment (zeroes minor and patch)
	scripts/bump_version.sh major