# MetaProject - improve learn command

**Author**: John. **Status**: Draft.

## Problem
The learn command does a simple diff of the template and the operation document in a project. This rough approach is inadequate as an operational document needs to interpretted inorder to have meaningful changes extracted and added to the templates.

## Proposed outcome
Use claude cli with a well crafted prompt to review all current operational documents and identify meaningful changes for the templates. For each template in templates gather all operational documents in the universe.db and identify common improvement patterns and other candidates for promotion to templates.

Identification will ignore project specific text (based on best estimate or heuristic) and will score candidates by frequency of occurances. That is, a change to a document that appears in several projects gets a higher score than another that appears once. Recent changes are also scored positively. Accumulated scores become the rank for the change. 

learn contains the prompt for claude. It prepares the documents packages - one for each template, and launches claude with the prompt. Output from claude is structured and is used by learn to create the acceptance flow for the operator.
 
### Acceptance Flow
Candidates are reviewed by operator in a line by line or side by side diff TUI with Accept, Edit, Discard actions.
** Accept ** copies the candidate to the appropriate template.
** Edit ** allows the operator to edit the candidate with a Save action that copies to appropriate template.
** Discard ** discards the candidate and moves to the next candidate.

Flow loops for all candidates for a template. And then loops for all templates.

### Persistence
learn may benefit from a sqlite db. Make a recommendation. 

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
This will change src/learn.py and other sources.

## Scope

### In Scope 
- `metaproject learn` as a corroborated, model-driven proposal pipeline with a durable
  proposal ledger, provenance, and human-reviewed application (see design section above).

### Out of Scope (v1)
- `learn` proposing *removals* from templates (negative signal). Additions and
  modifications only.
- Scheduled or daemonized `learn` runs. Operator-invoked only.
- Any model provider other than `claude -p`; no direct SDK or API-key path.

## Resolved decisions
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
- learn must run from CLI
- learn must be able to access claude cli
