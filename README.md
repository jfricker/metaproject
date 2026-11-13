# MetaProject

A CLI tool for setting up and managing agentic projects. Template based system to maintain consistency across projects. Learn mode reviews changes over time and recommends updates to the templates.

## Features
- **Instant Scaffolding (`metaproject new`)**: Scaffold projects with full SDLC documentation and automatic git initialization.
- **Agent-Safe Backfill (`metaproject backfill`)**: Create specific missing documents without confirmation, in agent sessions.
- **Agent-Safe Adoption (`metaproject adopt`)**: Bring an already-cloned repository under metaproject — identity, every missing document and skill — create-only, no git, no confirmation.
- **Environment Setup (`metaproject init` / `install`)**: Prepare templates and configure project workspace.
- **Project Skills**: The SDLC cycle skills (`/write-intent` … `/wrapup`, `/backlog-new`) and the metaproject skill ship in the wheel and are copied into each project's `.agents/skills/` by `new`, `backfill` and `adopt`, and kept current by `metaproject skills sync`.
- **Repair & Migration (`metaproject doctor`)**: Bring the template store, config and cataloged projects up to date after an upgrade, behind per-fix confirmation.
- **Workspace Universe (`metaproject universe`)**: Catalog and classify all projects across subdirectories into a SQLite database.
- **Drift Auditing (`metaproject review`)**: Detect drift between project files and central templates.
- **Template Learning (`metaproject learn`)**: Observe drift across many projects, synthesize corroborated template proposals, and apply them only after review.
- **Package Manifest (`metaproject -v` / `--version`)**: Inspect package metadata, runtime dependencies, license, and version.

## Install

1. **Install the CLI** (needs [uv](https://docs.astral.sh/uv/); Python 3.11+):

   ```bash
   uv tool install "metaproject[tui] @ git+https://github.com/jfricker/metaproject@v0.9.1"
   ```

   pipx and pip work too ([other installers](#other-installers)). metaproject is **not
   on PyPI**: the PyPI package named `metaproject` is unrelated, so always install from
   the `git+https://github.com/jfricker/metaproject` source.

2. **Set up once:** `metaproject init` — config, template store and project catalog
   under `~/.metaproject/`.

3. **Start or adopt a project:** `metaproject new my-app` for a new one, or
   `cd existing-repo && metaproject adopt` for one you already have. Either copies the
   project skills into `.agents/skills/` and links `.claude/skills` to them.

4. **Verify:** `metaproject --version`, then `metaproject skills status` inside the
   project.

### Core vs `[tui]`

| Install | Brings | Runs |
|---|---|---|
| core | `typer`, `rich`, `jinja2` | `--version`, `new`, `backfill`, `adopt`, `review --no-tui`, `skills status`, `skills sync` |
| `[tui]` | adds `textual`, `questionary`, `sqlite-utils` | the TUIs and prompts, `universe`, `learn`, `doctor`, `skills status --all`, `skills sync --all` |

Use `[tui]` on a workstation; core is enough for containers, CI and Claude Code on the
web. A command that needs the extra without it says so in one line and exits 1.

### Other installers

```bash
# Full, with pipx, or with pip inside a virtualenv
pipx install "metaproject[tui] @ git+https://github.com/jfricker/metaproject@v0.9.1"
python3 -m pip install "metaproject[tui] @ git+https://github.com/jfricker/metaproject@v0.9.1"

# Core only
uv tool install "git+https://github.com/jfricker/metaproject@v0.9.1"

# Track main instead of a release tag (then `uv tool upgrade metaproject` updates it)
uv tool install "metaproject[tui] @ git+https://github.com/jfricker/metaproject"

# Uninstall
uv tool uninstall metaproject    # or: pipx uninstall metaproject
```

## Update

1. **Upgrade the CLI.** A tag-pinned install does not move with `uv tool upgrade`;
   re-run the install command with the new tag:

   ```bash
   uv tool install --force "metaproject[tui] @ git+https://github.com/jfricker/metaproject@v0.9.1"
   ```

   (pipx: `pipx install --force ...`; pip: `python3 -m pip install --upgrade ...`.) If
   you installed from main, `uv tool upgrade metaproject` is enough.

2. **Refresh each project's skills:** `metaproject skills sync` inside a project, or
   `metaproject skills sync --all` for every cataloged project (asks once; `--dry-run`
   previews).

3. **Repair anything else:** `metaproject doctor --dry-run`, then `metaproject doctor`
   (template store, config, anchors, cycle-document locations).

`skills sync` installs missing skills and replaces outdated ones you have not edited. A
skill you edited is kept and reported, never overwritten unless you name it with
`--force NAME`. Sync never runs git: review the diff in each project and commit it
yourself. Updates arrive only this way — a project's skills are its own committed copies,
not a global install.

## Where skills live and which agents see them

Instructions and skills are separate. Every harness below reads `AGENTS.md` (Claude Code
through the scaffolded `CLAUDE.md`, which contains `@AGENTS.md`). Skills are plain files
in `.agents/skills/<name>/SKILL.md`, committed with the project, following the Agent
Skills convention.

| Harness | Sees the skills via | Invoke |
|---|---|---|
| Claude Code (CLI, desktop, web) | `.claude/skills` → `../.agents/skills` symlink, created by `new`/`adopt` | `/write-intent` |
| OpenAI Codex CLI | `.agents/skills`, natively | `$write-intent` or implicitly |
| Amp | `.agents/skills`, natively | implicitly |
| OpenCode | `.agents/skills` (also `.claude/skills`) | implicitly |

Reported to work, but check your harness's current docs: GitHub Copilot (CLI, VS Code
agent, coding agent) and Goose read `.agents/skills`; Gemini CLI reads it as an alias of
`.gemini/skills` but needs `context.fileName` set to include `AGENTS.md`; Cursor reads
`.cursor/skills` and `.claude/skills`. Windsurf and Antigravity use their own
directories.

- A harness without skills support can still be told to read
  `.agents/skills/write-intent/SKILL.md`.
- Where symlinks are unavailable (some Windows setups) Claude Code will not see the
  skills; metaproject refuses to write skills when `.claude/skills` is a real directory.
- A harness that wants its own directory can be given a symlink to `.agents/skills` by
  hand; metaproject creates only the Claude Code one.

## Claude Code on the web

In a Claude Code on the web session (`CLAUDE_CODE_REMOTE=true` with no
`~/.metaproject/config.json`, or `METAPROJECT_PROFILE=web` anywhere) metaproject runs in
the **web profile**: `init` writes a minimal config (`"profile": "web"`), never prompts,
and skips template-store seeding and the workspace scan; `universe` and `learn` print a
one-line "not available in web sessions" notice and exit 0 (`universe --format json`
keeps stdout JSON); `doctor` skips its store, config and catalog checks with that notice
and runs only one project's identity, docs and skills checks — `[PROJECT]` if given, else
the current directory (in an agent session,
or without `questionary`, it reports them as `--dry-run` would instead of refusing: exit 0
when healthy, 1 with findings); `review` prints the notice and then the board instead of
opening it, exit 0. `adopt`, `backfill`, `review --no-tui` and `--version` work
as usual, rendering from the project's `templates.source` when it declares one (below),
else the bundled templates. `METAPROJECT_PROFILE=local` forces the local profile.

`new` and `backfill` install a `SessionStart` hook that bootstraps each web session. It
runs `scripts/metaproject-session.sh` (copied create-only) **only** when
`CLAUDE_CODE_REMOTE=true`; the script installs the CLI at the version pinned in
`.metaproject.json` (`metaproject_version`) with
`uv tool install git+https://github.com/jfricker/metaproject@v<version>` (falling back to
pipx, then `pip --user`, then the default branch), adds `~/.local/bin` to the session's
`PATH`, runs `metaproject skills sync` and `metaproject templates fetch`. If the
installed CLI has no `skills` command (a pin of 0.9.1 or earlier, which predates it), it
reinstalls from the default branch instead of silently skipping both steps. It is
idempotent (a matching installed version is left alone), writes only to a log
(`$TMPDIR/metaproject-session.log`), and always exits 0 — offline, no `uv`, or a missing
script never blocks a session.

### Template store in a fresh container (`templates.source`)

A web container has no `~/.metaproject/templates`, so documents would render from the
bundled defaults and `review` would report drift against your own store that is not real.
Declare where the store lives in `.metaproject.json`:

```json
{ "templates": { "source": { "url": "https://github.com/you/templates.git", "ref": "main" } } }
```

`source` may also be a bare git URL, `{"url": ..., "ref": ..., "subdir": ...}` for a store
inside a larger repository, or a repository path (`"tools/templates"` or
`{"path": "tools/templates"}`). When `~/.metaproject/templates` is missing or empty,
`backfill`, `adopt` and `review` use it — a git source is shallow-fetched once into
`~/.metaproject/cache/templates/` and reused from there — and print which store they used
(`Templates: ...`). A source that is malformed, missing or unreachable falls back to the
bundled templates, and the line says why. A local store always wins over a declared
source. `metaproject templates fetch` refreshes the cache (the session script runs it);
it is a no-op without a source.

## Upgrading from older releases

This is migration reference; the everyday path is [Update](#update). After upgrading the CLI, what
metaproject put outside it can lag behind: the template store at
`~/.metaproject/templates` (including its layout), `learn.targets` in `config.json`, an
orphaned `~/.claude/skills/metaproject/` from releases that installed the skill globally,
per-project `.metaproject.json` anchors, and — in each cataloged, metaproject-managed
project — cycle documents still at the root under their old names and missing project
skills. Run `metaproject doctor` to check them in that order and repair what's stale —
each fix asks for confirmation first (once per project for the project checks), and
`--dry-run` previews findings without writing anything. Name a project to scope the run
to it — `metaproject doctor Projects/PPPS`, or `metaproject doctor .` for the current
directory — and only that project's anchor, cycle documents, and skills are checked; the
environment-wide checks are skipped:

```bash
metaproject doctor --dry-run   # preview
metaproject doctor             # diagnose, confirm each fix
metaproject doctor .           # just this project: its anchor, docs, and skills
```

Notes:

- The template store is git-backed and yours to edit (`learn apply` commits to it):
  doctor only *adds* templates missing from the new package and never deletes or
  overwrites anything already there. A deliberate `metaproject init --force` remains
  the way to force content back to the bundled defaults.
- `learn.targets` migration is additive — newly declared deliverables are appended;
  your own pinned targets are never removed or reordered.
- Cycle documents moved into `docs/` with new names (`intent.md` → `docs/INTENT.md`,
  `spec.md` → `docs/SPEC.md`, `design.md` → `docs/TECH-DESIGN.md`, `plan.md` →
  `docs/PLAN.md`, and `STATE.md`, `HANDOFF.md`, `ARCHITECTURE.md` into `docs/`). Doctor
  moves the store's templates into `docs.template/` (one commit in the store, of only the
  moved paths), rewrites old `learn.targets` paths in place, and moves each project's
  documents with `git mv` when they are tracked. It never overwrites — a document already
  at its new path is reported and both copies are kept — and it never commits inside a
  project; review and commit the moves yourself. `review` shows an unmigrated project as
  `↻ OUTOFDATE` until then.
- Project skills from an earlier release are updated by `metaproject skills sync` (or
  doctor's project-skills fix) — but only when unmodified. A skill you edited is reported
  and never overwritten unless you name it: `metaproject skills sync --force NAME`.

### Retiring the sdlc-skills plugin

The cycle skills used to ship as the separate `sdlc-skills` Claude Code plugin; they are
absorbed into metaproject ≥ 0.9.0. In this order:

1. Install the new release ([Install](#install)).
2. Uninstall the `sdlc-skills` plugin and remove its directory marketplace, so sessions
   stop loading the old plugin-namespaced copies of the skills.
3. Run `metaproject doctor` (after `--dry-run`) to migrate the store, config and projects
   and install the project skills.
4. Add a pointer to `~/Projects/SDLC-skills`'s README ("absorbed into metaproject ≥
   0.9.0") and leave that repository read-only on disk.

## Development

```bash
git clone https://github.com/jfricker/metaproject.git
cd metaproject
make install          # editable install with dev tools and the `tui` extra
make test && make lint
make install-global   # put this checkout on PATH as `metaproject` (with `[tui]`)
```

Releases: `python3 scripts/bump_version.py --dry-run` previews the next version,
`make bump-version` bumps, commits and tags it, and `make bump-major` forces a major
release. The bump rewrites the install tag in this README. Push the tag
(`git push origin vX.Y.Z`) — the install commands above resolve only tags that exist
on GitHub. `twine` is a `dev` dependency (release tooling), not a runtime one.

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

#### Project Skills
`init` installs no skill. Ten skills ship inside the package and are copied into each
project by `metaproject new` and `metaproject backfill`, into `.agents/skills/<name>/`
(reachable as `.claude/skills/<name>/` through the symlink `new` creates), and committed
with the project like any other file:

- the nine SDLC skills — `/write-intent`, `/generate-spec`, `/generate-design`,
  `/generate-plan`, `/implement-plan`, `/execute-tests`, `/wrapup`, `/shipit` (merge, push, deploy and
  clean up a finished branch; production deploys wait for a five-line zero-downtime plan and your OK), and `/backlog-new` for parking ideas — invoked by bare name;
- the `metaproject` skill, which teaches an agent when to reach for each command, which
  forms are safe to run unattended (`review --no-tui`, `learn list`, `universe`) and which
  need a human (`learn scan` calls a model; `learn apply` commits to your template store;
  scaffolding into an existing directory asks two confirmations).

Each cycle skill checks its own precondition: the project must have `.metaproject.json`
and `metaproject` must be on `PATH`, otherwise it stops and asks the operator to run
`metaproject new .`.

`new`, `backfill` (with no file arguments) and `adopt` are create-only: they add a skill
whose directory is missing and never write into an existing one. If `.claude/skills` is a
real directory, or a symlink to somewhere other than `.agents/skills`, no skill is written
and a notice says why.

Every install records `.agents/skills/.metaproject-skills.json` — the release that wrote
each skill and the sha256 of each file — so a later release can tell a pristine older
copy from your own edit. Commit it with the project. To update skills (agent-safe, also
in web sessions):

```bash
metaproject skills status            # each skill: current / outdated / modified / missing
metaproject skills sync --dry-run    # what sync would do
metaproject skills sync              # install missing, replace outdated-and-unmodified
metaproject skills sync --force wrapup   # also replace a modified skill (discards edits)
metaproject skills status --format json
metaproject skills status --all      # every cataloged project (needs `[tui]`)
metaproject skills sync --all        # asks once; --yes skips; --dry-run previews
```

`sync --all` runs the single-project sync in every project of `universe.db` that carries
`.metaproject.json`, one line per project. In an agent session it only reports unless
`--yes` is given. `sync` exits 0 when it keeps modified skills; each replacement is atomic (staged, then
swapped in by rename, with the old copy restored if the swap fails).

#### Claude Code Hooks
`new` and `backfill` also wire Claude Code hooks into the project, so lint errors are
caught right after an edit and a stale preview server cannot break an e2e run (plus the
web-only `SessionStart` bootstrap described under
[Claude Code on the web](#claude-code-on-the-web-web-profile)):

| Event | Matcher | What it does |
|---|---|---|
| `PostToolUse` | `Edit\|Write` | Runs `commands.lint`, then `commands.typecheck`, from `.metaproject.json`. Silent when neither is set or both pass; on failure the first 20 lines go back to the agent (exit 2). |
| `PreToolUse` | `Bash` | When the command mentions playwright and `e2e_port` is set, stops whatever is listening on that port. When a Playwright install lock looks held (a `__dirlock` under the browsers path, or a running `playwright install`), it tells the agent to use a worktree-local, ignored `PLAYWRIGHT_BROWSERS_PATH` (`.playwright-browsers/`) instead of waiting. It only advises: it never sets variables, installs, or removes a lock. Never blocks the command. |

Both run `.claude/hooks/metaproject_hook.py`, a stdlib-only Python script copied into the
project create-only (needs `python3` on `PATH`). It reads `.metaproject.json` each time, so
configuring a project is one edit:

```json
{
  "commands": { "lint": "make lint", "typecheck": "npx tsc --noEmit -p ." },
  "e2e_port": 4173
}
```

`.claude/settings.json` is **merged, never overwritten**: every key already there is kept,
and metaproject only adds its own entries under `hooks`, keyed by their command string so
a re-run adds nothing. A settings file that is not valid JSON is left untouched and
reported. `review` reports `.claude/settings.json` missing until every hook is merged and
both scripts are present.
Claude Code's sandbox can deny an agent writes to `.claude/settings.json` and
`.claude/hooks/`; a default-mode `backfill` then lists the hooks as "Not written" with a
notice and still exits 0 — run it yourself to install them. The hook commands are guarded
(`[ -f "$f" ] || exit 0`), so a settings file whose script is missing never blocks a tool
call.

#### Agent-Session Guards
The skill tells an agent what to do; the CLI enforces it either way. When `metaproject`
detects that an agent is driving it — from markers no ordinary login shell sets
(`CLAUDECODE`, `CLAUDE_CODE`, `AI_AGENT`, `CI`) — it changes behavior:

| | In an agent session |
|---|---|
| `review`, `learn` reviewer | Print the board or queue and exit 0, instead of opening the TUI |
| `learn scan`, bare `learn` | Refused (exit 1); prints the command for you to run |
| Scaffold-into-existing confirmations | Refused (exit 1); `--dry-run` still previews |

A TUI opened inside a tool call blocks on keystrokes that never arrive, and `learn scan`
spends money and sends redacted diffs off the machine — that one is yours to start.

`METAPROJECT_AGENT=0` forces human mode if you are working inside a harness and want your
TUI back; `METAPROJECT_AGENT=1` forces agent mode.

#### Existing Configuration Protection
If `~/.metaproject/config.json` is already present, running `metaproject init` will not overwrite your settings or re-run the wizard. Instead, it displays your current configuration along with the status summary of your `universe.db` (total projects, active now count, and last run).

To force a re-initialization and overwrite existing configuration and templates, pass `--force`:

```bash
metaproject init --force
```

#### Non-Interactive Setup
To seed templates and configure non-interactively in scripts or CI:

```bash
metaproject init --non-interactive --author "Jane Doe" --project-home ~/Projects
metaproject init --config-dir ~/.metaproject --project-home ~/Projects --force
```

The author defaults to `git config user.name`, then `$USER`, but a detected identity a
container gives itself (`Claude`, `root`, …) is never used: it falls through to
`Developer`. An author you configure explicitly is always used as written. Documents
take their author from the project's `.metaproject.json` first, then config, then git.

---

### 2. Scaffolding a New Project (`metaproject new`)

`metaproject new` generates a complete repository with the full SDLC cycle template set — governance files (`README.md`, `AGENTS.md`, `CLAUDE.md`, `.gitignore`), the cycle documents in `docs/` (`docs/INTENT.md`, `docs/SPEC.md`, `docs/TECH-DESIGN.md`, `docs/PLAN.md`, `docs/STATE.md`), the long-lived docs (`docs/ARCHITECTURE.md`, `docs/DESIGN-INVARIANTS.md`, `docs/VERIFIED-FACTS.md`), `docs/archive/`, `.metaproject.json`, and the project skills in `.agents/skills/` — and initializes git with an initial commit in under a second. The project root keeps only `README.md`, `AGENTS.md`, `CLAUDE.md` and `.gitignore`. (`docs/HANDOFF.md` is on-demand and not scaffolded; create it with `metaproject backfill docs/HANDOFF.md` only when work is interrupted.)

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

#### Scaffolding into a directory that already has work in it
Pointing `new` at a directory that already contains files shows you what is there and asks
for two separate confirmations — one to copy the templates in, and one to set up git:

```bash
cd ~/bin
metaproject new .
```

- Files that already exist are **kept as-is** and listed under "Kept (Already Present)"; only
  the missing template files are written.
- The project title and slug come from the directory name when you pass `.`.
- Declining the git prompt still scaffolds the templates, just without `git init`/commit.
- If the directory is already a git repository, metaproject leaves it alone entirely — no
  re-init, no staging, no commit.
- `--yes` cannot answer these prompts. For automation, pass `--force`, which skips both
  confirmations and **overwrites** colliding files.
- In an agent session this whole flow is refused; `metaproject backfill` (below) is the
  agent-safe alternative when only specific documents are missing.

Every scaffold — fresh or into an existing directory — also writes `.metaproject.json` at
the project root (`title`, `description`, `author`, `created`, `metaproject_version`),
tracked in the initial commit. `review`, `learn`, `backfill`, and `universe` all read it
first when resolving a project's variables. It may also carry optional `commands.lint`,
`commands.typecheck` and `e2e_port` for the Claude Code hooks (above); metaproject never
removes keys it did not write.

#### Previewing with Dry Run
To inspect the files and paths that would be generated without writing anything to disk:

```bash
metaproject new sample-app --dry-run
```

---

### 2a. Filling In Missing Documents (`metaproject backfill`)

`metaproject backfill [FILE...]` creates missing deliverables from the template store.
Unlike scaffolding into an existing directory, it needs no confirmation, never overwrites,
and never touches git — it is safe to run from an agent session or a hook:

```bash
# Create every deliverable `new` scaffolds that is currently missing, plus missing skills
metaproject backfill

# Create specific documents by name, including the on-demand docs/HANDOFF.md
metaproject backfill docs/SPEC.md docs/HANDOFF.md

# Old names still resolve to docs/ — this creates docs/TECH-DESIGN.md
metaproject backfill design.md

# Preview without writing
metaproject backfill --dry-run

# Target a different project directory
metaproject backfill --dir ~/Projects/other-project
```

With no file argument, every missing scaffolded deliverable is created in one call
(on-demand deliverables excluded) and any that already exist are listed under "Skipped
(already exists)". Naming files creates exactly those — including on-demand ones — but if
*any* named file already exists, nothing at all is written and the command exits non-zero,
listing the file(s) under "Refused — already exists, nothing written".

### 2b. Adopting an Existing Repository (`metaproject adopt`)

`metaproject adopt [--dir PATH] [--title T]` brings a repository that already exists —
typically one that was just cloned — under metaproject. It writes `.metaproject.json`
(title from `--title`, else the README heading, `pyproject.toml`/`package.json` name, or
the directory name), the `.agents/skills` layout with its `.claude/skills` link, and
every missing deliverable and project skill. It never overwrites a file (an existing
`.metaproject.json` is kept as written), runs no git command, needs no confirmation, and
is permitted in agent sessions. `--dry-run` previews; re-running it is a no-op. The
author comes from `--author`, config, then git/`$USER` (never a container identity such
as "Claude"); when none yields a real name, adopt writes nothing and asks for `--author`,
because `.metaproject.json` would otherwise pin a placeholder author for good.
`metaproject new .` keeps its interactive, operator-confirmed semantics.

```bash
cd my-cloned-repo && metaproject adopt
metaproject adopt --dir ~/Projects/game-workshop --title "Game Workshop"
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

As central templates evolve or projects customize their workflow, `metaproject review`
checks compliance against the latest standard deliverables and detects content drift in
every standard file that a template backs:

```bash
# Review current project
metaproject review

# Audit all projects across subdirectories
metaproject review ~/Projects --all

# Descend further than the default single level
metaproject review ~/Projects --all --depth 3
```

Each template is rendered *with that project's own variables* before it is compared, so a
project's own name and description are never mistaken for drift.

#### The compliance board

`review` opens with the score and what was audited, prints the
`Project Drift & Governance Review` table, and on a terminal stays open on it:

```
╭─ Project Drift & Governance Review ───────────────────────────────────────────╮
│ 3 projects · ✓ CLEAN 1 · ~ DRIFTED 1 · ↻ OUTOFDATE 0 · ! INCOMPLETE 1 · 2 on …│
│ scanned /Users/you/Projects against /Users/you/.metaproject/templates         │
╰───────────────────────────────────────────────────────────────────────────────╯
```

| Column | Meaning |
|---|---|
| `#` | Row number — the handle you type to select a project. |
| `Compliance` | `CLEAN`, `DRIFTED`, `OUTOFDATE` or `INCOMPLETE` — see below. |
| `Missing` | How many standard deliverables the project does not have. |
| `Drifted` | How many existing files no longer match their rendered template. |

| State | Meaning |
|---|---|
| `✓ CLEAN` | Nothing missing, nothing drifted, and no working document has lost a heading. |
| `~ DRIFTED` | Every deliverable exists, but a governance file's content has diverged, or a working document is missing a heading its template expects. |
| `↻ OUTOFDATE` | Nothing is missing, but a cycle document is still at its old location (a root `intent.md`, a lowercase `docs/design.md`). It is listed on the detail screen under "Legacy location — run `metaproject doctor`" and is never offered for Deploy. Wins over `DRIFTED`. |
| `! INCOMPLETE` | At least one standard deliverable is missing. Wins over every other state. |

Governance deliverables (`AGENTS.md`, `CLAUDE.md`, `README.md`, `.gitignore`) are diffed
body-for-body and are the only files `u`/`update` can act on. Working deliverables
(`docs/INTENT.md`, `docs/SPEC.md`, `docs/TECH-DESIGN.md`, `docs/PLAN.md`, `docs/STATE.md`,
`docs/ARCHITECTURE.md`, `docs/DESIGN-INVARIANTS.md`, `docs/VERIFIED-FACTS.md`) are checked
for heading structure
only — their body text is never diffed, and they are never offered for Update; the fix
for a missing heading is filling it in yourself, not an automatic overwrite.

Each state carries a **glyph as well as a colour**, so the verdict survives `NO_COLOR`, a
piped log and a colourblind reader.

The board is a triage view: it tells you *which project to open next*, and the file names
themselves are on the detail screen one keystroke away.

Commands are **verb first**, the same on both screens: `u 2`, `d 2`, `i 2`, `o 2` (a bare
`2` opens the project). The older number-first forms — `2u`, `2 u` — still work, and `?`
prints the whole command list.

| Action | What it does |
|---|---|
| **Open** (`u <n>`, `d <n>`, `<n>`) | Opens the project's detail screen, where its missing and drifted files are listed and every write happens. |
| **Ignore** (`i <n>`) | Records the project as allowed to stay out of compliance. It leaves the board **and is not checked again** until `--unignore`. |
| **OK** (`o <n>`) | Dismisses the project from this board. Nothing is recorded, so it **is checked again next review**. |

**OK and Ignore are different decisions.** OK is "not now" and lasts only for this
session; Ignore is "not ever" and is written to the ignore ledger. The closing summary
printed when you quit says which of the two each project got.

The detail screen lists the project's missing and drifted deliverables, numbered, and is
where the writes happen:

| Command | What it does |
|---|---|
| `d <n>` / `d all` | Deploy the numbered missing deliverable, or every one. `d all` asks first. |
| `u <n>` / `u all` | Update the numbered drifted file from its rendered template, or every one. Overwrites, and `u all` asks first. |
| `v <n>` | Show the unified diff for a drifted file. It stays pinned while you act on it; one taller than the screen opens in your pager. |
| `v` | The same, when exactly one file has drifted. |
| `c` | Close the pinned diff. |
| `o` | OK — dismiss this project for now; it is checked again next review. |
| `i` | Ignore this project; it is not checked again until `--unignore`. |
| `?` | Print the command list. |
| `b` | Back to the board. |
| `q` | Quit. |

A bare `d` or `u` **writes nothing**: it asks you to name a row or say `all`, because
"update this project" is not a thing you can mean by accident.

`Deploy` never overwrites an existing file and `Update` never creates a missing one —
they are separate verbs precisely so a reviewed file cannot be silently clobbered.

Both screens run on the terminal's alternate screen, so quitting hands your scrollback
back exactly as it was.

#### Managing the ignore list

```bash
metaproject review --list-ignored              # show what is being skipped
metaproject review ~/Projects/legacy --unignore  # start reviewing it again
metaproject review ~/Projects --all --show-ignored  # audit everything, ignore list included
```

#### Scripted use

The board degrades exactly like the `learn` reviewer — `--no-tui`, `TERM=dumb`, or a
non-TTY stdout prints the table and exits — so CI and pipelines need no special flag.

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
