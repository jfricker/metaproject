# MetaProject — State

## Process

<!-- each stage ticks its own item here as it completes -->
- [x] 1. write-intent: intent.md approved
- [x] 2. generate-spec: spec.md approved
- [x] 3. generate-design: design.md approved
- [x] 4. generate-plan: plan.md approved
- [ ] 5. implement-plan: code and tests written
- [ ] 6. execute-tests: tests passing
- [ ] 7. wrapup: cycle archived

## Implementation phases

<!-- written by implement-plan as steps land -->
- [x] 1. Bundle agents and packaging
- [x] 2. Manifest v3 in skills.py
- [x] 3. subagents.py core
- [x] 4. Ledger agents section
- [x] 5. Scaffold/backfill/adopt call sites
- [x] 6. CLI skills status/sync
- [x] 7. Doctor agents check
- [x] 8. review --format json and --managed
- [x] 9. learn synthesizer wiring
- [x] 10. Skills and docs
- [ ] 11. Dogfood this repository
- [ ] 12. Final gate and manual checks

## Design invariants (regression guards)

<!-- written by implement-plan/execute-tests; appended to docs/DESIGN-INVARIANTS.md by wrapup -->
- `skills._write_manifest` accepts only a `Manifest`; every manifest write carries the `agents` section through, so a skills pass never drops agents and an agents pass never drops skills/bridges (`tests/test_skills_sync.py`, `tests/test_subagents.py`).
- `subagents.py` is the only writer of `<home>/.claude/agents/<name>.md` and the manifest `agents` section; `skills` never imports `subagents` (`tests/test_subagents.py`).
- Agent files are written temp-then-`os.replace` after a hash check; a failed write leaves the original and the manifest unchanged; a symlinked `.claude`/`.claude/agents` is never written through; staging uses `tempfile.mkstemp` (O_EXCL, random name) so a planted symlink is never followed (`tests/test_subagents.py::test_planted_temp_symlink_is_not_followed`).
- `backfill` with named files touches exactly the named agents (`only=`), never other missing ones (`tests/test_backfill.py`).
- `review --format json` writes nothing and prints only JSON on stdout; `compliance_cell` derives from `review.compliance_state`, so board and JSON cannot disagree (`tests/test_review.py`).
- `review --managed` never opens the interactive board when projects resolve to different template stores (Deploy/Update write from one store) (`tests/test_review.py::test_review_managed_mixed_stores_never_open_the_board`).
- `synth.claude_command` always passes `--tools "" --strict-mcp-config --disable-slash-commands --system-prompt <learn-synthesizer body>`, and `run_claude` runs in an empty temp cwd; the synthesizer system prompt counts against the chunk budget (`tests/test_learn_synth.py`).
- `.claude/agents` paths are `DeliverableClass.SUBAGENT` and never appear in `scaffolded()` or `learn_targets()` (`tests/test_subagents.py`).

## Open items carried into plan.md

<!-- written by implement-plan/execute-tests; resolved with the operator by wrapup -->
- `skills status --all` table shows no agents column (agents only in JSON); `skills sync --all` adds an agents suffix to a project line only when a count is nonzero. Accepted as within R-AGT-15 (existing output unchanged).
- `review --managed --format json`: each project uses its own template store; the top-level `"templates"` is the first project's store (default store when the catalog is empty). Confirm or change to per-project only.
- Amend DESIGN-INVARIANTS doctor order line: project agents run right after project skills (wrapup).

## Verified facts (do not re-investigate)

<!-- written by implement-plan/execute-tests; appended to docs/VERIFIED-FACTS.md by wrapup -->
- Claude Code 2.1.332: `claude -p --tools "" --strict-mcp-config` init event has `tools: []`, `mcp: []`; `--tools default` lists all built-ins. An agent file with `tools: []` is listed as "All tools" (frontmatter does not disable tools). Confirmed by running both, 2026-11-26.
