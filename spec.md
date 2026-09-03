# MetaProject — Requirements & Design Specification

**Status**: Draft  
**Reference**: [intent.md](file:///Users/johnfricker/Projects/MetaProject/intent.md)  
**Author**: John (Operator), Antigravity (Agent)  

---

## 1. Executive Summary

`metaproject` is a lightweight, opinionated command-line utility built in Python to automate the creation and maintenance of projects following the agentic software development lifecycle (SDLC) defined in [AGENTS.md](file:///Users/johnfricker/Projects/MetaProject/AGENTS.md). It eliminates repetitive manual scaffolding, enforces consistent project layouts, and establishes a foundation for tracking and evolving templates across the user's workspace.

---

## 2. Goals & Non-Goals

### 2.1 Goals
- **Instant Scaffolding**: Generate a complete, ready-to-use project repository with standard files (`README.md`, `AGENTS.md`, `intent.md`, `STATE.md`, `HANDOFF.md`, `CLAUDE.md`, `.gitignore`, `docs/`) in under a second.
- **Dynamic Variable Substitution**: Automatically inject project metadata (`ProjectTitle`, `ProjectDescription`, `Author`, `Date`, etc.) into template files.
- **Intelligent Defaults**: Source default values seamlessly from local environment (`git config user.name`, current date, directory names). Pre-flight check git identity; fall back to author name from config, or warn and leave files staged without committing.
- **Dual Invocation UX**: Provide an interactive wizard for guided creation alongside non-interactive CLI flags for automation and scriptability.
- **Safety First**: Prevent accidental data loss through strict collision detection, non-destructive defaults, and path-containment checks.
- **Git Integration**: Initialize a clean git repository on branch `main` with an initial commit reflecting the generated template state.
- **Extensible Template Architecture**: Decouple templates from code so templates can be updated without reinstalling the CLI.

### 2.2 Non-Goals (v1)
- Remote template downloading or registry synchronization (e.g., fetching from GitHub/GitLab).
- Multi-language AST-level code manipulation or complex conditional templating engines (e.g. Jinja2 macro systems).
- Full cross-platform OS abstractions outside macOS/Linux POSIX zsh environments.

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
├── pyproject.toml              # Build config & CLI entry point [project.scripts]
├── Makefile                    # Standard make targets (test, lint, install)
├── intent.md                   # Source of truth for feature proposals
├── spec.md                     # This specification
├── STATE.md                    # Process tracking and task checklist
├── templates/                  # Seed template directory
│   ├── .gitignore.template
│   ├── AGENTS.template.md
│   ├── CLAUDE.template.md
│   ├── HANDOFF.template.md
│   ├── README.template.md
│   ├── STATE.template.md
│   ├── intent.template.md
│   └── docs.template/
└── src/
    └── metaproject/
        ├── __init__.py
        ├── __main__.py         # CLI router
        ├── cli.py              # CLI commands & argument parsing
        ├── config.py           # ~/.metaproject configuration manager
        ├── templates.py        # Template discovery, copying, and rendering
        ├── variables.py        # Metadata resolver (git, date, prompt)
        ├── git.py              # Git initialisation helpers
        ├── universe.py         # Workspace scanner, classification & metadata extraction
        ├── db.py               # SQLite schema, connections & upsert queries
        └── exceptions.py       # Domain-specific error types
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
  1. Checks if `~/.metaproject` exists.
  2. Seeds `~/.metaproject/templates/` from `path/to/templates` or bundled package data.
  3. Prompts for author name (defaulting to `git config user.name`), default branch (`main`), and confirms `project_home`.
  4. Writes `~/.metaproject/config.json`.
  5. Initializes `universe.db` with WAL mode and `busy_timeout=5000`.
  6. Executes the initial `universe` scan on `project_home` to build the workspace catalog.

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
  - `--all`: Review all subdirectories of the current working directory.
  - `--templates <path>`: Template directory to compare against (default: `~/.metaproject/templates`).
- **Output**:
  - Missing standard files (e.g. project lacks `HANDOFF.md` or `docs/`).
  - Structural diffs between current project files and the latest template version.
  - Actionable recommendations to update files.

### 5.4 `metaproject learn`
Scans existing projects to find recurring customizations or improvements to incorporate back into the central templates.

- **Usage**:
  ```bash
  metaproject learn [project-dir] [--all] [--templates <path>]
  ```
- **Arguments & Options**:
  - `<project-dir>`: Project directory to learn from (default: current working directory `./`).
  - `--all`: Review all subdirectories of the current working directory.
  - `--templates <path>`: Central template directory to update (default: `~/.metaproject/templates`).
- **Output**:
  - Discovered additions (e.g., custom rules in `AGENTS.md`, extra gitignore rules).
  - Prompts operator to export improvements into `~/.metaproject/templates`.

### 5.5 `metaproject universe`
Scans from the current directory (or a specified root), catalogs all subdirectories, classifies them by activity and archive status, extracts metadata, and persists the catalog into a SQLite database at `~/.metaproject/universe.db`.

- **Usage**:
  ```bash
  metaproject universe [dir] [options]
  ```
- **Arguments & Options**:
  - `[dir]`: Starting scan directory (default: current directory `./` or `project_home` from config).
  - `--db <path>`: SQLite database path (default: `~/.metaproject/universe.db` or config setting).
  - `--filter <classification>`: Filter console output by classification (`Active Now`, `Active Near`, `Active Far`, `Idle`, `Ancient`, `Archived`).
  - `--depth <int>`: Maximum directory traversal depth (default: `4`).
  - `--format [table|json|csv]`: Console output format (default: `table`).
  - `--quiet, -q`: Run silently and refresh the database without printing tables.
  - `--list, -l`: Query and list projects in the database without re-running a full filesystem scan.
  - `--show-missing`: In `--list` mode, display projects previously cataloged that are now missing (`missing_since IS NOT NULL`).

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
- **Environment & Packaging**: Managed with `uv` (`pyproject.toml`)
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

### 9.2 Verification Commands
- `make lint` &rarr; `ruff check` and `ruff format --check`
- `make test` &rarr; `pytest -v tests/`
- `make install` &rarr; `uv pip install -e .` or `uv tool install .`
