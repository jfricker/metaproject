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

**metaproject learn** — see [Design: `metaproject learn`](#design-metaproject-learn) below.

**metaproject universe [dir]**
Scans starting at the current directory (or specified root) and catalogs all subdirectories, classifying them by activity recency and archive status (`Active Now`, `Active Near`, `Active Far`, `Idle`, `Ancient`, `Archived`). Records brief description, location, and metadata in a SQLite database at `~/.metaproject/universe.db`.


## Design: `metaproject learn`

**Status**: Designed 2026-09-04. Supersedes the v1 line-diff implementation in `src/metaproject/learn.py`.

### Why the current implementation is wrong

`learn` today treats a *raw line* as the unit of learning: any line in `AGENTS.md`,
`.gitignore`, or `Makefile` that is not byte-identical to a line in the template
becomes a candidate, and accepted candidates are appended verbatim to the end of the
template file. Concretely:

- Project names, paths, and one-off prose are indistinguishable from real conventions.
- `extract_file_additions` discards every line starting with `#` as a "comment" — in a
  Markdown file that is every heading, so document structure can never be learned.
- Application is a blind append under a `# Added via metaproject learn` banner, which
  ignores Markdown structure entirely.
- One project's quirk carries the same weight as a convention repeated across twenty.
- A declined candidate is re-proposed on every subsequent run; there is no memory.
- Project files contain concrete values where templates contain Jinja placeholders, so
  substituted content always registers as novel.
- Templates are mutated in place with no dry run, no history, and no way back.

The root problem is that *deciding whether a local edit is a general improvement is a
judgment task*, and the current design attempts it with string equality.

### Core model

`learn` is a **corroborated proposal pipeline**, not an editor. It observes drift across
many projects, uses a model to synthesize generalizable template changes, records them
as durable proposals with provenance, and applies them only through a human-reviewed
diff against a git-backed template repository.

```
projects ──▶ deterministic diff ──▶ evidence bundle ──▶ model synthesis ──▶ proposals ──▶ review ──▶ git commit
             (redacted, ignored     (per target file,   (one call per      (universe.db)  (diff)     (templates/)
              paths filtered)        all projects)       target file)
```

### Pipeline

**1. Collect (deterministic).** Enumerate projects via `universe.db`. For each project
and each target file, render the template with that project's variables and diff it
against the project's actual file. The *diff*, not the whole file, is the evidence unit —
this both cuts token cost and removes the placeholder-substitution false positives.

**2. Guard (deterministic).** Before anything leaves the machine:
- Skip anything matched by the project's `.gitignore`.
- Skip a hard denylist (`.env*`, `*.pem`, `*.key`, `id_*`, `*credentials*`, `*secret*`).
- Redact high-entropy strings and known token shapes from the diffs that remain.
- On the first run of a session, print the file list to be sent and require confirmation
  (`--yes` bypasses for non-interactive use).

**3. Synthesize (model).** One model call **per target file**, carrying every project's
redacted diff for that file. The model is asked to identify changes that recur across
projects and are general enough to belong in a template, and to return structured
proposals: a title, a rationale, the proposed template body, the target section, and the
list of contributing projects. Evidence weighting is supplied to the prompt and enforced
on the output: a proposal must be corroborated by **N ≥ 2 projects** (configurable via
`learn.min_projects`), and projects are weighted by their `universe.db` activity class —
`Active Now` counts fully, `Ancient`/`Archived` counts fractionally.

Batching: when the bundle for one target file exceeds the context budget, it is split
into chunks and a final reduce call merges the per-chunk proposals. Cost therefore scales
with target files, not projects × files.

**4. Record.** Proposals land in `universe.db` (new tables, reusing the existing WAL and
busy-timeout setup) with a content hash, status, evidence count, weighted score, and a
provenance row per contributing project.

**5. Apply.** `learn apply` renders a unified diff of the model-authored template patch,
requires confirmation, writes it, and commits to the template repository with the
proposal id and contributing projects in the message.

### Invocation

The model is reached by shelling out to `claude -p` on the operator's PATH. This adds no
runtime dependency, manages no API key, and reuses existing authentication — consistent
with the "minimal external dependencies" constraint. If `claude` is absent, `learn`
exits with a clear message naming the missing binary rather than degrading to the old
line-diff heuristic. `--model` is passed through.

### CLI surface

| Command | Behavior |
|---|---|
| `metaproject learn scan [root] [--all] [--depth N] [--since DATE] [--yes]` | Run the pipeline; write pending proposals. Never mutates templates. |
| `metaproject learn list [--status pending\|applied\|rejected]` | Table of proposals: id, target file, title, evidence count, score. |
| `metaproject learn show <id>` | Full rationale, proposed diff, and the list of contributing projects with paths. |
| `metaproject learn apply <id> \| --all [--yes]` | Review diff, write template, commit. |
| `metaproject learn reject <id> [--forget]` | Suppress the proposal. `--forget` clears the suppression instead. |

`--templates <path>` remains available on all subcommands.

Bare `metaproject learn` runs `scan` then drops into `list`, preserving the current
one-shot ergonomics.

### Data model (`universe.db`)

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
  target_section TEXT           -- heading or anchor the change belongs under
  evidence_count INTEGER        -- distinct contributing projects
  evidence_score REAL           -- activity-weighted
  status TEXT                   -- "pending" | "applied" | "rejected"
  created_at, updated_at TEXT
  applied_commit TEXT           -- git sha in the template repo

learn_evidence
  proposal_id INTEGER FK
  project_id INTEGER FK -> projects.id
  project_path TEXT
  excerpt TEXT                  -- redacted snippet that contributed
  weight REAL

learn_runs
  id, started_at, finished_at, root, projects_scanned,
  files_scanned, model, proposals_created
```

### Rejection semantics

Rejection is *"not yet,"* not *"never."* A rejected proposal is suppressed by content
hash, but resurfaces if its `evidence_score` later exceeds the score at rejection time by
a configurable margin (`learn.resurface_factor`, default 2.0). `learn reject --forget`
clears the record entirely.

### Targets

Everything the template set defines (`README.md`, `AGENTS.md`, `CLAUDE.md`, `intent.md`,
`STATE.md`, `HANDOFF.md`, `.gitignore`, `docs/`) plus recurring config-shaped files that
have no template yet (`Makefile`, `pyproject.toml`, linter configs). Overridable via a
`learn.targets` config key.

When a file appears in N or more projects with **no corresponding template at all**,
`learn` emits a `new_template` proposal — a candidate new template file rather than an
edit to an existing one.

Additions and modifications only. Proposing *removals* from templates is explicitly out
of scope for this design.

### Template versioning

`~/.metaproject/templates` becomes a git repository, initialized by `metaproject init`.
Every applied proposal is a commit whose message carries the proposal id and the
contributing project names. This provides rollback, history, and a diffable audit trail —
necessary now that templates are machine-edited.

### Provenance and integration

Every proposal names the projects that produced it, with absolute paths, in both
`learn show` and `learn list --verbose`, so the operator can read the source directly.

`review` findings feed `learn` as an evidence source: recurring drift detected by `review`
*is* the learning signal, so a project that `review` flags as diverging from a template in
the same way as several others raises that pattern's evidence score.

### Failure modes

| Failure | Behavior |
|---|---|
| `claude` not on PATH | Exit non-zero with the missing-binary message. No silent fallback. |
| Model returns malformed output | Retry once with a stricter instruction, then record the run as failed and skip that target file. |
| Bundle exceeds context | Chunk and reduce (see Synthesize). |
| Template repo dirty at apply time | Refuse to apply; tell the operator to commit or stash. |
| No projects found / no drift | Report cleanly and exit zero. |

### Open questions

- Default value for `learn.min_projects` — 2 is proposed; may want 3 for large workspaces.
- Exact activity weights per `universe.db` classification.
- Whether `learn scan` should be nudged periodically (intent.md's "periodically review all
  projects") or remain purely operator-invoked. Deferred.

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
- `metaproject learn` as a corroborated, model-driven proposal pipeline with a durable
  proposal ledger, provenance, and human-reviewed application (see design section above).
- `~/.metaproject/templates` initialized as a git repository so template changes are
  versioned and revertible.

### Out of Scope (v1)
- Remote template fetching (e.g., downloading from GitHub repos).
- Multi-archetype / multi-language scaffolding matrices (keep to the primary project template set first).
- Complex conditional AST transformations.
- `learn` proposing *removals* from templates (negative signal). Additions and
  modifications only.
- Scheduled or daemonized `learn` runs. Operator-invoked only.
- Any model provider other than `claude -p`; no direct SDK or API-key path.

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
- `learn` uses a model as its primary engine, invoked by shelling out to `claude -p`. No
  new runtime dependency and no API key management; hard failure if `claude` is absent.
- `learn` never writes templates during a scan. Proposals are persisted to `universe.db`
  and applied only through a separate, diff-reviewed `learn apply`.
- A `learn` proposal requires corroboration from at least 2 projects, weighted by
  `universe.db` activity classification.
- Only redacted diffs (project file vs. rendered template) are sent to the model — never
  whole files, never `.gitignore`d or denylisted paths.
- Rejected proposals are suppressed by content hash but resurface if evidence grows.

## Constraints
- CLI tool will only write into the specified directory for the current user.
- Minimal external dependencies for end users running the CLI. Dependencies must be discussed and approved by operator.
- Must cleanly support macOS zsh terminal environments.
