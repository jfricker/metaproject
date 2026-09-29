# metaproject command reference

Every command accepts `--help`. Paths default to the current directory unless noted.
Anything marked **interactive** prompts or opens a TUI and needs a human at the keyboard.

## Contents
- [init](#init)
- [new](#new)
- [backfill](#backfill)
- [review](#review)
- [learn](#learn)
- [universe](#universe)
- [doctor](#doctor)
- [Agent-session guards](#agent-session-guards)
- [Non-interactive recipes](#non-interactive-recipes)
- [Where state lives](#where-state-lives)

---

## init

`metaproject init [SOURCE_TEMPLATES] [PROJECT_HOME]` — **interactive**

Creates `~/.metaproject/`: `config.json`, the template store (git-backed, so every
`learn apply` is a revertible commit), and `universe.db`. It installs no skill: project
skills are copied into each project by `new` and `backfill`.

| Flag | Effect |
|---|---|
| `--project-home <path>` | Root directory containing workspaces (default `~/Projects`) |
| `--config-dir <path>` | Override `~/.metaproject` |
| `--force`, `-f` | Overwrite existing configuration and templates |

Run without `--force` when config already exists and it prints the current settings and
catalog summary instead of changing anything — a safe way to inspect the environment.

## new

`metaproject new <project-name>` — prompts unless `--yes` or all values are supplied.

| Flag | Effect |
|---|---|
| `--output`, `-o <path>` | Destination directory or exact path (default `./<project-name>`) |
| `--templates`, `-t <path>` | Render from a different template store |
| `--title <str>` | Human-readable title (default: title-cased project name) |
| `--description`, `-d <str>` | One-line summary |
| `--author`, `-a <str>` | Author (default: config, then `git config user.name`) |
| `--yes`, `-y` | Accept defaults without prompting |
| `--force`, `-f` | Scaffold into a non-empty directory, **overwriting** collisions |
| `--dry-run` | Print what would be written; touches nothing |
| `--no-git` | Skip `git init` and the initial commit |

Also writes `.metaproject.json` (`title`, `description`, `author`, `created`,
`metaproject_version`) and copies the project skills (this one plus the eight SDLC cycle
skills) into `.agents/skills/<name>/`, reachable as `.claude/skills/<name>/`; both are
tracked in the initial commit. Cycle documents land in `docs/` (`docs/INTENT.md`,
`docs/SPEC.md`, `docs/TECH-DESIGN.md`, `docs/PLAN.md`, `docs/STATE.md`,
`docs/ARCHITECTURE.md`).

**Path resolution:** no `--output` → `./<project-name>`; `--output` naming an existing
directory → `<output>/<project-name>`; `--output` that does not exist or ends in `/` →
that exact path.

**`metaproject new .`** targets the current directory and takes the project name from the
directory itself.

**Scaffolding into an existing directory** (target already has files) —
**interactive**: two confirmations, one for the templates and one for git. Colliding
files are kept as-is and reported under "Kept (Already Present)". `--yes` cannot answer
these prompts; `--force` skips both and overwrites. If the directory is already a git
repository, this leaves it entirely alone — no init, no staging, no commit. In an agent
session this whole flow is refused (exit 1); use `backfill` instead for the documents an
agent is allowed to create unattended.

## backfill

`metaproject backfill [FILE...] [--dir PROJECT_DIR]` — create missing deliverables from
the template store. Never overwrites, never runs git, and is **permitted in agent
sessions** (spec R-TPL-8) — this is how a skill or hook fills in a document `review`
reports missing, without `new .`'s confirmations.

| Flag | Effect |
|---|---|
| `FILE...` (positional, optional) | Specific deliverables to create, e.g. `docs/SPEC.md docs/HANDOFF.md`. Old names (`spec.md`, `design.md`) and bare new names (`SPEC.md`) resolve to their `docs/` path. Default: every deliverable `new` scaffolds that is currently missing, plus missing project skills. |
| `--dir`, `-d <path>` | Project directory to backfill (default: current directory). |
| `--templates <path>` | Template directory to create from (default `~/.metaproject/templates`). |
| `--dry-run` | Preview what would be created; writes nothing. |

Two modes:

- **No `FILE`** — creates every currently-missing deliverable `new` would have
  scaffolded (on-demand deliverables excluded); existing files are listed under
  "Skipped (already exists)" rather than touched. Then copies each project skill whose
  `.agents/skills/<name>/` directory is absent; an existing skill directory is never
  written into (a copy that differs from this release is reported stale). If
  `.claude/skills` is a real directory, or a symlink to somewhere other than
  `.agents/skills`, no skill is written and a notice says why.
- **Named `FILE`s** — creates exactly those (never skills), including on-demand ones
  like `docs/HANDOFF.md`. If *any* named file already exists, nothing at all is written and every
  existing name is reported under "Refused — already exists, nothing written"; the
  command exits non-zero. A named path with no template in the store is reported under
  "No template in the store" and also writes nothing.

Exit codes: `0` on success (including "nothing to do" when everything already exists in
no-`FILE` mode); `1` if any named file was refused or had no template.

```bash
metaproject backfill                       # every missing scaffolded deliverable
metaproject backfill docs/SPEC.md docs/TECH-DESIGN.md   # exactly these
metaproject backfill docs/HANDOFF.md       # on-demand deliverable, created by name
metaproject backfill intent.md             # an old name: creates docs/INTENT.md
metaproject backfill --dry-run             # preview only, writes nothing
metaproject backfill docs/SPEC.md          # exits 1, writes nothing, if it exists
```

## review

`metaproject review [PROJECT_DIR]` — interactive TUI for a person; prints the board and
exits in an agent session (see [Agent-session guards](#agent-session-guards)).

| Flag | Effect |
|---|---|
| `--no-tui` | Print the board and exit explicitly |
| `--all` | Review every project found under the directory |
| `--depth <int>` | Traversal depth for `--all` (default 1) |
| `--templates <path>` | Compare against a different template store |
| `--show-ignored` | Include projects on the ignore list |
| `--list-ignored` | Print the ignore list and exit |
| `--unignore` | Remove the target project from the ignore list and exit |

States: `✓ CLEAN` (nothing missing, nothing drifted, no working document missing a
heading), `~ DRIFTED` (present but a governance file's content differs, or a working
document is missing a template heading), `↻ OUTOFDATE` (nothing missing, but a cycle
document is still at its old root or lowercase location — listed under "Legacy location —
run `metaproject doctor`", never offered for Deploy; wins over drift), `! INCOMPLETE` (a
scaffolded deliverable is missing; wins over everything). Comparison renders each template with the project's own
variables first, so substituted placeholders are never reported as drift.

Governance deliverables (`AGENTS.md`, `CLAUDE.md`, `README.md`, `.gitignore`) are diffed
body-for-body. Working deliverables (`docs/INTENT.md`, `docs/SPEC.md`,
`docs/TECH-DESIGN.md`, `docs/PLAN.md`, `docs/STATE.md`, `docs/ARCHITECTURE.md`,
`docs/DESIGN-INVARIANTS.md`, `docs/VERIFIED-FACTS.md`) are
checked for heading structure only — a per-file list of template headings the project
file is missing, shown as notes on the detail screen — and are never offered for Update;
`.metaproject.json`'s absence is reported as an informational note rather than
`! INCOMPLETE`. A store template containing an unwhitelisted `{placeholder}` prints a
warning naming the file and placeholder rather than failing the review.

Remediation is inside the TUI: `u <n>` update a drifted governance file, `d <n>` deploy a
missing one, `i <n>` ignore a project durably, `o <n>` dismiss it for this session only,
`?` help. `u all` / `d all` require a typed confirmation. `update_entry` raises for a
working deliverable — deploy (or `metaproject backfill`) is the only way to add one that
is missing. The ignore ledger lives at `~/.metaproject/review-ignore.json`.

## learn

`metaproject learn [ROOT]` with no subcommand scans and then opens the acceptance TUI —
**avoid the bare form**; use the subcommands.

| Subcommand | Safety | Purpose |
|---|---|---|
| `learn list` | read-only | Table of proposals: id, target file, title, evidence count, score |
| `learn show <id>` | read-only | Rationale, proposed body, contributing projects |
| `learn scan [ROOT]` | **refused in an agent session**; calls a model, sends data off-machine | Collect drift and synthesize proposals |
| `learn apply <id>` | **writes and commits a template** | Splice the proposal into its target section |
| `learn edit <id>` | **interactive** | Open the proposed body in `$EDITOR`; saving applies it |
| `learn reject <id>` | writes to the ledger | Suppress by content hash (`--forget` clears it) |

`learn list --status pending|applied|rejected|all` (default `pending`), `--verbose` adds
the proposed section.

`learn scan` flags: `--all` (scan the configured projects home), `--depth <int>`,
`--since <date-or-N-days>`, `--yes` (skip the egress confirmation), `--model <name>`,
`--templates <path>`.

`learn apply` flags: `--all` (every pending proposal in turn), `--yes` (skip the diff
confirmation). One commit per accepted proposal, naming the proposal id and the projects
that contributed evidence. A dirty template repository is refused.

Guardrails worth knowing when you explain the tool: a scan never mutates a template;
`.gitignore` matches and a hard denylist (`.env*`, `*.pem`, `*.key`, `id_*`,
`*credentials*`, `*secret*`) are excluded before anything is sent; high-entropy strings
are redacted; only diffs leave the machine, never whole files.

## universe

`metaproject universe [TARGET_DIR]` — scans and catalogs into `~/.metaproject/universe.db`.

| Flag | Effect |
|---|---|
| `--summary`, `-s` | Status summary without scanning |
| `--list`, `-l` | List from the database without touching disk |
| `--all`, `-a` | All cataloged projects across all workspaces |
| `--filter <str>` | Filter by classification, e.g. `'Active Now'` |
| `--depth <int>` | Traversal depth (default 4) |
| `--format <str>` | `table`, `json`, or `csv` |
| `--show-missing` | Include projects cataloged but now gone |
| `--db <path>` | Alternate database |
| `--quiet`, `-q` | Refresh the database silently |

Classifications: `Active Now`, `Active Near`, `Active Far`, `Idle`, `Ancient`, `Archived`.
A project root is anything with a git repo, a `.metaproject` marker, or marker files like
`AGENTS.md` / `pyproject.toml`.

---

## doctor

`metaproject doctor [--dry-run]` — **interactive**: diagnoses an environment and projects
left behind by an upgrade, and repairs each finding behind its own confirmation.

| Check | Fix (on confirmation) |
|---|---|
| Template-store layout | Moves root cycle templates (`intent.template.md`, …) into `docs.template/` with their new names; `git mv` plus one commit of only the moved paths |
| Template store | Seeds templates missing from the store; extras are kept and only listed |
| Config | Rewrites old `learn.targets` paths (`intent.md` → `docs/INTENT.md`) in place, order kept, and appends missing core targets |
| Orphaned global skill | Removes `~/.claude/skills/metaproject/` from older releases; nothing else under `~/.claude` |
| Project identity | Backfills a missing `.metaproject.json` in cataloged projects |
| Project docs (per project) | Moves cycle documents at the root or under old names into `docs/` (`git mv` when tracked); never overwrites (a clash is reported, both files kept) and never commits |
| Project skills (per project) | Installs missing project skills; stale ones are reported, never overwritten |

The project checks cover `universe`-cataloged projects that have `.metaproject.json`, one
confirmation per project. Declining one fix never blocks the rest. A second run after a
full migration is clean (a stale skill stays reported until its directory is deleted and
`backfill` is re-run). In an agent session only `--dry-run` runs; it writes nothing.
Exit code `1` while any finding remains.

## Agent-session guards

The CLI detects that an agent rather than a person is driving it, and refuses the things
that need an operator. Detection reads environment markers no ordinary login shell sets:
`CLAUDECODE`, `CLAUDE_CODE`, `AI_AGENT`, `CI`.

| Behavior | In an agent session |
|---|---|
| `review` board | Printed, then exits 0, with a line naming the marker |
| `learn` acceptance reviewer | The queue table, then exits 0 |
| `learn scan` / bare `learn [ROOT]` | Refused, exit 1, printing the command to hand over |
| Scaffolding into an existing directory (`new .`'s two confirmations) | Refused, exit 1; `--dry-run` still previews |
| `metaproject backfill` | **Allowed** — create-only, no confirmations needed, never runs git |
| `metaproject doctor` | Refused, exit 1; `doctor --dry-run` still reports |
| Everything else | Unchanged |

`METAPROJECT_AGENT` overrides detection in both directions: `0` forces human mode (an
operator working inside a harness gets their TUI back), any other truthy value forces
agent mode (useful for testing, or a harness that sets no marker of its own).

These guards are for the operator's benefit. Relaying a refusal — "this one needs you,
here is the command" — is the intended response; setting `METAPROJECT_AGENT=0` to get
around one is not.

## Non-interactive recipes

```bash
# Scaffold without any prompt
metaproject new <name> --title "<Title>" --description "<one line>" --yes

# Preview scaffolding into an existing directory without writing
metaproject new . --dry-run

# Create a specific missing document without any confirmation (agent-safe)
metaproject backfill docs/SPEC.md docs/HANDOFF.md

# Fill in every missing scaffolded deliverable in one call
metaproject backfill

# Audit this project (prints the board in an agent session)
metaproject review

# Audit a whole workspace tree
metaproject review ~/Projects --all --depth 2

# What would a migration after an upgrade change? (writes nothing)
metaproject doctor --dry-run

# What has the learn pipeline already proposed?
metaproject learn list
metaproject learn show <id>

# Machine-readable project catalog
metaproject universe --list --all --format json
```

## Where state lives

| Path | Contents |
|---|---|
| `~/.metaproject/config.json` | Author, default branch, projects home, template path, db path |
| `~/.metaproject/templates/` | The template store — a git repository |
| `~/.metaproject/universe.db` | Project catalog and the `learn` proposal ledger |
| `~/.metaproject/review-ignore.json` | Projects allowed to stay out of compliance |
| `<project>/.agents/skills/<name>/` | Project skills, copied by `new`/`backfill`, committed with the project (`.claude/skills` links here) |
| `<project>/.metaproject.json` | Per-project identity: title, description, author, created, metaproject_version — written by `new`, read by `review`/`learn`/`backfill`/`universe` |

Template files carry a `.template` infix that is stripped on render:
`AGENTS.template.md` → `AGENTS.md`, `.gitignore.template` → `.gitignore`,
`docs.template/` → `docs/`.

Substituted variables: `{ProjectTitle}`, `{ProjectSlug}`, `{ProjectDescription}`,
`{Author}`, `{Date}`, `{Year}`. Braces that are not on this list are left alone, so JSON,
CSS, and `${SHELL}` syntax inside templates survive untouched.
