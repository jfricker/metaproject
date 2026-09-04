.PHONY: help check test lint
help:
	@grep -E '^[a-z-]+:' Makefile
check: lint test
test:
	pytest -v tests/
lint:
	ruff check .
