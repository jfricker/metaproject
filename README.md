# MetaProject

A CLI tool for scaffolding and managing agentic projects and templates following the AI-native SDLC playbook.

## Features
- **Instant Scaffolding (`metaproject new`)**: Scaffold projects with full SDLC documentation and automatic git initialization.
- **Environment Setup (`metaproject init` / `install`)**: Prepare templates and configure project workspace.
- **Workspace Universe (`metaproject universe`)**: Catalog and classify all projects across subdirectories into a SQLite database.
- **Drift Auditing (`metaproject review`)**: Detect drift between project files and central templates.
- **Template Learning (`metaproject learn`)**: Harvest project additions back into the central templates.
- **Package Manifest (`metaproject -v` / `--version`)**: Inspect package metadata, runtime dependencies, license, and version.

## Installation & Development

Install `metaproject` in editable mode using `uv` or `pip`:

```bash
# Clone the repository
git clone https://github.com/johnfricker/metaproject.git
cd metaproject

# Install in editable mode
make install

# Check version and package manifest
metaproject --version

# Verify installation and run test suite
make test
make lint
```

---

## Tutorial: Setup & Usage

### 1. Initial Setup (`metaproject init` / `install`)

Before scaffolding projects, run `init` (or its alias `install`) to establish your central configuration and seed the standard templates into `~/.metaproject/templates/`:

```bash
# Interactive setup wizard
metaproject init
```

The wizard will prompt for:
- **Default Author Name** (defaults to `git config user.name`)
- **Default Git Branch** (defaults to `main`)
- **Projects Root Directory** (e.g., `~/Projects`)

It automatically initializes your SQLite catalog at `~/.metaproject/universe.db` and indexes existing projects in your workspace.

#### Existing Configuration Protection
If `~/.metaproject/config.json` is already present, running `metaproject init` will not overwrite your settings or re-run the wizard. Instead, it displays your current configuration along with the status summary of your `universe.db` (total projects, active now count, and last run).

To force a re-initialization and overwrite existing configuration and templates, pass `--force`:

```bash
metaproject init --force
```

#### Non-Interactive Setup
To seed templates and configure non-interactively in scripts or CI:

```bash
metaproject init --config-dir ~/.metaproject --project-home ~/Projects --force
```

---

### 2. Scaffolding a New Project (`metaproject new`)

`metaproject new` generates a complete repository with the AI-native SDLC governance files (`README.md`, `AGENTS.md`, `intent.md`, `STATE.md`, `HANDOFF.md`, `CLAUDE.md`, `.gitignore`, `docs/`) and initializes git with an initial commit in under a second.

#### Guided Wizard
```bash
metaproject new my-new-service
```
You will be prompted to confirm or specify the project title, a one-line description, and author.

#### One-Liner / Automation Mode
Pass `--yes` (or `-y`) to accept defaults without prompting:

```bash
metaproject new rover-api \
  --title "Rover Telemetry API" \
  --description "High-throughput telemetry streaming service" \
  --output ~/Projects/rover-api \
  --yes
```

#### Scaffolding into an Existing Directory
If you have already created a directory or ran `git init`:

```bash
mkdir -p my-app && cd my-app
metaproject new . --yes
```
> Note: If the directory contains existing files, add `--force` to proceed. Existing non-template files are preserved.

#### Previewing with Dry Run
To inspect the files and paths that would be generated without writing anything to disk:

```bash
metaproject new sample-app --dry-run
```

---

### 3. Exploring Your Workspace Universe (`metaproject universe`)

The `universe` command scans your workspace trees, catalogs projects, classifies their activity recency, and stores the state in `~/.metaproject/universe.db`.

#### Scan Current Workspace
```bash
# Scan from current directory up to depth 4
metaproject universe

# Scan a specific directory tree
metaproject universe ~/Projects --depth 3
```

Projects are classified according to activity and archive precedence:
- **`Archived`**: Any project in an `Archive/` or `archive/` folder
- **`Active Now`**: Modified within the last 2 days
- **`Active Near`**: Modified within the last 7 days (1 week)
- **`Active Far`**: Modified within the last 30 days (1 month)
- **`Idle`**: Inactive for 1 to 6 months
- **`Ancient`**: Dormant (> 6 months)

#### Universe Status Summary
Inspect summary metrics of your cataloged database without scanning the filesystem:

```bash
# View database path, total projects, active now count, and last run timestamp
metaproject universe summary

# Output summary as JSON
metaproject universe summary --format json
```

#### Fast Listing (Without Re-Scanning Disk)
Query the database instantly without traversing the filesystem:

```bash
metaproject universe --list
```

#### Filtering & Alternative Formats
```bash
# Filter only active projects
metaproject universe --list --filter "Active Now"

# Output catalog as JSON or CSV
metaproject universe --list --format json
metaproject universe --list --format csv
```

---

### 4. Auditing Template Drift (`metaproject review`)

As central templates evolve or projects customize their workflow, `metaproject review` checks compliance against the latest standard deliverables and detects structural drift in shared governance files (like `AGENTS.md`):

```bash
# Review current project
metaproject review

# Audit all projects across subdirectories
metaproject review ~/Projects --all
```

Output displays:
- **Compliance Status**: `PASS` if all standard deliverables exist, or `DRIFT` if missing.
- **Missing Files**: Explicitly flags any missing files (e.g. `HANDOFF.md`, `CLAUDE.md`).
- **Template Drift**: Highlights modifications in governance files against standard templates.
- **Actionable Recommendations**: Clear next steps to bring projects up to date.

---

### 5. Evolving Central Templates (`metaproject learn`)

When you create useful new rules or tooling patterns in an individual project (e.g., in `AGENTS.md`, `.gitignore`, or `Makefile`), `metaproject learn` extracts these additions and prompts you to export them back to your central templates:

```bash
# Inspect current project for candidate improvements
metaproject learn

# Inspect all projects in your workspace
metaproject learn ~/Projects --all

# Automatically export additions without prompting
metaproject learn ~/Projects/rover-api --yes
```

Exported additions are safely appended to your template files in `~/.metaproject/templates/`, making them available for all future projects scaffolded via `metaproject new`.

### Development cycle
Automate semantic version incrementing based on git heuristics or launch milestones:
```bash
# Preview increment decision (dry run)
python3 scripts/bump_version.py --dry-run

# Increment version based on git heuristics and commit version files
make bump-version

# Force a major milestone release (zeroes minor and patch, and commits)
make bump-major # or: python3 scripts/bump_version.py major
```

Install the latest version of the tool globally for running outside the repo:
```bash
python3 -m pip install --index-url https://test.pypi.org/simple/ --upgrade metaproject==0.5.0 --no-cache-dir --extra-index-url https://pypi.org/simple/
```