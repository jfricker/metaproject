# MetaProject — Requirements & Design Specification

**Status**: Draft  
**Reference**: [intent.md](file:///Users/johnfricker/Projects/MetaProject/intent.md)  
**Author**: John (Operator), Claude (Agent)  

---

## 1. Executive Summary


---

## 2. Goals & Non-Goals

### 2.1 Goals
-
### 2.2 Non-Goals (v1)

---

## 3. Architecture & System Structure

### 3.1 High-Level Component Diagram

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
                                |
                                v
                      +-------------------+
                      | Target Project /  |
                      |    Filesystem     |
                      +-------------------+
```

### 3.2 Directory & Package Organization

```
metaproject/
├── pyproject.toml              # Build config & CLI entry point (Hatchling backend)
├── Makefile                    # Make targets (test, lint, install, build, bump-version)
├── LICENSE                     # MIT License
├── intent.md                   # Source of truth for feature proposals
├── spec.md                     # This specification
├── STATE.md                    # Process tracking and task checklist
├── scripts/
│   └── bump_version.py         # Heuristic version incrementing script
├── templates/                  # Seed template directory
│   ├── .gitignore.template
│   ├── AGENTS.template.md
│   ├── CLAUDE.template.md
│   ├── HANDOFF.template.md
│   ├── README.template.md
│   ├── STATE.template.md
│   ├── intent.template.md
│   └── docs.template/
├── src/
│   └── metaproject/
│       ├── __init__.py         # Package entry & dynamic __version__
│       ├── __main__.py         # CLI router
│       ├── cli.py              # CLI commands, version option & argument parsing
│       ├── config.py           # ~/.metaproject configuration manager
│       ├── templates.py        # Template discovery, copying, and rendering
│       ├── variables.py        # Metadata resolver (git, date, prompt)
│       ├── git.py              # Git initialisation helpers
│       ├── universe.py         # Workspace scanner, classification & metadata extraction
│       ├── db.py               # SQLite schema, connections, summary & upsert queries
│       ├── review.py           # Drift review engine
│       ├── learn.py            # Template learning & enhancement harvester
│       └── exceptions.py       # Domain-specific error types
└── tests/
    ├── test_baseline.py        # Version & CLI help tests
    ├── test_bump_version.py    # Version bump automation tests
    ├── test_config.py          # Config & template seeding tests
    ├── test_e2e.py             # Full lifecycle and performance tests
    ├── test_learn.py           # Template learning tests
    ├── test_review.py          # Drift review tests
    ├── test_scaffold.py        # Scaffolding & init guard tests
    ├── test_templates.py       # Template engine tests
    └── test_universe.py        # Universe scanning & summary tests
```

---

## 4. User Configuration & Template Storage

### 4.1 Storage Layout (`~/.metaproject`)

`metaproject` maintains a user-level directory at `~/.metaproject`:
- `~/.metaproject/config.json`: Persistent user settings.
- `~/.metaproject/templates/`: Default template repository loaded by `metaproject new`.
- `~/.metaproject/universe.db`: SQLite database storing project catalog, classifications, and metadata.

### 4.2 Configuration Schema (`config.json`)

```json
{
  "author": "John Fricker",
  "default_branch": "main",
  "project_home": "/Users/johnfricker/Projects",
  "templates_dir": "/Users/johnfricker/.metaproject/templates",
  "universe_db": "/Users/johnfricker/.metaproject/universe.db",
  "auto_git_init": true,
  "default_license": "MIT"
}
```

---

## 5. CLI Command Specifications

### 5.1 `metaproject init` (Alias: `metaproject install`)
Sets up the tool for use. Copies templates to the user's home directory `~/.metaproject/templates/`, creates the configuration file, and builds the `universe.db` catalog.

- **Usage**:
  ```bash
  metaproject init [path/to/templates] [project_home] [--config-dir PATH] [--force]
  # Alias:
  metaproject install [path/to/templates] [project_home] [--config-dir PATH] [--force]
  ```
- **Arguments & Options**:
  - `[path/to/templates]`: Optional path to source templates. If omitted, self-seeds using bundled package templates via `importlib.resources`.
  - `[project_home]`: Root workspace directory for scanning projects (default: current working directory `./` or `~/Projects`).
  - `--config-dir <path>`: Override configuration directory (default: `~/.metaproject`).
  - `--force, -f`: Reinitialize configuration and overwrite existing templates.

- **Behavior**:
  1. **Existing Configuration Safeguard**:
     - Checks if `config.json` already exists in the target directory (default `~/.metaproject/config.json`).
     - If found and `--force` is **not** provided, initialization immediately halts without modifying any files.
     - Formats and displays two Rich panels/tables:
       a. Current configuration settings (`author`, `default_branch`, `project_home`, `templates_dir`, `universe_db`, `auto_git_init`, `default_license`).
       b. Current `universe.db` status summary (total projects, active now count, last scan timestamp).
       c. Clear prompt informing the operator that initialization is skipped and `--force` is required to overwrite.
  2. If clean or `--force` specified:
     - Seeds `~/.metaproject/templates/` from `path/to/templates` or bundled package data via `importlib.resources`.
     - Prompts for author name (defaulting to `git config user.name`), default branch (`main`), and confirms `project_home`.
     - Writes `~/.metaproject/config.json`.
     - Initializes `universe.db` with WAL mode and `busy_timeout=5000`.
     - Executes the initial `universe` scan on `project_home` to build the workspace catalog.

### 5.2 `metaproject new`
Scaffolds a new project directory and generates boilerplate files.

- **Usage**:
  ```bash
  metaproject new <project-name> [options]
  ```
- **Arguments & Options**:
  - `<project-name>`: Name of the project. Used for directory name and default title.
  - `--output, -o <path>`: Destination parent directory or exact path (default: current working directory `./`).
  - `--templates, -t <path>`: Custom template directory (default: `~/.metaproject/templates`).
  - `--title <title>`: Human-readable project title (default: title-cased `<project-name>`).
  - `--description, -d <desc>`: One-line project summary.
  - `--author, -a <name>`: Author name (default: from config or `git config user.name`).
  - `--yes, -y`: Non-interactive mode; accepts all default values without prompting.
  - `--force, -f`: Allow scaffolding into an existing, non-empty directory.
  - `--dry-run`: Display all actions and file contents that would be created without writing to disk.
  - `--no-git`: Skip `git init` and initial commit.

- **Scaffolding Lifecycle**:
  ```
  1. Resolve paths: target_dir = resolve_output(output, project_name)
     - Resolution algorithm:
       * No --output provided -> ./<project-name>
       * --output is an existing directory -> <output>/<project-name>
       * --output does not exist or ends in / -> create <output> as the exact project root
  2. Safety check:
     - If target_dir contains non-hidden files and not force -> ABORT
     - Allow target_dir containing solitary .git/ or .DS_Store (e.g. if git init was run beforehand)
  3. Collect variables:
     - ProjectTitle = title or prompt(default=titlecase(project_name))
     - ProjectDescription = description or prompt()
     - Author = author or config.author or git_config("user.name")
     - Date = current_date("YYYY-MM-DD")
     - Year = current_year()
  4. Create target directory (track all created directories for transactional rollback)
  5. Walk template directory:
     - For each directory: mirror into target_dir (preserving empty directories like docs/)
     - For each file:
       a. Strip '.template' from filename (e.g., 'AGENTS.template.md' -> 'AGENTS.md')
       b. Check if file is binary (images/fonts): if binary, copy bytes verbatim
       c. If text: rewrite only whitelisted {VarName} placeholders, render Jinja2, write to target
  6. Git initialization (if not --no-git):
     a. Pre-flight check git identity (user.name and user.email); fall back to author from config or warn
     b. Execute: git init -b <default_branch> (with fallback to git init && git checkout -b)
     c. Execute: git add .
     d. Execute: git commit -m "chore: initial scaffold from metaproject"
  7. Print success summary with next steps.
  ```

### 5.3 `metaproject review`
Analyzes an existing project against current templates to identify drift or missing files.

- **Usage**:
  ```bash
  metaproject review [project-dir] [--all] [--templates <path>]
  ```
- **Arguments & Options**:
  - `<project-dir>`: Project directory to review (default: current working directory `./`).
  - `--all`: Review all subdirectories of the target directory. When `--all` is specified, traversal continues descending into subdirectories even if the root itself is a project root.
  - `--templates <path>`: Template directory to compare against (default: `~/.metaproject/templates`).
- **Output**:
  - Missing standard files (e.g. project lacks `HANDOFF.md` or `docs/`).
  - Structural diffs between current project files and the latest template version.
  - Actionable recommendations to update files.

### 5.4 `metaproject learn`
Scans existing projects to find recurring customizations or improvements to incorporate back into the central templates.

- **Usage**:
  ```bash
  metaproject learn [project-dir] [--all] [--templates <path>] [--yes]
  ```
- **Arguments & Options**:
  - `<project-dir>`: Project directory to learn from (default: current working directory `./`).
  - `--all`: Review all subdirectories of the target directory. When `--all` is specified, traversal continues descending into subdirectories even if the root itself is a project root.
  - `--templates <path>`: Central template directory to update (default: `~/.metaproject/templates`).
  - `--yes, -y`: Automatically export enhancements without interactive confirmation prompts.
- **Output**:
  - Discovered additions (e.g., custom rules in `AGENTS.md`, extra gitignore rules).
  - Prompts operator to export improvements into `~/.metaproject/templates`.

### 5.5 `metaproject universe` & `universe summary`
Scans from the current directory (or a specified root), catalogs all subdirectories, classifies them by activity and archive status, extracts metadata, and persists the catalog into a SQLite database at `~/.metaproject/universe.db`.

- **Usage**:
  ```bash
  # Filesystem scan and catalog refresh
  metaproject universe [dir] [options]

  # Instant status summary of cataloged universe
  metaproject universe summary [--db PATH] [--format table|json|csv]
  metaproject universe --summary [--db PATH] [--format table|json|csv]
  ```
- **Arguments & Options**:
  - `[dir]`: Starting scan directory or `"summary"` subcommand (default: current directory `./` or `project_home` from config).
  - `--db <path>`: SQLite database path (default: `~/.metaproject/universe.db` or config setting).
  - `--summary, -s`: Display a concise 2-line status summary of `universe.db` without scanning the filesystem.
  - `--filter <classification>`: Filter console output by classification (`Active Now`, `Active Near`, `Active Far`, `Idle`, `Ancient`, `Archived`).
  - `--depth <int>`: Maximum directory traversal depth (default: `4`).
  - `--format [table|json|csv]`: Console output format (default: `table`).
  - `--quiet, -q`: Run silently and refresh the database without printing tables.
  - `--list, -l`: Query and list projects in the database without re-running a full filesystem scan.
  - `--show-missing`: In `--list` mode, display projects previously cataloged that are now missing (`missing_since IS NOT NULL`).
  - `--all, -a`: In `--list` mode, show all cataloged projects across all workspaces rather than scoping to current target directory.

- **Status Summary Output (`metaproject universe summary`)**:
  When `summary` is requested, the command bypasses filesystem scanning and queries `universe.db` (safely handling missing database files with zero counts). In default mode, it renders a clean, non-wrapping 2-line summary:
  ```text
  Universe DB status: <total_projects> projects (<active_now> active now)
  Last update to the db: <last_run_timestamp>
  ```
  When `--format json` or `--format csv` is passed, the output emits structured records including `database`, `total_projects`, `active_now`, `last_run`, and `missing_projects`.

- **Classification Rules & Precedence**:
  Every discovered project is classified into exactly one category based on location and recency of last modification:
  
  | Classification | Rule / Condition | Description |
  |---|---|---|
  | **Archived** | Path or parent directory named `Archive` or `archive` | Inactive projects explicitly moved to archive locations. In interactive mode, prompts operator to confirm; in non-interactive/quiet mode, classifies automatically. |
  | **Active Now** | Last modified $\le$ 2 days ago | Actively in development right now |
  | **Active Near** | 2 days $<$ Last modified $\le$ 7 days (1 week) ago | Touched within the past week |
  | **Active Far** | 7 days $<$ Last modified $\le$ 30 days (1 month) ago | Touched within the past month |
  | **Idle** | 30 days $<$ Last modified $\le$ 180 days (6 months) ago | Inactive for 1 to 6 months |
  | **Ancient** | Last modified $>$ 180 days (6 months) ago | Dormant / legacy projects |

  *Precedence Rule*: If a project top-level or ancestor directory contains `/Archive/` or `/archive/`, it is classified as `Archived` regardless of timestamp.

- **Project Discovery & Boundary Heuristics**:
  - Traversal skips vendor and cache folders: `.git`, `node_modules`, `venv`, `.venv`, `dist`, `build`, `__pycache__`, `.gemini`, `.cargo`.
  - A directory is cataloged as a project root if it contains any of:
    1. `.git/` directory
    2. `AGENTS.md` or `intent.md`
    3. Standard project manifests (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `Makefile`)
  - Once a directory is classified as a project root, the scanner does not treat internal subfolders as separate projects unless they contain an independent nested git repository.

- **Metadata Extraction**:
  - **Title**: Extracted from `README.md` (first `# Heading`), `intent.md`, or title-cased folder name.
  - **Description**: Extracted from `intent.md` (`## Proposed outcome` or problem statement), `README.md` (lead paragraph under main header), or package manifest `description` field.
  - **Last Modified Timestamp**:
    - For Git repositories: `git -C <dir> log -1 --format=%cI` (commit timestamp) if clean; if uncommitted modifications exist (`git status --porcelain` is non-empty), check the newest mtime of working tree files.
    - For non-git directories: Maximum `os.path.getmtime` among non-ignored files within the project root.
  - **SDLC Compliance Indicators**: Flags recording presence of `AGENTS.md`, `intent.md`, `STATE.md`, `HANDOFF.md`, `CLAUDE.md`, and `README.md`.

- **SQLite Persistence Schema & Pruning Reconciliation (`~/.metaproject/universe.db`)**:
  ```sql
  CREATE TABLE IF NOT EXISTS projects (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      path TEXT UNIQUE NOT NULL,
      relative_path TEXT NOT NULL,
      title TEXT,
      description TEXT,
      last_modified TEXT NOT NULL,
      last_modified_ts REAL NOT NULL,
      classification TEXT NOT NULL,
      is_git INTEGER NOT NULL DEFAULT 0,
      git_branch TEXT,
      has_agents_md INTEGER NOT NULL DEFAULT 0,
      has_intent_md INTEGER NOT NULL DEFAULT 0,
      has_state_md INTEGER NOT NULL DEFAULT 0,
      has_handoff_md INTEGER NOT NULL DEFAULT 0,
      has_readme_md INTEGER NOT NULL DEFAULT 0,
      scanned_at TEXT NOT NULL,
      scan_root TEXT NOT NULL,
      missing_since TEXT
  );

  CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_path ON projects(path);
  CREATE INDEX IF NOT EXISTS idx_projects_classification ON projects(classification);
  CREATE INDEX IF NOT EXISTS idx_projects_last_modified_ts ON projects(last_modified_ts);
  CREATE INDEX IF NOT EXISTS idx_projects_scan_root ON projects(scan_root);
  ```

  - **Upsert & Reconciliation Lifecycle**:
    1. During scan: Discovered projects are upserted into `projects` with `scanned_at = CURRENT_TIMESTAMP` and `missing_since = NULL`.
    2. Post-scan reconciliation: Mark projects under `scan_root` that were deleted or moved:
       ```sql
       UPDATE projects
       SET missing_since = CURRENT_TIMESTAMP
       WHERE scan_root = ? AND scanned_at < ? AND missing_since IS NULL;
       ```

### 5.6 Global Version & Package Manifest (`metaproject -v` / `--version`)
Inspects and outputs comprehensive package metadata, dependencies, and configuration.

- **Usage**:
  ```bash
  metaproject --version
  metaproject -v
  ```
- **Behavior**:
  - Implemented as an eager Typer callback (`is_eager=True`) executed before command routing.
  - Dynamically extracts package metadata using `importlib.metadata`, falling back to static constants if running from source in an uninstalled state.
  - Renders a Rich table containing:
    - **Name**: `metaproject`
    - **Version**: Current semantic version (e.g. `0.1.2`)
    - **Summary**: Package summary from metadata
    - **Author**: Author name from metadata
    - **License**: Package license identifier (e.g. `MIT`)
    - **Requires Python**: Python compatibility constraint (e.g. `>=3.11`)
    - **Dependencies**: Core runtime dependencies (filtered to omit optional dev extras)
    - **CLI Entrypoint**: `metaproject = metaproject.cli:app`

---

## 6. Template Engine Specification

### 6.1 Filename Transformation Rules
- Files with pattern `<name>.template.<ext>` &rarr; `<name>.<ext>`  
  *(Example: `AGENTS.template.md` &rarr; `AGENTS.md`)*
- Files with pattern `.<name>.template` &rarr; `.<name>`  
  *(Example: `.gitignore.template` &rarr; `.gitignore`)*
- Directories with pattern `<name>.template` &rarr; `<name>`  
  *(Example: `docs.template/` &rarr; `docs/`)*

### 6.2 Variable Substitution & Template Engine (Jinja2)
Templates are processed using Jinja2. To support existing templates while allowing future conditional logic, the engine supports:
1. **Jinja2 Expressions**: `{{ ProjectTitle }}`, `{{ Author }}`, `{{ Date }}`.
2. **Backward-Compatible Placeholders**: `{ProjectTitle}`, `{ProjectDescription}`, etc. (converted during pre-processing for whitelisted variables only).
3. **Conditionals & Blocks**: `{% if has_git %}...{% endif %}`.

| Placeholder | Resolution Source | Fallback Value |
|---|---|---|
| `{{ ProjectTitle }}` / `{ProjectTitle}` | `--title` flag or interactive prompt | Title-cased project name |
| `{{ ProjectSlug }}` / `{ProjectSlug}` | Project directory name | Normalized lower-hyphen string |
| `{{ ProjectDescription }}` / `{ProjectDescription}` | `--description` flag or prompt | Empty or prompt text |
| `{{ Author }}` / `{Author}` | `--author`, `config.json`, or `git config user.name` | System user `$USER` |
| `{{ Date }}` / `{Date}` | Current local date (`YYYY-MM-DD`) | ISO date |
| `{{ Year }}` / `{Year}` | Current 4-digit year | Current year |

### 6.3 Missing Placeholders & Undefined Variables
- If running interactively, prompt the user for any undefined required variables.
- If running non-interactively (`--yes`), undefined variables render as empty strings or retain the placeholder (configurable, default: retain).

---

## 7. Safety, Permissions, & Invariants

1. **Non-destructive Overwrite Guard**:
   - `metaproject` must never write files into a non-empty directory without `--force`.
   - Even with `--force`, existing files not present in the template are never deleted; colliding files are explicitly overwritten.
   - **Empty Directory Definition**: A directory containing no non-hidden files, allowing a solitary `.git/` directory and `.DS_Store`.
   - **Transactional Rollback**: On a failed scaffold, only delete paths created during *this* run; never `rmtree` an existing pre-created directory.
2. **Filesystem Confinement**:
   - The tool will only write to the resolved target directory or `~/.metaproject/`.
   - Prevent path traversal attacks in project names (e.g., `../../etc`).
3. **Fail-Safe Rollback**:
   - If an error occurs during template rendering before git initialization, prompt or cleanup partial generation to avoid dirty partial states.
4. **Template Walker & Variable Whitelist Guard**:
   - Only rewrite known whitelisted variables (`ProjectTitle`, `Author`, `Date`, etc.), leaving all other curly braces untouched.
   - Template walker must sniff or filter binary files (images, icons) to copy verbatim rather than decoding as UTF-8.
   - Ensure the template engine mirrors empty directories like `docs/` (or place `.gitkeep` inside `docs.template/`).

---

## 8. Technology Stack & Dependencies

- **Language & Runtime**: Python 3.11+
- **Build Backend**: `hatchling` (`[build-system]` configured with `build-backend = "hatchling.build"`)
- **Package Manager**: Managed with `uv` (`pyproject.toml`)
- **License**: MIT (`LICENSE` file distributed with package)
- **Approved Runtime Dependencies**:
  - `typer>=0.12.0`: Modern CLI declaration, type validation, subcommands, and shell autocompletion.
  - `rich>=13.7.0`: Terminal styling, status spinners, colored tables, and badges for project classifications.
  - `sqlite-utils>=3.36`: High-level SQLite interface with automatic schema handling and atomic upsert operations for `universe.db`.
  - `questionary>=2.0.0`: Interactive terminal prompts and arrow-key selection menus for the `init` wizard and variable prompts.
  - `jinja2>=3.1.0`: Flexible, industry-standard template rendering with variables and conditional sections.
- **Approved Development & Test Dependencies**:
  - `pytest>=8.0.0`: Unit and integration test runner.
  - `pytest-mock>=3.12.0`: Mocking fixtures for environment variables, git interactions, and filesystem tests.
  - `ruff>=0.3.0`: High-speed linter and code formatter.
  - `editables>=0.3`: Editable installation support for local development under Hatchling.
  - `hatch`: Project building and environment management.
  - `typer.testing.CliRunner`: In-memory isolated CLI execution testing.

---

## 9. Verification & Testing Plan

### 9.1 Automated Tests (`pytest`)
1. **Template Transformation Unit Tests**:
   - Filename renaming logic (`.template` stripping).
   - Jinja2 and `{Var}` placeholder substitution across single and multiline files.
   - Handling of special characters, missing keys, and empty templates.
2. **Variable Resolution Tests**:
   - Git user detection mocking.
   - CLI flag precedence over config values.
   - Interactive prompt fallbacks (`questionary` mocks).
3. **End-to-End CLI Scaffolding Tests (`CliRunner`)**:
   - Running `metaproject new my-test-project` into a `tmp_path`.
   - Verifying all target files (`README.md`, `AGENTS.md`, `intent.md`, `STATE.md`, `HANDOFF.md`, `CLAUDE.md`, `.gitignore`, `docs/`) exist and contain substituted content.
   - Verifying `git init` was executed and initial commit exists.
   - Testing collision abort when target directory contains files.
   - Testing `--dry-run` flag emits plan without creating filesystem entities.
4. **Universe Catalog & Classification Tests**:
   - Discovering project directories across mock directory trees with depth limits.
   - Correct classification into `Archived`, `Active Now`, `Active Near`, `Active Far`, `Idle`, and `Ancient` using mocked timestamps.
   - Extracting titles and descriptions from `README.md` and `intent.md`.
   - SQLite table schema creation, `sqlite-utils` upsert on conflict, and query filtering.
   - `metaproject universe summary` 2-line concise status output verification.
5. **Version Flag & Manifest Tests (`tests/test_baseline.py`)**:
   - Verifying `-v` and `--version` options render complete package manifest information.
6. **Version Bump Automation Tests (`tests/test_bump_version.py`)**:
   - Semver parsing, next version arithmetic, major-zero downgrade policy, diff command detection, and synchronized file updates.

### 9.2 Verification Commands
- `make lint` &rarr; `ruff check` and `ruff format --check`
- `make test` &rarr; `pytest -v tests/`
- `make build` &rarr; `uv build --no-build-isolation` (generates sdist and wheel)
- `make bump-version` &rarr; `python3 scripts/bump_version.py`
- `make install` &rarr; `uv pip install -e .`

---

## 10. Development Automation & Version Management

### 10.1 Heuristic Semantic Version Incrementing & Milestones (`scripts/bump_version.py`)
To automate release versioning following AI-native development practices, `metaproject` includes an intelligent semantic version incrementing script at `scripts/bump_version.py`, accessible via `make bump-version` or `make bump-major`.

#### 10.1.1 Decision Rules & Heuristics
1. **Operator Milestone Command (`major`)**:
   - Explicitly forces a **major version increment** (`(X+1).0.0`), zeroing out both minor and patch numbers.
   - Used by the operator to mark significant project milestones.
   - **Bypasses the major version 0 policy** (e.g. increments `0.1.2` directly to `1.0.0`).
2. **Heuristic Major Version Increment (`X+1.0.0`)**:
   - Automatically triggered when **new files have been added** to the repository (either untracked or staged new files, excluding cache and build artifacts).
3. **Heuristic Minor Version Increment (`X.Y+1.0`)**:
   - Triggered when existing files have been changed and **a new CLI command or feature is added** (e.g. `@app.command`, `@*.command`, `def *_cmd`, or commit messages marked with `feat:`).
4. **Heuristic Patch Version Increment (`X.Y.Z+1`)**:
   - Triggered when changes are **only bug fixes or maintenance updates** (e.g. `fix:`, parameter adjustments, refactoring without new commands).
5. **Major Version 0 Policy (Heuristic Mode)**:
   - **If the current major version is 0 (`0.Y.Z`), heuristic evaluation only increments minor or patch numbers.**
   - Any heuristic decision that would otherwise trigger a major increment is automatically **downgraded to a minor increment** (`0.Y+1.0`).

#### 10.1.2 Target File Synchronization
When a version increment is applied, the script automatically updates all synchronized version strings across the project:
- `pyproject.toml`: `version = "X.Y.Z"`
- `src/metaproject/__init__.py`: fallback `__version__ = "X.Y.Z"`
- `src/metaproject/cli.py`: `get_manifest_info()` fallback `"version": "X.Y.Z"`
- `tests/test_baseline.py`: `assert metaproject.__version__ == "X.Y.Z"` and output assertion
- `README.md`: `metaproject==X.Y.Z` in installation instructions

#### 10.1.3 Automated Git Commit & Tagging
At the end of a successful non-dry-run execution, the script:
1. Stages **only** the modified version files (`git add <files>`).
2. Creates a git commit with a formatted message indicating bump category (`Milestone` or `Heuristic`) and decision summary:
   ```text
   chore(release): bump version to <new_version> [<Category>]

   <Category> bump: <old_version> -> <new_version>

   Summary: <decision_explanation>
   ```
3. Creates an annotated git tag for the release (`v<new_version>`):
   ```bash
   git tag -a v<new_version> -m "Release v<new_version>"
   ```

#### 10.1.4 Idempotency Guard (Tag & Metadata Match)
When `bump_version.sh` runs (e.g. invoked via `make package`), it checks if git tag at `HEAD` matches the current version in `pyproject.toml`. If the tag matches:
- The script exits cleanly with return code 0 and logs:
  ```text
  Version metadata (<version>) matches current git tag (v<version>). No bump is needed.
  ```
- This prevents duplicate version bumps during packaging workflows (`make package`, `make testpypi`, `make pypi`).

#### 10.1.5 CLI Interface (`scripts/bump_version.sh` / `scripts/bump_version.py`)
- `scripts/bump_version.sh [major|heuristic]`: Shell executable wrapper invoking `bump_version.py`.
- `python3 scripts/bump_version.py [major|heuristic]`: Positional action (`major` launches a milestone; default is `heuristic`).
- `--major`: Flag alias to force a major milestone bump.
- `--dry-run`: Evaluate git status and preview the decided version increment and planned commit without modifying any files, committing, or tagging.
- `--force {major,minor,patch}`: Override heuristic detection with an explicit bump type.
- `--force-bump`: Force a version increment even if the git tag on HEAD matches current version metadata.
- `--no-commit`: Skip creating git commit and tag after updating files.
- `--current`: Print the active package version and exit.

