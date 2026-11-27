# Ship project subagents as a deliverable — Spec

**Author**: John Fricker.
**Derived from**: INTENT.md (2026-11-26, approved).
**Last updated**: 2026-11-26.
**Status**: Approved.
**Approved by**: John Fricker (2026-11-26).

Terms: a **project agent** is a bundled agent installed into projects (`spec-reviewer`,
`backlog-worker`, `project-auditor`). The **internal agent** is `learn-synthesizer`, which is
never installed. The **agents dir** is `<home>/.claude/agents/`, where `home` is the project, or
for a `skills.location: "root"` sub-project the home that `skills.skills_home` resolves. An
**agent file** is `<agents dir>/<name>.md`. The **manifest** is the existing
`<home>/.agents/skills/.metaproject-skills.json`. The **ledger** is `skill_history.json`.
**Enabled agents** are the project agents that `agents.enabled` selects (R-AGT-4).

## Requirements

### Functional

**Bundle**

- **R-AGT-1** The package ships the project agents as `src/metaproject/agents/<name>.md` and
  the internal agent as `src/metaproject/learn/agents/learn-synthesizer.md`, all as package
  data read through `importlib.resources`. `bundled_agents()` declares the project agents. It
  never returns `learn-synthesizer`.
- **R-AGT-2** Each project agent is one Markdown file with YAML frontmatter (`name`,
  `description`, `tools`, optional `disallowedTools`, `effort`) and no `model` key. `name` equals
  the file stem. A test enforces both rules for every bundled project agent.
- **R-AGT-3** The bundled bodies are the four prototypes from this repository's
  `.claude/agents/`, changed only as follows:
  `model` removed (all four). `project-auditor` loses `Bash(metaproject review:*)` and its
  `disallowedTools`, and its Inputs/Process take findings passed in by the dispatcher
  (R-AGT-22). The prototypes are then deleted from `.claude/agents/`, and this repository
  receives the shipped copies through its own sync.

**Configuration**

- **R-AGT-4** `.metaproject/config.json` gains an optional `agents.enabled` list of
  project-agent names. When it is absent, every project agent is enabled. `[]` enables none. An
  unknown name produces one warning per run and is ignored, never an error. metaproject never
  writes this key.
- **R-AGT-5** A delegating sub-project uses its home's `agents.enabled`, just as skills follow
  the home.

**Classification and manifest**

- **R-AGT-6** `DeliverableClass.SUBAGENT` is added, and each enabled project agent is a
  deliverable `.claude/agents/<name>.md` of that class. `SUBAGENT` paths are installed and
  updated only by the agent sync path (R-AGT-11). `review`'s render, deploy and update
  functions never act on them, and they are never `learn` targets.
- **R-AGT-7** Manifest format version 3 adds a top-level `agents` object: name →
  `{ "release": <release>, "sha256": <hex> }`. v3 keeps `skills` and `bridges` unchanged. A v2
  manifest reads as v3 with no agents recorded, and the next write emits v3. A manifest newer
  than v3 is `newer` for agents too: report only, no write.
- **R-AGT-8** The ledger gains an `agents` section: name → list of `{digest, release}`, where
  the digest is the sha256 of the file bytes. `make skill-history` regenerates both sections. A
  test fails until the ledger covers every current bundled agent.
- **R-AGT-9** Each enabled agent is classified with the skills vocabulary:
  `current` (bytes equal this release's bundle), `outdated` (hash matches the manifest entry or
  an earlier ledger release), `modified` (exists and matches neither), `missing` (absent). A
  file the manifest does not record is `modified` unless it matches a ledger digest, in which
  case it is `outdated`.
- **R-AGT-10** A file in the agents dir that is not a bundled project agent, or is disabled, is
  never read for writing, replaced, moved or deleted. Disabling an agent that metaproject
  installed does not delete its file. `skills status` reports it as `disabled` (kept).

**Install and sync (one write path)**

- **R-AGT-11** One function is the only writer of agent files and of the manifest's `agents`
  section. Each write stages the new file in the agents dir, verifies its hash, and renames it
  into place. A failed write leaves the previous file intact. That function creates the agents
  dir when needed, never creates `.claude/agents` as a symlink, and writes nothing through a
  symlinked agents dir (it reports and skips, exit 0).
- **R-AGT-12** `new`, `backfill` (with no file arguments) and `adopt` install `missing`
  enabled agents create-only, in the same pass and transaction tracker as skills. `backfill`
  with named files touches agents only when a named file is an agent path.
- **R-AGT-13** `skills sync` also installs `missing` agents and replaces `outdated` ones, keeps
  `modified` ones (reported), and replaces a modified agent only when it is named:
  `--force NAME`. Bundled agent and skill names never collide, and a bundle test fails if they
  do, so `NAME` is never ambiguous.
- **R-AGT-14** `skills sync --dry-run`, the agent-session guard (report only without `--yes`),
  the TTY confirmation, `--all` over `catalog.managed_projects`, per-project failure isolation
  (exit 1), and the git rule (only `git.read_only_query`) apply to agents exactly as they apply
  to skills.

**Reporting**

- **R-AGT-15** `skills status` lists agents in a separate "Agents" section with the same
  columns, state labels and actions as skills. `--format json` adds `"agents": [{name, state,
  installed_release, action, note}]` beside the existing keys and changes no existing key. Exit
  codes keep their current meaning. A `modified` agent counts the same as a `modified` skill.
- **R-AGT-16** `doctor` gains a project-agents check after the project-skills check. It reports
  each enabled agent's state and offers to fix `missing`/`outdated` through the R-AGT-11 path
  (confirmed, report-only in agent sessions). `modified` is reported, never fixed. The check
  runs for `doctor` and `doctor PROJECT`.
- **R-AGT-17** `review` gains no agent findings. It audits templates, not bundled assets, and
  skills are reported only by `skills status` and `doctor` too (operator, 2026-11-26).

**Skill wiring**

- **R-AGT-18** `backlog-factory` dispatches one `backlog-worker` subagent per item with the
  inputs `Item`, `Worktree` and `Branch`. When `backlog-worker` is not available, it falls back
  to the existing pasted brief. The brief and the agent stay consistent: the agent's rules are
  a superset of the brief's.
- **R-AGT-19** `execute-tests`, at its acceptance-criteria step, dispatches `spec-reviewer` when
  it is available and records each `blocker` finding in STATE.md as an unmet criterion. Without
  the agent, the existing manual check stands.
- **R-AGT-20** A new bundled SDLC skill, `review-fleet`, runs
  `metaproject review <p> --format json` for each project in `catalog.managed_projects`, skips
  clean and ignored projects, dispatches one `project-auditor` per remaining project in
  parallel with that project's JSON findings, and merges the reports into one table grouped by
  recommended action (update, doctor, learn, ignore, human). It never runs a remediation
  itself. Without subagents, it prints the merged JSON findings and stops.
- **R-AGT-21** The `metaproject` skill and README document the project agents, `agents.enabled`,
  and `review-fleet`.

**Review JSON**

- **R-AGT-22** `metaproject review [PROJECT] --format json` (and with `--all`) prints one JSON
  document on stdout: `{"templates": <dir>, "projects": [ReviewResult fields + derived
  updatable, is_compliant, is_current, is_clean, compliance state]}`. Diffs are unified-diff
  strings. It never opens the TUI and never writes (including the ignore ledger).
  `--format table` (the default) is the current board. `--format json` is rejected together
  with `--unignore`/`--list-ignored` with a usage error. Notices go to stderr.

**Learn synthesizer**

- **R-AGT-23** `synth.claude_command` returns
  `[claude, "-p", "--tools", "", "--strict-mcp-config", "--disable-slash-commands",
  "--system-prompt", <learn-synthesizer body>] (+ ["--model", m])`. The body is the package
  file with its frontmatter removed. A test asserts this argv.
- **R-AGT-24** `run_claude` runs with `cwd` set to a fresh empty temporary directory, so no
  project `CLAUDE.md`, settings or hooks from the operator's working directory are loaded.
- **R-AGT-25** `_instructions()` / `build_prompt` / `build_reduce_prompt` drop the static
  SECURITY, RULES and OUTPUT text that the agent body now carries, keeping TARGET, KIND, MODE,
  the strict-retry prefix, and the fenced evidence or proposals. Fencing, `_neutralize`,
  budgeting and chunking, JSON validation and `source_lines` verification are unchanged.
- **R-AGT-26** The internal agent's rules include everything the removed prompt text required
  (RULES 1–6, the security paragraph, the output schema, reduce behaviour). A test checks that
  the exact fence marker strings appear in the body.

### Non-functional

- **N-AGT-1** No new runtime dependency. Agent code is reachable from `--version`, `backfill`,
  `adopt` and `review --no-tui` without importing `textual`, `questionary` or `sqlite-utils`
  (`tests/test_extras.py`).
- **N-AGT-2** Safety: no agent file is ever overwritten unless it is pristine (current, outdated
  or recorded) or named with `--force`. A user's own `.claude/agents/*.md` is never touched.
  Read-only agents are restricted by their `tools` allowlists, not by prose.
- **N-AGT-3** Agent bodies are generic. No bundled agent names this repository, its invariants
  or a specific project. A test greps bundled agents for `metaproject`-repo-only identifiers
  (for example `R-`, `Checks D`, `/Users/`).
- **N-AGT-4** Idempotence: a second `skills sync` after a successful one writes nothing,
  including the manifest bytes.
- **N-AGT-5** The quality gate `make format && make lint && make test` passes.

## Acceptance criteria

1. **New project.** `metaproject new` creates `.claude/agents/{spec-reviewer,backlog-worker,
   project-auditor}.md`, byte-equal to the bundle, and the manifest is v3 with an `agents`
   section. No `learn-synthesizer.md` is written (R-AGT-1/6/7/12).
2. **Adopt with a user agent.** A repo with `.claude/agents/my-agent.md` and a hand-written
   `.claude/agents/spec-reviewer.md`: `adopt` installs the other two, reports `spec-reviewer` as
   `modified`, and leaves both user files byte-identical. `skills sync --force spec-reviewer`
   replaces it and records it (R-AGT-9/10/13).
3. **Update.** After a bundled agent changes, `skills sync` replaces a pristine older copy
   (`outdated` → `updated`), keeps a hand-edited one (`modified`, kept), and a second run writes
   nothing (R-AGT-9/13, N-AGT-4).
4. **v2 manifest.** A project with a v2 manifest: `skills status` shows agents as missing or
   modified without error, and the next sync writes v3 with `skills`/`bridges` unchanged
   (R-AGT-7).
5. **Opt-out.** `agents.enabled: ["spec-reviewer"]` installs only that agent, and an existing
   installed `backlog-worker.md` is reported `disabled` and left in place. `[]` installs none.
   `["nope"]` warns once (R-AGT-4/10).
6. **Sub-project.** A `skills.location: "root"` sub-project's agents go to its home's
   `.claude/agents/`, recorded in the home's manifest, with nothing under the sub-project
   (R-AGT-5).
7. **Agent session.** With `CLAUDECODE=1` and no `--yes`, `skills sync` reports agent changes
   and writes nothing. With `--yes` it writes (R-AGT-14).
8. **Failure safety.** With the rename patched to fail mid-write, the previous agent file is
   intact and the manifest is unchanged (R-AGT-11).
9. **Symlinked agents dir.** `.claude/agents` is a symlink: nothing is written through it, the
   warning is reported, and the exit is 0 (R-AGT-11).
10. **Doctor.** A missing agent is reported and fixed after confirmation. Under an agent session
    it is report-only. A modified agent is reported, never fixed (R-AGT-16).
11. **Status JSON.** `skills status --format json` has an `agents` array, existing keys are
    byte-compatible, and exit codes are unchanged (R-AGT-15).
12. **Review JSON.** `review <p> --format json` parses as JSON, matches the board's counts and
    compliance state, writes nothing (the ignore ledger's mtime is unchanged), and with
    `--unignore` is a usage error (R-AGT-22).
13. **Synth argv.** `claude_command("claude", None)` equals the R-AGT-23 list, and `run_claude`
    passes a `cwd` that is an empty temp dir, removed afterwards. Existing synth tests for
    fencing, validation and `source_lines` still pass (R-AGT-23/24/25).
14. **Tool-less, live (manual).** `claude -p` built from `claude_command` reports `tools: []`
    and `mcp: []` in its stream-json init event. Recorded in TODO.md if it is not runnable in
    CI (R-AGT-23).
15. **Wiring.** `backlog-factory`, `execute-tests` and `review-fleet` name their agents and
    describe the fallback, and `review-fleet` is in `bundled_skills()` with ledger coverage
    (R-AGT-18–20).
16. **Generic bundle.** The N-AGT-3 grep finds nothing in the bundled agents, the R-AGT-2
    frontmatter test passes, and no bundled agent shares a name with a bundled skill (R-AGT-13).

## Flagged concerns

All resolved by the operator, 2026-11-26:

1. Agents get no `review` findings, matching skills (R-AGT-17).
2. `spec-reviewer` is dispatched by `execute-tests`, at the acceptance-criteria step
   (R-AGT-19).
3. Agent and skill names must never collide. A bundle test enforces this, and `--force NAME` has
   no qualifier (R-AGT-13).
4. The synth call loads `learn-synthesizer` with `--system-prompt` (R-AGT-23).

## Open questions

None.
