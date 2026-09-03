# MetaProject — Implementation Plan

**Reference**: [spec.md](file:///Users/johnfricker/Projects/MetaProject/spec.md) | [intent.md](file:///Users/johnfricker/Projects/MetaProject/intent.md) | [STATE.md](file:///Users/johnfricker/Projects/MetaProject/STATE.md)  
**Status**: Ready for Implementation  
**Runtime**: Python 3.11+ via `uv`  

---

## 1. Overview & Architecture Strategy

`metaproject` is structured as a modular Python package under `src/metaproject/` driven by `typer` for CLI routing, `rich` for formatting, `sqlite-utils` for database management, `questionary` for interactive wizards, and `jinja2` for template expansion.

```
src/metaproject/
├── __init__.py
├── __main__.py          # Python -m metaproject entry
├── cli.py               # Typer app & subcommand registration
├── config.py            # ~/.metaproject/config.json management
├── db.py                # SQLite schema, WAL mode, queries & reconciliation
├── exceptions.py        # Domain-specific error types
├── git.py               # Git pre-flight checks, init, commit helpers
├── learn.py             # Template harvesting engine (learn command)
├── review.py            # Drift & audit engine (review command)
├── scaffold.py          # Output resolver, rollback, file generator (new command)
├── templates.py         # Template discovery, stripping, Jinja2 rendering
├── universe.py          # Workspace scanner, mtime/git resolver & classifier
└── variables.py         # Variable extraction, titlecase, slugify, prompts
```

---

## 2. Implementation Phases & Gate Criteria

```
+--------------------------------------------------------------------------------+
| P0: Foundation & Tooling (uv, pyproject.toml, Makefile, ruff, pytest)           |
+--------------------------------------------------------------------------------+
                                       | [Gate G0: lint & test pass]
                                       v
+--------------------------------------------------------------------------------+
| P1: Configuration Manager, Packaging & Seed Templates                           |
+--------------------------------------------------------------------------------+
                                       | [Gate G1: config & resource tests pass]
                                       v
+--------------------------------------------------------------------------------+
| P2: Template Engine & Variable Resolver                                        |
+--------------------------------------------------------------------------------+
                                       | [Gate G2: template & variable tests pass]
                                       v
+--------------------------------------------------------------------------------+
| P3: Core Project Scaffolding & Git Integration (`new`, `init`/`install`)       |
+--------------------------------------------------------------------------------+
                                       | [Gate G3: end-to-end scaffolding tests]
                                       v
+--------------------------------------------------------------------------------+
| P4: Workspace Cataloger, Classifier & SQLite Store (`universe`)                |
+--------------------------------------------------------------------------------+
                                       | [Gate G4: universe scanning & db tests]
                                       v
+--------------------------------------------------------------------------------+
| P5: Template Drift Auditing (`review`)                                         |
+--------------------------------------------------------------------------------+
                                       | [Gate G5: drift detection tests pass]
                                       v
+--------------------------------------------------------------------------------+
| P6: Template Feedback & Learning Engine (`learn`)                              |
+--------------------------------------------------------------------------------+
                                       | [Gate G6: template learning tests pass]
                                       v
+--------------------------------------------------------------------------------+
| P7: Verification, Documentation & Packaging                                    |
+--------------------------------------------------------------------------------+
                                       | [Gate G7: 100% verification & release]
```

---

### Phase 0 (P0): Foundation & Development Environment

**Objective**: Establish project layout, build configuration, dev toolchain, and baseline testing harness.

* **Tasks**:
  1. Create `pyproject.toml` declaring dependencies:
     - Runtime: `typer>=0.12.0`, `rich>=13.7.0`, `sqlite-utils>=3.36`, `questionary>=2.0.0`, `jinja2>=3.1.0`.
     - Dev/Test: `pytest>=8.0.0`, `pytest-mock>=3.12.0`, `ruff>=0.3.0`.
     - Entry point: `[project.scripts] metaproject = "metaproject.cli:app"`.
     - Package data inclusion for default templates.
  2. Create standard `Makefile` with targets: `help`, `lint`, `format`, `test`, `install`.
  3. Create `.gitignore` ignoring Python virtualenvs, cache, build artifacts, and SQLite databases.
  4. Create `src/metaproject/__init__.py` and `src/metaproject/__main__.py`.
  5. Create `tests/conftest.py` with shared fixtures (`tmp_path`, mock git, isolated runner).
* **Verification Gate G0**:
  - `uv sync` installs dependencies.
  - `make lint` runs `ruff check` and passes.
  - `make test` executes `pytest` and passes with zero failures.

---

### Phase 1 (P1): Configuration Manager & Seed Template Packaging

**Objective**: Implement persistent user configuration (`~/.metaproject/config.json`) and package bundled seed templates.

* **Tasks**:
  1. Author `src/metaproject/exceptions.py`: define `MetaProjectError`, `ConfigError`, `TemplateError`, `CollisionError`, `GitError`.
  2. Author `src/metaproject/config.py`:
     - Load and save `~/.metaproject/config.json`.
     - Schema fields: `version: 1`, `author`, `default_branch`, `project_home`, `templates_dir`, `universe_db`, `auto_git_init`, `default_license`.
     - Precedence resolver: CLI flag > Environment variable > `config.json` > Built-in defaults.
  3. Bundle existing seed templates in `src/metaproject/templates/`:
     - Copy `templates/` seed files into package resources.
     - Add `HANDOFF.template.md` (adapting standard handoff format).
     - Populate empty template files (`README.template.md`, `CLAUDE.template.md`, `.gitignore.template`).
  4. Implement `get_default_templates_dir()` using `importlib.resources`.
* **Verification Gate G1**:
  - Tests verify `config.py` loads default settings when config is missing.
  - Tests verify saving/updating `config.json`.
  - Tests verify bundled templates are discoverable and readable from package resources.

---

### Phase 2 (P2): Template Engine & Variable Resolver

**Objective**: Build robust metadata extraction, string transforms, and safe Jinja2 template rendering.

* **Tasks**:
  1. Author `src/metaproject/variables.py`:
     - Implement `titlecase(name: str) -> str`: split on `[-_ ]`, capitalize words cleanly.
     - Implement `slugify(name: str) -> str`: normalize to lowercase-hyphenated string.
     - Implement `resolve_author(cli_author, config)`: CLI arg > `config.author` > `git config user.name` > `$USER`.
     - Collect standard variables: `ProjectTitle`, `ProjectSlug`, `ProjectDescription`, `Author`, `Date`, `Year`.
     - Interactive variable prompt fallback using `questionary`.
  2. Author `src/metaproject/templates.py`:
     - **Filename stripping**: `<name>.template.<ext>` &rarr; `<name>.<ext>`, `.<name>.template` &rarr; `.<name>`, `<name>.template/` &rarr; `<name>/`.
     - **Whitelisted Placeholder Preprocessor**: Replace `{KnownVar}` with `{{ KnownVar }}` while strictly preserving literal non-whitelisted braces (JSON, CSS, shell `${VAR}`).
     - **Binary Asset Filter**: Detect binary files (images, icons, fonts) via null-byte sniffing and copy verbatim without UTF-8 decoding.
     - **Empty Directory Mirroring**: Ensure empty directories (such as `docs/`) are mirrored or populated with `.gitkeep`.
* **Verification Gate G2**:
  - Unit tests for `titlecase` and `slugify` with edge cases (`my-api_service` &rarr; `My Api Service` / `my-api-service`).
  - Unit tests ensuring templates with literal JSON `{ "key": "value" }` or bash `${VAR}` render without corruption.
  - Unit tests verifying binary file verbatim pass-through.

---

### Phase 3 (P3): Scaffolding Engine & Git Integration (`new`, `init`/`install`)

**Objective**: Implement core scaffolding lifecycle, collision guards, transactional rollback, git repository creation, and initialization wizard.

* **Tasks**:
  1. Author `src/metaproject/git.py`:
     - `verify_git_installed()` and version check ($\ge 2.28$).
     - `preflight_git_identity()`: check `user.name` and `user.email`; fall back to configured author or issue warning.
     - `init_repository(target_dir, branch, commit_message)`: `git init -b <branch>`, `git add .`, `git commit -m "chore: initial scaffold from metaproject"`.
  2. Author `src/metaproject/scaffold.py`:
     - Implement `resolve_output(output, project_name)`:
       - No `--output` &rarr; `./<project-name>`
       - `--output` is an existing directory &rarr; `<output>/<project-name>`
       - `--output` does not exist or ends in `/` &rarr; exact root `<output>`
     - Collision check: target directory is empty or contains only solitary `.git/` and `.DS_Store`; abort unless `--force`.
     - Overwrite semantics: template-colliding files overwritten; non-template files preserved.
     - **Transactional Rollback**: Track all paths created during execution; on unhandled exception before git commit, unwind only created paths without deleting pre-existing files.
  3. Author `src/metaproject/cli.py` commands:
     - `metaproject init [path/to/templates] [project_home]`: wizard, seeds `~/.metaproject/templates`, writes `config.json`, triggers initial `universe` scan. Alias `metaproject install`.
     - `metaproject new <project-name>`: flags `--output`, `--templates`, `--title`, `--description`, `--author`, `--yes`, `--force`, `--dry-run`, `--no-git`.
* **Verification Gate G3**:
  - `CliRunner` tests:
    - Scaffolding a fresh project generates all 8 standard files (`README.md`, `AGENTS.md`, `intent.md`, `STATE.md`, `HANDOFF.md`, `CLAUDE.md`, `.gitignore`, `docs/`).
    - Verifying git repository is initialized with initial commit on branch `main`.
    - Verifying `--dry-run` prints plan without creating disk files.
    - Verifying collision abort when target contains existing files (unless `--force`).
    - Verifying rollback cleans up partial files on simulated error.

---

### Phase 4 (P4): Workspace Cataloger, Classifier & SQLite Persistence (`universe`)

**Objective**: Build fast directory tree scanner, activity classification engine, and SQLite store with reconciliation.

* **Tasks**:
  1. Author `src/metaproject/db.py`:
     - Initialize `universe.db` with table `projects` and indices on `path`, `classification`, `last_modified_ts`, `scan_root`.
     - Execute `PRAGMA journal_mode=WAL;` and `PRAGMA busy_timeout=5000;`.
     - Upsert query using `sqlite-utils` on conflict of `path`.
     - Soft-delete reconciliation query setting `missing_since = CURRENT_TIMESTAMP` for records under `scan_root` not seen in current scan.
  2. Author `src/metaproject/universe.py`:
     - **Scanner**: Traverse directory tree up to `--depth` (default 4), skipping ignored trees (`.git`, `node_modules`, `venv`, `.venv`, `dist`, `build`, `__pycache__`, `.gemini`).
     - **Root Detection**: Recognize project boundaries by presence of `.git/`, `AGENTS.md`, `intent.md`, or package manifests (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `Makefile`).
     - **Metadata Parser**: Extract title, description, SDLC compliance flags (`has_agents_md`, `has_intent_md`, `has_state_md`, `has_handoff_md`, `has_claude_md`, `has_readme_md`).
     - **Last Modified Resolver**:
       - Git repos: check `git log -1 --format=%cI`; if working tree has uncommitted modifications (`git status --porcelain`), use newest file mtime.
       - Non-git: find newest file `mtime`.
     - **Classifier**:
       1. `Archived`: Path top-level or ancestor directory matches `Archive`/`archive`. (Prompts operator in interactive mode; auto-classifies in non-interactive/quiet mode).
       2. `Active Now`: $\le 2\text{ days}$.
       3. `Active Near`: $> 2\text{ days}$ and $\le 7\text{ days}$.
       4. `Active Far`: $> 7\text{ days}$ and $\le 30\text{ days}$.
       5. `Idle`: $> 30\text{ days}$ and $\le 180\text{ days}$.
       6. `Ancient`: $> 180\text{ days}$.
  3. Wire CLI command `metaproject universe [dir]`:
     - Options: `--db`, `--filter`, `--depth`, `--format` (`table`/`json`/`csv`), `--quiet`, `--list`, `--show-missing`.
     - Render formatted `rich` table with colored classification badges.
* **Verification Gate G4**:
  - Tests verify correct project detection and boundary pruning across mock directory trees.
  - Tests verify timestamp resolution and exact classification tier assignment.
  - Tests verify `universe.db` persistence and reconciliation pass for deleted/moved projects.
  - Tests verify `metaproject universe --list` queries existing DB without rescanning disk.

---

### Phase 5 (P5): Template Drift Auditing (`review`)

**Objective**: Detect structural and content drift between existing projects and central templates.

* **Tasks**:
  1. Author `src/metaproject/review.py`:
     - Identify missing template files (e.g. project lacks `HANDOFF.md`, `CLAUDE.md`, or `docs/`).
     - Compare file contents against rendered base templates using `difflib.unified_diff`.
     - Support single project review and multi-project audit (`--all`).
  2. Wire CLI command `metaproject review [project-dir]`:
     - Options: `--all`, `--templates`.
     - Format findings with `rich` panels, summary badges, and actionable recommendations.
* **Verification Gate G5**:
  - Tests verify detection of missing SDLC files in audited projects.
  - Tests verify diff computation between project files and base templates.
  - Tests verify `--all` scans and reports across all project subdirectories.

---

### Phase 6 (P6): Template Feedback & Learning Engine (`learn`)

**Objective**: Inspect projects to harvest custom rules and improvements to feed back into `~/.metaproject/templates/`.

* **Tasks**:
  1. Author `src/metaproject/learn.py`:
     - Inspect project `AGENTS.md`, `.gitignore`, and tooling configurations for additions not in the central templates.
     - Extract candidate additions (e.g. custom agent rules, extra ignore rules).
     - Interactive mode: Prompt operator via `questionary` to confirm exporting candidate additions into `~/.metaproject/templates/`.
     - Non-interactive mode: Output discovered additions in JSON or diff format.
  2. Wire CLI command `metaproject learn [project-dir]`:
     - Options: `--all`, `--templates`.
* **Verification Gate G6**:
  - Tests verify rule extraction from customized project files.
  - Tests verify interactive export updates central template files without data loss.

---

### Phase 7 (P7): Final Verification, Polishing & Documentation

**Objective**: Complete end-to-end integration, performance check, and documentation updates.

* **Tasks**:
  1. Validate full workflow end-to-end:
     - Fresh machine simulation: `metaproject init` seeds environment and catalogs workspace.
     - Project creation: `metaproject new sample-proj` scaffolds project and initializes git.
     - Workspace review: `metaproject universe` lists cataloged projects.
     - Audit & Learn: `metaproject review` and `metaproject learn` run across test projects.
  2. Verify performance: Scaffolding executes in $< 1\text{ second}$.
  3. Ensure code quality: 100% passing tests via `make test`, clean linting via `make lint`.
  4. Update [STATE.md](file:///Users/johnfricker/Projects/MetaProject/STATE.md) to mark all implementation phases complete.
* **Verification Gate G7**:
  - Full test suite passes.
  - CLI commands respond with `--help` and expected behaviors.

---

## 3. Risk Analysis & Mitigation Matrix

| Risk | Impact | Likelihood | Mitigation Strategy |
|---|---|---|---|
| **Accidental file overwrite on existing projects** | High | Low | Enforce strict collision check; require explicit `--force`; never delete non-template files. |
| **Failed scaffold leaves dirty partial directory** | Medium | Medium | Implement transactional creation tracker that unwinds only created files on error. |
| **Git identity unconfigured in environment** | Medium | Medium | Pre-flight check `git config user.email` and `user.name`; fall back to config author or warn gracefully. |
| **Accidental corruption of template braces (JSON, CSS)** | High | Medium | Preprocessor strictly checks against whitelisted variable names before Jinja rendering. |
| **Large directory scan performance degradation** | Medium | Medium | Prune vendor/cache directories at root level; prioritize git commit timestamps over walking disk mtimes. |
| **SQLite database locking under concurrent runs** | Low | Low | Enable WAL mode (`PRAGMA journal_mode=WAL`) and set `busy_timeout=5000`. |
| **Stale projects lingering in universe catalog** | Low | Medium | Execute reconciliation pass after every scan to flag missing projects with `missing_since`. |
