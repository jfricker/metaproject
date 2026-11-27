# AGENTS.md

## Dev environment tips
- Makefile is the primary tool for development and testing. Use `make help` to see available targets.

## Build Commands
- `make install`: Install package in editable mode with development dependencies (`uv pip install -e ".[dev]"`).
- `make build`: Build source distribution and wheel into `dist/` (`uv build --no-build-isolation`).
- `make package`: Run `bump-version` (if needed) and build distributables in `dist/`.
- `make clean`: Remove build artifacts (`dist/`, `build/`, `*.egg-info`), test/lint caches, and `__pycache__` directories.
- `make uninstall`: Uninstall `metaproject` from the active Python environment.

## Testing instructions
- `make test`: Run the complete test suite with verbose output (`pytest -v tests`).
- `make lint`: Run code linter and formatting checks (`ruff check src tests` and `ruff format --check src tests`).
- `make format`: Auto-format source and test files and apply autofixes (`ruff format` and `ruff check --fix`).
- Specific test: Run a single test file or function via `.venv/bin/pytest tests/<test_file>.py -k <test_name> -v`.
- Quality Gate: Always execute `make format && make lint && make test` before committing changes.

## Releases
- **Heuristic Version Bumping**:
  - `make bump-version` or `scripts/bump_version.sh`: Evaluates git diff and file additions to increment semver (New files &rarr; Major/Minor per major-0 policy, New commands &rarr; Minor, Bugfixes &rarr; Patch).
  - Synchronizes `pyproject.toml`, package metadata, fallback versions, baseline tests, and `README.md`.
  - Automatically creates a git commit with summary and creates an annotated git tag (`v<version>`).
  - Rewrites every `github.com/jfricker/metaproject@vX.Y.Z` install ref in `README.md`. The tag is local until pushed (`git push origin v<version>`); the documented `uv tool install ...@v<version>` resolves only tags that exist on GitHub. metaproject is not on PyPI (the PyPI name `metaproject` is an unrelated package), so the publishing targets below are not a user install path.
- **Idempotency Guard**:
  - If `git tag --points-at HEAD` matches the version in `pyproject.toml`, `scripts/bump_version.sh` exits cleanly with code `0` (`No bump is needed.`), allowing safe re-runs during packaging (`make package`, `make testpypi`, `make pypi`). Use `--force-bump` to override.
- **Milestone Bumps**:
  - `make bump-major` or `scripts/bump_version.sh major`: Forces a major version increment (`(X+1).0.0`), zeroes minor and patch, commits, and tags `v<version>`.
- **Publishing Targets**:
  - `make testpypi`: Cleans, packages, and uploads distribution archives to TestPyPI via `twine`.
  - `make pypi`: Cleans, packages, and uploads distribution archives to production PyPI via `twine`.
  - `make install-testpypi`: Installs/upgrades the latest release from TestPyPI.
---
## Architecture

`metaproject` is an AI-native governance and scaffolding CLI built with Python 3.11+, Typer, and Rich. It is structured into cleanly decoupled functional layers:

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
| (Env & Templates  | | (Project Scaffold | |  (Template Drift  | |(Corroborated Tmpl.| | (Catalog, Classify|
|      Setup)       | |    & Git Init)    | |    & Auditing)    | | Proposal Pipeline)| |  & SQLite Store)  |
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
```

### Core Subsystems
1. **CLI Routing & Manifest (`src/metaproject/cli.py`, `__main__.py`)**:
   - Built on `typer` with `rich` console formatting.
   - Registers commands (`init`, `new`, `backfill`, `adopt`, `universe`, `review`, `doctor`), the
     agent-safe `skills` (`status`, `sync`) and `templates` (`fetch`) groups, and the `learn`
     command group (`scan`, `review`, `list`, `show`, `apply`, `edit`, `reject`), whose
     bare `learn [ROOT]` form is routed to a hidden default command by
     `LearnGroup.parse_args`. Any new `learn` subcommand must be registered on
     `learn_app` or it is read as a path. `backfill` is the non-interactive, create-only
     counterpart to `new .`'s interactive scaffold-into-existing flow — agent-safe, never overwrites, never
     changes the repository. `adopt` (`scaffold.adopt_project`) is the same for a whole existing repository:
     `.metaproject/config.json`, the `.agents/skills` layout, then `backfill_missing` — create-only, and the
     only git it runs is read-only `git config --get core.symlinks|user.name|user.email`.
   - The `skills` group (`status`, `sync`) acts on one project, or with `--all` on every
     project in `catalog.managed_projects` (cataloged, existing, carrying `.metaproject/config.json`
     — the same set `doctor` checks), calling the single-project function once per project.
     `sync --all` asks once at a TTY, only reports in an agent session without `--yes`, never
     changes the repository (same read-only `git config` queries only), and one project's failure does not stop the rest (exit 1).
   - `MetaprojectGroup.invoke` turns a `MissingExtraError` (an optional `tui` dependency
     reached without the extra) into one line plus exit 1; `LearnGroup.invoke` gates every
     `learn` subcommand on the web profile and on `sqlite-utils`.
   - Handles eager manifest inspection via `-v` / `--version`.
   - The project a command acts on is the nearest `.metaproject/config.json` at or above the
     current directory (stopping at the git root), resolved once by
     `identity.resolve_project_dir`; an explicit `--dir`/`PROJECT` wins, and with no
     anchor it is the current directory. `review --all`, `learn`, `universe` and `new`
     keep the current directory. `universe.is_project_root` counts `.metaproject/config.json`
     as a marker so anchor-only sub-projects are discovered.

2. **Configuration & Template Seeding (`src/metaproject/config.py`)**:
   - Manages user settings at `~/.metaproject/settings.json`.
   - Bootstraps bundled seed templates from package resources via `importlib.resources`.
   - Safeguards existing configurations during `init` unless `--force` is supplied.

3. **Template Engine & Variable Resolution (`src/metaproject/templates.py`, `variables.py`)**:
   - Resolves template variables from Git config, system clock, CLI flags, or interactive Questionary prompts.
   - Pre-processes Jinja2 variables with whitelist safety (stripping unknown Jinja expressions to prevent syntax collisions in foreign templates).
   - Renders template trees, stripping `.template` extensions and preserving directory structures and permissions.
   - `template_source.resolve_templates` picks the store `backfill`, `adopt` and `review` render from: `--templates`, else the local store, else the project's optional `templates.source` (a repository path, or a git URL/ref shallow-fetched once into `~/.metaproject/cache/templates/`), else the bundled templates — every fallback says why, and nothing about it ever fails a command.

4. **Universe Scanner & Catalog Database (`src/metaproject/universe.py`, `db.py`)**:
   - Discovers project roots recursively (via Git repos, `.metaproject`, or marker files like `AGENTS.md` / `pyproject.toml`).
   - Evaluates project classification heuristics (`Active Now`, `Active`, `Idle`, `Archived`) based on file modification timestamps and path semantics.
   - Persists project metadata in SQLite (`~/.metaproject/universe.db`) and reconciles missing/deleted projects.
   - Exposes summary metrics via `metaproject universe summary` and `get_universe_summary()`.

5. **Compliance & Drift Detection (`src/metaproject/review.py`, `src/metaproject/review_tui.py`)**:
   - `review.py`: audits projects against active templates in `~/.metaproject/templates/`, identifying missing governance files and content drift across workspace repositories. One audit is one `ReviewResult` — a frozen dataclass that is the single declaration of the schema, storing only what the scan observed and deriving `updatable`, `is_compliant` ("nothing is missing"), `is_current` ("no cycle document at a legacy location") and `is_clean` ("nothing missing, nothing drifted, nothing legacy") as properties. A relocated document still at its old root or lowercase location is recorded in `legacy`, never in `missing_files`/`deployable`, so Deploy cannot create a blank copy beside the real one. Every comparison renders the template with the project's own variables first (shared with `learn.collect`), so substituted placeholders are never reported as drift. It also owns the two remediations — `deploy_entry` writes a missing deliverable, `update_entry` rewrites a drifted one, and neither will do the other's job — and the `~/.metaproject/review-ignore.json` ledger of projects permitted to stay out of compliance.
   - `review_tui.py`: the `rich` compliance board behind `metaproject review`. It opens with a summary header — the aggregate score over the scan root and the template store it was measured against — above the table. The `Compliance` column has four states, each named for the defect it reports and each carrying a glyph as well as a colour (`✓ CLEAN` / `~ DRIFTED` / `↻ OUTOFDATE` / `! INCOMPLETE`, with precedence INCOMPLETE > OUTOFDATE > DRIFTED; legacy documents are listed on the detail screen under "Legacy location — run `metaproject doctor`" with no action key), so the verdict survives `NO_COLOR` and a pipe; `Missing` and `Drifted` are counts rather than file lists because the board is a triage view. Both screens read verb-first (`u 3`, `d 2`, `i 4`, `o 1`), with the board's old number-first form (`3u`) still accepted and `?` documenting both — `OK` dismisses a project for the session and it is checked again next review, `Ignore` is durable and it is not; `u <n>` and `d <n>` are the same door onto a detail screen listing that project's missing and drifted files, where each write calls the same `review.py` function a non-interactive path would, so there is no board-only code path. A bare `u`/`d` writes nothing and `u all`/`d all` are gated on a typed confirmation; a remediation batch resolves template variables once before its first write. A viewed diff stays pinned until `c` closes it, and one taller than the screen goes to the pager. Both loops run on the alternate screen so the operator's scrollback survives, and the whole thing degrades to the printed board (header included) without a TTY, with `--no-tui`, or under `TERM=dumb`.

6. **Template Learning Pipeline (`src/metaproject/learn/`)**:
   - `collect.py`: renders each template with a project's own variables and diffs it against the project's file, so substituted placeholders are not mistaken for novel content.
   - `guard.py`: filters `.gitignore` matches and a hard denylist, redacts credentials, and builds the send manifest before anything leaves the machine.
   - `score.py`: clusters evidence into candidates and ranks them by frequency, recency, and `universe` activity weighting.
   - `store.py`: the proposal ledger (`learn_proposals` / `learn_evidence` / `learn_runs`) — upsert by content hash, provenance, suppression and resurfacing. The only module that touches SQLite.
   - `synth.py`: bundles guarded evidence one bundle per target file, measures the rendered prompt against the context budget and chunks-and-reduces when it overruns, shells out to `claude -p`, and parses the reply as schema-validated structured data. The only module that reaches a model; model output is data, never instruction.
   - `apply.py`: splices an accepted proposal into its `target_section` (never an end-of-file append under a banner), refuses a dirty template repository, and makes exactly one commit per accept naming the proposal id and its contributing projects. The only module that writes to a template. An unresolvable section falls back to a *reviewed* append that says so, never a silent misplacement.
   - `drift.py`: reduces `review`'s findings to a scoring signal. Recurring drift that `review` already reports raises the matching pattern's weight rather than creating a parallel finding — it is a bounded multiplier on an existing contribution, never a candidate of its own, so the same divergence is never counted twice. `review.py` is unchanged.
   - `api.py`: the public surface `cli.py` and `tui.py` call — `scan()`, `review()`, `apply_proposal()`, `reject_proposal()`. `scan` runs stages 1–4 and imports nothing from `apply`, so a scan cannot reach the write path.
   - `tui.py`: the `rich` acceptance loop behind `metaproject learn` (default mode) and `metaproject learn review`. Every keystroke delegates to the same function the equivalent subcommand calls and writes through to `universe.db` immediately, so there is no TUI-only code path; it degrades to the `list` table without a TTY, with `--no-tui`, or under `TERM=dumb`.

7. **Release & Versioning Automation (`scripts/bump_version.sh`, `scripts/bump_version.py`)**:
   - AI-native semantic version incrementing driven by git diff analysis and file additions.
   - Supports operator milestone launches (`bump-major`), idempotency tagging guards, and synchronized updates across metadata, tests, and documentation.
---
## Key Files
- `src/metaproject/cli.py`: Main entry point for CLI commands.
- `src/metaproject/config.py`: Handles configuration and template seeding.
- `src/metaproject/templates.py`: Template rendering engine.
- `src/metaproject/variables.py`: Template variable resolution.
- `src/metaproject/universe.py`: Workspace universe scanning and classification.
- `src/metaproject/db.py`: SQLite database management for the universe.
- `src/metaproject/review.py`: Template drift detection, compliance, remediation and the ignore list.
- `src/metaproject/review_tui.py`: The `rich` compliance board and its per-project detail screen.
- `src/metaproject/learn/`: Corroborated-proposal pipeline (`collect`, `guard`, `score`, `store`, `synth`, `apply`, `drift`, `api`, `tui`).
- `src/metaproject/identity.py`: `.metaproject/config.json` identity, plus the one project-root resolver — `find_project_root` (nearest anchor, stopping at the git boundary), `find_repo_root`, and `resolve_project_dir` (explicit `--dir`/`PROJECT` wins, else the nearest anchor, else cwd) that every cwd-defaulting command (`backfill`, `adopt`, `review`, `skills status|sync`, web `doctor`, `templates fetch`) uses. The hook and session scripts carry their own stdlib copy of the walk.
- `src/metaproject/deliverables.py`: The single declaration of deliverable paths and classes, plus the legacy-name mapping (`LEGACY_NAMES`, `LEGACY_LEARN_TARGETS`, `MIGRATABLE_SUBDIRS`, `canonical_path`, `legacy_locations`, `exact_exists`) behind the root/`docs/` → `.metaproject/docs/` relocation.
- `src/metaproject/skill/`: The bundled metaproject skill (`SKILL.md` plus `references/`), shipped as package data.
- `src/metaproject/extras.py`: `require`/`LazyModule` — the only way core code reaches `textual`, `questionary` or `sqlite-utils` (the optional `tui` extra), so `--version`, `backfill`, `adopt` and `review --no-tui` import none of them.
- `src/metaproject/hooks.py`: The `.claude/settings.json` deliverable (class `SETTINGS`): `merge_hooks(settings_path, entries)` adds hook entries keyed by command string and preserves every other key (merge, never overwrite; invalid JSON is refused with `SettingsError`); `install_hooks` also copies the bundled `hook_scripts/metaproject_hook.py` to `.claude/hooks/` create-only. The web-only `SessionStart` entry is one more `HookEntry` through the same function: guarded to run `scripts/metaproject-session.sh` (bundled `hook_scripts/metaproject-session.sh`, also copied create-only) only when it exists and `CLAUDE_CODE_REMOTE=true`; the script installs the pinned CLI, runs `skills sync` and `templates fetch`, and always exits 0.
- `src/metaproject/hook_scripts/metaproject_hook.py`: Stdlib-only hook script shipped as package data. `post-edit` runs `.metaproject/config.json` `commands.lint`/`commands.typecheck` (silent when unset or passing; truncated output and exit 2 on failure); `pre-bash` stops listeners on `e2e_port` before a playwright command and, when a Playwright install lock looks held, adds `additionalContext` advising a worktree-local `PLAYWRIGHT_BROWSERS_PATH` (advice only; always exit 0).
- `src/metaproject/sdlc_skills/`: The twelve bundled SDLC skills (`write-intent` … `wrapup`, `backlog-new`, `shipit`, `verify-browser`, `backlog-factory`, `review-fleet`; `shipit` gates production deploys on a zero-downtime plan and operator OK; `verify-browser` reproduces a browser bug in WebKit and never commits before webkit, chromium and mobile-safari pass; `backlog-factory` fans independent backlog items out to worktrees and subagents, merges only on operator OK and never deploys to production), imported with history from the retired sdlc-skills repository.
- `src/metaproject/subagents.py`: the only writer of `.claude/agents/<name>.md` and the manifest `agents` section; depends on `skills`, never the reverse.
- `src/metaproject/agents/`: the bundled project agents (`spec-reviewer`, `backlog-worker`, `project-auditor`); `learn/agents/learn-synthesizer.md` is internal, loaded by `synth.py` with tools disabled.
- `src/metaproject/skills.py`: `bundled_skills()` declares the project skills; the only module that writes under `.agents/skills/<name>/` (the single source — Copilot, Codex, Antigravity, ZCode, Gemini CLI and Cursor read it natively). `file_map` hashes a skill, `inspect_project_skills` classifies each as current/outdated/modified/missing against the install manifest (`.agents/skills/.metaproject-skills.json`, format version 3 with `bridges` and `agents` sections) and the `skill_history.json` ledger, and `sync_project_skills` is the single write path (atomic staged swap) behind `metaproject skills sync`, doctor's fix and `install_project_skills` (create-only, for `new`/`backfill`/`adopt`; `init` installs none). `skills_home`/`project_skills_dir` resolve `skills.location: "root"` — a sub-project whose skills live once in the nearest non-delegating ancestor project (or the git root); its own `.claude/skills/<name>` bridge entries point up there.
- `src/metaproject/bridges.py`: the only writer under `.claude/skills/<name>`. For Claude Code it keeps one bridge entry per bundled skill — a relative symlink, or a copy on Windows, `core.symlinks=false` or `skills.link_mode: "copy"` (`auto` default, `symlink`, `copy`) — for each `skills.targets` entry (`["claude"]` default; `[]` removes the bridge). It owns only entries recorded in the manifest's `bridges` section; a user's own entry is never touched, and an unrecorded entry with a bundled name is foreign, replaced only by `skills sync --force NAME`. There is no whole-directory `.claude/skills` link; a foreign `.claude/skills` symlink or file means sources install and no bridge entries are written (reported, exit 0). Also reports shadowing by `~/.claude/skills/<n>` or `.github/skills/<n>`.
- `src/metaproject/treeops.py`: directory-tree primitives for the installer — file hashing, copying, the atomic staged swap, and staging recovery confined to the skills home. Imports nothing from `skills`.
- `src/metaproject/scaffold.py`: `new`, `adopt_project` and the transactional file tracker; never creates `.claude/skills` itself (bridges are `bridges.py`'s).
- `src/metaproject/git.py`: git pre-flight, `init` and commit helpers for `new`, plus `read_only_query`, the allow-listed read-only `git config --get core.symlinks|user.name|user.email` (timeout; failure means no opinion) — the only git `backfill`, `adopt` and `skills status|sync` ever run.
- `src/metaproject/skill_history.json`: digests of every released skill, regenerated by `make skill-history` (`scripts/gen_skill_history.py`); a test fails until it covers the current bundle.
- `src/metaproject/catalog.py`: `managed_projects(cfg)` / `is_managed` — the one declaration of the cataloged, managed project set shared by `doctor` and `skills status|sync --all`. An absent `universe.db` is an empty catalog.
- `src/metaproject/doctor.py`: `metaproject doctor` — store layout, store, config, orphaned global skill, identity, and per-project docs migration, skills and project agents (the missing/outdated check runs after project skills; modified and disabled agents are not findings), each fix behind confirmation. An optional `[PROJECT]` path (`metaproject doctor .`) scopes the run to that one project's identity, docs, and skills checks.
- `src/metaproject/template_source.py`: `resolve_templates()` — the one answer to "which template store?" (`--templates` > local store > the project's `templates.source` in `.metaproject/config.json` > bundled), plus the shallow git fetch into `~/.metaproject/cache/templates/` behind `metaproject templates fetch`.
- `src/metaproject/session.py`: Agent-session detection (`CLAUDECODE`, `AI_AGENT`, `CI`, `METAPROJECT_AGENT`) behind the TUI, scan, and backfill guards.
- `scripts/bump_version.sh`: AI-native version bumping script.
- `scripts/bump_version.py`: Python helper for version bumping.

## Project Constraints
- Python 3.11+ required.
- Typer for CLI construction.
- Jinja2 for templating.
- Questionary for interactive prompts.
- SQLite for persistent workspace catalog.
- Core dependencies are `typer`, `rich`, `jinja2` only. `textual`, `questionary` and
  `sqlite-utils` are the optional `tui` extra: import them lazily through
  `metaproject.extras`, never at module top level of a core path (`tests/test_extras.py`
  enforces this). `metaproject.learn` resolves its public names lazily for the same reason.
- Built-in templates packaged via `importlib.resources`.

## Learnings
- **Build Isolation & Offline Packaging**: `uv build` and `uv pip install` create isolated build environments by default, attempting network lookups for build backends (`hatchling`). In sandboxed or offline environments, always pass `--no-build-isolation` to leverage `.venv` packages.
- **Packaging Idempotency**: Tying `bump-version` directly into `make package` or publishing targets requires an idempotency check against `git tag --points-at HEAD`. If the tag matches `pyproject.toml`, exiting cleanly with code `0` prevents infinite or unintentional version increments on rebuilds.
- **Whitelist-Safe Jinja2 Expansion**: Markdown governance files commonly include curly braces or foreign templating syntax. Whitelist-safe extraction of known keys (`project_name`, `author`, `year`, etc.) ensures unknown Jinja expressions do not trigger render failures during scaffolding.
- **Root Project Traversal**: Scanning workspaces where the root itself is a project (e.g. contains `.git` or `pyproject.toml`) requires cataloging the root while continuing to descend into nested subdirectories (while pruning `.git`, `node_modules`, `.venv`, and `__pycache__`).
- **Selective Commit Staging in Automation**: Automated release scripts must selectively stage only modified metadata files (`pyproject.toml`, `__init__.py`, `cli.py`, baseline tests, `README.md`) rather than using `git add -A` to avoid capturing unrelated working tree modifications.
- **Rich Output Line Constraints**: When CLI commands enforce strict line budgets (e.g. `universe summary` 2-line output), configure Rich prints with `soft_wrap=True` to prevent terminal dimensions from wrapping lines unexpectedly in tests or narrow terminals.

## Process
This process is based on https://claude.com/blog/the-ai-native-sdlc-playbook with modifications. This document adds to the playbook and merges ideas. It doesn't supercede the playbook unless explicitly stated.

The cycle documents live in `.metaproject/docs/` (note: `.metaproject/` is a hidden dot-directory, so `rg`/`fd` searches targeting `.metaproject/docs/` need `--hidden` or an explicit path); the cycle skills are this project's own copies in `.agents/skills/` (bridged one entry per skill into `.claude/skills/<name>`), invoked by bare name (`/write-intent`, …, `/wrapup`).

### .metaproject/docs/TODO.md
 On-demand (`metaproject backfill .metaproject/docs/TODO.md`). `wrapup` appends a dated "Needs manual verification" entry listing what the agent could not verify itself, with exact steps for the operator. Never archived.

### .metaproject/docs/HANDOFF.md
 When work is interrupted before completion, create `.metaproject/docs/HANDOFF.md` (`metaproject backfill .metaproject/docs/HANDOFF.md`) to capture the state of the work and any other information needed to resume the work or hand it off to another agent at another time.

### .metaproject/docs/STATE.md
 Maintain a running list of all tasks and their status. Update it as tasks are completed. Format the list as a checklist with a box, task number and a task description.

### .metaproject/docs/INTENT.md
 `.metaproject/docs/INTENT.md` is a source of truth for proposed changes to the system. Read it when instructed to and mark it complete after all work is tested and merged.

### .metaproject/docs/SPEC.md
 The agent will be instructed to create a requirements spec from `.metaproject/docs/INTENT.md`.

### .metaproject/docs/TECH-DESIGN.md
 The agent will be instructed to create a technical design from an approved `.metaproject/docs/SPEC.md`.

### .metaproject/docs/PLAN.md
 The agent will be instructed by the operator to create an implementation plan based upon `.metaproject/docs/SPEC.md` and `.metaproject/docs/TECH-DESIGN.md`.


