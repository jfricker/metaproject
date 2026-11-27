# Ship project subagents as a deliverable

**Author**: John Fricker.
**Last updated**: 2026-11-26.
**Status**: Approved.
**Approved by**: John Fricker (2026-11-26).

## Problem

metaproject keeps managed projects consistent through templates and bundled skills, but it
ships no subagents. The cycle skills describe work that should go to a separate, restricted
agent: an independent spec review, one isolated worker per backlog item, and a read-only audit
for each project. Today each project would have to write those agents itself, so their tool
restrictions, report formats and safety rules would drift apart, which is the problem
metaproject exists to prevent.

Four generic prototypes now exist in this repository's `.claude/agents/` (`spec-reviewer`,
`backlog-worker`, `project-auditor`, `learn-synthesizer`). They are unversioned, unshipped and
not wired to the skills that should dispatch them. `metaproject learn` also still runs
`claude -p` with default tools, in the operator's working directory, over untrusted project
evidence.

## Proposed outcome

- The bundled agents ship with the package and are installed into every managed project's
  `.claude/agents/<name>.md` by `new`, `backfill` and `adopt` (create-only), and updated by a
  sync with the same guarantees as `skills sync`: install manifest, release history ledger,
  current/outdated/modified/missing classification, atomic write, user-modified files kept
  unless forced, and `--all` across `catalog.managed_projects`.
- `doctor` and `review` report missing, outdated and modified agents the same way they report
  skills.
- The skills that should dispatch an agent name it: `backlog-factory` dispatches
  `backlog-worker`, and the cycle (after `implement-plan`, before `execute-tests`/`wrapup`)
  dispatches `spec-reviewer`. The new `review-fleet` skill dispatches `project-auditor` once
  per non-clean project.
- `learn` runs its synthesis through `learn-synthesizer` with every tool disabled. That agent
  is internal package data and is never installed into projects.
- The prototypes move out of this repository's `.claude/agents/` into package data, and this
  repository receives the shipped copies through its own sync (dogfood).

## Affected users and systems

- Operators of managed projects, who gain three project agents and one more sync surface.
- `deliverables.py` (new deliverable class), `skills.py`, `treeops.py` and `bridges.py`
  (reuse or generalise the manifest, ledger and atomic-swap machinery), `scaffold.py`
  (`new`/`adopt`), `backfill`, `doctor.py`, `review.py`/`review_tui.py`, `catalog.py`,
  `cli.py` (sync/status surface), `learn/synth.py` (`claude_command`, `_instructions`),
  bundled skills (`backlog-factory`, cycle skills, the `metaproject` skill), the release
  tooling (`make skill-history` equivalent for agents), README and AGENTS.md.
- Claude Code, which loads `.claude/agents/*.md`.

## Scope

### In Scope (v1)

- New package data directory holding the agent definitions. Three are project agents
  (`spec-reviewer`, `backlog-worker`, `project-auditor`) and one is internal
  (`learn-synthesizer`).
- `DeliverableClass.SUBAGENT` for project agents. `skills status|sync` covers them too:
  install (create-only), status and sync with the shared manifest (v3, `agents` section) and
  ledger (`skill_history.json` `agents` section), atomic write, `--force NAME` and `--all`.
  Agent-session rules match skills: report-only without `--yes`, and nothing that changes the
  repository.
- `.metaproject/config.json` `agents.enabled` (absent means all bundled agents, `[]` means none).
- A new bundled `review-fleet` skill: run `review --format json` over
  `catalog.managed_projects`, dispatch one `project-auditor` per non-clean project in parallel,
  and merge one triage table grouped by recommended action.
- `project-auditor` loses `Bash(metaproject review:*)` and its deny pattern. The orchestrator
  passes it that project's `review --format json` findings, and it keeps only Read, Glob, Grep
  and read-only git.
- Shipped agents drop the `model` pin and keep `effort`. `learn --model` still applies to
  `learn-synthesizer`.
- `doctor` and `review` coverage for agents, including the `review` compliance states.
- Wiring the shipped skills to dispatch the agents by name (`backlog-factory` → `backlog-worker`,
  the cycle → `spec-reviewer`, `review-fleet` → `project-auditor`).
- `learn/synth.py`: `claude_command` loads `learn-synthesizer` from package data (its body as
  the system prompt) and disables all tools with `--tools "" --strict-mcp-config`, plus
  `--disable-slash-commands`. `_instructions()` shrinks to TARGET/KIND/MODE and the fenced evidence. Fencing,
  `_neutralize`, chunking, JSON validation and `source_lines` verification stay in code.
- `review --format json`, which `project-auditor` and the fleet-review orchestrator need instead
  of parsing the printed board.
- Fleet review over `catalog.managed_projects` (not `--all --depth 1`).
- Removing the prototypes from this repository's `.claude/agents/` once the shipped copies
  replace them.

### Out of Scope (v1)

- `learn` proposing edits to agent definitions. The ledger and the deliverable class should not
  rule it out, but no learn target is added.
- Agent formats for other harnesses (Copilot `.github/agents/`, Codex, Gemini, Cursor). Claude
  Code only.
- User-defined or per-project custom agents beyond leaving foreign files untouched.
- Changing the prototypes' behaviour beyond what the wiring and verification below require.

## Resolved decisions

- **Agents are generic.** No agent names a specific project, invariant or check. Each one learns
  the project from its AGENTS.md, CLAUDE.md and `.metaproject/docs/` at run time.
- **`learn-synthesizer` is internal.** It ships as package data, is loaded by `synth.py` per call
  and is never written into a project. The other three are project deliverables.
- **Reuse the skills distribution model** (manifest, history ledger, atomic sync, pristine vs
  modified, create-only on scaffold) instead of inventing a second one, generalised where the
  differences require it (single files rather than directories, no `.agents/` source, and no
  bridge, since Claude Code reads `.claude/agents/` directly).
- **Safety stays in code, not only in prompts.** Read-only agents are restricted through
  `tools`/`disallowedTools`. `learn` still validates and verifies everything the model returns.
- **Every write is behind the existing guards.** Agent-session detection, confirmation at a TTY,
  and no git writes.
- **Tool-less synthesis comes from CLI flags, not frontmatter.** Claude Code 2.1.332 lists an
  agent with `tools: []` as having all tools. `claude -p --tools "" --strict-mcp-config` starts
  with `tools: []` and `mcp: []` in its init event, and `--tools default` with the full set
  (verified 2026-11-26). `synth.py` uses the flags, and a test asserts they are in the argv.
- **The auditor gets its findings passed in** instead of running `metaproject review` itself.
  That removes the unverified deny pattern for `--unignore` (2026-11-26, operator).
- **One sync surface.** `skills status|sync` covers agents. There is no `agents` command group,
  and there is one manifest and one ledger (2026-11-26, operator).
- **The class is `SUBAGENT`**, which avoids a collision with `AGENTS.md`/governance
  (2026-11-26, operator).
- **Sub-projects follow the skills home.** With `skills.location: "root"`, agents install once in
  the delegating ancestor's `.claude/agents/` (2026-11-26, operator).
- **The fleet review is a new `review-fleet` skill**, not a section of the `metaproject` skill
  (2026-11-26, operator).
- **Pin effort, not model**, so frontmatter does not age as models change (2026-11-26,
  operator).
- **Opt-out is `agents.enabled`** in `.metaproject/config.json`, mirroring `skills.targets`
  (2026-11-26, operator).

## Constraints

- Core dependencies stay `typer`, `rich` and `jinja2`. No new runtime dependency.
- Agents ship through `importlib.resources`, like skills and templates.
- `skills.py` remains the only writer under `.agents/skills/` and `bridges.py` the only writer
  under `.claude/skills/`. The agents writer is a single module of its own, or a generalisation
  those modules own explicitly. There are never two writers for one tree.
- A user's own `.claude/agents/*.md` files and modified copies are never overwritten without
  `--force NAME`.
- The quality gate (`make format && make lint && make test`) must pass. History ledger coverage
  of the current bundle is enforced by a test, as `skill_history.json` is.

## Open questions

None open. Q1–Q9 were resolved on 2026-11-26 (see Resolved decisions). Details left to SPEC:
the `review --format json` schema, manifest v2 → v3 migration, and how `doctor` and `review`
present agent states.
