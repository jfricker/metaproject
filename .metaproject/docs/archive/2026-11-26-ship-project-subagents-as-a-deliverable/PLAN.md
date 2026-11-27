# Ship project subagents as a deliverable — Plan

**Author**: John Fricker.
**Derived from**: SPEC.md and TECH-DESIGN.md (2026-11-26, approved).
**Last updated**: 2026-11-26.
**Status**: Approved.
**Approved by**: John Fricker (2026-11-26).

## Context

metaproject ships skills to managed projects but no subagents. This cycle bundles three
project agents (`spec-reviewer`, `backlog-worker`, `project-auditor`), syncs them into
`<home>/.claude/agents/` with the same manifest, ledger and atomic guarantees as skills, wires the
skills that dispatch them, adds `review --format json` and `--managed` for the new `review-fleet`
skill, and runs `learn` synthesis through an internal, tool-less `learn-synthesizer`. Requirements
are R-AGT-1–26 and N-AGT-1–5 (SPEC.md). Structure is in TECH-DESIGN.md.

Each step lands with its tests (failing first). The gate runs at the end of each step:
`make format && make lint && make test`.

## Steps

### 1. Bundle and packaging (R-AGT-1–3, 8 partial, N-AGT-3)
- Create `src/metaproject/agents/{spec-reviewer,backlog-worker,project-auditor}.md` from
  `.claude/agents/`, removing `model:`. In `project-auditor`, remove `Bash(metaproject review:*)` and
  `disallowedTools`, and rewrite Inputs/Process so that `FINDINGS` (that project's
  `review --format json` entry) is passed in by the dispatcher.
- Create `src/metaproject/learn/agents/learn-synthesizer.md`, removing `model:` and `tools: []`
  (frontmatter is stripped at load time anyway; keep `name`/`description`).
- `pyproject.toml` package-data: add `"agents/**"`, `"learn/agents/**"`.
- Tests (`tests/test_subagents_bundle.py`): the frontmatter keys and `name == stem`, no `model`,
  the N-AGT-3 grep (`R-AGT`, `R-`-prefixed IDs, `Checks D`, `/Users/`, `MetaProject`), agent and
  skill names disjoint, and the fence markers present in the synthesizer body.

### 2. Manifest v3 in `skills.py` (R-AGT-7)
- `MANIFEST_VERSION = 3`. `Manifest.agents: Dict[str, Dict]`. `load_manifest` validates
  `agents` for v3 (`{release: str, sha256: 64-hex}`) and loads v1/v2 with `{}`.
  `render_manifest` always emits `agents`.
- `_write_manifest` accepts only `Manifest`. Update both callers (`skills.py:774`,
  `skills.py:822`) to carry `loaded.agents`.
- Tests (`tests/test_skills.py`/`test_skills_sync.py`): a v2 load gives empty agents, a v3
  round-trip, a skills sync preserving an existing agents entry, and an invalid agents value
  reading as `unreadable`. Update fixtures/assertions that pin `"version": 2`.

### 3. `subagents.py` core (R-AGT-4–6, 9–11, 13, N-AGT-2, N-AGT-4)
- New module per TECH-DESIGN: `BundledAgent`, `bundled_agents()`, `internal_agent_body()`,
  `enabled_agents()`, `classify_agent()`, `inspect_project_agents()`,
  `sync_project_agents()`, `install_project_agents()`, and `AgentStatus`/`AgentsReport`, plus
  `DISABLED`.
- Reuse `skills.skills_home`, `skills.load_manifest`/`_write_manifest`, `skills.running_release`,
  `skills.CURRENT…RECORDED`, `skills._manifest_warning`. Read the ledger's `agents` section via a new
  `skills.load_history(section="agents")` parameter (default `"skills"`).
- `deliverables.py`: `DeliverableClass.SUBAGENT` and `subagent_paths()`. Do not add to
  `DELIVERABLES`, because `scaffolded()`/`learn_targets()` must stay unchanged (test asserts this).
- Tests (`tests/test_subagents.py`): every state, `agents.enabled` (absent, `[]`, subset, unknown
  name warns once), disabled-file untouched, user file untouched, `--force` replaces only a named
  modified file, unknown force name raises before any write, symlinked agents dir refused with exit
  0, a patched `os.replace` failure leaves the original intact and the manifest unchanged, a
  delegating sub-project writing to its home, a second sync writing nothing (mtime and bytes),
  and `dry_run` writing nothing.

### 4. Ledger (R-AGT-8)
- `scripts/gen_skill_history.py`: emit an `agents` section (digest = sha256 of the file bytes,
  release = running). `--check` covers both. Run `make skill-history`.
- `skills.parse_history`/`load_history` tolerate both sections.
- Test: the existing ledger-coverage test is extended to the agents.

### 5. Call sites: scaffold, backfill, adopt (R-AGT-12, N-AGT-1)
- `scaffold.py:345` (`new`/`adopt`) and `review.py:856` (`backfill_missing`): call
  `subagents.install_project_agents(..., dry_run, tracker)` right after the skills install, and
  put the report on the result objects (`agents` field next to `skills`). Render it where skills are
  rendered in `cli.py`.
- `backfill` with named files: touch agents only when a named path is under `.claude/agents/`.
- Tests in `test_scaffold.py`, `test_adopt.py`, `test_backfill.py` (acceptance criteria 1, 2, 6),
  and `test_extras.py` still passing (no optional imports).

### 6. CLI `skills status|sync` (R-AGT-13–15)
- `cli.py` `skills status` (≈2130) and `skills sync` (≈2005, ≈2186): run the agent pass after
  skills, split `--force` names by membership, render an "Agents" section using
  `SKILL_STATE_LABELS` plus `disabled`, and add the `agents` key to the JSON (single and `--all`).
  Compute the exit code over both. Guard and confirmation happen once.
- Tests in `test_skills_sync.py`, `test_skills_sync_all.py` (acceptance criteria 3, 4, 5, 7, 11):
  existing JSON keys stay byte-compatible.

### 7. Doctor (R-AGT-16)
- `doctor.py`: `check_project_agents` after `check_project_skills`, with fix
  `sync_project_agents(update=True)` behind the existing confirmation. Run it for `doctor` and
  `doctor PROJECT`.
- Amend `.metaproject/docs/DESIGN-INVARIANTS.md`'s doctor order line during wrapup (record it in
  STATE.md now).
- Tests in `test_doctor.py` (acceptance criterion 10).

### 8. `review --format json` and `--managed` (R-AGT-17, 22)
- `review.py`: `compliance_state(result) -> "CLEAN"|"DRIFTED"|"OUTOFDATE"|"INCOMPLETE"` (plain,
  no rich), which `review_tui.compliance_cell` now uses, plus `result_to_dict(result)`.
- `cli.py` `review_cmd`: `--format table|json` and `--managed` (uses
  `catalog.managed_projects`). Usage errors: json with `--unignore`/`--list-ignored`;
  `--managed` with `--all`/`--depth`/`PROJECT`. JSON never opens the TUI or writes, and notices go
  to stderr.
- Tests in `test_review.py` (acceptance criterion 12): JSON parses, counts and state match the board,
  the ignore ledger is untouched, the usage errors, and an empty catalog.

### 9. learn synthesizer (R-AGT-23–26)
- `synth.py`: `synthesizer_prompt()` (cached, `subagents.internal_agent_body`), the new
  `claude_command` argv, `run_claude` under `TemporaryDirectory` with `cwd=`, `_instructions` reduced
  to TARGET/KIND/MODE plus the strict prefix, `build_reduce_prompt` sending `MODE: reduce`, and
  `chunk_bundle` subtracting `measure(synthesizer_prompt())`.
- Tests in `test_learn_synth.py` (acceptance criterion 13): exact argv, `cwd` an empty temp dir that is
  gone afterwards (patch `subprocess.run`), the prompt no longer containing the RULES text, and
  existing fence, validation and `source_lines` tests unchanged. Budget tests adjusted for the
  system-prompt size.

### 10. Skills and docs (R-AGT-18–21)
- `sdlc_skills/backlog-factory/SKILL.md`: dispatch `backlog-worker` with Item/Worktree/Branch,
  with the brief as fallback.
- `sdlc_skills/execute-tests/SKILL.md` step 6: dispatch `spec-reviewer`, blockers go to STATE.md
  unmet criteria, fall back to the manual check.
- New `sdlc_skills/review-fleet/SKILL.md` (frontmatter `name`/`description`, Process, Output table,
  Stop conditions: writes nothing, no remediation).
- `skill/SKILL.md` (+ references) and README: agents, `agents.enabled`, `review-fleet`,
  `review --format json|--managed`, and the v3-manifest upgrade note. Update AGENTS.md Key Files
  (`subagents.py`, `agents/`) and the `sdlc_skills` count (eleven → twelve).
- Run `make skill-history` again (skill bundle changed).
- Tests: `test_backlog_factory_skill.py` (the brief rules ⊆ agent body), `test_sdlc_skills.py`
  (review-fleet declared), `test_skills.py` ledger coverage.

### 11. Dogfood this repository (R-AGT-3)
- Delete `.claude/agents/*.md` (the four prototypes; only `learn-synthesizer.md` and
  `project-auditor.md` are untracked, the other two are committed in `f6c6ddb`).
- Run `metaproject skills sync` here (unsandboxed if needed). This installs the three project
  agents and writes a v3 manifest. Verify byte-equality with the bundle.

### 12. Final gate and manual checks
- `make format && make lint && make test` green.
- Manual (record in STATE.md/TODO.md if not done): the live `claude -p` built from
  `claude_command` reports `tools: []`/`mcp: []` in the stream-json init event (acceptance criterion 14),
  and one real `metaproject learn scan` compared against the pre-change proposal quality.

## Sequencing

1 → 2 → 3 → 4 → {5, 6, 7} → 11. Step 8 is independent of steps 1–7. Step 9 depends on steps 1 and 3
(`internal_agent_body`). Step 10 depends on steps 1 and 8 (it documents their flags). Step 12 is
last. Steps 5, 6 and 8 all touch `cli.py`, so the steps run in this session in order, not in
parallel sessions.

## Risks and rollback

- **Manifest clobber**: forcing `_write_manifest(Manifest)` and the cross-pass preservation tests
  (steps 2 and 3) guard it.
- **v3 forward-incompatibility** for older CLIs: documented in the README (step 10). There is no
  data loss, because older releases only report.
- **learn quality shift** from removing the default system prompt: the manual scan comparison
  (step 12). Rollback is reverting `claude_command` to the old argv and keeping the agent file
  unused.
- **Test fixture churn** from `"version": 2` → 3: limited to the skills/bridges tests, and updated in step 2.
- Each step is a separate commit once the gate is green, so a revert is per step.

## Verification

- `make format && make lint && make test` after every step and at the end.
- End to end in a scratch dir: `metaproject new demo` gives three agents plus a v3 manifest.
  Hand-edit one agent, then `metaproject skills status --format json` shows `modified`. Then
  `skills sync --force spec-reviewer` restores it, and a second `skills sync` writes nothing.
- `metaproject review --managed --format json | python -m json.tool`.
- `metaproject doctor .` in this repository reports agents current.
