# MetaProject — State

## Process
- [x] 1. write-intent: intent.md approved
- [x] 2. generate-spec: spec.md approved
- [x] 3. generate-design: design.md approved
- [x] 4. generate-plan: plan.md approved
- [ ] 5. implement-plan: plan steps implemented
- [ ] 6. execute-tests: verification green
- [ ] 7. wrapup: cycle archived

## Implementation phases
- [x] A1. deliverables.py
- [x] A2. markdown.py
- [x] A3. identity.py + variable resolution
- [x] A4. placeholder warnings + render exclusions
- [x] B1. scaffold writes identity, skips on-demand
- [x] B2. review classes
- [x] B3. backfill_missing + `metaproject backfill`
- [x] B4. TUI + CLI surfaces
- [x] C1. structural evidence
- [x] C2. learn/structure.py + api partition
- [x] C3. apply heading proposals
- [x] C4. drift signal for structure
- [x] D1. templates
- [ ] D2. skill docs + README
- [x] D3. discovery doc
- [x] E1. sdlc-skills hook + Makefile
- [x] E2. sdlc-skills skills
- [ ] E3. sdlc-skills repo docs + identity + version
- [ ] F. release on main (after merge)

## Design invariants (regression guards)
- Working deliverables are never updatable: `ReviewResult.updatable` reads only `diffs`,
  which holds governance files; structural drift lives in `structure` (design.md).
- Heading (structure) evidence never reaches the egress guard, confirmation, or any model
  prompt; it is turned into proposals locally (spec R-LRN-1, design.md).
- Heading proposals need ≥ `learn.min_structure_evidence` (default 2) projects; model
  proposals for governance files stay ranked, not gated (spec R-LRN-1c).
- A template missing from the live store is an error, never a silent fallback to the
  bundled copy (design.md).

## Open items carried into plan.md
- FC-3 (spec.md): live store refresh deferred to a future `metaproject doctor` command;
  operator refreshes `~/.metaproject/templates` by hand after merge (2026-09-14).
- `doctor` must also update a `config.json` that pins `learn.targets`, so new working
  deliverables get scanned (spec R-LRN-3, 2026-09-14).
- `doctor` must also refresh the installed skill at `~/.claude/skills/metaproject/`
  (spec R-DOC-1, 2026-09-14).
- B2 (2026-09-14): the bundled template store has no template yet for spec.md,
  design.md, plan.md, ARCHITECTURE.md, docs/DESIGN-INVARIANTS.md, docs/VERIFIED-FACTS.md
  (D1 does this). Until D1 lands, no project reviewed against the bundled store can
  reach `is_clean`/`is_compliant`, because those six WORKING deliverables (plus
  `docs/archive`, untemplated too) are always `missing_files`. Tests that need a fully
  compliant project (AC-1, AC-5, and two pre-existing tests —
  `test_review_compliant_project`,
  `test_deployed_files_do_not_immediately_report_as_drifted` — which plan.md B2 said
  should stay unmodified but could not without this) build a test-local template store
  (`full_cycle_templates_store` in `tests/test_review.py`) with minimal templates for
  those six files. D1 should delete that duplication once the bundled store has them.

- B4 (2026-09-15, deviation from plan.md, out of B4's own scope but required for a green
  gate): `scaffold_project`'s `created = date.today()` bypassed the `variables._today()`
  seam tests patch for a fixed clock (spec R-ID-2, AC-5); it only ever passed because the
  suite happened to run on the same calendar day the test hardcodes. Fixed to call
  `variables._today()` (looked up through the module, not a bound name, so the seam stays
  patchable) so `test_ac5_review_is_stable_across_an_advancing_clock` is stable across a
  real day boundary, not just a mocked one.

## Verified facts (do not re-investigate)
- Running pytest inside the Claude Code sandbox: the default TMPDIR contains `claude-501`,
  which trips the test suites' "no `claude` subprocess" guard (24 false failures). Use
  `--basetemp=<repo>/.pytest_cache/tmp-<lane>` (outside any `claude` path); baseline
  435 passed that way (2026-09-14).
- `uv` needs the sandbox disabled (its cache under ~/.cache/uv is not readable); worktree
  venvs were created unsandboxed (2026-09-14).
- The prior "improve learn command" cycle shipped (v0.6.0, 333 tests) but was never
  wrapped up; its docs, including its full STATE.md with invariants, facts and open
  items, are archived under `docs/archive/2026-09-04-improve-learn-command/` (2026-09-13).
