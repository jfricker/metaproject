# MetaProject

A CLI tool for scaffolding and managing agentic projects and templates following the AI-native SDLC playbook.

## Features
- **Instant Scaffolding (`metaproject new`)**: Scaffold projects with full SDLC documentation and automatic git initialization.
- **Environment Setup (`metaproject init` / `install`)**: Prepare templates and configure project workspace.
- **Workspace Universe (`metaproject universe`)**: Catalog and classify all projects across subdirectories into a SQLite database.
- **Drift Auditing (`metaproject review`)**: Detect drift between project files and central templates.
- **Template Learning (`metaproject learn`)**: Observe drift across many projects, synthesize corroborated template proposals, and apply them only after review.
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

`learn` is a corroborated-proposal pipeline. It watches how your projects have *diverged*
from their templates, asks a model to generalize what many of them agree on, records the
result as a ranked, durable proposal with full provenance, and writes into a template only
after you have reviewed the diff.

The distinction that matters: **a scan never mutates a template.** Scanning and applying
are separate acts, and only the accept step writes.

#### The pipeline

| Stage | Who decides | What happens |
|---|---|---|
| 1. Collect | Code | Each template is rendered *with that project's own variables*, then diffed against the project's real file. Because the placeholders are substituted first, your project name is not mistaken for a novel contribution. |
| 2. Guard | Code | `.gitignore` matches and a hard denylist are dropped; credential-shaped and high-entropy strings are redacted; you are shown a manifest of exactly what would leave the machine, and confirm it once per session. |
| 3. Synthesize | Model | One `claude -p` call per target file, carrying every project's redacted diff for that file. Oversized bundles are chunked and reduced. |
| 4. Record | Code | Proposals and per-project evidence land in `~/.metaproject/universe.db`. |
| 5. Review | You | The acceptance TUI, or the queue subcommands. |
| 6. Apply | Code | The template is patched under the named section and committed. |

Ranking is corroboration: a change several recently-active projects made independently
outranks one project's idea. A single-project candidate still surfaces — it just sorts
lower. Projects are weighted by their `universe` activity class, so an `Ancient` or
`Archived` project counts fractionally.

#### Default mode: scan, then review

```bash
# Scan the current directory, then review the queue in the acceptance TUI
metaproject learn

# Scan a specific workspace root
metaproject learn ~/Projects

# Scan everything under your configured projects home, no prompts, print the queue table
metaproject learn --all --yes --no-tui
```

Before anything is sent, `learn` prints the send manifest — every project and file whose
redacted diff would leave the machine, its size in bytes, and every path that was withheld
with the reason — and waits for confirmation. `--yes` skips that prompt for
non-interactive use.

#### Scanning without reviewing

```bash
metaproject learn scan ~/Projects --all --depth 3
metaproject learn scan ~/Projects --since 30      # only projects changed in the last 30 days
metaproject learn scan ~/Projects --since 2026-01-01
metaproject learn scan --model claude-sonnet-4-5  # passed through to `claude`
```

`learn scan` runs stages 1–4 and stops. It never opens the TUI and never touches a
template — after a scan the template store is byte-identical and its git worktree clean.

#### The acceptance TUI

```bash
metaproject learn review                     # review the existing queue, no scan
metaproject learn review --target AGENTS.md
metaproject learn review --min-score 2.0
```

Candidates loop within a template, highest score first, then advance to the next template.

| Key | Action | Effect |
|---|---|---|
| `a` | Accept | Write into the template, commit, mark applied, advance. |
| `e` | Edit | Open the proposed body in `$EDITOR`; saving applies your edited text. |
| `d` | Discard | Reject and suppress by content hash. |
| `s` | Skip | Leave pending; it reappears next review. |
| `u` | Toggle view | Switch between side-by-side and unified diff. |
| `p` | Provenance | Expand the contributing projects with absolute paths. |
| `q` | Quit | Exit; everything already actioned is saved. |

Nothing is buffered — each keystroke writes through to the ledger immediately, so a
session can be abandoned and resumed, or finished from the CLI, without loss.

The TUI degrades on its own: without a TTY, with `--no-tui`, or under `TERM=dumb` it
prints the `list` table and exits zero, so scripted and CI use needs no special flag. A
terminal too narrow for side-by-side falls back to the unified diff. An empty queue does
not open the TUI at all.

#### The queue from the CLI

The subcommands and the TUI are two interfaces to one queue, not two pipelines.

```bash
metaproject learn list                       # id, target file, title, evidence count, score
metaproject learn list --status applied
metaproject learn list --status all --verbose

metaproject learn show 12                    # rationale, proposed body, contributing project paths

metaproject learn apply 12                   # review the diff, write, commit
metaproject learn apply --all --yes
metaproject learn edit 12                    # edit in $EDITOR, then apply
metaproject learn reject 12
metaproject learn reject 12 --forget         # clear the suppression instead
```

`--templates <path>` is accepted on every subcommand (default `~/.metaproject/templates`).

#### Rejection is "not yet", not "never"

A discarded proposal is suppressed by a content hash derived from its *evidence*, not from
the model's wording — so re-scanning does not resurrect it just because the model phrased
it differently this time. It resurfaces only when its evidence score later exceeds the
score at rejection time by `learn.resurface_factor` (default `2.0`) — that is, when
materially more projects have since agreed. `learn reject --forget` clears the record
entirely.

#### Safety properties

- **A scan never writes.** The module that runs stages 1–4 has no reference to the module
  that writes templates. This is structural, not a convention.
- **You approve the egress.** Only rendered *diffs* leave the machine, never whole files,
  and only after `.gitignore` filtering, denylisting, redaction, and your confirmation of
  the manifest.
- **Model output is data, never instruction.** Replies are parsed against a fixed schema;
  unknown keys are dropped, unparseable output is discarded rather than salvaged, and a
  proposal body becomes template text only — it is never executed and cannot change what
  the tool does. Project content quoted into a prompt cannot escape its evidence block.
- **Provenance is verified, not claimed.** The evidence lines a proposal cites are matched
  back against what was actually collected; unmatched claims are dropped, and a proposal
  citing no real evidence is discarded.
- **The template store is git-backed.** `metaproject init` initializes it as a repository.
  Each accept is exactly one commit, staging exactly one file, naming the proposal id and
  its contributing projects — so reverting one commit undoes exactly one decision. Accepts
  are never batched, and `apply` refuses to run against a dirty worktree.
- **Placement is exact or admitted.** A proposal is spliced under the section it names.
  If that heading does not exist, `learn` appends at end of file and tells you so, above
  the diff and in the commit message — never a silent guess at a near-match heading.

#### New templates, not just edits

When a file recurs across projects with no corresponding template at all (a `Makefile`,
say), `learn` proposes it as a `new_template` — a candidate new file in the template store
rather than an edit — which the next `metaproject new` then scaffolds. Additions and
modifications only; `learn` never proposes removing anything from a template.

#### Requirements and failure modes

`learn` reaches the model by shelling out to `claude -p` on your `PATH`. There is no new
runtime dependency and no API key to manage. If `claude` is not found, `learn` exits
non-zero naming the binary and writes nothing — it never falls back to a heuristic.
Malformed model output is retried once, then that target file is skipped and the run is
recorded as `partial`. No projects and no drift is a clean exit zero.

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
python3 -m pip install --index-url https://test.pypi.org/simple/ --upgrade metaproject==0.6.1 --no-cache-dir --extra-index-url https://pypi.org/simple/
```
