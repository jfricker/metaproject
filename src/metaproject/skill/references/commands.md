# metaproject command reference

Every command accepts `--help`. Paths default to the current directory unless noted.
Anything marked **interactive** prompts or opens a TUI and needs a human at the keyboard.

## Contents
- [init](#init)
- [new](#new)
- [review](#review)
- [learn](#learn)
- [universe](#universe)
- [Agent-session guards](#agent-session-guards)
- [Non-interactive recipes](#non-interactive-recipes)
- [Where state lives](#where-state-lives)

---

## init

`metaproject init [SOURCE_TEMPLATES] [PROJECT_HOME]` — **interactive**

Creates `~/.metaproject/`: `config.json`, the template store (git-backed, so every
`learn apply` is a revertible commit), and `universe.db`. Also installs this skill into
`~/.claude/skills/metaproject/`.

| Flag | Effect |
|---|---|
| `--project-home <path>` | Root directory containing workspaces (default `~/Projects`) |
| `--config-dir <path>` | Override `~/.metaproject` |
| `--force`, `-f` | Overwrite existing configuration, templates, and skill |
| `--no-skill` | Skip installing the skill |

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

**Path resolution:** no `--output` → `./<project-name>`; `--output` naming an existing
directory → `<output>/<project-name>`; `--output` that does not exist or ends in `/` →
that exact path.

**`metaproject new .`** targets the current directory and takes the project name from the
directory itself.

**Backfill** (target already has files) — **interactive**: two confirmations, one for the
templates and one for git. Colliding files are kept as-is and reported under "Kept
(Already Present)". `--yes` cannot answer these prompts; `--force` skips both and
overwrites. If the directory is already a git repository, a backfill leaves it entirely
alone — no init, no staging, no commit.

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

States: `✓ CLEAN`, `~ DRIFTED` (present but differs), `! INCOMPLETE` (a template file is
missing; wins when both apply). Comparison renders each template with the project's own
variables first, so substituted placeholders are never reported as drift.

Remediation is inside the TUI: `u <n>` update a drifted file, `d <n>` deploy a missing
one, `i <n>` ignore a project durably, `o <n>` dismiss it for this session only, `?` help.
`u all` / `d all` require a typed confirmation. The ignore ledger lives at
`~/.metaproject/review-ignore.json`.

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

## Agent-session guards

The CLI detects that an agent rather than a person is driving it, and refuses the things
that need an operator. Detection reads environment markers no ordinary login shell sets:
`CLAUDECODE`, `CLAUDE_CODE`, `AI_AGENT`, `CI`.

| Behavior | In an agent session |
|---|---|
| `review` board | Printed, then exits 0, with a line naming the marker |
| `learn` acceptance reviewer | The queue table, then exits 0 |
| `learn scan` / bare `learn [ROOT]` | Refused, exit 1, printing the command to hand over |
| A backfill's two confirmations | Refused, exit 1; `--dry-run` still previews |
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

# Preview a scaffold or backfill without writing
metaproject new . --dry-run

# Audit this project (prints the board in an agent session)
metaproject review

# Audit a whole workspace tree
metaproject review ~/Projects --all --depth 2

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
| `~/.claude/skills/metaproject/` | This skill, installed by `init` |

Template files carry a `.template` infix that is stripped on render:
`AGENTS.template.md` → `AGENTS.md`, `.gitignore.template` → `.gitignore`,
`docs.template/` → `docs/`.

Substituted variables: `{ProjectTitle}`, `{ProjectSlug}`, `{ProjectDescription}`,
`{Author}`, `{Date}`, `{Year}`. Braces that are not on this list are left alone, so JSON,
CSS, and `${SHELL}` syntax inside templates survive untouched.
