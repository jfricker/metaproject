# metaproject command reference

Every command accepts `--help`. Paths default to the current directory unless noted.
Anything marked **interactive** prompts or opens a TUI and needs a human at the keyboard.

**Nested projects.** The project a command acts on is the nearest directory at or above
the current one that holds `.metaproject.json`, stopping at the git root — not the git
root itself. Run from `packages/a/src` of a monorepo whose `packages/a` carries its own
`.metaproject.json`, `backfill`, `adopt`, `review`, `skills status|sync`, `templates
fetch` and web-profile `doctor` all act on `packages/a`, and print a dim
`project: <root>` line when that differs from the current directory. An explicit
`--dir`/`PROJECT` always wins; with no anchor at all the current directory is used, as
before. `review --all`, `learn`, `universe` and `new` keep the current directory.
Because `adopt` with no `--dir` now resolves upward, creating a new sub-project inside
a managed one needs `metaproject adopt --dir .`.

## Contents
- [init](#init)
- [new](#new)
- [backfill](#backfill)
- [adopt](#adopt)
- [review](#review)
- [learn](#learn)
- [universe](#universe)
- [doctor](#doctor)
- [skills](#skills)
- [Agent-session guards](#agent-session-guards)
- [Web profile (Claude Code on the web)](#web-profile-claude-code-on-the-web)
- [Optional `tui` extra](#optional-tui-extra)
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
| `--non-interactive` | Accept defaults (and `--author`) without prompting |
| `--author`, `-a <str>` | Default author (default: `git config user.name`, then `$USER`; a detected container identity such as `Claude` or `root` is skipped for `Developer`) |

In the [web profile](#web-profile-claude-code-on-the-web) `init` writes a minimal
`config.json` recording `"profile": "web"`, never prompts, and skips seeding the template
store and the workspace scan.

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
`metaproject_version`) and copies the project skills (this one plus the eleven SDLC
skills) into `.agents/skills/<name>/`, reachable as `.claude/skills/<name>/`; both are
tracked in the initial commit. Also installs the Claude Code hooks: the scripts
`.claude/hooks/metaproject_hook.py` and `scripts/metaproject-session.sh` (create-only)
and three entries (`PostToolUse`, `PreToolUse`, web-only session-start) merged into
`.claude/settings.json` (merge, never overwrite; invalid JSON there is reported and left
alone). Cycle documents land in `docs/` (`docs/INTENT.md`,
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
| `--dir`, `-d <path>` | Project directory to backfill (default: the nearest `.metaproject.json` at or above the current directory, else the current directory). |
| `--templates <path>` | Template directory to create from (default `~/.metaproject/templates`). |
| `--dry-run` | Preview what would be created; writes nothing. |

Two modes:

- **No `FILE`** — creates every currently-missing deliverable `new` would have
  scaffolded (on-demand deliverables excluded); existing files are listed under
  "Skipped (already exists)" rather than touched. Then copies each project skill whose
  `.agents/skills/<name>/` directory is absent; an existing skill directory is never
  written into (a copy from an earlier release is reported outdated, a locally edited
  one modified; `metaproject skills sync` updates the former). If
  `.claude/skills` is a real directory, or a symlink to somewhere other than
  `.agents/skills`, no skill is written and a notice says why.
  `.claude/settings.json` counts as missing until the metaproject hooks are merged into
  it; backfilling it merges them and keeps every existing key. An invalid settings file
  is listed under "Refused — hooks not installed" with a notice, and backfill exits 1.
  When Claude Code's sandbox denies the agent writes under `.claude/`, the hooks are
  listed under "Not written" with a notice and backfill still exits 0 (everything else
  landed); the operator runs `metaproject backfill` themselves to install them. Naming
  `.claude/settings.json` explicitly and failing to write it exits 1.
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

## adopt

`metaproject adopt [--dir PATH] [--title T]` — adopt an existing repository (typically
one that is already cloned). **Permitted in agent sessions**: create-only, runs no git
command, needs no confirmation. This is the agent's way in; `new .` keeps its
interactive, operator-confirmed semantics and is refused in an agent session.

| Flag | Effect |
|---|---|
| `--dir`, `-d <path>` | Repository to adopt (default: the nearest `.metaproject.json` at or above the current directory, else the current directory; use `--dir .` to adopt a new sub-project inside a managed one) |
| `--title <str>` | Title (default: `README.md` heading, `pyproject.toml`/`package.json` name, then the directory name) |
| `--description <str>` | One-line summary (default: the paragraph under the README heading) |
| `--author`, `-a <str>` | Author (default: config, then `git config user.name`, then `$USER`; never a container identity). When none yields a real name — a web container with no config — adopt refuses before writing anything and asks for `--author` |
| `--templates <path>` | Template directory to create from |
| `--dry-run` | Preview; writes nothing |

It writes `.metaproject.json` (kept as written if one exists; an unreadable one stops
the command with exit 1 rather than being replaced), the `.agents/skills` directory with
its `.claude/skills` link, then everything `backfill` with no `FILE` would: every missing
scaffolded deliverable and every missing project skill. Re-running it is a no-op.

```bash
metaproject adopt                          # this repository
metaproject adopt --title "Game Workshop"  # explicit title
metaproject adopt --dry-run                # preview only
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

`metaproject doctor [PROJECT] [--dry-run]` — **interactive**: diagnoses an environment and projects
left behind by an upgrade, and repairs each finding behind its own confirmation.

| Check | Fix (on confirmation) |
|---|---|
| Template-store layout | Moves root cycle templates (`intent.template.md`, …) into `docs.template/` with their new names; `git mv` plus one commit of only the moved paths |
| Template store | Seeds templates missing from the store; extras are kept and only listed |
| Config | Rewrites old `learn.targets` paths (`intent.md` → `docs/INTENT.md`) in place, order kept, and appends missing core targets |
| Orphaned global skill | Removes `~/.claude/skills/metaproject/` from older releases; nothing else under `~/.claude` |
| Project identity | Backfills a missing `.metaproject.json` in cataloged projects |
| Project docs (per project) | Moves cycle documents at the root or under old names into `docs/` (`git mv` when tracked); never overwrites (a clash is reported, both files kept) and never commits |
| Project skills (per project) | Installs missing project skills and updates outdated, unmodified ones (same classification as `skills status`); modified ones are reported, never overwritten |

The project checks cover `universe`-cataloged projects that have `.metaproject.json`, one
confirmation per project. Declining one fix never blocks the rest. A second run after a
full migration is clean (a modified skill stays reported until
`metaproject skills sync --force NAME` replaces it). In an agent session only `--dry-run` runs; it writes nothing.
Exit code `1` while any finding remains.

With a PROJECT path the run is scoped to that one project — `metaproject doctor .` for
the current directory, `metaproject doctor Projects/PPPS` for another. Only its checks
run, in the full run's order: identity (the anchor is backfilled on confirmation even if
the project is not cataloged — accepting is what puts it in scope), then docs, then
skills. The store, config, and global-skill checks are skipped; a path that is not a
directory is refused.

## skills

`metaproject skills status [--dir PATH] [--format table|json]` and
`metaproject skills sync [--dir PATH] [--dry-run] [--force NAME]... [--format table|json]`
— agent-safe: no prompt, no config or template store, permitted in agent sessions and in
the web profile. Both need `.metaproject.json` in the project (else exit 1: run `adopt`).

Each bundled skill is in one of four states:

| State | Meaning | `sync` does |
|---|---|---|
| `✓ current` | Matches this release's copy | Keeps it (records the manifest if needed) |
| `↻ outdated` | A pristine copy of an earlier release (matches its recorded manifest, or a released digest) | Replaces it |
| `~ modified` | Local edits, extra or missing files, a symlink — or a legacy install matching no known release | Keeps it and names it, unless `--force NAME` |
| `! missing` | Not installed | Installs it |

`sync` exits 0 even when modified skills were kept. `--force NAME` (repeatable) replaces
that skill and discards its local edits; an unknown name exits 1 before anything is
written. `--dry-run` reports the same actions and writes nothing. Each replacement is
atomic: the new copy is staged in `.agents/.metaproject-skills-tmp/` and swapped in by
rename, and a failed swap restores the old copy (exit 1).

Every install path (`new`, `backfill`, `adopt`, `skills sync`, doctor's fix) records
`.agents/skills/.metaproject-skills.json` — per skill, the release that wrote it and the
sha256 of each file. Commit it with the project; it is what lets `sync` tell a pristine
older copy from a local edit. A skill installed by a newer metaproject is reported current
and never downgraded; a manifest written by a newer metaproject makes `sync` exit 1 and
is left untouched. A refusal (`.claude/skills` a real directory, or a symlink elsewhere)
writes nothing and exits 1. `sync` does not create the `.claude/skills` link; it points
at `adopt` when the link is absent.

**One copy per monorepo: `skills.location`.** A sub-project's `.metaproject.json` may
declare `"skills": {"location": "root"}` (an enum, never a path; absent or `"project"`
is the default, and an invalid value is a notice, not an error). Its skills then live
in the nearest ancestor project that does not itself declare `"root"` — or, failing
that, the git root — so `new`/`backfill`/`adopt`/`sync` install and update one copy
(and one manifest) there and none in the sub-project. The sub-project's
`.claude/skills` becomes a relative symlink up to that copy (e.g.
`../../../.agents/skills` from `packages/a`): `sync` and `adopt` create it when absent
and re-point the default link to the sub-project's own `.agents/skills`; a real
directory or a link elsewhere is still a refusal. With no ancestor project and no git
root, nothing is written and the command exits 1. Copies left in the sub-project's own
`.agents/skills` after switching are reported, never deleted.

`--format json` writes `{"project", "target", "location", "home", "link", "release",
"manifest", "refusal", "dry_run", "skills": [{"name", "state", "installed_release",
"basis", "changed", "note", "action"}]}` to stdout (`state` is the state before the
pass; `action` is null for `status`; `location` is `project` or `root`, `home` the
directory holding the skills, `link` the sub-project link created or pending), with
notices on stderr.

### Every managed project: `--all`

`metaproject skills status --all [--format table|json]` and
`metaproject skills sync --all [--dry-run] [--yes] [--format table|json]` act on every
cataloged project in `universe.db` that still exists and carries `.metaproject.json` —
the same set `doctor` checks. Each project goes through the single-project code path;
`sync --all` prints one line per project (`updated N  installed N  kept-modified N`, or
`refused <reason>`) and a totals line. It never runs git and never commits.

- `--all` with `--dir` or `--force` is a usage error (exit 2).
- Needs the `tui` extra (the catalog is SQLite); without it, one line and exit 1.
- Web profile: one-line notice, exit 0, nothing written. Empty catalog: a pointer to
  `metaproject universe <root>`, exit 0.
- `sync --all` asks once at a terminal ("Sync skills in N project(s)?"); `--yes` skips
  it. In an agent session without `--yes` it reports as `--dry-run` would, prints
  `metaproject skills sync --all --yes` for the operator, and exits 0 — leave running it
  to the operator.
- A project that fails or is refused does not stop the rest; the exit code is then 1.
- `status --all` is read-only and allowed in agent sessions.

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
| `metaproject adopt` | **Allowed** — create-only, no confirmations needed, never runs git |
| `metaproject doctor` | Refused, exit 1; `doctor --dry-run` still reports |
| Everything else | Unchanged |

`METAPROJECT_AGENT` overrides detection in both directions: `0` forces human mode (an
operator working inside a harness gets their TUI back), any other truthy value forces
agent mode (useful for testing, or a harness that sets no marker of its own).

These guards are for the operator's benefit. Relaying a refusal — "this one needs you,
here is the command" — is the intended response; setting `METAPROJECT_AGENT=0` to get
around one is not.

## Web profile (Claude Code on the web)

A Claude Code on the web session runs in a fresh container: no `~/.metaproject`, no
projects home, no operator. metaproject treats it as the **web profile** when
`METAPROJECT_PROFILE=web`, or when `CLAUDE_CODE_REMOTE=true` and no `config.json`
exists. Once `init` has written a config it records `"profile": "web"`, so the profile
holds; a config without that key is a local machine whatever the environment says, and
`METAPROJECT_PROFILE=local` forces the local profile.

| Command | In the web profile |
|---|---|
| `init` | Minimal config (`"profile": "web"`), no prompt, no template-store seeding, no workspace scan |
| `universe`, `learn` (every subcommand) | One-line "not available in web sessions" notice, exit 0. With `universe --format json` the notice goes to stderr and stdout carries `{"available": false, "profile": "web", ...}`; with `--format csv` stdout stays empty |
| `doctor` | One-line notice that the store, config and catalog checks are skipped; the per-project checks (identity, docs, skills) still run against `PROJECT` when given, else the current directory. `--dry-run` reports. Without `--dry-run`, an agent session (or a core install without `questionary`) gets the same report instead of a refusal; exit 0 when the project is healthy, 1 when there are findings. A fix still needs an operator to confirm it |
| `review` | The interactive board is not available: one-line notice, then the printed board (as `--no-tui`), exit 0 |
| `adopt`, `backfill`, `new`, `review --no-tui`, `--version` | Unchanged; when the store is absent, `adopt`/`backfill`/`review` render from the project's `templates.source`, else the bundled templates |
| `skills`, `templates fetch` | Unchanged (agent-safe) |

### Session-start bootstrap

`new` and `backfill` merge a session-start hook entry into `.claude/settings.json` and copy
`scripts/metaproject-session.sh` create-only. The entry runs the script only when the
file exists **and** `CLAUDE_CODE_REMOTE=true`, and always exits 0. The script installs
the CLI at `.metaproject.json`'s `metaproject_version`
(`uv tool install git+https://github.com/jfricker/metaproject@v<version>`, then pipx,
then `pip --user`, then the default branch; skipped when that version is already
installed; if the installed CLI has no `skills` command — a pin of 0.9.1 or earlier —
it reinstalls from the default branch), appends `~/.local/bin` to `PATH` via `$CLAUDE_ENV_FILE`, then runs
`metaproject skills sync` and `metaproject templates fetch` against the nearest
`.metaproject.json` at or above `CLAUDE_PROJECT_DIR` (stopping at the git root). Output goes to
`$METAPROJECT_SESSION_LOG` (default `$TMPDIR/metaproject-session.log`); offline or
without `uv` it still exits 0. `METAPROJECT_REPO_URL` overrides the repository.

### `templates.source`

Optional, in `.metaproject.json`: `"templates": {"source": ...}` — a git URL, an object
`{"url", "ref", "subdir"}`, or a repository path (`"tools/templates"` /
`{"path": ...}`). Only consulted when `~/.metaproject/templates` is missing or empty
(`--templates` and a local store always win). A git source is shallow-fetched
(`--depth 1`, non-interactive, 120 s timeout) into
`~/.metaproject/cache/templates/<name>-<hash>/` on first use and reused offline after
that. `backfill`, `adopt` and `review` print `Templates: ...` naming the store used; a
malformed, missing or unreachable source falls back to the bundled templates and the
line says why (in `review --all`, the line is a per-project note instead).

`metaproject templates fetch [--dir PATH]` — fetch or refresh the cache. Exit 0 with no
source declared, or after a successful fetch (a path source is only checked); exit 1 on
a malformed source or a failed fetch (a cache from an earlier fetch is kept and used).

## Optional `tui` extra

The core install (`typer`, `rich`, `jinja2`) runs `--version`, `new`, `backfill`,
`adopt` and `review --no-tui`. `textual`, `questionary` and `sqlite-utils` ship in the
`tui` extra and back the TUIs, interactive prompts, `universe`, `learn`, `doctor` and
`skills status|sync --all`. metaproject is installed from a git tag (see the README's
Install section); it is not on PyPI, where `metaproject` is an unrelated package. Without it those exit 1 with one line naming the
install command.

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

# Adopt an already-cloned repository: identity, docs, skills (agent-safe)
metaproject adopt

# Which project skills are behind this release? Update the unmodified ones (agent-safe)
metaproject skills status
metaproject skills sync

# Fetch or refresh the project's declared templates.source (agent-safe)
metaproject templates fetch

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
| `~/.metaproject/config.json` | Author, default branch, projects home, template path, db path, profile (`local`/`web`) |
| `~/.metaproject/templates/` | The template store — a git repository |
| `~/.metaproject/universe.db` | Project catalog and the `learn` proposal ledger |
| `~/.metaproject/review-ignore.json` | Projects allowed to stay out of compliance |
| `~/.metaproject/cache/templates/` | Shallow checkouts of projects' git `templates.source` |
| `<project>/.agents/skills/<name>/` | Project skills, copied by `new`/`backfill`/`adopt`, updated by `skills sync`, committed with the project (`.claude/skills` links here) |
| `<project>/.agents/skills/.metaproject-skills.json` | Skills install manifest: release and per-file sha256 for each installed skill; committed |
| `<project>/.metaproject.json` | Per-project identity: title, description, author, created, metaproject_version — written by `new`/`adopt`, read by `review`/`learn`/`backfill`/`universe`. The nearest one at or above the current directory marks the project root. Optional `commands.lint`, `commands.typecheck`, `e2e_port` for the hooks, `templates.source`, and `skills.location` (`"root"` keeps a sub-project's skills in an ancestor) |
| `<project>/.claude/settings.json` | Claude Code settings; `new`/`backfill` merge the metaproject hook entries in, keeping everything else |
| `<project>/.claude/hooks/metaproject_hook.py` | The hook script (`post-edit`, `pre-bash`; `pre-bash` also advises a worktree-local `PLAYWRIGHT_BROWSERS_PATH` when the Playwright install lock is held), copied create-only |
| `<project>/scripts/metaproject-session.sh` | The web session-start bootstrap script, copied create-only |

Template files carry a `.template` infix that is stripped on render:
`AGENTS.template.md` → `AGENTS.md`, `.gitignore.template` → `.gitignore`,
`docs.template/` → `docs/`.

Substituted variables: `{ProjectTitle}`, `{ProjectSlug}`, `{ProjectDescription}`,
`{Author}`, `{Date}`, `{Year}`. Braces that are not on this list are left alone, so JSON,
CSS, and `${SHELL}` syntax inside templates survive untouched.
