# AGENTS.md

## Dev environment tips
- Makefile is the primary tool for development and testing. Use `make help` to see available targets.

## Build Commands
- `make install`: Install package in editable mode with development dependencies (`uv pip install -e ".[dev]"`).
- `make build`: Build source distribution and wheel into `dist/` (`uv build --no-build-isolation`).
- `make package`: Run `bump-version` (if needed) and build distributables in `dist/`.
- `make clean`: Remove build artifacts (`dist/`, `build/`, `*.egg-info`), test/lint caches, and `__pycache__` directories.
- `make uninstall`: Uninstall `metaproject` from the active Python environment.

## Testing instructions
- `make test`: Run the complete test suite with verbose output (`pytest -v tests`).
- `make lint`: Run code linter and formatting checks (`ruff check src tests` and `ruff format --check src tests`).
- `make format`: Auto-format source and test files and apply autofixes (`ruff format` and `ruff check --fix`).
- Specific test: Run a single test file or function via `.venv/bin/pytest tests/<test_file>.py -k <test_name> -v`.
- Quality Gate: Always execute `make format && make lint && make test` before committing changes.

## Releases
- **Heuristic Version Bumping**:
  - `make bump-version` or `scripts/bump_version.sh`: Evaluates git diff and file additions to increment semver (New files &rarr; Major/Minor per major-0 policy, New commands &rarr; Minor, Bugfixes &rarr; Patch).
  - Synchronizes `pyproject.toml`, package metadata, fallback versions, baseline tests, and `README.md`.
  - Automatically creates a git commit with summary and creates an annotated git tag (`v<version>`).
- **Idempotency Guard**:
  - If `git tag --points-at HEAD` matches the version in `pyproject.toml`, `scripts/bump_version.sh` exits cleanly with code `0` (`No bump is needed.`), allowing safe re-runs during packaging (`make package`, `make testpypi`, `make pypi`). Use `--force-bump` to override.
- **Milestone Bumps**:
  - `make bump-major` or `scripts/bump_version.sh major`: Forces a major version increment (`(X+1).0.0`), zeroes minor and patch, commits, and tags `v<version>`.
- **Publishing Targets**:
  - `make testpypi`: Cleans, packages, and uploads distribution archives to TestPyPI via `twine`.
  - `make pypi`: Cleans, packages, and uploads distribution archives to production PyPI via `twine`.
  - `make install-testpypi`: Installs/upgrades the latest release from TestPyPI.
---
## Architecture

`metaproject` is an AI-native governance and scaffolding CLI built with Python 3.11+, Typer, and Rich. It is structured into cleanly decoupled functional layers:

```
                                    +-----------------------+
                                    |     metaproject       |
                                    |      CLI Entry        |
                                    +-----------+-----------+
                                                |
      +-------------------+---------------------+-------------------+-------------------+
      |                   |                     |                   |                   |
      v                   v                     v                   v                   v
+-------------------+ +-------------------+ +-------------------+ +-------------------+ +-------------------+
|   init Command    | |    new Command    | |  review Command   | |   learn Command   | | universe Command  |
| (Env & Templates  | | (Project Scaffold | |  (Template Drift  | |(Template Feedback | | (Catalog, Classify|
|      Setup)       | |    & Git Init)    | |    & Auditing)    | |  & Enhancements)  | |  & SQLite Store)  |
+---------+---------+ +---------+---------+ +---------+---------+ +---------+---------+ +---------+---------+
      |                     |                     |                     |                     |
      | (seeds)             v                     | (diffs against)     | (updates)           v
      |           +-------------------+           |                     |           +-------------------+
      |           |  VariableResolver |           |                     |           |  Universe Scanner |
      |           | (Env, Git, Flags) |           |                     |           | (Classifier/Mtime)|
      |           +---------+---------+           |                     |           +---------+---------+
      |                     |                     |                     |                     |
      v                     v                     v                     v                     v
+-------------------+ +-------------------+ +-----------------------------------------+ +-------------------+
| ~/.metaproject/   | |  TemplateEngine   | |         ~/.metaproject/templates/       | |    universe.db    |
|   config.json     | | (Jinja2 & Render) | |            (Template Store)             | |    (SQLite DB)    |
+-------------------+ +---------+---------+ +-----------------------------------------+ +-------------------+
```

### Core Subsystems
1. **CLI Routing & Manifest (`src/metaproject/cli.py`, `__main__.py`)**:
   - Built on `typer` with `rich` console formatting.
   - Registers commands (`init`, `new`, `universe`, `review`, `learn`).
   - Handles eager manifest inspection via `-v` / `--version`.

2. **Configuration & Template Seeding (`src/metaproject/config.py`)**:
   - Manages user settings at `~/.metaproject/config.json`.
   - Bootstraps bundled seed templates from package resources via `importlib.resources`.
   - Safeguards existing configurations during `init` unless `--force` is supplied.

3. **Template Engine & Variable Resolution (`src/metaproject/templates.py`, `variables.py`)**:
   - Resolves template variables from Git config, system clock, CLI flags, or interactive Questionary prompts.
   - Pre-processes Jinja2 variables with whitelist safety (stripping unknown Jinja expressions to prevent syntax collisions in foreign templates).
   - Renders template trees, stripping `.template` extensions and preserving directory structures and permissions.

4. **Universe Scanner & Catalog Database (`src/metaproject/universe.py`, `db.py`)**:
   - Discovers project roots recursively (via Git repos, `.metaproject`, or marker files like `AGENTS.md` / `pyproject.toml`).
   - Evaluates project classification heuristics (`Active Now`, `Active`, `Idle`, `Archived`) based on file modification timestamps and path semantics.
   - Persists project metadata in SQLite (`~/.metaproject/universe.db`) and reconciles missing/deleted projects.
   - Exposes summary metrics via `metaproject universe summary` and `get_universe_summary()`.

5. **Compliance & Drift Detection (`src/metaproject/review.py`)**:
   - Audits projects against active templates in `~/.metaproject/templates/`.
   - Identifies missing governance files and structural drift across workspace repositories.

6. **Template Learning Pipeline (`src/metaproject/learn/`)**:
   - `collect.py`: renders each template with a project's own variables and diffs it against the project's file, so substituted placeholders are not mistaken for novel content.
   - `guard.py`: filters `.gitignore` matches and a hard denylist, redacts credentials, and builds the send manifest before anything leaves the machine.
   - `score.py`: clusters evidence into candidates and ranks them by frequency, recency, and `universe` activity weighting.
   - `store.py`: the proposal ledger (`learn_proposals` / `learn_evidence` / `learn_runs`) — upsert by content hash, provenance, suppression and resurfacing. The only module that touches SQLite.
   - `synth.py`: bundles guarded evidence one bundle per target file, measures the rendered prompt against the context budget and chunks-and-reduces when it overruns, shells out to `claude -p`, and parses the reply as schema-validated structured data. The only module that reaches a model; model output is data, never instruction.
   - Later stages (`apply`, `tui`) land in subsequent phases; see `plan.md`.

7. **Release & Versioning Automation (`scripts/bump_version.sh`, `scripts/bump_version.py`)**:
   - AI-native semantic version incrementing driven by git diff analysis and file additions.
   - Supports operator milestone launches (`bump-major`), idempotency tagging guards, and synchronized updates across metadata, tests, and documentation.
---
## Key Files
- `src/metaproject/cli.py`: Main entry point for CLI commands.
- `src/metaproject/config.py`: Handles configuration and template seeding.
- `src/metaproject/templates.py`: Template rendering engine.
- `src/metaproject/variables.py`: Template variable resolution.
- `src/metaproject/universe.py`: Workspace universe scanning and classification.
- `src/metaproject/db.py`: SQLite database management for the universe.
- `src/metaproject/review.py`: Template drift detection and compliance.
- `src/metaproject/learn/`: Template learning pipeline (`collect`, `guard`, `score`, `store`; further stages per `plan.md`).
- `scripts/bump_version.sh`: AI-native version bumping script.
- `scripts/bump_version.py`: Python helper for version bumping.

## Project Constraints
- Python 3.11+ required.
- Typer for CLI construction.
- Jinja2 for templating.
- Questionary for interactive prompts.
- SQLite for persistent workspace catalog.
- Built-in templates packaged via `importlib.resources`.

## Learnings
- **Build Isolation & Offline Packaging**: `uv build` and `uv pip install` create isolated build environments by default, attempting network lookups for build backends (`hatchling`). In sandboxed or offline environments, always pass `--no-build-isolation` to leverage `.venv` packages.
- **Packaging Idempotency**: Tying `bump-version` directly into `make package` or publishing targets requires an idempotency check against `git tag --points-at HEAD`. If the tag matches `pyproject.toml`, exiting cleanly with code `0` prevents infinite or unintentional version increments on rebuilds.
- **Whitelist-Safe Jinja2 Expansion**: Markdown governance files commonly include curly braces or foreign templating syntax. Whitelist-safe extraction of known keys (`project_name`, `author`, `year`, etc.) ensures unknown Jinja expressions do not trigger render failures during scaffolding.
- **Root Project Traversal**: Scanning workspaces where the root itself is a project (e.g. contains `.git` or `pyproject.toml`) requires cataloging the root while continuing to descend into nested subdirectories (while pruning `.git`, `node_modules`, `.venv`, and `__pycache__`).
- **Selective Commit Staging in Automation**: Automated release scripts must selectively stage only modified metadata files (`pyproject.toml`, `__init__.py`, `cli.py`, baseline tests, `README.md`) rather than using `git add -A` to avoid capturing unrelated working tree modifications.
- **Rich Output Line Constraints**: When CLI commands enforce strict line budgets (e.g. `universe summary` 2-line output), configure Rich prints with `soft_wrap=True` to prevent terminal dimensions from wrapping lines unexpectedly in tests or narrow terminals.

## Process
This process is based on https://claude.com/blog/the-ai-native-sdlc-playbook with modifications. This document adds to the playbook and merges ideas. It doesn't supercede the playbook unless explicitly stated.

### HANDOFF.md
 When work is interrupted before completion, create a HANDOFF.md to capture the state of the work and any other information needed to resume the work or hand it off to another agent at another time.

### STATE.md
 Maintain a running list of all tasks and their status. Update it as tasks are completed. Format the list as a checklist with a box, task number and a task description.

### intent.md
 intent.md is a source of truth for proposed changes to the system. Read it when instructed to and mark it complete after all work is tested and merged.  

### spec.md
 The agent will be instructed to create a design and requirements spec from the intent.md.

### plan.md
 The agent will be instructed by the operated to create an implementation plan based up on the spec.md and any design artifacts. 


