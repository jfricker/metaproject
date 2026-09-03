# MetaProject - a CLI tool for creating a new project

**Author**: John. **Status**: Draft.

## Problem
I create new projects on a regular basis and I find myself creating the same files over and over again. 

## Proposed outcome
 CLI tool **metaproject** that creates a new project directory and generate the project boilerplate files based on a collection of templates. The templates are stored in the ./templates directory and the tool can periodically review all projects to find useful changes to make to the templates. The tool can also review existing files and make recommendations to improve/update them based on current templates.

**metaproject init {path/to/templates} project_home**
Sets up the tool for use. It copies the templates from the project home into the users home directory `~/.metaproject/templates/`. It creates the config file in .metaproject and builds the universe.db database. (Note: symantically this might be better named `install`)

**metaproject new {nameofproject} --templates {path/to/templates} --output {path/to/output}**
path/to/templates default is ~/.metaproject/templates
path/to/output default is current directory, creating the directory if it does not exist

The new project directory will be created with the following files:
- README.md
- AGENTS.md
- intent.md
- HANDOFF.md
- STATE.md
- CLAUDE.md
- .gitignore
- docs/

**metaproject review {directory} --templates {path/to/templates}**

**metaproject learn {directory} --templates {path/to/templates}**

**metaproject universe [dir]**
Scans starting at the current directory (or specified root) and catalogs all subdirectories, classifying them by activity recency and archive status (`Active Now`, `Active Near`, `Active Far`, `Idle`, `Ancient`, `Archived`). Records brief description, location, and metadata in a SQLite database at `~/.metaproject/universe.db`.


## Affected users and systems
Only the operator running the CLI tool.

## Scope

### In Scope (v1)
- CLI command to scaffold a project directory by name or into the current working directory.
- Recursive copying of the template directory tree, stripping `.template` extensions.
- Variable substitution for template placeholders (`{ProjectTitle}`, `{ProjectDescription}`, `{Author}`, `{Date}`).
- Automatic defaults derived from the environment (git user, current date, folder name).
- Interactive prompt mode when required parameters are omitted, with non-interactive flag support (`-y` / `--yes`).
- Collision protection (abort if destination directory is not empty unless `--force` is specified).
- `metaproject universe`: cataloging, activity classification, metadata extraction, and SQLite storage (`~/.metaproject/universe.db`).
- `metaproject review` and `metaproject learn` as first class v1 features.

### Out of Scope (v1)
- Remote template fetching (e.g., downloading from GitHub repos).
- Multi-archetype / multi-language scaffolding matrices (keep to the primary project template set first).
- Complex conditional AST transformations.

## Resolved decisions
- Template naming convention: Files ending in `.template` or `.template.<ext>` have `.template` removed upon generation.
- Default author lookup: Query `git config user.name`.
- Runtime/Language preference: Python 3.11+ (managed via `uv`).
- Approved runtime dependencies: `typer`, `rich`, `sqlite-utils`, `questionary`, `jinja2`.
- Approved test/dev tooling: `pytest`, `pytest-mock`, `ruff`, and `typer.testing.CliRunner`.
- Template location: read from a user home directory (`~/.metaproject/templates`), with overrides.
- Automatically run `git init` and create an initial commit.
- `review` and `learn` are first class, v1 features.
- Bundle default templates inside the Python package (using `importlib.resources`) so a fresh installation can self-seed `~/.metaproject/templates` during `init`.
- `git init` will set the default branch to `main`. First commit message will be `chore: initial scaffold from metaproject`.
- Use Jinja2 for variable substitution in templates. 
- Set SQLite PRAGMA journal_mode=WAL and busy_timeout=5000 to prevent database locks.

## Constraints
- CLI tool will only write into the specified directory for the current user.
- Minimal external dependencies for end users running the CLI. Dependencies must be discussed and approved by operator.
- Must cleanly support macOS zsh terminal environments.
