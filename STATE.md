# MetaProject — State

## Process
- [x] 1. Review `intent.md` and explore CLI concept
- [x] 2. Initialise `./STATE.md` from `templates/STATE.template.md`
- [x] 3. Update `intent.md` with open questions on CLI commands, scope, and configuration
- [x] 4. Author comprehensive `spec.md` based on `intent.md`
- [x] 5. Review open questions with operator and subagent; harmonize `intent.md` and `spec.md`
- [x] 6. Author implementation `plan.md` based on `spec.md`
- [x] 7. Implementation execution (P0–P7) complete and verified
- [x] 8. Init existing configuration safeguard and universe summary command complete and verified

## Implementation phases (plan.md §2)
- [x] P0: Foundation & tooling
  - [x] 0.1 Create `pyproject.toml` with approved dependencies and CLI entry point
  - [x] 0.2 Create `Makefile` with `help`, `lint`, `format`, `test`, `install` targets
  - [x] 0.3 Create `.gitignore`
  - [x] 0.4 Create package skeleton `src/metaproject/__init__.py` and `__main__.py`
  - [x] 0.5 Create `tests/conftest.py` and `tests/test_baseline.py`
  - [x] 0.6 Install dependencies and verify Gate G0 (`make lint`, `make test`)
- [x] P1: Configuration manager, packaging & seed templates
  - [x] 1.1 Create `src/metaproject/exceptions.py` with domain error hierarchy
  - [x] 1.2 Create `src/metaproject/config.py` with `Config` schema, load/save, and precedence resolution
  - [x] 1.3 Seed templates in `src/metaproject/templates/` (copying seeds, populating `README`, `CLAUDE`, `.gitignore`, `HANDOFF`)
  - [x] 1.4 Implement `get_default_templates_dir()` via `importlib.resources`
  - [x] 1.5 Unit tests in `tests/test_config.py` and verify Gate G1 (`make lint`, `make test`)
- [x] P2: Template engine & variable resolver
  - [x] 2.1 Implement `variables.py`: `titlecase`, `slugify`, `resolve_author`, standard variable collection
  - [x] 2.2 Implement template filename transformation (`.template` stripping, dotfile renaming, directory stripping)
  - [x] 2.3 Implement whitelisted `{Var}` preprocessor and Jinja2 rendering (preserving literal braces)
  - [x] 2.4 Implement binary file detection and verbatim copy
  - [x] 2.5 Implement empty directory mirroring
  - [x] 2.6 Unit tests in `tests/test_templates.py` and verify Gate G2 (`make lint`, `make test`)
- [x] P3: Core scaffolding & git integration
  - [x] 3.1 Implement `src/metaproject/git.py`: pre-flight checks, repository initialization, initial commit
  - [x] 3.2 Implement `src/metaproject/scaffold.py`: `resolve_output`, empty dir checking, transactional rollback
  - [x] 3.3 Implement `metaproject init` and `install` alias in `src/metaproject/cli.py`
  - [x] 3.4 Implement `metaproject new` command in `src/metaproject/cli.py` with flags and rollback handler
  - [x] 3.5 Author `tests/test_scaffold.py` and verify Gate G3 (`make lint`, `make test`)
- [x] P4: Workspace cataloger, classifier & SQLite persistence
  - [x] 4.1 Implement `src/metaproject/db.py`: SQLite WAL mode, schema, upsert, and reconciliation query
  - [x] 4.2 Implement `src/metaproject/universe.py`: scanner, heuristics, timestamp extraction, classification hierarchy
  - [x] 4.3 Implement `metaproject universe` command in `src/metaproject/cli.py` with table and list modes
  - [x] 4.4 Author `tests/test_universe.py` and verify Gate G4 (`make lint`, `make test`)
- [x] P5: Template drift auditing
  - [x] 5.1 Implement `src/metaproject/review.py`: missing deliverable audit and template diff analysis
  - [x] 5.2 Implement `metaproject review` command in `src/metaproject/cli.py` with `--all` batch audit
  - [x] 5.3 Author `tests/test_review.py` and verify Gate G5 (`make lint`, `make test`)
- [x] P6: Template feedback & learning engine
  - [x] 6.1 Implement `src/metaproject/learn.py`: rule extraction, diff analysis, and template updating
  - [x] 6.2 Implement `metaproject learn` command in `src/metaproject/cli.py` with interactive prompt
  - [x] 6.3 Author `tests/test_learn.py` and verify Gate G6 (`make lint`, `make test`)
- [x] P7: Verification, performance checks & documentation
  - [x] 7.1 Author `tests/test_e2e.py` verifying full SDLC workflow (`init` -> `new` -> `universe` -> `review` -> `learn`)
  - [x] 7.2 Sub-second scaffolding benchmark test
  - [x] 7.3 Run full test suite and verify Gate G7 (`make lint`, `make test`)
- [x] P8: Init safeguard & Universe summary enhancements
  - [x] 8.1 Implement `get_universe_summary` in `src/metaproject/db.py`
  - [x] 8.2 Guard `metaproject init` against overwriting existing `config.json`, displaying config and universe.db status summary
  - [x] 8.3 Implement `metaproject universe summary` subcommand and `--summary` flag in `src/metaproject/cli.py`
  - [x] 8.4 Add unit & CLI integration tests in `tests/test_universe.py` and `tests/test_scaffold.py`
  - [x] 8.5 Update `README.md` and verify Gate G8 (`make lint`, `make test`, `make build`)
  - [x] 8.6 Format `universe summary` output as a clean 2-line status summary
- [x] P9: Version flag & manifest info option
  - [x] 9.1 Add `-v` / `--version` eager callback option in `src/metaproject/cli.py`
  - [x] 9.2 Implement `print_manifest_info()` displaying package metadata, dependencies, license, and entrypoint
  - [x] 9.3 Synchronize `__version__` to `0.1.2` with dynamic package lookup in `src/metaproject/__init__.py`
  - [x] 9.4 Add CLI tests for `-v` and `--version` in `tests/test_baseline.py`
  - [x] 9.5 Verify Gate G9 (`make lint`, `make test`, `make build`)
- [x] P10: Automated heuristic version incrementing script
  - [x] 10.1 Create `scripts/bump_version.py` with semver parsing, git status/diff analysis, and heuristic detection
  - [x] 10.2 Support major-zero policy: downgrade major to minor if major is 0
  - [x] 10.3 Synchronize version updates across `pyproject.toml`, `src/metaproject/__init__.py`, `src/metaproject/cli.py`, `tests/test_baseline.py`, and `README.md`
  - [x] 10.4 Add `make bump-version` target in `Makefile`
  - [x] 10.5 Add unit tests in `tests/test_bump_version.py` and document in `README.md`
  - [x] 10.6 Add `major` command to force major milestone increments zeroing minor and patch (`make bump-major`)
  - [x] 10.7 Add automatic git commit for modified version files indicating Milestone vs Heuristic with summary
  - [x] 10.8 Update `spec.md` with complete development automation and milestone specification
  - [x] 10.9 Verify Gate G10 (`make lint`, `make test`, `make build`)
  - [x] 10.10 Create executable shell wrapper `scripts/bump_version.sh`
  - [x] 10.11 Add automated git tag creation (`vX.Y.Z`) on version bump in `bump_version.sh` / `bump_version.py`
  - [x] 10.12 Add idempotency guard: exit cleanly when git tag matches current version metadata
  - [x] 10.13 Add unit test coverage and integrate with `Makefile` (`package`, `bump-version`, `bump-major`)

## Design invariants (regression guards)
- Non-destructive by default: Never overwrite existing non-empty target directories unless explicit `--force` is provided.
- Safe template rendering: Template expansion must strip `.template` suffix and preserve directory structure.
- Scoped filesystem access: CLI only writes to user-specified target directory or `~/.metaproject/`.
- Non-destructive universe scanning: `universe` performs read-only directory scanning and writes catalog data exclusively to `~/.metaproject/universe.db`.
- Deterministic classification: Hierarchy prioritizes `/Archive/` paths first, then recency thresholds (`Active Now` $\le$ 2d, `Active Near` $\le$ 7d, `Active Far` $\le$ 30d, `Idle` $\le$ 180d, `Ancient` $>$ 180d).
- Pruned directory traversal: Scanner must skip cache and vendor trees (`.git`, `node_modules`, `venv`, `.venv`, `dist`, `__pycache__`).
- Minimal approved dependencies: Any external Python dependencies must be justified and approved by the operator.

## Open items carried into plan.md
- [x] Clarify whether `review` and `learn` commands are in v1 scope: Confirmed first-class v1 features.
- [x] Define exact interactive wizard steps, `project_home`, and config storage for `metaproject init`.
- [x] Finalize operator-approved Python CLI libraries: `typer`, `rich`, `sqlite-utils`, `questionary`, `jinja2`, `pytest`, `pytest-mock`.

## Verified facts (do not re-investigate)
- Python runtime managed via `uv`.
- Target OS is macOS (zsh environment).
- Template directory defaults to `~/.metaproject/templates`.
- Standard SDLC lifecycle requires `AGENTS.md`, `intent.md`, `STATE.md`, `HANDOFF.md`, `README.md`, `CLAUDE.md`, `.gitignore`, and `docs/`.
- Approved runtime dependencies: `typer`, `rich`, `sqlite-utils`, `questionary`, `jinja2`.
- Approved dev/test dependencies: `pytest`, `pytest-mock`, `ruff`, and `typer.testing.CliRunner`.
- Git default branch is `main`; initial commit message is `chore: initial scaffold from metaproject`.
- `metaproject universe [target_dir]` scopes output to `target_dir` (use `--all` to view all cataloged projects across all workspaces).
- Universe scanner directly catalogs `target_dir` itself if `target_dir` is a project root.
