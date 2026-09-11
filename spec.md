# MetaProject — Requirements & Design Specification

**Status**: Draft  
**Reference**: [intent.md](file:///Users/johnfricker/Projects/MetaProject/intent.md)  
**Author**: John (Operator), Claude (Agent)  

---

## 1. Executive Summary

`metaproject learn` closes the loop between projects and templates: it observes how operational documents diverge from the templates they were scaffolded from, and promotes the divergences that recur into the templates themselves.

The shipped implementation treats a raw line as the unit of learning — any line not byte-identical to a template line becomes a candidate, and accepted candidates are appended verbatim. That approach cannot distinguish a project's name from a convention, drops every Markdown heading as a "comment", ignores document structure when writing, and forgets a rejection the moment it is made.

This specification replaces it. Deciding whether a local edit is a general improvement is a judgment task, so a model performs the judgment while deterministic code performs everything around it: gathering evidence, redacting it, scoring corroboration, persisting proposals, and applying approved changes to a version-controlled template store. The operator reviews candidates in a `rich` diff TUI with Accept, Edit, Discard, and Skip — the default mode — or through equivalent queue subcommands for scripting.

The judgment is the model's; the record, the safety rails, and the final write are not.

---

## 2. Goals & Non-Goals

### 2.1 Goals
- **G1** — Extract *meaningful*, generalizable template changes from operational documents, not textual deltas.
- **G2** — Rank candidates by corroboration: frequency and recency across projects, weighted by project activity.
- **G3** — Exclude project-specific text deterministically, by rendering each template with the project's own variables before diffing, rather than by heuristic.
- **G4** — Give the operator a fast review loop: a diff TUI with Accept / Edit / Discard / Skip as the default mode.
- **G5** — Remember decisions. A rejection persists and suppresses a candidate until the evidence for it materially strengthens.
- **G6** — Make every template mutation auditable and revertible via a git-backed template store, one commit per accepted proposal.
- **G7** — Never send more than necessary: redacted diffs only, `.gitignore` and denylist respected, send list confirmed.
- **G8** — Introduce no new Python dependency, and no API key handling.

### 2.2 Non-Goals (v1)
- Proposing *removals* from templates. Additions and modifications only.
- Scheduled, daemonized, or background `learn` runs. Operator-invoked only.
- Any model provider other than the `claude` CLI; no direct SDK or API-key path.
- Automatic application of proposals without operator review.
- Cross-machine or shared proposal ledgers. The ledger is local to `~/.metaproject`.

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
| (Env & Templates  | | (Project Scaffold | |  (Template Drift  | | (Proposal Pipeline| | (Catalog, Classify|
|      Setup)       | |    & Git Init)    | |    & Auditing)    | |  claude -p + TUI) | |  & SQLite Store)  |
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
│       ├── review.py           # Drift review engine, remediation & ignore list
│       ├── review_tui.py       # Compliance board + per-project detail screen
│       ├── learn/               # Template learning pipeline
│       │   ├── __init__.py      # Public API: scan(), review(), apply(), reject()
│       │   ├── collect.py       # Render-and-diff evidence gathering per project × target
│       │   ├── guard.py         # .gitignore/denylist filtering and secret redaction
│       │   ├── synth.py         # `claude -p` invocation, prompt, structured output parsing
│       │   ├── score.py         # Frequency + recency + activity weighting
│       │   ├── store.py         # learn_proposals / learn_evidence / learn_runs CRUD
│       │   ├── apply.py         # Template patching and per-accept git commit
│       │   └── tui.py           # rich acceptance flow (Accept/Edit/Discard/Skip)
│       └── exceptions.py       # Domain-specific error types
└── tests/
    ├── test_baseline.py        # Version & CLI help tests
    ├── test_bump_version.py    # Version bump automation tests
    ├── test_config.py          # Config & template seeding tests
    ├── test_e2e.py             # Full lifecycle and performance tests
    ├── test_learn_collect.py   # Render-and-diff evidence gathering tests
    ├── test_learn_guard.py     # Redaction and denylist tests
    ├── test_learn_synth.py     # Prompt assembly, chunking, output parsing (claude mocked)
    ├── test_learn_score.py     # Frequency/recency/activity weighting tests
    ├── test_learn_store.py     # Proposal ledger, suppression, resurfacing tests
    ├── test_learn_apply.py     # Template patching and commit tests
    ├── test_learn_tui.py       # Keybinding-to-subcommand equivalence tests
    ├── test_review.py          # Drift review, remediation, ignore list & board tests
    ├── test_scaffold.py        # Scaffolding & init guard tests
    ├── test_templates.py       # Template engine tests
    └── test_universe.py        # Universe scanning & summary tests
```

---

## 4. User Configuration & Template Storage

### 4.1 Storage Layout (`~/.metaproject`)

`metaproject` maintains a user-level directory at `~/.metaproject`:
- `~/.metaproject/config.json`: Persistent user settings.
- `~/.metaproject/templates/`: Default template repository loaded by `metaproject new`. Initialized as a **git repository** by `metaproject init`, so every change applied by `learn` is a commit with provenance, and any change is revertible.
- `~/.metaproject/universe.db`: SQLite database storing the project catalog, classifications, metadata, and the `learn` proposal ledger.

### 4.2 Configuration Schema (`config.json`)

```json
{
  "author": "John Fricker",
  "default_branch": "main",
  "project_home": "/Users/johnfricker/Projects",
  "templates_dir": "/Users/johnfricker/.metaproject/templates",
  "universe_db": "/Users/johnfricker/.metaproject/universe.db",
  "auto_git_init": true,
  "default_license": "MIT",
  "learn": {
    "targets": [
      "README.md", "AGENTS.md", "CLAUDE.md", "intent.md", "STATE.md",
      "HANDOFF.md", ".gitignore", "docs/", "Makefile", "pyproject.toml"
    ],
    "resurface_factor": 2.0,
    "model": "claude-haiku-4-5-20251001",
    "activity_weights": {
      "Active Now": 1.0, "Active Near": 0.8, "Active Far": 0.6,
      "Idle": 0.4, "Ancient": 0.2, "Archived": 0.1
    }
  }
}
```

`learn.model` defaults to `claude-haiku-4-5-20251001`, so a scan costs little even at one call per target file (§5.4.3); set it to `null` to let `claude -p` choose, or to another model name to override. `learn.activity_weights` values are provisional; see [intent.md § Open questions](file:///Users/johnfricker/Projects/MetaProject/intent.md).

---

## 5. CLI Command Specifications

### 5.1 `metaproject init` (Alias: `metaproject install`)
Sets up the tool for use. Copies templates to the user's home directory `~/.metaproject/templates/`, creates the configuration file, and builds the `universe.db` catalog.

- **Usage**:
  ```bash
  metaproject init [path/to/templates] [project_home] [--config-dir PATH] [--force] [--no-skill]
  # Alias:
  metaproject install [path/to/templates] [project_home] [--config-dir PATH] [--force]
  ```
- **Arguments & Options**:
  - `[path/to/templates]`: Optional path to source templates. If omitted, self-seeds using bundled package templates via `importlib.resources`.
  - `[project_home]`: Root workspace directory for scanning projects (default: current working directory `./` or `~/Projects`).
  - `--config-dir <path>`: Override configuration directory (default: `~/.metaproject`).
  - `--force, -f`: Reinitialize configuration and overwrite existing templates and skill.
  - `--no-skill`: Skip installing the bundled Claude Code skill.

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
     - Installs the bundled Claude Code skill into `~/.claude/skills/metaproject/`
       (overridable with `METAPROJECT_SKILL_DIR`, skippable with `--no-skill`). An
       installed copy that diverges from the release is reported and left in place unless
       `--force` is supplied, so an operator's own edits are never silently discarded. A
       failure here is reported as a notice and never aborts `init`.
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
  - `--force, -f`: Allow scaffolding into an existing, non-empty directory, overwriting colliding files.
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
     - Allow target_dir containing solitary .git/ or .DS_Store (e.g. if git init was run beforehand)
     - If target_dir contains non-hidden files -> BACKFILL (see below), or ABORT if unconfirmed
  2b. Backfill (target_dir already holds the operator's work):
     - Show what occupies target_dir, then ask the operator to confirm the backfill.
     - Ask a second, separate confirmation before any git setup.
     - Declining the first prompt writes nothing; declining the second scaffolds without git.
     - `--yes` cannot answer these prompts: a non-interactive backfill must pass `--force`.
     - Colliding files are kept as-is and reported; only missing template files are written.
     - `--force` skips both prompts and overwrites colliding files instead of keeping them.
     - If target_dir is already a git repository, a backfill never re-inits, stages, or commits.
  3. Collect variables:
     - project_name of `.` (or `./`, `..`) names a destination, not a project: the target
       directory's own name is used for ProjectTitle and ProjectSlug.
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
Analyzes an existing project against current templates to identify drift or missing files, and offers the operator the remediation for each finding.

- **Usage**:
  ```bash
  metaproject review [project-dir] [--all] [--depth N] [--templates <path>] [--no-tui]
  metaproject review [project-dir] --unignore
  metaproject review --list-ignored
  ```
- **Arguments & Options**:
  - `<project-dir>`: Project directory to review (default: current working directory `./`).
  - `--all`: Review all subdirectories of the target directory. When `--all` is specified, traversal continues descending into subdirectories even if the root itself is a project root.
  - `--depth N`: Maximum subdirectory traversal depth for `--all` (default: `1`, i.e. immediate subdirectories only).
  - `--templates <path>`: Template directory to compare against (default: `~/.metaproject/templates`).
  - `--no-tui`: Print the board and exit instead of opening the interactive actions.
  - `--show-ignored`: Include ignored projects in the audit.
  - `--list-ignored`: Print the ignore list and exit.
  - `--unignore`: Remove the target project from the ignore list and exit.

#### 5.3.1 Drift detection
Every standard deliverable that a template backs is compared, not only `AGENTS.md`. The template is **rendered with that project's own variables** before the comparison (the same rule `learn` follows — see §5.4.2), so placeholder substitution is never reported as drift. Directory deliverables (`docs`) are a presence check only.

A review reports one `ReviewResult` per project (`review.py`). It stores only what the scan observed — `project_name`, `project_path`, `templates_dir`, `missing_files`, `deployable`, `diffs`, `is_ignored` — and derives everything it concludes: `updatable` is the sorted keys of `diffs`, and the two verdicts are properties. A verdict that can be stored is a verdict that can be stored wrong.

`is_compliant` means "nothing is missing". Drift is reported but is not by itself non-compliance: a project is expected to add to its templates. `is_clean` is the stronger claim — nothing missing *and* nothing drifted — and it is what the `Compliance` column's three states are drawn from:

| State | Condition |
|---|---|
| `✓ CLEAN` | `is_clean` — the project matches its rendered templates exactly. |
| `~ DRIFTED` | `is_compliant` but drifted — every deliverable exists, some have diverged in content. |
| `! INCOMPLETE` | A standard deliverable is missing. It wins over `DRIFTED`: a file that is not there cannot be reconciled, so it is the defect the row is named for. |

Each state word names the *defect*, not a grade — a row that says `DRIFTED` has drifted and a row that says `INCOMPLETE` is missing something. Each also carries a **glyph**, because a state told apart only by colour is not told apart at all under `NO_COLOR`, in a pipe, or by a colourblind operator; `rich` strips the style and the character keeps the meaning. The same glyphs mark the per-file `missing` / `drifted` states on the detail screen.

#### 5.3.2 The compliance board
The `Project Drift & Governance Review` table is the operator's working surface, and it is a **triage** view: it answers "which project do I open next", not "which files". Its columns are a row number, `Project`, `Compliance`, and right-aligned `Missing` and `Drifted` **counts** — the file names live on the detail screen, numbered and actionable, so the board never carries a wrapping list of them.

Above the table sits the **summary header**: the aggregate (total projects, how many are clean, drifted and incomplete, and how many are on the ignore list) over the scan context (the root that was scanned and the template store it was compared against). A governance report that opens with a bare row count makes the operator total the column themselves, and a verdict that does not name what it measured cannot be acted on. `review_cmd` supplies the scan root and the ignore count; every part is optional and the header degrades a line at a time, so a caller that knows none of it still gets a board.

Commands are **verb first on both screens** (`u 3`, `d 2`, `i 4`, `o 1`; a bare `3` opens the project), matching the detail screen, vim and git, so muscle memory survives the screen transition. The board also still accepts its former number-first grammar (`3u`, `3 u`) — both forms parse to the same selection — and `?` prints the verb list and both grammars.

| Action | Effect |
|---|---|
| **Open** (`u <n>`, `d <n>`, `<n>`) | Open the project's detail screen. `u` and `d` are the same door: they were once two "focuses" that dimmed a different column and changed no behaviour. |
| **Ignore** (`i <n>`) | Record the project as permitted to stay out of compliance. It leaves the board immediately and is excluded from **every future review** until `--unignore`. |
| **OK** (`o <n>`) | Dismiss the project from this board. Nothing is recorded, so it **is checked again on the next review**. |

**OK and Ignore must not be conflated.** They are the two halves of "I do not want to look at this": OK is session-local and unrecorded, Ignore is durable and written to the ledger. `BoardResult.actioned` counts writes and Ignore decisions but never dismissals, because a dismissal changed nothing. The closing summary `review_cmd` prints on exit states the difference in words rather than leaving `OK 2` to be misread as a recorded decision.

#### 5.3.3 The detail screen
Lists the selected project's missing and drifted deliverables as one continuously numbered list, missing first. Commands:

| Command | Effect |
|---|---|
| `d <n>` / `d all` | Deploy the numbered missing deliverable, or every one. `d all` is gated on a typed confirmation. |
| `u <n>` / `u all` | Update the numbered drifted file from its rendered template (overwrites), or every one. `u all` is gated on a typed confirmation that names the loss. |
| `v <n>` | Show the unified diff for a drifted file. It stays **pinned** until `c` closes it or the write it argued for lands; a diff taller than the screen goes to `console.pager()` first. |
| `v` | The same, when exactly one file has drifted — the only row on offer is not an ambiguous request. |
| `c` | Close the pinned diff. |
| `o` | OK — dismiss this project for now; checked again next review. |
| `i` | Ignore this project; not checked again until `--unignore`. |
| `?` | Print the command list. |
| `b` | Back to the board. |
| `q` | Quit. |

A bare `d` or `u` **selects nothing and writes nothing**; it asks the operator to name a row or say `all`. Folding a missing argument into `all` is how a single keystroke came to overwrite every drifted file in a project unasked.

**Deploy** refuses to write over an existing path and **Update** refuses to create a missing one; they are separate verbs so that a reviewed file cannot be silently clobbered. A batch resolves template variables **once, before its first write**: resolving per file would let an early write change how a later one renders, and the board would then report files it had just written as drifted.

Every action is durable when it is typed — nothing is buffered, and quitting loses nothing. The board is an interface to `review.py`'s engine, never a second implementation of it.

#### 5.3.3.1 Presentation
Both loops run on the terminal's **alternate screen** (`console.screen()`), so the session ends with the operator's scrollback intact rather than scrolled away by `console.clear()`. The **notice line is painted every frame**, notice or not: it holds its position so the key bar never moves, and a message survives until a command produces a new one instead of being wiped by the next repaint.

The palette is deliberately narrow — cyan is the one structural accent (panels, project names, paths), red/yellow/green mean compliance state and nothing else, and bold marks the *key* an operator types rather than the label beside it. Seven competing channels made none of them mean anything.

#### 5.3.4 The ignore list
A JSON ledger at `~/.metaproject/review-ignore.json` (`{"version": 1, "projects": [...]}`), holding absolute project paths. A malformed or unreadable ledger is treated as empty rather than raised: an operator who cannot parse their own ignore file must still be able to run a review.

#### 5.3.5 Degradation
Identical to `learn`'s reviewer (§5.4.5): `--no-tui`, `TERM=dumb`, or a non-TTY stdout prints the board and exits. Scripted and CI use therefore needs no special flag.

### 5.4 `metaproject learn`

A corroborated proposal pipeline. `learn` observes drift across many projects, uses a model to synthesize generalizable template changes, records them as durable ranked proposals with provenance, and applies them only after operator review. It never mutates a template during a scan.

Reference: [intent.md § Design: `metaproject learn`](file:///Users/johnfricker/Projects/MetaProject/intent.md).

#### 5.4.1 Pipeline

| Stage | Determinism | Behavior |
|---|---|---|
| 1. Collect | Deterministic | Enumerate projects from `universe.db`. For each project × target file, render the template with that project's variables and diff against the project's actual file. The rendered-then-diffed delta is the evidence unit, which removes placeholder-substitution false positives. |
| 2. Guard | Deterministic | Filter `.gitignore` matches and a hard denylist; redact high-entropy strings; print withheld paths once, informationally. |
| 3. Synthesize | Model | For each target file, confirm that file's slice of the send list with the operator (send or skip); a skip costs no call and no evidence for that file leaves the machine. A sent file becomes one `claude -p` call carrying every project's redacted diff for that file. Returns structured proposals. Chunk-and-reduce when a bundle exceeds the context budget. |
| 4. Record | Deterministic | Persist proposals and per-project evidence rows to `universe.db`. |
| 5. Review | Operator | Diff TUI (default) or the queue subcommands. |
| 6. Apply | Deterministic | Patch the template, commit to the template git repository. |

#### 5.4.2 Scoring

Candidates are **ranked, not gated**. Score accumulates frequency (distinct contributing projects) and recency, weighted by each contributing project's `universe.db` activity classification — `Active Now` counts fully, `Ancient` and `Archived` fractionally. A single-project candidate still surfaces; it simply ranks below a corroborated one. The queue is ordered by score descending.

#### 5.4.3 Model invocation

The model is reached by shelling out to `claude -p` on the operator's `PATH`. No new runtime dependency, no API key management, no direct SDK path. If `claude` is not found, `learn` exits non-zero naming the missing binary; it never falls back to the legacy line-diff heuristic. `--model` is passed through to the CLI.

#### 5.4.4 Command surface

| Command | Behavior |
|---|---|
| `metaproject learn [root] [--no-tui]` | **Default mode.** Scan, then open the acceptance TUI over the resulting queue. |
| `metaproject learn scan [root] [--all] [--depth N] [--since DATE] [--yes]` | Run stages 1–4. Never mutates templates, never opens the TUI. |
| `metaproject learn review [--target FILE] [--status pending] [--min-score N]` | Open the TUI over the existing queue without scanning. |
| `metaproject learn list [--status pending\|applied\|rejected] [--verbose]` | Table of proposals: id, target file, title, evidence count, score. |
| `metaproject learn show <id>` | Full rationale, proposed diff, contributing projects with absolute paths. |
| `metaproject learn apply <id> \| --all [--yes]` | Review diff, write template, commit. |
| `metaproject learn edit <id>` | Open the proposed body in `$EDITOR`; saving applies the edited version. |
| `metaproject learn reject <id> [--forget]` | Suppress by content hash. `--forget` clears the suppression. |

`--templates <path>` is available on all subcommands (default `~/.metaproject/templates`).

The TUI and the subcommands are two interfaces to one queue, not two pipelines. Every TUI keystroke performs the equivalent subcommand and writes through to `universe.db` immediately, so a review session can be abandoned and resumed, or finished from the CLI, without loss or divergence.

#### 5.4.5 Acceptance flow (TUI)

Built on `rich`; no new dependency. Diffs render as `rich` tables with `Syntax` highlighting; the loop reads single keystrokes and repaints rather than running a widget framework's event loop.

Candidates loop within a template, highest score first, then advance to the next template. Templates are ordered by their highest-scoring pending candidate.

| Key | Action | Equivalent | Effect |
|---|---|---|---|
| `a` | Accept | `learn apply <id>` | Write into the template, commit, mark `applied`, advance. |
| `e` | Edit | `learn edit <id>` | Suspend, open the proposed body in `$EDITOR`. Saving applies the edited text and stores it as `edited_body`; exiting without saving returns unchanged. |
| `d` | Discard | `learn reject <id>` | Mark `rejected`; suppressed by content hash, resurfaces on stronger evidence. |
| `s` | Skip | — | Leave `pending` and advance. Reappears next review. |
| `u` | Toggle view | — | Switch between side-by-side and unified diff. |
| `p` | Provenance | — | Expand the full contributing-project list with absolute paths. |
| `q` | Quit | — | Exit; actioned items persist, the remainder stays pending. |

Discard is a judgment that is remembered; Skip is deferral that is not.

Each accept is an individual commit in the template repository carrying the proposal id and contributing project names. Accepts are never batched.

**Degradation**: when stdout is not a TTY, `--no-tui` is passed, or `TERM=dumb`, the default mode prints the `list` table and exits zero. Scripted and CI use needs no special flag. When the terminal is too narrow for side-by-side, the TUI falls back to the unified view automatically. On an empty queue the TUI is not opened.

#### 5.4.6 Targets

Every file the template set defines (`README.md`, `AGENTS.md`, `CLAUDE.md`, `intent.md`, `STATE.md`, `HANDOFF.md`, `.gitignore`, `docs/`) plus recurring config-shaped files with no template yet (`Makefile`, `pyproject.toml`, linter configs). Overridable via the `learn.targets` config key.

When a file recurs across projects with no corresponding template at all, `learn` emits a `new_template` proposal — a candidate new template file rather than an edit. Additions and modifications only; proposing removals from templates is out of scope.

#### 5.4.7 Rejection semantics

Rejection is "not yet", not "never". A rejected proposal is suppressed by `content_hash`, but resurfaces when its `evidence_score` later exceeds the score recorded at rejection time by `learn.resurface_factor` (default `2.0`). `learn reject --forget` clears the record entirely.

#### 5.4.8 Data model (`universe.db`)

Created by `init_schema` alongside the existing `projects` table, reusing the configured WAL mode and busy timeout.

```
learn_proposals
  id INTEGER PK
  content_hash TEXT UNIQUE      -- stable identity across scans; drives suppression
  target_file TEXT              -- e.g. "AGENTS.md"
  template_path TEXT
  kind TEXT                     -- "edit" | "new_template"
  title TEXT
  rationale TEXT
  proposed_body TEXT            -- model-authored replacement/insert
  edited_body TEXT              -- operator's TUI edit, if any; applied in preference
  target_section TEXT           -- heading or anchor the change belongs under
  evidence_count INTEGER        -- distinct contributing projects
  evidence_score REAL           -- frequency + recency, activity-weighted
  status TEXT                   -- "pending" | "applied" | "rejected"
  rejected_score REAL           -- evidence_score at time of rejection; drives resurfacing
  created_at TEXT
  updated_at TEXT
  applied_commit TEXT           -- git sha in the template repo

learn_evidence
  id INTEGER PK
  proposal_id INTEGER  -- FK -> learn_proposals.id
  project_id INTEGER   -- FK -> projects.id
  project_path TEXT
  excerpt TEXT         -- redacted snippet that contributed
  weight REAL

learn_runs
  id INTEGER PK
  started_at TEXT
  finished_at TEXT
  root TEXT
  projects_scanned INTEGER
  files_scanned INTEGER
  model TEXT
  proposals_created INTEGER
  status TEXT          -- "ok" | "partial" | "failed"
```

Indexes: `learn_proposals(status, evidence_score DESC)` for queue ordering, `learn_proposals(target_file)` for `--target` filtering, `learn_evidence(proposal_id)`.

#### 5.4.9 Integration with `review`

`review` findings feed `learn` as an evidence source. Recurring drift detected by `review` is itself the learning signal: a project that `review` flags as diverging from a template in the same way as several others raises that pattern's `evidence_score`.

#### 5.4.10 Failure modes

| Failure | Behavior |
|---|---|
| `claude` not on `PATH` | Exit non-zero naming the missing binary. No silent fallback. |
| Model returns malformed output | Retry once with a stricter instruction, then record the run `partial` and skip that target file. |
| Bundle exceeds context budget | Chunk and reduce. |
| Template repo dirty at apply time | Refuse to apply; instruct the operator to commit or stash. |
| No projects found / no drift | Report cleanly, exit zero. |
| Not a TTY, or `--no-tui` | Fall back to the `list` table. No error. |
| `$EDITOR` unset or exits non-zero | Abort the edit, keep the candidate pending, stay in the TUI. |
| Terminal too narrow for side-by-side | Fall back to the unified diff view automatically. |

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
   - `metaproject` must never write files into a non-empty directory without either `--force` or an explicit interactive backfill confirmation.
   - A confirmed backfill keeps every colliding file exactly as it is; only missing template files are written.
   - Even with `--force`, existing files not present in the template are never deleted; colliding files are explicitly overwritten.
   - Rollback never deletes a file that existed before the run, including one overwritten by `--force`.
   - **Empty Directory Definition**: A directory containing no non-hidden files, allowing a solitary `.git/` directory and `.DS_Store`.
   - **Transactional Rollback**: On a failed scaffold, only delete paths created during *this* run; never `rmtree` an existing pre-created directory.
2. **Filesystem Confinement**:
   - The tool will only write to the resolved target directory or `~/.metaproject/`.
   - Prevent path traversal attacks in project names (e.g., `../../etc`).
3. **Fail-Safe Rollback**:
   - If an error occurs during template rendering before git initialization, prompt or cleanup partial generation to avoid dirty partial states.
4. **Agent-Session Guards**:
   - The CLI detects whether a person or an agent is driving it, from environment markers
     no ordinary login shell sets (`CLAUDECODE`, `CLAUDE_CODE`, `AI_AGENT`, `CI`).
   - In an agent session the interactive TUIs never open: `review` and the `learn`
     acceptance reviewer print their board or table and exit zero, naming the marker. A
     full-screen loop inside a tool call blocks on keystrokes that never arrive, and a
     harness that allocates a pty defeats the TTY check on its own.
   - `learn scan` (and the bare `learn [ROOT]` form, which scans) is refused with exit 1.
     It spends the operator's money and egresses their diffs; the refusal prints the exact
     command for the operator to run.
   - A backfill's confirmations are refused with exit 1 and a handover message. `--dry-run`
     still previews, because it writes nothing.
   - `METAPROJECT_AGENT` overrides detection in both directions: `0` forces human mode,
     any other truthy value forces agent mode.
   - Every guard degrades to something useful. A person misdetected as an agent loses
     interactivity, never work.
5. **`learn` Egress Guard** (data leaving the machine):
   - Only redacted **diffs** are sent to the model — never whole project files.
   - Anything matched by the project's `.gitignore` is excluded.
   - A hard denylist is excluded regardless of `.gitignore`: `.env*`, `*.pem`, `*.key`, `id_*`, `*credentials*`, `*secret*`.
   - High-entropy strings and known token shapes are redacted from surviving diffs.
   - Each target file's slice of the send list is displayed and confirmed separately, before that file's evidence is sent; `--yes` bypasses every prompt for non-interactive use.
6. **`learn` Write Guard**:
   - A scan never mutates a template. Mutation happens only via `apply`, from a persisted proposal.
   - `apply` refuses to run when the template repository has uncommitted changes.
   - Every applied proposal is an individual commit; accepts are never batched.
   - Model output is treated as data, never as instructions. A proposal's body is inserted as template text; it is never executed, and never interpreted as a directive to the tool.
7. **Template Walker & Variable Whitelist Guard**:
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
- **External Binaries (not packaged)**:
  - `claude`: the Claude Code CLI, required on `PATH` for `metaproject learn`. Invoked as `claude -p`. Deliberately not a Python dependency — no API key handling, no SDK, and no version pinning. All other commands function without it.
  - `git`: required for `init` (template repository) and `learn apply` (commits).
- **Explicitly Not Adopted**:
  - `textual`: the `learn` acceptance TUI is built on the already-approved `rich`. `learn` introduces **no new Python dependency**.
  - `anthropic` SDK or any direct model API path.
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
5. **`learn` Pipeline Tests** (`claude` subprocess mocked throughout; no test invokes a model):
   - **Collect**: rendering a template with a project's variables before diffing suppresses placeholder-substitution false positives; a project whose file matches the rendered template yields no evidence.
   - **Guard**: `.gitignore`d paths and denylisted patterns are excluded; high-entropy strings are redacted; the confirmation is skipped under `--yes`.
   - **Synth**: one call per target file; bundles over budget are chunked and reduced; malformed model output retries once then marks the run `partial`; missing `claude` binary exits non-zero without touching templates.
   - **Score**: frequency and recency combine with activity weights; a single-project candidate still surfaces and ranks below a corroborated one; the queue orders by score descending.
   - **Store**: proposals upsert by `content_hash`; a rejected hash stays suppressed; it resurfaces once `evidence_score` exceeds `rejected_score * resurface_factor`; `--forget` clears the record.
   - **Apply**: the template is patched at `target_section`; `edited_body` takes precedence over `proposed_body`; one commit per accept carrying proposal id and project names; `apply` refuses on a dirty template repository.
   - **TUI**: each keybinding performs the same state transition as its equivalent subcommand; Skip leaves the candidate `pending` while Discard marks it `rejected`; quitting persists everything already actioned; non-TTY, `--no-tui`, and `TERM=dumb` fall back to the `list` table and exit zero; a narrow terminal falls back to the unified view.
   - **Scan invariant**: a full `learn scan` leaves the template directory byte-identical and its git worktree clean.
6. **Version Flag & Manifest Tests (`tests/test_baseline.py`)**:
   - Verifying `-v` and `--version` options render complete package manifest information.
7. **Version Bump Automation Tests (`tests/test_bump_version.py`)**:
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

