# Handoff: MetaProject

**Date**: 2026-09-02  
**Author**: Claude Code  
**Status**: draft  

---

## Executive Summary

## Test & Code Quality Status

---

## Project Structure

```
metaproject/
├── Makefile
├── pyproject.toml
├── README.md
├── AGENTS.md
├── intent.md
├── spec.md
├── plan.md
├── STATE.md
├── HANDOFF.md
├── templates/                  # Seed template directory
│   ├── .gitignore.template
│   ├── AGENTS.template.md
│   ├── CLAUDE.template.md
│   ├── HANDOFF.template.md
│   ├── README.template.md
│   ├── STATE.template.md
│   ├── intent.template.md
│   └── docs.template/
│       └── .gitkeep
├── src/
│   └── metaproject/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py              # Top-level commands (init, install, new, universe, review, learn)
│       ├── config.py           # ~/.metaproject configuration manager
│       ├── db.py               # SQLite WAL mode schema, upsert, and reconciliation
│       ├── exceptions.py       # Domain error hierarchy
│       ├── git.py              # Git initialisation and identity pre-flight
│       ├── learn.py            # Template harvesting engine
│       ├── review.py           # Template drift & compliance audit engine
│       ├── scaffold.py         # Path resolution, empty check, transactional rollback
│       ├── templates.py        # Stripping, whitelisted token preprocessor, Jinja2 engine
│       ├── universe.py         # Workspace scanner, activity classifier, metadata extractor
│       ├── variables.py        # String transforms (titlecase, slugify), author resolution
│       └── templates/          # Bundled package templates
└── tests/
    ├── conftest.py
    ├── test_baseline.py
    ├── test_config.py
    ├── test_e2e.py
    ├── test_learn.py
    ├── test_review.py
    ├── test_scaffold.py
    ├── test_templates.py
    └── test_universe.py
```

---

## Primary Dev Commands
- `make help`: Display targets
- `make test`: Run pytest test suite
- `make lint`: Run ruff lint and format check
- `make format`: Auto-format code
- `make install`: Install in editable mode
